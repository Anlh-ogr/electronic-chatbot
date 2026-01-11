# thesis/electronic-chatbot/apps/api/app/domains/circuits/template_builders.py
"""
Parametric Template Builders - Sinh mạch khuếch đại tự động từ config.

Thay thế hard-code templates để:
* Dễ mở rộng (>10 loại mạch)
* Tự động tính toán giá trị linh kiện
* Auto-generate ĐÚNG số lượng components cần thiết
* AI agent customize parameters dễ dàng

Usage:
    # Simple API
    circuit = AmplifierFactory.create_bjt(
        topology="CE",
        gain=15.0,
        vcc=12.0
    )
    
    # Full control
    config = BJTAmplifierConfig(
        topology="CE",
        gain_target=20.0,
        rc=3300  # override auto-calc
    )
    circuit = BJTAmplifierBuilder(config).build()
"""

from typing import Dict, Literal, Optional, List, Tuple
from dataclasses import dataclass
import math
from .entities import (
    Circuit, Component, Net, Port, Constraint, PinRef,
    ComponentType, PortDirection, ParameterValue
)


# ========== CONFIG DEFINITIONS ==========

@dataclass
class BJTAmplifierConfig:
    """
    Config cho BJT amplifier - parametric configuration.
    
    Builder sẽ tự động:
    - Sinh ĐÚNG số lượng components cần thiết (R1, R2, RC, RE, Cin, Cout, CE)
    - Tính toán values từ gain/VCC target
    - Tạo topology phù hợp (CE/CC/CB)
    """
    topology: Literal["CE", "CC", "CB"]
    bias_type: Literal["voltage_divider", "fixed", "self"] = "voltage_divider"
    
    # Operating point
    vcc: float = 12.0  # V
    ic_target: float = 1.5e-3  # A
    gain_target: float = 10.0 # out > 10 in
    
    # BJT model
    bjt_model: str = "2N3904"
    beta: float = 100.0
    
    # Component overrides (None = auto-calculate)
    rc: Optional[float] = None
    re: Optional[float] = None
    r1: Optional[float] = None
    r2: Optional[float] = None
    
    # Capacitors
    include_coupling: bool = True
    cin: float = 10e-6  # F
    cout: float = 10e-6
    ce: float = 100e-6


@dataclass
class OpAmpAmplifierConfig:
    """Config cho Op-Amp amplifier - parametric configuration."""
    topology: Literal["inverting", "non_inverting", "differential"]
    gain: float = 10.0
    
    # Op-Amp model
    opamp_model: str = "LM741"
    
    # Component overrides
    r1: Optional[float] = None
    r2: Optional[float] = None
    r3: Optional[float] = None  # for differential
    r4: Optional[float] = None
    
    # Capacitors
    include_coupling: bool = True
    cin: Optional[float] = 10e-6
    cout: Optional[float] = 10e-6


# ========== COMPONENT VALUE CALCULATORS ==========

