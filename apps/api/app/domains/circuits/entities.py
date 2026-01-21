# .\thesis\electronic-chatbot\apps\api\app\domains\circuits\entities.py
""" Thông tin chung:
Thiết kế hệ thống theo kiến trúc Domain-Driven Design (DDD), đặt domain (nghiệp vụ) là cốt lõi trung tâm, xây dựng mô hình kiến trúc phản ánh chính xác các quy tắt và logic.
Đóng vai trò là tầng domain trong kiến trúc nhiều tầng, tách biệt rõ ràng với các tầng khác như application, infrastructure, interface, tool,...
 * Trong hệ thống tổng quan Domain Entities nằm trong lớp Service Layer, chứa các nghiệp vụ xử lý.
 * Trong hệ thống kiến trúc Domain Entities nằm trong Khối xử lý trung tâm, đóng vai trò "bộ não" của hệ thống.
Circuit Domain Entities là tập hợp các thực thể (entities) và đối tượng giá trị (value objects) đại diện cho các khái niệm và quy tắc trong lĩnh vực mạch điện tử, bao gồm ("linh kiện", "dây nối", "ports", "ràng buộc", "mạch").
Tuyệt đối không được chứa AI Logic, KiCad Logic, UI Logic tránh phá vỡ Source of Truth.
Chỉ được chứa nghiệp vụ thuần túy của domain với các bất biến (validation invariants) đảm bảo tính toàn vẹn và nhất quán của dữ liệu.
"""


from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Dict, Optional, Tuple, Any

""" Lý do sử dụng thư viện
__future__ : do không thể sử dụng một class làm kiểu dữ liệu cho một biến trong chính class đó (class chưa khởi tạo xong), nên cần import từ "annotations" để hỗ trợ kiểu dữ liệu tham chiếu chéo (forward references).
dataclasses dataclass: gọi frozen = True để tạo bất biến (immutability) cho component, net, circuit. Ngăn chặn việc các layer khác sửa đổi trực tiếp các entity này, bảo vệ Source of Truth.
dataclasses field: tạo trường dữ liệu mạch định là một dict bất biến (immutable dict) để ngăn chặn việc sửa đổi trực tiếp từ bên ngoài.
enum: tự động định nghĩa các hằng số cho từng loại linh kiện, hướng port, ép do người/AI code phải đúng giá trị định nghĩa sẵn (ComponentType.Resistor, v.v).
mappingproxytype: frozen=True chỉ bảo vệ các biến đơn giản, có thể bị can thiệp do người. MappingProxy sẽ bọc Dict và biến nó thành read-only, mọi hành động sửa đổi đều bị báo lỗi ngay lập tức.
typing: cung cấp thông tin về kiểu dữ liệu cho các biến, hàm:
 * Dict[str, param value]: dùng key là str và value là object. VD: {"resistance": ParameterValue(1000, "Ohm")}.
 * Optional[str]: biến có thể là str hoặc None. VD: {"unit": "Ohm"} hoặc {"unit": None}.
 * Tuple[str, ...]: dùng tuple thay list vì tuple có tính bất biến (không thêm bớt các phần tử sau khi tạo) phù hợp với danh sách Pin linh kiện.
 * Any: sử dụng các trường dữ liệu linh hoạt (giá trị ràng buộc), kiểu dữ liệu có thể tùy ý (int, float, str).
"""

# ====== ENUMS ======
""" Định nghĩa các loại linh kiện
 Điện trở: "resistor"
 Tụ điện: "capacitor"
 Cuộn cảm: "inductor"
 Transistor lưỡng cực: "bjt"
 Transistor hiệu ứng trường: "mosfet"
 Op-amp: "opamp"
 Nguồn điện áp: "voltage_source"
 Nguồn dòng điện: "current_source"
 Mass (Ground): "ground"
 Đi-ot: "diode"
"""
class ComponentType(Enum):
    RESISTOR = "resistor"
    CAPACITOR = "capacitor"
    INDUCTOR = "inductor"
    BJT = "bjt"
    MOSFET = "mosfet"
    OPAMP = "opamp"
    VOLTAGE_SOURCE = "voltage_source"
    CURRENT_SOURCE = "current_source"
    GROUND = "ground"
    DIODE = "diode"


""" Định nghĩa hướng Port
 Input : "input"
 Output : "output"
 Nguồn : "power"
 Mass : "ground"
"""
class PortDirection(Enum):
    INPUT = "input"
    OUTPUT = "output"
    POWER = "power"
    GROUND = "ground"



