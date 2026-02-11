# .\thesis\electronic-chatbot\apps\api\app\domains\circuits\builder\common.py
""" Công cụ chung và cấu trúc dùng cho builder templates.
 * PreferredSeries: chứa E series cho linh kiện
 * AmplifierTopology: danh sách topology mạch khuếch đại
 * ComponentMetadata: metadata hỗ trợ KiCad integration (library_id, symbol_name, footprint ...)
 * PCBHints: gợi ý layout PCB cho routing và placement
 * BuildOptions: tùy chọn build cho việc sinh mạch
 * ComponentCalculator: hàm hỗ trợ tính toán giá trị linh kiện
 * KiCadMetadata: ánh xạ metadata linh kiện cho KiCad integration
 * PCBHintProvider: factory tạo gợi ý layout PCB
"""

import math
from dataclasses import dataclass, field
from typing import Dict, Literal, Optional, Tuple, Any, List
from enum import Enum

""" Thư viện sử dụng:
math: sử dụng các hàm toán học để triển khai component calculator tính toán giá trị.
_dataclass: định nghĩa các cấu trúc dữ liệu như BuildOptions, PCBHints, ComponentMetadata.
_field: khởi tạo các trường dữ liệu mặc định trong dataclass.
typing: cung cấp các kiểu dữ liệu như Dict, List, Optional, Literal để định nghĩa kiểu cho các trường dữ liệu.
enum: định nghĩa các Enum như PreferredSeries, AmplifierTopology để liệt kê các giá trị cố định.
"""


""" Tạo dãy giá trị chuẩn cho linh kiện điện tử 
 * E6 : 6 giá trị trên mỗi thập phân - chuẩn cơ bản
 * E12: 12 giá trị trên mỗi thập phân - chuẩn phổ biến
 * E24: 24 giá trị trên mỗi thập phân - chuẩn chi tiết
 * E96: 96 giá trị trên mỗi thập phân - chuẩn cao cấp
"""
class PreferredSeries(Enum):
    E6 = [10, 15, 22, 33, 47, 68]
    E12 = [10, 12, 15, 18, 22, 27, 33, 39, 47, 56, 68, 82]
    E24 = [10, 11, 12, 13, 15, 16, 18, 20, 22, 24, 27, 30, 33, 36, 39, 43, 47, 51, 56, 62, 68, 75, 82, 91]
    E96 = [10, 10.2, 10.5, 10.7, 11.0, 11.3, 11.5, 11.8, 12.1, 12.4, 12.7, 13.0, 13.3, 13.7, 14.0, 14.3,
           14.7, 15.0, 15.4, 15.8, 16.2, 16.5, 16.9, 17.4, 17.8, 18.2, 18.7, 19.1, 19.6, 20.0, 20.5, 21.0,
           21.5, 22.1, 22.6, 23.2, 23.7, 24.3, 24.9, 25.5, 26.1, 26.7, 27.4, 28.0, 28.7, 29.4, 30.1, 30.9,
           31.6, 32.4, 33.2, 34.0, 34.8, 35.7, 36.5, 37.4, 38.3, 39.2, 40.2, 41.2, 42.2, 43.2, 44.2, 45.3,
           46.4, 47.5, 48.7, 49.9, 51.1, 52.3, 53.6, 54.9, 56.2, 57.6, 59.0, 60.4, 61.9, 63.4, 64.9, 66.5,
           68.1, 69.8, 71.5, 73.2, 75.0, 76.8, 78.7, 80.6, 82.5, 84.5, 86.6, 88.7, 90.9, 93.1, 95.3, 97.6]


