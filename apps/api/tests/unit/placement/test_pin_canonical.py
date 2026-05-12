from app.infrastructure.exporters.placement.agr_templates import GRID_MM
from app.infrastructure.exporters.placement.pin_resolver import (
    canonical_pin_name,
    pin_offset_for_instance,
)


def test_opamp_numbered_pins_match_library_keys() -> None:
    assert canonical_pin_name("opamp", "1") == "OUT"
    assert canonical_pin_name("opamp_ic", "2") == "+"
    assert canonical_pin_name("opamp", "3") == "-"
    assert canonical_pin_name("opamp", "4") == "VS+"
    assert canonical_pin_name("opamp", "5") == "VS-"


def test_power_pin_aliases() -> None:
    assert canonical_pin_name("opamp", "V+") == "VS+"
    assert canonical_pin_name("opamp_ic", "V-") == "VS-"


def test_pin_offset_for_numbered_opamp_matches_named() -> None:
    G = GRID_MM
    o_out = pin_offset_for_instance("opamp", "OUT", 0)
    o_1 = pin_offset_for_instance("opamp", "1", 0)
    assert o_out == o_1 == (2.0 * G, 0.0)
    assert pin_offset_for_instance("opamp", "+", 0) == pin_offset_for_instance("opamp", "2", 0)
