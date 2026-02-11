# .\thesis\electronic-chatbot\apps\api\app\domains\circuits\rules.py
""" Circuit Rules Engine & Validation
Thiết kế hệ thống theo kiến trúc Domain-Driven Design (DDD), đặt domain (nghiệp vụ) là cốt lõi trung tâm.
Tuyệt đối không được chứa AI Logic, KiCad Logic, UI Logic — chỉ chứa logic kiểm tra nghiệp vụ mạch.

Mục tiêu:
1. Tách business logic ra khỏi entities (không validate hết ở __post_init__).
2. Validate mạch sau khi generate (templates, AI, user input).
3. Phát hiện lỗi thiết kế sớm: kết nối sai, thiếu nguồn, trùng pin, v.v.

Rules Engine = "tư vấn viên điện tử" kiểm tra mạch — không sửa mạch, chỉ báo lỗi/cảnh báo.

Kiến trúc tổng quan:
 * ViolationSeverity (enum): ERROR / WARNING / INFO.
 * RuleViolation (frozen dataclass): kết quả vi phạm từ mỗi rule.
 * CircuitRule (abstract base): interface cho tất cả rules.
 * 15 rules cụ thể (Phase 1 + Phase 2): kiểm tra tham số, kết nối, bias, power rating, v.v.
 * CircuitRulesEngine: orchestrator chạy tất cả rules, sắp xếp kết quả.
 * RuleRegistry: extensibility — đăng ký rules tùy chỉnh.
 * Helper functions: validate_circuit(), validate_circuit_with_summary().
"""

# todo : mở rộng AI/LLM : Tích hợp AI/LLM cho tự động phân tích rules, gợi ý sửa lỗi.


from __future__ import annotations
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from .entities import (
    Circuit, Component, ComponentType, Net, Port, PortDirection,
    PinRef, Constraint, ParameterValue
)

""" Lý do sử dụng thư viện:
__future__: hỗ trợ forward references (kiểu dữ liệu tham chiếu chéo).
typing: cung cấp type hints cho biến (Dict, List, Optional, Tuple, Any).
dataclasses: dùng frozen=True cho RuleViolation để đảm bảo bất biến.
enum: định nghĩa hằng số ViolationSeverity (ERROR, WARNING, INFO).
.entities: nhập các lớp domain (Circuit, Component, ComponentType, ...) để kiểm tra mạch.
"""



# ====== ENUMS ======
""" Mức độ nghiêm trọng của vi phạm
 ERROR : mạch không hoạt động, phải sửa
 WARNING : có thể hoạt động nhưng không tối ưu
 INFO : gợi ý cải thiện
"""
class ViolationSeverity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"



# ====== VALUE OBJECTS ======
""" Kết quả kiểm tra từ một rule.
Đại diện cho một vi phạm/cảnh báo/gợi ý khi kiểm tra mạch.
Đảm bảo bất biến (frozen=True) — không sửa được sau khi tạo.
Args:
 * rule_name (str): tên rule tạo ra vi phạm.
 * message (str): thông điệp mô tả vi phạm.
 * severity (ViolationSeverity): mức độ nghiêm trọng.
 * component_id (Optional[str]): ID linh kiện liên quan.
 * net_name (Optional[str]): tên net liên quan.
 * port_name (Optional[str]): tên port liên quan.
 * constraint_name (Optional[str]): tên constraint liên quan.
 * details (Dict): thông tin chi tiết bổ sung.
"""
@dataclass(frozen=True)
class RuleViolation:
    rule_name: str
    message: str
    severity: ViolationSeverity
    component_id: Optional[str] = None
    net_name: Optional[str] = None
    port_name: Optional[str] = None
    constraint_name: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    # chuyển obj -> dict (API)
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



