/* ============================================
   Electronic Circuit Chatbot - Main JavaScript
   ============================================ */

const API_BASE = '';  // Same origin

// ── State ──
let isProcessing = false;
/** True while POST /api/chat/simulate/stream is in flight (separate from chat SSE). */
let simulateRequestInFlight = false;
let lastCircuitData = null;
let currentCircuitId = null;
let currentTab = 'schematic';
let waveformChart = null;
let lastWaveformPayload = null;
/** Full last simulation API payload (analysis, gain_metrics, …). */
let lastSimulationResult = null;
/** Metadata from last simulation (frequency, source_params, …) for display resampling. */
let lastWaveformSimMeta = null;
/** Stashed request payload until SSE result arrives (frequency may not be in result body). */
let pendingWaveformSimMeta = null;
/** Current x-axis display range in seconds.  null = auto-fit. */
let waveformTimeRange = { startS: null, endS: null };
/** Last applied smoothness plan (points/cycle, total display points). */
let lastWaveformSmoothPlan = null;
const FRONTEND_BUILD = '20260608wf20ms';

/**
 * Độ mịn waveform — công thức bắt buộc:
 *   Points = TimeRange × f × N
 *   TimeRange: cửa sổ hiển thị (giây), f: Hz, N: độ phân giải (điểm/chu kỳ).
 */
const WF_SMOOTH = {
    RESOLUTION: 128,
    MIN_PPC: 32,
    MIN_TOTAL: 64,
    /** Giới hạn điểm vẽ Chart.js (tránh stack overflow khi spread Math.max). */
    MAX_TOTAL: 16384,
};

function arrayMin(values) {
    let m = Infinity;
    for (const v of values) {
        const n = Number(v);
        if (Number.isFinite(n) && n < m) m = n;
    }
    return Number.isFinite(m) ? m : NaN;
}

function arrayMax(values) {
    let m = -Infinity;
    for (const v of values) {
        const n = Number(v);
        if (Number.isFinite(n) && n > m) m = n;
    }
    return Number.isFinite(m) ? m : NaN;
}

function traceTimeMaxS(trace) {
    const xs = trace?.x;
    if (!Array.isArray(xs) || !xs.length) return 0;
    const last = Number(xs[xs.length - 1]);
    if (Number.isFinite(last)) return last;
    return arrayMax(xs);
}

/** Max transient window (seconds) — must match backend transient_window.MAX_TRAN_STOP_S */
const MAX_TRAN_STOP_S = 0.02;
/** Max display / custom range (ms) */
const MAX_WAVEFORM_MS = 20;

function parseSpiceTimeSeconds(value) {
    if (value == null || value === '') return null;
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const text = String(value).trim().toLowerCase();
    const m = text.match(/^([+-]?\d*\.?\d+(?:e[+-]?\d+)?)\s*([a-z]*)$/i);
    if (!m) return null;
    const n = Number(m[1]);
    const unit = m[2] || 's';
    const scale = { s: 1, ms: 1e-3, us: 1e-6, ns: 1e-9, ps: 1e-12, fs: 1e-15 };
    if (!(unit in scale) || !Number.isFinite(n)) return null;
    return n * scale[unit];
}

function extractFrequencyHzFromCircuit(core) {
    if (!core || typeof core !== 'object') return null;
    const sp = core.source_params;
    const candidates = [core.input_frequency_hz, core.frequency_hz, sp?.frequency, sp?.frequency_hz];
    for (const raw of candidates) {
        const f = Number(raw);
        if (Number.isFinite(f) && f > 0) return f;
    }
    return null;
}

function formatSpiceTimeSeconds(seconds) {
    if (!Number.isFinite(seconds)) return '0.02';
    if (seconds < 0.001) return `${Math.round(seconds * 1e6)}us`;
    if (seconds < 1) return `${Math.round(seconds * 1e3)}ms`;
    return String(seconds);
}

function clampWaveformEndMs(endMs, startMs = 0) {
    const start = Math.max(0, Number(startMs) || 0);
    let end = Number(endMs);
    if (!Number.isFinite(end)) return start + MAX_WAVEFORM_MS;
    end = Math.min(MAX_WAVEFORM_MS, Math.max(start + 0.001, end));
    return end;
}

/**
 * Luôn ép mô phỏng 5 s và đồng bộ tran_* trên payload + circuit_data.
 * Backend sẽ tính tran_step theo Points = TimeRange × f × N.
 */
function ensureSimulationWindow(core, payload) {
    if (!payload || typeof payload !== 'object') return;
    const stop = formatSpiceTimeSeconds(MAX_TRAN_STOP_S);
    const start = '0';

    payload.tran_stop = stop;
    payload.tran_start = start;
    payload.analysis_type = payload.analysis_type || 'transient';

    const cd = payload.circuit_data || core;
    if (cd && typeof cd === 'object') {
        cd.tran_stop = stop;
        cd.tran_start = start;
        cd.analysis_type = cd.analysis_type || 'transient';
        if (!payload.circuit_data) payload.circuit_data = cd;
        if (cd.source_params && !payload.source_params) {
            payload.source_params = cd.source_params;
        }
    }

    payload.analysis = {
        ...(payload.analysis || {}),
        type: 'transient',
        step: payload.tran_step || cd?.tran_step || payload.analysis?.step || '10us',
        stop,
        start,
    };
}
let currentSessionId = null;
let activePcbProgressCloser = null;

function clearCircuitArtifacts() {
    closeActivePcbProgressStream();
    lastCircuitData = null;
    currentCircuitId = null;
    window._lastCircuitData = null;
    window._lastKicadSch = null;
    window._lastKicadSchUrl = null;
    window._lastPcbContent = null;
    window._pcbReady = false;
    window._pcbRendered = false;
    window.__schematicUpToDateCircuitId = null;

    const schematicPlaceholder = document.getElementById('schematicPlaceholder');
    if (schematicPlaceholder) {
        schematicPlaceholder.style.display = 'block';
        schematicPlaceholder.innerHTML = '<i class="fas fa-project-diagram fa-4x"></i><p>Sơ đồ mạch sẽ hiển thị ở đây sau khi tạo mạch</p>';
    }

    const pcbPlaceholder = document.getElementById('pcbPlaceholder');
    if (pcbPlaceholder) {
        pcbPlaceholder.style.display = 'block';
        pcbPlaceholder.innerHTML = '<i class="fas fa-drafting-compass fa-4x"></i><p>PCB layout sẽ hiển thị ở đây</p>';
    }
}

function setDownloadUrl(downloadUrl) {
    const value = String(downloadUrl || '').trim();
    window._lastKicadSchUrl = value || null;
}

// ── DOM Elements ──
const chatMessages = document.getElementById('chatMessages');
const chatInput = document.getElementById('chatInput');
const btnSend = document.getElementById('btnSend');
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const processingTime = document.getElementById('processingTime');
const suggestions = document.getElementById('suggestions');
const detailPanel = document.getElementById('detailPanel');
const modelSelector = document.getElementById('modelSelector');
const modelDropdownToggle = document.getElementById('modelDropdownToggle');
const modelDropdownMenu = document.getElementById('modelDropdownMenu');
const modelDropdownLabel = document.getElementById('modelDropdownLabel');
let selectedModelTier = 'fast';

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
    checkHealth();
    setupEventListeners();
    autoResize(chatInput);
    initPanelResizer();
    initWelcomeOverlay();
    initThemeToggle();
    initWaveformToolbar();
});

// ── Theme toggle (light/dark) ──
const THEME_STORAGE_KEY = 'elpis-theme';

function getActiveTheme() {
    return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}

/** KiCanvas theme ids (built-ins + elpis-light patch in static/kicanvas/kicanvas.js). */
const KICANVAS_THEME_BY_APP = {
    light: 'elpis-light', // white PCB + light schematic (KiCad palette)
    dark: 'witchhazel',
};

function getKiCanvasThemeName() {
    return getActiveTheme() === 'light'
        ? KICANVAS_THEME_BY_APP.light
        : KICANVAS_THEME_BY_APP.dark;
}

function configureKiCanvasEmbed(kicanvas) {
    kicanvas.setAttribute('controls', 'full');
    kicanvas.setAttribute('theme', getKiCanvasThemeName());
    kicanvas.classList.add('elpis-kicanvas-embed');
    kicanvas.style.width = '100%';
    kicanvas.style.height = '100%';
    kicanvas.style.minHeight = '450px';
    kicanvas.style.display = 'block';
    kicanvas.style.border = 'none';
    kicanvas.style.borderRadius = '8px';
}

function applyKiCanvasThemeToViewer(viewerEl, themeName) {
    if (!viewerEl) return;
    if (viewerEl.getAttribute('theme') !== themeName) {
        viewerEl.setAttribute('theme', themeName);
    }
    if (viewerEl.viewer?.loaded && typeof viewerEl.update_theme === 'function') {
        viewerEl.update_theme();
        viewerEl.viewer.paint?.();
        viewerEl.viewer.draw?.();
    }
}

function applyKiCanvasThemeToEmbed(embedEl, themeName) {
    if (!embedEl) return;
    if (embedEl.getAttribute('theme') !== themeName) {
        embedEl.setAttribute('theme', themeName);
    }
    const root = embedEl.shadowRoot;
    if (!root) return;
    root.querySelectorAll('kc-board-app, kc-schematic-app').forEach((app) => {
        if (app.getAttribute('theme') !== themeName) {
            app.setAttribute('theme', themeName);
        }
    });
    root.querySelectorAll('kc-board-viewer, kc-schematic-viewer').forEach((viewer) => {
        applyKiCanvasThemeToViewer(viewer, themeName);
    });
}

function syncKiCanvasEmbedsTheme() {
    const themeName = getKiCanvasThemeName();
    document.querySelectorAll('kicanvas-embed').forEach((embed) => {
        applyKiCanvasThemeToEmbed(embed, themeName);
    });
}

function scheduleKiCanvasThemeApply(embedEl) {
    const themeName = getKiCanvasThemeName();
    const applyWhenReady = () => applyKiCanvasThemeToEmbed(embedEl, themeName);
    applyWhenReady();
    requestAnimationFrame(applyWhenReady);
    setTimeout(applyWhenReady, 120);
    setTimeout(applyWhenReady, 400);
}

function reloadKiCanvasEmbedsForThemeChange() {
    syncKiCanvasEmbedsTheme();
    if (window._lastPcbContent) {
        window._pcbRendered = false;
        if (currentTab === 'pcb') {
            renderPCBKiCanvas();
        }
    }
}

// Background colors used by the transition veil. We can't rely on
// `getComputedStyle(root, '--bg-main')` directly because the variable swaps
// to the new theme as soon as we set `data-theme` — so the veil would tint
// to the NEW bg instead of the OLD. These constants snapshot the canonical
// surface color for each theme.
const THEME_BG_SNAPSHOTS = {
    dark:  '#0b0b0b',
    light: '#f4f7fb',
};

// Run the theme-swap wash overlay: fade a veil tinted with the OLD theme's
// background up to 55% opacity, swap CSS variables, then fade the veil out.
// Net visual effect: light→dark = gradually darkens; dark→light = gradually
// brightens. Total duration ≈ 650ms.
function _runThemeTransitionVeil(prev, next) {
    const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduceMotion) return;

    let veil = document.querySelector('.theme-transition-veil');
    if (!veil) {
        veil = document.createElement('div');
        veil.className = 'theme-transition-veil';
        document.body.appendChild(veil);
    }
    // Tint the veil with the OLD background so the "wash" reads as a fade
    // from current → target.
    veil.style.background = THEME_BG_SNAPSHOTS[prev] || THEME_BG_SNAPSHOTS.dark;
    // Force reflow before adding the active class so the opacity transition
    // actually animates from 0 to its target.
    void veil.offsetWidth;
    veil.classList.add('is-active');

    setTimeout(() => {
        if (!veil) return;
        veil.classList.remove('is-active');
        setTimeout(() => {
            if (veil && veil.parentNode) veil.parentNode.removeChild(veil);
        }, 600);
    }, 280);
}

function applyTheme(theme, options = {}) {
    const next = theme === 'light' ? 'light' : 'dark';
    const root = document.documentElement;
    const previous = root.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    const isSwap = options.animate !== false && previous !== next;

    if (isSwap) {
        // Enable smooth color transitions on every themed surface for the
        // duration of the swap (CSS rule scoped to `html.theme-transitioning`).
        root.classList.add('theme-transitioning');
        _runThemeTransitionVeil(previous, next);
    }

    root.setAttribute('data-theme', next);
    try { localStorage.setItem(THEME_STORAGE_KEY, next); } catch (_) { /* noop */ }

    document.querySelectorAll('.theme-toggle').forEach((btn) => {
        const label = next === 'dark' ? 'Chuyển sang chế độ sáng' : 'Chuyển sang chế độ tối';
        btn.setAttribute('aria-label', label);
        btn.setAttribute('title', label);
    });

    if (window.ElpisCircuitAnimation && typeof window.ElpisCircuitAnimation.setTheme === 'function') {
        try { window.ElpisCircuitAnimation.setTheme(next); } catch (_) { /* noop */ }
    }

    reloadKiCanvasEmbedsForThemeChange();

    if (isSwap) {
        // Drop the transition class once the slowest property (background)
        // has settled — keeps default snappy behaviour for other state changes.
        setTimeout(() => {
            root.classList.remove('theme-transitioning');
        }, 700);
    }
}

function initThemeToggle() {
    applyTheme(getActiveTheme());

    const buttons = document.querySelectorAll('.theme-toggle');
    buttons.forEach((btn) => {
        btn.addEventListener('click', () => {
            const next = getActiveTheme() === 'dark' ? 'light' : 'dark';
            applyTheme(next);
        });
    });
}

// ── Typewriter effect ──
// Append `text` into `element` one character at a time. A blinking caret
// (rendered via .typewriter-cursor) sits at the tail of the typed text and
// disappears once typing completes. Resolves with the final element.
//
//   text     — string to type out (plain text only, never HTML)
//   element  — target DOM node (its innerHTML is overwritten)
//   speed    — milliseconds per character (default 28)
//   opts.cursor   — set to false to suppress the blinking caret
//   opts.onDone   — callback fired once typing completes
//   opts.signal   — optional AbortSignal to cancel mid-type
function typewriter(text, element, speed = 28, opts = {}) {
    if (!element) return Promise.resolve(null);
    const str = String(text == null ? '' : text);
    const wantCursor = opts.cursor !== false;
    const onDone = typeof opts.onDone === 'function' ? opts.onDone : null;
    const signal = opts.signal || null;

    return new Promise((resolve) => {
        element.classList.add('is-typing');
        element.classList.remove('typewriter-done');
        element.innerHTML = '';

        const textNode = document.createTextNode('');
        element.appendChild(textNode);

        let cursorEl = null;
        if (wantCursor) {
            cursorEl = document.createElement('span');
            cursorEl.className = 'typewriter-cursor';
            element.appendChild(cursorEl);
        }

        let i = 0;
        let cancelled = false;
        const finish = () => {
            element.classList.remove('is-typing');
            element.classList.add('typewriter-done');
            if (cursorEl && cursorEl.parentNode) {
                cursorEl.parentNode.removeChild(cursorEl);
            }
            if (onDone) {
                try { onDone(element); } catch (_) { /* noop */ }
            }
            resolve(element);
        };

        if (signal) {
            signal.addEventListener('abort', () => {
                if (cancelled) return;
                cancelled = true;
                textNode.data = str;
                finish();
            }, { once: true });
        }

        const tick = () => {
            if (cancelled) return;
            if (i >= str.length) {
                finish();
                return;
            }
            textNode.data += str.charAt(i);
            i += 1;
            setTimeout(tick, Math.max(4, speed));
        };
        setTimeout(tick, Math.max(4, speed));
    });
}

// Expose globally so other modules (or future console tooling) can call it.
window.typewriter = typewriter;

// ── Circuit Animation Lifecycle ──
let _circuitAnimationActive = false;
let _heroIntroTimeline = null;
let _ctaPulseTween = null;
let _titleTypewriterTimer = null;
let _titleTypewriterController = null;

function _hasGsap() {
    return typeof window.gsap !== 'undefined';
}

// Loop the welcome title typewriter forever: type "Elpis AI" → wait
// `idleMs` (3–4s feels natural) → clear + retype. Each pass uses the same
// blinking caret. Aborted via stopTitleTypewriterLoop().
function startTitleTypewriterLoop(titleEl, text, speed, idleMs) {
    if (!titleEl || typeof typewriter !== 'function') return;
    stopTitleTypewriterLoop();

    const controller = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    _titleTypewriterController = controller;
    const signal = controller ? controller.signal : null;

    const tick = () => {
        if (signal && signal.aborted) return;
        typewriter(text, titleEl, speed, {
            cursor: true,
            signal: signal,
            onDone: () => {
                if (signal && signal.aborted) return;
                _titleTypewriterTimer = setTimeout(tick, idleMs);
            },
        });
    };
    tick();
}

function stopTitleTypewriterLoop() {
    if (_titleTypewriterTimer != null) {
        clearTimeout(_titleTypewriterTimer);
        _titleTypewriterTimer = null;
    }
    if (_titleTypewriterController) {
        try { _titleTypewriterController.abort(); } catch (_) { /* noop */ }
        _titleTypewriterController = null;
    }
}

function startCircuitAnimation() {
    if (_circuitAnimationActive) return;
    if (!window.ElpisCircuitAnimation || typeof window.ElpisCircuitAnimation.start !== 'function') return;
    const overlay = document.getElementById('welcomeOverlay');
    const svgEl = document.getElementById('circuitBgSvg');
    if (!overlay || !svgEl) return;
    if (overlay.classList.contains('is-hidden')) return;

    try {
        window.ElpisCircuitAnimation.setTheme(getActiveTheme());
        window.ElpisCircuitAnimation.start(svgEl);
        _circuitAnimationActive = true;
    } catch (err) {
        console.warn('Circuit animation failed to start:', err);
    }
}

function stopCircuitAnimation() {
    if (!_circuitAnimationActive) return;
    if (!window.ElpisCircuitAnimation || typeof window.ElpisCircuitAnimation.stop !== 'function') return;
    try { window.ElpisCircuitAnimation.stop(); } catch (_) { /* noop */ }
    _circuitAnimationActive = false;
}

// Run the welcome-hero intro:
//   school header → "Elpis AI" typewriter (blinking caret) → subtitle →
//   circuit traces begin → info card → CTA appears + pulses gently.
// Falls back to a no-op + plain typewriter on title if GSAP isn't loaded.
function runHeroIntroTimeline() {
    const overlay = document.getElementById('welcomeOverlay');
    if (!overlay || overlay.classList.contains('is-hidden')) return;

    const header   = overlay.querySelector('.welcome-header');
    const title    = overlay.querySelector('#welcomeTitle');
    const subtitle = overlay.querySelector('.welcome-subtitle');
    const info     = overlay.querySelector('.welcome-info-card');
    const cta      = overlay.querySelector('#welcomeStartBtn');
    const foot     = overlay.querySelector('.welcome-foot');

    // Snapshot the original title string before we clear it for the
    // typewriter pass. Use a non-breaking space so "Elpis" and "AI" stay on
    // the same baseline regardless of viewport width.
    const titleText = (title?.textContent || 'Elpis AI').trim().replace(/\s+/g, '\u00A0');
    const charSpeed = 110;             // ms per character while typing
    const titleIdleMs = 3500;          // pause between consecutive typewriter passes
    const titleTypeDurSec = (titleText.length * charSpeed) / 1000;

    // Prepare title for the typewriter: clear content but keep the element
    // visible so the caret has somewhere to anchor.
    if (title) {
        title.textContent = '';
        title.style.opacity = '1';
    }

    if (!_hasGsap()) {
        // No GSAP: run the looping typewriter inline + spawn circuits now.
        if (title) {
            startTitleTypewriterLoop(title, titleText, charSpeed, titleIdleMs);
        }
        startCircuitAnimation();
        return;
    }

    // Kill any previous run (e.g. user navigates back to the overlay).
    if (_heroIntroTimeline) {
        try { _heroIntroTimeline.kill(); } catch (_) { /* noop */ }
        _heroIntroTimeline = null;
    }
    if (_ctaPulseTween) {
        try { _ctaPulseTween.kill(); } catch (_) { /* noop */ }
        _ctaPulseTween = null;
    }

    // Stage every animated element at 0 opacity (title stays opaque — its
    // characters appear progressively via typewriter, not a fade).
    const stage = [header, subtitle, info, cta, foot].filter(Boolean);
    window.gsap.set(stage, { opacity: 0 });
    if (cta)  window.gsap.set(cta,  { y: 14 });
    if (info) window.gsap.set(info, { y: 10 });

    const tl = window.gsap.timeline({
        defaults: { ease: 'power2.out' },
        onComplete: () => {
            // After the intro finishes, gently pulse the CTA forever so the
            // user has a constant visual hint to click. Stored separately so
            // dismiss() can kill it.
            if (cta) {
                _ctaPulseTween = window.gsap.to(cta, {
                    boxShadow: '0 20px 48px rgba(78,168,255,0.45), 0 0 0 10px rgba(78,168,255,0.08)',
                    scale: 1.025,
                    duration: 1.1,
                    ease: 'sine.inOut',
                    yoyo: true,
                    repeat: -1,
                });
            }
        },
    });

    tl.to(header, { opacity: 1, duration: 0.55 }, 0.05)
      // Kick off the typewriter loop as a side-effect, then absorb the first
      // pass's duration with an empty tween so subsequent timeline items
      // wait until the title is fully typed once before they animate in.
      .add(() => {
          if (title) {
              startTitleTypewriterLoop(title, titleText, charSpeed, titleIdleMs);
          }
      }, '+=0.15')
      .to({}, { duration: titleTypeDurSec + 0.15 })
      .to(subtitle, { opacity: 1, duration: 0.55 }, '-=0.1')
      // Kick off circuit traces just before the info card animates in so the
      // background visibly comes alive while the foreground is still settling.
      .add(() => startCircuitAnimation(), '-=0.25')
      .to(info, { opacity: 1, y: 0, duration: 0.5 }, '-=0.15')
      .to(cta,  { opacity: 1, y: 0, duration: 0.5 }, '-=0.1')
      .to(foot, { opacity: 1, duration: 0.4 }, '-=0.25');

    _heroIntroTimeline = tl;
}

