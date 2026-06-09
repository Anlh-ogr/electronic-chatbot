"""Deterministic BJT topology wiring repair for LLM-generated CircuitIR payloads.

All three BJT NPN configurations are covered:
  common_emitter   — input at Base, output at Collector, CE bypass on RE
  common_base      — input at Emitter, output at Collector, CB bypass on Base
  common_collector — input at Base, output at Emitter, Collector tied to VCC

The repair logic references topology_wiring_spec as the single source of truth
for what the hallmark wiring must look like.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.application.ai.topology_wiring_spec import get_spec

logger = logging.getLogger(__name__)

_BJT_FAMILIES = {"common_emitter", "common_base", "common_collector"}

_CB_HINTS = (
    r"\bcb\b",
    r"common[\s_-]*base",
    r"base\s*chung",
    r"b\s*chung",
    r"mắc\s*b\s*chung",
    r"mắc\s*base\s*chung",
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _pin_map(nets: List[Dict[str, Any]]) -> Dict[str, str]:
    """Return {REF:PIN → net_name} for every node in the nets list."""
    out: Dict[str, str] = {}
    for net in nets or []:
        if not isinstance(net, dict):
            continue
        name = str(net.get("net_name") or "").strip()
        if not name:
            continue
        for node in net.get("nodes") or []:
            key = str(node).strip().upper()
            if key and ":" in key:
                out[key] = name
    return out


def _component_refs(components: List[Dict[str, Any]]) -> Set[str]:
    refs: Set[str] = set()
    for comp in components or []:
        if isinstance(comp, dict):
            ref = str(comp.get("ref") or "").strip().upper()
            if ref:
                refs.add(ref)
    return refs


def _pick_ref(refs: Set[str], candidates: Tuple[str, ...], *, prefix: str = "") -> Optional[str]:
    for cand in candidates:
        if cand.upper() in refs:
            return cand.upper()
    if prefix:
        for ref in sorted(refs):
            if ref.startswith(prefix.upper()):
                return ref
    return None


def _dedupe_net_nodes(nets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for net in nets:
        if not isinstance(net, dict):
            continue
        seen: List[str] = []
        for node in net.get("nodes") or []:
            key = str(node).strip().upper()
            if key and key not in seen:
                seen.append(key)
        cleaned.append({"net_name": net.get("net_name"), "nodes": seen})
    return cleaned


def _is_supply_net(name: str) -> bool:
    t = (name or "").strip().upper()
    return t in {"VCC", "VDD", "V+", "VPLUS", "VS+", "VS_PLUS"} or t.startswith("VCC") or t.startswith("VDD")


def _ensure_cap(components: List[Dict[str, Any]], refs: Set[str],
                preferred: Tuple[str, ...], fallback_prefix: str,
                value: str, role: str) -> str:
    existing = _pick_ref(refs, preferred, prefix=fallback_prefix)
    if existing:
        return existing
    new_ref = fallback_prefix
    idx = 1
    while new_ref in refs:
        idx += 1
        new_ref = f"{fallback_prefix}{idx}"
    components.append({
        "ref": new_ref,
        "type": "capacitor",
        "value": value,
        "model": "Generic",
        "role": role,
        "topology_stage": 0,
    })
    refs.add(new_ref)
    return new_ref


def _in_out_signal_nodes(refs: Set[str], cin_ref: str, cout_ref: str) -> Tuple[List[str], List[str]]:
    """Return (in_nodes, out_nodes) including any external connector refs."""
    in_nodes = [f"{cin_ref}:1"]
    out_nodes = [f"{cout_ref}:2"]
    for ref in ("VIN", "VTB", "VSIG", "IN"):
        if ref in refs:
            in_nodes.insert(0, f"{ref}:1")
            break
    for ref in ("VOUT", "OUT"):
        if ref in refs:
            out_nodes.append(f"{ref}:1")
            break
    return in_nodes, out_nodes


def _patch_topology_metadata(repaired: Dict[str, Any], family: str) -> None:
    signal_flow = repaired.get("signal_flow")
    if isinstance(signal_flow, dict):
        sf = dict(signal_flow)
        sf["input_node"] = "IN_SIG"
        sf["output_node"] = "OUT_SIG"
        repaired["signal_flow"] = sf

    architecture = repaired.get("architecture")
    if isinstance(architecture, dict):
        arch = dict(architecture)
        stages = arch.get("stages")
        if isinstance(stages, list) and stages:
            s0 = dict(stages[0]) if isinstance(stages[0], dict) else {}
            s0["topology"] = family
            arch["stages"] = [s0] + list(stages[1:])
        repaired["architecture"] = arch

    analysis = repaired.get("analysis")
    if isinstance(analysis, dict):
        a = dict(analysis)
        a["topology_classification"] = family
        repaired["analysis"] = a


# ---------------------------------------------------------------------------
# BJT family inference
# ---------------------------------------------------------------------------


def infer_bjt_family(payload: Dict[str, Any], requirements: str = "") -> Optional[str]:
    """Resolve BJT family from IR fields or explicit user requirements text."""
    candidates: List[str] = []
    architecture = payload.get("architecture") if isinstance(payload.get("architecture"), dict) else {}
    for stage in architecture.get("stages") or []:
        if isinstance(stage, dict) and stage.get("topology"):
            candidates.append(str(stage["topology"]))
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
    for key in ("topology_classification", "circuit_name"):
        val = analysis.get(key)
        if val:
            candidates.append(str(val))
    if architecture.get("topology_type"):
        candidates.append(str(architecture["topology_type"]))

    blob = re.sub(r"[^a-z0-9]+", "_", " ".join(candidates).lower())
    if "common_base" in blob or blob.endswith("_cb") or "_cb_" in blob:
        return "common_base"
    if "common_collector" in blob or blob.endswith("_cc") or "_cc_" in blob:
        return "common_collector"
    if "common_emitter" in blob or blob.endswith("_ce") or "_ce_" in blob:
        return "common_emitter"

    req = (requirements or "").lower()
    if any(re.search(pat, req, re.IGNORECASE) for pat in _CB_HINTS):
        return "common_base"
    if re.search(r"\bcc\b|common[\s_-]*collector|collector\s*chung|c\s*chung|emitter\s*follower", req, re.I):
        return "common_collector"
    if re.search(r"\bce\b|common[\s_-]*emitter|emitter\s*chung|(?<![a-z])e\s*chung\b", req, re.I):
        return "common_emitter"
    return None


# ---------------------------------------------------------------------------
# Wiring validation helpers (quick-check before deciding to repair)
# ---------------------------------------------------------------------------


def _find_base_bypass_ref(pin_map: Dict[str, str], q1_b_net: str) -> Optional[str]:
    """Return the ref of the cap bridging Q1:B → GND, or None."""
    if not q1_b_net:
        return None
    gnd_names = {"0", "GND", "GROUND"}
    for pin, net in pin_map.items():
        if not pin.startswith("C") or pin.count(":") != 1:
            continue
        ref, pin_no = pin.split(":", 1)
        if ref in {"CIN", "COUT"}:
            continue
        other = f"{ref}:{'2' if pin_no == '1' else '1'}"
        if pin_map.get(other, "") in gnd_names and net == q1_b_net:
            return ref
    return None


def common_base_wiring_ok(payload: Dict[str, Any]) -> bool:
    """True if payload already has correct CB hallmark wiring."""
    pm = _pin_map(payload.get("nets") or [])
    q1_e = pm.get("Q1:E", "")
    q1_b = pm.get("Q1:B", "")
    cin2 = pm.get("CIN:2", "")
    cout1 = pm.get("COUT:1", "")
    if not q1_e or cin2 != q1_e:
        return False
    if cout1 and cout1 != pm.get("Q1:C", ""):
        return False
    if q1_b and not _find_base_bypass_ref(pm, q1_b):
        return False
    return True


def common_collector_wiring_ok(payload: Dict[str, Any]) -> bool:
    """True if payload already has correct CC hallmark wiring."""
    pm = _pin_map(payload.get("nets") or [])
    q1_c_net = pm.get("Q1:C", "")
    q1_e_net = pm.get("Q1:E", "")
    cout1_net = pm.get("COUT:1", "")
    # Q1:C must be on a supply rail; output (COUT:1) must share Q1:E net
    if not q1_c_net or not _is_supply_net(q1_c_net):
        return False
    if q1_e_net and cout1_net and cout1_net != q1_e_net:
        return False
    return True


def common_emitter_wiring_ok(payload: Dict[str, Any]) -> bool:
    """True if payload already has correct CE hallmark wiring."""
    pm = _pin_map(payload.get("nets") or [])
    q1_c_net = pm.get("Q1:C", "")
    cin2_net = pm.get("CIN:2", "")
    q1_b_net = pm.get("Q1:B", "")
    # Q1:C must NOT be on supply rail (needs RC load)
    if q1_c_net and _is_supply_net(q1_c_net):
        return False
    # CIN:2 should be on same net as Q1:B
    if cin2_net and q1_b_net and cin2_net != q1_b_net:
        return False
    return True


# ---------------------------------------------------------------------------
# Net rebuild functions (one per topology)
# ---------------------------------------------------------------------------


def _rebuild_common_base_nets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Enforce: CIN → Emitter, CB bypass on Base, COUT from Collector."""
    components = payload.get("components") or []
    refs = _component_refs(components)

    rb1 = _pick_ref(refs, ("RB1", "R1"), prefix="RB") or "RB1"
    rb2 = _pick_ref(refs, ("RB2", "R2"), prefix="RB") or "RB2"
    rc = _pick_ref(refs, ("RC", "RL", "RD"), prefix="R") or "RC"
    re_ref = _pick_ref(refs, ("RE", "RS"), prefix="R") or "RE"
    cin = _pick_ref(refs, ("CIN",), prefix="C") or "CIN"
    cout = _pick_ref(refs, ("COUT",), prefix="C") or "COUT"
    cb = _ensure_cap(components, refs, ("CB", "CBYP", "C_B", "CB_BYP"), "CB", "10uF", "bypass_cap")
    payload["components"] = components

    vcc = _pick_ref(refs, ("VCC", "VDD", "VS+"), prefix="V") or "VCC"
    gnd = _pick_ref(refs, ("GND",), prefix="G") or "GND"

    in_nodes, out_nodes = _in_out_signal_nodes(refs, cin, cout)

    return [
        {"net_name": "VCC",          "nodes": [f"{vcc}:1", f"{rb1}:1", f"{rc}:1"]},
        {"net_name": "COLLECTOR_Q1", "nodes": ["Q1:C",   f"{rc}:2",  f"{cout}:1"]},
        {"net_name": "BASE_Q1",      "nodes": ["Q1:B",   f"{rb1}:2", f"{rb2}:1", f"{cb}:1"]},
        {"net_name": "0",            "nodes": [f"{gnd}:1", f"{rb2}:2", f"{re_ref}:2", f"{cb}:2"]},
        {"net_name": "IN_SIG",       "nodes": in_nodes},
        {"net_name": "EMITTER_Q1",   "nodes": [f"{cin}:2", "Q1:E", f"{re_ref}:1"]},
        {"net_name": "OUT_SIG",      "nodes": out_nodes},
    ]


