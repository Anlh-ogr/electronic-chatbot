""" MOSFET Amplifier Builder - CS, CD, CG topologies.
* khuếch đại S chung: tăng tín hiệu, đảo hình dạng tín hiệu (voltage amplifier)
* khuếch đại D chung: độ lợi ~ 1, trở kháng ra thấp, buffer (source follower)
* khuếch đại G chung: tần số cao, không đảo pha, trở kháng vào thấp
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
math: cần cho hằng số π và các hàm toán học cơ bản để tính toán giá trị linh kiện.
_dataclass: dùng để định nghĩa các cấu hình và lớp một cách rõ ràng và tiện lợi.
_field: để cung cấp giá trị mặc định cho các trường trong dataclass.
typing: để sử dụng các kiểu dữ liệu như Dict và Any cho việc gõ kiểu dữ liệu.
..entities: nhập các lớp domain như Circuit, Component, Net, Port, Constraint, PinRef, ComponentType, PortDirection, ParameterValue để xây dựng mạch.
.common: nhập các tiện ích chung như PreferredSeries, BuildOptions, ComponentCalculator, KiCadMetadata để hỗ trợ tính toán và metadata linh kiện.
"""



""" Cấu hình cho MOSFET amplifier (CS, CD, CG).
Cho phép tùy chỉnh các thông số nguồn, dòng, điện áp, hệ số khuếch đại, cũng như override linh kiện và build options cho từng mạch MOSFET cụ thể.
Args:
 * topology (Literal["CS", "CD", "CG"]): Kiểu topology mạch MOSFET (Common Source, Drain, Gate).
 * vdd (float): Điện áp nguồn cấp Drain (V).
 * id_target (float): Dòng Drain mục tiêu (A).
 * gain_target (float): Hệ số khuếch đại mục tiêu.
 * vgs_target (float): Điện áp Gate-Source mục tiêu (V).
 * vds_min (float): Điện áp Drain-Source tối thiểu để đảm bảo vùng bão hòa (V).
 * kn (float): Tham số transconductance (A/V²).
 * vth (float): Điện áp ngưỡng (V).
 * lambda_ (float): Tham số điều chế chiều dài kênh (1/V).
 * freq (float): Tần số hoạt động (Hz).
 * mosfet_model (str): Model MOSFET sử dụng (VD: "2N7000").
 * resistors (Dict[str, float]): Override giá trị điện trở (theo key: "RD", "RS", ...).
 * capacitors (Dict[str, float]): Override giá trị tụ điện (theo key: "CIN", "COUT", ...).
 * build (BuildOptions): Tùy chọn build chi tiết (tụ ghép, bypass, layout, ...).
"""
@dataclass
class MOSFETConfig:
    topology: Literal["CS", "CD", "CG"]
    vdd: float = 12.0           # nguồn cấp (default)
    id_target: float = 2e-3     # dòng drain mục tiêu (A)
    gain_target: float = 15.0   # hệ số khuếch đại mục tiêu
    vgs_target: float = 2.0     # điện áp gate-source mục tiêu (V)
    vds_min: float = 2.0        # điện áp drain-source tối thiểu (V)
    # thông số MOSFET
    kn: float = 0.5e-3          # tham số dẫn truyền (A/V²)
    vth: float = 1.0            # điện áp ngưỡng (V)
    lambda_: float = 0.02       # tham số điều chế chiều dài kênh (1/V)
    freq: float = 1000.0        # tần số hoạt động (Hz) - mặc định 1kHz
    channel_type: Literal["n", "p"] = "n"  # n-channel (default) hoặc p-channel
    mosfet_model: str = "2N7000"
    resistors: Dict[str, float] = field(default_factory=dict)
    capacitors: Dict[str, float] = field(default_factory=dict)
    # tùy chọn build
    build: BuildOptions = field(default_factory=BuildOptions)
    


