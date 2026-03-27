/* ============================================
   Electronic Circuit Chatbot - Main JavaScript
   ============================================ */

const API_BASE = '';  // Same origin

// ── State ──
let isProcessing = false;
let lastCircuitData = null;
let currentTab = 'schematic';
let waveformChart = null;
let lastWaveformPayload = null;
const FRONTEND_BUILD = '20260320a';

function clearCircuitArtifacts() {
    lastCircuitData = null;
    window._lastCircuitData = null;
    window._lastKicadSch = null;
    window._lastPcbContent = null;
    window._pcbReady = false;
    window._pcbRendered = false;

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
});

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
        btnDownload.addEventListener('click', () => {
            if (window._lastKicadSch) {
                const blob = new Blob([window._lastKicadSch], { type: 'text/plain' });
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = (window._lastTemplateId || 'circuit') + '.kicad_sch';
                a.click();
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
async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text || isProcessing) return;

    // Add user message
    addMessage(text, 'user');
    chatInput.value = '';
    autoResize(chatInput);

    // Show typing indicator
    const typingId = showTyping();

    isProcessing = true;
    btnSend.disabled = true;

    try {
        const resp = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                mode: selectedModelTier,
            }),
        });

        const data = await resp.json();

        // Remove typing indicator
        removeTyping(typingId);

        if (resp.ok) {
            handleBotResponse(data);
        } else {
            const errMsg = data.detail?.message || data.detail || 'Lỗi server';
            addMessage(`❌ Lỗi: ${errMsg}`, 'bot');
        }
    } catch (e) {
        removeTyping(typingId);
        addMessage(`❌ Không thể kết nối đến server: ${e.message}`, 'bot');
    }

    isProcessing = false;
    btnSend.disabled = false;
    chatInput.focus();
}

async function sendSimulation(rawText) {
    const payload = buildSimulationPayload(rawText);
    if (!payload.netlist) {
        addMessage('❌ Không tạo được netlist mô phỏng.', 'bot');
        return;
    }

    await sendSimulationPayload(payload, rawText);
}

