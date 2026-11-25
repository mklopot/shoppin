/**
 * Shoppin App Shell, SWR Navigation Cache, Idiomorph Protection,
 * Actionable Undo Toasts, Top Progress Bar, Skeletons & Service Worker Hook.
 */
(function () {
    'use strict';

    const SWR_MAX_ENTRIES = 12;
    const SWR_TTL_MS = 240000;
    const swrCache = new Map();
    const scrollByRoute = new Map();

    // -------------------------------------------------------------------------
    // 1. Cookie Purge Check & Global Cache Reset
    // -------------------------------------------------------------------------

    function getUserScope() {
        const body = document.body;
        const userId = body ? (body.getAttribute('data-user-id') || 'anon') : 'anon';
        const wsId = body ? (body.getAttribute('data-workspace-id') || '0') : '0';
        return `${userId}:${wsId}`;
    }

    function normalizePath(url) {
        try {
            const u = new URL(url, window.location.origin);
            if (u.origin !== window.location.origin) return '';
            u.searchParams.delete('org.htmx.cache-buster');
            return u.pathname + u.search;
        } catch (_) {
            return '';
        }
    }

    function invalidateWorkspaceCache() {
        swrCache.clear();
        if (window.ShoppinPrefetch) window.ShoppinPrefetch.purgeAll();
    }

    function purgeClientCaches() {
        swrCache.clear();
        scrollByRoute.clear();
        if (window.ShoppinPrefetch) window.ShoppinPrefetch.purgeAll();
        try {
            if (navigator.serviceWorker && navigator.serviceWorker.controller) {
                navigator.serviceWorker.controller.postMessage({ type: 'PURGE_USER_CACHES' });
            } else if (navigator.serviceWorker && navigator.serviceWorker.ready) {
                navigator.serviceWorker.ready.then((reg) => {
                    if (reg.active) reg.active.postMessage({ type: 'PURGE_USER_CACHES' });
                }).catch(() => {});
            }
        } catch (_) {}
    }

    if (document.cookie.includes('shoppin_purge_cache=')) {
        document.cookie = 'shoppin_purge_cache=; path=/; max-age=0; SameSite=Lax';
        purgeClientCaches();
    }

    // Register root-scoped PWA Service Worker silently
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('/sw.js', { scope: '/' }).then((reg) => {
                navigator.serviceWorker.addEventListener('message', (evt) => {
                    if (evt.data && evt.data.type === 'SW_OFFLINE_SNAPSHOT') {
                        const banner = document.getElementById('sw-offline-banner');
                        if (banner) banner.classList.remove('hidden');
                    }
                });
                if (reg.waiting && reg.active) {
                    reg.waiting.postMessage({ type: 'SKIP_WAITING' });
                }
            }).catch(() => {});
        });
    }

    // -------------------------------------------------------------------------
    // 2. Smart Top Progress Bar (>120ms threshold, zero flicker on fast swaps)
    // -------------------------------------------------------------------------

    let progressShowTimer = null;
    let progressTrickleTimer = null;
    let progressValue = 0;
    let activeNavRequests = 0;

    function getProgressBar() {
        return document.getElementById('global-nav-progress');
    }

    function startProgressBar() {
        activeNavRequests += 1;
        if (activeNavRequests > 1) return;
        const bar = getProgressBar();
        if (!bar) return;

        if (progressShowTimer) clearTimeout(progressShowTimer);
        progressShowTimer = setTimeout(() => {
            if (activeNavRequests <= 0) return;
            progressValue = 0.14;
            bar.style.transition = 'transform 180ms cubic-bezier(0.16, 1, 0.3, 1), opacity 150ms ease-out';
            bar.style.opacity = '1';
            bar.style.transform = `scaleX(${progressValue})`;
            if (progressTrickleTimer) clearInterval(progressTrickleTimer);
            progressTrickleTimer = setInterval(() => {
                progressValue = Math.min(0.88, progressValue + (0.9 - progressValue) * 0.22);
                bar.style.transform = `scaleX(${progressValue})`;
            }, 220);
        }, 120);
    }

    function finishProgressBar() {
        activeNavRequests = Math.max(0, activeNavRequests - 1);
        if (activeNavRequests > 0) return;

        if (progressShowTimer) {
            clearTimeout(progressShowTimer);
            progressShowTimer = null;
        }
        if (progressTrickleTimer) {
            clearInterval(progressTrickleTimer);
            progressTrickleTimer = null;
        }
        const bar = getProgressBar();
        if (!bar || bar.style.opacity === '0' || !bar.style.opacity) return;

        bar.style.transition = 'transform 140ms ease-out, opacity 200ms ease-out 100ms';
        bar.style.transform = 'scaleX(1)';
        bar.style.opacity = '0';
        setTimeout(() => {
            if (activeNavRequests === 0) {
                bar.style.transition = 'none';
                bar.style.transform = 'scaleX(0)';
            }
        }, 320);
    }

    // -------------------------------------------------------------------------
    // 3. Actionable Toast System (Undo Button + Hover/Focus Auto-Dismiss Pause)
    // -------------------------------------------------------------------------

    const MAX_TOASTS = 3;
    const toastTimers = new WeakMap();

    function dismissToast(el) {
        if (!el || el.dataset.dismissing) return;
        el.dataset.dismissing = 'true';
        const state = toastTimers.get(el);
        if (state && state.timer) clearTimeout(state.timer);
        el.style.transition = 'opacity 0.22s ease-out, transform 0.22s ease-out';
        el.style.opacity = '0';
        el.style.transform = window.innerWidth >= 640 ? 'translateY(-8px) scale(0.97)' : 'translateY(8px) scale(0.97)';
        setTimeout(() => {
            el.remove();
        }, 220);
    }

    function scheduleToastAutoDismiss(toast, durationMs) {
        const state = {
            remaining: durationMs,
            startedAt: Date.now(),
            timer: null
        };
        const arm = (ms) => {
            state.startedAt = Date.now();
            state.timer = setTimeout(() => dismissToast(toast), ms);
            const bar = toast.querySelector('.toast-progress-fill');
            if (bar) {
                bar.style.transition = `transform ${ms}ms linear`;
                requestAnimationFrame(() => {
                    bar.style.transform = 'scaleX(0)';
                });
            }
        };
        const pause = () => {
            if (state.timer) {
                clearTimeout(state.timer);
                state.timer = null;
            }
            const elapsed = Date.now() - state.startedAt;
            state.remaining = Math.max(800, state.remaining - elapsed);
            const bar = toast.querySelector('.toast-progress-fill');
            if (bar) {
                const ratio = Math.max(0.05, state.remaining / durationMs);
                bar.style.transition = 'none';
                bar.style.transform = `scaleX(${ratio})`;
            }
        };
        const resume = () => {
            if (!toast.dataset.dismissing && !state.timer) {
                arm(state.remaining);
            }
        };

        toast.addEventListener('mouseenter', pause);
        toast.addEventListener('mouseleave', resume);
        toast.addEventListener('focusin', pause);
        toast.addEventListener('focusout', resume);
        toastTimers.set(toast, state);
        arm(durationMs);
    }

    function showToast(message, options = {}) {
        if (!message) return;
        const container = document.getElementById('toast-container');
        if (!container) return;

        const opts = typeof options === 'object' && options ? options : {};
        const type = opts.type || 'info';
        const duration = typeof opts.duration === 'number' ? opts.duration : (opts.onUndo ? 4500 : 3500);

        const toneClasses = {
            success: 'border-emerald-400 bg-white/95 text-gray-900',
            warning: 'border-amber-400 bg-amber-50/95 text-amber-950',
            error: 'border-red-400 bg-red-50/95 text-red-950',
            info: 'border-gray-300 bg-white/95 text-gray-900'
        };
        const barColors = {
            success: 'bg-emerald-500',
            warning: 'bg-amber-500',
            error: 'bg-red-500',
            info: 'bg-gray-700'
        };

        const toast = document.createElement('div');
        toast.className = `toast-item relative overflow-hidden pointer-events-auto flex items-center justify-between gap-2 backdrop-blur-sm text-xs px-3.5 py-2.5 shadow-lg border min-w-[260px] max-w-sm rounded-none cursor-pointer ${toneClasses[type] || toneClasses.info}`;

        const span = document.createElement('span');
        span.className = 'font-medium pr-1 flex-1';
        span.textContent = message;
        toast.appendChild(span);

        if (typeof opts.onUndo === 'function') {
            const undoBtn = document.createElement('button');
            undoBtn.type = 'button';
            undoBtn.className = 'px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider bg-gray-900 hover:bg-black text-white rounded-none flex-shrink-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900';
            undoBtn.textContent = opts.undoLabel || 'Undo';
            undoBtn.onclick = function (e) {
                e.stopPropagation();
                if (toast.dataset.undone) return;
                toast.dataset.undone = '1';
                dismissToast(toast);
                opts.onUndo();
            };
            toast.appendChild(undoBtn);
        }

        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.setAttribute('aria-label', 'Dismiss notification');
        closeBtn.className = 'text-gray-700 hover:text-gray-950 font-bold text-base leading-none ml-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900';
        closeBtn.innerHTML = '<span aria-hidden="true">&times;</span>';
        closeBtn.onclick = function (e) {
            e.stopPropagation();
            dismissToast(toast);
        };
        toast.appendChild(closeBtn);

        const barTrack = document.createElement('div');
        barTrack.className = 'absolute bottom-0 left-0 right-0 h-[2px] bg-transparent pointer-events-none';
        barTrack.innerHTML = `<div class="toast-progress-fill h-full w-full origin-left opacity-60 ${barColors[type] || barColors.info}" style="transform: scaleX(1);"></div>`;
        toast.appendChild(barTrack);

        toast.onclick = function () {
            dismissToast(toast);
        };
        toast.dataset.toastInitialized = 'true';

        container.appendChild(toast);
        enforceMaxToasts(container);
        scheduleToastAutoDismiss(toast, duration);
    }

    function enforceMaxToasts(container) {
        const activeToasts = Array.from(container.querySelectorAll('.toast-item')).filter((t) => !t.dataset.dismissing);
        if (activeToasts.length > MAX_TOASTS) {
            const excess = activeToasts.length - MAX_TOASTS;
            for (let i = 0; i < excess; i++) {
                dismissToast(activeToasts[i]);
            }
        }
    }

    function initToasts() {
        const container = document.getElementById('toast-container');
        if (!container) return;
        enforceMaxToasts(container);
        container.querySelectorAll('.toast-item:not([data-toast-initialized])').forEach((toast) => {
            toast.dataset.toastInitialized = 'true';
            if (!toast.onclick) {
                toast.style.cursor = 'pointer';
                toast.onclick = function () { dismissToast(toast); };
            }
            scheduleToastAutoDismiss(toast, 3500);
        });
    }

    window.showToast = showToast;
    window.dismissToast = dismissToast;
    window.initToasts = initToasts;

    // -------------------------------------------------------------------------
    // 4. Surgical DOM Morphing (Idiomorph + Outbox Pending-Row Guard)
    // -------------------------------------------------------------------------

    function isNodeProtected(node) {
        if (!node || node.nodeType !== 1) return false;
        const active = document.activeElement;
        if (active && (node === active || node.contains(active))) {
            const tag = active.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
        }
        if (node.dataset) {
            if (node.dataset.pendingDelete === '1' || node.dataset.optimisticPending === '1') return true;
            if (node.dataset.itemId && window.ShoppinQueue && window.ShoppinQueue.isRowLocked(node.dataset.itemId)) {
                return true;
            }
        }
        return false;
    }

    function syncProtectedShoppingRowsToIncoming(targetEl, newNode) {
        if (!targetEl || !newNode) return;
        const incomingRoot = newNode.id === 'shopping-list-content'
            ? newNode
            : newNode.querySelector?.('#shopping-list-content');
        const oldRoot = targetEl.id === 'shopping-list-content'
            ? targetEl
            : targetEl.querySelector?.('#shopping-list-content');
        if (!incomingRoot || !oldRoot) return;

        const protectedRows = Array.from(oldRoot.querySelectorAll('.item-row')).filter((r) => isNodeProtected(r) && r.id);
        protectedRows.forEach((oldRow) => {
            const staleIncoming = incomingRoot.querySelector(`#${CSS.escape(oldRow.id)}`);
            if (staleIncoming) staleIncoming.remove();

            const clone = oldRow.cloneNode(true);
            const inPantry = Boolean(oldRow.closest('#pantry-items-list'));
            const inGot = Boolean(oldRow.closest('#got-items-list'));

            if (inPantry) {
                const pantryList = incomingRoot.querySelector('#pantry-items-list');
                const pantryBox = incomingRoot.querySelector('#pantry-section-container');
                if (pantryList) {
                    pantryBox?.classList.remove('hidden');
                    pantryList.prepend(clone);
                }
            } else if (inGot) {
                const gotList = incomingRoot.querySelector('#got-items-list');
                const gotBox = incomingRoot.querySelector('#got-section-container');
                if (gotList) {
                    gotBox?.classList.remove('hidden');
                    gotList.prepend(clone);
                }
            } else {
                const groupName = oldRow.closest('.section-group-block')?.getAttribute('data-group-name') || oldRow.getAttribute('data-group-name');
                const sections = incomingRoot.querySelector('#section-groups-container');
                if (sections) {
                    const escGroup = groupName && window.CSS && window.CSS.escape ? window.CSS.escape(groupName) : (groupName || '');
                    const matchBlock = escGroup ? sections.querySelector(`.section-group-block[data-group-name="${escGroup}"]`) : null;
                    const destGroup = (matchBlock || sections.querySelector('.section-group-block'))?.querySelector('.sortable-group');
                    if (destGroup) {
                        destGroup.closest('.section-group-block')?.classList.remove('hidden');
                        incomingRoot.querySelector('#to-buy-empty-placeholder')?.classList.add('hidden');
                        destGroup.prepend(clone);
                    }
                }
            }
        });
    }

    function morphElement(targetEl, htmlOrNode, morphStyle = 'outerHTML') {
        if (!targetEl || !document.body.contains(targetEl)) return null;

        let newNode = null;
        if (typeof htmlOrNode === 'string') {
            const wrapper = document.createElement('div');
            wrapper.innerHTML = htmlOrNode.trim();
            if (targetEl.id) {
                newNode = wrapper.querySelector(`#${CSS.escape(targetEl.id)}`);
            }
            if (!newNode) {
                newNode = wrapper.firstElementChild;
            }
            // Also extract any OOB toasts accompanying the partial
            wrapper.querySelectorAll('[hx-swap-oob]').forEach((oobEl) => {
                if (oobEl.id === 'toast-container') {
                    const tc = document.getElementById('toast-container');
                    if (tc) {
                        Array.from(oobEl.children).forEach((child) => tc.appendChild(child));
                        initToasts();
                    }
                }
            });
        } else {
            newNode = htmlOrNode;
        }

        if (!newNode) return null;

        // Protect optimistic ghost rows still waiting for server creation
        const ghosts = Array.from(targetEl.querySelectorAll('[data-optimistic-pending="1"]'));
        syncProtectedShoppingRowsToIncoming(targetEl, newNode);

        if (typeof window.Idiomorph !== 'undefined' && typeof window.Idiomorph.morph === 'function') {
            window.Idiomorph.morph(targetEl, newNode, {
                morphStyle,
                callbacks: {
                    beforeNodeMorphed: function (oldEl, incomingEl) {
                        if (!oldEl || oldEl.nodeType !== 1) return true;
                        // Preserve <details> open state smoothly
                        if (oldEl.tagName === 'DETAILS' && incomingEl && incomingEl.tagName === 'DETAILS') {
                            if (oldEl.open) incomingEl.setAttribute('open', '');
                        }
                        if (isNodeProtected(oldEl)) return false;
                        return true;
                    }
                }
            });
            const morphedTarget = document.getElementById(targetEl.id) || targetEl;
            // Re-attach any un-settled optimistic ghost rows if server hasn't materialized them yet
            if (ghosts.length > 0 && morphedTarget.id === 'shopping-list-content') {
                const container = morphedTarget.querySelector('#section-groups-container .sortable-group');
                if (container) {
                    ghosts.forEach((g) => {
                        if (!document.body.contains(g)) container.prepend(g);
                    });
                }
            }
            if (window.htmx) window.htmx.process(morphedTarget);
            return morphedTarget;
        }

        targetEl.replaceWith(newNode);
        if (window.htmx) window.htmx.process(newNode);
        return newNode;
    }

    function swapFromHtml(selector, html) {
        const el = document.querySelector(selector);
        if (!el) return null;
        const result = morphElement(el, html, 'outerHTML');
        reinitPageModules(result);
        return result;
    }

    // Configure native HTMX morphing guard when hx-swap="morph:*" is used
    window.ShoppinMorph = { morphElement, swapFromHtml };

    // -------------------------------------------------------------------------
    // 5. Boosted App-Shell Navigation, SWR Cache & Instant Tab Feedback
    // -------------------------------------------------------------------------

    function updateNavActiveState(pathname, search) {
        const full = `${pathname}${search || ''}`;
        let activeTab = 'shopping';
        if (pathname.includes('/mealplans')) activeTab = 'mealplan';
        else if (pathname.includes('/recipes')) activeTab = 'recipes';
        else if (pathname.includes('/preset')) activeTab = 'presets';
        else if (pathname.includes('/pantry-check') || full.includes('mode=pantry')) activeTab = 'pantry';

        const dtActive = 'inline-flex items-center px-2.5 text-xs font-semibold text-gray-900 border-b-2 border-gray-800 -mb-[1px]';
        const dtInactive = 'inline-flex items-center px-2.5 text-xs font-medium text-gray-600 hover:text-gray-900 border-b-2 border-transparent hover:border-gray-300 -mb-[1px]';
        const mbActive = 'inline-flex items-center justify-center px-2.5 py-1 text-xs font-bold whitespace-nowrap flex-shrink-0 rounded-none transition-colors bg-gray-950 text-white border border-gray-950 shadow-sm';
        const mbInactive = 'inline-flex items-center justify-center px-2.5 py-1 text-xs font-bold whitespace-nowrap flex-shrink-0 rounded-none transition-colors bg-white text-gray-700 hover:text-gray-950 border border-gray-300';

        const matchTab = (link) => {
            const href = link.getAttribute('href') || '';
            const mode = link.getAttribute('data-mode-switch');
            if (mode === 'pantry') return activeTab === 'pantry';
            if (mode === 'shopping') return activeTab === 'shopping';
            if (href.includes('/mealplans')) return activeTab === 'mealplan';
            if (href.includes('/recipes')) return activeTab === 'recipes';
            if (href.includes('/preset')) return activeTab === 'presets';
            return false;
        };

        document.querySelectorAll('nav[aria-label="Primary Navigation"] a').forEach((a) => {
            const isActive = matchTab(a);
            a.className = isActive ? dtActive : dtInactive;
            if (isActive) a.setAttribute('aria-current', 'page');
            else a.removeAttribute('aria-current');
        });

        document.querySelectorAll('#mobile-nav-tabs a').forEach((a) => {
            const isActive = matchTab(a);
            a.className = isActive ? mbActive : mbInactive;
            if (isActive) a.setAttribute('aria-current', 'page');
            else a.removeAttribute('aria-current');
        });
    }

    function storeSwrSnapshot(url, html, title) {
        const norm = normalizePath(url);
        if (!norm || !html) return;
        const key = `${getUserScope()}:${norm}`;
        swrCache.set(key, {
            url: norm,
            html,
            title: title || document.title,
            timestamp: Date.now()
        });
        while (swrCache.size > SWR_MAX_ENTRIES) {
            const oldest = swrCache.keys().next().value;
            swrCache.delete(oldest);
        }
    }

    function getSwrSnapshot(url) {
        const key = `${getUserScope()}:${normalizePath(url)}`;
        const entry = swrCache.get(key);
        if (!entry) return null;
        if (Date.now() - entry.timestamp > SWR_TTL_MS) {
            swrCache.delete(key);
            return null;
        }
        return entry;
    }

    function parseTitleAndMain(fullHtml) {
        const doc = new DOMParser().parseFromString(fullHtml, 'text/html');
        const main = doc.getElementById('main-content');
        const title = doc.title;
        return { main, title };
    }

    function executeEmbeddedScripts(container) {
        if (!container) return;
        container.querySelectorAll('script').forEach((oldScript) => {
            if (oldScript.type && oldScript.type !== 'text/javascript') return;
            const newScript = document.createElement('script');
            Array.from(oldScript.attributes).forEach((attr) => newScript.setAttribute(attr.name, attr.value));
            newScript.textContent = oldScript.textContent;
            oldScript.parentNode.replaceChild(newScript, oldScript);
        });
    }

    function reinitPageModules(root) {
        initToasts();
        if (typeof window.initSortables === 'function') window.initSortables();
        if (typeof window.syncCardState === 'function') window.syncCardState();
        if (typeof window.applyPresetListsCardState === 'function') window.applyPresetListsCardState();
        if (typeof window.updateResetButtonState === 'function') window.updateResetButtonState();
        if (window.ShoppinQueue) window.ShoppinQueue.updateSyncIndicators();
        if (window.ShoppinSync && document.getElementById('shopping-list-content')) {
            window.ShoppinSync.updateSyncIndicator();
        }
        const scope = root || document;
        if (window.htmx && scope && scope !== document) {
            window.htmx.process(scope);
        }
    }

    function applyBoostedMainHtml(fullHtml, targetUrl, pushHistory) {
        const { main: incomingMain, title } = parseTitleAndMain(fullHtml);
        const currentMain = document.getElementById('main-content');
        if (!incomingMain || !currentMain) return false;

        // Save current route scroll
        scrollByRoute.set(normalizePath(window.location.href), window.scrollY || 0);

        const newMain = incomingMain.cloneNode(true);
        currentMain.replaceWith(newMain);
        executeEmbeddedScripts(newMain);
        if (window.htmx) window.htmx.process(newMain);

        if (title) document.title = title;
        if (pushHistory && window.history && window.history.pushState) {
            window.history.pushState({ swrUrl: targetUrl }, document.title, targetUrl);
        }

        const u = new URL(targetUrl, window.location.origin);
        updateNavActiveState(u.pathname, u.search);
        reinitPageModules(newMain);

        const savedY = scrollByRoute.get(normalizePath(targetUrl)) || 0;
        window.scrollTo({ top: savedY, behavior: 'instant' });
        return true;
    }

    // Immediate highlight on nav tap & SWR instant cache swap
    document.addEventListener('pointerdown', function (e) {
        if (e.button && e.button !== 0) return;
        const link = e.target && e.target.closest && e.target.closest('nav[aria-label="Primary Navigation"] a, #mobile-nav-tabs a');
        if (!link) return;
        const href = link.getAttribute('href');
        if (!href) return;
        const u = new URL(href, window.location.origin);
        updateNavActiveState(u.pathname, u.search);
    }, { capture: true, passive: true });

    document.addEventListener('click', function (e) {
        if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
        const link = e.target && e.target.closest && e.target.closest('a[href]');
        if (!link || link.hasAttribute('download')) return;
        if (link.getAttribute('hx-boost') === 'false') return;
        if (link.closest('#shopping-list-content') && link.hasAttribute('data-mode-switch')) return;
        if (link.hasAttribute('data-mode-switch') && document.getElementById('shopping-list-content')) return;

        const isBoostNav = (
            link.getAttribute('hx-boost') === 'true' ||
            link.hasAttribute('data-boost-nav') ||
            link.closest('nav[aria-label="Primary Navigation"]') ||
            link.closest('#mobile-nav-tabs')
        );
        if (!isBoostNav) return;

        const href = link.getAttribute('href');
        const norm = normalizePath(href);
        if (!norm) return;

        // Same-route click skips redundant nav
        if (norm === normalizePath(window.location.href)) {
            e.preventDefault();
            return;
        }

        const swr = getSwrSnapshot(norm) || (window.ShoppinPrefetch && window.ShoppinPrefetch.getCached(norm, 60000));
        if (swr && swr.html && swr.html.includes('id="main-content"')) {
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();

            const ok = applyBoostedMainHtml(swr.html, norm, true);
            if (ok) {
                // Silent background revalidation (no progress flicker, no opacity dimming!)
                const swrStartEpoch = window.ShoppinQueue && window.ShoppinQueue.getMutationEpoch
                    ? window.ShoppinQueue.getMutationEpoch()
                    : 0;
                fetch(norm, {
                    method: 'GET',
                    credentials: 'same-origin',
                    headers: {
                        'HX-Request': 'true',
                        'HX-Boosted': 'true',
                        'HX-Target': 'main-content',
                        'X-SWR-Revalidate': '1',
                        'X-Client-Id': window.CLIENT_ID || 'client_web'
                    }
                }).then(async (resp) => {
                    if (!resp.ok || resp.redirected) return;
                    const epochNow = window.ShoppinQueue && window.ShoppinQueue.getMutationEpoch
                        ? window.ShoppinQueue.getMutationEpoch()
                        : 0;
                    const pendingNow = window.ShoppinQueue && window.ShoppinQueue.hasPendingWork
                        ? window.ShoppinQueue.hasPendingWork()
                        : false;
                    if (epochNow !== swrStartEpoch || pendingNow) {
                        invalidateWorkspaceCache();
                        return;
                    }
                    const freshHtml = await resp.text();
                    if (!freshHtml.includes('id="main-content"')) return;
                    storeSwrSnapshot(norm, freshHtml);
                    if (normalizePath(window.location.href) !== norm) return;
                    const { main: freshMain, title } = parseTitleAndMain(freshHtml);
                    const curMain = document.getElementById('main-content');
                    if (freshMain && curMain && freshMain.innerHTML !== curMain.innerHTML) {
                        morphElement(curMain, freshMain, 'outerHTML');
                        if (title) document.title = title;
                        reinitPageModules(document.getElementById('main-content'));
                    }
                }).catch(() => {});
            }
            return;
        }

        const inflightEntry = window.ShoppinPrefetch && window.ShoppinPrefetch.getInflight
            ? window.ShoppinPrefetch.getInflight(norm)
            : null;
        if (inflightEntry) {
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            startProgressBar();
            inflightEntry.then((entry) => {
                finishProgressBar();
                if (entry && entry.html && entry.html.includes('id="main-content"')) {
                    storeSwrSnapshot(norm, entry.html);
                    const applied = applyBoostedMainHtml(entry.html, norm, true);
                    if (applied) return;
                }
                window.location.href = norm;
            }).catch(() => {
                finishProgressBar();
                window.location.href = norm;
            });
        }
    }, true);

    // -------------------------------------------------------------------------
    // 6. Contextual Shimmer Skeletons & Request Progress Wiring
    // -------------------------------------------------------------------------

    function renderStorePickerSkeletonHtml() {
        return `
            <div id="modal-container" role="dialog" aria-modal="true" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-[2px] p-2 sm:p-4">
                <div class="bg-white border border-gray-400 max-w-2xl w-full flex flex-col shadow-2xl text-xs rounded-none p-4 space-y-3">
                    <div class="flex justify-between items-center border-b border-gray-300 pb-2">
                        <div class="h-4 w-56 skeleton-shimmer"></div>
                        <button type="button" onclick="document.getElementById('modal-container')?.remove()" class="text-gray-700 font-bold text-xl leading-none px-1">&times;</button>
                    </div>
                    <div class="h-8 w-full skeleton-shimmer"></div>
                    <div class="h-[230px] w-full skeleton-shimmer border border-gray-200 flex items-center justify-center text-gray-600 font-medium">
                        Locating nearby stores...
                    </div>
                    <div class="space-y-2">
                        <div class="h-12 w-full skeleton-shimmer"></div>
                        <div class="h-12 w-full skeleton-shimmer"></div>
                        <div class="h-12 w-full skeleton-shimmer"></div>
                    </div>
                </div>
            </div>
        `;
    }

    function renderSuggestionsSkeletonHtml() {
        return `
            <div class="mt-2.5 p-3 bg-indigo-50/40 border border-indigo-200 space-y-2 text-xs">
                <div class="flex items-center space-x-2 text-indigo-900 font-semibold">
                    <span class="inline-block w-3.5 h-3.5 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin"></span>
                    <span>Scoring recipes &amp; meal rules...</span>
                </div>
                <div class="h-14 w-full skeleton-shimmer"></div>
                <div class="h-14 w-full skeleton-shimmer"></div>
            </div>
        `;
    }

    // Attach skeleton & import-progress listeners cleanly via delegation
    document.addEventListener('click', function (e) {
        const suggestBtn = e.target && e.target.closest && e.target.closest('button[hx-get*="suggestions"]');
        if (suggestBtn) {
            const targetSel = suggestBtn.getAttribute('hx-target');
            const box = targetSel ? document.querySelector(targetSel) : null;
            if (box) box.innerHTML = renderSuggestionsSkeletonHtml();
        }
    });

    document.addEventListener('submit', function (e) {
        const importForm = e.target && e.target.closest && e.target.closest('#import-url-modal form');
        if (importForm) {
            let statusBox = importForm.querySelector('.import-progress-box');
            if (!statusBox) {
                statusBox = document.createElement('div');
                statusBox.className = 'import-progress-box p-2.5 bg-indigo-50 border border-indigo-200 text-indigo-950 text-xs flex items-center gap-2';
                statusBox.innerHTML = `
                    <span class="inline-block w-3.5 h-3.5 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin flex-shrink-0"></span>
                    <span class="import-progress-label font-medium">Connecting to webpage &amp; parsing recipe...</span>
                `;
                importForm.appendChild(statusBox);
            }
            const btns = importForm.querySelectorAll('button[type="submit"]');
            btns.forEach((b) => { b.disabled = true; b.classList.add('opacity-70'); });
            setTimeout(() => {
                const lbl = importForm.querySelector('.import-progress-label');
                if (lbl) lbl.textContent = 'Extracting ingredients, steps & nutritional data...';
            }, 1200);
        }
    });

    document.addEventListener('htmx:beforeRequest', function (evt) {
        const detail = evt.detail;
        if (!detail || !detail.requestConfig) return;
        const elt = detail.elt;
        const verb = (detail.requestConfig.verb || 'get').toLowerCase();
        const url = detail.pathInfo?.requestPath || '';
        const target = detail.target;

        // Only show top progress bar for boosted nav or user-initiated slow GETs (never background WS syncs!)
        const isBackgroundRefresh = Boolean(
            target && (target.id === 'shopping-list-content' || target.id === 'mealplan-content') && !elt
        );
        if (verb === 'get' && !isBackgroundRefresh && !url.includes('org.htmx.cache-buster')) {
            startProgressBar();
        }

        // Archived drawer lazy-load skeleton
        if (elt && elt.closest && elt.closest('#archived-meals-details')) {
            const body = document.getElementById('archived-meals-drawer-body');
            if (body) {
                body.innerHTML = '<div class="space-y-2 py-1"><div class="h-14 w-full skeleton-shimmer"></div><div class="h-14 w-full skeleton-shimmer"></div></div>';
            }
        }
    });

    document.addEventListener('htmx:afterOnLoad', function (evt) {
        const detail = evt.detail;
        if (!detail || !detail.xhr) return;
        const target = detail.target;
        if (target && target.id === 'main-content' && detail.xhr.status === 200) {
            const url = detail.pathInfo?.finalRequestPath || detail.pathInfo?.requestPath || window.location.href;
            storeSwrSnapshot(url, detail.xhr.responseText);
        }
    });

    document.addEventListener('htmx:afterSettle', function (evt) {
        finishProgressBar();
        const detail = evt.detail;
        if (detail && detail.target) {
            reinitPageModules(detail.target);
            if (detail.target.id === 'main-content') {
                updateNavActiveState(window.location.pathname, window.location.search);
            }
        }
    });

    document.addEventListener('htmx:responseError', finishProgressBar);
    document.addEventListener('htmx:sendError', finishProgressBar);

    // Seed initial full-page SWR cache once loaded
    document.addEventListener('DOMContentLoaded', () => {
        initToasts();
        const main = document.getElementById('main-content');
        if (main) {
            const fullStub = `<html><head><title>${document.title}</title></head><body>${main.outerHTML}</body></html>`;
            storeSwrSnapshot(window.location.href, fullStub, document.title);
        }
    });

    window.addEventListener('popstate', function () {
        const norm = normalizePath(window.location.href);
        const swr = getSwrSnapshot(norm);
        if (swr && swr.html) {
            applyBoostedMainHtml(swr.html, norm, false);
        }
    });

    window.purgeClientCaches = purgeClientCaches;
    window.ShoppinShell = {
        storeSwrSnapshot,
        getSwrSnapshot,
        invalidateWorkspaceCache,
        purgeClientCaches,
        updateNavActiveState,
        reinitPageModules,
        renderStorePickerSkeletonHtml
    };
})();
