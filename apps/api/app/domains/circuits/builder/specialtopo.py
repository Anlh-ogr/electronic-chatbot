# .\thesis\electronic-chatbot\apps\api\app\domains\circuits\builder\specialtopo.py
""" Special Amplifier Builder - Darlington Pair, Multi-Stage topologies.
* Darlington Pair: β tổng ~ β₁·β₂, trở kháng vào rất cao, dòng ra lớn.
  - Q1.E → Q2.B (nối serial), collector chung.
  - VBE tổng ≈ 2✕VBE (1.4V cho silicon).
* Multi-Stage CE-CC: tầng 1 CE (gain cao), tầng 2 CC (buffer, Rout thấp).
  - Nối tầng qua Cmid (coupling capacitor liên tầng).
  - Mỗi tầng có bias riêng (voltage divider).
Tạo pipeline pattern để xây dựng mạch:
1. _compute_values() - Tính toán giá trị linh kiện
2. _apply_overrides() - Cập nhật thay đổi từ user
3. _create_components() - Tạo component thực tế
4. _create_nets() - Tạo nối dây theo topology
5. _create_ports() - Xác định cổng I/O
6. _create_constraints() - Gắn ràng buộc nghiệp vụ
7. _assemble_circuit() - Tạo đối tượng Circuit hoàn chỉnh
"""


import math
from typing import Dict, Any

from ..entities import (
    Circuit, Component, Net, Port, Constraint, PinRef,
    ComponentType, PortDirection, ParameterValue
)
from .common import (
    PreferredSeries, BuildOptions, SpecialAmpConfig,
    ComponentCalculator, KiCadMetadata
)

""" Lý do sử dụng thư viện:
math: cần cho hằng số π trong tính toán tụ điện.
typing: dùng để khai báo kiểu dữ liệu cho cấu hình và builder.
..entities: nhập các lớp domain như Circuit, Component, Net, Port, Constraint, PinRef, ComponentType, PortDirection, ParameterValue để xây dựng mạch.
.common: nhập các tiện ích chung như PreferredSeries, BuildOptions, SpecialAmpConfig, ComponentCalculator, KiCadMetadata để hỗ trợ tính toán và metadata linh kiện.
"""



# ============================================================================
# DARLINGTON PAIR BUILDER
# ============================================================================

""" Bộ tính toán chuyên dụng cho Darlington Pair.
Cung cấp các hàm tính toán bias, điện trở emitter/collector, tụ coupling,
phục vụ cho việc thiết kế và tối ưu hóa mạch Darlington.
Methods:
 * calc_total_beta(beta1, beta2) -> ParameterValue:
   Tính hệ số khuếch đại dòng tổng: β_total = β₁ · β₂.

 * calc_voltage_divider_bias(vcc, vbe_total, ic_total, beta_total, series) -> Dict[str, ParameterValue]:
   Tính cầu phân áp (R1, R2) cho Darlington.
    Logic: VB = VBE_total + 0.1·VCC (VBE_total = 2✕VBE, ~1.4V).
           IB = IC / β_total → I_divider = 10·IB.
           R2 = VB / I_divider, R1 = (VCC - VB) / I_divider.
    Returns: dict chứa R1, R2, VB đã chuẩn hóa.

 * calc_emitter_resistor(vb, vbe_total, ic, series) -> ParameterValue:
   Tính RE: VE = VB - VBE_total, RE = VE / IC.
    Logic: kiểm tra VE > 0 (tránh hỏng linh kiện).
    Returns: giá trị RE đã chuẩn hóa.

 * calc_collector_resistor(vcc, ic, gain, re, series) -> ParameterValue:
   Tính RC: RC = gain · RE, headroom check VC > 30%·VCC.
    Returns: giá trị RC đã chuẩn hóa.

 * calc_bypass_capacitor(re, freq_low) -> ParameterValue:
   Tính tụ bypass cho emitter: C = 10 / (2π·fL·RE).
    Returns: giá trị tụ bypass (F).

 * calc_coupling_capacitor(r_load, freq_low) -> ParameterValue:
   Tính tụ ghép input/output: C = 10 / (2π·f·R).
    Returns: giá trị tụ coupling (F).
"""
class DarlingtonCalculator:
    @staticmethod
    def calc_total_beta(beta1: float, beta2: float) -> ParameterValue:
        """β_total = β₁ · β₂ — hệ số khuếch đại dòng tổng Darlington."""
        return ParameterValue(beta1 * beta2, "")

    @staticmethod
    def calc_voltage_divider_bias(vcc: float, vbe_total: float, ic: float, beta_total: float, series: PreferredSeries) -> Dict[str, ParameterValue]:
        """Tính cầu phân áp (R1, R2) cho Darlington.
        VBE_total = 2✕VBE (~1.4V silicon). VB = VBE_total + 10% VCC."""
        vb = vbe_total + 0.1 * vcc
        ib = ic / beta_total
        i_divider = 10 * ib

        if i_divider <= 0:
            raise ValueError(f"Dòng divider = {i_divider}A <= 0, kiểm tra IC và β_total.")

        r2 = vb / i_divider
        r1 = (vcc - vb) / i_divider

        return {
            "R1": ParameterValue(ComponentCalculator.standardize(r1, series), "Ω"),
            "R2": ParameterValue(ComponentCalculator.standardize(r2, series), "Ω"),
            "VB": ParameterValue(vb, "V")
        }

    @staticmethod
    def calc_emitter_resistor(vb: ParameterValue, vbe_total: float, ic: float, series: PreferredSeries) -> ParameterValue:
        """RE = (VB - VBE_total) / IC. VBE_total ~ 1.4V (2 mối nối silicon)."""
        ve = vb.value - vbe_total
        if ve <= 0:
            raise ValueError(f"VE = {ve}V <= 0, không hợp lệ. Hãy tăng VB hoặc giảm IC để VE > 0.")
        re = ve / ic
        return ParameterValue(ComponentCalculator.standardize(re, series), "Ω")

    @staticmethod
    def calc_collector_resistor(vcc: float, ic: float, gain: float, re: ParameterValue, series: PreferredSeries) -> ParameterValue:
        """RC = gain · RE, kiểm tra headroom VC > 30% VCC."""
        rc_from_gain = abs(gain) * re.value
        vc = vcc - ic * rc_from_gain

        if vc < 0.3 * vcc:
            rc_from_headroom = 0.5 * vcc / ic
            rc = min(rc_from_gain, rc_from_headroom)
        else:
            rc = rc_from_gain

        return ParameterValue(ComponentCalculator.standardize(rc, series), "Ω")

    @staticmethod
    def calc_bypass_capacitor(re: ParameterValue, freq_low: float = 100.0) -> ParameterValue:
        """Tụ bypass emitter: XC = RE/10 tại fL → C = 10 / (2π·fL·RE)."""
        c = 10 / (2 * math.pi * freq_low * re.value)
        return ParameterValue(c, "F")

    @staticmethod
    def calc_coupling_capacitor(r_load: ParameterValue, freq_low: float = 100.0) -> ParameterValue:
        """Tụ ghép input/output: XC << R tại fL → C = 10 / (2π·f·R)."""
        c = 10 / (2 * math.pi * freq_low * r_load.value)
        return ParameterValue(c, "F")


