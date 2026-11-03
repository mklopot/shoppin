/**
 * Shoppin Optimistic UI & Offline Background Resync Engine
 *
 * Provides instantaneous (0ms) local DOM state transitions for shopping list
 * item actions (Got, Need, Have, Skip, Lock/Reset) with persistent queueing
 * in localStorage and automated background synchronization with the server.
 */

(function () {
    'use strict';

    const QUEUE_STORAGE_KEY = 'shoppin_offline_actions_v1';
    const BADGE_BASE = 'w-[110px] h-[22px] min-w-[110px] max-w-[110px] min-h-[22px] max-h-[22px] inline-flex items-center justify-center text-center text-[11px] font-semibold px-1.5 py-0.5 border rounded-none select-none transition-opacity duration-200 whitespace-nowrap overflow-hidden flex-shrink-0';
    let isFlushing = false;
    let syncIndicatorTimer = null;

    function getCsrfToken() {
        const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (input && input.value) return input.value;
        const match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }

    function getQueue() {
        try {
            const raw = localStorage.getItem(QUEUE_STORAGE_KEY);
            return raw ? JSON.parse(raw) : [];
        } catch (_) {
            return [];
        }
    }

    function saveQueue(queue) {
        try {
            localStorage.setItem(QUEUE_STORAGE_KEY, JSON.stringify(queue));
        } catch (_) {}
        updateSyncIndicator();
    }

    function updateSyncIndicator() {
        const indicator = document.getElementById('offline-sync-indicator');
        if (!indicator) return;

        const queue = getQueue();
        const isOnline = navigator.onLine;

        if (syncIndicatorTimer) {
            clearTimeout(syncIndicatorTimer);
            syncIndicatorTimer = null;
        }

        if (queue.length > 0) {
            if (!isOnline) {
                indicator.textContent = queue.length > 1 ? `⚡ Offline (${queue.length})` : '⚡ Offline';
                indicator.className = `${BADGE_BASE} opacity-100 border-amber-400 bg-amber-50 text-amber-900`;
                indicator.setAttribute('title', `${queue.length} change(s) saved on your phone. Will sync when back online.`);
            } else {
                indicator.textContent = queue.length > 1 ? `🔄 Sync (${queue.length})` : '🔄 Syncing';
                indicator.className = `${BADGE_BASE} opacity-100 border-blue-400 bg-blue-50 text-blue-900`;
                indicator.setAttribute('title', 'Syncing changes with server in background.');
            }
        } else {
            if (!isOnline) {
                indicator.textContent = '⚡ Offline';
                indicator.className = `${BADGE_BASE} opacity-100 border-amber-300 bg-amber-50 text-amber-800`;
                indicator.setAttribute('title', 'Working offline. You can continue checking items off.');
            } else {
                indicator.className = `${BADGE_BASE} opacity-0 pointer-events-none border-transparent bg-transparent`;
            }
        }
    }

    function showTemporarySyncedBadge() {
        const indicator = document.getElementById('offline-sync-indicator');
        if (!indicator) return;
        indicator.textContent = '✓ Saved';
        indicator.className = `${BADGE_BASE} opacity-100 border-emerald-400 bg-emerald-50 text-emerald-900`;
        if (syncIndicatorTimer) clearTimeout(syncIndicatorTimer);
        syncIndicatorTimer = setTimeout(() => {
            updateSyncIndicator();
        }, 1800);
    }

    function triggerToast(message) {
        if (!message) return;
        if (typeof window.showToast === 'function') {
            window.showToast(message);
        } else {
            const container = document.getElementById('toast-container');
            if (!container) return;
            const toast = document.createElement('div');
            toast.className = 'toast-item pointer-events-auto flex items-center justify-between bg-white/95 backdrop-blur-sm text-gray-900 text-xs px-3.5 py-2.5 shadow-lg border border-gray-300 min-w-[260px] max-w-sm rounded-none cursor-pointer';
            toast.innerHTML = `<span class="font-medium pr-2">${message}</span><button type="button" class="text-gray-500 hover:text-gray-800 font-bold text-base ml-2 leading-none focus:outline-none">&times;</button>`;
            toast.onclick = function() { toast.remove(); };
            container.appendChild(toast);
            setTimeout(() => { toast.remove(); }, 3500);
        }
    }

    // -------------------------------------------------------------------------
    // Local DOM Optimistic Mutations (0ms Immediate Response)
    // -------------------------------------------------------------------------

    function adjustCount(elementId, delta) {
        const el = document.getElementById(elementId);
        if (!el) return;
        const match = el.textContent.match(/\d+/);
        if (match) {
            const current = parseInt(match[0], 10);
            const updated = Math.max(0, current + delta);
            el.textContent = `(${updated})`;
        }
    }

    function animateRow(row, glowColor) {
        if (!row || !row.animate) return;
        row.animate([
            { transform: 'scale(1.015)', backgroundColor: glowColor },
            { transform: 'scale(1)', backgroundColor: '' }
        ], {
            duration: 220,
            easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)'
        });
    }

    function handleLocalGot(itemId, row) {
        const gotList = document.getElementById('got-items-list');
        const gotContainer = document.getElementById('got-section-container');
        if (!gotList || !gotContainer) return;

        // 1. Move DOM element to Got section
        gotContainer.classList.remove('hidden');
        gotList.prepend(row);

        // 2. Adjust counter numbers
        adjustCount('need-items-count', -1);
        adjustCount('got-items-count', 1);

        // 3. Update styling and attributes
        row.setAttribute('data-item-status', 'GOT');
        row.className = 'item-row py-1.5 px-3 flex items-center justify-between hover:bg-emerald-100/50 text-xs transition-colors';

        // 4. Update left icon: from drag handle to green checkmark
        const leftWrap = row.querySelector('.flex.items-center.space-x-2');
        if (leftWrap) {
            const dragHandle = leftWrap.querySelector('.drag-handle, .status-icon');
            if (dragHandle) {
                dragHandle.outerHTML = '<span class="status-icon text-emerald-700 font-bold select-none text-sm" aria-hidden="true">✓</span>';
            }
        }

        // 5. Update actions: replace Got/Skip with Need button
        const actionsWrap = row.querySelector('.item-actions');
        if (actionsWrap) {
            const groupBy = document.getElementById('section-groups-container')?.getAttribute('data-group-by') || 'category';
            const mode = document.querySelector('input[name="mode"]')?.value || 'shopping';
            const csrf = getCsrfToken();
            const itemName = row.getAttribute('data-item-name') || 'item';

            actionsWrap.innerHTML = `
                <form method="POST" action="/item/${itemId}/status/NEED/?group_by=${groupBy}&mode=${mode}" class="inline">
                    <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                    <button type="submit" aria-label="Put ${itemName} back to To Buy" title="Put back to To Buy" class="border border-emerald-300 hover:border-emerald-500 bg-white hover:bg-emerald-50 px-2 py-0.5 text-xs text-gray-800 font-medium rounded-none">
                        📋 Need
                    </button>
                </form>
                <button hx-get="/item/${itemId}/edit/?group_by=${groupBy}" hx-target="#modal-placeholder" class="text-gray-500 hover:text-gray-900 px-1 py-0.5" aria-label="Edit item ${itemName}" title="Edit">
                    <span aria-hidden="true">✏️</span>
                </button>
            `;
        }

        // 6. Tactile celebration animation & instant toast
        animateRow(row, '#d1fae5');
        const itemName = row.getAttribute('data-item-name') || 'item';
        triggerToast(`🛒 You got '${itemName}'`);
    }

    function handleLocalNeed(itemId, row) {
        const sectionsContainer = document.getElementById('section-groups-container');
        if (!sectionsContainer) return;

        const previousStatus = row.getAttribute('data-item-status') || 'GOT';

        // 1. Move row to To Buy section
        let targetGroup = sectionsContainer.querySelector('.sortable-group');
        if (targetGroup) {
            targetGroup.prepend(row);
        } else {
            sectionsContainer.prepend(row);
        }

        // 2. Adjust counters
        adjustCount('need-items-count', 1);
        if (previousStatus === 'GOT') {
            adjustCount('got-items-count', -1);
            const gotList = document.getElementById('got-items-list');
            if (gotList && gotList.children.length === 0) {
                document.getElementById('got-section-container')?.classList.add('hidden');
            }
        } else {
            adjustCount('pantry-items-count', -1);
            const pantryList = document.getElementById('pantry-items-list');
            if (pantryList && pantryList.children.length === 0) {
                document.getElementById('pantry-section-container')?.classList.add('hidden');
            }
        }

        // 3. Update styling and attributes
        row.setAttribute('data-item-status', 'NEED');
        row.className = 'item-row py-1.5 px-3 flex items-center justify-between hover:bg-gray-50 text-xs transition-colors';

        // 4. Update left icon: back to drag handle
        const leftWrap = row.querySelector('.flex.items-center.space-x-2');
        if (leftWrap) {
            const icon = leftWrap.querySelector('.status-icon, .drag-handle');
            if (icon) {
                icon.outerHTML = '<span class="drag-handle cursor-grab active:cursor-grabbing text-gray-400 hover:text-gray-600 select-none text-sm font-mono" aria-hidden="true">⋮⋮</span>';
            }
        }

        // 5. Update actions: replace Need with Got and Skip buttons
        const actionsWrap = row.querySelector('.item-actions');
        if (actionsWrap) {
            const groupBy = sectionsContainer.getAttribute('data-group-by') || 'category';
            const mode = document.querySelector('input[name="mode"]')?.value || 'shopping';
            const csrf = getCsrfToken();
            const itemName = row.getAttribute('data-item-name') || 'item';

            actionsWrap.innerHTML = `
                <form method="POST" action="/item/${itemId}/status/GOT/?group_by=${groupBy}&mode=${mode}" class="inline">
                    <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                    <button type="submit" aria-label="Mark ${itemName} as got in cart" title="Got it (Put in Cart)" class="border border-gray-300 hover:border-gray-500 bg-white hover:bg-gray-100 px-2 py-0.5 text-xs text-gray-800 font-medium rounded-none">
                        🛒 Got
                    </button>
                </form>
                <form method="POST" action="/item/${itemId}/status/DONT_NEED/?group_by=${groupBy}&mode=${mode}" class="inline">
                    <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                    <button type="submit" aria-label="Skip ${itemName} for this trip" title="Don't need this trip" class="border border-gray-300 hover:border-gray-500 bg-white hover:bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600 hover:text-gray-900 rounded-none">
                        ⏭ Skip
                    </button>
                </form>
                <button hx-get="/item/${itemId}/edit/?group_by=${groupBy}" hx-target="#modal-placeholder" class="text-gray-500 hover:text-gray-900 px-1 py-0.5" aria-label="Edit item ${itemName}" title="Edit">
                    <span aria-hidden="true">✏️</span>
                </button>
            `;
        }

        animateRow(row, '#dbeafe');
        const itemName = row.getAttribute('data-item-name') || 'item';
        triggerToast(`📋 You moved '${itemName}' back to To Buy`);
    }

    function handleLocalHaveOrSkip(itemId, row, targetStatus) {
        const pantryList = document.getElementById('pantry-items-list');
        const pantryContainer = document.getElementById('pantry-section-container');
        if (!pantryList || !pantryContainer) return;

        // 1. Move row to pantry list
        pantryContainer.classList.remove('hidden');
        pantryList.prepend(row);

        // 2. Adjust counters
        adjustCount('need-items-count', -1);
        adjustCount('pantry-items-count', 1);

        // 3. Update styling
        row.setAttribute('data-item-status', targetStatus);
        row.className = 'item-row py-1.5 px-3 flex items-center justify-between hover:bg-blue-100/50 text-xs transition-colors';

        // 4. Update left icon
        const iconSymbol = targetStatus === 'HAVE' ? '🏠' : '⏭';
        const iconTitle = targetStatus === 'HAVE' ? 'Already have at home' : 'Skipped';
        const leftWrap = row.querySelector('.flex.items-center.space-x-2');
        if (leftWrap) {
            const handleOrIcon = leftWrap.querySelector('.drag-handle, .status-icon');
            if (handleOrIcon) {
                handleOrIcon.outerHTML = `<span class="status-icon ${targetStatus === 'HAVE' ? 'text-blue-800' : 'text-gray-600'} font-bold select-none text-sm" title="${iconTitle}" aria-label="${iconTitle}">${iconSymbol}</span>`;
            }
        }

        // 5. Update right actions: Need button
        const actionsWrap = row.querySelector('.item-actions');
        if (actionsWrap) {
            const groupBy = document.getElementById('section-groups-container')?.getAttribute('data-group-by') || 'category';
            const mode = document.querySelector('input[name="mode"]')?.value || 'pantry';
            const csrf = getCsrfToken();
            const itemName = row.getAttribute('data-item-name') || 'item';

            actionsWrap.innerHTML = `
                <form method="POST" action="/item/${itemId}/status/NEED/?group_by=${groupBy}&mode=${mode}" class="inline">
                    <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                    <button type="submit" aria-label="Move ${itemName} back to To Buy" title="Move back to To Buy" class="border border-blue-300 hover:border-blue-500 bg-white hover:bg-blue-50 px-2 py-0.5 text-xs text-gray-800 font-medium rounded-none">
                        📋 Need
                    </button>
                </form>
                <button hx-get="/item/${itemId}/edit/?group_by=${groupBy}" hx-target="#modal-placeholder" class="text-gray-500 hover:text-gray-900 px-1 py-0.5" aria-label="Edit item ${itemName}" title="Edit">
                    <span aria-hidden="true">✏️</span>
                </button>
            `;
        }

        animateRow(row, '#e0f2fe');
        const itemName = row.getAttribute('data-item-name') || 'item';
        if (targetStatus === 'HAVE') {
            triggerToast(`🏠 You marked '${itemName}' as Already in Pantry`);
        } else {
            triggerToast(`⏭ You skipped '${itemName}'`);
        }
    }

    function handleLocalLockToggle(itemId, row, button) {
        const isLocked = row.getAttribute('data-locked') === 'true';
        const titleEl = row.querySelector('.item-title');
        const itemName = row.getAttribute('data-item-name') || 'item';

        if (!isLocked) {
            // UNLOCKED -> LOCKED ("Need" was pressed, now changes to "Reset")
            row.setAttribute('data-locked', 'true');
            row.classList.add('bg-blue-50/40');

            // Insert 📋 Need tag next to item title if not already present
            if (titleEl && !row.querySelector('.item-need-tag')) {
                const tag = document.createElement('span');
                tag.className = 'item-need-tag ml-1.5 px-1 py-0.2 text-[10px] font-bold uppercase tracking-wider bg-blue-100 text-blue-800 border border-blue-300 select-none';
                tag.textContent = '📋 Need';
                titleEl.after(tag);
            }

            // Button flips from "Need" to "↺ Reset"
            if (button) {
                button.innerHTML = '↺ Reset';
                button.className = 'border border-gray-400 bg-gray-100 hover:bg-gray-200 px-2 py-0.5 text-xs text-gray-800 font-semibold rounded-none';
                button.setAttribute('title', 'Confirmed need (click to reset)');
                button.setAttribute('aria-label', `Reset confirmed need for ${itemName}`);
            }

            // In pantry mode, hide the "Have" button on this row since it's confirmed needed
            const haveForm = row.querySelector('form[action*="/status/HAVE"]');
            if (haveForm) {
                haveForm.classList.add('hidden');
            }

            animateRow(row, '#dbeafe');
            triggerToast(`📋 You set '${itemName}' to "needed"`);
        } else {
            // LOCKED -> UNLOCKED ("Reset" was pressed, flips back to "Need")
            row.setAttribute('data-locked', 'false');
            row.classList.remove('bg-blue-50/40');

            // Remove 📋 Need tag
            const tag = row.querySelector('.item-need-tag');
            if (tag) {
                tag.remove();
            }

            // Button flips back to "📋 Need"
            if (button) {
                button.innerHTML = '📋 Need';
                button.className = 'border border-gray-300 hover:border-gray-500 bg-white hover:bg-gray-100 px-2 py-0.5 text-xs text-gray-700 font-medium rounded-none';
                button.setAttribute('title', 'Check item: confirm we need to buy this');
                button.setAttribute('aria-label', `Confirm need to buy ${itemName}`);
            }

            // Restore the "Have" button if in pantry mode
            const haveForm = row.querySelector('form[action*="/status/HAVE"]');
            if (haveForm) {
                haveForm.classList.remove('hidden');
            }

            animateRow(row, '#f3f4f6');
            triggerToast(`You unchecked '${itemName}'`);
        }
    }

    // -------------------------------------------------------------------------
    // Persistent Offline Queue & Background Sync Worker
    // -------------------------------------------------------------------------

    function enqueueAction(url, body, meta) {
        const queue = getQueue();
        const actionItem = {
            id: 'act_' + Date.now() + '_' + Math.random().toString(36).substring(2, 7),
            url: url,
            body: body,
            meta: meta || {},
            timestamp: Date.now()
        };
        queue.push(actionItem);
        saveQueue(queue);
        flushQueue();
    }

    async function flushQueue() {
        if (isFlushing) return;
        if (!navigator.onLine) {
            updateSyncIndicator();
            return;
        }

        const queue = getQueue();
        if (queue.length === 0) {
            updateSyncIndicator();
            return;
        }

        isFlushing = true;
        updateSyncIndicator();

        let hadQueue = queue.length > 0;

        try {
            while (queue.length > 0) {
                if (!navigator.onLine) {
                    break;
                }

                const currentAction = queue[0];
                try {
                    const response = await fetch(currentAction.url, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded',
                            'X-Client-Id': window.CLIENT_ID || 'client_web'
                        },
                        body: currentAction.body
                    });

                    if (response.ok) {
                        // Succeeded: remove from queue and persist
                        queue.shift();
                        saveQueue(queue);
                    } else if (response.status >= 500 || response.status === 408) {
                        // Server error / timeout: halt queue and retry on next tick
                        break;
                    } else {
                        // Client error (4xx): discard invalid action to prevent infinite loop
                        queue.shift();
                        saveQueue(queue);
                    }
                } catch (networkErr) {
                    // Offline or network dropped mid-flight
                    break;
                }
            }
        } finally {
            isFlushing = false;
            updateSyncIndicator();

            if (hadQueue && getQueue().length === 0) {
                showTemporarySyncedBadge();
            }
        }
    }

    // -------------------------------------------------------------------------
    // Event Delegation Interceptor
    // -------------------------------------------------------------------------

    function interceptAction(event) {
        let target = event.target;
        if (!target) return;
        if (target.nodeType === 3) {
            target = target.parentElement;
        }
        if (!target || typeof target.closest !== 'function') return;

        // Check if click was inside an action button or form in the shopping list
        const button = target.closest('button[type="submit"], button');
        const form = target.closest('form');
        const row = target.closest('.item-row');
        if (!row || !form) return;

        const actionUrl = form.getAttribute('action') || form.getAttribute('hx-post') || '';
        if (!actionUrl) return;

        // Pattern matches:
        // /item/<id>/status/<STATUS>/
        // /item/<id>/lock/
        const statusMatch = actionUrl.match(/\/item\/(\d+)\/status\/(GOT|NEED|HAVE|DONT_NEED)/);
        const lockMatch = actionUrl.match(/\/item\/(\d+)\/lock\//);

        if (!statusMatch && !lockMatch) {
            return; // Not a status transition or lock toggle, let normal HTMX flow handle it
        }

        // Stop HTMX from duplicating or doing full DOM swaps that overwrite optimistic clicks
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        const formData = new FormData(form);
        if (!formData.has('csrfmiddlewaretoken')) {
            formData.append('csrfmiddlewaretoken', getCsrfToken());
        }
        const bodyParams = new URLSearchParams(formData).toString();

        if (statusMatch) {
            const itemId = statusMatch[1];
            const targetStatus = statusMatch[2];

            if (targetStatus === 'GOT') {
                handleLocalGot(itemId, row);
            } else if (targetStatus === 'NEED') {
                handleLocalNeed(itemId, row);
            } else if (targetStatus === 'HAVE' || targetStatus === 'DONT_NEED') {
                handleLocalHaveOrSkip(itemId, row, targetStatus);
            }

            enqueueAction(actionUrl, bodyParams, { itemId, targetStatus, type: 'status' });
        } else if (lockMatch) {
            const itemId = lockMatch[1];
            handleLocalLockToggle(itemId, row, button);
            enqueueAction(actionUrl, bodyParams, { itemId, type: 'lock' });
        }
    }

    function initShoppingSync() {
        updateSyncIndicator();
        flushQueue();
    }

    // Capture event early before HTMX attaches its listeners (both document and bubbling)
    document.addEventListener('click', interceptAction, true);
    document.addEventListener('submit', interceptAction, true);

    // Global lifecycle triggers
    window.addEventListener('online', () => {
        updateSyncIndicator();
        flushQueue();
    });

    window.addEventListener('offline', () => {
        updateSyncIndicator();
    });

    window.addEventListener('focus', () => {
        flushQueue();
    });

    // Periodic heartbeat to flush queue if back online
    setInterval(flushQueue, 6000);

    document.addEventListener('DOMContentLoaded', initShoppingSync);
    document.addEventListener('htmx:afterSwap', function (evt) {
        if (evt.detail.target.id === 'shopping-list-content') {
            initShoppingSync();
        }
    });

    // Expose API for external diagnostics if needed
    window.ShoppinSync = {
        getQueue,
        flushQueue,
        updateSyncIndicator
    };
})();
