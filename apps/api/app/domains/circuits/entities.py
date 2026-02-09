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
typing: cung cấp thông tin về kiểu dữ liệu cho các biến, hàm, hỗ trợ syntax ":" cho biến và "->" cho giá trị trả về của hàm.
 * Dict[str, param value]: dùng key là str và value là object. VD: {"resistance": ParameterValue(1000, "Ohm")}.
 * Optional[str]: biến có thể là str hoặc None. VD: {"unit": "Ohm"} hoặc {"unit": None}.
 * Tuple[str, ...]: dùng tuple thay list vì tuple có tính bất biến (không thêm bớt các phần tử sau khi tạo) phù hợp với danh sách Pin linh kiện.
 * Any: sử dụng các trường dữ liệu linh hoạt (giá trị ràng buộc), kiểu dữ liệu có thể tùy ý (int, float, str).
"""

# ====== ENUMS ======
""" Định nghĩa các loại linh kiện
 Điện trở: "resistor"
 Tụ điện: "capacitor"
    Tụ điện phân: "capacitor_polarized"
 Cuộn cảm: "inductor"
 Transistor lưỡng cực: "bjt"
    Transistor lưỡng cực NPN: "bjt_npn"
    Transistor lưỡng cực PNP: "bjt_pnp"
 Transistor hiệu ứng trường: "mosfet"
    Transistor hiệu ứng trường N-channel: "mosfet_n"
    Transistor hiệu ứng trường P-channel: "mosfet_p"
 Op-amp: "opamp"
 Nguồn điện áp: "voltage_source"
 Nguồn dòng điện: "current_source"
 Mass (Ground): "ground"
 Đi-ot: "diode"
 Kết nối: "connector"
 Cổng: "port"
"""
class ComponentType(Enum):
    RESISTOR = "resistor"
    CAPACITOR = "capacitor"
    CAPACITOR_POLARIZED = "capacitor_polarized"
    INDUCTOR = "inductor"
    BJT = "bjt"
    BJT_NPN = "bjt_npn"
    BJT_PNP = "bjt_pnp"
    MOSFET = "mosfet"
    MOSFET_N = "mosfet_n"
    MOSFET_P = "mosfet_p"
    OPAMP = "opamp"
    VOLTAGE_SOURCE = "voltage_source"
    CURRENT_SOURCE = "current_source"
    GROUND = "ground"
    DIODE = "diode"
    CONNECTOR = "connector"
    PORT = "port"

    # ====== helpers ======
    """ Xây dựng bảng ánh xạ alias (tên thay thế) sang ComponentType.
    - mục đích: cho phép nhận diện linh kiện từ nhiều tên khác nhau (tên gốc, tên viết thường, alias ngắn).
    - hỗ trợ nhập dữ liệu linh hoạt, tương thích với nhiều định dạng (json, api, ui ...).
    - chỉ khởi tạo bảng alias khi cần (1 lần), tiết kiệm tài nguyên.
    Returns:
      * giá trị gốc enum ("resistor")
      * tên viết thường ("resistor")
      * tên ngắn phổ biến ("nmos", "pmos", "npn", "pnp" ...)
    """
    # Bảng alias bổ sung (key viết thường)
    _ALIASES = None # sẽ được khởi tạo khi cần, dùng search nhanh.

    """Xây dựng bảng ánh xạ alias → ComponentType (lazy, chỉ chạy 1 lần)."""
    @classmethod
    def _build_aliases(cls) -> Dict[str, "ComponentType"]:
        aliases: Dict[str, ComponentType] = {}
        for member in cls:
            if member.name.startswith("_"):
                continue
            aliases[member.value] = member             # ánh xạ giá trị gốc: "resistor" → RESISTOR
            aliases[member.name.lower()] = member      # ánh xạ tên viết thường: "RESISTOR" → RESISTOR
        
        # Thêm ngoại lệ alias ngắn phổ biến cho json 
        aliases["cap_polarized"] = cls.CAPACITOR_POLARIZED
        aliases["nmos"] = cls.MOSFET_N
        aliases["pmos"] = cls.MOSFET_P
        aliases["npn"] = cls.BJT_NPN
        aliases["pnp"] = cls.BJT_PNP
        return aliases

    """Chuyển đổi chuỗi bất kỳ (tên component, alias, hoa/thường) -> ComponentType chuẩn.
    - hỗ trợ input: enum, str gốc, str hoa/thường, xóa " ".
    - tự động chuẩn hóa về dạng thường, xóa " ".
    - khởi tạo bảng alias (nếu chưa có) để tra cứu nhanh.
    - tìm mapping, trả ComponentType tương ứng.
    - không tìm thấy, báo lỗi kèm danh sách giá trị hợp lệ.
    Args: raw(str): chuỗi tên component/alias.
    Return: component type: enum tương ứng.
    Raises: value error: nếu không tìm thấy mapping.
    """
    @classmethod
    def normalize(cls, raw: str) -> "ComponentType":
        if isinstance(raw, cls):
            return raw
        key = raw.strip().lower()
        
        # Khởi tạo bảng alias nếu chưa có
        if not hasattr(cls, '_alias_table') or cls._alias_table is None:
            cls._alias_table = cls._build_aliases()
        result = cls._alias_table.get(key)
        if result is not None:
            return result
        
        raise ValueError(
            f"ComponentType không hợp lệ: '{raw}'. "
            f"Các giá trị hợp lệ: {sorted(cls._alias_table.keys())}"
        )


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
""" Linh kiện vật lý trong mạch điện tử.
Đại diện cho một linh kiện với các trường:
 * id: định danh duy nhất, không được trống.
 * type: loại linh kiện (ComponentType).
 * pins: danh sách chân, dạng tuple bất biến, tối thiểu 2 chân.
 * parameters: dict các tham số, mỗi giá trị phải là ParameterValue.
 