# ====== BASE RULE ======
""" Lớp cơ sở trừu tượng cho tất cả rules.
Mỗi rule kế thừa CircuitRule phải implement validate().
Cung cấp helper _create_violation() để giảm boilerplate.
"""
class CircuitRule:
    # tên rule, lấy từ tên class
    @property
    def name(self) -> str:
        return self.__class__.__name__

    # validate mạch, trả về danh sách vi phạm — abstract method
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        raise NotImplementedError

    # helper tạo RuleViolation nhanh với rule_name tự động
    def _create_violation(self,
                         message: str,
                         severity: ViolationSeverity = ViolationSeverity.ERROR,
                         **kwargs) -> RuleViolation:
        return RuleViolation(
            rule_name=self.name,
            message=message,
            severity=severity,
            **kwargs
        )



# ====== PHASE 1 RULES ======

""" Rule 1: Kiểm tra tham số bắt buộc của từng loại component.
ĐÃ TÁCH từ __post_init__ của Component (entities.py).
Dùng bảng _REQUIRED_PARAMS (table-driven) thay vì if/elif lặp lại.
Logic:
 - Passive (R, C, L): phải có tham số resistance/capacitance/inductance → ERROR.
 - Active (BJT, MOSFET, OpAmp): nên có model → WARNING.
 - Source (V, I): phải có voltage/current → ERROR.
"""
class ComponentParameterRule(CircuitRule):
    # Bảng tra cứu: component_type → (tên tham số bắt buộc, severity)
    _REQUIRED_PARAMS: Dict[ComponentType, Tuple[str, ViolationSeverity]] = {
        ComponentType.RESISTOR:       ("resistance",  ViolationSeverity.ERROR),
        ComponentType.CAPACITOR:      ("capacitance", ViolationSeverity.ERROR),
        ComponentType.INDUCTOR:       ("inductance",  ViolationSeverity.ERROR),
        ComponentType.BJT:            ("model",       ViolationSeverity.WARNING),
        ComponentType.MOSFET:         ("model",       ViolationSeverity.WARNING),
        ComponentType.OPAMP:          ("model",       ViolationSeverity.WARNING),
        ComponentType.VOLTAGE_SOURCE: ("voltage",     ViolationSeverity.ERROR),
        ComponentType.CURRENT_SOURCE: ("current",     ViolationSeverity.ERROR),
    }

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        for component in circuit.components.values():
            entry = self._REQUIRED_PARAMS.get(component.type)
            if entry is None:
                continue

            param_name, severity = entry
            if param_name not in component.parameters:
                violations.append(self._create_violation(
                    f"{component.type.value.upper()} {component.id} phải có tham số '{param_name}'",
                    component_id=component.id,
                    severity=severity
                ))

        return violations


""" Rule 2: Kiểm tra kết nối pin cơ bản.
 1. Tất cả pin phải được kết nối (trừ pin optional).
 2. Pin không được "treo lơ lửng".
 3. Pin không được kết nối đến nhiều nets khác nhau.
"""
class PinConnectionRule(CircuitRule):
    # Danh sách pin optional theo component type (không bắt buộc kết nối)
    _OPTIONAL_PINS: Dict[ComponentType, List[str]] = {
        ComponentType.OPAMP:  ["NC", "OFFSET"],
        ComponentType.BJT:    [],
        ComponentType.MOSFET: ["BULK"],
    }

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        # Tạo mapping pin → danh sách nets chứa pin đó
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
                    optional = self._OPTIONAL_PINS.get(component.type, [])
                    if pin_name not in optional:
                        violations.append(self._create_violation(
                            f"Pin {component.id}.{pin_name} không được kết nối",
                            component_id=component.id,
                            severity=ViolationSeverity.ERROR,
                            details={"pin": pin_name}
                        ))

                # Pin được kết nối đến nhiều nets khác nhau (lỗi thật sự)
                elif len(set(pin_nets[key])) > 1:
                    violations.append(self._create_violation(
                        f"Pin {component.id}.{pin_name} được kết nối đến "
                        f"{len(set(pin_nets[key]))} nets khác nhau: {set(pin_nets[key])}",
                        component_id=component.id,
                        severity=ViolationSeverity.ERROR,
                        details={"pin": pin_name, "nets": list(set(pin_nets[key]))}
                    ))

        return violations


