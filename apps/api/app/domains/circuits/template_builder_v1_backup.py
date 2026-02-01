# .\thesis\electronic-chatbot\apps\api\app\domains\circuits\template_builder.py
""" Thông tin chung:
Module Template Builder chịu trách nhiệm sinh tự động các mạch khuếch đại (amplifier) dựa trên tham số đầu vào (parametric), thay thế cho các template hard-code truyền thống.
Thiết kế theo kiến trúc Domain-Driven Design (DDD), module này thuộc tầng domain, tập trung vào logic nghiệp vụ sinh mạch, tách biệt hoàn toàn với AI, UI, KiCad, hay các tầng khác.
Vai trò:
 * Cho phép mở rộng dễ dàng số lượng topology mạch (>10 loại)
 * Tự động tính toán giá trị linh kiện, sinh đúng số lượng component cần thiết
 * Hỗ trợ AI agent hoặc user tùy biến tham số linh hoạt
 * Đảm bảo các bất biến nghiệp vụ (validation invariants) về cấu trúc mạch
Chỉ chứa logic sinh mạch và kiểm tra tính hợp lệ, không chứa bất kỳ logic AI, UI, hay KiCad nào để bảo vệ Source of Truth của domain.
- Ví dụ sử dụng: Cách đơn giản (API nhanh)
    * Tạo mạch khuếch đại BJT với các tham số cơ bản, mọi giá trị linh kiện sẽ được tự động tính toán
        circuit = AmplifierFactory.create_bjt(
            topology="CE",    # Chọn kiểu mạch: CE (common emitter)
            gain=15.0,        # Hệ số khuếch đại mong muốn
            vcc=12.0          # Điện áp nguồn
        )

- Kiểm soát chi tiết (toàn quyền cấu hình)
    * Tự tạo config, có thể override từng giá trị linh kiện nếu muốn
        config = BJTAmplifierConfig(
            topology="CE",          # Kiểu mạch
            gain_target=20.0,       # Hệ số khuếch đại mục tiêu
            rc=3300                 # Gán giá trị RC cụ thể, các giá trị khác vẫn tự động tính
        )
circuit = BJTAmplifierBuilder(config).build()  # Sinh mạch từ config trên
"""


import math
from dataclasses import dataclass
from typing import Dict, Literal, Optional
from enum import Enum
from .entities import (
    Circuit, Component, Net, Port, Constraint, PinRef,
    ComponentType, PortDirection, ParameterValue
)

""" Lý do sử dụng thư viện:
dataclasses dataclass: @dataclass dùng để định nghĩa các class cấu hình mạch một cách gọn gàng, tự động sinh constructor và các phương thức tiện ích.
typing: cung cấp thông tin về kiểu dữ liệu cho các biến, hàm, hỗ trợ syntax ":" cho biến và "->" cho giá trị trả về của hàm.
 * Dict[str, param value]: dùng cho các dict ánh xạ tên thuộc tính (str) sang giá trị (object), ví dụ: Dict[str, float]
 * Literal: giới hạn giá trị biến chỉ nhận các giá trị cụ thể, giúp kiểm soát logic và tránh lỗi nhập sai
 * Optional[type]: cho phép biến nhận giá trị kiểu type hoặc None, dùng cho các tham số có thể bỏ qua hoặc tự động tính toán
enum: dùng để định nghĩa tập giá trị cố định (hằng số) cho các loại linh kiện, hướng port, hoặc series chuẩn (E6, E12, E24...), giúp đảm bảo type safety, tránh nhập sai giá trị, và buộc code (người/AI) phải dùng đúng các giá trị hợp lệ (ví dụ: ComponentType.RESISTOR, PortDirection.INPUT, PreferredSeries.E12).
.entities: gọi các object liên quan để quản lý đối tượng, đúng cấu trúc dữ liệu, đảm bảo mọi thao tác sinh mạch/kiểm tra/ràng buộc/thao tác các thành phần đều tuân thủ theo và không phụ thuộc các tầng ngoài.
"""

# Định nghĩa cấu hình sinh mạch
""" Tham chiếu linh kiện (component reference)
 * Lưu thông tin loại linh kiện (BJT, MOSFET, OPAMP), model, và preference (low_noise, high_gain, ...)
 * Cho phép builder chọn đúng loại linh kiện hoặc override theo ý user
 * Không chứa logic nghiệp vụ, chỉ là data trung gian
In/Out:
 * In: user chọn model, preference hoặc builder tự sinh
 * Out: truyền vào builder để sinh mạch đúng ý định
"""
@dataclass
class ComponentRef:
    kind: Literal["BJT", "MOSFET", "OPAMP"]
    model: str                        # "2N3904", "LM741", etc.
    preference: str = "typ"           # "low_noise", "high_gain", etc.
    library_id: Optional[str] = None  # ID thư viện linh kiện



""" Tùy chọn build mạch (build options)
 * Lưu ý định về các đặc điểm build: có coupling, bypass, layout style...
 * Không chứa logic nghiệp vụ, chỉ là data trung gian
 * Cho phép user/builder kiểm soát chi tiết quá trình sinh mạch
In/Out:
 * In: user/builder truyền vào các tùy chọn build
 * Out: builder đọc để quyết định sinh mạch như thế nào
"""
@dataclass
class BuildOptions:
    include_input_coupling: bool = True                         # Có thêm tụ input coupling không
    include_output_coupling: bool = True                        # Có thêm tụ output coupling không
    include_emitter_bypass: bool = True                         # Có thêm tụ emitter bypass không (CE only)
    layout_style: Literal["compact", "textbook"] = "textbook"   # Kiểu bố trí mạch
    resistor_series: Literal["E12", "E24", "E96"] = "E12"       # Chuẩn điện trở sử dụng
    capacitor_series: Literal["E6", "E12", "E24"] = "E12"       # Chuẩn tụ điện sử dụng



