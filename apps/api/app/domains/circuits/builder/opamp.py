""" Op-Amp Amplifier Builder - Inverting, Non-Inverting, Differential topologies.
* Inverting: đảo pha, gain = -R2/R1, trở kháng vào = R1
* Non-Inverting: không đảo pha, gain = 1 + R2/R1, trở kháng vào rất cao
* Differential: khuếch đại hiệu, gain = R2/R1 · (V+ - V-), CMRR cao
* Instrumentation: 3 op-amp, gain = 1 + 2·R1/RG, CMRR rất cao, Rin cực lớn
Tạo pipeline pattern để xây dựng mạch:
1. _compute_values() - Tính toán giá trị linh kiện
2. _apply_overrides() - Cập nhật thay đổi từ user
3. _create_components() - Tạo component thực tế
4. _create_nets() - Tạo nối dây theo topology
5. _create_ports() - Xác định cổng I/O
6. _create_constraints() - Gắn ràng buộc nghiệp vụ
7. _assemble_circuit() - Tạo đối tượng Circuit hoàn chỉnh
"""


from dataclasses import dataclass, field
from typing import Dict, Any, Literal

from ..entities import (
    Circuit, Component, Net, Port, Constraint, PinRef,
    ComponentType, PortDirection, ParameterValue
)
from .common import (
    PreferredSeries, BuildOptions, ComponentCalculator, KiCadMetadata
)

""" Lý do sử dụng thư viện:
_dataclass: dùng để định nghĩa cấu hình OpAmpConfig.
_field: dùng để khởi tạo dict mặc định cho overrides linh kiện.
typing: dùng để khai báo kiểu dữ liệu cho cấu hình và builder.
..entities: nhập các lớp domain như Circuit, Component, Net, Port, Constraint, PinRef, ComponentType, PortDirection, ParameterValue để xây dựng mạch.
.common: nhập các tiện ích chung như PreferredSeries, BuildOptions, ComponentCalculator, KiCadMetadata để hỗ trợ tính toán và metadata linh kiện.
"""



""" Cấu hình cho Op-Amp amplifier (Inverting, Non-Inverting, Differential).
Cho phép tùy chỉnh các thông số gain, trở kháng đầu vào, model op-amp, cũng như override linh kiện và build options cho từng mạch Op-Amp cụ thể.
Args:
 * topology (Literal["inverting", "non_inverting", "differential"]): Kiểu topology mạch Op-Amp.
 * gain (float): Hệ số khuếch đại mục tiêu (dùng giá trị tuyệt đối cho inverting).
 * input_impedance (float): Trở kháng đầu vào mong muốn (Ω) — quyết định R1.
 * opamp_model (str): Model op-amp sử dụng (VD: "LM358").
 * resistors (Dict[str, float]): Override giá trị điện trở (theo key: "R1", "R2", ...).
 * capacitors (Dict[str, float]): Override giá trị tụ điện (theo key).
 * build (BuildOptions): Tùy chọn build chi tiết.
"""
@dataclass
class OpAmpConfig:
    topology: Literal["inverting", "non_inverting", "differential", "instrumentation"]
    gain: float = 10.0              # hệ số khuếch đại mục tiêu
    input_impedance: float = 10e3   # trở kháng đầu vào (Ω), quyết định R1
    # cập nhật linh kiện
    opamp_model: str = "LM358"
    resistors: Dict[str, float] = field(default_factory=dict)
    capacitors: Dict[str, float] = field(default_factory=dict)
    # ina-specific: gain resistor (càng nhỏ → gain càng cao)
    gain_resistor: float | None = None
    # tùy chọn build
    build: BuildOptions = field(default_factory=BuildOptions)


