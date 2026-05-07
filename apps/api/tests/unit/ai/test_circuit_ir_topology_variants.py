import pytest

from app.application.ai.circuit_ir_schema import CircuitIR


def _calc_values(*, use_bjt: bool) -> dict:
    values = {
        "gain_dB": 20.0,
        "bandwidth_Hz": 100000.0,
        "input_impedance_ohm": 10000.0,
        "output_impedance_ohm": 200.0,
    }
    if use_bjt:
        values["IC_mA"] = 2.0
        values["VCE_V"] = 6.0
    else:
        values["ID_mA"] = 2.0
        values["VDS_V"] = 6.0
    return values


def _base_analysis(topology: str, *, use_bjt: bool) -> dict:
    return {
        "circuit_name": f"Test {topology}",
        "topology_classification": topology,
        "design_explanation": "Mo ta ngan gon.",
        "math_basis": "Av = 10.",
        "design_summary": "Tom tat.",
        "expected_bom": ["R1", "C1"],
        "calculations_table": [],
        "calculated_values": _calc_values(use_bjt=use_bjt),
    }


def _base_power_and_flow() -> tuple[dict, dict]:
    power_and_coupling = {
        "power_rail": "Single +12V",
        "output_strategy": "Single-ended",
        "interstage_coupling": "RC Coupling",
    }
    signal_flow = {
        "input_node": "IN",
        "output_node": "OUT",
        "main_chain": ["S1"],
        "stage_links": [],
    }
    return power_and_coupling, signal_flow


def _build_transistor_ir(topology: str, active_type: str, *, use_bjt: bool) -> dict:
    active_ref = "Q1" if active_type.startswith("bjt") else "M1"
    in_pin = "B" if active_type.startswith("bjt") else "G"
    out_pin = "C" if active_type.startswith("bjt") else "D"
    gnd_pin = "E" if active_type.startswith("bjt") else "S"

    power_and_coupling, signal_flow = _base_power_and_flow()

    payload = {
        "is_valid_request": True,
        "analysis": _base_analysis(topology, use_bjt=use_bjt),
        "architecture": {
            "topology_type": "Single-stage",
            "stage_count": 1,
            "stages": [
                {
                    "id": "S1",
                    "topology": topology,
                    "active_device_ref": active_ref,
                    "coupling_to_next": None,
                }
            ],
        },
        "power_and_coupling": power_and_coupling,
        "signal_flow": signal_flow,
        "components": [
            {
                "ref": "IN",
                "type": "connector",
                "value": "IN",
                "model": "Generic",
                "role": "coupling_in",
                "topology_stage": 0,
            },
            {
                "ref": "OUT",
                "type": "connector",
                "value": "OUT",
                "model": "Generic",
                "role": "coupling_out",
                "topology_stage": 0,
            },
            {
                "ref": "VCC",
                "type": "power_supply",
                "value": "12V",
                "model": "DC",
                "role": "supply",
                "topology_stage": 0,
            },
            {
                "ref": "GND",
                "type": "ground",
                "value": "0V",
                "model": "GND",
                "role": "ground",
                "topology_stage": 0,
            },
            {
                "ref": active_ref,
                "type": active_type,
                "value": "Generic",
                "model": "Generic",
                "role": "stage_bridge",
                "topology_stage": 0,
            },
            {
                "ref": "RL",
                "type": "resistor",
                "value": "10k",
                "model": "Generic",
                "role": "load",
                "topology_stage": 0,
            },
        ],
        "nets": [
            {"net_name": "IN", "nodes": [f"IN:1", f"{active_ref}:{in_pin}"]},
            {"net_name": "OUT", "nodes": [f"OUT:1", f"{active_ref}:{out_pin}", "RL:1"]},
            {"net_name": "VCC", "nodes": ["VCC:1", "RL:2"]},
            {"net_name": "0", "nodes": ["GND:1", f"{active_ref}:{gnd_pin}"]},
        ],
        "probe_nodes": ["IN", "OUT", "VCC", "0"],
    }
    return payload


