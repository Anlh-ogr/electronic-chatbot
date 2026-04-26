from __future__ import annotations

from app.domains.circuits.ai_core.spec_parser import UserSpec
from app.domains.circuits.ai_core.topology_planner import TopologyPlan, TopologyPlanner


class _SelectorStub:
    def __init__(self, result):
        self._result = dict(result)

    def select_topology(self, input_json):
        return dict(self._result)


def _candidate(template_id: str, family: str, block_type: str, priority: float = 0.5):
    return {
        "template_id": template_id,
        "domain": {
            "family": family,
            "topology_tags": ["single_supply"],
        },
        "planner_hints": {
            "required_capabilities": [],
            "priority_score": priority,
        },
        "functional_structure": {
            "pattern_signature": {
                "ordered_block_types": [block_type],
            },
            "blocks": [{"type": block_type}],
            "total_gain_formula": "Av",
        },
    }


def test_planner_falls_back_when_llm_choice_fails_rule_engine() -> None:
    selector = _SelectorStub(
        {
            "ok": True,
            "validated": True,
            "prompt_version": "v2",
            "selected_topology": "common_collector",
            "llm_output": {
                "selected_topology": "common_collector",
                "confidence": 0.85,
                "rationale": ["best by llm"],
                "constraints_checked": ["available_topologies"],
            },
        }
    )
    planner = TopologyPlanner(llm_selector=selector)

    spec = UserSpec(circuit_type="common_emitter", gain=150.0)
    plan = TopologyPlan(blocks=["ce_block"])
    candidates = [
        _candidate("T_CE", "common_emitter", "ce_block", 0.8),
        _candidate("T_CC", "common_collector", "cc_block", 0.9),
    ]

    planner._select_best_template(spec, plan, candidates, [])

    assert plan.matched_template_id == "T_CE"
    assert any("rejected by rule engine" in reason for reason in plan.rationale)


def test_planner_uses_llm_selected_topology_when_rules_pass() -> None:
    selector = _SelectorStub(
        {
            "ok": True,
            "validated": True,
            "prompt_version": "v2",
            "selected_topology": "common_collector",
            "llm_output": {
                "selected_topology": "common_collector",
                "confidence": 0.7,
                "rationale": ["llm preference"],
                "constraints_checked": ["available_topologies"],
            },
        }
    )
    planner = TopologyPlanner(llm_selector=selector)

    spec = UserSpec(circuit_type="common_emitter", gain=10.0)
    plan = TopologyPlan(blocks=["ce_block"])
    candidates = [
        _candidate("T_CE", "common_emitter", "ce_block", 0.9),
        _candidate("T_CC", "common_collector", "cc_block", 0.4),
    ]

    planner._select_best_template(spec, plan, candidates, [])

    assert plan.matched_template_id == "T_CC"
    assert any("LLM selected topology family 'common_collector'" in reason for reason in plan.rationale)
