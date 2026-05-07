from dataclasses import dataclass

import pytest

from app.infrastructure.exporters.placement.agr_templates import GRID_MM
from app.infrastructure.exporters.placement.coordinate_solver import solve_stage
from app.infrastructure.exporters.placement.topology_classifier import PlacementFamily


@dataclass
class SimpleComponent:
    ref: str
    type: str
    role: str
    topology_stage: int = 0


def test_single_transistor_placement():
    components = [
        SimpleComponent("Q1", "bjt_npn", "stage_bridge"),
        SimpleComponent("RC", "resistor", "load"),
        SimpleComponent("RE", "resistor", "degeneration"),
        SimpleComponent("CIN", "capacitor", "coupling_in"),
        SimpleComponent("COUT", "capacitor", "coupling_out"),
        SimpleComponent("VCC", "power_supply", "supply"),
        SimpleComponent("GND", "ground", "ground"),
        SimpleComponent("RB1", "resistor", "bias_top"),
        SimpleComponent("RB2", "resistor", "bias_bottom"),
    ]

    result = solve_stage(
        components,
        PlacementFamily.SINGLE_TRANSISTOR,
        topology="bjt_common_emitter",
    )

    q1 = result.components["Q1"]
    assert q1.x_mm == pytest.approx(0.0)
    assert q1.y_mm == pytest.approx(0.0)

    cin = result.components["CIN"]
    assert cin.rotation == 90
    assert cin.x_mm == pytest.approx(-6.0 * GRID_MM)
    assert cin.y_mm == pytest.approx(0.0)

    cout = result.components["COUT"]
    assert cout.rotation == 90
    assert cout.x_mm == pytest.approx(4.0 * GRID_MM)
    assert cout.y_mm == pytest.approx(-2.0 * GRID_MM)

    vcc = result.components["VCC"]
    gnd = result.components["GND"]
    assert vcc.y_mm < q1.y_mm
    assert gnd.y_mm > q1.y_mm
