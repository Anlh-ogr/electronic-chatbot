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

import logging
# typing: Type hints cho PCB s-expression generation
# uuid: Unique IDs cho nets/segments
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

# ====== Domain & Infrastructure layers ======
from app.domains.circuits.entities import Circuit
from app.domains.circuits.ir import CircuitIR
from app.infrastructure.exporters.kicad_footprint_library import KiCadFootprintLibrary

logger = logging.getLogger(__name__)

# ── Footprint map keyed by reference-designator prefix ──────────────────────
# Used as the primary footprint override: takes priority over the type-based
# library lookup so common passives and ICs always get the correct footprint.
_FOOTPRINT_BY_REF_PREFIX: Dict[str, str] = {
    "R": "Resistor_SMD:R_0805_2012Metric",
    "C": "Capacitor_SMD:C_0805_2012Metric",
    "L": "Inductor_SMD:L_0805_2012Metric",
    "U": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "J": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
    "Q": "Package_TO_SOT_THT:TO-92_Inline",
    "D": "Diode_THT:D_DO-35_SOD27_P7.62mm_Horizontal",
    "SW": "Button_Switch_THT:SW_Push_6mm_H5mm",
}

# ── Component types that must NOT appear as physical footprints on a PCB ─────
_POWER_COMPONENT_TYPES: Set[str] = {
    "ground",
    "power_symbol",
    "power_supply",
}

# ── Reference prefixes / exact names that indicate schematic-only symbols ────
_POWER_REF_EXACT: Set[str] = {
    "VCC", "VEE", "VDD", "VSS", "GND", "AGND", "DGND",
    "+15V", "-15V", "+5V", "-5V", "+3V3", "+12V", "-12V",
    "PWR_FLAG",
}