""" Cấu hình sinh mạch BJT amplifier (parametric config)
 * Chỉ là data trung gian, không chứa logic nghiệp vụ
 * Lưu ý định user về topology, operating point, loại transistor, giá trị linh kiện, build options
 * Cho phép builder tự động sinh mạch hoặc user override từng giá trị
 * Tất cả thông tin đều ở dạng dict hoặc object, không có logic kiểm tra/bảo vệ
In/Out:
 * In: user nhập topology, operating point, transistor, resistors, capacitors, build options
 * Out: truyền vào builder để sinh Circuit đúng ý định
"""
@dataclass
class BJTAmplifierBuildConfig:
    topology: Literal["CE", "CC", "CB"]                                             # kiểu topo: e chung, c chung, b chung                 
    bias_type: Literal["voltage_divider", "fixed", "self"] = "voltage_divider"      # kiểu phân cực: chia áp, cố định, tự phân cực

    # thông số transistor
    vcc: float = 12.0           # V
    ic_target: float = 1.5e-3   # A
    gain_target: float = 10.0   # out > 10 in

    # thông số linh kiện
    transistor: 'ComponentRef' = None
    resistors: Optional[Dict[str, float]] = None
    capacitors: Optional[Dict[str, float]] = None
    build: 'BuildOptions' = None

    def __post_init__(self):
        if self.transistor is None:
            self.transistor = ComponentRef(kind="BJT", model="2N3904")
        if self.resistors is None:
            self.resistors = {}
        if self.capacitors is None:
            self.capacitors = {}
        if self.build is None:
            self.build = BuildOptions()



""" Cấu hình sinh mạch Op-Amp amplifier (parametric config)
 * Chỉ là data trung gian, không chứa logic nghiệp vụ
 * Lưu ý định user về topology, gain, loại opamp, giá trị linh kiện, build options
 * Cho phép builder tự động sinh mạch hoặc user override từng giá trị
 * Tất cả thông tin đều ở dạng dict hoặc object, không có logic kiểm tra/bảo vệ
In/Out:
 * In: user nhập topology, gain, opamp, resistors, capacitors, build options
 * Out: truyền vào builder để sinh Circuit đúng ý định
"""
@dataclass
class OpAmpAmplifierConfig:
    topology: Literal["inverting", "non_inverting", "differential"]     # kiểu topo: đảo, không đảo, vi sai
    gain: float = 10.0

    # thông số linh kiện
    opamp: 'ComponentRef' = None
    resistors: Optional[Dict[str, float]] = None
    capacitors: Optional[Dict[str, float]] = None
    build: 'BuildOptions' = None

    def __post_init__(self):
        if self.opamp is None:
            self.opamp = ComponentRef(kind="OPAMP", model="LM741")
        if self.resistors is None:
            self.resistors = {}
        if self.capacitors is None:
            self.capacitors = {}
        if self.build is None:
            self.build = BuildOptions()



""" Định nghĩa các dãy giá trị chuẩn (series) cho linh kiện thụ động như điện trở, tụ điện.
Mục đích:
 * Chuẩn hóa giá trị linh kiện về các giá trị phổ biến, dễ mua trên thị trường (E6, E12, E24).
 * Hỗ trợ các hàm tính toán tự động làm tròn giá trị về đúng series, đảm bảo thiết kế thực tế.
 * Tránh sinh ra giá trị linh kiện lẻ, khó tìm.
Phạm vi sử dụng:
 * Dùng cho các hàm tính toán giá trị resistor/capacitor trong các builder, calculator.
 * Có thể mở rộng cho các series khác nếu cần."""
class PreferredSeries(Enum):
    E06 = [10, 15, 22, 33, 47, 68]
    E12 = [10, 12, 15, 18, 22, 27, 33, 39, 47, 56, 68, 82]
    E24 = [10, 11, 12, 13, 15, 16, 18, 20, 22, 24, 27, 30, 33, 36, 39, 43, 47, 51, 56, 62, 68, 75, 82, 91]



