from __future__ import annotations

from app.domains.circuits.ai_core.llm_topology_contracts import TopologySelectionInput
from app.domains.circuits.ai_core.llm_topology_rules import TopologyRuleEngine


def test_high_gain_rejects_common_collector() -> None:
    engine = TopologyRuleEngine()
    selector_input = TopologySelectionInput(
        prompt_version="v2",
        user_spec={"gain": 150.0, "extra_requirements": []},
        available_topologies=["common_collector", "common_emitter"],
        topology_metadata={},
        constraints={"high_gain_threshold": 100.0},
    )

    result = engine.evaluate("common_collector", selector_input)

    assert result.passed is False
    assert result.penalty_score == 1.0
    assert any(item.rule_id == "high_gain_reject_common_collector" and item.passed is False for item in result.results)


def test_high_input_impedance_penalizes_common_emitter() -> None:
    engine = TopologyRuleEngine()
    selector_input = TopologySelectionInput(
        prompt_version="v2",
        user_spec={"gain": 12.0, "extra_requirements": ["high_input_impedance"]},
        available_topologies=["common_emitter", "common_drain"],
        topology_metadata={},
        constraints={},
    )

    result = engine.evaluate("common_emitter", selector_input)

    assert result.passed is True
    assert result.penalty_score > 0.0
    assert any(item.rule_id == "high_input_impedance_penalize_common_emitter" and item.penalty > 0.0 for item in result.results)


def test_nominal_selection_passes_without_penalty() -> None:
    engine = TopologyRuleEngine()
    selector_input = TopologySelectionInput(
        prompt_version="v2",
        user_spec={"gain": 20.0, "extra_requirements": []},
        available_topologies=["common_source", "common_emitter"],
        topology_metadata={},
        constraints={"high_gain_threshold": 100.0},
    )

    result = engine.evaluate("common_source", selector_input)

    assert result.passed is True
    assert result.penalty_score == 0.0
