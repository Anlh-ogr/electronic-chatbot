"""
IR serialization roundtrip tests
Tests serialize/deserialize không làm mất dữ liệu
"""

import pytest
import json
from app.domains.circuits.entities import (
    Component, ComponentType, Net, Port, Circuit, ParameterValue,
    PinRef, PortDirection, Constraint
)
from app.domains.circuits.ir import CircuitIRSerializer


class TestCircuitIRSerialization:
    """Test IR serialize/deserialize"""
    
    def test_serialize_empty_circuit(self):
        """Serialize empty circuit"""
        circuit = Circuit(
            name="Empty",
            _components={},
            _nets={},
            _ports={},
            _constraints={}
        )
        
        ir_dict = CircuitIRSerializer.serialize(circuit)
        
        assert ir_dict["meta"]["circuit_name"] == "Empty"
        assert ir_dict["components"] == []
        assert ir_dict["nets"] == []
        assert ir_dict["ports"] == []
        assert ir_dict["constraints"] == []
    
    def test_serialize_circuit_with_resistor(self):
        """Serialize circuit với 1 resistor"""
        r1 = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(1000, "ohm")}
        )
        
        circuit = Circuit(
            name="Simple",
            _components={"R1": r1},
            _nets={},
            _ports={},
            _constraints={}
        )
        
        ir_dict = CircuitIRSerializer.serialize(circuit)
        
        assert len(ir_dict["components"]) == 1
        comp = ir_dict["components"][0]
        assert comp["id"] == "R1"
        assert comp["type"] == ComponentType.RESISTOR.value
        assert "resistance" in comp["parameters"]
        assert comp["parameters"]["resistance"]["value"] == 1000
        assert comp["parameters"]["resistance"]["unit"] == "ohm"
    
    def test_deserialize_circuit_with_resistor(self):
        """Deserialize circuit từ dict"""
        ir_dict = {
            "meta": {
                "version": "1.0",
                "schema_version": "1.0",
                "circuit_name": "Test",
            },
            "components": [
                {
                    "id": "R1",
                    "type": ComponentType.RESISTOR.value,
                    "pins": ["1", "2"],
                    "parameters": {
                        "resistance": {
                            "value": 2200,
                            "unit": "ohm"
                        }
                    }
                }
            ],
            "nets": [],
            "ports": [],
            "constraints": []
        }
        
        circuit = CircuitIRSerializer.deserialize(ir_dict)
        
        assert circuit.name == "Test"
        assert len(circuit.components) == 1
        assert "R1" in circuit.components
        
        r1 = circuit.components["R1"]
        assert r1.type == ComponentType.RESISTOR
        assert r1.parameters["resistance"].value == 2200
        assert r1.parameters["resistance"].unit == "ohm"
    
    def test_roundtrip_simple_circuit(self):
        """Roundtrip test: Circuit → Dict → Circuit"""
        # Original circuit
        r1 = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(1000, "ohm")}
        )
        
        original = Circuit(
            name="Original",
            _components={"R1": r1},
            _nets={},
            _ports={},
            _constraints={}
        )
        
        # Serialize
        ir_dict = CircuitIRSerializer.serialize(original)
        
        # Deserialize
        restored = CircuitIRSerializer.deserialize(ir_dict)
        
        # Compare
        assert restored.name == original.name
        assert len(restored.components) == len(original.components)
        assert "R1" in restored.components
        
        r1_restored = restored.components["R1"]
        r1_original = original.components["R1"]
        
        assert r1_restored.id == r1_original.id
        assert r1_restored.type == r1_original.type
        assert r1_restored.pins == r1_original.pins
        assert r1_restored.parameters["resistance"].value == r1_original.parameters["resistance"].value
    
    def test_roundtrip_circuit_with_nets(self):
        """Roundtrip với nets"""
        r1 = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(1000, "ohm")}
        )
        
        r2 = Component(
            id="R2",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(2200, "ohm")}
        )
        
        net_vcc = Net(
            name="VCC",
            connected_pins=(
                PinRef("R1", "1"),
                PinRef("R2", "1")
            )
        )
        
        original = Circuit(
            name="With Nets",
            _components={"R1": r1, "R2": r2},
            _nets={"VCC": net_vcc},
            _ports={},
            _constraints={}
        )
        
        # Roundtrip
        ir_dict = CircuitIRSerializer.serialize(original)
        restored = CircuitIRSerializer.deserialize(ir_dict)
        
        assert len(restored.nets) == 1
        assert "VCC" in restored.nets
        
        net = restored.nets["VCC"]
        assert net.name == "VCC"
        assert len(net.connected_pins) == 2
        
        pins = [f"{p.component_id}.{p.pin_name}" for p in net.connected_pins]
        assert "R1.1" in pins
        assert "R2.1" in pins
    
    def test_roundtrip_circuit_with_ports(self):
        """Roundtrip với ports"""
        r1 = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(1000, "ohm")}
        )
        net_in = Net(name="IN", connected_pins=(PinRef("R1", "1"),))
        net_out = Net(name="OUT", connected_pins=(PinRef("R1", "2"),))

        port_in = Port(
            name="INPUT",
            net_name="IN",
            direction=PortDirection.INPUT
        )
        
        port_out = Port(
            name="OUTPUT",
            net_name="OUT",
            direction=PortDirection.OUTPUT
        )
        
        original = Circuit(
            name="With Ports",
            _components={"R1": r1},
            _nets={"IN": net_in, "OUT": net_out},
            _ports={"INPUT": port_in, "OUTPUT": port_out},
            _constraints={}
        )
        
        ir_dict = CircuitIRSerializer.serialize(original)
        restored = CircuitIRSerializer.deserialize(ir_dict)
        
        assert len(restored.ports) == 2
        assert "INPUT" in restored.ports
        assert "OUTPUT" in restored.ports
        
        assert restored.ports["INPUT"].direction == PortDirection.INPUT
        assert restored.ports["OUTPUT"].direction == PortDirection.OUTPUT
    
    def test_roundtrip_circuit_with_constraints(self):
        """Roundtrip với constraints"""
        constraint_gain = Constraint(
            name="gain",
            value=20.0,
            unit="dB"
        )
        
        constraint_bw = Constraint(
            name="bandwidth",
            value=100e3,
            unit="Hz"
        )
        
        original = Circuit(
            name="With Constraints",
            _components={},
            _nets={},
            _ports={},
            _constraints={
                "gain": constraint_gain,
                "bandwidth": constraint_bw
            }
        )
        
        ir_dict = CircuitIRSerializer.serialize(original)
        restored = CircuitIRSerializer.deserialize(ir_dict)
        
        assert len(restored.constraints) == 2
        assert "gain" in restored.constraints
        assert "bandwidth" in restored.constraints
        
        assert restored.constraints["gain"].value == 20.0
        assert restored.constraints["bandwidth"].value == 100e3
    
    def test_roundtrip_complex_circuit(self):
        """Roundtrip test với circuit phức tạp (BJT amplifier)"""
        # Components
        q1 = Component(
            id="Q1",
            type=ComponentType.BJT,
            pins=("C", "B", "E"),
            parameters={"model": ParameterValue("2N2222", None)}
        )
        
        rc = Component(
            id="RC",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(3300, "ohm")}
        )
        
        re = Component(
            id="RE",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(1000, "ohm")}
        )
        
        vcc = Component(
            id="VCC",
            type=ComponentType.VOLTAGE_SOURCE,
            pins=("P", "N"),
            parameters={"voltage": ParameterValue(12, "V")}
        )
        
        gnd = Component(
            id="GND",
            type=ComponentType.GROUND,
            pins=("G",),
            parameters={}
        )
        
        # Nets
        net_vcc = Net(
            name="VCC",
            connected_pins=(
                PinRef("RC", "1"),
                PinRef("VCC", "P")
            )
        )
        
        net_collector = Net(
            name="COLLECTOR",
            connected_pins=(
                PinRef("RC", "2"),
                PinRef("Q1", "C")
            )
        )
        
        net_emitter = Net(
            name="EMITTER",
            connected_pins=(
                PinRef("Q1", "E"),
                PinRef("RE", "1")
            )
        )

        net_base = Net(
            name="BASE",
            connected_pins=(PinRef("Q1", "B"),)
        )
        
        net_gnd = Net(
            name="GND",
            connected_pins=(
                PinRef("RE", "2"),
                PinRef("VCC", "N"),
                PinRef("GND", "G")
            )
        )
        
        # Ports
        port_base = Port(
            name="BASE",
            net_name="BASE",
            direction=PortDirection.INPUT
        )
        
        port_out = Port(
            name="OUTPUT",
            net_name="COLLECTOR",
            direction=PortDirection.OUTPUT
        )
        
        # Constraints
        constraint_gain = Constraint(
            name="gain",
            value=15.0,
            unit=None
        )
        
        # Circuit
        original = Circuit(
            name="BJT Amplifier CE",
            _components={
                "Q1": q1,
                "RC": rc,
                "RE": re,
                "VCC": vcc,
                "GND": gnd
            },
            _nets={
                "VCC": net_vcc,
                "COLLECTOR": net_collector,
                "EMITTER": net_emitter,
                "BASE": net_base,
                "GND": net_gnd
            },
            _ports={
                "BASE": port_base,
                "OUTPUT": port_out
            },
            _constraints={
                "gain": constraint_gain
            }
        )
        
        # Roundtrip
        ir_dict = CircuitIRSerializer.serialize(original)
        restored = CircuitIRSerializer.deserialize(ir_dict)
        
        # Verify
        assert restored.name == original.name
        assert len(restored.components) == len(original.components)
        assert len(restored.nets) == len(original.nets)
        assert len(restored.ports) == len(original.ports)
        assert len(restored.constraints) == len(original.constraints)
        
        # Verify BJT
        assert "Q1" in restored.components
        q1_restored = restored.components["Q1"]
        assert q1_restored.type == ComponentType.BJT
        assert q1_restored.parameters["model"].value == "2N2222"
        
        # Verify net connections
        net_collector_restored = restored.nets["COLLECTOR"]
        pins = [f"{p.component_id}.{p.pin_name}" for p in net_collector_restored.connected_pins]
        assert "RC.2" in pins
        assert "Q1.C" in pins
    
    def test_roundtrip_with_json_string(self):
        """Roundtrip qua JSON string (thực tế)"""
        r1 = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(1000, "ohm")}
        )
        
        original = Circuit(
            name="JSON Test",
            _components={"R1": r1},
            _nets={},
            _ports={},
            _constraints={}
        )
        
        # Serialize → JSON string
        ir_dict = CircuitIRSerializer.serialize(original)
        json_str = json.dumps(ir_dict, indent=2)
        
        # JSON string → Deserialize
        ir_dict_loaded = json.loads(json_str)
        restored = CircuitIRSerializer.deserialize(ir_dict_loaded)
        
        # Verify
        assert restored.name == original.name
        assert "R1" in restored.components
    
    def test_roundtrip_utility_function(self):
        """Test CircuitIRSerializer.roundtrip_test()"""
        r1 = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(1000, "ohm")}
        )
        
        circuit = Circuit(
            name="Roundtrip Test",
            _components={"R1": r1},
            _nets={},
            _ports={},
            _constraints={}
        )
        
        # Utility function
        success = CircuitIRSerializer.roundtrip_test(circuit)
        
        assert success is True