""" Bộ tính toán chuyên dụng cho Op-Amp (Inverting, Non-Inverting, Differential).
Cung cấp các hàm tính toán điện trở feedback/input cho từng topology, phục vụ cho việc thiết kế mạch Op-Amp.
Methods:
 * calc_inverting(gain, input_impedance, series) -> Dict[str, float]:
   Tính giá trị điện trở cho mạch inverting: Vout = -(R2/R1)·Vin
    Args: gain mục tiêu, trở kháng đầu vào (quyết định R1), E series chuẩn.
    Logic: - R1 = input_impedance (chuẩn hóa theo E series)
           - R2 = gain ✕ R1 (feedback resistor quyết định độ lợi)
           - Gain thực tế: Av = -R2/R1 (đảo pha, dấu âm)
           - Trở kháng vào: Rin ≈ R1 (virtual ground tại IN-)
    Returns: dictionary chứa R1, R2 đã chuẩn hóa.

 * calc_non_inverting(gain, input_impedance, series) -> Dict[str, float]:
   Tính giá trị điện trở cho mạch non-inverting: Vout = (1 + R2/R1)·Vin
    Args: gain mục tiêu, trở kháng cho R1, E series chuẩn.
    Logic: - R1 = input_impedance (chuẩn hóa, R1 nối từ IN- xuống GND)
           - R2 = (gain - 1) ✕ R1 (feedback từ output về IN-)
           - Gain thực tế: Av = 1 + R2/R1 (không đảo pha)
           - Trở kháng vào: Rin ≈ ∞ (op-amp lý tưởng, IN+ có trở kháng cực cao)
    Returns: dictionary chứa R1, R2 đã chuẩn hóa.

 * calc_differential(gain, input_impedance, series) -> Dict[str, float]:
   Tính giá trị điện trở cho mạch differential: Vout = (R2/R1)·(V+ - V-)
    Args: gain mục tiêu, trở kháng cho R1/R3, E series chuẩn.
    Logic: - Balanced: R1=R3, R2=R4 (đảm bảo CMRR cao)
           - R1 = input_impedance (chuẩn hóa)
           - R2 = gain ✕ R1
           - Gain = R2/R1 khi cân bằng (R1=R3, R2=R4)
    Returns: dictionary chứa R1, R2, R3, R4 đã chuẩn hóa.

 * calc_instrumentation(gain, input_impedance, rg_override, series) -> Dict[str, float]:
   Tính giá trị điện trở cho mạch INA 3-op-amp: Av = (1 + 2·R1/RG) · (R3/R2)
    Args: gain mục tiêu, trở kháng đầu vào, RG override (optional), E series chuẩn.
    Logic: - Simplified: R2=R3=R4=R5 → Av = 1 + 2·R1/RG
           - R1 = input_impedance (buffer stage feedback)
           - RG = 2·R1/(gain - 1) (gain-setting resistor)
           - Stage 2: balanced differential (R2=R3, R4=R5)
    Returns: dictionary chứa R1, RG, R2, R3, R4, R5, Av đã chuẩn hóa.
"""
class OpAmpCalculator:

    @staticmethod
    def calc_inverting(
        gain: float, input_impedance: float,
        series: PreferredSeries = PreferredSeries.E12
    ) -> Dict[str, float]:
        """Inverting: Av = -R2/R1, Rin ≈ R1"""
        gain = abs(gain)
        r1 = ComponentCalculator.standardize(input_impedance, series)
        r2_ideal = gain * r1
        r2 = ComponentCalculator.standardize(r2_ideal, series)
        return {
            "R1": ParameterValue(r1, "Ω"),
            "R2": ParameterValue(r2, "Ω")
        }

    @staticmethod
    def calc_non_inverting(
        gain: float, input_impedance: float,
        series: PreferredSeries = PreferredSeries.E12
    ) -> Dict[str, float]:
        """Non-Inverting: Av = 1 + R2/R1, Rin ≈ ∞"""
        r1 = ComponentCalculator.standardize(input_impedance, series)
        r2_ideal = (gain - 1.0) * r1
        r2 = ComponentCalculator.standardize(r2_ideal, series)
        return {
            "R1": ParameterValue(r1, "Ω"),
            "R2": ParameterValue(r2, "Ω")
        }

    @staticmethod
    def calc_differential(
        gain: float, input_impedance: float,
        series: PreferredSeries = PreferredSeries.E12
    ) -> Dict[str, float]:
        """Differential: Av = R2/R1 · (V+ - V-), balanced R1=R3, R2=R4"""
        gain = abs(gain)
        r1 = ComponentCalculator.standardize(input_impedance, series)
        r2_ideal = gain * r1
        r2 = ComponentCalculator.standardize(r2_ideal, series)
        return {
            "R1": ParameterValue(r1, "Ω"),
            "R2": ParameterValue(r2, "Ω"),
            "R3": ParameterValue(r1, "Ω"),
            "R4": ParameterValue(r2, "Ω")
        }
    
    
    @staticmethod
    def calc_instrumentation(
        gain: float,
        input_impedance: float = 10e3,
        rg_override: float | None = None,
        series: PreferredSeries = PreferredSeries.E12
    ) -> Dict[str, float]:
        """Instrumentation Amplifier 3-op-amp:
        Av = (1 + 2*R1/RG) * (R3/R2)
        
        Simplified: R2=R3=R4=R5 → Av = 1 + 2*R1/RG
        
        Args:
            gain: Hệ số khuếch đại tổng mục tiêu
            input_impedance: Quyết định R1 (cặp đầu vào)
            rg_override: Nếu user chỉ định RG trực tiếp
            series: E12/E24 chuẩn hóa
            
        Returns:
            Dict chứa R1, RG, R2, R3, R4, R5 đã chuẩn hóa
        """
        # Stage 1: R1a = R1b (input resistors tầng buffer)
        r1 = ComponentCalculator.standardize(input_impedance, series)
        
        # Stage 2: R2 = R3 = R4 = R5 (differential stage, balanced)
        # Thông thường chọn R2 = 10kΩ standard
        r2 = ComponentCalculator.standardize(10e3, series)
        r3 = r4 = r5 = r2
        
        # Tính RG từ gain: gain = 1 + 2*R1/RG → RG = 2*R1/(gain - 1)
        if rg_override is not None:
            rg = ComponentCalculator.standardize(rg_override, series)
        else:
            if gain <= 1.0:
                raise ValueError("INA gain phải > 1. Hãy tăng gain hoặc điều chỉnh R1/RG để gain > 1.")
            rg_ideal = (2 * r1) / (gain - 1.0)
            rg = ComponentCalculator.standardize(rg_ideal, series)
        
        # Gain thực tế sau khi chuẩn hóa
        av_actual = 1.0 + (2 * r1 / rg)
        
        return {
            "R1": ParameterValue(r1, "Ω"),      # R1a, R1b (input stage)
            "RG": ParameterValue(rg, "Ω"),      # gain resistor
            "R2": ParameterValue(r2, "Ω"),      # differential stage
            "R3": ParameterValue(r3, "Ω"),
            "R4": ParameterValue(r4, "Ω"),
            "R5": ParameterValue(r5, "Ω"),
            "Av": ParameterValue(av_actual, "")
        }

        

