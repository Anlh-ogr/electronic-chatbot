from __future__ import annotations

from typing import Dict, Tuple

from .geometry_manager import GeometryManager

# ── KiCad schematic grid ────────────────────────────────────────────────────
# KiCad schematics use the 100-mil (2.54 mm) grid.  agr_templates.GRID_MM is
# the 50-mil AGR internal grid (1.27 mm) which is NOT appropriate for KiCad
# symbol pin positions — import the correct constant here directly.
GRID_MM: float = 2.54   # KiCad 100-mil schematic grid

# ── Pin offset constants ────────────────────────────────────────────────────
# Distance from symbol centre to the wire-connection point for 2-pin passives
# (resistor, capacitor, inductor).  Must be a multiple of GRID_MM so that pin
# positions always land on the 100-mil KiCad routing grid.
#   Body half-length = 2.54 mm + 1 pin-stub (2.54 mm) → total = 5.08 mm
PIN_OFFSET: float = 2.0 * GRID_MM   # 5.08 mm (2 grid units)

# BJT pin distances:  base lateral (2 grid), collector/emitter vertical (2 grid)
BJT_BASE_OFFSET: float = 2.0 * GRID_MM   # 5.08 mm left for base
BJT_CE_OFFSET:   float = 2.0 * GRID_MM   # 5.08 mm up/down for C / E

# Connector: connection point is 1 grid unit left of symbol centre
CONNECTOR_PIN_OFFSET: float = GRID_MM    # 2.54 mm

# KiCad ``Amplifier_Operational``-style numbering: pin 1 OUT, 2 +, 3 -, 4 V+, 5 V-
_OPAMP_PIN_BY_NUMBER: Tuple[str, ...] = ("OUT", "+", "-", "VS+", "VS-")

_PIN_ALIASES: Dict[str, str] = {
    "V+": "VS+",
    "V-": "VS-",
    "VP": "VS+",
    "VN": "VS-",
}


def canonical_pin_name(comp_type: str | None, pin_name: str) -> str:
    """Map netlist / KiCad pin labels to keys in ``PIN_LIBRARY`` (op-amp power & numbered pins)."""
    p = str(pin_name).strip()
    if p in _PIN_ALIASES:
        return _PIN_ALIASES[p]
    t = str(comp_type or "").lower()
    if t in ("opamp", "opamp_ic") and p.isdigit():
        idx = int(p)
        if 1 <= idx <= len(_OPAMP_PIN_BY_NUMBER):
            return _OPAMP_PIN_BY_NUMBER[idx - 1]
    return p


def pin_offset_for_instance(comp_type: str | None, pin_name: str, rotation: int = 0) -> Tuple[float, float]:
    """Offset (mm) of a pin's connection point from the symbol origin.

    Applies ``rotation`` so callers can pass the KiCad symbol rotation directly
    (0 = vertical passive, 90 = horizontal passive).

    Lookup order: canonical name → raw name → uppercase variants.
    Falls back to (0, 0) only when no library entry is found, which means the
    wire will route to the symbol centre — callers should ensure that all
    component types and pin names map to a library entry.
    """
    raw = str(pin_name).strip()
    canon = canonical_pin_name(comp_type, raw)
    offsets = resolve_pins(str(comp_type or ""), rotation)
    # Try exact match, then uppercase (IR sometimes uses "b"/"c"/"e" in lowercase)
    for key in (canon, raw, canon.upper(), raw.upper()):
        if key in offsets:
            return offsets[key]
    return (0.0, 0.0)


def get_pin_coordinate(
    cx: float,
    cy: float,
    comp_type: str | None,
    pin_name: str,
    rotation: int = 0,
) -> Tuple[float, float]:
    """Return absolute KiCad coordinate for a pin, given its symbol centre.

    This is the canonical function that wire-routing MUST use as the start/end
    point for every wire segment.  It applies the pin's physical offset (from
    the symbol origin in the KiCad symbol library) and the component's current
    rotation so that wires land exactly on the symbol's connection dot — NOT
    on the component centre.

    Conventions (KiCad Y-axis positive = downward):
      • Vertical passive (rotation=0): pin 1 at (cx, cy−OFFSET), pin 2 at (cx, cy+OFFSET)
      • Horizontal passive (rotation=90): pin 1 at (cx−OFFSET, cy), pin 2 at (cx+OFFSET, cy)
      • BJT NPN (rotation=0): B=(cx−OFFSET, cy), C=(cx, cy−OFFSET), E=(cx, cy+OFFSET)
      • Connector (rotation=0): pin 1 at (cx−2.54, cy)

    Where OFFSET = PIN_OFFSET = 5.08 mm (2 × 2.54 mm grid units).
    """
    ox, oy = pin_offset_for_instance(comp_type, pin_name, rotation)
    return (cx + ox, cy + oy)


