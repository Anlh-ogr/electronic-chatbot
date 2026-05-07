from __future__ import annotations

from typing import Dict, Iterable


POWER_REFS = {"vcc", "vdd", "v+", "vss", "vee"}
GROUND_REFS = {"gnd", "ground", "0", "0v", "v-"}


def infer_roles(components: Iterable) -> Dict[str, str]:
    """Infer component roles when missing from the CircuitIR payload."""
    inferred: Dict[str, str] = {}

    for comp in components:
        ref = _get_ref(comp)
        if not ref:
            continue
        role = str(_get_attr(comp, "role", "") or "").strip()
        if role:
            inferred[ref] = role
            continue

        comp_type = str(_get_attr(comp, "type", "") or "").lower()
        ref_l = ref.lower()

        if _is_power(comp_type, ref_l):
            inferred[ref] = "supply"
            continue
        if _is_ground(comp_type, ref_l):
            inferred[ref] = "ground"
            continue
        if _is_active(comp_type):
            inferred[ref] = "stage_bridge"
            continue

        inferred[ref] = _infer_passive_role(ref_l, comp_type)

    return inferred


def _infer_passive_role(ref_l: str, comp_type: str) -> str:
    if "cin" in ref_l or "input" in ref_l:
        return "coupling_in"
    if "cout" in ref_l or "output" in ref_l:
        return "coupling_out"
    if "rf" in ref_l or "fb" in ref_l or "feedback" in ref_l:
        return "feedback"
    if ref_l.startswith("rc") or "load" in ref_l:
        return "load"
    if ref_l.startswith("re") or ref_l.startswith("rs") or "deg" in ref_l:
        return "degeneration"
    if ref_l.startswith("rb") or "bias" in ref_l:
        return "bias_top"
    if ref_l.startswith("ce") or "bypass" in ref_l:
        return "bypass"
    if comp_type in {"capacitor", "capacitor_polarized"}:
        return "coupling_in"
    return "auxiliary"


def _is_power(comp_type: str, ref_l: str) -> bool:
    return comp_type in {"power_supply", "power_symbol", "vcc", "vdd"} or ref_l in POWER_REFS


def _is_ground(comp_type: str, ref_l: str) -> bool:
    return comp_type in {"ground", "gnd"} or ref_l in GROUND_REFS


def _is_active(comp_type: str) -> bool:
    return comp_type in {
        "bjt_npn",
        "bjt_pnp",
        "mosfet_n",
        "mosfet_p",
        "jfet_n",
        "jfet_p",
        "opamp_ic",
    }


def _get_ref(comp) -> str:
    return (
        _get_attr(comp, "ref")
        or _get_attr(comp, "ref_id")
        or _get_attr(comp, "id")
        or ""
    ).strip()


def _get_attr(obj, name: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


__all__ = ["infer_roles"]