""" Bộ tính toán chuyên dụng cho MOSFET (CS, CD, CG).
Cung cấp các hàm tính toán bias, điện trở drain/source/gate, tụ bypass, phục vụ cho việc thiết kế và tối ưu hóa mạch MOSFET.
Methods:
 * calc_transconductance(id_val, vgs, vth, kn) -> float:
   Tính transconductance của MOSFET: gm = 2√(kn·ID)
   Logic: gm quyết định độ lợi, tăng tỷ lệ với √ID.
   
 * calc_output_resistance(id_val, lambda_) -> float:
   Tính trở kháng ra của MOSFET: ro = 1/(λ·ID)
   Logic: ro ảnh hưởng độ lợi thực tế (Early effect).
   
 * calc_source_resistor(id_target, vgs, series) -> float:
   Tính điện trở source (RS) để đạt dòng ID: RS = VGS / ID
   Logic: VS = ID·RS, chọn RS để bias ổn định.
   
 * calc_drain_resistor(vdd, id_target, vds_min, vs, series) -> float:
   Tính điện trở drain (RD): RD = (VDD - VDS_min - VS) / ID
   Logic: đảm bảo VDS đủ lớn cho vùng bão hòa, headroom cho tín hiệu.
   
 * calc_gate_resistor_divider(vdd, vg_target, r_total, series) -> Dict[str, float]:
   Tính cầu phân áp gate (R1, R2): VG = VDD · R2/(R1+R2)
   Logic: thiết lập điện áp gate DC, trở kháng đầu vào cao.
   
 * calc_bypass_capacitor(rs, freq, factor, series) -> float:
   Tính tụ bypass source: CS >> 1/(2πf·RS)
   Logic: ngắn mạch AC để tăng độ lợi.
   
 * calc_coupling_capacitor(r, freq, factor, series) -> float:
   Tính tụ ghép nối: Xc << R tại tần số thấp.
   
 * calc_gate_ac_ground_capacitor(rg, freq, factor, series) -> float:
   Tính tụ nối gate xuống ground cho AC (dùng trong CG).
"""

class MOSFETCalculator:
    @staticmethod
    def calc_transconductance(id_val: float, vgs: float, vth: float, kn: float) -> ParameterValue:
        gm = 2.0 * math.sqrt(kn * abs(id_val))
        return ParameterValue(gm, "S")

    @staticmethod
    def calc_output_resistance(id_val: float, lambda_: float) -> ParameterValue:
        if lambda_ <= 0 or id_val == 0:
            return ParameterValue(float('inf'), "Ω")
        return ParameterValue(1.0 / (lambda_ * abs(id_val)), "Ω")

    @staticmethod
    def calc_source_resistor(id_target: float, vgs: float, series: PreferredSeries, channel_type: str) -> ParameterValue:
        # For p-channel, polarity is reversed
        if channel_type == "n":
            rs_ideal = vgs / id_target
        else:
            rs_ideal = -vgs / id_target
        return ParameterValue(ComponentCalculator.standardize(abs(rs_ideal), series), "Ω")

    @staticmethod
    def calc_drain_resistor(vdd: float, id_target: float, vds_min: float, vs: float, series: PreferredSeries, channel_type: str) -> ParameterValue:
        # For p-channel, vdd is negative, id is negative
        if channel_type == "n":
            rd_ideal = (vdd - vds_min - vs) / id_target
        else:
            rd_ideal = (vdd - (-vds_min) - vs) / id_target
        return ParameterValue(ComponentCalculator.standardize(abs(rd_ideal), series), "Ω")

    @staticmethod
    def calc_gate_resistor_divider(vdd: float, vg_target: float, r_total: float, series: PreferredSeries, channel_type: str) -> Dict[str, ParameterValue]:
        # For p-channel, vdd is negative, vg_target is negative
        if channel_type == "n":
            ratio = vg_target / vdd
        else:
            ratio = vg_target / vdd if vdd != 0 else 0
        r2_ideal = ratio * abs(r_total)
        r1_ideal = abs(r_total) - r2_ideal
        r2 = ParameterValue(ComponentCalculator.standardize(abs(r2_ideal), series), "Ω")
        r1 = ParameterValue(ComponentCalculator.standardize(abs(r1_ideal), series), "Ω")
        return {"R1": r1, "R2": r2}

    @staticmethod
    def calc_bypass_capacitor(rs: ParameterValue, freq: float, factor: float = 10.0, series: PreferredSeries = PreferredSeries.E12) -> ParameterValue:
        xc_target = rs.value / factor
        cs_ideal = 1.0 / (2.0 * math.pi * freq * xc_target)
        return ParameterValue(ComponentCalculator.standardize(cs_ideal, series), "F")

    @staticmethod
    def calc_coupling_capacitor(r: ParameterValue, freq: float, factor: float = 10.0, series: PreferredSeries = PreferredSeries.E12) -> ParameterValue:
        xc_target = r.value / factor
        c_ideal = 1.0 / (2.0 * math.pi * freq * xc_target)
        return ParameterValue(ComponentCalculator.standardize(c_ideal, series), "F")

    @staticmethod
    def calc_gate_ac_ground_capacitor(rg: ParameterValue, freq: float, factor: float = 10.0, series: PreferredSeries = PreferredSeries.E12) -> ParameterValue:
        xc_target = rg.value / factor
        c_ideal = 1.0 / (2.0 * math.pi * freq * xc_target)
        return ParameterValue(ComponentCalculator.standardize(c_ideal, series), "F")


