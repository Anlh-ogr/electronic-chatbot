# .\\thesis\\electronic-chatbot\\apps\\api\\app\\infrastructure\\exporters\\kicad_footprint_library.py
"""Thư viện chân linh kiện KiCad (Footprint Library) - Ánh xạ các chân linh kiện.

Module này cung cấp các định nghĩa chân linh kiện (pad definitions) cho PCB export.
Nó ánh xạ các loại component tới tiêu chuẩn KiCad footprint libraries.

Mỗi chân linh kiện bao gồm:
- Pad definitions (position, size, drill, shape)
- Silkscreen outlines (F.SilkS) để nhận diện hình dạng
- Fabrication layer outlines (F.Fab)
- Courtyard boundaries (F.CrtYd)
- Pin-to-pad mapping (schematic pin name → pad number)

Vietnamese:
- Trách nhiệm: Quản lý footprint definitions và pad layouts
- Đầu ra: Pad + layer definitions cho KiCad PCB export
- Tiêu chuẩn: KiCad 8 standard footprints

English:
- Responsibility: Manage footprint definitions and pad layouts
- Output: Pad + layer definitions for KiCad PCB export
- Standard: KiCad 8 standard footprints
"""

import math
from typing import Dict, List, Optional, Tuple


# ====== Outline Drawing Helpers ======
# Các hàm hỗ trợ vẽ outline silkscreen + fabrication layers

def _rect(x1: float, y1: float, x2: float, y2: float,
          layer: str, w: float = 0.12) -> List[Dict]:
    """Rectangle as 4 fp_line segments."""
    return [
        {"type": "fp_line", "start": (x1, y1), "end": (x2, y1), "layer": layer, "width": w},
        {"type": "fp_line", "start": (x2, y1), "end": (x2, y2), "layer": layer, "width": w},
        {"type": "fp_line", "start": (x2, y2), "end": (x1, y2), "layer": layer, "width": w},
        {"type": "fp_line", "start": (x1, y2), "end": (x1, y1), "layer": layer, "width": w},
    ]


def _circle(cx: float, cy: float, r: float,
            layer: str, w: float = 0.12) -> List[Dict]:
    """Circle as fp_circle."""
    return [{"type": "fp_circle", "center": (cx, cy),
             "end": (cx + r, cy), "layer": layer, "width": w}]


def _arc(cx: float, cy: float, r: float,
         a0: float, a1: float, layer: str, w: float = 0.12) -> List[Dict]:
    """Arc from angle a0 to a1 (degrees) as fp_arc with start/mid/end."""
    sx = cx + r * math.cos(math.radians(a0))
    sy = cy + r * math.sin(math.radians(a0))
    mx = cx + r * math.cos(math.radians((a0 + a1) / 2))
    my = cy + r * math.sin(math.radians((a0 + a1) / 2))
    ex = cx + r * math.cos(math.radians(a1))
    ey = cy + r * math.sin(math.radians(a1))
    return [{"type": "fp_arc", "start": (sx, sy), "mid": (mx, my),
             "end": (ex, ey), "layer": layer, "width": w}]


def _line(x1, y1, x2, y2, layer, w=0.12):
    """Single fp_line."""
    return {"type": "fp_line", "start": (x1, y1), "end": (x2, y2),
            "layer": layer, "width": w}


# ──────────────────────────────────────────────────────
# Footprint definitions  (type → dict)
# ──────────────────────────────────────────────────────
#   "footprint"  – KiCad library:name
#   "description"
#   "pads"       – list of pad dicts
#   "drawings"   – list of graphical items (fp_line / fp_circle / fp_arc)
#   "pin_map"    – schematic pin name → footprint pad number

