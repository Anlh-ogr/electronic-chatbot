from __future__ import annotations

from typing import Dict, Tuple

from .agr_templates import GRID_MM


PIN_LIBRARY = {
    "resistor": {"1": (0.0, -2.0 * GRID_MM), "2": (0.0, 2.0 * GRID_MM)},
    "capacitor": {"1": (0.0, -2.0 * GRID_MM), "2": (0.0, 2.0 * GRID_MM)},
    "capacitor_polarized": {"1": (0.0, -2.0 * GRID_MM), "2": (0.0, 2.0 * GRID_MM)},
    "inductor": {"1": (0.0, -2.0 * GRID_MM), "2": (0.0, 2.0 * GRID_MM)},
    "transformer": {"1": (-GRID_MM, 0.0), "2": (GRID_MM, 0.0)},
    "diode": {"A": (-2.0 * GRID_MM, 0.0), "K": (2.0 * GRID_MM, 0.0)},
    "bjt": {"B": (-2.0 * GRID_MM, 0.0), "C": (0.0, -2.0 * GRID_MM), "E": (0.0, 2.0 * GRID_MM)},
    "bjt_npn": {"B": (-2.0 * GRID_MM, 0.0), "C": (0.0, -2.0 * GRID_MM), "E": (0.0, 2.0 * GRID_MM)},
    "bjt_pnp": {"B": (-2.0 * GRID_MM, 0.0), "C": (0.0, -2.0 * GRID_MM), "E": (0.0, 2.0 * GRID_MM)},
    "mosfet": {"G": (-2.0 * GRID_MM, 0.0), "D": (0.0, -2.0 * GRID_MM), "S": (0.0, 2.0 * GRID_MM)},
    "mosfet_n": {"G": (-2.0 * GRID_MM, 0.0), "D": (0.0, -2.0 * GRID_MM), "S": (0.0, 2.0 * GRID_MM)},
    "mosfet_p": {"G": (-2.0 * GRID_MM, 0.0), "D": (0.0, -2.0 * GRID_MM), "S": (0.0, 2.0 * GRID_MM)},
    "jfet_n": {"G": (-2.0 * GRID_MM, 0.0), "D": (0.0, -2.0 * GRID_MM), "S": (0.0, 2.0 * GRID_MM)},
    "jfet_p": {"G": (-2.0 * GRID_MM, 0.0), "D": (0.0, -2.0 * GRID_MM), "S": (0.0, 2.0 * GRID_MM)},
    "opamp": {
        "-": (-2.0 * GRID_MM, -GRID_MM),
        "+": (-2.0 * GRID_MM, GRID_MM),
        "OUT": (2.0 * GRID_MM, 0.0),
        "VS+": (0.0, -2.0 * GRID_MM),
        "VS-": (0.0, 2.0 * GRID_MM),
    },
    "opamp_ic": {
        "-": (-2.0 * GRID_MM, -GRID_MM),
        "+": (-2.0 * GRID_MM, GRID_MM),
        "OUT": (2.0 * GRID_MM, 0.0),
        "VS+": (0.0, -2.0 * GRID_MM),
        "VS-": (0.0, 2.0 * GRID_MM),
    },
    "connector": {"1": (0.0, 0.0)},
    "port": {"1": (0.0, 0.0)},
    "power_supply": {"1": (0.0, 0.0)},
    "power_symbol": {"1": (0.0, 0.0)},
    "ground": {"1": (0.0, 0.0)},
    "transformer": {"1": (0.0, -2.0 * GRID_MM), "2": (0.0, 2.0 * GRID_MM)},
}


def resolve_pins(comp_type: str, rotation: int = 0) -> Dict[str, Tuple[float, float]]:
    """Return pin offsets for a component type, applying rotation."""
    base = PIN_LIBRARY.get(str(comp_type or "").lower(), {"1": (0.0, 0.0)})
    if rotation % 360 == 0:
        return dict(base)
    return rotate_offsets(base, rotation)


def rotate_offsets(offsets: Dict[str, Tuple[float, float]], rotation: int) -> Dict[str, Tuple[float, float]]:
    """Rotate pin offsets by 0/90/180/270 degrees."""
    rot = rotation % 360
    rotated: Dict[str, Tuple[float, float]] = {}
    for name, (x, y) in offsets.items():
        if rot == 90:
            rotated[name] = (y, -x)
        elif rot == 180:
            rotated[name] = (-x, -y)
        elif rot == 270:
            rotated[name] = (-y, x)
        else:
            rotated[name] = (x, y)
    return rotated


__all__ = ["resolve_pins", "rotate_offsets", "PIN_LIBRARY"]
