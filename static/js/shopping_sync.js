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
            toast.innerHTML = `<span class="font-medium pr-2">${message}</span><button type="button" class="text-gray-500 hover:text-gray-800 font-bold text-base ml-2 leading-none focus:outline-none" aria-label="Dismiss notification">&times;</button>`;
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

    function checkAndUpdateSectionEmptyState(sectionBlock) {
        if (!sectionBlock) return;
        const remainingItems = sectionBlock.querySelectorAll('.item-row');
        if (remainingItems.length === 0) {
            sectionBlock.classList.add('hidden');
        } else {
            sectionBlock.classList.remove('hidden');
        }

        const sectionsContainer = document.getElementById('section-groups-container');
        const emptyPlaceholder = document.getElementById('to-buy-empty-placeholder');
        if (sectionsContainer && emptyPlaceholder) {
            const anyVisible = sectionsContainer.querySelector('.section-group-block:not(.hidden)');
            if (!anyVisible) {
                emptyPlaceholder.classList.remove('hidden');
            } else {
                emptyPlaceholder.classList.add('hidden');
            }
        }
    }

    function handleLocalGot(itemId, row) {
        const gotList = document.getElementById('got-items-list');
        const gotContainer = document.getElementById('got-section-container');
        if (!gotList || !gotContainer) return;

        const itemName = row.getAttribute('data-item-name') || 'item';

        // Remember original category/section block before moving
        const originalGroupBlock = row.closest('.section-group-block');
        if (originalGroupBlock) {
            const groupName = originalGroupBlock.getAttribute('data-group-name');
            if (groupName) row.setAttribute('data-group-name', groupName);
        }

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
            if (window.htmx) {
                htmx.process(actionsWrap);
            }
        }

        // Hide empty category header if last item in group was bought
        if (originalGroupBlock) {
            checkAndUpdateSectionEmptyState(originalGroupBlock);
        }

        // 6. Tactile celebration animation & instant toast
        animateRow(row, '#d1fae5');
        triggerToast(`🛒 You got '${itemName}'`);
    }

    function handleLocalNeed(itemId, row) {
        const sectionsContainer = document.getElementById('section-groups-container');
        if (!sectionsContainer) return;

        const previousStatus = row.getAttribute('data-item-status') || 'GOT';
        let groupName = row.getAttribute('data-group-name');
        if (!groupName || groupName === 'null') {
            groupName = 'Other';
        }

        // 1. Move row to To Buy section under its matching category block
        let targetBlock = sectionsContainer.querySelector(`.section-group-block[data-group-name="${CSS.escape(groupName)}"]`);
        if (!targetBlock) {
            targetBlock = document.createElement('div');
            targetBlock.className = 'section-group-block space-y-1.5';
            targetBlock.setAttribute('data-group-name', groupName);
            targetBlock.innerHTML = `
                <div class="bg-gray-100 hover:bg-gray-200/80 px-2.5 py-1 text-xs font-bold text-gray-800 uppercase tracking-wider flex items-center justify-between border-y border-gray-200 select-none group/header">
                    <div class="flex items-center space-x-1.5">
                        <span class="section-drag-handle cursor-grab active:cursor-grabbing text-gray-400 hover:text-gray-800 font-mono text-sm leading-none opacity-0 group-hover/header:opacity-100 transition-opacity focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900" role="button" tabindex="0" title="Drag section to reorder" aria-label="Reorder section: press Alt+Up or Alt+Down to move">⋮⋮</span>
                        <span>${groupName}</span>
                    </div>
                </div>
                <div class="sortable-group divide-y divide-gray-200 border-b border-gray-200 bg-white min-h-[10px]" data-group="${groupName}"></div>
            `;
            sectionsContainer.appendChild(targetBlock);
        }

        targetBlock.classList.remove('hidden');
        const targetGroup = targetBlock.querySelector('.sortable-group');
        if (targetGroup) {
            targetGroup.prepend(row);
        } else {
            targetBlock.appendChild(row);
        }

        const emptyPlaceholder = document.getElementById('to-buy-empty-placeholder');
        if (emptyPlaceholder) emptyPlaceholder.classList.add('hidden');

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

        const listContent = document.getElementById('shopping-list-content');
        const mode = listContent?.getAttribute('data-mode') || (window.location.search.includes('mode=pantry') ? 'pantry' : 'shopping');
        const groupBy = sectionsContainer.getAttribute('data-group-by') || 'category';
        const csrf = getCsrfToken();
        const itemName = row.getAttribute('data-item-name') || 'item';

        // 3. Update styling and attributes
        row.setAttribute('data-item-status', 'NEED');
        if (mode === 'pantry') {
            row.setAttribute('data-locked', 'true');
            row.className = 'item-row py-1.5 px-3 flex items-center justify-between hover:bg-gray-50 text-xs transition-colors bg-blue-50/40';

            // Insert 📋 Need tag next to item title if not already present
            const titleEl = row.querySelector('.item-title');
            if (titleEl && !row.querySelector('.item-need-tag')) {
                const tag = document.createElement('span');
                tag.className = 'item-need-tag ml-1.5 px-1 py-0.2 text-[10px] font-bold uppercase tracking-wider bg-blue-100 text-blue-800 border border-blue-300 select-none';
                tag.textContent = '📋 Need';
                titleEl.after(tag);
            }
        } else {
            row.className = 'item-row py-1.5 px-3 flex items-center justify-between hover:bg-gray-50 text-xs transition-colors';
        }

        // 4. Update left icon: back to drag handle
        const leftWrap = row.querySelector('.flex.items-center.space-x-2');
        if (leftWrap) {
            const icon = leftWrap.querySelector('.status-icon, .drag-handle');
            if (icon) {
                icon.outerHTML = '<span class="drag-handle cursor-grab active:cursor-grabbing text-gray-400 hover:text-gray-700 select-none text-sm font-mono focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900" role="button" tabindex="0" title="Drag to rearrange item" aria-label="Reorder item: press Alt+Up or Alt+Down to move">⋮⋮</span>';
            }
        }

        // 5. Update actions: in pantry mode show Reset, Have (hidden), Skip; in store mode show Got, Skip
        const actionsWrap = row.querySelector('.item-actions');
        if (actionsWrap) {
            if (mode === 'pantry') {
                actionsWrap.innerHTML = `
                    <form hx-post="/item/${itemId}/status/HAVE/?group_by=${groupBy}&mode=${mode}" hx-target="#shopping-list-content" hx-swap="outerHTML transition:true" class="have-status-form hidden">
                        <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                        <button type="submit" aria-label="Mark ${itemName} as have at home" title="Already have at home" class="border border-amber-400 bg-amber-50 hover:bg-amber-100 px-2 py-0.5 text-xs text-amber-900 font-semibold rounded-none">
                            🏠 Have
                        </button>
                    </form>
                    <form hx-post="/item/${itemId}/lock/?group_by=${groupBy}&mode=${mode}" hx-target="#shopping-list-content" hx-swap="outerHTML transition:true">
                        <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                        <button type="submit" aria-label="Reset confirmed need for ${itemName}" title="Confirmed need (click to reset)" class="border border-gray-400 bg-gray-100 hover:bg-gray-200 px-2 py-0.5 text-xs text-gray-800 font-semibold rounded-none">
                            ↺ Reset
                        </button>
                    </form>
                    <form hx-post="/item/${itemId}/status/DONT_NEED/?group_by=${groupBy}&mode=${mode}" hx-target="#shopping-list-content" hx-swap="outerHTML transition:true">
                        <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                        <button type="submit" aria-label="Skip ${itemName} for this trip" title="Don't need this trip" class="border border-gray-300 hover:border-gray-500 bg-white hover:bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600 hover:text-gray-900">
                            ⏭ Skip
                        </button>
                    </form>
                    <button hx-get="/item/${itemId}/edit/?group_by=${groupBy}" hx-target="#modal-placeholder" class="text-gray-500 hover:text-gray-900 px-1 py-0.5" aria-label="Edit item ${itemName}" title="Edit">
                        <span aria-hidden="true">✏️</span>
                    </button>
                `;
            } else {
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
            if (window.htmx) {
                htmx.process(actionsWrap);
            }
        }

        animateRow(row, '#dbeafe');
        triggerToast(`📋 You moved '${itemName}' back to To Buy`);
    }

    function handleLocalHaveOrSkip(itemId, row, targetStatus) {
        const pantryList = document.getElementById('pantry-items-list');
        const pantryContainer = document.getElementById('pantry-section-container');
        if (!pantryList || !pantryContainer) return;

        const itemName = row.getAttribute('data-item-name') || 'item';

        // Remember original category/section block before moving
        const originalGroupBlock = row.closest('.section-group-block');
        if (originalGroupBlock) {
            const groupName = originalGroupBlock.getAttribute('data-group-name');
            if (groupName) row.setAttribute('data-group-name', groupName);
        }

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
            if (window.htmx) {
                htmx.process(actionsWrap);
            }
        }

        // Hide empty category header if last item in group was skipped or marked in pantry
        if (originalGroupBlock) {
            checkAndUpdateSectionEmptyState(originalGroupBlock);
        }

        animateRow(row, '#e0f2fe');
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
        const lockBtn = button || row.querySelector('form[action*="/lock/"] button, form[hx-post*="/lock/"] button');

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
            if (lockBtn) {
                lockBtn.innerHTML = '↺ Reset';
                lockBtn.className = 'border border-gray-400 bg-gray-100 hover:bg-gray-200 px-2 py-0.5 text-xs text-gray-800 font-semibold rounded-none';
                lockBtn.setAttribute('title', 'Confirmed need (click to reset)');
                lockBtn.setAttribute('aria-label', `Reset confirmed need for ${itemName}`);
            }

            // In pantry mode, hide the "Have" button on this row since it's confirmed needed
            const haveForm = row.querySelector('form[action*="/status/HAVE"], form[hx-post*="/status/HAVE"]');
            if (haveForm) {
                haveForm.classList.add('hidden');
            }

            // In store mode, hide the "pantry check needed" button if present
            const checkTag = row.querySelector('button[title*="Pantry check needed"]');
            if (checkTag) {
                const checkForm = checkTag.closest('form');
                if (checkForm) checkForm.classList.add('hidden');
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
            if (lockBtn) {
                lockBtn.innerHTML = '📋 Need';
                lockBtn.className = 'border border-gray-300 hover:border-gray-500 bg-white hover:bg-gray-100 px-2 py-0.5 text-xs text-gray-700 font-medium rounded-none';
                lockBtn.setAttribute('title', 'Check item: confirm we need to buy this');
                lockBtn.setAttribute('aria-label', `Confirm need to buy ${itemName}`);
            }

            // Restore the "Have" button if in pantry mode
            let haveForm = row.querySelector('form[action*="/status/HAVE"], form[hx-post*="/status/HAVE"]');
            if (haveForm) {
                haveForm.classList.remove('hidden');
            } else {
                const lockForm = lockBtn?.closest('form') || row.querySelector('form[action*="/lock/"], form[hx-post*="/lock/"]');
                if (lockForm) {
                    const groupBy = document.getElementById('section-groups-container')?.getAttribute('data-group-by') || 'category';
                    const mode = document.querySelector('input[name="mode"]')?.value || 'pantry';
                    const csrf = getCsrfToken();
                    haveForm = document.createElement('form');
                    haveForm.setAttribute('hx-post', `/item/${itemId}/status/HAVE/?group_by=${groupBy}&mode=${mode}`);
                    haveForm.setAttribute('hx-target', '#shopping-list-content');
                    haveForm.setAttribute('hx-swap', 'outerHTML transition:true');
                    haveForm.className = 'have-status-form';
                    haveForm.innerHTML = `
                        <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                        <button type="submit" aria-label="Mark ${itemName} as have at home" title="Already have at home" class="border border-amber-400 bg-amber-50 hover:bg-amber-100 px-2 py-0.5 text-xs text-amber-900 font-semibold rounded-none">
                            🏠 Have
                        </button>
                    `;
                    lockForm.before(haveForm);
                }
            }

            // In store mode, restore the "pantry check needed" button if present
            const checkTag = row.querySelector('button[title*="Pantry check needed"]');
            if (checkTag) {
                const checkForm = checkTag.closest('form');
                if (checkForm) checkForm.classList.remove('hidden');
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
    // Quick Add Draft Preservation & In-Place Mode Switch Engine
    // -------------------------------------------------------------------------

    const QUICK_ADD_STORAGE_KEY = 'shoppin_quick_add_draft';
    let isSwitchingMode = false;

    function getQuickAddDraft() {
        const nameEl = document.getElementById('add-item-name');
        const amountEl = document.getElementById('add-item-amount');
        const brandEl = document.getElementById('add-item-brand');
        const vendorEl = document.getElementById('add-item-vendor');
        const purposeEl = document.getElementById('add-item-purpose');
        const priorityEl = nameEl?.form?.querySelector('input[name="priority"]');

        if (!nameEl) {
            try {
                const raw = sessionStorage.getItem(QUICK_ADD_STORAGE_KEY);
                return raw ? JSON.parse(raw) : null;
            } catch (_) {
                return null;
            }
        }

        const activeEl = document.activeElement;
        const isQuickAddActive = activeEl && (
            activeEl.id === 'add-item-name' ||
            activeEl.id === 'add-item-amount' ||
            activeEl.id === 'add-item-brand' ||
            activeEl.id === 'add-item-vendor' ||
            activeEl.id === 'add-item-purpose'
        );

        return {
            name: nameEl.value || '',
            amount: amountEl ? amountEl.value : '1',
            brand: brandEl ? brandEl.value : '',
            vendor: vendorEl ? vendorEl.value : '',
            purpose: purposeEl ? purposeEl.value : '',
            priority: priorityEl ? priorityEl.checked : false,
            focusedId: isQuickAddActive ? activeEl.id : null,
            selectionStart: isQuickAddActive && typeof activeEl.selectionStart === 'number' ? activeEl.selectionStart : null,
            selectionEnd: isQuickAddActive && typeof activeEl.selectionEnd === 'number' ? activeEl.selectionEnd : null
        };
    }

    function saveQuickAddDraft(draft) {
        if (!draft) draft = getQuickAddDraft();
        if (!draft) return;
        const hasContent = Boolean(
            draft.name ||
            draft.brand ||
            draft.vendor ||
            draft.purpose ||
            draft.priority ||
            (draft.amount && draft.amount !== '1')
        );
        try {
            if (hasContent) {
                sessionStorage.setItem(QUICK_ADD_STORAGE_KEY, JSON.stringify(draft));
            } else {
                sessionStorage.removeItem(QUICK_ADD_STORAGE_KEY);
            }
        } catch (_) {}
    }

    function clearQuickAddDraft() {
        try {
            sessionStorage.removeItem(QUICK_ADD_STORAGE_KEY);
        } catch (_) {}
    }

    function restoreQuickAddDraft(draft) {
        if (!draft) {
            try {
                const raw = sessionStorage.getItem(QUICK_ADD_STORAGE_KEY);
                if (raw) draft = JSON.parse(raw);
            } catch (_) {}
        }
        if (!draft) return;

        const nameEl = document.getElementById('add-item-name');
        const amountEl = document.getElementById('add-item-amount');
        const brandEl = document.getElementById('add-item-brand');
        const vendorEl = document.getElementById('add-item-vendor');
        const purposeEl = document.getElementById('add-item-purpose');
        const priorityEl = nameEl?.form?.querySelector('input[name="priority"]');

        if (nameEl && typeof draft.name === 'string') nameEl.value = draft.name;
        if (amountEl && typeof draft.amount === 'string' && draft.amount) amountEl.value = draft.amount;
        if (brandEl && typeof draft.brand === 'string') brandEl.value = draft.brand;
        if (vendorEl && typeof draft.vendor === 'string') vendorEl.value = draft.vendor;
        if (purposeEl && typeof draft.purpose === 'string') purposeEl.value = draft.purpose;
        if (priorityEl && typeof draft.priority === 'boolean') priorityEl.checked = draft.priority;

        if (draft.focusedId) {
            const elToFocus = document.getElementById(draft.focusedId);
            if (elToFocus) {
                elToFocus.focus();
                if (typeof draft.selectionStart === 'number' && typeof elToFocus.setSelectionRange === 'function') {
                    try {
                        elToFocus.setSelectionRange(draft.selectionStart, draft.selectionEnd);
                    } catch (_) {}
                }
            }
        }
    }

    function updateNavTabsStyling(targetMode) {
        const isPantry = targetMode === 'pantry';

        // Desktop Primary Navigation Tabs
        const dtShop = document.querySelector('nav[aria-label="Primary Navigation"] a[data-mode-switch="shopping"]');
        const dtPantry = document.querySelector('nav[aria-label="Primary Navigation"] a[data-mode-switch="pantry"]');

        const dtActive = 'inline-flex items-center px-2.5 text-xs font-semibold text-gray-900 border-b-2 border-gray-800 -mb-[1px]';
        const dtInactive = 'inline-flex items-center px-2.5 text-xs font-medium text-gray-600 hover:text-gray-900 border-b-2 border-transparent hover:border-gray-300 -mb-[1px]';

        if (dtShop) {
            dtShop.className = isPantry ? dtInactive : dtActive;
            if (isPantry) {
                dtShop.removeAttribute('aria-current');
            } else {
                dtShop.setAttribute('aria-current', 'page');
            }
        }
        if (dtPantry) {
            dtPantry.className = isPantry ? dtActive : dtInactive;
            if (isPantry) {
                dtPantry.setAttribute('aria-current', 'page');
            } else {
                dtPantry.removeAttribute('aria-current');
            }
        }

        // Mobile Navigation Tabs
        const mbShop = document.querySelector('#mobile-nav-tabs a[data-mode-switch="shopping"]');
        const mbPantry = document.querySelector('#mobile-nav-tabs a[data-mode-switch="pantry"]');

        const mbActive = 'inline-flex items-center justify-center px-2.5 py-1 text-xs font-bold whitespace-nowrap flex-shrink-0 rounded-none transition-colors bg-gray-950 text-white border border-gray-950 shadow-sm';
        const mbInactive = 'inline-flex items-center justify-center px-2.5 py-1 text-xs font-bold whitespace-nowrap flex-shrink-0 rounded-none transition-colors bg-white text-gray-700 hover:text-gray-950 border border-gray-300';

        if (mbShop) {
            mbShop.className = isPantry ? mbInactive : mbActive;
            if (isPantry) {
                mbShop.removeAttribute('aria-current');
            } else {
                mbShop.setAttribute('aria-current', 'page');
            }
        }
        if (mbPantry) {
            mbPantry.className = isPantry ? mbActive : mbInactive;
            if (isPantry) {
                mbPantry.setAttribute('aria-current', 'page');
            } else {
                mbPantry.removeAttribute('aria-current');
            }
        }
    }

    function getModeScrollAnchor() {
        const y = window.scrollY || window.pageYOffset || (document.documentElement ? document.documentElement.scrollTop : 0) || 0;
        const header = document.querySelector('header[role="banner"]');
        const headerHeight = (header ? header.offsetHeight : 0) + 10;
        let anchorItemId = null;
        let anchorOffset = 0;

        const rows = document.querySelectorAll('.item-row');
        for (let i = 0; i < rows.length; i++) {
            const row = rows[i];
            const rect = row.getBoundingClientRect();
            if (rect.bottom > headerHeight && rect.top < window.innerHeight) {
                anchorItemId = row.getAttribute('data-item-id');
                anchorOffset = rect.top;
                break;
            }
        }
        return { scrollY: y, anchorItemId: anchorItemId, anchorOffset: anchorOffset };
    }

    function applyModeScrollAnchor(anchor) {
        if (!anchor) return;
        if (anchor.anchorItemId) {
            const esc = window.CSS && window.CSS.escape ? window.CSS.escape(anchor.anchorItemId) : anchor.anchorItemId;
            const targetRow = document.querySelector('.item-row[data-item-id="' + esc + '"]');
            if (targetRow) {
                const currentRect = targetRow.getBoundingClientRect();
                const delta = currentRect.top - anchor.anchorOffset;
                const newY = Math.max(0, (window.scrollY || window.pageYOffset || 0) + delta);
                window.scrollTo({ top: newY, behavior: 'instant' });
                if (document.documentElement) document.documentElement.scrollTop = newY;
                if (document.body) document.body.scrollTop = newY;
                return;
            }
        }
        window.scrollTo({ top: anchor.scrollY, behavior: 'instant' });
        if (document.documentElement) document.documentElement.scrollTop = anchor.scrollY;
        if (document.body) document.body.scrollTop = anchor.scrollY;
    }

    function finishModeSwitch(targetMode, targetUrl, anchor, draft, pushHistory) {
        isSwitchingMode = false;

        // Restore Quick Add Draft values
        restoreQuickAddDraft(draft);

        // Lock / Restore Scroll Position relative to anchor item or exact scroll
        const restoreScroll = function () {
            applyModeScrollAnchor(anchor);
        };

        restoreScroll();
        requestAnimationFrame(restoreScroll);
        setTimeout(restoreScroll, 30);
        setTimeout(restoreScroll, 80);
        setTimeout(restoreScroll, 180);
        setTimeout(function () {
            restoreScroll();
            try {
                sessionStorage.removeItem('shoppin_mode_anchor');
                sessionStorage.removeItem('shoppin_mode_scroll');
            } catch (_) {}
        }, 500);

        // Update Document Title & Browser History
        const pageTitle = targetMode === 'pantry' ? 'Pantry Check - Shoppin' : 'Shopping List - Shoppin';
        document.title = pageTitle;

        if (pushHistory && window.history && window.history.pushState) {
            window.history.pushState({ mode: targetMode, scrollY: anchor.scrollY }, pageTitle, targetUrl);
        }

        // Finalize Nav tabs styling
        updateNavTabsStyling(targetMode);

        // Reinitialize Sortables and Card State
        if (typeof window.initSortables === 'function') {
            window.initSortables();
        }
        if (typeof window.syncCardState === 'function') {
            window.syncCardState();
        }
    }

    function performModeSwitch(targetMode, pushHistory = true) {
        if (isSwitchingMode) return;
        const listContent = document.getElementById('shopping-list-content');
        if (!listContent) return;

        isSwitchingMode = true;

        // Capture scroll position, anchor item, and input draft
        const anchor = getModeScrollAnchor();
        const draft = getQuickAddDraft();
        saveQuickAddDraft(draft);
        try {
            sessionStorage.setItem('shoppin_mode_anchor', JSON.stringify(anchor));
            sessionStorage.setItem('shoppin_mode_scroll', String(anchor.scrollY));
        } catch (_) {}

        // Determine target URL preserving current group_by
        const currentGroupBy = listContent.getAttribute('data-group-by') || 'category';
        let targetUrl;
        if (targetMode === 'pantry') {
            targetUrl = `/pantry-check/?group_by=${encodeURIComponent(currentGroupBy)}`;
        } else {
            targetUrl = `/?mode=shopping&group_by=${encodeURIComponent(currentGroupBy)}`;
        }

        // Immediately update nav tab styling for instant feedback
        updateNavTabsStyling(targetMode);

        // Request partial HTML via htmx.ajax or fetch (no transition:true to prevent view transition scroller freeze)
        if (window.htmx) {
            htmx.ajax('GET', targetUrl, {
                target: '#shopping-list-content',
                swap: 'outerHTML'
            }).then(() => {
                finishModeSwitch(targetMode, targetUrl, anchor, draft, pushHistory);
            }).catch((err) => {
                console.error('[Shoppin Mode] Mode switch error:', err);
                isSwitchingMode = false;
                window.location.href = targetUrl;
            });
        } else {
            fetch(targetUrl, {
                headers: {
                    'HX-Request': 'true',
                    'HX-Target': 'shopping-list-content',
                    'X-Client-Id': window.CLIENT_ID || 'client_web'
                }
            })
            .then(res => res.text())
            .then(html => {
                const temp = document.createElement('div');
                temp.innerHTML = html;
                const newContent = temp.querySelector('#shopping-list-content') || temp.firstElementChild;
                if (newContent) {
                    listContent.replaceWith(newContent);
                }
                finishModeSwitch(targetMode, targetUrl, anchor, draft, pushHistory);
            })
            .catch(() => {
                isSwitchingMode = false;
                window.location.href = targetUrl;
            });
        }
    }

    function handleModeSwitchClick(event, link) {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) {
            return;
        }

        const listContent = document.getElementById('shopping-list-content');
        if (!listContent) {
            // Not on the shopping list page, allow standard page navigation
            return;
        }

        const targetMode = link.getAttribute('data-mode-switch');
        if (!targetMode) return;

        const currentMode = listContent.getAttribute('data-mode') || 'shopping';
        if (targetMode === currentMode) {
            event.preventDefault();
            event.stopPropagation();
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        performModeSwitch(targetMode, true);
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

        // Check for mode switch links (Desktop/Mobile Nav tabs or helper banner)
        const modeSwitchLink = target.closest('[data-mode-switch]');
        if (modeSwitchLink) {
            handleModeSwitchClick(event, modeSwitchLink);
            return;
        }

        // If user clicks edit while offline, provide immediate feedback that connection is required
        const editBtn = target.closest('button[hx-get*="/edit/"]');
        if (editBtn && !navigator.onLine) {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            triggerToast('⚠️ Editing item details requires an internet connection');
            return;
        }

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
        const lockMatch = actionUrl.match(/\/item\/(\d+)\/lock/);

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
        if (!isSwitchingMode) {
            restoreQuickAddDraft();
            try {
                let anchor = null;
                const rawAnchor = sessionStorage.getItem('shoppin_mode_anchor');
                if (rawAnchor) {
                    try { anchor = JSON.parse(rawAnchor); } catch (_) {}
                }
                if (!anchor) {
                    const saved = sessionStorage.getItem('shoppin_mode_scroll');
                    if (saved !== null) {
                        const y = parseInt(saved, 10);
                        if (!isNaN(y)) anchor = { scrollY: y };
                    }
                }
                if (anchor) {
                    const restore = function () { applyModeScrollAnchor(anchor); };
                    restore();
                    requestAnimationFrame(restore);
                    setTimeout(restore, 35);
                    setTimeout(restore, 90);
                    setTimeout(restore, 200);
                    setTimeout(function () {
                        restore();
                        sessionStorage.removeItem('shoppin_mode_anchor');
                        sessionStorage.removeItem('shoppin_mode_scroll');
                    }, 500);
                }
            } catch (_) {}
        }
    }

    // Capture event early before HTMX attaches its listeners (both document and bubbling)
    document.addEventListener('click', interceptAction, true);
    document.addEventListener('submit', interceptAction, true);

    // Quick Add form draft listeners
    function handleQuickAddInput(e) {
        const target = e.target;
        if (target && target.id && (
            target.id === 'add-item-name' ||
            target.id === 'add-item-amount' ||
            target.id === 'add-item-brand' ||
            target.id === 'add-item-vendor' ||
            target.id === 'add-item-purpose'
        )) {
            saveQuickAddDraft();
        }
    }

    function handleQuickAddChange(e) {
        const target = e.target;
        if (target && target.name === 'priority' && target.form && target.form.querySelector('#add-item-name')) {
            saveQuickAddDraft();
        }
    }

    function handleQuickAddSubmit(e) {
        const form = e.target;
        if (form && form.querySelector && form.querySelector('#add-item-name')) {
            clearQuickAddDraft();
        }
    }

    // Browser history back/forward navigation support
    function handlePopState() {
        const listContent = document.getElementById('shopping-list-content');
        if (!listContent) return;

        const pathname = window.location.pathname;
        const search = window.location.search;
        let targetMode = 'shopping';
        if (pathname.includes('pantry-check') || search.includes('mode=pantry')) {
            targetMode = 'pantry';
        }

        const currentMode = listContent.getAttribute('data-mode') || 'shopping';
        if (targetMode !== currentMode) {
            performModeSwitch(targetMode, false);
        }
    }

    document.addEventListener('input', handleQuickAddInput);
    document.addEventListener('change', handleQuickAddChange);
    document.addEventListener('submit', handleQuickAddSubmit);
    window.addEventListener('popstate', handlePopState);

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
