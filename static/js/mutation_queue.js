/**
 * Shoppin Unified Transactional Outbox & Cross-App Optimistic Mutation Queue
 *
 * Manages offline-safe FIFO execution, request coalescing, X-Idempotency-Key
 * headers, cross-tab exclusivity (Web Locks / BroadcastChannel), temp-ID
 * resolution, exponential retry backoff, hold-to-undo deletes, and 0ms
 * optimistic updates across Recipes, Meal Plans, and Preset Lists.
 */
(function () {
    'use strict';

    const QUEUE_STORAGE_KEY = 'shoppin_offline_actions_v1';
    const LEASE_STORAGE_KEY = 'shoppin_outbox_lease_v1';
    const LIST_BADGE_BASE = 'w-[110px] h-[22px] min-w-[110px] max-w-[110px] min-h-[22px] max-h-[22px] inline-flex items-center justify-center text-center text-[11px] font-semibold px-1.5 py-0.5 border rounded-none select-none transition-opacity duration-200 whitespace-nowrap overflow-hidden flex-shrink-0';
    const GLOBAL_BADGE_BASE = 'inline-flex items-center justify-center text-[11px] font-semibold px-2 py-0.5 border rounded-none select-none transition-all duration-150 whitespace-nowrap';
    const BACKOFF_STEPS_MS = [400, 1000, 2200, 5000, 12000, 25000];
    const HOLD_DELAY_MS = 2600;

    let isFlushing = false;
    let retryTimer = null;
    let syncBadgeTimer = null;
    let consecutiveFailures = 0;
    let mutationEpoch = 0;
    let inFlightActionId = null;
    let inFlightItemId = null;
    const pendingReconcileTargets = new Set();

    const lockedRowIds = new Set();
    const burstProtectedRowIds = new Set();
    const tempIdMap = new Map();
    const pendingHolds = new Map();
    const scaleDebounceTimers = new Map();
    const recentClickStamps = new Map();

    function bumpEpoch() {
        mutationEpoch += 1;
    }

    function getMutationEpoch() {
        return mutationEpoch;
    }

    function hasPendingWork() {
        return inFlightActionId !== null || pendingHolds.size > 0 || getQueue().length > 0;
    }

    let channel = null;
    try {
        if (typeof BroadcastChannel !== 'undefined') {
            channel = new BroadcastChannel('shoppin_outbox_sync');
            channel.onmessage = function (evt) {
                if (evt && evt.data && evt.data.type === 'queue_updated') {
                    updateSyncIndicators();
                }
            };
        }
    } catch (_) {}

    function getCsrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta && meta.content) return meta.content;
        const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (input && input.value) return input.value;
        const match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }

    function generateKey(prefix) {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') {
            return `${prefix}_${window.crypto.randomUUID()}`;
        }
        return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
    }

    function getQueue() {
        try {
            const raw = localStorage.getItem(QUEUE_STORAGE_KEY);
            const parsed = raw ? JSON.parse(raw) : [];
            return Array.isArray(parsed) ? parsed : [];
        } catch (_) {
            return [];
        }
    }

    function saveQueue(queue) {
        try {
            localStorage.setItem(QUEUE_STORAGE_KEY, JSON.stringify(queue));
            if (channel) {
                channel.postMessage({ type: 'queue_updated', length: queue.length });
            }
        } catch (_) {}
        rebuildLockedRows(queue);
        updateSyncIndicators();
    }

    function rebuildLockedRows(queue) {
        lockedRowIds.clear();
        (queue || []).forEach((act) => {
            if (act && act.meta && act.meta.itemId) {
                lockedRowIds.add(String(act.meta.itemId));
            }
        });
        if (inFlightItemId) {
            lockedRowIds.add(String(inFlightItemId));
        }
        for (const hold of pendingHolds.values()) {
            if (hold && hold.itemId) lockedRowIds.add(String(hold.itemId));
        }
    }

    function isRowLocked(itemId) {
        if (!itemId) return false;
        const key = String(itemId);
        return (
            lockedRowIds.has(key)
            || (inFlightItemId !== null && inFlightItemId === key)
            || (burstProtectedRowIds.has(key) && hasPendingWork())
        );
    }

    function getTotalPendingCount() {
        return getQueue().length + pendingHolds.size;
    }

    function updateSyncIndicators() {
        const count = getTotalPendingCount();
        const isOnline = navigator.onLine;

        if (syncBadgeTimer) {
            clearTimeout(syncBadgeTimer);
            syncBadgeTimer = null;
        }

        const listInd = document.getElementById('offline-sync-indicator');
        const globalInd = document.getElementById('global-sync-indicator');

        const setVisual = (el, baseCls, text, cls, title, hidden) => {
            if (!el) return;
            if (hidden) {
                el.textContent = '';
                el.className = `${baseCls} hidden opacity-0 pointer-events-none border-transparent bg-transparent`;
                el.removeAttribute('title');
                return;
            }
            el.textContent = text;
            el.className = `${baseCls} ${cls}`;
            if (title) el.setAttribute('title', title);
        };

        if (count > 0) {
            if (!isOnline) {
                const txt = count > 1 ? `⚡ Offline (${count})` : '⚡ Offline (1)';
                const title = `${count} change(s) queued safely offline. Will sync automatically when reconnected.`;
                setVisual(listInd, LIST_BADGE_BASE, txt, 'opacity-100 border-amber-400 bg-amber-50 text-amber-900', title, false);
                setVisual(globalInd, GLOBAL_BADGE_BASE, txt, 'opacity-100 border-amber-400 bg-amber-50 text-amber-900', title, false);
            } else {
                const txt = count > 1 ? `🔄 Sync (${count})` : '🔄 Syncing';
                const title = 'Syncing queued actions in background.';
                setVisual(listInd, LIST_BADGE_BASE, txt, 'opacity-100 border-blue-400 bg-blue-50 text-blue-900', title, false);
                setVisual(globalInd, GLOBAL_BADGE_BASE, txt, 'opacity-100 border-blue-400 bg-blue-50 text-blue-900', title, false);
            }
        } else if (!isOnline) {
            const title = 'Working offline. Actions will queue locally and auto-sync.';
            setVisual(listInd, LIST_BADGE_BASE, '⚡ Offline', 'opacity-100 border-amber-300 bg-amber-50 text-amber-800', title, false);
            setVisual(globalInd, GLOBAL_BADGE_BASE, '⚡ Offline', 'opacity-100 border-amber-300 bg-amber-50 text-amber-800', title, false);
        } else {
            if (listInd) {
                listInd.className = `${LIST_BADGE_BASE} opacity-0 pointer-events-none border-transparent bg-transparent`;
            }
            setVisual(globalInd, GLOBAL_BADGE_BASE, '', '', '', true);
        }
    }

    function showTemporarySyncedBadge() {
        const listInd = document.getElementById('offline-sync-indicator');
        const globalInd = document.getElementById('global-sync-indicator');
        if (listInd) {
            listInd.textContent = '✓ Saved';
            listInd.className = `${LIST_BADGE_BASE} opacity-100 border-emerald-400 bg-emerald-50 text-emerald-900`;
        }
        if (globalInd) {
            globalInd.textContent = '✓ Synced';
            globalInd.className = `${GLOBAL_BADGE_BASE} opacity-100 border-emerald-400 bg-emerald-50 text-emerald-900`;
        }
        if (syncBadgeTimer) clearTimeout(syncBadgeTimer);
        syncBadgeTimer = setTimeout(() => {
            updateSyncIndicators();
        }, 1600);
    }

    function ensureIdempotencyBodyAndHeaders(bodyParams, idempotencyKey) {
        return {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-Client-Id': window.CLIENT_ID || 'client_web',
            'X-Idempotency-Key': idempotencyKey,
            'HX-Request': 'true',
            'HX-Current-URL': window.location.href
        };
    }

    function serializeForm(form) {
        const fd = new FormData(form);
        if (!fd.has('csrfmiddlewaretoken')) {
            const tok = getCsrfToken();
            if (tok) fd.append('csrfmiddlewaretoken', tok);
        }
        return new URLSearchParams(fd).toString();
    }

    /**
     * Enqueue a POST mutation into the persistent FIFO outbox.
     * Options may include `coalesceKey`, `idempotencyKey`, `onSuccess(resp, html)`, `onError(resp)`.
     */
    function enqueue(url, body, meta = {}, callbacks = {}) {
        bumpEpoch();
        const rawQueue = getQueue();
        const actId = generateKey('act');
        const idempotencyKey = meta.idempotencyKey || generateKey('idem');

        const actionItem = {
            id: actId,
            url,
            body,
            meta,
            coalesceKey: meta.coalesceKey || null,
            idempotencyKey,
            timestamp: Date.now()
        };

        if (meta && meta.reconcileTarget) {
            pendingReconcileTargets.add(meta.reconcileTarget);
        }
        if (meta && meta.itemId) {
            burstProtectedRowIds.add(String(meta.itemId));
        }

        // Store non-serializable callbacks on memory registry for live tab reconciliation
        if (callbacks && (callbacks.onSuccess || callbacks.onError)) {
            liveCallbackRegistry.set(actId, callbacks);
        }

        // Collapse earlier queued (NEVER currently in-flight) items sharing coalesceKey,
        // placing the newest intent cleanly at the tail to preserve strict chronological ordering.
        let nextQueue = rawQueue;
        if (actionItem.coalesceKey) {
            nextQueue = rawQueue.filter((q) => {
                if (inFlightActionId && q.id === inFlightActionId) return true;
                if (q.coalesceKey === actionItem.coalesceKey) {
                    liveCallbackRegistry.delete(q.id);
                    return false;
                }
                return true;
            });
        }

        nextQueue.push(actionItem);
        saveQueue(nextQueue);
        consecutiveFailures = 0;
        scheduleFlush(0);
        return actId;
    }

    const liveCallbackRegistry = new Map();

    function resolveTempIdsInAction(action) {
        let url = action.url;
        let body = action.body || '';
        for (const [tempId, realId] of tempIdMap.entries()) {
            url = url.replace(new RegExp(`/item/${tempId}(?=/|$)`, 'g'), `/item/${realId}`);
            if (body.includes(tempId)) {
                body = body.replaceAll(tempId, realId);
            }
            if (action.meta && String(action.meta.itemId) === String(tempId)) {
                action.meta.itemId = realId;
            }
        }
        action.url = url;
        action.body = body;
    }

    function applyOutboxResponse(action, response, responseHtml, ctx = {}) {
        // Record newly created canonical ID for optimistic ghost rows
        const createdId = response.headers.get('X-Created-Item-Id');
        if (createdId && action.meta && action.meta.tempId) {
            tempIdMap.set(String(action.meta.tempId), String(createdId));
        }

        if (window.ShoppinPrefetch) {
            window.ShoppinPrefetch.purgeAll();
        }
        if (window.ShoppinShell && typeof window.ShoppinShell.invalidateWorkspaceCache === 'function') {
            window.ShoppinShell.invalidateWorkspaceCache();
        }

        const cbs = liveCallbackRegistry.get(action.id);
        liveCallbackRegistry.delete(action.id);
        if (cbs && typeof cbs.onSuccess === 'function') {
            try {
                cbs.onSuccess(response, responseHtml, ctx);
            } catch (_) {}
        }
    }

    function acquireLease(fn) {
        if (navigator.locks && typeof navigator.locks.request === 'function') {
            return navigator.locks.request('shoppin_outbox_flush_lock', { ifAvailable: false }, fn);
        }
        const now = Date.now();
        try {
            const raw = localStorage.getItem(LEASE_STORAGE_KEY);
            if (raw) {
                const parsed = JSON.parse(raw);
                if (parsed.owner !== window.CLIENT_ID && now - parsed.ts < 8000) {
                    return Promise.resolve();
                }
            }
            localStorage.setItem(LEASE_STORAGE_KEY, JSON.stringify({ owner: window.CLIENT_ID, ts: now }));
        } catch (_) {}
        return Promise.resolve(fn()).finally(() => {
            try { localStorage.removeItem(LEASE_STORAGE_KEY); } catch (_) {}
        });
    }

    function scheduleFlush(delayMs) {
        if (retryTimer) {
            clearTimeout(retryTimer);
            retryTimer = null;
        }
        if (!navigator.onLine) {
            updateSyncIndicators();
            return;
        }
        if (delayMs <= 0) {
            flushQueue();
            return;
        }
        retryTimer = setTimeout(() => {
            retryTimer = null;
            flushQueue();
        }, delayMs);
    }

    async function flushQueue() {
        if (isFlushing) return;
        const initialQueue = getQueue();
        if (initialQueue.length === 0 || !navigator.onLine) {
            updateSyncIndicators();
            return;
        }

        await acquireLease(async () => {
            if (isFlushing) return;
            if (getQueue().length === 0 || !navigator.onLine) {
                updateSyncIndicators();
                return;
            }

            isFlushing = true;
            updateSyncIndicators();
            let hadItems = false;
            let processedCount = 0;
            let lastShoppingHtml = null;
            let haltedByNetworkOrServer = false;

            try {
                while (true) {
                    const liveQueue = getQueue();
                    if (liveQueue.length === 0) break;
                    if (!navigator.onLine) {
                        haltedByNetworkOrServer = true;
                        break;
                    }

                    hadItems = true;
                    const current = liveQueue[0];
                    inFlightActionId = current.id;
                    inFlightItemId = current.meta && current.meta.itemId ? String(current.meta.itemId) : null;
                    rebuildLockedRows(liveQueue);
                    resolveTempIdsInAction(current);

                    try {
                        // Replace fresh CSRF if cookie updated
                        let bodyStr = current.body || '';
                        const liveCsrf = getCsrfToken();
                        if (liveCsrf && bodyStr.includes('csrfmiddlewaretoken=')) {
                            bodyStr = bodyStr.replace(/csrfmiddlewaretoken=[^&]*/g, `csrfmiddlewaretoken=${encodeURIComponent(liveCsrf)}`);
                        }

                        const response = await fetch(current.url, {
                            method: 'POST',
                            credentials: 'same-origin',
                            headers: ensureIdempotencyBodyAndHeaders(bodyStr, current.idempotencyKey),
                            body: bodyStr
                        });

                        if (response.ok) {
                            const html = await response.text();
                            const remaining = getQueue().filter((q) => q.id !== current.id);
                            inFlightActionId = null;
                            inFlightItemId = null;
                            saveQueue(remaining);
                            consecutiveFailures = 0;
                            processedCount += 1;
                            if (html && html.includes('id="shopping-list-content"')) {
                                lastShoppingHtml = html;
                            }
                            const hasMoreWork = remaining.length > 0 || pendingHolds.size > 0;
                            applyOutboxResponse(current, response, html, { hasMoreWork });
                        } else if (response.status >= 500 || response.status === 408 || response.status === 429) {
                            haltedByNetworkOrServer = true;
                            break;
                        } else {
                            // Non-retryable 4xx (e.g. deleted upstream, validation error, forbidden)
                            const errHtml = await response.text().catch(() => '');
                            const remaining = getQueue().filter((q) => q.id !== current.id);
                            inFlightActionId = null;
                            inFlightItemId = null;
                            saveQueue(remaining);
                            const cbs = liveCallbackRegistry.get(current.id);
                            liveCallbackRegistry.delete(current.id);
                            if (cbs && typeof cbs.onError === 'function') {
                                try { cbs.onError(response, errHtml); } catch (_) {}
                            }
                            if (response.status === 403 && window.showToast) {
                                window.showToast('You do not have permission for that change.', { type: 'error' });
                            }
                        }
                    } catch (_) {
                        haltedByNetworkOrServer = true;
                        break;
                    }
                }
            } finally {
                inFlightActionId = null;
                inFlightItemId = null;
                isFlushing = false;
                const remainingAfter = getQueue();
                rebuildLockedRows(remainingAfter);
                updateSyncIndicators();

                const burstComplete = remainingAfter.length === 0 && pendingHolds.size === 0;
                if (burstComplete) {
                    burstProtectedRowIds.clear();
                }

                const shouldReconcileShopping = (
                    burstComplete
                    && lastShoppingHtml
                    && (processedCount > 1 || pendingReconcileTargets.has('#shopping-list-content'))
                );
                if (shouldReconcileShopping && window.ShoppinMorph && document.getElementById('shopping-list-content')) {
                    pendingReconcileTargets.delete('#shopping-list-content');
                    window.ShoppinMorph.swapFromHtml('#shopping-list-content', lastShoppingHtml);
                }

                if (hadItems && burstComplete) {
                    showTemporarySyncedBadge();
                } else if (haltedByNetworkOrServer && navigator.onLine && remainingAfter.length > 0) {
                    const step = BACKOFF_STEPS_MS[Math.min(consecutiveFailures, BACKOFF_STEPS_MS.length - 1)];
                    const jitter = Math.floor(Math.random() * 250);
                    consecutiveFailures += 1;
                    scheduleFlush(step + jitter);
                }
            }
        });
    }

    /**
     * Delayed Outbox Hold for single-row destructive removals:
     * Visually hides row at 0ms, shows Undo toast for 2.6s, and only sends POST if not undone.
     */
    function scheduleHoldDelete({ key, rowEl, itemId, url, form, targetSelector, label, onCommitRestoreCheck }) {
        // Cancel existing hold on same key if somehow double-triggered
        const body = serializeForm(form);
        if (!rowEl) {
            enqueue(url, body, { itemId, type: 'delete' });
            return;
        }

        const prevHeight = rowEl.offsetHeight;
        rowEl.style.transition = 'opacity 140ms ease-out, max-height 160ms ease-out, margin 160ms ease-out, padding 160ms ease-out';
        rowEl.style.maxHeight = `${prevHeight || 120}px`;
        rowEl.style.overflow = 'hidden';
        requestAnimationFrame(() => {
            rowEl.style.opacity = '0';
            rowEl.style.maxHeight = '0px';
            rowEl.style.paddingTop = '0px';
            rowEl.style.paddingBottom = '0px';
            rowEl.style.marginTop = '0px';
            rowEl.style.marginBottom = '0px';
            rowEl.style.borderWidth = '0px';
        });
        rowEl.dataset.pendingDelete = '1';

        const commitTimer = setTimeout(() => {
            pendingHolds.delete(key);
            rebuildLockedRows(getQueue());
            enqueue(url, body, { itemId, type: 'delete' }, {
                onSuccess: (_, html) => {
                    if (rowEl && rowEl.parentNode) rowEl.remove();
                    if (targetSelector && html && window.ShoppinMorph) {
                        window.ShoppinMorph.swapFromHtml(targetSelector, html);
                    }
                },
                onError: () => {
                    restoreRow();
                }
            });
        }, HOLD_DELAY_MS);

        function restoreRow() {
            rowEl.dataset.pendingDelete = '';
            rowEl.style.maxHeight = '';
            rowEl.style.overflow = '';
            rowEl.style.opacity = '1';
            rowEl.style.paddingTop = '';
            rowEl.style.paddingBottom = '';
            rowEl.style.marginTop = '';
            rowEl.style.marginBottom = '';
            rowEl.style.borderWidth = '';
            if (rowEl.animate) {
                rowEl.animate([{ backgroundColor: '#dbeafe' }, { backgroundColor: '' }], { duration: 350 });
            }
            if (onCommitRestoreCheck) onCommitRestoreCheck();
        }

        pendingHolds.set(key, { itemId, commitTimer, restoreRow });
        bumpEpoch();
        rebuildLockedRows(getQueue());
        updateSyncIndicators();

        if (window.showToast) {
            window.showToast(`Removed ${label}`, {
                type: 'info',
                duration: HOLD_DELAY_MS + 400,
                undoLabel: 'Undo',
                onUndo: () => {
                    const entry = pendingHolds.get(key);
                    if (!entry) return;
                    clearTimeout(entry.commitTimer);
                    pendingHolds.delete(key);
                    bumpEpoch();
                    rebuildLockedRows(getQueue());
                    updateSyncIndicators();
                    entry.restoreRow();
                    window.showToast(`Restored ${label}`, { type: 'success', duration: 2200 });
                }
            });
        }
    }

    // -------------------------------------------------------------------------
    // Optimistic Handlers for Recipes, Meal Plans, & Presets
    // -------------------------------------------------------------------------

    function handleOptimisticRecipeRating(form, submitter) {
        const widget = form.closest('[id^="recipe-rating-widget-"]');
        if (!widget) return false;
        const starsVal = parseInt(form.querySelector('input[name="stars"]')?.value || '5', 10);
        const thumbsVal = form.querySelector('input[name="thumbs_up"]')?.value === 'true';
        const recipeMatch = widget.id.match(/recipe-rating-widget-(\d+)/);
        const recipeId = recipeMatch ? recipeMatch[1] : widget.id;

        // Instant visual update of stars & thumbs button inside widget
        widget.querySelectorAll('form[hx-post*="/rate/"] button').forEach((btn) => {
            const btnForm = btn.closest('form');
            const isThumbsForm = btnForm && btnForm.querySelector('input[name="thumbs_up"]') && btnForm.querySelector('span[aria-hidden="true"]')?.textContent.includes('👍');
            if (isThumbsForm) {
                const countSpan = btn.querySelector('span:last-child');
                const wasEndorsed = btn.className.includes('bg-amber-100');
                if (thumbsVal && !wasEndorsed) {
                    btn.className = 'inline-flex items-center space-x-1 px-2 py-0.5 border text-xs font-semibold bg-amber-100 border-amber-300 text-amber-900';
                    if (countSpan) countSpan.textContent = String(Math.max(0, (parseInt(countSpan.textContent, 10) || 0) + 1));
                } else if (!thumbsVal && wasEndorsed) {
                    btn.className = 'inline-flex items-center space-x-1 px-2 py-0.5 border text-xs font-semibold bg-white border-gray-300 text-gray-700 hover:bg-gray-100';
                    if (countSpan) countSpan.textContent = String(Math.max(0, (parseInt(countSpan.textContent, 10) || 1) - 1));
                }
                const nextToggleInput = btnForm.querySelector('input[name="thumbs_up"]');
                if (nextToggleInput) nextToggleInput.value = thumbsVal ? 'false' : 'true';
                return;
            }
            const sInput = btnForm?.querySelector('input[name="stars"]');
            if (sInput) {
                const idx = parseInt(sInput.value, 10);
                const starIcon = btn.querySelector('span[aria-hidden="true"]');
                if (starIcon) {
                    if (idx <= starsVal) {
                        starIcon.className = 'text-amber-500 font-bold';
                    } else {
                        starIcon.className = 'text-gray-300 hover:text-amber-400';
                    }
                }
            }
        });

        if (submitter && submitter.animate) {
            submitter.animate([{ transform: 'scale(1.3)' }, { transform: 'scale(1)' }], { duration: 180 });
        }

        const actionUrl = form.getAttribute('hx-post') || form.getAttribute('action');
        const body = serializeForm(form);
        enqueue(actionUrl, body, { type: 'rate', coalesceKey: `rate:recipe:${recipeId}` }, {
            onSuccess: (_, html) => {
                if (html && window.ShoppinMorph) {
                    window.ShoppinMorph.swapFromHtml(`#${widget.id}`, html);
                }
            }
        });
        return true;
    }

    function handleOptimisticPresetToggle(form) {
        const row = form.closest('[id^="preset-item-"]');
        const checkbox = form.querySelector('input[type="checkbox"]');
        if (!row || !checkbox) return false;

        const isActive = checkbox.checked;
        row.classList.toggle('bg-gray-50/70', !isActive);
        const labelText = form.querySelector('span');
        if (labelText) {
            labelText.textContent = isActive ? 'Active' : 'Inactive';
            labelText.className = `ml-2 text-xs font-semibold select-none ${isActive ? 'text-indigo-700' : 'text-gray-500'} hidden sm:inline`;
        }
        const nameEl = row.querySelector('span.font-semibold.text-sm');
        if (nameEl) {
            nameEl.className = `font-semibold text-sm ${isActive ? 'text-gray-900' : 'text-gray-600'}`;
        }

        const actionUrl = form.getAttribute('hx-post') || form.getAttribute('action');
        enqueue(actionUrl, serializeForm(form), {
            type: 'preset_toggle',
            coalesceKey: `preset_toggle:${row.id}`
        }, {
            onSuccess: (_, html) => {
                if (html && window.ShoppinMorph && document.getElementById('preset-items-container')) {
                    window.ShoppinMorph.swapFromHtml('#preset-items-container', html);
                }
            }
        });
        return true;
    }

    function handleOptimisticRuleToggle(form) {
        const row = form.closest('.border');
        const btn = form.querySelector('button[type="submit"]');
        if (!row || !btn) return false;
        const wasActive = btn.textContent.trim().toLowerCase() === 'pause';
        const nextActive = !wasActive;
        btn.textContent = nextActive ? 'Pause' : 'Enable';
        row.className = `flex items-center justify-between p-2 border ${nextActive ? 'border-emerald-200 bg-emerald-50/40' : 'border-gray-200 bg-gray-50 text-gray-700'}`;
        const textSpan = row.querySelector('span:nth-child(2)');
        if (textSpan) {
            textSpan.className = nextActive ? 'font-medium text-gray-900' : 'line-through text-gray-500';
        }
        const statusBadge = row.querySelector('span:nth-child(3)');
        if (statusBadge) {
            statusBadge.textContent = nextActive ? 'Active' : 'Paused';
            statusBadge.className = nextActive
                ? 'text-[10px] bg-emerald-100 text-emerald-800 border border-emerald-300 px-1.5 py-0.2 font-semibold'
                : 'text-[10px] bg-gray-200 text-gray-600 border border-gray-300 px-1.5 py-0.2 font-semibold';
        }

        const actionUrl = form.getAttribute('hx-post') || form.getAttribute('action');
        enqueue(actionUrl, serializeForm(form), {
            type: 'rule_toggle',
            coalesceKey: `rule:${actionUrl}`
        });
        return true;
    }

    function isDuplicateMicroTap(key, windowMs = 60) {
        const now = Date.now();
        const prev = recentClickStamps.get(key) || 0;
        if (now - prev < windowMs) return true;
        recentClickStamps.set(key, now);
        return false;
    }

    function interceptExtendedActions(event) {
        const target = event.target && event.target.nodeType === 3 ? event.target.parentElement : event.target;
        if (!target || typeof target.closest !== 'function') return;

        // 1. Recipe star & thumbs-up widget
        const rateForm = target.closest('form[hx-post*="/rate/"]');
        if (rateForm && (event.type === 'submit' || target.closest('button[type="submit"]'))) {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            const submitBtn = target.closest('button[type="submit"]');
            if (isDuplicateMicroTap(`rate:${rateForm.getAttribute('hx-post')}:${submitBtn?.textContent}`, 50)) return;
            window.ShoppinHaptics?.tap?.(8);
            handleOptimisticRecipeRating(rateForm, submitBtn);
            return;
        }

        // 2. Preset active/inactive slider
        const presetToggleForm = target.closest('form[hx-post*="/toggle-active/"]');
        if (presetToggleForm && event.type === 'submit') {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            window.ShoppinHaptics?.tap?.(8);
            handleOptimisticPresetToggle(presetToggleForm);
            return;
        }

        // 3. Meal plan rule toggle
        const ruleToggleForm = target.closest('form[hx-post*="/rules/"][hx-post*="/toggle/"]');
        if (ruleToggleForm && (event.type === 'submit' || target.closest('button[type="submit"]'))) {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            if (isDuplicateMicroTap(`rule:${ruleToggleForm.getAttribute('hx-post')}`, 60)) return;
            handleOptimisticRuleToggle(ruleToggleForm);
            return;
        }

        // 3b. Meal plan scale submit (pressing Enter inside number field)
        const scaleForm = target.closest('form[hx-post*="/scale/"]');
        if (scaleForm && event.type === 'submit') {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            const scaleInput = scaleForm.querySelector('input[name="scale_factor"]');
            if (scaleInput) {
                handleScaleInputChange({ target: scaleInput, stopPropagation: () => {}, stopImmediatePropagation: () => {} });
            }
            return;
        }

        // 4. Meal plan dish / rule / preset item / archive card single-row delete (Hold-to-Undo)
        const holdDeleteForm = target.closest(
            'form[hx-post*="/dish/"][hx-post*="/delete/"], ' +
            'form[hx-post*="/rules/"][hx-post*="/delete/"], ' +
            'form[hx-post*="/items/"][hx-post*="/delete/"], ' +
            'form[hx-post*="/item/"][hx-post*="/delete/"], ' +
            'form[hx-post*="/archive/"][hx-post*="/delete/"]'
        );
        if (holdDeleteForm && (event.type === 'submit' || target.closest('button[type="submit"]'))) {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            const actionUrl = holdDeleteForm.getAttribute('hx-post') || holdDeleteForm.getAttribute('action');
            if (isDuplicateMicroTap(`del:${actionUrl}`, 120)) return;
            const row = holdDeleteForm.closest('[id^="preset-item-"], .archived-meal-card, .item-row, .border');
            const idMatch = actionUrl.match(/\/(?:item|items|dish|rules|archive)\/(\d+)\//);
            const itemName = row?.getAttribute('data-item-name') || row?.querySelector('h3, button, .font-semibold, .font-medium')?.textContent?.trim() || 'item';
            scheduleHoldDelete({
                key: `hold:${actionUrl}`,
                rowEl: row,
                itemId: idMatch ? idMatch[1] : null,
                url: actionUrl,
                form: holdDeleteForm,
                targetSelector: holdDeleteForm.getAttribute('hx-target'),
                label: `'${itemName}'`
            });
            return;
        }
    }

    // 5. Meal plan Dish Scale debounce + coalesce (preserves input focus smoothly!)
    function handleScaleInputChange(event) {
        const input = event.target;
        if (!input || !input.closest) return;
        const form = input.closest('form[hx-post*="/scale/"]');
        if (!form) return;

        event.stopPropagation();
        event.stopImmediatePropagation();

        const actionUrl = form.getAttribute('hx-post') || form.getAttribute('action');
        const box = input.closest('div');
        const val = parseFloat(input.value);
        if (box) {
            if (!isNaN(val) && val !== 1) {
                box.classList.add('border-amber-400', 'bg-amber-50', 'text-amber-900');
                box.classList.remove('border-gray-300', 'border-teal-300', 'bg-white');
            } else {
                box.classList.remove('border-amber-400', 'bg-amber-50', 'text-amber-900');
                box.classList.add('border-gray-300', 'bg-white');
            }
        }

        if (scaleDebounceTimers.has(actionUrl)) {
            clearTimeout(scaleDebounceTimers.get(actionUrl));
        }
        const t = setTimeout(() => {
            scaleDebounceTimers.delete(actionUrl);
            enqueue(actionUrl, serializeForm(form), {
                type: 'scale_dish',
                coalesceKey: `scale:${actionUrl}`
            });
        }, 280);
        scaleDebounceTimers.set(actionUrl, t);
    }

    document.addEventListener('click', interceptExtendedActions, true);
    document.addEventListener('submit', interceptExtendedActions, true);
    document.addEventListener('change', handleScaleInputChange, true);

    window.addEventListener('online', () => {
        consecutiveFailures = 0;
        updateSyncIndicators();
        scheduleFlush(0);
    });
    window.addEventListener('offline', () => {
        updateSyncIndicators();
    });
    window.addEventListener('focus', () => {
        updateSyncIndicators();
        scheduleFlush(0);
    });
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) scheduleFlush(0);
    });

    // Expose API & initialize
    rebuildLockedRows(getQueue());
    document.addEventListener('DOMContentLoaded', () => {
        updateSyncIndicators();
        scheduleFlush(0);
    });

    window.ShoppinQueue = {
        getQueue,
        saveQueue,
        enqueue,
        flushQueue,
        updateSyncIndicators,
        isRowLocked,
        getMutationEpoch,
        hasPendingWork,
        scheduleHoldDelete,
        serializeForm,
        getCsrfToken,
        generateKey,
        tempIdMap,
        isDuplicateMicroTap
    };
})();
