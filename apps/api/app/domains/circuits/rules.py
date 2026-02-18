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
 * ViolationSeverity (enum): ERROR / WARNING / INFO / SUCCESS.
 * RuleViolation (frozen dataclass): kết quả vi phạm từ mỗi rule.
 * CircuitRule (abstract base): interface cho tất cả rules.
 * 15 rules cụ thể : kiểm tra tham số, kết nối, bias, power rating, v.v.
 * CircuitRulesEngine: orchestrator chạy tất cả rules, sắp xếp kết quả.
 * RuleRegistry: extensibility — đăng ký rules tùy chỉnh.
 * tái sử dụng functions: validate_circuit(), validate_circuit_with_summary().
"""


from __future__ import annotations
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from .entities import (
    Circuit, Component, ComponentType, Net, Port, PortDirection,
    PinRef, Constraint, ParameterValue
)

""" Lý do sử dụng thư viện:
__future__: hỗ trợ forward references (kiểu dữ liệu tham chiếu chéo).
typing: cung cấp type hints cho biến (Dict, List, Optional, Tuple, Any).
dataclasses: dùng frozen=True cho RuleViolation để đảm bảo bất biến.
enum: định nghĩa hằng số ViolationSeverity (ERROR, WARNING, INFO).
abc: tạo lớp trừu tượng CircuitRule với phương thức abstract validate() để tất cả rules phải thực hiện.
.entities: nhập các lớp domain (Circuit, Component, ComponentType, ...) để kiểm tra mạch.
"""



""" Mức độ nghiêm trọng của vi phạm
 ERROR : mạch không hoạt động, phải sửa
 WARNING : có thể hoạt động nhưng không tối ưu
 INFO : gợi ý cải thiện
"""
class ViolationSeverity(Enum):
    ERROR = "error"         # mạch không hoạt động được
    WARNING = "warning"     # mạch có thể hoạt động nhưng có vấn đề (thiết kế kém, không tối ưu, ...)
    INFO = "info"           # gợi ý cải thiện, không phải lỗi nghiêm trọng
    SUCCESS = "success"     # trạng thái tốt, không có vấn đề gì (dùng cho feedback tích cực)




""" Kết quả kiểm tra từ một rule.
Đại diện cho một vi phạm/cảnh báo/gợi ý khi kiểm tra mạch.
Đảm bảo bất biến (frozen=True) — không sửa được sau khi tạo.
Args:
 * rule_name (str): tên rule tạo ra vi phạm.
 * message (str): thông điệp mô tả vi phạm.
 * severity (ViolationSeverity): mức độ nghiêm trọng.
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



