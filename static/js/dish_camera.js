/**
 * Shoppin Dish Photo Capture (Native Mobile Camera + Live Desktop Webcam Modal)
 *
 * - On mobile / touch devices: triggers <input type="file" accept="image/*" capture="environment">
 *   for native camera app quality (autofocus, flash, HDR).
 * - On desktop browsers with a camera: opens an accessible live webcam viewfinder via
 *   navigator.mediaDevices.getUserMedia(), snaps JPEG frames into the target file input
 *   via DataTransfer, and always stops MediaStream tracks on snap/cancel/Escape.
 * - On camera-less desktops (or insecure contexts without mediaDevices): hides [data-camera-trigger]
 *   buttons so users see only the clean Upload Photo action.
 */
(function () {
    'use strict';

    let activeStream = null;
    let activeModalEl = null;
    let availableVideoDevices = [];
    let activeDeviceIndex = 0;
    let activeTargetCameraInputId = null;
    let activeTargetUploadInputId = null;

    function isMobileCameraDevice() {
        const ua = navigator.userAgent || '';
        const isMobileUa = /Android|iPhone|iPad|iPod|Mobile/i.test(ua);
        const isCoarsePointer = Boolean(
            window.matchMedia && window.matchMedia('(pointer: coarse)').matches
        );
        return isMobileUa || (isCoarsePointer && 'ontouchstart' in window);
    }

    function hasGetUserMedia() {
        return Boolean(
            navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === 'function'
        );
    }

    function stopActiveStream() {
        if (activeStream) {
            try {
                activeStream.getTracks().forEach((track) => {
                    try { track.stop(); } catch (_) {}
                });
            } catch (_) {}
            activeStream = null;
        }
    }

    function closeWebcamModal() {
        stopActiveStream();
        if (activeModalEl && activeModalEl.parentNode) {
            activeModalEl.remove();
        }
        activeModalEl = null;
        activeTargetCameraInputId = null;
        activeTargetUploadInputId = null;
    }

    function setCameraButtonsHidden(root, hidden) {
        const scope = root && root.querySelectorAll ? root : document;
        scope.querySelectorAll('[data-camera-trigger]').forEach((btn) => {
            btn.classList.toggle('hidden', Boolean(hidden));
        });
    }

    function syncCameraButtonsVisibility(root) {
        if (isMobileCameraDevice()) {
            setCameraButtonsHidden(root, false);
            return;
        }
        if (!hasGetUserMedia()) {
            setCameraButtonsHidden(root, true);
            return;
        }
        if (typeof navigator.mediaDevices.enumerateDevices !== 'function') {
            setCameraButtonsHidden(root, false);
            return;
        }
        navigator.mediaDevices.enumerateDevices()
            .then((devices) => {
                const videoInputs = (devices || []).filter((d) => d && d.kind === 'videoinput');
                availableVideoDevices = videoInputs;
                // Only hide when enumerateDevices returned entries and confirmed zero cameras
                const noCameraHardware = Array.isArray(devices) && devices.length > 0 && videoInputs.length === 0;
                setCameraButtonsHidden(root, noCameraHardware);
            })
            .catch(() => {
                // Keep visible and handle gracefully on click if enumerateDevices fails
                setCameraButtonsHidden(root, false);
            });
    }

    function showWebcamError(message) {
        if (!activeModalEl) return;
        const errBox = activeModalEl.querySelector('#dish-webcam-error');
        const videoWrap = activeModalEl.querySelector('#dish-webcam-video-wrap');
        const snapBtn = activeModalEl.querySelector('#dish-webcam-snap-btn');
        if (errBox) {
            errBox.textContent = message;
            errBox.classList.remove('hidden');
        }
        if (videoWrap) videoWrap.classList.add('hidden');
        if (snapBtn) snapBtn.disabled = true;
    }

    async function startCameraStream(deviceId) {
        stopActiveStream();
        if (!activeModalEl) return;

        const videoEl = activeModalEl.querySelector('#dish-webcam-video');
        const statusEl = activeModalEl.querySelector('#dish-webcam-status');
        const snapBtn = activeModalEl.querySelector('#dish-webcam-snap-btn');
        const errBox = activeModalEl.querySelector('#dish-webcam-error');
        const videoWrap = activeModalEl.querySelector('#dish-webcam-video-wrap');

        if (errBox) errBox.classList.add('hidden');
        if (videoWrap) videoWrap.classList.remove('hidden');
        if (statusEl) {
            statusEl.textContent = 'Starting camera...';
            statusEl.classList.remove('hidden');
        }
        if (snapBtn) snapBtn.disabled = true;

        const constraints = deviceId
            ? { video: { deviceId: { exact: deviceId }, width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false }
            : { video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false };

        let stream = null;
        try {
            stream = await navigator.mediaDevices.getUserMedia(constraints);
        } catch (firstErr) {
            if (!deviceId) {
                try {
                    stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
                } catch (secondErr) {
                    stream = null;
                    firstErr = secondErr;
                }
            }
            if (!stream) {
                const name = (firstErr && firstErr.name) || '';
                if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
                    showWebcamError('Camera permission was denied. Allow camera access in your browser or use Upload Photo instead.');
                } else if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
                    showWebcamError('No camera was found on this device. You can choose an image with Upload Photo instead.');
                } else if (name === 'NotReadableError' || name === 'TrackStartError') {
                    showWebcamError('Your camera appears to be in use by another app. Close it and try again, or use Upload Photo.');
                } else {
                    showWebcamError('Could not start camera right now. You can still attach an image with Upload Photo.');
                }
                return;
            }
        }

        // Modal may have been closed while waiting for permission
        if (!activeModalEl || !document.body.contains(activeModalEl)) {
            stream.getTracks().forEach((t) => { try { t.stop(); } catch (_) {} });
            return;
        }

        activeStream = stream;
        if (videoEl) {
            videoEl.srcObject = stream;
            try {
                await videoEl.play();
            } catch (_) {}
        }
        if (statusEl) statusEl.classList.add('hidden');
        if (snapBtn) snapBtn.disabled = false;

        // Refresh device list now that permission is granted so Switch Camera works on multi-cam laptops
        if (typeof navigator.mediaDevices.enumerateDevices === 'function') {
            navigator.mediaDevices.enumerateDevices().then((devices) => {
                availableVideoDevices = (devices || []).filter((d) => d && d.kind === 'videoinput');
                const switchBtn = activeModalEl && activeModalEl.querySelector('#dish-webcam-switch-btn');
                if (switchBtn) {
                    switchBtn.classList.toggle('hidden', availableVideoDevices.length < 2);
                }
            }).catch(() => {});
        }
    }

    function attachCapturedFileToInput(targetInput, file) {
        if (!targetInput || !file) return;
        const dt = new DataTransfer();
        if (targetInput.multiple && targetInput.files && targetInput.files.length) {
            Array.from(targetInput.files).forEach((existing) => dt.items.add(existing));
        }
        dt.items.add(file);
        targetInput.files = dt.files;
        targetInput.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function captureCurrentFrame() {
        if (!activeModalEl) return;
        const videoEl = activeModalEl.querySelector('#dish-webcam-video');
        const snapBtn = activeModalEl.querySelector('#dish-webcam-snap-btn');
        const uploadInput = activeTargetUploadInputId
            ? document.getElementById(activeTargetUploadInputId)
            : null;
        const cameraInput = activeTargetCameraInputId
            ? document.getElementById(activeTargetCameraInputId)
            : null;
        const targetInput = (uploadInput && uploadInput.multiple) ? uploadInput : cameraInput;
        if (!videoEl || !targetInput) {
            closeWebcamModal();
            return;
        }

        const width = videoEl.videoWidth || 1280;
        const height = videoEl.videoHeight || 720;
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        if (!ctx) {
            closeWebcamModal();
            return;
        }
        ctx.drawImage(videoEl, 0, 0, width, height);
        if (snapBtn) snapBtn.disabled = true;

        const finishWithBlob = (blob) => {
            if (!blob) {
                if (snapBtn) snapBtn.disabled = false;
                showWebcamError('Could not capture photo from camera. Please try again or use Upload Photo.');
                return;
            }
            const file = new File([blob], `dish_camera_${Date.now()}.jpg`, {
                type: 'image/jpeg',
                lastModified: Date.now()
            });
            attachCapturedFileToInput(targetInput, file);
            closeWebcamModal();
        };

        if (typeof canvas.toBlob === 'function') {
            canvas.toBlob(finishWithBlob, 'image/jpeg', 0.9);
        } else {
            try {
                const dataUrl = canvas.toDataURL('image/jpeg', 0.9);
                const bin = atob(dataUrl.split(',')[1]);
                const arr = new Uint8Array(bin.length);
                for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
                finishWithBlob(new Blob([arr], { type: 'image/jpeg' }));
            } catch (_) {
                finishWithBlob(null);
            }
        }
    }

    function openWebcamModal(cameraInputId, uploadInputId) {
        closeWebcamModal();
        activeTargetCameraInputId = cameraInputId;
        activeTargetUploadInputId = uploadInputId || null;
        activeDeviceIndex = 0;

        const modal = document.createElement('div');
        modal.id = 'dish-webcam-modal';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.setAttribute('aria-labelledby', 'dish-webcam-title');
        modal.className = 'fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-xs p-4';
        modal.innerHTML = `
            <div class="bg-white border-2 border-gray-800 shadow-2xl w-full max-w-lg flex flex-col rounded-none overflow-hidden">
                <div class="px-4 py-2.5 bg-gray-100 border-b border-gray-300 flex items-center justify-between">
                    <h3 id="dish-webcam-title" class="text-sm font-bold text-gray-900 flex items-center space-x-1.5">
                        <span aria-hidden="true">📷</span>
                        <span>Take Dish Photo</span>
                    </h3>
                    <button type="button"
                            id="dish-webcam-close-btn"
                            aria-label="Close camera"
                            class="text-gray-600 hover:text-black font-bold text-xl leading-none px-1 cursor-pointer">&times;</button>
                </div>

                <div class="p-4 space-y-3 bg-white">
                    <div id="dish-webcam-error" class="hidden p-3 bg-amber-50 border border-amber-300 text-amber-950 text-xs leading-relaxed"></div>

                    <div id="dish-webcam-video-wrap" class="relative bg-black border border-gray-300 aspect-[4/3] w-full flex items-center justify-center overflow-hidden">
                        <video id="dish-webcam-video" autoplay playsinline muted class="w-full h-full object-cover"></video>
                        <div id="dish-webcam-status" class="absolute inset-0 flex items-center justify-center bg-black/60 text-white text-xs font-medium">
                            Starting camera...
                        </div>
                    </div>

                    <div class="flex flex-wrap items-center justify-between gap-2 pt-1">
                        <div class="flex items-center gap-2">
                            <button type="button"
                                    id="dish-webcam-switch-btn"
                                    class="hidden border border-gray-400 bg-white hover:bg-gray-100 text-gray-800 font-medium px-2.5 py-1.5 text-xs rounded-none cursor-pointer">
                                🔄 Switch Camera
                            </button>
                            <button type="button"
                                    id="dish-webcam-fallback-upload-btn"
                                    class="border border-gray-300 bg-white hover:bg-gray-100 text-gray-700 font-medium px-2.5 py-1.5 text-xs rounded-none cursor-pointer">
                                🖼️ Upload File Instead
                            </button>
                        </div>
                        <div class="flex items-center gap-2">
                            <button type="button"
                                    id="dish-webcam-cancel-btn"
                                    class="border border-gray-300 bg-white hover:bg-gray-100 text-gray-700 font-medium px-3 py-1.5 text-xs rounded-none cursor-pointer">
                                Cancel
                            </button>
                            <button type="button"
                                    id="dish-webcam-snap-btn"
                                    disabled
                                    class="bg-gray-900 hover:bg-black disabled:opacity-50 text-white font-bold px-4 py-1.5 text-xs rounded-none cursor-pointer flex items-center space-x-1">
                                <span aria-hidden="true">📸</span>
                                <span>Snap Photo</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        modal.addEventListener('click', (evt) => {
            if (evt.target === modal) closeWebcamModal();
        });
        modal.querySelector('#dish-webcam-close-btn').addEventListener('click', closeWebcamModal);
        modal.querySelector('#dish-webcam-cancel-btn').addEventListener('click', closeWebcamModal);
        modal.querySelector('#dish-webcam-snap-btn').addEventListener('click', captureCurrentFrame);
        modal.querySelector('#dish-webcam-switch-btn').addEventListener('click', () => {
            if (availableVideoDevices.length < 2) return;
            activeDeviceIndex = (activeDeviceIndex + 1) % availableVideoDevices.length;
            const nextDev = availableVideoDevices[activeDeviceIndex];
            startCameraStream(nextDev ? nextDev.deviceId : null);
        });
        modal.querySelector('#dish-webcam-fallback-upload-btn').addEventListener('click', () => {
            const fallbackId = activeTargetUploadInputId || activeTargetCameraInputId;
            closeWebcamModal();
            const el = fallbackId ? document.getElementById(fallbackId) : null;
            if (el) el.click();
        });

        document.body.appendChild(modal);
        activeModalEl = modal;
        startCameraStream(null);
    }

    function openTakePhoto(cameraInputId, uploadInputId) {
        const camInput = document.getElementById(cameraInputId);
        if (!camInput) return;

        // Mobile devices launch native camera directly via capture="environment"
        if (isMobileCameraDevice() || !hasGetUserMedia()) {
            camInput.click();
            return;
        }

        openWebcamModal(cameraInputId, uploadInputId);
    }

    // Intercept Escape in capture phase so closing webcam does NOT dismiss the underlying Rating Modal
    document.addEventListener('keydown', (evt) => {
        if (evt.key === 'Escape' && activeModalEl) {
            evt.preventDefault();
            evt.stopPropagation();
            evt.stopImmediatePropagation();
            closeWebcamModal();
        }
    }, true);

    window.addEventListener('pagehide', closeWebcamModal);
    document.addEventListener('DOMContentLoaded', () => syncCameraButtonsVisibility(document));
    document.addEventListener('htmx:afterSettle', (evt) => {
        syncCameraButtonsVisibility(evt.detail && evt.detail.target ? evt.detail.target : document);
    });

    window.ShoppinDishCamera = {
        openTakePhoto,
        closeWebcamModal,
        syncCameraButtonsVisibility,
        isMobileCameraDevice
    };
})();
