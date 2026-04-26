from __future__ import annotations

from typing import Any, Dict, List

from app.domains.circuits.ai_core.llm_topology_selector import LLMTopologySelector


class _FakeRouter:
    def __init__(self, responses: List[Any], *, gemini_available: bool = True) -> None:
        self._responses = list(responses)
        self._gemini_available = gemini_available
        self.calls = 0

    def get_status(self) -> Dict[str, Any]:
        return {"gemini_available": self._gemini_available}

    def chat_json(self, *args, **kwargs) -> Any:
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return None


def _selector_input() -> Dict[str, Any]:
    return {
        "prompt_version": "v2",
        "user_spec": {
            "circuit_type": "common_emitter",
            "gain": 20.0,
            "extra_requirements": [],
        },
        "available_topologies": ["common_emitter", "common_collector"],
        "topology_metadata": {
            "common_emitter": {"priority_score": 0.8},
        },
        "constraints": {
            "must_select_from_available_topologies": True,
            "high_gain_threshold": 100.0,
        },
    }


def test_selector_retries_malformed_output_then_succeeds() -> None:
    router = _FakeRouter(
        responses=[
            "not json",
            {
                "selected_topology": "common_emitter",
                "confidence": 0.88,
                "rationale": ["family match"],
                "constraints_checked": ["available_topologies"],
            },
        ]
    )
    selector = LLMTopologySelector(router=router, enabled=True, max_malformed_retries=2)

    result = selector.select_topology(_selector_input())

    assert result["ok"] is True
    assert result["validated"] is True
    assert result["selected_topology"] == "common_emitter"
    assert router.calls == 2


def test_selector_returns_business_validation_error_for_unknown_topology() -> None:
    router = _FakeRouter(
        responses=[
            {
                "selected_topology": "non_existing_topology",
                "confidence": 0.9,
                "rationale": ["best fit"],
                "constraints_checked": [],
            }
        ]
    )
    selector = LLMTopologySelector(router=router, enabled=True, max_malformed_retries=2)

    result = selector.select_topology(_selector_input())

    assert result["ok"] is False
    assert result["error"]["code"] == "BUSINESS_VALIDATION_FAILED"


def test_selector_stops_after_max_malformed_retries() -> None:
    router = _FakeRouter(responses=["x", "y", "z"])
    selector = LLMTopologySelector(router=router, enabled=True, max_malformed_retries=2)

    result = selector.select_topology(_selector_input())

    assert result["ok"] is False
    assert result["error"]["code"] == "MALFORMED_OUTPUT"
    assert router.calls == 3


def test_selector_returns_unavailable_when_runtime_disabled() -> None:
    router = _FakeRouter(responses=[], gemini_available=False)
    selector = LLMTopologySelector(router=router, enabled=True)

    result = selector.select_topology(_selector_input())

    assert result["ok"] is False
    assert result["error"]["code"] == "LLM_UNAVAILABLE"
    assert router.calls == 0
