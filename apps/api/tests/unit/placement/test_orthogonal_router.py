import pytest

from app.infrastructure.exporters.placement.agr_templates import GRID_MM
from app.infrastructure.exporters.placement.orthogonal_router import route_pair


def test_route_pair_returns_orthogonal_path():
    end = 8.0 * GRID_MM
    wire = route_pair((0.0, 0.0), (end, end))
    points = wire.points
    assert points[0] == (0.0, 0.0)
    assert points[-1] == (end, end)
    assert len(points) == 3
    assert points[1][0] == pytest.approx(end) or points[1][1] == pytest.approx(end)