""" Rule 3: Mạch phải có reference ground.
Ít nhất một trong: component ground, port ground, hoặc net tên GND.
"""
class GroundReferenceRule(CircuitRule):
    # Tên net hợp lệ cho ground reference
    _GND_NET_NAMES = {"GND", "GROUND", "VSS", "0V"}

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        # Tìm component ground
        has_ground_comp = any(
            c.type == ComponentType.GROUND
            for c in circuit.components.values()
        )

        # Tìm port ground
        has_ground_port = any(
            p.direction == PortDirection.GROUND
            for p in circuit.ports.values()
        )

        # Tìm net có tên GND
        has_ground_net = any(
            n.name.upper() in self._GND_NET_NAMES
            for n in circuit.nets.values()
        )

        if not has_ground_comp and not has_ground_port and not has_ground_net:
            violations.append(self._create_violation(
                "Mạch không có điểm ground reference. Cần ít nhất một trong: "
                "component ground, port ground, hoặc net tên GND",
                severity=ViolationSeverity.WARNING
            ))

        return violations


""" Rule 4: OpAmp phải có kết nối nguồn (V+ và V-).
ĐÃ TÁCH từ TODO comment trong entities.py.
Kiểm tra: power port hoặc voltage source kết nối đến OpAmp.
"""
class OpAmpPowerRule(CircuitRule):

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        # Tìm tất cả OpAmps
        opamps = [
            c for c in circuit.components.values()
            if c.type == ComponentType.OPAMP
        ]

        if not opamps:
            return violations

        # Build component → nets mapping một lần (O(1) lookup)
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
            connected_nets = component_nets.get(opamp.id, [])
            has_power_supply = False

            # Cách 1: power port kết nối đến net của opamp
            for port in power_ports:
                if port.net_name in connected_nets:
                    has_power_supply = True
                    break

            # Cách 2: voltage source kết nối đến opamp (shared net)
            if not has_power_supply:
                for vs in voltage_sources:
                    vs_nets = component_nets.get(vs.id, [])
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


""" Rule 5: BJT cần có phân cực đúng.
Kiểm tra cơ bản: base phải có resistor kết nối (voltage divider hoặc fixed bias).
"""
class BJTBiasingRule(CircuitRule):

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        bjts = [
            c for c in circuit.components.values()
            if c.type == ComponentType.BJT
        ]

        for bjt in bjts:
            # Tìm net kết nối đến base của BJT
            base_net = self._find_pin_net(circuit, bjt.id, "B")

            # Kiểm tra có base resistor không
            base_resistors = []
            if base_net:
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

    # tìm net kết nối đến pin cụ thể của component
    @staticmethod
    def _find_pin_net(circuit: Circuit, comp_id: str, pin_name: str) -> Optional[Net]:
        for net in circuit.nets.values():
            for pin_ref in net.connected_pins:
                if pin_ref.component_id == comp_id and pin_ref.pin_name == pin_name:
                    return net
        return None


""" Rule 6: Net chỉ có 1 connection là nghi ngờ (dây treo).
Trừ net là port output hoặc test point.
"""
class NetSingleConnectionRule(CircuitRule):

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        for net_name, net in circuit.nets.items():
            if len(net.connected_pins) == 1:
                # Net là port → cho phép 1 connection
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


""" Rule 7: Kiểm tra constraint có hợp lý không.
 - Một số constraint không được âm (bandwidth, resistance, ...).
 - Giá trị cực đoan: gain > 1000, supply_voltage > 1000V.
 - NOTE: gain có thể âm (inverting amplifier — đảo pha).
"""
class ConstraintFeasibilityRule(CircuitRule):
    # Danh sách constraint không được âm
    _NON_NEGATIVE = {
        "bandwidth", "supply_voltage",
        "current", "power", "resistance", "capacitance"
    }

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        for constraint in circuit.constraints.values():
            if not isinstance(constraint.value, (int, float)):
                continue

            # 1. Không âm cho tập constraint xác định
            if constraint.name in self._NON_NEGATIVE and constraint.value < 0:
                violations.append(self._create_violation(
                    f"Constraint '{constraint.name}' có giá trị âm: {constraint.value}",
                    constraint_name=constraint.name,
                    severity=ViolationSeverity.ERROR,
                    details={"value": constraint.value}
                ))

            # 2. Gain quá lớn
            if constraint.name == "gain" and abs(constraint.value) > 1000:
                violations.append(self._create_violation(
                    f"Gain quá lớn ({constraint.value}). "
                    "Gain thực tế thường dưới 1000",
                    constraint_name=constraint.name,
                    severity=ViolationSeverity.WARNING,
                    details={"value": constraint.value}
                ))

            # 3. Điện áp nguồn quá lớn
            if constraint.name == "supply_voltage" and constraint.value > 1000:
                violations.append(self._create_violation(
                    f"Điện áp nguồn quá lớn ({constraint.value}V). "
                    "Kiểm tra đơn vị (mV/V)",
                    constraint_name=constraint.name,
                    severity=ViolationSeverity.WARNING,
                    details={"value": constraint.value}
                ))

        return violations


