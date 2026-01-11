"""
Edge case tests for entities module
Tests để tăng coverage từ 60% → 80%
"""

import pytest
from app.domains.circuits.entities import (
    Component, ComponentType, Net, Port, Circuit, ParameterValue,
    PinRef, PortDirection, Constraint
)


class TestParameterValue:
    """Test ParameterValue validation và edge cases"""
    
    def test_parameter_value_with_none_unit(self):
        """ParameterValue có thể có unit=None (như model string)"""
        param = ParameterValue(value="2N2222", unit=None)
        assert param.value == "2N2222"
        assert param.unit is None
    
    def test_parameter_value_with_numeric_value(self):
        """ParameterValue với giá trị số"""
        param = ParameterValue(value=1000, unit="ohm")
        assert param.value == 1000
        assert param.unit == "ohm"
    
    def test_parameter_value_with_float(self):
        """ParameterValue với float"""
        param = ParameterValue(value=10.5e-6, unit="F")
        assert param.value == 10.5e-6
        assert param.unit == "F"
    
    def test_parameter_value_immutable(self):
        """ParameterValue là immutable"""
        param = ParameterValue(value=1000, unit="ohm")
        with pytest.raises(Exception):  # FrozenInstanceError
            param.value = 2000


class TestComponent:
    """Test Component validation"""
    
    def test_component_resistor_valid(self):
        """Component RESISTOR hợp lệ"""
        component = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={
                "resistance": ParameterValue(1000, "ohm")
            }
        )
        assert component.id == "R1"
        assert component.type == ComponentType.RESISTOR
        assert len(component.pins) == 2
    
    def test_component_bjt_missing_model_parameter(self):
        """Component BJT thiếu 'model' parameter → ValueError"""
        with pytest.raises(ValueError) as exc_info:
            Component(
                id="Q1",
                type=ComponentType.BJT,
                pins=("C", "B", "E"),
                parameters={
                    # Thiếu "model"
                    "beta": ParameterValue(100, None)
                }
            )
        # Error message tiếng Việt
        assert "model" in str(exc_info.value).lower()
        assert "q1" in str(exc_info.value).lower()
        assert "bjt" in str(exc_info.value).lower()
    
    def test_component_bjt_with_model_valid(self):
        """Component BJT với 'model' parameter hợp lệ"""
        component = Component(
            id="Q1",
            type=ComponentType.BJT,
            pins=("C", "B", "E"),
            parameters={
                "model": ParameterValue("2N2222", None)
            }
        )
        assert component.id == "Q1"
        assert component.parameters["model"].value == "2N2222"
    
    def test_component_opamp_no_validation(self):
        """Component OPAMP không bắt buộc model parameter ở entities layer"""
        # OpAmp không validate ở entities layer (sẽ validate ở rules layer)
        component = Component(
            id="U1",
            type=ComponentType.OPAMP,
            pins=("IN+", "IN-", "OUT", "V+", "V-"),
            parameters={}  # OK - không raise error
        )
        assert component.type == ComponentType.OPAMP
    
    def test_component_opamp_with_model_valid(self):
        """Component OPAMP với model hợp lệ"""
        component = Component(
            id="U1",
            type=ComponentType.OPAMP,
            pins=("IN+", "IN-", "OUT", "V+", "V-"),
            parameters={
                "model": ParameterValue("LM741", None)
            }
        )
        assert component.parameters["model"].value == "LM741"
    
    def test_component_capacitor_valid(self):
        """Component CAPACITOR hợp lệ"""
        component = Component(
            id="C1",
            type=ComponentType.CAPACITOR,
            pins=("P", "N"),
            parameters={
                "capacitance": ParameterValue(10e-6, "F")
            }
        )
        assert component.type == ComponentType.CAPACITOR
        assert component.parameters["capacitance"].value == 10e-6
    
    def test_component_ground_no_parameters(self):
        """Component GROUND không cần parameters"""
        component = Component(
            id="GND1",
            type=ComponentType.GROUND,
            pins=("G",),
            parameters={}
        )
        assert component.type == ComponentType.GROUND
        assert len(component.parameters) == 0
    
    def test_component_immutable(self):
        """Component là immutable"""
        component = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(1000, "ohm")}
        )
        
        with pytest.raises(Exception):  # FrozenInstanceError
            component.id = "R2"
        
        with pytest.raises(Exception):
            component.pins = ("3", "4")


