# Hướng Dẫn Sử Dụng API - Domain Layer

**Tài liệu này hướng dẫn cách sử dụng domain layer để tạo, validate và xử lý mạch điện**

---

## 📚 Mục Lục

1. [Tạo Circuit Từ Template](#1-tạo-circuit-từ-template)
2. [Tạo Circuit Thủ Công](#2-tạo-circuit-thủ-công)
3. [Validation](#3-validation)
4. [Serialization](#4-serialization)
5. [Thêm Rules Mới](#5-thêm-rules-mới)
6. [Thêm Template Mới](#6-thêm-template-mới)

---

## 1. Tạo Circuit Từ Template

### **BJT Amplifier - Cách Đơn Giản**

```python
from app.domains.circuits.template_builder import AmplifierFactory

# Tạo Common Emitter amplifier
circuit = AmplifierFactory.create_bjt(
    topology="CE",      # CE, CC, hoặc CB
    gain=15.0,         # Gain mục tiêu
    vcc=12.0           # Điện áp nguồn (V)
)

# Kết quả: Circuit object với tất cả components đã tính toán
print(f"Circuit: {circuit.name}")
print(f"Components: {len(circuit.components)}")
```

### **BJT Amplifier - Cách Chi Tiết**

```python
from app.domains.circuits.template_builder import (
    BJTAmplifierConfig,
    BJTAmplifierBuilder
)

# Cấu hình chi tiết
config = BJTAmplifierConfig(
    # Topology
    topology="CE",              # CE, CC, CB
    bias_type="voltage_divider", # voltage_divider, fixed, self
    
    # Operating point
    vcc=12.0,                   # Điện áp nguồn (V)
    ic_target=1.5e-3,          # Dòng collector mục tiêu (A)
    gain_target=20.0,          # Gain mục tiêu
    
    # BJT model
    bjt_model="2N3904",        # Hoặc "2N2222", "BC547"
    beta=100.0,                # Hệ số khuếch đại dòng
    
    # Override giá trị tự động (optional)
    rc=3300,                   # Collector resistor (Ω)
    re=1000,                   # Emitter resistor (Ω)
    r1=47000,                  # Base bias R1 (Ω)
    r2=10000,                  # Base bias R2 (Ω)
    
    # Capacitors
    include_coupling=True,
    cin=10e-6,                 # Input coupling capacitor (F)
    cout=10e-6,                # Output coupling capacitor (F)
    ce=100e-6                  # Emitter bypass capacitor (F)
)

# Build circuit
builder = BJTAmplifierBuilder(config)
circuit = builder.build()
```

### **OpAmp Amplifier**

```python
# Inverting amplifier
circuit = AmplifierFactory.create_opamp(
    topology="inverting",
    gain=-10.0
)

# Non-inverting amplifier  
circuit = AmplifierFactory.create_opamp(
    topology="non_inverting",
    gain=11.0
)

# Differential amplifier
circuit = AmplifierFactory.create_opamp(
    topology="differential",
    gain=5.0
)

# Chi tiết với config
from app.domains.circuits.template_builder import (
    OpAmpAmplifierConfig,
    OpAmpAmplifierBuilder
)

config = OpAmpAmplifierConfig(
    topology="inverting",
    gain=-10.0,
    opamp_model="LM741",       # Hoặc "LM358", "TL071"
    r1=10000,                  # Input resistor (Ω)
    r2=100000,                 # Feedback resistor (Ω)
    include_coupling=True
)

circuit = OpAmpAmplifierBuilder(config).build()
```

---

## 2. Tạo Circuit Thủ Công

### **Bước 1: Tạo Components**

```python
from app.domains.circuits.entities import (
    Component, ComponentType, ParameterValue
)

# Điện trở
r1 = Component(
    id="R1",
    type=ComponentType.RESISTOR,
    pins=("1", "2"),
    parameters={
        "resistance": ParameterValue(1000, "ohm")
    }
)

# Tụ điện
c1 = Component(
    id="C1",
    type=ComponentType.CAPACITOR,
    pins=("P", "N"),
    parameters={
        "capacitance": ParameterValue(10e-6, "F")
    }
)

# BJT
q1 = Component(
    id="Q1",
    type=ComponentType.BJT,
    pins=("C", "B", "E"),
    parameters={
        "model": ParameterValue("2N2222", None)
    }
)

# OpAmp
u1 = Component(
    id="U1",
    type=ComponentType.OPAMP,
    pins=("IN+", "IN-", "OUT", "V+", "V-"),
    parameters={
        "model": ParameterValue("LM741", None)
    }
)

# Nguồn điện áp
v1 = Component(
    id="V1",
    type=ComponentType.VOLTAGE_SOURCE,
    pins=("P", "N"),
    parameters={
        "voltage": ParameterValue(12, "V")
    }
)

# Ground
gnd = Component(
    id="GND1",
    type=ComponentType.GROUND,
    pins=("G",),
    parameters={}
)
```

### **Bước 2: Tạo Nets (Kết Nối)**

```python
from app.domains.circuits.entities import Net, PinRef

# Net kết nối R1 với Q1
net_collector = Net(
    name="COLLECTOR",
    connected_pins=(
        PinRef("R1", "2"),
        PinRef("Q1", "C")
    )
)

# Net VCC (nguồn)
net_vcc = Net(
    name="VCC",
    connected_pins=(
        PinRef("R1", "1"),
        PinRef("V1", "P")
    )
)

# Net GND
net_gnd = Net(
    name="GND",
    connected_pins=(
        PinRef("Q1", "E"),
        PinRef("V1", "N"),
        PinRef("GND1", "G")
    )
)
```

### **Bước 3: Tạo Ports (Optional)**

```python
from app.domains.circuits.entities import Port, PortDirection

# Input port
port_in = Port(
    name="INPUT",
    net_name="BASE",
    direction=PortDirection.INPUT
)

# Output port
port_out = Port(
    name="OUTPUT",
    net_name="COLLECTOR",
    direction=PortDirection.OUTPUT
)

# Power port
port_vcc = Port(
    name="VCC",
    net_name="VCC",
    direction=PortDirection.POWER
)
```

### **Bước 4: Tạo Constraints (Optional)**

```python
from app.domains.circuits.entities import Constraint

# Gain constraint
constraint_gain = Constraint(
    name="gain",
    value=20.0,
    unit="dB"
)

# Bandwidth constraint
constraint_bw = Constraint(
    name="bandwidth",
    value=100e3,
    unit="Hz"
)
```

### **Bước 5: Tạo Circuit**

```python
from app.domains.circuits.entities import Circuit

circuit = Circuit(
    name="My Custom Circuit",
    _components={
        "R1": r1,
        "C1": c1,
        "Q1": q1,
        "V1": v1,
        "GND1": gnd
    },
    _nets={
        "VCC": net_vcc,
        "COLLECTOR": net_collector,
        "GND": net_gnd
    },
    _ports={
        "INPUT": port_in,
        "OUTPUT": port_out,
        "VCC": port_vcc
    },
    _constraints={
        "gain": constraint_gain,
        "bandwidth": constraint_bw
    }
)

# Validation tự động được gọi
print(f"✅ Circuit created: {circuit.name}")
```

---

## 3. Validation

### **Validate Circuit**

```python
from app.domains.circuits.rules import (
    CircuitRulesEngine, 
    ViolationSeverity
)

# Tạo engine
engine = CircuitRulesEngine()

# Validate
violations = engine.validate(circuit)

# Phân loại
errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
warnings = [v for v in violations if v.severity == ViolationSeverity.WARNING]
info = [v for v in violations if v.severity == ViolationSeverity.INFO]

# Hiển thị kết quả
print(f"Errors: {len(errors)}")
print(f"Warnings: {len(warnings)}")
print(f"Info: {len(info)}")

if errors:
    print("\n❌ Lỗi nghiêm trọng:")
    for error in errors:
        print(f"  - {error.message}")
        if error.component_id:
            print(f"    Component: {error.component_id}")
        if error.details:
            print(f"    Details: {error.details}")
else:
    print("\n✅ Mạch hợp lệ!")
```

### **Validate và Throw Exception**

```python
# Ném exception nếu có lỗi ERROR
try:
    engine.validate_and_throw(circuit, throw_on_error=True)
    print("✅ Validation passed!")
except ValueError as e:
    print(f"❌ Validation failed: {e}")
```

### **Lấy Summary**

```python
violations = engine.validate(circuit)
summary = engine.get_summary(violations)

print(f"Total violations: {summary['total']}")
print(f"  Errors: {summary['errors']}")
print(f"  Warnings: {summary['warnings']}")
print(f"  Info: {summary['info']}")

print("\nBy rule:")
for rule_name, count in summary['by_rule'].items():
    print(f"  {rule_name}: {count}")

print("\nBy component:")
for comp_id, count in summary['by_component'].items():
    print(f"  {comp_id}: {count}")
```

---

## 4. Serialization

### **Circuit → JSON**

```python
from app.domains.circuits.ir import CircuitIRSerializer
import json

# Serialize
ir_dict = CircuitIRSerializer.serialize(circuit)

# To JSON string
json_str = json.dumps(ir_dict, indent=2)
print(json_str)

# Lưu file
with open("circuit.json", "w", encoding="utf-8") as f:
    f.write(json_str)
```

### **JSON → Circuit**

```python
# Đọc file
with open("circuit.json", "r", encoding="utf-8") as f:
    ir_dict = json.load(f)

# Deserialize
circuit = CircuitIRSerializer.deserialize(ir_dict)

print(f"✅ Loaded circuit: {circuit.name}")
print(f"Components: {len(circuit.components)}")
print(f"Nets: {len(circuit.nets)}")
```

### **Roundtrip Test**

```python
# Kiểm tra dữ liệu không bị mất qua serialize/deserialize
success = CircuitIRSerializer.roundtrip_test(circuit)

if success:
    print("✅ Roundtrip test passed!")
else:
    print("❌ Roundtrip test failed - data loss detected")
```

---

## 5. Thêm Rules Mới

### **Tạo Custom Rule**

```python
from app.domains.circuits.rules import (
    CircuitRule, 
    RuleViolation, 
    ViolationSeverity
)
from app.domains.circuits.entities import Circuit
from typing import List

class MyCustomRule(CircuitRule):
    """
    Rule tùy chỉnh - Kiểm tra điều kiện cụ thể
    """
    
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []
        
        # Ví dụ: Kiểm tra tất cả resistors có giá trị > 0
        for component in circuit.components.values():
            if component.type == ComponentType.RESISTOR:
                resistance = component.parameters.get("resistance")
                if resistance and resistance.value <= 0:
                    violations.append(self._create_violation(
                        message=f"Resistor {component.id} có giá trị không hợp lệ: {resistance.value}",
                        severity=ViolationSeverity.ERROR,
                        component_id=component.id,
                        details={"value": resistance.value}
                    ))
        
        return violations
```

### **Đăng Ký Rule**

```python
from app.domains.circuits.rules import RuleRegistry

# Đăng ký rule
RuleRegistry.register(MyCustomRule())

# Tạo engine với tất cả rules (bao gồm custom)
engine = RuleRegistry.create_engine_with_registered_rules()

# Hoặc thêm vào engine hiện có
engine = CircuitRulesEngine()
engine.rules.append(MyCustomRule())
```

---

## 6. Thêm Template Mới

### **Tạo Config Class**

```python
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class MyCircuitConfig:
    """Config cho custom circuit template"""
    
    # Tham số bắt buộc
    topology: Literal["type_a", "type_b"]
    supply_voltage: float = 12.0
    
    # Tham số optional
    include_protection: bool = True
    custom_value: Optional[float] = None
```

### **Tạo Builder Class**

```python
from app.domains.circuits.entities import (
    Circuit, Component, Net, Port, ComponentType, 
    ParameterValue, PinRef, PortDirection
)

class MyCircuitBuilder:
    """Builder cho custom circuit"""
    
    def __init__(self, config: MyCircuitConfig):
        self.config = config
    
    def build(self) -> Circuit:
        """Xây dựng circuit từ config"""
        
        # 1. Tạo components
        components = self._create_components()
        
        # 2. Tạo nets
        nets = self._create_nets(components)
        
        # 3. Tạo ports
        ports = self._create_ports()
        
        # 4. Tạo constraints
        constraints = self._create_constraints()
        
        # 5. Tạo circuit
        return Circuit(
            name=f"My Circuit - {self.config.topology}",
            _components=components,
            _nets=nets,
            _ports=ports,
            _constraints=constraints
        )
    
    def _create_components(self):
        """Tạo các components"""
        components = {}
        
        # Ví dụ: Tạo resistor
        r1 = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={
                "resistance": ParameterValue(1000, "ohm")
            }
        )
        components["R1"] = r1
        
        # Thêm components khác...
        
        return components
    
    def _create_nets(self, components):
        """Tạo các nets"""
        nets = {}
        
        # Ví dụ: Tạo net
        net_vcc = Net(
            name="VCC",
            connected_pins=(
                PinRef("R1", "1"),
                # Thêm pins khác...
            )
        )
        nets["VCC"] = net_vcc
        
        return nets
    
    def _create_ports(self):
        """Tạo ports"""
        return {}
    
    def _create_constraints(self):
        """Tạo constraints"""
        return {}
```

### **Sử Dụng Builder**

```python
# Tạo config
config = MyCircuitConfig(
    topology="type_a",
    supply_voltage=12.0,
    include_protection=True
)

# Build circuit
builder = MyCircuitBuilder(config)
circuit = builder.build()

# Validate
engine = CircuitRulesEngine()
violations = engine.validate(circuit)

if not any(v.severity == ViolationSeverity.ERROR for v in violations):
    print("✅ Circuit hợp lệ!")
```

---

## 📝 Best Practices

### 1. **Luôn Validate Circuit**
```python
# Sau khi tạo/modify circuit
violations = engine.validate(circuit)
if any(v.severity == ViolationSeverity.ERROR for v in violations):
    raise ValueError("Circuit không hợp lệ")
```

### 2. **Sử Dụng Type Hints**
```python
from app.domains.circuits.entities import Circuit

def process_circuit(circuit: Circuit) -> dict:
    """Type hints giúp catch errors sớm"""
    return circuit.to_dict()
```

### 3. **Immutability**
```python
# ❌ Không được modify trực tiếp
circuit.components["NEW"] = new_component  # TypeError!

# ✅ Tạo circuit mới
new_circuit = circuit.with_component(new_component)
```

### 4. **Error Handling**
```python
try:
    circuit = builder.build()
    violations = engine.validate(circuit)
    
    errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
    if errors:
        raise ValueError(f"Validation errors: {len(errors)}")
        
except ValueError as e:
    print(f"❌ Error: {e}")
    # Handle error...
```

---

## 🔗 Tài Liệu Liên Quan

- [Tổng Quan](tong-quan.md) - Overview hệ thống
- [Kiến Trúc](kien-truc.md) - Chi tiết architecture
- [Hành Động](hanh-dong.md) - Roadmap và tasks

---

*Cập nhật lần cuối: 11/01/2026*
