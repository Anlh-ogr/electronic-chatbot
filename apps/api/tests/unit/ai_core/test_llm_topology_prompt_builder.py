from __future__ import annotations

from app.domains.circuits.ai_core.llm_topology_contracts import PromptVersion, TopologySelectionInput
from app.domains.circuits.ai_core.llm_topology_prompt_builder import build_topology_prompt


def _input_model(version: PromptVersion) -> TopologySelectionInput:
    return TopologySelectionInput(
        prompt_version=version,
        user_spec={"circuit_type": "common_emitter", "gain": 20.0, "extra_requirements": []},
        available_topologies=["common_emitter", "common_collector"],
        topology_metadata={"common_emitter": {"priority_score": 0.8}},
        constraints={"must_select_from_available_topologies": True},
    )


def test_prompt_builder_v1_contains_required_contract_fields() -> None:
    bundle = build_topology_prompt(_input_model(PromptVersion.V1))

    assert bundle.prompt_version == PromptVersion.V1
    assert "Return JSON only" in bundle.system_prompt
    assert bundle.user_payload["contract_version"] == "topology_selection.v1"
    assert "available_topologies" in bundle.user_payload
    assert "topology_metadata" in bundle.user_payload
    assert "constraints" in bundle.user_payload


def test_prompt_builder_v2_enforces_json_only_and_no_extra_text() -> None:
    bundle = build_topology_prompt(_input_model(PromptVersion.V2))

    assert bundle.prompt_version == PromptVersion.V2
    assert "Output JSON only" in bundle.system_prompt
    assert bundle.user_payload["contract_version"] == "topology_selection.v2"
    assert bundle.user_payload["output_contract"]["json_only"] is True
    assert bundle.user_payload["output_contract"]["no_extra_text"] is True
