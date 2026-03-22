import sys
import time
from pathlib import Path

# Ensure app package imports work when running tests from apps/api
APP_DIR = Path(__file__).resolve().parents[2] / "app"
sys.path.insert(0, str(APP_DIR))

from app.application.ai.chatbot_service import ChatResponse, ChatbotService
from app.application.ai.constraint_validator import ValidationReport, Violation
from app.application.ai.llm_router import LLMMode
from app.application.ai.nlu_service import CircuitIntent, EditOperation
from app.application.ai.repair_engine import RepairResult
from app.domains.circuits.ai_core.ai_core import PipelineResult
from app.domains.circuits.ai_core.circuit_generator import GeneratedCircuit
from app.domains.circuits.ai_core.parameter_solver import SolvedParams
from app.domains.circuits.ai_core.topology_planner import TopologyPlan


def _mk_pipeline(template_id: str, actual_gain: float) -> PipelineResult:
    circuit = GeneratedCircuit(
        template_id=template_id,
        circuit_data={
            "template_id": template_id,
            "topology_type": "composed_multi_stage",
            "components": [{"id": "X1", "type": "subcircuit", "parameters": {}}],
            "nets": [{"id": "N1", "connections": [["X1", "IN"]]}],
            "composition_plan": {
                "interstage_links": [{"from_stage": "stage1", "to_stage": "stage2", "coupling_mode": "direct"}],
            },
        },
        success=True,
        message="ok",
    )
    solved = SolvedParams(values={"RD_S1": 5100.0}, actual_gain=actual_gain, success=True)
    plan = TopologyPlan(matched_template_id=template_id, mode="exact_template")
    return PipelineResult(
        user_text="",
        plan=plan,
        solved=solved,
        circuit=circuit,
        success=True,
        stage_reached="generate",
    )


def test_create_flow_fail_fast_regenerates_on_hard_constraint(monkeypatch) -> None:
    service = ChatbotService()

    initial = _mk_pipeline("INITIAL-FAIL", actual_gain=8.0)
    retried = _mk_pipeline("RETRY-OK", actual_gain=25.0)

    calls = {"n": 0}

    def fake_handle_spec(_spec):
        calls["n"] += 1
        return initial if calls["n"] == 1 else retried

    monkeypatch.setattr(service._ai_core, "handle_spec", fake_handle_spec)

    reports = [
        ValidationReport(
            passed=False,
            violations=[Violation(code="HARD_ZOUT_MAX", severity="error", message="zout too high")],
            checked_rules=1,
        ),
        ValidationReport(
            passed=False,
            violations=[Violation(code="HARD_ZOUT_MAX", severity="error", message="zout still high")],
            checked_rules=1,
        ),
        ValidationReport(passed=True, violations=[], checked_rules=1),
    ]

    def fake_validate(_circuit_data, _intent_dict, _solved_params):
        if reports:
            return reports.pop(0)
        return ValidationReport(passed=True, violations=[], checked_rules=1)

    monkeypatch.setattr(service._validator, "validate", fake_validate)

    monkeypatch.setattr(
        service._repair,
        "repair",
        lambda circuit_data, solved_params, intent_dict, report: RepairResult(
            repaired=False,
            circuit_data=circuit_data,
            solved_params=solved_params,
            actions=[],
            rounds_used=1,
            final_report=report,
        ),
    )

    intent = CircuitIntent(
        intent_type="create",
        circuit_type="multi_stage",
        gain_target=25.0,
        confidence=0.9,
        device_preference="mosfet",
        raw_text="thiet ke 2 tang CS-CD direct coupling gain 20-30",
        hard_constraints={
            "gain_min": 20.0,
            "gain_max": 30.0,
            "output_impedance_max_ohm": 50.0,
            "direct_coupling_required": True,
        },
    )

    response = service._handle_create(intent, ChatResponse(), time.time(), mode=LLMMode.AIR)

    assert calls["n"] >= 2
    assert response.success is True
    assert response.template_id == "RETRY-OK"
    assert response.validation is not None
    assert response.validation.get("passed") is True