""" Lớp cơ sở trừu tượng cho tất cả rules.
Mỗi rule kế thừa CircuitRule phải implement validate().

Nâng cấp so với phiên bản cũ:
 - description property: mô tả rule (dùng cho logging, UI, debug).
 - enabled flag: bật/tắt rule mà không cần xóa khỏi engine.
 - validate_safe(): đóng gói tự catch exception → trả violation thay vì crash.
 - Shorthand helpers: _warn(), _info(), _success() giảm boilerplate.
 - __repr__: debug dễ hơn.
"""
class CircuitRule(ABC):
    # bật/tắt rule — 0: thì engine bỏ qua
    enabled: bool = True

    # tên rule, lấy từ tên class
    @property
    def name(self) -> str:
        return self.__class__.__name__

    # mô tả ngắn rule này kiểm tra gì — override ở subclass nếu muốn
    @property
    def description(self) -> str:
        return self.__doc__.strip().splitlines()[0] if self.__doc__ else self.name

    # validate mạch, trả về danh sách vi phạm — abstract method
    @abstractmethod
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        ...

    # đóng gói an toàn: catch exception → trả RuleViolation (kết quả ktra) thay vì crash engine
    def validate_safe(self, circuit: Circuit) -> List[RuleViolation]:
        # nếu rule bị tắt, trả về list rỗng (không có vi phạm)
        # để engine tiếp tục chạy các rule khác mà không bị ảnh hưởng (lỗi nghiêm trọng / thiết kế kém nếu để rule bị lỗi làm crash toàn bộ validation)
        if not self.enabled:
            return []
        try:
            return self.validate(circuit)
        except Exception as exc:
            return [self._create_violation(
                f"Rule '{self.name}' gặp lỗi khi chạy: {exc}",
                severity=ViolationSeverity.ERROR,
                details={"exception": str(exc), "exception_type": type(exc).__name__}
            )]

    # ── Tái sử dụng Shorthand  ──────────────────────────────────────────────────────

    # tạo violation với severity tùy chọn (mặc định ERROR) giảm code trùng ở subclass
    # tạo violation, severity=Error mặc đinh, đánh giá ViolationSeverity, kế thừa thay vì phải chạy nhiều lần.
    def _create_violation(self, message: str, severity: ViolationSeverity = ViolationSeverity.ERROR, **kwargs) -> RuleViolation:
        return RuleViolation(rule_name=self.name, message=message, severity=severity, **kwargs)

    # gọi warning thay cho error(default) - phân biệt lỗi
    def _warn(self, message: str, **kwargs) -> RuleViolation:
        return self._create_violation(message, ViolationSeverity.WARNING, **kwargs)

    # gọi info thay cho error(default) - phân biệt lỗi
    def _info(self, message: str, **kwargs) -> RuleViolation:
        return self._create_violation(message, ViolationSeverity.INFO, **kwargs)

    # gọi success thay cho error(default) - phân biệt lỗi
    def _success(self, message: str, **kwargs) -> RuleViolation:
        return self._create_violation(message, ViolationSeverity.SUCCESS, **kwargs)

    # show tên rule + trạng thái (ON/OFF) khi debug
    def __repr__(self) -> str:
        status = "ON" if self.enabled else "OFF"
        return f"<{self.name} [{status}]>"

    # ── Shared constants & helpers cho subclass ────────────────────────────────
    # nhóm component type families — subclass dùng chung, không cần define lại
    _BJT_FAMILY = {ComponentType.BJT, ComponentType.BJT_NPN, ComponentType.BJT_PNP}
    _MOSFET_FAMILY = {ComponentType.MOSFET, ComponentType.MOSFET_N, ComponentType.MOSFET_P}
    _CAPACITOR_FAMILY = {ComponentType.CAPACITOR, ComponentType.CAPACITOR_POLARIZED}

    _ACTIVE_TYPES = {
        ComponentType.BJT, ComponentType.BJT_NPN, ComponentType.BJT_PNP,
        ComponentType.MOSFET, ComponentType.MOSFET_N, ComponentType.MOSFET_P,
        ComponentType.OPAMP, ComponentType.DIODE,
    }
    _PASSIVE_TYPES = {
        ComponentType.RESISTOR, ComponentType.CAPACITOR,
        ComponentType.CAPACITOR_POLARIZED, ComponentType.INDUCTOR,
    }
    _SOURCE_TYPES = {ComponentType.VOLTAGE_SOURCE, ComponentType.CURRENT_SOURCE}

    # tìm net kết nối đến pin cụ thể của component (dùng chung cho BJT, MOSFET, OpAmp rules)
    @staticmethod
    def _find_pin_net(circuit: Circuit, comp_id: str, pin_name: str) -> Optional[Net]:
        for net in circuit.nets.values():
            for pin_ref in net.connected_pins:
                if pin_ref.component_id == comp_id and pin_ref.pin_name == pin_name:
                    return net
        return None

    # trích xuất giá trị float từ ParameterValue hoặc raw value (dùng chung cho power/voltage rating rules)
    @staticmethod
    def _extract_value(param: Any) -> Any:
        if param is None:
            return None
        return param.value if isinstance(param, ParameterValue) else param