""" Hỗ trợ các topology mạch khuếch đại phổ biến trong thiết kế."""
class AmplifierTopology(Enum):
    # BJT Topologies
    BJT_CE = "bjt_common_emitter"
    BJT_CC = "bjt_common_collector"
    BJT_CB = "bjt_common_base"
    
    # FET/MOSFET Topologies
    MOSFET_CS = "mosfet_common_source"
    MOSFET_CD = "mosfet_common_drain"
    MOSFET_CG = "mosfet_common_gate"
    
    # Op-Amp Configurations
    OPAMP_INVERTING = "opamp_inverting"
    OPAMP_NON_INVERTING = "opamp_non_inverting"
    OPAMP_DIFFERENTIAL = "opamp_differential"
    OPAMP_INSTRUMENTATION = "opamp_instrumentation"
    
    # Operation Classes
    CLASS_A_POWER = "class_a_power_amp"
    CLASS_AB_PUSH_PULL = "class_ab_push_pull"
    CLASS_B_PUSH_PULL = "class_b_push_pull"
    CLASS_C_TUNED = "class_c_tuned"
    CLASS_D_SWITCHING = "class_d_switching"
    
    # Special Amplifiers
    DARLINGTON_PAIR = "darlington_pair"
    MULTI_STAGE_CASCADE = "multi_stage_cascade"


""" Metadata cho component - hỗ trợ KiCad integration.
Lưu trữ thông tin nhận diện và hiển thị linh kiện cho các trình thiết kế mạch (như KiCad), giúp tự động ánh xạ model linh kiện sang symbol, footprint, và các thuộc tính hiển thị khác.
Args:
 * library_id (str): Tên thư viện hoặc loại linh kiện trong schematic library (VD: "Device", "Amplifier_Operational").
 * symbol_name (str): Tên symbol trong thư viện schematic (VD: "Q_NPN_BCE", "LM741").
 * footprint (Optional[str]): Tên footprint cho layout PCB (VD: "Package_TO_SOT_THT:TO-92_Inline"). Có thể None nếu không yêu cầu.
 * symbol_version (Optional[str]): Phiên bản symbol (nếu có), dùng để phân biệt các revision của symbol trong thư viện.
 * render_style (Dict[str, Any]): Các thuộc tính mở rộng cho hiển thị (màu, style, orientation, ...), cho phép tùy biến khi render schematic hoặc export.
"""
@dataclass
class ComponentMetadata:
    library_id: str
    symbol_name: str
    footprint: Optional[str] = None
    symbol_version: Optional[str] = None
    render_style: Dict[str, Any] = field(default_factory=dict)


""" PCB layout hints cho component hoặc net.
Cung cấp các gợi ý về layout, routing, và các ràng buộc vật lý cho từng linh kiện hoặc lưới kết nối trên PCB, giúp tối ưu hóa thiết kế mạch in (PCB) tự động hoặc bán tự động.
Args:
 * layer (Optional[str]): Lớp PCB mong muốn cho đối tượng ("F.Cu" - mặt trên, "B.Cu" - mặt dưới, ...).
 * trace_width (Optional[float]): Độ rộng đường mạch (mm), ảnh hưởng đến khả năng chịu dòng và nhiễu.
 * clearance (Optional[float]): Khoảng cách tối thiểu đến các đối tượng khác (mm), đảm bảo an toàn điện và tiêu chuẩn sản xuất.
 * via_size (Optional[float]): Kích thước lỗ via (mm) nếu cần chuyển lớp.
 * keepout_zone (Optional[Tuple[float, float, float, float]]): Vùng cấm layout (tọa độ x, y, width, height) để tránh đặt linh kiện hoặc đường mạch.
 * thermal_relief (bool): Có bật thermal relief cho pad/via không (giúp dễ hàn, giảm stress nhiệt).
 * notes (List[str]): Ghi chú bổ sung cho designer hoặc tool layout (ví dụ: "Power net", "High-Z signal", ...).
"""
@dataclass
class PCBHints:
    layer: Optional[str] = None
    trace_width: Optional[float] = None
    clearance: Optional[float] = None
    via_size: Optional[float] = None
    keepout_zone: Optional[Tuple[float, float, float, float]] = None
    thermal_relief: bool = False
    notes: List[str] = field(default_factory=list)


