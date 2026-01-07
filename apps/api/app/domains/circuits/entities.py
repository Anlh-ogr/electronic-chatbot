# thesis/electronic-chatbot/apps/api/app/domains/circuits/entities.py
""" Info:
    Circuit Domain Entities - Luật vật lý của vũ trụ mạch điện
    TUYỆT ĐỐI KHÔNG: AI logic, KiCad logic, UI logic
    Chỉ pure domain entities với validation invariants.
"""


""" Giải thích thư viện
    annotations: cho phép sử dụng kiểu dữ liệu chưa được định nghĩa trong cùng module nhằm hỗ trợ kiểu dữ liệu đệ quy và tham chiếu chéo.
    dataclass: Sử dụng frozen để ngăn chặn việc các layer khác sửa CircuitCircuit. Hạn chế việc Source of Truth bị Phá
    field: để tùy chỉnh các trường trong dataclass, ví dụ như thiết lập giá trị mặc định.
    typing: cung cấp các kiểu dữ liệu tổng quát như Dict, Optional, Tuple, Any để định nghĩa kiểu dữ liệu phức tạp hơn.
    enum: để định nghĩa các kiểu dữ liệu liệt kê (enumerations) như ComponentType.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Any
from enum import Enum


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
    """ 
        Đề phòng Any linh hoạt -> mất kiểm soát
        Rules engine sẽ hiểu ParameterValue chứ không phải Any -> xử lý đồng nhất
        IR stable
        AI không phá kiểu dữ liệu
    """
    value: Any
    unit: Optional[str] = None # VD: "Ohm", "F", "V", "A"
    
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
    id: str  # VD: "R1", "C2", "Q3"
    type: ComponentType
    pins: Tuple[str, ...] # VD: ("A", "B") cho resistor; ("C", "B", "E") cho BJT
    parameters: Dict[str, ParameterValue]   # chuẩn hóa trong class ParameterValue
    
    def __post_init__(self):
        """Validation invariants cho Component"""
        if not self.id:
            raise ValueError("Mã linh kiện không được để trống")
        if not self.pins:
            raise ValueError(f"Linh kiện {self.id} phải có ít nhất một chân")
        
        """Validation cho parameters"""
        for key, val in self.parameters.items():
            if not isinstance(val, ParameterValue):
                raise TypeError(
                    f"Parameter '{key}' của {self.id} phải là ParameterValue"
                )

        """Domain entity KHÔNG được tự sửa dữ liệu đầu vào"""
        if not isinstance(self.pins, tuple):
            raise TypeError(
                f"pins của {self.id} phải là Tuple[str, ...], không được dùng list"
            )

        # Validation theo loại component
        """ TODO -> rule engine
            Hard-code kiến thức điện tử
            Đang khóa chặt topology trong entities -> không linh hoạt khi viết templates [darlington, multi-emitter, op-amp custom symbol]
            -> VỠ HỆ THỐNG.
        """
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
            raise ValueError("Tên dây nối không được để trống")
        if not self.connected_pins:
            raise ValueError(f"Dây nối {self.name} phải kết nối ít nhất một chân")
        
        # Kiểm tra kiểu connected_pins
        for ref in self.connected_pins:
            if not isinstance(ref, PinRef):
                raise TypeError("connected_pins phải là PinRef")


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
    components: Dict[str, Component]  # component_id -> Component
    nets: Dict[str, Net]  # net_name -> Net
    ports: Dict[str, Port]  # port_name -> Port
    constraints: Dict[str, Constraint]  # constraint_name -> Constraint
    
    def __post_init__(self):
        self.validate_basic()
    
    def validate_basic(self) -> None:
        """Basic validation invariants - hàng rào bảo vệ đầu tiên"""
        errors = []
        
        # 1. Mỗi net phải kết nối đến component tồn tại
        for net_name, net in self.nets.items():
            for ref in net.connected_pins:
                if ref.component_id not in self.components:
                    errors.append(f"Dây nối '{net_name}' kết nối đến linh kiện không tồn tại '{ref.component_id}'")
                else:
                    component = self.components[ref.component_id]
                    if ref.pin_name not in component.pins:
                        errors.append(f"Dây nối '{net_name}' kết nối đến chân không hợp lệ '{ref.pin_name}' của linh kiện '{ref.component_id}'")
        
        # 2. Validation cho name
        if not self.name:
            errors.append("Tên mạch không được để trống")
        
        # 3. Mỗi port phải kết nối đến net tồn tại
        for port_name, port in self.ports.items():
            if port.net_name not in self.nets:
                errors.append(f"Port '{port_name}' kết nối đến dây nối không tồn tại '{port.net_name}'")
        
        # 4. Check logic trùng key trong Dict
        for comp_id, comp in self.components.items():
            if comp_id != comp.id:
                errors.append(f"Component ID không khớp: key '{comp_id}' khác với component.id '{comp.id}'")
        
        if errors:
            raise ValueError(f"Xác thực mạch thất bại: {', '.join(errors)}")
    
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
        new_components = dict(self.components)
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
            components=new_components,
            nets=dict(self.nets),
            ports=dict(self.ports),
            constraints=dict(self.constraints)
        )