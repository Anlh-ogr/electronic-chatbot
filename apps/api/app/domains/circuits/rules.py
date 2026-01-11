# rules.py
"""
Circuit Analysis Rules Engine & Validation (Phase 1)

Mục tiêu:
1. Tách business logic ra khỏi entities (TODO comment line)
2. Validate mạch sau khi generate (templates, AI, user input)
3. Phát hiện lỗi thiết kế sớm: kết nối sai, thiếu nguồn, trùng pin, v.v.

Rules Engine = "tư vấn viên điện tử" kiểm tra mạch
Không sửa mạch, chỉ báo lỗi/cảnh báo.
"""

from __future__ import annotations
from typing import List, Dict, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from .entities import (
    Circuit, Component, ComponentType, Net, Port, PortDirection,
    PinRef, Constraint, ParameterValue
)


# ===== RULE VIOLATION =====
class ViolationSeverity(Enum):
    """Mức độ nghiêm trọng của lỗi"""
    ERROR = "error"      # Mạch không hoạt động, phải sửa
    WARNING = "warning"  # Có thể hoạt động nhưng không tối ưu
    INFO = "info"        # Gợi ý cải thiện


@dataclass(frozen=True)
class RuleViolation:
    """Kết quả kiểm tra từ một rule"""
    rule_name: str
    message: str
    severity: ViolationSeverity
    component_id: Optional[str] = None
    net_name: Optional[str] = None
    port_name: Optional[str] = None
    constraint_name: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "message": self.message,
            "severity": self.severity.value,
            "component_id": self.component_id,
            "net_name": self.net_name,
            "port_name": self.port_name,
            "constraint_name": self.constraint_name,
            "details": self.details
        }


# ===== BASE RULE CLASS =====
class CircuitRule:
    """Abstract base cho tất cả rules"""
    
    @property
    def name(self) -> str:
        return self.__class__.__name__
    
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        """Validate circuit, trả về danh sách vi phạm"""
        raise NotImplementedError
    
    def _create_violation(self, 
                         message: str, 
                         severity: ViolationSeverity = ViolationSeverity.ERROR,
                         **kwargs) -> RuleViolation:
        """Helper tạo RuleViolation"""
        return RuleViolation(
            rule_name=self.name,
            message=message,
            severity=severity,
            **kwargs
        )


# ===== BASIC RULES (PHASE 1) =====

class ComponentParameterRule(CircuitRule):
    """
    Rule 1: Kiểm tra tham số bắt buộc của từng loại component
    ĐÃ TÁCH từ __post_init__ của Component
    """
    
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []
        
        for component in circuit.components.values():
            # Kiểm tra theo từng loại component
            if component.type == ComponentType.RESISTOR:
                if "resistance" not in component.parameters:
                    violations.append(self._create_violation(
                        f"Resistor {component.id} phải có tham số 'resistance'",
                        component_id=component.id
                    ))
            
            elif component.type == ComponentType.CAPACITOR:
                if "capacitance" not in component.parameters:
                    violations.append(self._create_violation(
                        f"Capacitor {component.id} phải có tham số 'capacitance'",
                        component_id=component.id
                    ))
            
            elif component.type == ComponentType.INDUCTOR:
                if "inductance" not in component.parameters:
                    violations.append(self._create_violation(
                        f"Inductor {component.id} phải có tham số 'inductance'",
                        component_id=component.id
                    ))
            
            elif component.type == ComponentType.BJT:
                if "model" not in component.parameters:
                    violations.append(self._create_violation(
                        f"BJT {component.id} phải có tham số 'model'",
                        component_id=component.id,
                        severity=ViolationSeverity.WARNING
                    ))
            
            elif component.type == ComponentType.MOSFET:
                if "model" not in component.parameters:
                    violations.append(self._create_violation(
                        f"MOSFET {component.id} phải có tham số 'model'",
                        component_id=component.id,
                        severity=ViolationSeverity.WARNING
                    ))
            
            elif component.type == ComponentType.OPAMP:
                if "model" not in component.parameters:
                    violations.append(self._create_violation(
                        f"OpAmp {component.id} nên có tham số 'model'",
                        component_id=component.id,
                        severity=ViolationSeverity.WARNING
                    ))
            
            elif component.type == ComponentType.VOLTAGE_SOURCE:
                if "voltage" not in component.parameters:
                    violations.append(self._create_violation(
                        f"Voltage source {component.id} phải có tham số 'voltage'",
                        component_id=component.id
                    ))
            
            elif component.type == ComponentType.CURRENT_SOURCE:
                if "current" not in component.parameters:
                    violations.append(self._create_violation(
                        f"Current source {component.id} phải có tham số 'current'",
                        component_id=component.id
                    ))
        
        return violations


