# .\thesis\electronic-chatbot\apps\api\app\domains\circuits\builder\bjt.py
""" BJT Amplifier Builder - CE, CC, CB topologies.
* khuếch đại E chung: tăng tín hiệu, đảo pha
* khuếch đại C chung: tín hiệu ra bằng tín hiệu vào, trở kháng thấp (theo chân emitter)
* khuếch đại B chung: băng thông cao, không đảo pha
Tạo pipeline pattern để xây dựng mạch:
1. _compute_values() - Tính toán giá trị linh kiện
2. _apply_overrides() - Cập nhật thay đổi từ user
3. _create_components() - Tạo component thực tế
4. _create_nets() - Tạo nối dây theo topology
5. _create_ports() - Xác định cổng I/O
6. _create_constraints() - Gắn ràng buộc nghiệp vụ
7. _assemble_circuit() - Tạo đối tượng Circuit hoàn chỉnh
"""

# todo 1: xử lý lỗi giá trị biên (ve <= 0) - > raise lỗi, yêu cầu user tăng VB hoặc giảm IC.
# todo 2: kiểm soát unit, giá trị trả về nên rõ ràng hơn (float có thể gây nhầm lẫn khi hiển thị BoM).
# todo 3: mở rộng AI/LLM (soon)


import math
from dataclasses import dataclass, field
from typing import Dict, Literal, Any

from ..entities import (
    Circuit, Component, Net, Port, Constraint, PinRef,
    ComponentType, PortDirection, ParameterValue
)
from .common import (
    PreferredSeries, BuildOptions, ComponentCalculator, KiCadMetadata
)

""" Lý do sử dụng thư viện:
math: cần cho hằng số pi trong tính toán tụ điện.
_dataclass: dùng để định nghĩa cấu hình BJTConfig.
_field: dùng để khởi tạo dict mặc định cho overrides linh kiện.
_typing: dùng để khai báo kiểu dữ liệu cho cấu hình và builder.
from ..entities: nhập các lớp domain như Circuit, Component, Net, Port, Constraint, PinRef, ComponentType, PortDirection, ParameterValue để xây dựng mạch.
from .common: nhập các tiện ích chung như PreferredSeries, BuildOptions, ComponentCalculator, KiCadMetadata để hỗ trợ tính toán và metadata linh kiện.
"""



""" Cấu hình cho BJT amplifier (CE, CC, CB).
Cho phép tùy chỉnh các thông số nguồn, dòng, hệ số khuếch đại, loại bias, cũng như override linh kiện và build options cho từng mạch BJT cụ thể.
Args:
 * topology (Literal["CE", "CC", "CB"]): Kiểu topology mạch BJT (Common Emitter, Collector, Base).
 * vcc (float): Điện áp nguồn nuôi (V).
 * ic_target (float): Dòng collector mục tiêu (A).
 * gain_target (float): Hệ số khuếch đại mục tiêu.
 * beta (float): Hệ số khuếch đại dòng (hFE) của transistor.
 * vbe (float): Điện áp base-emitter (V).
 * bias_type (Literal["voltage_divider", "fixed", "self"]): chia áp, cố định, tự định thiên.
 * transistor_model (str): Model transistor sử dụng (VD: "2N3904").
 * resistors (Dict[str, float]): Override giá trị điện trở (theo key: "R1", "R2", ...).
 * capacitors (Dict[str, float]): Override giá trị tụ điện (theo key: "CIN", "COUT", ...).
 * build (BuildOptions): Tùy chọn build chi tiết (tụ ghép, bypass, layout, ...).
"""
@dataclass
class BJTConfig:
    topology: Literal["CE", "CC", "CB"]
    vcc: float = 12.0           # V
    ic_target: float = 1.5e-3   # A (1.5mA)
    gain_target: float = 10.0   # hệ số khuếch đại
    beta: float = 100.0         # hFE
    vbe: float = 0.7            # V
    bias_type: Literal["voltage_divider", "fixed", "self"] = "voltage_divider"
    # cập nhật linh kiện
    transistor_model: str = "2N3904"
    resistors: Dict[str, float] = field(default_factory=dict)
    capacitors: Dict[str, float] = field(default_factory=dict)
    # tùy chọn build
    build: BuildOptions = field(default_factory=BuildOptions)