_FOOTPRINT_DEFS: Dict[str, Dict] = {

    # ── Resistor (Axial, 10.16 mm pitch) ───────────────────────
    "resistor": {
        "footprint": "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
        "description": "Resistor, Through-Hole, Axial",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "circle",
             "at": (0, 0), "size": (1.6, 1.6), "drill": 0.8},
            {"number": "2", "type": "thru_hole", "shape": "oval",
             "at": (10.16, 0), "size": (1.6, 1.6), "drill": 0.8},
        ],
        "drawings": [
            *_rect(1.93, -1.25, 8.23, 1.25, "F.SilkS"),
            _line(0, 0, 1.93, 0, "F.SilkS"),
            _line(8.23, 0, 10.16, 0, "F.SilkS"),
            *_rect(1.93, -1.25, 8.23, 1.25, "F.Fab", 0.10),
            *_rect(-1.05, -1.65, 11.21, 1.65, "F.CrtYd", 0.05),
        ],
        "pin_map": {"1": "1", "2": "2"},
    },

    # ── Capacitor Disc (5 mm pitch) ────────────────────────────
    "capacitor": {
        "footprint": "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm",
        "description": "Capacitor, Disc, Through-Hole",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "circle",
             "at": (0, 0), "size": (1.6, 1.6), "drill": 0.8},
            {"number": "2", "type": "thru_hole", "shape": "circle",
             "at": (5.0, 0), "size": (1.6, 1.6), "drill": 0.8},
        ],
        "drawings": [
            *_circle(2.5, 0, 2.5, "F.SilkS"),
            *_circle(2.5, 0, 2.5, "F.Fab", 0.10),
            *_rect(-1.05, -2.9, 6.05, 2.9, "F.CrtYd", 0.05),
        ],
        "pin_map": {"1": "1", "2": "2"},
    },

    # ── Capacitor Electrolytic Radial (2.5 mm pitch) ──────────
    "capacitor_polarized": {
        "footprint": "Capacitor_THT:CP_Radial_D5.0mm_P2.50mm",
        "description": "Capacitor, Electrolytic, Radial",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "rect",
             "at": (0, 0), "size": (1.6, 1.6), "drill": 0.8},
            {"number": "2", "type": "thru_hole", "shape": "circle",
             "at": (2.5, 0), "size": (1.6, 1.6), "drill": 0.8},
        ],
        "drawings": [
            *_circle(1.25, 0, 2.5, "F.SilkS"),
            # + marker near pad 1
            _line(-1.0, -0.5, -1.0, 0.5, "F.SilkS"),
            _line(-1.5, 0, -0.5, 0, "F.SilkS"),
            *_circle(1.25, 0, 2.5, "F.Fab", 0.10),
            *_rect(-1.55, -2.8, 4.05, 2.8, "F.CrtYd", 0.05),
        ],
        "pin_map": {"1": "1", "2": "2"},
    },

    # ── BJT NPN TO-92 (E‐B‐C inline) ─────────────────────────
    "bjt_npn": {
        "footprint": "Package_TO_SOT_THT:TO-92_Inline",
        "description": "BJT NPN, TO-92 package",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "rect",
             "at": (0, 0), "size": (1.05, 1.5), "drill": 0.75},
            {"number": "2", "type": "thru_hole", "shape": "oval",
             "at": (1.27, 0), "size": (1.05, 1.5), "drill": 0.75},
            {"number": "3", "type": "thru_hole", "shape": "oval",
             "at": (2.54, 0), "size": (1.05, 1.5), "drill": 0.75},
        ],
        "drawings": [
            # D-shape outline (flat + semicircle)
            _line(1.27, -2.2, 1.27, 2.2, "F.SilkS"),
            *_arc(1.27, 0, 2.2, -90, 90, "F.SilkS"),
            _line(1.27, -2.2, 1.27, 2.2, "F.Fab", 0.10),
            *_arc(1.27, 0, 2.2, -90, 90, "F.Fab", 0.10),
            *_rect(-1.15, -2.55, 3.69, 2.55, "F.CrtYd", 0.05),
        ],
        "pin_map": {"E": "1", "B": "2", "C": "3"},
    },

    # ── BJT PNP TO-92 ─────────────────────────────────────────
    "bjt_pnp": {
        "footprint": "Package_TO_SOT_THT:TO-92_Inline",
        "description": "BJT PNP, TO-92 package",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "rect",
             "at": (0, 0), "size": (1.05, 1.5), "drill": 0.75},
            {"number": "2", "type": "thru_hole", "shape": "oval",
             "at": (1.27, 0), "size": (1.05, 1.5), "drill": 0.75},
            {"number": "3", "type": "thru_hole", "shape": "oval",
             "at": (2.54, 0), "size": (1.05, 1.5), "drill": 0.75},
        ],
        "drawings": [
            _line(1.27, -2.2, 1.27, 2.2, "F.SilkS"),
            *_arc(1.27, 0, 2.2, -90, 90, "F.SilkS"),
            _line(1.27, -2.2, 1.27, 2.2, "F.Fab", 0.10),
            *_arc(1.27, 0, 2.2, -90, 90, "F.Fab", 0.10),
            *_rect(-1.15, -2.55, 3.69, 2.55, "F.CrtYd", 0.05),
        ],
        "pin_map": {"E": "1", "B": "2", "C": "3"},
    },

    # ── MOSFET N-ch TO-220 ─────────────────────────────────────
    "mosfet_n": {
        "footprint": "Package_TO_SOT_THT:TO-220-3_Vertical",
        "description": "MOSFET N-channel, TO-220",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "rect",
             "at": (0, 0), "size": (1.7, 1.7), "drill": 1.0},
            {"number": "2", "type": "thru_hole", "shape": "oval",
             "at": (2.54, 0), "size": (1.7, 1.7), "drill": 1.0},
            {"number": "3", "type": "thru_hole", "shape": "oval",
             "at": (5.08, 0), "size": (1.7, 1.7), "drill": 1.0},
        ],
        "drawings": [
            *_rect(-2.2, -3.5, 7.28, 3.5, "F.SilkS"),
            _line(-2.2, -1.5, 7.28, -1.5, "F.SilkS"),
            *_rect(-2.2, -3.5, 7.28, 3.5, "F.Fab", 0.10),
            *_rect(-2.55, -3.85, 7.63, 3.85, "F.CrtYd", 0.05),
        ],
        "pin_map": {"G": "1", "D": "2", "S": "3"},
    },

    # ── MOSFET P-ch TO-220 ─────────────────────────────────────
    "mosfet_p": {
        "footprint": "Package_TO_SOT_THT:TO-220-3_Vertical",
        "description": "MOSFET P-channel, TO-220",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "rect",
             "at": (0, 0), "size": (1.7, 1.7), "drill": 1.0},
            {"number": "2", "type": "thru_hole", "shape": "oval",
             "at": (2.54, 0), "size": (1.7, 1.7), "drill": 1.0},
            {"number": "3", "type": "thru_hole", "shape": "oval",
             "at": (5.08, 0), "size": (1.7, 1.7), "drill": 1.0},
        ],
        "drawings": [
            *_rect(-2.2, -3.5, 7.28, 3.5, "F.SilkS"),
            _line(-2.2, -1.5, 7.28, -1.5, "F.SilkS"),
            *_rect(-2.2, -3.5, 7.28, 3.5, "F.Fab", 0.10),
            *_rect(-2.55, -3.85, 7.63, 3.85, "F.CrtYd", 0.05),
        ],
        "pin_map": {"G": "1", "D": "2", "S": "3"},
    },

    # ── OpAmp DIP-8 ────────────────────────────────────────────
    "opamp": {
        "footprint": "Package_DIP:DIP-8_W7.62mm",
        "description": "Operational Amplifier, DIP-8",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "rect",
             "at": (0, 0), "size": (1.6, 1.6), "drill": 0.8},
            {"number": "2", "type": "thru_hole", "shape": "oval",
             "at": (0, 2.54), "size": (1.6, 1.6), "drill": 0.8},
            {"number": "3", "type": "thru_hole", "shape": "oval",
             "at": (0, 5.08), "size": (1.6, 1.6), "drill": 0.8},
            {"number": "4", "type": "thru_hole", "shape": "oval",
             "at": (0, 7.62), "size": (1.6, 1.6), "drill": 0.8},
            {"number": "5", "type": "thru_hole", "shape": "oval",
             "at": (7.62, 7.62), "size": (1.6, 1.6), "drill": 0.8},
            {"number": "6", "type": "thru_hole", "shape": "oval",
             "at": (7.62, 5.08), "size": (1.6, 1.6), "drill": 0.8},
            {"number": "7", "type": "thru_hole", "shape": "oval",
             "at": (7.62, 2.54), "size": (1.6, 1.6), "drill": 0.8},
            {"number": "8", "type": "thru_hole", "shape": "oval",
             "at": (7.62, 0), "size": (1.6, 1.6), "drill": 0.8},
        ],
        "drawings": [
            *_rect(-1.27, -1.27, 8.89, 8.89, "F.SilkS"),
            # Notch + pin-1 dot
            *_arc(-1.27, 0, 1.0, -90, 90, "F.SilkS"),
            *_circle(-0.5, -0.5, 0.3, "F.SilkS"),
            *_rect(-1.27, -1.27, 8.89, 8.89, "F.Fab", 0.10),
            *_rect(-1.77, -1.77, 9.39, 9.39, "F.CrtYd", 0.05),
        ],
        "pin_map": {
            "OUT": "1", "-": "2", "+": "3", "V-": "4",
            "V+": "8", "IN-": "2", "IN+": "3",
            "1": "1", "2": "2", "3": "3", "4": "4",
            "5": "5", "6": "6", "7": "7", "8": "8",
        },
    },

    # ── Inductor Axial ─────────────────────────────────────────
    "inductor": {
        "footprint": "Inductor_THT:L_Axial_L5.3mm_D2.2mm_P10.16mm_Horizontal",
        "description": "Inductor, Through-Hole, Axial",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "circle",
             "at": (0, 0), "size": (1.8, 1.8), "drill": 0.9},
            {"number": "2", "type": "thru_hole", "shape": "oval",
             "at": (10.16, 0), "size": (1.8, 1.8), "drill": 0.9},
        ],
        "drawings": [
            *_rect(2.43, -1.1, 7.73, 1.1, "F.SilkS"),
            _line(0, 0, 2.43, 0, "F.SilkS"),
            _line(7.73, 0, 10.16, 0, "F.SilkS"),
            *_rect(2.43, -1.1, 7.73, 1.1, "F.Fab", 0.10),
            *_rect(-1.05, -1.5, 11.21, 1.5, "F.CrtYd", 0.05),
        ],
        "pin_map": {"1": "1", "2": "2"},
    },

    # ── Diode DO-35 ────────────────────────────────────────────
    "diode": {
        "footprint": "Diode_THT:D_DO-35_SOD27_P7.62mm_Horizontal",
        "description": "Diode, DO-35, Through-Hole",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "rect",
             "at": (0, 0), "size": (1.6, 1.6), "drill": 0.8},
            {"number": "2", "type": "thru_hole", "shape": "oval",
             "at": (7.62, 0), "size": (1.6, 1.6), "drill": 0.8},
        ],
        "drawings": [
            *_rect(1.5, -1.1, 6.12, 1.1, "F.SilkS"),
            # cathode band
            _line(1.5, -1.1, 1.5, 1.1, "F.SilkS", 0.25),
            _line(0, 0, 1.5, 0, "F.SilkS"),
            _line(6.12, 0, 7.62, 0, "F.SilkS"),
            *_rect(1.5, -1.1, 6.12, 1.1, "F.Fab", 0.10),
            *_rect(-1.05, -1.5, 8.67, 1.5, "F.CrtYd", 0.05),
        ],
        "pin_map": {"A": "1", "K": "2", "1": "1", "2": "2"},
    },

    # ── LED 5 mm ───────────────────────────────────────────────
    "led": {
        "footprint": "LED_THT:LED_D5.0mm",
        "description": "LED, 5 mm, Through-Hole",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "rect",
             "at": (0, 0), "size": (1.8, 1.8), "drill": 0.9},
            {"number": "2", "type": "thru_hole", "shape": "circle",
             "at": (2.54, 0), "size": (1.8, 1.8), "drill": 0.9},
        ],
        "drawings": [
            *_circle(1.27, 0, 2.5, "F.SilkS"),
            *_circle(1.27, 0, 2.5, "F.Fab", 0.10),
            *_rect(-1.55, -2.85, 4.09, 2.85, "F.CrtYd", 0.05),
        ],
        "pin_map": {"A": "1", "K": "2", "1": "1", "2": "2"},
    },

    # ── Voltage Source (Pin Header 1×02) ───────────────────────
    "voltage_source": {
        "footprint": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
        "description": "Voltage Source (Pin Header 1x02)",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "rect",
             "at": (0, 0), "size": (1.7, 1.7), "drill": 1.0},
            {"number": "2", "type": "thru_hole", "shape": "oval",
             "at": (0, 2.54), "size": (1.7, 1.7), "drill": 1.0},
        ],
        "drawings": [
            *_rect(-1.33, -1.33, 1.33, 3.87, "F.SilkS"),
            *_rect(-1.33, -1.33, 1.33, 3.87, "F.Fab", 0.10),
            *_rect(-1.8, -1.8, 1.8, 4.34, "F.CrtYd", 0.05),
        ],
        "pin_map": {"+": "1", "-": "2", "1": "1", "2": "2"},
    },

    # ── Current Source (same form factor) ──────────────────────
    "current_source": {
        "footprint": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
        "description": "Current Source (Pin Header 1x02)",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "rect",
             "at": (0, 0), "size": (1.7, 1.7), "drill": 1.0},
            {"number": "2", "type": "thru_hole", "shape": "oval",
             "at": (0, 2.54), "size": (1.7, 1.7), "drill": 1.0},
        ],
        "drawings": [
            *_rect(-1.33, -1.33, 1.33, 3.87, "F.SilkS"),
            *_rect(-1.33, -1.33, 1.33, 3.87, "F.Fab", 0.10),
            *_rect(-1.8, -1.8, 1.8, 4.34, "F.CrtYd", 0.05),
        ],
        "pin_map": {"+": "1", "-": "2", "1": "1", "2": "2"},
    },

    # ── Ground (Pin Header 1×01) ──────────────────────────────
    "ground": {
        "footprint": "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical",
        "description": "Ground Connection (Pin Header 1x01)",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "circle",
             "at": (0, 0), "size": (1.7, 1.7), "drill": 1.0},
        ],
        "drawings": [
            *_rect(-1.33, -1.33, 1.33, 1.33, "F.SilkS"),
            *_rect(-1.33, -1.33, 1.33, 1.33, "F.Fab", 0.10),
            *_rect(-1.8, -1.8, 1.8, 1.8, "F.CrtYd", 0.05),
        ],
        "pin_map": {"GND": "1", "1": "1"},
    },

    # ── Connector / Port (1 pin) ──────────────────────────────
    "connector": {
        "footprint": "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical",
        "description": "Connector (Pin Header 1x01)",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "rect",
             "at": (0, 0), "size": (1.7, 1.7), "drill": 1.0},
        ],
        "drawings": [
            *_rect(-1.33, -1.33, 1.33, 1.33, "F.SilkS"),
            *_rect(-1.33, -1.33, 1.33, 1.33, "F.Fab", 0.10),
            *_rect(-1.8, -1.8, 1.8, 1.8, "F.CrtYd", 0.05),
        ],
        "pin_map": {"IN": "1", "OUT": "1", "1": "1"},
    },

    # ── Port (alias for connector) ────────────────────────────
    "port": {
        "footprint": "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical",
        "description": "Port (Pin Header 1x01)",
        "pads": [
            {"number": "1", "type": "thru_hole", "shape": "rect",
             "at": (0, 0), "size": (1.7, 1.7), "drill": 1.0},
        ],
        "drawings": [
            *_rect(-1.33, -1.33, 1.33, 1.33, "F.SilkS"),
            *_rect(-1.33, -1.33, 1.33, 1.33, "F.Fab", 0.10),
            *_rect(-1.8, -1.8, 1.8, 1.8, "F.CrtYd", 0.05),
        ],
        "pin_map": {"IN": "1", "OUT": "1", "1": "1"},
    },
}