""" Builder cho MOSFET amplifier topologies (CS, CD, CG).
Sử dụng pipeline pattern để tách biệt các bước xây dựng mạch, cho phép CS/CD/CG dùng chung logic tính toán, override, tạo component và chỉ khác nhau ở topology wiring (nets) và ports.
Attributes:
 - config (MOSFETConfig): Cấu hình MOSFET amplifier.
 - values (Dict[str, Any]): Giá trị trung gian sau compute + override (RD, RS, RG1, RG2, CIN, COUT, CS).
 - components (Dict[str, Component]): Danh sách linh kiện đã tạo.
 - nets (Dict[str, Net]): Danh sách net kết nối.
 - ports (Dict[str, Port]): Danh sách port I/O.
 - constraints (Dict[str, Constraint]): Danh sách ràng buộc nghiệp vụ.
"""
class MOSFETAmplifierBuilder:
    _TOPOLOGY_NAMES = {
        "CS": "Common_Source",
        "CD": "Common_Drain",
        "CG": "Common_Gate",
    }

    def __init__(self, config: MOSFETConfig):
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
    
    # tạo mạch theo pattern: compute → override → components → nets → ports → constraints → assemble
    def build(self) -> Circuit:
        self._compute_values()
        self._apply_overrides()
        self._create_components()
        self._create_nets()
        self._create_ports()
        self._create_constraints()
        return self._assemble_circuit()
    
    """ Tính toán giá trị điện trở và tụ điện từ MOSFETCalculator.
    - lưu kết quả vào self.values dưới dạng dict trung gian, chưa tạo Component.
    - CS/CD/CG đều dùng cùng mạch bias gate voltage divider (RG1, RG2).
    - RD chỉ CS/CG cần, CD thì drain nối thẳng VDD (không cần RD).
    - CS dùng bypass cho source, CG dùng bypass cho gate.
    """
    def _compute_values(self) -> None:
        series = self.config.build.resistor_series
        topology = self.config.topology
        
        id_val = self.config.id_target
        vgs = self.config.vgs_target
        vth = self.config.vth
        kn = self.config.kn
        vdd = self.config.vdd
        freq = self.config.freq
        lambda_ = self.config.lambda_
        
        # Transconductance: gm = 2√(kn·ID)
        gm = MOSFETCalculator.calc_transconductance(id_val, vgs, vth, kn)
        
        # Output resistance: ro = 1/(λ·ID)
        ro = MOSFETCalculator.calc_output_resistance(id_val, lambda_)
        
        # Source resistor: RS = VGS / ID
        rs = MOSFETCalculator.calc_source_resistor(id_val, vgs, series)
        
        # VS = ID · RS (điện áp tại source)
        vs = id_val * rs
        
        # VG = VS + VGS (điện áp gate cần thiết để bias)
        vg = vs + vgs
        
        # Drain resistor — CS và CG cần RD, CD thì drain nối thẳng VDD
        rd = None
        if topology in ("CS", "CG"):
            # RD = (VDD - VDS_min - VS) / ID
            rd = MOSFETCalculator.calc_drain_resistor(
                vdd, id_val, self.config.vds_min, vs, series
            )
        
        # VD = VDD - ID·RD (nếu có RD)
        vd = vdd - (id_val * rd) if rd else vdd
        
        # VDS = VD - VS (kiểm tra vùng bão hòa)
        vds = vd - vs
        if vds < self.config.vds_min:
            raise ValueError(
                f"[MOSFET] VDS thực tế ({vds:.2f}V) nhỏ hơn VDS_min yêu cầu ({self.config.vds_min}V). "
                f"Hãy điều chỉnh lại thông số bias, RD, RS, hoặc VDD để đảm bảo VDS đủ headroom cho vùng bão hòa."
            )
        
        # Gate voltage divider: VG = VDD · RG2/(RG1+RG2)
        gate_div = MOSFETCalculator.calc_gate_resistor_divider(
            vdd, vg, 1e6, series
        )
        rg1 = gate_div["R1"]
        rg2 = gate_div["R2"]
        
        # Bypass capacitor — CS bypass source, CG bypass gate
        cs_cap = None
        if topology == "CS" and self.config.build.include_bypass_caps:
            # CS bypass cho source: CS >> 1/(2πf·RS)
            cs_cap = MOSFETCalculator.calc_bypass_capacitor(
                rs, freq, 10.0, self.config.build.capacitor_series
            )
        elif topology == "CG" and self.config.build.include_bypass_caps:
            # CG bypass cho gate (AC ground): CG >> 1/(2πf·RG)
            rg_parallel = rg1 * rg2 / (rg1 + rg2)  # RG1 || RG2
            cs_cap = MOSFETCalculator.calc_gate_ac_ground_capacitor(
                rg_parallel, freq, 10.0, self.config.build.capacitor_series
            )
        
        # Coupling capacitors — tính theo trở kháng
        cin = None
        cout = None
        
        if self.config.build.include_input_coupling:
            # Input coupling: tính theo trở kháng đầu vào
            rin_bias = rg1 * rg2 / (rg1 + rg2)  # RG1 || RG2
            cin = MOSFETCalculator.calc_coupling_capacitor(
                rin_bias, freq, 10.0, self.config.build.capacitor_series
            )
        
        if self.config.build.include_output_coupling:
            # Output coupling: tính theo RD (hoặc RS cho CD)
            r_out = rs if topology == "CD" else (rd if rd else 1e3)
            cout = MOSFETCalculator.calc_coupling_capacitor(
                r_out, freq, 10.0, self.config.build.capacitor_series
            )
        
        # AC analysis parameters — tính độ lợi và trở kháng theo topology
        rin_bias = rg1 * rg2 / (rg1 + rg2)  # RG1 || RG2 (trở kháng đầu vào DC bias)
        
        if topology == "CS":
            # Common Source: voltage amplifier, đảo pha
            # Av ≈ -gm·(RD || ro) — độ lợi phụ thuộc RD và gm
            # Rin cao (gate), Rout ≈ RD
            rd_eff = (rd * ro) / (rd + ro) if ro != float('inf') else rd
            av = -gm * rd_eff
            rin = rin_bias
            rout = rd
            gain_class = "voltage"
            
        elif topology == "CD":
            # Common Drain (Source Follower): buffer, không đảo pha
            # Av ≈ gm·RS/(1 + gm·RS) ≈ 1 — độ lợi gần bằng 1
            # Rin cao (gate), Rout thấp ≈ 1/gm
            av = (gm * rs) / (1.0 + gm * rs)
            rin = rin_bias
            rout = 1.0 / gm  # Approximation: 1/gm || RS ≈ 1/gm
            gain_class = "near_unity"
            
        elif topology == "CG":
            # Common Gate: cascode amplifier, không đảo pha
            # Av ≈ gm·(RD || ro) — độ lợi cao, băng thông rộng
            # Rin thấp ≈ 1/gm, Rout ≈ RD
            rd_eff = (rd * ro) / (rd + ro) if ro != float('inf') else rd
            av = gm * rd_eff
            rin = 1.0 / (gm + 1.0 / rs)  # Chính xác hơn: 1/(gm + 1/RS)
            rout = rd
            gain_class = "voltage"
        else:
            av = 0.0
            rin = 1e6
            rout = 1e3
            gain_class = "unknown"
        
        # Store all values
        self.values = {
            "ID": id_val,
            "VGS": vgs,
            "VG": vg,
            "VS": vs,
            "VD": vd,
            "VDS": vds,
            "gm": gm,
            "ro": ro,
            "RD": rd,
            "RS": rs,
            "RG1": rg1,
            "RG2": rg2,
            "CS": cs_cap,
            "CIN": cin,
            "COUT": cout,
            "Av": av,
            "Rin": rin,
            "Rout": rout,
            "gain_class": gain_class
        }

    # Cho phép user override bất kỳ giá trị nào qua config.resistors / config.capacitors.
    # CS/CD/CG không cần biết override xảy ra thế nào, chỉ nhận final values.
    def _apply_overrides(self) -> None:
        self.values["RG1"] = self.config.resistors.get("RG1", self.values["RG1"])
        self.values["RG2"] = self.config.resistors.get("RG2", self.values["RG2"])
        self.values["RS"] = self.config.resistors.get("RS", self.values["RS"])

        if self.values["RD"] is not None:
            self.values["RD"] = self.config.resistors.get("RD", self.values["RD"])

        if self.values["CIN"] is not None:
            self.values["CIN"] = self.config.capacitors.get("CIN", self.values["CIN"])
        if self.values["COUT"] is not None:
            self.values["COUT"] = self.config.capacitors.get("COUT", self.values["COUT"])
        if self.values["CS"] is not None:
            self.values["CS"] = self.config.capacitors.get("CS", self.values["CS"])
    
    """ Factory tạo tất cả Component cần thiết (M1, RD, RS, RG1, RG2, CIN, COUT, CS, GND).
        CS/CD/CG dùng chung 100% — chỉ khác ở cách nối (nets), không khác component.
        Sử dụng _create_resistor() / _create_capacitor() factory helpers để giảm boilerplate. """
    def _create_components(self) -> None:
        v = self.values

        # MOSFET M1 — component đặc biệt, không dùng factory
        m_meta = KiCadMetadata.get_metadata(self.config.mosfet_model)
        
        # Xác định vùng hoạt động (cutoff, saturation, triode)
        vds = v["VDS"]
        vgs = v["VGS"]
        vth = self.config.vth
        
        if vgs < vth:
            region = "cutoff"
        elif vds >= (vgs - vth):
            region = "saturation"
        else:
            region = "triode"
        
        self.components["M1"] = Component(
            id="M1",
            type=ComponentType.MOSFET,
            pins=("D", "G", "S"),
            parameters={
                "model": ParameterValue(self.config.mosfet_model),
                "type": ParameterValue("n-channel"),
                "kn": ParameterValue(self.config.kn, "A/V²"),
                "vth": ParameterValue(self.config.vth, "V"),
                "lambda": ParameterValue(self.config.lambda_, "1/V"),
                "ro": ParameterValue(v["ro"], "Ω"),
                "region": ParameterValue(region),
                "channel": ParameterValue("n-channel")
            },
            library_id=m_meta.library_id,
            symbol_name=m_meta.symbol_name,
            footprint=m_meta.footprint
        )

        # Bias resistors (RG1, RG2) — luôn có
        self.components["RG1"] = self._create_resistor("RG1", v["RG1"])
        self.components["RG2"] = self._create_resistor("RG2", v["RG2"])

        # RD — chỉ tạo nếu topology cần (CS, CG)
        if v["RD"] is not None:
            self.components["RD"] = self._create_resistor("RD", v["RD"])

        # RS — luôn có
        self.components["RS"] = self._create_resistor("RS", v["RS"])

        # Coupling capacitors (CIN, COUT) — tùy build option
        if v["CIN"]:
            self.components["CIN"] = self._create_capacitor("CIN", v["CIN"])
        if v["COUT"]:
            self.components["COUT"] = self._create_capacitor("COUT", v["COUT"])

        # Bypass capacitor (CS) — tùy build option (polarized cho electrolytic)
        if v["CS"]:
            self.components["CS"] = self._create_capacitor("CS", v["CS"], polarized=True)

        # Ground — luôn có
        self.components["GND"] = Component(
            id="GND", type=ComponentType.GROUND, pins=("1",),
            parameters={}
        )
    
    # Tạo nets tùy thuộc vào topology CS/CD/CG thông qua dispatch
    def _compute_values(self) -> None:
        series = self.config.build.resistor_series
        topology = self.config.topology
        channel_type = self.config.channel_type
        id_val = self.config.id_target
        vgs = self.config.vgs_target
        vth = self.config.vth
        kn = self.config.kn
        vdd = self.config.vdd
        freq = self.config.freq
        lambda_ = self.config.lambda_
        # Transconductance: gm = 2√(kn·ID)
        gm = MOSFETCalculator.calc_transconductance(id_val, vgs, vth, kn)
        # Output resistance: ro = 1/(λ·ID)
        ro = MOSFETCalculator.calc_output_resistance(id_val, lambda_)
        # Source resistor: RS = VGS / ID (with channel type)
        rs = MOSFETCalculator.calc_source_resistor(id_val, vgs, series, channel_type)
        # VS = ID · RS (điện áp tại source)
        vs = id_val * rs.value
        # VG = VS + VGS (n-channel: VG = VS + VGS, p-channel: VG = VS + VGS, but sign)
        if channel_type == "n":
            vg = vs + vgs
        else:
            vg = vs - abs(vgs)
        # Bias gate error check (todo 1)
        # For n-channel: VG must be between 0 and VDD; for p-channel: VG negative, between VDD and 0
        if channel_type == "n":
            if vg < 0 or vg > vdd:
                raise ValueError(f"[MOSFET] Invalid gate bias: VG={vg:.2f}V out of range [0, VDD={vdd}V]. Check VGS, VS, VDD.")
        else:
            if vg > 0 or vg < vdd:
                raise ValueError(f"[MOSFET] Invalid p-channel gate bias: VG={vg:.2f}V out of range [VDD={vdd}V, 0]. Check VGS, VS, VDD.")
        # Gate resistor divider
        gate_div = MOSFETCalculator.calc_gate_resistor_divider(vdd, vg, 1e6, series, channel_type)
        # Drain resistor (only for CS/CG)
        rd = None
        if topology in ("CS", "CG"):
            rd = MOSFETCalculator.calc_drain_resistor(vdd, id_val, self.config.vds_min, vs, series, channel_type)
        # Bypass/source/gate capacitors
        cs = MOSFETCalculator.calc_bypass_capacitor(rs, freq)
        # Coupling capacitors (input/output)
        cin = MOSFETCalculator.calc_coupling_capacitor(rs, freq)
        cout = MOSFETCalculator.calc_coupling_capacitor(rd if rd else rs, freq)
        # Store all values as ParameterValue
        self.values = {
            "GM": gm,
            "RO": ro,
            "RS": rs,
            "VS": ParameterValue(vs, "V"),
            "VG": ParameterValue(vg, "V"),
            "RD": rd,
            "RG1": gate_div["R1"],
            "RG2": gate_div["R2"],
            "CS": cs,
            "CIN": cin,
            "COUT": cout,
        }
        # ...existing code...
        # VGATE net: RG1 dưới + RG2 trên + input coupling
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")
        has_cs = self._has("CS")
        vgate_pins = [PinRef("RG1", "2"), PinRef("RG2", "1")]
        if has_cin:
            vgate_pins.append(PinRef("CIN", "2"))
        else:
            vgate_pins.append(PinRef("M1", "G"))
        self.nets["VGATE"] = Net("VGATE", tuple(vgate_pins))

        # VIN net (nếu có CIN)
        if has_cin:
            self.nets["VIN"] = Net("VIN", (
                PinRef("CIN", "1"),
                PinRef("M1", "G")
            ))

        # VDRAIN net: RD dưới + M1.D + output coupling
        vdrain_pins = [PinRef("RD", "2"), PinRef("M1", "D")]
        if has_cout:
            vdrain_pins.append(PinRef("COUT", "1"))
        self.nets["VDRAIN"] = Net("VDRAIN", tuple(vdrain_pins))

        # VOUT net (nếu có COUT)
        if has_cout:
            self.nets["VOUT"] = Net("VOUT", (PinRef("COUT", "2"),))

        # VSOURCE net: M1.S + RS trên + bypass CS
        vsource_pins = [PinRef("M1", "S"), PinRef("RS", "1")]
        if has_cs:
            vsource_pins.append(PinRef("CS", "1"))
        self.nets["VSOURCE"] = Net("VSOURCE", tuple(vsource_pins))

        # GND net
        gnd_pins = [PinRef("GND", "1"), PinRef("RG2", "2"), PinRef("RS", "2")]
        if has_cs:
            gnd_pins.append(PinRef("CS", "2"))
        self.nets["GND"] = Net("GND", tuple(gnd_pins))
    
    """ Tạo nets cho Common Drain (Source Follower): VDD → RG1.1, M1.D (drain nối thẳng VDD, không qua RD)
                                                              VGATE → RG1.2, RG2.1, [CIN.2 hoặc M1.G]
                                                              VSOURCE → M1.S, RS.1, [COUT.1] (output lấy từ source)
                                                              GND → GND.1, RG2.2, RS.2
        Đặc trưng CD: Gain ≈ 1 (voltage follower), trở kháng ra thấp, không có RD. """
    def _create_nets_cd(self) -> None:
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")
        # VDD net: RG1 trên + M1 drain nối trực tiếp VDD
        self.nets["VDD"] = Net("VDD", (
            PinRef("RG1", "1"),
            PinRef("M1", "D")
        ))

        # VGATE net: giống CS
        vgate_pins = [PinRef("RG1", "2"), PinRef("RG2", "1")]
        if has_cin:
            vgate_pins.append(PinRef("CIN", "2"))
        else:
            vgate_pins.append(PinRef("M1", "G"))
        self.nets["VGATE"] = Net("VGATE", tuple(vgate_pins))

        # VIN net (nếu có CIN)
        if has_cin:
            self.nets["VIN"] = Net("VIN", (
                PinRef("CIN", "1"),
                PinRef("M1", "G")
            ))

        # VSOURCE net: M1.S + RS trên + output coupling (output lấy từ source)
        vsource_pins = [PinRef("M1", "S"), PinRef("RS", "1")]
        if has_cout:
            vsource_pins.append(PinRef("COUT", "1"))
        self.nets["VSOURCE"] = Net("VSOURCE", tuple(vsource_pins))

        # VOUT net (nếu có COUT)
        if has_cout:
            self.nets["VOUT"] = Net("VOUT", (PinRef("COUT", "2"),))

        # GND net
        gnd_pins = [PinRef("GND", "1"), PinRef("RG2", "2"), PinRef("RS", "2")]
        self.nets["GND"] = Net("GND", tuple(gnd_pins))
    
    """ Tạo nets cho Common Gate: VDD → RG1.1, RD.1
                                  VGATE → RG1.2, RG2.1, M1.G (gate DC bias, AC grounded qua CS)
                                  VSOURCE → M1.S, RS.1, [CIN.1 hoặc input trực tiếp] (input qua source)
                                  VDRAIN → RD.2, M1.D, [COUT.1] (output từ drain)
                                  GND → GND.1, RG2.2, RS.2, [CS.2 gate bypass]
        Đặc trưng CG: Gate AC ground, input qua source, output từ drain.
        Trở kháng vào thấp, băng thông rộng hơn CS. """
    def _create_nets_cg(self) -> None:
        has_cin = self._has("CIN")
        has_cout = self._has("COUT")
        has_cs = self._has("CS")

        # VDD net: RG1 trên + RD trên
        self.nets["VDD"] = Net("VDD", (
            PinRef("RG1", "1"),
            PinRef("RD", "1")
        ))

        # VGATE net: RG1 dưới + RG2 trên + M1.G + CS (gate DC bias, AC ground qua CS)
        vgate_pins = [
            PinRef("RG1", "2"),
            PinRef("RG2", "1"),
            PinRef("M1", "G")
        ]
        if has_cs:
            vgate_pins.append(PinRef("CS", "1"))
        self.nets["VGATE"] = Net("VGATE", tuple(vgate_pins))

        # VSOURCE net: M1.S + RS trên + input coupling (input đi vào source)
        vsource_pins = [PinRef("M1", "S"), PinRef("RS", "1")]
        if has_cin:
            vsource_pins.append(PinRef("CIN", "2"))
        self.nets["VSOURCE"] = Net("VSOURCE", tuple(vsource_pins))

        # VIN net (nếu có CIN, input qua source)
        if has_cin:
            self.nets["VIN"] = Net("VIN", (PinRef("CIN", "1"),))

        # VDRAIN net: RD dưới + M1.D + output coupling
        vdrain_pins = [PinRef("RD", "2"), PinRef("M1", "D")]
        if has_cout:
            vdrain_pins.append(PinRef("COUT", "1"))
        self.nets["VDRAIN"] = Net("VDRAIN", tuple(vdrain_pins))

        # VOUT net (nếu có COUT)
        if has_cout:
            self.nets["VOUT"] = Net("VOUT", (PinRef("COUT", "2"),))

        # GND net
        gnd_pins = [PinRef("GND", "1"), PinRef("RG2", "2"), PinRef("RS", "2")]
        if has_cs:
            gnd_pins.append(PinRef("CS", "2"))
        self.nets["GND"] = Net("GND", tuple(gnd_pins))
    
    # Tạo ports — topology tương tự, chuẩn hóa interface
    def _create_ports(self) -> None:
        topology = self.config.topology
        
        if topology == "CS":
            # CS: input qua gate, output từ drain
            self.ports["VIN"] = Port("VIN", "VIN", PortDirection.INPUT)
            self.ports["VOUT"] = Port("VOUT", "VOUT", PortDirection.OUTPUT)
        elif topology == "CD":
            # CD: input qua gate, output từ source
            self.ports["VIN"] = Port("VIN", "VIN", PortDirection.INPUT)
            self.ports["VOUT"] = Port("VOUT", "VOUT", PortDirection.OUTPUT)
        elif topology == "CG":
            # CG: input qua source, output từ drain
            self.ports["VIN"] = Port("VIN", "VIN", PortDirection.INPUT)
            self.ports["VOUT"] = Port("VOUT", "VOUT", PortDirection.OUTPUT)
        
        self.ports["VDD"] = Port("VDD", "VDD", PortDirection.POWER)
        self.ports["GND"] = Port("GND", "GND", PortDirection.GROUND)
    
    # Gắn constraints nghiệp vụ: gain, ID, VDD, topology, bypass, coupling
    def _create_constraints(self) -> None:
        topo = self.config.topology
        topo_name = self._TOPOLOGY_NAMES.get(topo, topo)
        
        self.constraints["topology"] = Constraint("topology", topo_name)
        self.constraints["vdd"] = Constraint("vdd", self.config.vdd)
        self.constraints["id_target"] = Constraint("id_target", self.config.id_target)
        self.constraints["gain_estimate"] = Constraint("gain_estimate", self.values["Av"])
        self.constraints["input_impedance"] = Constraint("input_impedance", self.values["Rin"])
        self.constraints["output_impedance"] = Constraint("output_impedance", self.values["Rout"])
    
    # Tạo assemble circuit từ components, nets, ports, constraints
    def _assemble_circuit(self) -> Circuit:
        topo = self.config.topology
        topo_name = self._TOPOLOGY_NAMES.get(topo, topo)
        gain_val = int(abs(self.values["Av"]))
        
        name = f"MOSFET_{topo_name}_Gain_{gain_val}"
        
        return Circuit(
            name=name,
            _components=self.components,
            _nets=self.nets,
            _ports=self.ports,
            _constraints=self.constraints
        )
