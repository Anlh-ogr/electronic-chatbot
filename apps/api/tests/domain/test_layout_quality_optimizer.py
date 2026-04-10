import sys
from pathlib import Path

# Ensure app package imports work when running tests from apps/api
APP_DIR = Path(__file__).resolve().parents[2] / "app"
sys.path.insert(0, str(APP_DIR))

from app.domains.circuits.entities import Circuit, Component, ComponentType, Net, PinRef
from app.domains.circuits.placement import LayoutQualityEvaluator
from app.infrastructure.exporters.layout_planner import LayoutPlanner
from app.infrastructure.exporters.pcb_layout_planner import PCBLayoutPlanner


def _build_two_stage_subcircuit() -> Circuit:
    a1 = Component(id="A1", type=ComponentType.SUBCIRCUIT, pins=("IN", "OUT"))
    b1 = Component(id="B1", type=ComponentType.SUBCIRCUIT, pins=("IN", "OUT"))

    n_in = Net(
        name="N_IN",
        connected_pins=(
            PinRef(component_id="A1", pin_name="IN"),
            PinRef(component_id="B1", pin_name="IN"),
        ),
    )
    n_out = Net(
        name="N_OUT",
        connected_pins=(
            PinRef(component_id="A1", pin_name="OUT"),
            PinRef(component_id="B1", pin_name="OUT"),
        ),
    )

    return Circuit(
        name="subcircuit_chain",
        _components={"A1": a1, "B1": b1},
        _nets={"N_IN": n_in, "N_OUT": n_out},
        _ports={},
        _constraints={},
    )


def test_layout_planner_fallback_pin_position_not_center_for_multi_pin_component() -> None:
    circuit = _build_two_stage_subcircuit()
    placements = {"A1": (50.0, 50.0), "B1": (90.0, 50.0)}

    planner = LayoutPlanner()
    pin = PinRef(component_id="A1", pin_name="IN")

    pos = planner.get_pin_position(
        pin=pin,
        placements=placements,
        circuit=circuit,
        pin_offsets={},
        rotations={},
    )

    assert pos is not None
    assert pos != placements["A1"]


def test_layout_quality_evaluator_flags_center_attachment_violation() -> None:
    circuit = _build_two_stage_subcircuit()
    placements = {"A1": (50.0, 50.0), "B1": (90.0, 50.0)}
    wires = [{"points": [(52.0, 50.0), (88.0, 50.0)]}]

    # Intentionally place A1.IN at center to trigger violation.
    pin_positions = {
        ("A1", "IN"): (50.0, 50.0),
        ("A1", "OUT"): (52.0, 50.0),
        ("B1", "IN"): (88.0, 50.0),
        ("B1", "OUT"): (92.0, 50.0),
    }

    evaluator = LayoutQualityEvaluator()
    report = evaluator.evaluate_schematic(
        circuit=circuit,
        placements=placements,
        wires=wires,
        pin_positions=pin_positions,
        label_positions=[(20.0, 50.0)],
        min_component_spacing=2.0,
    )

    assert report.center_attachment_count >= 1
    assert report.is_hard_valid is False
    assert report.objective > 900.0


def test_pcb_layout_planner_fallback_pad_positions_not_center_for_multi_pin_component() -> None:
    circuit = _build_two_stage_subcircuit()
    placements = {"A1": (30.0, 30.0), "B1": (70.0, 30.0)}

    planner = PCBLayoutPlanner()
    pad_positions = planner._compute_pad_positions(circuit, placements)

    assert pad_positions[("A1.IN")] != placements["A1"]
    assert pad_positions[("A1.OUT")] != placements["A1"]
    assert pad_positions[("A1.IN")] != pad_positions[("A1.OUT")]