# Aliases for enum names that differ from the keys above
_ALIASES: Dict[str, str] = {
    "bjt": "bjt_npn",
    "mosfet": "mosfet_n",
    "capacitor_electrolytic": "capacitor_polarized",
}


class KiCadFootprintLibrary:
    """Library of KiCad footprint definitions for PCB components.

    Provides pads, outline drawings (silkscreen / fab / courtyard),
    and a schematic-pin-name → pad-number mapping for each component type.
    """

    # ── Public API ─────────────────────────────────────────────

    @classmethod
    def _resolve(cls, component_type: str) -> Dict:
        """Resolve component type to its footprint definition dict."""
        key = component_type.lower()
        key = _ALIASES.get(key, key)
        return _FOOTPRINT_DEFS.get(key, _FOOTPRINT_DEFS["connector"])

    @classmethod
    def get_footprint(cls, component_type: str) -> Optional[str]:
        return cls._resolve(component_type).get("footprint")

    @classmethod
    def get_pads(cls, component_type: str) -> list:
        return cls._resolve(component_type).get("pads", [])

    @classmethod
    def get_drawings(cls, component_type: str) -> list:
        return cls._resolve(component_type).get("drawings", [])

    @classmethod
    def get_pin_map(cls, component_type: str) -> Dict[str, str]:
        """Schematic pin name → footprint pad number."""
        return cls._resolve(component_type).get("pin_map", {})

    @classmethod
    def get_description(cls, component_type: str) -> str:
        return cls._resolve(component_type).get("description", "Generic component")

    @classmethod
    def resolve_pad_number(cls, component_type: str, pin_name: str) -> str:
        """Map a schematic pin name to a pad number.

        Falls back to returning pin_name itself (works for components
        whose pin names *are* pad numbers: "1", "2", …).
        """
        return cls.get_pin_map(component_type).get(pin_name, pin_name)

    @classmethod
    def infer_footprint_from_metadata(cls, component) -> str:
        if hasattr(component, 'footprint') and component.footprint:
            return component.footprint
        comp_type = component.type.value if hasattr(component.type, 'value') else str(component.type)
        return cls.get_footprint(comp_type) or "Package_DIP:DIP-8_W7.62mm"
