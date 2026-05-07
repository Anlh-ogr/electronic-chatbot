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

# ====== Lý do sử dụng thư viện ======
# typing: Type hints cho IDE support
from typing import Dict, Any, Tuple

# ====== Domain & Application layers ======
from app.domains.circuits.entities import Circuit
from app.domains.circuits.ir import CircuitIR, CircuitIRSerializer
from app.application.circuits.ports import ExporterPort
from app.application.circuits.dtos import ExportFormat
from app.application.circuits.errors import ExportError

# ====== Infrastructure - PCB Layout & Serialization ======
from app.infrastructure.exporters.pcb_layout_planner import PCBLayoutPlanner
from app.infrastructure.exporters.kicad_pcb_serializer import KiCadPCBSerializer


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

        board_width_map = {1: 50.0, 2: 90.0, 3: 130.0}
        return board_width_map[stage_count], 40.0
    
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
            self.layout_planner = PCBLayoutPlanner(
                board_width=board_width,
                board_height=board_height,
            )

            # Convert to IR first
            ir = self._create_ir(circuit)
            
            export_options = dict(options or {})
            export_options.setdefault("board_width", board_width)
            export_options.setdefault("board_height", board_height)
            export_options.setdefault("enable_power_zones", True)

            # Plan PCB layout
            placements = self.layout_planner.place_components(circuit, options=export_options)
            
            # Extract nets from circuit connections
            nets = self.layout_planner.plan_nets(circuit)
            
            # Plan track routing
            tracks = self.layout_planner.plan_tracks(circuit, placements, nets, options=export_options)
            zones = self.layout_planner.get_last_zones()

            self._last_routing_report = self.layout_planner.get_last_routing_report()
            
            # Serialize to KiCad PCB format
            pcb_content = self.serializer.serialize(
                ir,
                placements,
                nets,
                tracks,
                board_size=(board_width, board_height),
                zones=zones,
            )
            
            return pcb_content
            
        except Exception as e:
            raise ExportError(
                format_type=format_type.value,
                reason=f"KiCad PCB export failed: {str(e)}"
            ) from e
    
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
