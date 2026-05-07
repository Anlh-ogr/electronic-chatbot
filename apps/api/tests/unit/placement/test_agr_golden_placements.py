from dataclasses import dataclass

import pytest

from app.infrastructure.exporters.placement.agr_templates import GRID_MM, STAGE_WIDTH_GRIDS
from app.infrastructure.exporters.placement.coordinate_solver import solve_stage
from app.infrastructure.exporters.placement.multistage_composer import compose
from app.infrastructure.exporters.placement.topology_classifier import PlacementFamily


@dataclass
class SimpleComponent:
    ref: str
    type: str
    role: str
    topology_stage: int = 0


@dataclass
class SimpleStage:
    id: str
    topology: str


@dataclass
class SimpleArchitecture:
    stage_count: int
    stages: list


@dataclass
class SimpleAnalysis:
    topology_classification: str


@dataclass
class SimpleIR:
    components: list
    architecture: SimpleArchitecture
    analysis: SimpleAnalysis


def _single_transistor_components(active_type: str) -> list[SimpleComponent]:
    return [
        SimpleComponent("Q1", active_type, "stage_bridge"),
        SimpleComponent("RC", "resistor", "load"),
        SimpleComponent("RE", "resistor", "degeneration"),
        SimpleComponent("CIN", "capacitor", "coupling_in"),
        SimpleComponent("COUT", "capacitor", "coupling_out"),
        SimpleComponent("RB1", "resistor", "bias_top"),
        SimpleComponent("RB2", "resistor", "bias_bottom"),
        SimpleComponent("VCC", "power_supply", "supply"),
        SimpleComponent("GND", "ground", "ground"),
    ]


def test_golden_ce_cc_cb():
    g = GRID_MM

    ce = solve_stage(
        _single_transistor_components("bjt_npn"),
        PlacementFamily.SINGLE_TRANSISTOR,
        topology="bjt_common_emitter",
    )
    assert ce.components["CIN"].x_mm == pytest.approx(-6.0 * g)
    assert ce.components["COUT"].x_mm == pytest.approx(4.0 * g)
    assert ce.components["COUT"].y_mm == pytest.approx(-2.0 * g)

    cc = solve_stage(
        _single_transistor_components("bjt_npn"),
        PlacementFamily.SINGLE_TRANSISTOR,
        topology="bjt_common_collector",
    )
    assert cc.components["COUT"].y_mm == pytest.approx(2.0 * g)

    cb = solve_stage(
        _single_transistor_components("bjt_npn"),
        PlacementFamily.SINGLE_TRANSISTOR,
        topology="bjt_common_base",
    )
    assert cb.components["CIN"].y_mm == pytest.approx(2.0 * g)
    assert cb.components["COUT"].y_mm == pytest.approx(-2.0 * g)


def test_golden_cs_cd_cg():
    g = GRID_MM

    cs = solve_stage(
        _single_transistor_components("mosfet_n"),
        PlacementFamily.SINGLE_TRANSISTOR,
        topology="mosfet_common_source",
    )
    assert cs.components["COUT"].y_mm == pytest.approx(-2.0 * g)

    cd = solve_stage(
        _single_transistor_components("mosfet_n"),
        PlacementFamily.SINGLE_TRANSISTOR,
        topology="mosfet_common_drain",
    )
    assert cd.components["COUT"].y_mm == pytest.approx(2.0 * g)

    cg = solve_stage(
        _single_transistor_components("mosfet_n"),
        PlacementFamily.SINGLE_TRANSISTOR,
        topology="mosfet_common_gate",
    )
    assert cg.components["CIN"].y_mm == pytest.approx(2.0 * g)