def _build_opamp_ir(topology: str) -> dict:
    power_and_coupling, signal_flow = _base_power_and_flow()
    signal_flow = dict(signal_flow)
    signal_flow["main_chain"] = ["S1"]

    components = [
        {
            "ref": "IN",
            "type": "connector",
            "value": "IN",
            "model": "Generic",
            "role": "coupling_in",
            "topology_stage": 0,
        },
        {
            "ref": "OUT",
            "type": "connector",
            "value": "OUT",
            "model": "Generic",
            "role": "coupling_out",
            "topology_stage": 0,
        },
        {
            "ref": "VCC",
            "type": "power_supply",
            "value": "12V",
            "model": "DC",
            "role": "supply",
            "topology_stage": 0,
        },
        {
            "ref": "GND",
            "type": "ground",
            "value": "0V",
            "model": "GND",
            "role": "ground",
            "topology_stage": 0,
        },
        {
            "ref": "U1",
            "type": "opamp_ic",
            "value": "Generic",
            "model": "Generic",
            "role": "stage_bridge",
            "topology_stage": 0,
        },
        {
            "ref": "R1",
            "type": "resistor",
            "value": "10k",
            "model": "Generic",
            "role": "feedback",
            "topology_stage": 0,
        },
    ]

    if topology == "opamp_inverting":
        nets = [
            {"net_name": "IN", "nodes": ["IN:1", "U1:-", "R1:1"]},
            {"net_name": "OUT", "nodes": ["OUT:1", "U1:OUT", "R1:2"]},
            {"net_name": "VCC", "nodes": ["VCC:1", "U1:VS+"]},
            {"net_name": "0", "nodes": ["GND:1", "U1:VS-", "U1:+"]},
        ]
    elif topology == "opamp_non_inverting":
        nets = [
            {"net_name": "IN", "nodes": ["IN:1", "U1:+"]},
            {"net_name": "FB", "nodes": ["U1:-", "R1:1"]},
            {"net_name": "OUT", "nodes": ["OUT:1", "U1:OUT", "R1:2"]},
            {"net_name": "VCC", "nodes": ["VCC:1", "U1:VS+"]},
            {"net_name": "0", "nodes": ["GND:1", "U1:VS-"]},
        ]
    else:
        components.append(
            {
                "ref": "IN2",
                "type": "connector",
                "value": "IN2",
                "model": "Generic",
                "role": "coupling_in",
                "topology_stage": 0,
            }
        )
        nets = [
            {"net_name": "IN", "nodes": ["IN:1", "U1:+"]},
            {"net_name": "IN2", "nodes": ["IN2:1", "U1:-"]},
            {"net_name": "OUT", "nodes": ["OUT:1", "U1:OUT"]},
            {"net_name": "VCC", "nodes": ["VCC:1", "U1:VS+"]},
            {"net_name": "0", "nodes": ["GND:1", "U1:VS-"]},
        ]

    return {
        "is_valid_request": True,
        "analysis": _base_analysis(topology, use_bjt=True),
        "architecture": {
            "topology_type": "Single-stage",
            "stage_count": 1,
            "stages": [
                {
                    "id": "S1",
                    "topology": topology,
                    "active_device_ref": "U1",
                    "coupling_to_next": None,
                }
            ],
        },
        "power_and_coupling": power_and_coupling,
        "signal_flow": signal_flow,
        "components": components,
        "nets": nets,
        "probe_nodes": ["IN", "OUT", "VCC", "0"],
    }


