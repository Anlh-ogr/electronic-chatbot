from __future__ import annotations

from enum import Enum
from typing import Iterable, Optional


class PlacementFamily(Enum):
    """High-level placement families for schematic layout."""

    SINGLE_TRANSISTOR = "single_transistor"
    PUSH_PULL = "push_pull"
    OPAMP_IC = "opamp_ic"
    CLASS_D = "class_d"
    MULTISTAGE = "multistage"


def classify(ir) -> PlacementFamily:
    """Classify a circuit into a placement family."""
    stage_count = _get_stage_count(ir)
    if stage_count > 1 or _has_multistage_components(ir):
        return PlacementFamily.MULTISTAGE

    if _has_class_d(ir):
        return PlacementFamily.CLASS_D
    if _has_opamp(ir):
        return PlacementFamily.OPAMP_IC
    if _has_push_pull(ir):
        return PlacementFamily.PUSH_PULL
    return PlacementFamily.SINGLE_TRANSISTOR


def classify_stage(stage, components: Iterable) -> PlacementFamily:
    """Classify a single stage into a placement family."""
    topology = _get_attr(stage, "topology", "")
    if _topology_is_class_d(topology):
        return PlacementFamily.CLASS_D
    if _topology_is_opamp(topology):
        return PlacementFamily.OPAMP_IC
    if _topology_is_push_pull(topology):
        return PlacementFamily.PUSH_PULL

    if _has_opamp_components(components):
        return PlacementFamily.OPAMP_IC
    if _has_push_pull_components(components):
        return PlacementFamily.PUSH_PULL
    return PlacementFamily.SINGLE_TRANSISTOR


def _get_stage_count(ir) -> int:
    architecture = _get_attr(ir, "architecture")
    if architecture is None:
        return 1
    return int(_get_attr(architecture, "stage_count", 1) or 1)


def _has_multistage_components(ir) -> bool:
    comps = _get_attr(ir, "components", []) or []
    for comp in comps:
        stage = _get_attr(comp, "topology_stage")
        if stage is None:
            continue
        try:
            if int(stage) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _has_class_d(ir) -> bool:
    analysis = _get_attr(ir, "analysis")
    if analysis is not None:
        if _topology_is_class_d(_get_attr(analysis, "topology_classification", "")):
            return True
    architecture = _get_attr(ir, "architecture")
    stages = _get_attr(architecture, "stages", []) or []
    for stage in stages:
        if _topology_is_class_d(_get_attr(stage, "topology", "")):
            return True
    return False


def _has_opamp(ir) -> bool:
    analysis = _get_attr(ir, "analysis")
    if analysis is not None:
        if _topology_is_opamp(_get_attr(analysis, "topology_classification", "")):
            return True
    return _has_opamp_components(_get_attr(ir, "components", []) or [])


def _has_push_pull(ir) -> bool:
    analysis = _get_attr(ir, "analysis")
    if analysis is not None:
        if _topology_is_push_pull(_get_attr(analysis, "topology_classification", "")):
            return True
    return _has_push_pull_components(_get_attr(ir, "components", []) or [])


def _has_opamp_components(components: Iterable) -> bool:
    for comp in components:
        comp_type = str(_get_attr(comp, "type", "") or "").lower()
        if comp_type == "opamp_ic":
            return True
    return False


def _has_push_pull_components(components: Iterable) -> bool:
    for comp in components:
        role = str(_get_attr(comp, "role", "") or "").lower()
        if role in {"output_pair_top", "output_pair_bottom"}:
            return True
    return False


def _topology_is_class_d(topology: Optional[str]) -> bool:
    topo = str(topology or "").lower()
    return "class_d" in topo or "class d" in topo


def _topology_is_opamp(topology: Optional[str]) -> bool:
    topo = str(topology or "").lower()
    return topo.startswith("opamp") or "opamp" in topo


def _topology_is_push_pull(topology: Optional[str]) -> bool:
    topo = str(topology or "").lower()
    return "class_ab" in topo or "class ab" in topo or "class_b" in topo or "class b" in topo


def _get_attr(obj, name: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


__all__ = ["PlacementFamily", "classify", "classify_stage"]