# ====== VALUE OBJECTS ======
""" Giá trị tham số
Lưu trữ các giá trị tham số của linh kiện.
 * Value không được None, bắt buộc phải có giá trị thực tế.
 * Kiểm tra kiểu dữ liệu để tránh lỗi khi tính toán hoặc truyền vào kiểu không hợp lệ (dict, list, function).
In/Out:
 * In: Any {int | float | str}
 * Out: dict {"value": int | float | str, "unit": str|None}
Chuyển đổi các Object phức tạp thành dữ liệu đơn giản (cỗ máy phiên dịch) để truyền qua API, lưu trữ database, hiển thị UI.
"""
@dataclass(frozen=True)
class ParameterValue:
    value: Any
    unit: Optional[str] = None
    
    def __post_init__(self):
        if self.value is None:
            raise ValueError("Value không được None")
        if not isinstance(self.value, (int, float, str)):
            raise TypeError(f"Value chỉ chấp nhận int|float|str, nhận {type(self.value)}")
            
    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "unit": self.unit
        }
        
""" Tham chiếu chân linh kiện
 * Tạo id và tên chân cụ thể cho từng linh kiện.
 * Khi kết nối các chân trong mạch, cần tham chiếu đến đúng chân linh kiện.
 * Đảm bảo id và tên chân của linh kiện không được để trống.
 In/Out:
  * In: str (component_id), str (pin_name)
  * Out: dict {"component_id": str, "pin_name": str}
Chuyển đổi các Object phức tạp thành dữ liệu đơn giản (cỗ máy phiên dịch) để truyền qua API, lưu trữ hoặc hiển thị UI.
"""
@dataclass(frozen=True)
class PinRef:
    component_id: str
    pin_name: str
    
    def __post_init__(self):
        if not self.component_id or not self.pin_name:
            raise ValueError("PinRef không hợp lệ")
        
    def to_dict(self) -> dict:
        return {
            "component_id": self.component_id,
            "pin_name": self.pin_name
        }



# ===== ENTITIES =====
""" Linh kiện vật lý trong mạch
Đại diện cho một linh kiện với id, loại, danh sách chân và các tham số.
Đảm bảo id không trống, pins là tuple và có ít nhất hai chân.
Mọi tham số phải là ParameterValue, kiểm tra chặt chẽ kiểu dữ liệu.
In/Out:
 * In: str (id), ComponentType (type), tuple[str, ...] (pins), dict[str, ParameterValue] (parameters)
 * Out: dict {"id": str, "type": str, "pins": tuple[str, ...], "parameters": dict[str, dict]}
Chuyển đổi object thành dict đơn giản để truyền qua API, lưu trữ hoặc hiển thị UI.
"""
@dataclass(frozen=True)
class Component:
    id: str
    type: ComponentType
    pins: Tuple[str, ...]
    # Ngăn chặn việc immutable bị phá (circuit.component.clear()/circuit.component["R1"]=some_fake_component -> phá vỡ SOA)
    parameters: Dict[str, ParameterValue] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.id:
            raise ValueError("Mã linh kiện không được trống")
        if not isinstance(self.pins, tuple):
            raise TypeError(f"Pins của {self.id} phải là Tuple")
        if not self.pins:
            raise ValueError(f"Linh kiện {self.id} phải có ít nhất hai chân")
        
        params_copy = dict(self.parameters)
        for key, val in params_copy.items():
            if not isinstance(val, ParameterValue):
                raise TypeError(f"Parameter '{key}' của {self.id} phải là ParameterValue")
                # {"bjt_model": "2N2222"} sai -> phải {"bjt_model": ParameterValue("2N2222")}

        # Set lại field với bản copy immutable
        object.__setattr__(self, "parameters", MappingProxyType(params_copy))
        
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
            
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "pins": self.pins,
            "parameters": {key: val.to_dict() for key, val in self.parameters.items()}
        }



""" Dây nối giữa các chân linh kiện
Đại diện cho một net (dây nối) với tên và danh sách các chân kết nối.
Đảm bảo tên net không trống, danh sách chân hợp lệ, "không trùng lặp".
In/Out:
 * In: str (name), tuple[PinRef, ...] (connected_pins)
 * Out: dict {"name": str, "connected_pins": list[dict]}
Chuyển đổi object thành dict đơn giản để truyền qua API, lưu trữ hoặc hiển thị UI.
"""
@dataclass(frozen=True)
class Net:
    name: str
    connected_pins: Tuple[PinRef, ...]
    
    def __post_init__(self):
        if not self.name:
            raise ValueError("Tên net không được trống")
        if not self.connected_pins:
            raise ValueError(f"Net '{self.name}' phải có ít nhất hai pin")
        
        for ref in self.connected_pins:
            if not isinstance(ref, PinRef):
                raise TypeError(f"Mỗi phần tử trong connected_pins phải là PinRef, nhận {type(ref)}")
        
        seen = set()
        for ref in self.connected_pins:
            key = (ref.component_id, ref.pin_name)
            if key in seen:
                raise ValueError(f"Net '{self.name}' chứa nhiều lần cùng một chân: {ref.component_id}.{ref.pin_name}")
            seen.add(key)
            
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "connected_pins": [ref.to_dict() for ref in self.connected_pins]
        }



