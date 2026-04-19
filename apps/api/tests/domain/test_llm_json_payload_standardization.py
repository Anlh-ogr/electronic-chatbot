import sys
from pathlib import Path

# Ensure app package imports work when running tests from apps/api
APP_DIR = Path(__file__).resolve().parents[2] / "app"
sys.path.insert(0, str(APP_DIR))

from app.application.ai.chatbot_service import ChatbotService
from app.application.ai.llm_router import LLMMode
from app.application.ai.nlg_service import NLGService
from app.application.ai.nlu_service import CircuitIntent
from app.application.services.circuit_design_orchestrator import CircuitDesignOrchestrator


class _FakeRouter:
    def __init__(self, *, json_response=None, text_response: str = "ok") -> None:
        self._json_response = json_response if json_response is not None else {"ok": True}
        self._text_response = text_response
        self.calls = []

    def is_available(self, *args, **kwargs) -> bool:
        return True

    def chat_json(self, *args, **kwargs):
        self.calls.append(("json", args, kwargs))
        if isinstance(self._json_response, dict):
            return dict(self._json_response)
        return self._json_response

    def chat_text(self, *args, **kwargs):
        self.calls.append(("text", args, kwargs))
        return self._text_response


class _DummyIntent:
    circuit_type = "common_emitter"


def test_nlg_llm_calls_use_structured_json_payloads() -> None:
    router = _FakeRouter(text_response="ok")
    nlg = NLGService()
    nlg._router = router

    nlg._llm_success_response(
        circuit_type="common_emitter",
        gain_actual=11.5,
        gain_target=10.0,
        params={"R1": 10000.0},
        gain_formula="Av = -gm*Rc",
        warnings=[],
        template_id="tmpl_ce",
        mode=LLMMode.FAST,
    )
    nlg._llm_error_response(
        error_msg="domain validation failed",
        stage="validate",
        circuit_type="common_emitter",
        gain_target=10.0,
        vcc=12.0,
        mode=LLMMode.FAST,
    )
    nlg._llm_clarification(
        circuit_type="common_emitter",
        missing_fields=["gain", "vcc"],
        mode=LLMMode.FAST,
    )
    nlg._llm_modify_response(
        intent=_DummyIntent(),
        edit_log=["change R1"],
        circuit_data={"components": [{"id": "R1"}]},
        solved={"R1": 4700.0},
        mode=LLMMode.FAST,
    )

    payload_tasks = []
    for kind, _args, kwargs in router.calls:
        if kind != "text":
            continue
        payload = kwargs.get("user_content")
        assert isinstance(payload, dict)
        assert payload.get("sv") == "req.v1"
        assert payload.get("of") == "md"
        assert isinstance(payload.get("in"), dict)
        payload_tasks.append(payload.get("tk"))

    assert payload_tasks == [
        "nlg.s.v1",
        "nlg.e.v1",
        "nlg.c.v1",
        "nlg.m.v1",
    ]


def test_chatbot_llm_helpers_use_structured_json_payloads() -> None:
    router = _FakeRouter(json_response={"sv": "domain.v1", "ok": True}, text_response="ok")

    service = ChatbotService.__new__(ChatbotService)
    service._router = router
    service._electronics_domain_only = True

    assert service._domain_check("thiet ke mach ce", mode=LLMMode.FAST) is None
    assert service._smart_clarification("thiet ke ce", ["gain", "vcc"], mode=LLMMode.FAST) == "ok"

    intent = CircuitIntent(
        intent_type="create",
        circuit_type="common_emitter",
        topology="common_emitter",
        gain_target=15.0,
        vcc=12.0,
        frequency=1000.0,
        raw_text="thiet ke ce gain 15 vcc 12v",
    )

    assert service._reasoning_fallback(intent, "template not found", mode=LLMMode.FAST) == "ok"
    assert service._reasoning_explain(intent, mode=LLMMode.FAST) == "ok"

    json_calls = [c for c in router.calls if c[0] == "json"]
    text_calls = [c for c in router.calls if c[0] == "text"]

    assert len(json_calls) == 1
    domain_payload = json_calls[0][2].get("user_content")
    assert isinstance(domain_payload, dict)
    assert domain_payload.get("sv") == "req.v1"
    assert domain_payload.get("tk") == "domain.check.v1"
    assert domain_payload.get("of") == "json"
    assert domain_payload.get("in", {}).get("txt") == "thiet ke mach ce"

    text_tasks = []
    for _kind, _args, kwargs in text_calls:
        payload = kwargs.get("user_content")
        assert isinstance(payload, dict)
        assert payload.get("sv") == "req.v1"
        assert payload.get("of") == "md"
        text_tasks.append(payload.get("tk"))

    assert text_tasks == [
        "chat.c.v1",
        "chat.rf.v1",
        "chat.rx.v1",
    ]


def test_orchestrator_propose_components_uses_structured_json_payload() -> None:
    router = _FakeRouter(
        json_response={
            "sv": "cmp.v1",
            "tp": "CE",
            "r1": 12000.0,
            "r2": 2200.0,
            "rc": 4700.0,
            "re": 1000.0,
            "v": 12.0,
            "b": 120.0,
        }
    )

    orchestrator = CircuitDesignOrchestrator(
        llm_router=router,
        dc_validator=object(),
        ngspice_runner=object(),
    )

    intent = CircuitIntent(
        topology="common_emitter",
        gain_target=12.0,
        vcc=12.0,
        frequency=1000.0,
    )

    components = orchestrator._propose_components(
        intent=intent,
        feedback_history=[
            {
                "attempt": 1,
                "type": "domain_error",
                "errors": ["zout too high"],
                "suggestions": ["decrease RC"],
            }
        ],
        mode=LLMMode.FAST,
    )

    assert components is not None
    assert components.R1 == 12000.0

    assert len(router.calls) == 1
    kind, _args, kwargs = router.calls[0]
    assert kind == "json"
    payload = kwargs.get("user_content")
    assert isinstance(payload, dict)
    assert payload.get("sv") == "req.v1"
    assert payload.get("tk") == "cmp.propose.v1"
    assert payload.get("of") == "json"
    assert payload.get("in", {}).get("it", {}).get("tp") == "CE"