""" Builder cho Op-Amp amplifier topologies (Inverting, Non-Inverting, Differential, Instrumentation).
Sử dụng pipeline pattern để tách biệt các bước xây dựng mạch, cho phép các topology dùng chung logic override, tạo component và chỉ khác nhau ở topology wiring (nets) và ports.
Attributes:
 - config (OpAmpConfig): Cấu hình Op-Amp amplifier.
 - values (Dict[str, Any]): Giá trị trung gian sau compute + override (R1, R2, R3, R4, RG, R5).
 - components (Dict[str, Component]): Danh sách linh kiện đã tạo.
 - nets (Dict[str, Net]): Danh sách net kết nối.
 - ports (Dict[str, Port]): Danh sách port I/O.
 - constraints (Dict[str, Constraint]): Danh sách ràng buộc nghiệp vụ.
"""
class OpAmpAmplifierBuilder:
    _TOPOLOGY_NAMES = {
        "inverting": "Inverting",
        "non_inverting": "Non_Inverting",
        "differential": "Differential",
        "instrumentation": "Instrumentation"
    }

    def __init__(self, config: OpAmpConfig):
        self.config = config
        self.values: Dict[str, Any] = {}
        self.components: Dict[str, Component] = {}
        self.nets: Dict[str, Net] = {}
        self.ports: Dict[str, Port] = {}
        self.constraints: Dict[str, Constraint] = {}

    # kiểm tra component có tồn tại không. Chuẩn hóa pattern "name in self.components".
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

    """ Tính toán giá trị điện trở từ OpAmpCalculator.
    - lưu kết quả vào self.values dưới dạng dict trung gian, chưa tạo Component.
    - Inverting/Non-Inverting dùng R1, R2.
    - Differential dùng R1, R2, R3, R4 (balanced: R1=R3, R2=R4).
    - Instrumentation dùng R1, RG, R2, R3, R4, R5 (3-op-amp INA).
    """
    def _compute_values(self) -> None:
        series = self.config.build.resistor_series
        topology = self.config.topology

        if topology == "inverting":
            # Inverting: Av = -R2/R1, Rin ≈ R1
            calc = OpAmpCalculator.calc_inverting(
                self.config.gain, self.config.input_impedance, series
            )
            r1 = calc["R1"]
            r2 = calc["R2"]
            # Gain thực tế (đảo pha)
            av = -(r2 / r1)
            rin = r1  # trở kháng vào ≈ R1 (virtual ground)
            rout = 0.0  # op-amp lý tưởng: Rout ≈ 0

            self.values = {
                "R1": r1, "R2": r2,
                "Av": av, "Rin": rin, "Rout": rout,
            }

        elif topology == "non_inverting":
            # Non-Inverting: Av = 1 + R2/R1, Rin ≈ ∞
            calc = OpAmpCalculator.calc_non_inverting(
                self.config.gain, self.config.input_impedance, series
            )
            r1 = calc["R1"]
            r2 = calc["R2"]
            # Gain thực tế (không đảo pha)
            av = 1.0 + (r2 / r1)
            rin = float("inf")  # trở kháng vào rất cao (IN+)
            rout = 0.0

            self.values = {
                "R1": r1, "R2": r2,
                "Av": av, "Rin": rin, "Rout": rout,
            }

        elif topology == "differential":
            # Differential: Av = R2/R1 · (V+ - V-), balanced R1=R3, R2=R4
            calc = OpAmpCalculator.calc_differential(
                self.config.gain, self.config.input_impedance, series
            )
            r1 = calc["R1"]
            r2 = calc["R2"]
            r3 = calc["R3"]
            r4 = calc["R4"]
            # Gain thực tế
            av = r2 / r1
            rin = r1 + r3  # trở kháng vào (mỗi đầu ≈ R1 hoặc R3)
            rout = 0.0

            self.values = {
                "R1": r1, "R2": r2, "R3": r3, "R4": r4,
                "Av": av, "Rin": rin, "Rout": rout,
            }
        
        elif topology == "instrumentation":
            # Instrumentation: 3 op-amps, Av = 1 + 2*R1/RG
            calc = OpAmpCalculator.calc_instrumentation(
                self.config.gain,
                self.config.input_impedance,
                self.config.gain_resistor,
                series
            )
            
            self.values = {
                "R1": calc["R1"],
                "RG": calc["RG"],
                "R2": calc["R2"],
                "R3": calc["R3"],
                "R4": calc["R4"],
                "R5": calc["R5"],
                "Av": calc["Av"],
                "Rin": float("inf"),  # INA có Rin cực cao (IN+ U1/U2)
                "Rout": 0.0
            }

        else:
            raise ValueError(f"Unknown Op-Amp topology: {topology}")
    # Cho phép user override bất kỳ giá trị nào qua config.resistors / config.capacitors.
    # Inverting/Non-Inverting/Differential không cần biết override xảy ra thế nào, chỉ nhận final values.
    def _apply_overrides(self) -> None:
        self.values["R1"] = self.config.resistors.get("R1", self.values["R1"])
        self.values["R2"] = self.config.resistors.get("R2", self.values["R2"])

        # Differential / INA có thêm R3, R4
        if "R3" in self.values:
            self.values["R3"] = self.config.resistors.get("R3", self.values["R3"])
        if "R4" in self.values:
            self.values["R4"] = self.config.resistors.get("R4", self.values["R4"])
        # INA có thêm RG, R5
        if "RG" in self.values:
            self.values["RG"] = self.config.resistors.get("RG", self.values["RG"])
        if "R5" in self.values:
            self.values["R5"] = self.config.resistors.get("R5", self.values["R5"])

    """ Factory tạo tất cả Component cần thiết.
        - Inverting/Non-Inverting/Differential: U1, R1, R2, [R3, R4], GND
        - Instrumentation: U1, U2, U3, R1, R1b, RG, R2, R3, R4, R5, GND
        Sử dụng _create_resistor() factory helper để giảm boilerplate. """
    def _create_components(self) -> None:
        v = self.values

        # Op-Amp(s) — INA cần 3 op-amp, các topology khác cần 1
        if self.config.topology == "instrumentation":
            for i in [1, 2, 3]:
                uid = f"U{i}"
                meta = KiCadMetadata.get_metadata(self.config.opamp_model)
                self.components[uid] = Component(
                    id=uid,
                    type=ComponentType.OPAMP,
                    pins=("IN+", "IN-", "OUT", "V+", "V-"),
                    parameters={"model": ParameterValue(self.config.opamp_model)},
                    library_id=meta.library_id,
                    symbol_name=meta.symbol_name,
                    footprint=meta.footprint
                )
        else:
            opamp_meta = KiCadMetadata.get_metadata(self.config.opamp_model)
            self.components["U1"] = Component(
                id="U1",
                type=ComponentType.OPAMP,
                pins=("IN+", "IN-", "OUT", "V+", "V-"),
                parameters={"model": ParameterValue(self.config.opamp_model)},
                library_id=opamp_meta.library_id,
                symbol_name=opamp_meta.symbol_name,
                footprint=opamp_meta.footprint
            )

        # Resistors — luôn có R1, R2
        self.components["R1"] = self._create_resistor("R1", v["R1"])
        self.components["R2"] = self._create_resistor("R2", v["R2"])

        # Differential / INA có thêm R3, R4
        if "R3" in v:
            self.components["R3"] = self._create_resistor("R3", v["R3"])
        if "R4" in v:
            self.components["R4"] = self._create_resistor("R4", v["R4"])
        # INA có thêm RG, R1b (đối xứng R1a=R1b), R5
        if "RG" in v:
            self.components["RG"] = self._create_resistor("RG", v["RG"])
            self.components["R1b"] = self._create_resistor("R1b", v["R1"])
        if "R5" in v:
            self.components["R5"] = self._create_resistor("R5", v["R5"])

        # Ground — luôn có
        self.components["GND"] = Component(
            id="GND", type=ComponentType.GROUND, pins=("1",),
            parameters={}
        )

    # Tạo nets tùy thuộc vào topology thông qua dispatch
    def _create_nets(self) -> None:
        topology = self.config.topology
        if topology == "inverting":
            self._create_nets_inverting()
        elif topology == "non_inverting":
            self._create_nets_non_inverting()
        elif topology == "differential":
            self._create_nets_differential()
        elif topology == "instrumentation":
            self._create_nets_instrumentation()
        else:
            raise ValueError(f"Unknown Op-Amp topology: {topology}")

    """ Tạo nets cho Inverting: VIN → R1.1
                                VINV → R1.2, R2.1, U1.IN- (summing point / virtual ground)
                                VOUT → R2.2, U1.OUT (output = feedback point)
                                GND → GND.1, U1.IN+ (non-inverting input nối GND)
                                VCC → U1.V+ (nguồn dương)
                                VEE → U1.V- (nguồn âm)
        Input qua R1, output từ U1.OUT. IN+ nối GND (virtual ground). """
    def _create_nets_inverting(self) -> None:
        # VIN net: input → R1
        self.nets["VIN"] = Net("VIN", (PinRef("R1", "1"),))

        # VINV net: summing point (virtual ground tại IN-)
        self.nets["VINV"] = Net("VINV", (
            PinRef("R1", "2"),
            PinRef("R2", "1"),
            PinRef("U1", "IN-")
        ))

        # VOUT net: output + feedback
        self.nets["VOUT"] = Net("VOUT", (
            PinRef("R2", "2"),
            PinRef("U1", "OUT")
        ))

        # GND net: IN+ nối GND
        self.nets["GND"] = Net("GND", (
            PinRef("GND", "1"),
            PinRef("U1", "IN+")
        ))

        # Power nets
        self.nets["VCC"] = Net("VCC", (PinRef("U1", "V+"),))
        self.nets["VEE"] = Net("VEE", (PinRef("U1", "V-"),))

    """ Tạo nets cho Non-Inverting: VIN → U1.IN+ (tín hiệu vào trực tiếp IN+)
                                     VINV → R1.1, R2.1, U1.IN- (feedback network)
                                     VOUT → R2.2, U1.OUT (output = feedback point)
                                     GND → GND.1, R1.2 (R1 nối IN- xuống GND)
                                     VCC → U1.V+
                                     VEE → U1.V-
        Input trực tiếp vào IN+, R1 nối IN- xuống GND, R2 feedback từ output về IN-.
        Đặc trưng: trở kháng vào rất cao, không đảo pha. """
    def _create_nets_non_inverting(self) -> None:
        # VIN net: input trực tiếp vào IN+
        self.nets["VIN"] = Net("VIN", (PinRef("U1", "IN+"),))

        # VINV net: feedback network (R1 + R2 tại IN-)
        self.nets["VINV"] = Net("VINV", (
            PinRef("R1", "1"),
            PinRef("R2", "1"),
            PinRef("U1", "IN-")
        ))

        # VOUT net: output + feedback qua R2
        self.nets["VOUT"] = Net("VOUT", (
            PinRef("R2", "2"),
            PinRef("U1", "OUT")
        ))

        # GND net: R1 nối xuống GND
        self.nets["GND"] = Net("GND", (
            PinRef("GND", "1"),
            PinRef("R1", "2")
        ))

        # Power nets
        self.nets["VCC"] = Net("VCC", (PinRef("U1", "V+"),))
        self.nets["VEE"] = Net("VEE", (PinRef("U1", "V-"),))

    """ Tạo nets cho Differential: VIN_P → R3.1 (tín hiệu V+ qua R3)
                                    VIN_N → R1.1 (tín hiệu V- qua R1)
                                    VINV → R1.2, R2.1, U1.IN- (summing point)
                                    VNONINV → R3.2, R4.1, U1.IN+ (non-inverting divider)
                                    VOUT → R2.2, U1.OUT (output = feedback)
                                    GND → GND.1, R4.2 (R4 nối IN+ divider xuống GND)
                                    VCC → U1.V+
                                    VEE → U1.V-
        Balanced differential: R1=R3, R2=R4 cho CMRR cao.
        Output = (R2/R1) · (V+ - V-). """
    def _create_nets_differential(self) -> None:
        # VIN_N net: inverting input qua R1
        self.nets["VIN_N"] = Net("VIN_N", (PinRef("R1", "1"),))

        # VIN_P net: non-inverting input qua R3
        self.nets["VIN_P"] = Net("VIN_P", (PinRef("R3", "1"),))

        # VINV net: summing point tại IN-
        self.nets["VINV"] = Net("VINV", (
            PinRef("R1", "2"),
            PinRef("R2", "1"),
            PinRef("U1", "IN-")
        ))

        # VNONINV net: non-inverting divider tại IN+
        self.nets["VNONINV"] = Net("VNONINV", (
            PinRef("R3", "2"),
            PinRef("R4", "1"),
            PinRef("U1", "IN+")
        ))

        # VOUT net: output + feedback qua R2
        self.nets["VOUT"] = Net("VOUT", (
            PinRef("R2", "2"),
            PinRef("U1", "OUT")
        ))

        # GND net: R4 nối xuống GND
        self.nets["GND"] = Net("GND", (
            PinRef("GND", "1"),
            PinRef("R4", "2")
        ))

        # Power nets
        self.nets["VCC"] = Net("VCC", (PinRef("U1", "V+"),))
        self.nets["VEE"] = Net("VEE", (PinRef("U1", "V-"),))
        
    """ INA 3-op-amp nets:
    Stage 1 (U1, U2): buffer + gain qua RG
        VIN_P → U1.IN+        (input dương)
        VIN_N → U2.IN+        (input âm)
        OUT1: U1.OUT → R1.1 (feedback) + R2.1 (→ stage 2)
        OUT2: U2.OUT → R1b.1 (feedback) + R4.1 (→ stage 2)
        FB1: R1.2 + RG.1 + U1.IN-  (feedback junction top)
        FB2: R1b.2 + RG.2 + U2.IN- (feedback junction bottom)
        → RG nối giữa 2 inverting input, quyết định gain stage 1
    Stage 2 (U3): differential amplifier
        VINV: R2.2 + R3.1 + U3.IN-  (summing point)
        VNONINV: R4.2 + R5.1 + U3.IN+ (non-inverting divider)
        VOUT: R3.2 + U3.OUT  (output + feedback)
        GND: R5.2 + GND.1   (reference)
    """
    def _create_nets_instrumentation(self) -> None:
        # Input nets
        self.nets["VIN_P"] = Net("VIN_P", (PinRef("U1", "IN+"),))
        self.nets["VIN_N"] = Net("VIN_N", (PinRef("U2", "IN+"),))

        # Stage 1: OUT1 — U1 output + R1 feedback + R2 to stage 2
        self.nets["OUT1"] = Net("OUT1", (
            PinRef("U1", "OUT"),
            PinRef("R1", "1"),      # feedback resistor (output side)
            PinRef("R2", "1")       # → stage 2 via R2
        ))

        # Stage 1: OUT2 — U2 output + R1b feedback + R4 to stage 2
        self.nets["OUT2"] = Net("OUT2", (
            PinRef("U2", "OUT"),
            PinRef("R1b", "1"),     # feedback resistor (output side)
            PinRef("R4", "1")       # → stage 2 via R4
        ))

        # Stage 1: FB1 — feedback junction tại U1.IN- (R1 + RG)
        self.nets["FB1"] = Net("FB1", (
            PinRef("R1", "2"),      # feedback resistor (IN- side)
            PinRef("RG", "1"),      # gain resistor (top end)
            PinRef("U1", "IN-")
        ))

        # Stage 1: FB2 — feedback junction tại U2.IN- (R1b + RG)
        self.nets["FB2"] = Net("FB2", (
            PinRef("R1b", "2"),     # feedback resistor (IN- side)
            PinRef("RG", "2"),      # gain resistor (bottom end)
            PinRef("U2", "IN-")
        ))
        
        # Stage 2 nets (differential)
        self.nets["VINV"] = Net("VINV", (
            PinRef("R2", "2"),
            PinRef("R3", "1"),
            PinRef("U3", "IN-")
        ))
        
        self.nets["VNONINV"] = Net("VNONINV", (
            PinRef("R4", "2"),
            PinRef("R5", "1"),
            PinRef("U3", "IN+")
        ))
        
        self.nets["VOUT"] = Net("VOUT", (
            PinRef("R3", "2"),
            PinRef("U3", "OUT")
        ))
        
        # GND
        self.nets["GND"] = Net("GND", (
            PinRef("GND", "1"),
            PinRef("R5", "2")
        ))
        
        # Power
        self.nets["VCC"] = Net("VCC", tuple(PinRef(f"U{i}", "V+") for i in [1,2,3]))
        self.nets["VEE"] = Net("VEE", tuple(PinRef(f"U{i}", "V-") for i in [1,2,3]))


    # Tạo ports — topology quyết định số lượng input port
    def _create_ports(self) -> None:
        """ Tạo ports I/O boundary. Mỗi topology có input khác nhau:
            Inverting: VIN (single-ended)
            Non-Inverting: VIN (single-ended)
            Differential: VIN_P, VIN_N (differential pair)
        VCC, VEE, GND, VOUT dùng chung 100%. """
        topology = self.config.topology

        # Input ports — topology quyết định
        if topology == "differential" or topology == "instrumentation":
            # Differential pair inputs
            self.ports["VIN_P"] = Port("VIN_P", "VIN_P", PortDirection.INPUT)
            self.ports["VIN_N"] = Port("VIN_N", "VIN_N", PortDirection.INPUT)
        else: # inverting / non-inverting
            self.ports["VIN"] = Port("VIN", "VIN", PortDirection.INPUT)


        # VOUT — luôn có
        self.ports["VOUT"] = Port("VOUT", "VOUT", PortDirection.OUTPUT)

        # Power — luôn có
        self.ports["VCC"] = Port("VCC", "VCC", PortDirection.POWER)
        self.ports["VEE"] = Port("VEE", "VEE", PortDirection.POWER)

        # GND — luôn có
        self.ports["GND"] = Port("GND", "GND", PortDirection.GROUND)

    # Gắn constraints nghiệp vụ: gain, topology, input_impedance
    def _create_constraints(self) -> None:
        self.constraints["gain"] = Constraint("gain", self.config.gain)
        self.constraints["topology"] = Constraint("topology", self.config.topology)
        self.constraints["input_impedance"] = Constraint("input_impedance", self.config.input_impedance, "Ω")
        self.constraints["gain_actual"] = Constraint("gain_actual", self.values["Av"])
        self.constraints["opamp_model"] = Constraint("opamp_model", self.config.opamp_model)

    # Tạo assemble circuit từ components, nets, ports, constraints
    def _assemble_circuit(self) -> Circuit:
        topology_name = self._TOPOLOGY_NAMES.get(self.config.topology, self.config.topology)
        return Circuit(
            name=f"OpAmp_{topology_name}_Gain_{int(abs(self.config.gain))}",
            _components=self.components,
            _nets=self.nets,
            _ports=self.ports,
            _constraints=self.constraints
        )