""" Bộ tính toán chuyên dụng cho BJT (CE, CC, CB).
Cung cấp các hàm tính toán bias, điện trở emitter/collector, tụ bypass, phục vụ cho việc thiết kế và tối ưu hóa mạch BJT.
Methods:
 * calc_voltage_divider_bias(vcc, vbe, ic, beta, series) -> Dict[str, float]:
   Tính giá trị điện trở chia áp (R1, R2) cho bias voltage divider.
    Args: điện áp nguồn nuôi, điện áp base-emitter, dòng collector, hệ số khuếch đại dòng, dãy series chuẩn.
    Logic: tính giá trị 2 điện trở R1, R2 sao cho:
           - thiết lập điện áp base : vb = vbe + 0.1 ✕ vcc (vb = vbe + vre, vre ~ 10% vcc)
           - tính dòng base : ib = ic / beta
           - dòng qua cầu phân áp : i_divider = 10 ✕ ib (vb phải ổn định (không bị sụt áp khi vào cực base, dòng qua R1, R2 phải lớn hơn nhiều (✕10) dòng vào cực base)
           (định luật ohm r=v/i)
           - tính R2 = vb / i_divider (với r2 nối vb xuống gnd).
           - tính R1 = (vcc - vb) / i_divider (với r1 vcc xuống vb -> vcc - vb).
    Returns: dictionary chứa giá trị R1, R2 đã chuẩn hóa và VB (điện áp base).

 * calc_emitter_resistor(vb, vbe, ic, series) -> float:
   Tính giá trị điện trở emitter (RE) để đạt dòng IC mong muốn.
    Args: điện áp base, điện áp base-emitter, dòng collector, E series.
    Logic: tính RE sao cho:
           - ve = vb - vbe (cực B luôn cao hơn E khoảng 0.7v-silicon). phụ thuộc trực tiếp vào vb ở calc_voltage_divider_bias.
           - tránh ve<=0, Base quá thấp có thể gây cháy linh kiện.
           - re = ve / ic (định luật ohm r=v/i, ie ~ ic). 
    Returns: giá trị RE đã chuẩn hóa.
    
 * calc_collector_resistor(vcc, ic, gain, re, series) -> float:
   Tính giá trị điện trở collector (RC) từ hệ số khuếch đại mong muốn.
    Args: điện áp nguồn nuôi, dòng collector, hệ số khuếch đại mong muốn, điện trở emitter, E series.
    Logic: tính RC sao cho:
           - rc = gain(độ lợi) ✕ re (từ hệ số khuếch đại mong muốn), độ lợi: av ~ rc/re.
           - vc = vcc - ic ✕ rc (điện áp collector)
           áp dụng quy tắc 30% - vùng an toàn -> tín hiệu ổn định:
           - đảm bảo headroom đủ (>30% VCC), nếu rc quá lớn -> ic✕rc lớn -> vc thấp -> méo tín hiệu.
    Returns: giá trị RC đã chuẩn hóa.
   
 * calc_bypass_capacitor(re, freq_low=100.0) -> float:
   Tính giá trị tụ bypass cho emitter để ổn định bias ở tần số thấp.
    Args: điện trở emitter, tần số thấp (Hz, default 100Hz).
    Logic: tính tụ bypass sao cho:
           - khi có tín hiệu xoay chiều, để độ lợi lớn nhất, ngắn mạch re về ac.
           Quy tắc ngón tay cái:
           xc = 1/(2πfC) <= RE/10 (trở kháng tụ xc tại tần số thấp(fl) <= 1/10 giá trị re).
           - C = 10 / (2πfL✕RE) (tần số mặc định 100hz - audio cơ bản).
    Returns: giá trị tụ bypass (F).
"""
class BJTCalculator:
    @staticmethod
    def calc_voltage_divider_bias(vcc: float, vbe: float, ic: float, beta: float, series: PreferredSeries) -> Dict[str, float]:
        vb = vbe + 0.1 * vcc    # VB ~ VBE + 10% VCC
        ib = ic / beta
        i_divider = 10 * ib     # Dòng qua divider = 10*IB
        
        r2 = vb / i_divider
        r1 = (vcc - vb) / i_divider
        
        return {
            "R1": ComponentCalculator.standardize(r1, series),
            "R2": ComponentCalculator.standardize(r2, series),
            "VB": vb
        }
    
    @staticmethod
    def calc_emitter_resistor(vb: float, vbe: float, ic: float, series: PreferredSeries) -> float:
        ve = vb - vbe
        if ve <= 0:
            raise ValueError(f"VE = {ve}V <= 0, không hợp lệ")
        re = ve / ic
        return ComponentCalculator.standardize(re, series)
    
    @staticmethod
    def calc_collector_resistor(vcc: float, ic: float, gain: float, re: float, series: PreferredSeries) -> float:
        rc_from_gain = abs(gain) * re
        vc = vcc - ic * rc_from_gain
        
        # Đảm bảo headroom đủ (>30% VCC) -> tín hiệu ổn định
        if vc < 0.3 * vcc:
            rc_from_headroom = 0.5 * vcc / ic
            rc = min(rc_from_gain, rc_from_headroom)
        else:
            rc = rc_from_gain
            
        return ComponentCalculator.standardize(rc, series)
    
    @staticmethod
    def calc_bypass_capacitor(re: float, freq_low: float = 100.0) -> float:
        # tụ bypass cho emitter (fL = 100Hz default) - XC = 1/(2*pi*f*C) = RE/10 tại tần số thấp
        c = 10 / (2 * math.pi * freq_low * re)
        return c

    @staticmethod
    def calc_base_ac_ground_capacitor(r1: float, r2: float, freq_low: float = 100.0) -> float:
        """Tính tụ AC ground cho base trong CB topology.
        CB_CAP nối base → GND để AC ground base, giữ DC bias không đổi.
        Rth_base = R1 || R2 (trở kháng Thevenin nhìn từ base).
        XC << Rth tại freq_low → C = 10 / (2*pi*f*Rth)."""
        r_th = (r1 * r2) / (r1 + r2)
        c = 10 / (2 * math.pi * freq_low * r_th)
        return c

    @staticmethod
    def calc_coupling_capacitor(r_load: float, freq_low: float = 100.0) -> float:
        """Tụ ghép input/output — XC << R_load tại freq_low.
        C = 10 / (2*pi*f*R)."""
        c = 10 / (2 * math.pi * freq_low * r_load)
        return c

    @staticmethod
    def calc_collector_resistor_cb(vcc: float, ic: float, gain: float, series: PreferredSeries) -> float:
        """Tính RC cho CB topology: Av ≈ RC/re.
        Sử dụng headroom approach tương tự CE."""
        # Dùng approach: RC sao cho VC ≈ 50% VCC (headroom tốt)
        rc_max = 0.5 * vcc / ic
        return ComponentCalculator.standardize(rc_max, series)


