"""Unit tests for opamp_ir_wiring_repair — covers Inverting, Non-Inverting, Differential."""

import pytest

from app.application.ai.opamp_ir_wiring_repair import (
    _pin_map,
    infer_opamp_family,
    opamp_inverting_wiring_ok,
    opamp_non_inverting_wiring_ok,
    opamp_differential_wiring_ok,
    repair_opamp_ir_wiring,
)


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _calc():
    return {
        "gain_dB": 20.0,
        "bandwidth_Hz": 10000.0,
        "input_impedance_ohm": 10000.0,
        "output_impedance_ohm": 0.1,
        "IC_mA": 0.0,
        "VCE_V": 0.0,
    }


def _base_arch(topo: str) -> dict:
    return {
        "topology_type": "Single-stage",
        "stage_count": 1,
        "stages": [{"id": "S1", "topology": topo, "active_device_ref": "U1", "coupling_to_next": None}],
    }


def _signal_flow(inp: str = "IN_SIG") -> dict:
    return {"input_node": inp, "output_node": "OUT_SIG", "main_chain": ["S1"], "stage_links": []}


# ── Inverting payloads ────────────────────────────────────────────────────


def _inverting_correct() -> dict:
    """LLM correctly wired inverting amp."""
    return {
        "is_valid_request": True,
        "analysis": {"circuit_name": "Inv amp", "topology_classification": "opamp_inverting",
                     "design_summary": "s", "design_explanation": "e", "math_basis": "m",
                     "expected_bom": [], "calculations_table": [], "calculated_values": _calc()},
        "architecture": _base_arch("opamp_inverting"),
        "power_and_coupling": {"power_rail": "+12V", "output_strategy": "SE", "interstage_coupling": ""},
        "signal_flow": _signal_flow(),
        "components": [
            {"ref": "U1", "type": "opamp_ic", "value": "LM358", "model": "LM358", "role": "unknown_passive", "topology_stage": 0},
            {"ref": "RIN", "type": "resistor", "value": "10k", "model": "Generic", "role": "feedback", "topology_stage": 0},
            {"ref": "RF", "type": "resistor", "value": "100k", "model": "Generic", "role": "feedback", "topology_stage": 0},
            {"ref": "VCC", "type": "power_supply", "value": "12V", "model": "DC", "role": "supply", "topology_stage": 0},
            {"ref": "GND", "type": "ground", "value": "0V", "model": "GND", "role": "ground", "topology_stage": 0},
        ],
        "nets": [
            {"net_name": "VCC",       "nodes": ["VCC:1"]},
            {"net_name": "0",         "nodes": ["GND:1", "U1:+"]},
            {"net_name": "IN_SIG",    "nodes": ["RIN:1"]},
            {"net_name": "U1_INV_IN", "nodes": ["RIN:2", "RF:2", "U1:-"]},
            {"net_name": "OUT_SIG",   "nodes": ["RF:1", "U1:OUT"]},
        ],
        "probe_nodes": ["IN_SIG", "OUT_SIG", "VCC", "0"],
    }


def _inverting_miswired() -> dict:
    """LLM put U1:+ on IN_SIG and U1:- on GND (swapped inputs)."""
    p = _inverting_correct()
    p["nets"] = [
        {"net_name": "VCC",       "nodes": ["VCC:1"]},
        {"net_name": "0",         "nodes": ["GND:1", "U1:-"]},   # WRONG: minus to GND
        {"net_name": "IN_SIG",    "nodes": ["RIN:1", "U1:+"]},   # WRONG: plus to IN_SIG
        {"net_name": "U1_INV_IN", "nodes": ["RIN:2", "RF:2"]},
        {"net_name": "OUT_SIG",   "nodes": ["RF:1", "U1:OUT"]},
    ]
    return p


# ── Non-Inverting payloads ─────────────────────────────────────────────────


def _non_inverting_correct() -> dict:
    return {
        "is_valid_request": True,
        "analysis": {"circuit_name": "NonInv", "topology_classification": "opamp_non_inverting",
                     "design_summary": "s", "design_explanation": "e", "math_basis": "m",
                     "expected_bom": [], "calculations_table": [], "calculated_values": _calc()},
        "architecture": _base_arch("opamp_non_inverting"),
        "power_and_coupling": {"power_rail": "+12V", "output_strategy": "SE", "interstage_coupling": ""},
        "signal_flow": _signal_flow(),
        "components": [
            {"ref": "U1", "type": "opamp_ic", "value": "LM358", "model": "LM358", "role": "unknown_passive", "topology_stage": 0},
            {"ref": "RG", "type": "resistor", "value": "10k", "model": "Generic", "role": "feedback", "topology_stage": 0},
            {"ref": "RF", "type": "resistor", "value": "90k", "model": "Generic", "role": "feedback", "topology_stage": 0},
            {"ref": "VCC", "type": "power_supply", "value": "12V", "model": "DC", "role": "supply", "topology_stage": 0},
            {"ref": "GND", "type": "ground", "value": "0V", "model": "GND", "role": "ground", "topology_stage": 0},
        ],
        "nets": [
            {"net_name": "VCC",       "nodes": ["VCC:1"]},
            {"net_name": "0",         "nodes": ["GND:1", "RG:1"]},
            {"net_name": "IN_SIG",    "nodes": ["U1:+"]},
            {"net_name": "U1_INV_IN", "nodes": ["RG:2", "RF:2", "U1:-"]},
            {"net_name": "OUT_SIG",   "nodes": ["RF:1", "U1:OUT"]},
        ],
        "probe_nodes": ["IN_SIG", "OUT_SIG", "VCC", "0"],
    }