PIN_LIBRARY = {
    # 2-pin passives — vertical default orientation: pin 1 top, pin 2 bottom.
    # Both at PIN_OFFSET (5.08 mm = 2 × 2.54 mm) from centre so wire endpoints
    # always land on the 100-mil KiCad grid.
    "resistor":           {"1": (0.0, -PIN_OFFSET), "2": (0.0,  PIN_OFFSET)},
    "capacitor":          {"1": (0.0, -PIN_OFFSET), "2": (0.0,  PIN_OFFSET)},
    "capacitor_polarized":{"1": (0.0, -PIN_OFFSET), "2": (0.0,  PIN_OFFSET)},
    "inductor":           {"1": (0.0, -PIN_OFFSET), "2": (0.0,  PIN_OFFSET)},
    "transformer":        {"1": (0.0, -PIN_OFFSET), "2": (0.0,  PIN_OFFSET)},
    # Diode — horizontal: A left, K right
    "diode": {"A": (-PIN_OFFSET, 0.0), "K": (PIN_OFFSET, 0.0)},
    # BJT — Q_NPN/PNP_BCE layout: B far-left, C top, E bottom.
    # These offsets are hardcoded to match kicad_symbol_library.py exactly.
    "bjt":     {"B": (-BJT_BASE_OFFSET, 0.0), "C": (0.0, -BJT_CE_OFFSET), "E": (0.0,  BJT_CE_OFFSET)},
    "bjt_npn": {"B": (-BJT_BASE_OFFSET, 0.0), "C": (0.0, -BJT_CE_OFFSET), "E": (0.0,  BJT_CE_OFFSET)},
    # PNP: C bottom, E top (reversed vs NPN)
    "bjt_pnp": {"B": (-BJT_BASE_OFFSET, 0.0), "C": (0.0,  BJT_CE_OFFSET), "E": (0.0, -BJT_CE_OFFSET)},
    # MOSFET / JFET: G left, D top, S bottom
    "mosfet":   {"G": (-PIN_OFFSET, 0.0), "D": (0.0, -PIN_OFFSET), "S": (0.0,  PIN_OFFSET)},
    "mosfet_n": {"G": (-PIN_OFFSET, 0.0), "D": (0.0, -PIN_OFFSET), "S": (0.0,  PIN_OFFSET)},
    "mosfet_p": {"G": (-PIN_OFFSET, 0.0), "D": (0.0, -PIN_OFFSET), "S": (0.0,  PIN_OFFSET)},
    "jfet_n":   {"G": (-PIN_OFFSET, 0.0), "D": (0.0, -PIN_OFFSET), "S": (0.0,  PIN_OFFSET)},
    "jfet_p":   {"G": (-PIN_OFFSET, 0.0), "D": (0.0, -PIN_OFFSET), "S": (0.0,  PIN_OFFSET)},
    # Op-amp (Amplifier_Operational:LM358): OUT right, +/- left, V+/V- top/bottom
    "opamp": {
        "-":   (-PIN_OFFSET, -GRID_MM),
        "+":   (-PIN_OFFSET,  GRID_MM),
        "OUT": ( PIN_OFFSET,  0.0),
        "VS+": (0.0, -PIN_OFFSET),
        "VS-": (0.0,  PIN_OFFSET),
    },
    "opamp_ic": {
        "-":   (-PIN_OFFSET, -GRID_MM),
        "+":   (-PIN_OFFSET,  GRID_MM),
        "OUT": ( PIN_OFFSET,  0.0),
        "VS+": (0.0, -PIN_OFFSET),
        "VS-": (0.0,  PIN_OFFSET),
    },
    # Connector_Generic:Conn_01x01 — wire connection point is CONNECTOR_PIN_OFFSET
    # (one grid unit = 2.54 mm) to the LEFT of the symbol centre, matching the
    # (-2.54, 0, 0) pin definition in kicad_symbol_library.py.
    "connector": {"1": (-CONNECTOR_PIN_OFFSET, 0.0)},
    "port":      {"1": (-CONNECTOR_PIN_OFFSET, 0.0)},
    # Power / ground: connection point at symbol origin
    "power_supply":  {"1": (0.0, 0.0)},
    "power_symbol":  {"1": (0.0, 0.0)},
    "ground":        {"1": (0.0, 0.0)},
}