KiCad Metadata (hỗ trợ pipeline mới với symbol chuẩn KiCad):
 * library_id: định danh thư viện KiCad (VD: "Device", "Amplifier_Operational").
 * symbol_name: tên symbol trong KiCad (VD: "R", "C", "Q_NPN_BCE").
 * footprint: tham chiếu footprint PCB (VD: "Resistor_SMD:R_0805_2012Metric").
 * symbol_version: phiên bản/biến thể của thư viện symbol.
 * render_style: thuộc tính render tùy chỉnh (vị trí, góc xoay, style,...).

Đảm bảo bất biến (immutability) và kiểm tra chặt chẽ:
 * Tất cả trường đều được xác thực khi khởi tạo.
 * Mọi tham số phải là ParameterValue, đúng kiểu dữ liệu.
 * Áp dụng các quy tắc nghiệp vụ: linh kiện phải có tham số bắt buộc (VD: resistor cần resistance).
 * KiCad metadata được validate: library_id yêu cầu symbol_name, các trường phải đúng kiểu.
 * render_style được freeze thành immutable dict.

Input:
 * id: str
 * type: ComponentType
 * pins: tuple[str, ...]
 * parameters: dict[str, ParameterValue]
 * library_id: Optional[str]
 * symbol_name: Optional[str]
 * footprint: Optional[str]
 * symbol_version: Optional[str]
 * render_style: Optional[dict[str, Any]]

Output:
    dict: { 
        "id": str, 
        "type": str, 
        "pins": tuple[str, ...], 
        "parameters": dict[str, dict],
        "library_id": str (nếu có),
        "symbol_name": str (nếu có),
        "footprint": str (nếu có),
        "symbol_version": str (nếu có),
        "render_style": dict (nếu có)
    }