// ── Welcome Overlay ──
// Dismiss the full-screen empty-state hero with a smooth GSAP fade-out, kill
// every running animation, and free up GPU for KiCanvas behind the overlay.
function initWelcomeOverlay() {
    const overlay = document.getElementById('welcomeOverlay');
    const startBtn = document.getElementById('welcomeStartBtn');
    if (!overlay || !startBtn) return;

    runHeroIntroTimeline();

    const dismiss = () => {
        if (overlay.classList.contains('is-leaving')) return;
        overlay.classList.add('is-leaving');

        // Stop the title typewriter loop right away so it doesn't keep
        // mutating the (about to be hidden) title element.
        stopTitleTypewriterLoop();

        // Always stop the spawn loop immediately so no new traces appear
        // during the fade-out (existing ones keep fading via GSAP/CSS).
        const finalize = () => {
            overlay.classList.add('is-hidden');
            stopCircuitAnimation();
            stopTitleTypewriterLoop();
            if (_heroIntroTimeline) {
                try { _heroIntroTimeline.kill(); } catch (_) { /* noop */ }
                _heroIntroTimeline = null;
            }
            if (_ctaPulseTween) {
                try { _ctaPulseTween.kill(); } catch (_) { /* noop */ }
                _ctaPulseTween = null;
            }
        };

        if (_hasGsap()) {
            // Kill the CTA pulse first so the fade-out tween doesn't fight
            // a yoyo'd scale/box-shadow change still in flight.
            if (_ctaPulseTween) {
                try { _ctaPulseTween.kill(); } catch (_) { /* noop */ }
                _ctaPulseTween = null;
            }
            if (_heroIntroTimeline) {
                try { _heroIntroTimeline.kill(); } catch (_) { /* noop */ }
                _heroIntroTimeline = null;
            }
            window.gsap.to(overlay, {
                opacity: 0,
                scale: 1.04,
                duration: 0.55,
                ease: 'power2.inOut',
                onComplete: finalize,
            });
        } else {
            // CSS fallback (existing transition rules).
            const fallback = setTimeout(finalize, 700);
            overlay.addEventListener(
                'transitionend',
                (e) => {
                    if (e.target !== overlay || e.propertyName !== 'opacity') return;
                    clearTimeout(fallback);
                    finalize();
                },
                { once: true }
            );
        }

        if (typeof chatInput !== 'undefined' && chatInput) {
            try { chatInput.focus(); } catch (_) { /* noop */ }
        }
    };

    startBtn.addEventListener('click', dismiss);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !overlay.classList.contains('is-hidden')) {
            dismiss();
        }
    });

    // Safety net: stop the spawn loop if the tab goes hidden while the
    // overlay is already dismissed.
    document.addEventListener('visibilitychange', () => {
        if (document.hidden && overlay.classList.contains('is-hidden')) {
            stopCircuitAnimation();
        }
    });
}

function setupEventListeners() {
    // Send on Enter (Shift+Enter for newline)
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Send button
    btnSend.addEventListener('click', sendMessage);

    setupModelDropdown();

    // Auto-resize textarea
    chatInput.addEventListener('input', () => autoResize(chatInput));

    // Info button
    document.getElementById('btnInfo').addEventListener('click', showSystemInfo);

    // Schematic toolbar buttons
    const btnDownload = document.getElementById('btnDownloadSch');
    if (btnDownload) {
        btnDownload.addEventListener('click', async () => {
            try {
                if (window._lastKicadSchUrl) {
                    const resp = await fetch(window._lastKicadSchUrl, { cache: 'no-store' });
                    if (resp.ok) {
                        const text = await resp.text();
                        window._lastKicadSch = text;
                    }
                }

                if (window._lastKicadSch) {
                    const blob = new Blob([window._lastKicadSch], { type: 'text/plain' });
                    const a = document.createElement('a');
                    a.href = URL.createObjectURL(blob);
                    a.download = (window._lastTemplateId || 'circuit') + '.kicad_sch';
                    a.click();
                }
            } catch (err) {
                console.error('Schematic download failed:', err);
            }
        });
    }
    
    const btnDownloadPCB = document.getElementById('btnDownloadPCB');
    if (btnDownloadPCB) {
        btnDownloadPCB.addEventListener('click', () => {
            if (window._lastPcbContent) {
                const blob = new Blob([window._lastPcbContent], { type: 'text/plain' });
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = (window._lastTemplateId || 'circuit') + '.kicad_pcb';
                a.click();
            }
        });
    }
    
    const btnCompList = document.getElementById('btnShowComponents');
    if (btnCompList) {
        btnCompList.addEventListener('click', () => {
            const panel = document.getElementById('componentListPanel');
            if (panel) panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
        });
    }

    const btnRunSim = document.getElementById('btnRunSim');
    if (btnRunSim) {
        btnRunSim.addEventListener('click', runSimulationFromCurrentCircuit);
    }
}

function setupModelDropdown() {
    if (!modelSelector || !modelDropdownToggle || !modelDropdownMenu) {
        return;
    }

    const modeOptions = Array.from(modelDropdownMenu.querySelectorAll('.mode-option'));

    const applyMode = (mode) => {
        selectedModelTier = String(mode || 'fast').toLowerCase();
        if (modelDropdownLabel) {
            modelDropdownLabel.textContent = selectedModelTier.charAt(0).toUpperCase() + selectedModelTier.slice(1);
        }
        for (const opt of modeOptions) {
            const isActive = opt.dataset.mode === selectedModelTier;
            opt.classList.toggle('is-active', isActive);
            opt.setAttribute('aria-selected', String(isActive));
        }
    };

    const closeMenu = () => {
        modelSelector.classList.remove('open');
        modelDropdownToggle.setAttribute('aria-expanded', 'false');
    };

    modelDropdownToggle.addEventListener('click', () => {
        const isOpen = modelSelector.classList.toggle('open');
        modelDropdownToggle.setAttribute('aria-expanded', String(isOpen));
    });

    for (const opt of modeOptions) {
        opt.addEventListener('click', () => {
            applyMode(opt.dataset.mode || 'fast');
            closeMenu();
        });
    }

    document.addEventListener('click', (event) => {
        if (!modelSelector.contains(event.target)) {
            closeMenu();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeMenu();
        }
    });

    applyMode('fast');
}

// ── Health Check ──
async function checkHealth() {
    try {
        const resp = await fetch(`${API_BASE}/api/chat/health`);
        if (resp.ok) {
            statusDot.classList.add('connected');
            statusDot.classList.remove('error');
            statusText.textContent = 'Connected';
        } else {
            throw new Error('API not responding');
        }
    } catch (e) {
        statusDot.classList.add('error');
        statusDot.classList.remove('connected');
        statusText.textContent = 'Disconnected';
    }
}

// ── Send Message ──
async function requestChatReply(text, options = {}) {
    const messageText = String(text || '').trim();
    if (!messageText || isProcessing) return null;

    const includeUserMessage = options.includeUserMessage !== false;
    const sessionIdOverride = String(options.sessionIdOverride || '').trim();
    const sessionIdForRequest = sessionIdOverride || currentSessionId || undefined;

    // Clear stale analysis data immediately so the panel doesn't show
    // results from the previous request while the new one is loading.
    clearAnalysisPanel();

    const userMessageEl = includeUserMessage
        ? addMessage(messageText, 'user', { editable: true })
        : null;

    const typingId = showTyping();
    isProcessing = true;
    btnSend.disabled = true;

    try {
        const resp = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: messageText,
                mode: selectedModelTier,
                session_id: sessionIdForRequest,
            }),
        });

        if (!resp.ok || !resp.body) {
            const data = await resp.json().catch(() => ({}));
            removeTyping(typingId);
            const errMsg = data.detail?.message || data.detail || 'Lỗi server';
            addMessage(`Lỗi: ${errMsg}`, 'bot');
            return null;
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let currentEvent = 'message';
        let currentData = [];
        const finalData = {};

        const dispatchBlock = (block) => {
            let eventName = currentEvent;
            const dataLines = [];

            for (const rawLine of block.split(/\r?\n/)) {
                const line = rawLine.trim();
                if (!line) continue;
                if (line.startsWith('event:')) {
                    eventName = line.slice(6).trim() || eventName;
                } else if (line.startsWith('data:')) {
                    dataLines.push(line.slice(5).trim());
                }
            }

            if (!dataLines.length) {
                currentEvent = 'message';
                currentData = [];
                return;
            }

            let payload;
            try {
                payload = JSON.parse(dataLines.join('\n'));
            } catch {
                payload = { raw: dataLines.join('\n') };
            }

            if (eventName === 'thinking') {
                statusText.textContent = 'Processing';
                currentEvent = 'message';
                currentData = [];
                return;
            }

            if (eventName === 'circuit_ready') {
                if (payload && typeof payload === 'object') {
                    if (payload.circuit_id) finalData.circuit_id = payload.circuit_id;
                    if (payload.circuit_data) finalData.circuit_data = payload.circuit_data;
                    if (payload.sch_url) finalData.sch_url = payload.sch_url;
                    if (payload.spice_url) finalData.spice_url = payload.spice_url;
                    if (payload.ngspice_url) finalData.ngspice_url = payload.ngspice_url;
                    if (payload.session_id) finalData.session_id = payload.session_id;
                    if (payload.user_message_id) finalData.user_message_id = payload.user_message_id;
                    if (payload.assistant_message_id) finalData.assistant_message_id = payload.assistant_message_id;
                    if (payload.sch_url) setDownloadUrl(payload.sch_url);
                    // Run Simulation reads lastCircuitData — set as soon as IR arrives (do not wait for `text` / stream end).
                    if (payload.circuit_data && typeof payload.circuit_data === 'object') {
                        if (payload.circuit_id) currentCircuitId = payload.circuit_id;
                        lastCircuitData = {
                            circuit_id: payload.circuit_id,
                            circuit_data: payload.circuit_data,
                            sch_url: payload.sch_url,
                            spice_url: payload.spice_url,
                            ngspice_url: payload.ngspice_url,
                            session_id: payload.session_id,
                            user_message_id: payload.user_message_id,
                            assistant_message_id: payload.assistant_message_id,
                        };
                        try {
                            window.__schematicUpToDateCircuitId = payload.circuit_id || null;
                            updateSchematicPanel(lastCircuitData);
                        } catch (err) {
                            console.error('[circuit_ready] updateSchematicPanel failed:', err);
                        }
                    }
                }
                currentEvent = 'message';
                currentData = [];
                return;
            }

            if (eventName === 'render_ready') {
                if (payload && typeof payload === 'object') {
                    if (payload.circuit_id) finalData.circuit_id = payload.circuit_id;
                    if (payload.sch_url) finalData.sch_url = payload.sch_url;
                    if (payload.pcb_url) finalData.pcb_url = payload.pcb_url;
                    if (payload.ngspice_url) finalData.ngspice_url = payload.ngspice_url;
                    if (payload.spice_url) finalData.spice_url = payload.spice_url;
                    if (payload.sch_url) setDownloadUrl(payload.sch_url);
                }
                currentEvent = 'message';
                currentData = [];
                return;
            }

            if (eventName === 'text') {
                if (payload && typeof payload === 'object') {
                    Object.assign(finalData, payload);
                    handleBotResponse(payload);
                }
                currentEvent = 'message';
                currentData = [];
                return;
            }

            if (eventName === 'error') {
                const message = payload?.message || payload?.error || 'Lỗi xử lý chat';
                addMessage(`Lỗi: ${message}`, 'bot');
                currentEvent = 'message';
                currentData = [];
                return;
            }

            currentEvent = 'message';
            currentData = [];
        };

        while (true) {
            const { value, done } = await reader.read();
            if (!done) {
                buffer += decoder.decode(value, { stream: true });
            } else {
                buffer += decoder.decode();
            }

            const parts = buffer.split(/\r?\n\r?\n/);
            buffer = parts.pop() || '';

            for (const part of parts) {
                dispatchBlock(part);
            }

            if (done) {
                if (buffer.trim()) {
                    dispatchBlock(buffer);
                }
                break;
            }
        }

        removeTyping(typingId);
        if (finalData.session_id && typeof finalData.session_id === 'string' && finalData.session_id.trim()) {
            currentSessionId = finalData.session_id.trim();
        }
        if (userMessageEl) {
            bindUserMessageMetadata(userMessageEl, {
                messageId: finalData.user_message_id,
                sessionId: finalData.session_id || currentSessionId,
                chatId: finalData.chat_id || finalData.session_id || currentSessionId,
            });
        }
        return finalData;
    } catch (e) {
        removeTyping(typingId);
        addMessage(`Không thể kết nối đến server: ${e.message}`, 'bot');
        return null;
    } finally {
        isProcessing = false;
        btnSend.disabled = false;
        chatInput.focus();
    }
}

async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text || isProcessing) return;

    chatInput.value = '';
    autoResize(chatInput);

    const result = await requestChatReply(text, { includeUserMessage: true });
    if (!result) return;

    if (result.circuit_id) {
        currentCircuitId = result.circuit_id;
    }

    if (result.circuit_data && typeof result.circuit_data === 'object') {
        lastCircuitData = result;
        const rid = result.circuit_id || '';
        if (!window.__schematicUpToDateCircuitId || window.__schematicUpToDateCircuitId !== rid) {
            window.__schematicUpToDateCircuitId = rid || null;
            updateSchematicPanel(result);
        }
    }
}

async function sendSimulation(rawText) {
    const payload = buildSimulationPayload(rawText);
    if (!payload.netlist) {
        addMessage('Không tạo được netlist mô phỏng.', 'bot');
        return;
    }

    await sendSimulationPayload(payload, rawText);
}

function formatApiErrorDetail(detail) {
    if (detail == null) return '';
    if (typeof detail === 'string') return detail;
    if (typeof detail === 'object') {
        if (detail.message) return String(detail.message);
        try {
            return JSON.stringify(detail);
        } catch {
            return String(detail);
        }
    }
    return String(detail);
}