""" Bộ tính toán giá trị linh kiện cho các mạch khuếch đại BJT 
Chức năng:
 * Tự động tính toán các giá trị điện trở phân cực (bias - Rb), điện trở collector (Rc), điện trở emitter (Re) dựa trên các tham số đầu vào như Vcc, Ic, gain, beta, Vbe.
 * Chuẩn hóa giá trị linh kiện về các dãy chuẩn E6, E12, E24 để dễ dàng lựa chọn linh kiện thực tế.
 * Hỗ trợ nhiều kiểu phân cực: voltage divider - chia áp, fixed bias - cố định, self bias - tự phân cực.
Đảm bảo:  
 * Tính toán đúng công thức cơ bản cho từng topology - CE, CC, CB.
 * Kiểm tra hợp lệ đầu vào (giá trị dương, không âm, hợp lý, v.v.).
 * Dễ mở rộng cho các series linh kiện khác.
Input:
 * vcc: điện áp nguồn (V)
 * vbe: điện áp base-emitter (V)
 * ic: dòng collector mong muốn (A)
 * beta: hệ số khuếch đại dòng (hFE)
 * gain: hệ số khuếch đại mong muốn (đối với RC)
 * bias_type: kiểu phân cực ("voltage_divider", "fixed", "self")
 * series: dãy chuẩn linh kiện (PreferredSeries.E12, E24, v.v.)
Output:
 * Dict[str, float]: giá trị linh kiện tính toán được (R1, R2, RC, RE, v.v.) theo chuẩn E
"""
class BJTComponentCalculator:
    DEFAULT_SERIES = PreferredSeries.E12
    
    # Làm tròn giá trị về giá trị chuẩn gần nhất trong dãy series (E6, E12, E24).
    @staticmethod
    def _standardize(value: float, series: PreferredSeries) -> float:
        if value <= 0:
            raise ValueError(f"Resistor value {value} <= 0")
        magnitude = 10 ** math.floor(math.log10(value))
        normalized = value / magnitude
        series_values = series.value
        closest = min(series_values, key=lambda x: abs(x - normalized))
        return closest * magnitude
        
    # Tính toán giá trị điện trở phân cực (bias resistors) cho kiểu phân cực chia áp (voltage divider).
    @staticmethod
    def _calc_voltage_divider_bias(vcc: float, vbe: float, ic: float, beta: float, series: PreferredSeries) -> Dict[str, float]:
        vb = vbe + 0.1 * vcc
        ib = ic / beta
        i_divider = 10 * ib
        r2 = vb / i_divider
        r1 = (vcc - vb) / i_divider
        return {
            "R1": BJTComponentCalculator._standardize(r1, series),
            "R2": BJTComponentCalculator._standardize(r2, series),
            "VB": vb
        }
    
    # Tính toán giá trị điện trở phân cực (bias resistors) cho kiểu phân cực cố định (fixed bias).
    @staticmethod
    def _calc_fixed_bias(vcc: float, vbe: float, ic: float, beta: float, series: PreferredSeries) -> Dict[str, float]:
        ib = ic / beta
        rb = (vcc - vbe) / ib
        return {
            "RB": BJTComponentCalculator._standardize(rb, series),
            "VB": vbe
        }
    
    # Tính toán giá trị điện trở phân cực (bias resistors) cho kiểu phân cực tự phân cực (self bias).
    @staticmethod
    def _calc_self_bias(vcc: float, vbe: float, ic: float, beta: float, series: PreferredSeries) -> Dict[str, float]:
        ib = ic / beta
        vc = 0.5 * vcc
        rb = (vc - vbe) / ib
        return {
            "RB": BJTComponentCalculator._standardize(rb, series),
            "VB": vbe,
            "VC": vc
        }
    
    # Tính toán giá trị điện trở phân cực (bias resistors) dựa trên kiểu phân cực và các tham số đầu vào.
    @staticmethod
    def calculate_bias_resistors(vcc: float, vbe: float, ic: float, beta: float, bias_type: str = "voltage_divider", series: PreferredSeries = None) -> Dict[str, float]:
        if series is None:
            series = BJTComponentCalculator.DEFAULT_SERIES
        if bias_type == "voltage_divider":
            return BJTComponentCalculator._calc_voltage_divider_bias(vcc, vbe, ic, beta, series)
        elif bias_type == "fixed":
            return BJTComponentCalculator._calc_fixed_bias(vcc, vbe, ic, beta, series)
        elif bias_type == "self":
            return BJTComponentCalculator._calc_self_bias(vcc, vbe, ic, beta, series)
        else:
            raise NotImplementedError(
                f"Bias type '{bias_type}' chưa được hỗ trợ. "
                "Các giá trị hợp lệ: 'voltage_divider', 'fixed', 'self'. "
                "Vui lòng kiểm tra lại tham số bias_type."
            )
    
    # Tính toán giá trị điện trở emitter (RE) để đạt dòng collector (IC) mong muốn, với tùy chọn dãy chuẩn linh kiện.
    @staticmethod
    def calculate_emitter_resistor(vb: float, vbe: float, ic: float, series: PreferredSeries = None) -> float:
        if series is None:
            series = BJTComponentCalculator.DEFAULT_SERIES
        ve = vb - vbe
        if ve <= 0:
            raise ValueError(f"VE = {ve}V <= 0, không hợp lệ")
        re = ve / ic
        return BJTComponentCalculator._standardize(re, series)
    
    # Tính toán giá trị điện trở collector (RC) từ gain mong muốn, với tùy chọn dãy chuẩn linh kiện.
    @staticmethod
    def calculate_collector_resistor(vcc: float, ic: float, gain: float, re: float,series: PreferredSeries = None) -> float:
        if series is None:
            series = BJTComponentCalculator.DEFAULT_SERIES
        rc_from_gain = abs(gain) * re
        vc = vcc - ic * rc_from_gain
        if vc < 0.3 * vcc:
            rc_from_headroom = 0.5 * vcc / ic
            rc = min(rc_from_gain, rc_from_headroom)
        else:
            rc = rc_from_gain
        return BJTComponentCalculator._standardize(rc, series)
    
    
    
""" Bộ tính toán giá trị linh kiện cho các mạch khuếch đại Op-Amp
Chức năng:
 * Tự động tính toán các giá trị điện trở phản hồi (feedback resistors) dựa trên tham số đầu vào như gain, topology, R1 base.
 * Chuẩn hóa giá trị linh kiện về các dãy chuẩn E6, E12, E24 để dễ dàng lựa chọn linh kiện thực tế.
 * Hỗ trợ nhiều topology: inverting, non-inverting, differential.
Đảm bảo:
 * Tính toán đúng công thức cơ bản cho từng topology Op-Amp.
 * Kiểm tra hợp lệ đầu vào (gain, topology, giá trị dương, không âm, hợp lý, v.v.).
 * Dễ mở rộng cho các series linh kiện hoặc topology khác.
Input:
 * gain: hệ số khuếch đại mong muốn
 * topology: kiểu mạch op-amp ('inverting', 'non_inverting', 'differential')
 * r1_base: giá trị R1 cơ sở (ohm)
 * series: dãy chuẩn linh kiện (PreferredSeries.E12, E24, v.v.)
Output:
 * Dict[str, float]: giá trị linh kiện tính toán được (R1, R2, R3, R4) theo chuẩn E
"""
class OpAmpComponentCalculator:
    DEFAULT_SERIES = PreferredSeries.E12
        
    # Làm tròn giá trị về giá trị chuẩn gần nhất trong dãy series (E6, E12, E24).
    @staticmethod
    def _standardize(value: float, series: PreferredSeries) -> float:
        if value <= 0:
            raise ValueError(f"Resistor value {value} <= 0")
        import math
        magnitude = 10 ** math.floor(math.log10(value))
        normalized = value / magnitude
        series_values = series.value
        closest = min(series_values, key=lambda x: abs(x - normalized))
        return closest * magnitude
    
    # Kiểm tra tính hợp lệ của gain dựa trên topology.
    @staticmethod
    def _validate_gain(topology, gain):
        if topology == "non_inverting" and gain < 1:
            raise ValueError("Non-inverting gain phải >= 1")

    # Tính toán giá trị điện trở cho mạch Op-Amp đảo (inverting).
    @staticmethod
    def _calc_inverting(gain: float, r1_base: float, series: PreferredSeries) -> Dict[str, float]:
        """
        Tính toán giá trị R1, R2 cho mạch Op-Amp đảo (inverting): Av = -R2/R1
        """
        r2 = abs(gain) * r1_base
        return {
            "R1": OpAmpComponentCalculator._standardize(r1_base, series),
            "R2": OpAmpComponentCalculator._standardize(r2, series)
        }

    # Tính toán giá trị điện trở cho mạch Op-Amp đảo (inverting).
    @staticmethod
    def _calc_non_inverting(gain: float, r1_base: float, series: PreferredSeries) -> Dict[str, float]:
        r2 = (gain - 1) * r1_base
        return {
            "R1": OpAmpComponentCalculator._standardize(r1_base, series),
            "R2": OpAmpComponentCalculator._standardize(r2, series)
        }
    
    # Tính toán giá trị điện trở cho mạch Op-Amp vi sai (differential).
    @staticmethod
    def _calc_differential(gain: float, r1_base: float, series: PreferredSeries) -> Dict[str, float]:
        r2 = gain * r1_base
        return {
            "R1": OpAmpComponentCalculator._standardize(r1_base, series),
            "R2": OpAmpComponentCalculator._standardize(r2, series),
            "R3": OpAmpComponentCalculator._standardize(r1_base, series),
            "R4": OpAmpComponentCalculator._standardize(r2, series)
        }
    
    # Tính toán giá trị điện trở phản hồi (feedback resistors) dựa trên gain và topology.
    @staticmethod
    def calculate_feedback_resistors(gain: float, topology: str, r1_base: float = 10_000, series: PreferredSeries = None) -> Dict[str, float]:
        if series is None:
            series = OpAmpComponentCalculator.DEFAULT_SERIES
        OpAmpComponentCalculator._validate_gain(topology, gain)
        if topology == "inverting":
            return OpAmpComponentCalculator._calc_inverting(gain, r1_base, series)
        elif topology == "non_inverting":
            return OpAmpComponentCalculator._calc_non_inverting(gain, r1_base, series)
        elif topology == "differential":
            return OpAmpComponentCalculator._calc_differential(gain, r1_base, series)
        else:
            raise NotImplementedError(
                f"Topology '{topology}' chưa được hỗ trợ. "
                "Các giá trị hợp lệ: 'inverting', 'non_inverting', 'differential'. "
                "Vui lòng kiểm tra lại tham số topology."
            )





