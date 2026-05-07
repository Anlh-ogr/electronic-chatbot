from __future__ import annotations

from typing import Dict, Iterable, List

from .agr_templates import GRID_MM, STACK_STEP_GRIDS, STAGE_WIDTH_GRIDS
from .coordinate_solver import PASSIVE_TYPES, PlacedComponent, PlacementResult, solve_stage
from .role_inferrer import infer_roles
from .topology_classifier import classify_stage


def compose(ir) -> PlacementResult:
    """Compose placements for multi-stage circuits."""
    components = list(_get_attr(ir, "components", []) or [])
    architecture = _get_attr(ir, "architecture")
    stages = list(_get_attr(architecture, "stages", []) or [])
    stage_count = int(_get_attr(architecture, "stage_count", 1) or 1)
    if stage_count < 1:
        stage_count = 1

    role_map = infer_roles(components)

    stage_components: Dict[int, List] = {idx: [] for idx in range(stage_count)}
    bridge_components: List = []

    for comp in components:
        stage = _get_stage_index(comp)
        role = str(_get_attr(comp, "role", "") or role_map.get(_get_ref(comp), "")).strip().lower()
        comp_type = str(_get_attr(comp, "type", "") or "").lower()
        if role == "stage_bridge" and comp_type in PASSIVE_TYPES and stage_count > 1:
            bridge_components.append(comp)
            continue
        if stage is None:
            stage = 0
        if stage not in stage_components:
            stage = 0
        stage_components[stage].append(comp)

    placements: Dict[str, PlacedComponent] = {}

    for idx in range(stage_count):
        stage = stages[idx] if idx < len(stages) else None
        stage_topology = str(_get_attr(stage, "topology", "") or _get_attr(_get_attr(ir, "analysis"), "topology_classification", ""))
        family = classify_stage(stage, stage_components.get(idx, []))
        offset = (idx * STAGE_WIDTH_GRIDS * GRID_MM, 0.0)
        result = solve_stage(
            stage_components.get(idx, []),
            family,
            topology=stage_topology,
            base_offset=offset,
        )
        placements.update(result.components)

    placements.update(_place_bridges(bridge_components, stage_count))

    return PlacementResult(components=placements)


def _place_bridges(components: Iterable, stage_count: int) -> Dict[str, PlacedComponent]:
    if stage_count < 2:
        return {}
    placements: Dict[str, PlacedComponent] = {}
    y_offset = 0.0
    for idx, comp in enumerate(sorted(components, key=_get_ref)):
        stage = _get_stage_index(comp) or 0
        if stage >= stage_count - 1:
            stage = stage_count - 2
        left_x = stage * STAGE_WIDTH_GRIDS * GRID_MM
        right_x = (stage + 1) * STAGE_WIDTH_GRIDS * GRID_MM
        mid_x = (left_x + right_x) / 2.0
        y = y_offset + idx * STACK_STEP_GRIDS * GRID_MM
        placements[_get_ref(comp)] = _place_bridge_component(comp, mid_x, y)
    return placements


def _place_bridge_component(comp, x: float, y: float) -> PlacedComponent:
    from .coordinate_solver import ComponentSpec, _place_component  # local import to avoid cycle

    spec = ComponentSpec(
        ref=_get_ref(comp),
        comp_type=str(_get_attr(comp, "type", "") or "").lower(),
        role=str(_get_attr(comp, "role", "") or "stage_bridge").strip().lower(),
        topology_stage=_get_stage_index(comp),
    )
    return _place_component(spec, x, y, 90)


def _get_stage_index(comp) -> int | None:
    stage = _get_attr(comp, "topology_stage")
    try:
        return int(stage) if stage is not None else None
    except (TypeError, ValueError):
        return None


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


__all__ = ["compose"]