class PinConnectionRule(CircuitRule):
    """
    Rule 2: Kiểm tra kết nối pin cơ bản
    1. Tất cả pin phải được kết nối (trừ pin optional)
    2. Pin không được "treo lơ lửng"
    """
    
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []
        
        # Tạo mapping pin -> danh sách nets chứa pin đó
        pin_nets: Dict[Tuple[str, str], List[str]] = {}
        
        for net in circuit.nets.values():
            for pin_ref in net.connected_pins:
                key = (pin_ref.component_id, pin_ref.pin_name)
                if key not in pin_nets:
                    pin_nets[key] = []
                pin_nets[key].append(net.name)
        
        # Kiểm tra từng component
        for component in circuit.components.values():
            for pin_name in component.pins:
                key = (component.id, pin_name)
                
                # Pin không được kết nối = treo lơ lửng
                if key not in pin_nets:
                    # Một số pin có thể được phép không kết nối (VD: NC pin trên IC)
                    if not self._is_optional_pin(component.type, pin_name):
                        violations.append(self._create_violation(
                            f"Pin {component.id}.{pin_name} không được kết nối",
                            component_id=component.id,
                            severity=ViolationSeverity.ERROR,
                            details={"pin": pin_name}
                        ))
                
                # Pin được kết nối đến nhiều nets khác nhau (lỗi thật sự)
                elif len(set(pin_nets[key])) > 1:
                    violations.append(self._create_violation(
                        f"Pin {component.id}.{pin_name} được kết nối đến {len(set(pin_nets[key]))} nets khác nhau: {set(pin_nets[key])}",
                        component_id=component.id,
                        severity=ViolationSeverity.ERROR,
                        details={"pin": pin_name, "nets": list(set(pin_nets[key]))}
                    ))
        
        return violations
    
    def _is_optional_pin(self, comp_type: ComponentType, pin_name: str) -> bool:
        """Xác định pin có bắt buộc phải kết nối không"""
        # Danh sách pin optional cho từng loại component
        optional_pins = {
            ComponentType.OPAMP: ["NC", "OFFSET"],  # No-Connect pins
            ComponentType.BJT: [],  # Tất cả pin BJT đều phải kết nối
            ComponentType.MOSFET: ["BULK"],  # Bulk pin có thể nối substrate
        }
        
        return pin_name in optional_pins.get(comp_type, [])


class GroundReferenceRule(CircuitRule):
    """
    Rule 3: Mạch phải có reference ground
    Ít nhất một net được đánh dấu là GND hoặc có component ground
    """
    
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []
        
        # Tìm component ground
        ground_components = [
            c for c in circuit.components.values()
            if c.type == ComponentType.GROUND
        ]
        
        # Tìm port ground
        ground_ports = [
            p for p in circuit.ports.values()
            if p.direction == PortDirection.GROUND
        ]
        
        # Tìm net có tên GND
        ground_nets = [
            n for n in circuit.nets.values()
            if n.name.upper() in ["GND", "GROUND", "VSS", "0V"]
        ]
        
        # Kiểm tra
        if not ground_components and not ground_ports and not ground_nets:
            violations.append(self._create_violation(
                "Mạch không có điểm ground reference. Cần ít nhất một trong: "
                "component ground, port ground, hoặc net tên GND",
                severity=ViolationSeverity.WARNING
            ))
        
        return violations


