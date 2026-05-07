from types import SimpleNamespace

from app.infrastructure.exporters.placement.role_inferrer import infer_roles


def test_infer_roles_basic():
    components = [
        SimpleNamespace(ref="VCC", type="power_supply", role=None),
        SimpleNamespace(ref="GND", type="ground", role=None),
        SimpleNamespace(ref="Q1", type="bjt_npn", role=None),
        SimpleNamespace(ref="CIN", type="capacitor", role=None),
        SimpleNamespace(ref="COUT", type="capacitor", role=None),
        SimpleNamespace(ref="RC", type="resistor", role=None),
        SimpleNamespace(ref="RE", type="resistor", role=None),
        SimpleNamespace(ref="RF", type="resistor", role=None),
        SimpleNamespace(ref="RB1", type="resistor", role=None),
    ]

    roles = infer_roles(components)

    assert roles["VCC"] == "supply"
    assert roles["GND"] == "ground"
    assert roles["Q1"] == "stage_bridge"
    assert roles["CIN"] == "coupling_in"
    assert roles["COUT"] == "coupling_out"
    assert roles["RC"] == "load"
    assert roles["RE"] == "degeneration"
    assert roles["RF"] == "feedback"
    assert roles["RB1"] == "bias_top"