async function sendSimulationPayload(payload, userLabel = 'Run Simulation') {
    if (!payload) {
        addMessage('❌ Không có payload mô phỏng.', 'bot');
        return;
    }
    const hasNetlist = String(payload.netlist || '').trim().length > 0;
    const cd = payload.circuit_data;
    const hasCircuitData = cd && typeof cd === 'object' && !Array.isArray(cd);
    if (!hasNetlist && !hasCircuitData) {
        addMessage(
            '❌ Thiếu netlist và circuit_data — backend không thể tổng hợp deck (cần components + nets).',
            'bot',
        );
        return;
    }

    if (simulateRequestInFlight) {
        addMessage('⏳ Đang chạy mô phỏng khác — chờ hoàn tất.', 'bot');
        return;
    }

    addMessage(userLabel, 'user');
    chatInput.value = '';
    autoResize(chatInput);

    const typingId = showTyping();
    simulateRequestInFlight = true;
    const btnRunSimEl = document.getElementById('btnRunSim');
    if (btnRunSimEl) btnRunSimEl.disabled = true;

    pendingWaveformSimMeta = {
        circuit_data: payload.circuit_data || null,
        source_params: payload.source_params || payload.circuit_data?.source_params || null,
    };

    try {
        const resp = await fetch(`${API_BASE}/api/chat/simulate/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        removeTyping(typingId);
        if (!resp.ok || !resp.body) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(formatApiErrorDetail(err.detail) || `HTTP ${resp.status}`);
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { value, done } = await reader.read();
            if (!done) {
                buffer += decoder.decode(value, { stream: true });
            } else {
                buffer += decoder.decode();
            }

            let parts = buffer.split(/\r?\n\r?\n/);
            buffer = parts.pop() || '';
            for (const block of parts) {
                handleSimulationSseBlock(block);
            }

            if (done) {
                if (buffer.trim()) {
                    handleSimulationSseBlock(buffer);
                }
                break;
            }
        }
    } catch (e) {
        removeTyping(typingId);
        console.error('[simulate]', e);
        addMessage(`❌ Mô phỏng thất bại: ${e.message}`, 'bot');
    }

    simulateRequestInFlight = false;
    if (btnRunSimEl) btnRunSimEl.disabled = false;
    chatInput.focus();
}

async function runSimulationFromCurrentCircuit() {
    const base = lastCircuitData?.circuit_data || lastCircuitData;
    if (!base) {
        addMessage('❌ Chưa có mạch để mô phỏng. Hãy generate mạch trước.', 'bot');
        return;
    }

    const core = base.circuit_data || base;
    const payload = buildSimulationPayloadFromCircuit(base);

    // Always pass circuit_id so backend can fall back to spice_deck artifact
    const resolvedCircuitId = lastCircuitData?.circuit_id || currentCircuitId || base?.circuit_id || '';
    if (resolvedCircuitId) {
        payload.circuit_id = resolvedCircuitId;
        if (payload.circuit_data && typeof payload.circuit_data === 'object') {
            payload.circuit_data.circuit_id = resolvedCircuitId;
        }
    }

    // ── Robust netlist resolution ───────────────────────────────────────
    // If the chat response exposed a `spice_url`, fetch its content and ship
    // it directly to /simulate. This bypasses both the DB artifact lookup and
    // the server-side synthesis fallback, avoiding the
    // "circuit_data does not contain spice_netlist" failure for circuits
    // that the backend already compiled (e.g. op-amp + LM358).
    const cachedSpiceUrl = lastCircuitData?.spice_url || lastCircuitData?.ngspice_url || '';
    if (!String(payload.netlist || '').trim() && cachedSpiceUrl) {
        try {
            const deckResp = await fetch(`${API_BASE}${cachedSpiceUrl}`, { cache: 'no-store' });
            if (deckResp.ok) {
                const deck = (await deckResp.text() || '').trim();
                if (deck) {
                    payload.netlist = deck;
                    if (payload.circuit_data && typeof payload.circuit_data === 'object') {
                        payload.circuit_data.spice_netlist = deck;
                    }
                }
            } else {
                console.warn('[simulate] spice_url fetch returned', deckResp.status);
            }
        } catch (err) {
            console.warn('[simulate] could not fetch cached spice_url:', err);
        }
    }

    const hasIrShape =
        Array.isArray(core?.components) &&
        core.components.length > 0 &&
        Array.isArray(core?.nets) &&
        core.nets.length > 0;

    const hasNetlist = String(payload.netlist || '').trim().length > 0;

    // Client-side SPICE string may be empty (unknown component types / IR-only schema).
    // Backend still compiles from circuit_data via NgspiceCompilerService when components+nets exist.
    if (!hasNetlist && !hasIrShape) {
        addMessage(
            '❌ Không thể dựng netlist từ mạch hiện tại (thiếu components/nets trong circuit_data).',
            'bot',
        );
        return;
    }

    if (!hasNetlist && hasIrShape) {
        payload.circuit_data = core;
        payload.analysis_type = payload.analysis_type || String(core.analysis_type || 'transient');
        payload.tran_step = payload.tran_step || core.tran_step || '10us';
        ensureSimulationWindow(core, payload);
        if (Array.isArray(core.nodes_to_monitor) && core.nodes_to_monitor.length) {
            payload.nodes_to_monitor = core.nodes_to_monitor;
        } else if (Array.isArray(core.probe_nodes) && core.probe_nodes.length) {
            payload.nodes_to_monitor = core.probe_nodes.map((n) => {
                const s = String(n || '').trim();
                const low = s.toLowerCase();
                if (low.startsWith('v(') || low.startsWith('i(')) return s;
                return `v(${s})`;
            });
        }
        if (core.source_params && typeof core.source_params === 'object') {
            payload.source_params = core.source_params;
        }
    }

    ensureSimulationWindow(core, payload);
    await sendSimulationPayload(payload, '▶ Run Simulation');
}

function handleSimulationSseBlock(block) {
    if (!block) return;

    let eventName = 'message';
    const dataLines = [];
    const lines = block.split(/\r?\n/);
    for (const line of lines) {
        if (line.startsWith('event:')) {
            eventName = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
            dataLines.push(line.slice(5).trim());
        }
    }

    const dataRaw = dataLines.join('\n');
    if (!dataRaw) return;
    let payload;
    try {
        payload = JSON.parse(dataRaw);
    } catch {
        return;
    }

    if (eventName === 'progress') {
        processingTime.textContent = payload.message || payload.status || '';
        return;
    }
    if (eventName === 'error') {
        const bits = [payload.message || payload.detail || 'unknown error'];
        if (payload.diagnostic_note) bits.push(payload.diagnostic_note);
        if (payload.failure_phase) bits.push(`(${payload.failure_phase})`);
        addMessage(`❌ Mô phỏng thất bại: ${bits.filter(Boolean).join(' — ')}`, 'bot');
        return;
    }
    if (eventName === 'result') {
        addMessage(`✅ Mô phỏng hoàn tất: ${payload.points || 0} samples`, 'bot');
        processingTime.textContent = `⏱ ${Number(payload.execution_time_ms || 0).toFixed(0)}ms`;
        lastSimulationResult = payload;
        lastWaveformPayload = payload.waveform || null;
        lastWaveformSimMeta = extractWaveformSimMeta(payload);
        lastWaveformSmoothPlan = null;
        waveformTimeRange = { startS: null, endS: null };
        initWaveformToolbar();
        const toolbar = ensureWaveformToolbarElement();
        if (toolbar) {
            toolbar.querySelectorAll('.wf-preset-btn').forEach((b) => b.classList.remove('wf-preset-active'));
            const autoBtn = toolbar.querySelector('[data-ms="auto"]');
            if (autoBtn) autoBtn.classList.add('wf-preset-active');
            const s = document.getElementById('wfRangeStart');
            const e = document.getElementById('wfRangeEnd');
            if (s) s.value = '0';
            if (e) e.value = '';
        }
        try {
            updateWaveformDebug(payload.waveform, {
                points: payload.points,
                execution_time_ms: payload.execution_time_ms,
                event: 'result',
            });
            switchTab('waveform');
            requestAnimationFrame(() => {
                try {
                    renderWaveform(payload.waveform);
                } catch (renderErr) {
                    console.error('[waveform render]', renderErr);
                    addMessage(`⚠️ Mô phỏng xong nhưng không vẽ được waveform: ${renderErr.message}`, 'bot');
                }
            });
        } catch (postErr) {
            console.error('[waveform post-process]', postErr);
            addMessage(`⚠️ Mô phỏng xong nhưng xử lý waveform lỗi: ${postErr.message}`, 'bot');
        }
    }
}

function buildSimulationPayload(rawText) {
    const text = rawText.trim();
    const body = text.replace(/^\/(simulate|sim)\s*/i, '');

    let netlist = body;
    const fenced = body.match(/```(?:spice|ngspice|cir)?\s*([\s\S]*?)```/i);
    if (fenced) {
        netlist = fenced[1].trim();
    }

    const payload = {
        netlist,
        probes: ['v(out)', 'v(in)'],
        nodes_to_monitor: ['v(out)', 'v(in)'],
        analysis_type: 'transient',
        analysis: {
            type: 'transient',
            step: '20us',
            stop: formatSpiceTimeSeconds(MAX_TRAN_STOP_S),
            start: '0',
        },
    };
    ensureSimulationWindow(null, payload);
    return payload;
}

function buildSimulationPayloadFromCircuit(circuitData) {
    const root = circuitData || {};
    const core = root.circuit_data || root;
    const providedNetlist = String(core?.spice_netlist || core?.netlist || core?.ngspice_netlist || '').trim();
    const providedNodes = Array.isArray(core?.nodes_to_monitor) ? core.nodes_to_monitor : [];

    // Prefer backend-generated executable payload when available.
    // This preserves correct grounding/model/source semantics from API-side generator.
    if (providedNetlist) {
        const probes = providedNodes
            .map((n) => String(n || '').trim().toLowerCase())
            .filter((n) => !!n)
            .map((n) => (n.startsWith('v(') || n.startsWith('i(') ? n : `v(${n})`));

        const normalizedProbes = Array.from(new Set(probes.length ? probes : ['v(net_in)', 'v(net_out)']));
        const payload = {
            circuit_data: core,
            netlist: providedNetlist,
            nodes_to_monitor: normalizedProbes,
            analysis_type: String(core.analysis_type || 'transient'),
            tran_step: core.tran_step || '100us',
            tran_stop: core.tran_stop,
            tran_start: core.tran_start || '0',
            source_params: core.source_params || undefined,
            probes: normalizedProbes,
            analysis: {
                type: 'transient',
                step: core.tran_step || '100us',
                stop: core.tran_stop,
                start: core.tran_start || '0',
            },
        };
        ensureSimulationWindow(core, payload);
        return payload;
    }

    const components = Array.isArray(core?.components) ? core.components : [];
    const nets = Array.isArray(core?.nets) ? core.nets : [];
    const ports = Array.isArray(core?.ports) ? core.ports : [];

    if (!components.length || !nets.length) {
        const emptyPayload = {
            netlist: '',
            probes: ['v(out)', 'v(in)'],
            analysis: { type: 'transient', step: '10us', stop: formatSpiceTimeSeconds(MAX_TRAN_STOP_S), start: '0' },
            tran_stop: formatSpiceTimeSeconds(MAX_TRAN_STOP_S),
        };
        ensureSimulationWindow(core, emptyPayload);
        return emptyPayload;
    }

    const pinToNode = new Map();
    const nodeAlias = new Map();
    const allNodes = new Set();

    const normalizeNode = (name) => {
        if (!name) return '0';
        const raw = String(name).trim();
        const lower = raw.toLowerCase();
        if (
            ['0', 'gnd', 'ground', 'groud', 'vss'].includes(lower)
            || /(^|_)gnd($|_)|(^|_)ground($|_)|(^|_)vss($|_)/i.test(lower)
        ) {
            return '0';
        }
        if (nodeAlias.has(raw)) return nodeAlias.get(raw);
        const sanitized = raw.replace(/[^a-zA-Z0-9_]/g, '_');
        nodeAlias.set(raw, sanitized || '0');
        return nodeAlias.get(raw);
    };

    for (const net of nets) {
        const netName = normalizeNode(net.name || net.id || '');
        if (netName && netName !== '0') allNodes.add(netName);
        const conns = Array.isArray(net.connections) ? net.connections : (Array.isArray(net.connected_pins) ? net.connected_pins : []);
        for (const c of conns) {
            let compId = '';
            let pinName = '';
            if (Array.isArray(c) && c.length >= 2) {
                compId = String(c[0]);
                pinName = String(c[1]);
            } else if (c && typeof c === 'object') {
                compId = String(c.component_id || c.component || '');
                pinName = String(c.pin_name || c.pin || '');
            }
            if (compId && pinName) {
                pinToNode.set(`${compId}.${pinName}`, netName);
            }
        }
    }

    const getNode = (compId, pinCandidates) => {
        for (const p of pinCandidates) {
            const k = `${compId}.${p}`;
            if (pinToNode.has(k)) return pinToNode.get(k);
        }
        return '0';
    };

    const formatValue = (v, unit = '') => {
        if (v == null) return '';
        if (typeof v === 'object' && v.value != null) {
            return `${v.value}${v.unit || unit}`;
        }
        return `${v}${unit}`;
    };

    const lines = [];
    const modelLines = [];
    let hasIndependentSource = false;
    let hasDynamicSource = false;
    const sourceConnectedNodes = new Set();
    let hasOpAmp = false;
    const opAmpInputNodes = [];
    const opAmpOutputNodes = [];
    const topologyHint = String(root.topology_type || root.template_id || '').toLowerCase();
    const isBjtLikeTopology = /(bjt|common_emitter|common_base|common_collector|\bce\b|\bcb\b|\bcc\b)/i.test(topologyHint);
    const expectedGainAbs = Math.max(1, Math.abs(Number(root.actual_gain || root.gain_target || 10)));

    const findNodeByRegex = (regex, fallback = '') => {
        const hit = Array.from(allNodes).find((n) => regex.test(String(n).toLowerCase()));
        return hit || fallback;
    };

    for (const comp of components) {
        const id = String(comp.id || '').trim();
        const type = String(comp.type || '').toLowerCase();
        const p = comp.parameters || {};
        if (!id) continue;

        if (type === 'resistor') {
            const n1 = getNode(id, ['1', 'A', 'IN', '+']);
            const n2 = getNode(id, ['2', 'B', 'OUT', '-']);
            const value = formatValue(p.resistance || p.value, '');
            if (value) lines.push(`R${id} ${n1} ${n2} ${value}`);
        } else if (type === 'capacitor' || type === 'capacitor_polarized') {
            const n1 = getNode(id, ['1', '+', 'A']);
            const n2 = getNode(id, ['2', '-', 'B']);
            const value = formatValue(p.capacitance || p.value, '');
            if (value) lines.push(`C${id} ${n1} ${n2} ${value}`);
        } else if (type === 'inductor') {
            const n1 = getNode(id, ['1', 'A']);
            const n2 = getNode(id, ['2', 'B']);
            const value = formatValue(p.inductance || p.value, '');
            if (value) lines.push(`L${id} ${n1} ${n2} ${value}`);
        } else if (type === 'voltage_source') {
            const np = getNode(id, ['+', '1', 'P']);
            const nn = getNode(id, ['-', '2', 'N']);
            const waveform = String(p.waveform || p.signal || '').trim();
            if (waveform) {
                lines.push(`V${id} ${np} ${nn} ${waveform}`);
                hasDynamicSource = /(sin\(|pulse\(|pwl\(|ac\s+)/i.test(waveform);
            } else {
                const v = formatValue(p.voltage || p.value || 5, '');
                lines.push(`V${id} ${np} ${nn} DC ${v}`);
            }
            hasIndependentSource = true;
            if (np !== '0') sourceConnectedNodes.add(np);
            if (nn !== '0') sourceConnectedNodes.add(nn);
        } else if (type === 'bjt' || type === 'bjt_npn' || type === 'bjt_pnp') {
            const c = getNode(id, ['C', 'c', '1']);
            const b = getNode(id, ['B', 'b', '2']);
            const e = getNode(id, ['E', 'e', '3']);
            const model = type === 'bjt_pnp' ? 'QPNP' : 'QNPN';
            lines.push(`Q${id} ${c} ${b} ${e} ${model}`);
        } else if (type === 'opamp') {
            hasOpAmp = true;
            const out = getNode(id, ['OUT', 'out', '1']);
            const inn = getNode(id, ['IN-', 'in-', '2', 'N', '-']);
            const inp = getNode(id, ['IN+', 'in+', '3', 'P', '+']);
            let vp = getNode(id, ['V+', 'v+', '5', 'VCC', 'vcc']);
            let vn = getNode(id, ['V-', 'v-', '4', 'VEE', 'VSS', 'vee', 'vss']);

            if (!vp || vp === '0') vp = findNodeByRegex(/vcc|vdd/, 'net_auto_vcc');
            if (!vn || vn === '0') vn = findNodeByRegex(/vee|vss|vddn|vneg|neg/, 'net_auto_vee');

            if (!allNodes.has(vp) && vp !== '0') allNodes.add(vp);
            if (!allNodes.has(vn) && vn !== '0') allNodes.add(vn);

            opAmpInputNodes.push(inn, inp);
            opAmpOutputNodes.push(out);

            // Stable closed-loop behavioral model (topology-aware sign + rail clipping).
            const inPort = ports
                .map((p0) => ({
                    dir: String(p0.direction || '').toLowerCase(),
                    name: String(p0.name || '').toLowerCase(),
                    net: normalizeNode(p0.net || p0.net_name || ''),
                }))
                .find((p0) => p0.net && p0.net !== '0' && (p0.dir === 'input' || p0.name.includes('in')));
            const vinNode = inPort?.net || inp || inn || findNodeByRegex(/(^|_)in($|_)|vin/, '0');
            const sign = /non[_-]?inverting/.test(topologyHint) ? 1 : -1;
            lines.push(`B_OP_${id} ${out} 0 V=limit((${sign * expectedGainAbs})*V(${vinNode}), V(${vn})+0.2, V(${vp})-0.2)`);
            lines.push(`R_OP_OUT_${id} ${out} 0 10Meg`);
        } else if (type === 'ground') {
            // skip explicit ground symbol in spice deck
        }
    }

    if (lines.length === 0) {
        return {
            netlist: '',
            probes: ['v(out)', 'v(in)'],
            analysis: { type: 'transient', step: '10us', stop: '10ms', start: '0' },
        };
    }

    // Add gentle DC path to ground for every node to improve convergence on generated decks.
    let shuntIdx = 1;
    for (const node of allNodes) {
        if (!node || node === '0') continue;
        lines.push(`R__SHUNT_${shuntIdx} ${node} 0 1G`);
        shuntIdx += 1;
    }

    // If topology has a VCC-like rail but no source, inject a safe default supply.
    if (!hasIndependentSource) {
        const vccNode = Array.from(allNodes).find((n) => /(^|_)vcc($|_)|(^|_)vdd($|_)/i.test(n));
        if (vccNode) {
            lines.push(`V__AUTO_VCC ${vccNode} 0 DC 12`);
            hasIndependentSource = true;
            sourceConnectedNodes.add(vccNode);
        }
    }

    // If op-amp rails are still unresolved, inject symmetric rails.
    if (hasOpAmp) {
        if (allNodes.has('net_auto_vcc') || Array.from(allNodes).some((n) => /net_auto_vcc/i.test(String(n)))) {
            lines.push('V__AUTO_OP_VCC net_auto_vcc 0 DC 12');
            hasIndependentSource = true;
            sourceConnectedNodes.add('net_auto_vcc');
        }
        if (allNodes.has('net_auto_vee') || Array.from(allNodes).some((n) => /net_auto_vee/i.test(String(n)))) {
            lines.push('V__AUTO_OP_VEE net_auto_vee 0 DC -12');
            hasIndependentSource = true;
            sourceConnectedNodes.add('net_auto_vee');
        }
    }

    // For op-amp transient tests, inject a small sine stimulus when no dynamic source is present.
    if (hasOpAmp && !hasDynamicSource) {
        const fromPorts = ports
            .map((p) => ({
                dir: String(p.direction || '').toLowerCase(),
                name: String(p.name || '').toLowerCase(),
                net: normalizeNode(p.net || p.net_name || ''),
            }))
            .find((p) => p.net && p.net !== '0' && (p.dir === 'input' || p.name.includes('in')));

        const candidateInputs = [
            fromPorts?.net,
            ...opAmpInputNodes.filter(Boolean),
            findNodeByRegex(/(^|_)in($|_)|vin/, ''),
        ].filter((n) => !!n && n !== '0');

        const stimNode = candidateInputs.find((n) => !sourceConnectedNodes.has(n)) || candidateInputs[0];
        if (stimNode) {
            lines.push(`V__AUTO_STIM ${stimNode} 0 SIN(0 0.1 1k)`);
            hasIndependentSource = true;
            hasDynamicSource = true;
            sourceConnectedNodes.add(stimNode);
        }
    }

    // For generated amplifier templates (e.g. BJT CE), ports are often connectors
    // and do not include an explicit AC source. Inject a small-signal input so
    // transient simulation shows meaningful gain/phase waveform.
    if (!hasDynamicSource) {
        const inputPort = ports
            .map((p) => ({
                dir: String(p.direction || '').toLowerCase(),
                name: String(p.name || '').toLowerCase(),
                net: normalizeNode(p.net || p.net_name || ''),
            }))
            .find((p) => p.net && p.net !== '0' && (p.dir === 'input' || p.name.includes('in')));

        const genericInputCandidates = [
            inputPort?.net,
            findNodeByRegex(/(^|_)in($|_)|vin|input/, ''),
        ].filter((n) => !!n && n !== '0');

        const stimNode = genericInputCandidates.find((n) => !sourceConnectedNodes.has(n)) || genericInputCandidates[0];
        if (stimNode) {
            const amp = isBjtLikeTopology ? 0.01 : 0.1;
            lines.push(`V__AUTO_STIM ${stimNode} 0 SIN(0 ${amp} 1k)`);
            hasIndependentSource = true;
            hasDynamicSource = true;
            sourceConnectedNodes.add(stimNode);
        }
    }

    if (lines.some((l) => l.startsWith('Q'))) {
        modelLines.push('.model QNPN NPN (BF=200)');
        modelLines.push('.model QPNP PNP (BF=200)');
    }

    const probeNets = [];
    for (const port of ports) {
        const dir = String(port.direction || '').toLowerCase();
        const name = String(port.name || '').toLowerCase();
        const netName = normalizeNode(port.net || port.net_name || '');
        if (!netName || netName === '0') continue;
        if (dir === 'output' || name.includes('out')) {
            probeNets.unshift(netName);
        } else {
            probeNets.push(netName);
        }
    }

    const uniqueProbeNets = Array.from(new Set(probeNets.filter((n) => n !== '0' && allNodes.has(n))));
    if (hasOpAmp) {
        const preferred = [
            ...opAmpOutputNodes,
            ...opAmpInputNodes,
        ].filter((n) => n && n !== '0' && allNodes.has(n));
        for (const n of preferred.reverse()) {
            uniqueProbeNets.unshift(n);
        }
    }
    const uniqOrdered = Array.from(new Set(uniqueProbeNets));

    // Prefer explicit vin/vout nodes for clearer waveform comparison.
    const explicitVin = findNodeByRegex(/(^|_)vin($|_)|(^|_)net_vin($|_)/, '');
    const explicitVout = findNodeByRegex(/(^|_)vout($|_)|(^|_)net_vout($|_)/, '');
    if (explicitVout && allNodes.has(explicitVout)) {
        uniqOrdered.unshift(explicitVout);
    }
    if (explicitVin && allNodes.has(explicitVin)) {
        uniqOrdered.push(explicitVin);
    }

    const orderedDistinct = [];
    for (const n of uniqOrdered) {
        if (!n || n === '0') continue;
        if (!orderedDistinct.includes(n)) orderedDistinct.push(n);
    }

    if (uniqOrdered.length === 0) {
        const rankedNodes = Array.from(allNodes).sort((a, b) => {
            const score = (n) => {
                const ln = String(n).toLowerCase();
                if (ln.includes('out')) return 3;
                if (ln.includes('in')) return 2;
                if (ln.includes('vcc') || ln.includes('vdd')) return -1;
                return 1;
            };
            return score(b) - score(a);
        });
        orderedDistinct.push(...rankedNodes.slice(0, 2));
    }

    const probes = orderedDistinct.slice(0, 2).map((n) => `v(${n})`);
    if (probes.length === 0) probes.push('v(0)');
    if (probes.length === 1) probes.push('v(0)');

    const netlist = [
        ...lines,
        ...modelLines,
        '.end',
    ].join('\n');

    const analysis = {
        type: 'transient',
        step: '20us',
        stop: '2ms',
        start: '0',
    };

    // CE/CB/CC templates with coupling capacitors need a longer window to move
    // past startup transient; otherwise users only see a short sawtooth around 0V.
    if (isBjtLikeTopology || lines.some((l) => l.startsWith('Q'))) {
        analysis.step = '100us';
        analysis.stop = '100ms';
        analysis.start = '50ms';
    }

    const payload = {
        circuit_data: core,
        netlist,
        probes,
        nodes_to_monitor: probes,
        analysis,
        analysis_type: 'transient',
    };
    ensureSimulationWindow(core, payload);
    return payload;
}

function initPanelResizer() {
    const resizer = document.getElementById('panelResizer');
    const main = document.querySelector('.main-content');
    const chat = document.querySelector('.chat-panel');
    const detail = document.getElementById('detailPanel');

    if (!resizer || !main || !chat || !detail) return;

    let dragging = false;

    const onMouseMove = (ev) => {
        if (!dragging) return;
        const rect = main.getBoundingClientRect();
        const total = rect.width;
        const minChat = 320;
        const minDetail = 360;

        let chatWidth = ev.clientX - rect.left;
        chatWidth = Math.max(minChat, Math.min(total - minDetail, chatWidth));
        const detailWidth = total - chatWidth - resizer.getBoundingClientRect().width;

        chat.style.flex = `0 0 ${chatWidth}px`;
        chat.style.width = `${chatWidth}px`;
        detail.style.flex = `0 0 ${Math.max(minDetail, detailWidth)}px`;
        detail.style.width = `${Math.max(minDetail, detailWidth)}px`;
    };

    const stopDrag = () => {
        if (!dragging) return;
        dragging = false;
        resizer.classList.remove('dragging');
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', stopDrag);
    };

    resizer.addEventListener('mousedown', (ev) => {
        if (window.innerWidth <= 900) return;
        ev.preventDefault();
        dragging = true;
        resizer.classList.add('dragging');
        document.body.style.userSelect = 'none';
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', stopDrag);
    });
}

function sendSuggestion(text) {
    chatInput.value = text;
    sendMessage();
}

// ── Handle Bot Response ──
function handleBotResponse(data) {
    // Add bot message with a typewriter effect — adaptive speed so long
    // replies still finish quickly (cap total typing budget ~2.4s).
    const msgText = String(data && data.message || '');
    const adaptiveSpeed = Math.max(4, Math.floor(2400 / Math.max(60, msgText.length)));
    addMessage(msgText, 'bot', {
        mode: data.mode,
        typewriter: true,
        typewriterSpeed: adaptiveSpeed,
    });

    // Update processing time
    if (data.processing_time_ms) {
        processingTime.textContent = `${data.processing_time_ms.toFixed(0)}ms`;
    }

    // Update right panel — always render the BOM (from circuit_data.components
    // or parsed from the AI text), even when `data.params` is empty.
    const bomComponents =
        (data.circuit_data && Array.isArray(data.circuit_data.components) && data.circuit_data.components) ||
        (Array.isArray(data.components) ? data.components : []);
    const hasBomData = bomComponents.length > 0 || /(?:Danh\s*s[áa]ch\s*linh\s*ki[ệe]n|BOM|Components?|Linh\s*ki[ệe]n)\s*\**\s*[:：]/i.test(String(data.message || ''));
    if (data.params || hasBomData) {
        updateParamsPanel(data.params || {}, data.pipeline, {
            components: bomComponents,
            message: data.message || '',
        });
    }

    if (data.intent || data.analysis || data.pipeline) {
        updateAnalysisPanel(data.intent || {}, data.pipeline, data.analysis || null);
    }

    if (data.circuit_data && data.circuit_id) {
        if (data.circuit_id === currentCircuitId) {
            lastCircuitData = data.circuit_data;
        }
    }

    if (data.success === false) {
        clearCircuitArtifacts();
    }
}

// ── Message Rendering ──
function toModeLabel(mode) {
    const value = String(mode || '').trim().toLowerCase();
    if (value === 'fast' || value === 'air') return 'Fast';
    if (value === 'think') return 'Think';
    if (value === 'pro') return 'Pro';
    if (value === 'ultra') return 'Ultra';
    return 'Fast';
}

function addMessage(text, type, options = {}) {
    const div = document.createElement('div');
    div.className = `message ${type}-message`;

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.innerHTML = type === 'bot'
        ? '<img src="/static/logo/System-icon.png" alt="Bot Avatar">'
        : '<i class="fas fa-user"></i>';

    const content = document.createElement('div');
    content.className = 'message-content';

    const msgText = document.createElement('div');
    msgText.className = 'message-text';

    let modeMeta = null;
    let actions = null;

    if (type === 'bot') {
        // Optional typewriter: types plain text character-by-character, then
        // swaps in the fully-rendered markdown (with code blocks, tables,
        // LaTeX) once typing completes. Caller opts in via `options.typewriter`
        // — defaulting to false keeps the existing streaming flow unchanged.
        if (options.typewriter && typeof typewriter === 'function') {
            const plain = String(text || '').replace(/\s+/g, ' ').trim();
            const speed = Number.isFinite(options.typewriterSpeed) ? options.typewriterSpeed : 14;
            typewriter(plain, msgText, speed, {
                cursor: true,
                onDone: () => {
                    msgText.innerHTML = renderMarkdown(text);
                    if (typeof renderLatexInElement === 'function') {
                        renderLatexInElement(msgText);
                    }
                    scrollToBottom();
                },
            });
        } else {
            msgText.innerHTML = renderMarkdown(text);
            if (typeof renderLatexInElement === 'function') {
                renderLatexInElement(msgText);
            }
        }

        modeMeta = document.createElement('div');
        modeMeta.className = 'message-meta';
        modeMeta.textContent = `Mode: ${toModeLabel(options.mode)}`;
    } else {
        msgText.textContent = text;

        actions = document.createElement('div');
        actions.className = 'message-actions';

        const editBtn = document.createElement('button');
        editBtn.className = 'message-edit-btn';
        editBtn.type = 'button';
        editBtn.title = 'Chỉnh sửa yêu cầu đã gửi';
        editBtn.innerHTML = '<i class="fas fa-pen"></i> Edit';
        editBtn.disabled = true;
        editBtn.addEventListener('click', () => editUserMessage(div, msgText, editBtn));

        actions.appendChild(editBtn);
    }

    content.appendChild(msgText);
    if (modeMeta) {
        content.appendChild(modeMeta);
    }
    if (actions) {
        content.appendChild(actions);
    }
    div.appendChild(avatar);
    div.appendChild(content);

    if (type === 'user') {
        bindUserMessageMetadata(div, {
            messageId: options.messageId,
            sessionId: options.sessionId || currentSessionId,
            chatId: options.chatId,
        });
        if (options.edited) {
            markMessageEdited(div);
        }
    }

    chatMessages.appendChild(div);
    scrollToBottom();
    return div;
}

function bindUserMessageMetadata(messageEl, options = {}) {
    if (!messageEl) return;

    const messageId = String(options.messageId || '').trim();
    const sessionId = String(options.sessionId || '').trim();
    const chatId = String(options.chatId || '').trim();

    if (messageId) messageEl.dataset.messageId = messageId;
    if (sessionId) messageEl.dataset.sessionId = sessionId;
    if (chatId) {
        messageEl.dataset.chatId = chatId;
    } else if (sessionId && !messageEl.dataset.chatId) {
        messageEl.dataset.chatId = sessionId;
    }

    if (sessionId) {
        currentSessionId = sessionId;
    }

    const editBtn = messageEl.querySelector('.message-edit-btn');
    if (editBtn) {
        editBtn.disabled = !messageEl.dataset.messageId;
    }
}

function markMessageEdited(messageEl) {
    if (!messageEl) return;
    const actions = messageEl.querySelector('.message-actions');
    if (!actions) return;
    let badge = actions.querySelector('.message-edited-badge');
    if (!badge) {
        badge = document.createElement('span');
        badge.className = 'message-edited-badge';
        badge.textContent = 'edited';
        actions.appendChild(badge);
    }
}

async function editUserMessage(messageEl, textEl, buttonEl) {
    if (!messageEl || !textEl || !buttonEl) return;

    if (isProcessing) {
        addMessage('⏳ Hệ thống đang xử lý yêu cầu khác. Vui lòng thử lại sau vài giây.', 'bot');
        return;
    }

    const messageId = String(messageEl.dataset.messageId || '').trim();
    const chatId = String(messageEl.dataset.chatId || '').trim()
        || String(messageEl.dataset.sessionId || '').trim()
        || currentSessionId
        || '';
    const sessionId = String(messageEl.dataset.sessionId || '').trim() || currentSessionId || '';

    if (!messageId) {
        addMessage('❌ Không thể chỉnh sửa: thiếu message_id.', 'bot');
        return;
    }

    const oldText = String(textEl.textContent || '').trim();
    const nextText = window.prompt('Chỉnh sửa yêu cầu hội thoại', oldText);
    if (nextText === null) return;

    const editedText = String(nextText || '').trim();
    if (!editedText || editedText === oldText) return;

    buttonEl.disabled = true;
    try {
        const resp = await fetch(`${API_BASE}/api/chat/messages/${encodeURIComponent(messageId)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(
                chatId
                    ? { session_id: chatId, content: editedText }
                    : { content: editedText }
            ),
        });

        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            const errMsg = data.detail?.message || data.detail || 'Không thể cập nhật message';
            addMessage(`❌ ${errMsg}`, 'bot');
            return;
        }

        textEl.textContent = data.content || editedText;
        bindUserMessageMetadata(messageEl, {
            messageId: data.message_id || messageId,
            sessionId: data.session_id || sessionId,
            chatId: data.chat_id || chatId || data.session_id,
        });
        markMessageEdited(messageEl);

        // Re-run chatbot immediately with the edited prompt so UI receives a fresh answer.
        await requestChatReply(editedText, {
            includeUserMessage: false,
            sessionIdOverride: data.session_id || sessionId || currentSessionId,
        });
    } catch (e) {
        addMessage(`❌ Cập nhật yêu cầu thất bại: ${e.message}`, 'bot');
    } finally {
        buttonEl.disabled = false;
    }
}

