"""Anchor offsets (grid units) per topology — placement_layout_strategy §4.2.

Offsets are relative to the active device center (``Q1`` / ``U1``). Positive X = right,
positive Y = down (KiCad). Multiply by ``GRID_MM`` (2.54 mm) for millimetres.
"""

from __future__ import annotations

from typing import Final

# --- BJT Common-Emitter -----------------------------------------------------

CE_OFFSETS: Final[dict[str, tuple[int, int]]] = {
    "VCC":  (0, -5),   # above RC
    "RC":   (0, -3),   # above Q1 on collector branch
    "Q1":   (0, 0),    # center anchor
    "R1":   (-3, -2),  # upper bias divider, left side
    "R2":   (-3, +2),  # lower bias divider, left side
    "RE1":  (0, +3),   # emitter degeneration (upper)
    "RE2":  (0, +5),   # emitter degeneration (lower, bypassed)
    "CE":   (+2, +5),  # bypass cap beside RE2
    "CIN":  (-5, 0),   # input coupling, left
    "COUT": (+5, 0),   # output coupling, right
    "GND":  (0, +7),   # ground below RE
}

# --- BJT Common-Base --------------------------------------------------------

CB_OFFSETS: Final[dict[str, tuple[int, int]]] = {
    "VCC":  (0, -5),
    "RC":   (0, -3),   # collector load above Q1
    "Q1":   (0, 0),    # center anchor
    "R1":   (-3, -1),  # base bias upper (local, not in signal path)
    "R2":   (-3, +1),  # base bias lower
    "CB":   (-3, 0),   # base bypass cap (if present)
    "RE":   (0, +3),   # emitter / input resistor
    "CIN":  (-5, +3),  # input enters emitter side
    "COUT": (+5, 0),   # output at collector
    "GND":  (0, +5),
}

# --- BJT Common-Collector ---------------------------------------------------

CC_OFFSETS: Final[dict[str, tuple[int, int]]] = {
    "VCC":  (0, -3),   # collector connected directly to supply
    "Q1":   (0, 0),    # center anchor
    "R1":   (-3, -2),  # base bias upper
    "R2":   (-3, +2),  # base bias lower
    "RE":   (0, +3),   # emitter resistor to GND
    "CIN":  (-5, 0),   # input at base
    "COUT": (+5, +3),  # output at emitter
    "GND":  (0, +5),
}

# --- Op-Amp Inverting (INV_OFFSETS in strategy doc) -------------------------

INV_OFFSETS: Final[dict[str, tuple[int, int]]] = {
    "VCC":  (0, -4),   # VS+ supply above
    "VEE":  (0, +4),   # VS- supply below
    "CPS":  (0, -3),   # decoupling cap VS+ to 0
    "CPN":  (0, +3),   # decoupling cap VS- to 0
    "U1":   (0, 0),    # center anchor
    "Rin":  (-4, 0),   # input resistor into - pin
    "Rf":   (0, -2),   # feedback resistor (horizontal, above U1)
    "Rgnd": (-3, +2),  # + pin to GND reference
    "CIN":  (-6, 0),   # input coupling
    "COUT": (+4, 0),   # output coupling
    "GND":  (0, +5),
}

# --- Op-Amp Non-Inverting (strategy §4.2) -----------------------------------

NONINV_OFFSETS: Final[dict[str, tuple[int, int]]] = {
    "VCC":  (0, -4),
    "VEE":  (0, +4),
    "CPS":  (0, -3),
    "CPN":  (0, +3),
    "U1":   (0, 0),
    "CIN":  (-6, 0),   # input at + pin
    "Rf":   (+2, +2),  # feedback from OUT to - pin
    "Rg":   (0, +2),   # - pin to GND
    "COUT": (+5, 0),
    "GND":  (0, +5),
}


TOPOLOGY_ANCHOR_OFFSETS: Final[dict[str, dict[str, tuple[int, int]]]] = {
    "CE": CE_OFFSETS,
    "CB": CB_OFFSETS,
    "CC": CC_OFFSETS,
    "INVERTING_OPAMP": INV_OFFSETS,
    "NONINVERTING_OPAMP": NONINV_OFFSETS,
}

__all__ = [
    "TOPOLOGY_ANCHOR_OFFSETS",
    "CE_OFFSETS",
    "CB_OFFSETS",
    "CC_OFFSETS",
    "INV_OFFSETS",
    "NONINV_OFFSETS",
]