Chuyển đổi object thành dict đơn giản để truyền qua API, lưu trữ hoặc hiển thị UI.
"""
@dataclass(frozen=True)
class Component:
    id: str
    type: ComponentType
    pins: Tuple[str, ...]
    # Ngăn chặn việc immutable bị phá (circuit.component.clear()/circuit.component["R1"]=some_fake_component -> phá vỡ SOA)
    parameters: Dict[str, ParameterValue] = field(default_factory=dict)
    
    # Các trường dữ liệu đặc tả (metadata) trong KiCad phục vụ việc tích hợp và hiển thị linh kiện
    library_id: Optional[str] = None                                      # định dạng thư viện Kicad (thư viện trong folder ..\apps\api\resources\kicad\symbols\version)
    symbol_name: Optional[str] = None                                     # tên ký hiệu linh kiện
    footprint: Optional[str] = None                                       # tham chiếu PCB footprint
    symbol_version: Optional[str] = None                                  # phiên bản thư viện
    render_style: Optional[Dict[str, Any]] = field(default_factory=dict)  # thuộc tính render tùy chỉnh (vị trí, góc xoay, style,...)
    
    def __post_init__(self):
        self._validate_identity()
        self._validate_pins()

        # kiểm tra param val : {"bjt_model": "2N2222"} sai -> phải {"bjt_model": ParameterValue("2N2222")}
        params_copy = dict(self.parameters)
        self._validate_param_types(params_copy)

        # Set lại field với bản copy immutable cho business validation
        object.__setattr__(self, "parameters", MappingProxyType(params_copy))
        self._validate_required_param()
        
        # Xác thực và đóng băng dữ liệu
        self._validate_kicad_metadata()
        
        # Đóng băng render_style để đảm bảo tính bất biến
        if self.render_style:
            render_style_copy = dict(self.render_style)
            object.__setattr__(self, "render_style", MappingProxyType(render_style_copy))
        else:
            object.__setattr__(self, "render_style", MappingProxyType({}))
    
    # hàm kiểm tra id
    def _validate_identity(self):
        if not self.id:
            raise ValueError("ID linh kiện không được trống")
    # hàm kiểm tra pins và số lượng pins
    def _validate_pins(self):
        if not isinstance(self.pins, tuple):
            raise TypeError(f"Pins của {self.id} có dạng là tuple")
        # Connectors, ports, and grounds can have single pin
        single_pin_types = (
            ComponentType.CONNECTOR,
            ComponentType.PORT,
            ComponentType.GROUND,
        )
        if self.type not in single_pin_types:
            if len(self.pins) < 2:
                raise ValueError(f"Linh kiện {self.id} phải có ít nhất hai chân")
        elif len(self.pins) < 1:
            raise ValueError(f"Linh kiện {self.id} phải có ít nhất một chân")
    # hàm kiểm tra kiểu tham số
    def _validate_param_types(self, parameters: dict = None):
        if parameters is None:
            parameters = self.parameters
        for key, val in parameters.items():
            if not isinstance(val, ParameterValue):
                raise TypeError(f"Parameter '{key}' của {self.id} phải là ParameterValue")
    # Nhóm các component type cùng nghiệp vụ (capacitor variants, BJT variants, v.v.)
    _CAPACITOR_FAMILY = {ComponentType.CAPACITOR, ComponentType.CAPACITOR_POLARIZED}
    _BJT_FAMILY = {ComponentType.BJT, ComponentType.BJT_NPN, ComponentType.BJT_PNP}
    _MOSFET_FAMILY = {ComponentType.MOSFET, ComponentType.MOSFET_N, ComponentType.MOSFET_P}

    # hàm kiểm tra tham số bắt buộc theo loại linh kiện
    def _validate_required_param(self):
        if self.type == ComponentType.RESISTOR:
            if "resistance" not in self.parameters:
                raise ValueError(f"Resistor {self.id} phải có tham số resistance")
        if self.type in self._CAPACITOR_FAMILY:
            if "capacitance" not in self.parameters:
                raise ValueError(f"Capacitor {self.id} phải có tham số capacitance")
        if self.type == ComponentType.INDUCTOR:
            if "inductance" not in self.parameters:
                raise ValueError(f"Inductor {self.id} phải có tham số inductance")
        if self.type in self._BJT_FAMILY:
            if "model" not in self.parameters:
                raise ValueError(f"BJT {self.id} phải có tham số model")
        if self.type in self._MOSFET_FAMILY:
            if "model" not in self.parameters:
                raise ValueError(f"MOSFET {self.id} phải có tham số model")
        if self.type == ComponentType.VOLTAGE_SOURCE:
            if "voltage" not in self.parameters:
                raise ValueError(f"Voltage source {self.id} phải có tham số voltage")
    # hàm kiểm tra dữ liệu linh kiện (kicad metadata)
    def _validate_kicad_metadata(self):
        # Nếu symbol_name được cung cấp, library_id phải được cung cấp
        if self.library_id and not self.symbol_name:
            raise ValueError(f"Component {self.id}: library_id được cung cấp nhưng thiếu symbol_name")
        
        # kiểm tra xác thực kiểu dữ liệu metadata (str)
        if self.library_id is not None and not isinstance(self.library_id, str):
            raise TypeError(f"Component {self.id}: library_id phải là str, nhận {type(self.library_id)}")
        if self.symbol_name is not None and not isinstance(self.symbol_name, str):
            raise TypeError(f"Component {self.id}: symbol_name phải là str, nhận {type(self.symbol_name)}")
        if self.footprint is not None and not isinstance(self.footprint, str):
            raise TypeError(f"Component {self.id}: footprint phải là str, nhận {type(self.footprint)}")
        if self.symbol_version is not None and not isinstance(self.symbol_version, str):
            raise TypeError(f"Component {self.id}: symbol_version phải là str, nhận {type(self.symbol_version)}")
        
        # kiểm tra xác thực kiểu dữ liệu render_style (dict)
        if self.render_style is not None and not isinstance(self.render_style, dict):
            raise TypeError(f"Component {self.id}: render_style phải là dict, nhận {type(self.render_style)}")
    # chuyển obj -> dict (API)
    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "type": self.type.value,
            "pins": self.pins,
            "parameters": {key: val.to_dict() for key, val in self.parameters.items()}
        }
        
        # Thêm metadata KiCad nếu có
        if self.library_id:
            result["library_id"] = self.library_id
        if self.symbol_name:
            result["symbol_name"] = self.symbol_name
        if self.footprint:
            result["footprint"] = self.footprint
        if self.symbol_version:
            result["symbol_version"] = self.symbol_version
        if self.render_style and len(self.render_style) > 0:
            result["render_style"] = dict(self.render_style)
        
        return result


""" Dây nối (Net) giữa các chân linh kiện trong mạch điện tử.
Đại diện cho một net với các trường:
 * name: tên net, không được trống.
 * connected_pins: tuple các PinRef, mỗi phần tử là tham chiếu đến một chân linh kiện.