function showTyping() {
    const id = 'typing-' + Date.now();
    const div = document.createElement('div');
    div.id = id;
    div.className = 'message bot-message';
    div.innerHTML = `
        <div class="message-avatar"><img src="/static/logo/System-icon.png" alt="Bot Avatar"></div>
        <div class="message-content">
            <div class="message-text">
                <div class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        </div>
    `;
    chatMessages.appendChild(div);
    scrollToBottom();
    return id;
}

function removeTyping(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// ── Right Panel Updates ──

// Escape user-supplied strings before injecting them into innerHTML.
function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

/**
 * Classify a parameter by its name prefix to pick an icon, unit family, and
 * human-readable tag. Used by the Params CARDS template.
 */
function classifyParam(name) {
    const n = String(name || '').trim();
    const head = n.charAt(0).toUpperCase();
    const lower = n.toLowerCase();

    if (head === 'R') return { icon: 'fa-bolt',          tag: 'Resistor',  unitKind: 'ohm' };
    if (head === 'C') return { icon: 'fa-database',      tag: 'Capacitor', unitKind: 'farad' };
    if (head === 'L') return { icon: 'fa-wave-square',   tag: 'Inductor',  unitKind: 'henry' };
    if (head === 'V' || lower.includes('vcc') || lower.includes('vee') || lower.includes('vdd'))
        return { icon: 'fa-plug',            tag: 'Voltage',   unitKind: 'volt' };
    if (head === 'I' || lower.includes('current'))
        return { icon: 'fa-arrow-right-arrow-left', tag: 'Current', unitKind: 'amp' };
    if (head === 'Q') return { icon: 'fa-microchip',     tag: 'BJT',       unitKind: 'raw' };
    if (head === 'M') return { icon: 'fa-microchip',     tag: 'MOSFET',    unitKind: 'raw' };
    if (head === 'D') return { icon: 'fa-bolt',          tag: 'Diode',     unitKind: 'raw' };
    if (head === 'U') return { icon: 'fa-microchip',     tag: 'IC',        unitKind: 'raw' };
    if (lower.includes('gain'))     return { icon: 'fa-chart-line', tag: 'Gain',      unitKind: 'ratio' };
    if (lower.includes('freq') || lower.includes('hz'))
        return { icon: 'fa-wave-square',     tag: 'Frequency', unitKind: 'hertz' };
    if (lower.includes('bw') || lower.includes('bandwidth'))
        return { icon: 'fa-wave-square',     tag: 'Bandwidth', unitKind: 'hertz' };
    if (lower.includes('temp'))     return { icon: 'fa-temperature-half', tag: 'Temp', unitKind: 'celsius' };
    return { icon: 'fa-microchip',           tag: 'Param',     unitKind: 'auto' };
}

const SI_PREFIXES = [
    { f: 1e9,  p: 'G' },
    { f: 1e6,  p: 'M' },
    { f: 1e3,  p: 'k' },
    { f: 1,    p: ''  },
    { f: 1e-3, p: 'm' },
    { f: 1e-6, p: 'μ' },
    { f: 1e-9, p: 'n' },
    { f: 1e-12, p: 'p' },
];

function formatValueRich(rawValue, unitKind) {
    if (rawValue === null || rawValue === undefined) return { value: '—', unit: '' };
    if (typeof rawValue === 'string' && Number.isNaN(Number(rawValue))) {
        return { value: rawValue, unit: '' };
    }
    const n = Number(rawValue);
    if (Number.isNaN(n)) return { value: String(rawValue), unit: '' };

    const baseUnitMap = {
        ohm:    'Ω',
        farad:  'F',
        henry:  'H',
        volt:   'V',
        amp:    'A',
        hertz:  'Hz',
        celsius: '°C',
        ratio:  '',
        raw:    '',
        auto:   '',
    };
    const baseUnit = baseUnitMap[unitKind] ?? '';
    if (unitKind === 'raw' || unitKind === 'ratio') {
        const formatted = Math.abs(n) >= 100 ? n.toFixed(0)
                        : Math.abs(n) >= 10  ? n.toFixed(1)
                        : n.toFixed(2);
        return { value: formatted, unit: baseUnit };
    }
    if (n === 0) return { value: '0', unit: baseUnit };

    const abs = Math.abs(n);
    const match = SI_PREFIXES.find(({ f }) => abs >= f);
    const scale = match ?? SI_PREFIXES[SI_PREFIXES.length - 1];
    const scaled = n / scale.f;
    const valueStr = Math.abs(scaled) >= 100 ? scaled.toFixed(0)
                   : Math.abs(scaled) >= 10  ? scaled.toFixed(1)
                   : scaled.toFixed(2);
    return { value: valueStr, unit: `${scale.p}${baseUnit}` };
}

// Parse the "Danh sách linh kiện: ..." line out of an AI message body and
// return a list of { kind, value, note } records. Robust to comma-separated
// items, parenthesised notes, and Vietnamese kind keywords. Returns [] if no
// such line is found.
function parseComponentListFromText(text) {
    if (!text) return [];
    // Allow optional markdown emphasis (`**...**`) between the label and the
    // colon, e.g. "**Danh sách linh kiện**: R1, R2".
    const re = /(?:Danh\s*s[áa]ch\s*linh\s*ki[ệe]n|BOM|Components?|Linh\s*ki[ệe]n)\s*\**\s*[:：]\s*([^\n]+)/i;
    const m = re.exec(String(text));
    if (!m) return [];

    // Split by top-level commas (don't break inside parentheses).
    // Trim any trailing markdown emphasis from the captured tail.
    const raw = m[1].replace(/\*+$/, '').trim();
    const items = [];
    let depth = 0;
    let cur = '';
    for (const ch of raw) {
        if (ch === '(' || ch === '[' || ch === '{') depth += 1;
        else if (ch === ')' || ch === ']' || ch === '}') depth = Math.max(0, depth - 1);
        if (ch === ',' && depth === 0) {
            if (cur.trim()) items.push(cur.trim());
            cur = '';
            continue;
        }
        cur += ch;
    }
    if (cur.trim()) items.push(cur.trim());

    return items.map(parseComponentDescriptor).filter(Boolean);
}

function parseComponentDescriptor(s) {
    const noteMatch = /\(([^)]+)\)/.exec(s);
    const note = noteMatch ? noteMatch[1].trim() : '';
    const head = s.replace(/\([^)]*\)/, '').trim();
    if (!head) return null;

    // Try multi-word kind prefix first (Vietnamese keywords come in 2 words).
    const kindKeywords = [
        'Điện trở', 'Tụ điện', 'Cuộn cảm', 'Nguồn DC', 'Nguồn AC',
        'Op-Amp', 'OpAmp', 'BJT NPN', 'BJT PNP', 'MOSFET N', 'MOSFET P',
        'Transistor', 'Diode', 'LED', 'Nguồn', 'IC',
    ];
    const lower = head.toLowerCase();
    let kind = '';
    let value = '';
    for (const kw of kindKeywords) {
        if (lower.startsWith(kw.toLowerCase())) {
            kind = head.slice(0, kw.length);
            value = head.slice(kw.length).trim();
            break;
        }
    }
    if (!kind) {
        const tokens = head.split(/\s+/);
        kind = tokens[0] || '';
        value = tokens.slice(1).join(' ').trim();
    }
    return { kind: kind.trim(), value: value.trim(), note };
}

// Convert a structured Component (from circuit_data.components) into a BOM
// row using the same SI-prefix formatting we use elsewhere.
const _COMPONENT_TYPE_VI = {
    resistor: 'Điện trở',
    capacitor: 'Tụ điện',
    inductor: 'Cuộn cảm',
    opamp: 'Op-Amp',
    bjt_npn: 'BJT NPN',
    bjt_pnp: 'BJT PNP',
    mosfet_n: 'MOSFET N',
    mosfet_p: 'MOSFET P',
    diode: 'Diode',
    led: 'LED',
    ic: 'IC',
    connector: 'Connector',
    ground: 'GND',
    power_symbol: 'Nguồn',
    voltage_source: 'Nguồn DC',
    current_source: 'Nguồn dòng',
    port: 'Port',
};

function _componentToRow(comp) {
    if (!comp || typeof comp !== 'object') return null;
    const id = comp.id || comp.ref || '';
    const typeKey = String(comp.type || '').toLowerCase();
    const kind = _COMPONENT_TYPE_VI[typeKey] || typeKey || '?';
    const params = comp.parameters || {};

    let valueText = '—';
    if (params.resistance !== undefined && params.resistance !== null) {
        const f = formatValueRich(params.resistance, 'ohm');
        valueText = `${f.value} ${f.unit}`.trim();
    } else if (params.capacitance !== undefined && params.capacitance !== null) {
        const f = formatValueRich(params.capacitance, 'farad');
        valueText = `${f.value} ${f.unit}`.trim();
    } else if (params.inductance !== undefined && params.inductance !== null) {
        const f = formatValueRich(params.inductance, 'henry');
        valueText = `${f.value} ${f.unit}`.trim();
    } else if (params.voltage !== undefined && params.voltage !== null) {
        const f = formatValueRich(params.voltage, 'volt');
        valueText = `${f.value} ${f.unit}`.trim();
    } else if (params.model) {
        valueText = String(params.model);
    }

    return { ref: id, kind, value: valueText };
}

function _kindsRoughlyEqual(structuredKind, parsedKind) {
    const a = String(structuredKind || '').toLowerCase();
    const b = String(parsedKind || '').toLowerCase();
    if (!a || !b) return false;
    const pairs = [
        ['điện trở', 'điện trở'],
        ['tụ', 'tụ'],
        ['cuộn', 'cuộn'],
        ['op-amp', 'op-amp'], ['op-amp', 'opamp'], ['opamp', 'op-amp'],
        ['bjt', 'bjt'], ['bjt', 'transistor'],
        ['mosfet', 'mosfet'],
        ['diode', 'diode'],
        ['ic', 'ic'],
    ];
    for (const [pa, pb] of pairs) {
        if (a.includes(pa) && b.includes(pb)) return true;
    }
    return a === b;
}

function _valuesRoughlyEqual(structuredVal, parsedVal) {
    const norm = (s) => String(s || '')
        .toLowerCase()
        .replace(/\s+/g, '')
        .replace(/μ/g, 'u')
        .replace(/ω/g, 'ohm')
        .replace(/Ω/g, 'ohm');
    const a = norm(structuredVal);
    const b = norm(parsedVal);
    return a.length > 0 && b.length > 0 && (a === b || a.startsWith(b) || b.startsWith(a));
}

// Build the BOM section HTML. Prefers structured components for the canonical
// rows; enriches each row with a "note" parsed from the AI message body when
// the kind/value loosely matches.
function renderBomTableHtml(components, parsedFromText) {
    const rows = [];
    const queue = Array.isArray(parsedFromText) ? parsedFromText.slice() : [];

    if (Array.isArray(components) && components.length > 0) {
        for (const comp of components) {
            const row = _componentToRow(comp);
            if (!row) continue;
            let note = '';
            for (let i = 0; i < queue.length; i++) {
                const p = queue[i];
                if (!p || !p.note) continue;
                if (_kindsRoughlyEqual(row.kind, p.kind) && _valuesRoughlyEqual(row.value, p.value)) {
                    note = p.note;
                    queue.splice(i, 1);
                    break;
                }
            }
            // Second pass: kind-only match (in case AI value formatting differs).
            if (!note) {
                for (let i = 0; i < queue.length; i++) {
                    const p = queue[i];
                    if (!p || !p.note) continue;
                    if (_kindsRoughlyEqual(row.kind, p.kind)) {
                        note = p.note;
                        queue.splice(i, 1);
                        break;
                    }
                }
            }
            rows.push({ ...row, note });
        }
    } else if (queue.length > 0) {
        for (const p of queue) {
            rows.push({ ref: '', kind: p.kind, value: p.value, note: p.note });
        }
    }

    if (rows.length === 0) return '';

    let html = '<section class="md-section bom-section">';
    html += `<h2 class="md-h2"><i class="fas fa-list-check"></i> Danh sách linh kiện <span class="bom-count">${rows.length}</span></h2>`;
    html += '<div class="bom-table-wrap"><table class="bom-table">';
    html += '<thead><tr><th class="bom-idx">#</th><th class="bom-ref">Ref</th><th>Loại</th><th>Giá trị</th><th>Ghi chú</th></tr></thead><tbody>';
    rows.forEach((r, i) => {
        html += `<tr>
            <td class="bom-idx">${i + 1}</td>
            <td class="bom-ref">${escapeHtml(r.ref || '—')}</td>
            <td>${escapeHtml(r.kind || '—')}</td>
            <td class="bom-value">${escapeHtml(r.value || '—')}</td>
            <td class="bom-note">${escapeHtml(r.note || '—')}</td>
        </tr>`;
    });
    html += '</tbody></table></div></section>';
    return html;
}

