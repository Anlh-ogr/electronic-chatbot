"""Schematic geometry helpers for KiCad 8 (Y positive downward)."""

from __future__ import annotations

import math
from typing import Tuple


class GeometryManager:
    """KiCad schematic space: +X right, +Y down. Rotations match ``pin_resolver.rotate_offsets``."""

    @staticmethod
    def rotate_offset(dx: float, dy: float, rotation: int) -> Tuple[float, float]:
        """Rotate a pin offset vector by ``rotation`` degrees (KiCad symbol rotation).

        Library offsets use the same Y-down convention as KiCad (e.g. pin 1 above center
        has negative *dy*). For multiples of 90°, only integer combination of *dx*/*dy* is
        used so values on the 2.54 mm grid stay exact.

        For other angles, the continuous Y-down CCW matrix is applied (may introduce tiny
        float residuals; prefer 0/90/180/270 for net routing).
        """
        deg = rotation % 360
        if deg == 0:
            return (dx, dy)
        if deg == 90:
            return (dy, -dx)
        if deg == 180:
            return (-dx, -dy)
        if deg == 270:
            return (-dy, dx)

        rad = math.radians(deg)
        cos_r = math.cos(rad)
        sin_r = math.sin(rad)
        # Y-down CCW: x' = x cos θ + y sin θ, y' = -x sin θ + y cos θ
        rx = dx * cos_r + dy * sin_r
        ry = -dx * sin_r + dy * cos_r
        return (rx, ry)


__all__ = ["GeometryManager"]