# ========== PARAMETRIC BUILDERS ==========

class BJTAmplifierBuilder:
    """
    Parametric builder cho BJT amplifier.
    
    Tự động:
    - Sinh ĐÚNG số lượng components (CE: 8 components, CC: 6 components, CB: 9 components)
    - Tính toán values từ gain/VCC
    - Tạo nets phù hợp topology
    """
    
    def __init__(self, config: BJTAmplifierBuildConfig):
        self.config = config
        self.calc = BJTComponentCalculator()
        # self.component_library = ComponentLibrary()  # TODO: Implement component library
    
    def build(self) -> Circuit:
        """Generate circuit dựa trên topology"""
        if self.config.topology == "CE":
            return self._build_common_emitter()
        elif self.config.topology == "CC":
            return self._build_common_collector()
        elif self.config.topology == "CB":
            return self._build_common_base()
        else:
            raise ValueError(f"Topology không hợp lệ: {self.config.topology}")
    
    def _build_common_emitter(self) -> Circuit:
        """
        Auto-generate Common Emitter amplifier.
        
        Components sinh ra:
        - Q1: BJT
        - R1, R2: Bias network (voltage divider)
        - RC: Collector load
        - RE: Emitter stability
        - Cin, Cout, CE: Coupling/bypass (nếu include_coupling=True)
        
        Tổng: 5 components (no coupling) hoặc 8 components (with coupling)
        """
        cfg = self.config
        VBE = 0.7
        
        # === Auto-calculate values ===
        bias = self.calc.calculate_bias_resistors(
            cfg.vcc, VBE, cfg.ic_target, cfg.beta, cfg.bias_type
        )
        re_calc = self.calc.calculate_emitter_resistor(bias["VB"], VBE, cfg.ic_target)
        rc_calc = self.calc.calculate_collector_resistor(
            cfg.vcc, cfg.ic_target, cfg.gain_target, re_calc
        )
        
        r1_val = cfg.r1 or bias["R1"]
        r2_val = cfg.r2 or bias["R2"]
        re_val = cfg.re or re_calc
        rc_val = cfg.rc or rc_calc
        
        # === Auto-generate components (ĐÚNG số lượng cần) ===
        components = {}
        
        # Core components (luôn có)
        components["Q1"] = Component(
            id="Q1",
            type=ComponentType.BJT,
            pins=("C", "B", "E"),
            parameters={
                "model": ParameterValue(cfg.bjt_model),
                "beta": ParameterValue(cfg.beta)
            }
        )
        
        components["R1"] = Component(
            id="R1",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(r1_val, "ohm")}
        )
        
        components["R2"] = Component(
            id="R2",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(r2_val, "ohm")}
        )
        
        components["RC"] = Component(
            id="RC",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(rc_val, "ohm")}
        )
        
        components["RE"] = Component(
            id="RE",
            type=ComponentType.RESISTOR,
            pins=("1", "2"),
            parameters={"resistance": ParameterValue(re_val, "ohm")}
        )
        
        # Conditional components (chỉ thêm nếu cần)
        if cfg.include_coupling:
            components["Cin"] = Component(
                id="Cin",
                type=ComponentType.CAPACITOR,
                pins=("1", "2"),
                parameters={"capacitance": ParameterValue(cfg.cin, "F")}
            )
            components["Cout"] = Component(
                id="Cout",
                type=ComponentType.CAPACITOR,
                pins=("1", "2"),
                parameters={"capacitance": ParameterValue(cfg.cout, "F")}
            )
            components["CE"] = Component(
                id="CE",
                type=ComponentType.CAPACITOR,
                pins=("1", "2"),
                parameters={"capacitance": ParameterValue(cfg.ce, "F")}
            )
        
        # === Auto-generate nets (topology-specific) ===
        nets = {}
        
        if cfg.include_coupling:
            nets["VCC"] = Net("VCC", (
                PinRef("R1", "1"),
                PinRef("RC", "1"),
            ))
            nets["BASE"] = Net("BASE", (
                PinRef("R1", "2"),
                PinRef("R2", "1"),
                PinRef("Cin", "2"),
                PinRef("Q1", "B"),
            ))
            nets["COLLECTOR"] = Net("COLLECTOR", (
                PinRef("RC", "2"),
                PinRef("Q1", "C"),
                PinRef("Cout", "1"),
            ))
            nets["EMITTER"] = Net("EMITTER", (
                PinRef("Q1", "E"),
                PinRef("RE", "1"),
                PinRef("CE", "1"),
            ))
            nets["GND"] = Net("GND", (
                PinRef("R2", "2"),
                PinRef("RE", "2"),
                PinRef("CE", "2"),
            ))
            nets["INPUT"] = Net("INPUT", (PinRef("Cin", "1"),))
            nets["OUTPUT"] = Net("OUTPUT", (PinRef("Cout", "2"),))
        else:
            nets["VCC"] = Net("VCC", (
                PinRef("R1", "1"),
                PinRef("RC", "1"),
            ))
            nets["BASE"] = Net("BASE", (
                PinRef("R1", "2"),
                PinRef("R2", "1"),
                PinRef("Q1", "B"),
            ))
            nets["COLLECTOR"] = Net("COLLECTOR", (
                PinRef("RC", "2"),
                PinRef("Q1", "C"),
            ))
            nets["EMITTER"] = Net("EMITTER", (
                PinRef("Q1", "E"),
                PinRef("RE", "1"),
            ))
            nets["GND"] = Net("GND", (
                PinRef("R2", "2"),
                PinRef("RE", "2"),
            ))
            # nets["INPUT"] = Net("INPUT", (PinRef("Q1", "B"),))
            # nets["OUTPUT"] = Net("OUTPUT", (PinRef("Q1", "C"),))
        
        # === Ports & Constraints ===
        ports = {
            "VCC": Port("VCC", "VCC", PortDirection.POWER),
            "VIN": Port("VIN", "INPUT" if cfg.include_coupling else "BASE", PortDirection.INPUT),
            "VOUT": Port("VOUT", "OUTPUT" if cfg.include_coupling else "COLLECTOR", PortDirection.OUTPUT),
            "GND": Port("GND", "GND", PortDirection.GROUND),
        }
        
        constraints = {
            "gain": Constraint("gain", -cfg.gain_target, None),
            "vcc": Constraint("vcc", cfg.vcc, "V"),
            "ic": Constraint("ic", cfg.ic_target, "A"),
            "topology": Constraint("topology", "CE", None),
            "class": Constraint("class", "A", None)
        }
        
        return Circuit(
            name=f"CE Amplifier (Av≈{cfg.gain_target}, VCC={cfg.vcc}V)",
            _components=components,
            _nets=nets,
            _ports=ports,
            _constraints=constraints
        )
    
    def _build_common_collector(self) -> Circuit:
        """
        Auto-generate Common Collector (Emitter Follower).
        
        Components: Q1, R1, R2, RE (+ Cin, Cout nếu coupling)
        Tổng: 4-6 components
        """
        cfg = self.config
        VBE = 0.7
        
        bias = self.calc.calculate_bias_resistors(
            cfg.vcc, VBE, cfg.ic_target, cfg.beta, cfg.bias_type
        )
        re_calc = self.calc.calculate_emitter_resistor(bias["VB"], VBE, cfg.ic_target)
        
        r1_val = cfg.r1 or bias["R1"]
        r2_val = cfg.r2 or bias["R2"]
        re_val = cfg.re or re_calc
        
        # === Components ===
        components = {
            "Q1": Component(
                id="Q1",
                type=ComponentType.BJT,
                pins=("C", "B", "E"),
                parameters={
                    "model": ParameterValue(cfg.bjt_model),
                    "beta": ParameterValue(cfg.beta)
                }
            ),
            "R1": Component(
                id="R1",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(r1_val, "ohm")}
            ),
            "R2": Component(
                id="R2",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(r2_val, "ohm")}
            ),
            "RE": Component(
                id="RE",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(re_val, "ohm")}
            ),
        }
        
        if cfg.include_coupling:
            components["Cin"] = Component(
                id="Cin",
                type=ComponentType.CAPACITOR,
                pins=("1", "2"),
                parameters={"capacitance": ParameterValue(cfg.cin, "F")}
            )
            components["Cout"] = Component(
                id="Cout",
                type=ComponentType.CAPACITOR,
                pins=("1", "2"),
                parameters={"capacitance": ParameterValue(cfg.cout, "F")}
            )
        
        # === Nets (CC: output ở emitter) ===
        nets = {}
        
        if cfg.include_coupling:
            nets["VCC"] = Net("VCC", (
                PinRef("R1", "1"),
                PinRef("Q1", "C"),
            ))
            nets["BASE"] = Net("BASE", (
                PinRef("R1", "2"),
                PinRef("R2", "1"),
                PinRef("Cin", "2"),
                PinRef("Q1", "B"),
            ))
            nets["EMITTER"] = Net("EMITTER", (
                PinRef("Q1", "E"),
                PinRef("RE", "1"),
                PinRef("Cout", "1"),
            ))
            nets["GND"] = Net("GND", (
                PinRef("R2", "2"),
                PinRef("RE", "2"),
            ))
            nets["INPUT"] = Net("INPUT", (PinRef("Cin", "1"),))
            nets["OUTPUT"] = Net("OUTPUT", (PinRef("Cout", "2"),))
        else:
            nets["VCC"] = Net("VCC", (
                PinRef("R1", "1"),
                PinRef("Q1", "C"),
            ))
            nets["BASE"] = Net("BASE", (
                PinRef("R1", "2"),
                PinRef("R2", "1"),
                PinRef("Q1", "B"),
            ))
            nets["EMITTER"] = Net("EMITTER", (
                PinRef("Q1", "E"),
                PinRef("RE", "1"),
            ))
            nets["GND"] = Net("GND", (
                PinRef("R2", "2"),
                PinRef("RE", "2"),
            ))
            # nets["INPUT"] = Net("INPUT", (PinRef("Q1", "B"),))
            # nets["OUTPUT"] = Net("OUTPUT", (PinRef("Q1", "E"),))
        
        ports = {
            "VCC": Port("VCC", "VCC", PortDirection.POWER),
            "VIN": Port("VIN", "INPUT" if cfg.include_coupling else "BASE", PortDirection.INPUT),
            "VOUT": Port("VOUT", "OUTPUT" if cfg.include_coupling else "EMITTER", PortDirection.OUTPUT),
            "GND": Port("GND", "GND", PortDirection.GROUND),
        }
        
        constraints = {
            "gain": Constraint("gain", 0.99, None),
            "vcc": Constraint("vcc", cfg.vcc, "V"),
            "ic": Constraint("ic", cfg.ic_target, "A"),
            "topology": Constraint("topology", "CC", None),
            "purpose": Constraint("purpose", "buffer", None)
        }
        
        return Circuit(
            name=f"CC Amplifier (Emitter Follower, VCC={cfg.vcc}V)",
            _components=components,
            _nets=nets,
            _ports=ports,
            _constraints=constraints
        )
    
    def _build_common_base(self) -> Circuit:
        """
        Auto-generate Common Base amplifier.
        
        Components: Q1, R1, R2, RC, RE (+ Cin, Cout, CB nếu coupling)
        Tổng: 5-8 components
        """
        cfg = self.config
        VBE = 0.7
        
        bias = self.calc.calculate_bias_resistors(
            cfg.vcc, VBE, cfg.ic_target, cfg.beta, cfg.bias_type
        )
        re_calc = self.calc.calculate_emitter_resistor(bias["VB"], VBE, cfg.ic_target)
        rc_calc = self.calc.calculate_collector_resistor(
            cfg.vcc, cfg.ic_target, cfg.gain_target, re_calc
        )
        
        r1_val = cfg.r1 or bias["R1"]
        r2_val = cfg.r2 or bias["R2"]
        re_val = cfg.re or re_calc
        rc_val = cfg.rc or rc_calc
        
        # === Components ===
        components = {
            "Q1": Component(
                id="Q1",
                type=ComponentType.BJT,
                pins=("C", "B", "E"),
                parameters={
                    "model": ParameterValue(cfg.bjt_model),
                    "beta": ParameterValue(cfg.beta)
                }
            ),
            "R1": Component(
                id="R1",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(r1_val, "ohm")}
            ),
            "R2": Component(
                id="R2",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(r2_val, "ohm")}
            ),
            "RC": Component(
                id="RC",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(rc_val, "ohm")}
            ),
            "RE": Component(
                id="RE",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(re_val, "ohm")}
            ),
        }
        
        if cfg.include_coupling:
            components["Cin"] = Component(
                id="Cin",
                type=ComponentType.CAPACITOR,
                pins=("1", "2"),
                parameters={"capacitance": ParameterValue(cfg.cin, "F")}
            )
            components["Cout"] = Component(
                id="Cout",
                type=ComponentType.CAPACITOR,
                pins=("1", "2"),
                parameters={"capacitance": ParameterValue(cfg.cout, "F")}
            )
            components["CB"] = Component(
                id="CB",
                type=ComponentType.CAPACITOR,
                pins=("1", "2"),
                parameters={"capacitance": ParameterValue(100e-6, "F")}
            )
        
        # === Nets (CB: input ở emitter) ===
        nets = {}
        
        if cfg.include_coupling:
            nets["VCC"] = Net("VCC", (
                PinRef("R1", "1"),
                PinRef("RC", "1"),
            ))
            nets["BASE"] = Net("BASE", (
                PinRef("R1", "2"),
                PinRef("R2", "1"),
                PinRef("Q1", "B"),
                PinRef("CB", "1"),
            ))
            nets["COLLECTOR"] = Net("COLLECTOR", (
                PinRef("RC", "2"),
                PinRef("Q1", "C"),
                PinRef("Cout", "1"),
            ))
            nets["EMITTER"] = Net("EMITTER", (
                PinRef("Q1", "E"),
                PinRef("RE", "1"),
                PinRef("Cin", "2"),
            ))
            nets["GND"] = Net("GND", (
                PinRef("R2", "2"),
                PinRef("RE", "2"),
                PinRef("CB", "2"),
            ))
            nets["INPUT"] = Net("INPUT", (PinRef("Cin", "1"),))
            nets["OUTPUT"] = Net("OUTPUT", (PinRef("Cout", "2"),))
        else:
            nets["VCC"] = Net("VCC", (
                PinRef("R1", "1"),
                PinRef("RC", "1"),
            ))
            nets["BASE"] = Net("BASE", (
                PinRef("R1", "2"),
                PinRef("R2", "1"),
                PinRef("Q1", "B"),
            ))
            nets["COLLECTOR"] = Net("COLLECTOR", (
                PinRef("RC", "2"),
                PinRef("Q1", "C"),
            ))
            nets["EMITTER"] = Net("EMITTER", (
                PinRef("Q1", "E"),
                PinRef("RE", "1"),
            ))
            nets["GND"] = Net("GND", (
                PinRef("R2", "2"),
                PinRef("RE", "2"),
            ))
            # nets["INPUT"] = Net("INPUT", (PinRef("Q1", "E"),))
            # nets["OUTPUT"] = Net("OUTPUT", (PinRef("Q1", "C"),))
        
        ports = {
            "VCC": Port("VCC", "VCC", PortDirection.POWER),
            "VIN": Port("VIN", "INPUT" if cfg.include_coupling else "EMITTER", PortDirection.INPUT),
            "VOUT": Port("VOUT", "OUTPUT" if cfg.include_coupling else "COLLECTOR", PortDirection.OUTPUT),
            "GND": Port("GND", "GND", PortDirection.GROUND),
        }
        
        constraints = {
            "gain": Constraint("gain", cfg.gain_target, None),
            "vcc": Constraint("vcc", cfg.vcc, "V"),
            "ic": Constraint("ic", cfg.ic_target, "A"),
            "topology": Constraint("topology", "CB", None),
            "purpose": Constraint("purpose", "high_frequency", None)
        }
        
        return Circuit(
            name=f"CB Amplifier (Av≈{cfg.gain_target}, VCC={cfg.vcc}V)",
            _components=components,
            _nets=nets,
            _ports=ports,
            _constraints=constraints
        )


