/**
 * Shoppin PWA Service Worker (/sw.js)
 *
 * 1. Stale-While-Revalidate cache for immutable static icons & pinned vendor JS/CSS libs
 * 2. Safe NetworkFirst (with 1.8s fast timeout fallback) ONLY for offline resilience
 * 3. Instant full purge of HTML caches on logout / workspace / persona switches
 */
const STATIC_CACHE = 'shoppin-static-v3';
const PAGE_CACHE = 'shoppin-pages-v1';

const PRECACHE_ASSETS = [
    '/static/js/lazy_assets.js',
    '/static/js/prefetcher.js',
    '/static/js/mutation_queue.js',
    '/static/js/app_shell.js',
    '/static/js/shopping_sync.js',
    '/static/js/shortcuts.js',
    '/static/images/icon.svg'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then((cache) => cache.addAll(PRECACHE_ASSETS).catch(() => {}))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => Promise.all(
            keys
                .filter((k) => k !== STATIC_CACHE && k !== PAGE_CACHE)
                .map((k) => caches.delete(k))
        )).then(() => self.clients.claim())
    );
});

self.addEventListener('message', (event) => {
    const msg = event.data || {};
    if (msg.type === 'SKIP_WAITING') {
        self.skipWaiting();
    } else if (msg.type === 'PURGE_USER_CACHES') {
        event.waitUntil(caches.delete(PAGE_CACHE));
    }
});

function isStaticOrVendorAsset(url) {
    if (url.origin === self.location.origin && url.pathname.startsWith('/static/')) {
        return true;
    }
    const vendorHosts = ['unpkg.com', 'cdn.jsdelivr.net', 'cdn.tailwindcss.com'];
    return vendorHosts.includes(url.hostname);
}

function isCacheableDocument(request, url) {
    if (request.method !== 'GET') return false;
    if (url.origin !== self.location.origin) return false;
    const excludedPrefixes = [
        '/admin',
        '/accounts',
        '/login',
        '/logout',
        '/core',
        '/nearest-store',
        '/health',
        '/sw.js'
    ];
    if (excludedPrefixes.some((p) => url.pathname.startsWith(p))) return false;
    const accept = request.headers.get('Accept') || '';
    return accept.includes('text/html') || request.mode === 'navigate';
}

self.addEventListener('fetch', (event) => {
    const request = event.request;
    if (request.method !== 'GET') return;

    const url = new URL(request.url);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return;

    // 1. Stale-While-Revalidate for static & pinned CDN libs
    if (isStaticOrVendorAsset(url)) {
        event.respondWith(
            caches.open(STATIC_CACHE).then(async (cache) => {
                const cached = await cache.match(request);
                const networkFetch = fetch(request).then((resp) => {
                    if (resp && (resp.ok || resp.type === 'opaque')) {
                        cache.put(request, resp.clone()).catch(() => {});
                    }
                    return resp;
                }).catch(() => cached);
                return cached || networkFetch;
            })
        );
        return;
    }

    // 2. NetworkFirst with offline snapshot fallback for primary authenticated screens
    if (isCacheableDocument(request, url) && !request.headers.get('HX-Request')) {
        event.respondWith(
            caches.open(PAGE_CACHE).then(async (cache) => {
                const timeoutController = new AbortController();
                const timer = setTimeout(() => timeoutController.abort(), 1800);
                try {
                    const networkResp = await fetch(request, { signal: timeoutController.signal });
                    clearTimeout(timer);
                    if (networkResp && networkResp.ok && !networkResp.redirected) {
                        cache.put(url.pathname + url.search, networkResp.clone()).catch(() => {});
                    }
                    return networkResp;
                } catch (_) {
                    clearTimeout(timer);
                    const cached = await cache.match(url.pathname + url.search);
                    if (cached) {
                        const clientsList = await self.clients.matchAll({ type: 'window' });
                        clientsList.forEach((c) => c.postMessage({ type: 'SW_OFFLINE_SNAPSHOT' }));
                        return cached;
                    }
                    return fetch(request);
                }
            })
        );
    }
});

self.addEventListener('sync', (event) => {
    if (event.tag === 'shoppin-outbox-sync') {
        event.waitUntil(
            self.clients.matchAll({ type: 'window' }).then((clientsList) => {
                clientsList.forEach((c) => c.postMessage({ type: 'FLUSH_OUTBOX' }));
            })
        );
    }
});
