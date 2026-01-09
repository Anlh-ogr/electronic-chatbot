# thesis/electronic-chatbot/apps/api/app/domains/circuits/entities.py
""" Info:
    Circuit Domain Entities - Luật vật lý của vũ trụ mạch điện
    TUYỆT ĐỐI KHÔNG: AI logic, KiCad logic, UI logic
    Chỉ pure domain entities với validation invariants.
"""

from __future__ import annotations

""" Giải thích thư viện
    annotations: cho phép sử dụng kiểu dữ liệu chưa được định nghĩa trong cùng module nhằm hỗ trợ kiểu dữ liệu đệ quy và tham chiếu chéo.
    dataclass: Sử dụng frozen để ngăn chặn việc các layer khác sửa CircuitCircuit. Hạn chế việc Source of Truth bị Phá
    field: để tùy chỉnh các trường trong dataclass, ví dụ như thiết lập giá trị mặc định.
    enum: để định nghĩa các kiểu dữ liệu liệt kê (enumerations) như ComponentType.
    mappingproxytype: để tạo các dict bất biến, cần thiết trong trường hợp là source of truth.
    typing: cung cấp các kiểu dữ liệu tổng quát như Dict, Optional, Tuple, Any để định nghĩa kiểu dữ liệu phức tạp hơn.
"""
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Dict, Optional, Tuple, Any

# ===== ENUMS =====
class ComponentType(Enum):
    """Loại linh kiện - KHÔNG cho phép user định nghĩa thêm"""
    RESISTOR = "resistor"
    CAPACITOR = "capacitor"
    INDUCTOR = "inductor"
    BJT = "bjt"
    MOSFET = "mosfet"
    OPAMP = "opamp"
    VOLTAGE_SOURCE = "voltage_source" # nguồn điện
    CURRENT_SOURCE = "current_source" # nguồn dòng
    GROUND = "ground"
    DIODE = "diode"

class PortDirection(Enum):
    """
        Tạo Direction chuẩn cho direction của class Port
        Hướng của port - KHÔNG cho phép user định nghĩa thêm
        Giải quyết tai họa typo, auto-complete
        Rule engine xử lý dễ dàng
    """
    INPUT = "input"
    OUTPUT = "output"
    POWER = "power"
    GROUND = "ground"


# ===== VALUE OBJECTS =====
# Tạo Parameter chuẩn cho parameter của class Component
@dataclass(frozen=True)
class ParameterValue:
    """ Value Object cho tham số linh kiện.
        Mục đích:
        * Ngăn Any linh hoạt quá mức gây mất kiểm soát
        * Chuẩn hóa để Rules engine xử lý đồng nhất
        * Đảm bảo IR stable, AI không phá kiểu dữ liệu
        Chỉ chấp nhận: int, float, str (từ chối dict/list/function)
    """
    value: Any                  # int | float | str only
    unit: Optional[str] = None  # VD: "Ohm", "F", "V", "A"
    
    """ Validation cho parameters từ chối cho dict/list/function lọt vào"""
    def __post_init__(self):
        if self.value is None:
            raise ValueError("ParameterValue.value không được None")

        if not isinstance(self.value, (int, float, str)):
            raise TypeError(
                f"ParameterValue.value chỉ chấp nhận int|float|str, nhận {type(self.value)}"
            )

@dataclass(frozen=True)
class PinRef:
    """
        Chuẩn hóa "Connection Object" trong Net
        Tham chiếu đến chân của một linh kiện
        Giúp chuẩn hóa connected_pins trong Net
    """
    component_id: str  # VD: "R1", "C2"
    pin_name: str      # VD: "A", "B", "C"
    
    def __post_init__(self):
        if not self.component_id or not self.pin_name:
            raise ValueError("PinRef không hợp lệ")