""" Rule 8: Kiểm tra hướng port có hợp lý không.
 - INPUT không thể kết nối trực tiếp đến GND (short circuit).
 - OUTPUT treo lơ lửng → cảnh báo (phase 2).
"""
class PortDirectionRule(CircuitRule):

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        for port in circuit.ports.values():
            if port.direction == PortDirection.INPUT:
                net = circuit.get_net(port.net_name)
                if net:
                    # Input kết nối trực tiếp đến ground → short circuit
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
                # Output treo lơ lửng — phase 2 sẽ kiểm tra chi tiết hơn
                pass

        return violations


""" Rule 9: Kiểm tra ID component không trùng.
Đã có trong Circuit.validate_basic nhưng thêm rule cho defense-in-depth.
"""
class ComponentUniqueIdRule(CircuitRule):

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        seen_ids: set = set()
        for comp_id in circuit.components:
            if comp_id in seen_ids:
                violations.append(self._create_violation(
                    f"Component ID '{comp_id}' bị trùng lặp",
                    component_id=comp_id,
                    severity=ViolationSeverity.ERROR
                ))
            seen_ids.add(comp_id)

        return violations


""" Rule 10: Kiểm tra topology cơ bản.
 - Mạch có constraint gain nhưng không có active component → lỗi.
 - Mạch có constraint filter nhưng không có linh kiện thụ động → lỗi.
"""
class CircuitTopologyRule(CircuitRule):
    # Nhóm active component types
    _ACTIVE_TYPES = {
        ComponentType.BJT, ComponentType.MOSFET,
        ComponentType.OPAMP, ComponentType.DIODE
    }

    # Nhóm passive component types
    _PASSIVE_TYPES = {
        ComponentType.RESISTOR, ComponentType.CAPACITOR, ComponentType.INDUCTOR
    }

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        # Đếm active components
        has_active = any(
            c.type in self._ACTIVE_TYPES
            for c in circuit.components.values()
        )

        # Kiểm tra gain constraint mà không có active component
        has_gain = any(
            c.name.lower() == "gain"
            for c in circuit.constraints.values()
        )

        if has_gain and not has_active:
            violations.append(self._create_violation(
                "Mạch có constraint gain nhưng không có active component "
                "(BJT, MOSFET, OpAmp, Diode). Không thể khuếch đại",
                severity=ViolationSeverity.ERROR
            ))

        # Kiểm tra filter constraint mà không có passive component
        has_filter = any(
            "filter" in c.name.lower() or "frequency" in c.name.lower()
            for c in circuit.constraints.values()
        )

        if has_filter:
            has_passive = any(
                c.type in self._PASSIVE_TYPES
                for c in circuit.components.values()
            )

            if not has_passive:
                violations.append(self._create_violation(
                    "Mạch có constraint filter nhưng không có linh kiện thụ động "
                    "(R, L, C). Không thể lọc tín hiệu",
                    severity=ViolationSeverity.ERROR
                ))

        return violations



# ====== PHASE 2 RULES ======