""" Builder cho BJT amplifier topologies (CE, CC, CB).
Sử dụng pipeline pattern để tách biệt các bước xây dựng mạch, cho phép CE/CC/CBdùng chung logic tính toán, override, tạo component và chỉ khác nhau ở topology wiring (nets) và ports.
Attributes:
 - config (BJTConfig): Cấu hình BJT amplifier.
 - values (Dict[str, Any]): Giá trị trung gian sau compute + override (R1, R2, RE, RC, CIN, COUT, CE).
 - components (Dict[str, Component]): Danh sách linh kiện đã tạo.
 - nets (Dict[str, Net]): Danh sách net kết nối.
 - ports (Dict[str, Port]): Danh sách port I/O.
 - constraints (Dict[str, Constraint]): Danh sách ràng buộc nghiệp vụ.
"""
class BJTAmplifierBuilder:
    _TOPOLOGY_NAMES = {
        "CE": "Common_Emitter",
        "CC": "Common_Collector",
        "CB": "Common_Base",
    }

    def __init__(self, config: BJTConfig):
        self.config = config
        self.values: Dict[str, Any] = {}
        self.components: Dict[str, Component] = {}
        self.nets: Dict[str, Net] = {}
        self.ports: Dict[str, Port] = {}
        self.constraints: Dict[str, Constraint] = {}

    # kiểm tra component có tồn tại không. Chuẩn hóa pattern 'name in self.components'.
    def _has(self, name: str) -> bool:
        return name in self.components

    # factory tạo linh kiện trở với KiCad metadata chuẩn
    def _create_resistor(self, comp_id: str, value: float) -> Component:
        meta = KiCadMetadata.get_metadata("R", "resistor")
        return Component(
            id=comp_id, type=ComponentType.RESISTOR, pins=("1", "2"),
            parameters={"resistance": ParameterValue(value, "Ω")},
            library_id=meta.library_id, symbol_name=meta.symbol_name, footprint=meta.footprint
        )

    # factory tạo linh kiện tụ với KiCad metadata chuẩn (phân cực / không phân cực)
    def _create_capacitor(self, comp_id: str, value: float, polarized: bool = False) -> Component:
        model = "C_Polarized" if polarized else "C"
        meta = KiCadMetadata.get_metadata(model, "capacitor")
        return Component(
            id=comp_id, type=ComponentType.CAPACITOR, pins=("1", "2"),
            parameters={"capacitance": ParameterValue(value, "F")},
            library_id=meta.library_id, symbol_name=meta.symbol_name, footprint=meta.footprint
        )

    # tạo mạch theo patten: compute → override → components → nets → ports → constraints → assemble
    def build(self) -> Circuit:
        self._compute_values()
        self._apply_overrides()
        self._create_components()
        self._create_nets()
        self._create_ports()
        self._create_constraints()
        return self._assemble_circuit()

    """ Tính toán giá trị điện trở và tụ điện từ BJTCalculator.
    - lưu kết quả vào self.values dưới dạng dict trung gian, chưa tạo Component.
    - CE/CC/CB đều dùng cùng mạch bias voltage divider (R1, R2) và RE.
    - RC chỉ CE/CB cần, CC thì collector nối thẳng VCC (RC = 0 hoặc bỏ qua).
    """
    def _compute_values(self) -> None:
        series = self.config.build.resistor_series
        topology = self.config.topology

        # Bias resistors (R1, R2, VB) — dùng chung cho CE/CC/CB
        bias = BJTCalculator.calc_voltage_divider_bias(
            self.config.vcc, self.config.vbe, self.config.ic_target,
            self.config.beta, series
        )

        # RE — dùng chung cho CE/CC/CB
        re = BJTCalculator.calc_emitter_resistor(
            bias["VB"], self.config.vbe, self.config.ic_target, series
        )

        # RC — CE và CB tính khác nhau; CC collector nối thẳng VCC (không cần RC)
        rc = None
        if topology == "CE":
            # CE: Av ≈ -RC/RE → gain phụ thuộc RC/RE
            rc = BJTCalculator.calc_collector_resistor(
                self.config.vcc, self.config.ic_target,
                self.config.gain_target, re, series
            )
        elif topology == "CB":
            # CB: Av ≈ RC/re (re = VT/IC) → gain phụ thuộc RC/re, logic khác CE
            rc = BJTCalculator.calc_collector_resistor_cb(
                self.config.vcc, self.config.ic_target,
                self.config.gain_target, series
            )

        # Bypass capacitor (CE bypass) — dùng chung nếu build option bật
        ce_cap = BJTCalculator.calc_bypass_capacitor(re) if self.config.build.include_bypass_caps else None

        # AC ground capacitor cho CB topology — base AC ground qua CB_CAP
        cb_cap = None
        if topology == "CB":
            cb_cap = BJTCalculator.calc_base_ac_ground_capacitor(bias["R1"], bias["R2"])

        # Coupling capacitors — tính theo trở kháng thay vì hardcode 10µF
        cin = None
        cout = None
        
        if self.config.build.include_input_coupling:
            # Rin ≈ R1 || R2 (trở kháng bias nhìn từ ngõ vào)
            r_in = (bias["R1"] * bias["R2"]) / (bias["R1"] + bias["R2"])
            cin = BJTCalculator.calc_coupling_capacitor(r_in)
        
        if self.config.build.include_output_coupling:
            # Rout ≈ RC (CE/CB) hoặc RE (CC) — trở kháng ngõ ra
            r_out = rc if rc is not None else re
            cout = BJTCalculator.calc_coupling_capacitor(r_out)

        self.values = {
            "R1": bias["R1"],
            "R2": bias["R2"],
            "VB": bias["VB"],
            "RE": re,
            "RC": rc,
            "CE": ce_cap,
            "CB_CAP": cb_cap,
            "CIN": cin,
            "COUT": cout,
        }


        # Cho phép user override bất kỳ giá trị nào qua config.resistors / config.capacitors.
        # CE/CC/CB không cần biết override xảy ra thế nào, chỉ nhận final values.
    def _apply_overrides(self) -> None:
        self.values["R1"] = self.config.resistors.get("R1", self.values["R1"])
        self.values["R2"] = self.config.resistors.get("R2", self.values["R2"])
        self.values["RE"] = self.config.resistors.get("RE", self.values["RE"])

        if self.values["RC"] is not None:
            self.values["RC"] = self.config.resistors.get("RC", self.values["RC"])

        if self.values["CIN"] is not None:
            self.values["CIN"] = self.config.capacitors.get("CIN", self.values["CIN"])
        if self.values["COUT"] is not None:
            self.values["COUT"] = self.config.capacitors.get("COUT", self.values["COUT"])
        if self.values["CB_CAP"] is not None:
            self.values["CB_CAP"] = self.config.capacitors.get("CB_CAP", self.values["CB_CAP"])


    """ Factory tạo tất cả Component cần thiết (Q1, R1, R2, RC, RE, CIN, COUT, CE, GND).
        CE/CC/CB dùng chung 100% — chỉ khác ở cách nối (nets), không khác component.
        Sử dụng _create_resistor() / _create_capacitor() factory helpers để giảm boilerplate. """
    def _create_components(self) -> None:
        v = self.values

        # BJT Q1 — component đặc biệt, không dùng factory
        q_meta = KiCadMetadata.get_metadata(self.config.transistor_model)
        self.components["Q1"] = Component(
            id="Q1",
            type=ComponentType.BJT,
            pins=("B", "C", "E"),
            parameters={"model": ParameterValue(self.config.transistor_model)},
            library_id=q_meta.library_id,
            symbol_name=q_meta.symbol_name,
            footprint=q_meta.footprint
        )

        # Bias resistors (R1, R2) — luôn có
        self.components["R1"] = self._create_resistor("R1", v["R1"])
        self.components["R2"] = self._create_resistor("R2", v["R2"])

        # RC — chỉ tạo nếu topology cần (CE, CB)
        if v["RC"] is not None:
            self.components["RC"] = self._create_resistor("RC", v["RC"])

        # RE — luôn có
        self.components["RE"] = self._create_resistor("RE", v["RE"])

        # Coupling capacitors (CIN, COUT) — tùy build option
        if v["CIN"]:
            self.components["CIN"] = self._create_capacitor("CIN", v["CIN"])
        if v["COUT"]:
            self.components["COUT"] = self._create_capacitor("COUT", v["COUT"])

        # Bypass capacitor (CE) — tùy build option (polarized)
        if v["CE"]:
            self.components["CE"] = self._create_capacitor("CE", v["CE"], polarized=True)

        # AC ground capacitor (CB_CAP) — chỉ cho CB topology
        if v.get("CB_CAP"):
            self.components["CB_CAP"] = self._create_capacitor("CB_CAP", v["CB_CAP"])

        # Ground — luôn có
        self.components["GND"] = Component(
            id="GND", type=ComponentType.GROUND, pins=("1",),
            parameters={}
        )

    # Tạo nets tùy thuộc vào topology CE/CC/CB thông qua dispatch
    def _create_nets(self) -> None:
        topology = self.config.topology
        if topology == "CE":
            self._create_nets_ce()
        elif topology == "CC":
            self._create_nets_cc()
        elif topology == "CB":
            self._create_nets_cb()
        else:
            raise ValueError(f"Unknown BJT topology: {topology}")


    """ Tạo nets cho Common Emitter: VCC → R1.1, RC.1
                                     VBIAS → R1.2, R2.1, [CIN.2 hoặc Q1.B]
                                     VCOLLECTOR → RC.2, Q1.C, [COUT.1]
                                     VEMITTER → Q1.E, RE.1, [CE.1]
                                     GND → GND.1, R2.2, RE.2, [CE.2]
        Input qua Base (hoặc CIN → Base), output từ Collector (hoặc → COUT). """
    def _create_nets_ce(self) -> None:
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")
        has_ce = self._has("CE")

        # VCC net: R1 trên + RC trên
        self.nets["VCC"] = Net("VCC", (
            PinRef("R1", "1"),
            PinRef("RC", "1")
        ))

        # VBIAS net: R1 dưới + R2 trên + input coupling
        vbias_pins = [PinRef("R1", "2"), PinRef("R2", "1")]
        if has_cin:
            vbias_pins.append(PinRef("CIN", "2"))
        else:
            vbias_pins.append(PinRef("Q1", "B"))
        self.nets["VBIAS"] = Net("VBIAS", tuple(vbias_pins))

        # VIN net (nếu có CIN)
        if has_cin:
            self.nets["VIN"] = Net("VIN", (PinRef("CIN", "1"),))
            self.nets["_VIN_INTERNAL"] = Net("_VIN_INTERNAL", (
                PinRef("CIN", "2"),
                PinRef("Q1", "B")
            ))

        # VCOLLECTOR net: RC dưới + Q1.C + output coupling
        vcoll_pins = [PinRef("RC", "2"), PinRef("Q1", "C")]
        if has_cout:
            vcoll_pins.append(PinRef("COUT", "1"))
        self.nets["VCOLLECTOR"] = Net("VCOLLECTOR", tuple(vcoll_pins))

        # VOUT net (nếu có COUT)
        if has_cout:
            self.nets["VOUT"] = Net("VOUT", (PinRef("COUT", "2"),))

        # VEMITTER net: Q1.E + RE trên + bypass CE
        vemit_pins = [PinRef("Q1", "E"), PinRef("RE", "1")]
        if has_ce:
            vemit_pins.append(PinRef("CE", "1"))
        self.nets["VEMITTER"] = Net("VEMITTER", tuple(vemit_pins))

        # GND net
        gnd_pins = [PinRef("GND", "1"), PinRef("R2", "2"), PinRef("RE", "2")]
        if has_ce:
            gnd_pins.append(PinRef("CE", "2"))
        self.nets["GND"] = Net("GND", tuple(gnd_pins))

    def _create_nets_cc(self) -> None:
        """ Tạo nets cho Common Collector (Emitter Follower): VCC → R1.1, Q1.C (collector nối thẳng VCC, không qua RC)
                                                              VBIAS → R1.2, R2.1, [CIN.2 hoặc Q1.B]
                                                              VEMITTER → Q1.E, RE.1, [COUT.1] (output lấy từ emitter)
                                                              GND → GND.1, R2.2, RE.2
        Đặc trưng CC: Gain ≈ 1 (voltage follower), trở kháng ra thấp, không có RC. """
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")

        # VCC net: R1 trên + Q1 collector nối trực tiếp VCC
        self.nets["VCC"] = Net("VCC", (
            PinRef("R1", "1"),
            PinRef("Q1", "C")
        ))

        # VBIAS net: giống CE
        vbias_pins = [PinRef("R1", "2"), PinRef("R2", "1")]
        if has_cin:
            vbias_pins.append(PinRef("CIN", "2"))
        else:
            vbias_pins.append(PinRef("Q1", "B"))
        self.nets["VBIAS"] = Net("VBIAS", tuple(vbias_pins))

        # VIN net (nếu có CIN)
        if has_cin:
            self.nets["VIN"] = Net("VIN", (PinRef("CIN", "1"),))
            self.nets["_VIN_INTERNAL"] = Net("_VIN_INTERNAL", (
                PinRef("CIN", "2"),
                PinRef("Q1", "B")
            ))

        # VEMITTER net: Q1.E + RE trên + output coupling (output lấy từ emitter)
        vemit_pins = [PinRef("Q1", "E"), PinRef("RE", "1")]
        if has_cout:
            vemit_pins.append(PinRef("COUT", "1"))
        self.nets["VEMITTER"] = Net("VEMITTER", tuple(vemit_pins))

        # VOUT net (nếu có COUT)
        if has_cout:
            self.nets["VOUT"] = Net("VOUT", (PinRef("COUT", "2"),))

        # GND net
        gnd_pins = [PinRef("GND", "1"), PinRef("R2", "2"), PinRef("RE", "2")]
        self.nets["GND"] = Net("GND", tuple(gnd_pins))


    """ Tạo nets cho Common Base: VCC → R1.1, RC.1
                                  VBIAS → R1.2, R2.1, Q1.B (base DC bias, AC grounded qua CB_CAP)
                                  VEMITTER → Q1.E, RE.1, [CIN.1 hoặc input trực tiếp] (input qua emitter)
                                  VCOLLECTOR → RC.2, Q1.C, [COUT.1] (output từ collector)
                                  GND → GND.1, R2.2, RE.2
    Đặc trưng CB: Base AC ground, input qua emitter, output từ collector.
    Trở kháng vào thấp, băng thông rộng hơn CE. """
    def _create_nets_cb(self) -> None:
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")

        # VCC net: R1 trên + RC trên
        self.nets["VCC"] = Net("VCC", (
            PinRef("R1", "1"),
            PinRef("RC", "1")
        ))

        # VBIAS net: R1 dưới + R2 trên + Q1.B + CB_CAP (base DC bias, AC ground qua CB_CAP)
        vbias_pins = [
            PinRef("R1", "2"),
            PinRef("R2", "1"),
            PinRef("Q1", "B")
        ]
        has_cb_cap = self._has("CB_CAP")
        if has_cb_cap:
            vbias_pins.append(PinRef("CB_CAP", "1"))
        self.nets["VBIAS"] = Net("VBIAS", tuple(vbias_pins))

        # VEMITTER net: Q1.E + RE trên + input coupling (input đi vào emitter)
        vemit_pins = [PinRef("Q1", "E"), PinRef("RE", "1")]
        if has_cin:
            vemit_pins.append(PinRef("CIN", "2"))
        self.nets["VEMITTER"] = Net("VEMITTER", tuple(vemit_pins))

        # VIN net (nếu có CIN, input qua emitter)
        if has_cin:
            self.nets["VIN"] = Net("VIN", (PinRef("CIN", "1"),))

        # VCOLLECTOR net: RC dưới + Q1.C + output coupling
        vcoll_pins = [PinRef("RC", "2"), PinRef("Q1", "C")]
        if has_cout:
            vcoll_pins.append(PinRef("COUT", "1"))
        self.nets["VCOLLECTOR"] = Net("VCOLLECTOR", tuple(vcoll_pins))

        # VOUT net (nếu có COUT)
        if has_cout:
            self.nets["VOUT"] = Net("VOUT", (PinRef("COUT", "2"),))

        # GND net
        gnd_pins = [PinRef("GND", "1"), PinRef("R2", "2"), PinRef("RE", "2")]
        if has_cb_cap:
            gnd_pins.append(PinRef("CB_CAP", "2"))
        self.nets["GND"] = Net("GND", tuple(gnd_pins))


    # Tạo ports — KHÁC NHAU NHẸ, chuẩn hóa interface
    def _create_ports(self) -> None:
        """ Tạo ports I/O boundary. Mỗi topology có output net khác nhau:
            CE: output = VCOLLECTOR (hoặc VOUT nếu có COUT)
            CC: output = VEMITTER (hoặc VOUT nếu có COUT)
            CB: output = VCOLLECTOR (hoặc VOUT nếu có COUT)
        VCC, GND, VIN dùng chung 100%. """
        topology = self.config.topology
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")

        # VCC — luôn có
        self.ports["VCC"] = Port("VCC", "VCC", PortDirection.POWER)

        # VIN — nếu có CIN thì từ net VIN, không thì từ VBIAS (CE/CC) hoặc VEMITTER (CB)
        if has_cin:
            self.ports["VIN"] = Port("VIN", "VIN", PortDirection.INPUT)
        elif topology == "CB":
            self.ports["VIN"] = Port("VIN", "VEMITTER", PortDirection.INPUT)
        else:
            self.ports["VIN"] = Port("VIN", "VBIAS", PortDirection.INPUT)

        # VOUT — topology quyết định output net
        if has_cout:
            self.ports["VOUT"] = Port("VOUT", "VOUT", PortDirection.OUTPUT)
        elif topology == "CC":
            self.ports["VOUT"] = Port("VOUT", "VEMITTER", PortDirection.OUTPUT)
        else:  # CE, CB
            self.ports["VOUT"] = Port("VOUT", "VCOLLECTOR", PortDirection.OUTPUT)

        # GND — luôn có
        self.ports["GND"] = Port("GND", "GND", PortDirection.GROUND)


    # Gắn constraints nghiệp vụ: gain, IC, VCC, topology, bypass, coupling
    def _create_constraints(self) -> None:
        self.constraints["gain"] = Constraint("gain_target", self.config.gain_target)
        self.constraints["ic"] = Constraint("ic_target", self.config.ic_target, "A")
        self.constraints["vcc"] = Constraint("vcc", self.config.vcc, "V")
        self.constraints["topology"] = Constraint("topology", self.config.topology)
        self.constraints["has_bypass"] = Constraint("has_bypass", self._has("CE"))
        self.constraints["input_coupled"] = Constraint("input_coupled", self._has("CIN"))
        self.constraints["output_coupled"] = Constraint("output_coupled", self._has("COUT"))


    # Tạo assemble circuit từ components, nets, ports, constraints
    def _assemble_circuit(self) -> Circuit:
        topology_name = self._TOPOLOGY_NAMES.get(self.config.topology, self.config.topology)
        return Circuit(
            name=f"BJT_{topology_name}_Gain_{int(self.config.gain_target)}",
            _components=self.components,
            _nets=self.nets,
            _ports=self.ports,
            _constraints=self.constraints
        )
