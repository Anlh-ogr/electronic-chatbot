"""Business safety rules applied after LLM topology selection.

Rules are driven by the topology characteristics defined in topology_wiring_spec,
ensuring that selecting a topology also enforces its structural constraints.
"""

from __future__ import annotations

import sys
import os
from typing import Any, Dict, List

from .llm_topology_contracts import RuleEvaluationResult, RuleResultItem, TopologySelectionInput

# Resolve topology spec from the application layer (avoid circular imports).
def _get_spec(family: str):
    try:
        from app.application.ai.topology_wiring_spec import get_spec
        return get_spec(family)
    except Exception:
        return None


class TopologyRuleEngine:
    """Business safety rules applied after LLM topology selection.

    Each rule maps one or more characteristics from topology_wiring_spec to a
    pass/fail decision.  Adding a new rule only requires adding a new method
    and calling it in evaluate().
    """

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

        spec = _get_spec(selected_topology)

        # ── Rule 1: High-gain request must not use Common Collector ────────
        # spec.gain_sign == "unity" → Av ≈ 1, useless for high-gain targets.
        if (
            gain_value is not None
            and gain_value >= high_gain_threshold
            and _is_common_collector(selected_topology)
        ):
            results.append(RuleResultItem(
                rule_id="high_gain_reject_common_collector",
                passed=False,
                penalty=1.0,
                message=(
                    f"Rejected: common_collector (Av≈1) cannot satisfy gain={gain_value} "
                    f"(threshold={high_gain_threshold}). "
                    f"Use common_emitter or common_base instead."
                ),
            ))
        else:
            results.append(RuleResultItem(
                rule_id="high_gain_reject_common_collector",
                passed=True,
                penalty=0.0,
                message="Rule passed.",
            ))

        # ── Rule 2: High-impedance source should penalise CE ──────────────
        # spec.zin_char for CE is "medium"; CC/NON-INV are better choices.
        if _requires_high_input_impedance(selector_input.user_spec) and _is_common_emitter(selected_topology):
            results.append(RuleResultItem(
                rule_id="high_input_impedance_penalize_common_emitter",
                passed=True,
                penalty=0.25,
                message="Penalty: common_emitter has medium Zin; prefer common_collector or non_inverting op-amp.",
            ))
        else:
            results.append(RuleResultItem(
                rule_id="high_input_impedance_penalize_common_emitter",
                passed=True,
                penalty=0.0,
                message="Rule passed.",
            ))

        # ── Rule 3: RF / high-frequency application prefers Common Base ───
        # spec: common_base.typical_use mentions "RF/wideband", "Miller effect".
        if _requires_rf_or_highfreq(selector_input.user_spec) and _is_common_emitter(selected_topology):
            results.append(RuleResultItem(
                rule_id="rf_prefer_common_base_over_ce",
                passed=True,
                penalty=0.20,
                message=(
                    "Penalty: for RF/high-frequency, common_base is preferred "
                    "(no Miller effect, lower input capacitance)."
                ),
            ))
        else:
            results.append(RuleResultItem(
                rule_id="rf_prefer_common_base_over_ce",
                passed=True,
                penalty=0.0,
                message="Rule passed.",
            ))

        # ── Rule 4: Buffer / impedance-matching task should use CC or NON-INV
        if _requires_buffer(selector_input.user_spec):
            if not (_is_common_collector(selected_topology) or _is_non_inverting(selected_topology)):
                results.append(RuleResultItem(
                    rule_id="buffer_prefer_cc_or_non_inverting",
                    passed=True,
                    penalty=0.30,
                    message=(
                        "Penalty: buffer/impedance-matching tasks are best served by "
                        "common_collector (Av≈1, very high Zin, very low Zout) "
                        "or opamp_non_inverting."
                    ),
                ))
            else:
                results.append(RuleResultItem(
                    rule_id="buffer_prefer_cc_or_non_inverting",
                    passed=True,
                    penalty=0.0,
                    message="Rule passed.",
                ))
        else:
            results.append(RuleResultItem(
                rule_id="buffer_prefer_cc_or_non_inverting",
                passed=True,
                penalty=0.0,
                message="Rule not applicable.",
            ))

        # ── Rule 5: Phase inversion requirement must match topology ────────
        # If the user explicitly requested phase inversion, the chosen topology
        # must have phase_inverted == True.
        phase_req = _required_phase(selector_input.user_spec)
        if phase_req is not None and spec is not None:
            if phase_req == "inverted" and not spec.phase_inverted:
                results.append(RuleResultItem(
                    rule_id="phase_inversion_mismatch",
                    passed=False,
                    penalty=0.8,
                    message=(
                        f"Rejected: user requires phase inversion (180°) but "
                        f"'{selected_topology}' is non-inverting."
                    ),
                ))
            elif phase_req == "non_inverted" and spec.phase_inverted:
                results.append(RuleResultItem(
                    rule_id="phase_inversion_mismatch",
                    passed=False,
                    penalty=0.8,
                    message=(
                        f"Rejected: user requires non-inverted output but "
                        f"'{selected_topology}' inverts the signal."
                    ),
                ))
            else:
                results.append(RuleResultItem(
                    rule_id="phase_inversion_mismatch",
                    passed=True,
                    penalty=0.0,
                    message="Phase requirement satisfied.",
                ))

        # ── Rule 6: Differential topology requires differential source ─────
        if _is_differential(selected_topology) and not _has_differential_source(selector_input.user_spec):
            results.append(RuleResultItem(
                rule_id="differential_requires_differential_source",
                passed=True,
                penalty=0.15,
                message=(
                    "Penalty: opamp_differential was selected but only a single-ended "
                    "source was specified; consider non_inverting or inverting."
                ),
            ))
        else:
            results.append(RuleResultItem(
                rule_id="differential_requires_differential_source",
                passed=True,
                penalty=0.0,
                message="Rule passed.",
            ))

        penalty_score = min(1.0, sum(item.penalty for item in results))
        all_passed = all(item.passed for item in results)

        return RuleEvaluationResult(
            passed=all_passed,
            penalty_score=penalty_score,
            results=results,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_normalized_extras(user_spec: Dict[str, Any]) -> set:
    requirements = user_spec.get("extra_requirements")
    if not isinstance(requirements, list):
        return set()
    return {str(item).strip().lower() for item in requirements}


def _requires_high_input_impedance(user_spec: Dict[str, Any]) -> bool:
    return "high_input_impedance" in _get_normalized_extras(user_spec)


def _requires_rf_or_highfreq(user_spec: Dict[str, Any]) -> bool:
    extras = _get_normalized_extras(user_spec)
    if extras & {"rf", "high_frequency", "wideband", "rf_amplifier"}:
        return True
    freq = _safe_float(user_spec.get("frequency"))
    return freq is not None and freq >= 100_000  # ≥ 100 kHz


def _requires_buffer(user_spec: Dict[str, Any]) -> bool:
    extras = _get_normalized_extras(user_spec)
    return bool(extras & {"buffer", "impedance_matching", "low_output_impedance", "emitter_follower"})


def _required_phase(user_spec: Dict[str, Any]) -> str | None:
    """Return 'inverted', 'non_inverted', or None if not specified."""
    extras = _get_normalized_extras(user_spec)
    if "phase_inversion" in extras or "inverted" in extras:
        return "inverted"
    if "non_inverted" in extras or "no_phase_inversion" in extras:
        return "non_inverted"
    return None


def _has_differential_source(user_spec: Dict[str, Any]) -> bool:
    extras = _get_normalized_extras(user_spec)
    return bool(extras & {"differential_source", "differential_input", "two_inputs"})


def _is_common_collector(topology: str) -> bool:
    return str(topology).strip().lower() in {"common_collector", "cc", "emitter_follower"}


def _is_common_emitter(topology: str) -> bool:
    return str(topology).strip().lower() in {"common_emitter", "ce"}


def _is_common_base(topology: str) -> bool:
    return str(topology).strip().lower() in {"common_base", "cb"}


def _is_non_inverting(topology: str) -> bool:
    return str(topology).strip().lower() in {"opamp_non_inverting", "non_inverting", "non_inv"}


def _is_differential(topology: str) -> bool:
    return str(topology).strip().lower() in {"opamp_differential", "differential", "diff"}
