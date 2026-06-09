"""Deterministic Op-Amp topology wiring repair for LLM-generated CircuitIR payloads.

Three Op-Amp configurations are covered:
  opamp_inverting      — signal to U1:-, U1:+ tied to GND, RF feedback from output
  opamp_non_inverting  — signal to U1:+, feedback divider (RF/RG) to U1:-
  opamp_differential   — V1 via R1 to U1:-, V2 via R3 to U1:+, R2/R4 feedback; R1=R3, R2=R4

The repair logic references topology_wiring_spec as the single source of truth.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.application.ai.topology_wiring_spec import get_spec

logger = logging.getLogger(__name__)

_OPAMP_FAMILIES = {"opamp_inverting", "opamp_non_inverting", "opamp_differential"}

_GND_NETS = {"0", "GND", "GROUND"}
_SUPPLY_NETS = {"VCC", "VDD", "V+", "VS+", "VPLUS"}


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


def _patch_topology_metadata(repaired: Dict[str, Any], family: str) -> None:
    signal_flow = repaired.get("signal_flow")
    if isinstance(signal_flow, dict):
        sf = dict(signal_flow)
        sf["input_node"] = "IN_PLUS_SIG" if family == "opamp_differential" else "IN_SIG"
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


def _get_value_from_component(components: List[Dict], ref: str) -> Optional[str]:
    for comp in components or []:
        if isinstance(comp, dict) and str(comp.get("ref", "")).strip().upper() == ref.upper():
            return str(comp.get("value") or "")
    return None


def _set_component_value(components: List[Dict], ref: str, value: str) -> None:
    for comp in components or []:
        if isinstance(comp, dict) and str(comp.get("ref", "")).strip().upper() == ref.upper():
            comp["value"] = value
            return


# ---------------------------------------------------------------------------
# Op-Amp family inference
# ---------------------------------------------------------------------------

_INV_HINTS = (
    r"\binverting\b",
    r"khu\s*[eế]ch\s*[dđ]\s*[aại]\s*[dđ][aảo]",
    r"\binv\b",
    r"[dđ][aả]o\s*pha",
    r"opamp[\s_-]*inv",
)
_NON_INV_HINTS = (
    r"\bnon[\s_-]inverting\b",
    r"khu\s*[eế]ch\s*[dđ][aại]\s*kh[oô]ng\s*[dđ][aả]o",
    r"\bnon[\s_-]inv\b",
    r"kh[oô]ng\s*[dđ][aả]o",
    r"khu\s*[eế]ch\s*[dđ][aại]\s*thu\s*[aậ]n",
)
_DIFF_HINTS = (
    r"\bdifferential\b",
    r"\bvi\s+sai\b",
    r"\bvisai\b",
    r"\bdiff\s*amp\b",
    r"khu\s*[eế]ch\s*[dđ][aại]\s*vi\s+sai",
)


def infer_opamp_family(payload: Dict[str, Any], requirements: str = "") -> Optional[str]:
    """Resolve Op-Amp family from IR fields or explicit user requirements text."""
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

    blob = re.sub(r"[^a-z0-9]+", "_", " ".join(candidates).lower())
    if "opamp_differential" in blob or "differential" in blob:
        return "opamp_differential"
    if "opamp_non_inverting" in blob or "non_inverting" in blob:
        return "opamp_non_inverting"
    if "opamp_inverting" in blob or "inverting" in blob:
        return "opamp_inverting"
    # Check if any opamp_ic device is present — needed to activate repair
    components = payload.get("components") or []
    has_opamp = any(
        str(c.get("type", "")).lower() in {"opamp_ic", "opamp"} for c in components if isinstance(c, dict)
    )
    if not has_opamp:
        return None

    req = (requirements or "").lower()
    if any(re.search(pat, req, re.IGNORECASE) for pat in _DIFF_HINTS):
        return "opamp_differential"
    if any(re.search(pat, req, re.IGNORECASE) for pat in _NON_INV_HINTS):
        return "opamp_non_inverting"
    if any(re.search(pat, req, re.IGNORECASE) for pat in _INV_HINTS):
        return "opamp_inverting"
    return None


# ---------------------------------------------------------------------------
# Wiring validation helpers
# ---------------------------------------------------------------------------


def _vcc_ref(refs: Set[str]) -> str:
    return _pick_ref(refs, ("VCC", "VDD", "VS+"), prefix="V") or "VCC"


def _gnd_ref(refs: Set[str]) -> str:
    return _pick_ref(refs, ("GND",), prefix="G") or "GND"


def opamp_inverting_wiring_ok(payload: Dict[str, Any]) -> bool:
    """True if payload already has correct Inverting op-amp hallmark wiring."""
    pm = _pin_map(payload.get("nets") or [])
    u1_plus_net = pm.get("U1:+", "")
    rf1_net = pm.get("RF:1", "")
    u1_out_net = pm.get("U1:OUT", "")
    rf2_net = pm.get("RF:2", "")
    u1_minus_net = pm.get("U1:-", "")
    rin2_net = pm.get("RIN:2", "")

    # U1:+ must be on GND (0)
    if u1_plus_net and u1_plus_net not in _GND_NETS:
        return False
    # RF:1 must share net with U1:OUT (feedback FROM output)
    if rf1_net and u1_out_net and rf1_net != u1_out_net:
        return False
    # RF:2 must share net with U1:- (summing junction)
    if rf2_net and u1_minus_net and rf2_net != u1_minus_net:
        return False
    # RIN:2 must share net with U1:- (summing junction)
    if rin2_net and u1_minus_net and rin2_net != u1_minus_net:
        return False
    return True


def opamp_non_inverting_wiring_ok(payload: Dict[str, Any]) -> bool:
    """True if payload already has correct Non-Inverting op-amp hallmark wiring."""
    pm = _pin_map(payload.get("nets") or [])
    u1_plus_net = pm.get("U1:+", "")
    u1_minus_net = pm.get("U1:-", "")
    rg1_net = pm.get("RG:1", "")
    rf2_net = pm.get("RF:2", "")
    rf1_net = pm.get("RF:1", "")
    u1_out_net = pm.get("U1:OUT", "")

    # U1:+ must NOT be on GND (it receives the signal)
    if u1_plus_net and u1_plus_net in _GND_NETS:
        return False
    # RG:1 should be on GND
    if rg1_net and rg1_net not in _GND_NETS:
        return False
    # RF:1 should share with U1:OUT (feedback path starts from output)
    if rf1_net and u1_out_net and rf1_net != u1_out_net:
        return False
    # RF:2 should share with U1:- (feedback to inverting input)
    if rf2_net and u1_minus_net and rf2_net != u1_minus_net:
        return False
    return True


def opamp_differential_wiring_ok(payload: Dict[str, Any]) -> bool:
    """True if payload already has correct Differential op-amp hallmark wiring."""
    pm = _pin_map(payload.get("nets") or [])
    r1_2_net = pm.get("R1:2", "")    # should share with U1:- (INV_IN)
    r2_1_net = pm.get("R2:1", "")    # should share with U1:- (INV_IN)
    r3_2_net = pm.get("R3:2", "")    # should share with U1:+ (NON_INV_IN)
    r4_1_net = pm.get("R4:1", "")    # should share with U1:+ (NON_INV_IN)
    u1_minus_net = pm.get("U1:-", "")
    u1_plus_net = pm.get("U1:+", "")
    r2_2_net = pm.get("R2:2", "")    # should share with U1:OUT (feedback)
    u1_out_net = pm.get("U1:OUT", "")
    r4_2_net = pm.get("R4:2", "")    # should be on GND

    if r1_2_net and u1_minus_net and r1_2_net != u1_minus_net:
        return False
    if r2_1_net and u1_minus_net and r2_1_net != u1_minus_net:
        return False
    if r3_2_net and u1_plus_net and r3_2_net != u1_plus_net:
        return False
    if r4_1_net and u1_plus_net and r4_1_net != u1_plus_net:
        return False
    if r2_2_net and u1_out_net and r2_2_net != u1_out_net:
        return False
    if r4_2_net and r4_2_net not in _GND_NETS:
        return False
    return True


def _differential_values_matched(components: List[Dict]) -> bool:
    """Return True if R1=R3 and R2=R4 (CMRR matching requirement)."""
    r1 = _get_value_from_component(components, "R1")
    r3 = _get_value_from_component(components, "R3")
    r2 = _get_value_from_component(components, "R2")
    r4 = _get_value_from_component(components, "R4")
    if r1 and r3 and r1 != r3:
        return False
    if r2 and r4 and r2 != r4:
        return False
    return True


# ---------------------------------------------------------------------------
# Net rebuild functions
# ---------------------------------------------------------------------------


def _rebuild_inverting_nets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Enforce: U1:+ → GND, RIN → inv input, RF feedback from output."""
    components = payload.get("components") or []
    refs = _component_refs(components)

    rin = _pick_ref(refs, ("RIN", "R_IN", "RI"), prefix="RIN") or "RIN"
    rf = _pick_ref(refs, ("RF", "R_F", "RFB"), prefix="RF") or "RF"
    vcc = _vcc_ref(refs)
    gnd = _gnd_ref(refs)

    in_nodes: List[str] = [f"{rin}:1"]
    for ref in ("VIN", "VTB", "VSIG", "IN"):
        if ref in refs:
            in_nodes.insert(0, f"{ref}:1")
            break
    out_nodes: List[str] = ["U1:OUT"]
    for ref in ("VOUT", "OUT"):
        if ref in refs:
            out_nodes.append(f"{ref}:1")
            break

    decoupling_caps = [
        r for r in sorted(refs)
        if r.startswith("C") and r not in {"CIN", "COUT"} and not r.startswith("CB")
    ]

    nets = [
        {"net_name": "VCC",         "nodes": [f"{vcc}:1"]},
        {"net_name": "0",           "nodes": [f"{gnd}:1", "U1:+"]},
        {"net_name": "IN_SIG",      "nodes": in_nodes},
        {"net_name": "U1_INV_IN",   "nodes": [f"{rin}:2", f"{rf}:2", "U1:-"]},
        {"net_name": "OUT_SIG",     "nodes": [f"{rf}:1"] + out_nodes},
    ]
    # VS- for dual supply
    if "VS-" in refs or any(r.startswith("VS-") for r in refs):
        vsneg = _pick_ref(refs, ("VS-",), prefix="VS") or "VS-"
        nets.append({"net_name": "VS_NEG", "nodes": [f"{vsneg}:1"]})
    # Decoupling caps to 0
    for cap in decoupling_caps[:2]:
        nets.append({"net_name": "VCC", "nodes": [f"{cap}:1"]})
        nets[1]["nodes"].append(f"{cap}:2")

    if "U1:VS+" in {f"{c['ref']}:VS+" for c in components if isinstance(c, dict)}:
        for net in nets:
            if net["net_name"] == "VCC":
                net["nodes"].append("U1:VS+")
    return nets


