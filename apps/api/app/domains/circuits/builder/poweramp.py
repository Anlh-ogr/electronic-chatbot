# .\thesis\electronic-chatbot\apps\api\app\domains\circuits\builder\poweramp.py
""" Power Amplifier Builder - Class A, AB, B, C, D topologies.
* Class A: transistor luôn dẫn (360°), công suất thấp, méo thấp
* Class B: push-pull bổ sung, mỗi transistor dẫn 180°, méo crossover
* Class AB: push-pull có bias diode, loại bỏ méo crossover
* Class C: dẫn < 180°, cần tank LC, hiệu suất cao, ứng dụng RF
* Class D: chuyển mạch PWM, MOSFET, bộ lọc LC, hiệu suất >90%
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
    PreferredSeries, BuildOptions, PowerAmpConfig,
    ComponentCalculator, KiCadMetadata
)

""" Lý do sử dụng thư viện:
math: cần cho sqrt, pi trong tính toán công suất, LC tank, bộ lọc.
typing: khai báo kiểu dữ liệu Dict, Any.
..entities: nhập các lớp domain (Circuit, Component, Net, Port, Constraint, PinRef, ComponentType, PortDirection, ParameterValue) để xây dựng mạch.
.common: nhập PowerAmpConfig (cấu hình), ComponentCalculator (chuẩn hóa giá trị), KiCadMetadata (metadata linh kiện), PreferredSeries, BuildOptions.
"""



""" Bộ tính toán chuyên dụng cho Power Amplifier (Class A, B, AB, C, D).
Cung cấp các hàm tính toán bias, công suất output, LC tank, bộ lọc LC, phục vụ thiết kế mạch khuếch đại công suất.
Methods:
 * calc_class_a(vcc, pout, rl, beta, vbe, series) -> Dict:
   Tính toán bias và linh kiện cho Class A single-ended.
    Args: VCC, công suất ra, trở kháng tải, hFE, VBE, dãy series.
    Logic:
           - Q-point ở giữa đường tải để swing tối đa.
           - RC = VCC² / (8 ✕ Pout) : collector load cho max undistorted output.
             Pout_max = Vpeak ✕ Ipeak / 2 = (VCC/2)² / (2✕RC) = VCC²/(8✕RC).
           - ICQ = VCC / (2 ✕ RC) : dòng tĩnh Q-point.
           - RE = 0.1 ✕ RC : ổn định nhiệt (10% degeneration).
           - Bias divider (R1, R2): VB = VBE + ICQ ✕ RE, dòng divider = 10 ✕ IB.
    Returns: dict chứa R1, R2, RC, RE, ICQ, VB.

 * calc_class_b(vcc, pout, rl) -> Dict:
   Tính thông số output cho Class B push-pull.
    Args: VCC, công suất ra, trở kháng tải.
    Logic:
           - Vpeak = √(2 ✕ Pout ✕ RL) : biên độ đỉnh output.
           - IC_peak = Vpeak / RL : dòng đỉnh qua transistor.
           - VCC_min = Vpeak + VCE_sat : VCC tối thiểu cần thiết.
           - η_max = π/4 ≈ 78.5% : hiệu suất lý thuyết Class B.
    Returns: dict chứa VPEAK, IC_PEAK, VCC_MIN, EFFICIENCY.

 * calc_class_ab_bias(vcc, i_bias, series) -> Dict:
   Tính bias network cho Class AB push-pull.
    Args: VCC, dòng bias tĩnh, dãy series.
    Logic:
           - 2 diode tạo 2 ✕ VD ≈ 1.4V giữa base Q1 và Q2, loại bỏ crossover.
           - R_BIAS1 = (VCC/2 - VD) / I_bias : điện trở bias phía trên.
           - R_BIAS2 = (VCC/2 - VD) / I_bias : điện trở bias phía dưới.
    Returns: dict chứa R_BIAS1, R_BIAS2, I_BIAS.

 * calc_class_c_tank(freq, rl, q_factor) -> Dict:
   Tính LC tank cho Class C tuned amplifier.
    Args: tần số cộng hưởng (Hz), trở kháng tải, hệ số phẩm chất Q.
    Logic:
           - f0 = 1/(2π√(LC)) : tần số cộng hưởng của mạch LC.
           - L = Q ✕ RL / (2π ✕ f0) : cuộn cảm tank.
           - C = 1 / ((2π ✕ f0)² ✕ L) : tụ tank.
    Returns: dict chứa L_TANK, C_TANK, F0, Q.

 * calc_class_c_bias(rl, series) -> Dict:
   Tính R_BASE cho Class C self-bias.
    Args: trở kháng tải, dãy series.
    Logic: R_BASE >> RL để không ảnh hưởng tank, thường 10 ✕ RL.
    Returns: dict chứa R_BASE.

 * calc_class_d_filter(freq_cutoff, rl) -> Dict:
   Tính LC filter cho Class D switching amplifier.
    Args: tần số cắt (Hz), trở kháng tải.
    Logic:
           - Butterworth 2nd order: f_c = 1/(2π√(LC)).
           - L = RL / (2π ✕ f_cutoff) : cuộn cảm lọc.
           - C = 1 / ((2π ✕ f_cutoff)² ✕ L) : tụ lọc.
    Returns: dict chứa L_FILTER, C_FILTER, F_CUTOFF.

 * calc_class_d_gate(series) -> Dict:
   Tính gate resistors cho Class D MOSFET.
    Args: dãy series.
    Logic: R_GATE ~ 10Ω, giới hạn dòng nạp/xả gate MOSFET.
    Returns: dict chứa R_GATE1, R_GATE2.

 * calc_coupling_capacitor(r_load, freq_low) -> float:
   Tụ ghép I/O — XC << R_load tại freq_low (20Hz audio).
    Args: trở kháng tải, tần số thấp (default 20Hz cho audio).
    Logic: C = 10 / (2π ✕ f ✕ R).
    Returns: giá trị tụ (F).

 * calc_bypass_capacitor(re, freq_low) -> float:
   Tụ bypass cho emitter — XC << RE tại freq_low.
    Args: điện trở emitter, tần số thấp (default 20Hz).
    Logic: C = 10 / (2π ✕ f ✕ RE).
    Returns: giá trị tụ (F).

 * calc_thermal_class_a(vcc, icq, pout, tj_max, ta) -> Dict:
   Tính tổn hao nhiệt và yêu cầu tản nhiệt cho Class A.
    Args: VCC, dòng tĩnh ICQ, công suất ra, nhiệt độ junction max, nhiệt độ môi trường.
    Logic:
           - P_diss = VCC ✕ ICQ - Pout : công suất tiêu tán tại transistor.
           - θ_JA_no_hs = 65°C/W : trở kháng nhiệt TO-220 không tản nhiệt.
           - Tj_no_hs = Ta + P_diss ✕ θ_JA_no_hs : nhiệt độ junction không tản nhiệt.
           - heatsink_needed = Tj_no_hs > Tj_max.
           - θ_SA = (Tj_max - Ta) / P_diss - θ_JC - θ_CS : trở kháng nhiệt tản nhiệt cần.
    Returns: dict chứa P_DISS, THETA_SA, HEATSINK_NEEDED.

 * calc_thermal_class_ab(vcc, pout, rl, tj_max, ta) -> Dict:
   Tính tổn hao nhiệt cho Class AB push-pull.
    Args: VCC, công suất ra, trở kháng tải, nhiệt độ junction max, nhiệt độ môi trường.
    Logic:
           - Vpeak = √(2 ✕ Pout ✕ RL), I_avg = Vpeak / (π ✕ RL).
           - P_DC = VCC ✕ I_avg, P_diss = P_DC - Pout.
           - P_diss_per_transistor = P_diss / 2 (mỗi transistor chịu ~50%).
    Returns: dict chứa P_DISS_TOTAL, P_DISS_PER_TRANSISTOR, THETA_SA, HEATSINK_NEEDED.

 * calc_class_d_bootstrap(q_gate, vcc_gate) -> Dict:
   Tính bootstrap capacitor cho Class D high-side gate drive.
    Args: điện tích gate MOSFET (C), điện áp gate driver supply (V).
    Logic:
           - C_BOOT = 10 ✕ Q_gate / VCC_GATE (margin 10✕).
           - Minimum 100nF để đảm bảo nạp gate đủ.
    Returns: dict chứa C_BOOT.
