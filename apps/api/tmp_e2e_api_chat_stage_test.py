from __future__ import annotations

import json
from dataclasses import dataclass
from types import MethodType, SimpleNamespace

from fastapi.testclient import TestClient

from app.application.ai.chatbot_service import ChatbotService
from app.application.ai.nlu_service import CircuitIntent
from app.interfaces.http.routes import chatbot as chatbot_route
from app.main import app


@dataclass
class FakePipelineResult:
    success: bool
    circuit: object
    solved: object
    plan: object
    error: str = ""
    stage_reached: str = "done"

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "stage_reached": self.stage_reached,
            "error": self.error,
        }


def run_case_intent_fallback(client: TestClient) -> dict:
    trace: list[str] = []
    service = ChatbotService()

    def domain_check(_text, mode):
        trace.append("01.domain_check")
        return None

    def understand(_text, mode=None):
        trace.append("02.nlu_understand")
        return CircuitIntent(
            intent_type="invalid_type",
            circuit_type="common_emitter",
            topology="common_emitter",
            gain_target=10.0,
            vcc=12.0,
            confidence=0.9,
            raw_text="fallback request",
        )

    def handle_create(_self, intent, response, start, mode):
        trace.append("03.handle_create")
        response.success = True
        response.message = f"fallback_to_{intent.intent_type}_ok"
        response.processing_time_ms = 1.0
        return response

    service._domain_check = domain_check
    service._nlu.understand = understand
    service._handle_create = MethodType(handle_create, service)

    chatbot_route._chatbot_service = service
    resp = client.post("/api/chat", json={"message": "fallback test", "mode": "fast"})
    data = resp.json()

    ok = (
        resp.status_code == 200
        and data.get("success") is True
        and data.get("message") == "fallback_to_create_ok"
        and trace == ["01.domain_check", "02.nlu_understand", "03.handle_create"]
    )

    return {
        "case": "intent_fallback_to_create",
        "ok": ok,
        "status_code": resp.status_code,
        "message": data.get("message"),
        "trace": trace,
        "intent_type": ((data.get("intent") or {}).get("intent_type")),
    }


def run_case_physics_hard_fail(client: TestClient) -> dict:
    trace: list[str] = []
    service = ChatbotService()

    def domain_check(_text, mode):
        trace.append("01.domain_check")
        return None

    def understand(_text, mode=None):
        trace.append("02.nlu_understand")
        return CircuitIntent(
            intent_type="create",
            circuit_type="common_source",
            topology="common_source",
            gain_target=8.0,
            vcc=12.0,
            confidence=0.95,
            raw_text="thiet ke common source gain 8",
        )

    def handle_spec(_spec):
        trace.append("03.ai_core_handle_spec")
        circuit_data = {
            "topology_type": "common_source",
            "components": [
                {"id": "V1", "type": "VOLTAGE_SOURCE", "parameters": {"voltage": 12.0}},
                {"id": "R1", "type": "RESISTOR", "parameters": {"resistance": 100000}},
                {"id": "R2", "type": "RESISTOR", "parameters": {"resistance": 22000}},
                {"id": "RD", "type": "RESISTOR", "parameters": {"resistance": 4700}},
                {"id": "RS", "type": "RESISTOR", "parameters": {"resistance": 1000}},
            ],
            "nets": [],
        }
        fake_circuit = SimpleNamespace(
            circuit_data=circuit_data,
            gain_formula="Av ~= gm*RD",
            template_id="CS-TMP-01",
            validation=SimpleNamespace(warnings=[]),
        )
        fake_solved = SimpleNamespace(
            values={
                "R1": 100000.0,
                "R2": 22000.0,
                "RC": 4700.0,
                "RE": 1000.0,
                "actual_gain": 8.0,
                "VCC": 12.0,
            },
            actual_gain=8.0,
            stage_analysis=[],
            warnings=[],
        )
        fake_plan = SimpleNamespace(matched_template_id="CS-TMP-01")
        return FakePipelineResult(True, fake_circuit, fake_solved, fake_plan)

    original_validate = service._validator.validate
    original_run_physics = service._run_physics_validation
    original_nlg_error = service._nlg.generate_error_response

    def wrapped_validate(*args, **kwargs):
        trace.append("04.constraint_validate")
        return original_validate(*args, **kwargs)

    def wrapped_run_physics(*args, **kwargs):
        trace.append("05.physics_validate")
        return original_run_physics(*args, **kwargs)

    def wrapped_nlg_error(*args, **kwargs):
        trace.append("06.nlg_error_response")
        return original_nlg_error(*args, **kwargs)

    def wrapped_apply_sim(*args, **kwargs):
        trace.append("XX.simulation_stage_called")
        return None

    service._domain_check = domain_check
    service._nlu.understand = understand
    service._ai_core.handle_spec = handle_spec
    service._validator.validate = wrapped_validate
    service._run_physics_validation = wrapped_run_physics
    service._nlg.generate_error_response = wrapped_nlg_error
    service._apply_simulation_requirements = wrapped_apply_sim

    chatbot_route._chatbot_service = service
    resp = client.post("/api/chat", json={"message": "physics fail test", "mode": "fast"})
    data = resp.json()

    expected_start = [
        "01.domain_check",
        "02.nlu_understand",
        "03.ai_core_handle_spec",
        "04.constraint_validate",
        "04.constraint_validate",
        "05.physics_validate",
    ]

    ok = (
        resp.status_code == 200
        and data.get("success") is False
        and isinstance(data.get("message"), str)
        and bool(data.get("message"))
        and trace[: len(expected_start)] == expected_start
        and trace.count("03.ai_core_handle_spec") >= 1
        and trace.count("04.constraint_validate") >= 2
        and trace.count("05.physics_validate") >= 1
        and trace[-1] == "06.nlg_error_response"
        and "XX.simulation_stage_called" not in trace
    )

    return {
        "case": "physics_gate_hard_fail",
        "ok": ok,
        "status_code": resp.status_code,
        "message": data.get("message"),
        "trace": trace,
        "physics_validation": (data.get("validation") or {}).get("physics"),
    }