class OpAmpPowerRule(CircuitRule):
    """
    Rule 4: OpAmp phải có kết nối nguồn
    ĐÃ TÁCH từ TODO comment trong entities.py
    """
    
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []
        
        # Tìm tất cả OpAmps
        opamps = [
            c for c in circuit.components.values()
            if c.type == ComponentType.OPAMP
        ]
        
        if not opamps:
            return violations  # Không có OpAmp
        
        # Build component→nets mapping một lần (optimization)
        component_nets: Dict[str, List[str]] = {}
        for net in circuit.nets.values():
            for pin_ref in net.connected_pins:
                if pin_ref.component_id not in component_nets:
                    component_nets[pin_ref.component_id] = []
                component_nets[pin_ref.component_id].append(net.name)
        
        # Tìm tất cả power ports
        power_ports = [
            p for p in circuit.ports.values()
            if p.direction in [PortDirection.POWER, PortDirection.GROUND]
        ]
        
        # Tìm voltage sources
        voltage_sources = [
            c for c in circuit.components.values()
            if c.type == ComponentType.VOLTAGE_SOURCE
        ]
        
        for opamp in opamps:
            # Lấy nets kết nối đến opamp (O(1) lookup)
            connected_nets = component_nets.get(opamp.id, [])
            
            # Kiểm tra có power supply không
            has_power_supply = False
            
            # Cách 1: Có power port nào kết nối đến net của opamp không?
            for port in power_ports:
                if port.net_name in connected_nets:
                    has_power_supply = True
                    break
            
            # Cách 2: Có voltage source kết nối đến opamp không?
            if not has_power_supply:
                for vs in voltage_sources:
                    # Lookup nhanh thay vì nested loop
                    vs_nets = component_nets.get(vs.id, [])
                    
                    # Nếu voltage source và opamp có chung net
                    if any(net in connected_nets for net in vs_nets):
                        has_power_supply = True
                        break
            
            if not has_power_supply:
                violations.append(self._create_violation(
                    f"OpAmp {opamp.id} không có kết nối nguồn điện. "
                    "OpAmp cần V+ và V- để hoạt động",
                    component_id=opamp.id,
                    severity=ViolationSeverity.ERROR,
                    details={"connected_nets": connected_nets}
                ))
        
        return violations


class BJTBiasingRule(CircuitRule):
    """
    Rule 5: BJT cần có phân cực đúng
    Phase 1: Kiểm tra cơ bản
    Phase 2: Có thể kiểm tra VCE, IB, IC
    """
    
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []
        
        bjts = [
            c for c in circuit.components.values()
            if c.type == ComponentType.BJT
        ]
        
        for bjt in bjts:
            # Tìm net kết nối đến base của BJT
            base_net = None
            for net in circuit.nets.values():
                for pin_ref in net.connected_pins:
                    if pin_ref.component_id == bjt.id and pin_ref.pin_name == "B":
                        base_net = net
                        break
                if base_net:  # ✅ Break outer loop sau khi tìm thấy
                    break
            
            # Kiểm tra có base resistor không (cho CE amplifier)
            base_resistors = []
            if base_net:
                # Tìm resistor kết nối đến base net
                for pin_ref in base_net.connected_pins:
                    comp = circuit.get_component(pin_ref.component_id)
                    if comp and comp.type == ComponentType.RESISTOR:
                        base_resistors.append(comp.id)
            
            if not base_resistors:
                violations.append(self._create_violation(
                    f"BJT {bjt.id} không có base resistor. "
                    "Cần có resistor để hạn dòng base",
                    component_id=bjt.id,
                    severity=ViolationSeverity.WARNING
                ))
        
        return violations


class NetSingleConnectionRule(CircuitRule):
    """
    Rule 6: Net chỉ có 1 connection là nghi ngờ
    (trừ net là port output hoặc test point)
    """
    
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []
        
        for net_name, net in circuit.nets.items():
            if len(net.connected_pins) == 1:
                # Kiểm tra xem net có phải là port không
                is_port = any(
                    p.net_name == net_name 
                    for p in circuit.ports.values()
                )
                
                if not is_port:
                    violations.append(self._create_violation(
                        f"Net '{net_name}' chỉ có 1 kết nối. "
                        "Có thể là lỗi thiết kế (dây treo)",
                        net_name=net_name,
                        severity=ViolationSeverity.WARNING,
                        details={"connected_pins": [
                            (ref.component_id, ref.pin_name) 
                            for ref in net.connected_pins
                        ]}
                    ))
        
        return violations