""" Rule 11: Kiểm tra power rating của linh kiện.
Ước lượng công suất: P = V²/R hoặc P = I²·R.
Nếu vượt power_rating → ERROR.
"""
class PowerRatingRule(CircuitRule):

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        for comp in circuit.components.values():
            params = comp.parameters
            power_rating = params.get("power_rating")
            if power_rating is None:
                continue

            max_watts = self._extract_value(power_rating)
            if not isinstance(max_watts, (int, float)) or max_watts <= 0:
                continue

            # Ước lượng công suất nếu có voltage / current / resistance
            r_val = self._extract_value(params.get("resistance"))
            v_val = self._extract_value(params.get("voltage"))
            i_val = self._extract_value(params.get("current"))

            estimated_power: Optional[float] = None

            if isinstance(r_val, (int, float)) and r_val > 0:
                if isinstance(v_val, (int, float)):
                    estimated_power = v_val ** 2 / r_val      # P = V²/R
                elif isinstance(i_val, (int, float)):
                    estimated_power = i_val ** 2 * r_val      # P = I²·R

            if estimated_power is not None and estimated_power > max_watts:
                violations.append(self._create_violation(
                    f"Component {comp.id}: công suất ước tính {estimated_power:.3f}W "
                    f"vượt power_rating {max_watts}W",
                    component_id=comp.id,
                    severity=ViolationSeverity.ERROR,
                    details={
                        "estimated_power": estimated_power,
                        "max_power": max_watts,
                    },
                ))

        return violations

    # trích xuất giá trị float từ ParameterValue hoặc raw value
    @staticmethod
    def _extract_value(param: Any) -> Any:
        if param is None:
            return None
        return param.value if isinstance(param, ParameterValue) else param


""" Rule 12: Kiểm tra voltage rating của tụ / linh kiện.
Tụ có voltage_rating thấp hơn supply voltage → ERROR.
"""
class VoltageRatingRule(CircuitRule):

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        # Tìm Vmax trong mạch (từ voltage source hoặc constraint)
        supply_voltage = self._find_supply_voltage(circuit)
        if supply_voltage is None:
            return violations

        for comp in circuit.components.values():
            vr = comp.parameters.get("voltage_rating")
            if vr is None:
                continue
            rating = vr.value if isinstance(vr, ParameterValue) else vr
            if isinstance(rating, (int, float)) and supply_voltage > rating:
                violations.append(self._create_violation(
                    f"Component {comp.id}: voltage_rating ({rating}V) "
                    f"thấp hơn supply voltage ({supply_voltage}V)",
                    component_id=comp.id,
                    severity=ViolationSeverity.ERROR,
                    details={
                        "voltage_rating": rating,
                        "supply_voltage": supply_voltage,
                    },
                ))

        return violations

    # tìm supply voltage lớn nhất từ voltage source hoặc constraint
    @staticmethod
    def _find_supply_voltage(circuit: Circuit) -> Optional[float]:
        supply_voltage: Optional[float] = None

        # Từ voltage source component
        for comp in circuit.components.values():
            if comp.type == ComponentType.VOLTAGE_SOURCE:
                v = comp.parameters.get("voltage")
                val = v.value if isinstance(v, ParameterValue) else v
                if isinstance(val, (int, float)):
                    if supply_voltage is None or abs(val) > abs(supply_voltage):
                        supply_voltage = abs(val)

        # Từ constraint (vcc, vdd, supply_voltage)
        for con in circuit.constraints.values():
            if con.name in ("supply_voltage", "vcc", "vdd"):
                v = con.value
                if isinstance(v, (int, float)):
                    if supply_voltage is None or abs(v) > abs(supply_voltage):
                        supply_voltage = abs(v)

        return supply_voltage


