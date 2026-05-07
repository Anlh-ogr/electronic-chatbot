from dataclasses import dataclass

import pytest

from app.infrastructure.exporters.placement.agr_templates import GRID_MM, STAGE_WIDTH_GRIDS
from app.infrastructure.exporters.placement.multistage_composer import compose


@dataclass
class SimpleComponent:
    ref: str
    type: str
    role: str
    topology_stage: int


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


def test_compose_two_stage_offsets():
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

    assert result.components["Q1"].x_mm == pytest.approx(0.0)
    assert result.components["Q2"].x_mm == pytest.approx(STAGE_WIDTH_GRIDS * GRID_MM)
