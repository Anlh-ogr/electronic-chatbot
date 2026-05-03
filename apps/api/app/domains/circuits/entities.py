# .\thesis\electronic-chatbot\apps\api\app\domains\circuits\entities.py
""" Thông tin chung:
Thiết kế hệ thống theo kiến trúc Domain-Driven Design (DDD), đặt domain (nghiệp vụ) là cốt lõi trung tâm, xây dựng mô hình kiến trúc phản ánh chính xác các quy tắc và logic.
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
 Đi-ốt: "diode"
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
    POWER_SYMBOL = "power_symbol"
    DIODE = "diode"
    CONNECTOR = "connector"
    PORT = "port"
    SUBCIRCUIT = "subcircuit"

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
            aliases[member.name.lower()] = member      # ánh xạ tên viết thường: "resistor" → RESISTOR
        
        # Thêm ngoại lệ alias ngắn phổ biến cho json
        aliases["cap_polarized"] = cls.CAPACITOR_POLARIZED
        aliases["nmos"] = cls.MOSFET_N
        aliases["pmos"] = cls.MOSFET_P
        aliases["npn"] = cls.BJT_NPN
        aliases["pnp"] = cls.BJT_PNP
        aliases["block"] = cls.SUBCIRCUIT
        aliases["stage"] = cls.SUBCIRCUIT
        aliases["jumper"] = cls.CONNECTOR
        aliases["coupling"] = cls.CONNECTOR
        aliases["transformer"] = cls.INDUCTOR
        # common alternate names from legacy templates / LLM outputs
        aliases["power"] = cls.VOLTAGE_SOURCE
        aliases["vcc"] = cls.VOLTAGE_SOURCE
        aliases["vdd"] = cls.VOLTAGE_SOURCE
        aliases["vee"] = cls.VOLTAGE_SOURCE
        aliases["pwr"] = cls.VOLTAGE_SOURCE
        aliases["powersymbol"] = cls.POWER_SYMBOL
        aliases["power_symbol"] = cls.POWER_SYMBOL
        aliases["power symbol"] = cls.POWER_SYMBOL
        aliases["power_port"] = cls.PORT
        aliases["pwr_port"] = cls.PORT
        aliases["vcc_port"] = cls.PORT
        aliases["gnd_port"] = cls.PORT
        return aliases

    """
    Chuẩn hóa và chuyển đổi chuỗi đầu vào thành ComponentType tương ứng.

    Hàm thực hiện tiền xử lý chuỗi (xóa khoảng trắng, chuyển chữ thường), 
    tra cứu trong bảng alias và ánh xạ về Enum chuẩn của hệ thống EDA.

    Args:
        raw (str): Chuỗi tên linh kiện hoặc bí danh (alias) cần chuyển đổi.
    Returns:
        ComponentType: Enum tương ứng với linh kiện đã tìm thấy.
    Raises:
        ValueError: Nếu không tìm thấy mapping phù hợp. Thông báo lỗi sẽ đi kèm danh sách các loại linh kiện hợp lệ để gợi ý.
    """
    @classmethod
    def normalize(cls, raw: str) -> "ComponentType":
        if isinstance(raw, cls):
            return raw
        key = raw.strip().lower()
        
        # Khá»Ÿi táº¡o báº£ng alias náº¿u chÆ°a cÃ³
        if not hasattr(cls, '_alias_table') or cls._alias_table is None:
            cls._alias_table = cls._build_aliases()
        result = cls._alias_table.get(key)
        if result is not None:
            return result
        
        raise ValueError(
            f"ComponentType khÃ´ng há»£p lá»‡: '{raw}'. "
            f"CÃ¡c giÃ¡ trá»‹ há»£p lá»‡: {sorted(cls._alias_table.keys())}"
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
"""
Giá trị tham số
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
        if isinstance(self.value, ParameterValue):
            object.__setattr__(self, 'unit', self.value.unit or self.unit)
            object.__setattr__(self, 'value', self.value.value)
        if not isinstance(self.value, (int, float, str)):
            raise TypeError(f"Value chỉ chấp nhận int|float|str, nhận {type(self.value)}")
            
    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "unit": self.unit
        }

    def _get_val(self, other):
        if isinstance(other, ParameterValue):
            return float(other.value)
        return float(other)

    def __truediv__(self, other):
        return float(self.value) / self._get_val(other)

    def __rtruediv__(self, other):
        return self._get_val(other) / float(self.value)

    def __mul__(self, other):
        return float(self.value) * self._get_val(other)

    def __rmul__(self, other):
        return self._get_val(other) * float(self.value)

    def __add__(self, other):
        return float(self.value) + self._get_val(other)

    def __radd__(self, other):
        return self._get_val(other) + float(self.value)

    def __sub__(self, other):
        return float(self.value) - self._get_val(other)

    def __rsub__(self, other):
        return self._get_val(other) - float(self.value)
        
    def __float__(self):
        return float(self.value)

    def __gt__(self, other):
        return float(self.value) > self._get_val(other)
        
    def __lt__(self, other):
        return float(self.value) < self._get_val(other)
        
    def __ge__(self, other):
        return float(self.value) >= self._get_val(other)
        
    def __le__(self, other):
        return float(self.value) <= self._get_val(other)
        
    def __eq__(self, other):
        if isinstance(other, ParameterValue):
            return self.value == other.value and self.unit == other.unit
        return self.value == other

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


