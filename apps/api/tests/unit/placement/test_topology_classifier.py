from types import SimpleNamespace

from app.infrastructure.exporters.placement.topology_classifier import (
    PlacementFamily,
    classify,
    classify_stage,
)


def test_classify_multistage():
    ir = SimpleNamespace(architecture=SimpleNamespace(stage_count=2), components=[])
    assert classify(ir) == PlacementFamily.MULTISTAGE


def test_classify_opamp():
    ir = SimpleNamespace(
        analysis=SimpleNamespace(topology_classification="opamp_inverting"),
        components=[SimpleNamespace(ref="U1", type="opamp_ic", role="stage_bridge")],
    )
    assert classify(ir) == PlacementFamily.OPAMP_IC


def test_classify_push_pull():
    ir = SimpleNamespace(
        analysis=SimpleNamespace(topology_classification="class_ab"),
        components=[
            SimpleNamespace(ref="Q1", type="bjt_npn", role="output_pair_top"),
            SimpleNamespace(ref="Q2", type="bjt_pnp", role="output_pair_bottom"),
        ],
    )
    assert classify(ir) == PlacementFamily.PUSH_PULL


def test_classify_class_d():
    ir = SimpleNamespace(
        analysis=SimpleNamespace(topology_classification="class_d"),
        components=[],
    )
    assert classify(ir) == PlacementFamily.CLASS_D


def test_classify_stage_default():
    stage = SimpleNamespace(topology="bjt_common_emitter")
    comps = [SimpleNamespace(ref="Q1", type="bjt_npn", role="stage_bridge")]
    assert classify_stage(stage, comps) == PlacementFamily.SINGLE_TRANSISTOR