""" Cổng Ports
Đại diện cho giao diện giữa mạch và thế giới bên ngoài (VD: VIN, VOUT, VCC, GND).
Đảm bảo tên port và tên net không được để trống, direction (hướng) phải là Enum PortDirection nếu có.
In/Out:
 * In: str (name), str (net_name), Optional[PortDirection] (direction)
 * Out: dict {"name": str, "net_name": str, "direction": str|None}
Validation:
 * name: không được rỗng
 * net_name: không được rỗng
 * direction: nếu có, phải là PortDirection
Chuyển đổi object thành dict đơn giản để truyền qua API, lưu trữ hoặc hiển thị UI.
"""
@dataclass(frozen=True)
class Port:
    name: str
    net_name: str
    direction: Optional[PortDirection] = None

    def __post_init__(self):
        if not self.name:
            raise ValueError("Tên port không được để trống")
        if not self.net_name:
            raise ValueError(f"Port '{self.name}' phải kết nối đến một net (net_name không được để trống)")
        if self.direction is not None and not isinstance(self.direction, PortDirection):
            raise TypeError(f"Port '{self.name}': direction phải là PortDirection enum, nhận {type(self.direction)}")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "net_name": self.net_name,
            "direction": self.direction.value if self.direction else None
        }



""" Ràng buộc giữa các tham số
Đại diện cho ý định kỹ thuật (không phải rule), dùng làm input cho rules engine.
Đảm bảo tên constraint không được để trống.
In/Out:
 * In: str (name), Any (value), Optional[str] (unit)
 * Out: dict {"name": str, "value": Any, "unit": str|None}
Validation:
 * name: không được rỗng
Chuyển đổi object thành dict đơn giản để truyền qua API, lưu trữ hoặc hiển thị UI.
"""
@dataclass(frozen=True)
class Constraint:
    name: str
    value: Any
    unit: Optional[str] = None

    def __post_init__(self):
        if not self.name:
            raise ValueError("Ràng buộc phải có tên")
        
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit
        }