class OpAmpAmplifierBuilder:
    """Parametric builder cho Op-Amp amplifier"""
    
    def __init__(self, config: OpAmpAmplifierConfig):
        self.config = config
        self.calc = OpAmpComponentCalculator()
    
    def build(self) -> Circuit:
        """Generate circuit dựa trên topology"""
        if self.config.topology == "inverting":
            return self._build_inverting()
        elif self.config.topology == "non_inverting":
            return self._build_non_inverting()
        elif self.config.topology == "differential":
            return self._build_differential()
        else:
            raise ValueError(f"Topology không hợp lệ: {self.config.topology}")
    
    def _build_inverting(self) -> Circuit:
        """
        Auto-generate Inverting Op-Amp.
        Components: U1, R1, R2 (+ Cin, Cout nếu coupling)
        """
        cfg = self.config

        # For inverting topology, treat cfg.gain as magnitude (user may pass -10 or 10)
        gain_mag = abs(cfg.gain)
        
        resistors = self.calc.calculate_feedback_resistors(
            gain_mag, "inverting", cfg.r1 or 10_000
        )
        r1_val = cfg.r1 or resistors["R1"]
        r2_val = cfg.r2 or resistors["R2"]
        
        components = {
            "U1": Component(
                id="U1",
                type=ComponentType.OPAMP,
                pins=("V+", "V-", "OUT", "IN-", "IN+"),
                parameters={"model": ParameterValue(cfg.opamp_model)}
            ),
            "R1": Component(
                id="R1",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(r1_val, "ohm")}
            ),
            "R2": Component(
                id="R2",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(r2_val, "ohm")}
            ),
        }
        
        if cfg.include_coupling and cfg.cin:
            components["Cin"] = Component(
                id="Cin",
                type=ComponentType.CAPACITOR,
                pins=("1", "2"),
                parameters={"capacitance": ParameterValue(cfg.cin, "F")}
            )
        if cfg.include_coupling and cfg.cout:
            components["Cout"] = Component(
                id="Cout",
                type=ComponentType.CAPACITOR,
                pins=("1", "2"),
                parameters={"capacitance": ParameterValue(cfg.cout, "F")}
            )
        
        nets = {}
        
        if cfg.include_coupling and cfg.cin and cfg.cout:
            # Input coupling cap creates an external input node and an internal signal node.
            nets["INPUT"] = Net("INPUT", (PinRef("Cin", "1"),))
            nets["IN_SIGNAL"] = Net("IN_SIGNAL", (
                PinRef("Cin", "2"),
                PinRef("R1", "1"),
            ))
            # Inverting summing node: R1 -> IN-, R2 feedback -> IN-
            nets["IN_NEG"] = Net("IN_NEG", (
                PinRef("R1", "2"),
                PinRef("R2", "1"),
                PinRef("U1", "IN-"),
            ))
            nets["OUTPUT"] = Net("OUTPUT", (
                PinRef("R2", "2"),
                PinRef("U1", "OUT"),
                PinRef("Cout", "1"),
            ))
            nets["VOUT_EXT"] = Net("VOUT_EXT", (PinRef("Cout", "2"),))
        else:
            nets["INPUT"] = Net("INPUT", (PinRef("R1", "1"),))
            nets["IN_NEG"] = Net("IN_NEG", (
                PinRef("R1", "2"),
                PinRef("R2", "1"),
                PinRef("U1", "IN-"),
            ))
            nets["OUTPUT"] = Net("OUTPUT", (
                PinRef("R2", "2"),
                PinRef("U1", "OUT"),
            ))
        
        nets["GND"] = Net("GND", (PinRef("U1", "IN+"),))
        nets["VPLUS"] = Net("VPLUS", (PinRef("U1", "V+"),))
        nets["VMINUS"] = Net("VMINUS", (PinRef("U1", "V-"),))
        
        ports = {
            "VIN": Port("VIN", "INPUT", PortDirection.INPUT),
            "VOUT": Port("VOUT", "VOUT_EXT" if (cfg.include_coupling and cfg.cout) else "OUTPUT", PortDirection.OUTPUT),
            "VCC": Port("VCC", "VPLUS", PortDirection.POWER),
            "VEE": Port("VEE", "VMINUS", PortDirection.POWER),
            "GND": Port("GND", "GND", PortDirection.GROUND),
        }
        
        constraints = {
            "gain": Constraint("gain", -gain_mag, None),
            "topology": Constraint("topology", "inverting", None),
        }
        
        return Circuit(
            name=f"Inverting Op-Amp (Av={-gain_mag})",
            _components=components,
            _nets=nets,
            _ports=ports,
            _constraints=constraints
        )
    
    def _build_non_inverting(self) -> Circuit:
        """
        Auto-generate Non-Inverting Op-Amp.
        Components: U1, R1, R2 (+ Cin, Cout nếu coupling)
        """
        cfg = self.config
        
        resistors = self.calc.calculate_feedback_resistors(
            cfg.gain, "non_inverting", cfg.r1 or 10_000
        )
        r1_val = cfg.r1 or resistors["R1"]
        r2_val = cfg.r2 or resistors["R2"]
        
        components = {
            "U1": Component(
                id="U1",
                type=ComponentType.OPAMP,
                pins=("V+", "V-", "OUT", "IN-", "IN+"),
                parameters={"model": ParameterValue(cfg.opamp_model)}
            ),
            "R1": Component(
                id="R1",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(r1_val, "ohm")}
            ),
            "R2": Component(
                id="R2",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(r2_val, "ohm")}
            ),
        }
        
        if cfg.include_coupling and cfg.cin:
            components["Cin"] = Component(
                id="Cin",
                type=ComponentType.CAPACITOR,
                pins=("1", "2"),
                parameters={"capacitance": ParameterValue(cfg.cin, "F")}
            )
        if cfg.include_coupling and cfg.cout:
            components["Cout"] = Component(
                id="Cout",
                type=ComponentType.CAPACITOR,
                pins=("1", "2"),
                parameters={"capacitance": ParameterValue(cfg.cout, "F")}
            )
        
        nets = {}
        
        if cfg.include_coupling and cfg.cin:
            nets["INPUT"] = Net("INPUT", (PinRef("Cin", "1"),))
            nets["IN_PLUS"] = Net("IN_PLUS", (
                PinRef("Cin", "2"),
                PinRef("U1", "IN+"),
            ))
        else:
            nets["INPUT"] = Net("INPUT", (PinRef("U1", "IN+"),))
        
        nets["FEEDBACK"] = Net("FEEDBACK", (
            PinRef("R1", "1"),
            PinRef("R2", "1"),
            PinRef("U1", "IN-"),
        ))
        nets["GND"] = Net("GND", (PinRef("R1", "2"),))
        
        if cfg.include_coupling and cfg.cout:
            nets["OUTPUT"] = Net("OUTPUT", (
                PinRef("R2", "2"),
                PinRef("U1", "OUT"),
                PinRef("Cout", "1"),
            ))
            nets["VOUT_EXT"] = Net("VOUT_EXT", (PinRef("Cout", "2"),))
        else:
            nets["OUTPUT"] = Net("OUTPUT", (
                PinRef("R2", "2"),
                PinRef("U1", "OUT"),
            ))
        
        nets["VPLUS"] = Net("VPLUS", (PinRef("U1", "V+"),))
        nets["VMINUS"] = Net("VMINUS", (PinRef("U1", "V-"),))
        
        ports = {
            "VIN": Port("VIN", "INPUT", PortDirection.INPUT),
            "VOUT": Port("VOUT", "VOUT_EXT" if (cfg.include_coupling and cfg.cout) else "OUTPUT", PortDirection.OUTPUT),
            "VCC": Port("VCC", "VPLUS", PortDirection.POWER),
            "VEE": Port("VEE", "VMINUS", PortDirection.POWER),
            "GND": Port("GND", "GND", PortDirection.GROUND),
        }
        
        constraints = {
            "gain": Constraint("gain", cfg.gain, None),
            "topology": Constraint("topology", "non_inverting", None),
        }
        
        return Circuit(
            name=f"Non-Inverting Op-Amp (Av={cfg.gain})",
            _components=components,
            _nets=nets,
            _ports=ports,
            _constraints=constraints
        )
    
    def _build_differential(self) -> Circuit:
        """
        Auto-generate Differential Op-Amp.
        Components: U1, R1, R2, R3, R4 (matched pairs)
        """
        cfg = self.config
        
        resistors = self.calc.calculate_feedback_resistors(
            cfg.gain, "differential", cfg.r1 or 10_000
        )
        r1_val = cfg.r1 or resistors["R1"]
        r2_val = cfg.r2 or resistors["R2"]
        r3_val = cfg.r3 or resistors["R3"]
        r4_val = cfg.r4 or resistors["R4"]
        
        components = {
            "U1": Component(
                id="U1",
                type=ComponentType.OPAMP,
                pins=("V+", "V-", "OUT", "IN-", "IN+"),
                parameters={"model": ParameterValue(cfg.opamp_model)}
            ),
            "R1": Component(
                id="R1",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(r1_val, "ohm")}
            ),
            "R2": Component(
                id="R2",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(r2_val, "ohm")}
            ),
            "R3": Component(
                id="R3",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(r3_val, "ohm")}
            ),
            "R4": Component(
                id="R4",
                type=ComponentType.RESISTOR,
                pins=("1", "2"),
                parameters={"resistance": ParameterValue(r4_val, "ohm")}
            ),
        }
        
        nets = {
            "INPUT_POS": Net("INPUT_POS", (PinRef("R3", "1"),)),
            "INPUT_NEG": Net("INPUT_NEG", (PinRef("R1", "1"),)),
            "IN_PLUS": Net("IN_PLUS", (
                PinRef("R3", "2"),
                PinRef("R4", "1"),
                PinRef("U1", "IN+"),
            )),
            "FEEDBACK": Net("FEEDBACK", (
                PinRef("R1", "2"),
                PinRef("R2", "1"),
                PinRef("U1", "IN-"),
            )),
            "OUTPUT": Net("OUTPUT", (
                PinRef("R2", "2"),
                PinRef("U1", "OUT"),
            )),
            "GND": Net("GND", (PinRef("R4", "2"),)),
            "VPLUS": Net("VPLUS", (PinRef("U1", "V+"),)),
            "VMINUS": Net("VMINUS", (PinRef("U1", "V-"),)),
        }
        
        ports = {
            "VIN+": Port("VIN+", "INPUT_POS", PortDirection.INPUT),
            "VIN-": Port("VIN-", "INPUT_NEG", PortDirection.INPUT),
            "VOUT": Port("VOUT", "OUTPUT", PortDirection.OUTPUT),
            "VCC": Port("VCC", "VPLUS", PortDirection.POWER),
            "VEE": Port("VEE", "VMINUS", PortDirection.POWER),
            "GND": Port("GND", "GND", PortDirection.GROUND),
        }
        
        constraints = {
            "gain": Constraint("gain", cfg.gain, None),
            "topology": Constraint("topology", "differential", None),
            "purpose": Constraint("purpose", "differential", None)
        }
        
        return Circuit(
            name=f"Differential Op-Amp (Av={cfg.gain})",
            _components=components,
            _nets=nets,
            _ports=ports,
            _constraints=constraints
        )