def run_case_simulation_feedback_hard_fail(client: TestClient) -> dict:
    trace: list[str] = []
    service = ChatbotService()

    def domain_check(_text, mode):
        trace.append("01.domain_check")
        return None

    def understand(_text, mode=None):
        trace.append("02.nlu_understand")
        return CircuitIntent(
            intent_type="create",
            circuit_type="common_emitter",
            topology="common_emitter",
            gain_target=5.0,
            vcc=5.0,
            confidence=0.95,
            raw_text="thiet ke CE gain 5 VCC=5V",
        )

    def handle_spec(_spec):
        trace.append("03.ai_core_handle_spec")
        circuit_data = {
            "topology_type": "common_emitter",
            "components": [
                {"id": "V1", "type": "VOLTAGE_SOURCE", "parameters": {"voltage": 5.0}},
                {"id": "R1", "type": "RESISTOR", "parameters": {"resistance": 68000}},
                {"id": "R2", "type": "RESISTOR", "parameters": {"resistance": 12000}},
                {"id": "RC", "type": "RESISTOR", "parameters": {"resistance": 3300}},
            ],
            "nets": [],
        }
        fake_circuit = SimpleNamespace(
            circuit_data=circuit_data,
            gain_formula="Av ~= RC/re",
            template_id="CE-TMP-01",
            validation=SimpleNamespace(warnings=[]),
        )
        fake_solved = SimpleNamespace(
            values={
                "R1": 68000.0,
                "R2": 12000.0,
                "RC": 3300.0,
                "RE": 470.0,
                "actual_gain": 5.0,
                "VCC": 5.0,
            },
            actual_gain=5.0,
            stage_analysis=[],
            warnings=[],
        )
        fake_plan = SimpleNamespace(matched_template_id="CE-TMP-01")
        return FakePipelineResult(True, fake_circuit, fake_solved, fake_plan)

    def wrapped_validate(*_args, **_kwargs):
        trace.append("04.constraint_validate")
        return SimpleNamespace(
            passed=True,
            warnings=[],
            errors=[],
            to_dict=lambda: {"passed": True, "violations": [], "errors_count": 0, "warnings_count": 0, "checked_rules": 1},
        )

    def wrapped_physics(*_args, **_kwargs):
        trace.append("05.physics_validate")
        return {
            "enabled": True,
            "passed": True,
            "errors": [],
            "suggestions": [],
            "metrics": {},
        }

    def wrapped_build_analysis(*_args, **_kwargs):
        trace.append("06.build_analysis")
        return {
            "parameters": {"gain_actual": 5.0, "gain_target": 5.0, "vcc": 5.0},
            "voltage_range": {"min": 0.0, "max": 5.0},
            "cascading": {"stage_table": []},
            "simulation": {
                "status": "completed",
                "analysis": {
                    "gain_metrics": {
                        "status": "ok",
                        "expected_av": 5.0,
                        "measured_av": 3.2,
                        "rel_error_pct": 36.0,
                        "phase_match": True,
                    }
                },
            },
        }

    original_eval_sim = service._evaluate_simulation_feedback

    def wrapped_eval_sim(*args, **kwargs):
        trace.append("07.sim_feedback_gate")
        return original_eval_sim(*args, **kwargs)

    def wrapped_retry_sim(*_args, **_kwargs):
        trace.append("08.retry_sim_attempt")
        return None

    original_nlg_error = service._nlg.generate_error_response

    def wrapped_nlg_error(*args, **kwargs):
        trace.append("09.nlg_error_response")
        return original_nlg_error(*args, **kwargs)

    service._domain_check = domain_check
    service._nlu.understand = understand
    service._ai_core.handle_spec = handle_spec
    service._validator.validate = wrapped_validate
    service._run_physics_validation = wrapped_physics
    service._build_design_analysis = wrapped_build_analysis
    service._evaluate_simulation_feedback = wrapped_eval_sim
    service._retry_pipeline_for_simulation_feedback = wrapped_retry_sim
    service._nlg.generate_error_response = wrapped_nlg_error

    chatbot_route._chatbot_service = service
    resp = client.post("/api/chat", json={"message": "simulation feedback fail test", "mode": "fast"})
    data = resp.json()

    expected_prefix = [
        "01.domain_check",
        "02.nlu_understand",
        "03.ai_core_handle_spec",
        "04.constraint_validate",
        "04.constraint_validate",
        "05.physics_validate",
        "06.build_analysis",
        "07.sim_feedback_gate",
        "08.retry_sim_attempt",
        "09.nlg_error_response",
    ]

    ok = (
        resp.status_code == 200
        and data.get("success") is False
        and trace[: len(expected_prefix)] == expected_prefix
        and isinstance(data.get("message"), str)
        and bool(data.get("message"))
    )

    return {
        "case": "simulation_feedback_hard_fail",
        "ok": ok,
        "status_code": resp.status_code,
        "message": data.get("message"),
        "trace": trace,
    }


def main() -> None:
    client = TestClient(app)

    results = [
        run_case_intent_fallback(client),
        run_case_physics_hard_fail(client),
        run_case_simulation_feedback_hard_fail(client),
    ]

    summary = {
        "all_passed": all(r["ok"] for r in results),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
