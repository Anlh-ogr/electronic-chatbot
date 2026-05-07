import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure app package imports work when running tests from apps/api
APP_DIR = Path(__file__).resolve().parents[2] / "app"
sys.path.insert(0, str(APP_DIR))

from app.application.circuits.dtos import ExportFormat
from app.domains.circuits.entities import (
    Circuit,
    Component,
    ComponentType,
    Net,
    ParameterValue,
    PinRef,
)
from app.infrastructure.exporters.kicad_sch_exporter import KiCadSchExporter


def _resistor(ref: str) -> Component:
    return Component(
        id=ref,
        type=ComponentType.RESISTOR,
        pins=("1", "2"),
        parameters={"resistance": ParameterValue("1k", "Ohm")},
    )


def _capacitor(ref: str) -> Component:
    return Component(
        id=ref,
        type=ComponentType.CAPACITOR,
        pins=("1", "2"),
        parameters={"capacitance": ParameterValue("1u", "F")},
    )


def _inductor(ref: str) -> Component:
    return Component(
        id=ref,
        type=ComponentType.INDUCTOR,
        pins=("1", "2"),
        parameters={"inductance": ParameterValue("10u", "H")},
    )


def _voltage_source(ref: str = "VCC") -> Component:
    return Component(
        id=ref,
        type=ComponentType.VOLTAGE_SOURCE,
        pins=("1",),
        parameters={"voltage": ParameterValue("12", "V")},
    )


def _ground(ref: str = "GND") -> Component:
    return Component(
        id=ref,
        type=ComponentType.GROUND,
        pins=("1",),
        parameters={},
    )


def _connector(ref: str) -> Component:
    return Component(
        id=ref,
        type=ComponentType.CONNECTOR,
        pins=("1",),
        parameters={},
    )


def _bjt(ref: str, model: str, stage: str | None = None) -> Component:
    return Component(
        id=ref,
        type=ComponentType.BJT_NPN if model == "BC547" else ComponentType.BJT_PNP,
        pins=("B", "C", "E"),
        parameters={"model": ParameterValue(model, None)},
        stage=stage,
    )


def _mosfet(ref: str, model: str, stage: str | None = None) -> Component:
    comp_type = ComponentType.MOSFET_N if model == "IRF540" else ComponentType.MOSFET_P
    return Component(
        id=ref,
        type=comp_type,
        pins=("G", "D", "S"),
        parameters={"model": ParameterValue(model, None)},
        stage=stage,
    )


def _opamp(ref: str, stage: str | None = None) -> Component:
    return Component(
        id=ref,
        type=ComponentType.OPAMP,
        pins=("OUT", "+", "-", "VS+", "VS-"),
        parameters={"model": ParameterValue("LM741", None)},
        stage=stage,
    )


def _circuit(name: str, components: list[Component], nets: list[Net], topology: str) -> Circuit:
    return Circuit(
        name=name,
        _components={comp.id: comp for comp in components},
        _nets={net.name: net for net in nets},
        _ports={},
        _constraints={},
        topology_type=topology,
    )


def _net(name: str, pins: list[tuple[str, str]]) -> Net:
    return Net(
        name=name,
        connected_pins=tuple(PinRef(component_id=cid, pin_name=pin) for cid, pin in pins),
    )


def _build_bjt_topology(topology: str, input_pin: str, output_pin: str) -> Circuit:
    q1 = _bjt("Q1", "BC547")
    r1 = _resistor("R1")
    cin = _capacitor("CIN")
    cout = _capacitor("COUT")
    vcc = _voltage_source()
    gnd = _ground()
    vin = _connector("IN")
    vout = _connector("OUT")

    nets = [
        _net("IN", [("IN", "1"), ("CIN", "1")]),
        _net("IN_SIG", [("CIN", "2"), ("Q1", input_pin)]),
        _net("OUT", [("OUT", "1"), ("COUT", "2")]),
        _net("OUT_SIG", [("COUT", "1"), ("Q1", output_pin), ("R1", "2")]),
        _net("VCC", [("VCC", "1"), ("R1", "1")]),
    ]

    return _circuit(topology, [q1, r1, cin, cout, vcc, vin, vout], nets, topology)