def _build_multistage_ir() -> dict:
    power_and_coupling, signal_flow = _base_power_and_flow()
    signal_flow["main_chain"] = ["S1", "S2"]
    signal_flow["stage_links"] = [["S1", "S2"]]

    return {
        "is_valid_request": True,
        "analysis": _base_analysis("multistage", use_bjt=True),
        "architecture": {
            "topology_type": "Multi-stage",
            "stage_count": 2,
            "stages": [
                {
                    "id": "S1",
                    "topology": "common_emitter",
                    "active_device_ref": "Q1",
                    "coupling_to_next": "rc",
                },
                {
                    "id": "S2",
                    "topology": "common_collector",
                    "active_device_ref": "Q2",
                    "coupling_to_next": None,
                },
            ],
        },
        "power_and_coupling": power_and_coupling,
        "signal_flow": signal_flow,
        "components": [
            {
                "ref": "IN",
                "type": "connector",
                "value": "IN",
                "model": "Generic",
                "role": "coupling_in",
                "topology_stage": 0,
            },
            {
                "ref": "OUT",
                "type": "connector",
                "value": "OUT",
                "model": "Generic",
                "role": "coupling_out",
                "topology_stage": 1,
            },
            {
                "ref": "VCC",
                "type": "power_supply",
                "value": "12V",
                "model": "DC",
                "role": "supply",
                "topology_stage": 0,
            },
            {
                "ref": "GND",
                "type": "ground",
                "value": "0V",
                "model": "GND",
                "role": "ground",
                "topology_stage": 0,
            },
            {
                "ref": "Q1",
                "type": "bjt_npn",
                "value": "Generic",
                "model": "Generic",
                "role": "stage_bridge",
                "topology_stage": 0,
            },
            {
                "ref": "Q2",
                "type": "bjt_npn",
                "value": "Generic",
                "model": "Generic",
                "role": "stage_bridge",
                "topology_stage": 1,
            },
            {
                "ref": "RL1",
                "type": "resistor",
                "value": "10k",
                "model": "Generic",
                "role": "load",
                "topology_stage": 0,
            },
            {
                "ref": "RL2",
                "type": "resistor",
                "value": "10k",
                "model": "Generic",
                "role": "load",
                "topology_stage": 1,
            },
        ],
        "nets": [
            {"net_name": "IN", "nodes": ["IN:1", "Q1:B"]},
            {"net_name": "LINK", "nodes": ["Q1:C", "Q2:B"]},
            {"net_name": "OUT", "nodes": ["OUT:1", "Q2:C", "RL2:1"]},
            {"net_name": "VCC", "nodes": ["VCC:1", "RL1:1", "RL2:2"]},
            {"net_name": "0", "nodes": ["GND:1", "Q1:E", "Q2:E", "RL1:2"]},
        ],
        "probe_nodes": ["IN", "OUT", "VCC", "0"],
    }


TOPOLOGY_CASES = [
    ("common_emitter", "bjt_npn", True),
    ("common_collector", "bjt_npn", True),
    ("common_base", "bjt_npn", True),
    ("common_source", "mosfet_n", False),
    ("common_drain", "mosfet_n", False),
    ("common_gate", "mosfet_n", False),
    ("opamp_inverting", "opamp_ic", True),
    ("opamp_non_inverting", "opamp_ic", True),
    ("opamp_differential", "opamp_ic", True),
    ("class_a", "bjt_npn", True),
    ("class_b", "bjt_npn", True),
    ("class_c", "bjt_npn", True),
    ("class_d", "mosfet_n", False),
    ("class_ab", "bjt_npn", True),
    ("darlington_npn", "bjt_npn", True),
    ("darlington_pnp", "bjt_pnp", True),
]


@pytest.mark.parametrize("topology,active_type,use_bjt", TOPOLOGY_CASES)
def test_circuit_ir_topology_variants(topology: str, active_type: str, use_bjt: bool) -> None:
    if topology.startswith("opamp_"):
        payload = _build_opamp_ir(topology)
    else:
        payload = _build_transistor_ir(topology, active_type, use_bjt=use_bjt)
    CircuitIR.model_validate(payload)


def test_circuit_ir_multistage_variant() -> None:
    payload = _build_multistage_ir()
    CircuitIR.model_validate(payload)