class ConstraintFeasibilityRule(CircuitRule):
    """
    Rule 7: Kiểm tra constraint có hợp lý không
    Phase 1: Kiểm tra cơ bản (giá trị âm, quá lớn, v.v.)
    """
    
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []
        
        for constraint in circuit.constraints.values():
            # Kiểm tra giá trị
            if isinstance(constraint.value, (int, float)):
                # 1. Không âm cho một số constraint
                non_negative_constraints = [
                    # NOTE: "gain" can be negative for inverting amplifiers (phase inversion)
                    "bandwidth", "supply_voltage", 
                    "current", "power", "resistance", "capacitance"
                ]
                
                if constraint.name in non_negative_constraints and constraint.value < 0:
                    violations.append(self._create_violation(
                        f"Constraint '{constraint.name}' có giá trị âm: {constraint.value}",
                        constraint_name=constraint.name,
                        severity=ViolationSeverity.ERROR,
                        details={"value": constraint.value}
                    ))
                
                # 2. Giá trị quá lớn/cực đoan
                if constraint.name == "gain" and abs(constraint.value) > 1000:
                    violations.append(self._create_violation(
                        f"Gain quá lớn ({constraint.value}). "
                        "Gain thực tế thường dưới 1000",
                        constraint_name=constraint.name,
                        severity=ViolationSeverity.WARNING,
                        details={"value": constraint.value}
                    ))
                
                if constraint.name == "supply_voltage" and constraint.value > 1000:
                    violations.append(self._create_violation(
                        f"Điện áp nguồn quá lớn ({constraint.value}V). "
                        "Kiểm tra đơn vị (mV/V)",
                        constraint_name=constraint.name,
                        severity=ViolationSeverity.WARNING,
                        details={"value": constraint.value}
                    ))
        
        return violations


class PortDirectionRule(CircuitRule):
    """
    Rule 8: Kiểm tra hướng port có hợp lý không
    VD: INPUT không thể kết nối trực tiếp đến GND
    """
    
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []
        
        for port in circuit.ports.values():
            if port.direction == PortDirection.INPUT:
                # Tìm net của port
                net = circuit.get_net(port.net_name)
                if net:
                    # Kiểm tra net này có kết nối đến ground không
                    for pin_ref in net.connected_pins:
                        comp = circuit.get_component(pin_ref.component_id)
                        if comp and comp.type == ComponentType.GROUND:
                            violations.append(self._create_violation(
                                f"Port input '{port.name}' kết nối trực tiếp đến ground. "
                                "Input sẽ bị short circuit",
                                port_name=port.name,
                                net_name=port.net_name,
                                severity=ViolationSeverity.ERROR
                            ))
                            break
            
            elif port.direction == PortDirection.OUTPUT:
                # Output không nên treo lơ lửng
                net = circuit.get_net(port.net_name)
                if net and len(net.connected_pins) <= 2:
                    # Output chỉ có 1-2 kết nối có thể là vấn đề
                    pass  # Phase 2 sẽ kiểm tra chi tiết hơn
        
        return violations


class ComponentUniqueIdRule(CircuitRule):
    """
    Rule 9: Kiểm tra ID component không trùng
    (Đã có trong Circuit.validate_basic nhưng thêm rule cho rõ)
    """
    
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []
        
        seen_ids = set()
        for comp_id, component in circuit.components.items():
            if comp_id in seen_ids:
                violations.append(self._create_violation(
                    f"Component ID '{comp_id}' bị trùng lặp",
                    component_id=comp_id,
                    severity=ViolationSeverity.ERROR
                ))
            seen_ids.add(comp_id)
        
        return violations