def _non_inverting_miswired() -> dict:
    """LLM grounded U1:+ and connected signal to U1:- (inverting style)."""
    p = _non_inverting_correct()
    p["nets"] = [
        {"net_name": "VCC",       "nodes": ["VCC:1"]},
        {"net_name": "0",         "nodes": ["GND:1", "RG:1", "U1:+"]},   # WRONG: U1:+ grounded
        {"net_name": "IN_SIG",    "nodes": ["U1:-"]},                     # WRONG: signal to U1:-
        {"net_name": "U1_INV_IN", "nodes": ["RG:2", "RF:2"]},
        {"net_name": "OUT_SIG",   "nodes": ["RF:1", "U1:OUT"]},
    ]
    return p


# ── Differential payloads ──────────────────────────────────────────────────


def _differential_correct() -> dict:
    return {
        "is_valid_request": True,
        "analysis": {"circuit_name": "Diff amp", "topology_classification": "opamp_differential",
                     "design_summary": "s", "design_explanation": "e", "math_basis": "m",
                     "expected_bom": [], "calculations_table": [], "calculated_values": _calc()},
        "architecture": _base_arch("opamp_differential"),
        "power_and_coupling": {"power_rail": "+12V", "output_strategy": "SE", "interstage_coupling": ""},
        "signal_flow": _signal_flow("IN_PLUS_SIG"),
        "components": [
            {"ref": "U1", "type": "opamp_ic", "value": "LM358", "model": "LM358", "role": "unknown_passive", "topology_stage": 0},
            {"ref": "R1", "type": "resistor", "value": "10k", "model": "Generic", "role": "feedback", "topology_stage": 0},
            {"ref": "R2", "type": "resistor", "value": "100k", "model": "Generic", "role": "feedback", "topology_stage": 0},
            {"ref": "R3", "type": "resistor", "value": "10k", "model": "Generic", "role": "feedback", "topology_stage": 0},
            {"ref": "R4", "type": "resistor", "value": "100k", "model": "Generic", "role": "feedback", "topology_stage": 0},
            {"ref": "VCC", "type": "power_supply", "value": "12V", "model": "DC", "role": "supply", "topology_stage": 0},
            {"ref": "GND", "type": "ground", "value": "0V", "model": "GND", "role": "ground", "topology_stage": 0},
        ],
        "nets": [
            {"net_name": "VCC",           "nodes": ["VCC:1"]},
            {"net_name": "0",             "nodes": ["GND:1", "R4:2"]},
            {"net_name": "IN_MINUS_SIG",  "nodes": ["R1:1"]},
            {"net_name": "IN_PLUS_SIG",   "nodes": ["R3:1"]},
            {"net_name": "U1_INV_IN",     "nodes": ["R1:2", "R2:1", "U1:-"]},
            {"net_name": "U1_NON_INV_IN", "nodes": ["R3:2", "R4:1", "U1:+"]},
            {"net_name": "OUT_SIG",       "nodes": ["R2:2", "U1:OUT"]},
        ],
        "probe_nodes": ["IN_PLUS_SIG", "IN_MINUS_SIG", "OUT_SIG", "VCC", "0"],
    }


def _differential_unmatched_values() -> dict:
    """R1 != R3 and R2 != R4 — CMRR will be bad."""
    p = _differential_correct()
    for comp in p["components"]:
        if comp["ref"] == "R3":
            comp["value"] = "15k"   # WRONG: should match R1=10k
        if comp["ref"] == "R4":
            comp["value"] = "80k"   # WRONG: should match R2=100k
    return p


def _differential_miswired() -> dict:
    """R2 feedback goes to INV_IN instead of U1:OUT."""
    p = _differential_correct()
    p["nets"] = [
        {"net_name": "VCC",           "nodes": ["VCC:1"]},
        {"net_name": "0",             "nodes": ["GND:1", "R4:2"]},
        {"net_name": "IN_MINUS_SIG",  "nodes": ["R1:1"]},
        {"net_name": "IN_PLUS_SIG",   "nodes": ["R3:1"]},
        {"net_name": "U1_INV_IN",     "nodes": ["R1:2", "R2:1", "R2:2", "U1:-"]},  # WRONG: R2:2 should go to OUT
        {"net_name": "U1_NON_INV_IN", "nodes": ["R3:2", "R4:1", "U1:+"]},
        {"net_name": "OUT_SIG",       "nodes": ["U1:OUT"]},
    ]
    return p


