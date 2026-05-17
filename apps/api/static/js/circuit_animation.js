/* ============================================================================
 * Elpis AI — GSAP-driven Animated Analog Circuit Background
 *
 * Renders procedurally generated SVG polylines that "draw themselves" in
 * (stroke-dashoffset → 0), hold for a beat, then fade out — all orchestrated
 * by GSAP timelines. The visual mood is intentionally calm: slow drawing
 * speed (1.8–3.2s) and ~0.2 base opacity so the title and CTA stay readable.
 *
 * Public API (exposed on window.ElpisCircuitAnimation):
 *   start(svgEl)      — kick off the spawn loop on the given <svg>
 *   stop()            — kill every active timeline + scheduled spawn,
 *                       remove every child node from the SVG
 *   setTheme(theme)   — swap palette ('dark' | 'light'); re-tints any
 *                       traces currently on screen so the swap is instant.
 *
 * Performance / cleanup notes:
 *   • Each trace is its own gsap.timeline() — kept in `traces[]` for stop().
 *   • Concurrency capped at MAX_TRACES so the SVG never accumulates nodes.
 *   • spawn loop uses setTimeout (NOT rAF) to keep CPU minimal between
 *     spawns; GSAP itself drives the per-frame work efficiently.
 *   • stop() kills every timeline, clears scheduled spawns, and empties
 *     the SVG — guaranteed zero residual work for KiCanvas in the layout
 *     behind the overlay.
 *
 * Graceful degradation:
 *   • If GSAP fails to load, start() is a no-op (callers see no error).
 * ========================================================================== */

