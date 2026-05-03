# .\\thesis\\electronic-chatbot\\apps\\api\\app\\infrastructure\\exporters\\kicad_symbol_library.py
"""Thư viện ký hiệu KiCad (Symbol Library) - Định nghĩa ký hiệu thực tế.

Module này cung cấp các định nghĩa ký hiệu KiCad (polylines, arcs, circles,
pins) để thay thế hình chữ nhật placeholder trong quá trình xuất schematic.
Các ký hiệu này được lấy từ KiCad 8 standard libraries.

Vietnamese:
- Trách nhiệm: Cung cấp định nghĩa ký hiệu (graphical footprint) cho components
- Nguồn: KiCad 8 standard symbol libraries
- Đầu ra: Symbol definitions với pins, body, reference labels

English:
- Responsibility: Provide symbol definitions (graphical footprints) for components
- Source: KiCad 8 standard symbol libraries
- Output: Symbol definitions with pins, body, reference labels
"""

from typing import Dict, List, Tuple


# ====== Symbol & Component Definitions ======
class KiCadSymbolLibrary:
    """Thư viện ký hiệu KiCad với các định nghĩa đồ họa phù hợp.
    
    Class này quản lý tập hợp các định nghĩa ký hiệu cho các component thường gặp
    (resistors, capacitors, opamps, transistors, etc.) được lấy từ
    KiCad 8 standard libraries.
    
    Responsibilities (Trách nhiệm):
    - Cung cấp symbol definitions dựa trên component type
    - Quản lý pin positions + orientations
    - Hỗ trợ symbol scaling và rotation
    """
    
    # Symbol definitions extracted from KiCad 8 standard libraries
    SYMBOL_DEFINITIONS = {
        "resistor": {
            "lib_id": "Device:R",
            "ref_prefix": "R",
            "pins": [
                (0, 3.81, 270),    # Pin 1: top
                (0, -3.81, 90),    # Pin 2: bottom
            ],
            "graphics": [
                # Rectangle resistor symbol (vertical orientation - REAL KiCad style)
                '        (rectangle',
                '          (start -1.016 -2.54)',
                '          (end 1.016 2.54)',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },
        
        "capacitor": {
            "lib_id": "Device:C",
            "ref_prefix": "C",
            "pins": [
                (-2.54, 0, 0),     # Pin 1: left (horizontal orientation)
                (2.54, 0, 180),    # Pin 2: right (horizontal orientation)
            ],
            "graphics": [
                # Two vertical lines for capacitor - HORIZONTAL orientation
                '        (polyline',
                '          (pts',
                '            (xy -0.762 -2.032) (xy -0.762 2.032)',
                '          )',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0.762 -2.032) (xy 0.762 2.032)',
                '          )',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },
        
        "bjt": {
            "lib_id": "Transistor_BJT:BC547",
            "ref_prefix": "Q",
            "pin_length": 2.54,
            "pins": [
                (-2.54, 0, 0),       # Pin B (base) - straight horizontal
                (2.54, 2.54, 90),    # Pin C (collector) - pointing up
                (2.54, -2.54, 270),  # Pin E (emitter) - pointing down
            ],
            "graphics": [
                # Collector line from bar to collector endpoint
                '        (polyline',
                '          (pts',
                '            (xy 0.635 0.635) (xy 2.54 2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                # Emitter line from bar to emitter endpoint
                '        (polyline',
                '          (pts',
                '            (xy 0.635 -0.635) (xy 2.54 -2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                # Vertical bar (base region)
                '        (polyline',
                '          (pts',
                '            (xy 0.635 1.905) (xy 0.635 -1.905)',
                '          )',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
                # Emitter arrow
                '        (polyline',
                '          (pts',
                '            (xy 1.27 -1.778) (xy 1.778 -1.27) (xy 2.286 -2.286) (xy 1.27 -1.778)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type outline))',
                '        )',
                # Circle around transistor
                '        (circle',
                '          (center 1.27 0)',
                '          (radius 2.8194)',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },
        
        "voltage_source": {
            "lib_id": "Device:V",
            "ref_prefix": "V",
            "pins": [
                (0, 5.08, 270),    # Pin +
                (0, -5.08, 90),    # Pin -
            ],
            "graphics": [
                # Circle with + and - symbols
                '        (circle',
                '          (center 0 0)',
                '          (radius 2.54)',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type background))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0 -1.905) (xy 0 -2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0 1.905) (xy 0 2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy -0.635 1.27) (xy 0.635 1.27)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0 1.905) (xy 0 0.635)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (text "+"',
                '          (at 0 1.905 0)',
                '          (effects (font (size 1.27 1.27)))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy -0.635 -1.27) (xy 0.635 -1.27)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },
        
        "vcc": {
            "lib_id": "power:VCC",
            "ref_prefix": "#PWR",
            "is_power": True,
            "pin_type": "power_in",
            "pin_length": 0,
            "pins": [
                (0, 0, 90),
            ],
            "graphics": [
                '        (polyline',
                '          (pts',
                '            (xy 0 0) (xy 0 1.27)',
                '          )',
                '          (stroke (width 0) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy -0.762 1.27) (xy 0 2.54)',
                '          )',
                '          (stroke (width 0) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0 2.54) (xy 0.762 1.27)',
                '          )',
                '          (stroke (width 0) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },
        
        "ground": {
            "lib_id": "power:GND",
            "ref_prefix": "#PWR",
            "is_power": True,
            "pin_type": "power_in",
            "pin_length": 0,
            "pins": [
                (0, 0, 270),
            ],
            "graphics": [
                # Ground symbol - triangle shape (REAL KiCad style)
                '        (polyline',
                '          (pts',
                '            (xy 0 0) (xy 0 -1.27) (xy 1.27 -1.27) (xy 0 -2.54) (xy -1.27 -1.27) (xy 0 -1.27)',
                '          )',
                '          (stroke (width 0) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },

        "power_symbol": {
            "lib_id": "power:VCC",
            "ref_prefix": "#PWR",
            "is_power": True,
            "pin_type": "power_in",
            "pin_length": 0,
            "pins": [
                (0, 0, 90),
            ],
            "graphics": [
                '        (polyline',
                '          (pts',
                '            (xy 0 0) (xy 0 1.27)',
                '          )',
                '          (stroke (width 0) (type default))',
                '          (fill (type none))',
                '        )',
            ],
        },
        
        "port": {
            "lib_id": "Connector:Conn_01x01",
            "ref_prefix": "J",
            "pin_length": 1.27,
            "pins": [
                (-2.54, 0, 0),   # Pin pointing right, stub reaches pentagon left edge
            ],
            "graphics": [
                # Pentagon shape (like a hierarchical port)
                '        (polyline',
                '          (pts',
                '            (xy -1.27 1.27) (xy 1.27 1.27) (xy 2.54 0) (xy 1.27 -1.27) (xy -1.27 -1.27) (xy -1.27 1.27)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type background))',
                '        )',
            ]
        },
        
        "connector": {
            "lib_id": "Connector:Conn_01x01",
            "ref_prefix": "J",
            "pin_length": 1.27,
            "pins": [
                (-2.54, 0, 0),   # Pin pointing right, stub reaches pentagon left edge
            ],
            "graphics": [
                # Pentagon shape (like a hierarchical port)
                '        (polyline',
                '          (pts',
                '            (xy -1.27 1.27) (xy 1.27 1.27) (xy 2.54 0) (xy 1.27 -1.27) (xy -1.27 -1.27) (xy -1.27 1.27)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type background))',
                '        )',
            ]
        },
        
        # ── Op-Amp (5-pin: OUT, +, -, V+, V-) ──────────────────────────
        "opamp": {
            "lib_id": "Amplifier_Operational:LM358",
            "ref_prefix": "U",
            "pin_length": 2.54,
            "pins": [
                (5.08, 0, 180),      # Pin 1: OUT (right)
                (-5.08, 2.54, 0),    # Pin 2: + (non-inv, left-top)
                (-5.08, -2.54, 0),   # Pin 3: - (inv, left-bottom)
                (0, 7.62, 270),      # Pin 4: V+ (top)
                (0, -7.62, 90),      # Pin 5: V- (bottom)
            ],
            "graphics": [
                # Triangle body of op-amp
                '        (polyline',
                '          (pts',
                '            (xy -3.81 5.08) (xy -3.81 -5.08) (xy 5.08 0) (xy -3.81 5.08)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type background))',
                '        )',
                # Plus sign at non-inverting input
                '        (polyline',
                '          (pts',
                '            (xy -2.54 3.175) (xy -2.54 1.905)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy -3.175 2.54) (xy -1.905 2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                # Minus sign at inverting input
                '        (polyline',
                '          (pts',
                '            (xy -3.175 -2.54) (xy -1.905 -2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },
        
        # ── MOSFET N-channel (3-pin: D, G, S) ──────────────────────────
        "mosfet": {
            "lib_id": "Transistor_FET:Q_NMOS_DGS",
            "ref_prefix": "M",
            "pin_length": 2.54,
            "pins": [
                (2.54, 2.54, 90),    # Pin D (drain) - top
                (-2.54, 0, 0),       # Pin G (gate) - left horizontal
                (2.54, -2.54, 270),  # Pin S (source) - bottom
            ],
            "graphics": [
                # Gate vertical line
                '        (polyline',
                '          (pts',
                '            (xy 0.254 1.905) (xy 0.254 -1.905)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                # Gate connection line (horizontal from left to gate bar)
                '        (polyline',
                '          (pts',
                '            (xy 0.254 0) (xy -0.508 0)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                # Channel line segments (3 dashes)
                '        (polyline',
                '          (pts',
                '            (xy 0.762 1.778) (xy 0.762 1.016)',
                '          )',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0.762 0.381) (xy 0.762 -0.381)',
                '          )',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0.762 -1.016) (xy 0.762 -1.778)',
                '          )',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
                # Drain line
                '        (polyline',
                '          (pts',
                '            (xy 0.762 1.397) (xy 2.54 1.397) (xy 2.54 2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                # Source line
                '        (polyline',
                '          (pts',
                '            (xy 0.762 -1.397) (xy 2.54 -1.397) (xy 2.54 -2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                # Body line (connecting D and S internally)
                '        (polyline',
                '          (pts',
                '            (xy 2.54 1.397) (xy 2.54 -1.397)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                # Arrow at source (N-channel direction)
                '        (polyline',
                '          (pts',
                '            (xy 0.762 0) (xy 1.778 0.508) (xy 1.778 -0.508) (xy 0.762 0)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type outline))',
                '        )',
                # Circle around transistor
                '        (circle',
                '          (center 1.651 0)',
                '          (radius 2.8194)',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },
        
        # ── MOSFET N-channel alias ──────────────────────────────────────
        "mosfet_n": {
            "lib_id": "Transistor_FET:Q_NMOS_DGS",
            "ref_prefix": "M",
            "pin_length": 2.54,
            "pins": [
                (2.54, 2.54, 90),    # Pin D (drain) - top
                (-2.54, 0, 0),       # Pin G (gate) - left horizontal
                (2.54, -2.54, 270),  # Pin S (source) - bottom
            ],
            "graphics": [
                # Same as mosfet (NMOS)
                '        (polyline',
                '          (pts',
                '            (xy 0.254 1.905) (xy 0.254 -1.905)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0.254 0) (xy -0.508 0)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0.762 1.778) (xy 0.762 1.016)',
                '          )',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0.762 0.381) (xy 0.762 -0.381)',
                '          )',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0.762 -1.016) (xy 0.762 -1.778)',
                '          )',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0.762 1.397) (xy 2.54 1.397) (xy 2.54 2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0.762 -1.397) (xy 2.54 -1.397) (xy 2.54 -2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 2.54 1.397) (xy 2.54 -1.397)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0.762 0) (xy 1.778 0.508) (xy 1.778 -0.508) (xy 0.762 0)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type outline))',
                '        )',
                '        (circle',
                '          (center 1.651 0)',
                '          (radius 2.8194)',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },
        
        # ── MOSFET P-channel ────────────────────────────────────────────
        "mosfet_p": {
            "lib_id": "Transistor_FET:Q_PMOS_DGS",
            "ref_prefix": "M",
            "pin_length": 2.54,
            "pins": [
                (2.54, -2.54, 270),  # Pin D (drain) - bottom (P-ch: reversed)
                (-2.54, 0, 0),       # Pin G (gate) - left horizontal
                (2.54, 2.54, 90),    # Pin S (source) - top (P-ch: reversed)
            ],
            "graphics": [
                # Gate vertical line
                '        (polyline',
                '          (pts',
                '            (xy 0.254 1.905) (xy 0.254 -1.905)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0.254 0) (xy -0.508 0)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                # Channel line segments
                '        (polyline',
                '          (pts',
                '            (xy 0.762 1.778) (xy 0.762 1.016)',
                '          )',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0.762 0.381) (xy 0.762 -0.381)',
                '          )',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0.762 -1.016) (xy 0.762 -1.778)',
                '          )',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
                # Source line (top for PMOS)
                '        (polyline',
                '          (pts',
                '            (xy 0.762 1.397) (xy 2.54 1.397) (xy 2.54 2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                # Drain line (bottom for PMOS)
                '        (polyline',
                '          (pts',
                '            (xy 0.762 -1.397) (xy 2.54 -1.397) (xy 2.54 -2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                # Body line
                '        (polyline',
                '          (pts',
                '            (xy 2.54 1.397) (xy 2.54 -1.397)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                # Arrow at channel pointing OUT (P-channel direction - reversed)
                '        (polyline',
                '          (pts',
                '            (xy 1.778 0) (xy 0.762 0.508) (xy 0.762 -0.508) (xy 1.778 0)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type outline))',
                '        )',
                # Circle around transistor
                '        (circle',
                '          (center 1.651 0)',
                '          (radius 2.8194)',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },
        
        # ── BJT NPN (same as generic bjt) ───────────────────────────────
        "bjt_npn": {
            "lib_id": "Transistor_BJT:Q_NPN_BCE",
            "ref_prefix": "Q",
            "pin_length": 2.54,
            "pins": [
                (-2.54, 0, 0),       # Pin B (base) - straight horizontal
                (2.54, 2.54, 90),    # Pin C (collector) - pointing up
                (2.54, -2.54, 270),  # Pin E (emitter) - pointing down
            ],
            "graphics": [
                '        (polyline',
                '          (pts',
                '            (xy 0.635 0.635) (xy 2.54 2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0.635 -0.635) (xy 2.54 -2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 0.635 1.905) (xy 0.635 -1.905)',
                '          )',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy 1.27 -1.778) (xy 1.778 -1.27) (xy 2.286 -2.286) (xy 1.27 -1.778)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type outline))',
                '        )',
                '        (circle',
                '          (center 1.27 0)',
                '          (radius 2.8194)',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },
        
        # ── BJT PNP ─────────────────────────────────────────────────────
        "bjt_pnp": {
            "lib_id": "Transistor_BJT:Q_PNP_BCE",
            "ref_prefix": "Q",
            "pin_length": 2.54,
            "pins": [
                (-2.54, 0, 0),       # Pin B (base) - straight horizontal
                (2.54, 2.54, 90),    # Pin C (collector) - pointing up
                (2.54, -2.54, 270),  # Pin E (emitter) - pointing down
            ],
            "graphics": [
                # Collector line
                '        (polyline',
                '          (pts',
                '            (xy 0.635 0.635) (xy 2.54 2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                # Emitter line
                '        (polyline',
                '          (pts',
                '            (xy 0.635 -0.635) (xy 2.54 -2.54)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                # Vertical bar (base region)
                '        (polyline',
                '          (pts',
                '            (xy 0.635 1.905) (xy 0.635 -1.905)',
                '          )',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
                # Arrow at collector pointing IN (PNP direction)
                '        (polyline',
                '          (pts',
                '            (xy 1.27 1.778) (xy 1.778 1.27) (xy 2.286 2.286) (xy 1.27 1.778)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type outline))',
                '        )',
                # Circle around transistor
                '        (circle',
                '          (center 1.27 0)',
                '          (radius 2.8194)',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },
        
        # ── Polarized capacitor ─────────────────────────────────────────
        "capacitor_polarized": {
            "lib_id": "Device:C_Polarized",
            "ref_prefix": "C",
            "pins": [
                (-2.54, 0, 0),     # Pin 1: + (left)
                (2.54, 0, 180),    # Pin 2: - (right)
            ],
            "graphics": [
                # Flat plate (positive side)
                '        (polyline',
                '          (pts',
                '            (xy -0.762 -2.032) (xy -0.762 2.032)',
                '          )',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
                # Curved plate (negative side) - approximated with arc-like polyline
                '        (arc',
                '          (start 0.762 2.032)',
                '          (mid 1.397 0)',
                '          (end 0.762 -2.032)',
                '          (stroke (width 0.508) (type default))',
                '          (fill (type none))',
                '        )',
                # Plus sign near positive plate
                '        (polyline',
                '          (pts',
                '            (xy -1.524 1.524) (xy -1.524 0.762)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy -1.905 1.143) (xy -1.143 1.143)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },
        
        # ── Inductor ────────────────────────────────────────────────────
        "inductor": {
            "lib_id": "Device:L",
            "ref_prefix": "L",
            "pins": [
                (0, 3.81, 270),    # Pin 1: top
                (0, -3.81, 90),    # Pin 2: bottom
            ],
            "graphics": [
                # 4 arcs to form inductor coil shape
                '        (arc',
                '          (start 0 -2.54)',
                '          (mid 0.6323 -1.905)',
                '          (end 0 -1.27)',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (arc',
                '          (start 0 -1.27)',
                '          (mid 0.6323 -0.635)',
                '          (end 0 0)',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (arc',
                '          (start 0 0)',
                '          (mid 0.6323 0.635)',
                '          (end 0 1.27)',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (arc',
                '          (start 0 1.27)',
                '          (mid 0.6323 1.905)',
                '          (end 0 2.54)',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },
        
        # ── Diode ───────────────────────────────────────────────────────
        "diode": {
            "lib_id": "Device:D",
            "ref_prefix": "D",
            "pins": [
                (-2.54, 0, 0),     # Pin K (cathode) - left
                (2.54, 0, 180),    # Pin A (anode) - right
            ],
            "graphics": [
                # Triangle (anode side)
                '        (polyline',
                '          (pts',
                '            (xy 1.27 1.27) (xy -1.27 0) (xy 1.27 -1.27) (xy 1.27 1.27)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type outline))',
                '        )',
                # Bar (cathode side)
                '        (polyline',
                '          (pts',
                '            (xy -1.27 1.27) (xy -1.27 -1.27)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },
        
        # ── Current source ──────────────────────────────────────────────
        "current_source": {
            "lib_id": "Device:I",
            "ref_prefix": "I",
            "pins": [
                (0, 5.08, 270),    # Pin +
                (0, -5.08, 90),    # Pin -
            ],
            "graphics": [
                # Circle
                '        (circle',
                '          (center 0 0)',
                '          (radius 2.54)',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type background))',
                '        )',
                # Arrow pointing up (current direction)
                '        (polyline',
                '          (pts',
                '            (xy 0 -1.905) (xy 0 1.905)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
                '        (polyline',
                '          (pts',
                '            (xy -0.635 1.27) (xy 0 1.905) (xy 0.635 1.27)',
                '          )',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        },
    }

    @classmethod
    def _resolve_symbol_key(
        cls,
        component_type: str,
        component_id: str | None = None,
        component_pin_count: int | None = None,
    ) -> str:
        comp_type = (component_type or "").lower()
        comp_id_norm = (component_id or "").strip().lower()

        if comp_type == "power_symbol":
            if comp_id_norm in ("gnd", "ground", "vss", "vee", "0"):
                return "ground"
            return "power_symbol"

        # Use a dedicated one-pin symbol for power rails named like VCC/VDD/VSS/VEE.
        if comp_type == "voltage_source":
            if (component_pin_count == 1) and any(token in comp_id_norm for token in ("vcc", "vdd", "vss", "vee")):
                return "vcc"
            return "voltage_source"

        return comp_type
    
    @classmethod
    def get_symbol_def(
        cls,
        component_type: str,
        component_id: str | None = None,
        component_pin_count: int | None = None,
    ) -> Dict:
        """Get symbol definition for component type.
        
        Args:
            component_type: Component type string (e.g., "resistor", "capacitor")
            
        Returns:
            Dict with lib_id, ref_prefix, pins, graphics
        """
        symbol_key = cls._resolve_symbol_key(component_type, component_id, component_pin_count)
        return cls.SYMBOL_DEFINITIONS.get(symbol_key, cls._get_default_symbol())
    
    @classmethod
    def _get_default_symbol(cls) -> Dict:
        """Get default symbol for unknown types."""
        return {
            "lib_id": "Device:R",
            "ref_prefix": "U",
            "pins": [
                (-2.54, 0, 0),
                (2.54, 0, 180),
            ],
            "graphics": [
                '        (rectangle',
                '          (start -2.5 -1.0)',
                '          (end 2.5 1.0)',
                '          (stroke (width 0.254) (type default))',
                '          (fill (type none))',
                '        )',
            ]
        }