async function sendSimulationPayload(payload, userLabel = 'Run Simulation') {
    if (!payload || !payload.netlist) {
        addMessage('❌ Không có dữ liệu netlist để mô phỏng.', 'bot');
        return;
    }

    addMessage(userLabel, 'user');
    chatInput.value = '';
    autoResize(chatInput);

    const typingId = showTyping();
    isProcessing = true;
    btnSend.disabled = true;

    try {
        const resp = await fetch(`${API_BASE}/api/chat/simulate/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        removeTyping(typingId);
        if (!resp.ok || !resp.body) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail?.message || `HTTP ${resp.status}`);
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
        addMessage(`❌ Mô phỏng thất bại: ${e.message}`, 'bot');
    }

    isProcessing = false;
    btnSend.disabled = false;
    chatInput.focus();
}

async function runSimulationFromCurrentCircuit() {
    if (isProcessing) return;

    const base = lastCircuitData?.circuit_data || lastCircuitData;
    if (!base) {
        addMessage('❌ Chưa có mạch để mô phỏng. Hãy generate mạch trước.', 'bot');
        return;
    }

    const payload = buildSimulationPayloadFromCircuit(base);
    if (!payload.netlist) {
        addMessage('❌ Không thể dựng netlist từ mạch hiện tại.', 'bot');
        return;
    }

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
        addMessage(`❌ Mô phỏng thất bại: ${payload.message || 'unknown error'}`, 'bot');
        return;
    }
    if (eventName === 'result') {
        addMessage(`✅ Mô phỏng hoàn tất: ${payload.points || 0} samples`, 'bot');
        processingTime.textContent = `⏱ ${Number(payload.execution_time_ms || 0).toFixed(0)}ms`;
        lastWaveformPayload = payload.waveform || null;
        updateWaveformDebug(payload.waveform, {
            points: payload.points,
            execution_time_ms: payload.execution_time_ms,
            event: 'result',
        });
        switchTab('waveform');
        // Render after tab is visible so Chart.js gets non-zero canvas size.
        requestAnimationFrame(() => renderWaveform(payload.waveform));
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

    return {
        netlist,
        probes: ['v(out)', 'v(in)'],
        analysis: {
            type: 'transient',
            step: '20us',
            stop: '2ms',
            start: '0',
        },
    };
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
        return {
            circuit_data: core,
            netlist: providedNetlist,
            nodes_to_monitor: normalizedProbes,
            analysis_type: String(core.analysis_type || 'transient'),
            tran_step: core.tran_step || '100us',
            tran_stop: core.tran_stop || '100ms',
            tran_start: core.tran_start || '50ms',
            source_params: core.source_params || undefined,
            // Keep legacy fields for compatibility with non-circuit_data path.
            probes: normalizedProbes,
            analysis: {
                type: 'transient',
                step: core.tran_step || '100us',
                stop: core.tran_stop || '100ms',
                start: core.tran_start || '50ms',
            },
        };
    }

    const components = Array.isArray(core?.components) ? core.components : [];
    const nets = Array.isArray(core?.nets) ? core.nets : [];
    const ports = Array.isArray(core?.ports) ? core.ports : [];

    if (!components.length || !nets.length) {
        return { netlist: '', probes: ['v(out)', 'v(in)'], analysis: { type: 'transient', step: '10us', stop: '10ms', start: '0' } };
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

    return {
        netlist,
        probes,
        analysis,
    };
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
    // Add bot message (markdown rendered) + mode badge for easier tracking
    addMessage(data.message, 'bot', { mode: data.mode });

    // Update processing time
    if (data.processing_time_ms) {
        processingTime.textContent = `⏱ ${data.processing_time_ms.toFixed(0)}ms`;
    }

    // Update right panel if we have data
    if (data.params) {
        updateParamsPanel(data.params, data.pipeline);
    }

    if (data.intent || data.analysis || data.pipeline) {
        updateAnalysisPanel(data.intent || {}, data.pipeline, data.analysis || null);
    }

    if (data.circuit_data) {
        lastCircuitData = data.circuit_data;
        updateSchematicPanel(data.circuit_data);
    } else if (data.success === false || data.intent?.intent_type === 'create' || data.intent?.intent_type === 'modify') {
        // Avoid exporting/simulating stale artifacts from a previous successful circuit.
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

    if (type === 'bot') {
        msgText.innerHTML = renderMarkdown(text);
        if (typeof renderLatexInElement === 'function') {
            renderLatexInElement(msgText);
        }

        const modeMeta = document.createElement('div');
        modeMeta.className = 'message-meta';
        modeMeta.textContent = `Mode: ${toModeLabel(options.mode)}`;
        content.appendChild(modeMeta);
    } else {
        msgText.textContent = text;
    }

    content.appendChild(msgText);
    div.appendChild(avatar);
    div.appendChild(content);

    chatMessages.appendChild(div);
    scrollToBottom();
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

function updateParamsPanel(params, pipeline) {
    const el = document.getElementById('paramsContent');
    if (!params || Object.keys(params).length === 0) {
        el.innerHTML = '<div class="placeholder-content"><i class="fas fa-table fa-3x"></i><p>Không có thông số</p></div>';
        return;
    }

    let html = '<table class="params-table">';
    html += '<tr><th>Linh kiện</th><th>Giá trị</th><th>Đơn vị</th></tr>';

    for (const [name, value] of Object.entries(params)) {
        const formatted = formatValue(value);
        html += `<tr>
            <td><strong>${name}</strong></td>
            <td class="param-value">${formatted.value}</td>
            <td>${formatted.unit}</td>
        </tr>`;
    }

    html += '</table>';

    // Add gain info if available
    if (pipeline && pipeline.solved) {
        const solved = pipeline.solved;
        html += '<div class="analysis-section" style="margin-top:12px">';
        html += '<h3><i class="fas fa-calculator"></i> Kết quả tính toán</h3>';
        if (solved.gain_formula) {
            html += `<div class="analysis-item"><span class="label">Công thức:</span><span class="value">${solved.gain_formula}</span></div>`;
        }
        if (solved.actual_gain !== null && solved.actual_gain !== undefined) {
            html += `<div class="analysis-item"><span class="label">Gain thực tế:</span><span class="value">${solved.actual_gain.toFixed(2)}</span></div>`;
        }
        if (solved.notes && solved.notes.length > 0) {
            html += '<div style="margin-top:8px;font-size:12px;color:#64748b">';
            for (const note of solved.notes) {
                html += `<div>📝 ${note}</div>`;
            }
            html += '</div>';
        }
        html += '</div>';
    }

    el.innerHTML = html;
}

function updateAnalysisPanel(intent, pipeline, analysis) {
    const el = document.getElementById('analysisContent');

    let html = '';

    const formatOhm = (value) => {
        if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
        const n = Number(value);
        if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)} MOhm`;
        if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(2)} kOhm`;
        return `${n.toFixed(2)} Ohm`;
    };

    const formatHz = (value) => {
        if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
        const n = Number(value);
        if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)} MHz`;
        if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(2)} kHz`;
        return `${n.toFixed(2)} Hz`;
    };

    // Intent section
    html += '<div class="analysis-section">';
    html += '<h3><i class="fas fa-brain"></i> NLU Analysis</h3>';

    const intentFields = [
        { label: 'Circuit Type', value: intent.circuit_type || 'N/A' },
        { label: 'Gain Target', value: intent.gain_target !== null ? intent.gain_target : 'N/A' },
        { label: 'VCC', value: intent.vcc !== null ? `${intent.vcc}V` : 'N/A' },
        { label: 'Source', value: intent.source || 'rule_based' },
    ];

    for (const f of intentFields) {
        html += `<div class="analysis-item"><span class="label">${f.label}:</span><span class="value">${f.value}</span></div>`;
    }

    // Confidence bar
    const conf = (intent.confidence || 0) * 100;
    const confClass = conf >= 70 ? 'high' : conf >= 40 ? 'medium' : 'low';
    html += `<div style="margin-top:8px;font-size:12px;color:#64748b">Confidence: ${conf.toFixed(0)}%</div>`;
    html += `<div class="confidence-bar"><div class="confidence-fill ${confClass}" style="width:${conf}%"></div></div>`;
    html += '</div>';

    // Pipeline section
    if (pipeline) {
        html += '<div class="analysis-section">';
        html += '<h3><i class="fas fa-cogs"></i> Pipeline Result</h3>';

        html += `<div class="analysis-item"><span class="label">Stage:</span><span class="value">${pipeline.stage_reached || 'N/A'}</span></div>`;
        html += `<div class="analysis-item"><span class="label">Thành công:</span><span class="value">${pipeline.success ? '✅ Yes' : '❌ No'}</span></div>`;

        if (pipeline.plan) {
            html += `<div class="analysis-item"><span class="label">Template:</span><span class="value">${pipeline.plan.matched_template_id || 'N/A'}</span></div>`;
            html += `<div class="analysis-item"><span class="label">Mode:</span><span class="value">${pipeline.plan.mode || 'N/A'}</span></div>`;
            html += `<div class="analysis-item"><span class="label">Confidence:</span><span class="value">${(pipeline.plan.confidence * 100).toFixed(0)}%</span></div>`;

            if (pipeline.plan.blocks && pipeline.plan.blocks.length > 0) {
                html += '<div style="margin-top:8px"><span class="label">Blocks:</span>';
                html += '<div class="tag-list" style="margin-top:4px">';
                for (const b of pipeline.plan.blocks) {
                    const btype = typeof b === 'string' ? b : b.block_type;
                    html += `<span class="tag">${btype}</span>`;
                }
                html += '</div></div>';
            }
        }

        if (pipeline.error) {
            html += `<div style="margin-top:8px;padding:8px;background:#fef2f2;border-radius:6px;font-size:12px;color:#dc2626">⚠️ ${pipeline.error}</div>`;
        }

        html += '</div>';
    }

    if (analysis) {
        const cascade = analysis.cascading || {};
        const stageTable = Array.isArray(cascade.stage_table) ? cascade.stage_table : [];

        html += '<div class="analysis-section">';
        html += '<h3><i class="fas fa-project-diagram"></i> Topology Analysis</h3>';

        html += `<div class="analysis-item"><span class="label">Stages:</span><span class="value">${cascade.stage_count ?? 'N/A'}</span></div>`;

        if (stageTable.length > 0) {
            html += '<div style="margin-top:8px;font-size:12px;color:#334155">Cascading Stage Table</div>';
            html += '<div style="margin-top:6px;overflow:auto">';
            html += '<table style="width:100%;border-collapse:collapse;font-size:12px">';
            html += '<thead><tr style="background:#f8fafc">';
            html += '<th style="text-align:left;padding:6px;border-bottom:1px solid #e2e8f0">Stage</th>';
            html += '<th style="text-align:left;padding:6px;border-bottom:1px solid #e2e8f0">Type</th>';
            html += '<th style="text-align:left;padding:6px;border-bottom:1px solid #e2e8f0">Gain</th>';
            html += '<th style="text-align:left;padding:6px;border-bottom:1px solid #e2e8f0">Equation</th>';
            html += '<th style="text-align:left;padding:6px;border-bottom:1px solid #e2e8f0">Zin</th>';
            html += '<th style="text-align:left;padding:6px;border-bottom:1px solid #e2e8f0">Zout</th>';
            html += '<th style="text-align:left;padding:6px;border-bottom:1px solid #e2e8f0">BW</th>';
            html += '</tr></thead><tbody>';

            for (const row of stageTable) {
                html += '<tr>';
                html += `<td style="padding:6px;border-bottom:1px solid #f1f5f9">${row.stage ?? 'N/A'}</td>`;
                html += `<td style="padding:6px;border-bottom:1px solid #f1f5f9">${row.type || 'N/A'}</td>`;
                html += `<td style="padding:6px;border-bottom:1px solid #f1f5f9">${row.gain !== undefined ? Number(row.gain).toFixed(4) : 'N/A'}</td>`;
                html += `<td style="padding:6px;border-bottom:1px solid #f1f5f9">${row.equation || 'N/A'}</td>`;
                html += `<td style="padding:6px;border-bottom:1px solid #f1f5f9">${formatOhm(row.zin_ohm)}</td>`;
                html += `<td style="padding:6px;border-bottom:1px solid #f1f5f9">${formatOhm(row.zout_ohm)}</td>`;
                html += `<td style="padding:6px;border-bottom:1px solid #f1f5f9">${formatHz(row.bandwidth_hz)}</td>`;
                html += '</tr>';
            }

            html += '</tbody></table></div>';
        }

        html += '</div>';
    }

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
    try {
        const resp = await fetch('/api/chat/export-kicad', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ circuit_data: templateData }),
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

        // Create KiCanvas embed with INLINE source
        const kicanvas = document.createElement('kicanvas-embed');
        kicanvas.setAttribute('controls', 'full');
        kicanvas.style.width = '100%';
        kicanvas.style.height = '100%';
        kicanvas.style.minHeight = '450px';
        kicanvas.style.display = 'block';
        kicanvas.style.border = 'none';
        kicanvas.style.borderRadius = '8px';
        kicanvas.style.backgroundColor = '#ffffff';

        // Use inline <kicanvas-source> with content directly embedded
        const source = document.createElement('kicanvas-source');
        source.textContent = kicadContent;
        kicanvas.appendChild(source);

        container.appendChild(kicanvas);

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

/**
 * Export circuit to PCB and render inline with KiCanvas
 */
async function exportAndRenderPCB(templateData, circuitData) {
    const container = document.getElementById('pcbArea');
    const toolbar = document.getElementById('pcbToolbar');
    const placeholder = document.getElementById('pcbPlaceholder');

    if (!container) return;

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

    try {
        const resp = await fetch('/api/chat/export-pcb', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ circuit_data: templateData }),
        });

        if (!resp.ok) {
            const errData = await resp.json().catch(() => ({}));
            throw new Error(errData.detail?.message || `HTTP ${resp.status}`);
        }

        const result = await resp.json();
        const fileUrl = result.url;

        // Fetch .kicad_pcb content for download
        const contentResp = await fetch(fileUrl);
        const pcbContent = await contentResp.text();

        // Store for download and deferred render
        window._lastPcbContent = pcbContent;
        window._pcbReady = true;
        window._pcbRendered = false;

        // Update placeholder to indicate ready state
        if (placeholder) {
            placeholder.innerHTML = '<i class="fas fa-check-circle fa-3x" style="color:#10b981"></i><p>PCB sẵn sàng — chuyển sang tab PCB để xem</p>';
        }

        // If PCB tab is currently active, render immediately
        if (currentTab === 'pcb') {
            renderPCBKiCanvas();
        }

        console.log('PCB export ready, size:', pcbContent.length);

    } catch (err) {
        console.error('PCB render error:', err);
        window._pcbReady = false;
        if (placeholder) {
            placeholder.style.display = 'block';
            placeholder.innerHTML = `
                <i class="fas fa-exclamation-triangle fa-2x" style="color:#d97706"></i>
                <p>Không thể tạo PCB</p>
                <p class="sub-text" style="font-size:11px">${err.message}</p>
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

    // Create KiCanvas embed for PCB
    const kicanvas = document.createElement('kicanvas-embed');
    kicanvas.setAttribute('controls', 'full');
    kicanvas.style.width = '100%';
    kicanvas.style.height = '100%';
    kicanvas.style.minHeight = '450px';
    kicanvas.style.display = 'block';
    kicanvas.style.border = 'none';
    kicanvas.style.borderRadius = '8px';
    kicanvas.style.backgroundColor = '#ffffff';

    // Use inline <kicanvas-source> with PCB content
    const source = document.createElement('kicanvas-source');
    source.setAttribute('filename', 'circuit.kicad_pcb');
    source.textContent = window._lastPcbContent;
    kicanvas.appendChild(source);

    container.appendChild(kicanvas);
    window._pcbRendered = true;

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

function renderWaveform(waveform) {
    const canvas = document.getElementById('waveformCanvas');
    const empty = document.getElementById('waveformEmpty');
    if (!canvas || !waveform || !Array.isArray(waveform.traces)) return;

    // If CDN Chart.js is blocked (tracking prevention / offline), draw directly on canvas.
    if (typeof Chart === 'undefined') {
        renderWaveformFallbackCanvas(canvas, waveform);
        if (empty) empty.style.display = 'none';
        updateWaveformNotice(waveform);
        updateWaveformDebug(waveform, { event: 'render-fallback', chartBlocked: true });
        return;
    }

    const datasets = waveform.traces.map((trace, idx) => ({
        label: trace.unit ? `${trace.name} (${trace.unit})` : trace.name,
        data: (trace.x || []).map((x, i) => ({ x, y: (trace.y || [])[i] })),
        borderColor: pickChartColor(idx),
        backgroundColor: 'transparent',
        borderWidth: 2,
        pointRadius: 0,
        tension: 0,
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
                    title: { display: true, text: waveform.x_label || 'time_s' },
                },
                y: {
                    title: { display: true, text: 'Amplitude' },
                },
            },
            plugins: {
                legend: { display: true, position: 'top' },
            },
        },
    });

    if (empty) empty.style.display = 'none';
    updateWaveformNotice(waveform);
    updateWaveformDebug(waveform, { event: 'render' });
}