def test_golden_opamp_inverting_and_diff():
    g = GRID_MM
    inv_components = [
        SimpleComponent("U1", "opamp_ic", "stage_bridge"),
        SimpleComponent("RIN", "resistor", "coupling_in"),
        SimpleComponent("RF", "resistor", "feedback"),
        SimpleComponent("VCC", "power_supply", "supply"),
        SimpleComponent("GND", "ground", "ground"),
    ]
    inv = solve_stage(
        inv_components,
        PlacementFamily.OPAMP_IC,
        topology="opamp_inverting",
    )
    assert inv.components["RIN"].x_mm == pytest.approx(-6.0 * g)
    assert inv.components["RIN"].y_mm == pytest.approx(-1.0 * g)

    diff_components = [
        SimpleComponent("U1", "opamp_ic", "stage_bridge"),
        SimpleComponent("RIN1", "resistor", "coupling_in"),
        SimpleComponent("RIN2", "resistor", "coupling_in"),
    ]
    diff = solve_stage(
        diff_components,
        PlacementFamily.OPAMP_IC,
        topology="opamp_differential",
    )
    assert diff.components["RIN1"].y_mm == pytest.approx(2.0 * g)
    assert diff.components["RIN2"].y_mm == pytest.approx(0.0)


def test_golden_class_ab_and_class_d():
    g = GRID_MM
    class_ab_components = [
        SimpleComponent("QP", "bjt_npn", "output_pair_top"),
        SimpleComponent("QN", "bjt_pnp", "output_pair_bottom"),
        SimpleComponent("CIN", "capacitor", "coupling_in"),
        SimpleComponent("COUT", "capacitor", "coupling_out"),
        SimpleComponent("VCC", "power_supply", "supply"),
        SimpleComponent("GND", "ground", "ground"),
    ]
    class_ab = solve_stage(
        class_ab_components,
        PlacementFamily.PUSH_PULL,
        topology="class_ab",
    )
    assert class_ab.components["QP"].y_mm == pytest.approx(-4.0 * g)
    assert class_ab.components["QN"].y_mm == pytest.approx(4.0 * g)
    assert class_ab.components["COUT"].x_mm == pytest.approx(4.0 * g)

    class_d_components = [
        SimpleComponent("QP", "mosfet_n", "output_pair_top"),
        SimpleComponent("QN", "mosfet_n", "output_pair_bottom"),
        SimpleComponent("L1", "inductor", "filter"),
    ]
    class_d = solve_stage(
        class_d_components,
        PlacementFamily.CLASS_D,
        topology="class_d",
    )
    assert class_d.components["L1"].x_mm == pytest.approx(6.0 * g)


def test_golden_darlington():
    g = GRID_MM
    components = [
        SimpleComponent("Q1", "bjt_npn", "stage_bridge"),
        SimpleComponent("Q2", "bjt_npn", "stage_bridge"),
    ]
    result = solve_stage(
        components,
        PlacementFamily.SINGLE_TRANSISTOR,
        topology="darlington",
    )
    assert result.components["Q2"].x_mm == pytest.approx(3.0 * g)


def test_golden_multistage_ce_to_ce():
    g = GRID_MM
    components = [
        SimpleComponent("Q1", "bjt_npn", "stage_bridge", 0),
        SimpleComponent("Q2", "bjt_npn", "stage_bridge", 1),
    ]
    ir = SimpleIR(
        components=components,
        architecture=SimpleArchitecture(
            stage_count=2,
            stages=[
                SimpleStage("S1", "bjt_common_emitter"),
                SimpleStage("S2", "bjt_common_emitter"),
            ],
        ),
        analysis=SimpleAnalysis(topology_classification="multi"),
    )
    result = compose(ir)
    assert result.components["Q2"].x_mm == pytest.approx(STAGE_WIDTH_GRIDS * g)


def test_golden_multistage_ce_to_opamp():
    g = GRID_MM
    components = [
        SimpleComponent("Q1", "bjt_npn", "stage_bridge", 0),
        SimpleComponent("U1", "opamp_ic", "stage_bridge", 1),
    ]
    ir = SimpleIR(
        components=components,
        architecture=SimpleArchitecture(
            stage_count=2,
            stages=[
                SimpleStage("S1", "bjt_common_emitter"),
                SimpleStage("S2", "opamp_inverting"),
            ],
        ),
        analysis=SimpleAnalysis(topology_classification="multi"),
    )
    result = compose(ir)
    assert result.components["U1"].x_mm == pytest.approx(STAGE_WIDTH_GRIDS * g)