def _is_power_component(comp_id: str, comp_type_value: str) -> bool:
    """Return True when the component is schematic-only (no physical PCB footprint)."""
    ref = comp_id.upper().strip()
    if ref in _POWER_REF_EXACT:
        return True
    if ref.startswith("PWR") or ref.startswith("#PWR"):
        return True
    ctype = (comp_type_value or "").lower()
    return ctype in _POWER_COMPONENT_TYPES


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
        tracks: List[Dict],
        board_size: Optional[Tuple[float, float]] = None,
        zones: Optional[List[Dict[str, Any]]] = None,
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

        # Pre-compute pad→net map once for the whole board so each
        # _build_footprint call can do an O(1) lookup.
        pad_net_map = self._build_pad_net_map(nets)

        # Build net map (must happen after filtering power symbols so indices
        # match only the nets carried by physical components)
        self._build_net_map(nets)
        
        lines = []
        
        # Header
        lines.extend(self._build_header())
        lines.append("")
        
        # Nets
        lines.extend(self._build_nets())
        lines.append("")
        
        # Footprints (component instances) — skip schematic-only power symbols
        skipped_power: List[str] = []
        for comp_id, component in circuit.components.items():
            comp_type_val = (
                component.type.value
                if hasattr(component.type, "value")
                else str(component.type)
            )
            if _is_power_component(comp_id, comp_type_val):
                skipped_power.append(comp_id)
                continue
            if comp_id in placements:
                x, y = placements[comp_id]
                lines.extend(self._build_footprint(
                    comp_id, component, x, y, nets, pad_net_map
                ))
                lines.append("")

        if skipped_power:
            logger.debug(
                "PCB serializer: skipped %d power/schematic-only symbols: %s",
                len(skipped_power),
                skipped_power,
            )

        if board_size is not None:
            lines.extend(self._build_board_outline(board_size))
            lines.append("")
        
        # Tracks (PCB traces)
        if tracks:
            lines.extend(self._build_tracks(tracks))
            lines.append("")
        
        # Zones (copper pours) - optional, can add GND plane
        lines.extend(self._build_zones(zones or [], board_size))
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
        nets: Dict[str, List[str]],
        pad_net_map: Optional[Dict[tuple, str]] = None,
    ) -> List[str]:
        """Build footprint instance for a component.

        Args:
            comp_id: Component ID
            component: Component entity
            x, y: Position in mm
            nets: Net connections {net_name -> [comp_id.pin, ...]}
            pad_net_map: Pre-built (comp_id, pad_num) -> net_name map
        """
        if pad_net_map is None:
            pad_net_map = self._build_pad_net_map(nets)

        comp_type = component.type.value if hasattr(component.type, 'value') else str(component.type)
        effective_comp_type = self._effective_comp_type(component, comp_type)

        # ── Footprint selection priority ────────────────────────────────────
        # 1. Explicit footprint attr on the component (comes from KiCad sync)
        # 2. Ref-prefix lookup (R→Resistor_SMD, C→Capacitor_SMD, Q→TO-92, …)
        # 3. Type-based library lookup (opamp, bjt_npn, mosfet_n, …)
        ref = comp_id.upper()
        ref_prefix = ref[0] if ref else "X"

        if hasattr(component, 'footprint') and component.footprint:
            footprint = component.footprint
        elif ref_prefix in _FOOTPRINT_BY_REF_PREFIX:
            footprint = _FOOTPRINT_BY_REF_PREFIX[ref_prefix]
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
            # Primary: direct lookup using the pre-built map
            pad_net = pad_net_map.get((comp_id, pad["number"]), "")
            if not pad_net:
                # Fallback: try case-insensitive ref and try domain pin names
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

    def _build_pad_net_map(
        self, nets: Dict[str, List[str]]
    ) -> Dict[tuple, str]:
        """Build a (comp_id, pad_num) -> net_name map from the nets dict.

        Handles both dot-separated ("R1.1") and colon-separated ("R1:1") pin
        references and resolves domain pin names to pad numbers via the
        footprint library's pin_map.

        The returned keys use the ORIGINAL comp_id casing from the nets dict
        and the footprint pad number (a string like "1", "2", "3").
        """
        result: Dict[tuple, str] = {}
        # Also build a case-folded shadow so _find_pad_net can try upper-case refs
        upper_result: Dict[tuple, str] = {}

        for net_name, pin_refs in nets.items():
            for pin_ref in pin_refs:
                # Normalise separator: accept "R1.1" or "R1:1"
                if "." in pin_ref:
                    cid, pin_name = pin_ref.split(".", 1)
                elif ":" in pin_ref:
                    cid, pin_name = pin_ref.split(":", 1)
                else:
                    continue

                # Record using the domain pin name as the pad key (direct match
                # works for resistors/capacitors where pin names ARE pad numbers)
                key = (cid, pin_name)
                if key not in result:
                    result[key] = net_name

                # Also try to resolve the domain pin name to a footprint pad
                # number via the component type's pin_map.  We don't know the
                # comp type here, so we store an upper-case version and the
                # per-type resolution happens in _find_pad_net as fallback.
                upper_key = (cid.upper(), pin_name.upper())
                if upper_key not in upper_result:
                    upper_result[upper_key] = net_name

        # Merge upper-case shadow into result (won't override original casing entries)
        for k, v in upper_result.items():
            if k not in result:
                result[k] = v

        return result

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
        nets: Dict[str, List[str]],
    ) -> str:
        """Find which net a pad belongs to (fallback used after pad_net_map miss).

        Builds candidate pin-reference strings for the given (comp_id, pad_num)
        and searches the nets dict.  Handles:
        - dot vs colon separator in net pin refs
        - domain pin names vs pad numbers (via footprint library pin_map)
        - case-insensitive component-id matching
        """
        pin_map = KiCadFootprintLibrary.get_pin_map(comp_type)
        # pad_number → [domain_pin_name, ...]
        reverse_map: Dict[str, List[str]] = {}
        for pin_name, mapped_pad in pin_map.items():
            reverse_map.setdefault(str(mapped_pad), []).append(pin_name)

        # Build all candidate strings we might find in the nets dict
        domain_pins = reverse_map.get(str(pad_num), [])
        candidate_pins: List[str] = [pad_num] + domain_pins

        candidates: set = set()
        for sep in (".", ":"):
            for cid in (comp_id, comp_id.upper(), comp_id.lower()):
                for p in candidate_pins:
                    candidates.add(f"{cid}{sep}{p}")
                    candidates.add(f"{cid}{sep}{p.upper()}")

        # Flat set of all net pin-refs for fast membership test
        all_refs: Dict[str, str] = {}
        for net_name, connections in nets.items():
            for conn in connections:
                if conn not in all_refs:
                    all_refs[conn] = net_name
                # Also normalise separator and case to handle mismatches
                norm = conn.replace(":", ".").upper()
                if norm not in all_refs:
                    all_refs[norm] = net_name

        for cand in candidates:
            net = all_refs.get(cand) or all_refs.get(cand.replace(":", ".").upper())
            if net:
                return net
        return ""
    
    def _build_tracks(self, tracks: List[Dict]) -> List[str]:
        """Build PCB track and via definitions.

        Accepts two entry formats in the `tracks` list:
        - Segment: {"start": (x,y), "end": (x,y), "net": ..., "layer": ..., "width": ...}
        - Standalone via: {"via": True, "x": float, "y": float, "net": ..., "layer": ...}
        """
        lines = []
        for track in tracks:
            # ── Standalone via emitted by two-layer router ──────────────────
            if track.get("via"):
                net_name = track.get("net", "")
                net_idx = self._net_map.get(net_name, 0)
                vx = float(track.get("x", 0))
                vy = float(track.get("y", 0))
                via_uuid = self._get_uuid(f"via_standalone_{vx}_{vy}_{net_name}")
                lines.extend([
                    "  (via",
                    f'    (at {vx} {vy})',
                    '    (size 0.8)',
                    '    (drill 0.4)',
                    '    (layers "F.Cu" "B.Cu")',
                    f'    (net {net_idx})',
                    f'    (uuid "{via_uuid}")',
                    "  )",
                ])
                continue

            # ── Normal segment ───────────────────────────────────────────────
            start_x, start_y = track["start"]
            end_x, end_y = track["end"]
            net_name = track.get("net", "")
            net_idx = self._net_map.get(net_name, 0)
            layer = track.get("layer", "F.Cu")
            width = track.get("width", 0.5 if self._is_power_net(net_name) else 0.25)

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

            for via_index, (vx, vy) in enumerate(self._extract_vias(track)):
                via_uuid = self._get_uuid(f"via_{start_x}_{start_y}_{end_x}_{end_y}_{via_index}")
                lines.extend([
                    "  (via",
                    f'    (at {vx} {vy})',
                    '    (size 0.8)',
                    '    (drill 0.4)',
                    '    (layers "F.Cu" "B.Cu")',
                    f'    (net {net_idx})',
                    f'    (uuid "{via_uuid}")',
                    "  )",
                ])

        return lines
    
    def _build_zones(
        self,
        zones: List[Dict[str, Any]],
        board_size: Optional[Tuple[float, float]],
    ) -> List[str]:
        """Build zone definitions (e.g., ground plane).
        
        Returns:
            Lines of zone definitions.
        """
        outline = self._zone_outline(board_size)
        lines: List[str] = []
        zone_specs = list(zones) if zones else self._default_ground_zones(outline)

        for zone in zone_specs:
            net_name = str(zone.get("net", "")).strip()
            if not net_name or not self._is_ground_net(net_name):
                continue

            polygon = zone.get("polygon") or outline
            if not polygon:
                continue

            net_idx = self._net_map.get(net_name, 0)
            layer = str(zone.get("layer", "B.Cu"))
            clearance = float(zone.get("clearance", 0.3))
            zone_uuid = self._get_uuid(f"zone_{net_name}_{layer}")

            lines.extend([
                "  (zone",
                f'    (net {net_idx})',
                f'    (net_name "{net_name}")',
                f'    (layer "{layer}")',
                '    (hatch edge 0.508)',
                '    (priority 1)',
                f'    (connect_pads (clearance {clearance}))',
                '    (min_thickness 0.25)',
                '    (filled_areas_thickness no)',
                '    (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))',
                f'    (uuid "{zone_uuid}")',
                '    (polygon',
                '      (pts',
            ])
            for x, y in polygon:
                lines.append(f'        (xy {x} {y})')
            lines.extend([
                '      )',
                '    )',
                '  )',
            ])

        return lines

    def _default_ground_zones(self, outline: List[Tuple[float, float]]) -> List[Dict[str, Any]]:
        if not outline:
            return []
        for net_name in self._net_map:
            if self._is_ground_net(net_name):
                return [{
                    "net": net_name,
                    "layer": "B.Cu",
                    "clearance": 0.3,
                    "polygon": outline,
                }]
        if "0" in self._net_map:
            return [{
                "net": "0",
                "layer": "B.Cu",
                "clearance": 0.3,
                "polygon": outline,
            }]
        return []

    def _build_board_outline(self, board_size: Tuple[float, float]) -> List[str]:
        width, height = board_size
        return [
            f'  (gr_rect (start 0 0) (end {width} {height}) (layer "Edge.Cuts") (stroke (width 0.1) (type solid)) (fill none))'
        ]

    def _zone_outline(self, board_size: Optional[Tuple[float, float]]) -> List[Tuple[float, float]]:
        if not board_size:
            return []
        width, height = board_size
        return [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)]

    def _extract_vias(self, track: Dict[str, Any]) -> List[Tuple[float, float]]:
        vias: List[Tuple[float, float]] = []
        raw_vias = track.get("vias") or track.get("via_positions") or []
        for entry in raw_vias:
            if isinstance(entry, dict) and "x" in entry and "y" in entry:
                vias.append((float(entry["x"]), float(entry["y"])))
            elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                vias.append((float(entry[0]), float(entry[1])))
        return vias

    def _is_power_net(self, net_name: str) -> bool:
        name = net_name.strip().lower()
        return any(token in name for token in ("vcc", "vdd", "v+", "vbat", "power", "vin", "vout"))

    def _is_ground_net(self, net_name: str) -> bool:
        name = net_name.strip().lower()
        return name in {"gnd", "ground", "0", "0v", "vss"} or "gnd" in name or "ground" in name
    
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
