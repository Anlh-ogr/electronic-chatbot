"""Unit tests for ConnectivityValidator.

Covers all 9 requirements without touching the live exporter pipeline.
All circuits are synthetic — no IO, no API calls.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.infrastructure.exporters.connectivity_validator import (
    ConnectivityReport,
    ConnectivityValidator,
    WireSegment,
    run_connectivity_validation,
)

G = 2.54  # GRID_MM


# --------------------------------------------------------------------------- #
#  Minimal fake Circuit helpers                                                #
# --------------------------------------------------------------------------- #

def _pin(comp_id: str, pin_name: str):
    return SimpleNamespace(component_id=comp_id, pin_name=pin_name)


def _net(name: str, *pins):
    return SimpleNamespace(name=name, connected_pins=list(pins))


def _comp(cid: str, ctype: str = "resistor"):
    return SimpleNamespace(type=SimpleNamespace(value=ctype), id=cid, pins=(1, 2))


def _circuit(components: dict, nets: list):
    return SimpleNamespace(components=components, nets={n.name: n for n in nets})


def _wire(*pts):
    return {"points": list(pts)}


# --------------------------------------------------------------------------- #
#  Req 2+3: pin-to-net logging (smoke test — no crash)                        #
# --------------------------------------------------------------------------- #

def test_log_rotated_pin_debug_no_crash():
    circuit = _circuit(
        {"R1": _comp("R1", "resistor")},
        [_net("VCC", _pin("R1", "1"))],
    )
    placements = {"R1": (150.0, 100.0)}
    rotations = {"R1": 90}
    pin_pos = {("R1", "1"): (150.0, 97.46), ("R1", "2"): (150.0, 102.54)}
    wires = [_wire((150.0, 97.46), (150.0, 100.0))]

    v = ConnectivityValidator(circuit, placements, rotations, pin_pos, wires)
    v.log_rotated_pin_debug()  # must not raise


# --------------------------------------------------------------------------- #
#  Req 4: wire segment decomposition                                           #
# --------------------------------------------------------------------------- #

def test_wire_segments_decomposed_correctly():
    """A 3-point polyline decomposes into 2 segments."""
    circuit = _circuit({"R1": _comp("R1")}, [])
    placements = {"R1": (0.0, 0.0)}
    v = ConnectivityValidator(circuit, placements, {}, {}, [
        _wire((0.0, 0.0), (10.0, 0.0), (10.0, 5.0)),
    ])
    v._build_pin_to_net()
    v._build_point_index()
    v._build_wire_segments()

    assert len(v._wire_segs) == 2
    assert v._wire_segs[0].start == (0.0, 0.0)
    assert v._wire_segs[0].end   == (10.0, 0.0)
    assert v._wire_segs[1].start == (10.0, 0.0)
    assert v._wire_segs[1].end   == (10.0, 5.0)


# --------------------------------------------------------------------------- #
#  Req 5: net connectivity report (happy path)                                 #
# --------------------------------------------------------------------------- #

def test_fully_connected_net_reports_no_missing():
    # R1:2 ── R2:1 on a simple horizontal wire, both declared in net BIAS
    circuit = _circuit(
        {"R1": _comp("R1"), "R2": _comp("R2")},
        [_net("BIAS", _pin("R1", "2"), _pin("R2", "1"))],
    )
    placements  = {"R1": (140.0, 100.0), "R2": (160.0, 100.0)}
    rotations   = {}
    pin_pos = {
        ("R1", "2"): (140.0, 102.54),
        ("R2", "1"): (160.0, 97.46),
    }
    # wire linking R1:2 → R2:1
    wires = [_wire((140.0, 102.54), (160.0, 102.54), (160.0, 97.46))]

    report = ConnectivityValidator(circuit, placements, rotations, pin_pos, wires).validate()

    assert report.missing_pins.get("BIAS", []) == []


# --------------------------------------------------------------------------- #
#  Req 5: missing pin detected                                                  #
# --------------------------------------------------------------------------- #

def test_missing_pin_detected_when_no_wire_reaches_pin():
    circuit = _circuit(
        {"R1": _comp("R1"), "Q1": _comp("Q1", "bjt_npn")},
        [_net("BASE", _pin("R1", "2"), _pin("Q1", "B"))],
    )
    placements = {"R1": (140.0, 100.0), "Q1": (160.0, 100.0)}
    rotations  = {}
    pin_pos = {
        ("R1", "2"): (140.0, 102.54),
        ("Q1", "B"): (154.92, 100.0),
    }
    # Wire only reaches R1:2, never touches Q1:B
    wires = [_wire((140.0, 102.54), (148.0, 102.54))]

    report = ConnectivityValidator(circuit, placements, rotations, pin_pos, wires).validate()

    assert "Q1:B" in report.missing_pins.get("BASE", [])
    assert not report.connectivity_ok


# --------------------------------------------------------------------------- #
#  Req 6: orphan pin detection                                                  #
# --------------------------------------------------------------------------- #

def test_orphan_pin_detected():
    circuit = _circuit(
        {"R1": _comp("R1"), "R2": _comp("R2")},
        [_net("VCC", _pin("R1", "1"), _pin("R2", "1"))],
    )
    placements = {"R1": (150.0, 100.0), "R2": (170.0, 100.0)}
    rotations  = {}
    pin_pos = {
        ("R1", "1"): (150.0, 97.46),
        ("R2", "1"): (170.0, 97.46),
    }
    # Wire touches only R1:1 — R2:1 is orphaned
    wires = [_wire((150.0, 97.46), (155.0, 97.46))]

    report = ConnectivityValidator(circuit, placements, rotations, pin_pos, wires).validate()

    assert "R2:1" in report.orphan_pins


# --------------------------------------------------------------------------- #
#  Req 7: fragmented net detection                                              #
# --------------------------------------------------------------------------- #

def test_fragmented_net_detected():
    """VCC declared on R1:1 and R2:1, but wires form two disconnected islands."""
    circuit = _circuit(
        {"R1": _comp("R1"), "R2": _comp("R2"), "R3": _comp("R3")},
        [_net("VCC", _pin("R1", "1"), _pin("R2", "1"), _pin("R3", "1"))],
    )
    placements = {"R1": (100.0, 90.0), "R2": (130.0, 90.0), "R3": (200.0, 90.0)}
    rotations  = {}
    pin_pos = {
        ("R1", "1"): (100.0, 87.46),
        ("R2", "1"): (130.0, 87.46),
        ("R3", "1"): (200.0, 87.46),
    }
    # Island A: R1:1 ── R2:1    Island B: R3:1 (alone)
    wires = [
        _wire((100.0, 87.46), (130.0, 87.46)),   # connects R1:1 and R2:1
    ]

    report = ConnectivityValidator(circuit, placements, rotations, pin_pos, wires).validate()

    frags = report.fragmented_nets.get("VCC", [])
    # Should have 2 islands (R3 is isolated)
    assert len(frags) >= 2, f"Expected >=2 fragments, got {frags}"


# --------------------------------------------------------------------------- #
#  Req 7: single-island net = no fragmentation                                  #
# --------------------------------------------------------------------------- #

def test_no_fragmentation_for_connected_net():
    circuit = _circuit(
        {"R1": _comp("R1"), "R2": _comp("R2")},
        [_net("VCC", _pin("R1", "1"), _pin("R2", "1"))],
    )
    placements = {"R1": (100.0, 90.0), "R2": (130.0, 90.0)}
    rotations  = {}
    pin_pos = {
        ("R1", "1"): (100.0, 87.46),
        ("R2", "1"): (130.0, 87.46),
    }
    wires = [_wire((100.0, 87.46), (130.0, 87.46))]

    report = ConnectivityValidator(circuit, placements, rotations, pin_pos, wires).validate()

    frags = report.fragmented_nets.get("VCC", [[]])
    assert all(len(f) <= len(frags[0]) for f in frags)
    # Only one fragment
    assert len(frags) == 1


# --------------------------------------------------------------------------- #
#  Req 8: tree text rendered                                                    #
# --------------------------------------------------------------------------- #

def test_tree_text_contains_net_and_pins():
    circuit = _circuit(
        {"R1": _comp("R1"), "Q1": _comp("Q1", "bjt_npn")},
        [_net("BASE_BIAS", _pin("R1", "2"), _pin("Q1", "B"))],
    )
    placements = {"R1": (140.0, 100.0), "Q1": (160.0, 100.0)}
    pin_pos = {
        ("R1", "2"): (140.0, 102.54),
        ("Q1", "B"): (154.92, 100.0),
    }
    wires = [_wire((140.0, 102.54), (154.92, 100.0))]

    report = ConnectivityValidator(circuit, placements, {}, pin_pos, wires).validate()

    assert "BASE_BIAS" in report.tree_text
    assert "R1:2" in report.tree_text
    assert "Q1:B" in report.tree_text


# --------------------------------------------------------------------------- #
#  Req 9: JSON artifact structure                                               #
# --------------------------------------------------------------------------- #

def test_json_artifact_keys():
    circuit = _circuit(
        {"R1": _comp("R1")},
        [_net("VCC", _pin("R1", "1"))],
    )
    report = ConnectivityValidator(circuit, {"R1": (150.0, 100.0)}, {}, {}, []).validate()
    data = json.loads(report.to_json())

    required_keys = {
        "component_positions", "pin_positions", "wire_segments",
        "resolved_nets", "connected_pins", "missing_pins",
        "fragmented_nets", "orphan_pins", "connectivity_ok", "connectivity_tree",
    }
    assert required_keys.issubset(data.keys()), f"Missing keys: {required_keys - data.keys()}"


# --------------------------------------------------------------------------- #
#  Req 10: run_connectivity_validation wrapper never raises                    #
# --------------------------------------------------------------------------- #

def test_run_validation_wrapper_never_raises():
    """Even a totally broken/empty input must return a report without exception."""
    report = run_connectivity_validation(
        _circuit({}, []),
        placements={},
        rotations={},
        pin_positions={},
        wires=[],
        emit_debug_log=False,
    )
    assert isinstance(report, ConnectivityReport)
    assert report.connectivity_ok is True  # empty circuit has nothing to fail


# --------------------------------------------------------------------------- #
#  Wire segment net attribution via pin lookup                                  #
# --------------------------------------------------------------------------- #

def test_wire_segment_carries_correct_net_name():
    circuit = _circuit(
        {"R1": _comp("R1")},
        [_net("VCC", _pin("R1", "1"))],
    )
    pin_pos = {("R1", "1"): (150.0, 97.46)}
    wires = [_wire((150.0, 97.46), (150.0, 90.0))]

    v = ConnectivityValidator(circuit, {"R1": (150.0, 100.0)}, {}, pin_pos, wires)
    v._build_pin_to_net()
    v._build_point_index()
    v._build_wire_segments()

    assert v._wire_segs[0].net_name == "VCC"