"""
class PowerAmpCalculator:
    @staticmethod
    def calc_class_a(vcc: float, pout: float, rl: float, beta: float,
                     vbe: float, series: PreferredSeries) -> Dict[str, float]:
        # RC = VCC² / (8 ✕ Pout) — max undistorted swing
        # Pout_max = (VCC/2)² / (2✕RC), suy ra RC = VCC²/(8✕Pout)
        rc = vcc ** 2 / (8 * pout)
        # ICQ = VCC / (2 ✕ RC) — Q-point ở giữa đường tải (VCE_Q = VCC/2)
        icq = vcc / (2 * rc)
        # RE ≈ 10% RC — ổn định nhiệt, emitter degeneration
        re = 0.1 * rc
        # Bias divider: VB = VBE + ICQ ✕ RE
        vb = vbe + icq * re
        ib = icq / beta
        i_div = 10 * ib  # dòng divider gấp 10 lần IB → VB ổn định
        r1 = (vcc - vb) / i_div
        r2 = vb / i_div

        return {
            "RC": ComponentCalculator.standardize(rc, series),
            "RE": ComponentCalculator.standardize(re, series),
            "R1": ComponentCalculator.standardize(r1, series),
            "R2": ComponentCalculator.standardize(r2, series),
            "ICQ": icq,
            "VB": vb,
        }

    @staticmethod
    def calc_class_b(vcc: float, pout: float, rl: float) -> Dict[str, float]:
        # Vpeak = √(2 ✕ Pout ✕ RL) — biên độ đỉnh output trên tải
        vpeak = math.sqrt(2 * pout * rl)
        # IC_peak = Vpeak / RL — dòng đỉnh qua mỗi transistor
        ic_peak = vpeak / rl
        # VCC tối thiểu: VCC >= Vpeak + VCE_sat
        vce_sat = 1.0  # VCE saturation ~ 1V cho power BJT (TIP31C/TIP32C)
        vcc_min = vpeak + vce_sat
        # Hiệu suất lý thuyết max: η = π/4 ≈ 78.5%
        eta = math.pi / 4

        return {
            "VPEAK": vpeak,
            "IC_PEAK": ic_peak,
            "VCC_MIN": vcc_min,
            "EFFICIENCY": eta,
        }

    @staticmethod
    def calc_class_ab_bias(vcc: float, i_bias: float,
                           series: PreferredSeries) -> Dict[str, float]:
        # Vdiode ≈ 0.7V — mỗi diode forward bias (silicon)
        v_diode = 0.7
        # R_BIAS = (VCC/2 - VD) / I_bias — mỗi bên cung cấp dòng qua diode chain
        r_bias1 = (vcc / 2 - v_diode) / i_bias
        r_bias2 = (vcc / 2 - v_diode) / i_bias

        return {
            "R_BIAS1": ComponentCalculator.standardize(r_bias1, series),
            "R_BIAS2": ComponentCalculator.standardize(r_bias2, series),
            "I_BIAS": i_bias,
        }

    @staticmethod
    def calc_class_c_tank(freq: float, rl: float,
                          q_factor: float = 10.0) -> Dict[str, float]:
        # L = Q ✕ RL / (2π ✕ f0) — cuộn cảm tank từ Q factor và tải
        l_tank = q_factor * rl / (2 * math.pi * freq)
        # C = 1 / ((2π ✕ f0)² ✕ L) — tụ tank, hoàn chỉnh mạch cộng hưởng
        c_tank = 1 / ((2 * math.pi * freq) ** 2 * l_tank)

        return {
            "L_TANK": l_tank,
            "C_TANK": c_tank,
            "F0": freq,
            "Q": q_factor,
        }

    @staticmethod
    def calc_class_c_bias(rl: float, series: PreferredSeries) -> Dict[str, float]:
        # R_BASE >> RL — self-bias: base kéo về GND, chỉ dẫn khi tín hiệu vượt VBE
        r_base = 10 * rl
        return {
            "R_BASE": ComponentCalculator.standardize(r_base, series),
        }

    @staticmethod
    def calc_class_d_filter(freq_cutoff: float, rl: float) -> Dict[str, float]:
        # L = RL / (2π ✕ f_cutoff) — Butterworth LC, lọc PWM thành tín hiệu analog
        l_filter = rl / (2 * math.pi * freq_cutoff)
        # C = 1 / ((2π ✕ f_cutoff)² ✕ L) — tụ lọc output
        c_filter = 1 / ((2 * math.pi * freq_cutoff) ** 2 * l_filter)

        return {
            "L_FILTER": l_filter,
            "C_FILTER": c_filter,
            "F_CUTOFF": freq_cutoff,
        }

    @staticmethod
    def calc_class_d_gate(series: PreferredSeries) -> Dict[str, float]:
        # Gate resistor ~ 10Ω — giới hạn dòng nạp/xả gate MOSFET, giảm ringing
        r_gate = 10.0
        return {
            "R_GATE1": ComponentCalculator.standardize(r_gate, series),
            "R_GATE2": ComponentCalculator.standardize(r_gate, series),
        }

    @staticmethod
    def calc_coupling_capacitor(r_load: float, freq_low: float = 20.0) -> float:
        # Tụ ghép: XC << R_load tại freq_low (20Hz cho audio power amp)
        # C = 10 / (2π ✕ f ✕ R)
        c = 10 / (2 * math.pi * freq_low * r_load)
        return c

    @staticmethod
    def calc_bypass_capacitor(re: float, freq_low: float = 20.0) -> float:
        # Tụ bypass: XC << RE tại freq_low (20Hz cho audio)
        # C = 10 / (2π ✕ f ✕ RE)
        c = 10 / (2 * math.pi * freq_low * re)
        return c

    @staticmethod
    def calc_thermal_class_a(vcc: float, icq: float, pout: float,
                             tj_max: float = 150.0, ta: float = 25.0) -> Dict[str, float]:
        # P_diss = VCC ✕ ICQ - Pout — công suất tiêu tán tại transistor output
        p_diss = vcc * icq - pout
        if p_diss <= 0:
            p_diss = 0.1  # giá trị tối thiểu tránh chia 0

        # θ_JC = 3°C/W (TO-220 junction-to-case), θ_CS = 0.5°C/W (thermal compound)
        theta_jc = 3.0
        theta_cs = 0.5

        # Kiểm tra có cần tản nhiệt không: Tj = Ta + P_diss ✕ θ_JA_no_heatsink
        theta_ja_no_hs = 65.0  # °C/W — TO-220 không tản nhiệt (junction-to-ambient)
        tj_no_heatsink = ta + p_diss * theta_ja_no_hs
        heatsink_needed = tj_no_heatsink > tj_max

        # θ_SA (heatsink-to-ambient) cần thiết nếu dùng tản nhiệt
        theta_ja_required = (tj_max - ta) / p_diss
        theta_sa = theta_ja_required - theta_jc - theta_cs

        return {
            "P_DISS": p_diss,
            "THETA_JC": theta_jc,
            "THETA_CS": theta_cs,
            "THETA_SA": max(theta_sa, 0),
            "HEATSINK_NEEDED": heatsink_needed,
            "TJ_MAX": tj_max,
        }

    @staticmethod
    def calc_thermal_class_ab(vcc: float, pout: float, rl: float,
                              tj_max: float = 150.0, ta: float = 25.0) -> Dict[str, float]:
        # Vpeak = √(2 ✕ Pout ✕ RL), I_avg = Vpeak / (π ✕ RL) — dòng DC trung bình
        vpeak = math.sqrt(2 * pout * rl)
        i_avg = vpeak / (math.pi * rl)
        # P_DC = VCC ✕ I_avg — tổng công suất DC cấp vào
        p_dc = vcc * i_avg
        p_diss = p_dc - pout if p_dc > pout else 0.1
        # Mỗi transistor chịu ~50% tổn hao
        p_diss_per = p_diss / 2

        theta_jc = 3.0
        theta_cs = 0.5
        theta_ja_no_hs = 65.0
        tj_no_heatsink = ta + p_diss_per * theta_ja_no_hs
        heatsink_needed = tj_no_heatsink > tj_max

        theta_ja_required = (tj_max - ta) / p_diss_per if p_diss_per > 0 else 999
        theta_sa = theta_ja_required - theta_jc - theta_cs

        return {
            "P_DISS_TOTAL": p_diss,
            "P_DISS_PER_TRANSISTOR": p_diss_per,
            "THETA_SA": max(theta_sa, 0),
            "HEATSINK_NEEDED": heatsink_needed,
            "TJ_MAX": tj_max,
        }

    @staticmethod
    def calc_class_d_bootstrap(q_gate: float = 71e-9, vcc_gate: float = 12.0) -> Dict[str, float]:
        # C_BOOT = 10 ✕ Q_gate / VCC_GATE — margin 10✕ cho gate charge
        # Q_gate ≈ 71nC cho IRF540N, VCC_GATE = 12V (gate driver supply)
        c_boot = 10 * q_gate / vcc_gate
        if c_boot < 100e-9:
            c_boot = 100e-9  # minimum 100nF cho nạp gate ổn định
        return {
            "C_BOOT": c_boot,
        }



""" Builder cho Power Amplifier topologies (Class A, B, AB, C, D).
Sử dụng pipeline pattern (giống BJT Builder) để tách biệt các bước xây dựng mạch,
cho phép 5 class dùng chung logic override, tạo component, và chỉ khác nhau ở
topology wiring (nets), components đặc thù, và ports.
Attributes:
 - config (PowerAmpConfig): Cấu hình power amplifier.
 - values (Dict[str, Any]): Giá trị trung gian sau compute + override (R1, R2, RC, RE, ...).
 - components (Dict[str, Component]): Danh sách linh kiện đã tạo.
 - nets (Dict[str, Net]): Danh sách net kết nối.
 - ports (Dict[str, Port]): Danh sách port I/O.
 - constraints (Dict[str, Constraint]): Danh sách ràng buộc nghiệp vụ.