function renderWaveformFallbackCanvas(canvas, waveform) {
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
    const y = Array.isArray(trace?.y) ? trace.y.filter((v) => Number.isFinite(v)) : [];
    const x = Array.isArray(trace?.x) ? trace.x.filter((v) => Number.isFinite(v)) : [];
    if (y.length === 0 || x.length === 0) {
        return {
            points: 0,
            min: NaN,
            max: NaN,
            xMin: NaN,
            xMax: NaN,
        };
    }
    return {
        points: Math.min(x.length, y.length),
        min: Math.min(...y),
        max: Math.max(...y),
        xMin: Math.min(...x),
        xMax: Math.max(...x),
    };
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

    for (let i = 0; i < traces.length; i++) {
        const t = traces[i];
        const s = traceStats(t);
        lines.push(
            `trace[${i}] ${t?.name || 'unnamed'}: points=${s.points}, x=[${s.xMin}, ${s.xMax}], y=[${s.min}, ${s.max}]`
        );
    }

    const { inTrace, outTrace } = pickInputOutputTraces(traces);
    if (inTrace && outTrace) {
        const inM = signalMetrics(inTrace);
        const outM = signalMetrics(outTrace);
        const gain = (Number.isFinite(inM.p2p) && inM.p2p > 1e-12 && Number.isFinite(outM.p2p))
            ? (outM.p2p / inM.p2p)
            : NaN;
        const polarity = estimatePolarity(inTrace, outTrace);

        lines.push('--- quick_validation ---');
        lines.push(`input_trace=${inTrace.name}, output_trace=${outTrace.name}`);
        lines.push(`vin_p2p=${inM.p2p}, vout_p2p=${outM.p2p}`);
        lines.push(`gain_estimate_abs=${Number.isFinite(gain) ? gain : 'NaN'}`);
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