def _rebuild_non_inverting_nets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Enforce: signal → U1:+, feedback divider RF/RG to U1:-."""
    components = payload.get("components") or []
    refs = _component_refs(components)

    rg = _pick_ref(refs, ("RG", "R_G", "RG1"), prefix="RG") or "RG"
    rf = _pick_ref(refs, ("RF", "R_F", "RFB"), prefix="RF") or "RF"
    vcc = _vcc_ref(refs)
    gnd = _gnd_ref(refs)

    in_nodes: List[str] = ["U1:+"]
    for ref in ("VIN", "VTB", "VSIG", "IN"):
        if ref in refs:
            in_nodes.insert(0, f"{ref}:1")
            break
    out_nodes: List[str] = ["U1:OUT"]
    for ref in ("VOUT", "OUT"):
        if ref in refs:
            out_nodes.append(f"{ref}:1")
            break

    decoupling_caps = [
        r for r in sorted(refs)
        if r.startswith("C") and r not in {"CIN", "COUT"} and not r.startswith("CB")
    ]

    nets = [
        {"net_name": "VCC",         "nodes": [f"{vcc}:1"]},
        {"net_name": "0",           "nodes": [f"{gnd}:1", f"{rg}:1"]},
        {"net_name": "IN_SIG",      "nodes": in_nodes},
        {"net_name": "U1_INV_IN",   "nodes": [f"{rg}:2", f"{rf}:2", "U1:-"]},
        {"net_name": "OUT_SIG",     "nodes": [f"{rf}:1"] + out_nodes},
    ]
    for cap in decoupling_caps[:2]:
        nets[0]["nodes"].append(f"{cap}:1")
        nets[1]["nodes"].append(f"{cap}:2")
    return nets


def _rebuild_differential_nets(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Enforce: R1/R3 input resistors, R2/R4 feedback, R1=R3, R2=R4."""
    components = payload.get("components") or []
    refs = _component_refs(components)

    r1 = _pick_ref(refs, ("R1",)) or "R1"
    r2 = _pick_ref(refs, ("R2",)) or "R2"
    r3 = _pick_ref(refs, ("R3",)) or "R3"
    r4 = _pick_ref(refs, ("R4",)) or "R4"
    vcc = _vcc_ref(refs)
    gnd = _gnd_ref(refs)

    # Enforce R1=R3, R2=R4 by equalising values
    val_r1 = _get_value_from_component(components, r1) or "10k"
    val_r2 = _get_value_from_component(components, r2) or "10k"
    _set_component_value(components, r3, val_r1)   # R3 = R1
    _set_component_value(components, r4, val_r2)   # R4 = R2
    payload["components"] = components

    decoupling_caps = [
        r for r in sorted(refs)
        if r.startswith("C") and r not in {"CIN", "COUT"} and not r.startswith("CB")
    ]

    nets = [
        {"net_name": "VCC",              "nodes": [f"{vcc}:1"]},
        {"net_name": "0",                "nodes": [f"{gnd}:1", f"{r4}:2"]},
        {"net_name": "IN_MINUS_SIG",     "nodes": [f"{r1}:1"]},
        {"net_name": "IN_PLUS_SIG",      "nodes": [f"{r3}:1"]},
        {"net_name": "U1_INV_IN",        "nodes": [f"{r1}:2", f"{r2}:1", "U1:-"]},
        {"net_name": "U1_NON_INV_IN",    "nodes": [f"{r3}:2", f"{r4}:1", "U1:+"]},
        {"net_name": "OUT_SIG",          "nodes": [f"{r2}:2", "U1:OUT"]},
    ]
    for ref in ("VIN", "VTB", "VSIG", "IN"):
        if ref in refs:
            nets[2]["nodes"].insert(0, f"{ref}:1")
            break
    for ref in ("VOUT", "OUT"):
        if ref in refs:
            nets[-1]["nodes"].append(f"{ref}:1")
            break
    for cap in decoupling_caps[:2]:
        nets[0]["nodes"].append(f"{cap}:1")
        nets[1]["nodes"].append(f"{cap}:2")
    return nets


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def repair_opamp_ir_wiring(payload: Dict[str, Any], requirements: str = "") -> Dict[str, Any]:
    """Rewrite nets when an Op-Amp family is detected but hallmark wiring is wrong.

    Validates each topology against the characteristic rules from topology_wiring_spec
    and deterministically rebuilds the nets section when a violation is found.
    """
    if not isinstance(payload, dict):
        return payload

    family = infer_opamp_family(payload, requirements)
    if family not in _OPAMP_FAMILIES:
        return payload

    spec = get_spec(family)

    # ── Inverting ──────────────────────────────────────────────────────────
    if family == "opamp_inverting":
        if opamp_inverting_wiring_ok(payload):
            return payload
        repaired = copy.deepcopy(payload)
        repaired["nets"] = _dedupe_net_nodes(_rebuild_inverting_nets(repaired))
        _patch_topology_metadata(repaired, "opamp_inverting")
        logger.warning(
            "Auto-repaired opamp_inverting wiring "
            "(U1:+ → GND, RIN → U1_INV_IN, RF feedback from U1:OUT)"
        )
        return repaired

    # ── Non-Inverting ──────────────────────────────────────────────────────
    if family == "opamp_non_inverting":
        if opamp_non_inverting_wiring_ok(payload):
            return payload
        repaired = copy.deepcopy(payload)
        repaired["nets"] = _dedupe_net_nodes(_rebuild_non_inverting_nets(repaired))
        _patch_topology_metadata(repaired, "opamp_non_inverting")
        logger.warning(
            "Auto-repaired opamp_non_inverting wiring "
            "(signal → U1:+, RG to GND, RF feedback to U1:-)"
        )
        return repaired

    # ── Differential ──────────────────────────────────────────────────────
    if family == "opamp_differential":
        values_ok = _differential_values_matched(payload.get("components") or [])
        if opamp_differential_wiring_ok(payload) and values_ok:
            return payload
        repaired = copy.deepcopy(payload)
        repaired["nets"] = _dedupe_net_nodes(_rebuild_differential_nets(repaired))
        _patch_topology_metadata(repaired, "opamp_differential")
        if not values_ok:
            logger.warning("Auto-repaired opamp_differential: equalised R1=R3 and R2=R4 for CMRR")
        logger.warning(
            "Auto-repaired opamp_differential wiring "
            "(R1/R3 inputs, R2/R4 feedback, R4 to GND)"
        )
        return repaired

    return payload
