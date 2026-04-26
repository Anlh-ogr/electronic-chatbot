from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from pydantic import ValidationError

from app.application.ai.llm_router import LLMMode, LLMRole, get_router

from .llm_topology_contracts import (
    LLMTopologyOutput,
    PromptVersion,
    SelectorError,
    TopologySelectionInput,
    TopologySelectionResult,
)
from .llm_topology_prompt_builder import build_topology_prompt


logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


class LLMTopologySelector:
    """LLM-based topology selector with strict schema and safe fallback behavior."""

    def __init__(
        self,
        *,
        router: Optional[Any] = None,
        mode: Optional[LLMMode] = None,
        max_malformed_retries: int = 2,
        enabled: Optional[bool] = None,
    ) -> None:
        self._router = router or get_router()
        self._mode = mode or self._resolve_mode()
        self._max_malformed_retries = max(0, int(max_malformed_retries))
        self._enabled = _env_flag("TOPOLOGY_LLM_SELECTOR_ENABLED", True) if enabled is None else bool(enabled)

    def select_topology(self, input_json: Dict[str, Any]) -> Dict[str, Any]:
        prompt_version = _coerce_prompt_version(input_json.get("prompt_version"))

        try:
            selector_input = TopologySelectionInput.model_validate(input_json)
        except ValidationError as exc:
            return TopologySelectionResult(
                ok=False,
                prompt_version=prompt_version,
                validated=False,
                error=SelectorError(
                    code="INPUT_SCHEMA_VALIDATION_FAILED",
                    message="Input JSON does not satisfy topology selector contract.",
                    details={"errors": exc.errors()},
                ),
            ).model_dump(mode="json")

        if not self._is_runtime_available():
            return TopologySelectionResult(
                ok=False,
                prompt_version=selector_input.prompt_version,
                validated=False,
                error=SelectorError(
                    code="LLM_UNAVAILABLE",
                    message="LLM runtime is unavailable or disabled.",
                ),
            ).model_dump(mode="json")

        prompt = build_topology_prompt(selector_input)
        malformed_reasons = []

        for attempt in range(self._max_malformed_retries + 1):
            raw_response = self._router.chat_json(
                LLMRole.GENERAL,
                mode=self._mode,
                system=prompt.system_prompt,
                user_content=prompt.user_payload,
                temperature=0.0,
                max_tokens=512,
                response_model=None,
                max_schema_retries=0,
            )

            parsed = _safe_parse_json_object(raw_response)
            if parsed is None:
                malformed_reasons.append(
                    {
                        "attempt": attempt + 1,
                        "reason": "not_a_json_object",
                        "raw_type": type(raw_response).__name__,
                    }
                )
                continue

            try:
                llm_output = LLMTopologyOutput.model_validate(parsed)
            except ValidationError as exc:
                malformed_reasons.append(
                    {
                        "attempt": attempt + 1,
                        "reason": "schema_validation_failed",
                        "errors": exc.errors(),
                    }
                )
                continue

            business_error = _business_validate(llm_output, selector_input)
            if business_error is not None:
                return TopologySelectionResult(
                    ok=False,
                    prompt_version=selector_input.prompt_version,
                    validated=False,
                    llm_output=llm_output,
                    selected_topology=llm_output.selected_topology,
                    error=business_error,
                ).model_dump(mode="json")

            return TopologySelectionResult(
                ok=True,
                prompt_version=selector_input.prompt_version,
                validated=True,
                llm_output=llm_output,
                selected_topology=llm_output.selected_topology,
            ).model_dump(mode="json")

        return TopologySelectionResult(
            ok=False,
            prompt_version=selector_input.prompt_version,
            validated=False,
            error=SelectorError(
                code="MALFORMED_OUTPUT",
                message="LLM output was malformed after maximum retries.",
                details={"attempts": self._max_malformed_retries + 1, "reasons": malformed_reasons},
            ),
        ).model_dump(mode="json")

    def _is_runtime_available(self) -> bool:
        if not self._enabled:
            return False

        status_getter = getattr(self._router, "get_status", None)
        if callable(status_getter):
            try:
                status = status_getter()
                if isinstance(status, dict):
                    return bool(status.get("gemini_available", True))
            except Exception as exc:  # pragma: no cover - defensive branch
                logger.warning("LLM selector status check failed: %s", exc)

        return True

    @staticmethod
    def _resolve_mode() -> LLMMode:
        raw = (os.getenv("TOPOLOGY_LLM_MODE") or "fast").strip().lower()
        if raw in {"pro"}:
            return LLMMode.PRO
        if raw in {"think"}:
            return LLMMode.THINK
        if raw in {"ultra"}:
            return LLMMode.ULTRA
        return LLMMode.FAST


def select_topology(input_json: Dict[str, Any]) -> Dict[str, Any]:
    """Public function contract required by topology selection pipeline."""
    selector = LLMTopologySelector()
    return selector.select_topology(input_json)


def _safe_parse_json_object(raw_response: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw_response, dict):
        return raw_response

    if isinstance(raw_response, str):
        content = raw_response.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None

        return parsed if isinstance(parsed, dict) else None

    return None


def _business_validate(
    llm_output: LLMTopologyOutput,
    selector_input: TopologySelectionInput,
) -> Optional[SelectorError]:
    if not llm_output.selected_topology:
        return SelectorError(
            code="BUSINESS_VALIDATION_FAILED",
            message="selected_topology is missing.",
        )

    if llm_output.selected_topology not in selector_input.available_topologies:
        return SelectorError(
            code="BUSINESS_VALIDATION_FAILED",
            message="selected_topology is not in available_topologies.",
            details={
                "selected_topology": llm_output.selected_topology,
                "available_topologies": selector_input.available_topologies,
            },
        )

    return None


def _coerce_prompt_version(raw: Any) -> PromptVersion:
    if str(raw).strip().lower() == PromptVersion.V1.value:
        return PromptVersion.V1
    return PromptVersion.V2