function updateParamsPanel(params, pipeline, extras = {}) {
    const el = document.getElementById('paramsContent');
    if (!el) return;

    const hasParams = params && typeof params === 'object' && Object.keys(params).length > 0;
    const solved = pipeline && pipeline.solved ? pipeline.solved : null;

    const components = Array.isArray(extras.components) ? extras.components : [];
    const parsedFromText = parseComponentListFromText(extras.message || '');
    const hasBom = components.length > 0 || parsedFromText.length > 0;

    if (!hasParams && !solved && !hasBom) {
        el.innerHTML = `
            <div class="placeholder-content">
                <i class="fas fa-table fa-3x"></i>
                <p>Chưa có thông số</p>
                <p class="sub-text">Gửi yêu cầu thiết kế để hệ thống tính toán giá trị linh kiện.</p>
            </div>`;
        return;
    }

    const entries = hasParams ? Object.entries(params) : [];
    const counter = entries.length;

    let html = '';

    // BOM table from AI components — rendered first so users see the line-up.
    if (hasBom) {
        html += renderBomTableHtml(components, parsedFromText);
    }

    if (!hasParams && !solved) {
        el.innerHTML = html;
        return;
    }

    html += `
        <div class="params-header">
            <h2><i class="fas fa-cube"></i> Thông số chi tiết</h2>
            <span class="params-meta">${counter} item${counter !== 1 ? 's' : ''}</span>
        </div>
        <div class="params-card-grid">`;

    for (const [name, value] of entries) {
        const meta = classifyParam(name);
        const formatted = formatValueRich(value, meta.unitKind);
        html += `
            <div class="params-card" role="group" aria-label="${escapeHtml(name)}">
                <div class="params-card-head">
                    <span class="params-card-icon"><i class="fas ${meta.icon}"></i></span>
                    <span class="params-card-name">${escapeHtml(name)}</span>
                    <span class="params-card-tag">${escapeHtml(meta.tag)}</span>
                </div>
                <div class="params-card-value">${escapeHtml(formatted.value)}<span class="params-card-unit">${escapeHtml(formatted.unit)}</span></div>
            </div>`;
    }
    html += '</div>';

    // Solved/calculation summary block (markdown-style)
    if (solved) {
        html += '<div class="md-section" style="margin-top:14px">';
        html += '<h2 class="md-h2"><i class="fas fa-calculator"></i> Kết quả tính toán</h2>';
        html += '<div class="md-kv-grid">';
        if (solved.gain_formula) {
            html += `<div class="md-kv"><span class="md-kv-key">Công thức</span><span class="md-kv-val is-mono">${escapeHtml(solved.gain_formula)}</span></div>`;
        }
        if (solved.actual_gain !== null && solved.actual_gain !== undefined) {
            const gainNum = Number(solved.actual_gain);
            const sign = Number.isFinite(gainNum) ? (gainNum >= 0 ? 'is-pos' : 'is-neg') : '';
            const gainTxt = Number.isFinite(gainNum) ? gainNum.toFixed(2) : escapeHtml(solved.actual_gain);
            html += `<div class="md-kv"><span class="md-kv-key">Gain thực tế</span><span class="md-kv-val is-mono ${sign}">${gainTxt}</span></div>`;
        }
        if (solved.gain_target !== null && solved.gain_target !== undefined) {
            html += `<div class="md-kv"><span class="md-kv-key">Gain mục tiêu</span><span class="md-kv-val is-mono">${escapeHtml(solved.gain_target)}</span></div>`;
        }
        html += '</div>';
        if (Array.isArray(solved.notes) && solved.notes.length > 0) {
            for (const note of solved.notes) {
                html += `
                    <div class="md-alert md-alert--note" style="margin-top:10px">
                        <i class="fas fa-sticky-note"></i>
                        <div>${escapeHtml(note)}</div>
                    </div>`;
            }
        }
        html += '</div>';
    }

    el.innerHTML = html;
}

/**
 * Reset the analysis panel to its "loading" placeholder.
 * Call this at the start of every new chat request so old data
 * never lingers while a new response is being streamed.
 */
function clearAnalysisPanel() {
    const el = document.getElementById('analysisContent');
    if (!el) return;
    el.innerHTML = `
        <div class="placeholder-content">
            <i class="fas fa-spinner fa-spin fa-2x" style="color:var(--accent-blue,#3b82f6);"></i>
            <p style="margin-top:10px;">Đang phân tích yêu cầu…</p>
        </div>`;
}

function updateAnalysisPanel(intent, pipeline, analysis) {
    const el = document.getElementById('analysisContent');
    if (!el) return;

    intent = intent || {};

    const hasIntent = Object.keys(intent).length > 0;
    const hasPipeline = pipeline && Object.keys(pipeline).length > 0;
    const hasAnalysis = analysis && Object.keys(analysis).length > 0;

    if (!hasIntent && !hasPipeline && !hasAnalysis) {
        el.innerHTML = `
            <div class="placeholder-content">
                <i class="fas fa-search-plus fa-3x"></i>
                <p>Chưa có phân tích</p>
                <p class="sub-text">Khi AI xử lý yêu cầu, kết quả phân tích NLU, pipeline và topology sẽ hiển thị ở đây.</p>
            </div>`;
        return;
    }

    const formatOhm = (value) => {
        if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
        const n = Number(value);
        if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)} MΩ`;
        if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(2)} kΩ`;
        return `${n.toFixed(2)} Ω`;
    };

    const formatHz = (value) => {
        if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
        const n = Number(value);
        if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)} MHz`;
        if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(2)} kHz`;
        return `${n.toFixed(2)} Hz`;
    };

    let html = '<div class="analysis-md">';

    // ── Section 1: NLU Analysis ──
    html += '<section class="md-section">';
    html += '<h2 class="md-h2"><i class="fas fa-brain"></i> NLU Analysis</h2>';

    const intentFields = [
        { label: 'Circuit Type',  value: intent.circuit_type || 'N/A' },
        { label: 'Gain Target',   value: (intent.gain_target !== null && intent.gain_target !== undefined) ? intent.gain_target : 'N/A' },
        { label: 'VCC',           value: (intent.vcc !== null && intent.vcc !== undefined) ? `${intent.vcc} V` : 'N/A' },
        { label: 'Source',        value: intent.source || 'rule_based' },
    ];

    const topoProfile = intent.topology_profile || {};
    if (topoProfile.display_name || topoProfile.topology_id) {
        intentFields.splice(1, 0, {
            label: 'Topology',
            value: topoProfile.display_name || topoProfile.topology_id,
        });
    }
    if (topoProfile.gain_formula) {
        intentFields.push({ label: 'Gain Formula', value: topoProfile.gain_formula });
    }
    if (topoProfile.phase_inverted !== undefined) {
        intentFields.push({
            label: 'Phase',
            value: topoProfile.phase_inverted ? 'inverted (~180°)' : 'non-inverted (~0°)',
        });
    }

    html += '<div class="md-kv-grid">';
    for (const f of intentFields) {
        html += `<div class="md-kv">
            <span class="md-kv-key">${escapeHtml(f.label)}</span>
            <span class="md-kv-val">${escapeHtml(f.value)}</span>
        </div>`;
    }
    html += '</div>';

    const conf = Number(intent.confidence || 0) * 100;
    const confClass = conf >= 70 ? 'is-high' : conf >= 40 ? 'is-medium' : 'is-low';
    html += `
        <div class="md-progress-wrap">
            <div class="md-progress-label">
                <span>Confidence</span>
                <span>${conf.toFixed(0)}%</span>
            </div>
            <div class="md-progress-track">
                <div class="md-progress-fill ${confClass}" style="width:${conf}%"></div>
            </div>
        </div>`;
    html += '</section>';

    // ── Section 2: Pipeline ──
    if (hasPipeline) {
        html += '<section class="md-section">';
        html += '<h2 class="md-h2"><i class="fas fa-cogs"></i> Pipeline Result</h2>';

        html += '<div class="md-kv-grid">';
        html += `<div class="md-kv"><span class="md-kv-key">Stage Reached</span><span class="md-kv-val">${escapeHtml(pipeline.stage_reached || 'N/A')}</span></div>`;
        const success = !!pipeline.success;
        html += `<div class="md-kv"><span class="md-kv-key">Trạng thái</span><span class="md-kv-val ${success ? 'is-pos' : 'is-neg'}">${success ? 'Success' : 'Failed'}</span></div>`;

        if (pipeline.plan) {
            const plan = pipeline.plan;
            html += `<div class="md-kv"><span class="md-kv-key">Template</span><span class="md-kv-val">${escapeHtml(plan.matched_template_id || 'N/A')}</span></div>`;
            html += `<div class="md-kv"><span class="md-kv-key">Mode</span><span class="md-kv-val">${escapeHtml(plan.mode || 'N/A')}</span></div>`;
            const planConf = Number(plan.confidence || 0) * 100;
            html += `<div class="md-kv"><span class="md-kv-key">Plan Conf.</span><span class="md-kv-val">${planConf.toFixed(0)}%</span></div>`;
        }
        html += '</div>';

        if (pipeline.plan && Array.isArray(pipeline.plan.blocks) && pipeline.plan.blocks.length > 0) {
            html += '<h3 class="md-h3">Blocks</h3>';
            html += '<div class="tag-list">';
            for (const b of pipeline.plan.blocks) {
                const btype = typeof b === 'string' ? b : b.block_type;
                html += `<span class="tag">${escapeHtml(btype)}</span>`;
            }
            html += '</div>';
        }

        if (pipeline.error) {
            html += `
                <div class="md-alert md-alert--error" style="margin-top:12px">
                    <i class="fas fa-triangle-exclamation"></i>
                    <div><strong>Lỗi pipeline:</strong> ${escapeHtml(pipeline.error)}</div>
                </div>`;
        } else if (success) {
            html += `
                <div class="md-alert md-alert--success" style="margin-top:12px">
                    <i class="fas fa-circle-check"></i>
                    <div>Pipeline hoàn tất thành công, mạch đã được build và sẵn sàng để render.</div>
                </div>`;
        }
        html += '</section>';
    }

    // ── Section 3: Topology Analysis ──
    if (hasAnalysis) {
        const cascade = analysis.cascading || {};
        const stageTable = Array.isArray(cascade.stage_table) ? cascade.stage_table : [];

        html += '<section class="md-section">';
        html += '<h2 class="md-h2"><i class="fas fa-project-diagram"></i> Topology Analysis</h2>';

        html += '<div class="md-kv-grid">';
        html += `<div class="md-kv"><span class="md-kv-key">Stage Count</span><span class="md-kv-val">${escapeHtml(cascade.stage_count ?? 'N/A')}</span></div>`;
        if (cascade.total_gain !== undefined && cascade.total_gain !== null) {
            const totalGain = Number(cascade.total_gain);
            const sign = Number.isFinite(totalGain) ? (totalGain >= 0 ? 'is-pos' : 'is-neg') : '';
            html += `<div class="md-kv"><span class="md-kv-key">Total Gain</span><span class="md-kv-val is-mono ${sign}">${Number.isFinite(totalGain) ? totalGain.toFixed(3) : escapeHtml(cascade.total_gain)}</span></div>`;
        }
        if (cascade.overall_bandwidth_hz !== undefined && cascade.overall_bandwidth_hz !== null) {
            html += `<div class="md-kv"><span class="md-kv-key">Bandwidth</span><span class="md-kv-val is-mono">${escapeHtml(formatHz(cascade.overall_bandwidth_hz))}</span></div>`;
        }
        html += '</div>';

        if (stageTable.length > 0) {
            html += '<h3 class="md-h3">Cascading Stage Table</h3>';
            html += '<div class="md-table-wrap"><table class="md-table">';
            html += '<thead><tr><th>Stage</th><th>Type</th><th>Gain</th><th>Equation</th><th>Zin</th><th>Zout</th><th>BW</th></tr></thead>';
            html += '<tbody>';
            for (const row of stageTable) {
                const gainNum = row.gain !== undefined ? Number(row.gain) : NaN;
                const gainTxt = Number.isFinite(gainNum) ? gainNum.toFixed(4) : 'N/A';
                html += '<tr>';
                html += `<td class="is-mono">${escapeHtml(row.stage ?? 'N/A')}</td>`;
                html += `<td>${escapeHtml(row.type || 'N/A')}</td>`;
                html += `<td class="is-mono">${escapeHtml(gainTxt)}</td>`;
                html += `<td class="is-mono">${escapeHtml(row.equation || 'N/A')}</td>`;
                html += `<td class="is-mono">${escapeHtml(formatOhm(row.zin_ohm))}</td>`;
                html += `<td class="is-mono">${escapeHtml(formatOhm(row.zout_ohm))}</td>`;
                html += `<td class="is-mono">${escapeHtml(formatHz(row.bandwidth_hz))}</td>`;
                html += '</tr>';
            }
            html += '</tbody></table></div>';
        }

        if (Array.isArray(analysis.notes) && analysis.notes.length > 0) {
            html += '<h3 class="md-h3">Nhận xét</h3>';
            html += '<ul class="md-ul">';
            for (const note of analysis.notes) html += `<li>${escapeHtml(note)}</li>`;
            html += '</ul>';
        }

        if (analysis.recommendation) {
            html += `
                <div class="md-alert md-alert--info" style="margin-top:12px">
                    <i class="fas fa-lightbulb"></i>
                    <div><strong>Gợi ý:</strong> ${escapeHtml(analysis.recommendation)}</div>
                </div>`;
        }
        html += '</section>';
    }

    html += '</div>';
    el.innerHTML = html;
}

function updateSchematicPanel(circuitData) {
    const el = document.getElementById('schematicArea');
    const toolbar = document.getElementById('schematicToolbar');
    const placeholder = document.getElementById('schematicPlaceholder');
    const compPanel = document.getElementById('componentListPanel');
    const btnRunSim = document.getElementById('btnRunSim');

    el.classList.add('has-content');

    // Show toolbar
    if (toolbar) toolbar.style.display = 'flex';
    if (btnRunSim) btnRunSim.style.display = 'inline-flex';

    // Update toolbar title
    const titleEl = document.getElementById('schematicTitle');
    if (titleEl) {
        titleEl.textContent = circuitData.template_id
            ? `${circuitData.template_id} — ${circuitData.topology_type || ''}`
            : 'Schematic';
    }

    // Show a loading state
    if (placeholder) {
        placeholder.innerHTML = '<i class="fas fa-spinner fa-spin fa-3x"></i><p>Đang render schematic...</p>';
    }

    // Extract the raw circuit template data (components, nets, etc.)
    const templateData = circuitData.circuit_data || circuitData;

    // Call export-kicad endpoint
    exportAndRenderKiCanvas(templateData, el, placeholder, circuitData);

    // Reset PCB state for new circuit and trigger PCB export
    window._pcbReady = false;
    window._pcbRendered = false;
    window._lastPcbContent = null;
    exportAndRenderPCB(templateData, circuitData);

    // Prepare component list panel
    buildComponentListPanel(circuitData, compPanel);
}

/**
 * Call /api/chat/export-kicad → get .kicad_sch → render with KiCanvas
 */
async function exportAndRenderKiCanvas(templateData, container, placeholder, circuitData) {
    console.log('[export] circuitData.circuit_id:', circuitData?.circuit_id);
    try {
        const resp = await fetch('/api/chat/export-kicad', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                circuit_data: templateData,
                circuit_id: circuitData?.circuit_id || null
            }),
        });

        if (!resp.ok) {
            const errData = await resp.json().catch(() => ({}));
            throw new Error(errData.detail?.message || `HTTP ${resp.status}`);
        }

        const result = await resp.json();
        const fileUrl = result.url;  // e.g. "/api/chat/kicad-file/{id}.kicad_sch"

        // Fetch .kicad_sch content
        const contentResp = await fetch(fileUrl);
        const kicadContent = await contentResp.text();

        // Store for download
        window._lastKicadSch = kicadContent;
        window._lastTemplateId = circuitData.template_id || 'circuit';
        window._lastCircuitData = templateData;  // Save circuit data for PCB export

        // Remove old placeholder text
        if (placeholder) placeholder.style.display = 'none';

        // Remove any existing viewer elements
        container.querySelectorAll('kicanvas-embed, .kicanvas-iframe, .fallback-schematic')
            .forEach(el => el.remove());

        // Wait for KiCanvas custom element to be defined
        await customElements.whenDefined('kicanvas-embed');
        console.log('KiCanvas embed defined:', customElements.get('kicanvas-embed') ? 'yes' : 'no');
        console.log('KiCanvas source file URL:', fileUrl);
        console.log('KiCanvas fetched content length:', kicadContent.length);

        const kicanvas = document.createElement('kicanvas-embed');
        configureKiCanvasEmbed(kicanvas);

        // Use inline <kicanvas-source> with content directly embedded
        const source = document.createElement('kicanvas-source');
        source.textContent = kicadContent;
        console.log('KiCanvas inline source attached:', source.textContent.length);
        kicanvas.appendChild(source);

        kicanvas.addEventListener('error', (event) => {
            console.error('KiCanvas embed error event:', event);
        });
        kicanvas.addEventListener('load', (event) => {
            console.log('KiCanvas embed load event:', event);
        });

        container.appendChild(kicanvas);
        scheduleKiCanvasThemeApply(kicanvas);

        // Auto-switch to schematic tab
        switchTab('schematic');

        console.log('KiCanvas schematic rendered via inline source, size:', kicadContent.length);

    } catch (err) {
        console.error('KiCanvas render error:', err);
        // Fallback: show text-based component info
        if (placeholder) {
            placeholder.style.display = 'block';
            placeholder.innerHTML = `
                <i class="fas fa-exclamation-triangle fa-2x" style="color:#d97706"></i>
                <p>Không thể render schematic</p>
                <p class="sub-text" style="font-size:11px">${err.message}</p>
            `;
        }
        // Show fallback component table
        showFallbackSchematic(container, circuitData);
    }
}

/**
 * Fallback: hiển thị bảng linh kiện khi KiCanvas không render được
 */
function showFallbackSchematic(container, circuitData) {
    const fallback = document.createElement('div');
    fallback.className = 'fallback-schematic';
    fallback.style.padding = '16px';

    let html = '';

    // Basic info
    html += '<div class="analysis-section">';
    html += `<h3><i class="fas fa-microchip"></i> ${circuitData.template_id || 'Circuit'}</h3>`;
    html += `<div class="analysis-item"><span class="label">Topology:</span><span class="value">${circuitData.topology_type || 'N/A'}</span></div>`;
    html += `<div class="analysis-item"><span class="label">Gain Formula:</span><span class="value">${circuitData.gain_formula || 'N/A'}</span></div>`;
    if (circuitData.actual_gain != null) {
        html += `<div class="analysis-item"><span class="label">Actual Gain:</span><span class="value">${circuitData.actual_gain.toFixed(2)}</span></div>`;
    }
    html += '</div>';

    // Components table
    const comps = circuitData.circuit_data?.components || circuitData.components || [];
    if (comps.length > 0) {
        html += '<div class="analysis-section">';
        html += '<h3><i class="fas fa-puzzle-piece"></i> Components</h3>';
        html += '<table class="params-table">';
        html += '<tr><th>ID</th><th>Type</th><th>Value</th></tr>';
        for (const comp of comps) {
            const params = comp.parameters || {};
            let value = '-';
            if (params.resistance !== undefined) value = formatValue(params.resistance).value + ' ' + formatValue(params.resistance).unit;
            else if (params.capacitance !== undefined) value = params.capacitance;
            else if (params.model) value = params.model;
            html += `<tr><td><strong>${comp.id}</strong></td><td>${comp.type || '-'}</td><td class="param-value">${value}</td></tr>`;
        }
        html += '</table></div>';
    }

    fallback.innerHTML = html;
    container.appendChild(fallback);
}

function closeActivePcbProgressStream() {
    if (typeof activePcbProgressCloser === 'function') {
        try {
            activePcbProgressCloser();
        } catch (_) {
            // no-op
        }
    }
    activePcbProgressCloser = null;
}

function registerActivePcbProgressCloser(closer) {
    closeActivePcbProgressStream();
    activePcbProgressCloser = typeof closer === 'function' ? closer : null;
}