""" Rule 1: Kiểm tra tham số bắt buộc của từng loại component.
Tạo bảng danh sách thay vì if/elif.
Logic:
 - Passive (R, C, C_polarized, L): phải có tham số resistance/capacitance/inductance → ERROR.
 - Active (BJT/NPN/PNP, MOSFET/N/P, OpAmp): nên có model → WARNING.
 - Source (V, I): phải có voltage/current → ERROR.
"""
class ComponentParameterRule(CircuitRule):
    # Bảng tra cứu: component_type → (tên tham số bắt buộc, severity)
    # bao gồm tất cả subtypes (BJT_NPN, MOSFET_N, CAPACITOR_POLARIZED, ...)
    _REQUIRED_PARAMS: Dict[ComponentType, Tuple[str, ViolationSeverity]] = {
        ComponentType.RESISTOR:            ("resistance",  ViolationSeverity.ERROR),
        ComponentType.CAPACITOR:           ("capacitance", ViolationSeverity.ERROR),
        ComponentType.CAPACITOR_POLARIZED: ("capacitance", ViolationSeverity.ERROR),
        ComponentType.INDUCTOR:            ("inductance",  ViolationSeverity.ERROR),
        ComponentType.BJT:                 ("model",       ViolationSeverity.WARNING),
        ComponentType.BJT_NPN:             ("model",       ViolationSeverity.WARNING),
        ComponentType.BJT_PNP:             ("model",       ViolationSeverity.WARNING),
        ComponentType.MOSFET:              ("model",       ViolationSeverity.WARNING),
        ComponentType.MOSFET_N:            ("model",       ViolationSeverity.WARNING),
        ComponentType.MOSFET_P:            ("model",       ViolationSeverity.WARNING),
        ComponentType.OPAMP:               ("model",       ViolationSeverity.WARNING),
        ComponentType.VOLTAGE_SOURCE:      ("voltage",     ViolationSeverity.ERROR),
        ComponentType.CURRENT_SOURCE:      ("current",     ViolationSeverity.ERROR),
    }

    # dựa vào bảng để kiểm tra từng linh kiện, nếu thiếu tham số → tạo violation với severity tương ứng
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        for component in circuit.components.values():
            entry = self._REQUIRED_PARAMS.get(component.type)
            # nếu linh kiện chưa có trong bảng thì bỏ qua
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


""" Rule 2: Kiểm tra kết nối pins cơ bản.
 1. Tất cả pin phải được kết nối (trừ pin optional).
 2. Pin không được "treo lơ lửng".
 3. Pin không được kết nối đến nhiều nets khác nhau.
"""
class PinConnectionRule(CircuitRule):
    # Danh sách pin optional theo component type (không bắt buộc kết nối)
    # bao gồm subtypes (BJT_NPN, MOSFET_N, ...)
    _OPTIONAL_PINS: Dict[ComponentType, List[str]] = {
        ComponentType.OPAMP:    ["NC", "OFFSET"],
        ComponentType.BJT:      [],
        ComponentType.BJT_NPN:  [],
        ComponentType.BJT_PNP:  [],
        ComponentType.MOSFET:   ["BULK"],
        ComponentType.MOSFET_N: ["BULK"],
        ComponentType.MOSFET_P: ["BULK"],
    }

    # tạo mapping pin → nets chứa pin đó, sau đó kiểm tra từng component:
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []
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
    _GND_NET_NAMES = {"GND", "GROUND", "VSS", "0V"} # tên hợp lệ cho ground

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        # Tìm component ground
        has_ground_comp = any(
            comp.type == ComponentType.GROUND
            for comp in circuit.components.values()
        )

        # Tìm port ground
        has_ground_port = any(
            port.direction == PortDirection.GROUND
            for port in circuit.ports.values()
        )

        # Tìm net có tên GND
        has_ground_net = any(
            net.name.upper() in self._GND_NET_NAMES
            for net in circuit.nets.values()
        )

        if not has_ground_comp and not has_ground_port and not has_ground_net:
            violations.append(self._warn(
                "Mạch không có điểm ground reference. Cần ít nhất một trong: "
                "component ground, port ground, hoặc net tên GND",
            ))
        else:
            violations.append(self._success(
                "Mạch có ground reference hợp lệ",
            ))

        return violations