class BJTComponentCalculator:
    """Tính toán giá trị linh kiện cho BJT amplifier"""
    
    E12_SERIES = [10, 12, 15, 18, 22, 27, 33, 39, 47, 56, 68, 82]
    
    @staticmethod
    def calculate_bias_resistors(
        vcc: float, 
        vbe: float, 
        ic: float, 
        beta: float,
        bias_type: str = "voltage_divider"
    ) -> Dict[str, float]:
        """
        Tính R1, R2 cho bias network.
        
        Strategy: VB = VBE + 0.1*VCC (rule of thumb)
        Current through divider = 10*IB (stiff bias)
        """
        if bias_type != "voltage_divider":
            raise NotImplementedError(f"Bias type '{bias_type}' chưa support")
        
        vb = vbe + 0.1 * vcc
        ib = ic / beta
        i_divider = 10 * ib
        
        r2 = vb / i_divider
        r1 = (vcc - vb) / i_divider
        
        return {
            "R1": BJTComponentCalculator._standardize(r1),
            "R2": BJTComponentCalculator._standardize(r2),
            "VB": vb
        }
    
    @staticmethod
    def calculate_emitter_resistor(vb: float, vbe: float, ic: float) -> float:
        """Tính RE để đạt IC mong muốn"""
        ve = vb - vbe
        if ve <= 0:
            raise ValueError(f"VE = {ve}V <= 0, không hợp lệ")
        re = ve / ic
        return BJTComponentCalculator._standardize(re)
    
    @staticmethod
    def calculate_collector_resistor(
        vcc: float, 
        ic: float, 
        gain: float, 
        re: float
    ) -> float:
        """
        Tính RC từ gain mong muốn.
        Gain ≈ -RC/RE (CE với bypass cap)
        Constraint: VC ở mid-supply (0.4-0.6 VCC)
        """
        rc_from_gain = abs(gain) * re
        vc = vcc - ic * rc_from_gain
        
        if vc < 0.3 * vcc:
            rc_from_headroom = 0.5 * vcc / ic
            rc = min(rc_from_gain, rc_from_headroom)
        else:
            rc = rc_from_gain
        
        return BJTComponentCalculator._standardize(rc)
    
    @staticmethod
    def _standardize(value: float) -> float:
        """Làm tròn về giá trị E12 chuẩn"""
        if value <= 0:
            raise ValueError(f"Resistor value {value} <= 0")
        
        magnitude = 10 ** math.floor(math.log10(value))
        normalized = value / magnitude
        closest = min(BJTComponentCalculator.E12_SERIES, 
                     key=lambda x: abs(x - normalized))
        
        return closest * magnitude


class OpAmpComponentCalculator:
    """Tính toán giá trị linh kiện cho Op-Amp amplifier"""
    
    @staticmethod
    def calculate_feedback_resistors(
        gain: float, 
        topology: str, 
        r1_base: float = 10_000
    ) -> Dict[str, float]:
        """
        Tính R1, R2 (và R3, R4 cho differential) từ gain.
        
        Formulas:
        - Inverting: Av = -R2/R1
        - Non-inverting: Av = 1 + R2/R1
        - Differential: Av = R2/R1 (matched: R3=R1, R4=R2)
        """
        if topology == "inverting":
            r2 = abs(gain) * r1_base
            return {"R1": r1_base, "R2": r2}
        
        elif topology == "non_inverting":
            if gain < 1:
                raise ValueError("Non-inverting gain phải >= 1")
            r2 = (gain - 1) * r1_base
            return {"R1": r1_base, "R2": r2}
        
        elif topology == "differential":
            r2 = gain * r1_base
            return {
                "R1": r1_base,
                "R2": r2,
                "R3": r1_base,  # matched
                "R4": r2        # matched
            }
        
        else:
            raise ValueError(f"Unknown topology: {topology}")


# ========== PARAMETRIC BUILDERS ==========

class BJTAmplifierBuilder:
    """
    Parametric builder cho BJT amplifier.
    
    Tự động:
    - Sinh ĐÚNG số lượng components (CE: 8 components, CC: 6 components, CB: 9 components)
    - Tính toán values từ gain/VCC
    - Tạo nets phù hợp topology
    """
    
    def __init__(self, config: BJTAmplifierConfig):
        self.config = config
        self.calc = BJTComponentCalculator()
    
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
        
        resistors = self.calc.calculate_feedback_resistors(
            cfg.gain, "inverting", cfg.r1 or 10_000
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
            nets["INPUT"] = Net("INPUT", (PinRef("Cin", "1"),))
            nets["FEEDBACK"] = Net("FEEDBACK", (
                PinRef("Cin", "2"),
                PinRef("R1", "1"),
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
            nets["FEEDBACK"] = Net("FEEDBACK", (
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
            "gain": Constraint("gain", -cfg.gain, None),
            "topology": Constraint("topology", "inverting", None),
        }
        
        return Circuit(
            name=f"Inverting Op-Amp (Av={-cfg.gain})",
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
        config = BJTAmplifierConfig(
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
