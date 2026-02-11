# .\thesis\electronic-chatbot\apps\api\app\domains\circuits\builder\factory.py
""" AmplifierFactory - API tạo nhanh các mạch khuếch đại (amplifier).

Cung cấp các phương thức factory để sinh nhanh các topology mạch khuếch đại phổ biến:
    - BJT: CE (Common Emitter), CC (Common Collector), CB (Common Base)
    - MOSFET: CS (Common Source), CD (Common Drain), CG (Common Gate)
    - Op-Amp: Inverting, Non-Inverting, Differential, Instrumentation
    - Power Amps: Class A, AB, B, C, D (dùng ParametricEngine)
    - Đặc biệt: Darlington, Multi-Stage Cascade

Thiết kế theo Domain-Driven Design (DDD), chỉ chứa logic nghiệp vụ tạo mạch, không phụ thuộc tầng ngoài.
"""


from typing import Dict, Any, Optional

from app.domains.circuits.entities import Circuit

from .common import PowerAmpConfig, SpecialAmpConfig
from .bjt import BJTConfig, BJTAmplifierBuilder
from .mosfet import MOSFETConfig, MOSFETAmplifierBuilder
from .opamp import OpAmpConfig, OpAmpAmplifierBuilder
from .specialtopo import DarlingtonAmplifierBuilder, MultiStageAmplifierBuilder
from .parametric import ParametricEngine

"""Lý do sử dụng thư viện:
typing: Định nghĩa type hint cho Dict, Any, Optional giúp code rõ ràng, dễ kiểm tra.
app.domains.circuits.entities: Sử dụng lớp Circuit làm kết quả đầu ra cho các factory method.
.common, .bjt, .mosfet, .opamp, .specialtopo: Import các config/builder chuyên biệt cho từng loại mạch.
.parametric: Dùng ParametricEngine để sinh mạch từ template JSON nếu có.
"""

