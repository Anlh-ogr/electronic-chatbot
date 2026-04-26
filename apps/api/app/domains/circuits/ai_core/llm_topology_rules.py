from __future__ import annotations

from typing import Any, Dict, List

from .llm_topology_contracts import RuleEvaluationResult, RuleResultItem, TopologySelectionInput


class TopologyRuleEngine:
    """Business safety rules applied after LLM topology selection."""

    def evaluate(
        self,
        selected_topology: str,
        selector_input: TopologySelectionInput,
    ) -> RuleEvaluationResult:
        results: List[RuleResultItem] = []

        gain_value = _safe_float(selector_input.user_spec.get("gain"))
        high_gain_threshold = _safe_float(selector_input.constraints.get("high_gain_threshold"))
        if high_gain_threshold is None:
            high_gain_threshold = 100.0

        # Rule 1: high gain must not use common collector.
        if (
            gain_value is not None
            and gain_value >= high_gain_threshold
            and _is_common_collector(selected_topology)
        ):
            results.append(
                RuleResultItem(
                    rule_id="high_gain_reject_common_collector",
                    passed=False,
                    penalty=1.0,
                    message=(
                        "Rejected by rule: high gain request cannot use common_collector "
                        f"(gain={gain_value}, threshold={high_gain_threshold})."
                    ),
                )
            )
        else:
            results.append(
                RuleResultItem(
                    rule_id="high_gain_reject_common_collector",
                    passed=True,
                    penalty=0.0,
                    message="Rule passed.",
                )
            )

        # Rule 2: high input impedance should penalize common emitter.
        if _requires_high_input_impedance(selector_input.user_spec) and _is_common_emitter(selected_topology):
            results.append(
                RuleResultItem(
                    rule_id="high_input_impedance_penalize_common_emitter",
                    passed=True,
                    penalty=0.25,
                    message=(
                        "Penalty applied: common_emitter is less suitable for "
                        "high input impedance targets."
                    ),
                )
            )
        else:
            results.append(
                RuleResultItem(
                    rule_id="high_input_impedance_penalize_common_emitter",
                    passed=True,
                    penalty=0.0,
                    message="Rule passed.",
                )
            )

        penalty_score = min(1.0, sum(item.penalty for item in results))
        all_passed = all(item.passed for item in results)

        return RuleEvaluationResult(
            passed=all_passed,
            penalty_score=penalty_score,
            results=results,
        )


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _requires_high_input_impedance(user_spec: Dict[str, Any]) -> bool:
    requirements = user_spec.get("extra_requirements")
    if not isinstance(requirements, list):
        return False

    normalized = {str(item).strip().lower() for item in requirements}
    return "high_input_impedance" in normalized


def _is_common_collector(topology: str) -> bool:
    return str(topology).strip().lower() in {"common_collector", "cc", "emitter_follower"}


def _is_common_emitter(topology: str) -> bool:
    return str(topology).strip().lower() in {"common_emitter", "ce"}