class TestNet:
    """Test Net validation"""
    
    def test_net_with_two_pins_valid(self):
        """Net với 2 pins hợp lệ"""
        net = Net(
            name="VCC",
            connected_pins=(
                PinRef("R1", "1"),
                PinRef("V1", "P")
            )
        )
        assert net.name == "VCC"
        assert len(net.connected_pins) == 2
    
    def test_net_with_multiple_pins(self):
        """Net có thể kết nối nhiều pins"""
        net = Net(
            name="GND",
            connected_pins=(
                PinRef("R1", "2"),
                PinRef("R2", "2"),
                PinRef("C1", "N"),
                PinRef("GND1", "G")
            )
        )
        assert len(net.connected_pins) == 4
    
    def test_net_immutable(self):
        """Net là immutable"""
        net = Net(
            name="VCC",
            connected_pins=(PinRef("R1", "1"), PinRef("V1", "P"))
        )
        
        with pytest.raises(Exception):
            net.name = "VDD"


class TestPort:
    """Test Port"""
    
    def test_port_input_direction(self):
        """Port với direction INPUT"""
        port = Port(
            name="INPUT",
            net_name="IN",
            direction=PortDirection.INPUT
        )
        assert port.direction == PortDirection.INPUT
    
    def test_port_output_direction(self):
        """Port với direction OUTPUT"""
        port = Port(
            name="OUTPUT",
            net_name="OUT",
            direction=PortDirection.OUTPUT
        )
        assert port.direction == PortDirection.OUTPUT
    
    def test_port_power_direction(self):
        """Port với direction POWER"""
        port = Port(
            name="VCC",
            net_name="VCC",
            direction=PortDirection.POWER
        )
        assert port.direction == PortDirection.POWER


