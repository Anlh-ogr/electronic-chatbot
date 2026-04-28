from app.application.ai.llm_contracts import NLUIntentOutputV1, TopologyCode
from app.domains.validators.dc_bias_validator import ComponentSet, DCBiasValidator


def test_nlu_topology_alias_ci_maps_to_inv() -> None:
    payload = NLUIntentOutputV1.model_validate(
        {
            "sv": "nlu.v1",
            "it": "CRT",
            "tp": "CI",
        }
    )
    assert payload.tp == TopologyCode.INV


def test_nlu_topology_aliases_map_to_canonical_codes() -> None:
    non = NLUIntentOutputV1.model_validate(
        {
            "sv": "nlu.v1",
            "it": "CRT",
            "tp": "NI",
        }
    )
    dif = NLUIntentOutputV1.model_validate(
        {
            "sv": "nlu.v1",
            "it": "CRT",
            "tp": "DIFF",
        }
    )
    assert non.tp == TopologyCode.NON
    assert dif.tp == TopologyCode.DIF


def test_physics_gate_opamp_topology_avoids_bjt_vce_checks() -> None:
    validator = DCBiasValidator()
    component_set = ComponentSet(
        R1=1.0,
        R2=1.0,
        RC=20_000.0,
        RE=1_000.0,
        VCC=15.0,
        beta=100.0,
        topology="ci",
    )

    result = validator.validate_by_topology(component_set, gain_target=20.0)
    all_messages = " ".join(result.errors + result.suggestions)

    assert "VCE" not in all_messages
    assert "Q-point" not in all_messages


def test_physics_gate_differential_uses_opamp_swing_path() -> None:
    validator = DCBiasValidator()
    component_set = ComponentSet(
        R1=1.0,
        R2=1.0,
        RC=10_000.0,
        RE=10_000.0,
        VCC=15.0,
        beta=100.0,
        topology="differential",
    )

    result = validator.validate_by_topology(component_set, gain_target=20.0)
    all_messages = " ".join(result.errors + result.suggestions)

    assert result.passed is True
    assert "VCE" not in all_messages
    assert "Q-point" not in all_messages
