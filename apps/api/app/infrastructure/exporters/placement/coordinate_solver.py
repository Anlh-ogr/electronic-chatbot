from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

from .agr_templates import GRID_MM, STACK_STEP_GRIDS, RoleTemplate, get_templates
from .pin_resolver import resolve_pins
from .role_inferrer import infer_roles
from .topology_classifier import PlacementFamily


PASSIVE_TYPES = {
    "resistor",
    "capacitor",
    "capacitor_polarized",
    "inductor",
    "transformer",
    "diode",
}


@dataclass(frozen=True)
class ComponentSpec:
    ref: str
    comp_type: str
    role: str
    topology_stage: int | None = None


@dataclass(frozen=True)
class PlacedComponent:
    ref: str
    comp_type: str
    x_mm: float
    y_mm: float
    rotation: int
    pins: Dict[str, Tuple[float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class PlacementResult:
    components: Dict[str, PlacedComponent]
    wires: List[List[Tuple[float, float]]] = field(default_factory=list)
    junctions: List[Tuple[float, float]] = field(default_factory=list)


def solve_stage(
    components: Iterable,
    family: PlacementFamily,
    *,
    topology: str | None = None,
    base_offset: Tuple[float, float] = (0.0, 0.0),
) -> PlacementResult:
    """Solve deterministic placement for a single stage."""
    specs = _normalize_components(components)
    if not specs:
        return PlacementResult(components={})

    templates = get_templates(family)
    placements: Dict[str, PlacedComponent] = {}
    fixed_refs: set[str] = set()

    topology_label = str(topology or "").lower()

    if family == PlacementFamily.OPAMP_IC:
        master = _pick_master(specs, prefer_type="opamp_ic")
        if master:
            placements[master.ref] = _place_component(master, 0.0, 0.0, 0)
            fixed_refs.add(master.ref)
        anchor_points = _opamp_anchor_points(master, topology_label)
    elif family in {PlacementFamily.PUSH_PULL, PlacementFamily.CLASS_D}:
        anchor_points = {"origin": (0.0, 0.0)}
        _place_push_pull_pair(specs, placements, fixed_refs)
    else:
        master = _pick_master(specs)
        if master:
            placements[master.ref] = _place_component(master, 0.0, 0.0, 0)
            fixed_refs.add(master.ref)
        anchor_points = _active_anchor_points(master, topology_label)
        _place_darlington_pair(specs, topology_label, placements, fixed_refs)

    role_groups = _group_by_role(specs)
    role_axis = {role: tmpl.stack_axis for role, tmpl in templates.items()}
    role_by_ref = {spec.ref: spec.role for spec in specs}

    for role, group in role_groups.items():
        for idx, spec in enumerate(group):
            if spec.ref in placements:
                continue
            template = templates.get(role)
            if template is None:
                template = RoleTemplate(role, "origin", 0, 0, 0, "y")
            anchor = _resolve_anchor(template.anchor, anchor_points)
            dx, dy = template.dx_grids * GRID_MM, template.dy_grids * GRID_MM
            stack_dx, stack_dy = _stack_offset(template.stack_axis, idx)

            if role == "coupling_in" and family == PlacementFamily.OPAMP_IC and len(group) > 1:
                anchor = _resolve_anchor("input_pin_alt" if idx % 2 == 1 else "input_pin", anchor_points)
                dy += (1 if idx % 2 == 0 else -1) * GRID_MM

            x = anchor[0] + dx + stack_dx
            y = anchor[1] + dy + stack_dy
            placements[spec.ref] = _place_component(spec, x, y, template.rotation)

    placements = _apply_base_offset(placements, base_offset)
    placements = _resolve_overlaps(placements, role_axis, role_by_ref, fixed_refs)

    return PlacementResult(components=placements)


def _normalize_components(components: Iterable) -> List[ComponentSpec]:
    roles = infer_roles(components)
    specs: List[ComponentSpec] = []
    for comp in components:
        ref = _get_ref(comp)
        if not ref:
            continue
        comp_type = str(_get_attr(comp, "type", "") or "").lower()
        role = str(_get_attr(comp, "role", "") or roles.get(ref, "auxiliary")).strip().lower()
        stage = _get_attr(comp, "topology_stage")
        try:
            stage = int(stage) if stage is not None else None
        except (TypeError, ValueError):
            stage = None
        specs.append(ComponentSpec(ref=ref, comp_type=comp_type, role=role, topology_stage=stage))
    return specs


def _pick_master(specs: Iterable[ComponentSpec], prefer_type: str | None = None) -> ComponentSpec | None:
    if prefer_type:
        for spec in specs:
            if spec.comp_type == prefer_type:
                return spec
    for spec in specs:
        if _is_active(spec.comp_type):
            return spec
    return next(iter(specs), None)


def _place_component(spec: ComponentSpec, x: float, y: float, rotation: int) -> PlacedComponent:
    pins = resolve_pins(spec.comp_type, rotation)
    abs_pins = {name: (x + dx, y + dy) for name, (dx, dy) in pins.items()}
    return PlacedComponent(
        ref=spec.ref,
        comp_type=spec.comp_type,
        x_mm=x,
        y_mm=y,
        rotation=rotation,
        pins=abs_pins,
    )


def _place_push_pull_pair(
    specs: Iterable[ComponentSpec],
    placements: Dict[str, PlacedComponent],
    fixed_refs: set[str],
) -> None:
    top_devices = [s for s in specs if s.role == "output_pair_top" and _is_active(s.comp_type)]
    bottom_devices = [s for s in specs if s.role == "output_pair_bottom" and _is_active(s.comp_type)]
    actives = [s for s in specs if _is_active(s.comp_type)]

    if not top_devices and actives:
        top_devices = actives[:1]
    if not bottom_devices and len(actives) > 1:
        bottom_devices = actives[1:2]

    for device, y in [(top_devices[:1], -4 * GRID_MM), (bottom_devices[:1], 4 * GRID_MM)]:
        if not device:
            continue
        spec = device[0]
        placements[spec.ref] = _place_component(spec, 0.0, y, 0)
        fixed_refs.add(spec.ref)


def _place_darlington_pair(
    specs: Iterable[ComponentSpec],
    topology: str,
    placements: Dict[str, PlacedComponent],
    fixed_refs: set[str],
) -> None:
    if "darlington" not in topology:
        return
    actives = [s for s in specs if _is_active(s.comp_type)]
    if len(actives) < 2:
        return
    primary = actives[0]
    secondary = actives[1]
    if primary.ref not in placements:
        placements[primary.ref] = _place_component(primary, 0.0, 0.0, 0)
        fixed_refs.add(primary.ref)
    if secondary.ref not in placements:
        placements[secondary.ref] = _place_component(secondary, 3 * GRID_MM, 0.0, 0)
        fixed_refs.add(secondary.ref)


def _group_by_role(specs: Iterable[ComponentSpec]) -> Dict[str, List[ComponentSpec]]:
    grouped: Dict[str, List[ComponentSpec]] = {}
    for spec in specs:
        grouped.setdefault(spec.role, []).append(spec)
    for role in grouped:
        grouped[role].sort(key=lambda s: s.ref)
    return grouped


def _active_anchor_points(master: ComponentSpec | None, topology: str) -> Dict[str, Tuple[float, float]]:
    origin = (0.0, 0.0)
    if master is None:
        return {
            "origin": origin,
            "input_pin": origin,
            "output_pin": origin,
            "bias_pin": origin,
            "upper_pin": origin,
            "lower_pin": origin,
        }

    pins = resolve_pins(master.comp_type, 0)
    mapping = _pin_roles_for_topology(master.comp_type, topology)
    input_pin = pins.get(mapping["input"], (0.0, 0.0))
    output_pin = pins.get(mapping["output"], (0.0, 0.0))
    bias_pin = pins.get(mapping["bias"], input_pin)
    upper_pin = pins.get(mapping["upper"], output_pin)
    lower_pin = pins.get(mapping["lower"], (0.0, 0.0))

    return {
        "origin": origin,
        "input_pin": (origin[0] + input_pin[0], origin[1] + input_pin[1]),
        "output_pin": (origin[0] + output_pin[0], origin[1] + output_pin[1]),
        "bias_pin": (origin[0] + bias_pin[0], origin[1] + bias_pin[1]),
        "upper_pin": (origin[0] + upper_pin[0], origin[1] + upper_pin[1]),
        "lower_pin": (origin[0] + lower_pin[0], origin[1] + lower_pin[1]),
    }


def _opamp_anchor_points(master: ComponentSpec | None, topology: str) -> Dict[str, Tuple[float, float]]:
    origin = (0.0, 0.0)
    if master is None:
        return {
            "origin": origin,
            "input_pin": origin,
            "input_pin_alt": origin,
            "inv_pin": origin,
            "output_pin": origin,
            "supply_pin": origin,
            "ground_pin": origin,
        }

    pins = resolve_pins(master.comp_type, 0)
    inv_pin = pins.get("-", (0.0, 0.0))
    noninv_pin = pins.get("+", (0.0, 0.0))
    out_pin = pins.get("OUT", (0.0, 0.0))
    supply_pin = pins.get("VS+", (0.0, 0.0))
    ground_pin = pins.get("VS-", (0.0, 0.0))

    input_pin = noninv_pin
    if "inverting" in topology:
        input_pin = inv_pin

    return {
        "origin": origin,
        "input_pin": (origin[0] + input_pin[0], origin[1] + input_pin[1]),
        "input_pin_alt": (origin[0] + inv_pin[0], origin[1] + inv_pin[1]),
        "inv_pin": (origin[0] + inv_pin[0], origin[1] + inv_pin[1]),
        "output_pin": (origin[0] + out_pin[0], origin[1] + out_pin[1]),
        "supply_pin": (origin[0] + supply_pin[0], origin[1] + supply_pin[1]),
        "ground_pin": (origin[0] + ground_pin[0], origin[1] + ground_pin[1]),
    }


def _pin_roles_for_topology(comp_type: str, topology: str) -> Dict[str, str]:
    topo = topology or ""
    comp = comp_type.lower()

    if comp.startswith("bjt"):
        if "common_collector" in topo or "bjt_cc" in topo:
            return {"input": "B", "output": "E", "bias": "B", "upper": "C", "lower": "E"}
        if "common_base" in topo or "bjt_cb" in topo:
            return {"input": "E", "output": "C", "bias": "B", "upper": "C", "lower": "E"}
        return {"input": "B", "output": "C", "bias": "B", "upper": "C", "lower": "E"}

    if comp.startswith("mosfet") or comp.startswith("jfet"):
        if "common_drain" in topo or "mosfet_cd" in topo:
            return {"input": "G", "output": "S", "bias": "G", "upper": "D", "lower": "S"}
        if "common_gate" in topo or "mosfet_cg" in topo:
            return {"input": "S", "output": "D", "bias": "G", "upper": "D", "lower": "S"}
        return {"input": "G", "output": "D", "bias": "G", "upper": "D", "lower": "S"}

    return {"input": "1", "output": "2", "bias": "1", "upper": "2", "lower": "1"}


def _resolve_anchor(name: str, anchors: Dict[str, Tuple[float, float]]) -> Tuple[float, float]:
    return anchors.get(name, anchors.get("origin", (0.0, 0.0)))


def _stack_offset(axis: str, index: int) -> Tuple[float, float]:
    if index <= 0:
        return (0.0, 0.0)
    step = STACK_STEP_GRIDS * GRID_MM * index
    if axis == "x":
        return (step, 0.0)
    return (0.0, step)


def _apply_base_offset(
    placements: Dict[str, PlacedComponent],
    base_offset: Tuple[float, float],
) -> Dict[str, PlacedComponent]:
    if base_offset == (0.0, 0.0):
        return placements
    dx, dy = base_offset
    return {ref: _move_component(comp, dx, dy) for ref, comp in placements.items()}


def _resolve_overlaps(
    placements: Dict[str, PlacedComponent],
    role_axis: Dict[str, str],
    role_by_ref: Dict[str, str],
    fixed_refs: set[str],
) -> Dict[str, PlacedComponent]:
    refs = list(placements.keys())
    for _ in range(30):
        moved = False
        for i, ref_a in enumerate(refs):
            for ref_b in refs[i + 1:]:
                comp_a = placements[ref_a]
                comp_b = placements[ref_b]
                if not _overlaps(comp_a, comp_b):
                    continue
                mover_ref = ref_b if ref_b not in fixed_refs else ref_a
                if mover_ref in fixed_refs:
                    continue
                axis = role_axis.get(role_by_ref.get(mover_ref, ""), "y")
                shift = STACK_STEP_GRIDS * GRID_MM
                dx, dy = (shift, 0.0) if axis == "x" else (0.0, shift)
                placements[mover_ref] = _move_component(placements[mover_ref], dx, dy)
                moved = True
        if not moved:
            break
    return placements


def _move_component(component: PlacedComponent, dx: float, dy: float) -> PlacedComponent:
    x = component.x_mm + dx
    y = component.y_mm + dy
    pins = resolve_pins(component.comp_type, component.rotation)
    abs_pins = {name: (x + ox, y + oy) for name, (ox, oy) in pins.items()}
    return PlacedComponent(
        ref=component.ref,
        comp_type=component.comp_type,
        x_mm=x,
        y_mm=y,
        rotation=component.rotation,
        pins=abs_pins,
    )


def _overlaps(a: PlacedComponent, b: PlacedComponent) -> bool:
    a_min_x, a_max_x, a_min_y, a_max_y = _bounds(a)
    b_min_x, b_max_x, b_min_y, b_max_y = _bounds(b)
    return not (
        a_max_x <= b_min_x
        or a_min_x >= b_max_x
        or a_max_y <= b_min_y
        or a_min_y >= b_max_y
    )


def _bounds(component: PlacedComponent) -> Tuple[float, float, float, float]:
    width, height = _component_size(component.comp_type, component.rotation)
    half_w = width / 2.0
    half_h = height / 2.0
    return (
        component.x_mm - half_w,
        component.x_mm + half_w,
        component.y_mm - half_h,
        component.y_mm + half_h,
    )


def _component_size(comp_type: str, rotation: int) -> Tuple[float, float]:
    comp = comp_type.lower()
    if comp in {"opamp_ic"}:
        return (6.0 * GRID_MM, 6.0 * GRID_MM)
    if _is_active(comp):
        return (4.0 * GRID_MM, 4.0 * GRID_MM)
    if comp in PASSIVE_TYPES:
        if rotation % 180 == 0:
            return (2.0 * GRID_MM, 4.0 * GRID_MM)
        return (4.0 * GRID_MM, 2.0 * GRID_MM)
    return (2.0 * GRID_MM, 2.0 * GRID_MM)


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


__all__ = [
    "GRID_MM",
    "ComponentSpec",
    "PlacedComponent",
    "PlacementResult",
    "solve_stage",
]
