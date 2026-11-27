/**
 * Shoppin Speculative Intent Prefetcher
 *
 * Pre-warms safe read-only GET partials (Edit Item, Load Preset, Schedule,
 * Recipe Modals) and navigation tabs on 65ms hover dwell or immediate
 * pointerdown/touchstart intent, eliminating full RTT wait when clicking.
 * Respects Save-Data / 2G heuristics and purges cleanly on mutations/WS updates.
 */
(function () {
    'use strict';

    const MAX_ENTRIES = 28;
    const MODAL_TTL_MS = 12000;
    const ROUTE_TTL_MS = 35000;
    const DWELL_MS = 65;

    const cache = new Map();
    const inflight = new Map();
    let dwellTimer = null;
    let activeDwellEl = null;

    function getScopePrefix() {
        const body = document.body;
        const wsId = body ? (body.getAttribute('data-workspace-id') || '0') : '0';
        const userId = body ? (body.getAttribute('data-user-id') || 'anon') : 'anon';
        return `${userId}:${wsId}`;
    }

    function normalizeUrl(rawUrl) {
        if (!rawUrl) return '';
        try {
            const parsed = new URL(rawUrl, window.location.origin);
            if (parsed.origin !== window.location.origin) return '';
            parsed.searchParams.delete('org.htmx.cache-buster');
            return parsed.pathname + parsed.search;
        } catch (_) {
            return '';
        }
    }

    function buildKey(rawUrl) {
        const norm = normalizeUrl(rawUrl);
        return norm ? `${getScopePrefix()}:${norm}` : '';
    }

    function isNetworkConstrained() {
        const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
        if (!conn) return false;
        if (conn.saveData) return true;
        return conn.effectiveType === '2g' || conn.effectiveType === 'slow-2g';
    }

    function trimCache() {
        while (cache.size > MAX_ENTRIES) {
            const oldestKey = cache.keys().next().value;
            cache.delete(oldestKey);
        }
    }

    function isPrefetchSafeUrl(normUrl) {
        if (!normUrl) return false;
        if (normUrl.includes('/item/tmp_')) return false;
        const blocked = ['/login', '/logout', '/accounts/', '/admin/', '/core/dev/', '/core/workspace/switch'];
        return !blocked.some((p) => normUrl.startsWith(p));
    }

    function fetchUrl(rawUrl, options = {}) {
        if (!navigator.onLine) return Promise.resolve(null);
        if (!options.force && isNetworkConstrained()) return Promise.resolve(null);

        const norm = normalizeUrl(rawUrl);
        if (!isPrefetchSafeUrl(norm)) return Promise.resolve(null);

        const key = `${getScopePrefix()}:${norm}`;
        const ttl = options.ttl || (norm.includes('/edit/') || norm.includes('-modal') || norm.includes('/modal/') ? MODAL_TTL_MS : ROUTE_TTL_MS);

        const existing = cache.get(key);
        if (existing && !options.force && (Date.now() - existing.timestamp <= ttl)) {
            return Promise.resolve(existing);
        }

        if (inflight.has(key)) {
            return inflight.get(key);
        }

        if (inflight.size >= 3 && !options.force) {
            return Promise.resolve(null);
        }

        const headers = {
            'HX-Request': 'true',
            'X-Prefetch': '1',
            'X-Client-Id': window.CLIENT_ID || 'client_web'
        };
        if (options.boosted) {
            headers['HX-Boosted'] = 'true';
        }
        if (options.targetId) {
            headers['HX-Target'] = options.targetId;
        }

        const reqPromise = fetch(norm, {
            method: 'GET',
            headers,
            credentials: 'same-origin',
            priority: options.priority || 'low'
        }).then(async (resp) => {
            inflight.delete(key);
            if (!resp.ok) return null;
            if (resp.redirected && !isPrefetchSafeUrl(normalizeUrl(resp.url))) {
                return null;
            }
            if (resp.headers.get('HX-Redirect')) return null;

            const html = await resp.text();
            const entry = {
                url: norm,
                html,
                title: '',
                timestamp: Date.now(),
                ttl
            };
            cache.set(key, entry);
            trimCache();
            return entry;
        }).catch(() => {
            inflight.delete(key);
            return null;
        });

        inflight.set(key, reqPromise);
        return reqPromise;
    }

    function getCached(rawUrl, maxAgeMs) {
        const key = buildKey(rawUrl);
        if (!key) return null;
        const entry = cache.get(key);
        if (!entry) return null;
        const limit = typeof maxAgeMs === 'number' ? maxAgeMs : entry.ttl;
        if (Date.now() - entry.timestamp > limit) {
            cache.delete(key);
            return null;
        }
        // Touch LRU order
        cache.delete(key);
        cache.set(key, entry);
        return entry;
    }

    function getInflight(rawUrl) {
        const key = buildKey(rawUrl);
        return key ? inflight.get(key) || null : null;
    }

    function storeManual(rawUrl, html, ttl = ROUTE_TTL_MS) {
        const norm = normalizeUrl(rawUrl);
        if (!isPrefetchSafeUrl(norm) || !html) return;
        const key = `${getScopePrefix()}:${norm}`;
        cache.set(key, {
            url: norm,
            html,
            timestamp: Date.now(),
            ttl
        });
        trimCache();
    }

    function invalidateMatching(substr) {
        if (!substr) {
            cache.clear();
            return;
        }
        for (const key of cache.keys()) {
            if (key.includes(substr)) {
                cache.delete(key);
            }
        }
    }

    function purgeAll() {
        cache.clear();
        inflight.clear();
    }

    function extractCandidate(el) {
        if (!el || typeof el.closest !== 'function') return null;

        // Priority 1: explicit hx-get interactive trigger (excluding search bars/confirm buttons)
        const hxEl = el.closest('[hx-get]');
        if (hxEl && !hxEl.hasAttribute('data-no-prefetch') && hxEl.tagName !== 'INPUT' && hxEl.tagName !== 'SELECT') {
            const url = hxEl.getAttribute('hx-get');
            const norm = normalizeUrl(url);
            if (!isPrefetchSafeUrl(norm)) return null;
            const rawTarget = (hxEl.getAttribute('hx-target') || '').replace(/^#/, '');
            return { el: hxEl, url: norm, boosted: false, targetId: rawTarget || 'modal-placeholder' };
        }

        // Priority 2: boosted or primary nav / detail links
        const link = el.closest('a[href]');
        if (link && !link.hasAttribute('download') && !link.hasAttribute('data-no-prefetch')) {
            if (link.target && link.target !== '_self') return null;
            const href = link.getAttribute('href') || '';
            if (!href || href.startsWith('#') || href.startsWith('mailto:') || href.startsWith('javascript:')) return null;
            const isBoostable = (
                link.closest('nav[aria-label="Primary Navigation"]') ||
                link.closest('#mobile-nav-tabs') ||
                link.hasAttribute('data-boost-nav') ||
                link.getAttribute('hx-boost') === 'true'
            );
            if (!isBoostable) return null;
            const norm = normalizeUrl(href);
            if (!isPrefetchSafeUrl(norm)) return null;
            return { el: link, url: norm, boosted: true, targetId: 'main-content' };
        }
        return null;
    }

    function runPrefetch(candidate, isImmediate) {
        if (!candidate) return;
        fetchUrl(candidate.url, {
            boosted: candidate.boosted,
            targetId: candidate.targetId,
            priority: isImmediate ? 'high' : 'low'
        });
    }

    document.addEventListener('pointerenter', function (e) {
        const candidate = extractCandidate(e.target);
        if (!candidate) return;
        if (activeDwellEl === candidate.el) return;
        if (dwellTimer) clearTimeout(dwellTimer);
        activeDwellEl = candidate.el;
        dwellTimer = setTimeout(() => {
            runPrefetch(candidate, false);
        }, DWELL_MS);
    }, true);

    document.addEventListener('pointerleave', function (e) {
        if (activeDwellEl && (e.target === activeDwellEl || (activeDwellEl.contains && !activeDwellEl.contains(e.relatedTarget)))) {
            if (dwellTimer) {
                clearTimeout(dwellTimer);
                dwellTimer = null;
            }
            activeDwellEl = null;
        }
    }, true);

    function handleImmediateIntent(e) {
        if (e.button && e.button !== 0) return;
        const candidate = extractCandidate(e.target);
        if (candidate) {
            if (dwellTimer) {
                clearTimeout(dwellTimer);
                dwellTimer = null;
            }
            runPrefetch(candidate, true);
        }
    }

    document.addEventListener('pointerdown', handleImmediateIntent, { capture: true, passive: true });
    document.addEventListener('touchstart', handleImmediateIntent, { capture: true, passive: true });

    // Serve cached or in-flight HTMX GET triggers cleanly (e.g. Edit Modal, Recipe Modal, Preset Modals)
    document.addEventListener('htmx:beforeRequest', function (evt) {
        const detail = evt.detail;
        if (!detail || !detail.requestConfig) return;
        if ((detail.requestConfig.verb || 'get').toLowerCase() !== 'get') {
            // Mutating request -> clear prefetched edit/list caches so next open is fresh
            purgeAll();
            return;
        }
        const elt = detail.elt;
        if (!elt || elt.hasAttribute('data-no-prefetch')) return;
        if (elt.tagName === 'INPUT' || elt.tagName === 'SELECT' || elt.tagName === 'FORM') return;
        if (elt.getAttribute('hx-boost') === 'true' || elt.hasAttribute('data-boost-nav')) return;

        const targetEl = detail.target || (elt.getAttribute('hx-target') ? document.querySelector(elt.getAttribute('hx-target')) : elt);
        if (!targetEl) return;

        const rawUrl = elt.getAttribute('hx-get') || detail.pathInfo?.requestPath;
        const norm = normalizeUrl(rawUrl);
        if (!isPrefetchSafeUrl(norm)) return;

        const applyHtmlSwap = (html) => {
            if (!html || !document.body.contains(targetEl)) return;
            const swapStyle = elt.getAttribute('hx-swap') || 'innerHTML';
            if (swapStyle.startsWith('outerHTML')) {
                const wrap = document.createElement('div');
                wrap.innerHTML = html;
                const replacement = wrap.firstElementChild;
                if (replacement) {
                    targetEl.replaceWith(replacement);
                    if (window.htmx) window.htmx.process(replacement);
                    replacement.dispatchEvent(new CustomEvent('htmx:afterSwap', { bubbles: true, detail: { target: replacement, elt } }));
                    replacement.dispatchEvent(new CustomEvent('htmx:afterSettle', { bubbles: true, detail: { target: replacement, elt } }));
                }
            } else {
                targetEl.innerHTML = html;
                if (window.htmx) window.htmx.process(targetEl);
                targetEl.dispatchEvent(new CustomEvent('htmx:afterSwap', { bubbles: true, detail: { target: targetEl, elt } }));
                targetEl.dispatchEvent(new CustomEvent('htmx:afterSettle', { bubbles: true, detail: { target: targetEl, elt } }));
            }
        };

        const hit = getCached(norm, MODAL_TTL_MS);
        if (hit && hit.html) {
            evt.preventDefault();
            applyHtmlSwap(hit.html);
            return;
        }

        const pending = getInflight(norm);
        if (pending) {
            evt.preventDefault();
            pending.then((entry) => {
                if (entry && entry.html) {
                    applyHtmlSwap(entry.html);
                } else {
                    window.htmx && window.htmx.ajax('GET', norm, { target: targetEl, swap: elt.getAttribute('hx-swap') || 'innerHTML' });
                }
            });
        }
    });

    window.ShoppinPrefetch = {
        fetchUrl,
        getCached,
        getInflight,
        storeManual,
        invalidateMatching,
        purgeAll,
        normalizeUrl
    };
})();