# ===== AGGREGATE ROOT =====
"""
Toàn bộ mạch điện tử (Aggregate Root)
Đại diện cho toàn bộ mạch điện tử, kiểm soát và xác thực tất cả thành phần: linh kiện, dây nối (net), cổng (port), ràng buộc (constraint).
- Đảm bảo bất biến (immutability):
    * Sử dụng dataclass(frozen=True) và MappingProxyType để ngăn chặn sửa đổi trực tiếp từ bên ngoài.
    * Mọi trường dữ liệu đều là immutable, bảo vệ Source of Truth (SOA).
- Kiểm soát toàn vẹn dữ liệu:
    * Xác thực tên mạch không được rỗng.
    * Mỗi component/net/port/constraint phải có key khớp với id/name.
    * Net: mọi chân phải tham chiếu đúng linh kiện và pin.
    * Port: phải kết nối đến net hợp lệ.
    * Không có pin nào thuộc nhiều net (duy nhất).
- Chuyển đổi object thành dict đơn giản để truyền qua API, lưu trữ hoặc hiển thị UI.

Input:
    - name: str
    - id: Optional[str]
    - _components: Dict[str, Component] (key là id linh kiện)
    - _nets: Dict[str, Net] (key là tên net)
    - _ports: Dict[str, Port] (key là tên port)
    - _constraints: Dict[str, Constraint] (key là tên constraint)
Output:
    - dict: {
        "name": str,
        "components": list[dict],
        "nets": list[dict],
        "ports": list[dict],
        "constraints": list[dict]
    }

Validation:
    - name: không được rỗng
    - Mỗi component/net/port/constraint phải có key khớp với id/name
    - Net: mọi chân phải tham chiếu đúng linh kiện và pin
    - Port: phải kết nối đến net hợp lệ
    - Không có pin nào thuộc nhiều net

Bất biến:
    - Ngăn chặn mutable phá vỡ SOA
    - Toàn bộ trường là immutable (frozen=True, MappingProxyType)
    - Không cho phép sửa đổi trực tiếp từ bên ngoài

Chuyển đổi:
    - to_dict(): Chuyển object thành dict đơn giản để truyền qua API, lưu trữ hoặc hiển thị UI.
"""
@dataclass(frozen=True)
class Circuit:
    name: str
    id: Optional[str] = None
    _components: Dict[str, Component] = field(default_factory=dict)     # component_id -> Component: key là id linh kiện, value la Component
    _nets: Dict[str, Net] = field(default_factory=dict)                 # net_name -> Net : key la ten net, value la Net
    _ports: Dict[str, Port] = field(default_factory=dict)               # port_name -> Port : key la ten port, value la Port
    _constraints: Dict[str, Constraint] = field(default_factory=dict)   # constraint_name -> Constraint : key la ten constraint, value la Constraint
    
    def __post_init__(self):
        # Tạo bản copy immutable để ngăn chặn mutable phá vỡ SOA
        object.__setattr__(self, "_components", dict(self._components))
        object.__setattr__(self, "_nets", dict(self._nets))
        object.__setattr__(self, "_ports", dict(self._ports))
        object.__setattr__(self, "_constraints", dict(self._constraints))
        # Bọc Dict bằng MappingProxyType để biến thành read-only
        object.__setattr__(self, "components", MappingProxyType(self._components))
        object.__setattr__(self, "nets", MappingProxyType(self._nets))
        object.__setattr__(self, "ports", MappingProxyType(self._ports))
        object.__setattr__(self, "constraints", MappingProxyType(self._constraints))
        # Thực hiện xác thực cơ bản
        self.validate_basic()

    def validate_basic(self) -> None:
        errors = []     # Thu thập lỗi
        
        if not self.name:
            errors.append("Tên mạch không được trống")

        for comp_id, comp in self.components.items():
            if comp_id != comp.id:
                errors.append(f"Component key '{comp_id}' không khớp với id của Component: '{comp.id}'")

        for net_key, net_obj in self.nets.items():
            if net_key != net_obj.name:
                errors.append(f"Net key '{net_key}' không khớp với tên của Net: '{net_obj.name}'")

        for port_key, port_obj in self.ports.items():
            if port_key != port_obj.name:
                errors.append(f"Port key '{port_key}' không khớp với tên của Port: '{port_obj.name}'")
        
        for constraint_key, constraint in self.constraints.items():
            if constraint_key != constraint.name:
                errors.append(f"Constraint key '{constraint_key}' không khớp với tên của Constraint: '{constraint.name}'")
        
        for net_key, net_obj in self.nets.items():
            for ref in net_obj.connected_pins:
                if ref.component_id not in self.components:
                    errors.append(f"Net '{net_key}' tham chiếu đến linh kiện không tồn tại: '{ref.component_id}'")
                else:
                    comp = self.components[ref.component_id]
                    if ref.pin_name not in comp.pins:
                        errors.append(f"Net '{net_key}' tham chiếu đến pin không tồn tại: '{ref.pin_name}' trên linh kiện '{ref.component_id}'")
        
        for port_key, port_obj in self.ports.items():
            if port_obj.net_name not in self.nets:
                errors.append(f"Port '{port_key}' tham chiếu đến net không tồn tại: '{port_obj.net_name}'")
        
        pin_to_net = {}     # kiểm tra trùng lặp
        for net_key, net_obj in self.nets.items():
            for ref in net_obj.connected_pins:
                pin_key = (ref.component_id, ref.pin_name)
                if pin_key in pin_to_net:
                    errors.append(
                        f"Pin '{ref.component_id}.{ref.pin_name}' bị tham chiếu bởi nhiều net: "
                        f"'{pin_to_net[pin_key]}' và '{net_key}'"
                    )
                pin_to_net[pin_key] = net_key
        
        if errors:
            error_message = "Xác thực mạch thất bại:\n" + "\n".join([f"  - {e}" for e in errors])
            raise ValueError(error_message)

    def get_component(self, component_id: str) -> Optional[Component]:
        return self.components.get(component_id)
    
    def get_net(self, net_name: str) -> Optional[Net]:
        return self.nets.get(net_name)

    def with_component(self, component: Component) -> "Circuit":
        new_components = dict(self.components)      # Tạo bản copy mutable
        new_components[component.id] = component    # Thêm/sửa component
        
        return Circuit(
            name=self.name,
            _components=new_components,
            _nets=dict(self.nets),              # Luôn tạo bản copy mới từ MappingProxyType để đảm bảo bất biến, không reuse reference _nets
            _ports=dict(self.ports),            # Tương tự, copy từ proxy để tránh mutable phá vỡ SOA
            _constraints=dict(self.constraints) # Copy từ proxy, không dùng reference trực tiếp
        )
    
    def to_dict(self): 
        return {
            "name": self.name,
            "components": [comp.to_dict() for comp in self.components.values()],
            "nets": [net.to_dict() for net in self.nets.values()],
            "ports": [port.to_dict() for port in self._ports.values()],
            "constraints": [constraint.to_dict() for constraint in self._constraints.values()],
        }