""" Builder cho Darlington Pair amplifier.
Sử dụng pipeline pattern giống BJT Builder, tách biệt các bước xây dựng mạch.
Darlington: 2 BJT nối serial (Q1.E → Q2.B), collector chung, β_total ~ β₁·β₂.
Attributes:
 - config (SpecialAmpConfig): Cấu hình Darlington amplifier.
 - values (Dict[str, Any]): Giá trị trung gian sau compute + override.
 - components (Dict[str, Component]): Danh sách linh kiện đã tạo.
 - nets (Dict[str, Net]): Danh sách net kết nối.
 - ports (Dict[str, Port]): Danh sách port I/O.
 - constraints (Dict[str, Constraint]): Danh sách ràng buộc nghiệp vụ.
"""
class DarlingtonAmplifierBuilder:
    _TOPOLOGY_NAME = "Darlington_Pair"

    def __init__(self, config: SpecialAmpConfig):
        self.config = config
        self.values: Dict[str, Any] = {}
        self.components: Dict[str, Component] = {}
        self.nets: Dict[str, Net] = {}
        self.ports: Dict[str, Port] = {}
        self.constraints: Dict[str, Constraint] = {}

        # Darlington dùng 2 transistor (mặc định: Q1=2N3904, Q2=2N2222)
        self._q1_model = config.transistors[0] if len(config.transistors) >= 1 else "2N3904"
        self._q2_model = config.transistors[1] if len(config.transistors) >= 2 else "2N2222"

        # Thông số mặc định Darlington
        self._beta1 = 100.0       # β Q1
        self._beta2 = 100.0       # β Q2
        self._vbe = 0.7           # VBE mỗi transistor (V, silicon)
        self._vbe_total = 1.4     # VBE tổng: 2✕0.7V
        self._ic_target = 2e-3    # dòng collector mục tiêu (A)

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

    # tạo mạch theo pattern: compute → override → components → nets → ports → constraints → assemble
    def build(self) -> Circuit:
        self._compute_values()
        self._apply_overrides()
        self._create_components()
        self._create_nets()
        self._create_ports()
        self._create_constraints()
        return self._assemble_circuit()

    """ Tính toán giá trị điện trở và tụ điện từ DarlingtonCalculator.
    - lưu kết quả vào self.values dưới dạng dict trung gian, chưa tạo Component.
    - Darlington: β_total = β₁·β₂, VBE_total = 2✕VBE.
    - Bias qua voltage divider (R1, R2).
    - RC → collector (giống CE), RE → emitter Q2.
    - Collector nối chung: Q1.C + Q2.C → RC.
    """
    def _compute_values(self) -> None:
        series = self.config.build.resistor_series
        vcc = self.config.vcc

        # β tổng Darlington: β₁ · β₂
        beta_total = DarlingtonCalculator.calc_total_beta(self._beta1, self._beta2)

        # Bias (R1, R2, VB) — voltage divider, VBE_total = 1.4V
        bias = DarlingtonCalculator.calc_voltage_divider_bias(
            vcc, self._vbe_total, self._ic_target,
            beta_total.value, series
        )

        # RE — emitter Q2
        re = DarlingtonCalculator.calc_emitter_resistor(
            bias["VB"], self._vbe_total, self._ic_target, series
        )

        # RC — collector (Av ≈ RC/RE)
        rc = DarlingtonCalculator.calc_collector_resistor(
            vcc, self._ic_target,
            self.config.total_gain, re, series
        )

        # Bypass capacitor (CE bypass RE) — tùy build option
        ce_cap = DarlingtonCalculator.calc_bypass_capacitor(re) if self.config.build.include_bypass_caps else None

        # Coupling capacitors — tính theo trở kháng
        cin = None
        cout = None

        if self.config.build.include_input_coupling:
            # Rin ≈ R1 || R2 (trở kháng bias nhìn từ ngõ vào)
            r_in = ParameterValue(
                (bias["R1"].value * bias["R2"].value) / (bias["R1"].value + bias["R2"].value), "Ω"
            )
            cin = DarlingtonCalculator.calc_coupling_capacitor(r_in)

        if self.config.build.include_output_coupling:
            # Rout ≈ RC
            cout = DarlingtonCalculator.calc_coupling_capacitor(rc)

        self.values = {
            "R1": bias["R1"],
            "R2": bias["R2"],
            "VB": bias["VB"],
            "RE": re,
            "RC": rc,
            "CE": ce_cap,
            "CIN": cin,
            "COUT": cout,
            "BETA_TOTAL": beta_total,
        }

    # Cho phép user override bất kỳ giá trị nào qua config.resistors / config.capacitors.
    def _apply_overrides(self) -> None:
        self.values["R1"] = self.config.resistors.get("R1", self.values["R1"])
        self.values["R2"] = self.config.resistors.get("R2", self.values["R2"])
        self.values["RE"] = self.config.resistors.get("RE", self.values["RE"])
        self.values["RC"] = self.config.resistors.get("RC", self.values["RC"])

        if self.values["CIN"] is not None:
            self.values["CIN"] = self.config.capacitors.get("CIN", self.values["CIN"])
        if self.values["COUT"] is not None:
            self.values["COUT"] = self.config.capacitors.get("COUT", self.values["COUT"])
        if self.values["CE"] is not None:
            self.values["CE"] = self.config.capacitors.get("CE", self.values["CE"])

    """ Factory tạo tất cả Component cần thiết (Q1, Q2, R1, R2, RC, RE, CIN, COUT, CE, GND).
        Darlington: 2 BJT (Q1 input, Q2 output), collectors nối chung.
        Sử dụng _create_resistor() / _create_capacitor() factory helpers để giảm boilerplate. """
    def _create_components(self) -> None:
        v = self.values

        # BJT Q1 — Darlington input stage
        q1_meta = KiCadMetadata.get_metadata(self._q1_model)
        self.components["Q1"] = Component(
            id="Q1",
            type=ComponentType.BJT,
            pins=("B", "C", "E"),
            parameters={
                "model": ParameterValue(self._q1_model),
                "role": ParameterValue("darlington_input"),
                "beta": ParameterValue(self._beta1, ""),
            },
            library_id=q1_meta.library_id,
            symbol_name=q1_meta.symbol_name,
            footprint=q1_meta.footprint
        )

        # BJT Q2 — Darlington output stage
        q2_meta = KiCadMetadata.get_metadata(self._q2_model)
        self.components["Q2"] = Component(
            id="Q2",
            type=ComponentType.BJT,
            pins=("B", "C", "E"),
            parameters={
                "model": ParameterValue(self._q2_model),
                "role": ParameterValue("darlington_output"),
                "beta": ParameterValue(self._beta2, ""),
            },
            library_id=q2_meta.library_id,
            symbol_name=q2_meta.symbol_name,
            footprint=q2_meta.footprint
        )

        # Bias resistors (R1, R2) — luôn có
        self.components["R1"] = self._create_resistor("R1", v["R1"].value)
        self.components["R2"] = self._create_resistor("R2", v["R2"].value)

        # RC — collector resistor
        self.components["RC"] = self._create_resistor("RC", v["RC"].value)

        # RE — emitter resistor (Q2 emitter)
        self.components["RE"] = self._create_resistor("RE", v["RE"].value)

        # Coupling capacitors (CIN, COUT) — tùy build option
        if v["CIN"]:
            self.components["CIN"] = self._create_capacitor("CIN", v["CIN"].value)
        if v["COUT"]:
            self.components["COUT"] = self._create_capacitor("COUT", v["COUT"].value)

        # Bypass capacitor (CE for RE) — tùy build option (polarized)
        if v["CE"]:
            self.components["CE"] = self._create_capacitor("CE", v["CE"].value, polarized=True)

        # Ground — luôn có
        self.components["GND"] = Component(
            id="GND", type=ComponentType.GROUND, pins=("1",),
            parameters={}
        )

    """ Tạo nets cho Darlington Pair:
        VCC → R1.1, RC.1
        VBIAS → R1.2, R2.1, [CIN.2 hoặc Q1.B]
        VDARLINGTON_MID → Q1.E, Q2.B (kết nối Darlington: emitter Q1 → base Q2)
        VCOLLECTOR → RC.2, Q1.C, Q2.C, [COUT.1] (collectors nối chung)
        VEMITTER → Q2.E, RE.1, [CE.1]
        GND → GND.1, R2.2, RE.2, [CE.2]
    Input qua Base Q1 (hoặc CIN → Q1.B), output từ Collector chung (hoặc → COUT). """
    def _create_nets(self) -> None:
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")
        has_ce = self._has("CE")

        # VCC net: R1 trên + RC trên
        self.nets["VCC"] = Net("VCC", (
            PinRef("R1", "1"),
            PinRef("RC", "1")
        ))

        # VBIAS net: R1.2 + R2.1 + input coupling
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

        # VDARLINGTON_MID net: Q1.E → Q2.B (kết nối Darlington)
        self.nets["VDARLINGTON_MID"] = Net("VDARLINGTON_MID", (
            PinRef("Q1", "E"),
            PinRef("Q2", "B")
        ))

        # VCOLLECTOR net: RC.2 + Q1.C + Q2.C + output coupling (collectors chung)
        vcoll_pins = [PinRef("RC", "2"), PinRef("Q1", "C"), PinRef("Q2", "C")]
        if has_cout:
            vcoll_pins.append(PinRef("COUT", "1"))
        self.nets["VCOLLECTOR"] = Net("VCOLLECTOR", tuple(vcoll_pins))

        # VOUT net (nếu có COUT)
        if has_cout:
            self.nets["VOUT"] = Net("VOUT", (PinRef("COUT", "2"),))

        # VEMITTER net: Q2.E + RE.1 + bypass CE
        vemit_pins = [PinRef("Q2", "E"), PinRef("RE", "1")]
        if has_ce:
            vemit_pins.append(PinRef("CE", "1"))
        self.nets["VEMITTER"] = Net("VEMITTER", tuple(vemit_pins))

        # GND net
        gnd_pins = [PinRef("GND", "1"), PinRef("R2", "2"), PinRef("RE", "2")]
        if has_ce:
            gnd_pins.append(PinRef("CE", "2"))
        self.nets["GND"] = Net("GND", tuple(gnd_pins))

    # Tạo ports — chuẩn hóa interface
    def _create_ports(self) -> None:
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")

        # VCC — luôn có
        self.ports["VCC"] = Port("VCC", "VCC", PortDirection.POWER)

        # VIN — nếu có CIN thì từ net VIN, không thì từ VBIAS
        if has_cin:
            self.ports["VIN"] = Port("VIN", "VIN", PortDirection.INPUT)
        else:
            self.ports["VIN"] = Port("VIN", "VBIAS", PortDirection.INPUT)

        # VOUT — nếu có COUT thì từ net VOUT, không thì từ VCOLLECTOR
        if has_cout:
            self.ports["VOUT"] = Port("VOUT", "VOUT", PortDirection.OUTPUT)
        else:
            self.ports["VOUT"] = Port("VOUT", "VCOLLECTOR", PortDirection.OUTPUT)

        # GND — luôn có
        self.ports["GND"] = Port("GND", "GND", PortDirection.GROUND)

    # Gắn constraints nghiệp vụ: gain, IC, VCC, topology, bypass, coupling
    def _create_constraints(self) -> None:
        self.constraints["gain"] = Constraint("gain_target", self.config.total_gain)
        self.constraints["beta_total"] = Constraint("beta_total", self.values["BETA_TOTAL"].value, "")
        self.constraints["vcc"] = Constraint("vcc", self.config.vcc, "V")
        self.constraints["topology"] = Constraint("topology", "darlington_pair")
        self.constraints["has_bypass"] = Constraint("has_bypass", self._has("CE"))
        self.constraints["input_coupled"] = Constraint("input_coupled", self._has("CIN"))
        self.constraints["output_coupled"] = Constraint("output_coupled", self._has("COUT"))

    # Tạo assemble circuit từ components, nets, ports, constraints
    def _assemble_circuit(self) -> Circuit:
        gain_val = int(abs(self.config.total_gain))
        return Circuit(
            name=f"Special_{self._TOPOLOGY_NAME}_Gain_{gain_val}",
            _components=self.components,
            _nets=self.nets,
            _ports=self.ports,
            _constraints=self.constraints
        )


