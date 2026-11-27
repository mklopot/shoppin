/**
 * Shoppin Shopping List Optimistic UI, Drag-Drop & Mode Switch Engine
 *
 * Delivers 0ms local DOM transitions (Got, Need, Have, Skip, Lock/Reset, Priority,
 * Quick Add ghost rows, Edit Modal row patching, Drag & Alt+Arrow reordering),
 * delegates persistent serialized queuing to ShoppinQueue, and handles instant
 * in-place Shopping <-> Pantry mode switching.
 */
(function () {
    'use strict';

    let isSwitchingMode = false;
    let modeSwitchResetTimer = null;
    const QUICK_ADD_STORAGE_KEY = 'shoppin_quick_add_draft';

    const Q = () => window.ShoppinQueue;
    const getCsrf = () => (Q() ? Q().getCsrfToken() : '');

    function triggerToast(message, options) {
        if (!message) return;
        if (typeof window.showToast === 'function') {
            window.showToast(message, options);
        }
    }

    // -------------------------------------------------------------------------
    // Client-Side Quick-Add Parser & Category Estimator (matches utils cues)
    // -------------------------------------------------------------------------

    const CATEGORY_KEYWORDS = [
        ['Produce', /\b(?:apple|banana|lettuce|spinach|kale|tomato|onion|garlic|potato|carrot|celery|pepper|avocado|lemon|lime|cilantro|parsley|basil|broccoli|cucumber|mushroom|zucchini|ginger|herb)e?s?\b|\b(?:straw|blue|black|rasp)?berr(?:y|ies)\b/i],
        ['Dairy', /\b(?:milk|cheese|cheddar|mozzarella|parmesan|butter|yogurt|cream|egg|sour cream|cottage)s?\b/i],
        ['Meat', /\b(?:chicken|beef|steak|pork|bacon|sausage|turkey|salmon|shrimp|fish|tuna|ground)s?\b/i],
        ['Bakery', /\b(?:bread|bagel|tortilla|bun|roll|croissant|muffin|pita|naan|baguette)s?\b/i],
        ['Pantry', /\b(?:flour|sugar|rice|pasta|spaghetti|oil|olive oil|vinegar|sauce|broth|stock|bean|lentil|salt|spice|honey|oats|cereal|canned|coffee|tea)s?\b/i],
        ['Frozen', /\b(?:frozen|ice cream|pea|edamame|waffle|pizza)s?\b/i],
        ['Beverages', /\b(?:water|juice|soda|beer|wine|seltzer|sparkling|drink)s?\b/i]
    ];

    function estimateCategory(name) {
        for (const [cat, regex] of CATEGORY_KEYWORDS) {
            if (regex.test(name)) return cat;
        }
        return 'Other';
    }

    function escapeHtml(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\x22/g, '&quot;')
            .replace(/\x27/g, '&#39;');
    }

    function parseQuickAddClient(rawName, rawAmount, rawPriority) {
        let priority = Boolean(rawPriority);
        let cleanName = String(rawName || '').trim();
        ['🚩', '!', '^'].forEach((tok) => {
            if (cleanName.includes(tok)) {
                priority = true;
                cleanName = cleanName.replaceAll(tok, '').trim();
            }
        });
        const amtText = String(rawAmount || '1').trim() || '1';
        const match = amtText.match(/^(\d+(?:\s+\d+\x2f\d+|[.\x2f]\d+)?)\s*(.*)$/);
        const amountDisplay = match ? match[1] : amtText;
        const unitDisplay = match ? match[2].trim() : '';
        return {
            name: cleanName,
            amountDisplay,
            unitDisplay,
            priority,
            category: estimateCategory(cleanName)
        };
    }

    const CLIENT_SINGULAR_EXCEPTIONS = {
        loaves: 'loaf',
        leaves: 'leaf',
        halves: 'half',
        calves: 'calf',
        knives: 'knife',
        cloves: 'clove',
        slices: 'slice',
        tomatoes: 'tomato',
        potatoes: 'potato',
        mangoes: 'mango',
        avocadoes: 'avocado',
        lbs: 'lb'
    };

    const CLIENT_UNCOUNTABLES = new Set([
        'asparagus', 'hummus', 'couscous', 'citrus', 'molasses', 'pasta', 'rice', 'lettuce', 'spinach', 'celery', 'broccoli', 'garlic', 'ginger', 'cheese', 'milk', 'butter', 'bread', 'beef', 'chicken', 'pork', 'fish', 'water', 'oil', 'flour', 'sugar', 'salt', 'oats'
    ]);

    function singularizeClient(word) {
        const clean = String(word || '').trim().toLowerCase();
        if (!clean) return '';
        if (CLIENT_UNCOUNTABLES.has(clean)) return clean;
        if (CLIENT_SINGULAR_EXCEPTIONS[clean]) return CLIENT_SINGULAR_EXCEPTIONS[clean];
        if (clean.length > 3 && clean.endsWith('ies')) {
            return clean.slice(0, -3) + 'y';
        }
        if (clean.length > 3 && clean.endsWith('oes')) {
            return clean.slice(0, -2);
        }
        if (clean.length > 3 && /(?:ch|sh|x|z|ss)es$/.test(clean)) {
            return clean.slice(0, -2);
        }
        if (clean.length > 2 && clean.endsWith('s') && !/(?:ss|us|is)$/.test(clean)) {
            return clean.slice(0, -1);
        }
        return clean;
    }

    const VOLUME_UNITS = new Set([
        'tsp', 'teaspoon', 'tbsp', 'tablespoon', 'fl oz', 'fluid ounce',
        'cup', 'pt', 'pint', 'qt', 'quart', 'gal', 'gallon',
        'ml', 'milliliter', 'l', 'liter'
    ]);

    const WEIGHT_UNITS = new Set([
        'oz', 'ounce', 'lb', 'pound', 'g', 'gram', 'kg', 'kilogram'
    ]);

    function getUnitFamilyClient(unit) {
        const norm = singularizeClient(unit);
        if (!norm) return null;
        if (VOLUME_UNITS.has(norm)) return 'volume';
        if (WEIGHT_UNITS.has(norm)) return 'weight';
        return null;
    }

    function canCombineUnitsClient(u1, u2) {
        const c1 = String(u1 || '').trim();
        const c2 = String(u2 || '').trim();
        if (!c1 && !c2) return true;
        if (!c1 || !c2) return false;
        if (singularizeClient(c1) === singularizeClient(c2)) return true;
        const f1 = getUnitFamilyClient(c1);
        const f2 = getUnitFamilyClient(c2);
        return Boolean(f1 && f1 === f2);
    }

    function parseNumericAmountClient(raw) {
        const s = String(raw || '').trim();
        if (!s) return null;
        const mixed = s.match(/^(\d+)\s+(\d+)\x2f(\d+)$/);
        if (mixed) {
            const denom = parseFloat(mixed[3]);
            return denom ? parseFloat(mixed[1]) + (parseFloat(mixed[2]) / denom) : null;
        }
        const frac = s.match(/^(\d+)\x2f(\d+)$/);
        if (frac) {
            const denom = parseFloat(frac[2]);
            return denom ? parseFloat(frac[1]) / denom : null;
        }
        const num = parseFloat(s);
        return Number.isFinite(num) ? num : null;
    }

    function formatAmountClient(num) {
        if (!Number.isFinite(num)) return '';
        const rounded = Math.round(num * 100) / 100;
        if (Math.abs(rounded - Math.round(rounded)) < 0.001) {
            return String(Math.round(rounded));
        }
        return String(rounded).replace(/0+$/, '').replace(/\.$/, '');
    }

    function getCurrentAuditMeta() {
        const listContent = document.getElementById('shopping-list-content');
        const actorDisplay = (listContent?.getAttribute('data-actor-display') || '').trim();
        const now = new Date();
        const mm = String(now.getMonth() + 1).padStart(2, '0');
        const dd = String(now.getDate()).padStart(2, '0');
        const dateStr = `${mm}/${dd}`;
        const title = actorDisplay
            ? `Date placed or updated by ${actorDisplay}`
            : 'Date placed or updated';
        const text = actorDisplay ? `${actorDisplay} ${dateStr}` : dateStr;
        const html = `<span class="item-audit-meta ml-1.5 text-gray-700 italic text-xs select-none" title="${escapeHtml(title)}">${escapeHtml(text)}</span>`;
        return { actorDisplay, dateStr, title, text, html };
    }

    function getRowData(row) {
        if (!row) return null;
        const titleText = row.querySelector('.item-title')?.textContent?.trim() || '';
        const qtyText = row.querySelector('.item-qty')?.textContent?.trim() || '';
        const fallbackParsed = parseQuickAddClient(titleText, qtyText || '1', false);
        const amount = row.getAttribute('data-item-amount') || fallbackParsed.amountDisplay || '1';
        const unit = row.hasAttribute('data-item-unit')
            ? (row.getAttribute('data-item-unit') || '')
            : fallbackParsed.unitDisplay;
        const unitDisplay = row.hasAttribute('data-item-unit-display')
            ? (row.getAttribute('data-item-unit-display') || '')
            : unit;
        const isPriority = row.getAttribute('data-priority') === 'true'
            || Boolean(row.querySelector('button[title*="Remove priority"], button[title*="click to remove priority"]'));
        return {
            id: row.getAttribute('data-item-id') || '',
            name: row.getAttribute('data-item-name') || titleText,
            status: row.getAttribute('data-item-status') || 'NEED',
            amount,
            unit,
            unitDisplay,
            category: row.getAttribute('data-item-category') || row.getAttribute('data-group-name') || '',
            aisle: row.getAttribute('data-item-aisle') || '',
            brand: row.getAttribute('data-item-brand') || '',
            vendor: row.getAttribute('data-item-vendor') || '',
            purpose: row.getAttribute('data-item-purpose') || '',
            priority: isPriority,
            locked: row.getAttribute('data-locked') === 'true',
            groupName: row.getAttribute('data-group-name') || row.closest('.section-group-block')?.getAttribute('data-group-name') || 'Other'
        };
    }

    function findMatchingRowInContainer(containerSelector, name, opts = {}) {
        const container = document.querySelector(containerSelector);
        if (!container) return null;
        const targetNorm = singularizeClient(name);
        if (!targetNorm) return null;
        const targetBrand = String(opts.brand || '').trim().toLowerCase();
        const targetVendor = String(opts.vendor || '').trim().toLowerCase();
        const targetUnit = String(opts.unit || '').trim();
        const excludeId = opts.excludeItemId ? String(opts.excludeItemId) : null;

        const rows = container.querySelectorAll('.item-row');
        for (let i = 0; i < rows.length; i++) {
            const cand = rows[i];
            if (cand.dataset && cand.dataset.pendingDelete === '1') continue;
            const candId = cand.getAttribute('data-item-id') || '';
            if (excludeId && candId === excludeId) continue;
            const candData = getRowData(cand);
            if (!candData) continue;
            if (
                singularizeClient(candData.name) === targetNorm
                && canCombineUnitsClient(candData.unit, targetUnit)
                && candData.brand.trim().toLowerCase() === targetBrand
                && candData.vendor.trim().toLowerCase() === targetVendor
            ) {
                return cand;
            }
        }
        return null;
    }

    function updateRowAuditMeta(row) {
        if (!row) return;
        const audit = getCurrentAuditMeta();
        const auditEl = row.querySelector('.item-audit-meta, .item-secondary-details > span[title*="Date placed"]');
        if (auditEl) {
            auditEl.textContent = audit.text;
            auditEl.setAttribute('title', audit.title);
        }
    }

    function mergeIntoExistingRowDom(targetRow, addedData, opts = {}) {
        if (!targetRow || !addedData) return;
        const targetData = getRowData(targetRow);
        if (!targetData) return;

        const sameUnit = singularizeClient(targetData.unit) === singularizeClient(addedData.unit);
        const a1 = parseNumericAmountClient(targetData.amount);
        const a2 = parseNumericAmountClient(addedData.amount);
        if (sameUnit && a1 !== null && a2 !== null) {
            const nextAmt = formatAmountClient(a1 + a2);
            targetRow.setAttribute('data-item-amount', nextAmt);
            const qtyEl = targetRow.querySelector('.item-qty');
            if (qtyEl) {
                const unitDisp = targetData.unitDisplay || targetData.unit || addedData.unitDisplay || addedData.unit || '';
                qtyEl.textContent = unitDisp ? `${nextAmt} ${unitDisp}` : nextAmt;
            }
        }

        if (addedData.priority && !targetData.priority) {
            targetRow.setAttribute('data-priority', 'true');
            const titleEl = targetRow.querySelector('.item-title');
            if (titleEl && !targetRow.querySelector('button[title*="Remove priority"], button[title*="click to remove priority"]')) {
                const badge = document.createElement('span');
                badge.className = 'ml-1.5 px-1.5 py-0.2 text-[10px] font-bold uppercase tracking-wider border border-[#800020]/40 bg-[#fdf2f4] text-[#800020] select-none inline-flex items-center gap-1 rounded-none whitespace-nowrap';
                badge.innerHTML = '<span aria-hidden="true">🚩</span><span>Priority</span>';
                titleEl.after(badge);
                targetRow.querySelector('.item-priority-toggle-btn')?.closest('form')?.remove();
            }
        }

        if (opts.lockInPantry) {
            targetRow.setAttribute('data-locked', 'true');
            targetRow.classList.add('bg-blue-50/40');
            const titleEl = targetRow.querySelector('.item-title');
            if (titleEl && !targetRow.querySelector('.item-need-tag')) {
                const tag = document.createElement('span');
                tag.className = 'item-need-tag ml-1.5 px-1 py-0.2 text-[10px] font-bold uppercase tracking-wider bg-blue-100 text-blue-800 border border-blue-300 select-none whitespace-nowrap inline-flex items-center';
                tag.textContent = '📋 Need';
                titleEl.after(tag);
            }
        }

        updateRowAuditMeta(targetRow);
        animateRow(targetRow, '#dbeafe');
    }

    // -------------------------------------------------------------------------
    // Local DOM Helpers
    // -------------------------------------------------------------------------

    function adjustCount(elementId, delta) {
        const el = document.getElementById(elementId);
        if (!el) return;
        const match = el.textContent.match(/\d+/);
        if (match) {
            const updated = Math.max(0, parseInt(match[0], 10) + delta);
            el.textContent = `(${updated})`;
        }
    }

    function animateRow(row, glowColor) {
        if (!row || !row.animate) return;
        if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
        row.animate([
            { transform: 'scale(1.012)', backgroundColor: glowColor },
            { transform: 'scale(1)', backgroundColor: '' }
        ], { duration: 200, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)' });
    }

    function checkAndUpdateSectionEmptyState(sectionBlock) {
        if (!sectionBlock) return;
        const remaining = sectionBlock.querySelectorAll('.item-row');
        sectionBlock.classList.toggle('hidden', remaining.length === 0);

        const sectionsContainer = document.getElementById('section-groups-container');
        const emptyPlaceholder = document.getElementById('to-buy-empty-placeholder');
        if (sectionsContainer && emptyPlaceholder) {
            const anyVisible = sectionsContainer.querySelector('.section-group-block:not(.hidden)');
            emptyPlaceholder.classList.toggle('hidden', Boolean(anyVisible));
        }
    }

    function getListMeta() {
        const listContent = document.getElementById('shopping-list-content');
        const sectionsContainer = document.getElementById('section-groups-container');
        const groupBy = sectionsContainer?.getAttribute('data-group-by') || listContent?.getAttribute('data-group-by') || 'category';
        const mode = listContent?.getAttribute('data-mode')
            || ((window.location.pathname.includes('pantry-check') || window.location.search.includes('mode=pantry')) ? 'pantry' : 'shopping');
        return { listContent, sectionsContainer, groupBy, mode };
    }

    function buildRowActionsHtml(itemId, itemName, status, opts = {}) {
        const { groupBy = 'category', mode = 'shopping', isLocked = false, isPriority = false } = opts;
        const csrf = getCsrf();
        const safeName = escapeHtml(itemName);
        const editBtn = `<button type="button" hx-get="/item/${itemId}/edit/?group_by=${groupBy}&mode=${mode}" hx-target="#modal-placeholder" class="text-gray-500 hover:text-gray-900 px-1 py-0.5 cursor-pointer" aria-label="Edit item ${safeName}" title="Edit"><span aria-hidden="true">✏️</span></button>`;

        if (status === 'GOT') {
            return `
                <form hx-post="/item/${itemId}/status/NEED/?group_by=${groupBy}&mode=${mode}" hx-target="#shopping-list-content" hx-swap="outerHTML" class="inline">
                    <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                    <button type="submit" aria-label="Need: Put ${safeName} back to To Buy" title="Put back to To Buy" class="border border-emerald-400 hover:border-emerald-600 bg-white hover:bg-emerald-50 px-2 py-0.5 text-xs text-gray-900 font-medium rounded-none">
                        📋 Need
                    </button>
                </form>
                ${editBtn}
            `;
        }
        if (status === 'HAVE' || status === 'DONT_NEED') {
            return `
                <form hx-post="/item/${itemId}/status/NEED/?group_by=${groupBy}&mode=${mode}" hx-target="#shopping-list-content" hx-swap="outerHTML" class="inline">
                    <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                    <button type="submit" aria-label="Need: Move ${safeName} back to To Buy" title="Move back to To Buy" class="border border-blue-400 hover:border-blue-600 bg-white hover:bg-blue-50 px-2 py-0.5 text-xs text-gray-900 font-medium rounded-none">
                        📋 Need
                    </button>
                </form>
                ${editBtn}
            `;
        }
        // status === 'NEED'
        if (mode === 'pantry') {
            const lockBtnHtml = isLocked
                ? '<button type="submit" aria-label="Reset: Need confirmed for ' + safeName + '" title="Confirmed need (click to reset)" class="border border-gray-400 bg-gray-100 hover:bg-gray-200 px-2 py-0.5 text-xs text-gray-800 font-semibold rounded-none">↺ Reset</button>'
                : '<button type="submit" aria-label="Need: Confirm need to buy ' + safeName + '" title="Check item: confirm we need to buy this" class="border border-gray-400 hover:border-gray-600 bg-gray-50/70 hover:bg-gray-100 px-2 py-0.5 text-xs text-gray-800 font-medium rounded-none">📋 Need</button>';
            return `
                <form hx-post="/item/${itemId}/status/HAVE/?group_by=${groupBy}&mode=${mode}" hx-target="#shopping-list-content" hx-swap="outerHTML" class="have-status-form ${isLocked ? 'hidden' : ''}">
                    <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                    <button type="submit" aria-label="Have: ${safeName} at home" title="Already have at home" class="border border-amber-500 bg-amber-50 hover:bg-amber-100 px-2 py-0.5 text-xs text-amber-900 font-semibold rounded-none">
                        🏠 Have
                    </button>
                </form>
                <form hx-post="/item/${itemId}/lock/?group_by=${groupBy}&mode=${mode}" hx-target="#shopping-list-content" hx-swap="outerHTML">
                    <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                    ${lockBtnHtml}
                </form>
                <form hx-post="/item/${itemId}/status/DONT_NEED/?group_by=${groupBy}&mode=${mode}" hx-target="#shopping-list-content" hx-swap="outerHTML">
                    <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                    <button type="submit" aria-label="Skip: ${safeName} for this trip" title="Don't need this trip" class="border border-gray-400 hover:border-gray-600 bg-gray-50/70 hover:bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700 hover:text-gray-900">
                        ⏭ Skip
                    </button>
                </form>
                ${editBtn}
            `;
        }
        const priorityBtn = isPriority ? '' : `
            <form hx-post="/item/${itemId}/priority/?group_by=${groupBy}&mode=${mode}" hx-target="#shopping-list-content" hx-swap="outerHTML" class="inline">
                <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                <button type="submit" class="item-priority-toggle-btn text-gray-700 hover:text-[#800020] min-w-[24px] min-h-[24px] inline-flex items-center justify-center p-1 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#800020]" aria-label="Flag ${safeName} as High Priority" title="Flag as High Priority">
                    <span aria-hidden="true">🚩</span>
                </button>
            </form>
        `;
        return `
            <form hx-post="/item/${itemId}/status/GOT/?group_by=${groupBy}&mode=${mode}" hx-target="#shopping-list-content" hx-swap="outerHTML">
                <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                <button type="submit" aria-label="Got: ${safeName} in cart" title="Got it (Put in Cart)" class="border border-gray-400 hover:border-gray-600 bg-gray-50/70 hover:bg-gray-100 px-2 py-0.5 text-xs text-gray-900 font-medium">
                    🛒 Got
                </button>
            </form>
            <form hx-post="/item/${itemId}/status/DONT_NEED/?group_by=${groupBy}&mode=${mode}" hx-target="#shopping-list-content" hx-swap="outerHTML">
                <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                <button type="submit" aria-label="Skip: ${safeName} for this trip" title="Don't need this trip" class="border border-gray-400 hover:border-gray-600 bg-gray-50/70 hover:bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700 hover:text-gray-900">
                    ⏭ Skip
                </button>
            </form>
            ${priorityBtn}
            ${editBtn}
        `;
    }

    function sendQueuedStatusReverse(itemId, status, row) {
        const { groupBy, mode } = getListMeta();
        const url = `/item/${itemId}/status/${status}/?group_by=${groupBy}&mode=${mode}`;
        const body = `csrfmiddlewaretoken=${encodeURIComponent(getCsrf())}`;
        if (status === 'NEED') {
            handleLocalNeed(itemId, row, { silentToast: true });
        } else if (status === 'GOT') {
            handleLocalGot(itemId, row, { silentToast: true });
        } else {
            handleLocalHaveOrSkip(itemId, row, status, { silentToast: true });
        }
        Q()?.enqueue(url, body, {
            itemId,
            targetStatus: status,
            type: 'status',
            reconcileTarget: status === 'NEED' ? '#shopping-list-content' : null,
            coalesceKey: `status:item:${itemId}`
        });
    }

    function handleLocalGot(itemId, row, opts = {}) {
        const gotList = document.getElementById('got-items-list');
        const gotContainer = document.getElementById('got-section-container');
        if (!gotList || !gotContainer) return;

        const itemName = row.getAttribute('data-item-name') || 'item';
        const { groupBy, mode } = getListMeta();
        const originalGroupBlock = row.closest('.section-group-block');
        if (originalGroupBlock) {
            const gn = originalGroupBlock.getAttribute('data-group-name');
            if (gn) row.setAttribute('data-group-name', gn);
        }

        gotContainer.classList.remove('hidden');
        gotList.prepend(row);
        adjustCount('need-items-count', -1);
        adjustCount('got-items-count', 1);

        row.setAttribute('data-item-status', 'GOT');
        row.className = 'item-row py-1.5 px-3 flex items-center justify-between hover:bg-emerald-100/50 text-xs transition-colors';

        const leftWrap = row.querySelector('.flex.items-center.space-x-2');
        if (leftWrap) {
            const dragHandle = leftWrap.querySelector('.drag-handle, .status-icon');
            if (dragHandle) {
                dragHandle.outerHTML = '<span class="status-icon text-emerald-700 font-bold select-none text-sm" aria-hidden="true">✓</span>';
            }
        }

        const actionsWrap = row.querySelector('.item-actions');
        if (actionsWrap) {
            actionsWrap.innerHTML = buildRowActionsHtml(itemId, itemName, 'GOT', { groupBy, mode });
            if (window.htmx) htmx.process(actionsWrap);
        }

        if (originalGroupBlock) checkAndUpdateSectionEmptyState(originalGroupBlock);
        animateRow(row, '#d1fae5');

        if (!opts.silentToast) {
            triggerToast(`🛒 You got '${itemName}'`, {
                type: 'success',
                undoLabel: 'Undo',
                onUndo: () => sendQueuedStatusReverse(itemId, 'NEED', row)
            });
        }
    }

    function getOrCreateGroupBlock(sectionsContainer, groupName) {
        const esc = window.CSS && window.CSS.escape ? window.CSS.escape(groupName) : groupName;
        let targetBlock = sectionsContainer.querySelector(`.section-group-block[data-group-name="${esc}"]`);
        if (!targetBlock) {
            targetBlock = document.createElement('div');
            targetBlock.className = 'section-group-block space-y-1.5';
            targetBlock.setAttribute('data-group-name', groupName);
            targetBlock.innerHTML = `
                <div class="flex items-center justify-between pb-1">
                    <div class="flex items-center space-x-2">
                        <span class="section-drag-handle cursor-grab active:cursor-grabbing text-gray-400 hover:text-gray-800 select-none text-base font-mono leading-none focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900" role="button" tabindex="0" title="Drag to rearrange section" aria-label="Reorder section ${escapeHtml(groupName)}: press Alt+Up or Alt+Down to move">⋮⋮</span>
                        <h3 class="font-black text-sm tracking-wider uppercase text-gray-950 select-none">${escapeHtml(groupName)}</h3>
                    </div>
                </div>
                <div class="sortable-group divide-y divide-gray-200" data-group="${escapeHtml(groupName)}"></div>
            `;
            sectionsContainer.appendChild(targetBlock);
            initSortables();
        }
        return targetBlock;
    }

    function handleLocalNeed(itemId, row, opts = {}) {
        const { sectionsContainer, groupBy, mode } = getListMeta();
        if (!sectionsContainer) return null;

        const previousStatus = row.getAttribute('data-item-status') || 'GOT';
        const rowData = getRowData(row);
        const itemName = (rowData && rowData.name) || row.getAttribute('data-item-name') || 'item';

        // Combine at the very first opportunity if a matching NEED item is already in To Buy!
        const matchRow = findMatchingRowInContainer('#section-groups-container', itemName, {
            brand: rowData?.brand || '',
            vendor: rowData?.vendor || '',
            unit: rowData?.unit || '',
            excludeItemId: itemId
        });

        if (matchRow) {
            row.remove();
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
            mergeIntoExistingRowDom(matchRow, rowData, { lockInPantry: mode === 'pantry' });
            const matchName = matchRow.getAttribute('data-item-name') || itemName;
            if (!opts.silentToast) {
                triggerToast(`📋 Combined '${itemName}' into '${matchName}'`, { type: 'info' });
            }
            return { mergedIntoId: matchRow.getAttribute('data-item-id') };
        }

        let groupName = row.getAttribute('data-group-name');
        if (!groupName || groupName === 'null') groupName = 'Other';

        const targetBlock = getOrCreateGroupBlock(sectionsContainer, groupName);
        targetBlock.classList.remove('hidden');
        const targetGroup = targetBlock.querySelector('.sortable-group');
        if (targetGroup) targetGroup.prepend(row);
        else targetBlock.appendChild(row);

        const emptyPlaceholder = document.getElementById('to-buy-empty-placeholder');
        if (emptyPlaceholder) emptyPlaceholder.classList.add('hidden');

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

        const isPriority = row.getAttribute('data-priority') === 'true' || Boolean(row.querySelector('form[action*="/priority/"] button, form[hx-post*="/priority/"] button[title*="Remove"]'));

        row.setAttribute('data-item-status', 'NEED');
        if (mode === 'pantry') {
            row.setAttribute('data-locked', 'true');
            row.className = 'item-row py-1.5 px-3 flex items-center justify-between hover:bg-gray-50 text-xs transition-colors bg-blue-50/40';
            const titleEl = row.querySelector('.item-title');
            if (titleEl && !row.querySelector('.item-need-tag')) {
                const tag = document.createElement('span');
                tag.className = 'item-need-tag ml-1.5 px-1 py-0.2 text-[10px] font-bold uppercase tracking-wider bg-blue-100 text-blue-800 border border-blue-300 select-none whitespace-nowrap inline-flex items-center';
                tag.textContent = '📋 Need';
                titleEl.after(tag);
            }
        } else {
            row.className = 'item-row py-1.5 px-3 flex items-center justify-between hover:bg-gray-50 text-xs transition-colors';
        }

        const leftWrap = row.querySelector('.flex.items-center.space-x-2');
        if (leftWrap) {
            const icon = leftWrap.querySelector('.status-icon, .drag-handle');
            if (icon) {
                icon.outerHTML = `<span class="drag-handle cursor-grab active:cursor-grabbing text-gray-400 hover:text-gray-700 select-none text-sm font-mono focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900" role="button" tabindex="0" title="Drag to rearrange item" aria-label="Reorder ${escapeHtml(itemName)}: press Alt+Up or Alt+Down to move">⋮⋮</span>`;
            }
        }

        const actionsWrap = row.querySelector('.item-actions');
        if (actionsWrap) {
            actionsWrap.innerHTML = buildRowActionsHtml(itemId, itemName, 'NEED', {
                groupBy,
                mode,
                isLocked: mode === 'pantry',
                isPriority
            });
            if (window.htmx) htmx.process(actionsWrap);
        }

        updateRowAuditMeta(row);
        animateRow(row, '#dbeafe');
        if (!opts.silentToast) {
            triggerToast(`📋 Moved '${itemName}' back to To Buy`, { type: 'info' });
        }
        return null;
    }

    function handleLocalHaveOrSkip(itemId, row, targetStatus, opts = {}) {
        const pantryList = document.getElementById('pantry-items-list');
        const pantryContainer = document.getElementById('pantry-section-container');
        if (!pantryList || !pantryContainer) return;

        const itemName = row.getAttribute('data-item-name') || 'item';
        const { groupBy, mode } = getListMeta();
        const originalGroupBlock = row.closest('.section-group-block');
        if (originalGroupBlock) {
            const gn = originalGroupBlock.getAttribute('data-group-name');
            if (gn) row.setAttribute('data-group-name', gn);
        }

        pantryContainer.classList.remove('hidden');
        pantryList.prepend(row);
        adjustCount('need-items-count', -1);
        adjustCount('pantry-items-count', 1);

        row.setAttribute('data-item-status', targetStatus);
        row.className = 'item-row py-1.5 px-3 flex items-center justify-between hover:bg-blue-100/50 text-xs transition-colors';

        const iconSymbol = targetStatus === 'HAVE' ? '🏠' : '⏭';
        const iconTitle = targetStatus === 'HAVE' ? 'Already have at home' : 'Skipped';
        const leftWrap = row.querySelector('.flex.items-center.space-x-2');
        if (leftWrap) {
            const handleOrIcon = leftWrap.querySelector('.drag-handle, .status-icon');
            if (handleOrIcon) {
                handleOrIcon.outerHTML = `<span class="status-icon ${targetStatus === 'HAVE' ? 'text-blue-800' : 'text-gray-600'} font-bold select-none text-sm" title="${iconTitle}" aria-label="${iconTitle}">${iconSymbol}</span>`;
            }
        }

        const actionsWrap = row.querySelector('.item-actions');
        if (actionsWrap) {
            actionsWrap.innerHTML = buildRowActionsHtml(itemId, itemName, targetStatus, { groupBy, mode });
            if (window.htmx) htmx.process(actionsWrap);
        }

        if (originalGroupBlock) checkAndUpdateSectionEmptyState(originalGroupBlock);
        animateRow(row, '#e0f2fe');

        if (!opts.silentToast) {
            const msg = targetStatus === 'HAVE' ? `🏠 Marked '${itemName}' as Already in Pantry` : `⏭ You skipped '${itemName}'`;
            triggerToast(msg, {
                type: 'info',
                undoLabel: 'Undo',
                onUndo: () => sendQueuedStatusReverse(itemId, 'NEED', row)
            });
        }
    }

    function handleLocalLockToggle(itemId, row, button) {
        const isLocked = row.getAttribute('data-locked') === 'true';
        const titleEl = row.querySelector('.item-title');
        const itemName = row.getAttribute('data-item-name') || 'item';
        const lockBtn = button || row.querySelector('form[action*="/lock/"] button, form[hx-post*="/lock/"] button');
        const { groupBy, mode } = getListMeta();

        // Always strip stale moving/locked classes so row buttons never stay dead
        row.classList.remove('item-moving', 'item-got-optimistic', 'item-have-optimistic', 'item-skip-optimistic', 'item-need-optimistic');

        if (!isLocked) {
            row.setAttribute('data-locked', 'true');
            row.classList.add('bg-blue-50/40');
            if (titleEl && !row.querySelector('.item-need-tag')) {
                const tag = document.createElement('span');
                tag.className = 'item-need-tag ml-1.5 px-1 py-0.2 text-[10px] font-bold uppercase tracking-wider bg-blue-100 text-blue-800 border border-blue-300 select-none whitespace-nowrap inline-flex items-center';
                tag.textContent = '📋 Need';
                titleEl.after(tag);
            }
            if (lockBtn) {
                lockBtn.innerHTML = '↺ Reset';
                lockBtn.className = 'border border-gray-400 bg-gray-100 hover:bg-gray-200 px-2 py-0.5 text-xs text-gray-800 font-semibold rounded-none';
                lockBtn.setAttribute('title', 'Confirmed need (click to reset)');
                lockBtn.setAttribute('aria-label', `Reset: Need confirmed for ${itemName}`);
            }
            row.querySelector('form[action*="/status/HAVE"], form[hx-post*="/status/HAVE"]')?.classList.add('hidden');
            row.querySelector('button[title*="Pantry check needed"]')?.closest('form')?.classList.add('hidden');
            animateRow(row, '#dbeafe');
            triggerToast(`📋 Confirmed need for '${itemName}'`, { type: 'info' });
        } else {
            row.setAttribute('data-locked', 'false');
            row.classList.remove('bg-blue-50/40');
            row.querySelector('.item-need-tag')?.remove();
            if (lockBtn) {
                lockBtn.innerHTML = '📋 Need';
                lockBtn.className = 'border border-gray-400 hover:border-gray-600 bg-gray-50/70 hover:bg-gray-100 px-2 py-0.5 text-xs text-gray-800 font-medium rounded-none';
                lockBtn.setAttribute('title', 'Check item: confirm we need to buy this');
                lockBtn.setAttribute('aria-label', `Need: Confirm need to buy ${itemName}`);
            }
            let haveForm = row.querySelector('form[action*="/status/HAVE"], form[hx-post*="/status/HAVE"]');
            if (haveForm) {
                haveForm.classList.remove('hidden');
            } else if (lockBtn?.closest('form')) {
                const csrf = getCsrf();
                haveForm = document.createElement('form');
                haveForm.setAttribute('hx-post', `/item/${itemId}/status/HAVE/?group_by=${groupBy}&mode=${mode}`);
                haveForm.setAttribute('hx-target', '#shopping-list-content');
                haveForm.setAttribute('hx-swap', 'outerHTML');
                haveForm.className = 'have-status-form';
                haveForm.innerHTML = `<input type="hidden" name="csrfmiddlewaretoken" value="${csrf}"><button type="submit" aria-label="Have: ${escapeHtml(itemName)} at home" title="Already have at home" class="border border-amber-500 bg-amber-50 hover:bg-amber-100 px-2 py-0.5 text-xs text-amber-900 font-semibold rounded-none">🏠 Have</button>`;
                lockBtn.closest('form').before(haveForm);
                if (window.htmx) htmx.process(haveForm);
            }
            row.querySelector('button[title*="Pantry check needed"]')?.closest('form')?.classList.remove('hidden');
            animateRow(row, '#f3f4f6');
            triggerToast(`Reset '${itemName}' check status`, { type: 'info' });
        }
        return !isLocked;
    }

    function handleLocalPriorityToggle(itemId, row) {
        const { groupBy, mode, sectionsContainer } = getListMeta();
        const titleEl = row.querySelector('.item-title');
        const itemName = row.getAttribute('data-item-name') || 'item';
        const actionsWrap = row.querySelector('.item-actions');
        const csrf = getCsrf();
        const currentlyPriority = Boolean(row.querySelector('button[title*="Remove priority"], button[title*="click to remove priority"]'));

        row.classList.remove('item-moving');

        if (!currentlyPriority) {
            row.setAttribute('data-priority', 'true');
            // Insert prominent crimson Priority pill right next to item title
            if (titleEl && !row.querySelector('form[hx-post*="/priority/"] button[title*="Remove"]')) {
                const form = document.createElement('form');
                form.setAttribute('hx-post', `/item/${itemId}/priority/?group_by=${groupBy}&mode=${mode}`);
                form.setAttribute('hx-target', '#shopping-list-content');
                form.setAttribute('hx-swap', 'outerHTML');
                form.className = 'inline';
                form.innerHTML = `
                    <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                    <button type="submit" class="ml-1.5 px-1.5 py-0.2 text-[10px] font-bold uppercase tracking-wider border border-[#800020]/40 bg-[#fdf2f4] hover:bg-[#fae1e6] text-[#800020] select-none inline-flex items-center gap-1 rounded-none cursor-pointer focus:outline-none transition-colors whitespace-nowrap" title="High Priority (click to remove priority)" aria-label="Priority: Remove high priority flag for ${escapeHtml(itemName)}">
                        <span aria-hidden="true">🚩</span><span>Priority</span>
                    </button>
                `;
                titleEl.after(form);
                if (window.htmx) htmx.process(form);
            }
            row.querySelector('.item-priority-toggle-btn')?.closest('form')?.remove();

            if (groupBy === 'priority' && sectionsContainer && row.getAttribute('data-item-status') === 'NEED') {
                const oldBlock = row.closest('.section-group-block');
                const prioBlock = getOrCreateGroupBlock(sectionsContainer, 'Priority Items');
                prioBlock.classList.remove('hidden');
                prioBlock.querySelector('.sortable-group')?.prepend(row);
                if (oldBlock && oldBlock !== prioBlock) checkAndUpdateSectionEmptyState(oldBlock);
            }
            animateRow(row, '#ffe4e6');
            triggerToast(`📌 '${itemName}' flagged as High Priority`, { type: 'info' });
        } else {
            row.setAttribute('data-priority', 'false');
            row.querySelector('button[title*="click to remove priority"]')?.closest('form')?.remove();
            if (actionsWrap && mode !== 'pantry' && !actionsWrap.querySelector('.item-priority-toggle-btn')) {
                const editBtn = actionsWrap.querySelector('button[hx-get*="/edit/"]');
                const form = document.createElement('form');
                form.setAttribute('hx-post', `/item/${itemId}/priority/?group_by=${groupBy}&mode=${mode}`);
                form.setAttribute('hx-target', '#shopping-list-content');
                form.setAttribute('hx-swap', 'outerHTML');
                form.className = 'inline';
                form.innerHTML = `
                    <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
                    <button type="submit" class="item-priority-toggle-btn text-gray-700 hover:text-[#800020] min-w-[24px] min-h-[24px] inline-flex items-center justify-center p-1 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#800020]" aria-label="Flag ${escapeHtml(itemName)} as High Priority" title="Flag as High Priority">
                        <span aria-hidden="true">🚩</span>
                    </button>
                `;
                if (editBtn) actionsWrap.insertBefore(form, editBtn);
                else actionsWrap.appendChild(form);
                if (window.htmx) htmx.process(form);
            }

            if (groupBy === 'priority' && sectionsContainer && row.getAttribute('data-item-status') === 'NEED') {
                const oldBlock = row.closest('.section-group-block');
                const stdBlock = getOrCreateGroupBlock(sectionsContainer, 'Standard Items');
                stdBlock.classList.remove('hidden');
                stdBlock.querySelector('.sortable-group')?.prepend(row);
                if (oldBlock && oldBlock !== stdBlock) checkAndUpdateSectionEmptyState(oldBlock);
            }
            animateRow(row, '#f3f4f6');
            triggerToast(`📌 Removed priority from '${itemName}'`, { type: 'info' });
        }
        return !currentlyPriority;
    }

    // -------------------------------------------------------------------------
    // Optimistic Quick Add + Live Input Chips + Edit Modal Row Patching
    // -------------------------------------------------------------------------

    function renderQuickAddPreview() {
        const nameEl = document.getElementById('add-item-name');
        const previewEl = document.getElementById('quick-add-preview');
        if (!nameEl || !previewEl) return;

        const val = (nameEl.value || '').trim();
        if (!val) {
            previewEl.innerHTML = '';
            previewEl.classList.add('hidden');
            return;
        }
        const amountEl = document.getElementById('add-item-amount');
        const prioEl = nameEl.form?.querySelector('input[name="priority"]');
        const parsed = parseQuickAddClient(val, amountEl?.value || '1', prioEl?.checked);

        const chips = [];
        if (parsed.priority) {
            chips.push('<span class="px-1.5 py-0.2 text-[10px] font-bold uppercase bg-[#fdf2f4] border border-[#800020]/40 text-[#800020]">🚩 Priority</span>');
        }
        chips.push(`<span class="px-1.5 py-0.2 text-[10px] font-medium bg-white border border-gray-300 text-gray-800">${escapeHtml(parsed.amountDisplay)}${parsed.unitDisplay ? ' ' + escapeHtml(parsed.unitDisplay) : ''}</span>`);
        chips.push(`<span class="px-1.5 py-0.2 text-[10px] font-medium bg-gray-100 border border-gray-300 text-gray-700">${escapeHtml(parsed.category)}</span>`);

        previewEl.innerHTML = `<span class="text-[10px] text-gray-500 font-semibold uppercase tracking-wider mr-1">Preview:</span>${chips.join('')}`;
        previewEl.classList.remove('hidden');
    }

    function insertOptimisticGhostRow(parsed, meta) {
        let sectionsContainer = document.getElementById('section-groups-container');
        const { groupBy, mode } = getListMeta();
        if (!sectionsContainer) {
            const emptyInitial = document.getElementById('to-buy-empty-initial');
            if (!emptyInitial || !emptyInitial.parentNode) return null;
            sectionsContainer = document.createElement('div');
            sectionsContainer.id = 'section-groups-container';
            sectionsContainer.className = 'space-y-6 px-3 py-4';
            sectionsContainer.setAttribute('data-group-by', groupBy);
            emptyInitial.parentNode.replaceChild(sectionsContainer, emptyInitial);
        }
        const groupName = groupBy === 'priority'
            ? (parsed.priority ? 'Priority Items' : 'Standard Items')
            : (groupBy === 'aisle' ? 'Other' : parsed.category);

        const tempId = meta.tempId;
        const row = document.createElement('div');
        row.id = `item-row-${tempId}`;
        row.className = `item-row py-1.5 px-3 flex items-center justify-between hover:bg-gray-50 text-xs transition-colors${mode === 'pantry' ? ' bg-blue-50/40' : ''}`;
        row.setAttribute('data-item-id', tempId);
        row.setAttribute('data-item-name', parsed.name);
        row.setAttribute('data-item-status', 'NEED');
        row.setAttribute('data-item-amount', parsed.amountDisplay);
        row.setAttribute('data-item-unit', parsed.unitDisplay || '');
        row.setAttribute('data-item-unit-display', parsed.unitDisplay || '');
        row.setAttribute('data-item-category', parsed.category.toLowerCase());
        row.setAttribute('data-item-aisle', '');
        row.setAttribute('data-item-brand', meta.brand || '');
        row.setAttribute('data-item-vendor', meta.vendor || '');
        row.setAttribute('data-item-purpose', meta.purpose || 'one-time purchase');
        row.setAttribute('data-priority', parsed.priority ? 'true' : 'false');
        row.setAttribute('data-locked', 'true');
        row.setAttribute('data-optimistic-pending', '1');
        row.setAttribute('data-group-name', groupName);

        const purposeText = meta.purpose && meta.purpose.toLowerCase() !== 'one-time purchase'
            ? `<span class="inline-block italic text-gray-600">For ${escapeHtml(meta.purpose)}</span>`
            : '<span class="inline-block italic text-gray-600">For one-time purchase</span>';
        const brandText = meta.brand ? `<span class="inline-block ml-1 italic text-gray-700">Brand: ${escapeHtml(meta.brand)}</span>` : '';
        const vendorText = meta.vendor ? `<span class="inline-block ml-1 italic text-gray-700">Vendor: ${escapeHtml(meta.vendor)}</span>` : '';
        const prioBadge = parsed.priority
            ? '<span class="ml-1.5 px-1.5 py-0.2 text-[10px] font-bold uppercase tracking-wider border border-[#800020]/40 bg-[#fdf2f4] text-[#800020] select-none inline-flex items-center gap-1 rounded-none whitespace-nowrap"><span aria-hidden="true">🚩</span><span>Priority</span></span>'
            : '';
        const pantryTag = mode === 'pantry'
            ? '<span class="item-need-tag ml-1.5 px-1 py-0.2 text-[10px] font-bold uppercase tracking-wider bg-blue-100 text-blue-800 border border-blue-300 select-none whitespace-nowrap inline-flex items-center">📋 Need</span>'
            : '';
        const auditMeta = getCurrentAuditMeta();

        row.innerHTML = `
            <div class="flex items-center space-x-2 flex-1 min-w-0 mr-2">
                <span class="drag-handle cursor-grab text-gray-400 select-none text-sm font-mono">⋮⋮</span>
                <div class="min-w-0 flex-1 leading-snug">
                    <span class="item-title font-semibold text-gray-900 text-sm">${escapeHtml(parsed.name)}</span>
                    ${prioBadge}
                    ${pantryTag}
                    <span class="item-qty font-normal text-gray-700 ml-1.5 whitespace-nowrap">${escapeHtml(parsed.amountDisplay)}${parsed.unitDisplay ? ' ' + escapeHtml(parsed.unitDisplay) : ''}</span>
                    <span class="item-secondary-details text-gray-600 ml-2">${purposeText}${brandText}${vendorText}${auditMeta.html}</span>
                </div>
            </div>
            <div class="item-actions flex items-center space-x-1 flex-shrink-0">
                ${buildRowActionsHtml(tempId, parsed.name, 'NEED', { groupBy, mode, isLocked: true, isPriority: parsed.priority })}
            </div>
        `;
        const block = getOrCreateGroupBlock(sectionsContainer, groupName);
        block.classList.remove('hidden');
        document.getElementById('to-buy-empty-placeholder')?.classList.add('hidden');
        const groupList = block.querySelector('.sortable-group');
        if (groupList) groupList.prepend(row);
        adjustCount('need-items-count', 1);
        animateRow(row, '#d1fae5');
        if (window.htmx) htmx.process(row);
        return row;
    }

    function handleOptimisticQuickAdd(form) {
        const nameEl = form.querySelector('#add-item-name');
        const rawName = nameEl?.value?.trim() || '';
        if (!rawName) return;

        const amountEl = form.querySelector('#add-item-amount');
        const brandEl = form.querySelector('#add-item-brand');
        const vendorEl = form.querySelector('#add-item-vendor');
        const purposeEl = form.querySelector('#add-item-purpose');
        const prioEl = form.querySelector('input[name="priority"]');

        const actionUrl = form.getAttribute('hx-post') || form.getAttribute('action');
        const body = Q().serializeForm(form);
        const brandVal = brandEl?.value?.trim() || '';
        const vendorVal = vendorEl?.value?.trim() || '';
        const purposeVal = purposeEl?.value?.trim() || '';
        const parsed = parseQuickAddClient(rawName, amountEl?.value || '1', prioEl?.checked);

        // Combine at 0ms if a matching NEED item already exists in To Buy
        const existingMatchRow = findMatchingRowInContainer('#section-groups-container', parsed.name, {
            brand: brandVal,
            vendor: vendorVal,
            unit: parsed.unitDisplay
        });

        let tempId = null;
        let ghostRow = null;
        if (existingMatchRow) {
            mergeIntoExistingRowDom(existingMatchRow, {
                amount: parsed.amountDisplay,
                unit: parsed.unitDisplay,
                unitDisplay: parsed.unitDisplay,
                priority: parsed.priority
            }, { lockInPantry: getListMeta().mode === 'pantry' });
        } else {
            tempId = Q().generateKey('tmp');
            ghostRow = insertOptimisticGhostRow(parsed, {
                tempId,
                brand: brandVal,
                vendor: vendorVal,
                purpose: purposeVal
            });
        }

        // Clear fields & keep focus in Quick Add immediately for rapid-fire grocery input!
        clearQuickAddDraft();
        if (nameEl) { nameEl.value = ''; nameEl.focus(); }
        if (amountEl) amountEl.value = '1';
        if (brandEl) brandEl.value = '';
        if (vendorEl) vendorEl.value = '';
        if (purposeEl) purposeEl.value = '';
        if (prioEl) prioEl.checked = false;
        renderQuickAddPreview();

        window.ShoppinHaptics?.tap?.(10);
        if (existingMatchRow) {
            const matchName = existingMatchRow.getAttribute('data-item-name') || parsed.name;
            triggerToast(`Updated '${matchName}'`, { type: 'success', duration: 2800 });
        } else {
            triggerToast(`Added '${parsed.name}'`, {
                type: 'success',
                duration: 3000,
                undoLabel: 'Undo',
                onUndo: () => {
                    const realId = Q().tempIdMap.get(tempId) || tempId;
                    if (ghostRow && ghostRow.parentNode) {
                        ghostRow.remove();
                        adjustCount('need-items-count', -1);
                    }
                    const { groupBy, mode } = getListMeta();
                    Q().enqueue(`/item/${realId}/delete/?group_by=${groupBy}&mode=${mode}`, `csrfmiddlewaretoken=${encodeURIComponent(getCsrf())}`, {
                        itemId: realId,
                        type: 'delete',
                        reconcileTarget: '#shopping-list-content'
                    }, {
                        onSuccess: (_, html, ctx) => {
                            if (html && !ctx?.hasMoreWork && window.ShoppinMorph) {
                                window.ShoppinMorph.swapFromHtml('#shopping-list-content', html);
                            }
                        }
                    });
                }
            });
        }

        Q().enqueue(actionUrl, body, {
            tempId,
            itemId: existingMatchRow ? existingMatchRow.getAttribute('data-item-id') : null,
            type: 'add_item',
            reconcileTarget: '#shopping-list-content',
            idempotencyKey: Q().generateKey('add')
        }, {
            onSuccess: (_, html, ctx) => {
                if (ghostRow) ghostRow.removeAttribute('data-optimistic-pending');
                if (html && !ctx?.hasMoreWork && window.ShoppinMorph) {
                    window.ShoppinMorph.swapFromHtml('#shopping-list-content', html);
                }
            },
            onError: () => {
                if (ghostRow && ghostRow.parentNode) {
                    ghostRow.remove();
                    adjustCount('need-items-count', -1);
                }
            }
        });
    }

    // -------------------------------------------------------------------------
    // 0ms Instant Edit Item Modal + Background History Hydration + Queued Save
    // -------------------------------------------------------------------------

    function extractAdvancedDetailsHtml(serverModalHtml) {
        if (!serverModalHtml) return '';
        const wrap = document.createElement('div');
        wrap.innerHTML = serverModalHtml;
        const detailsEl = wrap.querySelector('details');
        return detailsEl ? detailsEl.outerHTML : '';
    }

    function buildEditModalHtml(itemData, opts = {}) {
        const { resolvedId, groupBy, mode, token, isTemp, isOnline, cachedAdvancedHtml } = opts;
        const csrf = getCsrf();
        const amountFieldValue = itemData.unitDisplay
            ? `${itemData.amount} ${itemData.unitDisplay}`.trim()
            : (itemData.unit ? `${itemData.amount} ${itemData.unit}`.trim() : itemData.amount);
        const advancedStatus = isTemp
            ? 'Available once synced'
            : (!isOnline ? 'Offline — changes will queue' : 'Loading history...');
        const advancedInner = cachedAdvancedHtml || `
            <details class="group border border-gray-300 bg-gray-50/70">
                <summary class="cursor-pointer select-none px-2.5 py-1.5 text-[11px] font-bold uppercase tracking-wider text-gray-700 hover:text-gray-900 hover:bg-gray-100 flex items-center justify-between list-none">
                    <span class="flex items-center gap-1.5">
                        <span class="inline-block transition-transform duration-150 group-open:rotate-90 text-[10px]" aria-hidden="true">&#9654;</span>
                        <span>Advanced</span>
                    </span>
                    <span class="edit-advanced-status text-[10px] font-medium normal-case tracking-normal text-gray-500">${escapeHtml(advancedStatus)}</span>
                </summary>
                <div class="p-2.5 border-t border-gray-300 bg-white text-[11px] text-gray-600 italic">
                    ${escapeHtml(advancedStatus)}
                </div>
            </details>
        `;

        return `
<div id="modal-container" role="dialog" aria-modal="true" aria-labelledby="edit-item-modal-title" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onclick="if(event.target === this){ const mp = document.getElementById('modal-placeholder'); if(mp) mp.innerHTML=''; }">
    <div class="bg-white border border-gray-400 max-w-md w-full p-4 space-y-3 shadow-lg max-h-[90vh] overflow-y-auto">
        <div class="flex justify-between items-center border-b border-gray-300 pb-2">
            <h3 id="edit-item-modal-title" class="font-bold text-gray-900 text-sm uppercase">Edit Item</h3>
            <button type="button" onclick="const mp = document.getElementById('modal-placeholder'); if(mp) mp.innerHTML=''; else document.getElementById('modal-container')?.remove();" aria-label="Close dialog" class="text-gray-500 hover:text-black font-bold text-lg cursor-pointer"><span aria-hidden="true">&times;</span></button>
        </div>

        <form hx-post="/item/${escapeHtml(resolvedId)}/edit/?group_by=${encodeURIComponent(groupBy)}&amp;mode=${encodeURIComponent(mode)}" hx-target="#shopping-list-content" hx-swap="outerHTML transition:true" class="space-y-2.5 text-xs">
            <input type="hidden" name="csrfmiddlewaretoken" value="${escapeHtml(csrf)}">
            <input type="hidden" name="group_by" value="${escapeHtml(groupBy)}">
            <input type="hidden" name="mode" value="${escapeHtml(mode)}">
            <div>
                <label for="edit-item-name" class="block font-bold text-gray-700 mb-0.5">Item Name</label>
                <input type="text" id="edit-item-name" name="name" value="${escapeHtml(itemData.name)}" list="all-ingredients-datalist" autocomplete="off" required class="w-full px-2 py-1.5 border border-gray-400 bg-white text-xs">
            </div>

            <div>
                <label for="edit-item-amount" class="block font-bold text-gray-700 mb-0.5">Amount &amp; Unit</label>
                <input type="text" id="edit-item-amount" name="amount" value="${escapeHtml(amountFieldValue)}" placeholder="e.g. 2 lbs, 1/2 cup, 3 cans, 1" class="w-full px-2 py-1.5 border border-gray-400 bg-white text-xs">
                <span class="text-[10px] text-gray-500">Type quantity and unit together (e.g. &quot;2 lbs&quot;, &quot;1/2 cup&quot;, &quot;1 can&quot;) &mdash; automatically parsed.</span>
            </div>

            <div class="grid grid-cols-2 gap-2">
                <div>
                    <label for="edit-item-category" class="block font-bold text-gray-700 mb-0.5">Category</label>
                    <input type="text" id="edit-item-category" name="category" list="category-datalist" value="${escapeHtml(itemData.category)}" placeholder="Select or type category..." autocomplete="off" class="w-full px-2 py-1 border border-gray-400 bg-white rounded-none focus:outline-none focus:border-gray-700">
                </div>
                <div>
                    <label for="edit-item-aisle" class="block font-bold text-gray-700 mb-0.5">Aisle</label>
                    <input type="text" id="edit-item-aisle" name="aisle" list="aisle-datalist" value="${escapeHtml(itemData.aisle)}" placeholder="Select or type aisle..." autocomplete="off" class="w-full px-2 py-1 border border-gray-400 bg-white rounded-none focus:outline-none focus:border-gray-700">
                </div>
            </div>

            <div class="grid grid-cols-2 gap-2">
                <div>
                    <label for="edit-item-brand" class="block font-bold text-gray-700 mb-0.5">Brand (optional)</label>
                    <input type="text" id="edit-item-brand" name="brand" value="${escapeHtml(itemData.brand)}" class="w-full px-2 py-1 border border-gray-400 bg-white">
                </div>
                <div>
                    <label for="edit-item-vendor" class="block font-bold text-gray-700 mb-0.5">Vendor (optional)</label>
                    <input type="text" id="edit-item-vendor" name="vendor" value="${escapeHtml(itemData.vendor)}" placeholder="King Soopers, etc" class="w-full px-2 py-1 border border-gray-400 bg-white">
                </div>
            </div>

            <div>
                <label for="edit-item-purpose" class="block font-bold text-gray-700 mb-0.5">Purpose</label>
                <input type="text" id="edit-item-purpose" name="purpose" value="${escapeHtml(itemData.purpose)}" placeholder="e.g. one-time purchase, snack" class="w-full px-2 py-1 border border-gray-400 bg-white">
            </div>

            <div class="flex items-center space-x-2 pt-1 min-h-[28px]">
                <input type="checkbox" id="edit-item-priority" name="priority" value="true" ${itemData.priority ? 'checked' : ''} class="h-4 w-4 text-[#800020] border-gray-400 rounded-none cursor-pointer focus:ring-1 focus:ring-[#800020]">
                <label for="edit-item-priority" class="font-bold text-gray-800 flex items-center space-x-1.5 cursor-pointer select-none">
                    <span class="px-1.5 py-0.2 text-[10px] font-bold uppercase tracking-wider border border-[#800020]/40 bg-[#fdf2f4] text-[#800020] select-none inline-flex items-center gap-1 rounded-none whitespace-nowrap">
                        <span aria-hidden="true">🚩</span>
                        <span>Priority</span>
                    </span>
                    <span class="text-xs text-gray-700 font-normal">(Flag as high priority item)</span>
                </label>
            </div>

            <div id="edit-item-advanced-slot" data-modal-token="${escapeHtml(token)}">
                ${advancedInner}
            </div>

            <div class="flex justify-end space-x-2 pt-2 border-t border-gray-300">
                <button type="button" onclick="const mp = document.getElementById('modal-placeholder'); if(mp) mp.innerHTML=''; else document.getElementById('modal-container')?.remove();" class="px-3 py-1 border border-gray-400 bg-white hover:bg-gray-100 text-gray-700 font-medium cursor-pointer">
                    Cancel
                </button>
                <button type="submit" class="px-3 py-1 bg-gray-900 hover:bg-black text-white font-bold cursor-pointer">
                    Save
                </button>
            </div>
        </form>
    </div>
</div>`;
    }

    function applyHydratedAdvancedHtml(token, serverModalHtml) {
        const slot = document.querySelector(`#edit-item-advanced-slot[data-modal-token="${token}"]`);
        if (!slot) return;
        const detailsHtml = extractAdvancedDetailsHtml(serverModalHtml);
        if (!detailsHtml) return;
        const wasOpen = Boolean(slot.querySelector('details')?.open);
        slot.innerHTML = detailsHtml;
        if (wasOpen) {
            const nextDetails = slot.querySelector('details');
            if (nextDetails) nextDetails.open = true;
        }
        if (window.htmx) window.htmx.process(slot);
    }

    function hydrateEditModalAdvanced(editUrl, token) {
        if (!navigator.onLine) return;
        const cached = window.ShoppinPrefetch && window.ShoppinPrefetch.getCached(editUrl);
        if (cached && cached.html) {
            applyHydratedAdvancedHtml(token, cached.html);
            return;
        }

        const inflight = window.ShoppinPrefetch && window.ShoppinPrefetch.getInflight
            ? window.ShoppinPrefetch.getInflight(editUrl)
            : null;
        if (inflight) {
            inflight.then((entry) => {
                if (entry && entry.html) {
                    applyHydratedAdvancedHtml(token, entry.html);
                } else {
                    const slot = document.querySelector(`#edit-item-advanced-slot[data-modal-token="${token}"]`);
                    const st = slot?.querySelector('.edit-advanced-status');
                    if (st) st.textContent = 'History unavailable right now';
                }
            }).catch(() => {});
            return;
        }

        fetch(editUrl, {
            method: 'GET',
            credentials: 'same-origin',
            headers: {
                'HX-Request': 'true',
                'X-Client-Id': window.CLIENT_ID || 'client_web'
            }
        }).then(async (resp) => {
            const slot = document.querySelector(`#edit-item-advanced-slot[data-modal-token="${token}"]`);
            if (!slot) return;
            if (resp.ok) {
                const html = await resp.text();
                if (window.ShoppinPrefetch && window.ShoppinPrefetch.storeManual) {
                    window.ShoppinPrefetch.storeManual(editUrl, html, 12000);
                }
                applyHydratedAdvancedHtml(token, html);
            } else if (resp.status === 404) {
                const st = slot.querySelector('.edit-advanced-status');
                if (st) st.textContent = 'Item was merged or removed — refreshing list...';
                triggerToast('Item was already updated or merged — refreshing list...', { type: 'info' });
                const listEl = document.getElementById('shopping-list-content');
                const refreshUrl = listEl?.getAttribute('data-refresh-url');
                if (refreshUrl && window.ShoppinMorph) {
                    fetch(refreshUrl, {
                        credentials: 'same-origin',
                        headers: { 'HX-Request': 'true', 'HX-Target': 'shopping-list-content', 'X-Client-Id': window.CLIENT_ID || 'client_web' }
                    }).then((r) => (r.ok ? r.text() : '')).then((listHtml) => {
                        if (listHtml) window.ShoppinMorph.swapFromHtml('#shopping-list-content', listHtml);
                    }).catch(() => {});
                }
            } else {
                const st = slot.querySelector('.edit-advanced-status');
                if (st) st.textContent = 'History unavailable right now';
            }
        }).catch(() => {
            const slot = document.querySelector(`#edit-item-advanced-slot[data-modal-token="${token}"]`);
            const st = slot?.querySelector('.edit-advanced-status');
            if (st) st.textContent = 'History unavailable right now';
        });
    }

    function openInstantEditModal(editTrigger) {
        const placeholder = document.getElementById('modal-placeholder');
        if (!placeholder) return;

        const row = editTrigger.closest('.item-row');
        const rawHref = editTrigger.getAttribute('hx-get') || '';
        const urlMatch = rawHref.match(/\/item\/([a-zA-Z0-9_-]+)\/edit/);
        const rawId = (row && row.getAttribute('data-item-id')) || (urlMatch ? urlMatch[1] : '');
        if (!rawId) return;

        const resolvedId = (Q() && Q().tempIdMap && Q().tempIdMap.get(String(rawId))) || String(rawId);
        const isNumericId = /^\d+$/.test(resolvedId);
        const { groupBy, mode } = getListMeta();
        const editUrl = `/item/${resolvedId}/edit/?group_by=${encodeURIComponent(groupBy)}&mode=${encodeURIComponent(mode)}`;
        const itemData = row ? getRowData(row) : {
            id: resolvedId,
            name: '',
            amount: '1',
            unit: '',
            unitDisplay: '',
            category: '',
            aisle: '',
            brand: '',
            vendor: '',
            purpose: '',
            priority: false
        };

        const token = Q() ? Q().generateKey('editmodal') : `em_${Date.now()}`;
        const safeFetchUrl = (rawHref && rawHref.includes(`/item/${resolvedId}/edit/`)) ? rawHref : editUrl;
        const cachedEntry = isNumericId && window.ShoppinPrefetch
            ? (window.ShoppinPrefetch.getCached(safeFetchUrl) || window.ShoppinPrefetch.getCached(editUrl))
            : null;
        const cachedAdvancedHtml = cachedEntry && cachedEntry.html
            ? extractAdvancedDetailsHtml(cachedEntry.html)
            : '';

        // Mount immediately at 0ms so the very first click ALWAYS opens the dialog cleanly!
        placeholder.innerHTML = buildEditModalHtml(itemData, {
            resolvedId,
            groupBy,
            mode,
            token,
            isTemp: !isNumericId,
            isOnline: navigator.onLine,
            cachedAdvancedHtml
        });
        if (window.htmx) window.htmx.process(placeholder);
        const nameInput = document.getElementById('edit-item-name');
        if (nameInput) nameInput.focus();

        if (isNumericId && !cachedAdvancedHtml) {
            hydrateEditModalAdvanced(safeFetchUrl, token);
        }
    }

    function updateRowDetailsFromEdit(row, vals) {
        if (!row) return;
        const titleEl = row.querySelector('.item-title');
        if (titleEl && vals.name) titleEl.textContent = vals.name;
        if (vals.name) row.setAttribute('data-item-name', vals.name);

        const parsedAmt = parseQuickAddClient(vals.name || 'item', vals.amountText || '1', vals.priority);
        row.setAttribute('data-item-amount', parsedAmt.amountDisplay);
        row.setAttribute('data-item-unit', parsedAmt.unitDisplay || '');
        row.setAttribute('data-item-unit-display', parsedAmt.unitDisplay || '');
        row.setAttribute('data-item-category', vals.category || '');
        row.setAttribute('data-item-aisle', vals.aisle || '');
        row.setAttribute('data-item-brand', vals.brand || '');
        row.setAttribute('data-item-vendor', vals.vendor || '');
        row.setAttribute('data-item-purpose', vals.purpose || 'one-time purchase');
        row.setAttribute('data-priority', vals.priority ? 'true' : 'false');

        const qtyEl = row.querySelector('.item-qty, .item-title ~ span.whitespace-nowrap');
        if (qtyEl && vals.amountText) qtyEl.textContent = vals.amountText;

        const secondaryEl = row.querySelector('.item-secondary-details');
        if (secondaryEl) {
            const parts = [];
            if (vals.purpose) parts.push(`<span class="inline-block italic text-gray-600">For ${escapeHtml(vals.purpose)}</span>`);
            if (vals.brand) parts.push(`<span class="inline-block ml-1 italic text-gray-700">Brand: ${escapeHtml(vals.brand)}</span>`);
            if (vals.vendor) parts.push(`<span class="inline-block ml-1 italic text-gray-700">Vendor: ${escapeHtml(vals.vendor)}</span>`);
            parts.push(getCurrentAuditMeta().html);
            secondaryEl.innerHTML = parts.join('');
        }
        animateRow(row, '#dbeafe');
    }

    function handleOptimisticEditSave(form) {
        if (typeof form.reportValidity === 'function' && !form.reportValidity()) return;

        let actionUrl = form.getAttribute('hx-post') || form.getAttribute('action') || '';
        const match = actionUrl.match(/\/item\/([a-zA-Z0-9_-]+)\/edit/);
        const rawItemId = match ? match[1] : null;
        const itemId = rawItemId && Q()?.tempIdMap?.get(rawItemId) ? Q().tempIdMap.get(rawItemId) : rawItemId;
        if (rawItemId && itemId && rawItemId !== itemId) {
            actionUrl = actionUrl.replace(`/item/${rawItemId}/edit`, `/item/${itemId}/edit`);
        }
        const { groupBy, mode } = getListMeta();
        if (actionUrl && !actionUrl.includes('mode=')) {
            actionUrl += (actionUrl.includes('?') ? '&' : '?') + `mode=${encodeURIComponent(mode)}`;
        }
        const modeInput = form.querySelector('input[name="mode"]');
        if (modeInput) {
            modeInput.value = mode;
        }
        const groupInput = form.querySelector('input[name="group_by"]');
        if (groupInput && !groupInput.value) {
            groupInput.value = groupBy;
        }
        const body = Q().serializeForm(form);

        if (rawItemId) {
            const row = document.getElementById(`item-row-${itemId}`) || document.getElementById(`item-row-${rawItemId}`);
            if (row) {
                const editVals = {
                    name: form.querySelector('#edit-item-name')?.value?.trim() || '',
                    amountText: form.querySelector('#edit-item-amount')?.value?.trim() || '',
                    category: form.querySelector('#edit-item-category')?.value?.trim() || '',
                    aisle: form.querySelector('#edit-item-aisle')?.value?.trim() || '',
                    brand: form.querySelector('#edit-item-brand')?.value?.trim() || '',
                    vendor: form.querySelector('#edit-item-vendor')?.value?.trim() || '',
                    purpose: form.querySelector('#edit-item-purpose')?.value?.trim() || '',
                    priority: Boolean(form.querySelector('#edit-item-priority')?.checked)
                };
                updateRowDetailsFromEdit(row, editVals);

                // If edited to match another row in the same section, combine optimistically at 0ms
                const rowStatus = row.getAttribute('data-item-status') || 'NEED';
                const containerSel = rowStatus === 'NEED'
                    ? '#section-groups-container'
                    : (rowStatus === 'GOT' ? '#got-items-list' : '#pantry-items-list');
                const updatedData = getRowData(row);
                const dupMatch = findMatchingRowInContainer(containerSel, editVals.name, {
                    brand: editVals.brand,
                    vendor: editVals.vendor,
                    unit: updatedData?.unit || '',
                    excludeItemId: row.getAttribute('data-item-id')
                });
                if (dupMatch && dupMatch.getAttribute('data-item-status') === rowStatus) {
                    const oldGroupBlock = row.closest('.section-group-block');
                    row.remove();
                    if (rowStatus === 'NEED') {
                        adjustCount('need-items-count', -1);
                        if (oldGroupBlock) checkAndUpdateSectionEmptyState(oldGroupBlock);
                    } else if (rowStatus === 'GOT') {
                        adjustCount('got-items-count', -1);
                    } else {
                        adjustCount('pantry-items-count', -1);
                    }
                    mergeIntoExistingRowDom(dupMatch, updatedData);
                }
            }
        }

        // Cleanly close modal immediately after validation (replacing buggy 100ms timeout!)
        document.getElementById('modal-container')?.remove();
        const mp = document.getElementById('modal-placeholder');
        if (mp) mp.innerHTML = '';

        Q().enqueue(actionUrl, body, {
            itemId,
            type: 'edit_item',
            reconcileTarget: '#shopping-list-content',
            coalesceKey: itemId ? `edit:item:${itemId}` : null
        }, {
            onSuccess: (_, html, ctx) => {
                if (html && !ctx?.hasMoreWork && window.ShoppinMorph) {
                    window.ShoppinMorph.swapFromHtml('#shopping-list-content', html);
                }
            }
        });
    }

    // -------------------------------------------------------------------------
    // Quick Add Draft Persistence & In-Place Mode Switch Engine
    // -------------------------------------------------------------------------

    function getQuickAddDraft() {
        const nameEl = document.getElementById('add-item-name');
        if (!nameEl) {
            try {
                const raw = sessionStorage.getItem(QUICK_ADD_STORAGE_KEY);
                return raw ? JSON.parse(raw) : null;
            } catch (_) {
                return null;
            }
        }
        const activeEl = document.activeElement;
        const isQuickAddActive = activeEl && ['add-item-name', 'add-item-amount', 'add-item-brand', 'add-item-vendor', 'add-item-purpose'].includes(activeEl.id);
        return {
            name: nameEl.value || '',
            amount: document.getElementById('add-item-amount')?.value || '1',
            brand: document.getElementById('add-item-brand')?.value || '',
            vendor: document.getElementById('add-item-vendor')?.value || '',
            purpose: document.getElementById('add-item-purpose')?.value || '',
            priority: Boolean(nameEl.form?.querySelector('input[name="priority"]')?.checked),
            focusedId: isQuickAddActive ? activeEl.id : null,
            selectionStart: isQuickAddActive && typeof activeEl.selectionStart === 'number' ? activeEl.selectionStart : null,
            selectionEnd: isQuickAddActive && typeof activeEl.selectionEnd === 'number' ? activeEl.selectionEnd : null
        };
    }

    function saveQuickAddDraft(draft) {
        if (!draft) draft = getQuickAddDraft();
        if (!draft) return;
        const hasContent = Boolean(draft.name || draft.brand || draft.vendor || draft.purpose || draft.priority || (draft.amount && draft.amount !== '1'));
        try {
            if (hasContent) sessionStorage.setItem(QUICK_ADD_STORAGE_KEY, JSON.stringify(draft));
            else sessionStorage.removeItem(QUICK_ADD_STORAGE_KEY);
        } catch (_) {}
    }

    function clearQuickAddDraft() {
        try { sessionStorage.removeItem(QUICK_ADD_STORAGE_KEY); } catch (_) {}
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
                    try { elToFocus.setSelectionRange(draft.selectionStart, draft.selectionEnd); } catch (_) {}
                }
            }
        }
        renderQuickAddPreview();
    }

    function updateNavTabsStyling(targetMode) {
        if (window.ShoppinShell && typeof window.ShoppinShell.updateNavActiveState === 'function') {
            window.ShoppinShell.updateNavActiveState(targetMode === 'pantry' ? '/pantry-check/' : '/', targetMode === 'pantry' ? '' : '?mode=shopping');
        }
    }

    function getModeScrollAnchor() {
        const y = window.scrollY || window.pageYOffset || 0;
        const header = document.querySelector('header[role="banner"]');
        const headerHeight = (header ? header.offsetHeight : 0) + 10;
        let anchorItemId = null;
        let anchorOffset = 0;
        const rows = document.querySelectorAll('.item-row');
        for (let i = 0; i < rows.length; i++) {
            const rect = rows[i].getBoundingClientRect();
            if (rect.bottom > headerHeight && rect.top < window.innerHeight) {
                anchorItemId = rows[i].getAttribute('data-item-id');
                anchorOffset = rect.top;
                break;
            }
        }
        return { scrollY: y, anchorItemId, anchorOffset };
    }

    function applyModeScrollAnchor(anchor) {
        if (!anchor) return;
        if (anchor.anchorItemId) {
            const esc = window.CSS && window.CSS.escape ? window.CSS.escape(anchor.anchorItemId) : anchor.anchorItemId;
            const targetRow = document.querySelector(`.item-row[data-item-id="${esc}"]`);
            if (targetRow) {
                const delta = targetRow.getBoundingClientRect().top - anchor.anchorOffset;
                const newY = Math.max(0, (window.scrollY || 0) + delta);
                window.scrollTo({ top: newY, behavior: 'instant' });
                return;
            }
        }
        window.scrollTo({ top: anchor.scrollY, behavior: 'instant' });
    }

    function finishModeSwitch(targetMode, targetUrl, anchor, draft, pushHistory) {
        isSwitchingMode = false;
        if (modeSwitchResetTimer) { clearTimeout(modeSwitchResetTimer); modeSwitchResetTimer = null; }
        restoreQuickAddDraft(draft);
        const restoreScroll = () => applyModeScrollAnchor(anchor);
        restoreScroll();
        requestAnimationFrame(restoreScroll);
        setTimeout(() => {
            restoreScroll();
            try { sessionStorage.removeItem('shoppin_mode_anchor'); sessionStorage.removeItem('shoppin_mode_scroll'); } catch (_) {}
        }, 250);

        const pageTitle = targetMode === 'pantry' ? 'Pantry Check - Shoppin' : 'Shopping List - Shoppin';
        document.title = pageTitle;
        if (pushHistory && window.history && window.history.pushState) {
            window.history.pushState({ mode: targetMode, scrollY: anchor.scrollY }, pageTitle, targetUrl);
        }
        if (window.ShoppinShell) {
            window.ShoppinShell.clearNavTabPending?.();
            window.ShoppinShell.finishProgressBar?.();
        }
        updateNavTabsStyling(targetMode);
        initSortables();
        applyPresetListsCardState();
    }

    function performModeSwitch(targetMode, pushHistory = true) {
        if (isSwitchingMode) return;
        const listContent = document.getElementById('shopping-list-content');
        if (!listContent) return;

        isSwitchingMode = true;
        if (modeSwitchResetTimer) clearTimeout(modeSwitchResetTimer);
        modeSwitchResetTimer = setTimeout(() => { isSwitchingMode = false; }, 3500);

        const anchor = getModeScrollAnchor();
        const draft = getQuickAddDraft();
        saveQuickAddDraft(draft);

        const currentGroupBy = listContent.getAttribute('data-group-by') || 'category';
        const targetUrl = targetMode === 'pantry'
            ? `/pantry-check/?group_by=${encodeURIComponent(currentGroupBy)}`
            : `/?mode=shopping&group_by=${encodeURIComponent(currentGroupBy)}`;

        updateNavTabsStyling(targetMode);

        // If prefetched HTML is warm, apply immediately for 0ms mode switch
        const cached = window.ShoppinPrefetch && window.ShoppinPrefetch.getCached(targetUrl, 15000);
        if (cached && cached.html && window.ShoppinMorph) {
            window.ShoppinMorph.swapFromHtml('#shopping-list-content', cached.html);
            finishModeSwitch(targetMode, targetUrl, anchor, draft, pushHistory);
            return;
        }

        const pendingPath = targetMode === 'pantry' ? '/pantry-check/' : '/';
        const pendingSearch = targetMode === 'pantry' ? '' : '?mode=shopping';
        if (window.ShoppinShell) {
            window.ShoppinShell.setNavTabPending?.(pendingPath, pendingSearch);
            window.ShoppinShell.startProgressBar?.();
        }

        const inflight = window.ShoppinPrefetch && window.ShoppinPrefetch.getInflight
            ? window.ShoppinPrefetch.getInflight(targetUrl)
            : null;
        const fetchPromise = inflight
            ? inflight.then((entry) => (entry && entry.html ? entry.html : fetch(targetUrl, {
                credentials: 'same-origin',
                headers: {
                    'HX-Request': 'true',
                    'HX-Target': 'shopping-list-content',
                    'X-Client-Id': window.CLIENT_ID || 'client_web'
                }
            }).then((resp) => resp.text())))
            : fetch(targetUrl, {
                credentials: 'same-origin',
                headers: {
                    'HX-Request': 'true',
                    'HX-Target': 'shopping-list-content',
                    'X-Client-Id': window.CLIENT_ID || 'client_web'
                }
            }).then((resp) => resp.text());

        fetchPromise.then((html) => {
            if (window.ShoppinMorph) {
                window.ShoppinMorph.swapFromHtml('#shopping-list-content', html);
            } else {
                const wrap = document.createElement('div');
                wrap.innerHTML = html;
                const next = wrap.querySelector('#shopping-list-content') || wrap.firstElementChild;
                if (next && document.getElementById('shopping-list-content')) {
                    document.getElementById('shopping-list-content').replaceWith(next);
                }
            }
            finishModeSwitch(targetMode, targetUrl, anchor, draft, pushHistory);
        }).catch(() => {
            isSwitchingMode = false;
            if (window.ShoppinShell) {
                window.ShoppinShell.clearNavTabPending?.();
                window.ShoppinShell.finishProgressBar?.();
            }
            window.location.href = targetUrl;
        });
    }

    function handleModeSwitchClick(event, link) {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
        const listContent = document.getElementById('shopping-list-content');
        if (!listContent) return;
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
    // Store Picker, Preset Collapse, Sortables & Keyboard Reordering (Global)
    // -------------------------------------------------------------------------

    function openStorePickerModal(options) {
        const { groupBy, mode } = getListMeta();
        if (window.ShoppinAssets) window.ShoppinAssets.loadLeaflet().catch(() => {});

        const placeholder = document.getElementById('modal-placeholder');
        if (placeholder && window.ShoppinShell) {
            placeholder.innerHTML = window.ShoppinShell.renderStorePickerSkeletonHtml();
        }

        const payload = Object.assign({
            csrfmiddlewaretoken: getCsrf(),
            group_by: groupBy,
            mode
        }, options || {});

        if (window.htmx) {
            htmx.ajax('POST', '/nearest-store/', {
                target: '#modal-placeholder',
                swap: 'innerHTML',
                values: payload
            });
        }
    }

    let reorderDebounce = null;
    function triggerSectionReorder() {
        const sectionsContainer = document.getElementById('section-groups-container');
        if (!sectionsContainer) return;
        const groupNames = Array.from(sectionsContainer.querySelectorAll('.section-group-block')).map((el) => el.getAttribute('data-group-name'));
        const groupBy = sectionsContainer.getAttribute('data-group-by') || 'category';
        const params = new URLSearchParams();
        groupNames.forEach((n) => params.append('group_names[]', n));
        params.append('group_by', groupBy);
        params.append('csrfmiddlewaretoken', getCsrf());

        if (reorderDebounce) clearTimeout(reorderDebounce);
        reorderDebounce = setTimeout(() => {
            Q().enqueue('/reorder-sections/', params.toString(), { type: 'reorder_sections', coalesceKey: 'reorder:sections' });
        }, 120);
    }

    function triggerItemReorder() {
        const itemIds = Array.from(document.querySelectorAll('.sortable-group [data-item-id]'))
            .map((el) => el.getAttribute('data-item-id'))
            .filter((id) => id && /^\d+$/.test(id));
        if (!itemIds.length) return;
        const params = new URLSearchParams();
        itemIds.forEach((id) => params.append('item_ids[]', id));
        params.append('csrfmiddlewaretoken', getCsrf());

        if (reorderDebounce) clearTimeout(reorderDebounce);
        reorderDebounce = setTimeout(() => {
            Q().enqueue('/reorder/', params.toString(), { type: 'reorder_items', coalesceKey: 'reorder:items' });
        }, 120);
    }

    function initSortables() {
        if (typeof Sortable === 'undefined') return;
        const listEl = document.getElementById('shopping-list-content');
        if (listEl && listEl.getAttribute('data-can-write') === 'false') return;

        const sectionsContainer = document.getElementById('section-groups-container');
        if (sectionsContainer && !sectionsContainer._sortable) {
            sectionsContainer._sortable = new Sortable(sectionsContainer, {
                handle: '.section-drag-handle',
                draggable: '.section-group-block',
                filter: 'button, a, input, select, label, form',
                preventOnFilter: false,
                animation: 150,
                ghostClass: 'bg-gray-100',
                chosenClass: 'opacity-80',
                onEnd: triggerSectionReorder
            });
        }

        document.querySelectorAll('.sortable-group').forEach((group) => {
            if (group._sortable) return;
            group._sortable = new Sortable(group, {
                handle: '.drag-handle',
                draggable: '.item-row',
                filter: 'button, a, input, select, label, form',
                preventOnFilter: false,
                animation: 120,
                ghostClass: 'bg-gray-100',
                onEnd: triggerItemReorder
            });
        });
    }

    function togglePresetListsCard() {
        const body = document.getElementById('preset-lists-body');
        const caret = document.getElementById('preset-lists-caret');
        const header = document.querySelector('[aria-controls="preset-lists-body"]');
        if (!body) return;
        const isHidden = body.classList.toggle('hidden');
        if (caret) caret.style.transform = isHidden ? 'rotate(-90deg)' : '';
        if (header) header.setAttribute('aria-expanded', isHidden ? 'false' : 'true');
        const state = isHidden ? 'false' : 'true';
        try { localStorage.setItem('preset_lists_open', state); } catch (_) {}
        try { document.cookie = `preset_lists_open=${state}; path=/; max-age=31536000; SameSite=Lax`; } catch (_) {}
    }

    function applyPresetListsCardState() {
        try {
            let isOpen = localStorage.getItem('preset_lists_open');
            if (isOpen === null) {
                const match = document.cookie.match(/(^|;)\s*preset_lists_open=([^;]+)/);
                if (match) isOpen = match[2];
            }
            if (isOpen === 'false') {
                const body = document.getElementById('preset-lists-body');
                const caret = document.getElementById('preset-lists-caret');
                const header = document.querySelector('[aria-controls="preset-lists-body"]');
                if (body) body.classList.add('hidden');
                if (caret) caret.style.transform = 'rotate(-90deg)';
                if (header) header.setAttribute('aria-expanded', 'false');
            }
        } catch (_) {}
    }

    // -------------------------------------------------------------------------
    // Central Capture Interceptor (Shopping Status, Lock, Priority, Add, Edit)
    // -------------------------------------------------------------------------

    function interceptAction(event) {
        let target = event.target;
        if (!target) return;
        if (target.nodeType === 3) target = target.parentElement;
        if (!target || typeof target.closest !== 'function') return;

        // Instant visual press for Sort Order pills
        if (event.type === 'pointerdown') {
            const sortBtn = target.closest('[role="group"][aria-label="Sort order"] button');
            if (sortBtn) {
                const grp = sortBtn.closest('[role="group"]');
                if (grp) {
                    grp.querySelectorAll('button').forEach((b) => {
                        const active = b === sortBtn;
                        b.setAttribute('aria-pressed', active ? 'true' : 'false');
                        const isMiddle = Boolean(b.previousElementSibling);
                        b.className = `px-2.5 py-1 text-xs ${isMiddle ? 'border-l border-gray-400 ' : ''}${active ? 'bg-gray-800 text-white font-bold' : 'font-medium bg-white text-gray-700 hover:bg-gray-100'}`;
                    });
                }
            }
            return;
        }

        const modeSwitchLink = target.closest('[data-mode-switch]');
        if (modeSwitchLink && event.type === 'click') {
            handleModeSwitchClick(event, modeSwitchLink);
            return;
        }

        const editTrigger = target.closest('button[hx-get*="/edit/"]');
        if (editTrigger && event.type === 'click' && editTrigger.closest('#shopping-list-content')) {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            openInstantEditModal(editTrigger);
            return;
        }

        // Quick Add form submission
        const form = target.closest('form');
        if (form && event.type === 'submit' && form.querySelector('#add-item-name')) {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            handleOptimisticQuickAdd(form);
            return;
        }

        // Edit Item modal form submission (supports both canonical IDs and pending temp IDs)
        if (form && event.type === 'submit' && (form.getAttribute('hx-post') || '').match(/\/item\/[a-zA-Z0-9_-]+\/edit/)) {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            handleOptimisticEditSave(form);
            return;
        }

        const button = target.closest('button[type="submit"], button');
        const row = target.closest('.item-row');
        if (!row || !form) return;

        const actionUrl = form.getAttribute('action') || form.getAttribute('hx-post') || '';
        if (!actionUrl) return;

        const statusMatch = actionUrl.match(/\/item\/([a-zA-Z0-9_-]+)\/status\/(GOT|NEED|HAVE|DONT_NEED)/);
        const lockMatch = actionUrl.match(/\/item\/([a-zA-Z0-9_-]+)\/lock/);
        const prioMatch = actionUrl.match(/\/item\/([a-zA-Z0-9_-]+)\/priority/);
        if (!statusMatch && !lockMatch && !prioMatch) return;

        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        // Same-tick hardware/event bounce guard only (<15ms), preserving deliberate rapid taps
        if (Q().isDuplicateMicroTap(`shop:${actionUrl}`, 15)) return;
        window.ShoppinHaptics?.tap?.(10);

        const bodyParams = Q().serializeForm(form);
        if (statusMatch) {
            const itemId = statusMatch[1];
            const targetStatus = statusMatch[2];
            if (targetStatus === 'GOT') handleLocalGot(itemId, row);
            else if (targetStatus === 'NEED') handleLocalNeed(itemId, row);
            else handleLocalHaveOrSkip(itemId, row, targetStatus);
            Q().enqueue(actionUrl, bodyParams, {
                itemId,
                targetStatus,
                type: 'status',
                reconcileTarget: targetStatus === 'NEED' ? '#shopping-list-content' : null,
                coalesceKey: `status:item:${itemId}`
            });
        } else if (lockMatch) {
            const itemId = lockMatch[1];
            const nextLocked = handleLocalLockToggle(itemId, row, button);
            const lockBody = `${bodyParams}&target_locked=${nextLocked ? 'true' : 'false'}`;
            Q().enqueue(actionUrl, lockBody, { itemId, targetLocked: nextLocked, type: 'lock', coalesceKey: `lock:item:${itemId}` });
        } else if (prioMatch) {
            const itemId = prioMatch[1];
            const nextPriority = handleLocalPriorityToggle(itemId, row);
            const prioBody = `${bodyParams}&target_priority=${nextPriority ? 'true' : 'false'}`;
            Q().enqueue(actionUrl, prioBody, { itemId, targetPriority: nextPriority, type: 'priority', coalesceKey: `priority:item:${itemId}` });
        }
    }

    document.addEventListener('pointerdown', interceptAction, true);
    document.addEventListener('click', interceptAction, true);
    document.addEventListener('submit', interceptAction, true);

    document.addEventListener('input', (e) => {
        if (e.target && e.target.id && ['add-item-name', 'add-item-amount', 'add-item-brand', 'add-item-vendor', 'add-item-purpose'].includes(e.target.id)) {
            saveQuickAddDraft();
            renderQuickAddPreview();
        }
    });
    document.addEventListener('change', (e) => {
        if (e.target && e.target.name === 'priority' && e.target.form && e.target.form.querySelector('#add-item-name')) {
            saveQuickAddDraft();
            renderQuickAddPreview();
        }
    });

    // Keyboard Alt+Up / Alt+Down Reordering
    document.addEventListener('keydown', (evt) => {
        if (!evt.altKey || (evt.key !== 'ArrowUp' && evt.key !== 'ArrowDown')) return;
        const itemHandle = evt.target.closest?.('.drag-handle');
        if (itemHandle) {
            const row = itemHandle.closest('.item-row');
            if (!row) return;
            const parent = row.parentElement;
            if (evt.key === 'ArrowUp' && row.previousElementSibling) {
                evt.preventDefault();
                parent.insertBefore(row, row.previousElementSibling);
                itemHandle.focus();
                triggerItemReorder();
            } else if (evt.key === 'ArrowDown' && row.nextElementSibling) {
                evt.preventDefault();
                parent.insertBefore(row.nextElementSibling, row);
                itemHandle.focus();
                triggerItemReorder();
            }
            return;
        }
        const secHandle = evt.target.closest?.('.section-drag-handle');
        if (secHandle) {
            const secBlock = secHandle.closest('.section-group-block');
            if (!secBlock) return;
            const parent = secBlock.parentElement;
            if (evt.key === 'ArrowUp' && secBlock.previousElementSibling) {
                evt.preventDefault();
                parent.insertBefore(secBlock, secBlock.previousElementSibling);
                secHandle.focus();
                triggerSectionReorder();
            } else if (evt.key === 'ArrowDown' && secBlock.nextElementSibling) {
                evt.preventDefault();
                parent.insertBefore(secBlock.nextElementSibling, secBlock);
                secHandle.focus();
                triggerSectionReorder();
            }
        }
    });

    window.addEventListener('popstate', () => {
        const listContent = document.getElementById('shopping-list-content');
        if (!listContent) return;
        const targetMode = (window.location.pathname.includes('pantry-check') || window.location.search.includes('mode=pantry')) ? 'pantry' : 'shopping';
        const currentMode = listContent.getAttribute('data-mode') || 'shopping';
        if (targetMode !== currentMode) performModeSwitch(targetMode, false);
    });

    function initShoppingSync() {
        Q()?.updateSyncIndicators();
        Q()?.flushQueue();
        if (!isSwitchingMode) restoreQuickAddDraft();
        initSortables();
        applyPresetListsCardState();
    }

    document.addEventListener('DOMContentLoaded', initShoppingSync);
    document.addEventListener('htmx:afterSwap', (evt) => {
        if (evt.detail?.target?.id === 'shopping-list-content') initShoppingSync();
    });

    window.openStorePickerModal = openStorePickerModal;
    window.locateNearestStore = () => openStorePickerModal();
    window.triggerItemReorder = triggerItemReorder;
    window.triggerSectionReorder = triggerSectionReorder;
    window.initSortables = initSortables;
    window.syncCardState = applyPresetListsCardState;
    window.togglePresetListsCard = togglePresetListsCard;
    window.applyPresetListsCardState = applyPresetListsCardState;

    window.ShoppinSync = {
        getQueue: () => Q()?.getQueue() || [],
        flushQueue: () => Q()?.flushQueue(),
        updateSyncIndicator: () => Q()?.updateSyncIndicators(),
        handleModeSwitchClick,
        performModeSwitch
    };
})();