# ===== ENTITIES =====
@dataclass(frozen=True)
class Component:
    """
        Linh kiện vật lý. Immutable.
        KHÔNG chứa: vị trí, footprint, symbol
    """
    id: str               # VD: "R1", "C2", "Q3"
    type: ComponentType
    pins: Tuple[str, ...] # VD: ("1", "2") cho resistor; ("C", "B", "E") cho BJT
    # Ngăn chặn việc immutable bị phá (circuit.component.clear()/circuit.component["R1"]=some_fake_component -> phá vỡ SOA)
    _parameters: Dict[str, ParameterValue] = field(default_factory=dict)
    
    def __post_init__(self):
        # 1. Check cơ bản (type/shape)
        if not self.id:
            raise ValueError("Mã linh kiện không được để trống")
        if not isinstance(self.pins, tuple):
            raise TypeError(f"pins của {self.id} phải là Tuple[str, ...], không được dùng list")
        if not self.pins:
            raise ValueError(f"Linh kiện {self.id} phải có ít nhất một chân")
        
        # 2. Defensive copy + validate parameters
        params_copy = dict(self._parameters)
        for key, val in params_copy.items():
            if not isinstance(val, ParameterValue):
                raise TypeError(f"Parameter '{key}' của {self.id} phải là ParameterValue")

        # Set lại internal field với bản copy
        object.__setattr__(self, "_parameters", params_copy)
        # Tạo public proxy từ internal đã được copy
        object.__setattr__(self, "parameters", MappingProxyType(self._parameters))
        
        # 3. Business validation
        # TODO [PRIORITY]: Dời logic này sang rules.py (ComponentParameterRule)
        # Lý do: Hard-code kiến thức điện tử ở entity làm giảm tính mở rộng
        #  - Không tạo được partial circuit (mạch chưa hoàn thiện)
        #  - Không tạo được custom topology (Darlington, multi-emitter BJT)
        #  - Agent/AI phải biết chính xác tham số trước khi tạo component
        
        if self.type == ComponentType.RESISTOR:
            if "resistance" not in self.parameters:
                raise ValueError(f"Resistor {self.id} phải có tham số 'resistance'")          
        elif self.type == ComponentType.CAPACITOR:
            if "capacitance" not in self.parameters:
                raise ValueError(f"Capacitor {self.id} phải có tham số 'capacitance'")   
        elif self.type == ComponentType.BJT:
            if "model" not in self.parameters:
                raise ValueError(f"BJT {self.id} phải có tham số 'model'")    
        elif self.type == ComponentType.VOLTAGE_SOURCE:
            if "voltage" not in self.parameters:
                raise ValueError(f"Voltage source {self.id} phải có tham số 'voltage'")


@dataclass(frozen=True)
class Net:
    """
        Net = kết nối điện giữa các pin
        KHÔNG chứa: logic mạch, tính toán
    """
    name: str  # VD: "net1", "VCC", "GND"
    connected_pins: Tuple[PinRef, ...]  # Chuẩn hóa trong class PinRef
    
    def __post_init__(self):
        if not self.name:
            raise ValueError("Tên net không được trống")
        if not self.connected_pins:
            raise ValueError(f"Net '{self.name}' phải có ít nhất 1 pin")
        
        # Check kiểu
        for ref in self.connected_pins:
            if not isinstance(ref, PinRef):
                raise TypeError("connected_pins phải là PinRef")
        
        # Check duplicate (MỚI)
        seen = set()
        for ref in self.connected_pins:
            key = (ref.component_id, ref.pin_name)
            if key in seen:
                raise ValueError(f"Net '{self.name}' có duplicate pin {ref.component_id}.{ref.pin_name}")
            seen.add(key)



@dataclass(frozen=True)
class Port:
    """
    Port = giao diện mạch với thế giới ngoài
    Ví dụ: Vin, Vout, VCC, GND
    """
    name: str  # VD: "VIN", "VOUT", "VCC", "GND"
    net_name: str  # Tên net mà port này kết nối đến
    
    """
        Thành phần Optional[str] - String dễ thành TAI HỌA
        * typo = bug("power")
        * không auto-complete
        * rule engine khó xử lý
        -> Viết class Enum để kiểm soát chặt chẽ hơn
    """
    direction: Optional[PortDirection] = None
    
    def __post_init__(self):
        if not self.name:
            raise ValueError("Tên port không được để trống")
        if not self.net_name:
            raise ValueError(f"Port {self.name} phải kết nối đến một dây nối")
        if self.direction is not None and not isinstance(self.direction, PortDirection):
            raise TypeError("Port.direction phải là PortDirection enum")


@dataclass(frozen=True)
class Constraint:
    """
        Constraint = ý định kỹ thuật (KHÔNG PHẢI rule)
        Input cho rules engine (sẽ xử lý ở tuần 2)
    """
    name: str  # VD: "supply_voltage", "target_gain", "bandwidth"
    value: Any  # Có thể là số, string, dict
    unit: Optional[str] = None  # VD: "V", "Hz", "dB"
    
    def __post_init__(self):
        if not self.name:
            raise ValueError("Tên constraint không được để trống")