def _build_mosfet_topology(topology: str, input_pin: str, output_pin: str) -> Circuit:
    m1 = _mosfet("M1", "IRF540")
    r1 = _resistor("R1")
    cin = _capacitor("CIN")
    cout = _capacitor("COUT")
    vcc = _voltage_source()
    vin = _connector("IN")
    vout = _connector("OUT")

    nets = [
        _net("IN", [("IN", "1"), ("CIN", "1")]),
        _net("IN_SIG", [("CIN", "2"), ("M1", input_pin)]),
        _net("OUT", [("OUT", "1"), ("COUT", "2")]),
        _net("OUT_SIG", [("COUT", "1"), ("M1", output_pin), ("R1", "2")]),
        _net("VCC", [("VCC", "1"), ("R1", "1")]),
    ]

    return _circuit(topology, [m1, r1, cin, cout, vcc, vin, vout], nets, topology)


def _build_opamp_topology(topology: str) -> Circuit:
    u1 = _opamp("U1")
    rin = _resistor("RIN")
    rf = _resistor("RF")
    vcc = _voltage_source()
    gnd = _ground()
    vin = _connector("IN")
    vout = _connector("OUT")

    nets = [
        _net("IN", [("IN", "1"), ("RIN", "1")]),
        _net("INV", [("RIN", "2"), ("U1", "-") , ("RF", "1")]),
        _net("OUT", [("OUT", "1"), ("U1", "OUT"), ("RF", "2")]),
        _net("VCC", [("VCC", "1"), ("U1", "VS+")]),
        _net("0", [("GND", "1"), ("U1", "VS-")]),
    ]

    return _circuit(topology, [u1, rin, rf, vcc, gnd, vin, vout], nets, topology)


def _build_opamp_diff_topology(topology: str) -> Circuit:
    u1 = _opamp("U1")
    vinp = _connector("INP")
    vinn = _connector("INN")
    vout = _connector("OUT")
    vcc = _voltage_source()
    gnd = _ground()

    nets = [
        _net("INP", [("INP", "1"), ("U1", "+")]),
        _net("INN", [("INN", "1"), ("U1", "-")]),
        _net("OUT", [("OUT", "1"), ("U1", "OUT")]),
        _net("VCC", [("VCC", "1"), ("U1", "VS+")]),
        _net("0", [("GND", "1"), ("U1", "VS-")]),
    ]

    return _circuit(topology, [u1, vinp, vinn, vout, vcc, gnd], nets, topology)


def _build_class_ab(topology: str) -> Circuit:
    qp = _bjt("QP", "BC547")
    qn = _bjt("QN", "BC557")
    vcc = _voltage_source()
    vin = _connector("IN")
    vout = _connector("OUT")

    nets = [
        _net("IN", [("IN", "1"), ("QP", "B")]),
        _net("BIAS", [("QN", "B")]),
        _net("OUT", [("OUT", "1"), ("QP", "E"), ("QN", "E")]),
        _net("VCC", [("VCC", "1"), ("QP", "C")]),
    ]

    return _circuit(topology, [qp, qn, vcc, vin, vout], nets, topology)


def _build_class_d(topology: str) -> Circuit:
    qp = _mosfet("QP", "IRF540")
    qn = _mosfet("QN", "IRF540")
    l1 = _inductor("L1")
    vcc = _voltage_source()
    vin = _connector("IN")
    vout = _connector("OUT")

    nets = [
        _net("IN", [("IN", "1"), ("QP", "G"), ("QN", "G")]),
        _net("SW", [("QP", "D"), ("QN", "D"), ("L1", "1")]),
        _net("OUT", [("OUT", "1"), ("L1", "2")]),
        _net("VCC", [("VCC", "1"), ("QP", "S")]),
    ]

    return _circuit(topology, [qp, qn, l1, vcc, vin, vout], nets, topology)


def _build_darlington(topology: str) -> Circuit:
    q1 = _bjt("Q1", "BC547")
    q2 = _bjt("Q2", "BC547")
    vcc = _voltage_source()
    vin = _connector("IN")
    vout = _connector("OUT")

    nets = [
        _net("IN", [("IN", "1"), ("Q1", "B")]),
        _net("LINK", [("Q1", "C"), ("Q2", "B")]),
        _net("OUT", [("OUT", "1"), ("Q2", "C")]),
        _net("VCC", [("VCC", "1")]),
        _net("EMIT", [("Q1", "E"), ("Q2", "E")]),
    ]

    return _circuit(topology, [q1, q2, vcc, vin, vout], nets, topology)