function resolveIndustrialCircuitId(templateData, circuitData) {
    const candidates = [
        circuitData?.circuit_id,
        circuitData?.meta?.circuit_id,
        circuitData?.circuit_data?.circuit_id,
        circuitData?.circuit_data?.meta?.circuit_id,
        templateData?.circuit_id,
        templateData?.meta?.circuit_id,
    ];

    for (const candidate of candidates) {
        const value = String(candidate || '').trim();
        if (value) return value;
    }

    return '';
}

function escapeHtml(raw) {
    return String(raw ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function toAbsoluteWebSocketUrl(rawUrl) {
    if (!rawUrl) return '';
    const absolute = new URL(rawUrl, window.location.origin);
    if (absolute.protocol === 'https:') {
        absolute.protocol = 'wss:';
    } else if (absolute.protocol === 'http:') {
        absolute.protocol = 'ws:';
    }
    return absolute.toString();
}

function toProgressState(payload) {
    const status = String(payload?.status || '').trim().toLowerCase() || 'queued';
    const progress = payload?.progress && typeof payload.progress === 'object' ? payload.progress : {};
    const totalPhases = Math.max(1, Number(progress.total_phases || 4) || 4);
    const phaseIndex = Math.max(0, Number(progress.phase_index || 0) || 0);
    const phase = String(progress.phase || status || 'queued').trim() || 'queued';
    const rawPercent = Number(progress.progress);
    const percent = Number.isFinite(rawPercent)
        ? Math.max(0, Math.min(100, rawPercent))
        : Math.max(0, Math.min(100, (phaseIndex / totalPhases) * 100));
    const message = String(progress.message || payload?.error || '').trim();

    return {
        status,
        phase,
        phaseIndex,
        totalPhases,
        percent,
        message,
    };
}

function renderPcbProgressPlaceholder(placeholder, payload) {
    if (!placeholder) return;

    const state = toProgressState(payload);
    const safePhase = escapeHtml(state.phase);
    const safeMessage = escapeHtml(state.message || 'Đang xử lý PCB industrial routing...');
    const safePercent = Math.max(0, Math.min(100, state.percent));
    const phaseLabel = `Phase ${Math.min(state.phaseIndex, state.totalPhases)}/${state.totalPhases}`;
    const statusClass = state.status === 'failed'
        ? 'is-error'
        : (state.status === 'completed' ? 'is-done' : 'is-running');

    placeholder.style.display = 'block';
    placeholder.innerHTML = `
        <div class="pcb-progress ${statusClass}">
            <div class="pcb-progress-head">
                <span class="pcb-progress-phase">${escapeHtml(phaseLabel)} • ${safePhase}</span>
                <span class="pcb-progress-percent">${safePercent.toFixed(0)}%</span>
            </div>
            <div class="pcb-progress-bar">
                <div class="pcb-progress-fill" style="width:${safePercent}%"></div>
            </div>
            <p class="pcb-progress-message">${safeMessage}</p>
        </div>
    `;
}

function createIndustrialJobError(message, jobStatus = '') {
    const err = new Error(message);
    err.jobStatus = String(jobStatus || '').trim().toLowerCase();
    return err;
}

async function submitIndustrialPcbExport(circuitId) {
    // Default strict PCB (placement + DRC + 45° routing). Use routing_mode=industrial for legacy A*.
    const qs = new URLSearchParams({ routing_mode: 'strict' });
    const resp = await fetch(
        `/api/circuits/export/${encodeURIComponent(circuitId)}/pcb/industrial/submit?${qs.toString()}`,
        { method: 'POST' },
    );

    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        const message = payload?.detail?.message || payload?.message || `HTTP ${resp.status}`;
        throw createIndustrialJobError(`Không thể submit industrial PCB job: ${message}`, payload?.status);
    }

    return payload;
}

async function fetchIndustrialJobResult(jobInfo) {
    if (!jobInfo?.result_url) {
        throw createIndustrialJobError('Thiếu result_url cho industrial PCB job', 'result_missing');
    }

    const resp = await fetch(jobInfo.result_url, { cache: 'no-store' });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok && resp.status !== 202) {
        const message = payload?.error || payload?.detail?.message || `HTTP ${resp.status}`;
        throw createIndustrialJobError(`Không thể lấy kết quả industrial PCB: ${message}`, payload?.status);
    }
    return payload;
}

function monitorIndustrialJobViaWebSocket(jobInfo, onProgress, isCancelled) {
    return new Promise((resolve, reject) => {
        const wsUrl = toAbsoluteWebSocketUrl(jobInfo?.ws_url);
        if (!wsUrl) {
            reject(createIndustrialJobError('Thiếu ws_url cho industrial PCB stream', 'ws_unavailable'));
            return;
        }

        let settled = false;
        const ws = new WebSocket(wsUrl);

        const finalize = (err, payload) => {
            if (settled) return;
            settled = true;
            if (activePcbProgressCloser === cleanup) {
                activePcbProgressCloser = null;
            }
            cleanup();
            if (err) reject(err);
            else resolve(payload);
        };

        const cleanup = () => {
            try {
                ws.close();
            } catch (_) {
                // no-op
            }
        };

        registerActivePcbProgressCloser(cleanup);

        ws.onmessage = (event) => {
            if (isCancelled()) {
                finalize(createIndustrialJobError('PCB export stream cancelled', 'cancelled'));
                return;
            }

            let payload;
            try {
                payload = JSON.parse(event.data);
            } catch {
                return;
            }

            const eventName = String(payload?.event || '').trim().toLowerCase();
            const data = payload?.data || {};

            if (eventName === 'progress') {
                onProgress(data);
                return;
            }

            if (eventName === 'result') {
                finalize(null, data);
                return;
            }

            if (eventName === 'error') {
                const message = data?.message || data?.error || 'Industrial routing stream error';
                finalize(createIndustrialJobError(String(message), data?.status || 'failed'));
            }
        };

        ws.onerror = () => {
            if (isCancelled()) {
                finalize(createIndustrialJobError('PCB export stream cancelled', 'cancelled'));
                return;
            }
            finalize(createIndustrialJobError('WebSocket stream error', 'ws_error'));
        };

        ws.onclose = () => {
            if (settled) return;
            if (isCancelled()) {
                finalize(createIndustrialJobError('PCB export stream cancelled', 'cancelled'));
                return;
            }
            finalize(createIndustrialJobError('WebSocket closed before completion', 'ws_closed'));
        };
    });
}

function monitorIndustrialJobViaSse(jobInfo, onProgress, isCancelled) {
    return new Promise((resolve, reject) => {
        if (!jobInfo?.events_url || typeof EventSource === 'undefined') {
            reject(createIndustrialJobError('SSE is unavailable in this browser', 'sse_unavailable'));
            return;
        }

        let settled = false;
        const source = new EventSource(jobInfo.events_url);

        const cleanup = () => {
            try {
                source.close();
            } catch (_) {
                // no-op
            }
        };

        const finalize = (err, payload) => {
            if (settled) return;
            settled = true;
            if (activePcbProgressCloser === cleanup) {
                activePcbProgressCloser = null;
            }
            cleanup();
            if (err) reject(err);
            else resolve(payload);
        };

        registerActivePcbProgressCloser(cleanup);

        const parsePayload = (event) => {
            try {
                return JSON.parse(event.data || '{}');
            } catch {
                return null;
            }
        };

        source.addEventListener('progress', (event) => {
            if (isCancelled()) {
                finalize(createIndustrialJobError('PCB export stream cancelled', 'cancelled'));
                return;
            }
            const payload = parsePayload(event);
            if (payload) onProgress(payload);
        });

        source.addEventListener('result', (event) => {
            const payload = parsePayload(event) || {};
            finalize(null, payload);
        });

        source.addEventListener('error', (event) => {
            const payload = parsePayload(event);
            if (!payload || (!payload.message && !payload.error && !payload.status)) {
                return;
            }
            const message = payload?.message || payload?.error || 'Industrial routing stream error';
            finalize(createIndustrialJobError(String(message), payload?.status || 'failed'));
        });

        source.onerror = () => {
            if (settled) return;
            if (source.readyState === EventSource.CLOSED) {
                finalize(createIndustrialJobError('SSE stream closed before completion', 'sse_closed'));
            }
        };
    });
}

async function monitorIndustrialJobViaPolling(jobInfo, onProgress, isCancelled) {
    if (!jobInfo?.status_url) {
        throw createIndustrialJobError('Thiếu status_url cho industrial PCB job', 'poll_unavailable');
    }

    const maxAttempts = 300;
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
        if (isCancelled()) {
            throw createIndustrialJobError('PCB export polling cancelled', 'cancelled');
        }

        const resp = await fetch(jobInfo.status_url, { cache: 'no-store' });
        const statusPayload = await resp.json().catch(() => ({}));

        if (!resp.ok) {
            const message = statusPayload?.detail?.message || statusPayload?.error || `HTTP ${resp.status}`;
            throw createIndustrialJobError(`Không thể lấy trạng thái industrial PCB: ${message}`, statusPayload?.status);
        }

        onProgress(statusPayload);

        const statusValue = String(statusPayload?.status || '').trim().toLowerCase();
        if (statusValue === 'completed') {
            return fetchIndustrialJobResult(jobInfo);
        }
        if (statusValue === 'failed') {
            const message = statusPayload?.error || 'Industrial routing failed';
            throw createIndustrialJobError(String(message), 'failed');
        }

        await new Promise((resolve) => setTimeout(resolve, 900));
    }

    throw createIndustrialJobError('Hết thời gian chờ industrial PCB job', 'timeout');
}

async function monitorIndustrialPcbJob(jobInfo, onProgress, isCancelled) {
    if (isCancelled()) {
        throw createIndustrialJobError('PCB export stream cancelled', 'cancelled');
    }

    try {
        return await monitorIndustrialJobViaWebSocket(jobInfo, onProgress, isCancelled);
    } catch (wsError) {
        if (String(wsError?.jobStatus || '').toLowerCase() === 'failed') {
            throw wsError;
        }
        if (isCancelled()) {
            throw createIndustrialJobError('PCB export stream cancelled', 'cancelled');
        }
        console.warn('WebSocket tracking failed, fallback to SSE:', wsError);
    }

    try {
        return await monitorIndustrialJobViaSse(jobInfo, onProgress, isCancelled);
    } catch (sseError) {
        if (String(sseError?.jobStatus || '').toLowerCase() === 'failed') {
            throw sseError;
        }
        if (isCancelled()) {
            throw createIndustrialJobError('PCB export stream cancelled', 'cancelled');
        }
        console.warn('SSE tracking failed, fallback to polling:', sseError);
    }

    return monitorIndustrialJobViaPolling(jobInfo, onProgress, isCancelled);
}

/**
 * Export circuit to PCB and render inline with KiCanvas
 */
async function exportAndRenderPCB(templateData, circuitData) {
    const container = document.getElementById('pcbArea');
    const toolbar = document.getElementById('pcbToolbar');
    const placeholder = document.getElementById('pcbPlaceholder');

    if (!container) return;

    closeActivePcbProgressStream();
    const requestToken = `${Date.now()}_${Math.random().toString(16).slice(2)}`;
    window._activePcbExportToken = requestToken;
    const isCancelled = () => window._activePcbExportToken !== requestToken;

    // Show toolbar
    if (toolbar) toolbar.style.display = 'flex';

    // Update toolbar title
    const titleEl = document.getElementById('pcbTitle');
    if (titleEl) {
        titleEl.textContent = circuitData.template_id
            ? `PCB — ${circuitData.template_id}`
            : 'PCB Layout';
    }

    // Show loading
    if (placeholder) {
        placeholder.style.display = 'block';
        placeholder.innerHTML = '<i class="fas fa-spinner fa-spin fa-3x"></i><p>Đang tạo PCB layout...</p>';
    }

    const finalizePcbReady = async (fileUrl, sourceLabel) => {
        const contentResp = await fetch(fileUrl);
        if (!contentResp.ok) {
            throw new Error(`${sourceLabel}: không thể tải file PCB (HTTP ${contentResp.status})`);
        }

        const pcbContent = await contentResp.text();
        if (isCancelled()) return;

        window._lastPcbContent = pcbContent;
        window._pcbReady = true;
        window._pcbRendered = false;

        if (placeholder) {
            placeholder.innerHTML = '<i class="fas fa-check-circle fa-3x" style="color:#10b981"></i><p>PCB sẵn sàng - chuyển sang tab PCB để xem</p>';
        }

        if (currentTab === 'pcb') {
            renderPCBKiCanvas();
        }

        console.log(`${sourceLabel} PCB export ready, size:`, pcbContent.length);
    };

    try {
        const circuitId = resolveIndustrialCircuitId(templateData, circuitData);
        if (circuitId) {
            try {
                renderPcbProgressPlaceholder(placeholder, {
                    status: 'queued',
                    progress: {
                        phase: 'queued',
                        phase_index: 0,
                        total_phases: 4,
                        progress: 0,
                        message: 'Đang submit industrial PCB job...',
                    },
                });

                const jobInfo = await submitIndustrialPcbExport(circuitId);
                if (isCancelled()) return;

                renderPcbProgressPlaceholder(placeholder, jobInfo);

                const finalPayload = await monitorIndustrialPcbJob(
                    jobInfo,
                    (progressPayload) => {
                        if (isCancelled()) return;
                        renderPcbProgressPlaceholder(placeholder, progressPayload);
                    },
                    isCancelled,
                );

                if (isCancelled()) return;

                const resultPayload = finalPayload?.result && typeof finalPayload.result === 'object'
                    ? finalPayload.result
                    : finalPayload;
                const fileUrl = resultPayload?.download_url || resultPayload?.url;

                if (!fileUrl) {
                    throw createIndustrialJobError(
                        'Industrial PCB job hoàn tất nhưng thiếu download_url',
                        finalPayload?.status || 'failed',
                    );
                }

                closeActivePcbProgressStream();
                await finalizePcbReady(fileUrl, 'Industrial');
                return;
            } catch (industrialError) {
                if (isCancelled()) return;

                const industrialStatus = String(industrialError?.jobStatus || '').toLowerCase();
                if (industrialStatus === 'failed') {
                    throw industrialError;
                }

                console.warn('Industrial PCB flow unavailable, fallback to legacy export:', industrialError);
                if (placeholder) {
                    placeholder.innerHTML = '<i class="fas fa-spinner fa-spin fa-2x"></i><p>Fallback sang chế độ export PCB tiêu chuẩn...</p>';
                }
            }
        }

        closeActivePcbProgressStream();

        const resp = await fetch('/api/chat/export-pcb', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                circuit_data: templateData,
                circuit_id: circuitData?.circuit_id || null
            }),
        });

        if (!resp.ok) {
            const errData = await resp.json().catch(() => ({}));
            throw new Error(errData.detail?.message || `HTTP ${resp.status}`);
        }

        const result = await resp.json();
        const fileUrl = result.url;
        await finalizePcbReady(fileUrl, 'Legacy');

    } catch (err) {
        console.error('PCB render error:', err);
        closeActivePcbProgressStream();
        window._pcbReady = false;
        if (isCancelled()) return;

        if (placeholder) {
            placeholder.style.display = 'block';
            placeholder.innerHTML = `
                <i class="fas fa-exclamation-triangle fa-2x" style="color:#d97706"></i>
                <p>Không thể tạo PCB</p>
                <p class="sub-text" style="font-size:11px">${escapeHtml(err.message || 'Unknown error')}</p>
            `;
        }
    }
}

/**
 * Actually render the PCB in KiCanvas — called when the PCB tab becomes visible.
 */
async function renderPCBKiCanvas() {
    if (!window._lastPcbContent || window._pcbRendered) return;

    const container = document.getElementById('pcbArea');
    const placeholder = document.getElementById('pcbPlaceholder');
    if (!container) return;

    // Hide placeholder
    if (placeholder) placeholder.style.display = 'none';

    // Remove any existing viewer elements
    container.querySelectorAll('kicanvas-embed, .pcb-fallback')
        .forEach(el => el.remove());

    // Wait for KiCanvas custom element
    await customElements.whenDefined('kicanvas-embed');

    const kicanvas = document.createElement('kicanvas-embed');
    configureKiCanvasEmbed(kicanvas);

    // Use inline <kicanvas-source> with PCB content
    const source = document.createElement('kicanvas-source');
    source.setAttribute('filename', 'circuit.kicad_pcb');
    source.textContent = window._lastPcbContent;
    kicanvas.appendChild(source);

    container.appendChild(kicanvas);
    container.classList.add('has-content');
    window._pcbRendered = true;
    scheduleKiCanvasThemeApply(kicanvas);

    console.log('KiCanvas PCB rendered, size:', window._lastPcbContent.length);
}

/**
 * Build component list side panel
 */
function buildComponentListPanel(circuitData, panel) {
    if (!panel) return;

    const comps = circuitData.circuit_data?.components || circuitData.components || [];
    if (comps.length === 0) { panel.style.display = 'none'; return; }

    let html = '<div style="padding:12px">';
    html += `<h4 style="margin:0 0 8px"><i class="fas fa-list"></i> ${comps.length} linh kiện</h4>`;
    html += '<table class="params-table" style="font-size:11px">';
    html += '<tr><th>ID</th><th>Type</th><th>Value</th></tr>';
    for (const comp of comps) {
        const params = comp.parameters || {};
        let value = '-';
        if (params.resistance !== undefined) value = formatValue(params.resistance).value + ' Ω';
        else if (params.capacitance !== undefined) value = (params.capacitance * 1e6).toFixed(1) + ' µF';
        else if (params.model) value = params.model;
        else if (params.voltage) value = params.voltage + 'V';
        html += `<tr><td><strong>${comp.id}</strong></td><td>${comp.type}</td><td>${value}</td></tr>`;
    }
    html += '</table>';

    // Validation
    if (circuitData.validation) {
        const v = circuitData.validation;
        html += `<div style="margin-top:8px;font-size:11px"><strong>Validation:</strong> ${v.passed ? '✅' : '❌'}`;
        if (v.warnings?.length > 0) html += ` (${v.warnings.length} warnings)`;
        html += '</div>';
    }

    // Extensions
    if (circuitData.suggested_extensions?.length > 0) {
        html += '<div style="margin-top:8px;font-size:11px"><strong>Đề xuất:</strong></div>';
        for (const ext of circuitData.suggested_extensions) {
            html += `<div style="font-size:10px;padding:4px;margin:2px 0;background:#fffbeb;border-radius:3px">+ ${ext.extension_block}: ${ext.reason || ''}</div>`;
        }
    }

    html += '</div>';
    panel.innerHTML = html;
}

// ── Tabs ──
function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));

    document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
    document.getElementById(`tab-${tab}`).classList.add('active');

    if (tab === 'waveform' && waveformChart) {
        // Ensure chart reflows after the hidden tab becomes visible.
        requestAnimationFrame(() => {
            waveformChart.resize();
            if (lastWaveformPayload) {
                updateWaveformDebug(lastWaveformPayload, { event: 'resize' });
            }
        });
    }

    // Deferred PCB render: only render when tab becomes visible
    if (tab === 'pcb' && window._pcbReady && !window._pcbRendered) {
        renderPCBKiCanvas();
    }
}

function extractWaveformSimMeta(payload) {
    const p = payload && typeof payload === 'object' ? payload : {};
    const core = p.circuit_data
        || pendingWaveformSimMeta?.circuit_data
        || lastCircuitData?.circuit_data
        || {};
    const meta = core.meta || {};
    const sp = p.source_params || pendingWaveformSimMeta?.source_params || core.source_params || {};
    const freq = Number(
        sp.frequency
        ?? meta.input_frequency_hz
        ?? meta.frequency_hz
        ?? p.analysis?.gain_metrics?.frequency_hz,
    );
    return {
        frequency_hz: Number.isFinite(freq) && freq > 0 ? freq : null,
        input_frequency_hz: meta.input_frequency_hz ?? null,
        source_params: sp,
        analysis: p.analysis || null,
    };
}

/** Ước lượng tần số (Hz) từ zero-crossing trên trace AC. */
function estimateFrequencyFromTrace(trace, tMin, tMax) {
    const xs = Array.isArray(trace?.x) ? trace.x : [];
    const ys = Array.isArray(trace?.y) ? trace.y : [];
    const n = Math.min(xs.length, ys.length);
    if (n < 16) return null;

    const tLo = Number.isFinite(tMin) ? tMin : Number(xs[0]);
    const tHi = Number.isFinite(tMax) ? tMax : Number(xs[n - 1]);
    if (!(tHi > tLo)) return null;

    const samples = [];
    for (let i = 0; i < n; i++) {
        const t = Number(xs[i]);
        const y = Number(ys[i]);
        if (!Number.isFinite(t) || !Number.isFinite(y)) continue;
        if (t < tLo || t > tHi) continue;
        samples.push({ t, y });
    }
    if (samples.length < 16) return null;

    let mean = 0;
    for (const s of samples) mean += s.y;
    mean /= samples.length;

    const crossings = [];
    for (let i = 1; i < samples.length; i++) {
        const a = samples[i - 1].y - mean;
        const b = samples[i].y - mean;
        if (a === 0 || a * b > 0) continue;
        const t0 = samples[i - 1].t;
        const t1 = samples[i].t;
        const frac = Math.abs(a) / (Math.abs(a) + Math.abs(b));
        crossings.push(t0 + frac * (t1 - t0));
    }
    if (crossings.length < 3) return null;

    const halfPeriods = [];
    for (let i = 1; i < crossings.length; i++) {
        const dt = crossings[i] - crossings[i - 1];
        if (dt > 0) halfPeriods.push(dt);
    }
    if (!halfPeriods.length) return null;

    halfPeriods.sort((a, b) => a - b);
    const medianHalf = halfPeriods[Math.floor(halfPeriods.length / 2)];
    const period = medianHalf * 2;
    if (!(period > 0)) return null;
    const hz = 1 / period;
    return Number.isFinite(hz) && hz > 0 ? hz : null;
}