class CircuitTopologyRule(CircuitRule):
    """
    Rule 10: Kiểm tra topology cơ bản
    VD: Mạch khuếch đại phải có ít nhất 1 active component
    """
    
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []
        
        # Đếm active components
        active_components = [
            c for c in circuit.components.values()
            if c.type in [
                ComponentType.BJT, ComponentType.MOSFET, 
                ComponentType.OPAMP, ComponentType.DIODE
            ]
        ]
        
        # Kiểm tra nếu có constraint "gain" nhưng không có active component
        has_gain_constraint = any(
            c.name.lower() == "gain" 
            for c in circuit.constraints.values()
        )
        
        if has_gain_constraint and not active_components:
            violations.append(self._create_violation(
                "Mạch có constraint gain nhưng không có active component "
                "(BJT, MOSFET, OpAmp, Diode). Không thể khuếch đại",
                severity=ViolationSeverity.ERROR
            ))
        
        # Kiểm tra mạch lọc phải có ít nhất R, L, hoặc C
        has_filter_constraint = any(
            "filter" in c.name.lower() or "frequency" in c.name.lower()
            for c in circuit.constraints.values()
        )
        
        if has_filter_constraint:
            has_passive = any(
                c.type in [ComponentType.RESISTOR, ComponentType.CAPACITOR, ComponentType.INDUCTOR]
                for c in circuit.components.values()
            )
            
            if not has_passive:
                violations.append(self._create_violation(
                    "Mạch có constraint filter nhưng không có linh kiện thụ động "
                    "(R, L, C). Không thể lọc tín hiệu",
                    severity=ViolationSeverity.ERROR
                ))
        
        return violations


# ===== RULES ENGINE =====
class CircuitRulesEngine:
    """
    Rules Engine chính - chạy tất cả rules trên một Circuit
    """
    
    def __init__(self, rules: Optional[List[CircuitRule]] = None):
        """Khởi tạo với danh sách rules mặc định hoặc tùy chỉnh"""
        if rules is None:
            self.rules = self._get_default_rules()
        else:
            self.rules = rules
    
    def _get_default_rules(self) -> List[CircuitRule]:
        """Danh sách rules mặc định cho Phase 1"""
        return [
            ComponentParameterRule(),
            PinConnectionRule(),
            GroundReferenceRule(),
            OpAmpPowerRule(),  # QUAN TRỌNG: Đã tách từ entities
            BJTBiasingRule(),
            NetSingleConnectionRule(),
            ConstraintFeasibilityRule(),
            PortDirectionRule(),
            ComponentUniqueIdRule(),
            CircuitTopologyRule(),
        ]
    
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        """
        Chạy tất cả rules trên circuit
        Trả về danh sách vi phạm đã sắp xếp (ERROR trước, WARNING sau)
        """
        all_violations = []
        
        for rule in self.rules:
            try:
                violations = rule.validate(circuit)
                all_violations.extend(violations)
            except Exception as e:
                # Nếu rule bị lỗi, tạo violation đặc biệt
                error_violation = RuleViolation(
                    rule_name="RulesEngine",
                    message=f"Rule '{rule.name}' gặp lỗi khi chạy: {str(e)}",
                    severity=ViolationSeverity.ERROR
                )
                all_violations.append(error_violation)
        
        # Sắp xếp: ERROR -> WARNING -> INFO
        severity_order = {
            ViolationSeverity.ERROR: 0,
            ViolationSeverity.WARNING: 1,
            ViolationSeverity.INFO: 2
        }
        
        return sorted(
            all_violations,
            key=lambda v: (severity_order[v.severity], v.rule_name)
        )
    
    def validate_and_throw(self, circuit: Circuit, throw_on_error: bool = True) -> bool:
        """
        Validate circuit và ném exception nếu có lỗi ERROR
        Trả về True nếu chỉ có WARNING/INFO, False nếu có ERROR
        """
        violations = self.validate(circuit)
        
        # Lọc chỉ lỗi ERROR
        errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
        
        if errors and throw_on_error:
            error_messages = "\n".join([f"- {v.message}" for v in errors[:3]])  # Hiển thị 3 lỗi đầu
            raise ValueError(
                f"Circuit validation failed with {len(errors)} errors:\n{error_messages}"
            )
        
        return len(errors) == 0
    
    def get_summary(self, violations: List[RuleViolation]) -> Dict[str, Any]:
        """Tóm tắt kết quả validation"""
        summary = {
            "total": len(violations),
            "errors": len([v for v in violations if v.severity == ViolationSeverity.ERROR]),
            "warnings": len([v for v in violations if v.severity == ViolationSeverity.WARNING]),
            "info": len([v for v in violations if v.severity == ViolationSeverity.INFO]),
            "by_rule": {},
            "by_component": {},
        }
        
        # Nhóm theo rule
        for v in violations:
            summary["by_rule"][v.rule_name] = summary["by_rule"].get(v.rule_name, 0) + 1
            
            if v.component_id:
                summary["by_component"][v.component_id] = summary["by_component"].get(v.component_id, 0) + 1
        
        return summary


