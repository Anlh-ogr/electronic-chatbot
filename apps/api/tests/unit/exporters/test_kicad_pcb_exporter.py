from __future__ import annotations

import pytest

from app.application.circuits.dtos import ExportFormat
from app.domains.circuits.entities import Circuit, Component, ComponentType, Net, ParameterValue, PinRef
from app.infrastructure.exporters.kicad_footprint_library import KiCadFootprintLibrary
from app.infrastructure.exporters.kicad_pcb_exporter import KiCadPCBExporter


def _build_circuit(stage_a: str = "1", stage_b: str | None = None) -> Circuit:
    q1 = Component(
        id="Q1",
        type=ComponentType.BJT_NPN,
        pins=("C", "B", "E"),
        parameters={"model": ParameterValue("2N2222", None)},
        stage=stage_a,
    )
    r1 = Component(
        id="R1",
        type=ComponentType.RESISTOR,
        pins=("1", "2"),
        parameters={"resistance": ParameterValue(10000, "ohm")},
        stage=stage_a,
    )
    c1 = Component(
        id="C1",
        type=ComponentType.CAPACITOR_POLARIZED,
        pins=("1", "2"),
        parameters={"capacitance": ParameterValue(1e-6, "F")},
        stage=stage_b or stage_a,
    )
    gnd = Component(
        id="GND1",
        type=ComponentType.GROUND,
        pins=("G",),
        parameters={},
        stage=stage_b or stage_a,
    )

    nets = {
        "VIN": Net(name="VIN", connected_pins=(PinRef("R1", "1"),)),
        "BIAS": Net(name="BIAS", connected_pins=(PinRef("R1", "2"), PinRef("Q1", "B"))),
        "OUT": Net(name="OUT", connected_pins=(PinRef("Q1", "C"), PinRef("C1", "1"))),
        "GND": Net(name="GND", connected_pins=(PinRef("Q1", "E"), PinRef("C1", "2"), PinRef("GND1", "G"))),
    }

    return Circuit(
        name="PCB Export Sample",
        _components={"Q1": q1, "R1": r1, "C1": c1, "GND1": gnd},
        _nets=nets,
        _ports={},
        _constraints={},
    )


@pytest.mark.asyncio
async def test_kicad_pcb_export_includes_board_outline_and_gnd_zone() -> None:
    exporter = KiCadPCBExporter()
    circuit = _build_circuit()

    content = await exporter.export(circuit, ExportFormat.KICAD_PCB)

    assert '(gr_rect (start 0 0) (end 50.0 40.0) (layer "Edge.Cuts")' in content
    assert '(layer "B.Cu")' in content
    assert '(net_name "GND")' in content
    assert 'Capacitor_THT:CP_Radial_D5.0mm_P2.00mm' in content
    assert KiCadFootprintLibrary.get_footprint("capacitor") == "Capacitor_THT:C_Disc_D3.8mm_W2.6mm_P2.50mm"


@pytest.mark.asyncio
async def test_kicad_pcb_export_scales_board_for_two_stage_layout() -> None:
    exporter = KiCadPCBExporter()
    circuit = _build_circuit(stage_a="1", stage_b="2")

    content = await exporter.export(circuit, ExportFormat.KICAD_PCB)

    assert '(gr_rect (start 0 0) (end 90.0 40.0) (layer "Edge.Cuts")' in content