function resolveWaveformFrequencyHz(waveform, tMin, tMax) {
    const m = lastWaveformSimMeta || {};
    const candidates = [
        m.frequency_hz,
        m.input_frequency_hz,
        m.source_params?.frequency,
        waveform?.meta?.frequency_hz,
        waveform?.meta?.input_frequency_hz,
        lastCircuitData?.circuit_data?.source_params?.frequency,
        lastCircuitData?.circuit_data?.meta?.input_frequency_hz,
    ];
    for (const c of candidates) {
        const n = Number(c);
        if (Number.isFinite(n) && n > 0) return n;
    }
    const { inTrace } = pickInputOutputTraces(waveform?.traces || []);
    if (inTrace) {
        const est = estimateFrequencyFromTrace(inTrace, tMin, tMax);
        if (est > 0) return est;
    }
    return null;
}

function getWaveformDisplayWindow(waveform, xScaleMin, xScaleMax) {
    let tStart = xScaleMin;
    let tEnd = xScaleMax;
    if (!Number.isFinite(tStart) || !Number.isFinite(tEnd)) {
        let dataMin = Infinity;
        let dataMax = -Infinity;
        for (const tr of waveform?.traces || []) {
            for (const x of tr.x || []) {
                const v = Number(x);
                if (!Number.isFinite(v)) continue;
                if (v < dataMin) dataMin = v;
                if (v > dataMax) dataMax = v;
            }
        }
        tStart = Number.isFinite(dataMin) ? dataMin : 0;
        tEnd = Number.isFinite(dataMax) ? dataMax : tStart + 1e-3;
    }
    if (!(tEnd > tStart)) tEnd = tStart + 1e-9;
    return { tStartS: tStart, tEndS: tEnd };
}

/**
 * Points = TimeRange × f × N  (N = WF_SMOOTH.RESOLUTION, mặc định 128).
 */
function computeDisplayPointCount(timeRangeS, frequencyHz, resolutionN = WF_SMOOTH.RESOLUTION) {
    const dt = Number(timeRangeS);
    const f = Number(frequencyHz);
    const N = Number(resolutionN);
    if (!(dt > 0) || !Number.isFinite(f) || f <= 0 || !Number.isFinite(N) || N <= 0) {
        return { totalPoints: WF_SMOOTH.MIN_TOTAL, resolutionN: N, capped: false };
    }
    let nEff = Math.max(WF_SMOOTH.MIN_PPC, N);
    let totalPoints = Math.max(2, Math.ceil(dt * f * nEff) + 1);
    let capped = false;
    if (totalPoints > WF_SMOOTH.MAX_TOTAL) {
        nEff = Math.max(WF_SMOOTH.MIN_PPC, WF_SMOOTH.MAX_TOTAL / (dt * f));
        totalPoints = Math.max(2, Math.ceil(dt * f * nEff) + 1);
        capped = true;
    }
    totalPoints = Math.min(WF_SMOOTH.MAX_TOTAL, Math.max(WF_SMOOTH.MIN_TOTAL, totalPoints));
    return { totalPoints, resolutionN: nEff, capped };
}

function computeWaveformSamplePlan({ tStartS, tEndS, frequencyHz, rawPointCount }) {
    const timeRangeS = tEndS - tStartS;
    if (!(timeRangeS > 0)) {
        return { resample: false, applied: false };
    }

    const f = Number(frequencyHz);
    let periodS = null;
    let cycles = null;
    let pointsPerCycle = null;
    let totalPoints;
    let resolutionCapped = false;

    if (Number.isFinite(f) && f > 0) {
        periodS = 1 / f;
        cycles = timeRangeS * f;
        const planned = computeDisplayPointCount(timeRangeS, f, WF_SMOOTH.RESOLUTION);
        totalPoints = planned.totalPoints;
        pointsPerCycle = planned.resolutionN;
        resolutionCapped = planned.capped;
    } else {
        totalPoints = Math.max(WF_SMOOTH.MIN_TOTAL, Math.ceil(timeRangeS * 4000));
    }

    const stepS = timeRangeS / Math.max(totalPoints - 1, 1);
    const rawSparse = Number.isFinite(f) && f > 0 && rawPointCount > 0
        && rawPointCount < Math.ceil(timeRangeS * f * WF_SMOOTH.MIN_PPC);

    return {
        resample: Number.isFinite(f) && f > 0,
        resampleMode: 'linear',
        applied: false,
        userTimeWindow: waveformTimeRange.startS !== null || waveformTimeRange.endS !== null,
        frequencyHz: Number.isFinite(f) && f > 0 ? f : null,
        periodS,
        cycles,
        pointsPerCycle,
        resolutionN: pointsPerCycle,
        resolutionCapped,
        totalPoints,
        timeRangeS,
        dtS: timeRangeS,
        tStartS,
        tEndS,
        stepS,
        rawPointCount: rawPointCount || 0,
        rawSparse,
        formula: Number.isFinite(f) && f > 0
            ? `Points = ${timeRangeS.toExponential(3)} × ${f} × ${pointsPerCycle}`
            : null,
    };
}

function interpTraceAt(trace, t) {
    const xs = trace?.x || [];
    const ys = trace?.y || [];
    const n = Math.min(xs.length, ys.length);
    if (n === 0) return NaN;
    const tNum = Number(t);
    const x0n = Number(xs[0]);
    const xNn = Number(xs[n - 1]);
    if (tNum <= x0n) return Number(ys[0]);
    if (tNum >= xNn) return Number(ys[n - 1]);

    let lo = 0;
    let hi = n - 1;
    while (lo < hi - 1) {
        const mid = (lo + hi) >> 1;
        if (Number(xs[mid]) <= tNum) lo = mid;
        else hi = mid;
    }
    const xa = Number(xs[lo]);
    const xb = Number(xs[hi]);
    const ya = Number(ys[lo]);
    const yb = Number(ys[hi]);
    if (xb === xa) return ya;
    const u = (tNum - xa) / (xb - xa);
    return ya + u * (yb - ya);
}

function resampleTraceLinear(trace, plan) {
    const xs = [];
    const ys = [];
    for (let i = 0; i < plan.totalPoints; i++) {
        const t = plan.tStartS + i * plan.stepS;
        xs.push(t);
        ys.push(interpTraceAt(trace, t));
    }
    return { ...trace, x: xs, y: ys };
}

/** Giảm số điểm hiển thị nhưng giữ biên đỉnh (tránh gain nhìn bị sai). */
function resampleTraceMinMax(trace, plan) {
    const srcX = trace?.x || [];
    const srcY = trace?.y || [];
    const n = Math.min(srcX.length, srcY.length);
    if (n <= plan.totalPoints) return trace;

    const t0 = plan.tStartS;
    const t1 = plan.tEndS;
    const bucketCount = Math.max(2, Math.floor(plan.totalPoints / 2));
    const span = Math.max(t1 - t0, 1e-15);
    const bucketW = span / bucketCount;
    const buckets = Array.from({ length: bucketCount }, () => []);

    for (let i = 0; i < n; i++) {
        const tx = Number(srcX[i]);
        const ty = Number(srcY[i]);
        if (!Number.isFinite(tx) || !Number.isFinite(ty)) continue;
        if (tx < t0 || tx > t1) continue;
        let b = Math.floor((tx - t0) / bucketW);
        if (b >= bucketCount) b = bucketCount - 1;
        buckets[b].push({ x: tx, y: ty });
    }

    const xs = [];
    const ys = [];
    for (const bucket of buckets) {
        if (!bucket.length) continue;
        let minPt = bucket[0];
        let maxPt = bucket[0];
        for (const pt of bucket) {
            if (pt.y < minPt.y) minPt = pt;
            if (pt.y > maxPt.y) maxPt = pt;
        }
        if (minPt.x <= maxPt.x) {
            xs.push(minPt.x, maxPt.x);
            ys.push(minPt.y, maxPt.y);
        } else {
            xs.push(maxPt.x, minPt.x);
            ys.push(maxPt.y, minPt.y);
        }
    }
    return { ...trace, x: xs, y: ys };
}

function resampleTraceForDisplay(trace, plan) {
    if (!plan?.resample) return trace;
    return resampleTraceLinear(trace, plan);
}

function countRawPointsInWindow(trace, tStart, tEnd) {
    const xs = trace?.x || [];
    let count = 0;
    for (const x of xs) {
        const v = Number(x);
        if (Number.isFinite(v) && v >= tStart && v <= tEnd) count++;
    }
    return count;
}

/** Lọc + nội suy tuyến tính để đạt độ mịn mục tiêu trong cửa sổ hiển thị. */
function prepareWaveformForDisplay(waveform, { xScaleMin, xScaleMax, canvasWidthPx }) {
    if (!waveform || !Array.isArray(waveform.traces) || !waveform.traces.length) {
        return { waveform, plan: null };
    }

    const win = getWaveformDisplayWindow(waveform, xScaleMin, xScaleMax);
    const freq = resolveWaveformFrequencyHz(waveform, win.tStartS, win.tEndS);
    const ref = waveform.traces[0];
    const rawInWindow = countRawPointsInWindow(ref, win.tStartS, win.tEndS)
        || (ref?.x?.length || 0);

    const plan = computeWaveformSamplePlan({
        ...win,
        frequencyHz: freq,
        rawPointCount: rawInWindow,
    });

    if (!plan.resample) {
        return { waveform, plan: { ...plan, applied: false } };
    }

    const traces = waveform.traces.map((tr) => resampleTraceForDisplay(tr, plan));
    return {
        waveform: { ...waveform, traces },
        plan: { ...plan, applied: true },
    };
}

function updateWaveformSmoothInfo(plan) {
    let el = document.getElementById('wfSmoothInfo');
    const toolbar = document.getElementById('waveformToolbar');
    if (!toolbar) return;

    if (!el) {
        el = document.createElement('div');
        el.id = 'wfSmoothInfo';
        el.className = 'wf-smooth-info';
        toolbar.appendChild(el);
    }

    if (!plan) {
        el.hidden = true;
        return;
    }

    const parts = [];
    if (plan.frequencyHz) {
        const f = plan.frequencyHz;
        const fLabel = f >= 1000 ? `${(f / 1000).toFixed(3)} kHz` : `${f.toFixed(1)} Hz`;
        parts.push(`f = ${fLabel}`);
    }
    if (plan.timeRangeS != null) {
        parts.push(`Δt = ${formatTimeAxisLabel(plan.timeRangeS)}`);
    }
    if (plan.cycles != null) {
        parts.push(`${plan.cycles.toFixed(2)} chu kỳ`);
    }
    if (plan.resolutionN) {
        parts.push(`N = ${Number(plan.resolutionN).toFixed(1)}`);
    }
    if (plan.totalPoints) {
        parts.push(`${plan.totalPoints} điểm (= Δt×f×N)`);
    }
    if (plan.rawSparse) {
        parts.push('⚠ dữ liệu gốc thưa — chạy lại mô phỏng');
    } else if (plan.resolutionCapped) {
        parts.push('N giảm do giới hạn hiển thị');
    }
    if (plan.applied) {
        parts.push('đã nội suy theo công thức');
    } else if (plan.resample === false) {
        parts.push('chưa có tần số — không nội suy');
    }

    const dataMaxS = getWaveformDataMaxSeconds(lastWaveformPayload || null);
    const viewEndS = waveformTimeRange.endS;
    if (Number.isFinite(viewEndS) && viewEndS > MAX_TRAN_STOP_S * 1.001) {
        parts.push(`⚠ tối đa ${MAX_WAVEFORM_MS} ms`);
    } else if (Number.isFinite(viewEndS) && dataMaxS > 0 && viewEndS > dataMaxS * 1.001) {
        parts.push(`⚠ dữ liệu chỉ đến ${formatTimeAxisLabel(dataMaxS)} — chạy lại mô phỏng`);
    }

    if (!parts.length) {
        el.hidden = true;
        return;
    }

    el.hidden = false;
    el.textContent = `Độ mịn: ${parts.join(' · ')}`;
}

function getWaveformDataMaxSeconds(waveform) {
    const traces = Array.isArray(waveform?.traces) ? waveform.traces : [];
    let dataMaxS = 0;
    for (const t of traces) {
        const m = traceTimeMaxS(t);
        if (m > dataMaxS) dataMaxS = m;
    }
    return dataMaxS;
}

/**
 * Format a time value (in seconds) for the x-axis tick labels.
 * Automatically picks the most readable unit (ms, µs, s).
 */
function formatTimeAxisLabel(valueS) {
    const abs = Math.abs(valueS);
    if (abs === 0) return '0';
    if (abs < 1e-3) return `${(valueS * 1e6).toPrecision(3)} µs`;
    if (abs < 1) return `${(valueS * 1e3).toPrecision(4)} ms`;
    return `${valueS.toPrecision(4)} s`;
}

function renderWaveform(waveform) {
    const canvas = document.getElementById('waveformCanvas');
    const empty = document.getElementById('waveformEmpty');
    if (!canvas || !waveform || !Array.isArray(waveform.traces)) return;

    // Show the toolbar once we have data
    ensureWaveformToolbar(waveform);

    // Compute x-axis range from waveformTimeRange state
    const xScaleMin = waveformTimeRange.startS !== null ? waveformTimeRange.startS : undefined;
    const xScaleMax = waveformTimeRange.endS !== null   ? waveformTimeRange.endS   : undefined;

    const canvasW = canvas.clientWidth || canvas.getBoundingClientRect().width || 800;
    const prepared = prepareWaveformForDisplay(waveform, { xScaleMin, xScaleMax, canvasWidthPx: canvasW });
    const displayWaveform = prepared.waveform;
    lastWaveformSmoothPlan = prepared.plan;
    updateWaveformSmoothInfo(prepared.plan);

    // If CDN Chart.js is blocked (tracking prevention / offline), draw directly on canvas.
    if (typeof Chart === 'undefined') {
        renderWaveformFallbackCanvas(canvas, displayWaveform, xScaleMin, xScaleMax);
        if (empty) empty.style.display = 'none';
        updateWaveformNotice(displayWaveform);
        updateWaveformDebug(lastWaveformPayload || displayWaveform, {
            event: 'render-fallback',
            chartBlocked: true,
            smoothPlan: prepared.plan,
        });
        return;
    }

    const datasets = displayWaveform.traces.map((trace, idx) => ({
        label: trace.unit ? `${trace.name} (${trace.unit})` : trace.name,
        data: (trace.x || []).map((x, i) => ({ x, y: (trace.y || [])[i] })),
        borderColor: pickChartColor(idx),
        backgroundColor: 'transparent',
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.15,
    }));

    if (waveformChart) {
        waveformChart.destroy();
    }

    waveformChart = new Chart(canvas, {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            parsing: false,
            animation: false,
            interaction: { mode: 'nearest', axis: 'x', intersect: false },
            scales: {
                x: {
                    type: 'linear',
                    min: xScaleMin,
                    max: xScaleMax,
                    title: { display: true, text: waveform.x_label || 'time (s)' },
                    ticks: {
                        callback: (v) => formatTimeAxisLabel(v),
                        maxTicksLimit: 8,
                    },
                },
                y: {
                    title: { display: true, text: 'Biên độ (V)' },
                },
            },
            plugins: {
                legend: { display: true, position: 'top' },
                tooltip: {
                    callbacks: {
                        title: (items) => `t = ${formatTimeAxisLabel(items[0]?.parsed?.x ?? 0)}`,
                    },
                },
            },
        },
    });

    if (empty) empty.style.display = 'none';
    updateWaveformNotice(displayWaveform);
    updateWaveformDebug(lastWaveformPayload || displayWaveform, {
        event: 'render',
        xScaleMin,
        xScaleMax,
        smoothPlan: prepared.plan,
    });
}

const WF_PRESET_MS = ['auto', '1', '5', '10', '15', '20'];

function _wfPresetLabel(ms) {
    if (ms === 'auto') return 'Auto';
    const n = Number(ms);
    if (!Number.isFinite(n)) return ms;
    return `${n} ms`;
}

function _syncWaveformPresetButtons(presetGroup) {
    const sig = WF_PRESET_MS.join(',');
    if (presetGroup.dataset.wfPresetSig === sig && presetGroup.querySelector('.wf-preset-btn')) {
        return false;
    }
    presetGroup.dataset.wfPresetSig = sig;
    const activeEndMs = waveformTimeRange.endS !== null
        ? String(Math.round(waveformTimeRange.endS * 1000))
        : 'auto';
    presetGroup.innerHTML = WF_PRESET_MS.map((ms) => {
        const isAuto = ms === 'auto'
            && waveformTimeRange.startS === null
            && waveformTimeRange.endS === null;
        const isActive = isAuto || (ms === activeEndMs && waveformTimeRange.startS === 0);
        return `<button type="button" class="wf-preset-btn${isActive ? ' wf-preset-active' : ''}" data-ms="${ms}" title="${ms === 'auto' ? 'Tự động (0 → 20 ms)' : `0 → ${ms} ms`}">${_wfPresetLabel(ms)}</button>`;
    }).join('');
    return true;
}

/**
 * Ensure waveform toolbar DOM exists (handles stale cached index.html).
 * Returns the toolbar element or null.
 */
function ensureWaveformToolbarElement() {
    const panel = document.querySelector('#tab-waveform .waveform-panel');
    if (!panel) return null;

    let toolbar = document.getElementById('waveformToolbar');
    if (!toolbar) {
        toolbar = document.createElement('div');
        toolbar.id = 'waveformToolbar';
        toolbar.className = 'waveform-toolbar';
        toolbar.hidden = true;
        const canvasWrap = panel.querySelector('.waveform-canvas-wrap');
        if (canvasWrap) {
            panel.insertBefore(toolbar, canvasWrap);
        } else {
            panel.appendChild(toolbar);
        }
    }

    toolbar.classList.add('waveform-toolbar');

    // Rebuild preset row if missing (old cached HTML)
    if (!toolbar.querySelector('#waveformPresets')) {
        const presetsRow = document.createElement('div');
        presetsRow.className = 'wf-toolbar-row wf-toolbar-presets';
        presetsRow.innerHTML = `
            <span class="wf-toolbar-label"><i class="fas fa-clock"></i> Thời gian hiển thị:</span>
            <div id="waveformPresets" class="wf-preset-group"></div>`;
        toolbar.appendChild(presetsRow);
    }

    const presetGroup = toolbar.querySelector('#waveformPresets');
    if (presetGroup && _syncWaveformPresetButtons(presetGroup)) {
        toolbar.dataset.listenersAttached = '';
    }

    // Rebuild custom range row if missing — this was the main gap on cached HTML
    if (!document.getElementById('wfRangeEnd') || !document.getElementById('wfCustomRow')) {
        const oldCustom = toolbar.querySelector('#wfCustomRow');
        if (oldCustom) oldCustom.remove();

        const customRow = document.createElement('div');
        customRow.className = 'wf-toolbar-row wf-toolbar-custom';
        customRow.id = 'wfCustomRow';
        customRow.innerHTML = `
            <span class="wf-toolbar-label"><i class="fas fa-sliders"></i> Tùy chỉnh:</span>
            <label class="wf-range-label" for="wfRangeStart">Từ</label>
            <input id="wfRangeStart" class="wf-range-input" type="number" min="0" step="any" value="0" title="Thời gian bắt đầu (ms)">
            <label class="wf-range-label" for="wfRangeEnd">đến</label>
            <input id="wfRangeEnd" class="wf-range-input" type="number" min="0" max="20" step="any" placeholder="≤20 ms" title="Thời gian kết thúc (ms, tối đa 20)">
            <span class="wf-range-unit">ms</span>
            <button type="button" id="wfRangeApply" class="wf-range-apply"><i class="fas fa-check"></i> Áp dụng</button>`;
        toolbar.appendChild(customRow);
        toolbar.dataset.listenersAttached = '';
    }

    return toolbar;
}

