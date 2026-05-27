"""Convert application-level LLM CircuitIR to domain IR for KiCad export."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Set

from app.application.ai.circuit_ir_schema import CircuitIR as AppCircuitIR

_DEFAULT_PINS: Dict[str, List[str]] = {
    "resistor": ["1", "2"],
    "capacitor": ["1", "2"],
    "inductor": ["1", "2"],
    "transformer": ["1", "2", "3", "4"],
    "bjt_npn": ["B", "C", "E"],
    "bjt_pnp": ["B", "C", "E"],
    "mosfet_n": ["G", "D", "S"],
    "mosfet_p": ["G", "D", "S"],
    "jfet_n": ["G", "D", "S"],
    "jfet_p": ["G", "D", "S"],
    "opamp_ic": ["+", "-", "OUT", "VS+", "VS-"],
    "power_supply": ["1"],
    "ground": ["1"],
    "connector": ["1"],
}

_SINGLE_PIN_TYPES = frozenset({"power_supply", "ground", "connector"})


def _parameters_for(comp_type: str, value: str, model: str) -> Dict[str, Dict[str, Any]]:
    raw_value = str(value or "").strip()
    raw_model = str(model or raw_value or "Generic").strip() or "Generic"
    params: Dict[str, Dict[str, Any]] = {}
    if comp_type == "resistor":
        params["resistance"] = {"value": raw_value, "unit": None}
    elif comp_type == "capacitor":
        params["capacitance"] = {"value": raw_value, "unit": None}
    elif comp_type == "inductor":
        params["inductance"] = {"value": raw_value, "unit": None}
    elif comp_type in {"bjt_npn", "bjt_pnp", "mosfet_n", "mosfet_p", "jfet_n", "jfet_p", "opamp_ic"}:
        params["model"] = {"value": raw_model, "unit": None}
    elif comp_type == "power_supply":
        params["voltage"] = {"value": raw_value, "unit": None}
    return params


def _infer_pins_from_nets(ir: AppCircuitIR) -> Dict[str, List[str]]:
    pins_by_ref: Dict[str, List[str]] = {}
    for comp in ir.components:
        ref = comp.ref.strip().upper()
        if ref:
            pins_by_ref[ref] = list(_DEFAULT_PINS.get(comp.type, ["1", "2"]))

    for net in ir.nets:
        for node in net.nodes:
            if ":" not in node:
                continue
            ref, pin = node.split(":", 1)
            ref_u = ref.strip().upper()
            pin_u = pin.strip().upper()
            if not ref_u or not pin_u:
                continue
            pins_by_ref.setdefault(ref_u, [])
            if pin_u not in pins_by_ref[ref_u]:
                pins_by_ref[ref_u].append(pin_u)

    for comp in ir.components:
        ref = comp.ref.strip().upper()
        ctype = comp.type
        pins = pins_by_ref.get(ref, list(_DEFAULT_PINS.get(ctype, ["1", "2"])))
        if not pins:
            pins = ["1"] if ctype in _SINGLE_PIN_TYPES else ["1", "2"]
        if ctype not in _SINGLE_PIN_TYPES and len(pins) < 2:
            if "2" not in pins:
                pins.append("2")
            elif "1" not in pins:
                pins.insert(0, "1")
        pins_by_ref[ref] = pins

    return pins_by_ref


def app_circuit_ir_to_domain_dict(
    ir: AppCircuitIR,
    *,
    circuit_id: str | None = None,
) -> Dict[str, Any]:
    """Build domain IR dict consumed by ``CircuitIRSerializer.to_circuit``."""
    cid = (circuit_id or "").strip() or str(uuid.uuid4())
    pins_by_ref = _infer_pins_from_nets(ir)

    ir_components: List[Dict[str, Any]] = []
    for comp in ir.components:
        ref = comp.ref.strip().upper()
        ctype = comp.type
        render_style: Dict[str, Any] = {
            "role": comp.role,
            "component_role": comp.role,
            "stage": comp.topology_stage,
            "component_stage": comp.topology_stage,
        }
        ir_components.append(
            {
                "id": ref,
                "type": ctype,
                "pins": pins_by_ref.get(ref, list(_DEFAULT_PINS.get(ctype, ["1", "2"]))),
                "parameters": _parameters_for(ctype, comp.value, comp.model),
                "value": comp.value,
                "standardized_value": comp.standardized_value or comp.value,
                "footprint": comp.footprint or None,
                "render_style": render_style,
            }
        )

    ir_nets: List[Dict[str, Any]] = []
    for net in ir.nets:
        connected: List[Dict[str, str]] = []
        seen: Set[str] = set()
        for node in net.nodes:
            if ":" not in node:
                continue
            ref, pin = node.split(":", 1)
            ref_u = ref.strip().upper()
            pin_u = pin.strip().upper()
            key = f"{ref_u}:{pin_u}"
            if key in seen:
                continue
            seen.add(key)
            connected.append({"component_id": ref_u, "pin_name": pin_u})
        if connected:
            ir_nets.append({"name": net.net_name, "connected_pins": connected})

    topology = ""
    if ir.analysis is not None:
        topology = str(ir.analysis.topology_classification or "").strip()
    if not topology and ir.architecture.stages:
        topology = str(ir.architecture.stages[0].topology or "").strip()

    circuit_name = "circuit"
    if ir.analysis is not None and str(ir.analysis.circuit_name or "").strip():
        circuit_name = str(ir.analysis.circuit_name).strip()

    topology_type = topology
    if ir.architecture.stages:
        topology_type = str(ir.architecture.stages[0].topology or topology_type)

    return {
        "meta": {
            "version": "1.0",
            "schema_version": "1.0",
            "circuit_id": cid,
            "circuit_name": circuit_name,
        },
        "components": ir_components,
        "nets": ir_nets,
        "ports": [],
        "constraints": [],
        "topology_type": topology_type,
        "signal_flow": {
            "input_node": ir.signal_flow.input_node,
            "output_node": ir.signal_flow.output_node,
            "main_chain": list(ir.signal_flow.main_chain),
            "stage_links": [list(pair) for pair in ir.signal_flow.stage_links],
        },
    }


def llm_ir_to_validator_circuit_data(llm_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize LLM CircuitIR JSON for ConstraintValidator (template-style nets/components)."""
    components_out: List[Dict[str, Any]] = []
    for comp in llm_payload.get("components", []) or []:
        if not isinstance(comp, dict):
            continue
        ref = str(comp.get("ref") or comp.get("ref_id") or comp.get("id") or "").strip().upper()
        if not ref:
            continue
        ctype = str(comp.get("type") or "resistor").strip().lower()
        params: Dict[str, Any] = {}
        value = str(comp.get("value") or comp.get("standardized_value") or "").strip()
        if ctype == "resistor" and value:
            params["resistance"] = value
        elif ctype == "capacitor" and value:
            params["capacitance"] = value
        elif ctype == "inductor" and value:
            params["inductance"] = value
        elif ctype in {"bjt_npn", "bjt_pnp", "mosfet_n", "mosfet_p", "opamp_ic"}:
            params["model"] = str(comp.get("model") or value)
        components_out.append({"id": ref, "type": ctype.upper(), "parameters": params})

    nets_out: List[Dict[str, Any]] = []
    for net in llm_payload.get("nets", []) or []:
        if not isinstance(net, dict):
            continue
        name = str(net.get("net_name") or net.get("name") or "").strip()
        connections: List[List[str]] = []
        for node in net.get("nodes", []) or []:
            if isinstance(node, str) and ":" in node:
                ref, pin = node.split(":", 1)
                connections.append([ref.strip().upper(), pin.strip().upper()])
        if connections:
            nets_out.append({"name": name or connections[0][0], "connections": connections})

    topology = str(llm_payload.get("topology_type") or "").strip()
    analysis = llm_payload.get("analysis") if isinstance(llm_payload.get("analysis"), dict) else {}
    if not topology and analysis:
        topology = str(analysis.get("topology_classification") or "")

    return {
        "components": components_out,
        "nets": nets_out,
        "topology_type": topology,
    }