""" Rule 4: OpAmp phải có kết nối nguồn (V+ và V-).
Kiểm tra: power port hoặc voltage source kết nối đến OpAmp.
"""
class OpAmpPowerRule(CircuitRule):
    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        # Tìm tất cả OpAmps
        opamps = [
            comp for comp in circuit.components.values()
            if comp.type == ComponentType.OPAMP
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
            port for port in circuit.ports.values()
            if port.direction in [PortDirection.POWER, PortDirection.GROUND]
        ]

        # Tìm voltage sources
        voltage_sources = [
            comp for comp in circuit.components.values()
            if comp.type == ComponentType.VOLTAGE_SOURCE
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
            
            # Nếu không tìm thấy nguồn nào kết nối đến OpAmp → lỗi
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
Hỗ trợ BJT, BJT_NPN, BJT_PNP qua _BJT_FAMILY.
"""
class BJTBiasingRule(CircuitRule):

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        # Dùng _BJT_FAMILY từ base class để bắt cả BJT_NPN, BJT_PNP
        bjts = [
            comp for comp in circuit.components.values()
            if comp.type in self._BJT_FAMILY
        ]

        for bjt in bjts:
            # Tìm net kết nối đến base của BJT (dùng _find_pin_net từ base class)
            base_net = self._find_pin_net(circuit, bjt.id, "B")

            # Kiểm tra có base resistor không
            base_resistors = []
            if base_net:
                for pin_ref in base_net.connected_pins:
                    comp = circuit.get_component(pin_ref.component_id)
                    if comp and comp.type == ComponentType.RESISTOR:
                        base_resistors.append(comp.id)

            # Nếu ko có R kết nối đến Base -> cảnh báo
            if not base_resistors:
                violations.append(self._warn(
                    f"BJT {bjt.id} không có base resistor. "
                    "Cần có resistor để hạn dòng base",
                    component_id=bjt.id,
                ))
            else:
                violations.append(self._success(
                    f"BJT {bjt.id} có base bias resistor: {', '.join(base_resistors)}",
                    component_id=bjt.id,
                ))

        return violations


""" Rule 6: Net chỉ có 1 connection là nghi ngờ (dây treo).
Net không có connection nào cũng là lỗi.
Trừ net là port output hoặc test point.
"""
class NetSingleConnectionRule(CircuitRule):

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        for net_name, net in circuit.nets.items():
            # Net không có connection nào — net mồ côi
            if len(net.connected_pins) == 0:
                violations.append(self._create_violation(
                    f"Net '{net_name}' không có kết nối nào. Net mồ côi",
                    net_name=net_name,
                ))
                continue

            if len(net.connected_pins) == 1:
                # Net là port → cho phép 1 connection
                is_port = any(
                    port.net_name == net_name
                    for port in circuit.ports.values()
                )

                if not is_port:
                    violations.append(self._warn(
                        f"Net '{net_name}' chỉ có 1 kết nối. "
                        "Có thể là lỗi thiết kế (dây treo)",
                        net_name=net_name,
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
                    details={"value": constraint.value}
                ))

            # 2. Gain quá lớn
            if constraint.name == "gain" and abs(constraint.value) > 1000:
                violations.append(self._warn(
                    f"Gain quá lớn ({constraint.value}). "
                    "Gain thực tế thường dưới 1000",
                    constraint_name=constraint.name,
                    details={"value": constraint.value}
                ))

            # 3. Điện áp nguồn quá lớn
            if constraint.name == "supply_voltage" and constraint.value > 1000:
                violations.append(self._warn(
                    f"Điện áp nguồn quá lớn ({constraint.value}V). "
                    "Kiểm tra đơn vị (mV/V)",
                    constraint_name=constraint.name,
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
                net = circuit.get_net(port.net_name)

                # Output không có net → treo lơ lửng hoàn toàn
                if net is None:
                    violations.append(self._warn(
                        f"Port output '{port.name}' không có net kết nối. "
                        "Output treo lơ lửng, tín hiệu sẽ không đến đích",
                        port_name=port.name,
                        net_name=port.net_name,
                    ))

                # Output có net nhưng không có component nào nhận tín hiệu (chỉ có 1 pin = chính nó)
                elif len(net.connected_pins) == 0:
                    violations.append(self._warn(
                        f"Port output '{port.name}' có net '{port.net_name}' nhưng "
                        "không có component nào kết nối",
                        port_name=port.name,
                        net_name=port.net_name,
                    ))

                # Output kết nối trực tiếp vào nguồn → có thể gây tranh chấp (bus contention)
                else:
                    for pin_ref in net.connected_pins:
                        comp = circuit.get_component(pin_ref.component_id)
                        if comp and comp.type in (
                            ComponentType.VOLTAGE_SOURCE,
                            ComponentType.CURRENT_SOURCE,
                        ):
                            violations.append(self._create_violation(
                                f"Port output '{port.name}' kết nối trực tiếp đến nguồn "
                                f"({comp.id}). Có thể gây tranh chấp tín hiệu (bus contention)",
                                port_name=port.name,
                                net_name=port.net_name,
                                severity=ViolationSeverity.WARNING,
                                details={"source_component": comp.id},
                            ))
                            break

        return violations


""" Rule 9: Kiểm tra ID component không trùng.
Đã có trong Circuit.validate_basic nhưng thêm rule cho defense-in-depth.
"""
class ComponentUniqueIdRule(CircuitRule):

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        # circuit.components là Dict nên key đã unique theo định nghĩa.
        # Kiểm tra defense-in-depth: key dict phải khớp với component.id bên trong
        for comp_key, comp in circuit.components.items():
            if comp_key != comp.id:
                violations.append(self._create_violation(
                    f"Component key '{comp_key}' không khớp với id bên trong '{comp.id}'",
                    component_id=comp.id,
                ))

        return violations


""" Rule 10: Kiểm tra topology cơ bản.
 - Mạch có constraint gain nhưng không có active component → lỗi.
 - Mạch có constraint filter nhưng không có linh kiện thụ động → lỗi.
 - Mạch rỗng: buộ khuếch đại cần feedback, nguồn cần load.
 Dùng _ACTIVE_TYPES và _PASSIVE_TYPES từ base class (bao gồm subtypes).
"""
class CircuitTopologyRule(CircuitRule):
    # Dùng _ACTIVE_TYPES và _PASSIVE_TYPES bao gồm BJT_NPN/PNP, MOSFET_N/P, CAPACITOR_POLARIZED

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        # Đếm active components (dùng base class _ACTIVE_TYPES)
        has_active = any(
            comp.type in self._ACTIVE_TYPES
            for comp in circuit.components.values()
        )

        # Kiểm tra gain constraint mà không có active component
        has_gain = any(
            con.name.lower() == "gain"
            for con in circuit.constraints.values()
        )

        # Nếu có constraint gain nhưng không có active component → lỗi
        if has_gain and not has_active:
            violations.append(self._create_violation(
                "Mạch có constraint gain nhưng không có active component "
                "(BJT, MOSFET, OpAmp, Diode). Không thể khuếch đại",
            ))
        elif has_gain and has_active:
            violations.append(self._success(
                "Mạch có active component phù hợp với yêu cầu gain",
            ))

        # Kiểm tra filter constraint mà không có passive component
        has_filter = any(
            "filter" in con.name.lower() or "frequency" in con.name.lower()
            for con in circuit.constraints.values()
        )

        # Dùng base class _PASSIVE_TYPES (bao gồm CAPACITOR_POLARIZED)
        if has_filter:
            has_passive = any(
                comp.type in self._PASSIVE_TYPES
                for comp in circuit.components.values()
            )

            if not has_passive:
                violations.append(self._create_violation(
                    "Mạch có constraint filter nhưng không có linh kiện thụ động "
                    "(R, L, C). Không thể lọc tín hiệu",
                ))
            else:
                violations.append(self._success(
                    "Mạch có linh kiện thụ động phù hợp với yêu cầu filter",
                ))

        # Kiểm tra mạch rỗng không có linh kiện nào
        if len(circuit.components) == 0:
            violations.append(self._create_violation(
                "Mạch không có linh kiện nào",
            ))

        return violations



""" Rule 11: Kiểm tra power rating của linh kiện.
Ước lượng công suất: P = V²/R hoặc P = I²·R.
Nếu vượt power_rating → ERROR.
Dùng _extract_value() từ base class.
"""
class PowerRatingRule(CircuitRule):

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        # Duyệt qua tất cả component, nếu có power_rating → ước lượng công suất dựa trên voltage/current/resistance (nếu có) và so sánh với power_rating
        for comp in circuit.components.values():
            params = comp.parameters
            power_rating = params.get("power_rating")
            if power_rating is None:
                continue

            # Dùng _extract_value() từ base class CircuitRule
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
                    details={
                        "estimated_power": estimated_power,
                        "max_power": max_watts,
                    },
                ))
            elif estimated_power is not None:
                violations.append(self._success(
                    f"Component {comp.id}: công suất {estimated_power:.3f}W "
                    f"trong giới hạn {max_watts}W",
                    component_id=comp.id,
                ))

        return violations


""" Rule 12: Kiểm tra voltage rating của tụ / linh kiện.
Tụ có voltage_rating thấp hơn supply voltage → ERROR.
Dùng _extract_value() từ base class.
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
            
            # Dùng _extract_value() từ base class
            rating = self._extract_value(vr)
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

    # tìm supply voltage lớn nhất từ voltage source hoặc constraint (dùng _extract_value từ base class)
    # tạo biến cls(classmethod) để có thể gọi _extract_value() từ base class mà không cần instance tránh helper nhìu
    @classmethod
    def _find_supply_voltage(cls, circuit: Circuit) -> Optional[float]:
        supply_voltage: Optional[float] = None

        # Từ voltage source component
        for comp in circuit.components.values():
            if comp.type == ComponentType.VOLTAGE_SOURCE:
                val = cls._extract_value(comp.parameters.get("voltage"))
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
Hỗ trợ MOSFET, MOSFET_N, MOSFET_P qua _MOSFET_FAMILY.
Dùng _find_pin_net() từ base class.
"""
class MOSFETBiasRule(CircuitRule):

    def validate(self, circuit: Circuit) -> List[RuleViolation]:
        violations = []

        # Dùng _MOSFET_FAMILY từ base class để bắt cả MOSFET_N, MOSFET_P
        mosfets = [
            c for c in circuit.components.values()
            if c.type in self._MOSFET_FAMILY
        ]

        for mos in mosfets:
            # Tìm net kết nối đến gate (dùng _find_pin_net từ base class)
            gate_net = self._find_pin_net(circuit, mos.id, "G")

            # Kiểm tra có gate resistor không
            gate_resistors = []
            if gate_net:
                for pin_ref in gate_net.connected_pins:
                    comp = circuit.get_component(pin_ref.component_id)
                    if comp and comp.type == ComponentType.RESISTOR:
                        gate_resistors.append(comp.id)

            if not gate_resistors:
                violations.append(self._warn(
                    f"MOSFET {mos.id} không có gate bias resistor. "
                    "Gate cần được phân cực qua resistor để điều khiển VGS",
                    component_id=mos.id,
                ))
            else:
                violations.append(self._success(
                    f"MOSFET {mos.id} có gate bias resistor: {', '.join(gate_resistors)}",
                    component_id=mos.id,
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
                    violations.append(self._warn(
                        f"Constraint '{con.name}' tham chiếu target '{con.target}' "
                        "không tồn tại trong mạch",
                        constraint_name=con.name,
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
                violations.append(self._info(
                    f"Parametric key '{key}' không tìm thấy component "
                    "tương ứng trong mạch",
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
        ViolationSeverity.INFO: 2,
        ViolationSeverity.SUCCESS: 3,
    }

    def __init__(self, rules: Optional[List[CircuitRule]] = None):
        if rules is None:
            self.rules = self._get_default_rules()
        else:
            self.rules = rules

    # danh sách rules mặc định (Phase 1 + Phase 2)
    def _get_default_rules(self) -> List[CircuitRule]:
        return [
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
            # validate_safe() xử lý enabled-check + catch exception trong base class
            all_violations.extend(rule.validate_safe(circuit))

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

    # tóm tắt kết quả validation (bao gồm SUCCESS count)
    def get_summary(self, violations: List[RuleViolation]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "total": len(violations),
            "errors": len([v for v in violations if v.severity == ViolationSeverity.ERROR]),
            "warnings": len([v for v in violations if v.severity == ViolationSeverity.WARNING]),
            "info": len([v for v in violations if v.severity == ViolationSeverity.INFO]),
            "success": len([v for v in violations if v.severity == ViolationSeverity.SUCCESS]),
            "by_rule": {},
            "by_component": {},
        }

        for v in violations:
            summary["by_rule"][v.rule_name] = summary["by_rule"].get(v.rule_name, 0) + 1

            if v.component_id:
                summary["by_component"][v.component_id] = summary["by_component"].get(v.component_id, 0) + 1

        return summary


def validate_circuit_with_summary(circuit: Circuit) -> Dict[str, Any]:
    """Hàm gốc — validate và trả về summary chi tiết (dùng cho UI, debug, logging).
    Returns: dict { is_valid, summary, violations }."""
    engine = CircuitRulesEngine()
    violations = engine.validate(circuit)
    summary = engine.get_summary(violations)
    return {
        "is_valid": summary["errors"] == 0,
        "summary": summary,
        "violations": [v.to_dict() for v in violations]
    }


def validate_circuit(circuit: Circuit) -> Tuple[bool, List[Dict[str, Any]]]:
    """Wrapper gọn — dùng cho API layer chỉ cần (is_valid, violations_dict).
    Gọi lại validate_circuit_with_summary() để tránh chạy engine 2 lần.
    Returns: Tuple[is_valid, violations_dict]."""
    result = validate_circuit_with_summary(circuit)
    return (result["is_valid"], result["violations"])



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


# Test chạy trực tiếp
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
