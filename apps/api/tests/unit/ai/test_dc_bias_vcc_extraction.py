from app.domains.validators.dc_bias_validator import DCBiasValidator


def test_vcc_prefers_explicit_power_supply_over_vin() -> None:
    validator = DCBiasValidator()
    mock_ir = {
        "topology": "inverting",
        "power_supply": {"voltage": "±15V"},
        "architecture": {
            "stages": [
                {"active_device_vcc": 0.1},
            ]
        },
        "components": [
            {
                "type": "VOLTAGE_SOURCE",
                "id": "VIN",
                "parameters": {"voltage": 0.1},
            },
            {
                "type": "POWER_SUPPLY",
                "id": "VCC",
                "parameters": {"voltage": "15V"},
            },
        ],
        "analysis": {
            "design_specs": [
                {"parameter": "input_signal_vin", "value": "100mV"},
                {"parameter": "supply_voltage", "value": "15V"},
            ]
        },
    }

    vcc = validator._extract_vcc(mock_ir)

    assert vcc == 15.0
    assert vcc >= 14.9
    assert vcc != 0.1


def test_vcc_low_values_fall_back_to_safe_default() -> None:
    validator = DCBiasValidator()
    mock_ir = {
        "topology": "common_emitter",
        "architecture": {
            "stages": [
                {"active_device_vcc": 0.1},
            ]
        },
        "components": [
            {
                "type": "VOLTAGE_SOURCE",
                "id": "VIN",
                "parameters": {"voltage": 0.1},
            }
        ],
    }

    vcc = validator._extract_vcc(mock_ir)

    assert vcc == 12.0
    assert vcc > 1.0