# ============================================================================
# MULTI-STAGE CE-CC BUILDER
# ============================================================================

""" Bộ tính toán chuyên dụng cho Multi-Stage CE-CC amplifier.
Cung cấp các hàm tính toán bias, điện trở emitter/collector cho từng tầng,
tụ coupling liên tầng, phục vụ cho việc thiết kế mạch multi-stage.
Methods:
 * calc_voltage_divider_bias(vcc, vbe, ic, beta, series) -> Dict[str, ParameterValue]:
   Tính cầu phân áp cho một tầng. Logic giống BJT CE.

 * calc_emitter_resistor(vb, vbe, ic, series) -> ParameterValue:
   Tính RE cho một tầng. VE = VB - VBE, RE = VE / IC.

 * calc_collector_resistor(vcc, ic, gain, re, series) -> ParameterValue:
   Tính RC cho tầng CE. RC = gain · RE, headroom check.

 * calc_bypass_capacitor(re, freq_low) -> ParameterValue:
   Tính tụ bypass emitter cho tầng CE.

 * calc_coupling_capacitor(r_load, freq_low) -> ParameterValue:
   Tính tụ ghép input/output/liên tầng.
"""
class MultiStageCalculator:
    @staticmethod
    def calc_voltage_divider_bias(vcc: float, vbe: float, ic: float, beta: float, series: PreferredSeries) -> Dict[str, ParameterValue]:
        """Tính cầu phân áp cho một tầng — giống BJT CE."""
        vb = vbe + 0.1 * vcc
        ib = ic / beta
        i_divider = 10 * ib

        if i_divider <= 0:
            raise ValueError(f"Dòng divider = {i_divider}A <= 0, kiểm tra IC và β.")

        r2 = vb / i_divider
        r1 = (vcc - vb) / i_divider

        return {
            "R1": ParameterValue(ComponentCalculator.standardize(r1, series), "Ω"),
            "R2": ParameterValue(ComponentCalculator.standardize(r2, series), "Ω"),
            "VB": ParameterValue(vb, "V")
        }

    @staticmethod
    def calc_emitter_resistor(vb: ParameterValue, vbe: float, ic: float, series: PreferredSeries) -> ParameterValue:
        """RE = (VB - VBE) / IC."""
        ve = vb.value - vbe
        if ve <= 0:
            raise ValueError(f"VE = {ve}V <= 0, không hợp lệ. Hãy tăng VCC hoặc giảm IC để VE > 0.")
        re = ve / ic
        return ParameterValue(ComponentCalculator.standardize(re, series), "Ω")

    @staticmethod
    def calc_collector_resistor(vcc: float, ic: float, gain: float, re: ParameterValue, series: PreferredSeries) -> ParameterValue:
        """RC = gain · RE, headroom check VC > 30% VCC."""
        rc_from_gain = abs(gain) * re.value
        vc = vcc - ic * rc_from_gain

        if vc < 0.3 * vcc:
            rc_from_headroom = 0.5 * vcc / ic
            rc = min(rc_from_gain, rc_from_headroom)
        else:
            rc = rc_from_gain

        return ParameterValue(ComponentCalculator.standardize(rc, series), "Ω")

    @staticmethod
    def calc_bypass_capacitor(re: ParameterValue, freq_low: float = 100.0) -> ParameterValue:
        """Tụ bypass emitter: C = 10 / (2π·fL·RE)."""
        c = 10 / (2 * math.pi * freq_low * re.value)
        return ParameterValue(c, "F")

    @staticmethod
    def calc_coupling_capacitor(r_load: ParameterValue, freq_low: float = 100.0) -> ParameterValue:
        """Tụ ghép input/output/liên tầng: C = 10 / (2π·f·R)."""
        c = 10 / (2 * math.pi * freq_low * r_load.value)
        return ParameterValue(c, "F")