""" Build options cho amplifier.
Cho phép cấu hình các đặc điểm build mạch như có ghép tụ đầu vào/ra, bypass, lựa chọn series linh kiện, style layout, v.v. để phù hợp với mục đích thiết kế, kiểm thử hoặc sản xuất.
Args:
 * include_input_coupling (bool): Có thêm tụ ghép đầu vào (CIN) không (lọc DC, chống nhiễu).
 * include_output_coupling (bool): Có thêm tụ ghép đầu ra (COUT) không (lọc DC, bảo vệ tải).
 * include_bypass_caps (bool): Có thêm tụ bypass cho RE/RS không (tăng gain, ổn định bias).
 * include_pcb_hints (bool): Có sinh kèm các gợi ý layout PCB (PCBHints) cho từng linh kiện/net không.
 * layout_style (Literal["compact", "textbook", "professional"]): Kiểu layout mạch (compact: nhỏ gọn, textbook: chuẩn sách giáo khoa, professional: tối ưu hóa thực tế).
 * resistor_series (PreferredSeries): Series giá trị chuẩn cho điện trở (E6, E12, E24, E96).
 * capacitor_series (PreferredSeries): Series giá trị chuẩn cho tụ điện (E6, E12, E24, E96).
 * add_test_points (bool): Có thêm các điểm test (test point) trên mạch không (hỗ trợ đo kiểm).
 * add_power_protection (bool): Có thêm mạch bảo vệ nguồn (diode, fuse, ...) không.
"""
@dataclass
class BuildOptions:
    include_input_coupling: bool = True
    include_output_coupling: bool = True
    include_bypass_caps: bool = True
    include_pcb_hints: bool = False
    layout_style: Literal["compact", "textbook", "professional"] = "textbook"
    resistor_series: PreferredSeries = PreferredSeries.E12
    capacitor_series: PreferredSeries = PreferredSeries.E12
    add_test_points: bool = False
    add_power_protection: bool = True


""" Cấu hình cho Power Amplifiers (Class A, AB, B, C, D).
Args:
 * amp_class: Loại class (A, AB, B, C, D).
 * power_output: Công suất đầu ra mục tiêu (W).
 * load_impedance: Trở kháng tải (Ω, thường là loa 8Ω).
 * vcc: Điện áp nguồn (V).
 * efficiency_target: Hiệu suất mục tiêu.
 * frequency: Tần số hoạt động (Hz). Class C: tần số cộng hưởng RF (None → 1MHz). Class D: tần số cắt LC filter (None → 30kHz).
 * output_devices: Danh sách model transistor/mosfet output.
 * driver_devices: Danh sách model transistor/mosfet driver.
 * resistors: Override giá trị điện trở.
 * capacitors: Override giá trị tụ điện.
 * build: Tùy chọn build chi tiết.
"""
@dataclass
class PowerAmpConfig:
    amp_class: Literal["A", "AB", "B", "C", "D"]
    power_output: float = 1.0       # W
    load_impedance: float = 8.0     # Ω (speaker load)
    vcc: float = 24.0               # V
    efficiency_target: float = 0.5  # 50% efficiency
    frequency: Optional[float] = None  # Hz — Class C: f0 cộng hưởng RF, Class D: f_cutoff LC filter
    # ghi đè component
    output_devices: List[str] = field(default_factory=lambda: ["TIP31C", "TIP32C"])
    driver_devices: List[str] = field(default_factory=lambda: ["2N3904", "2N3906"])
    resistors: Dict[str, float] = field(default_factory=dict)
    capacitors: Dict[str, float] = field(default_factory=dict)
    # tùy chọn build
    build: BuildOptions = field(default_factory=BuildOptions)


""" Cấu hình cho Special Amplifiers (Darlington, Multi-stage).
Args:
 * topology: Darlington hoặc Multi-stage cascade.
 * num_stages: Số tầng khuếch đại (mặc định 2).
 * total_gain: Tổng hệ số khuếch đại mục tiêu (mặc định 100.0).
 * vcc: Điện áp nguồn nuôi (V, mặc định 12.0).
 * transistors: Danh sách model transistor sử dụng cho từng tầng.
 * resistors: Override giá trị điện trở.
 * capacitors: Override giá trị tụ điện.
 * build: Tùy chọn build chi tiết.
"""
@dataclass
class SpecialAmpConfig:
    topology: Literal["darlington", "multi_stage"]
    num_stages: int = 2         # số tầng
    total_gain: float = 100.0   # tổng hệ số khuếch đại
    vcc: float = 12.0           # V
    # ghi đè component
    transistors: List[str] = field(default_factory=lambda: ["2N3904"])
    resistors: Dict[str, float] = field(default_factory=dict)
    capacitors: Dict[str, float] = field(default_factory=dict)
    # tùy chọn build
    build: BuildOptions = field(default_factory=BuildOptions)


