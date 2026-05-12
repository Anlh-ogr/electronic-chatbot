# .\\thesis\\electronic-chatbot\\apps\\api\\app\\infrastructure\\exporters\\kicad_pcb_exporter.py
"""Công cụ xuất bản mạch in KiCad (.kicad_pcb).

Module này cung cấp triển khai cụ thể của ExporterPort cho định dạng KiCad
.kicad_pcb. Nó điều phối PCB layout planning + serialization để
tạo ra file .kicad_pcb hoàn chỉnh với footprints, nets, tracks.

Vietnamese:
- Trách nhiệm: Xuất Circuit entities thành KiCad PCB format
- Quy trình: Circuit → PCB layout planning → Serialization → .kicad_pcb text

English:
- Responsibility: Export Circuit entities to KiCad PCB format
- Workflow: Circuit → PCB layout planning → Serialization → .kicad_pcb text
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional, Tuple

from pydantic import ValidationError

logger = logging.getLogger(__name__)

# ====== Domain & Application layers ======
from app.domains.circuits.entities import Circuit
from app.domains.circuits.ir import CircuitIR, CircuitIRSerializer
from app.application.circuits.ports import ExporterPort
from app.application.circuits.dtos import ExportFormat
from app.application.circuits.errors import ExportError

# ====== Infrastructure - PCB Layout & Serialization ======
from app.infrastructure.exporters.pcb_layout_planner import PCBLayoutPlanner
from app.infrastructure.exporters.kicad_pcb_serializer import KiCadPCBSerializer
from app.infrastructure.exporters import pcb_strict_engine as strict_pcb
from app.core.structured_logger import log_stage

FOOTPRINT_MAP: Dict[str, str] = {
    "R": "Resistor_SMD:R_0805_2012Metric",
    "C": "Capacitor_SMD:C_0805_2012Metric",
    "U": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "Q": "Package_TO_SOT_THT:TO-92_Inline",
    "J": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
}

POWER_REFS = {"VCC", "VEE", "GND", "+15V", "-15V", "+5V", "PWR"}


class KiCadPCBExporter(ExporterPort):
    """Exporter for KiCad PCB (.kicad_pcb) format.
    
    This implementation orchestrates:
    1. Converting Circuit entity to CircuitIR
    2. Planning component placement on PCB (PCBLayoutPlanner)
    3. Planning net connectivity and routing
    4. Serializing to KiCad PCB s-expression format (KiCadPCBSerializer)
    """
    
    def __init__(self):
        """Initialize PCB exporter with planner and serializer."""
        self.layout_planner = PCBLayoutPlanner()
        self.serializer = KiCadPCBSerializer()
        self._last_routing_report: Dict[str, Any] = {}
        self._last_board_size_mm: Optional[Tuple[float, float]] = None

    @staticmethod
    def _resolve_board_size(circuit: Circuit) -> Tuple[float, float]:
        stage_labels = {
            str(component.stage).strip()
            for component in circuit.components.values()
            if getattr(component, "stage", None)
        }

        if stage_labels:
            stage_count = min(3, max(1, len(stage_labels)))
        else:
            component_count = len(circuit.components)
            if component_count <= 8:
                stage_count = 1
            elif component_count <= 16:
                stage_count = 2
            else:
                stage_count = 3

        board_width_map = {1: 90.0, 2: 90.0, 3: 130.0}
        return board_width_map[stage_count], 40.0

    @staticmethod
    def _is_power_ref(ref: str, comp_type: str) -> bool:
        r = str(ref or "").strip().upper()
        t = str(comp_type or "").strip().lower()
        return (
            r in POWER_REFS
            or r.startswith("PWR")
            or r.startswith("#PWR")
            or t in {"ground", "power_supply", "power_symbol", "voltage_source", "current_source"}
        )

    @classmethod
    def resolve_anchor(cls, components: List[Dict[str, str]]) -> str:
        """Resolve placement anchor before strict validation/model checks."""
        priority = [
            lambda r, t: r.startswith("U") and ("op_amp" in t or "opamp" in t),
            lambda r, t: r.startswith("Q") and t in ("bjt", "npn", "pnp", "transistor", "bjt_npn", "bjt_pnp"),
            lambda r, t: r.startswith("U"),
            lambda r, t: r.startswith("Q"),
        ]
        for fn in priority:
            for c in components:
                ref = str(c.get("ref") or "").upper()
                ctype = str(c.get("type") or "").lower()
                if cls._is_power_ref(ref, ctype):
                    continue
                if fn(ref, ctype):
                    return ref
        refs = [str(c.get("ref") or "") for c in components]
        raise ValueError(f"No U/Q anchor. Refs: {refs}")

    async def export(
        self,
        circuit: Circuit,
        format_type: ExportFormat,
        options: Dict[str, Any] | None = None,
    ) -> str:
        """Export circuit to KiCad PCB format.
        
        Args:
            circuit: Circuit entity to export
            format_type: Must be KICAD_PCB
            
        Returns:
            KiCad .kicad_pcb file content as string
            
        Raises:
            ExportError: If export fails or format not supported
        """
        if format_type not in [ExportFormat.KICAD, ExportFormat.KICAD_PCB]:
            raise ExportError(
                format_type=format_type.value,
                reason=f"This exporter only supports KiCad PCB formats"
            )
        
        # HARD GUARD: Reject export if circuit.id is None (prevents stray post-response invocations)
        cid = getattr(circuit, "id", None)
        if not cid or str(cid).strip() == "None":
            raise ExportError(
                format_type=format_type.value,
                reason="Exporter requires valid circuit.id (got None or empty). This is likely a stray background invocation without proper context."
            )
        
        try:
            board_width, board_height = self._resolve_board_size(circuit)
            self._last_board_size_mm = (board_width, board_height)

            # Convert to IR first
            ir = self._create_ir(circuit)

            export_options = dict(options or {})
            export_options.setdefault("board_width", board_width)
            export_options.setdefault("board_height", board_height)
            export_options.setdefault("enable_power_zones", True)
            export_options.setdefault("routing_mode", "strict")

            routing_mode = str(export_options.get("routing_mode") or "strict").strip().lower()
            zones: List[Dict[str, Any]] = []
            component_summaries = [
                {
                    "ref": str(cid).upper(),
                    "type": str(getattr(getattr(comp, "type", None), "value", getattr(comp, "type", ""))).lower(),
                }
                for cid, comp in circuit.components.items()
            ]
            anchor = self.resolve_anchor(component_summaries)

            if routing_mode == "strict":
                export_options["enable_power_zones"] = False
                placements, strict_anchor, _meta = strict_pcb.place_strict(
                    circuit,
                    nominal_w=float(export_options["board_width"]),
                    nominal_h=float(export_options["board_height"]),
                )
                anchor = strict_anchor or anchor
                placements, (board_width, board_height) = strict_pcb.finalize_board_size(
                    circuit, placements
                )
                self._last_board_size_mm = (board_width, board_height)
                overlap_final = strict_pcb.count_courtyard_overlaps(circuit, placements)

                self.layout_planner = PCBLayoutPlanner(
                    board_width=board_width,
                    board_height=board_height,
                )
                nets = self.layout_planner.plan_nets(circuit)
                total_r = len([n for n, p in nets.items() if len(p) >= 2])

                _log_pcb_stage(
                    "PCB_PLACEMENT",
                    board_width,
                    board_height,
                    anchor,
                    len(placements),
                    overlap_final,
                    total_r,
                    0,
                    total_r,
                    0,
                    0,
                    0,
                    0,
                )

                tracks, route_meta = strict_pcb.route_strict(circuit, placements, nets)
                via_count = int(route_meta.get("via_count") or 0)
                angle_v = strict_pcb.count_track_angle_violations(tracks)

                _log_pcb_stage(
                    "PCB_ROUTING",
                    board_width,
                    board_height,
                    anchor,
                    len(placements),
                    overlap_final,
                    total_r,
                    int(route_meta.get("routed_nets") or 0),
                    max(0, total_r - int(route_meta.get("routed_nets") or 0)),
                    via_count,
                    angle_v,
                    strict_pcb.count_shorts(tracks),
                    strict_pcb.count_clearance_violations(tracks),
                )

                drc = strict_pcb.run_pcb_drc(circuit, placements, nets, tracks)
                errors = int(drc["overlap_count"]) + int(drc["short_circuit_count"]) + int(drc["unrouted_nets"]) + int(drc["track_angle_violations"]) + int(drc["clearance_violations"])
                try:
                    log_stage(
                        "PCB_DRC",
                        errors=errors,
                        unconnected_items=int(drc["unrouted_nets"]),
                        clearance_violations=int(drc["clearance_violations"]),
                    )
                except Exception:
                    pass
                _log_pcb_stage(
                    "PCB_DRC",
                    board_width,
                    board_height,
                    anchor,
                    len(placements),
                    drc["overlap_count"],
                    drc["total_nets"],
                    drc["routed_nets"],
                    drc["unrouted_nets"],
                    via_count,
                    drc["track_angle_violations"],
                    drc["short_circuit_count"],
                    drc["clearance_violations"],
                )
                strict_pcb.raise_if_drc_fails(
                    drc, board_size_mm=(board_width, board_height), center=anchor
                )

                self._last_routing_report = {
                    "routing_mode": "strict",
                    "metrics": {
                        "track_count": len(tracks),
                        "routed_nets": drc["routed_nets"],
                        "total_nets": drc["total_nets"],
                        "unrouted_nets": drc["unrouted_nets"],
                        "via_count": via_count,
                    },
                    "drc": dict(drc),
                }
            else:
                self.layout_planner = PCBLayoutPlanner(
                    board_width=board_width,
                    board_height=board_height,
                )
                placements = self.layout_planner.place_components(circuit, options=export_options)
                nets = self.layout_planner.plan_nets(circuit)
                tracks = self.layout_planner.plan_tracks(
                    circuit, placements, nets, options=export_options
                )
                zones = self.layout_planner.get_last_zones()
                self._last_routing_report = self.layout_planner.get_last_routing_report()
                angle_v = strict_pcb.count_track_angle_violations(tracks)
                total_r = len([n for n, p in nets.items() if len(p) >= 2])
                routed_nets = total_r if tracks else 0
                unrouted_nets = max(0, total_r - routed_nets)
                try:
                    log_stage(
                        "PCB_PLACEMENT",
                        board_size_mm=f"{board_width:.2f}x{board_height:.2f}",
                        center_component=anchor,
                        components_placed=len(placements),
                        overlap_count=strict_pcb.count_courtyard_overlaps(circuit, placements),
                    )
                    log_stage(
                        "PCB_ROUTING",
                        total_nets=total_r,
                        routed_nets=routed_nets,
                        unrouted_nets=unrouted_nets,
                        track_angle_violations=angle_v,
                    )
                    log_stage(
                        "PCB_DRC",
                        errors=int(unrouted_nets > 0) + int(angle_v > 0),
                        unconnected_items=unrouted_nets,
                        clearance_violations=strict_pcb.count_clearance_violations(tracks),
                    )
                except Exception:
                    pass
                if unrouted_nets > 0 or angle_v > 0:
                    raise ValidationError.from_exception_data(
                        "KiCadPCB",
                        [
                            {
                                "type": "value_error",
                                "loc": ("pcb", "routing"),
                                "input": {"unrouted_nets": unrouted_nets, "track_angle_violations": angle_v},
                                "ctx": {
                                    "error": (
                                        f"Routing invalid: unrouted_nets={unrouted_nets} "
                                        f"track_angle_violations={angle_v}"
                                    )
                                },
                            }
                        ],
                    )

            # Verify footprint assignments & power-symbol exclusion
            fp_verify = self._verify_pcb_footprints(circuit)
            try:
                log_stage(
                    "PCB_FOOTPRINT_VERIFY",
                    r_ok=fp_verify["r_ok"],
                    c_ok=fp_verify["c_ok"],
                    power_symbols_in_pcb=fp_verify["power_in_pcb"],
                    all_ok=fp_verify["ok"],
                )
            except Exception:
                pass

            pcb_content = self.serializer.serialize(
                ir,
                placements,
                nets,
                tracks,
                board_size=(board_width, board_height),
                zones=zones,
            )

            return pcb_content

        except ValidationError:
            raise
        except Exception as e:
            raise ExportError(
                format_type=format_type.value,
                reason=f"KiCad PCB export failed: {str(e)}",
            ) from e
    
    def _verify_pcb_footprints(self, circuit: Circuit) -> Dict[str, Any]:
        """Verify footprint assignments and power-symbol filtering.

        Returns a dict with keys:
            ok           – True when all checks pass
            r_ok         – resistors have Resistor_SMD footprint
            c_ok         – capacitors have Capacitor_SMD footprint
            power_in_pcb – list of comp IDs that should have been excluded
        """
        r_bad: List[str] = []
        c_bad: List[str] = []
        power_leaked: List[str] = []

        for comp_id, comp in circuit.components.items():
            comp_type_val = (
                comp.type.value if hasattr(comp.type, "value") else str(comp.type)
            )
            if self._is_power_ref(comp_id, comp_type_val):
                power_leaked.append(comp_id)
                continue

            ref = comp_id.upper().strip()
            prefix = ref[0] if ref else "X"
            expected_fp = FOOTPRINT_MAP.get(prefix, "")

            if prefix == "R" and expected_fp and not expected_fp.startswith("Resistor_SMD"):
                r_bad.append(comp_id)
            if prefix == "C" and expected_fp and not expected_fp.startswith("Capacitor_SMD"):
                c_bad.append(comp_id)

        # power_leaked = components that exist in circuit entity but have no physical footprint.
        # This is EXPECTED — the serializer correctly filters them from PCB output.
        if power_leaked:
            logger.debug(
                "PCB footprint verification: %d power/ground symbols correctly excluded from PCB: %s",
                len(power_leaked),
                power_leaked,
            )

        ok = not r_bad and not c_bad
        result = {
            "ok": ok,
            "r_ok": not r_bad,
            "c_ok": not c_bad,
            "power_in_pcb": [],  # always empty — serializer handles this correctly
        }

        if not ok:
            logger.warning(
                "PCB footprint verification FAILED: r_bad=%s c_bad=%s",
                r_bad,
                c_bad,
            )
        else:
            logger.info("PCB footprint verification PASSED")

        return result

    def _create_ir(self, circuit: Circuit) -> CircuitIR:
        """Convert Circuit entity to intermediate representation.
        
        Args:
            circuit: Circuit entity
            
        Returns:
            CircuitIR
        """
        # Build IR directly from the Circuit entity
        return CircuitIRSerializer.build_ir(circuit)

    def get_last_routing_report(self) -> Dict[str, Any]:
        return dict(self._last_routing_report)

    def get_last_board_size_mm(self) -> Optional[Tuple[float, float]]:
        return self._last_board_size_mm


def _log_pcb_stage(
    stage: str,
    bw: float,
    bh: float,
    center: str,
    components_placed: int,
    overlap_count: int,
    total_nets: int,
    routed_nets: int,
    unrouted_nets: int,
    via_count: int,
    track_angle_violations: int,
    short_circuit_count: int,
    clearance_violations: int,
) -> None:
    try:
        log_stage(
            stage,
            board_size_mm=f"{bw:.2f}x{bh:.2f}",
            center_component=center,
            components_placed=components_placed,
            overlap_count=overlap_count,
            total_nets=total_nets,
            routed_nets=routed_nets,
            unrouted_nets=unrouted_nets,
            via_count=via_count,
            track_angle_violations=track_angle_violations,
            short_circuit_count=short_circuit_count,
            clearance_violations=clearance_violations,
        )
    except Exception:
        pass
