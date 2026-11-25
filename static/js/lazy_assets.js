/**
 * Shoppin Lazy Asset Loader
 *
 * Defers heavy third-party map & dial picker bundles (Leaflet.js, MDTimePicker)
 * out of initial page render so pages parse instantaneously, pre-warming seamlessly
 * on hover/focus intent and resolving once on demand.
 */
(function () {
    'use strict';

    const LEAFLET_CSS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
    const LEAFLET_CSS_SRI = 'sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=';
    const LEAFLET_JS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    const LEAFLET_JS_SRI = 'sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=';

    const TIMEPICKER_CSS = 'https://cdn.jsdelivr.net/npm/@dmuy/timepicker@2.0.2/dist/mdtimepicker.min.css';
    const TIMEPICKER_JS = 'https://cdn.jsdelivr.net/npm/@dmuy/timepicker@2.0.2/dist/mdtimepicker.min.js';

    let leafletPromise = null;
    let timePickerPromise = null;

    function loadStylesheet(href, integrity) {
        return new Promise((resolve) => {
            const existing = document.querySelector(`link[rel="stylesheet"][href="${href}"]`);
            if (existing) {
                resolve();
                return;
            }
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = href;
            if (integrity) {
                link.integrity = integrity;
                link.crossOrigin = '';
            }
            link.onload = () => resolve();
            link.onerror = () => resolve();
            document.head.appendChild(link);
        });
    }

    function loadScript(src, integrity) {
        return new Promise((resolve, reject) => {
            const existing = document.querySelector(`script[src="${src}"]`);
            if (existing && existing.dataset.loaded === '1') {
                resolve();
                return;
            }
            const script = document.createElement('script');
            script.src = src;
            script.async = true;
            if (integrity) {
                script.integrity = integrity;
                script.crossOrigin = '';
            }
            script.onload = () => {
                script.dataset.loaded = '1';
                resolve();
            };
            script.onerror = (err) => {
                script.remove();
                reject(err);
            };
            document.head.appendChild(script);
        });
    }

    function loadLeaflet() {
        if (typeof window.L !== 'undefined') {
            return Promise.resolve(window.L);
        }
        if (leafletPromise) {
            return leafletPromise;
        }
        leafletPromise = Promise.all([
            loadStylesheet(LEAFLET_CSS, LEAFLET_CSS_SRI),
            loadScript(LEAFLET_JS, LEAFLET_JS_SRI)
        ]).then(() => window.L).catch((err) => {
            leafletPromise = null;
            throw err;
        });
        return leafletPromise;
    }

    function loadTimePicker() {
        if (typeof window.mdtimepicker !== 'undefined') {
            return Promise.resolve(window.mdtimepicker);
        }
        if (timePickerPromise) {
            return timePickerPromise;
        }
        timePickerPromise = Promise.all([
            loadStylesheet(TIMEPICKER_CSS),
            loadScript(TIMEPICKER_JS)
        ]).then(() => window.mdtimepicker).catch((err) => {
            timePickerPromise = null;
            throw err;
        });
        return timePickerPromise;
    }

    function warmAssetForTarget(target) {
        if (!target || typeof target.closest !== 'function') return;
        if (target.closest('[onclick*="openStorePickerModal"], #store-selector-select, [hx-post*="nearest-store"]')) {
            loadLeaflet().catch(() => {});
        }
        if (target.closest('[hx-get*="schedule-modal"], [onclick*="triggerClockDialPicker"], .occurrence-picker-block')) {
            loadTimePicker().catch(() => {});
        }
    }

    document.addEventListener('pointerenter', (e) => warmAssetForTarget(e.target), true);
    document.addEventListener('focusin', (e) => warmAssetForTarget(e.target), true);
    document.addEventListener('pointerdown', (e) => warmAssetForTarget(e.target), { capture: true, passive: true });

    window.ShoppinAssets = {
        loadLeaflet,
        loadTimePicker
    };
})();
