# .\\thesis\\electronic-chatbot\\apps\\api\\app\\infrastructure\\exporters\\kicad_sch_exporter.py
"""Công cụ xuất sơ đồ mạch KiCad (.kicad_sch).

Module này cung cấp triển khai cụ thể của ExporterPort cho định dạng KiCad
.kicad_sch. Nó điều phối layout planning + schematic serialization để
tạo ra file .kicad_sch hoàn chỉnh.
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# typing: Type hints cho IDE support
# datetime: Timestamp metadata cho schematic files
from dataclasses import dataclass
from types import SimpleNamespace
import math
from typing import Dict, Any, List, Tuple
from datetime import datetime

# ====== Domain & Application layers ======
from app.domains.circuits.entities import Circuit, Component, ComponentType, ParameterValue
from app.domains.circuits.ir import CircuitIR, CircuitIRSerializer
from app.domains.circuits.placement import LayoutQualityEvaluator, LayoutQualityReport
from app.application.circuits.ports import ExporterPort
from app.application.circuits.dtos import ExportFormat
from app.application.circuits.errors import ExportError

# ====== Infrastructure - Layout & Serialization ======
from app.infrastructure.exporters.layout_planner import LayoutPlanner
from app.infrastructure.exporters.kicad_sch_serializer import KiCadSchSerializer
from app.infrastructure.exporters.placement import GRID_MM, classify, compose, solve_stage
from app.infrastructure.exporters.placement.orthogonal_router import route_net, route_pair
from app.infrastructure.exporters.placement.pin_resolver import get_pin_coordinate, pin_offset_for_instance
from app.infrastructure.exporters.placement.role_inferrer import infer_roles
from app.infrastructure.exporters.graphviz_schematic_layout import (
    center_placements_mm,
    layout_schematic_with_pygraphviz,
)
from app.infrastructure.exporters.connectivity_validator import (
    ConnectivityReport,
    run_connectivity_validation,
)
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Junction detection helpers (module-level so both class copies can share)
# ---------------------------------------------------------------------------

def _pt_on_orthogonal_segment(
    pt: Tuple[float, float],
    a: Tuple[float, float],
    b: Tuple[float, float],
) -> bool:
    """Return True iff *pt* lies STRICTLY between endpoints *a* and *b*
    on an axis-aligned (orthogonal) wire segment.
    """
    px, py = pt
    ax, ay = a
    bx, by = b
    if ax == bx == px:          # vertical segment
        lo, hi = (min(ay, by), max(ay, by))
        return lo < py < hi
    if ay == by == py:          # horizontal segment
        lo, hi = (min(ax, bx), max(ax, bx))
        return lo < px < hi
    return False


def _find_junctions_from_wires(wires: list, forced: set | None = None) -> set:
    """Detect KiCad junction points from a list of routed wire dicts.

    Algorithm
    ---------
    Route_pair produces L-shaped polylines [P1, corner, P2].  When two
    separate polylines share the same corner or when a wire endpoint lands
    on the interior of another wire, the naive "count all points ≥ 3"
    approach misses junctions because corners appear at most once per
    polyline.

    Fix: first *decompose* every polyline into individual 2-point segments,
    then count segment **endpoints** only.  Any grid point touched by 3 or
    more segment endpoints is a T/X junction and needs a KiCad junction dot.
    Additionally, any segment endpoint that falls strictly *inside* another
    segment (not at its endpoints) is a T-junction and also needs a dot.
    """
    # Step 1 – decompose polylines into individual straight 2-pt segments
    segments: list[tuple[tuple, tuple]] = []
    for wire in wires:
        pts = wire.get("points", [])
        for i in range(len(pts) - 1):
            a = (round(pts[i][0], 6), round(pts[i][1], 6))
            b = (round(pts[i + 1][0], 6), round(pts[i + 1][1], 6))
            if a != b:
                segments.append((a, b))

    # Step 2 – count how many segment endpoints touch each grid point
    ep_count: dict[tuple, int] = {}
    for a, b in segments:
        ep_count[a] = ep_count.get(a, 0) + 1
        ep_count[b] = ep_count.get(b, 0) + 1

    junctions: set[tuple] = set()

    # Rule 1 – 3+ segment endpoints → fan-out junction or X-crossing
    for pt, cnt in ep_count.items():
        if cnt >= 3:
            junctions.add(pt)

    # Rule 2 – endpoint strictly inside another segment → T-junction
    all_eps = list(ep_count.keys())
    for ep in all_eps:
        if ep in junctions:
            continue  # already flagged
        for a, b in segments:
            if ep in (a, b):
                continue
            if _pt_on_orthogonal_segment(ep, a, b):
                junctions.add(ep)
                break

    # Merge any hub points forced by the caller (hub-and-spoke centroids where
    # only 2 wires meet because one net-pin IS at the hub coordinate).
    if forced:
        junctions.update(forced)

    return junctions


class KiCadSchExporter(ExporterPort):
    """Exporter for KiCad schematic (.kicad_sch) format.
    
    This implementation orchestrates:
    1. Converting Circuit entity to CircuitIR
    2. Planning component layout and wire routing (LayoutPlanner)
    3. Serializing to KiCad s-expression format (KiCadSchSerializer)
    """
    
    def __init__(self):
        """Initialize exporter with layout planner and serializer."""
        self.layout_planner = LayoutPlanner()
        self.serializer = KiCadSchSerializer()
        self.quality_evaluator = LayoutQualityEvaluator()
        self._last_layout_quality_report: LayoutQualityReport | None = None
        self._last_connectivity_report: ConnectivityReport | None = None
        self._last_placements: Dict[str, Tuple[float, float]] = {}
        self._last_rotations: Dict[str, int] = {}
        self._last_export_metadata: Dict[str, Any] = {}
        self._placement_done = False
        self._finalize_done = False

    def get_last_placements(self) -> Dict[str, Tuple[float, float]]:
        return dict(self._last_placements)

    def get_last_export_metadata(self) -> Dict[str, Any]:
        return dict(self._last_export_metadata)

    def export_schematic_sync(
        self,
        circuit: Circuit,
        *,
        placement_mode: str = "auto",
    ) -> str:
        """Placement + orthogonal routing → .kicad_sch.

        placement_mode:
          - auto: pygraphviz (dot) when available, else coordinate_solver (AGR)
          - pygraphviz: require Graphviz layout, fallback to AGR
          - coordinate_solver: AGR solve_stage only
        """
        cid = getattr(circuit, "id", None)
        if not cid or str(cid).strip() == "None":
            raise ExportError(
                format_type=ExportFormat.KICAD.value,
                reason="Exporter requires valid circuit.id (got None or empty).",
            )

        try:
            comp_count = len(getattr(circuit, "components", {}))
            net_count = len(getattr(circuit, "nets", {}))
            logger.info(
                "[SCH DEBUG] Generating SCH for circuit_id=%s, components=%s, nets=%s",
                cid,
                comp_count,
                net_count,
            )
            self._last_layout_quality_report = None
            self._placement_done = False
            self._finalize_done = False

            if not getattr(circuit, "components", None) or not getattr(circuit, "nets", None):
                raise ExportError(
                    format_type=ExportFormat.KICAD.value,
                    reason=f"Empty circuit: components={comp_count}, nets={net_count}",
                )

            mode = str(placement_mode or "auto").strip().lower()
            placement_source = "coordinate_solver"
            gv = None
            if mode in {"auto", "pygraphviz"}:
                gv = layout_schematic_with_pygraphviz(circuit)
            if gv is not None:
                placements, rotations = gv
                placement_source = "pygraphviz"
                logger.info("[SCH DEBUG] Placement source=pygraphviz (dot)")
            else:
                placements, rotations, _agr_pins = self._agr_place_components(circuit)
                placement_source = "coordinate_solver"
                logger.info("[SCH DEBUG] Placement source=coordinate_solver (AGR)")

            placements = self._snap_placements(placements, GRID_MM)
            placements = self._normalize_origin(placements, GRID_MM * 4.0)
            placements = center_placements_mm(placements)
            placements = self._snap_placements(placements, GRID_MM)

            pin_positions = self._rebuild_pin_positions(circuit, placements, rotations, {})
            wires, forced_junctions = self._route_wires(circuit, pin_positions)
            wires = self._snap_wires(wires, GRID_MM)
            wires = self._filter_short_wires(wires, GRID_MM)

            circuit, placements, rotations, pin_positions, wires = self._ensure_power_flags(
                circuit,
                placements,
                rotations,
                pin_positions,
                wires,
            )
            wires = self._snap_wires(wires, GRID_MM)
            wires = self._filter_short_wires(wires, GRID_MM)

            self._last_connectivity_report = run_connectivity_validation(
                circuit,
                placements,
                rotations,
                pin_positions,
                wires,
                emit_debug_log=logger.isEnabledFor(logging.DEBUG),
            )

            self._last_layout_quality_report = self._evaluate_layout_quality_agr(
                circuit,
                placements,
                wires,
            )

            junctions = _find_junctions_from_wires(wires, forced=forced_junctions)
            junction_count = len(junctions)
            wire_count = len(wires)

            self._last_placements = {
                str(k).strip().upper(): (float(v[0]), float(v[1])) for k, v in placements.items()
            }
            self._last_rotations = dict(rotations)
            self._last_export_metadata = {
                "wires": wire_count,
                "junctions": junction_count,
                "placement_source": placement_source,
            }

            ir = CircuitIR(
                circuit=circuit,
                _meta={
                    "version": "1.0",
                    "schema_version": "1.0",
                    "circuit_name": circuit.name or "unnamed",
                    "timestamp": datetime.now().isoformat(),
                    "generator": "elpis",
                },
                _intent_snapshot={},
            )
            return self.serializer.serialize(ir, placements, wires, junctions, rotations)

        except ExportError:
            raise
        except Exception as exc:
            raise ExportError(
                format_type=ExportFormat.KICAD.value,
                reason=f"KiCad export failed: {exc}",
            ) from exc
    
    async def export(
        self,
        circuit: Circuit,
        format_type: ExportFormat
    ) -> str:
        """Export circuit to KiCad schematic format.
        
        Args:
            circuit: Circuit entity to export
            format_type: Must be KICAD_SCH
            
        Returns:
            KiCad .kicad_sch file content as string
            
        Raises:
            ExportError: If export fails or format not supported
        """
        if format_type != ExportFormat.KICAD:
            raise ExportError(
                format_type=format_type.value,
                reason=f"This exporter only supports {ExportFormat.KICAD.value}"
            )
        
        # HARD GUARD: Reject export if circuit.id is None (prevents stray post-response invocations)
        cid = getattr(circuit, "id", None)
        if not cid or str(cid).strip() == "None":
            raise ExportError(
                format_type=format_type.value,
                reason="Exporter requires valid circuit.id (got None or empty). This is likely a stray background invocation without proper context."
            )
        
        try:
            return self.export_schematic_sync(circuit)
        except ExportError:
            raise
        except Exception as exc:
            raise ExportError(
                format_type=format_type.value,
                reason=f"KiCad export failed: {exc}",
            ) from exc

    def _agr_place_components(
        self,
        circuit: Circuit,
    ) -> Tuple[Dict[str, tuple], Dict[str, int], Dict[Tuple[str, str], Tuple[float, float]]]:
        components = list(circuit.components.values())
        placement_components = self._build_agr_components(components)
        stage_count = self._infer_stage_count(placement_components)
        topology_label = self._infer_topology_label(circuit)

        if stage_count > 1:
            stages = [
                SimpleNamespace(id=f"S{idx + 1}", topology=topology_label)
                for idx in range(stage_count)
            ]
            ir_stub = SimpleNamespace(
                components=placement_components,
                architecture=SimpleNamespace(stage_count=stage_count, stages=stages),
            )
            result = compose(ir_stub)
        else:
            ir_stub = SimpleNamespace(
                components=placement_components,
                architecture=SimpleNamespace(stage_count=stage_count, stages=[]),
                analysis=SimpleNamespace(topology_classification=topology_label),
            )
            family = classify(ir_stub)
            result = solve_stage(placement_components, family, topology=topology_label)

        placements = {ref: (comp.x_mm, comp.y_mm) for ref, comp in result.components.items()}
        rotations = {ref: int(comp.rotation) for ref, comp in result.components.items()}
        pin_positions = {
            (ref, pin_name): pos
            for ref, comp in result.components.items()
            for pin_name, pos in comp.pins.items()
        }
        return placements, rotations, pin_positions

    def _build_agr_components(self, components: List[Component]) -> List[_AGRComponent]:
        role_hints = []
        for comp in components:
            role_hints.append(
                SimpleNamespace(
                    ref=comp.id,
                    type=comp.type.value,
                    role=self._render_style_role(comp),
                )
            )
        inferred = infer_roles(role_hints)

        specs: List[_AGRComponent] = []
        for comp in components:
            stage = self._render_style_stage(comp)
            role = self._render_style_role(comp) or inferred.get(comp.id, "auxiliary")
            specs.append(
                _AGRComponent(
                    ref=comp.id,
                    type=comp.type.value,
                    role=str(role).strip().lower(),
                    topology_stage=stage,
                )
            )
        return specs

    def _infer_stage_count(self, components: List[_AGRComponent]) -> int:
        stages = [comp.topology_stage for comp in components if comp.topology_stage is not None]
        if not stages:
            return 1
        return max(stages) + 1

    def _infer_topology_label(self, circuit: Circuit) -> str:
        label = str(circuit.topology_type or circuit.category or "").strip().lower()
        if label:
            return label
        if circuit.signal_flow is not None:
            return "multi_stage"
        return ""

    def _render_style_role(self, component: Component) -> str | None:
        render_style = getattr(component, "render_style", None) or {}
        role = render_style.get("role") or render_style.get("component_role")
        if role is None:
            return None
        return str(role).strip()

    def _render_style_stage(self, component: Component) -> int | None:
        stage_raw = component.stage
        render_style = getattr(component, "render_style", None) or {}
        if stage_raw is None:
            stage_raw = render_style.get("stage") or render_style.get("component_stage")
        if stage_raw is None:
            return None
        try:
            return int(stage_raw)
        except (TypeError, ValueError):
            return None

    def _rebuild_pin_positions(
        self,
        circuit: Circuit,
        placements: Dict[str, tuple],
        rotations: Dict[str, int],
        existing: Dict[Tuple[str, str], Tuple[float, float]],
    ) -> Dict[Tuple[str, str], Tuple[float, float]]:
        """Compute absolute pin connection-point coordinates for every pin in the circuit.

        Uses ``get_pin_coordinate`` (the canonical pin-offset function) so that
        wire endpoints always land on the symbol's physical connection dot — never
        on the component centre.  Each result is derived from the FINAL on-grid
        component placement, so the caller must ensure placements are grid-snapped
        before calling this method.
        """
        pin_positions: Dict[Tuple[str, str], Tuple[float, float]] = dict(existing)

        def _place_pin(comp_id: str, ctype: str, pin_name: str) -> None:
            key = (comp_id, pin_name)
            if key in pin_positions:
                return
            cx, cy = placements.get(comp_id, (0.0, 0.0))
            rot = int(rotations.get(comp_id, 0))
            pin_positions[key] = get_pin_coordinate(cx, cy, ctype, str(pin_name), rot)

        for comp_id, component in circuit.components.items():
            ctype_val = str(getattr(component.type, "value", component.type))
            for pin_name in component.pins:
                _place_pin(comp_id, ctype_val, str(pin_name))

        # Nets may reference pins not listed on ``component.pins`` (e.g. alternate
        # spellings from SPICE netlist) — resolve those too so no wire is orphaned.
        for net in circuit.nets.values():
            for pref in net.connected_pins:
                comp = circuit.components.get(pref.component_id)
                if comp is None:
                    continue
                ctype_val = str(getattr(comp.type, "value", comp.type))
                _place_pin(pref.component_id, ctype_val, str(pref.pin_name))

        return pin_positions

    def _route_wires(
        self,
        circuit: Circuit,
        pin_positions: Dict[Tuple[str, str], Tuple[float, float]],
    ) -> tuple[list, set]:
        """Route all nets and return (wires, forced_junctions).

        Strategy
        --------
        * 2-pin net  → direct L-wire via ``route_pair``.
        * 3+ pin net → hub-and-spoke: every pin connects to the net centroid
          (snapped to KiCad grid).  All wire endpoints converge at the hub,
          guaranteeing ≥3 endpoint occurrences there so ``_find_junctions``
          always detects the junction correctly.  The hub coordinate is added
          to ``forced_junctions`` to handle the edge case where the centroid
          coincides with an existing pin (endpoint count = 2, not 3).
        """
        wires: list = []
        forced_junctions: set = set()

        for net in circuit.nets.values():
            points: List[Tuple[float, float]] = []
            for pin in net.connected_pins:
                pos = pin_positions.get((pin.component_id, pin.pin_name))
                if pos is not None:
                    points.append(pos)

            points = self._unique_points(points)
            if len(points) < 2:
                continue

            if len(points) == 2:
                wire = route_pair(points[0], points[1], grid_mm=GRID_MM)
                wires.append({"points": wire.points})
                continue

            # 3+ pins: hub-and-spoke topology
            cx = sum(p[0] for p in points) / len(points)
            cy = sum(p[1] for p in points) / len(points)
            hub = (round(cx / GRID_MM) * GRID_MM, round(cy / GRID_MM) * GRID_MM)

            for pt in points:
                if abs(pt[0] - hub[0]) < 1e-6 and abs(pt[1] - hub[1]) < 1e-6:
                    # Pin already sits at hub; mark hub as forced junction so
                    # the junction dot is placed even when only 2 other wires
                    # converge here (endpoint count would be 2, not 3).
                    forced_junctions.add(hub)
                    continue
                wire = route_pair(pt, hub, grid_mm=GRID_MM)
                wires.append({"points": wire.points})

            # Always mark hub as forced junction for nets with 3+ pins.
            forced_junctions.add(hub)

        return wires, forced_junctions

    def _unique_points(self, points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        unique: List[Tuple[float, float]] = []
        seen: set[Tuple[float, float]] = set()
        for point in points:
            key = (round(point[0], 6), round(point[1], 6))
            if key in seen:
                continue
            seen.add(key)
            unique.append(point)
        return unique

    def _snap_placements(self, placements: Dict[str, tuple], grid: float) -> Dict[str, tuple]:
        return {cid: self._snap_point(pos, grid) for cid, pos in placements.items()}

    def _normalize_origin(self, placements: Dict[str, tuple], margin: float) -> Dict[str, tuple]:
        if not placements:
            return placements
        xs = [pos[0] for pos in placements.values()]
        ys = [pos[1] for pos in placements.values()]
        min_x = min(xs)
        min_y = min(ys)
        dx = margin - min_x if min_x < margin else 0.0
        dy = margin - min_y if min_y < margin else 0.0
        if dx == 0.0 and dy == 0.0:
            return placements
        return {cid: (pos[0] + dx, pos[1] + dy) for cid, pos in placements.items()}

    def _snap_wires(self, wires: list, grid: float) -> list:
        snapped = []
        for wire in wires:
            points = [self._snap_point(p, grid) for p in wire.get("points", [])]
            if len(points) >= 2:
                snapped.append({"points": points})
        return snapped

    def _filter_short_wires(self, wires: list, min_len: float) -> list:
        filtered: list = []
        for wire in wires:
            points = wire.get("points", [])
            if len(points) < 2:
                continue
            compact: List[Tuple[float, float]] = [points[0]]
            for point in points[1:]:
                if self._segment_length(compact[-1], point) + 1e-6 >= min_len:
                    compact.append(point)
            if len(compact) >= 2:
                filtered.append({"points": compact})
        return filtered

    def _find_junctions(self, wires: list) -> set:
        return _find_junctions_from_wires(wires)

    def _ensure_power_flags(
        self,
        circuit: Circuit,
        placements: Dict[str, tuple],
        rotations: Dict[str, int],
        pin_positions: Dict[Tuple[str, str], Tuple[float, float]],
        wires: list,
    ) -> Tuple[Circuit, Dict[str, tuple], Dict[str, int], Dict[Tuple[str, str], Tuple[float, float]], list]:
        power_nets = self._collect_power_nets(circuit, pin_positions)
        if not power_nets:
            return circuit, placements, rotations, pin_positions, wires

        extra_components: Dict[str, Component] = {}
        for net_name, anchor in power_nets.items():
            comp_id = f"PWR_FLAG_{net_name}"
            if comp_id in circuit.components:
                continue
            component = Component(
                id=comp_id,
                type=ComponentType.POWER_SYMBOL,
                pins=("1",),
                parameters={"value": ParameterValue("PWR_FLAG", None)},
                library_id="power",
                symbol_name="PWR_FLAG",
            )
            extra_components[comp_id] = component

            # Place PWR_FLAG 8 grid units right and 3 grid units above the
            # anchor so it doesn't collide with the power-rail text or symbol.
            flag_pos = (anchor[0] + (GRID_MM * 8.0), anchor[1] - (GRID_MM * 3.0))
            placements[comp_id] = self._snap_point(flag_pos, GRID_MM)
            rotations[comp_id] = 0
            pin_positions[(comp_id, "1")] = placements[comp_id]
            wire = route_pair(anchor, placements[comp_id], grid_mm=GRID_MM)
            wires.append({"points": wire.points})

        if not extra_components:
            return circuit, placements, rotations, pin_positions, wires

        new_components = dict(circuit.components)
        new_components.update(extra_components)
        new_circuit = Circuit(
            name=circuit.name,
            id=circuit.id,
            _components=new_components,
            _nets=dict(circuit.nets),
            _ports=dict(circuit.ports),
            _constraints=dict(circuit.constraints),
            topology_type=circuit.topology_type,
            category=circuit.category,
            template_id=circuit.template_id,
            tags=circuit.tags,
            description=circuit.description,
            parametric=dict(circuit.parametric) if circuit.parametric else None,
            pcb_hints=dict(circuit.pcb_hints) if circuit.pcb_hints else None,
            signal_flow=circuit.signal_flow,
        )
        return new_circuit, placements, rotations, pin_positions, wires

    def _collect_power_nets(
        self,
        circuit: Circuit,
        pin_positions: Dict[Tuple[str, str], Tuple[float, float]],
    ) -> Dict[str, Tuple[float, float]]:
        power_nets: Dict[str, Tuple[float, float]] = {}
        for net in circuit.nets.values():
            name = str(net.name or "").strip()
            if not name:
                continue
            lower = name.lower()
            if lower in {"0", "gnd", "ground", "vss"}:
                key = "GND"
            elif any(tok in lower for tok in ("vcc", "vdd", "v+", "power")):
                key = "VCC"
            else:
                continue

            anchor = None
            for pin in net.connected_pins:
                anchor = pin_positions.get((pin.component_id, pin.pin_name))
                if anchor is not None:
                    break
            if anchor is None:
                continue
            power_nets[key] = power_nets.get(key) or anchor
        return power_nets

    def _evaluate_layout_quality_agr(
        self,
        circuit: Circuit,
        placements: Dict[str, tuple],
        wires: list,
    ) -> LayoutQualityReport | None:
        try:
            report = self.quality_evaluator.evaluate(
                {
                    "circuit": circuit,
                    "placements": placements,
                    "wires": wires,
                }
            )
        except Exception:
            return None
        if isinstance(report, LayoutQualityReport):
            return report
        if hasattr(report, "to_dict"):
            return LayoutQualityReport(**report.to_dict())
        return None

    def _snap_point(self, point: Tuple[float, float], grid: float) -> Tuple[float, float]:
        x, y = point
        return (
            round(x / grid) * grid,
            round(y / grid) * grid,
        )

    def _segment_length(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        dx = abs(p2[0] - p1[0])
        dy = abs(p2[1] - p1[1])
        return max(dx, dy)


@dataclass(frozen=True)
class _AGRComponent:
    ref: str
    type: str
    role: str
    topology_stage: int | None

    def get_last_layout_quality_report(self) -> Dict[str, Any] | None:
        if self._last_layout_quality_report is None:
            return None
        return self._last_layout_quality_report.to_dict()

    def _create_ir(self, circuit: Circuit) -> CircuitIR:
        meta = {
            "version": "1.0",
            "schema_version": "1.0",
            "circuit_name": circuit.name or "unnamed",
            "timestamp": datetime.now().isoformat(),
            "generator": "elpis",
        }

        return CircuitIR(
            circuit=circuit,
            _meta=meta,
            _intent_snapshot={},
        )

    def _finalize_layout_and_validate(
        self,
        circuit: Circuit,
        pin_offsets: Dict[str, list],
        placements: Dict[str, tuple],
        rotations: Dict[str, int],
    ) -> Tuple[Dict[str, tuple], list, Dict[str, int]]:
        """Auto-fix pass: snap to grid, resolve overlaps, reroute, and validate connectivity."""
        if self._finalize_done:
            raise RuntimeError("_finalize_layout_and_validate() called more than once in one export run")
        self._finalize_done = True

        fixed_placements = self.layout_planner._snap_placements_to_grid(
            placements,
            self.layout_planner.grid_snap,
        )
        fixed_placements = self.layout_planner._resolve_component_overlaps(
            fixed_placements,
            self.layout_planner.min_component_spacing,
        )
        fixed_placements = self.layout_planner._fit_placements_to_sheet(fixed_placements, is_opamp=False)
        fixed_placements = self.layout_planner._snap_placements_to_grid(
            fixed_placements,
            self.layout_planner.grid_snap,
        )

        fixed_rotations = dict(rotations)
        fixed_wires = self._plan_wires(circuit, fixed_placements, pin_offsets, fixed_rotations)
        fixed_quality = self._evaluate_layout_quality(
            circuit,
            fixed_placements,
            fixed_wires,
            pin_offsets,
            fixed_rotations,
        )

        if (
            self._validate_pin_net_consistency(circuit, fixed_placements, pin_offsets, fixed_rotations)
            and fixed_quality.is_hard_valid
        ):
            return fixed_placements, fixed_wires, fixed_rotations

        # Fallback attempt: keep placements but reset rotations to defaults and reroute.
        fallback_rotations = {comp_id: 0 for comp_id in circuit.components.keys()}
        fallback_wires = self._plan_wires(circuit, fixed_placements, pin_offsets, fallback_rotations)
        fallback_quality = self._evaluate_layout_quality(
            circuit,
            fixed_placements,
            fallback_wires,
            pin_offsets,
            fallback_rotations,
        )
        if (
            self._validate_pin_net_consistency(circuit, fixed_placements, pin_offsets, fallback_rotations)
            and fallback_quality.is_hard_valid
        ):
            return fixed_placements, fallback_wires, fallback_rotations

        raise RuntimeError(
            "Layout auto-fix failed: hard constraints not satisfied "
            f"(overlap={fallback_quality.component_overlap_count}, "
            f"center_attach={fallback_quality.center_attachment_count})"
        )

    def _validate_pin_net_consistency(
        self,
        circuit: Circuit,
        placements: Dict[str, tuple],
        pin_offsets: Dict[str, list],
        rotations: Dict[str, int],
    ) -> bool:
        """Check that all original net pins remain resolvable after placement/rotation."""
        for net in circuit.nets.values():
            if len(net.connected_pins) < 2:
                continue
            for pin in net.connected_pins:
                pos = self.layout_planner.get_pin_position(
                    pin,
                    placements,
                    circuit,
                    pin_offsets,
                    rotations,
                )
                if pos is None:
                    return False
        return True

    def _topology_aware_placement(self, circuit) -> dict:
        if self._placement_done:
            raise RuntimeError("_topology_aware_placement() called more than once in one export run")
        self._placement_done = True

        PLACEMENT_MAP = {
            # Left→right signal; vertical rail VCC→Q→GND (mm-ish coordinates, centered later).
            "VCC":  (148, 22, 0),
            "RC":   (148, 46, 90),
            "Q1":   (148, 82, 0),
            "RE1":  (148, 114, 90),
            "RE2":  (148, 134, 90),
            "GND":  (148, 172, 0),
            "R1":   (102, 52, 90),
            "R2":   (102, 118, 90),
            "CE":   (188, 122, 0),
            "CIN":  (62, 82, 0),
            "C1":   (62, 82, 0),
            "COUT": (218, 82, 0),
            "C2":   (218, 82, 0),
            "IN":   (28, 82, 0),
            "OUT":  (252, 82, 0),
        }
        result = {}
        grid_x, grid_y, col = 250, 50, 0
        # circuit.components is usually a dict: {comp_id: comp_object}
        components = circuit.components
        items = components.items() if isinstance(components, dict) else [
            (c.id if hasattr(c, 'id') else c, c)
            for c in components
        ]

        def _norm(s: str) -> str:
            return s.replace("_", "").replace("-", "")

        for comp_id, comp in items:
            key = comp_id.upper()
            norm_key = _norm(key)
            if key in PLACEMENT_MAP:
                result[comp_id] = PLACEMENT_MAP[key]
            elif norm_key in PLACEMENT_MAP:
                # Handles IR-generated names like C_IN→CIN, C_OUT→COUT, C_E→CE
                result[comp_id] = PLACEMENT_MAP[norm_key]
            else:
                result[comp_id] = (grid_x + col * 40, grid_y, 90)
                col += 1
                if col > 3:
                    col = 0
                    grid_y += 50
        return result

    def _auto_relax_layout(
        self,
        circuit: Circuit,
        pin_offsets: Dict[str, list],
    ) -> Tuple[Dict[str, tuple], list, Dict[str, int]]:
        """Iteratively expand spacing and reroute to reduce crossings and improve readability.
        
        First attempts topology-aware placement for Common Emitter-like circuits;
        falls back to grid-based layout planner if needed.
        """
        # Try topology-aware placement first (for CE amplifier and similar circuits)
        topology_placements = self._topology_aware_placement(circuit)
        if topology_placements:
            logger.info("[SCH DEBUG] Using topology-aware placement")
            # topology_placements: dict[comp_id] -> (x, y, rot)
            placements = {cid: (float(x), float(y)) for cid, (x, y, rot) in topology_placements.items()}
            rotations = {cid: int(rot) for cid, (x, y, rot) in topology_placements.items()}
            wires = self._plan_wires(circuit, placements, pin_offsets, rotations)
            quality = self._evaluate_layout_quality(circuit, placements, wires, pin_offsets, rotations)

            if quality.is_hard_valid:
                return placements, wires, rotations
            # If topology placement has issues, continue to relaxation loop fallback
        
        # Fallback: iteratively expand spacing and reroute
        scales = [1.0, 1.15, 1.3, 1.45, 1.6]

        best_placements: Dict[str, tuple] = {}
        best_wires: list = []
        best_rotations: Dict[str, int] = {}
        best_score: float | None = None
        best_quality: LayoutQualityReport | None = None

        for idx, scale in enumerate(scales):
            placements = self.layout_planner.place_components(circuit, spacing_scale=scale)
            # Detect pathological placement results (empty or very large coords) and
            # fallback to a simple deterministic grid placement to avoid overlaps.
            try:
                if not placements or any(abs(x) > 1000 or abs(y) > 1000 for x, y in placements.values()):
                    logger.info("LayoutPlanner returned invalid placements, using simple grid placement fallback")
                    placements = self._simple_grid_placement(circuit)
            except Exception:
                placements = self._simple_grid_placement(circuit)
            rotations = self.layout_planner.infer_component_rotations(circuit, placements)
            wires = self._plan_wires(circuit, placements, pin_offsets, rotations)

            quality = self._evaluate_layout_quality(
                circuit,
                placements,
                wires,
                pin_offsets,
                rotations,
            )
            score = quality.objective

            if best_score is None or score < best_score:
                best_score = score
                best_quality = quality
                best_placements = placements
                best_wires = wires
                best_rotations = rotations

            # Early stop: no crossings, low bends and sufficiently readable spacing.
            if (
                quality.is_hard_valid
                and quality.wire_crossing_count == 0
                and quality.wire_label_overlap_count == 0
                and idx > 0
            ):
                break

        if best_quality is not None and not best_quality.is_hard_valid:
            # Keep best candidate even if not perfect; finalize pass will attempt recovery.
            pass

        return best_placements, best_wires, best_rotations

    def _simple_grid_placement(self, circuit: Circuit) -> Dict[str, tuple]:
        """Place components on a simple grid to avoid overlaps.

        - spacing: 150mm
        - start: x=100, y=100
        - 4 columns per row
        Power symbols (voltage_source, power_symbol, ground) will be placed
        near the first non-power component found on their nets when possible.
        """
        from app.domains.circuits.entities import ComponentType

        spacing = 150.0
        start_x = 100.0
        start_y = 100.0
        cols = 4

        placements: Dict[str, tuple] = {}
        power_candidates: Dict[str, object] = {}

        # First place non-power components in grid order
        col = 0
        row = 0
        for comp_id, comp in circuit.components.items():
            ctype = getattr(comp, 'type', None)
            is_power = False
            try:
                is_power = (ctype == ComponentType.POWER_SYMBOL or ctype == ComponentType.VOLTAGE_SOURCE or ctype == ComponentType.GROUND)
            except Exception:
                is_power = False

            if is_power:
                power_candidates[comp_id] = comp
                continue

            x = start_x + col * spacing
            y = start_y + row * spacing
            placements[comp_id] = (float(x), float(y))
            col += 1
            if col >= cols:
                col = 0
                row += 1

        # Place power symbols near connected components when possible
        for power_id, power_comp in power_candidates.items():
            # find nets that include this power component
            near_pos = None
            for net in circuit.nets.values():
                for ref in net.connected_pins:
                    if ref.component_id == power_id:
                        # find another component on this net
                        for other_ref in net.connected_pins:
                            if other_ref.component_id != power_id and other_ref.component_id in placements:
                                ox, oy = placements[other_ref.component_id]
                                near_pos = (ox - 30.0, oy)
                                break
                        if near_pos is not None:
                            break
                if near_pos is not None:
                    break

            if near_pos is None:
                # place at next grid slot
                x = start_x + col * spacing
                y = start_y + row * spacing
                placements[power_id] = (float(x), float(y))
                col += 1
                if col >= cols:
                    col = 0
                    row += 1
            else:
                placements[power_id] = (float(near_pos[0]), float(near_pos[1]))

        return placements

    def _evaluate_layout_quality(
        self,
        circuit: Circuit,
        placements: Dict[str, tuple],
        wires: list,
        pin_offsets: Dict[str, list],
        rotations: Dict[str, int],
    ) -> LayoutQualityReport:
        pin_positions = self._build_pin_position_map(
            circuit,
            placements,
            pin_offsets,
            rotations,
        )
        label_positions = self._build_default_label_positions(circuit)

        # Backward/forward compatibility: some evaluator versions expose
        # evaluate_schematic(...), newer simplified ones only expose evaluate(...).
        if hasattr(self.quality_evaluator, "evaluate_schematic"):
            return self.quality_evaluator.evaluate_schematic(
                circuit=circuit,
                placements=placements,
                wires=wires,
                pin_positions=pin_positions,
                label_positions=label_positions,
                min_component_spacing=self.layout_planner.min_component_spacing,
            )

        report = self.quality_evaluator.evaluate(
            {
                "circuit": circuit,
                "placements": placements,
                "wires": wires,
                "pin_positions": pin_positions,
                "label_positions": label_positions,
                "min_component_spacing": self.layout_planner.min_component_spacing,
            }
        )

        # Provide legacy attributes expected by exporter logic.
        if not hasattr(report, "objective"):
            overall = float(getattr(report, "overall_score", 0.8) or 0.8)
            report.objective = max(0.0, 1.0 - overall)
        if not hasattr(report, "is_hard_valid"):
            report.is_hard_valid = True
        if not hasattr(report, "wire_crossing_count"):
            report.wire_crossing_count = 0
        if not hasattr(report, "wire_label_overlap_count"):
            report.wire_label_overlap_count = 0

        return report

    def _build_pin_position_map(
        self,
        circuit: Circuit,
        placements: Dict[str, tuple],
        pin_offsets: Dict[str, list],
        rotations: Dict[str, int],
    ) -> Dict[Tuple[str, str], Tuple[float, float]]:
        pin_positions: Dict[Tuple[str, str], Tuple[float, float]] = {}
        for net in circuit.nets.values():
            for pin in net.connected_pins:
                pos = self.layout_planner.get_pin_position(
                    pin,
                    placements,
                    circuit,
                    pin_offsets,
                    rotations,
                )
                if pos is not None:
                    pin_positions[(pin.component_id, pin.pin_name)] = pos
        return pin_positions

    def _build_default_label_positions(self, circuit: Circuit) -> List[Tuple[float, float]]:
        positions: List[Tuple[float, float]] = []
        x_label, y_label = 20.0, 50.0
            # Ports
        for idx, _ in enumerate(circuit.ports.values()):
            positions.append((x_label, y_label + idx * 10.0))

        # Also add positions for input/output coupling caps so labels are emitted
        for comp_id, comp in circuit.components.items():
            key = comp_id.upper()
            if key in ("C1", "CIN"):
                positions.append((5.0, 50.0))
            elif key in ("C2", "COUT"):
                positions.append((95.0, 50.0))

        return positions

    def _count_wire_bends(self, wires: list) -> int:
        """Count bend points across all routed wires."""
        bends = 0
        for wire in wires:
            points = wire.get("points", [])
            bends += max(0, len(points) - 2)
        return bends

    def _readability_score(self, placements: Dict[str, tuple]) -> float:
        """Higher score means components are less crowded."""
        points = list(placements.values())
        if len(points) < 2:
            return 999.0

        nearest_distances: List[float] = []
        for i, (x1, y1) in enumerate(points):
            best = None
            for j, (x2, y2) in enumerate(points):
                if i == j:
                    continue
                dist = abs(x2 - x1) + abs(y2 - y1)
                if best is None or dist < best:
                    best = dist
            if best is not None:
                nearest_distances.append(float(best))

        if not nearest_distances:
            return 999.0
        return sum(nearest_distances) / len(nearest_distances)

    def _count_wire_crossings(self, wires: list) -> int:
        """Count geometric crossings between wire segments."""
        segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        for wire in wires:
            pts = wire.get("points", [])
            for i in range(len(pts) - 1):
                a = pts[i]
                b = pts[i + 1]
                if a == b:
                    continue
                segments.append((a, b))

        crossings = 0
        for i in range(len(segments)):
            for j in range(i + 1, len(segments)):
                if self._segments_cross(segments[i], segments[j]):
                    crossings += 1
        return crossings

    @staticmethod
    def _segments_cross(
        s1: Tuple[Tuple[float, float], Tuple[float, float]],
        s2: Tuple[Tuple[float, float], Tuple[float, float]],
    ) -> bool:
        """Return True when two orthogonal segments cross at interior points."""
        (x1, y1), (x2, y2) = s1
        (x3, y3), (x4, y4) = s2

        # Ignore if they share endpoints (intentional junctions).
        endpoints_1 = {(x1, y1), (x2, y2)}
        endpoints_2 = {(x3, y3), (x4, y4)}
        if endpoints_1 & endpoints_2:
            return False

        s1_vertical = x1 == x2
        s2_vertical = x3 == x4

        if s1_vertical == s2_vertical:
            return False

        if s1_vertical:
            xv = x1
            yh = y3
            return (
                min(y1, y2) < yh < max(y1, y2)
                and min(x3, x4) < xv < max(x3, x4)
            )

        xv = x3
        yh = y1
        return (
            min(y3, y4) < yh < max(y3, y4)
            and min(x1, x2) < xv < max(x1, x2)
        )
    
    def _create_ir(self, circuit: Circuit) -> CircuitIR:
        """Create CircuitIR from Circuit entity.
        
        Args:
            circuit: Circuit entity
            
        Returns:
            CircuitIR with metadata
        """
        meta = {
            "version": "1.0",
            "schema_version": "1.0",
            "circuit_name": circuit.name or "unnamed",
            "timestamp": datetime.now().isoformat(),
            "generator": "electronic-chatbot",
        }
        
        return CircuitIR(
            circuit=circuit,
            _meta=meta,
            _intent_snapshot={}
        )
    
    def _get_pin_offsets(self) -> Dict[str, list]:
        """Get pin offset definitions for all component types.
        Uses definitions from KiCadSymbolLibrary to ensure wires route exactly to the pins.
        """
        from app.infrastructure.exporters.kicad_symbol_library import KiCadSymbolLibrary
        
        # Mapping component types to symbol definitions
        mapping = {
            "resistor": "resistor",
            "capacitor": "capacitor",
            "capacitor_polarized": "capacitor",
            "inductor": "inductor",
            "bjt": "npn",
            "bjt_npn": "npn",
            "bjt_pnp": "pnp",
            "mosfet": "nmos",
            "mosfet_n": "nmos",
            "mosfet_p": "pmos",
            "diode": "diode",
            "opamp": "opamp",
            "voltage_source": "vsource",
            "current_source": "isource",
            "ground": "gnd",
            "port": "port",
            "connector": "connector"
        }
        
        offsets = {}
        for comp_type, sym_type in mapping.items():
            sym_def = KiCadSymbolLibrary.get_symbol_def(sym_type)
            if sym_def and 'pins' in sym_def:
                offsets[comp_type] = sym_def['pins']
                
        return offsets
    def _plan_wires(
        self,
        circuit: Circuit,
        placements: Dict[str, tuple],
        pin_offsets: Dict[str, list],
        rotations: Dict[str, int] | None = None,
    ) -> list:
        """Plan wire routing for all nets.
        
        Args:
            circuit: Circuit entity
            placements: Component placements
            pin_offsets: Pin offset definitions
            
        Returns:
            List of wire data dictionaries with 'points' key
        """
        grid = max(1.0, self.layout_planner.grid_snap)
        occupied_segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        wires: list = []

        axis_y = self._infer_signal_axis_y(circuit, placements)
        top_anchor = axis_y - 24.0
        bottom_anchor = axis_y + 24.0
        channel_step = 3.0 * grid

        route_items = []
        for net in circuit.nets.values():
            if len(net.connected_pins) < 2:
                continue

            pin_positions = []
            for pin in net.connected_pins:
                pos = self.layout_planner.get_pin_position(
                    pin, placements, circuit, pin_offsets, rotations
                )
                if pos is not None:
                    pin_positions.append(pos)

            points = self._unique_points(pin_positions)
            if len(points) < 2:
                continue

            net_class = self._classify_net_for_routing(net, circuit)
            priority = {"signal": 0, "coupling": 1, "bias": 2, "power": 3, "ground": 4, "other": 5}
            route_items.append((priority.get(net_class, 5), net_class, points))

        route_items.sort(key=lambda x: x[0])

        class_channel_index = {"signal": 0, "coupling": 0, "bias": 0, "power": 0, "ground": 0, "other": 0}

        for _, net_class, points in route_items:
            points = sorted(points, key=lambda p: (p[0], p[1]))
            ch_idx = class_channel_index.get(net_class, 0)
            channel_candidates = self._candidate_channels(
                net_class,
                axis_y,
                top_anchor,
                bottom_anchor,
                channel_step,
                ch_idx,
            )
            preferred_y = channel_candidates[0]
            class_channel_index[net_class] = ch_idx + 1

            for i in range(len(points) - 1):
                path = self._route_pair_with_occupancy(
                    points[i],
                    points[i + 1],
                    preferred_y,
                    occupied_segments,
                    grid,
                )
                wires.append({"points": path})
                occupied_segments.extend(self._path_to_segments(path))

        return wires

    def _route_pair_with_occupancy(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        preferred_y: float,
        occupied_segments: List[Tuple[Tuple[float, float], Tuple[float, float]]],
        grid: float,
    ) -> List[Tuple[float, float]]:
        x1, y1 = p1
        x2, y2 = p2

        if x1 == x2 or y1 == y2:
            return self._snap_path([p1, p2], grid)

        corner_hv = (x2, y1)
        corner_vh = (x1, y2)
        via_pref_h = (x1, preferred_y)
        via_pref_h2 = (x2, preferred_y)
        via_pref_v = ((x1 + x2) / 2.0, y1)
        via_pref_v2 = ((x1 + x2) / 2.0, y2)

        candidates = [
            [p1, corner_hv, p2],
            [p1, corner_vh, p2],
            [p1, via_pref_h, via_pref_h2, p2],
            [p1, via_pref_v, via_pref_v2, p2],
            [p1, (x1, preferred_y - 2.0 * grid), (x2, preferred_y - 2.0 * grid), p2],
            [p1, (x1, preferred_y + 2.0 * grid), (x2, preferred_y + 2.0 * grid), p2],
        ]

        best = min(candidates, key=lambda c: self._path_conflict_cost(self._snap_path(c, grid), occupied_segments))
        return self._snap_path(best, grid)

    def _infer_signal_axis_y(self, circuit: Circuit, placements: Dict[str, tuple]) -> float:
        vin_y = [placements[cid][1] for cid in placements if "vin" in cid.lower()]
        vout_y = [placements[cid][1] for cid in placements if "vout" in cid.lower()]
        if vin_y and vout_y:
            return (vin_y[0] + vout_y[0]) / 2.0
        if vin_y:
            return vin_y[0]
        if vout_y:
            return vout_y[0]
        return self.layout_planner.y_start

    def _classify_net_for_routing(self, net, circuit: Circuit) -> str:
        name = (net.name or "").lower()
        pin_ids = [p.component_id for p in net.connected_pins]
        pin_ids_l = [cid.lower() for cid in pin_ids]

        if any(tok in name for tok in ("vcc", "vdd", "v+", "power")):
            return "power"
        if any(tok in name for tok in ("gnd", "ground", "vss", "0v")):
            return "ground"
        if any(tok in name for tok in ("bias", "vb", "ib", "tail")):
            return "bias"
        if any("vin" in cid or "vout" in cid for cid in pin_ids_l):
            return "signal"

        comp_types = []
        for cid in pin_ids:
            comp = circuit.components.get(cid)
            if comp is not None:
                comp_types.append(comp.type.value.lower())

        if any(ct in ("opamp", "bjt", "bjt_npn", "bjt_pnp", "mosfet", "mosfet_n", "mosfet_p") for ct in comp_types):
            return "signal"
        if any(ct in ("capacitor", "capacitor_polarized", "inductor", "transformer") for ct in comp_types):
            return "coupling"
        return "other"

    def _candidate_channels(
        self,
        net_class: str,
        axis_y: float,
        top_anchor: float,
        bottom_anchor: float,
        step: float,
        index: int,
    ) -> List[float]:
        if net_class in ("signal", "coupling"):
            base = axis_y
            return [
                base + index * step,
                base - index * step,
                base + (index + 1) * step,
                base - (index + 1) * step,
            ]
        if net_class == "power":
            base = top_anchor
            return [base - index * step, base - (index + 1) * step, base + step]
        if net_class in ("ground", "bias"):
            base = bottom_anchor
            return [base + index * step, base + (index + 1) * step, base - step]
        return [axis_y + (index + 1) * step, axis_y - (index + 1) * step]

    def _select_trunk_y(
        self,
        candidates: List[float],
        x_min: float,
        x_max: float,
        occupied_segments: List[Tuple[Tuple[float, float], Tuple[float, float]]],
    ) -> float:
        best_y = candidates[0]
        best_score = None
        for y in candidates:
            trunk = ((x_min, y), (x_max, y))
            score = self._segment_conflict_cost(trunk, occupied_segments)
            if best_score is None or score < best_score:
                best_score = score
                best_y = y
        return best_y

    def _route_net_with_trunk(
        self,
        points: List[Tuple[float, float]],
        trunk_y: float,
        occupied_segments: List[Tuple[Tuple[float, float], Tuple[float, float]]],
        grid: float,
    ) -> List[List[Tuple[float, float]]]:
        xs = [p[0] for p in points]
        x_min = min(xs)
        x_max = max(xs)
        paths: List[List[Tuple[float, float]]] = []

        trunk_path = [(x_min, trunk_y), (x_max, trunk_y)]
        paths.append(trunk_path)

        for x, y in points:
            tap = (x, trunk_y)
            if abs(y - trunk_y) < 1e-9:
                continue

            direct = [(x, y), tap]
            detour_left_x = x - 2.0 * grid
            detour_right_x = x + 2.0 * grid
            via_left = [(x, y), (detour_left_x, y), (detour_left_x, trunk_y), tap]
            via_right = [(x, y), (detour_right_x, y), (detour_right_x, trunk_y), tap]

            candidates = [direct, via_left, via_right]
            best = min(candidates, key=lambda p: self._path_conflict_cost(p, occupied_segments))
            paths.append(best)
            occupied_segments.extend(self._path_to_segments(best))

        return [self._snap_path(path, grid) for path in paths]

    def _path_conflict_cost(
        self,
        path: List[Tuple[float, float]],
        occupied_segments: List[Tuple[Tuple[float, float], Tuple[float, float]]],
    ) -> float:
        segs = self._path_to_segments(path)
        crossings = 0
        overlaps = 0
        for s in segs:
            for occ in occupied_segments:
                if self._segments_cross(s, occ):
                    crossings += 1
                if self._segments_overlap(s, occ):
                    overlaps += 1
        bends = max(0, len(path) - 2)
        return crossings * 10.0 + overlaps * 3.0 + bends

    def _segment_conflict_cost(
        self,
        segment: Tuple[Tuple[float, float], Tuple[float, float]],
        occupied_segments: List[Tuple[Tuple[float, float], Tuple[float, float]]],
    ) -> float:
        crossings = 0
        overlaps = 0
        for occ in occupied_segments:
            if self._segments_cross(segment, occ):
                crossings += 1
            if self._segments_overlap(segment, occ):
                overlaps += 1
        return crossings * 10.0 + overlaps * 3.0

    @staticmethod
    def _segments_overlap(
        s1: Tuple[Tuple[float, float], Tuple[float, float]],
        s2: Tuple[Tuple[float, float], Tuple[float, float]],
    ) -> bool:
        (x1, y1), (x2, y2) = s1
        (x3, y3), (x4, y4) = s2
        s1_vertical = x1 == x2
        s2_vertical = x3 == x4
        if s1_vertical != s2_vertical:
            return False

        if s1_vertical:
            if x1 != x3:
                return False
            a1, a2 = sorted((y1, y2))
            b1, b2 = sorted((y3, y4))
            return max(a1, b1) < min(a2, b2)

        if y1 != y3:
            return False
        a1, a2 = sorted((x1, x2))
        b1, b2 = sorted((x3, x4))
        return max(a1, b1) < min(a2, b2)

    @staticmethod
    def _path_to_segments(path: List[Tuple[float, float]]) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
        segs = []
        for i in range(len(path) - 1):
            a = path[i]
            b = path[i + 1]
            if a != b:
                segs.append((a, b))
        return segs

    @staticmethod
    def _unique_points(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        out: List[Tuple[float, float]] = []
        seen = set()
        for p in points:
            key = (round(p[0], 6), round(p[1], 6))
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        return out

    def _snap_path(self, path: List[Tuple[float, float]], grid: float) -> List[Tuple[float, float]]:
        snapped = []
        for x, y in path:
            snapped.append((self.layout_planner._snap_value(x, grid), self.layout_planner._snap_value(y, grid)))
        return snapped
    
    def _find_junctions(self, wires: list) -> set:
        """Find junction points in wire routing (delegates to module-level helper)."""
        return _find_junctions_from_wires(wires)
