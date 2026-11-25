/**
 * Shoppin Keyboard Shortcuts, Power-User Navigation & Subtle Touch Haptics
 *
 * - `/` focuses primary Quick-Add or Search input (outside form controls)
 * - `Alt+1..5` switches primary navigation tabs instantaneously
 * - `?` opens an accessible keyboard shortcuts legend modal
 * - Optional tactile micro-haptics for Android/touch grocery check-offs
 */
(function () {
    'use strict';

    function prefersReducedMotion() {
        return Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    }

    function tapHaptic(ms = 10) {
        if (prefersReducedMotion()) return;
        try {
            if (typeof navigator.vibrate === 'function') {
                navigator.vibrate(ms);
            }
        } catch (_) {}
    }

    function isEditableElement(el) {
        if (!el) return false;
        const tag = (el.tagName || '').toUpperCase();
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
        return Boolean(el.isContentEditable);
    }

    function hasOpenModal() {
        const placeholder = document.getElementById('modal-placeholder');
        if (placeholder && placeholder.children.length > 0) return true;
        return Boolean(document.querySelector('[role="dialog"]:not(.hidden)'));
    }

    function openShortcutsModal() {
        const placeholder = document.getElementById('modal-placeholder');
        if (!placeholder) return;
        const existing = document.getElementById('keyboard-shortcuts-modal');
        if (existing) {
            placeholder.innerHTML = '';
            return;
        }
        placeholder.innerHTML = `
            <div id="keyboard-shortcuts-modal" role="dialog" aria-modal="true" aria-labelledby="shortcuts-modal-title"
                 onclick="if(event.target === this) document.getElementById('modal-placeholder').innerHTML = ''"
                 class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px] p-4">
                <div class="bg-white border border-gray-400 shadow-2xl max-w-md w-full p-5 space-y-3 text-xs rounded-none">
                    <div class="flex items-center justify-between border-b border-gray-300 pb-2">
                        <h3 id="shortcuts-modal-title" class="font-bold text-sm uppercase tracking-tight text-gray-900 flex items-center gap-1.5">
                            <span aria-hidden="true">⌨️</span>
                            <span>Keyboard Shortcuts</span>
                        </h3>
                        <button type="button" onclick="document.getElementById('modal-placeholder').innerHTML = ''" aria-label="Close dialog"
                                class="text-gray-700 hover:text-black font-bold text-lg leading-none px-1">
                            <span aria-hidden="true">&times;</span>
                        </button>
                    </div>
                    <div class="divide-y divide-gray-200 border border-gray-200 bg-gray-50/50">
                        <div class="flex items-center justify-between px-3 py-2">
                            <span class="text-gray-800">Focus Quick Add or Search bar</span>
                            <kbd class="px-2 py-0.5 bg-white border border-gray-300 font-mono text-[11px] font-bold">/</kbd>
                        </div>
                        <div class="flex items-center justify-between px-3 py-2">
                            <span class="text-gray-800">Switch tabs (Shopping, Pantry, Meal Plan, Recipes, Presets)</span>
                            <kbd class="px-2 py-0.5 bg-white border border-gray-300 font-mono text-[11px] font-bold">Alt + 1..5</kbd>
                        </div>
                        <div class="flex items-center justify-between px-3 py-2">
                            <span class="text-gray-800">Move focused item or aisle section up / down</span>
                            <kbd class="px-2 py-0.5 bg-white border border-gray-300 font-mono text-[11px] font-bold">Alt + ↑ / ↓</kbd>
                        </div>
                        <div class="flex items-center justify-between px-3 py-2">
                            <span class="text-gray-800">Flag High Priority while typing item</span>
                            <kbd class="px-2 py-0.5 bg-white border border-gray-300 font-mono text-[11px] font-bold">Add ! or ^</kbd>
                        </div>
                        <div class="flex items-center justify-between px-3 py-2">
                            <span class="text-gray-800">Close active dialog or menu</span>
                            <kbd class="px-2 py-0.5 bg-white border border-gray-300 font-mono text-[11px] font-bold">Esc</kbd>
                        </div>
                    </div>
                    <div class="flex justify-end pt-1">
                        <button type="button" onclick="document.getElementById('modal-placeholder').innerHTML = ''"
                                class="px-3 py-1 bg-gray-900 hover:bg-black text-white font-semibold">
                            Got it
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    function handleGlobalShortcuts(e) {
        if (e.ctrlKey || e.metaKey) return;

        // Alt+1..5 primary tab jumps
        if (e.altKey && !e.shiftKey && ['1', '2', '3', '4', '5'].includes(e.key)) {
            const idx = parseInt(e.key, 10) - 1;
            const navLinks = document.querySelectorAll('nav[aria-label="Primary Navigation"] a');
            const targetLink = navLinks[idx];
            if (targetLink) {
                e.preventDefault();
                targetLink.click();
            }
            return;
        }

        if (isEditableElement(e.target) || hasOpenModal()) return;

        if (e.key === '/') {
            const searchTarget = (
                document.getElementById('add-item-name') ||
                document.getElementById('recipe-search-input') ||
                document.getElementById('archive-search-input') ||
                document.querySelector('input[type="text"]:not([disabled])')
            );
            if (searchTarget) {
                e.preventDefault();
                searchTarget.focus({ preventScroll: false });
                if (typeof searchTarget.select === 'function' && searchTarget.value) {
                    searchTarget.select();
                }
            }
        } else if (e.key === '?') {
            e.preventDefault();
            openShortcutsModal();
        }
    }

    document.addEventListener('keydown', handleGlobalShortcuts);

    window.ShoppinHaptics = { tap: tapHaptic };
    window.openShortcutsModal = openShortcutsModal;
})();
