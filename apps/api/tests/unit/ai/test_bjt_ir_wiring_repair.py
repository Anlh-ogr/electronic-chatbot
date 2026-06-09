from app.application.ai.bjt_ir_wiring_repair import (
    _pin_map,
    common_base_wiring_ok,
    infer_bjt_family,
    repair_bjt_ir_wiring,
)
from app.application.ai.circuit_ir_schema import CircuitIR


def _cb_calc() -> dict:
    return {
        "gain_dB": 18.0,
        "bandwidth_Hz": 100000.0,
        "input_impedance_ohm": 26.0,
        "output_impedance_ohm": 200.0,
        "IC_mA": 1.0,
        "VCE_V": 6.0,
        "VBE_V": 0.7,
    }


def _miswired_ce_as_cb_payload() -> dict:
    """LLM often declares common_base but wires CIN to the base (CE style)."""
    return {
        "is_valid_request": True,
        "analysis": {
            "circuit_name": "BJT CB amp",
            "topology_classification": "common_base",
            "design_explanation": "CB stage",
            "math_basis": "Av = RC/re",
            "design_summary": "summary",
            "expected_bom": ["Q1", "RB1", "RB2", "RC", "RE", "CIN", "COUT"],
            "calculations_table": [],
            "calculated_values": _cb_calc(),
        },
        "architecture": {
            "topology_type": "Single-stage",
            "stage_count": 1,
            "stages": [
                {
                    "id": "S1",
                    "topology": "common_base",
                    "active_device_ref": "Q1",
                    "coupling_to_next": None,
                }
            ],
        },
        "power_and_coupling": {
            "power_rail": "Single +12V",
            "output_strategy": "Single-ended",
            "interstage_coupling": "RC Coupling",
        },
        "signal_flow": {
            "input_node": "IN_SIG",
            "output_node": "OUT_SIG",
            "main_chain": ["S1"],
            "stage_links": [],
        },
        "components": [
            {"ref": "Q1", "type": "bjt_npn", "value": "2N2222", "model": "2N2222", "role": "stage_bridge", "topology_stage": 0},
            {"ref": "RB1", "type": "resistor", "value": "47k", "model": "Generic", "role": "bias_top", "topology_stage": 0},
            {"ref": "RB2", "type": "resistor", "value": "10k", "model": "Generic", "role": "bias_bottom", "topology_stage": 0},
            {"ref": "RC", "type": "resistor", "value": "200", "model": "Generic", "role": "load", "topology_stage": 0},
            {"ref": "RE", "type": "resistor", "value": "1.2k", "model": "Generic", "role": "degeneration", "topology_stage": 0},
            {"ref": "CIN", "type": "capacitor", "value": "10uF", "model": "Generic", "role": "coupling_in", "topology_stage": 0},
            {"ref": "COUT", "type": "capacitor", "value": "10uF", "model": "Generic", "role": "coupling_out", "topology_stage": 0},
            {"ref": "VCC", "type": "power_supply", "value": "12V", "model": "DC", "role": "supply", "topology_stage": 0},
            {"ref": "GND", "type": "ground", "value": "0V", "model": "GND", "role": "ground", "topology_stage": 0},
        ],
        "nets": [
            {"net_name": "IN_SIG", "nodes": ["CIN:1"]},
            {"net_name": "BASE_Q1", "nodes": ["CIN:2", "Q1:B", "RB1:2", "RB2:1"]},
            {"net_name": "COLLECTOR_Q1", "nodes": ["Q1:C", "RC:2", "COUT:1"]},
            {"net_name": "EMITTER_Q1", "nodes": ["Q1:E", "RE:1"]},
            {"net_name": "0", "nodes": ["GND:1", "RB2:2", "RE:2"]},
            {"net_name": "VCC", "nodes": ["VCC:+", "RB1:1", "RC:1"]},
            {"net_name": "OUT_SIG", "nodes": ["COUT:2"]},
        ],
        "probe_nodes": ["IN_SIG", "OUT_SIG", "VCC", "0"],
    }


def test_infer_cb_from_requirements_text() -> None:
    req = "Thiết kế mạch BJT mắc B chung sử dụng nguồn 12V"
    assert infer_bjt_family({}, req) == "common_base"


def test_miswired_cb_detected_and_repaired() -> None:
    payload = _miswired_ce_as_cb_payload()
    assert common_base_wiring_ok(payload) is False

    repaired = repair_bjt_ir_wiring(payload)
    assert common_base_wiring_ok(repaired) is True

    pins = _pin_map(repaired["nets"])
    assert pins.get("CIN:2") == pins.get("Q1:E")
    assert pins.get("COUT:1") == pins.get("Q1:C")
    assert any(ref.startswith("CB") for ref in (c["ref"] for c in repaired["components"]))

    CircuitIR.model_validate(repaired)


def test_repair_runs_from_requirements_when_topology_field_missing() -> None:
    payload = _miswired_ce_as_cb_payload()
    payload["analysis"]["topology_classification"] = ""
    payload["architecture"]["stages"][0]["topology"] = "unknown"
    req = "Thiết kế mạch khuếch đại BJT mắc B chung VCC 12V gain 8"
    repaired = repair_bjt_ir_wiring(payload, requirements=req)
    assert common_base_wiring_ok(repaired) is True