def _fuzzy_pin_base(comp_type: str) -> Dict[str, Tuple[float, float]]:
    """Look up PIN_LIBRARY entry by exact key or by substring heuristics.

    IR-generated type strings sometimes differ from library keys
    (e.g. ``"npn"``, ``"bjt"``, ``"capacitor_electrolytic"``, ``"port"``).
    The heuristics below map common variants to the correct entry so that
    pin offsets are never silently (0, 0).
    """
    ct = str(comp_type or "").lower().strip()
    if ct in PIN_LIBRARY:
        return PIN_LIBRARY[ct]

    # BJT variants
    if ct in ("npn", "pnp", "bjt", "q_npn", "q_pnp") or "bjt" in ct or "npn" in ct or "pnp" in ct:
        return PIN_LIBRARY["bjt_npn"]
    # MOSFET variants
    if "mosfet" in ct or "mos" in ct or ct in ("nmos", "pmos", "nfet", "pfet"):
        return PIN_LIBRARY["mosfet"]
    # JFET
    if "jfet" in ct:
        return PIN_LIBRARY["jfet_n"]
    # Capacitor variants (polarized, electrolytic, film …)
    if ct.startswith("cap") or "capacitor" in ct or ct in ("c", "ce"):
        return PIN_LIBRARY["capacitor"]
    # Resistor variants
    if ct.startswith("res") or "resistor" in ct or ct in ("r",):
        return PIN_LIBRARY["resistor"]
    # Inductor
    if "inductor" in ct or "coil" in ct or ct in ("l",):
        return PIN_LIBRARY["inductor"]
    # Diode variants
    if "diode" in ct or ct in ("d", "led", "zener", "schottky"):
        return PIN_LIBRARY["diode"]
    # Op-amp variants
    if "opamp" in ct or "op_amp" in ct or "op-amp" in ct or "amplifier" in ct:
        return PIN_LIBRARY["opamp_ic"]
    # Power / supply variants
    if "power" in ct or "supply" in ct or ct in ("vcc", "vdd", "v+", "vee", "vss", "v-"):
        return PIN_LIBRARY["power_supply"]
    # Ground variants
    if "gnd" in ct or "ground" in ct or ct == "0":
        return PIN_LIBRARY["ground"]
    # Connector / port variants
    if "conn" in ct or "port" in ct or "jack" in ct or "header" in ct or "plug" in ct:
        return PIN_LIBRARY["connector"]

    # Unknown: single pin at origin (safe default, produces a warning)
    return {"1": (0.0, 0.0)}


def resolve_pins(comp_type: str, rotation: int = 0) -> Dict[str, Tuple[float, float]]:
    """Return pin offsets for a component type, applying rotation."""
    base = _fuzzy_pin_base(comp_type)
    if rotation % 360 == 0:
        return dict(base)
    return rotate_offsets(base, rotation)


def rotate_offsets(offsets: Dict[str, Tuple[float, float]], rotation: int) -> Dict[str, Tuple[float, float]]:
    """Rotate pin offsets by 0/90/180/270 degrees (KiCad Y-down)."""
    rot = rotation % 360
    return {name: GeometryManager.rotate_offset(x, y, rot) for name, (x, y) in offsets.items()}


__all__ = [
    "resolve_pins",
    "rotate_offsets",
    "PIN_LIBRARY",
    "canonical_pin_name",
    "pin_offset_for_instance",
]
