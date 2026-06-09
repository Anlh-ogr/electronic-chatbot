"""Tests for strict PCB placement overlap repair."""

from __future__ import annotations

from app.domains.circuits.entities import Circuit, Component, ComponentType, Net, ParameterValue, PinRef
from app.infrastructure.exporters import pcb_strict_engine as strict_pcb


def _sample_circuit() -> Circuit:
    q1 = Component(
        id="Q1",
        type=ComponentType.BJT_NPN,
        pins=("C", "B", "E"),
        parameters={"model": ParameterValue("2N2222", None)},
    )
    r1 = Component(
        id="R1",
        type=ComponentType.RESISTOR,
        pins=("1", "2"),
        parameters={"resistance": ParameterValue(10000, "ohm")},
    )
    r2 = Component(
        id="R2",
        type=ComponentType.RESISTOR,
        pins=("1", "2"),
        parameters={"resistance": ParameterValue(2200, "ohm")},
    )
    c1 = Component(
        id="C1",
        type=ComponentType.CAPACITOR,
        pins=("1", "2"),
        parameters={"capacitance": ParameterValue(100e-9, "F")},
    )
    gnd = Component(
        id="GND1",
        type=ComponentType.GROUND,
        pins=("G",),
        parameters={},
    )
    nets = {
        "IN": Net(name="IN", connected_pins=(PinRef("R1", "1"),)),
        "B": Net(name="B", connected_pins=(PinRef("R1", "2"), PinRef("Q1", "B"))),
        "OUT": Net(name="OUT", connected_pins=(PinRef("Q1", "C"), PinRef("C1", "1"))),
        "GND": Net(name="GND", connected_pins=(PinRef("Q1", "E"), PinRef("C1", "2"), PinRef("GND1", "G"))),
    }
    return Circuit(
        name="repair-test",
        _components={"Q1": q1, "R1": r1, "R2": r2, "C1": c1, "GND1": gnd},
        _nets=nets,
        _ports={},
        _constraints={},
    )


def test_repair_clears_overlaps_after_finalize_on_90x40_board() -> None:
    circuit = _sample_circuit()
    placements, anchor, _ = strict_pcb.place_strict(circuit, nominal_w=90.0, nominal_h=40.0)
    placements, (bw, bh) = strict_pcb.finalize_board_size(circuit, placements)
    repaired = strict_pcb.repair_placement_overlaps(circuit, placements, anchor, bw, bh)
    assert strict_pcb.count_courtyard_overlaps(circuit, repaired) == 0


def test_place_and_repair_export_path_has_zero_overlaps() -> None:
    circuit = _sample_circuit()
    placements, anchor, _ = strict_pcb.place_strict(circuit)
    placements, (bw, bh) = strict_pcb.finalize_board_size(circuit, placements)
    repaired = strict_pcb.repair_placement_overlaps(circuit, placements, anchor, bw, bh)
    drc = strict_pcb.run_pcb_drc(circuit, repaired, {}, [])
    strict_pcb.raise_if_drc_fails(drc, board_size_mm=(bw, bh), center=anchor or "Q1")