# ---------------------------------------------------------------------------
# Tests: family inference
# ---------------------------------------------------------------------------


def test_infer_inverting_from_topology_field():
    p = {"architecture": {"stages": [{"topology": "opamp_inverting"}]}, "components": []}
    assert infer_opamp_family(p) == "opamp_inverting"


def test_infer_non_inverting_from_requirements():
    assert infer_opamp_family({
        "architecture": {"stages": [{"topology": ""}]},
        "components": [{"ref": "U1", "type": "opamp_ic", "value": "LM358"}],
    }, requirements="khuếch đại không đảo") == "opamp_non_inverting"


def test_infer_differential_from_requirements():
    assert infer_opamp_family({
        "architecture": {"stages": [{"topology": ""}]},
        "components": [{"ref": "U1", "type": "opamp_ic", "value": "LM741"}],
    }, requirements="thiết kế mạch khuếch đại vi sai") == "opamp_differential"


def test_no_opamp_device_returns_none():
    assert infer_opamp_family({"architecture": {"stages": []}, "components": []}) is None


# ---------------------------------------------------------------------------
# Tests: wiring validation (ok path)
# ---------------------------------------------------------------------------


def test_inverting_correct_wiring_passes():
    assert opamp_inverting_wiring_ok(_inverting_correct()) is True


def test_non_inverting_correct_wiring_passes():
    assert opamp_non_inverting_wiring_ok(_non_inverting_correct()) is True


def test_differential_correct_wiring_passes():
    assert opamp_differential_wiring_ok(_differential_correct()) is True


# ---------------------------------------------------------------------------
# Tests: miswired detection
# ---------------------------------------------------------------------------


def test_inverting_miswired_detected():
    assert opamp_inverting_wiring_ok(_inverting_miswired()) is False


def test_non_inverting_miswired_detected():
    assert opamp_non_inverting_wiring_ok(_non_inverting_miswired()) is False


def test_differential_miswired_detected():
    assert opamp_differential_wiring_ok(_differential_miswired()) is False


# ---------------------------------------------------------------------------
# Tests: repair (main behaviour)
# ---------------------------------------------------------------------------


def test_inverting_miswired_repaired():
    payload = _inverting_miswired()
    assert opamp_inverting_wiring_ok(payload) is False

    repaired = repair_opamp_ir_wiring(payload)
    assert opamp_inverting_wiring_ok(repaired) is True

    pins = _pin_map(repaired["nets"])
    # After repair: U1:+ must be on GND net
    assert pins.get("U1:+") in {"0", "GND", "GROUND"}
    # RF:1 must share net with U1:OUT
    assert pins.get("RF:1") == pins.get("U1:OUT")
    # RF:2 must share net with U1:-
    assert pins.get("RF:2") == pins.get("U1:-")


def test_non_inverting_miswired_repaired():
    payload = _non_inverting_miswired()
    assert opamp_non_inverting_wiring_ok(payload) is False

    repaired = repair_opamp_ir_wiring(payload)
    assert opamp_non_inverting_wiring_ok(repaired) is True

    pins = _pin_map(repaired["nets"])
    # U1:+ must NOT be on GND
    assert pins.get("U1:+") not in {"0", "GND", "GROUND"}
    # RG:1 must be on GND
    assert pins.get("RG:1") in {"0", "GND", "GROUND"}


def test_differential_miswired_repaired():
    payload = _differential_miswired()
    assert opamp_differential_wiring_ok(payload) is False

    repaired = repair_opamp_ir_wiring(payload)
    assert opamp_differential_wiring_ok(repaired) is True

    pins = _pin_map(repaired["nets"])
    assert pins.get("R2:2") == pins.get("U1:OUT")


def test_differential_unmatched_values_equalised():
    payload = _differential_unmatched_values()
    repaired = repair_opamp_ir_wiring(payload)

    comps = {c["ref"]: c["value"] for c in repaired["components"]}
    # R1 = R3 and R2 = R4 after repair
    assert comps["R1"] == comps["R3"]
    assert comps["R2"] == comps["R4"]


def test_correct_wiring_not_touched():
    """A correctly wired payload must be returned unchanged (no deep-copy churn)."""
    payload = _inverting_correct()
    result = repair_opamp_ir_wiring(payload)
    assert result is payload   # same object, not a copy


def test_non_opamp_payload_skipped():
    bjt_payload = {
        "architecture": {"stages": [{"topology": "common_emitter"}]},
        "components": [{"ref": "Q1", "type": "bjt_npn", "value": "2N2222"}],
    }
    result = repair_opamp_ir_wiring(bjt_payload)
    assert result is bjt_payload
