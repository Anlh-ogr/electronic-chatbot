from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Tuple

from .agr_templates import GRID_MM


@dataclass(frozen=True)
class OrthogonalWire:
    points: List[Tuple[float, float]]


def route_pair(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    *,
    avoid_boxes: Iterable[Tuple[float, float, float, float]] | None = None,
    grid_mm: float = GRID_MM,
) -> OrthogonalWire:
    """Route a single orthogonal path between two points."""
    avoid_boxes = list(avoid_boxes or [])
    p1 = _snap_point(p1, grid_mm)
    p2 = _snap_point(p2, grid_mm)

    if p1[0] == p2[0] or p1[1] == p2[1]:
        return OrthogonalWire(points=[p1, p2])

    candidate_a = [p1, (p2[0], p1[1]), p2]
    candidate_b = [p1, (p1[0], p2[1]), p2]

    if not _path_hits_boxes(candidate_a, avoid_boxes):
        return OrthogonalWire(points=candidate_a)
    if not _path_hits_boxes(candidate_b, avoid_boxes):
        return OrthogonalWire(points=candidate_b)

    detour_y = p1[1] + 2.0 * grid_mm
    detour = [p1, (p1[0], detour_y), (p2[0], detour_y), p2]
    if not _path_hits_boxes(detour, avoid_boxes):
        return OrthogonalWire(points=detour)

    detour_y = p1[1] - 2.0 * grid_mm
    detour = [p1, (p1[0], detour_y), (p2[0], detour_y), p2]
    return OrthogonalWire(points=detour)


def route_net(
    points: Iterable[Tuple[float, float]],
    *,
    avoid_boxes: Iterable[Tuple[float, float, float, float]] | None = None,
    grid_mm: float = GRID_MM,
) -> List[OrthogonalWire]:
    """Route a multi-point net as chained orthogonal segments."""
    points = list(points)
    if len(points) < 2:
        return []
    wires: List[OrthogonalWire] = []
    for i in range(len(points) - 1):
        wires.append(route_pair(points[i], points[i + 1], avoid_boxes=avoid_boxes, grid_mm=grid_mm))
    return wires


def _snap_point(point: Tuple[float, float], grid_mm: float) -> Tuple[float, float]:
    return (round(point[0] / grid_mm) * grid_mm, round(point[1] / grid_mm) * grid_mm)


def _path_hits_boxes(path: List[Tuple[float, float]], boxes: Iterable[Tuple[float, float, float, float]]) -> bool:
    for i in range(len(path) - 1):
        if _segment_hits_boxes(path[i], path[i + 1], boxes):
            return True
    return False


def _segment_hits_boxes(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    boxes: Iterable[Tuple[float, float, float, float]],
) -> bool:
    x1, y1 = p1
    x2, y2 = p2
    for x_min, x_max, y_min, y_max in boxes:
        if x1 == x2 and x_min <= x1 <= x_max:
            if _range_overlap(y1, y2, y_min, y_max):
                return True
        if y1 == y2 and y_min <= y1 <= y_max:
            if _range_overlap(x1, x2, x_min, x_max):
                return True
    return False


def _range_overlap(a1: float, a2: float, b1: float, b2: float) -> bool:
    low_a, high_a = sorted((a1, a2))
    low_b, high_b = sorted((b1, b2))
    return not (high_a < low_b or low_a > high_b)


__all__ = ["OrthogonalWire", "route_pair", "route_net"]
