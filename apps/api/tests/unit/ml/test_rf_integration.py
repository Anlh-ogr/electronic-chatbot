from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List

from app.domains.circuits.ai_core.metadata_repo import MetadataRepository
from app.domains.circuits.ai_core.spec_parser import UserSpec
from app.domains.circuits.ai_core.topology_planner import TopologyPlanner


SAMPLE_SPECS: List[Dict[str, Any]] = [
    {"name": "bjt_ce", "circuit_type": "common_emitter", "gain": 35.0, "frequency": 1.0e4, "vcc": 12.0},
    {"name": "bjt_cb", "circuit_type": "common_base", "gain": 20.0, "frequency": 2.0e5, "vcc": 9.0},
    {"name": "bjt_cc", "circuit_type": "common_collector", "gain": 1.0, "frequency": 5.0e4, "vcc": 5.0, "output_buffer": True},
    {"name": "mosfet_cs", "circuit_type": "common_source", "gain": 25.0, "frequency": 1.5e5, "vcc": 12.0},
    {"name": "mosfet_cg", "circuit_type": "common_gate", "gain": 12.0, "frequency": 8.0e6, "vcc": 9.0},
    {"name": "opamp_non_inverting", "circuit_type": "non_inverting", "gain": 15.0, "frequency": 5.0e4, "vcc": 12.0, "device_preference": "opamp"},
    {"name": "opamp_differential", "circuit_type": "differential", "gain": 10.0, "frequency": 2.0e4, "vcc": 12.0, "high_cmr": True, "input_mode": "differential", "input_channels": 2},
    {"name": "class_ab", "circuit_type": "class_ab", "gain": 6.0, "frequency": 2.0e4, "vcc": 24.0, "power_output": True},
    {"name": "darlington_pair", "circuit_type": "darlington", "gain": 40.0, "frequency": 1.0e5, "vcc": 18.0},
    {
        "name": "multi_stage_2",
        "circuit_type": "multi_stage",
        "gain": 150.0,
        "frequency": 5.0e4,
        "vcc": 12.0,
        "requested_stage_blocks": ["ce_block", "cc_block"],
    },
]


def _build_spec(config: Dict[str, Any]) -> UserSpec:
    base = UserSpec(
        circuit_type="common_emitter",
        gain=10.0,
        vcc=12.0,
        frequency=1.0e4,
        input_channels=1,
        high_cmr=False,
        input_mode="single_ended",
        output_buffer=False,
        power_output=False,
        supply_mode="auto",
        coupling_preference="auto",
        device_preference="auto",
        requested_stage_blocks=[],
        extra_requirements=[],
        functional_features=[],
        topology_candidates=[],
        keyword_hits=[],
        confidence=1.0,
        source="smoke_test",
        raw_text="rf integration smoke test",
    )

    spec = replace(
        base,
        circuit_type=config.get("circuit_type", base.circuit_type),
        gain=config.get("gain", base.gain),
        vcc=config.get("vcc", base.vcc),
        frequency=config.get("frequency", base.frequency),
        input_channels=config.get("input_channels", base.input_channels),
        high_cmr=config.get("high_cmr", base.high_cmr),
        input_mode=config.get("input_mode", base.input_mode),
        output_buffer=config.get("output_buffer", base.output_buffer),
        power_output=config.get("power_output", base.power_output),
        supply_mode=config.get("supply_mode", base.supply_mode),
        coupling_preference=config.get("coupling_preference", base.coupling_preference),
        device_preference=config.get("device_preference", base.device_preference),
        requested_stage_blocks=config.get("requested_stage_blocks", base.requested_stage_blocks),
        extra_requirements=config.get("extra_requirements", base.extra_requirements),
        topology_candidates=[config.get("circuit_type", base.circuit_type)],
    )
    return spec


def test_rf_integration_smoke() -> None:
    repo = MetadataRepository()
    planner = TopologyPlanner()

    assert planner._ml_selector.is_available, "RF selector is unavailable (quality gate failed or model missing)"

    failures: List[str] = []

    for sample in SAMPLE_SPECS:
        sample_name = str(sample["name"])
        spec = _build_spec(sample)
        plan = planner.plan(spec, repo)
        ml_context = planner._ml_selector.predict_context(spec)

        if plan.matched_metadata is None:
            failures.append(f"{sample_name}: no matched template")
            print(f"[FAIL] {sample_name} | no matched template")
            continue

        ml_raw_score = planner._ml_selector.score_candidate(plan.matched_metadata, ml_context)
        passed = ml_raw_score > 0.0

        if passed:
            print(f"[PASS] {sample_name} | template={plan.matched_template_id} | ml_raw={ml_raw_score:.6f}")
        else:
            print(f"[FAIL] {sample_name} | template={plan.matched_template_id} | ml_raw={ml_raw_score:.6f}")
            failures.append(f"{sample_name}: ml_raw_score={ml_raw_score:.6f}")

    assert not failures, "RF integration smoke failures: " + "; ".join(failures)