class TestIRSchemaValidation:
    """Test IR schema validation"""
    
    def test_deserialize_missing_name_field(self):
        """Deserialize với missing 'meta' → ValueError"""
        ir_dict = {
            "components": [],
            "nets": [],
            "ports": [],
            "constraints": []
        }
        
        with pytest.raises(ValueError):
            CircuitIRSerializer.deserialize(ir_dict)
    
    def test_deserialize_invalid_component_type(self):
        """Deserialize với invalid ComponentType"""
        ir_dict = {
            "meta": {
                "version": "1.0",
                "schema_version": "1.0",
                "circuit_name": "Test",
            },
            "components": [
                {
                    "id": "X1",
                    "type": "INVALID_TYPE",  # Không tồn tại
                    "pins": ["1", "2"],
                    "parameters": {}
                }
            ],
            "nets": [],
            "ports": [],
            "constraints": []
        }
        
        with pytest.raises(ValueError):
            CircuitIRSerializer.deserialize(ir_dict)
    
    def test_serialize_to_json_and_back(self):
        """Serialize, convert to JSON, parse, deserialize"""
        r1 = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(4700, "ohm")}
        )
        
        circuit = Circuit(
            name="JSON Roundtrip",
            _components={"R1": r1},
            _nets={},
            _ports={},
            _constraints={}
        )
        
        # Circuit → dict → JSON
        ir_dict = CircuitIRSerializer.serialize(circuit)
        json_bytes = json.dumps(ir_dict).encode("utf-8")
        
        # JSON → dict → Circuit
        ir_dict_restored = json.loads(json_bytes.decode("utf-8"))
        circuit_restored = CircuitIRSerializer.deserialize(ir_dict_restored)
        
        assert circuit_restored.name == circuit.name
        assert circuit_restored.components["R1"].parameters["resistance"].value == 4700