def test_validate_flow_fail_fast_regenerates_on_hard_constraint(monkeypatch) -> None:
    service = ChatbotService()

    initial = _mk_pipeline("INITIAL-FAIL", actual_gain=8.0)
    retried = _mk_pipeline("RETRY-OK", actual_gain=25.0)

    calls = {"n": 0}

    def fake_handle_spec(_spec):
        calls["n"] += 1
        return initial if calls["n"] == 1 else retried

    monkeypatch.setattr(service._ai_core, "handle_spec", fake_handle_spec)

    def fake_validate(circuit_data, _intent_dict, _solved_params):
        if circuit_data.get("template_id") == "RETRY-OK":
            return ValidationReport(passed=True, violations=[], checked_rules=1)
        return ValidationReport(
            passed=False,
            violations=[Violation(code="HARD_ZOUT_MAX", severity="error", message="zout too high")],
            checked_rules=1,
        )

    monkeypatch.setattr(service._validator, "validate", fake_validate)

    intent = CircuitIntent(
        intent_type="validate",
        circuit_type="multi_stage",
        gain_target=25.0,
        confidence=0.9,
        device_preference="mosfet",
        raw_text="kiem tra mạch 2 tang CS-CD direct coupling gain 20-30",
        hard_constraints={
            "gain_min": 20.0,
            "gain_max": 30.0,
            "output_impedance_max_ohm": 50.0,
            "direct_coupling_required": True,
        },
    )

    response = service._handle_validate(intent, ChatResponse(), time.time(), mode=LLMMode.AIR)

    assert calls["n"] >= 2
    assert response.success is True
    assert response.validation is not None
    assert response.validation.get("passed") is True


def test_modify_flow_fail_fast_regenerates_on_hard_constraint(monkeypatch) -> None:
    service = ChatbotService()

    initial = _mk_pipeline("INITIAL-FAIL", actual_gain=8.0)
    retried = _mk_pipeline("RETRY-OK", actual_gain=25.0)

    calls = {"n": 0}

    def fake_handle_spec(_spec):
        calls["n"] += 1
        return initial if calls["n"] == 1 else retried

    monkeypatch.setattr(service._ai_core, "handle_spec", fake_handle_spec)

    def fake_validate(circuit_data, _intent_dict, _solved_params):
        if circuit_data.get("template_id") == "RETRY-OK":
            return ValidationReport(passed=True, violations=[], checked_rules=1)
        return ValidationReport(
            passed=False,
            violations=[Violation(code="HARD_ZOUT_MAX", severity="error", message="zout too high")],
            checked_rules=1,
        )

    monkeypatch.setattr(service._validator, "validate", fake_validate)

    monkeypatch.setattr(
        service._repair,
        "repair",
        lambda circuit_data, solved_params, intent_dict, report: RepairResult(
            repaired=False,
            circuit_data=circuit_data,
            solved_params=solved_params,
            actions=[],
            rounds_used=1,
            final_report=report,
        ),
    )

    intent = CircuitIntent(
        intent_type="modify",
        circuit_type="multi_stage",
        gain_target=25.0,
        confidence=0.9,
        device_preference="mosfet",
        raw_text="thêm linh kiện cho mạch CS-CD direct coupling gain 20-30",
        edit_operations=[EditOperation(action="add_component", target="RNEW", params={"type": "resistor", "value": 1000.0})],
        hard_constraints={
            "gain_min": 20.0,
            "gain_max": 30.0,
            "output_impedance_max_ohm": 50.0,
            "direct_coupling_required": True,
        },
    )

    response = service._handle_modify(intent, ChatResponse(), time.time(), mode=LLMMode.AIR)

    assert calls["n"] >= 2
    assert response.success is True
    assert response.validation is not None
    assert response.validation.get("passed") is True