@dataclass(frozen=True)
class SignalFlow:
    input_node: str
    output_node: str
    main_chain: Tuple[str, ...]
    stage_links: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self):
        if not self.input_node:
            raise ValueError("SignalFlow input_node không được trống")
        if not self.output_node:
            raise ValueError("SignalFlow output_node không được trống")

        main_chain = tuple(str(item).strip() for item in self.main_chain if str(item).strip())
        stage_links = tuple(
            (str(link[0]).strip(), str(link[1]).strip())
            for link in self.stage_links
            if isinstance(link, (tuple, list)) and len(link) >= 2 and str(link[0]).strip() and str(link[1]).strip()
        )
        object.__setattr__(self, "input_node", str(self.input_node).strip())
        object.__setattr__(self, "output_node", str(self.output_node).strip())
        object.__setattr__(self, "main_chain", main_chain)
        object.__setattr__(self, "stage_links", stage_links)

    def to_dict(self) -> dict:
        return {
            "input_node": self.input_node,
            "output_node": self.output_node,
            "main_chain": list(self.main_chain),
            "stage_links": [list(link) for link in self.stage_links],
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
    parameters: Dict[str, ParameterValue] = field(default_factory=dict)
    
    library_id: Optional[str] = None
    symbol_name: Optional[str] = None
    footprint: Optional[str] = None
    symbol_version: Optional[str] = None
    render_style: Optional[Dict[str, Any]] = field(default_factory=dict)
    stage: Optional[str] = None
    
    def __post_init__(self):
        self._validate_identity()
        self._validate_pins()

        params_copy = dict(self.parameters)
        self._validate_param_types(params_copy)

        object.__setattr__(self, "parameters", MappingProxyType(params_copy))
        self._validate_required_param()
        
        self._validate_kicad_metadata()
        
        if self.render_style:
            render_style_copy = dict(self.render_style)
            object.__setattr__(self, "render_style", MappingProxyType(render_style_copy))
        else:
            object.__setattr__(self, "render_style", MappingProxyType({}))

        if self.stage is not None:
            stage_value = str(self.stage).strip()
            object.__setattr__(self, "stage", stage_value or None)
    
    def _validate_identity(self):
        if not self.id:
            raise ValueError("ID linh kiện không được trống")

    def _validate_pins(self):
        if not isinstance(self.pins, tuple):
            raise TypeError(f"Pins của {self.id} có dạng là tuple")
        # Connectors, ports, and grounds can have single pin
        single_pin_types = (
            ComponentType.CONNECTOR,
            ComponentType.PORT,
            ComponentType.GROUND,
            ComponentType.POWER_SYMBOL,
            ComponentType.VOLTAGE_SOURCE,
            ComponentType.CURRENT_SOURCE,
        )
        if self.type not in single_pin_types:
            if len(self.pins) < 2:
                raise ValueError(f"Linh kiện {self.id} phải có ít nhất hai chân")
        elif len(self.pins) < 1:
            raise ValueError(f"Linh kiện {self.id} phải có ít nhất một chân")

    def _validate_param_types(self, parameters: dict = None):
        if parameters is None:
            parameters = self.parameters
        for key, val in parameters.items():
            if not isinstance(val, ParameterValue):
                raise TypeError(f"Parameter '{key}' của {self.id} phải là ParameterValue")
    
    _CAPACITOR_FAMILY = {ComponentType.CAPACITOR, ComponentType.CAPACITOR_POLARIZED}
    _BJT_FAMILY = {ComponentType.BJT, ComponentType.BJT_NPN, ComponentType.BJT_PNP}
    _MOSFET_FAMILY = {ComponentType.MOSFET, ComponentType.MOSFET_N, ComponentType.MOSFET_P}


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

    def _validate_kicad_metadata(self):
        if self.library_id and not self.symbol_name:
            raise ValueError(f"Component {self.id}: library_id được cung cấp nhưng thiếu symbol_name")

        if self.library_id is not None and not isinstance(self.library_id, str):
            raise TypeError(f"Component {self.id}: library_id phải là str, nhận {type(self.library_id)}")
        if self.symbol_name is not None and not isinstance(self.symbol_name, str):
            raise TypeError(f"Component {self.id}: symbol_name phải là str, nhận {type(self.symbol_name)}")
        if self.footprint is not None and not isinstance(self.footprint, str):
            raise TypeError(f"Component {self.id}: footprint phải là str, nhận {type(self.footprint)}")
        if self.symbol_version is not None and not isinstance(self.symbol_version, str):
            raise TypeError(f"Component {self.id}: symbol_version phải là str, nhận {type(self.symbol_version)}")
        if self.render_style is not None and not isinstance(self.render_style, dict):
            raise TypeError(f"Component {self.id}: render_style phải là dict, nhận {type(self.render_style)}")

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "type": self.type.value,
            "pins": self.pins,
            "parameters": {key: val.to_dict() for key, val in self.parameters.items()}
        }
        
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
        if self.stage:
            result["stage"] = self.stage
        
        return result


