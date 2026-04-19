import sys
from pathlib import Path

import pytest

# Ensure app package imports work when running tests from apps/api
APP_DIR = Path(__file__).resolve().parents[2] / "app"
sys.path.insert(0, str(APP_DIR))

from app.application.ai.nlu_service import CircuitIntent, NLUService


class _FakeRouter:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls = []

    def chat_json(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return dict(self._payload)


def _mk_llm_payload(intent_code: str) -> dict:
    return {
        "sv": "nlu.v1",
        "it": intent_code,
        "tp": "CE",
        "gn": 10.0,
        "vc": 12.0,
        "fq": 1000.0,
        "ic": 1,
        "ci": {},
        "vr": {"mn": None, "mx": None},
        "im": "SE",
        "hc": False,
        "ob": False,
        "po": False,
        "sm": "AUTO",
        "dp": "BJT",
        "xr": [],
        "eo": [],
        "ts": "ALL",
        "hcst": {},
        "sp": [],
        "ra": [],
        "ed": "B",
        "ef": [],
        "cf": 0.95,
    }


def test_extraction_prompt_declares_required_intent_type_values() -> None:
    nlu = NLUService()

    prompt = nlu._build_extraction_prompt()

    assert "nlu.v1" in prompt
    assert '"it":"CRT|MOD|VAL|EXP"' in prompt


@pytest.mark.parametrize(
    ("intent_code", "expected_type"),
    [
        ("CRT", "create"),
        ("MOD", "modify"),
        ("VAL", "validate"),
        ("EXP", "explain"),
    ],
)
def test_llm_extract_accepts_all_allowed_intent_types(intent_code: str, expected_type: str) -> None:
    nlu = NLUService()
    router = _FakeRouter(_mk_llm_payload(intent_code))
    nlu._router = router

    intent = nlu._llm_extract("thiet ke ce gain 10")

    assert intent is not None
    assert intent.intent_type == expected_type
    assert intent.source == "llm"
    assert len(router.calls) == 1


def test_llm_extract_sends_structured_json_payload_to_router() -> None:
    nlu = NLUService()
    router = _FakeRouter(_mk_llm_payload("CRT"))
    nlu._router = router

    intent = nlu._llm_extract("thiet ke ce gain 10")

    assert intent is not None
    assert len(router.calls) == 1

    _, kwargs = router.calls[0]
    assert isinstance(kwargs.get("user_content"), dict)
    assert kwargs["user_content"].get("sv") == "req.v1"
    assert kwargs["user_content"].get("tk") == "nlu.extract.v1"
    assert kwargs["user_content"].get("of") == "json"
    assert kwargs["user_content"].get("in", {}).get("txt") == "thiet ke ce gain 10"


@pytest.mark.parametrize("invalid_intent_code", ["", "BAD", "INVALID_TYPE"])
def test_llm_extract_rejects_invalid_schema(invalid_intent_code: str) -> None:
    nlu = NLUService()
    router = _FakeRouter(_mk_llm_payload(invalid_intent_code))
    nlu._router = router

    intent = nlu._llm_extract("thiet ke ce gain 10")

    assert intent is None


def test_understand_pipeline_prefers_llm_when_confidence_higher() -> None:
    nlu = NLUService()

    # Rule-based baseline
    rule_intent = CircuitIntent(
        intent_type="create",
        circuit_type="common_emitter",
        topology="common_emitter",
        confidence=0.6,
        raw_text="thiet ke ce gain 10",
        source="rule_based",
    )

    # LLM override with allowed intent_type
    llm_payload = _mk_llm_payload("EXP")
    llm_payload["cf"] = 0.95

    nlu._router = _FakeRouter(llm_payload)
    nlu._rule_based_parse = lambda _text: rule_intent

    merged = nlu.understand("thiet ke ce gain 10")

    assert merged.source == "merged"
    assert merged.intent_type == "explain"


def test_understand_pipeline_keeps_rule_intent_when_llm_intent_type_invalid() -> None:
    nlu = NLUService()

    # Rule-based says modify
    rule_intent = CircuitIntent(
        intent_type="modify",
        circuit_type="common_emitter",
        topology="common_emitter",
        confidence=0.7,
        raw_text="thay doi R1 thanh 10k",
        source="rule_based",
    )

    # Invalid enum code -> rejected by schema validation
    llm_payload = _mk_llm_payload("BAD")
    llm_payload["cf"] = 0.95

    nlu._router = _FakeRouter(llm_payload)
    nlu._rule_based_parse = lambda _text: rule_intent

    merged = nlu.understand("thay doi R1 thanh 10k")

    assert merged.source == "rule_based"
    assert merged.intent_type == "modify"
