import pytest

from app.infrastructure.exporters.placement.agr_templates import GRID_MM
from app.infrastructure.exporters.placement.pin_resolver import resolve_pins


def test_resistor_pins_rotation():
    pins = resolve_pins("resistor", 0)
    assert pins["1"] == pytest.approx((0.0, -2.0 * GRID_MM))
    assert pins["2"] == pytest.approx((0.0, 2.0 * GRID_MM))

    pins_rot = resolve_pins("resistor", 90)
    assert pins_rot["1"] == pytest.approx((-2.0 * GRID_MM, 0.0))
    assert pins_rot["2"] == pytest.approx((2.0 * GRID_MM, 0.0))


def test_bjt_pins():
    pins = resolve_pins("bjt_npn", 0)
    assert pins["B"] == pytest.approx((-2.0 * GRID_MM, 0.0))
    assert pins["C"] == pytest.approx((0.0, -2.0 * GRID_MM))
    assert pins["E"] == pytest.approx((0.0, 2.0 * GRID_MM))
