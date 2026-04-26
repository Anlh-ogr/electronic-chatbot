from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictSelectorModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PromptVersion(str, Enum):
    V1 = "v1"
    V2 = "v2"


class TopologySelectionInput(StrictSelectorModel):
    prompt_version: PromptVersion = PromptVersion.V2
    user_spec: Dict[str, Any]
    available_topologies: List[str] = Field(min_length=1)
    topology_metadata: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    constraints: Dict[str, Any] = Field(default_factory=dict)


class LLMTopologyOutput(StrictSelectorModel):
    selected_topology: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: List[str] = Field(default_factory=list)
    constraints_checked: List[str] = Field(default_factory=list)


class SelectorError(StrictSelectorModel):
    code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class TopologySelectionResult(StrictSelectorModel):
    ok: bool
    prompt_version: PromptVersion
    validated: bool = False
    llm_output: Optional[LLMTopologyOutput] = None
    selected_topology: Optional[str] = None
    error: Optional[SelectorError] = None


class RuleResultItem(StrictSelectorModel):
    rule_id: str
    passed: bool
    penalty: float = Field(ge=0.0, le=1.0)
    message: str


class RuleEvaluationResult(StrictSelectorModel):
    passed: bool
    penalty_score: float = Field(ge=0.0, le=1.0)
    results: List[RuleResultItem] = Field(default_factory=list)


class TopologySelectionLogEntry(StrictSelectorModel):
    input: Dict[str, Any]
    prompt_version: str
    llm_output: Optional[Dict[str, Any]] = None
    validated: bool
    final_topology: str