/** Wire toolbar controls once at startup (and after DOM repair). */
function initWaveformToolbar() {
    const toolbar = ensureWaveformToolbarElement();
    if (!toolbar) return;

    if (toolbar.dataset.listenersAttached === '1') return;
    toolbar.dataset.listenersAttached = '1';

    toolbar.querySelectorAll('.wf-preset-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
            toolbar.querySelectorAll('.wf-preset-btn').forEach((b) => b.classList.remove('wf-preset-active'));
            btn.classList.add('wf-preset-active');

            const ms = btn.dataset.ms;
            if (ms === 'auto') {
                waveformTimeRange = { startS: null, endS: null };
                const s = document.getElementById('wfRangeStart');
                const e = document.getElementById('wfRangeEnd');
                if (s) s.value = '0';
                if (e) e.value = '';
            } else {
                const endMs = clampWaveformEndMs(Number(ms), 0);
                const endS = endMs / 1000;
                waveformTimeRange = { startS: 0, endS };
                const s = document.getElementById('wfRangeStart');
                const e = document.getElementById('wfRangeEnd');
                if (s) s.value = '0';
                if (e) e.value = String(endMs);
            }
            if (lastWaveformPayload) renderWaveform(lastWaveformPayload);
        });
    });

    const applyBtn = document.getElementById('wfRangeApply');
    if (applyBtn) {
        applyBtn.addEventListener('click', () => {
            const startMs = parseFloat(document.getElementById('wfRangeStart')?.value ?? '0') || 0;
            const rawEndMs = parseFloat(document.getElementById('wfRangeEnd')?.value ?? '');
            const endMs = clampWaveformEndMs(rawEndMs, startMs);
            if (!Number.isFinite(rawEndMs) || endMs <= startMs) {
                document.getElementById('wfRangeEnd')?.focus();
                return;
            }
            const endInput = document.getElementById('wfRangeEnd');
            if (endInput) endInput.value = String(endMs);
            waveformTimeRange = { startS: startMs / 1000, endS: endMs / 1000 };
            toolbar.querySelectorAll('.wf-preset-btn').forEach((b) => b.classList.remove('wf-preset-active'));
            if (lastWaveformPayload) renderWaveform(lastWaveformPayload);
        });
    }

    const endInput = document.getElementById('wfRangeEnd');
    if (endInput) {
        endInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') document.getElementById('wfRangeApply')?.click();
        });
    }
}

/**
 * Show the time-range toolbar when waveform data is available.
 */
function ensureWaveformToolbar(waveform) {
    initWaveformToolbar();
    const toolbar = ensureWaveformToolbarElement();
    if (!toolbar) return;

    toolbar.hidden = false;
    toolbar.removeAttribute('style');

    const traces = Array.isArray(waveform?.traces) ? waveform.traces : [];
    let dataMaxS = 0;
    for (const t of traces) {
        const m = traceTimeMaxS(t);
        if (m > dataMaxS) dataMaxS = m;
    }

    const autoBtn = toolbar.querySelector('[data-ms="auto"]');
    if (autoBtn) {
        autoBtn.title = `Tự động khớp dữ liệu (0 → ${formatTimeAxisLabel(dataMaxS)})`;
    }
}

function renderWaveformFallbackCanvas(canvas, waveform, xScaleMin, xScaleMax) {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = canvas.clientWidth || 800;
    const height = canvas.clientHeight || 320;
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;

    const traces = (waveform.traces || []).filter((t) => Array.isArray(t.x) && Array.isArray(t.y) && t.x.length && t.y.length);
    if (!traces.length) {
        ctx.clearRect(0, 0, width, height);
        return;
    }

    let xMin = Infinity;
    let xMax = -Infinity;
    let yMin = Infinity;
    let yMax = -Infinity;

    for (const t of traces) {
        const n = Math.min(t.x.length, t.y.length);
        for (let i = 0; i < n; i++) {
            const x = Number(t.x[i]);
            const y = Number(t.y[i]);
            if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
            if (x < xMin) xMin = x;
            if (x > xMax) xMax = x;
            if (y < yMin) yMin = y;
            if (y > yMax) yMax = y;
        }
    }

    if (!Number.isFinite(xMin) || !Number.isFinite(xMax) || !Number.isFinite(yMin) || !Number.isFinite(yMax)) return;
    // Apply user-selected time range if set
    if (xScaleMin !== undefined && Number.isFinite(xScaleMin)) xMin = xScaleMin;
    if (xScaleMax !== undefined && Number.isFinite(xScaleMax)) xMax = xScaleMax;
    if (xMin === xMax) xMax = xMin + 1;
    if (yMin === yMax) yMax = yMin + 1;

    const padL = 52;
    const padR = 20;
    const padT = 16;
    const padB = 34;
    const plotW = Math.max(10, width - padL - padR);
    const plotH = Math.max(10, height - padT - padB);

    const toPxX = (x) => padL + ((x - xMin) / (xMax - xMin)) * plotW;
    const toPxY = (y) => padT + (1 - (y - yMin) / (yMax - yMin)) * plotH;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, width, height);

    // Grid
    ctx.strokeStyle = '#e2e8f0';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const gy = padT + (i / 4) * plotH;
        ctx.beginPath();
        ctx.moveTo(padL, gy);
        ctx.lineTo(padL + plotW, gy);
        ctx.stroke();
    }

    // Axes
    ctx.strokeStyle = '#475569';
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(padL, padT);
    ctx.lineTo(padL, padT + plotH);
    ctx.lineTo(padL + plotW, padT + plotH);
    ctx.stroke();

    for (let tIndex = 0; tIndex < traces.length; tIndex++) {
        const t = traces[tIndex];
        const n = Math.min(t.x.length, t.y.length);
        ctx.strokeStyle = pickChartColor(tIndex);
        ctx.lineWidth = 2;
        ctx.beginPath();
        let started = false;
        for (let i = 0; i < n; i++) {
            const x = Number(t.x[i]);
            const y = Number(t.y[i]);
            if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
            const px = toPxX(x);
            const py = toPxY(y);
            if (!started) {
                ctx.moveTo(px, py);
                started = true;
            } else {
                ctx.lineTo(px, py);
            }
        }
        ctx.stroke();
    }

    // Axis labels
    ctx.fillStyle = '#334155';
    ctx.font = '12px sans-serif';
    ctx.fillText(waveform.x_label || 'time_s', padL + plotW - 70, padT + plotH + 24);
    ctx.fillText(`${yMin.toPrecision(4)} .. ${yMax.toPrecision(4)}`, 6, padT + 12);
}

function ensureWaveformDebugElement() {
    let debugEl = document.getElementById('waveformDebug');
    if (debugEl) return debugEl;

    const panel = document.querySelector('#tab-waveform .waveform-panel');
    if (!panel) return null;

    debugEl = document.createElement('div');
    debugEl.id = 'waveformDebug';
    debugEl.style.marginTop = '10px';
    debugEl.style.padding = '10px';
    debugEl.style.border = '1px dashed #94a3b8';
    debugEl.style.borderRadius = '8px';
    debugEl.style.background = '#f8fafc';
    debugEl.style.fontFamily = 'monospace';
    debugEl.style.fontSize = '12px';
    debugEl.style.whiteSpace = 'pre-wrap';
    debugEl.style.color = '#0f172a';
    panel.appendChild(debugEl);
    return debugEl;
}

function ensureWaveformNoticeElement() {
    let noticeEl = document.getElementById('waveformNotice');
    if (noticeEl) return noticeEl;
    const panel = document.querySelector('#tab-waveform .waveform-panel');
    if (!panel) return null;
    noticeEl = document.createElement('div');
    noticeEl.id = 'waveformNotice';
    noticeEl.style.marginTop = '8px';
    noticeEl.style.padding = '8px 10px';
    noticeEl.style.borderRadius = '8px';
    noticeEl.style.fontSize = '12px';
    noticeEl.style.display = 'none';
    panel.appendChild(noticeEl);
    return noticeEl;
}

function updateWaveformNotice(waveform) {
    const noticeEl = ensureWaveformNoticeElement();
    if (!noticeEl) return;

    const traces = Array.isArray(waveform?.traces) ? waveform.traces : [];
    const { inTrace, outTrace } = pickInputOutputTraces(traces);
    if (!inTrace || !outTrace) {
        noticeEl.style.display = 'none';
        return;
    }

    const n = Math.min(inTrace.y.length, outTrace.y.length);
    if (n < 8) {
        noticeEl.style.display = 'none';
        return;
    }

    let maxDiff = 0;
    for (let i = 0; i < n; i++) {
        const d = Math.abs(Number(inTrace.y[i]) - Number(outTrace.y[i]));
        if (Number.isFinite(d) && d > maxDiff) maxDiff = d;
    }

    if (maxDiff < 1e-9) {
        noticeEl.style.display = 'block';
        noticeEl.style.background = '#fff7ed';
        noticeEl.style.border = '1px solid #fdba74';
        noticeEl.style.color = '#9a3412';
        noticeEl.textContent = 'Vin và Vout đang trùng gần như hoàn toàn. Hãy kiểm tra nodes_to_monitor/probes hoặc net output của mạch.';
        return;
    }

    noticeEl.style.display = 'none';
}

function traceStats(trace) {
    const xs = Array.isArray(trace?.x) ? trace.x : [];
    const ys = Array.isArray(trace?.y) ? trace.y : [];
    const n = Math.min(xs.length, ys.length);
    if (n === 0) {
        return {
            points: 0,
            min: NaN,
            max: NaN,
            xMin: NaN,
            xMax: NaN,
        };
    }
    let ymin = Infinity;
    let ymax = -Infinity;
    for (let i = 0; i < n; i++) {
        const y = Number(ys[i]);
        if (!Number.isFinite(y)) continue;
        if (y < ymin) ymin = y;
        if (y > ymax) ymax = y;
    }
    const xMin = Number(xs[0]);
    const xMax = Number(xs[n - 1]);
    return {
        points: n,
        min: ymin,
        max: ymax,
        xMin: Number.isFinite(xMin) ? xMin : NaN,
        xMax: Number.isFinite(xMax) ? xMax : arrayMax(xs),
    };
}

function acRms(trace) {
    const y = Array.isArray(trace?.y) ? trace.y.map((v) => Number(v)).filter((v) => Number.isFinite(v)) : [];
    const n = y.length;
    if (!n) return NaN;
    let mean = 0;
    for (const v of y) mean += v;
    mean /= n;
    let acc = 0;
    for (const v of y) {
        const d = v - mean;
        acc += d * d;
    }
    return Math.sqrt(acc / n);
}

function signalMetrics(trace) {
    const x = Array.isArray(trace?.x) ? trace.x.map((v) => Number(v)).filter((v) => Number.isFinite(v)) : [];
    const y = Array.isArray(trace?.y) ? trace.y.map((v) => Number(v)).filter((v) => Number.isFinite(v)) : [];
    const n = Math.min(x.length, y.length);
    if (n === 0) {
        return {
            points: 0,
            mean: NaN,
            min: NaN,
            max: NaN,
            p2p: NaN,
            rms: NaN,
        };
    }

    let sum = 0;
    let sumSq = 0;
    let min = Infinity;
    let max = -Infinity;
    for (let i = 0; i < n; i++) {
        const v = y[i];
        sum += v;
        sumSq += v * v;
        if (v < min) min = v;
        if (v > max) max = v;
    }

    return {
        points: n,
        mean: sum / n,
        min,
        max,
        p2p: max - min,
        rms: Math.sqrt(sumSq / n),
    };
}

function pickInputOutputTraces(traces) {
    const byName = (re) => traces.find((t) => re.test(String(t?.name || '').toLowerCase()));
    const inTrace = byName(/\(.*in.*\)|\bin\b|vin|input/) || traces[0] || null;
    const outTrace = byName(/\(.*out.*\)|\bout\b|vout|output/) || (traces.length > 1 ? traces[1] : null);
    if (!inTrace || !outTrace || inTrace === outTrace) return { inTrace: null, outTrace: null };
    return { inTrace, outTrace };
}

function estimatePolarity(inTrace, outTrace) {
    const inY = Array.isArray(inTrace?.y) ? inTrace.y : [];
    const outY = Array.isArray(outTrace?.y) ? outTrace.y : [];
    const n = Math.min(inY.length, outY.length);
    if (n < 8) return 'unknown';

    let inMean = 0;
    let outMean = 0;
    for (let i = 0; i < n; i++) {
        const a = Number(inY[i]);
        const b = Number(outY[i]);
        if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
        inMean += a;
        outMean += b;
    }
    inMean /= n;
    outMean /= n;

    let cov = 0;
    for (let i = 0; i < n; i++) {
        const a = Number(inY[i]);
        const b = Number(outY[i]);
        if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
        cov += (a - inMean) * (b - outMean);
    }

    if (!Number.isFinite(cov) || Math.abs(cov) < 1e-18) return 'unknown';
    return cov < 0 ? 'inverted (~180deg)' : 'non-inverted (~0deg)';
}

function updateWaveformDebug(waveform, extra = {}) {
    const debugEl = ensureWaveformDebugElement();
    if (!debugEl) return;

    const canvas = document.getElementById('waveformCanvas');
    const rect = canvas ? canvas.getBoundingClientRect() : { width: 0, height: 0 };
    const traces = Array.isArray(waveform?.traces) ? waveform.traces : [];

    const lines = [];
    lines.push('[Waveform Debug]');
    lines.push(`frontend_build=${FRONTEND_BUILD}`);
    lines.push(`event=${extra.event || 'unknown'}`);
    if (Number.isFinite(Number(extra.points))) {
        lines.push(`payload.points=${Number(extra.points)}`);
    }
    if (Number.isFinite(Number(extra.execution_time_ms))) {
        lines.push(`execution_time_ms=${Number(extra.execution_time_ms).toFixed(2)}`);
    }
    lines.push(`trace_count=${traces.length}`);
    lines.push(`canvas_size=${Math.round(rect.width)}x${Math.round(rect.height)}`);
    lines.push(`chart_exists=${waveformChart ? 'yes' : 'no'}`);
    lines.push(`chartjs_loaded=${typeof Chart === 'undefined' ? 'no' : 'yes'}`);
    if (extra.chartBlocked) {
        lines.push('Chart.js blocked/unavailable -> using fallback canvas renderer');
    }

    const sp = extra.smoothPlan || lastWaveformSmoothPlan;
    if (sp) {
        lines.push('--- smoothness ---');
        if (sp.frequencyHz) lines.push(`frequency_hz=${sp.frequencyHz}`);
        if (sp.periodS) lines.push(`period_s=${sp.periodS}`);
        if (sp.cycles != null) lines.push(`cycles_in_window=${sp.cycles}`);
        if (sp.pointsPerCycle) lines.push(`points_per_cycle=${sp.pointsPerCycle}`);
        if (sp.totalPoints) lines.push(`display_points=${sp.totalPoints}`);
        if (sp.rawPointCount != null) lines.push(`raw_points_in_window=${sp.rawPointCount}`);
        lines.push(`resampled=${sp.applied ? 'yes' : 'no'}`);
    }

    for (let i = 0; i < traces.length; i++) {
        const t = traces[i];
        const s = traceStats(t);
        lines.push(
            `trace[${i}] ${t?.name || 'unnamed'}: points=${s.points}, x=[${s.xMin}, ${s.xMax}], y=[${s.min}, ${s.max}]`
        );
    }

    const gm = extra.gainMetrics
        || lastSimulationResult?.analysis?.gain_metrics
        || lastWaveformSimMeta?.analysis?.gain_metrics;
    if (gm && typeof gm === 'object') {
        lines.push('--- gain (backend, raw sim) ---');
        if (gm.input_probe) lines.push(`input_probe=${gm.input_probe}`);
        if (gm.output_probe) lines.push(`output_probe=${gm.output_probe}`);
        if (gm.measurement_samples != null) lines.push(`measurement_samples=${gm.measurement_samples}`);
        if (gm.vin_rms_ac != null) lines.push(`vin_rms_ac=${gm.vin_rms_ac}`);
        if (gm.vout_rms_ac != null) lines.push(`vout_rms_ac=${gm.vout_rms_ac}`);
        if (gm.gain_rms != null) lines.push(`gain_rms=${gm.gain_rms}`);
        if (gm.measured_av != null) lines.push(`measured_av=${gm.measured_av}`);
        if (gm.expected_av != null) lines.push(`expected_av=${gm.expected_av}`);
        if (gm.rel_error_pct != null) lines.push(`rel_error_pct=${gm.rel_error_pct}`);
        if (gm.equation_match != null) lines.push(`equation_match=${gm.equation_match}`);
    }

    const rawTraces = Array.isArray(lastWaveformPayload?.traces) ? lastWaveformPayload.traces : traces;
    const { inTrace, outTrace } = pickInputOutputTraces(rawTraces);
    if (inTrace && outTrace) {
        const inM = signalMetrics(inTrace);
        const outM = signalMetrics(outTrace);
        const inAcRms = acRms(inTrace);
        const outAcRms = acRms(outTrace);
        const gainP2p = (Number.isFinite(inM.p2p) && inM.p2p > 1e-12 && Number.isFinite(outM.p2p))
            ? (outM.p2p / inM.p2p)
            : NaN;
        const gainRms = (inAcRms > 1e-12 && Number.isFinite(outAcRms)) ? (outAcRms / inAcRms) : NaN;
        const polarity = estimatePolarity(inTrace, outTrace);

        lines.push('--- quick_validation (raw traces) ---');
        lines.push(`input_trace=${inTrace.name}, output_trace=${outTrace.name}`);
        lines.push(`vin_p2p=${inM.p2p}, vout_p2p=${outM.p2p}`);
        lines.push(`gain_estimate_p2p=${Number.isFinite(gainP2p) ? gainP2p : 'NaN'}`);
        lines.push(`gain_estimate_rms_ac=${Number.isFinite(gainRms) ? gainRms : 'NaN'}`);
        lines.push(`phase_relation=${polarity}`);
    }

    if (traces.length === 0) {
        lines.push('No traces in waveform payload');
    }

    debugEl.textContent = lines.join('\n');
}

function pickChartColor(index) {
    const palette = ['#2563eb', '#dc2626', '#0891b2', '#7c3aed', '#16a34a', '#ea580c'];
    return palette[index % palette.length];
}

// ── Suggestions ──
function showSuggestions(items) {
    if (!suggestions) return;
    suggestions.style.display = 'flex';
    suggestions.innerHTML = '';
    for (const item of items) {
        const btn = document.createElement('button');
        btn.className = 'suggestion-chip';
        btn.innerHTML = `<i class="fas fa-bolt"></i> ${item}`;
        btn.onclick = () => sendSuggestion(item);
        suggestions.appendChild(btn);
    }
}

// ── System Info Modal ──
async function showSystemInfo() {
    const modal = document.getElementById('infoModal');
    const body = document.getElementById('infoModalBody');

    modal.classList.add('active');
    body.innerHTML = '<p>Loading...</p>';

    try {
        const resp = await fetch(`${API_BASE}/api/chat/info`);
        const data = await resp.json();

        let html = '<div class="info-grid">';
        html += `<div class="info-item"><span class="info-label">System</span><span class="info-value">${data.name}</span></div>`;
        html += `<div class="info-item"><span class="info-label">Version</span><span class="info-value">${data.version}</span></div>`;
        html += `<div class="info-item"><span class="info-label">Templates</span><span class="info-value">${data.template_count}</span></div>`;
        html += `<div class="info-item"><span class="info-label">Gemini AI</span><span class="info-value">${data.gemini_enabled ? '✅ Enabled' : '❌ Disabled'}</span></div>`;

        html += '<div class="info-item"><span class="info-label">Families</span><div class="tag-list">';
        for (const f of data.supported_families) {
            html += `<span class="tag">${f}</span>`;
        }
        html += '</div></div>';

        html += '<div class="info-item"><span class="info-label">Features</span><div>';
        for (const f of data.features) {
            html += `<div style="font-size:12px;margin:2px 0">✓ ${f}</div>`;
        }
        html += '</div></div>';

        html += '</div>';
        body.innerHTML = html;
    } catch (e) {
        body.innerHTML = `<p>❌ Cannot load system info: ${e.message}</p>`;
    }
}

function closeModal() {
    document.getElementById('infoModal').classList.remove('active');
}

// Click outside modal to close
document.getElementById('infoModal').addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) closeModal();
});

// ── Helpers ──
function formatValue(value) {
    if (typeof value !== 'number') return { value: String(value), unit: '' };
    if (value >= 1e6) return { value: (value / 1e6).toFixed(1), unit: 'MΩ' };
    if (value >= 1e3) return { value: (value / 1e3).toFixed(1), unit: 'kΩ' };
    if (value >= 1) return { value: value.toFixed(1), unit: 'Ω' };
    if (value >= 1e-3) return { value: (value * 1e3).toFixed(1), unit: 'mΩ' };
    return { value: value.toExponential(2), unit: '' };
}

function autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
}
