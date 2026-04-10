from app.domains.circuits.ai_core.spec_parser import NLPSpecParser, UserSpec
from app.domains.circuits.ai_core.topology_planner import TopologyPlan, TopologyPlanner


def _parse(text: str) -> UserSpec:
    return NLPSpecParser().parse(text)


def _assert_candidates_in_order(spec: UserSpec, expected_prefix: list[str]) -> None:
    for family in expected_prefix:
        assert family in spec.topology_candidates, f"Expected candidate '{family}' in {spec.topology_candidates}"

    first = spec.topology_candidates.index(expected_prefix[0])
    second = spec.topology_candidates.index(expected_prefix[1])
    assert first < second, (
        f"Expected '{expected_prefix[0]}' ranked before '{expected_prefix[1]}', "
        f"got {spec.topology_candidates}"
    )


def test_low_distortion_maps_to_class_a_then_class_ab() -> None:
    spec = _parse("khuếch đại âm thanh ít méo")

    _assert_candidates_in_order(spec, ["class_a", "class_ab"])
    assert spec.circuit_type in {"class_a", "class_ab"}
    assert "low_distortion" in spec.extra_requirements


def test_power_request_maps_to_class_ab_then_class_d() -> None:
    spec = _parse("mạch công suất lớn cho loa")

    _assert_candidates_in_order(spec, ["class_ab", "class_d"])
    assert spec.power_output is True
    assert "power_amplification" in spec.extra_requirements


def test_buffer_request_maps_to_cc_then_cd() -> None:
    spec = _parse("buffer tín hiệu đầu ra")

    _assert_candidates_in_order(spec, ["common_collector", "common_drain"])
    assert spec.output_buffer is True


def test_low_noise_request_maps_to_differential_then_instrumentation() -> None:
    spec = _parse("mạch đo lường nhiễu thấp cho cảm biến")

    _assert_candidates_in_order(spec, ["differential", "instrumentation"])
    assert "high_cmrr" in spec.extra_requirements


def test_high_gain_request_maps_to_multi_stage_then_darlington() -> None:
    spec = _parse("gain lớn cho tín hiệu yếu")

    _assert_candidates_in_order(spec, ["multi_stage", "darlington"])
    assert "voltage_gain" in spec.extra_requirements


def test_simple_request_maps_to_ce_then_cs() -> None:
    spec = _parse("mạch khuếch đại đơn giản")

    _assert_candidates_in_order(spec, ["common_emitter", "common_source"])


def test_planner_can_fallback_from_candidate_when_circuit_type_unknown() -> None:
    planner = TopologyPlanner()
    plan = TopologyPlan()
    spec = UserSpec(
        circuit_type="unknown",
        topology_candidates=["class_ab", "class_d"],
        raw_text="amplifier công suất cho loa",
    )

    result = planner._validate_circuit_type(spec, plan)

    assert result is True
    assert spec.circuit_type == "class_ab"
    assert any("functional keyword mapping" in msg for msg in plan.rationale)