""" Bộ tính toán giá trị linh kiện chung cho các mạch khuếch đại.
Cung cấp các hàm tiện ích để chuẩn hóa giá trị linh kiện về series chuẩn, tính toán điện trở song song, và chia áp điện áp, phục vụ cho các builder và calculator chuyên biệt.
Methods:
 * standardize(value: float, series: PreferredSeries) -> float:
   Làm tròn giá trị linh kiện về giá trị gần nhất trong dãy series chuẩn (E6, E12, ...).
    Args: giá trị cần chuẩn hóa, dãy series chuẩn.
    Logic: làm tròn giá trị linh kiện về tiêu chuẩn
           - trích xuất bậc thập phân (magnitude): log10(value).
           - chuẩn hóa giá trị (normalized): [1, 10) với bảng series E.
           - tra cứu trong dãy series E (value gần nhất).
           - đưa về giá trị thực: giá gần nhất * bậc thập phân.
    Returns: giá trị đã làm tròn về series chuẩn.
    
 * parallel_resistors(r1: float, r2: float) -> float:
   Tính giá trị tương đương của hai điện trở mắc song song.
    Args: giá trị điện trở thứ nhất, giá trị điện trở thứ hai
    Logic: tổng điện trở song song:
           R_eq = (R1 ✕ R2) / (R1 + R2)
    Returns: giá trị điện trở tương đương.

 * voltage_divider(vin: float, r1: float, r2: float) -> float:
   Tính điện áp ra của mạch chia áp hai điện trở.
    Args: điện áp đầu vào, giá trị điện trở trên (R1), giá trị điện trở dưới (R2)
    Logic: mạch chia áp
           vout = vin ✕ R2 / (R1 + R2) 
    Returns: Điện áp đầu ra.
"""
class ComponentCalculator:
    @staticmethod
    def standardize(value: float, series: PreferredSeries) -> float:
        if value <= 0:
            raise ValueError(f"Component value {value} phải > 0")
        
        # trích xuất bậc thập phân - E series
        magnitude = 10 ** math.floor(math.log10(value))                 # hàng đơn vị/chục/trăm/nghìn..
        normalized = value / magnitude                                  # [1, 10)
        series_values = series.value                                    # E series list
        closest = min(series_values, key=lambda x: abs(x - normalized)) # giá trị gần nhất trong series
        return closest * magnitude                                      # đưa về giá trị thực (ohm/kohm, ...)
    
    @staticmethod
    def parallel_resistors(r1: float, r2: float) -> float:
        # Rtương đương của hai điện trở song song
        return (r1 * r2) / (r1 + r2)
    
    @staticmethod
    def voltage_divider(vin: float, r1: float, r2: float) -> float:
        # điện áp ra của mạch chia áp
        return vin * r2 / (r1 + r2)