(function () {
    'use strict';

    // ── Configuration ───────────────────────────────────────────────────────
    const GRID = 56;                 // pixels between grid lattice points
    const MAX_TRACES = 10;           // concurrent visible polylines
    const SPAWN_MIN_MS = 850;        // gap between spawns (random in [min,max])
    const SPAWN_MAX_MS = 1600;
    const MIN_SEGMENTS = 3;
    const MAX_SEGMENTS = 6;
    const STROKE_WIDTH = 1.4;
    const NODE_RADIUS = 2.4;

    const DRAW_DUR_MIN = 1.8;        // seconds to fully draw a polyline
    const DRAW_DUR_MAX = 3.2;
    const HOLD_DUR_MIN = 1.0;        // seconds at peak opacity
    const HOLD_DUR_MAX = 2.4;
    const FADE_DUR = 1.4;            // seconds to fade out

    // ── Theme palettes ──────────────────────────────────────────────────────
    // Base opacity sits at ~0.2 per UX requirement — strokes are still
    // distinct because of the drop-shadow glow.
    const THEMES = {
        dark: {
            strokes: ['#00f2fe', '#7cfc00', '#5b7cfb'],
            node:    '#00f2fe',
            opacity: 0.22,
            glowBlur: 6,
        },
        light: {
            strokes: ['#1d4ed8', '#6366f1', '#475569'],
            node:    '#1d4ed8',
            opacity: 0.20,
            glowBlur: 4,
        },
    };

    const SVG_NS = 'http://www.w3.org/2000/svg';

    // ── Internal state ──────────────────────────────────────────────────────
    let svg = null;
    let traces = [];        // gsap.Timeline[] currently active
    let spawnTimeoutId = null;
    let activeTheme = 'dark';
    let isRunning = false;

    // ── Helpers ─────────────────────────────────────────────────────────────
    function hasGsap() {
        return typeof window.gsap !== 'undefined';
    }

    function randInt(min, max) {
        return Math.floor(min + Math.random() * (max - min + 1));
    }

    function randFloat(min, max) {
        return min + Math.random() * (max - min);
    }

    function pickPalette() {
        return THEMES[activeTheme] || THEMES.dark;
    }

    function viewport() {
        if (!svg) return { w: 0, h: 0 };
        const r = svg.getBoundingClientRect();
        return { w: r.width, h: r.height };
    }

    // Manhattan-style polyline anchored to a virtual grid. Each step picks a
    // new direction (different from the previous) so the line keeps turning
    // and never collapses back on itself.
    function generatePolyline() {
        const { w, h } = viewport();
        if (w < 100 || h < 100) return null;

        const cols = Math.max(3, Math.floor(w / GRID));
        const rows = Math.max(3, Math.floor(h / GRID));

        let cx = randInt(0, cols - 1) * GRID + GRID / 2;
        let cy = randInt(0, rows - 1) * GRID + GRID / 2;
        const pts = [{ x: cx, y: cy }];
        const segs = randInt(MIN_SEGMENTS, MAX_SEGMENTS);
        let lastDir = null;

        for (let i = 0; i < segs; i++) {
            const choices = ['N', 'S', 'E', 'W'].filter((d) => d !== lastDir);
            const dir = choices[randInt(0, choices.length - 1)];
            const stride = randInt(1, 3);
            const dx = dir === 'E' ? stride : dir === 'W' ? -stride : 0;
            const dy = dir === 'S' ? stride : dir === 'N' ? -stride : 0;
            let nx = cx + dx * GRID;
            let ny = cy + dy * GRID;
            nx = Math.max(GRID / 2, Math.min(w - GRID / 2, nx));
            ny = Math.max(GRID / 2, Math.min(h - GRID / 2, ny));
            if (Math.abs(nx - cx) < 1 && Math.abs(ny - cy) < 1) continue;
            cx = nx; cy = ny;
            pts.push({ x: cx, y: cy });
            lastDir = dir;
        }
        return pts.length >= 2 ? pts : null;
    }

    function buildPathData(pts) {
        return 'M ' + pts.map((p) => `${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' L ');
    }

    function makeTraceGroup(pts) {
        const palette = pickPalette();
        const color = palette.strokes[randInt(0, palette.strokes.length - 1)];

        const group = document.createElementNS(SVG_NS, 'g');
        group.setAttribute('opacity', '0');

        const path = document.createElementNS(SVG_NS, 'path');
        path.setAttribute('d', buildPathData(pts));
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', color);
        path.setAttribute('stroke-width', String(STROKE_WIDTH));
        path.setAttribute('stroke-linecap', 'round');
        path.setAttribute('stroke-linejoin', 'round');
        path.style.filter = `drop-shadow(0 0 ${palette.glowBlur}px ${color})`;
        group.appendChild(path);

        const circles = [];
        for (const p of pts) {
            const c = document.createElementNS(SVG_NS, 'circle');
            c.setAttribute('cx', String(p.x));
            c.setAttribute('cy', String(p.y));
            c.setAttribute('r', String(NODE_RADIUS));
            c.setAttribute('fill', palette.node);
            c.style.filter = `drop-shadow(0 0 ${Math.max(2, palette.glowBlur - 2)}px ${palette.node})`;
            c.setAttribute('opacity', '0');
            group.appendChild(c);
            circles.push(c);
        }
        return { group, path, circles };
    }

    function spawnTrace() {
        if (!isRunning || !svg || !hasGsap()) return;
        if (traces.length >= MAX_TRACES) {
            scheduleNext();
            return;
        }

        const pts = generatePolyline();
        if (!pts) { scheduleNext(); return; }

        const { group, path, circles } = makeTraceGroup(pts);
        svg.appendChild(group);

        // Prepare the "draw-in" effect: dasharray = total length, offset =
        // total length → 0 over the draw duration.
        let totalLen = 0;
        try { totalLen = path.getTotalLength(); }
        catch (_) { totalLen = 0; }
        if (totalLen > 0) {
            path.style.strokeDasharray = String(totalLen);
            path.style.strokeDashoffset = String(totalLen);
        }

        const palette = pickPalette();
        const drawDur = randFloat(DRAW_DUR_MIN, DRAW_DUR_MAX);
        const holdDur = randFloat(HOLD_DUR_MIN, HOLD_DUR_MAX);

        const tl = window.gsap.timeline({
            onComplete: () => {
                if (group.parentNode) group.parentNode.removeChild(group);
                const idx = traces.indexOf(tl);
                if (idx >= 0) traces.splice(idx, 1);
            },
        });

        // Phase 1: fade the group up to palette opacity while the stroke draws.
        tl.to(group, { opacity: palette.opacity, duration: 0.55, ease: 'power1.out' }, 0);
        if (totalLen > 0) {
            tl.to(path, { strokeDashoffset: 0, duration: drawDur, ease: 'power2.inOut' }, 0);
        }
        // Nodes appear progressively along the trace length so the "soldering"
        // beats line up with each elbow being reached.
        if (circles.length > 0) {
            tl.to(circles, {
                opacity: palette.opacity,
                duration: 0.4,
                stagger: Math.max(0.05, drawDur / Math.max(1, circles.length)),
                ease: 'power1.out',
            }, 0);
        }
        // Phase 2: hold.
        tl.to({}, { duration: holdDur });
        // Phase 3: fade everything out.
        tl.to(group, { opacity: 0, duration: FADE_DUR, ease: 'power1.in' });

        traces.push(tl);
        scheduleNext();
    }

    function scheduleNext() {
        if (!isRunning) return;
        const delay = randFloat(SPAWN_MIN_MS, SPAWN_MAX_MS);
        spawnTimeoutId = setTimeout(spawnTrace, delay);
    }

    // ── Public API ──────────────────────────────────────────────────────────
    function start(targetSvg) {
        if (isRunning) stop();
        if (!targetSvg) return;
        if (!hasGsap()) {
            // GSAP not available — fail soft, do nothing.
            return;
        }
        svg = targetSvg;

        // Set a viewBox matching the current bounding box so SVG coordinates
        // line up 1:1 with our generator output (in CSS pixels).
        const r = svg.getBoundingClientRect();
        const w = Math.max(1, Math.floor(r.width));
        const h = Math.max(1, Math.floor(r.height));
        svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
        svg.setAttribute('preserveAspectRatio', 'none');

        // Keep the SVG sized via CSS (100%/100%); update viewBox on resize.
        if (typeof ResizeObserver !== 'undefined') {
            try {
                _resizeObserver = new ResizeObserver(() => {
                    if (!svg) return;
                    const rr = svg.getBoundingClientRect();
                    svg.setAttribute('viewBox', `0 0 ${Math.floor(rr.width)} ${Math.floor(rr.height)}`);
                });
                _resizeObserver.observe(svg);
            } catch (_) { /* noop */ }
        }

        isRunning = true;
        traces = [];

        // Seed a few traces immediately so the canvas isn't blank for the
        // first SPAWN_MIN_MS after load.
        for (let i = 0; i < 3; i++) {
            setTimeout(spawnTrace, i * 220);
        }
    }

    function stop() {
        isRunning = false;
        if (spawnTimeoutId != null) {
            clearTimeout(spawnTimeoutId);
            spawnTimeoutId = null;
        }
        if (hasGsap()) {
            for (const tl of traces) {
                try { tl.kill(); } catch (_) { /* noop */ }
            }
        }
        traces = [];
        if (_resizeObserver) {
            try { _resizeObserver.disconnect(); } catch (_) { /* noop */ }
            _resizeObserver = null;
        }
        if (svg) {
            while (svg.firstChild) svg.removeChild(svg.firstChild);
        }
        svg = null;
    }

    function setTheme(theme) {
        activeTheme = theme === 'light' ? 'light' : 'dark';
        if (!svg) return;
        const palette = pickPalette();
        // Re-tint any visible groups so the palette swap is immediate.
        const groups = svg.querySelectorAll('g');
        groups.forEach((g) => {
            const color = palette.strokes[Math.floor(Math.random() * palette.strokes.length)];
            const path = g.querySelector('path');
            if (path) {
                path.setAttribute('stroke', color);
                path.style.filter = `drop-shadow(0 0 ${palette.glowBlur}px ${color})`;
            }
            g.querySelectorAll('circle').forEach((c) => {
                c.setAttribute('fill', palette.node);
                c.style.filter = `drop-shadow(0 0 ${Math.max(2, palette.glowBlur - 2)}px ${palette.node})`;
            });
        });
    }

    // Track resize observer at module scope so stop() can disconnect it.
    let _resizeObserver = null;

    window.ElpisCircuitAnimation = { start, stop, setTheme };
})();
