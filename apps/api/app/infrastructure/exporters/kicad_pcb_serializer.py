# .\\thesis\\electronic-chatbot\\apps\\api\\app\\infrastructure\\exporters\\kicad_pcb_serializer.py
"""Công cụ tuần tự hóa bản mạch in KiCad (.kicad_pcb format).

Module này chuyển đổi Circuit entities + PCB layout information thành
KiCad .kicad_pcb s-expression format. Nó xử lý footprint instances, nets,
tracks, vias, zones để tạo PCB layout đầy đủ theo KiCad 8+ standard.

Vietnamese:
- Trách nhiệm: Chuyển đổi Circuit + PCB layout → .kicad_pcb s-expression
- Đầu ra: (footprint ...), (net ...), (segment ...), (zone ...) blocks
- Tiêu chuẩn: KiCad 8 compatibility

English:
- Responsibility: Convert Circuit + PCB layout → .kicad_pcb s-expression
- Output: (footprint ...), (net ...), (segment ...), (zone ...) blocks
- Standard: KiCad 8 compatibility
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# typing: Type hints cho PCB s-expression generation
# datetime: Timestamps cho PCB metadata
# uuid: Unique IDs cho nets/segments
from typing import Dict, Tuple, List, Set
from datetime import datetime
import uuid

# ====== Domain & Infrastructure layers ======
from app.domains.circuits.entities import Circuit
from app.domains.circuits.ir import CircuitIR
from app.infrastructure.exporters.kicad_footprint_library import KiCadFootprintLibrary


# ====== PCB Serializer ======
class KiCadPCBSerializer:
    """Tuần tự hóa bản mạch in thành KiCad .kicad_pcb s-expression format.
    
    Class này chuyển đổi Circuit entities + PCB layout info (footprint positions,
    connections, routing) thành s-expression text format đúng với tiêu chuẩn KiCad 8.
    
    Responsibilities (Trách nhiệm):
    - Chuyển đổi Circuit + PCB layout → KiCad s-expression
    - Tạo footprint instances blocks
    - Tạo nets, segments (tracks), zones
    - Đảm bảo tương thích KiCad 8
    """
    
    # ====== KiCad PCB Format Configuration ======
    KICAD_PCB_VERSION = "20240108"
    GENERATOR_VERSION = "8.0"
    
    def __init__(self):
        """Initialize PCB serializer."""
        self._net_index = 1  # Net index counter (0 is reserved for "")
        self._net_map: Dict[str, int] = {}  # net_name -> net_index
        self._uuid_cache: Dict[str, str] = {}
        
    def serialize(
        self,
        ir: CircuitIR,
        placements: Dict[str, Tuple[float, float]],
        nets: Dict[str, List[str]],
        tracks: List[Dict]
    ) -> str:
        """Serialize Circuit with PCB layout to KiCad PCB format.
        
        Args:
            ir: Circuit intermediate representation
            placements: Component positions (comp_id -> (x, y) in mm)
            nets: Net definitions (net_name -> [comp_id.pin, ...])
            tracks: Track routing information
            
        Returns:
            KiCad .kicad_pcb file content as string
        """
        circuit = ir.circuit
        
        # Build net map
        self._build_net_map(nets)
        
        lines = []
        
        # Header
        lines.extend(self._build_header())
        lines.append("")
        
        # Nets
        lines.extend(self._build_nets())
        lines.append("")
        
        # Footprints (component instances)
        for comp_id, component in circuit.components.items():
            if comp_id in placements:
                x, y = placements[comp_id]
                lines.extend(self._build_footprint(
                    comp_id, component, x, y, nets
                ))
                lines.append("")
        
        # Tracks (PCB traces)
        if tracks:
            lines.extend(self._build_tracks(tracks))
            lines.append("")
        
        # Zones (copper pours) - optional, can add GND plane
        lines.extend(self._build_zones())
        lines.append("")
        
        # Footer
        lines.append(")")
        
        return "\n".join(lines)
    
    def _build_header(self) -> List[str]:
        """Build PCB file header."""
        return [
            "(kicad_pcb",
            f'  (version {self.KICAD_PCB_VERSION})',
            f'  (generator "electronic-chatbot")',
            f'  (generator_version "{self.GENERATOR_VERSION}")',
            "  (general",
            "    (thickness 1.6)",
            "    (legacy_teardrops no)",
            "  )",
            '  (paper "A4")',
            "  (layers",
            '    (0 "F.Cu" signal)',
            '    (31 "B.Cu" signal)',
            '    (32 "B.Adhes" user "B.Adhesive")',
            '    (33 "F.Adhes" user "F.Adhesive")',
            '    (34 "B.Paste" user)',
            '    (35 "F.Paste" user)',
            '    (36 "B.SilkS" user "B.Silkscreen")',
            '    (37 "F.SilkS" user "F.Silkscreen")',
            '    (38 "B.Mask" user)',
            '    (39 "F.Mask" user)',
            '    (40 "Dwgs.User" user "User.Drawings")',
            '    (41 "Cmts.User" user "User.Comments")',
            '    (42 "Eco1.User" user)',
            '    (43 "Eco2.User" user)',
            '    (44 "Edge.Cuts" user)',
            '    (45 "Margin" user)',
            '    (46 "B.CrtYd" user "B.Courtyard")',
            '    (47 "F.CrtYd" user "F.Courtyard")',
            '    (48 "B.Fab" user)',
            '    (49 "F.Fab" user)',
            "  )",
            "  (setup",
            "    (pad_to_mask_clearance 0)",
            "    (allow_soldermask_bridges_in_footprints no)",
            "    (pcbplotparams",
            "      (layerselection 0x00010fc_ffffffff)",
            "      (plot_on_all_layers_selection 0x0000000_00000000)",
            "      (disableapertmacros no)",
            "      (usegerberextensions no)",
            "      (usegerberattributes yes)",
            "      (usegerberadvancedattributes yes)",
            "      (creategerberjobfile yes)",
            "      (dashed_line_dash_ratio 12.000000)",
            "      (dashed_line_gap_ratio 3.000000)",
            "      (svgprecision 4)",
            "      (plotframeref no)",
            "      (viasonmask no)",
            "      (mode 1)",
            "      (useauxorigin no)",
            "      (hpglpennumber 1)",
            "      (hpglpenspeed 20)",
            "      (hpglpendiameter 15.000000)",
            "      (pdf_front_fp_property_popups yes)",
            "      (pdf_back_fp_property_popups yes)",
            "      (dxfpolygonmode yes)",
            "      (dxfimperialunits yes)",
            "      (dxfusepcbnewfont yes)",
            "      (psnegative no)",
            "      (psa4output no)",
            "      (plotreference yes)",
            "      (plotvalue yes)",
            "      (plotfptext yes)",
            "      (plotinvisibletext no)",
            "      (sketchpadsonfab no)",
            "      (subtractmaskfromsilk no)",
            "      (outputformat 1)",
            "      (mirror no)",
            "      (drillshape 1)",
            "      (scaleselection 1)",
            '      (outputdirectory "")',
            "    )",
            "  )",
        ]
    
    def _build_net_map(self, nets: Dict[str, List[str]]):
        """Build mapping from net names to net indices."""
        self._net_map = {"": 0}  # Empty net
        self._net_index = 1
        
        for net_name in sorted(nets.keys()):
            if net_name and net_name not in self._net_map:
                self._net_map[net_name] = self._net_index
                self._net_index += 1
    
    def _build_nets(self) -> List[str]:
        """Build net definitions."""
        lines = []
        for net_name, net_idx in sorted(self._net_map.items(), key=lambda x: x[1]):
            lines.append(f'  (net {net_idx} "{net_name}")')
        return lines
    
    def _build_footprint(
        self,
        comp_id: str,
        component,
        x: float,
        y: float,
        nets: Dict[str, List[str]]
    ) -> List[str]:
        """Build footprint instance for a component.
        
        Args:
            comp_id: Component ID
            component: Component entity
            x, y: Position in mm
            nets: Net connections
            
        Returns:
            Lines of footprint definition
        """
        comp_type = component.type.value if hasattr(component.type, 'value') else str(component.type)
        effective_comp_type = self._effective_comp_type(component, comp_type)
        
        # Get footprint from library
        if hasattr(component, 'footprint') and component.footprint:
            footprint = component.footprint
        else:
            footprint = KiCadFootprintLibrary.get_footprint(effective_comp_type)
        description = KiCadFootprintLibrary.get_description(effective_comp_type)
        pads = KiCadFootprintLibrary.get_pads(effective_comp_type)
        drawings = KiCadFootprintLibrary.get_drawings(effective_comp_type)
        
        # Generate UUID for this footprint instance
        fp_uuid = self._get_uuid(f"fp_{comp_id}")
        
        # Get reference designator
        ref = comp_id.upper()
        
        # Get value
        value = self._get_component_value(component)
        
        lines = [
            f'  (footprint "{footprint}"',
            '    (layer "F.Cu")',
            f'    (uuid "{fp_uuid}")',
            f'    (at {x} {y})',
            f'    (descr "{description}")',
            f'    (property "Reference" "{ref}"',
            f'      (at 0 -3 0)',
            '      (layer "F.SilkS")',
            f'      (uuid "{self._get_uuid(f"{comp_id}_ref")}")',
            '      (effects',
            '        (font',
            '          (size 1 1)',
            '          (thickness 0.15)',
            '        )',
            '      )',
            '    )',
            f'    (property "Value" "{value}"',
            f'      (at 0 3 0)',
            '      (layer "F.Fab")',
            f'      (uuid "{self._get_uuid(f"{comp_id}_val")}")',
            '      (effects',
            '        (font',
            '          (size 1 1)',
            '          (thickness 0.15)',
            '        )',
            '      )',
            '    )',
            f'    (property "Footprint" "{footprint}"',
            '      (at 0 0 0)',
            '      (unlocked yes)',
            '      (layer "F.Fab")',
            '      (hide yes)',
            f'      (uuid "{self._get_uuid(f"{comp_id}_fp")}")',
            '      (effects',
            '        (font',
            '          (size 1.27 1.27)',
            '          (thickness 0.15)',
            '        )',
            '      )',
            '    )',
            '    (attr through_hole)',
        ]
        
        # ── Graphical items (outlines on SilkS / Fab / CrtYd) ──
        for idx, drw in enumerate(drawings):
            drw_uuid = self._get_uuid(f"{comp_id}_drw_{idx}")
            dtype = drw["type"]
            layer = drw["layer"]
            w = drw.get("width", 0.12)

            if dtype == "fp_line":
                sx, sy = drw["start"]
                ex, ey = drw["end"]
                lines.append(
                    f'    (fp_line (start {sx} {sy}) (end {ex} {ey})'
                    f' (stroke (width {w}) (type solid))'
                    f' (layer "{layer}") (uuid "{drw_uuid}"))'
                )
            elif dtype == "fp_circle":
                cx, cy = drw["center"]
                rx, ry = drw["end"]
                lines.append(
                    f'    (fp_circle (center {cx} {cy}) (end {rx} {ry})'
                    f' (stroke (width {w}) (type solid))'
                    f' (fill none)'
                    f' (layer "{layer}") (uuid "{drw_uuid}"))'
                )
            elif dtype == "fp_arc":
                sx, sy = drw["start"]
                mx, my = drw["mid"]
                ex, ey = drw["end"]
                lines.append(
                    f'    (fp_arc (start {sx} {sy}) (mid {mx} {my}) (end {ex} {ey})'
                    f' (stroke (width {w}) (type solid))'
                    f' (layer "{layer}") (uuid "{drw_uuid}"))'
                )
        
        # ── Pads ───────────────────────────────────────────────
        for pad in pads:
            pad_net = self._find_pad_net(comp_id, pad["number"], effective_comp_type, nets)
            net_idx = self._net_map.get(pad_net, 0)
            
            lines.extend([
                f'    (pad "{pad["number"]}" {pad["type"]} {pad["shape"]}',
                f'      (at {pad["at"][0]} {pad["at"][1]})',
                f'      (size {pad["size"][0]} {pad["size"][1]})',
                f'      (drill {pad["drill"]})',
                '      (layers "*.Cu" "*.Mask")',
                f'      (net {net_idx} "{pad_net}")',
                f'      (uuid "{self._get_uuid(f"{comp_id}_pad_{pad["number"]}")}")',
                '    )',
            ])
        
        lines.append("  )")
        
        return lines

    def _effective_comp_type(self, component, raw_type: str) -> str:
        """Map normalized one-pin sources to one-pin connector footprints on PCB."""
        ctype = (raw_type or "").lower()
        pins = getattr(component, "pins", ()) or ()
        if ctype in {"voltage_source", "current_source"} and len(pins) <= 1:
            return "connector"
        return ctype
    
    def _get_component_value(self, component) -> str:
        """Extract component value for display."""
        if hasattr(component, 'value') and component.value:
            return str(component.value)
        if hasattr(component, 'model') and component.model:
            return str(component.model)
        return str(component.type.value).upper()
    
    def _find_pad_net(
        self,
        comp_id: str,
        pad_num: str,
        comp_type: str,
        nets: Dict[str, List[str]]
    ) -> str:
        """Find which net a component pad is connected to.
        
        Nets use domain pin names (e.g. Q1.C, Q1.B, Q1.E) while footprints
        use pad numbers (1, 2, 3).  We try both the pad number directly
        and the reverse-mapped domain pin name(s).
        
        Args:
            comp_id: Component ID
            pad_num: Pad number (footprint)
            comp_type: Component type string for pin_map lookup
            nets: Net definitions {net_name -> [comp_id.pin, ...]}
            
        Returns:
            Net name or empty string
        """
        # Build reverse map: pad_number -> list of domain pin names
        pin_map = KiCadFootprintLibrary.get_pin_map(comp_type)
        reverse_map: Dict[str, List[str]] = {}
        for pin_name, mapped_pad in pin_map.items():
            reverse_map.setdefault(mapped_pad, []).append(pin_name)

        # Candidate references to look for in nets
        candidates = {f"{comp_id}.{pad_num}"}
        for domain_pin in reverse_map.get(pad_num, []):
            candidates.add(f"{comp_id}.{domain_pin}")

        for net_name, connections in nets.items():
            for candidate in candidates:
                if candidate in connections:
                    return net_name
        return ""
    
    def _build_tracks(self, tracks: List[Dict]) -> List[str]:
        """Build PCB track definitions.
        
        Args:
            tracks: List of track definitions with start, end, net, layer, width
            
        Returns:
            Lines of track definitions
        """
        lines = []
        for track in tracks:
            start_x, start_y = track["start"]
            end_x, end_y = track["end"]
            net_name = track.get("net", "")
            net_idx = self._net_map.get(net_name, 0)
            layer = track.get("layer", "F.Cu")
            width = track.get("width", 0.25)
            
            track_uuid = self._get_uuid(f"track_{start_x}_{start_y}_{end_x}_{end_y}")
            
            lines.extend([
                "  (segment",
                f'    (start {start_x} {start_y})',
                f'    (end {end_x} {end_y})',
                f'    (width {width})',
                f'    (layer "{layer}")',
                f'    (net {net_idx})',
                f'    (uuid "{track_uuid}")',
                "  )",
            ])
        
        return lines
    
    def _build_zones(self) -> List[str]:
        """Build zone definitions (e.g., ground plane).
        
        Returns:
            Lines of zone definitions (empty for now)
        """
        # For basic implementation, we skip zones
        # Can be added later for ground/power planes
        return []
    
    def _get_uuid(self, key: str) -> str:
        """Get or generate UUID for a component.
        
        Args:
            key: Unique key for the element
            
        Returns:
            UUID string
        """
        if key not in self._uuid_cache:
            self._uuid_cache[key] = str(uuid.uuid4())
        return self._uuid_cache[key]