""" Cung cấp metadata cho các component dựa trên model."""
class KiCadMetadata:
    COMPONENT_METADATA = {
        # BJT
        "2N2222": ComponentMetadata("Device", "Q_NPN_BCE", "Package_TO_SOT_THT:TO-92_Inline"),
        "2N3904": ComponentMetadata("Device", "Q_NPN_BCE", "Package_TO_SOT_THT:TO-92_Inline"),
        "2N3906": ComponentMetadata("Device", "Q_PNP_BCE", "Package_TO_SOT_THT:TO-92_Inline"),
        "BC547": ComponentMetadata("Device", "Q_NPN_CBE", "Package_TO_SOT_THT:TO-92_Inline"),
        "BC557": ComponentMetadata("Device", "Q_PNP_CBE", "Package_TO_SOT_THT:TO-92_Inline"),
        
        # Power BJT
        "TIP31C": ComponentMetadata("Device", "Q_NPN_BCE", "Package_TO_SOT_THT:TO-220-3_Vertical"),
        "TIP32C": ComponentMetadata("Device", "Q_PNP_BCE", "Package_TO_SOT_THT:TO-220-3_Vertical"),
        "TIP41C": ComponentMetadata("Device", "Q_NPN_BCE", "Package_TO_SOT_THT:TO-220-3_Vertical"),
        "TIP42C": ComponentMetadata("Device", "Q_PNP_BCE", "Package_TO_SOT_THT:TO-220-3_Vertical"),
        
        # MOSFET
        "2N7000": ComponentMetadata("Device", "Q_NMOS_GDS", "Package_TO_SOT_THT:TO-92_Inline"),
        "BS170": ComponentMetadata("Device", "Q_NMOS_GDS", "Package_TO_SOT_THT:TO-92_Inline"),
        "IRF540N": ComponentMetadata("Device", "Q_NMOS_GDS", "Package_TO_SOT_THT:TO-220-3_Vertical"),
        
        # Op-Amp
        "LM741": ComponentMetadata("Amplifier_Operational", "LM741", "Package_DIP:DIP-8_W7.62mm"),
        "TL071": ComponentMetadata("Amplifier_Operational", "TL071", "Package_DIP:DIP-8_W7.62mm"),
        "TL072": ComponentMetadata("Amplifier_Operational", "TL072", "Package_DIP:DIP-8_W7.62mm"),
        "LM358": ComponentMetadata("Amplifier_Operational", "LM358", "Package_DIP:DIP-8_W7.62mm"),
        "OP07": ComponentMetadata("Amplifier_Operational", "OP07", "Package_DIP:DIP-8_W7.62mm"),
        
        # Resistor
        "R": ComponentMetadata("Device", "R", "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal"),
        
        # Capacitor
        "C": ComponentMetadata("Device", "C", "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm"),
        "C_Polarized": ComponentMetadata("Device", "CP", "Capacitor_THT:CP_Radial_D5.0mm_P2.00mm"),
    }
    
    """ Lấy metadata cho component model """
    @classmethod
    def get_metadata(cls, model: str, component_type: str = None) -> ComponentMetadata:
        if model in cls.COMPONENT_METADATA:
            return cls.COMPONENT_METADATA[model]
        
        # Nếu không tìm thấy, trả về metadata chung theo loại component mặc định
        if component_type == "resistor":
            return cls.COMPONENT_METADATA["R"]
        elif component_type == "capacitor":
            return cls.COMPONENT_METADATA["C"]
        else:
            return ComponentMetadata("Device", "Unknown", None)


""" Cung cấp PCB hints cho các loại nets khác nhau trong mạch. 
* Cung cấp hind cho các đường mạch nguồn (vcc, gnd).
* Cung cấp chỉ dẫn cho các đường tín hiệu điều khiển.
* Cung cấp chỉ dẫn cho các đường tín hiệu output.
"""
class PCBHintProvider:
    @staticmethod
    def get_power_net_hints(net_name: str, current: float) -> PCBHints:
        trace_width = max(0.5, min(current * 1.0, 3.0))         # tính toán tỉ lệ (1mm/A), giới hạn 0.5mm - 3.0mm cho power nets
        
        return PCBHints(
            layer="F.Cu",
            trace_width=trace_width,
            clearance=0.5,
            thermal_relief=True,
            notes=[f"Power net: {net_name}", f"Max current: {current}A"]
        )
    
    @staticmethod
    def get_signal_net_hints(net_name: str, is_high_impedance: bool = False) -> PCBHints:
        if is_high_impedance:
            return PCBHints(
                trace_width=0.25,                                           # đường mạch nhỏ cho tín hiệu high-Z
                clearance=0.3,                                              # khoảng cách lớn hơn để giảm nhiễu
                notes=[f"High-Z signal: {net_name}", "Keep traces short"]   # giảm nhiễu tín hiệu
            )
        else:
            return PCBHints(
                trace_width=0.5,
                clearance=0.25,
                notes=[f"Signal: {net_name}"]                               # tín hiệu thông thường
            )
    
    @staticmethod
    def get_output_net_hints(net_name: str, drive_current: float) -> PCBHints:
        trace_width = max(0.3, min(drive_current * 10, 2.0))    # tính toán tỉ lệ (10mm/A), giới hạn 0.3mm - 2.0mm cho output nets
        
        return PCBHints(
            trace_width=trace_width,
            clearance=0.3,
            notes=[f"Output: {net_name}", f"Drive current: {drive_current}mA"]  # tín hiệu output
        )