def _build_multistage(topology: str, second_stage_opamp: bool = False) -> Circuit:
    q1 = _bjt("Q1", "BC547", stage="0")
    stage2 = _opamp("U1", stage="1") if second_stage_opamp else _bjt("Q2", "BC547", stage="1")
    rc1 = _resistor("RC1")
    rc2 = _resistor("RC2") if not second_stage_opamp else None
    vcc = _voltage_source()
    vin = _connector("IN")
    vout = _connector("OUT")

    nets = [
        _net("IN", [("IN", "1"), ("Q1", "B")]),
        _net("MID", [("RC1", "2"), ("Q1", "C")]),
        _net("VCC", [("VCC", "1"), ("RC1", "1")]),
    ]

    components = [q1, stage2, rc1, vcc, vin, vout]
    if second_stage_opamp:
        nets.append(_net("MID", [("U1", "+"), ("RC1", "2")]))
        nets.append(_net("OUT", [("OUT", "1"), ("U1", "OUT")]))
        nets.append(_net("VCC", [("U1", "VS+"), ("VCC", "1")]))
    else:
        nets.append(_net("MID", [("Q2", "B"), ("RC1", "2")]))
        nets.append(_net("OUT", [("OUT", "1"), ("RC2", "2"), ("Q2", "C")]))
        nets.append(_net("VCC", [("RC2", "1"), ("VCC", "1")]))
        if rc2 is not None:
            components.append(rc2)
        components.append(_connector("IN2"))

    if second_stage_opamp:
        components.extend([vin, vout])

    return _circuit(topology, components, nets, topology)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "topology,circuit_builder,expected_libs",
    [
        ("bjt_common_emitter", lambda: _build_bjt_topology("bjt_common_emitter", "B", "C"), ["Transistor_BJT:BC547"]),
        ("bjt_common_collector", lambda: _build_bjt_topology("bjt_common_collector", "B", "E"), ["Transistor_BJT:BC547"]),
        ("bjt_common_base", lambda: _build_bjt_topology("bjt_common_base", "E", "C"), ["Transistor_BJT:BC547"]),
        ("mosfet_common_source", lambda: _build_mosfet_topology("mosfet_common_source", "G", "D"), ["Transistor_FET:IRF540"]),
        ("mosfet_common_drain", lambda: _build_mosfet_topology("mosfet_common_drain", "G", "S"), ["Transistor_FET:IRF540"]),
        ("mosfet_common_gate", lambda: _build_mosfet_topology("mosfet_common_gate", "S", "D"), ["Transistor_FET:IRF540"]),
        ("opamp_inverting", lambda: _build_opamp_topology("opamp_inverting"), ["Amplifier_Operational:LM358"]),
        ("opamp_differential", lambda: _build_opamp_diff_topology("opamp_differential"), ["Amplifier_Operational:LM358"]),
        ("class_ab", lambda: _build_class_ab("class_ab"), ["Transistor_BJT:BC547", "Transistor_BJT:BC557"]),
        ("class_d", lambda: _build_class_d("class_d"), ["Transistor_FET:IRF540", "Device:L"]),
        ("darlington", lambda: _build_darlington("darlington"), ["Transistor_BJT:BC547"]),
    ],
)
async def test_kicad_sch_export_golden(tmp_path: Path, topology: str, circuit_builder, expected_libs) -> None:
    circuit = circuit_builder()
    exporter = KiCadSchExporter()

    content = await exporter.export(circuit, ExportFormat.KICAD)
    assert "(kicad_sch" in content
    for lib_id in expected_libs:
        assert lib_id in content

    kicad_cli = shutil.which("kicad-cli")
    if kicad_cli:
        sch_path = tmp_path / f"{topology}.kicad_sch"
        sch_path.write_text(content, encoding="utf-8")
        out_path = tmp_path / f"{topology}.svg"
        subprocess.run(
            [kicad_cli, "sch", "export", "svg", "-o", str(out_path), str(sch_path)],
            check=True,
        )


@pytest.mark.asyncio
async def test_kicad_sch_export_multistage_variants(tmp_path: Path) -> None:
    exporter = KiCadSchExporter()

    ce_to_ce = _build_multistage("multi_ce", second_stage_opamp=False)
    ce_to_opamp = _build_multistage("multi_ce_opamp", second_stage_opamp=True)

    for name, circuit in [("multi_ce", ce_to_ce), ("multi_ce_opamp", ce_to_opamp)]:
        content = await exporter.export(circuit, ExportFormat.KICAD)
        assert "(kicad_sch" in content

        kicad_cli = shutil.which("kicad-cli")
        if kicad_cli:
            sch_path = tmp_path / f"{name}.kicad_sch"
            sch_path.write_text(content, encoding="utf-8")
            out_path = tmp_path / f"{name}.svg"
            subprocess.run(
                [kicad_cli, "sch", "export", "svg", "-o", str(out_path), str(sch_path)],
                check=True,
            )
