from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .llm_topology_contracts import PromptVersion, TopologySelectionInput


@dataclass(frozen=True)
class TopologyPromptBundle:
    prompt_version: PromptVersion
    system_prompt: str
    user_payload: Dict[str, Any]


def build_topology_prompt(selector_input: TopologySelectionInput) -> TopologyPromptBundle:
    if selector_input.prompt_version == PromptVersion.V1:
        return TopologyPromptBundle(
            prompt_version=PromptVersion.V1,
            system_prompt=_system_prompt_v1(),
            user_payload=_payload_v1(selector_input),
        )

    return TopologyPromptBundle(
        prompt_version=PromptVersion.V2,
        system_prompt=_system_prompt_v2(),
        user_payload=_payload_v2(selector_input),
    )


def _system_prompt_v1() -> str:
    return (
        "You are a topology selector for analog circuits. "
        "Return JSON only. "
        "Do not output markdown, prose, or code fences. "
        "Return exactly one JSON object that matches this schema: "
        "{\"selected_topology\": string, \"confidence\": number in [0,1], "
        "\"rationale\": string[], \"constraints_checked\": string[]}."
    )


def _system_prompt_v2() -> str:
    return (
        "You are a deterministic production topology selector. "
        "Use only the provided input payload. "
        "Pick one topology from available_topologies only. "
        "Apply constraints strictly. "
        "If uncertain, choose the safest available topology under constraints. "
        "Output JSON only with no extra text. "
        "Do not include markdown, comments, or explanations outside JSON. "
        "Required schema: "
        "{\"selected_topology\": string, \"confidence\": number in [0,1], "
        "\"rationale\": string[], \"constraints_checked\": string[]}."
    )


def _payload_v1(selector_input: TopologySelectionInput) -> Dict[str, Any]:
    return {
        "contract_version": "topology_selection.v1",
        "available_topologies": selector_input.available_topologies,
        "topology_metadata": selector_input.topology_metadata,
        "constraints": selector_input.constraints,
        "input": selector_input.user_spec,
    }


def _payload_v2(selector_input: TopologySelectionInput) -> Dict[str, Any]:
    return {
        "contract_version": "topology_selection.v2",
        "decision_goal": "Select one safe topology with strict constraints",
        "available_topologies": selector_input.available_topologies,
        "topology_metadata": selector_input.topology_metadata,
        "constraints": selector_input.constraints,
        "input": selector_input.user_spec,
        "output_contract": {
            "json_only": True,
            "no_extra_text": True,
            "required_fields": [
                "selected_topology",
                "confidence",
                "rationale",
                "constraints_checked",
            ],
            "confidence_range": [0, 1],
        },
    }