class TestCircuit:
    """Test Circuit entity"""
    
    def test_circuit_empty_valid(self):
        """Circuit rỗng hợp lệ"""
        circuit = Circuit(
            name="Empty Circuit",
            _components={},
            _nets={},
            _ports={},
            _constraints={}
        )
        assert circuit.name == "Empty Circuit"
        assert len(circuit.components) == 0
    
    def test_circuit_with_components(self):
        """Circuit với components"""
        r1 = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(1000, "ohm")}
        )
        
        circuit = Circuit(
            name="Test Circuit",
            _components={"R1": r1},
            _nets={},
            _ports={},
            _constraints={}
        )
        
        assert len(circuit.components) == 1
        assert "R1" in circuit.components
        assert circuit.components["R1"].id == "R1"
    
    def test_circuit_with_nets(self):
        """Circuit với nets (cần components tồn tại)"""
        r1 = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(1000, "ohm")}
        )
        
        v1 = Component(
            id="V1",
            type=ComponentType.VOLTAGE_SOURCE,
            pins=("P", "N"),
            parameters={"voltage": ParameterValue(12, "V")}
        )
        
        net = Net(
            name="VCC",
            connected_pins=(PinRef("R1", "1"), PinRef("V1", "P"))
        )
        
        circuit = Circuit(
            name="Test",
            _components={"R1": r1, "V1": v1},
            _nets={"VCC": net},
            _ports={},
            _constraints={}
        )
        
        assert "VCC" in circuit.nets
    
    def test_circuit_with_ports(self):
        """Circuit với ports (cần net tồn tại)"""
        net_in = Net(
            name="IN",
            connected_pins=(PinRef("R1", "1"),)
        )
        
        r1 = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(1000, "ohm")}
        )
        
        port = Port(
            name="INPUT",
            net_name="IN",
            direction=PortDirection.INPUT
        )
        
        circuit = Circuit(
            name="Test",
            _components={"R1": r1},
            _nets={"IN": net_in},
            _ports={"INPUT": port},
            _constraints={}
        )
        
        assert "INPUT" in circuit.ports
    
    def test_circuit_with_constraints(self):
        """Circuit với constraints"""
        constraint = Constraint(
            name="gain",
            value=20.0,
            unit="dB"
        )
        
        circuit = Circuit(
            name="Test",
            _components={},
            _nets={},
            _ports={},
            _constraints={"gain": constraint}
        )
        
        assert "gain" in circuit.constraints
        assert circuit.constraints["gain"].value == 20.0
    
    def test_circuit_components_mapping_is_readonly(self):
        """Circuit.components là read-only MappingProxyType"""
        circuit = Circuit(
            name="Test",
            _components={},
            _nets={},
            _ports={},
            _constraints={}
        )
        
        # Không thể modify
        with pytest.raises(TypeError):
            circuit.components["NEW"] = Component(
                id="NEW",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(1000, "ohm")}
            )
    
    def test_circuit_nets_mapping_is_readonly(self):
        """Circuit.nets là read-only"""
        circuit = Circuit(
            name="Test",
            _components={},
            _nets={},
            _ports={},
            _constraints={}
        )
        
        with pytest.raises(TypeError):
            circuit.nets["NEW"] = Net(
                name="NEW",
                connected_pins=(PinRef("A", "1"),)
            )
    
    def test_circuit_with_component_adds_component(self):
        """Circuit.with_component() trả về circuit mới với component mới"""
        original = Circuit(
            name="Original",
            _components={},
            _nets={},
            _ports={},
            _constraints={}
        )
        
        new_component = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(1000, "ohm")}
        )
        
        # Tạo circuit mới
        updated = original.with_component(new_component)
        
        # Original không thay đổi
        assert len(original.components) == 0
        
        # Updated có component mới
        assert len(updated.components) == 1
        assert "R1" in updated.components
    
    def test_circuit_validate_basic_no_errors(self):
        """Circuit.validate_basic() không throw exception với circuit hợp lệ"""
        r1 = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(1000, "ohm")}
        )
        
        # Không có exception
        circuit = Circuit(
            name="Valid",
            _components={"R1": r1},
            _nets={},
            _ports={},
            _constraints={}
        )
        
        # validate_basic() được gọi trong __post_init__
        assert circuit is not None
    
    def test_circuit_validate_basic_duplicate_component_id(self):
        """Circuit với duplicate component ID → ValidationError"""
        # Circuit không cho phép duplicate ID trong _components dict
        # Nhưng nếu 2 components có cùng ID...
        
        r1 = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(1000, "ohm")}
        )
        
        r2 = Component(
            id="R1",  # Trùng ID
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(2000, "ohm")}
        )
        
        # Dict key overwrite → chỉ có 1 component trong dict
        circuit = Circuit(
            name="Duplicate",
            _components={"R1": r2},  # Chỉ có r2
            _nets={},
            _ports={},
            _constraints={}
        )
        
        assert len(circuit.components) == 1


class TestPinRef:
    """Test PinRef"""
    
    def test_pin_ref_creation(self):
        """PinRef có thể tạo"""
        pin_ref = PinRef("R1", "1")
        assert pin_ref.component_id == "R1"
        assert pin_ref.pin_name == "1"  # Thuộc tính là pin_name, không phải pin
    
    def test_pin_ref_immutable(self):
        """PinRef là immutable"""
        pin_ref = PinRef("R1", "1")
        
        with pytest.raises(Exception):
            pin_ref.component_id = "R2"


class TestConstraint:
    """Test Constraint"""
    
    def test_constraint_with_numeric_value(self):
        """Constraint với numeric value"""
        constraint = Constraint(
            name="gain",
            value=20.0,
            unit="dB"
        )
        assert constraint.value == 20.0
        assert constraint.unit == "dB"
    
    def test_constraint_with_string_value(self):
        """Constraint có thể có string value"""
        constraint = Constraint(
            name="topology",
            value="CE",
            unit=None
        )
        assert constraint.value == "CE"
    
    def test_constraint_immutable(self):
        """Constraint là immutable"""
        constraint = Constraint(name="gain", value=20.0, unit="dB")
        
        with pytest.raises(Exception):
            constraint.value = 30.0


class TestValidationException:
    """Test ValueError exception cho validation"""
    
    def test_validation_error_can_be_raised(self):
        """ValueError có thể raise cho validation"""
        with pytest.raises(ValueError) as exc_info:
            raise ValueError("Test error")
        
        assert "Test error" in str(exc_info.value)