def _rebuild_common_emitter_nets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Enforce: CIN → Base, CE bypass on RE, COUT from Collector."""
    components = payload.get("components") or []
    refs = _component_refs(components)

    rb1 = _pick_ref(refs, ("RB1", "R1"), prefix="RB") or "RB1"
    rb2 = _pick_ref(refs, ("RB2", "R2"), prefix="RB") or "RB2"
    rc = _pick_ref(refs, ("RC", "RL", "RD"), prefix="R") or "RC"
    re_ref = _pick_ref(refs, ("RE", "RE1", "RE2"), prefix="R") or "RE"
    cin = _pick_ref(refs, ("CIN",), prefix="C") or "CIN"
    cout = _pick_ref(refs, ("COUT",), prefix="C") or "COUT"
    # Emitter bypass cap (CE)
    ce = _ensure_cap(components, refs, ("CE", "CE1", "CE2"), "CE", "100uF", "bypass_cap")
    payload["components"] = components

    vcc = _pick_ref(refs, ("VCC", "VDD", "VS+"), prefix="V") or "VCC"
    gnd = _pick_ref(refs, ("GND",), prefix="G") or "GND"

    in_nodes, out_nodes = _in_out_signal_nodes(refs, cin, cout)

    return [
        {"net_name": "VCC",          "nodes": [f"{vcc}:1", f"{rb1}:1", f"{rc}:1"]},
        {"net_name": "COLLECTOR_Q1", "nodes": ["Q1:C",   f"{rc}:2",  f"{cout}:1"]},
        {"net_name": "BASE_Q1",      "nodes": ["Q1:B",   f"{rb1}:2", f"{rb2}:1", f"{cin}:2"]},
        {"net_name": "EMITTER_Q1",   "nodes": ["Q1:E",   f"{re_ref}:1", f"{ce}:1"]},
        {"net_name": "0",            "nodes": [f"{gnd}:1", f"{rb2}:2", f"{re_ref}:2", f"{ce}:2"]},
        {"net_name": "IN_SIG",       "nodes": in_nodes},
        {"net_name": "OUT_SIG",      "nodes": out_nodes},
    ]


def _rebuild_common_collector_nets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Enforce: CIN → Base, Collector tied to VCC (no RC), COUT from Emitter."""
    components = payload.get("components") or []
    refs = _component_refs(components)

    rb1 = _pick_ref(refs, ("RB1", "R1"), prefix="RB") or "RB1"
    rb2 = _pick_ref(refs, ("RB2", "R2"), prefix="RB") or "RB2"
    re_ref = _pick_ref(refs, ("RE", "RS"), prefix="R") or "RE"
    cin = _pick_ref(refs, ("CIN",), prefix="C") or "CIN"
    cout = _pick_ref(refs, ("COUT",), prefix="C") or "COUT"
    # No bypass cap for CC; no RC load
    payload["components"] = components

    vcc = _pick_ref(refs, ("VCC", "VDD", "VS+"), prefix="V") or "VCC"
    gnd = _pick_ref(refs, ("GND",), prefix="G") or "GND"

    in_nodes, out_nodes = _in_out_signal_nodes(refs, cin, cout)

    return [
        # Collector ties directly to VCC — no RC load resistor
        {"net_name": "VCC",        "nodes": [f"{vcc}:1", "Q1:C", f"{rb1}:1"]},
        {"net_name": "BASE_Q1",    "nodes": ["Q1:B",   f"{rb1}:2", f"{rb2}:1", f"{cin}:2"]},
        {"net_name": "EMITTER_Q1", "nodes": ["Q1:E",   f"{re_ref}:1", f"{cout}:1"]},
        {"net_name": "0",          "nodes": [f"{gnd}:1", f"{rb2}:2", f"{re_ref}:2"]},
        {"net_name": "IN_SIG",     "nodes": in_nodes},
        {"net_name": "OUT_SIG",    "nodes": out_nodes},
    ]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def repair_bjt_ir_wiring(payload: Dict[str, Any], requirements: str = "") -> Dict[str, Any]:
    """Rewrite nets when a BJT family is explicit but hallmark wiring is wrong.

    Checks each topology against the wiring rules from topology_wiring_spec and
    repairs any mis-wired IR by rebuilding the nets section deterministically.
    """
    if not isinstance(payload, dict):
        return payload

    family = infer_bjt_family(payload, requirements)
    if family not in _BJT_FAMILIES:
        return payload

    spec = get_spec(family)

    # ── Common Base ────────────────────────────────────────────────────────
    if family == "common_base":
        if common_base_wiring_ok(payload):
            return payload
        repaired = copy.deepcopy(payload)
        repaired["nets"] = _dedupe_net_nodes(_rebuild_common_base_nets(repaired))
        _patch_topology_metadata(repaired, "common_base")
        logger.warning(
            "Auto-repaired common_base BJT wiring "
            "(spec: %s → %s, shared: %s with AC bypass)",
            spec.signal_in_pin if spec else "Q1:E",
            spec.signal_out_pin if spec else "Q1:C",
            spec.shared_pin if spec else "Q1:B",
        )
        return repaired

    # ── Common Collector ───────────────────────────────────────────────────
    if family == "common_collector":
        if common_collector_wiring_ok(payload):
            return payload
        repaired = copy.deepcopy(payload)
        repaired["nets"] = _dedupe_net_nodes(_rebuild_common_collector_nets(repaired))
        _patch_topology_metadata(repaired, "common_collector")
        logger.warning(
            "Auto-repaired common_collector BJT wiring "
            "(spec: %s → %s, Collector to VCC, no RC)",
            spec.signal_in_pin if spec else "Q1:B",
            spec.signal_out_pin if spec else "Q1:E",
        )
        return repaired

    # ── Common Emitter ─────────────────────────────────────────────────────
    if family == "common_emitter":
        if common_emitter_wiring_ok(payload):
            return payload
        repaired = copy.deepcopy(payload)
        repaired["nets"] = _dedupe_net_nodes(_rebuild_common_emitter_nets(repaired))
        _patch_topology_metadata(repaired, "common_emitter")
        logger.warning(
            "Auto-repaired common_emitter BJT wiring "
            "(spec: %s → %s, CE bypass on Emitter)",
            spec.signal_in_pin if spec else "Q1:B",
            spec.signal_out_pin if spec else "Q1:C",
        )
        return repaired

    return payload