# ========== FACADE / FACTORY ==========

class AmplifierFactory:
    """
    Factory facade - API đơn giản cho user/AI agent.
    
    Example:
        circuit = AmplifierFactory.create_bjt(
            topology="CE",
            gain=15.0,
            vcc=9.0
        )
    """
    
    @staticmethod
    def create_bjt(
        topology: Literal["CE", "CC", "CB"],
        gain: float = 10.0,
        vcc: float = 12.0,
        **kwargs
    ) -> Circuit:
        """
        Tạo BJT amplifier với config đơn giản.
        
        Args:
            topology: "CE", "CC", hoặc "CB"
            gain: Độ lợi điện áp (magnitude)
            vcc: Nguồn cấp (V)
            **kwargs: Override (rc, re, ic_target, include_coupling, ...)
        """
        config = BJTAmplifierBuildConfig(
            topology=topology,
            gain_target=gain,
            vcc=vcc,
            **kwargs
        )
        builder = BJTAmplifierBuilder(config)
        return builder.build()
    
    @staticmethod
    def create_opamp(
        topology: Literal["inverting", "non_inverting", "differential"],
        gain: float = 10.0,
        **kwargs
    ) -> Circuit:
        """
        Tạo Op-Amp amplifier với config đơn giản.
        
        Args:
            topology: "inverting", "non_inverting", hoặc "differential"
            gain: Độ lợi điện áp
            **kwargs: Override (r1, r2, opamp_model, include_coupling, ...)
        """
        config = OpAmpAmplifierConfig(
            topology=topology,
            gain=gain,
            **kwargs
        )
        builder = OpAmpAmplifierBuilder(config)
        return builder.build()
