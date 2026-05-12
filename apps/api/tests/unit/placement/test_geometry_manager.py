import pytest

from app.infrastructure.exporters.placement.agr_templates import GRID_MM
from app.infrastructure.exporters.placement.geometry_manager import GeometryManager

G = GRID_MM


def test_rotate_offset_vertical_passive_matches_strategy_doc() -> None:
    # Pin 1 top / Pin 2 bottom at 0°; after 90° Pin 1 left / Pin 2 right (Y-down)
    assert GeometryManager.rotate_offset(0.0, -G, 0) == (0.0, -G)
    assert GeometryManager.rotate_offset(0.0, G, 0) == (0.0, G)
    assert GeometryManager.rotate_offset(0.0, -G, 90) == (-G, 0.0)
    assert GeometryManager.rotate_offset(0.0, G, 90) == (G, 0.0)


def test_rotate_offset_multiples_of_90_exact_on_grid() -> None:
    dx, dy = -2.0 * G, 3.0 * G
    assert GeometryManager.rotate_offset(dx, dy, 90) == (dy, -dx)
    assert GeometryManager.rotate_offset(dx, dy, 180) == (-dx, -dy)
    assert GeometryManager.rotate_offset(dx, dy, 270) == (-dy, dx)
    assert GeometryManager.rotate_offset(dx, dy, -90) == GeometryManager.rotate_offset(dx, dy, 270)


def test_rotate_offset_normalizes_rotation() -> None:
    assert GeometryManager.rotate_offset(0.0, -G, 450) == (-G, 0.0)