""" Rule 13: MOSFET cần có phân cực gate.
Tương tự BJTBiasingRule nhưng cho MOSFET (gate → bias divider hoặc resistor).
"""
class MOSFETBiasRule(CircuitRule):

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        mosfets = [
            c for c in circuit.components.values()
            if c.type == ComponentType.MOSFET
        ]

        for mos in mosfets:
            # Tìm net kết nối đến gate
            gate_net = BJTBiasingRule._find_pin_net(circuit, mos.id, "G")

            # Kiểm tra có gate resistor không
            gate_resistors = []
            if gate_net:
                for pin_ref in gate_net.connected_pins:
                    comp = circuit.get_component(pin_ref.component_id)
                    if comp and comp.type == ComponentType.RESISTOR:
                        gate_resistors.append(comp.id)

            if not gate_resistors:
                violations.append(self._create_violation(
                    f"MOSFET {mos.id} không có gate bias resistor. "
                    "Gate cần được phân cực qua resistor để điều khiển VGS",
                    component_id=mos.id,
                    severity=ViolationSeverity.WARNING,
                ))

        return violations


""" Rule 14: Kiểm tra structured constraints (min_value, max_value, target).
 - min_value phải ≤ max_value.
 - target phải tham chiếu đến component/net tồn tại (nếu có).
"""
class StructuredConstraintRule(CircuitRule):

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        for con in circuit.constraints.values():
            # min ≤ max
            if (
                con.min_value is not None
                and con.max_value is not None
                and con.min_value > con.max_value
            ):
                violations.append(self._create_violation(
                    f"Constraint '{con.name}': min_value ({con.min_value}) > "
                    f"max_value ({con.max_value})",
                    constraint_name=con.name,
                    severity=ViolationSeverity.ERROR,
                    details={
                        "min_value": con.min_value,
                        "max_value": con.max_value,
                    },
                ))

            # target phải tồn tại
            if con.target:
                exists_comp = circuit.get_component(con.target) is not None
                exists_net = circuit.get_net(con.target) is not None
                if not exists_comp and not exists_net:
                    violations.append(self._create_violation(
                        f"Constraint '{con.name}' tham chiếu target '{con.target}' "
                        "không tồn tại trong mạch",
                        constraint_name=con.name,
                        severity=ViolationSeverity.WARNING,
                        details={"target": con.target},
                    ))

        return violations


""" Rule 15: Kiểm tra parametric section khớp với components thực tế.
Nếu circuit.parametric chứa component_id không tồn tại → cảnh báo INFO.
"""
class ParametricConsistencyRule(CircuitRule):

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        parametric = getattr(circuit, "parametric", None)
        if not parametric:
            return violations

        # Key ngoại lệ — không phải component_id
        _META_KEYS = {"note", "description", "defaults"}

        for key in parametric:
            if circuit.get_component(key) is None and key not in _META_KEYS:
                violations.append(self._create_violation(
                    f"Parametric key '{key}' không tìm thấy component "
                    "tương ứng trong mạch",
                    severity=ViolationSeverity.INFO,
                    details={"parametric_key": key},
                ))

        return violations