Đảm bảo bất biến (immutability) và kiểm tra chặt chẽ:
 * Tên net phải hợp lệ, không rỗng.
 * Danh sách chân phải là tuple PinRef, tối thiểu 2 chân.
 * Không có chân nào bị lặp lại (mỗi chân chỉ xuất hiện một lần trong net).

Input:
 * name: str
 * connected_pins: tuple[PinRef, ...]

Output:
    dict: { "name": str, "connected_pins": list[dict]}

Chuyển đổi object thành dict đơn giản để truyền qua API, lưu trữ hoặc hiển thị UI.
"""
@dataclass(frozen=True)
class Net:
    name: str
    connected_pins: Tuple[PinRef, ...]
    
    def __post_init__(self):
        self._validate_identity()
        self._validate_pin_count()
        self._validate_pin_refs()
        self._validate_no_duplicate_pins()
    
    # kiểm tra tên
    def _validate_identity(self):
        if not self.name:
            raise ValueError("Tên net không được trống")
    # kiểm tra số lượng chân (ít nhất 1 - validation ≥2 nằm ở rules layer)
    def _validate_pin_count(self):
        if len(self.connected_pins) < 1:
            raise ValueError(f"Net '{self.name}' phải có ít nhất một chân được kết nối (cần ít nhất một PinRef trong connected_pins)")
    # kiểm tra tham chiếu
    def _validate_pin_refs(self):
        for ref in self.connected_pins:
            if not isinstance(ref, PinRef):
                raise TypeError(f"Phần tử '{ref}' trong connected_pins của Net '{self.name}' phải là PinRef, nhận {type(ref)}")
    # kiểm tra trùng chân
    def _validate_no_duplicate_pins(self):
        seen = set()
        for ref in self.connected_pins:
            key = (ref.component_id, ref.pin_name)
            if key in seen:
                raise ValueError(f"Net '{self.name}' có chân '{ref.component_id}.{ref.pin_name}' bị lặp lại nhiều lần trong connected_pins (mỗi chân chỉ được xuất hiện một lần)")
            seen.add(key)
    # chuyển obj -> dict
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
    constraint_type: Optional[str] = None   # structured type: "voltage_range", "current_limit", "power_rating_min", ...
    target: Optional[str] = None            # component/net target: "Q1", "VCC", ...
    min_value: Optional[float] = None       # min bound (nếu có)
    max_value: Optional[float] = None       # max bound (nếu có)

    def __post_init__(self):
        if not self.name:
            raise ValueError("Ràng buộc phải có tên")
        
    def to_dict(self) -> dict:
        result = {
            "name": self.name,
            "value": self.value,
            "unit": self.unit
        }
        if self.constraint_type is not None:
            result["constraint_type"] = self.constraint_type
        if self.target is not None:
            result["target"] = self.target
        if self.min_value is not None:
            result["min_value"] = self.min_value
        if self.max_value is not None:
            result["max_value"] = self.max_value
        return result


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

In/Out:
 * In:
    - name: str
    - id: Optional[str]
    - _components: Dict[str, Component] (key là id linh kiện)
    - _nets: Dict[str, Net] (key là tên net)
    - _ports: Dict[str, Port] (key là tên port)
    - _constraints: Dict[str, Constraint] (key là tên constraint)
 * Out:
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
    
    # Template metadata – lưu nguồn gốc template cho truy vết & học mạch mẫu
    topology_type: Optional[str] = None           # vd: "bjt_common_emitter_voltage_amplifier"
    category: Optional[str] = None                # vd: "bjt", "opamp", "power_amplifier"
    template_id: Optional[str] = None             # vd: "OP-01", "CE-02"
    tags: Tuple[str, ...] = ()                    # vd: ("common-emitter", "voltage-divider-bias")
    description: Optional[str] = None             # mô tả dạng tự nhiên
    parametric: Optional[Dict[str, Any]] = None   # tham số tunable: {"R1": {"resistance": "optional"}, ...}
    pcb_hints: Optional[Dict[str, Any]] = None    # PCB layout hints: keepout_zones, critical_nets, ...
    
    def __post_init__(self):
        # Đóng băng metadata collections (parametric, pcb_hints)
        if self.parametric is not None:
            object.__setattr__(self, "parametric", MappingProxyType(dict(self.parametric)))
        if self.pcb_hints is not None:
            object.__setattr__(self, "pcb_hints", MappingProxyType(dict(self.pcb_hints)))
        # Tạo bản copy immutable để ngăn chặn mutable phá vỡ SOA
        self._freeze_internal_collection()
        # Bọc Dict bằng MappingProxyType để biến thành read-only
        self._expose_read_only_views()
        # Thực hiện xác thực cơ bản
        self.validate_basic()
    
    def _freeze_internal_collection(self):
        object.__setattr__(self, "components", MappingProxyType(self._components))
        object.__setattr__(self, "nets", MappingProxyType(self._nets))
        object.__setattr__(self, "ports", MappingProxyType(self._ports))
        object.__setattr__(self, "constraints", MappingProxyType(self._constraints))
    
    def _expose_read_only_views(self):
        object.__setattr__(self, "components", MappingProxyType(self._components))
        object.__setattr__(self, "nets", MappingProxyType(self._nets))
        object.__setattr__(self, "ports", MappingProxyType(self._ports))
        object.__setattr__(self, "constraints", MappingProxyType(self._constraints))
        
    def validate_basic(self) -> None:
        errors = []     # Thu thập lỗi
        self._validate_identity_and_keys(errors)
        self._validate_references(errors)
        self._validate_unique_connection(errors)
        self._raise_validation_errors(errors)
    
    # kiểm tra tên-key
    def _validate_identity_and_keys(self, errors = list[str]) -> None:
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
    # kiểm tra tham chiếu  
    def _validate_references(self, errors = list[str]) -> None:
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
    # kiểm tra trùng chân
    def _validate_unique_connection(self, errors = list[str]) -> None:
        pin_to_net = {}
        
        # Kiểm tra mỗi pin chỉ thuộc về một net duy nhất
        for net_key, net_obj in self.nets.items():
            for ref in net_obj.connected_pins:
                pin_key = (ref.component_id, ref.pin_name)
                if pin_key in pin_to_net:
                    errors.append(
                        f"Pin '{ref.component_id}.{ref.pin_name}' bị tham chiếu bởi nhiều net: "
                        f"'{pin_to_net[pin_key]}' và '{net_key}'"
                    )
                pin_to_net[pin_key] = net_key
    # báo lỗi 
    def _raise_validation_errors(self, errors: list[str]) -> None:
        if errors:
            error_message = "Xác thực mạch thất bại:\n" + "\n".join([f"  - {e}" for e in errors])
            raise ValueError(error_message)
    # lấy component/net theo id/name
    def get_component(self, component_id: str) -> Optional[Component]:
        return self.components.get(component_id)
    # lấy net theo tên
    def get_net(self, net_name: str) -> Optional[Net]:
        return self.nets.get(net_name)
    # thêm/sửa component, trả về Circuit mới
    def with_component(self, component: Component) -> "Circuit":
        new_components = dict(self.components)      # Tạo bản copy mutable
        new_components[component.id] = component    # Thêm/sửa component
        
        return Circuit(
            name=self.name,
            id=self.id,
            _components=new_components,
            _nets=dict(self.nets),                  # Luôn tạo bản copy mới từ MappingProxyType để đảm bảo bất biến, không reuse reference _nets
            _ports=dict(self.ports),                # Tương tự, copy từ proxy để tránh mutable phá vỡ SOA
            _constraints=dict(self.constraints),    # Copy từ proxy, không dùng reference trực tiếp
            topology_type=self.topology_type,
            category=self.category,
            template_id=self.template_id,
            tags=self.tags,
            description=self.description,
            parametric=dict(self.parametric) if self.parametric else None,
            pcb_hints=dict(self.pcb_hints) if self.pcb_hints else None,
        )
    # chuyển obj -> dict
    def to_dict(self) -> dict:
        result = {
            "name": self.name,
            "components": [comp.to_dict() for comp in self.components.values()],
            "nets": [net.to_dict() for net in self.nets.values()],
            "ports": [port.to_dict() for port in self._ports.values()],
            "constraints": [constraint.to_dict() for constraint in self._constraints.values()],
        }
        if self.id is not None:
            result["id"] = self.id
        if self.topology_type is not None:
            result["topology_type"] = self.topology_type
        if self.category is not None:
            result["category"] = self.category
        if self.template_id is not None:
            result["template_id"] = self.template_id
        if self.tags:
            result["tags"] = list(self.tags)
        if self.description is not None:
            result["description"] = self.description
        if self.parametric is not None:
            result["parametric"] = dict(self.parametric)
        if self.pcb_hints is not None:
            result["pcb_hints"] = dict(self.pcb_hints)
        return result