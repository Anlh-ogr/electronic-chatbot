"""KiCad schematic placement constants (placement_layout_strategy §2–§3)."""

from __future__ import annotations

GRID_MM: float = 2.54  # KiCad standard grid (100 mil)
SHEET_CENTER: tuple[float, float] = (150.0, 100.0)  # mm — A4 schematic center (strategy §3.1)

SYMBOL_BBOX_GRID: dict[str, tuple[int, int]] = {
    # (width, height) in grid units
    "bjt_npn":      (2, 3),
    "bjt_pnp":      (2, 3),
    "opamp_ic":     (4, 4),
    "resistor":     (1, 2),
    "capacitor":    (1, 2),
    "power_supply": (1, 1),
    "ground":       (1, 1),
    "connector":    (1, 1),
}

ROLE_ROTATION: dict[str, int] = {
    "bias_top":        0,
    "bias_bottom":     0,
    "load":            0,
    "degeneration":    0,
    "bypass_cap":      0,
    "supply":          0,
    "ground":          0,
    "unknown_passive": 0,
    "coupling_in":     90,
    "coupling_out":    90,
    "feedback":        90,
}


def grid(units: int) -> float:
    return units * GRID_MM
