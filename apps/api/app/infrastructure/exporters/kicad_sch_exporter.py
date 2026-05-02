# .\\thesis\\electronic-chatbot\\apps\\api\\app\\infrastructure\\exporters\\kicad_sch_exporter.py
"""Công cụ xuất sơ đồ mạch KiCad (.kicad_sch).

Module này cung cấp triển khai cụ thể của ExporterPort cho định dạng KiCad
.kicad_sch. Nó điều phối layout planning + schematic serialization để
tạo ra file .kicad_sch hoàn chỉnh.

Vietnamese:
- Trách nhiệm: Xuất Circuit entities thành KiCad schematic format
- Quy trình: Circuit → Layout planning → Serialization → .kicad_sch text

English:
- Responsibility: Export Circuit entities to KiCad schematic format
- Workflow: Circuit → Layout planning → Serialization → .kicad_sch text
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# typing: Type hints cho IDE support
# datetime: Timestamp metadata cho schematic files
from typing import Dict, Any, List, Tuple
from datetime import datetime

# ====== Domain & Application layers ======
from app.domains.circuits.entities import Circuit
from app.domains.circuits.ir import CircuitIR, CircuitIRSerializer
from app.domains.circuits.placement import LayoutQualityEvaluator, LayoutQualityReport
from app.application.circuits.ports import ExporterPort
from app.application.circuits.dtos import ExportFormat
from app.application.circuits.errors import ExportError

# ====== Infrastructure - Layout & Serialization ======
from app.infrastructure.exporters.layout_planner import LayoutPlanner
from app.infrastructure.exporters.kicad_sch_serializer import KiCadSchSerializer


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
        
        try:
            self._last_layout_quality_report = None

            # Convert to IR first
            ir = self._create_ir(circuit)

            # Get pin offset definitions for routing
            pin_offsets = self._get_pin_offsets()

            # Plan layout with relaxation loop (expand spacing if too dense).
            placements, wires, rotations = self._auto_relax_layout(circuit, pin_offsets)
            placements, wires, rotations = self._finalize_layout_and_validate(
                circuit,
                pin_offsets,
                placements,
                rotations,
            )

            self._last_layout_quality_report = self._evaluate_layout_quality(
                circuit,
                placements,
                wires,
                pin_offsets,
                rotations,
            )

            # Find junctions
            junctions = self._find_junctions(wires)
            
            # Serialize to KiCad format
            kicad_content = self.serializer.serialize(
                ir, placements, wires, junctions, rotations
            )
            
            return kicad_content
            
        except Exception as e:
            raise ExportError(
                format_type=format_type.value,
                reason=f"KiCad export failed: {str(e)}"
            ) from e

    def get_last_layout_quality_report(self) -> Dict[str, Any] | None:
        if self._last_layout_quality_report is None:
            return None
        return self._last_layout_quality_report.to_dict()

    def _finalize_layout_and_validate(
        self,
        circuit: Circuit,
        pin_offsets: Dict[str, list],
        placements: Dict[str, tuple],
        rotations: Dict[str, int],
    ) -> Tuple[Dict[str, tuple], list, Dict[str, int]]:
        """Auto-fix pass: snap to grid, resolve overlaps, reroute, and validate connectivity."""
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

    def _auto_relax_layout(
        self,
        circuit: Circuit,
        pin_offsets: Dict[str, list],
    ) -> Tuple[Dict[str, tuple], list, Dict[str, int]]:
        """Iteratively expand spacing and reroute to reduce crossings and improve readability."""
        scales = [1.0, 1.15, 1.3, 1.45, 1.6]

        best_placements: Dict[str, tuple] = {}
        best_wires: list = []
        best_rotations: Dict[str, int] = {}
        best_score: float | None = None
        best_quality: LayoutQualityReport | None = None

        for idx, scale in enumerate(scales):
            placements = self.layout_planner.place_components(circuit, spacing_scale=scale)
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
        x_label, y_label = 20.0, 50.0
        return [
            (x_label, y_label + idx * 10.0)
            for idx, _ in enumerate(circuit.ports.values())
        ]

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
        """Find junction points in wire routing.
        
        Args:
            wires: List of wire data dictionaries
            
        Returns:
            Set of junction coordinates
        """
        # Convert wire data to format expected by layout_planner
        wire_segments = [wire["points"] for wire in wires]
        return self.layout_planner.find_junctions(wire_segments)
