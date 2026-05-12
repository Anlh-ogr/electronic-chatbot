from app.application.circuits.dtos import ExportFormat
from app.domains.circuits.entities import Circuit, Component, ComponentType, Net, ParameterValue, PinRef
from app.infrastructure.exporters.kicad_sch_exporter import KiCadSchExporter
import asyncio


def R(ref, v):
    return Component(
        id=ref,
        type=ComponentType.RESISTOR,
        pins=("1", "2"),
        parameters={"resistance": ParameterValue(v, "Ohm")},
    )


def C(ref, v):
    return Component(
        id=ref,
        type=ComponentType.CAPACITOR,
        pins=("1", "2"),
        parameters={"capacitance": ParameterValue(v, "F")},
    )


def Q(ref):
    return Component(
        id=ref,
        type=ComponentType.BJT_NPN,
        pins=("B", "C", "E"),
        parameters={"model": ParameterValue("BC547", None)},
    )


comps = [
    R("R1", "10k"),
    R("R2", "10k"),
    R("RC", "1k"),
    R("RE1", "270"),
    R("RE2", "750"),
    C("CIN", "10u"),
    C("COUT", "10u"),
    C("CE", "100u"),
    Q("Q1"),
    Component(
        id="VCC",
        type=ComponentType.VOLTAGE_SOURCE,
        pins=("1",),
        parameters={"voltage": ParameterValue("12", "V")},
    ),
    Component(id="GND", type=ComponentType.GROUND, pins=("1",), parameters={}),
    Component(id="IN", type=ComponentType.CONNECTOR, pins=("1",), parameters={}),
    Component(id="OUT", type=ComponentType.CONNECTOR, pins=("1",), parameters={}),
]
nets = [
    Net(name="0", connected_pins=(PinRef("GND", "1"), PinRef("R2", "2"), PinRef("RE2", "2"), PinRef("CE", "2"))),
    Net(name="VCC", connected_pins=(PinRef("VCC", "1"), PinRef("R1", "1"), PinRef("RC", "1"))),
    Net(name="IN", connected_pins=(PinRef("IN", "1"), PinRef("CIN", "1"))),
    Net(name="OUT", connected_pins=(PinRef("OUT", "1"), PinRef("COUT", "2"))),
    Net(
        name="BASE_Q1",
        connected_pins=(PinRef("Q1", "B"), PinRef("R1", "2"), PinRef("R2", "1"), PinRef("CIN", "2")),
    ),
    Net(name="EMITTER_Q1", connected_pins=(PinRef("Q1", "E"), PinRef("RE1", "1"))),
    Net(name="COLLECTOR_Q1", connected_pins=(PinRef("Q1", "C"), PinRef("RC", "2"), PinRef("COUT", "1"))),
    Net(name="CE_BYPASS", connected_pins=(PinRef("RE1", "2"), PinRef("RE2", "1"), PinRef("CE", "1"))),
]
c = Circuit(
    name="t",
    id="test-id",
    _components={x.id: x for x in comps},
    _nets={n.name: n for n in nets},
    _ports={},
    _constraints={},
    topology_type="common_emitter",
)


async def main():
    exp = KiCadSchExporter()
    sch = await exp.export(c, ExportFormat.KICAD)
    marker = "  (symbol\n   (lib_id"
    marker2 = "  (symbol\r\n   (lib_id"
    i = sch.find(marker)
    if i < 0:
        i = sch.find(marker2)
    if i < 0:
        print("could not find symbol instance marker")
        return
    j = sch.find(marker, i + 3)
    if j < 0:
        j = sch.find(marker2, i + 3)
    block = sch[i:j] if j > i else sch[i : i + 2000]
    bal = 0
    for ch in block:
        if ch == "(":
            bal += 1
        elif ch == ")":
            bal -= 1
    print("paren balance in first SYMBOL INSTANCE block:", bal)
    print("--- tail of block ---")
    print(block[-400:])


asyncio.run(main())