class AmplifierFactory:
    """Factory tạo nhanh các amplifier circuits.
    
    Priority: ParametricEngine (JSON templates) → Python builders (BJT CE, OpAmp Inv)
    """
    
    # Topology key → JSON template topology_type
    _TEMPLATE_MAP: Dict[str, str] = {
        # BJT
        "bjt_ce": "bjt_common_emitter_voltage_amplifier",
        "bjt_cc": "bjt_common_collector_voltage_divider_bias_buffer",
        "bjt_cb": "bjt_common_base_vdiv_bypass_amplifier",
        # MOSFET
        "mosfet_cs": "mosfet_common_source_vdiv_bypass_amplifier",
        "mosfet_cd": "mosfet_common_drain_vdiv_buffer",
        "mosfet_cg": "mosfet_common_gate_vdiv_amplifier",
        # OpAmp
        "opamp_inverting": "opamp_inverting_dual_supply_core",
        "opamp_non_inverting": "opamp_non_inverting_dual_supply_core",
        "opamp_differential": "opamp_differential_dual_supply_4r",
        "opamp_instrumentation": "opamp_instrumentation_3opamp_basic",
        # Operation Classes
        "class_a": "class_a_power_amp_voltage_divider_bias_full",
        "class_ab": "class_ab_push_pull_amp_diode_bias_full",
        "class_b": "class_b_push_pull_amp_no_bias_full_ac_coupled",
        "class_c": "class_c_tuned_amp_voltage_divider_bias_full",
        "class_d": "class_d_mosfet_pwm_comparator_lc_filter_full",
        # Special
        "darlington": "darlington_pair_voltage_divider_bias_full",
        "multi_stage": "two_stage_ce_cc_full_coupling",
    }
    
    @classmethod
    def _try_parametric(cls, topology_key: str, overrides: Optional[Dict[str, Dict[str, Any]]] = None) -> Optional[Circuit]:
        """Thử tạo circuit qua ParametricEngine. Trả về None nếu không có template."""
        tid = cls._TEMPLATE_MAP.get(topology_key)
        if tid is None:
            return None
        try:
            engine = ParametricEngine()
            return engine.build(tid, overrides)
        except (ValueError, FileNotFoundError):
            return None
    
    # ----------------------------------------------------------------
    # Convenience methods (topology dispatch)
    # ----------------------------------------------------------------
    
    @classmethod
    def create_bjt(cls, topology: str = "CE", gain: float = 10.0, vcc: float = 12.0, **kwargs) -> Circuit:
        """Tạo BJT amplifier theo topology name.
        
        Args:
            topology: "CE", "CC", hoặc "CB"
            gain: Hệ số khuếch đại mục tiêu
            vcc: Điện áp nguồn (V)
        """
        topo = topology.upper()
        if topo == "CE":
            return cls.create_bjt_ce(gain=gain, vcc=vcc, **kwargs)
        elif topo == "CC":
            return cls.create_bjt_cc(vcc=vcc, **kwargs)
        elif topo == "CB":
            return cls.create_bjt_cb(gain=gain, vcc=vcc, **kwargs)
        else:
            raise ValueError(f"Unknown BJT topology: {topology}. Supported: CE, CC, CB")
    
    @classmethod
    def create_opamp(cls, topology: str = "inverting", gain: float = -10.0, **kwargs) -> Circuit:
        """Tạo Op-Amp amplifier theo topology name.
        
        Args:
            topology: "inverting", "non_inverting", "differential", "instrumentation"
            gain: Hệ số khuếch đại mục tiêu
        """
        topo = topology.lower()
        if topo == "inverting":
            return cls.create_opamp_inverting(gain=gain, **kwargs)
        elif topo == "non_inverting":
            return cls.create_opamp_non_inverting(gain=gain, **kwargs)
        elif topo == "differential":
            return cls.create_opamp_differential(gain=gain, **kwargs)
        elif topo == "instrumentation":
            return cls.create_opamp_instrumentation(gain=gain, **kwargs)
        else:
            raise ValueError(
                f"Unknown Op-Amp topology: {topology}. "
                f"Supported: inverting, non_inverting, differential, instrumentation"
            )
    
    @classmethod
    def create_mosfet(cls, topology: str = "CS", gain: float = 15.0, vdd: float = 12.0, **kwargs) -> Circuit:
        """Tạo MOSFET amplifier theo topology name.
        
        Args:
            topology: "CS", "CD", hoặc "CG"
            gain: Hệ số khuếch đại mục tiêu
            vdd: Điện áp nguồn (V)
        """
        topo = topology.upper()
        if topo == "CS":
            return cls.create_mosfet_cs(gain=gain, vdd=vdd, **kwargs)
        elif topo == "CD":
            return cls.create_mosfet_cd(vdd=vdd, **kwargs)
        elif topo == "CG":
            return cls.create_mosfet_cg(gain=gain, vdd=vdd, **kwargs)
        else:
            raise ValueError(f"Unknown MOSFET topology: {topology}. Supported: CS, CD, CG")
    
    # ----------------------------------------------------------------
    # BJT Topologies
    # ----------------------------------------------------------------
    
    @staticmethod
    def create_bjt_ce(gain: float = 10.0, vcc: float = 12.0, **kwargs) -> Circuit:
        """Tạo BJT Common Emitter amplifier"""
        config = BJTConfig(topology="CE", gain_target=gain, vcc=vcc, **kwargs)
        return BJTAmplifierBuilder(config).build()
    
    @classmethod
    def create_bjt_cc(cls, vcc: float = 12.0, **kwargs) -> Circuit:
        """Tạo BJT Common Collector (Emitter Follower)"""
        result = cls._try_parametric("bjt_cc", {"VCC": {"voltage": vcc}} if vcc != 12.0 else None)
        if result:
            return result
        config = BJTConfig(topology="CC", vcc=vcc, **kwargs)
        return BJTAmplifierBuilder(config).build()
    
    @classmethod
    def create_bjt_cb(cls, gain: float = 15.0, vcc: float = 12.0, **kwargs) -> Circuit:
        """Tạo BJT Common Base amplifier"""
        result = cls._try_parametric("bjt_cb")
        if result:
            return result
        config = BJTConfig(topology="CB", gain_target=gain, vcc=vcc, **kwargs)
        return BJTAmplifierBuilder(config).build()
    
    # ----------------------------------------------------------------
    # MOSFET Topologies
    # ----------------------------------------------------------------
    
    @classmethod
    def create_mosfet_cs(cls, gain: float = 15.0, vdd: float = 12.0, **kwargs) -> Circuit:
        """Tạo MOSFET Common Source amplifier"""
        result = cls._try_parametric("mosfet_cs")
        if result:
            return result
        config = MOSFETConfig(topology="CS", gain_target=gain, vdd=vdd, **kwargs)
        return MOSFETAmplifierBuilder(config).build()
    
    @classmethod
    def create_mosfet_cd(cls, vdd: float = 12.0, **kwargs) -> Circuit:
        """Tạo MOSFET Common Drain (Source Follower)"""
        result = cls._try_parametric("mosfet_cd")
        if result:
            return result
        config = MOSFETConfig(topology="CD", vdd=vdd, **kwargs)
        return MOSFETAmplifierBuilder(config).build()
    
    @classmethod
    def create_mosfet_cg(cls, gain: float = 10.0, vdd: float = 12.0, **kwargs) -> Circuit:
        """Tạo MOSFET Common Gate amplifier"""
        result = cls._try_parametric("mosfet_cg")
        if result:
            return result
        config = MOSFETConfig(topology="CG", gain_target=gain, vdd=vdd, **kwargs)
        return MOSFETAmplifierBuilder(config).build()
    
    # ----------------------------------------------------------------
    # Op-Amp Configurations
    # ----------------------------------------------------------------
    
    @staticmethod
    def create_opamp_inverting(gain: float = -10.0, **kwargs) -> Circuit:
        """Tạo Op-Amp Inverting amplifier"""
        config = OpAmpConfig(topology="inverting", gain=abs(gain), **kwargs)
        return OpAmpAmplifierBuilder(config).build()
    
    @classmethod
    def create_opamp_non_inverting(cls, gain: float = 10.0, **kwargs) -> Circuit:
        """Tạo Op-Amp Non-Inverting amplifier"""
        result = cls._try_parametric("opamp_non_inverting")
        if result:
            return result
        config = OpAmpConfig(topology="non_inverting", gain=gain, **kwargs)
        return OpAmpAmplifierBuilder(config).build()
    
    @classmethod
    def create_opamp_differential(cls, gain: float = 10.0, **kwargs) -> Circuit:
        """Tạo Op-Amp Differential amplifier"""
        result = cls._try_parametric("opamp_differential")
        if result:
            return result
        config = OpAmpConfig(topology="differential", gain=gain, **kwargs)
        return OpAmpAmplifierBuilder(config).build()
    
    @classmethod
    def create_opamp_instrumentation(cls, gain: float = 100.0, **kwargs) -> Circuit:
        """Tạo Op-Amp Instrumentation amplifier"""
        result = cls._try_parametric("opamp_instrumentation")
        if result:
            return result
        config = OpAmpConfig(topology="instrumentation", gain=gain, **kwargs)
        return OpAmpAmplifierBuilder(config).build()
    
    # ----------------------------------------------------------------
    # Operation Classes (Power Amps)
    # ----------------------------------------------------------------
    
    @classmethod
    def create_class_a_power(cls, power_output: float = 1.0, load_impedance: float = 8.0, **kwargs) -> Circuit:
        """Tạo Class A Power amplifier"""
        result = cls._try_parametric("class_a")
        if result:
            return result
        config = PowerAmpConfig(amp_class="A", power_output=power_output, load_impedance=load_impedance, **kwargs)
        raise NotImplementedError("Class A Power amplifier builder - coming soon")
    
    @classmethod
    def create_class_ab_push_pull(cls, power_output: float = 10.0, load_impedance: float = 8.0, **kwargs) -> Circuit:
        """Tạo Class AB Push-Pull amplifier"""
        result = cls._try_parametric("class_ab")
        if result:
            return result
        config = PowerAmpConfig(amp_class="AB", power_output=power_output, load_impedance=load_impedance, **kwargs)
        raise NotImplementedError("Class AB Push-Pull amplifier builder - coming soon")
    
    @classmethod
    def create_class_b_push_pull(cls, power_output: float = 10.0, load_impedance: float = 8.0, **kwargs) -> Circuit:
        """Tạo Class B Push-Pull amplifier"""
        result = cls._try_parametric("class_b")
        if result:
            return result
        config = PowerAmpConfig(amp_class="B", power_output=power_output, load_impedance=load_impedance, **kwargs)
        raise NotImplementedError("Class B Push-Pull amplifier builder - coming soon")
    
    @classmethod
    def create_class_c_tuned(cls, power_output: float = 5.0, frequency: float = 1e6, load_impedance: float = 50.0, **kwargs) -> Circuit:
        """Tạo Class C Tuned amplifier"""
        result = cls._try_parametric("class_c")
        if result:
            return result
        config = PowerAmpConfig(amp_class="C", power_output=power_output, load_impedance=load_impedance, **kwargs)
        raise NotImplementedError("Class C Tuned amplifier builder - coming soon")
    
    @classmethod
    def create_class_d_switching(cls, power_output: float = 50.0, frequency: float = 400e3, **kwargs) -> Circuit:
        """Tạo Class D Switching amplifier"""
        result = cls._try_parametric("class_d")
        if result:
            return result
        config = PowerAmpConfig(amp_class="D", power_output=power_output, **kwargs)
        raise NotImplementedError("Class D Switching amplifier builder - coming soon")
    
    # ----------------------------------------------------------------
    # Special Amplifiers
    # ----------------------------------------------------------------
    
    @classmethod
    def create_darlington_pair(cls, gain: float = 100.0, vcc: float = 12.0, **kwargs) -> Circuit:
        """Tạo Darlington Pair amplifier"""
        result = cls._try_parametric("darlington")
        if result:
            return result
        config = SpecialAmpConfig(topology="darlington", total_gain=gain, vcc=vcc, **kwargs)
        return DarlingtonAmplifierBuilder(config).build()
    
    @classmethod
    def create_multi_stage_cascade(cls, num_stages: int = 2, total_gain: float = 100.0, **kwargs) -> Circuit:
        """Tạo Multi-Stage Cascade amplifier"""
        result = cls._try_parametric("multi_stage")
        if result:
            return result
        config = SpecialAmpConfig(topology="multi_stage", num_stages=num_stages, total_gain=total_gain, **kwargs)
        return MultiStageAmplifierBuilder(config).build()
