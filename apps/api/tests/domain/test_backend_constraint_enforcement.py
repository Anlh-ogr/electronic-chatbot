import sys
from pathlib import Path

# Ensure app package imports work when running tests from apps/api
APP_DIR = Path(__file__).resolve().parents[2] / "app"
sys.path.insert(0, str(APP_DIR))

from app.application.ai.constraint_validator import ConstraintValidator
from app.application.ai.nlu_service import NLUService
from app.domains.circuits.ai_core.parameter_solver import ParameterSolver


def test_multi_stage_solver_distributes_gain_over_gain_stages_only() -> None:
    solver = ParameterSolver()
    solved = solver.solve(
        target_gain=25.0,
        family="multi_stage",
        metadata={"solver_hints": {"num_stages": 2, "topology": "CS+CD", "gm_ma": 5.0}},
    )

    assert solved.success is True
    assert solved.actual_gain is not None
    # CS should carry the main gain while CD stays near unity.
    assert solved.actual_gain > 15.0


def test_nlu_extracts_gain_range_zout_and_direct_coupling_constraints() -> None:
    nlu = NLUService()
    text = (
        "Thiết kế mạch 2 tầng CS-CD ghép trực tiếp, tổng gain 20-30, "
        "trở kháng ra rất thấp (< 50 ohm), không dùng tụ coupling giữa hai tầng"
    )
    intent = nlu._rule_based_parse(text)

    assert intent.hard_constraints.get("gain_min") == 20.0
    assert intent.hard_constraints.get("gain_max") == 30.0
    assert intent.hard_constraints.get("output_impedance_max_ohm") == 50.0
    assert intent.hard_constraints.get("direct_coupling_required") is True


def test_validator_rejects_non_direct_coupling_and_high_zout() -> None:
    validator = ConstraintValidator()
    intent_dict = {
        "hard_constraints": {
            "direct_coupling_required": True,
            "output_impedance_max_ohm": 50.0,
        }
    }
    circuit_data = {
        "topology_type": "composed_multi_stage",
        "composition_plan": {
            "interstage_links": [
                {
                    "from_stage": "stage1",
                    "to_stage": "stage2",
                    "coupling_mode": "capacitor",
                }
            ]
        },
        "components": [{"id": "X1", "type": "subcircuit", "parameters": {}}],
        "nets": [{"id": "N1", "connections": [["X1", "IN"]]}],
    }
    solved_params = {"output_impedance_ohm": 120.0}

    report = validator.validate(circuit_data, intent_dict, solved_params)

    codes = {v.code for v in report.errors}
    assert "HARD_DIRECT_COUPLING" in codes
    assert "HARD_ZOUT_MAX" in codes