# ====== RULES ENGINE ======
""" Rules Engine chính — orchestrator chạy tất cả rules trên một Circuit.
Cung cấp:
 - validate(): chạy tất cả rules, trả về danh sách vi phạm đã sắp xếp.
 - validate_and_throw(): validate + ném exception nếu có ERROR.
 - get_summary(): tóm tắt kết quả validation.
"""
class CircuitRulesEngine:

    # Thứ tự sắp xếp vi phạm: ERROR → WARNING → INFO
    _SEVERITY_ORDER = {
        ViolationSeverity.ERROR: 0,
        ViolationSeverity.WARNING: 1,
        ViolationSeverity.INFO: 2
    }

    def __init__(self, rules: Optional[List[CircuitRule]] = None):
        if rules is None:
            self.rules = self._get_default_rules()
        else:
            self.rules = rules

    # danh sách rules mặc định (Phase 1 + Phase 2)
    def _get_default_rules(self) -> List[CircuitRule]:
        return [
            # Phase 1 rules
            ComponentParameterRule(),
            PinConnectionRule(),
            GroundReferenceRule(),
            OpAmpPowerRule(),
            BJTBiasingRule(),
            NetSingleConnectionRule(),
            ConstraintFeasibilityRule(),
            PortDirectionRule(),
            ComponentUniqueIdRule(),
            CircuitTopologyRule(),
            # Phase 2 rules
            PowerRatingRule(),
            VoltageRatingRule(),
            MOSFETBiasRule(),
            StructuredConstraintRule(),
            ParametricConsistencyRule(),
        ]

    # chạy tất cả rules, trả về danh sách vi phạm đã sắp xếp (ERROR trước)
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        all_violations = []

        for rule in self.rules:
            try:
                violations = rule.validate(circuit)
                all_violations.extend(violations)
            except Exception as e:
                # Rule bị lỗi → tạo violation đặc biệt
                all_violations.append(RuleViolation(
                    rule_name="RulesEngine",
                    message=f"Rule '{rule.name}' gặp lỗi khi chạy: {str(e)}",
                    severity=ViolationSeverity.ERROR
                ))

        return sorted(
            all_violations,
            key=lambda v: (self._SEVERITY_ORDER[v.severity], v.rule_name)
        )

    # validate + ném exception nếu có ERROR, trả True nếu chỉ WARNING/INFO
    def validate_and_throw(self, circuit: Circuit, throw_on_error: bool = True) -> bool:
        violations = self.validate(circuit)
        errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]

        if errors and throw_on_error:
            error_messages = "\n".join([f"- {v.message}" for v in errors[:3]])
            raise ValueError(
                f"Circuit validation failed with {len(errors)} errors:\n{error_messages}"
            )

        return len(errors) == 0

    # tóm tắt kết quả validation
    def get_summary(self, violations: List[RuleViolation]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "total": len(violations),
            "errors": len([v for v in violations if v.severity == ViolationSeverity.ERROR]),
            "warnings": len([v for v in violations if v.severity == ViolationSeverity.WARNING]),
            "info": len([v for v in violations if v.severity == ViolationSeverity.INFO]),
            "by_rule": {},
            "by_component": {},
        }

        for v in violations:
            summary["by_rule"][v.rule_name] = summary["by_rule"].get(v.rule_name, 0) + 1

            if v.component_id:
                summary["by_component"][v.component_id] = summary["by_component"].get(v.component_id, 0) + 1

        return summary



# ====== VALIDATION HELPERS ======
def validate_circuit(circuit: Circuit) -> Tuple[bool, List[Dict[str, Any]]]:
    """Helper validate circuit cho các layer trên dùng.
    Returns: Tuple[is_valid, violations_dict].
    is_valid = True nếu không có ERROR (chỉ có WARNING/INFO)."""
    engine = CircuitRulesEngine()
    violations = engine.validate(circuit)
    violations_dict = [v.to_dict() for v in violations]
    has_error = any(v.severity == ViolationSeverity.ERROR for v in violations)
    return (not has_error, violations_dict)


def validate_circuit_with_summary(circuit: Circuit) -> Dict[str, Any]:
    """Validate và trả về summary chi tiết."""
    engine = CircuitRulesEngine()
    violations = engine.validate(circuit)
    summary = engine.get_summary(violations)
    return {
        "is_valid": summary["errors"] == 0,
        "summary": summary,
        "violations": [v.to_dict() for v in violations]
    }



# ====== RULE REGISTRY ======
""" Registry để đăng ký rules custom (extensibility).
Cho phép layer trên đăng ký rules mới mà không sửa CircuitRulesEngine.
"""
class RuleRegistry:
    _rules: Dict[str, CircuitRule] = {}

    # đăng ký rule mới
    @classmethod
    def register(cls, rule: CircuitRule) -> None:
        cls._rules[rule.name] = rule

    # lấy rule theo tên
    @classmethod
    def get_rule(cls, name: str) -> Optional[CircuitRule]:
        return cls._rules.get(name)

    # lấy tất cả rules đã đăng ký
    @classmethod
    def get_all_rules(cls) -> List[CircuitRule]:
        return list(cls._rules.values())

    # tạo engine với tất cả rules đã đăng ký
    @classmethod
    def create_engine_with_registered_rules(cls) -> CircuitRulesEngine:
        return CircuitRulesEngine(rules=cls.get_all_rules())



# ====== TEST UTILITIES ======
def create_test_circuit() -> Circuit:
    """Tạo test circuit có lỗi cố ý để test rules."""
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


# chạy test khi import module
if __name__ == "__main__":
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