"""
class PowerAmpBuilder:
    _CLASS_NAMES = {
        "A": "Class_A",
        "AB": "Class_AB",
        "B": "Class_B",
        "C": "Class_C",
        "D": "Class_D",
    }

    def __init__(self, config: PowerAmpConfig):
        self.config = config
        self.values: Dict[str, Any] = {}
        self.components: Dict[str, Component] = {}
        self.nets: Dict[str, Net] = {}
        self.ports: Dict[str, Port] = {}
        self.constraints: Dict[str, Constraint] = {}

    # kiểm tra component có tồn tại không. Chuẩn hóa pattern 'name in self.components'.
    def _has(self, name: str) -> bool:
        return name in self.components

    # factory tạo điện trở với KiCad metadata chuẩn
    def _create_resistor(self, comp_id: str, value: float) -> Component:
        meta = KiCadMetadata.get_metadata("R", "resistor")
        return Component(
            id=comp_id, type=ComponentType.RESISTOR, pins=("1", "2"),
            parameters={"resistance": ParameterValue(value, "Ω")},
            library_id=meta.library_id, symbol_name=meta.symbol_name, footprint=meta.footprint
        )

    # factory tạo tụ điện với KiCad metadata chuẩn (phân cực / không phân cực)
    def _create_capacitor(self, comp_id: str, value: float, polarized: bool = False) -> Component:
        model = "C_Polarized" if polarized else "C"
        meta = KiCadMetadata.get_metadata(model, "capacitor")
        cap_type = ComponentType.CAPACITOR_POLARIZED if polarized else ComponentType.CAPACITOR
        return Component(
            id=comp_id, type=cap_type, pins=("1", "2"),
            parameters={"capacitance": ParameterValue(value, "F")},
            library_id=meta.library_id, symbol_name=meta.symbol_name, footprint=meta.footprint
        )

    # factory tạo cuộn cảm (Class C tank, Class D filter)
    def _create_inductor(self, comp_id: str, value: float) -> Component:
        return Component(
            id=comp_id, type=ComponentType.INDUCTOR, pins=("1", "2"),
            parameters={"inductance": ParameterValue(value, "H")},
            library_id="Device", symbol_name="L",
            footprint="Inductor_THT:L_Axial_L5.3mm_D2.2mm_P10.16mm_Horizontal"
        )

    # factory tạo diode (Class AB bias)
    def _create_diode(self, comp_id: str, model: str = "1N4148") -> Component:
        return Component(
            id=comp_id, type=ComponentType.DIODE, pins=("A", "K"),
            parameters={"model": ParameterValue(model)},
            library_id="Device", symbol_name="D",
            footprint="Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal"
        )

    # pipeline: compute → override → components → nets → ports → constraints → assemble
    def build(self) -> Circuit:
        self._compute_values()
        self._apply_overrides()
        self._create_components()
        self._create_nets()
        self._create_ports()
        self._create_constraints()
        return self._assemble_circuit()


    """ Tính toán giá trị linh kiện theo amp_class.
    Dispatch sang phương thức tính riêng cho từng class (A, B, AB, C, D).
    - Kết quả lưu vào self.values dưới dạng dict trung gian, chưa tạo Component.
    - Mỗi class có bộ giá trị khác nhau (Class A: R1,R2,RC,RE; Class B: VPEAK; Class C: L_TANK,C_TANK; ...). """
    def _compute_values(self) -> None:
        amp_class = self.config.amp_class
        if amp_class == "A":
            self._compute_class_a()
        elif amp_class == "B":
            self._compute_class_b()
        elif amp_class == "AB":
            self._compute_class_ab()
        elif amp_class == "C":
            self._compute_class_c()
        elif amp_class == "D":
            self._compute_class_d()
        else:
            raise ValueError(f"Unknown amp class: {amp_class}")


    def _compute_class_a(self) -> None:
        """Class A: transistor luôn dẫn 360°, bias ở giữa đường tải.
        Giống CE topology nhưng tối ưu cho công suất: RC, ICQ từ Pout yêu cầu."""
        series = self.config.build.resistor_series
        beta = 100.0    # hFE mặc định cho power BJT
        vbe = 0.7       # VBE silicon

        # Tính bias + RC/RE từ Pout, VCC, RL
        vals = PowerAmpCalculator.calc_class_a(
            self.config.vcc, self.config.power_output,
            self.config.load_impedance, beta, vbe, series
        )

        # Bypass capacitor cho RE (nếu build option bật)
        ce_cap = None
        if self.config.build.include_bypass_caps:
            ce_cap = PowerAmpCalculator.calc_bypass_capacitor(vals["RE"])

        # Coupling capacitors — tính theo trở kháng tương ứng
        cin = None
        cout = None
        if self.config.build.include_input_coupling:
            # Rin ≈ R1 || R2 (trở kháng bias nhìn từ ngõ vào)
            r_in = (vals["R1"] * vals["R2"]) / (vals["R1"] + vals["R2"])
            cin = PowerAmpCalculator.calc_coupling_capacitor(r_in)
        if self.config.build.include_output_coupling:
            # Rout ≈ RL (trở kháng tải speaker)
            cout = PowerAmpCalculator.calc_coupling_capacitor(self.config.load_impedance)

        # Thermal calculation — Class A tiêu tán nhiều nhiệt nhất
        thermal = PowerAmpCalculator.calc_thermal_class_a(
            self.config.vcc, vals["ICQ"], self.config.power_output
        )

        self.values = {
            "R1": vals["R1"],
            "R2": vals["R2"],
            "RC": vals["RC"],
            "RE": vals["RE"],
            "VB": vals["VB"],
            "ICQ": vals["ICQ"],
            "CE": ce_cap,
            "CIN": cin,
            "COUT": cout,
            "P_DISS": thermal["P_DISS"],
            "THETA_SA": thermal["THETA_SA"],
            "HEATSINK_NEEDED": thermal["HEATSINK_NEEDED"],
        }


    def _compute_class_b(self) -> None:
        """Class B: push-pull bổ sung, mỗi transistor dẫn 180°, không bias.
        NPN dẫn nửa dương, PNP dẫn nửa âm → méo crossover tại zero-crossing."""
        # Tính thông số output
        vals = PowerAmpCalculator.calc_class_b(
            self.config.vcc, self.config.power_output,
            self.config.load_impedance
        )

        # Coupling capacitors
        cin = None
        cout = None
        if self.config.build.include_input_coupling:
            # Input impedance ~ 1kΩ giả định (base impedance push-pull)
            cin = PowerAmpCalculator.calc_coupling_capacitor(1e3)
        if self.config.build.include_output_coupling:
            cout = PowerAmpCalculator.calc_coupling_capacitor(self.config.load_impedance)

        self.values = {
            "VPEAK": vals["VPEAK"],
            "IC_PEAK": vals["IC_PEAK"],
            "VCC_MIN": vals["VCC_MIN"],
            "EFFICIENCY": vals["EFFICIENCY"],
            "CIN": cin,
            "COUT": cout,
        }


    def _compute_class_ab(self) -> None:
        """Class AB: push-pull có 2 diode bias loại bỏ crossover distortion.
        D1+D2 tạo ~1.4V giữa base Q1 và Q2, giữ cả hai transistor mở nhẹ."""
        series = self.config.build.resistor_series
        i_bias = 15e-3  # 15mA quiescent current mặc định

        # Tính output giống Class B (cùng push-pull topology)
        b_vals = PowerAmpCalculator.calc_class_b(
            self.config.vcc, self.config.power_output,
            self.config.load_impedance
        )

        # Tính bias network (R_BIAS + 2 diode)
        bias_vals = PowerAmpCalculator.calc_class_ab_bias(
            self.config.vcc, i_bias, series
        )

        # Coupling capacitors
        cin = None
        cout = None
        if self.config.build.include_input_coupling:
            cin = PowerAmpCalculator.calc_coupling_capacitor(1e3)
        if self.config.build.include_output_coupling:
            cout = PowerAmpCalculator.calc_coupling_capacitor(self.config.load_impedance)

        # Thermal calculation — Class AB push-pull, mỗi transistor chịu ~50% tổn hao
        thermal = PowerAmpCalculator.calc_thermal_class_ab(
            self.config.vcc, self.config.power_output,
            self.config.load_impedance
        )

        self.values = {
            "R_BIAS1": bias_vals["R_BIAS1"],
            "R_BIAS2": bias_vals["R_BIAS2"],
            "I_BIAS": bias_vals["I_BIAS"],
            "VPEAK": b_vals["VPEAK"],
            "IC_PEAK": b_vals["IC_PEAK"],
            "EFFICIENCY": b_vals["EFFICIENCY"],
            "CIN": cin,
            "COUT": cout,
            "P_DISS": thermal["P_DISS_TOTAL"],
            "P_DISS_PER": thermal["P_DISS_PER_TRANSISTOR"],
            "THETA_SA": thermal["THETA_SA"],
            "HEATSINK_NEEDED": thermal["HEATSINK_NEEDED"],
        }


    def _compute_class_c(self) -> None:
        """Class C: dẫn < 180°, tank LC cộng hưởng tại tần số hoạt động.
        Transistor chỉ dẫn khi tín hiệu vượt VBE, xung năng lượng duy trì dao động LC."""
        series = self.config.build.resistor_series
        freq = self.config.frequency if self.config.frequency else 1e6  # config hoặc 1MHz default RF
        q_factor = 10.0  # Q factor mặc định

        # LC tank — cộng hưởng tại freq
        tank = PowerAmpCalculator.calc_class_c_tank(
            freq, self.config.load_impedance, q_factor
        )

        # R_BASE — self-bias cho Class C
        bias = PowerAmpCalculator.calc_class_c_bias(
            self.config.load_impedance, series
        )

        # Coupling capacitors
        cin = None
        cout = None
        if self.config.build.include_input_coupling:
            cin = PowerAmpCalculator.calc_coupling_capacitor(bias["R_BASE"])
        if self.config.build.include_output_coupling:
            cout = PowerAmpCalculator.calc_coupling_capacitor(self.config.load_impedance)

        self.values = {
            "L_TANK": tank["L_TANK"],
            "C_TANK": tank["C_TANK"],
            "R_BASE": bias["R_BASE"],
            "F0": tank["F0"],
            "Q_FACTOR": tank["Q"],
            "CIN": cin,
            "COUT": cout,
        }


    def _compute_class_d(self) -> None:
        """Class D: chuyển mạch PWM, half-bridge MOSFET, bộ lọc LC đầu ra.
        MOSFET đóng/mở toàn phần → hiệu suất >90%. LC filter chuyển PWM → analog.
        Bootstrap circuit: C_BOOT + D_BOOT cấp floating supply cho high-side gate."""
        series = self.config.build.resistor_series
        freq_cutoff = self.config.frequency if self.config.frequency else 30e3  # config hoặc 30kHz default

        # LC output filter
        lc = PowerAmpCalculator.calc_class_d_filter(
            freq_cutoff, self.config.load_impedance
        )

        # Gate resistors
        gate = PowerAmpCalculator.calc_class_d_gate(series)

        # Bootstrap capacitor — cấp floating supply cho high-side MOSFET gate
        boot = PowerAmpCalculator.calc_class_d_bootstrap()

        # Output coupling (nếu cần DC blocking cho speaker)
        cout = None
        if self.config.build.include_output_coupling:
            cout = PowerAmpCalculator.calc_coupling_capacitor(self.config.load_impedance)

        self.values = {
            "L_FILTER": lc["L_FILTER"],
            "C_FILTER": lc["C_FILTER"],
            "R_GATE1": gate["R_GATE1"],
            "R_GATE2": gate["R_GATE2"],
            "C_BOOT": boot["C_BOOT"],
            "F_CUTOFF": lc["F_CUTOFF"],
            "COUT": cout,
        }


    # Cho phép user override bất kỳ giá trị nào qua config.resistors / config.capacitors.
    # Mỗi amp_class chỉ override các giá trị tồn tại; coupling/bypass override chung.
    def _apply_overrides(self) -> None:
        amp_class = self.config.amp_class

        if amp_class == "A":
            self.values["R1"] = self.config.resistors.get("R1", self.values["R1"])
            self.values["R2"] = self.config.resistors.get("R2", self.values["R2"])
            self.values["RC"] = self.config.resistors.get("RC", self.values["RC"])
            self.values["RE"] = self.config.resistors.get("RE", self.values["RE"])

        elif amp_class == "AB":
            self.values["R_BIAS1"] = self.config.resistors.get("R_BIAS1", self.values["R_BIAS1"])
            self.values["R_BIAS2"] = self.config.resistors.get("R_BIAS2", self.values["R_BIAS2"])

        elif amp_class == "C":
            self.values["R_BASE"] = self.config.resistors.get("R_BASE", self.values["R_BASE"])

        elif amp_class == "D":
            self.values["R_GATE1"] = self.config.resistors.get("R_GATE1", self.values["R_GATE1"])
            self.values["R_GATE2"] = self.config.resistors.get("R_GATE2", self.values["R_GATE2"])
            # Bootstrap capacitor override
            if self.values.get("C_BOOT") is not None:
                self.values["C_BOOT"] = self.config.capacitors.get("C_BOOT", self.values["C_BOOT"])

        # Coupling/bypass overrides — chung cho tất cả class
        if self.values.get("CIN") is not None:
            self.values["CIN"] = self.config.capacitors.get("CIN", self.values["CIN"])
        if self.values.get("COUT") is not None:
            self.values["COUT"] = self.config.capacitors.get("COUT", self.values["COUT"])
        if self.values.get("CE") is not None:
            self.values["CE"] = self.config.capacitors.get("CE", self.values["CE"])


    """ Factory tạo tất cả Component tùy theo amp_class.
    Dispatch sang phương thức tạo riêng cho từng class.
    Sử dụng _create_resistor() / _create_capacitor() / _create_inductor() / _create_diode() factory helpers.
    GND luôn được tạo sau cùng — chung cho mọi class. """
    def _create_components(self) -> None:
        amp_class = self.config.amp_class
        if amp_class == "A":
            self._create_components_class_a()
        elif amp_class == "B":
            self._create_components_class_b()
        elif amp_class == "AB":
            self._create_components_class_ab()
        elif amp_class == "C":
            self._create_components_class_c()
        elif amp_class == "D":
            self._create_components_class_d()
        else:
            raise ValueError(f"Unknown amp class: {amp_class}")

        # Ground — luôn có
        self.components["GND"] = Component(
            id="GND", type=ComponentType.GROUND, pins=("1",),
            parameters={}
        )


    def _create_components_class_a(self) -> None:
        """Class A: Q1 (power NPN), R1, R2, RC, RE, [CIN], [COUT], [CE]."""
        v = self.values

        # Q1 — power NPN transistor (component đặc biệt, không dùng factory)
        model = self.config.output_devices[0] if self.config.output_devices else "TIP41C"
        q_meta = KiCadMetadata.get_metadata(model)
        self.components["Q1"] = Component(
            id="Q1", type=ComponentType.BJT_NPN,
            pins=("B", "C", "E"),
            parameters={"model": ParameterValue(model)},
            library_id=q_meta.library_id, symbol_name=q_meta.symbol_name,
            footprint=q_meta.footprint
        )

        # Bias resistors (R1, R2) — luôn có
        self.components["R1"] = self._create_resistor("R1", v["R1"])
        self.components["R2"] = self._create_resistor("R2", v["R2"])

        # Collector load + Emitter stabilization — luôn có
        self.components["RC"] = self._create_resistor("RC", v["RC"])
        self.components["RE"] = self._create_resistor("RE", v["RE"])

        # Coupling capacitors — tùy build option
        if v["CIN"]:
            self.components["CIN"] = self._create_capacitor("CIN", v["CIN"])
        if v["COUT"]:
            self.components["COUT"] = self._create_capacitor("COUT", v["COUT"], polarized=True)

        # Bypass capacitor (CE) — tùy build option (polarized)
        if v["CE"]:
            self.components["CE"] = self._create_capacitor("CE", v["CE"], polarized=True)


    def _create_components_class_b(self) -> None:
        """Class B: Q1 (NPN), Q2 (PNP), [CIN], [COUT].
        Push-pull bổ sung — không có bias resistor, không CE."""
        v = self.values

        # Q1 — NPN output transistor
        model_npn = self.config.output_devices[0] if len(self.config.output_devices) > 0 else "TIP31C"
        q1_meta = KiCadMetadata.get_metadata(model_npn)
        self.components["Q1"] = Component(
            id="Q1", type=ComponentType.BJT_NPN,
            pins=("B", "C", "E"),
            parameters={"model": ParameterValue(model_npn)},
            library_id=q1_meta.library_id, symbol_name=q1_meta.symbol_name,
            footprint=q1_meta.footprint
        )

        # Q2 — PNP output transistor
        model_pnp = self.config.output_devices[1] if len(self.config.output_devices) > 1 else "TIP32C"
        q2_meta = KiCadMetadata.get_metadata(model_pnp)
        self.components["Q2"] = Component(
            id="Q2", type=ComponentType.BJT_PNP,
            pins=("B", "C", "E"),
            parameters={"model": ParameterValue(model_pnp)},
            library_id=q2_meta.library_id, symbol_name=q2_meta.symbol_name,
            footprint=q2_meta.footprint
        )

        # Coupling capacitors
        if v["CIN"]:
            self.components["CIN"] = self._create_capacitor("CIN", v["CIN"])
        if v["COUT"]:
            self.components["COUT"] = self._create_capacitor("COUT", v["COUT"], polarized=True)


    def _create_components_class_ab(self) -> None:
        """Class AB: Q1 (NPN), Q2 (PNP), D1, D2, R_BIAS1, R_BIAS2, [CIN], [COUT].
        Push-pull + 2 diode bias chain loại bỏ crossover distortion."""
        v = self.values

        # Q1 — NPN output transistor
        model_npn = self.config.output_devices[0] if len(self.config.output_devices) > 0 else "TIP31C"
        q1_meta = KiCadMetadata.get_metadata(model_npn)
        self.components["Q1"] = Component(
            id="Q1", type=ComponentType.BJT_NPN,
            pins=("B", "C", "E"),
            parameters={"model": ParameterValue(model_npn)},
            library_id=q1_meta.library_id, symbol_name=q1_meta.symbol_name,
            footprint=q1_meta.footprint
        )

        # Q2 — PNP output transistor
        model_pnp = self.config.output_devices[1] if len(self.config.output_devices) > 1 else "TIP32C"
        q2_meta = KiCadMetadata.get_metadata(model_pnp)
        self.components["Q2"] = Component(
            id="Q2", type=ComponentType.BJT_PNP,
            pins=("B", "C", "E"),
            parameters={"model": ParameterValue(model_pnp)},
            library_id=q2_meta.library_id, symbol_name=q2_meta.symbol_name,
            footprint=q2_meta.footprint
        )

        # D1, D2 — bias diodes (silicon, ~0.7V mỗi diode)
        self.components["D1"] = self._create_diode("D1")
        self.components["D2"] = self._create_diode("D2")

        # Bias resistors — đặt dòng qua diode chain
        self.components["R_BIAS1"] = self._create_resistor("R_BIAS1", v["R_BIAS1"])
        self.components["R_BIAS2"] = self._create_resistor("R_BIAS2", v["R_BIAS2"])

        # Coupling capacitors
        if v["CIN"]:
            self.components["CIN"] = self._create_capacitor("CIN", v["CIN"])
        if v["COUT"]:
            self.components["COUT"] = self._create_capacitor("COUT", v["COUT"], polarized=True)


    def _create_components_class_c(self) -> None:
        """Class C: Q1 (NPN), L_TANK, C_TANK, R_BASE, [CIN], [COUT].
        Tank LC cộng hưởng tại f0, transistor xung năng lượng cho tank."""
        v = self.values

        # Q1 — NPN RF/power transistor
        model = self.config.output_devices[0] if self.config.output_devices else "2N3904"
        q_meta = KiCadMetadata.get_metadata(model)
        self.components["Q1"] = Component(
            id="Q1", type=ComponentType.BJT_NPN,
            pins=("B", "C", "E"),
            parameters={"model": ParameterValue(model)},
            library_id=q_meta.library_id, symbol_name=q_meta.symbol_name,
            footprint=q_meta.footprint
        )

        # LC tank — cộng hưởng
        self.components["L_TANK"] = self._create_inductor("L_TANK", v["L_TANK"])
        self.components["C_TANK"] = self._create_capacitor("C_TANK", v["C_TANK"])

        # R_BASE — self-bias (base kéo về GND)
        self.components["R_BASE"] = self._create_resistor("R_BASE", v["R_BASE"])

        # Coupling capacitors
        if v["CIN"]:
            self.components["CIN"] = self._create_capacitor("CIN", v["CIN"])
        if v["COUT"]:
            self.components["COUT"] = self._create_capacitor("COUT", v["COUT"])


    def _create_components_class_d(self) -> None:
        """Class D: Q1, Q2 (MOSFET_N), L_FILTER, C_FILTER, R_GATE1, R_GATE2, C_BOOT, D_BOOT, [COUT].
        Half-bridge MOSFET + LC Butterworth filter + bootstrap circuit."""
        v = self.values

        # Q1 — high-side N-MOSFET
        model_hs = self.config.output_devices[0] if len(self.config.output_devices) > 0 else "IRF540N"
        q1_meta = KiCadMetadata.get_metadata(model_hs)
        self.components["Q1"] = Component(
            id="Q1", type=ComponentType.MOSFET_N,
            pins=("G", "D", "S"),
            parameters={"model": ParameterValue(model_hs)},
            library_id=q1_meta.library_id, symbol_name=q1_meta.symbol_name,
            footprint=q1_meta.footprint
        )

        # Q2 — low-side N-MOSFET
        model_ls = self.config.output_devices[1] if len(self.config.output_devices) > 1 else "IRF540N"
        q2_meta = KiCadMetadata.get_metadata(model_ls)
        self.components["Q2"] = Component(
            id="Q2", type=ComponentType.MOSFET_N,
            pins=("G", "D", "S"),
            parameters={"model": ParameterValue(model_ls)},
            library_id=q2_meta.library_id, symbol_name=q2_meta.symbol_name,
            footprint=q2_meta.footprint
        )

        # LC output filter
        self.components["L_FILTER"] = self._create_inductor("L_FILTER", v["L_FILTER"])
        self.components["C_FILTER"] = self._create_capacitor("C_FILTER", v["C_FILTER"])

        # Gate resistors — giới hạn dòng nạp/xả gate
        self.components["R_GATE1"] = self._create_resistor("R_GATE1", v["R_GATE1"])
        self.components["R_GATE2"] = self._create_resistor("R_GATE2", v["R_GATE2"])

        # Bootstrap circuit — cấp floating supply cho high-side MOSFET gate
        # C_BOOT: nạp khi low-side ON, cấp VGS cho high-side khi VSW lên cao
        self.components["C_BOOT"] = self._create_capacitor("C_BOOT", v["C_BOOT"])
        # D_BOOT: diode nạp C_BOOT từ VCC_GATE, chặn dòng ngược khi VSW cao
        self.components["D_BOOT"] = self._create_diode("D_BOOT", "1N4148")

        # Output coupling (nếu cần DC blocking)
        if v["COUT"]:
            self.components["COUT"] = self._create_capacitor("COUT", v["COUT"], polarized=True)


    # Tạo nets dispatch theo amp_class
    def _create_nets(self) -> None:
        amp_class = self.config.amp_class
        if amp_class == "A":
            self._create_nets_class_a()
        elif amp_class == "B":
            self._create_nets_class_b()
        elif amp_class == "AB":
            self._create_nets_class_ab()
        elif amp_class == "C":
            self._create_nets_class_c()
        elif amp_class == "D":
            self._create_nets_class_d()
        else:
            raise ValueError(f"Unknown amp class: {amp_class}")


    """ Class A nets — tương tự CE topology:
        VCC → R1.1, RC.1
        VBIAS → R1.2, R2.1, [CIN.2 hoặc Q1.B]
        VCOLLECTOR → RC.2, Q1.C, [COUT.1]
        VEMITTER → Q1.E, RE.1, [CE.1]
        GND → GND.1, R2.2, RE.2, [CE.2] """
    def _create_nets_class_a(self) -> None:
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")
        has_ce = self._has("CE")

        # VCC net: R1 trên + RC trên
        self.nets["VCC"] = Net("VCC", (
            PinRef("R1", "1"),
            PinRef("RC", "1"),
        ))

        # VBIAS net: R1 dưới + R2 trên + [CIN hoặc Q1.B]
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
                PinRef("Q1", "B"),
            ))

        # VCOLLECTOR net: RC dưới + Q1.C + [COUT]
        vcoll_pins = [PinRef("RC", "2"), PinRef("Q1", "C")]
        if has_cout:
            vcoll_pins.append(PinRef("COUT", "1"))
        self.nets["VCOLLECTOR"] = Net("VCOLLECTOR", tuple(vcoll_pins))

        # VOUT net (nếu có COUT)
        if has_cout:
            self.nets["VOUT"] = Net("VOUT", (PinRef("COUT", "2"),))

        # VEMITTER net: Q1.E + RE trên + [CE]
        vemit_pins = [PinRef("Q1", "E"), PinRef("RE", "1")]
        if has_ce:
            vemit_pins.append(PinRef("CE", "1"))
        self.nets["VEMITTER"] = Net("VEMITTER", tuple(vemit_pins))

        # GND net
        gnd_pins = [PinRef("GND", "1"), PinRef("R2", "2"), PinRef("RE", "2")]
        if has_ce:
            gnd_pins.append(PinRef("CE", "2"))
        self.nets["GND"] = Net("GND", tuple(gnd_pins))


    """ Class B nets — push-pull bổ sung (complementary):
        VCC → Q1.C (NPN collector nối VCC)
        VDRIVE → Q1.B, Q2.B, [CIN.2] (cả hai base nối chung, tín hiệu vào)
        VMID → Q1.E, Q2.E, [COUT.1] (output mid-point, nơi emitter gặp nhau)
        GND → GND.1, Q2.C (PNP collector nối GND) """
    def _create_nets_class_b(self) -> None:
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")

        # VCC net: Q1 collector (NPN top half)
        self.nets["VCC"] = Net("VCC", (
            PinRef("Q1", "C"),
        ))

        # VDRIVE net: Q1.B + Q2.B + [CIN]
        vdrive_pins = [PinRef("Q1", "B"), PinRef("Q2", "B")]
        if has_cin:
            vdrive_pins.append(PinRef("CIN", "2"))
        self.nets["VDRIVE"] = Net("VDRIVE", tuple(vdrive_pins))

        # VIN net (nếu có CIN)
        if has_cin:
            self.nets["VIN"] = Net("VIN", (PinRef("CIN", "1"),))

        # VMID net: Q1.E + Q2.E + [COUT] (output: nơi emitter gặp nhau)
        vmid_pins = [PinRef("Q1", "E"), PinRef("Q2", "E")]
        if has_cout:
            vmid_pins.append(PinRef("COUT", "1"))
        self.nets["VMID"] = Net("VMID", tuple(vmid_pins))

        # VOUT net (nếu có COUT)
        if has_cout:
            self.nets["VOUT"] = Net("VOUT", (PinRef("COUT", "2"),))

        # GND net: Q2 collector (PNP bottom half)
        self.nets["GND"] = Net("GND", (
            PinRef("GND", "1"),
            PinRef("Q2", "C"),
        ))


    """ Class AB nets — push-pull có bias diode:
        VCC → Q1.C, R_BIAS1.1
        VBIAS_TOP → R_BIAS1.2, D1.A (anode), Q1.B
        VDRIVE → D1.K (cathode), D2.A (anode), [CIN.2] (input drive point, giữa 2 diode)
        VBIAS_BOT → D2.K (cathode), R_BIAS2.1, Q2.B
        VMID → Q1.E, Q2.E, [COUT.1] (output mid-point)
        GND → GND.1, Q2.C, R_BIAS2.2 """
    def _create_nets_class_ab(self) -> None:
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")

        # VCC net: Q1 collector + R_BIAS1 trên
        self.nets["VCC"] = Net("VCC", (
            PinRef("Q1", "C"),
            PinRef("R_BIAS1", "1"),
        ))

        # VBIAS_TOP: R_BIAS1 dưới + D1 anode + Q1 base
        self.nets["VBIAS_TOP"] = Net("VBIAS_TOP", (
            PinRef("R_BIAS1", "2"),
            PinRef("D1", "A"),
            PinRef("Q1", "B"),
        ))

        # VDRIVE: D1 cathode + D2 anode + [CIN] (điểm giữa diode chain)
        vdrive_pins = [PinRef("D1", "K"), PinRef("D2", "A")]
        if has_cin:
            vdrive_pins.append(PinRef("CIN", "2"))
        self.nets["VDRIVE"] = Net("VDRIVE", tuple(vdrive_pins))

        # VIN net (nếu có CIN)
        if has_cin:
            self.nets["VIN"] = Net("VIN", (PinRef("CIN", "1"),))

        # VBIAS_BOT: D2 cathode + R_BIAS2 trên + Q2 base
        self.nets["VBIAS_BOT"] = Net("VBIAS_BOT", (
            PinRef("D2", "K"),
            PinRef("R_BIAS2", "1"),
            PinRef("Q2", "B"),
        ))

        # VMID: Q1.E + Q2.E + [COUT] (output mid-point)
        vmid_pins = [PinRef("Q1", "E"), PinRef("Q2", "E")]
        if has_cout:
            vmid_pins.append(PinRef("COUT", "1"))
        self.nets["VMID"] = Net("VMID", tuple(vmid_pins))

        # VOUT net (nếu có COUT)
        if has_cout:
            self.nets["VOUT"] = Net("VOUT", (PinRef("COUT", "2"),))

        # GND net: Q2 collector + R_BIAS2 dưới
        self.nets["GND"] = Net("GND", (
            PinRef("GND", "1"),
            PinRef("Q2", "C"),
            PinRef("R_BIAS2", "2"),
        ))


    """ Class C nets — tank LC cộng hưởng:
        VCC → L_TANK.1 (cấp DC cho collector qua cuộn cảm)
        VCOLLECTOR → L_TANK.2, C_TANK.1, Q1.C, [COUT.1] (tank + collector)
        VDRIVE → R_BASE.1, Q1.B, [CIN.2] (base drive + self-bias)
        GND → GND.1, C_TANK.2, Q1.E, R_BASE.2 """
    def _create_nets_class_c(self) -> None:
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")

        # VCC net: L_TANK trên (DC qua cuộn cảm đến collector)
        self.nets["VCC"] = Net("VCC", (
            PinRef("L_TANK", "1"),
        ))

        # VCOLLECTOR net: L_TANK dưới + C_TANK trên + Q1.C + [COUT]
        vcoll_pins = [
            PinRef("L_TANK", "2"),
            PinRef("C_TANK", "1"),
            PinRef("Q1", "C"),
        ]
        if has_cout:
            vcoll_pins.append(PinRef("COUT", "1"))
        self.nets["VCOLLECTOR"] = Net("VCOLLECTOR", tuple(vcoll_pins))

        # VOUT net (nếu có COUT)
        if has_cout:
            self.nets["VOUT"] = Net("VOUT", (PinRef("COUT", "2"),))

        # VDRIVE net: R_BASE trên + Q1.B + [CIN]
        vdrive_pins = [PinRef("R_BASE", "1"), PinRef("Q1", "B")]
        if has_cin:
            vdrive_pins.append(PinRef("CIN", "2"))
        self.nets["VDRIVE"] = Net("VDRIVE", tuple(vdrive_pins))

        # VIN net (nếu có CIN)
        if has_cin:
            self.nets["VIN"] = Net("VIN", (PinRef("CIN", "1"),))

        # GND net: C_TANK dưới + Q1.E + R_BASE dưới
        self.nets["GND"] = Net("GND", (
            PinRef("GND", "1"),
            PinRef("C_TANK", "2"),
            PinRef("Q1", "E"),
            PinRef("R_BASE", "2"),
        ))


    """ Class D nets — half-bridge MOSFET + LC filter + bootstrap:
        VCC → Q1.D (high-side drain)
        VSW → Q1.S, Q2.D, L_FILTER.1, C_BOOT.2 (switching node + bootstrap return)
        VBOOT → D_BOOT.K, C_BOOT.1 (bootstrap floating supply)
        VCC_GATE → D_BOOT.A (gate driver supply, nạp C_BOOT)
        VOUT_FILTER → L_FILTER.2, C_FILTER.1, [COUT.1] (output sau LC filter)
        VGATE1 → R_GATE1.2, Q1.G (high-side gate drive)
        VGATE2 → R_GATE2.2, Q2.G (low-side gate drive)
        VPWM_H → R_GATE1.1 (PWM high input)
        VPWM_L → R_GATE2.1 (PWM low input)
        GND → GND.1, Q2.S, C_FILTER.2 """
    def _create_nets_class_d(self) -> None:
        has_cout = self._has("COUT")

        # VCC net: Q1 drain (high-side MOSFET)
        self.nets["VCC"] = Net("VCC", (
            PinRef("Q1", "D"),
        ))

        # VSW net: switching node — Q1.S + Q2.D + L_FILTER input + C_BOOT return
        self.nets["VSW"] = Net("VSW", (
            PinRef("Q1", "S"),
            PinRef("Q2", "D"),
            PinRef("L_FILTER", "1"),
            PinRef("C_BOOT", "2"),
        ))

        # VBOOT net: D_BOOT cathode + C_BOOT trên (floating supply cho high-side gate)
        self.nets["VBOOT"] = Net("VBOOT", (
            PinRef("D_BOOT", "K"),
            PinRef("C_BOOT", "1"),
        ))

        # VCC_GATE net: D_BOOT anode (gate driver supply nạp C_BOOT qua D_BOOT)
        self.nets["VCC_GATE"] = Net("VCC_GATE", (
            PinRef("D_BOOT", "A"),
        ))

        # VOUT_FILTER net: L_FILTER output + C_FILTER + [COUT]
        vout_pins = [PinRef("L_FILTER", "2"), PinRef("C_FILTER", "1")]
        if has_cout:
            vout_pins.append(PinRef("COUT", "1"))
        self.nets["VOUT_FILTER"] = Net("VOUT_FILTER", tuple(vout_pins))

        # VOUT net (nếu có COUT)
        if has_cout:
            self.nets["VOUT"] = Net("VOUT", (PinRef("COUT", "2"),))

        # VGATE1 net: R_GATE1 output + Q1 gate (high-side)
        self.nets["VGATE1"] = Net("VGATE1", (
            PinRef("R_GATE1", "2"),
            PinRef("Q1", "G"),
        ))

        # VGATE2 net: R_GATE2 output + Q2 gate (low-side)
        self.nets["VGATE2"] = Net("VGATE2", (
            PinRef("R_GATE2", "2"),
            PinRef("Q2", "G"),
        ))

        # VPWM_H net: R_GATE1 input (PWM high-side signal)
        self.nets["VPWM_H"] = Net("VPWM_H", (
            PinRef("R_GATE1", "1"),
        ))

        # VPWM_L net: R_GATE2 input (PWM low-side signal)
        self.nets["VPWM_L"] = Net("VPWM_L", (
            PinRef("R_GATE2", "1"),
        ))

        # GND net: Q2 source + C_FILTER dưới
        self.nets["GND"] = Net("GND", (
            PinRef("GND", "1"),
            PinRef("Q2", "S"),
            PinRef("C_FILTER", "2"),
        ))


    # Tạo ports — KHÁC NHAU theo amp_class, chuẩn hóa interface
    def _create_ports(self) -> None:
        """ Tạo ports I/O boundary. Mỗi amp_class có output/input net khác nhau:
            A: output = VCOLLECTOR (hoặc VOUT); input = VBIAS (hoặc VIN)
            B: output = VMID (hoặc VOUT); input = VDRIVE (hoặc VIN)
            AB: output = VMID (hoặc VOUT); input = VDRIVE (hoặc VIN)
            C: output = VCOLLECTOR (hoặc VOUT); input = VDRIVE (hoặc VIN)
            D: output = VOUT_FILTER (hoặc VOUT); input = PWM_H, PWM_L
        VCC, GND luôn có. """
        amp_class = self.config.amp_class
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")

        # VCC — luôn có
        self.ports["VCC"] = Port("VCC", "VCC", PortDirection.POWER)

        # GND — luôn có
        self.ports["GND"] = Port("GND", "GND", PortDirection.GROUND)

        # VIN / input — tùy amp_class
        if amp_class == "A":
            if has_cin:
                self.ports["VIN"] = Port("VIN", "VIN", PortDirection.INPUT)
            else:
                self.ports["VIN"] = Port("VIN", "VBIAS", PortDirection.INPUT)
        elif amp_class in ("B", "AB", "C"):
            if has_cin:
                self.ports["VIN"] = Port("VIN", "VIN", PortDirection.INPUT)
            else:
                self.ports["VIN"] = Port("VIN", "VDRIVE", PortDirection.INPUT)
        elif amp_class == "D":
            # Class D: 2 input ports cho PWM high/low + bootstrap supply
            self.ports["PWM_H"] = Port("PWM_H", "VPWM_H", PortDirection.INPUT)
            self.ports["PWM_L"] = Port("PWM_L", "VPWM_L", PortDirection.INPUT)
            self.ports["VCC_GATE"] = Port("VCC_GATE", "VCC_GATE", PortDirection.POWER)

        # VOUT / output — tùy amp_class
        if amp_class in ("A", "C"):
            if has_cout:
                self.ports["VOUT"] = Port("VOUT", "VOUT", PortDirection.OUTPUT)
            else:
                self.ports["VOUT"] = Port("VOUT", "VCOLLECTOR", PortDirection.OUTPUT)
        elif amp_class in ("B", "AB"):
            if has_cout:
                self.ports["VOUT"] = Port("VOUT", "VOUT", PortDirection.OUTPUT)
            else:
                self.ports["VOUT"] = Port("VOUT", "VMID", PortDirection.OUTPUT)
        elif amp_class == "D":
            if has_cout:
                self.ports["VOUT"] = Port("VOUT", "VOUT", PortDirection.OUTPUT)
            else:
                self.ports["VOUT"] = Port("VOUT", "VOUT_FILTER", PortDirection.OUTPUT)


    # Gắn constraints nghiệp vụ: amp_class, power, load, VCC, efficiency, coupling, thermal, frequency
    def _create_constraints(self) -> None:
        amp_class = self.config.amp_class

        # --- constraints cơ bản ---
        self.constraints["amp_class"] = Constraint("amp_class", amp_class)
        self.constraints["power_output"] = Constraint("power_output", self.config.power_output, "W")
        self.constraints["load_impedance"] = Constraint("load_impedance", self.config.load_impedance, "Ω")
        self.constraints["vcc"] = Constraint("vcc", self.config.vcc, "V")
        self.constraints["efficiency"] = Constraint("efficiency_target", self.config.efficiency_target)
        self.constraints["input_coupled"] = Constraint("input_coupled", self._has("CIN"))
        self.constraints["output_coupled"] = Constraint("output_coupled", self._has("COUT"))

        # --- thermal constraints (Class A / AB) ---
        if amp_class in ("A", "AB"):
            self.constraints["power_dissipation"] = Constraint(
                "power_dissipation", self.values.get("P_DISS", 0), "W"
            )
            self.constraints["heatsink_needed"] = Constraint(
                "heatsink_needed", self.values.get("HEATSINK_NEEDED", False)
            )
            theta_sa = self.values.get("THETA_SA", 0)
            if theta_sa > 0:
                self.constraints["heatsink_thermal_resistance"] = Constraint(
                    "heatsink_thermal_resistance", round(theta_sa, 2), "°C/W"
                )

        # --- frequency constraint (Class C / D) ---
        if amp_class == "C":
            self.constraints["frequency"] = Constraint(
                "frequency", self.config.frequency or 1e6, "Hz"
            )
        elif amp_class == "D":
            self.constraints["frequency"] = Constraint(
                "frequency", self.config.frequency or 30e3, "Hz"
            )
            # dead-time tiêu biểu 200 ns, tránh shoot-through
            self.constraints["dead_time"] = Constraint(
                "dead_time", 200e-9, "s"
            )


    # Tạo assemble circuit từ components, nets, ports, constraints
    def _assemble_circuit(self) -> Circuit:
        class_name = self._CLASS_NAMES.get(self.config.amp_class, self.config.amp_class)
        return Circuit(
            name=f"PowerAmp_{class_name}_{int(self.config.power_output)}W",
            _components=self.components,
            _nets=self.nets,
            _ports=self.ports,
            _constraints=self.constraints,
        )