# ===== VALIDATION HELPERS =====
def validate_circuit(circuit: Circuit) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Helper function để validate circuit (cho các layer trên dùng)
    
    Returns:
        Tuple[is_valid, violations_dict]
        is_valid = True nếu không có ERROR (chỉ có WARNING/INFO)
    """
    engine = CircuitRulesEngine()
    violations = engine.validate(circuit)
    
    # Chuyển violations sang dict
    violations_dict = [v.to_dict() for v in violations]
    
    # Kiểm tra có ERROR không
    has_error = any(v.severity == ViolationSeverity.ERROR for v in violations)
    
    return (not has_error, violations_dict)


def validate_circuit_with_summary(circuit: Circuit) -> Dict[str, Any]:
    """Validate và trả về summary chi tiết"""
    engine = CircuitRulesEngine()
    violations = engine.validate(circuit)
    summary = engine.get_summary(violations)
    
    return {
        "is_valid": summary["errors"] == 0,
        "summary": summary,
        "violations": [v.to_dict() for v in violations]
    }


# ===== RULE REGISTRY (cho extensibility) =====
class RuleRegistry:
    """Registry để đăng ký rules custom (cho phase 2)"""
    
    _rules: Dict[str, CircuitRule] = {}
    
    @classmethod
    def register(cls, rule: CircuitRule) -> None:
        """Đăng ký rule mới"""
        cls._rules[rule.name] = rule
    
    @classmethod
    def get_rule(cls, name: str) -> Optional[CircuitRule]:
        """Lấy rule theo tên"""
        return cls._rules.get(name)
    
    @classmethod
    def get_all_rules(cls) -> List[CircuitRule]:
        """Lấy tất cả rules đã đăng ký"""
        return list(cls._rules.values())
    
    @classmethod
    def create_engine_with_registered_rules(cls) -> CircuitRulesEngine:
        """Tạo engine với tất cả rules đã đăng ký"""
        return CircuitRulesEngine(rules=cls.get_all_rules())


# ===== TEST UTILITIES =====
def create_test_circuit() -> Circuit:
    """Tạo test circuit để kiểm tra rules"""
    # Tạo một mạch có lỗi cố ý để test rules
    q1 = Component(
        id="Q1",
        type=ComponentType.BJT,
        pins=("C", "B", "E"),
        parameters={"model": ParameterValue("2N2222", None)}
    )
    
    r1 = Component(
        id="R1",
        type=ComponentType.RESISTOR,
        pins=("1", "2"),
        parameters={"resistance": ParameterValue(1000, "ohm")}
    )
    
    net_vcc = Net(
        name="VCC",
        connected_pins=(PinRef("R1", "1"),)
    )
    
    return Circuit(
        name="Test Circuit",
        _components={"Q1": q1, "R1": r1},
        _nets={"VCC": net_vcc},
        _ports={},
        _constraints={}
    )


# Example usage khi import module
if __name__ == "__main__":
    # Test với circuit mẫu
    test_circuit = create_test_circuit()
    engine = CircuitRulesEngine()
    
    print(f"Validating circuit: {test_circuit.name}")
    violations = engine.validate(test_circuit)
    summary = engine.get_summary(violations)
    
    print(f"\nSummary: {summary['errors']} errors, {summary['warnings']} warnings")
    
    for v in violations:
        print(f"\n[{v.severity.value.upper()}] {v.rule_name}: {v.message}")
        if v.component_id:
            print(f"  Component: {v.component_id}")