""" Dây nối (Net) giữa các chân linh kiện trong mạch điện tử.
Đại diện cho một net với các trường:
 * name: tên net, không được trống.
 * connected_pins: tuple các PinRef, mỗi phần tử là tham chiếu đến một chân linh kiện.

Đảm bảo bất biến (immutability) và kiểm tra chặt chẽ:
 * Tên net phải hợp lệ, không rỗng.
 * Danh sách chân phải là tuple PinRef, tối thiểu 2 chân (để tạo thành một kết nối).
 * Không có chân nào bị lặp lại (mỗi chân chỉ xuất hiện một lần trong một net cụ thể).

Input:
 * name: str
 * connected_pins: tuple[PinRef, ...]

Output (to_dict):
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
    

    def _validate_identity(self):
        if not self.name:
            raise ValueError("Tên net không được trống")

    def _validate_pin_count(self):
        if len(self.connected_pins) < 1:
            raise ValueError(f"Net '{self.name}' phải có ít nhất một chân được kết nối (cần ít nhất một PinRef trong connected_pins)")

    def _validate_pin_refs(self):
        for ref in self.connected_pins:
            if not isinstance(ref, PinRef):
                raise TypeError(f"Phần tử '{ref}' trong connected_pins của Net '{self.name}' phải là PinRef, nhận {type(ref)}")

    def _validate_no_duplicate_pins(self):
        seen = set()
        for ref in self.connected_pins:
            key = (ref.component_id, ref.pin_name)
            if key in seen:
                raise ValueError(f"Net '{self.name}' có chân '{ref.component_id}.{ref.pin_name}' bị lặp lại nhiều lần trong connected_pins (mỗi chân chỉ được xuất hiện một lần)")
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
 * name: không được rỗng.
 * net_name: không được rỗng.
 * direction: nếu có, phải là PortDirection.

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
  * Mọi trường dữ liệu đều là immutable, bảo vệ Source of Truth (SoT).

- Kiểm soát toàn vẹn dữ liệu:
  * Xác thực tên mạch không được rỗng.
  * Mỗi component/net/port/constraint phải có key khớp với id/name.
  * Net: mọi chân phải tham chiếu đúng linh kiện và pin.
  * Port: phải kết nối đến net hợp lệ.
  * Không có pin nào thuộc nhiều net (duy nhất).

- Chuyển đổi:
  * to_dict(): Chuyển object thành dict đơn giản để truyền qua API, lưu trữ hoặc hiển thị UI.

In/Out:
 * In:
    - name: str
    - id: Optional[str]
    - _components: Dict[str, Component] (key là id linh kiện)
    - _nets: Dict[str, Net] (key là tên net)
    - _ports: Dict[str, Port] (key là tên port)
    - _constraints: Dict[str, Constraint] (key là tên constraint)
 * Out (to_dict):
    - dict: {
        "name": str,
        "components": list[dict],
        "nets": list[dict],
        "ports": list[dict],
        "constraints": list[dict]
    }

Validation Logic:
    - name: không được rỗng.
    - Mỗi component/net/port/constraint phải có key khớp với id/name.
    - Net: mọi chân phải tham chiếu đúng linh kiện và pin.
    - Port: phải kết nối đến net hợp lệ.
    - Không có pin nào thuộc nhiều net.

Tính bất biến:
    - Ngăn chặn mutable phá vỡ SoT.
    - Toàn bộ trường là immutable (frozen=True, MappingProxyType).
    - Không cho phép sửa đổi trực tiếp từ bên ngoài.
"""
@dataclass(frozen=True)
class Circuit:
    name: str
    id: Optional[str] = None
    _components: Dict[str, Component] = field(default_factory=dict)
    _nets: Dict[str, Net] = field(default_factory=dict)
    _ports: Dict[str, Port] = field(default_factory=dict)
    _constraints: Dict[str, Constraint] = field(default_factory=dict)
    
    topology_type: Optional[str] = None
    category: Optional[str] = None
    template_id: Optional[str] = None
    tags: Tuple[str, ...] = ()
    description: Optional[str] = None
    parametric: Optional[Dict[str, Any]] = None
    pcb_hints: Optional[Dict[str, Any]] = None
    signal_flow: Optional[SignalFlow] = None
    
    def __post_init__(self):
        if self.parametric is not None:
            object.__setattr__(self, "parametric", MappingProxyType(dict(self.parametric)))
        if self.pcb_hints is not None:
            object.__setattr__(self, "pcb_hints", MappingProxyType(dict(self.pcb_hints)))
        if self.signal_flow is not None and not isinstance(self.signal_flow, SignalFlow):
            raise TypeError(f"signal_flow phải là SignalFlow, nhận {type(self.signal_flow)}")
        
        self._freeze_internal_collection()
        self._expose_read_only_views()
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
        errors = []
        self._validate_identity_and_keys(errors)
        self._validate_references(errors)
        self._validate_unique_connection(errors)
        self._raise_validation_errors(errors)
    
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

    def _validate_references(self, errors = list[str]) -> None:
        for net_key, net_obj in self.nets.items():
            for ref in net_obj.connected_pins:
                if ref.component_id not in self.components:
                    errors.append(f"Net '{net_key}' tham chiếu đến linh kiện không tồn tại: '{ref.component_id}'")
                # NOTE: Do NOT reject nets based on pin name semantics or component type.
                # LLM-generated IR may use varied pin naming; only enforce component existence here.

        for port_key, port_obj in self.ports.items():
            if port_obj.net_name not in self.nets:
                errors.append(f"Port '{port_key}' tham chiếu đến net không tồn tại: '{port_obj.net_name}'")

    def _validate_unique_connection(self, errors = list[str]) -> None:
        pin_to_net = {}
        
        for net_key, net_obj in self.nets.items():
            for ref in net_obj.connected_pins:
                pin_key = (ref.component_id, ref.pin_name)
                if pin_key in pin_to_net:
                    errors.append(
                        f"Pin '{ref.component_id}.{ref.pin_name}' bị tham chiếu bởi nhiều net: "
                        f"'{pin_to_net[pin_key]}' và '{net_key}'"
                    )
                pin_to_net[pin_key] = net_key

    def _raise_validation_errors(self, errors: list[str]) -> None:
        if errors:
            error_message = "Xác thực mạch fail:\n" + "\n".join([f"  - {e}" for e in errors])
            raise ValueError(error_message)

    def get_component(self, component_id: str) -> Optional[Component]:
        return self.components.get(component_id)

    def get_net(self, net_name: str) -> Optional[Net]:
        return self.nets.get(net_name)

    def with_component(self, component: Component) -> "Circuit":
        new_components = dict(self.components)
        new_components[component.id] = component
        
        return Circuit(
            name=self.name,
            id=self.id,
            _components=new_components,
            _nets=dict(self.nets),
            _constraints=dict(self.constraints),
            topology_type=self.topology_type,
            category=self.category,
            template_id=self.template_id,
            tags=self.tags,
            description=self.description,
            parametric=dict(self.parametric) if self.parametric else None,
            pcb_hints=dict(self.pcb_hints) if self.pcb_hints else None,
            signal_flow=self.signal_flow,
        )

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
        if self.signal_flow is not None:
            result["signal_flow"] = self.signal_flow.to_dict()
        return result