# ===== AGGREGATE ROOT =====
@dataclass(frozen=True)
class Circuit:
    """Entity cao nhất - đại diện cho toàn bộ mạch"""
    name: str
    
    """Ngăn chặn việc mutable phá vỡ SOA"""
    _components: Dict[str, Component] = field(default_factory=dict) # component_id -> Component
    _nets: Dict[str, Net] = field(default_factory=dict)  # net_name -> Net
    _ports: Dict[str, Port] = field(default_factory=dict)  # port_name -> Port
    _constraints: Dict[str, Constraint] = field(default_factory=dict)  # constraint_name -> Constraint
    
    def __post_init__(self):
        # Defensive copy CHO CHÍNH internal fields trước
        object.__setattr__(self, "_components", dict(self._components))
        object.__setattr__(self, "_nets", dict(self._nets))
        object.__setattr__(self, "_ports", dict(self._ports))
        object.__setattr__(self, "_constraints", dict(self._constraints))
        
        # Sau đó tạo public proxy từ internal đã được copy
        object.__setattr__(self, "components", MappingProxyType(self._components))
        object.__setattr__(self, "nets", MappingProxyType(self._nets))
        object.__setattr__(self, "ports", MappingProxyType(self._ports))
        object.__setattr__(self, "constraints", MappingProxyType(self._constraints))
        
        self.validate_basic()

    def validate_basic(self) -> None:
        """Validation invariants cơ bản - hàng rào bảo vệ đầu tiên"""
        errors = []
        
        # 1. Name không trống
        if not self.name:
            errors.append("Tên mạch không được trống")
        
        # 2. Sự không khớp khóa (ID) của linh kiện
        for comp_id, comp in self.components.items():
            if comp_id != comp.id:
                errors.append(f"Component key '{comp_id}' ≠ id '{comp.id}'")
        
        # 3. Sự không khớp khóa của nets/ports/constraints
        for net_name, net in self.nets.items():
            if net_name != net.name:
                errors.append(f"Net key '{net_name}' ≠ name '{net.name}'")
        
        for port_name, port in self.ports.items():
            if port_name != port.name:
                errors.append(f"Port key '{port_name}' ≠ name '{port.name}'")
        
        for cname, c in self.constraints.items():
            if cname != c.name:
                errors.append(f"Constraint key '{cname}' ≠ name '{c.name}'")
        
        # 4. Net → component/pin tồn tại (đã có)
        for net_name, net in self.nets.items():
            for ref in net.connected_pins:
                if ref.component_id not in self.components:
                    errors.append(f"Net '{net_name}' → linh kiện '{ref.component_id}' không tồn tại")
                else:
                    comp = self.components[ref.component_id]
                    if ref.pin_name not in comp.pins:
                        errors.append(f"Net '{net_name}' → pin '{ref.pin_name}' không tồn tại trên {ref.component_id}")
        
        # 5. Port → net tồn tại (đã có)
        for port_name, port in self.ports.items():
            if port.net_name not in self.nets:
                errors.append(f"Port '{port_name}' → net '{port.net_name}' không tồn tại")
        
        # 6. Pin không được thuộc nhiều net (MỚI - quan trọng)
        pin_to_net = {}
        for net_name, net in self.nets.items():
            for ref in net.connected_pins:
                pin_key = (ref.component_id, ref.pin_name)
                if pin_key in pin_to_net:
                    errors.append(
                        f"Pin {ref.component_id}.{ref.pin_name} thuộc nhiều net: "
                        f"'{pin_to_net[pin_key]}' và '{net_name}'"
                    )
                pin_to_net[pin_key] = net_name
        
        if errors:
            raise ValueError(f"Xác thực mạch thất bại:\n" + "\n".join(f"  - {e}" for e in errors))

    
    def get_component(self, component_id: str) -> Optional[Component]:
        """Helper method - không chứa logic điện"""
        return self.components.get(component_id)
    
    def get_net(self, net_name: str) -> Optional[Net]:
        """Helper method - không chứa logic điện"""
        return self.nets.get(net_name)
    
    """
        Cung cấp thêm copy helpers
        Entities ĐƯỢC PHÉP có method tạo bản sao (function style)
    """
    def with_component(self, component: Component) -> "Circuit":
        """Trả về bản sao của Circuit với component mới được thêm vào"""
        new_components = dict(self.components) # từ proxy
        new_components[component.id] = component
        
        """
            Không viết kiểu reuse reference cho:
            * nets=self.nets,                   -> nets=dict(self.nets)
            * ports=self.ports,                 -> ports=dict(self.ports)
            * constraints=self.constraints      -> constraints=dict(self.constraints)
            -> Dict này mà mutable ở ngoài -> Circuit không còn immutable -> phá vỡ SOA
        """
        return Circuit(
            name=self.name,
            _components=new_components,
            _nets=dict(self.nets),              # Từ proxy, không phải _nets
            _ports=dict(self.ports),            # Từ proxy
            _constraints=dict(self.constraints) # Từ proxy
        )