""" Builder cho Multi-Stage CE-CC amplifier (2 tầng: CE + CC).
Sử dụng pipeline pattern giống BJT Builder, tách biệt các bước xây dựng mạch.
Multi-Stage: Tầng 1 CE (Q1, gain cao) → Cmid → Tầng 2 CC (Q2, buffer, Rout thấp).
             Mỗi tầng có bias riêng (voltage divider): R1a/R2a cho Q1, R1b/R2b cho Q2.
Attributes:
 - config (SpecialAmpConfig): Cấu hình Multi-Stage amplifier.
 - values (Dict[str, Any]): Giá trị trung gian sau compute + override.
 - components (Dict[str, Component]): Danh sách linh kiện đã tạo.
 - nets (Dict[str, Net]): Danh sách net kết nối.
 - ports (Dict[str, Port]): Danh sách port I/O.
 - constraints (Dict[str, Constraint]): Danh sách ràng buộc nghiệp vụ.
"""
class MultiStageAmplifierBuilder:
    _TOPOLOGY_NAME = "MultiStage_CE_CC"

    def __init__(self, config: SpecialAmpConfig):
        self.config = config
        self.values: Dict[str, Any] = {}
        self.components: Dict[str, Component] = {}
        self.nets: Dict[str, Net] = {}
        self.ports: Dict[str, Port] = {}
        self.constraints: Dict[str, Constraint] = {}

        # Multi-stage dùng 2 transistor (mặc định: Q1=2N3904 CE, Q2=2N2222 CC)
        self._q1_model = config.transistors[0] if len(config.transistors) >= 1 else "2N3904"
        self._q2_model = config.transistors[1] if len(config.transistors) >= 2 else "2N2222"

        # Thông số mặc định
        self._beta = 100.0        # β cho cả 2 tầng
        self._vbe = 0.7           # VBE mỗi transistor (V)
        self._ic1_target = 1.5e-3 # dòng collector tầng 1 CE (A)
        self._ic2_target = 2e-3   # dòng collector tầng 2 CC (A)

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

    # tạo mạch theo pattern: compute → override → components → nets → ports → constraints → assemble
    def build(self) -> Circuit:
        self._compute_values()
        self._apply_overrides()
        self._create_components()
        self._create_nets()
        self._create_ports()
        self._create_constraints()
        return self._assemble_circuit()

    """ Tính toán giá trị điện trở và tụ điện cho 2 tầng.
    - Tầng 1 CE: R1a, R2a, RC1, RE1, CE1 (bypass).
    - Tầng 2 CC: R1b, R2b, RE2 (collector nối VCC, không cần RC).
    - Cmid: tụ coupling liên tầng (CE output → CC input).
    - CIN, COUT: tụ coupling input/output.
    """
    def _compute_values(self) -> None:
        series = self.config.build.resistor_series
        vcc = self.config.vcc

        # Gain phân bổ: tầng CE lấy hết gain, tầng CC gain ≈ 1
        gain_ce = self.config.total_gain  # tầng CE lấy toàn bộ gain
        # gain_cc ≈ 1 (emitter follower)

        # ---- Tầng 1: CE (Q1) ----
        bias_a = MultiStageCalculator.calc_voltage_divider_bias(
            vcc, self._vbe, self._ic1_target, self._beta, series
        )
        re1 = MultiStageCalculator.calc_emitter_resistor(
            bias_a["VB"], self._vbe, self._ic1_target, series
        )
        rc1 = MultiStageCalculator.calc_collector_resistor(
            vcc, self._ic1_target, gain_ce, re1, series
        )
        ce1_cap = MultiStageCalculator.calc_bypass_capacitor(re1) if self.config.build.include_bypass_caps else None

        # ---- Tầng 2: CC (Q2) ----
        bias_b = MultiStageCalculator.calc_voltage_divider_bias(
            vcc, self._vbe, self._ic2_target, self._beta, series
        )
        re2 = MultiStageCalculator.calc_emitter_resistor(
            bias_b["VB"], self._vbe, self._ic2_target, series
        )
        # CC: collector nối thẳng VCC, không cần RC2

        # ---- Inter-stage coupling (Cmid) ----
        # Cmid: trở kháng tải nhìn từ tầng CE = RC1 || Rin_CC
        # Rin_CC ≈ R1b || R2b || (β · RE2)
        rin_cc_bias = (bias_b["R1"].value * bias_b["R2"].value) / (bias_b["R1"].value + bias_b["R2"].value)
        rin_cc = min(rin_cc_bias, self._beta * re2.value)
        r_load_mid = ParameterValue(
            (rc1.value * rin_cc) / (rc1.value + rin_cc), "Ω"
        )
        cmid = MultiStageCalculator.calc_coupling_capacitor(r_load_mid)

        # ---- CIN, COUT ----
        cin = None
        cout = None

        if self.config.build.include_input_coupling:
            r_in = ParameterValue(
                (bias_a["R1"].value * bias_a["R2"].value) / (bias_a["R1"].value + bias_a["R2"].value), "Ω"
            )
            cin = MultiStageCalculator.calc_coupling_capacitor(r_in)

        if self.config.build.include_output_coupling:
            # Rout CC ≈ RE2 (emitter follower output impedance)
            cout = MultiStageCalculator.calc_coupling_capacitor(re2)

        self.values = {
            # Tầng 1 CE
            "R1a": bias_a["R1"],
            "R2a": bias_a["R2"],
            "VBa": bias_a["VB"],
            "RC1": rc1,
            "RE1": re1,
            "CE1": ce1_cap,
            # Tầng 2 CC
            "R1b": bias_b["R1"],
            "R2b": bias_b["R2"],
            "VBb": bias_b["VB"],
            "RE2": re2,
            # Coupling
            "Cmid": cmid,
            "CIN": cin,
            "COUT": cout,
        }

    # Cho phép user override bất kỳ giá trị nào qua config.resistors / config.capacitors.
    def _apply_overrides(self) -> None:
        # Tầng 1 CE
        self.values["R1a"] = self.config.resistors.get("R1a", self.values["R1a"])
        self.values["R2a"] = self.config.resistors.get("R2a", self.values["R2a"])
        self.values["RC1"] = self.config.resistors.get("RC1", self.values["RC1"])
        self.values["RE1"] = self.config.resistors.get("RE1", self.values["RE1"])

        # Tầng 2 CC
        self.values["R1b"] = self.config.resistors.get("R1b", self.values["R1b"])
        self.values["R2b"] = self.config.resistors.get("R2b", self.values["R2b"])
        self.values["RE2"] = self.config.resistors.get("RE2", self.values["RE2"])

        # Capacitors
        if self.values["CIN"] is not None:
            self.values["CIN"] = self.config.capacitors.get("CIN", self.values["CIN"])
        if self.values["COUT"] is not None:
            self.values["COUT"] = self.config.capacitors.get("COUT", self.values["COUT"])
        self.values["Cmid"] = self.config.capacitors.get("Cmid", self.values["Cmid"])
        if self.values["CE1"] is not None:
            self.values["CE1"] = self.config.capacitors.get("CE1", self.values["CE1"])

    """ Factory tạo tất cả Component:
        Tầng 1 CE: Q1, R1a, R2a, RC1, RE1, CE1
        Tầng 2 CC: Q2, R1b, R2b, RE2
        Coupling: CIN, Cmid, COUT
        Power: GND """
    def _create_components(self) -> None:
        v = self.values

        # ---- Tầng 1 CE: Q1 ----
        q1_meta = KiCadMetadata.get_metadata(self._q1_model)
        self.components["Q1"] = Component(
            id="Q1",
            type=ComponentType.BJT,
            pins=("B", "C", "E"),
            parameters={
                "model": ParameterValue(self._q1_model),
                "role": ParameterValue("stage1_ce"),
            },
            library_id=q1_meta.library_id,
            symbol_name=q1_meta.symbol_name,
            footprint=q1_meta.footprint
        )

        # ---- Tầng 2 CC: Q2 ----
        q2_meta = KiCadMetadata.get_metadata(self._q2_model)
        self.components["Q2"] = Component(
            id="Q2",
            type=ComponentType.BJT,
            pins=("B", "C", "E"),
            parameters={
                "model": ParameterValue(self._q2_model),
                "role": ParameterValue("stage2_cc"),
            },
            library_id=q2_meta.library_id,
            symbol_name=q2_meta.symbol_name,
            footprint=q2_meta.footprint
        )

        # Bias resistors tầng 1
        self.components["R1a"] = self._create_resistor("R1a", v["R1a"].value)
        self.components["R2a"] = self._create_resistor("R2a", v["R2a"].value)

        # RC1 — collector tầng 1
        self.components["RC1"] = self._create_resistor("RC1", v["RC1"].value)

        # RE1 — emitter tầng 1
        self.components["RE1"] = self._create_resistor("RE1", v["RE1"].value)

        # Bias resistors tầng 2
        self.components["R1b"] = self._create_resistor("R1b", v["R1b"].value)
        self.components["R2b"] = self._create_resistor("R2b", v["R2b"].value)

        # RE2 — emitter tầng 2
        self.components["RE2"] = self._create_resistor("RE2", v["RE2"].value)

        # Coupling capacitors
        if v["CIN"]:
            self.components["CIN"] = self._create_capacitor("CIN", v["CIN"].value)
        self.components["Cmid"] = self._create_capacitor("Cmid", v["Cmid"].value)
        if v["COUT"]:
            self.components["COUT"] = self._create_capacitor("COUT", v["COUT"].value)

        # Bypass capacitor tầng 1 (CE1)
        if v["CE1"]:
            self.components["CE1"] = self._create_capacitor("CE1", v["CE1"].value, polarized=True)

        # Ground — luôn có
        self.components["GND"] = Component(
            id="GND", type=ComponentType.GROUND, pins=("1",),
            parameters={}
        )

    """ Tạo nets cho Multi-Stage CE-CC:
        VCC → R1a.1, RC1.1, R1b.1, Q2.C
        VBIAS_A → R1a.2, R2a.1, [CIN.2 hoặc Q1.B] (bias tầng 1)
        VCOLLECTOR1 → RC1.2, Q1.C, Cmid.1 (output tầng 1 → coupling)
        VEMITTER1 → Q1.E, RE1.1, [CE1.1] (emitter tầng 1)
        VBIAS_B → R1b.2, R2b.1, Cmid.2, Q2.B (bias tầng 2 + coupling input)
        VEMITTER2 → Q2.E, RE2.1, [COUT.1] (output tầng 2, CC output từ emitter)
        GND → GND.1, R2a.2, RE1.2, [CE1.2], R2b.2, RE2.2 """
    def _create_nets(self) -> None:
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")
        has_ce1 = self._has("CE1")

        # VCC net: R1a trên + RC1 trên + R1b trên + Q2.C (CC collector nối VCC)
        self.nets["VCC"] = Net("VCC", (
            PinRef("R1a", "1"),
            PinRef("RC1", "1"),
            PinRef("R1b", "1"),
            PinRef("Q2", "C")
        ))

        # VBIAS_A net: R1a.2 + R2a.1 + input coupling (tầng 1)
        vbias_a_pins = [PinRef("R1a", "2"), PinRef("R2a", "1")]
        if has_cin:
            vbias_a_pins.append(PinRef("CIN", "2"))
        else:
            vbias_a_pins.append(PinRef("Q1", "B"))
        self.nets["VBIAS_A"] = Net("VBIAS_A", tuple(vbias_a_pins))

        # VIN net (nếu có CIN)
        if has_cin:
            self.nets["VIN"] = Net("VIN", (PinRef("CIN", "1"),))
            self.nets["_VIN_INTERNAL"] = Net("_VIN_INTERNAL", (
                PinRef("CIN", "2"),
                PinRef("Q1", "B")
            ))

        # VCOLLECTOR1 net: RC1.2 + Q1.C + Cmid.1 (output tầng 1 → coupling)
        self.nets["VCOLLECTOR1"] = Net("VCOLLECTOR1", (
            PinRef("RC1", "2"),
            PinRef("Q1", "C"),
            PinRef("Cmid", "1")
        ))

        # VEMITTER1 net: Q1.E + RE1.1 + bypass CE1
        vemit1_pins = [PinRef("Q1", "E"), PinRef("RE1", "1")]
        if has_ce1:
            vemit1_pins.append(PinRef("CE1", "1"))
        self.nets["VEMITTER1"] = Net("VEMITTER1", tuple(vemit1_pins))

        # VBIAS_B net: R1b.2 + R2b.1 + Cmid.2 + Q2.B (tầng 2 bias + coupling input)
        self.nets["VBIAS_B"] = Net("VBIAS_B", (
            PinRef("R1b", "2"),
            PinRef("R2b", "1"),
            PinRef("Cmid", "2"),
            PinRef("Q2", "B")
        ))

        # VEMITTER2 net: Q2.E + RE2.1 + output coupling (CC output từ emitter)
        vemit2_pins = [PinRef("Q2", "E"), PinRef("RE2", "1")]
        if has_cout:
            vemit2_pins.append(PinRef("COUT", "1"))
        self.nets["VEMITTER2"] = Net("VEMITTER2", tuple(vemit2_pins))

        # VOUT net (nếu có COUT)
        if has_cout:
            self.nets["VOUT"] = Net("VOUT", (PinRef("COUT", "2"),))

        # GND net: tất cả ground refs
        gnd_pins = [
            PinRef("GND", "1"),
            PinRef("R2a", "2"),
            PinRef("RE1", "2"),
            PinRef("R2b", "2"),
            PinRef("RE2", "2"),
        ]
        if has_ce1:
            gnd_pins.append(PinRef("CE1", "2"))
        self.nets["GND"] = Net("GND", tuple(gnd_pins))

    # Tạo ports — chuẩn hóa interface
    def _create_ports(self) -> None:
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")

        # VCC — luôn có
        self.ports["VCC"] = Port("VCC", "VCC", PortDirection.POWER)

        # VIN — nếu có CIN thì từ net VIN, không thì từ VBIAS_A
        if has_cin:
            self.ports["VIN"] = Port("VIN", "VIN", PortDirection.INPUT)
        else:
            self.ports["VIN"] = Port("VIN", "VBIAS_A", PortDirection.INPUT)

        # VOUT — CC output từ emitter tầng 2
        if has_cout:
            self.ports["VOUT"] = Port("VOUT", "VOUT", PortDirection.OUTPUT)
        else:
            self.ports["VOUT"] = Port("VOUT", "VEMITTER2", PortDirection.OUTPUT)

        # GND — luôn có
        self.ports["GND"] = Port("GND", "GND", PortDirection.GROUND)

    # Gắn constraints nghiệp vụ: gain, stages, VCC, topology, bypass, coupling
    def _create_constraints(self) -> None:
        self.constraints["gain"] = Constraint("gain_target", self.config.total_gain)
        self.constraints["num_stages"] = Constraint("num_stages", self.config.num_stages)
        self.constraints["vcc"] = Constraint("vcc", self.config.vcc, "V")
        self.constraints["topology"] = Constraint("topology", "multi_stage_ce_cc")
        self.constraints["stage1"] = Constraint("stage1_type", "CE")
        self.constraints["stage2"] = Constraint("stage2_type", "CC")
        self.constraints["has_bypass"] = Constraint("has_bypass", self._has("CE1"))
        self.constraints["input_coupled"] = Constraint("input_coupled", self._has("CIN"))
        self.constraints["output_coupled"] = Constraint("output_coupled", self._has("COUT"))

    # Tạo assemble circuit từ components, nets, ports, constraints
    def _assemble_circuit(self) -> Circuit:
        gain_val = int(abs(self.config.total_gain))
        return Circuit(
            name=f"Special_{self._TOPOLOGY_NAME}_Gain_{gain_val}",
            _components=self.components,
            _nets=self.nets,
            _ports=self.ports,
            _constraints=self.constraints
        )
