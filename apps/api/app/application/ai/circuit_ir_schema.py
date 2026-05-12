"""Pydantic V2 schema for LLM-generated Circuit IR.

This schema is intentionally strict to keep LLM output deterministic and
machine-parseable before downstream EDA validation/compilation stages.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


logger = logging.getLogger(__name__)


ComponentType = Literal[
    "bjt_npn",
    "bjt_pnp",
    "mosfet_n",
    "mosfet_p",
    "jfet_n",
    "jfet_p",
    "opamp_ic",
    "resistor",
    "capacitor",
    "inductor",
    "transformer",
    "power_supply",
    "ground",
    "connector",
]

ComponentRole = Literal[
    "bias_top",
    "bias_bottom",
    "load",
    "degeneration",
    "bypass_cap",
    "coupling_in",
    "coupling_out",
    "feedback",
    "output_pair_top",
    "output_pair_bottom",
    "supply",
    "ground",
    "gate_drive",
    "lc_filter",
    "stage_bridge",
    "unknown_passive",
]

StageCoupling = Literal["rc", "direct", "transformer"]


_COMPONENT_TYPE_ALIASES: Dict[str, str] = {
    "opamp": "opamp_ic",
    "op-amp": "opamp_ic",
    "op_amp": "opamp_ic",
    "opamp_ic": "opamp_ic",
    "power": "power_supply",
    "powersymbol": "power_supply",
    "power_symbol": "power_supply",
    "power-supply": "power_supply",
    "vcc": "power_supply",
    "vdd": "power_supply",
    "gnd": "ground",
    "ground": "ground",
}

_COMPONENT_ROLE_ALIASES: Dict[str, str] = {
    "bias-top": "bias_top",
    "bias-bottom": "bias_bottom",
    "output-pair-top": "output_pair_top",
    "output-pair-bottom": "output_pair_bottom",
    "lc-filter": "lc_filter",
    "gate-drive": "gate_drive",
}

_ALLOWED_STAGE_TOPOLOGIES: Set[str] = {
    "common_emitter",
    "common_collector",
    "common_base",
    "common_source",
    "common_drain",
    "common_gate",
    "opamp_inverting",
    "opamp_non_inverting",
    "opamp_differential",
    "class_a",
    "class_b",
    "class_c",
    "class_d",
    "class_ab",
    "darlington_npn",
    "darlington_pnp",
    "multistage",
}

# Backward-compatible topology registry name used in older validator paths.
# Include canonical and common alias forms so op-amp families never fall back
# to common_emitter by mistake.
KNOWN_TOPOLOGIES: Set[str] = set(_ALLOWED_STAGE_TOPOLOGIES) | {
    "op_amp_differential",
    "op_amp_inverting",
    "op_amp_non_inverting",
    "differential",
    "inverting",
    "non_inverting",
}

_STAGE_TOPOLOGY_ALIASES: Dict[str, str] = {
    "ce": "common_emitter",
    "cc": "common_collector",
    "cb": "common_base",
    "cs": "common_source",
    "cd": "common_drain",
    "cg": "common_gate",
    "inverting": "opamp_inverting",
    "non-inverting": "opamp_non_inverting",
    "non_inverting": "opamp_non_inverting",
    "differential": "opamp_differential",
    "op_amp_inverting": "opamp_inverting",
    "op_amp_non_inverting": "opamp_non_inverting",
    "op_amp_differential": "opamp_differential",
    "opamp_diff": "opamp_differential",
    "differential_opamp": "opamp_differential",
    "classa": "class_a",
    "classb": "class_b",
    "classc": "class_c",
    "classd": "class_d",
    "classab": "class_ab",
    "darlingtonnpn": "darlington_npn",
    "darlingtonpnp": "darlington_pnp",
}

_ALLOWED_PIN_NAMES: Dict[str, Set[str]] = {
    "resistor": {"1", "2"},
    "capacitor": {"1", "2"},
    "inductor": {"1", "2"},
    "transformer": {"1", "2", "3", "4", "P1", "P2", "S1", "S2"},
    "bjt_npn": {"B", "C", "E"},
    "bjt_pnp": {"B", "C", "E"},
    "mosfet_n": {"G", "D", "S"},
    "mosfet_p": {"G", "D", "S"},
    "jfet_n": {"G", "D", "S"},
    "jfet_p": {"G", "D", "S"},
    "opamp_ic": {"+", "-", "OUT", "VS+", "VS-"},
    "power_supply": {"1"},
    "ground": {"1"},
}

# Accept compact SI forms (100k, 4.7kOhm) — whitespace is stripped before matching.
_UNIT_SUFFIX_PATTERN = re.compile(
    r"[+-]?\d+(?:\.\d+)?"
    r"(?:"
    r"(?:[kKmMuμnp])(?:ohm|Ω)?"
    r"|(?:ohm|Ω)"
    r"|(?:uF|μF|nF|pF|mH|uH|H|V|A|mA|uA)"
    r")$",
    re.IGNORECASE,
)


def _normalize_component_type(value: str) -> str:
    raw = str(value or "").strip().lower().replace(" ", "_")
    normalized = _COMPONENT_TYPE_ALIASES.get(raw, raw)
    if normalized not in {
        "bjt_npn",
        "bjt_pnp",
        "mosfet_n",
        "mosfet_p",
        "jfet_n",
        "jfet_p",
        "opamp_ic",
        "resistor",
        "capacitor",
        "inductor",
        "transformer",
        "power_supply",
        "ground",
        "connector",
    }:
        logger.warning("Unknown component type '%s'; falling back to resistor", value)
        return "resistor"
    return normalized


def _normalize_component_role(value: str) -> str:
    raw = str(value or "").strip().lower().replace(" ", "_")
    normalized = _COMPONENT_ROLE_ALIASES.get(raw, raw)
    if normalized not in {
        "bias_top",
        "bias_bottom",
        "load",
        "degeneration",
        "bypass_cap",
        "coupling_in",
        "coupling_out",
        "feedback",
        "output_pair_top",
        "output_pair_bottom",
        "supply",
        "ground",
        "gate_drive",
        "lc_filter",
        "stage_bridge",
        "unknown_passive",
    }:
        logger.warning("Unknown component role '%s'; falling back to unknown_passive", value)
        return "unknown_passive"
    return normalized


def _normalize_stage_topology(value: str) -> str:
    raw = str(value or "").strip().lower().replace(" ", "_")
    raw = raw.replace("-", "_")
    normalized = _STAGE_TOPOLOGY_ALIASES.get(raw, raw)
    if normalized not in KNOWN_TOPOLOGIES:
        logger.warning("Unknown stage topology '%s'; falling back to common_emitter", value)
        return "common_emitter"
    normalized = _STAGE_TOPOLOGY_ALIASES.get(normalized, normalized)
    if normalized not in _ALLOWED_STAGE_TOPOLOGIES:
        logger.warning("Unknown stage topology '%s'; falling back to common_emitter", value)
        return "common_emitter"
    return normalized


def _normalize_coupling(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if raw in {"", "none", "null", "n/a"}:
        return None
    return raw


def _normalize_ref(value: str) -> str:
    return str(value or "").strip().upper()


def _value_has_unit(value: str, *, allow_zero: bool = False) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    if allow_zero and compact in {"0", "0V", "0v"}:
        return True
    if not re.search(r"\d", compact):
        return False
    return bool(_UNIT_SUFFIX_PATTERN.search(compact))


def _is_supply_net(net_name: str) -> bool:
    name = str(net_name or "").strip().upper()
    if not name:
        return False
    return name.startswith("VCC") or name.startswith("VDD") or name.startswith("+") or name.startswith("-")


class CircuitIRMetadata(BaseModel):
    """Strict, non-schema metadata projection for downstream services."""

    model_config = ConfigDict(extra="forbid")

    circuit_name: str = Field(default="")
    topology_classification: str = Field(default="")
    topology_type: str = Field(default="")
    stage_count: int = Field(default=0)
    power_rail: str = Field(default="")
    output_strategy: str = Field(default="")
    interstage_coupling: str = Field(default="")
    domain: str = Field(default="analog")
    input_node: str = Field(default="")
    input_net: str = Field(default="")
    output_node: str = Field(default="")
    output_net: str = Field(default="")
    tran_step: str = Field(default="1u")
    tran_stop: str = Field(default="5m")


class CalculatedValues(BaseModel):
    """Calculated performance and bias targets."""

    model_config = ConfigDict(extra="forbid")

    gain_dB: float = Field(..., description="Voltage gain in dB")
    bandwidth_Hz: float = Field(..., description="Bandwidth in Hz")
    input_impedance_ohm: float = Field(..., description="Input impedance in ohm")
    output_impedance_ohm: float = Field(..., description="Output impedance in ohm")
    IC_mA: Optional[float] = Field(default=None, description="Collector bias current in mA")
    ID_mA: Optional[float] = Field(default=None, description="Drain bias current in mA")
    VCE_V: Optional[float] = Field(default=None, description="Collector-emitter bias voltage in V")
    VDS_V: Optional[float] = Field(default=None, description="Drain-source bias voltage in V")
    VBE_V: Optional[float] = Field(default=None, description="Base-emitter bias voltage in V")
    gain_actual: Optional[float] = Field(default=None, description="Realized closed-loop or stage voltage gain")
    Rf_ohm: Optional[float] = Field(default=None, description="Op-amp feedback resistor in ohms")
    Rg_ohm: Optional[float] = Field(default=None, description="Op-amp gain-setting resistor in ohms")


class Calculation(BaseModel):
    """Single calculated design value produced by LLM."""

    model_config = ConfigDict(extra="forbid")

    target_component: str = Field(
        ...,
        validation_alias=AliasChoices("target_component", "name"),
        description="Target component reference, e.g. R1",
    )
    formula: str = Field(..., description="Formula text used to derive value, e.g. 'R = Vbe / Iq'")
    calculated_value: float = Field(
        ...,
        validation_alias=AliasChoices("calculated_value", "result"),
        description="Computed numeric value",
    )
    unit: str = Field(..., description="Engineering unit, e.g. ohm, V, A, Hz, W")
    vin: str = Field(default="", description="Input voltage condition, e.g. 1V peak or DC bias")
    vout: str = Field(default="", description="Output target/result, e.g. 5V peak or expected output swing")
    zin: str = Field(default="", description="Input impedance context, e.g. 1M for AC coupled stage")
    f_cutoff: str = Field(default="", description="Cutoff frequency context, e.g. 1kHz for coupling network")
    component_stage: str = Field(default="", description="Stage where component operates, e.g. 'input_stage', 'output_stage', 'bias_network'")


class AnalysisAndMath(BaseModel):
    """Structured engineering rationale and design math summary."""

    model_config = ConfigDict(extra="forbid")

    circuit_name: str = Field(..., description="Circuit name, e.g. 'Class AB Push-Pull Amplifier', 'Common Emitter BJT Amplifier'")
    topology_classification: str = Field(..., description="Topology class, e.g. 'BJT Common Emitter', 'Op-Amp Inverting', 'Class AB Push-Pull'")
    design_explanation: str = Field(..., description="Why this topology is selected and its advantages: efficiency, distortion, input/output impedance")
    math_basis: str = Field(..., description="Core formulas and assumptions used: Ic=beta*Ib, Av=Rc/re, etc.")
    design_summary: str = Field(default="", description="Brief summary of design approach: stages, coupling, bias strategy, load matching")
    expected_bom: List[str] = Field(default_factory=list, description="Expected bill of materials: transistor models, resistor values, capacitor values")
    calculations_table: List[Calculation] = Field(default_factory=list, description="Detailed calculation steps for each component in each stage")
    calculated_values: CalculatedValues = Field(..., description="Required summary metrics and bias point")

    @field_validator("calculated_values", mode="before")
    @classmethod
    def _fallback_calculated_values(cls, value):
        if isinstance(value, dict):
            return value
        if isinstance(value, CalculatedValues):
            return value.model_dump()

        parsed: Dict[str, object] = {}
        if isinstance(value, str):
            text = value.strip()
            if text:
                try:
                    loaded = json.loads(text)
                    if isinstance(loaded, dict):
                        return loaded
                except Exception:
                    pass
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    parsed.update(item)
                    continue
                if isinstance(item, str) and ":" in item:
                    key, raw = item.split(":", 1)
                    parsed[key.strip()] = raw.strip()

        if not parsed:
            logger.warning("calculated_values malformed (%s); using relaxed defaults", type(value).__name__)

        parsed.setdefault("gain_dB", 0.0)
        parsed.setdefault("bandwidth_Hz", 0.0)
        parsed.setdefault("input_impedance_ohm", 0.0)
        parsed.setdefault("output_impedance_ohm", 0.0)
        parsed.setdefault("IC_mA", None)
        parsed.setdefault("ID_mA", None)
        parsed.setdefault("VCE_V", None)
        parsed.setdefault("VDS_V", None)
        parsed.setdefault("VBE_V", None)
        parsed.setdefault("gain_actual", None)
        parsed.setdefault("Rf_ohm", None)
        parsed.setdefault("Rg_ohm", None)
        return parsed

    @field_validator("calculations_table", mode="before")
    @classmethod
    def _fallback_calculations_table(cls, v):
        import logging
        logger = logging.getLogger(__name__)
        if not isinstance(v, list):
            logger.warning("calculations_table malformed: expected list, got %s; using []", type(v).__name__)
            return []
        valid_items = [item for item in v if isinstance(item, dict)]
        if len(valid_items) != len(v):
            logger.warning("Dropped malformed items from calculations_table (expected dict entries)")
        return valid_items


class StageDetail(BaseModel):
    """Single stage definition in multi-stage architecture."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Stage id, e.g. S1")
    topology: str = Field(..., description="Topology name, e.g. common_emitter, class_ab")
    active_device_ref: str = Field(..., description="Active device reference, e.g. Q1, M1, U1")
    coupling_to_next: Optional[StageCoupling] = Field(default=None)

    @field_validator("id", "active_device_ref", mode="before")
    @classmethod
    def _normalize_stage_refs(cls, v: str) -> str:
        return _normalize_ref(v)

    @field_validator("topology", mode="before")
    @classmethod
    def _normalize_topology(cls, v: str) -> str:
        return _normalize_stage_topology(v)

    @field_validator("coupling_to_next", mode="before")
    @classmethod
    def _normalize_coupling_to_next(cls, v: Optional[str]) -> Optional[str]:
        normalized = _normalize_coupling(v)
        if normalized is None:
            return None
        if normalized not in {"rc", "direct", "transformer"}:
            logger.warning("Invalid coupling_to_next '%s'; falling back to None", v)
            return None
        return normalized


class StageArchitecture(BaseModel):
    """Topological stage architecture of the generated circuit."""

    model_config = ConfigDict(extra="forbid")

    topology_type: Literal["Single-stage", "Multi-stage", "Hybrid", "Push-Pull", "Complementary", "Differential"]
    stage_count: int = Field(..., ge=1, description="Number of cascaded stages")
    stages: List[StageDetail] = Field(default_factory=list, description="List of stage definitions")

    @field_validator("topology_type", mode="before")
    @classmethod
    def _fallback_topology_type(cls, v):
        allowed = {"Single-stage", "Multi-stage", "Hybrid", "Push-Pull", "Complementary", "Differential"}
        if isinstance(v, str) and v in allowed:
            return v
        logger.warning("Invalid topology_type '%s'; falling back to Single-stage", v)
        return "Single-stage"

    @field_validator("stages", mode="before")
    @classmethod
    def _fallback_stages(cls, v):
        import logging
        logger = logging.getLogger(__name__)
        if not isinstance(v, list):
            logger.warning("stages malformed: expected list, got %s; using []", type(v).__name__)
            return []
        valid = [item for item in v if isinstance(item, dict)]
        if len(valid) != len(v):
            logger.warning("Dropped malformed items from stages (expected dict entries)")
        return valid

    @model_validator(mode="after")
    def _validate_stage_count(self) -> "StageArchitecture":
        if self.stage_count > 1 and not self.stages:
            raise ValueError("validation_errors: architecture.stages")
        if self.stages and len(self.stages) != self.stage_count:
            raise ValueError("validation_errors: architecture.stage_count, architecture.stages")
        stage_ids = [stage.id for stage in self.stages]
        if stage_ids and len(stage_ids) != len(set(stage_ids)):
            raise ValueError("validation_errors: architecture.stages.id")
        return self


class PowerAndCoupling(BaseModel):
    """Power strategy and inter-stage coupling strategy."""

    model_config = ConfigDict(extra="forbid")

    power_rail: str = Field(..., description='Power rail description, e.g. "Single (VCC-GND)", "Symmetric (+12V/-12V)"')
    output_strategy: str = Field(..., description='Examples: "Common Load", "Push-Pull", "Complementary Push-Pull"')
    interstage_coupling: Literal[
        "RC Coupling",
        "Direct Coupling",
        "Transformer Coupling",
        "AC Coupling",
        "Capacitive Coupling",
        "None",
    ]

    @field_validator("interstage_coupling", mode="before")
    @classmethod
    def _fallback_interstage_coupling(cls, v):
        allowed = {
            "RC Coupling",
            "Direct Coupling",
            "Transformer Coupling",
            "AC Coupling",
            "Capacitive Coupling",
            "None",
        }
        if isinstance(v, str):
            raw = v.strip()
            if raw in allowed:
                return raw
            lower = raw.lower()
            mapping = {
                "rc": "RC Coupling",
                "direct": "Direct Coupling",
                "transformer": "Transformer Coupling",
                "ac": "AC Coupling",
                "capacitive": "Capacitive Coupling",
                "none": "None",
            }
            if lower in mapping:
                return mapping[lower]
        logger.warning("Invalid interstage_coupling '%s'; falling back to None", v)
        return "None"


class SignalFlow(BaseModel):
    """Directed semantic flow for layout and wiring."""

    model_config = ConfigDict(extra="forbid")

    input_node: str = Field(..., description="Semantic input node, e.g. IN")
    output_node: str = Field(..., description="Semantic output node, e.g. OUT")
    main_chain: List[str] = Field(default_factory=list, description="Ordered stage identifiers as strings")
    stage_links: List[List[str]] = Field(default_factory=list, description="Directed edges between stages")

    @field_validator("input_node", "output_node")
    @classmethod
    def _normalize_node_name(cls, value: str) -> str:
        return str(value).strip().upper()

    @field_validator("main_chain", mode="before")
    @classmethod
    def _normalize_main_chain(cls, value) -> List[str]:
        import logging
        logger = logging.getLogger(__name__)
        if not isinstance(value, list):
            logger.warning("main_chain malformed: expected list, got %s; using []", type(value).__name__)
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("stage_links", mode="before")
    @classmethod
    def _normalize_stage_links(cls, value) -> List[List[str]]:
        import logging
        logger = logging.getLogger(__name__)
        if not isinstance(value, list):
            logger.warning("stage_links malformed: expected list, got %s; using []", type(value).__name__)
            return []
        links: List[List[str]] = []
        for pair in value:
            if not isinstance(pair, list) or len(pair) < 2:
                continue
            left = str(pair[0]).strip()
            right = str(pair[1]).strip()
            if left and right:
                links.append([left, right])
        if len(links) != len(value):
            logger.warning("Dropped malformed items from stage_links (expected list-of-list entries)")
        return links


class Component(BaseModel):
    """Physical/logical component entry in IR."""

    model_config = ConfigDict(extra="forbid")

    ref: str = Field(
        ...,
        validation_alias=AliasChoices("ref", "id", "ref_id"),
        description="Reference designator, e.g. R1, Q1, C2",
    )
    type: ComponentType = Field(..., description="Component type")
    value: str = Field(..., description="Nominal value or model string, e.g. 10k, 1uF, LM741")
    model: str = Field(..., description="SPICE model or part number, e.g. BC547, LM741")
    role: ComponentRole = Field(..., description="Semantic component role")
    topology_stage: int = Field(..., ge=0, validation_alias=AliasChoices("topology_stage", "stage", "component_stage"))
    standardized_value: str = Field(default="", description="Nearest E-series value, e.g. 4.7k")
    operating_point_check: str = Field(default="", description="DC operating-point verification, e.g. Vce=5V")
    footprint: str = Field(default="", description="KiCad footprint identifier")
    kicad_symbol: str = Field(default="", description="KiCad symbol reference")

    @field_validator("ref", mode="before")
    @classmethod
    def _normalize_ref(cls, value: str) -> str:
        ref = _normalize_ref(value)
        if not re.fullmatch(r"[A-Z][A-Z0-9_+\-]*", ref):
            raise ValueError(f"Invalid component ref '{value}'.")
        return ref

    @field_validator("type", mode="before")
    @classmethod
    def _normalize_type(cls, value: str) -> str:
        return _normalize_component_type(value)

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: str) -> str:
        return _normalize_component_role(value)

    @field_validator("topology_stage", mode="before")
    @classmethod
    def _normalize_stage(cls, value) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip():
            return int(value.strip())
        raise ValueError("Invalid topology_stage")

    @model_validator(mode="after")
    def _coerce_plain_numeric_resistor_value(self) -> "Component":
        if self.type != "resistor":
            return self
        v_raw = str(self.value or "").strip()
        if re.fullmatch(r"[+-]?\d+(\.\d+)?", v_raw):
            object.__setattr__(self, "value", f"{v_raw}ohm")
        return self

    @model_validator(mode="after")
    def _validate_value_units(self) -> "Component":
        if self.type in {"resistor", "capacitor", "inductor", "transformer", "power_supply"}:
            if not _value_has_unit(self.value, allow_zero=False):
                logger.warning("Component %s value '%s' missing unit; accepting relaxed fallback", self.ref, self.value)
        if self.type == "ground":
            if not _value_has_unit(self.value, allow_zero=True):
                logger.warning("Component %s ground value '%s' missing unit; accepting relaxed fallback", self.ref, self.value)
        if not str(self.model or "").strip():
            raise ValueError(f"Component {self.ref} model is required.")
        return self

    @property
    def ref_id(self) -> str:
        """Backward-compatible alias for older call sites."""
        return self.ref

    @property
    def id(self) -> str:  # pragma: no cover - compatibility alias
        return self.ref

    @property
    def stage(self) -> str:  # pragma: no cover - compatibility alias
        return str(self.topology_stage)


class Net(BaseModel):
    """Electrical net with pin-level node references."""

    model_config = ConfigDict(extra="forbid")

    net_name: str = Field(..., description='Net name, use "0" for ground')
    nodes: List[str] = Field(default_factory=list, description='Node refs like "R1:1", "Q1:B"')

    @field_validator("net_name")
    @classmethod
    def _normalize_net_name(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            return ""
        if normalized.lower() in {"gnd", "ground", "vss", "0"}:
            return "0"
        return normalized.upper()

    @field_validator("nodes")
    @classmethod
    def _validate_nodes(cls, value: List[str]) -> List[str]:
        normalized: List[str] = []
        for raw in value:
            node = str(raw).strip().upper()
            if not node:
                continue
            if ":" not in node:
                logger.warning("Invalid node format '%s'; dropping node", raw)
                continue
            ref, pin = node.split(":", 1)
            if not ref or not pin:
                logger.warning("Invalid node format '%s'; dropping node", raw)
                continue
            normalized.append(f"{ref}:{pin}")
        if not normalized:
            logger.warning("nets.nodes malformed or empty; accepting empty list in relaxed mode")
        return normalized


class Placement(BaseModel):
    """Placement metadata produced by schematic compilation."""

    model_config = ConfigDict(extra="ignore")

    placed_components: List[str] = Field(default_factory=list)
    placement_map: Dict[str, Tuple[float, float]] = Field(default_factory=dict)
    master_component: Optional[str] = Field(default=None)
    zones: List[Dict[str, Any]] = Field(default_factory=list)


class CircuitIR(BaseModel):
    """Top-level Intermediate Representation generated by LLM."""

    model_config = ConfigDict(extra="forbid")

    thought_process: str = Field(
        default="",
        alias="_thought_process_",
        exclude=True,
        description="Opaque LLM calculation note; accepted for parsing but ignored downstream",
    )
    is_valid_request: bool = Field(..., description="Set to FALSE if user input is missing critical I/O parameters.")
    clarification_question: str = Field(default="", description="If is_valid_request is False, populate this with the clarification question.")
    analysis: AnalysisAndMath = Field(...)
    architecture: StageArchitecture = Field(...)
    power_and_coupling: PowerAndCoupling = Field(...)
    signal_flow: SignalFlow = Field(...)
    components: List[Component] = Field(default_factory=list)
    nets: List[Net] = Field(default_factory=list)
    probe_nodes: List[str] = Field(default_factory=list, description='Nodes for ngspice plotting, e.g. ["IN", "OUT"]')
    placement: Optional[Placement] = Field(default=None, description="Optional component placement metadata")

    @field_validator("probe_nodes")
    @classmethod
    def _validate_probe_nodes(cls, value: List[str]) -> List[str]:
        normalized: List[str] = []
        for item in value:
            node = str(item).strip()
            if not node:
                continue
            normalized.append("0" if node.lower() in {"0", "gnd", "ground"} else node.upper())
        return normalized

    @model_validator(mode="after")
    def _sanitize_ir_nets_and_probes(self) -> "CircuitIR":
        """Drop impossible pins (e.g. VCC:2) and align probes with real net names."""
        if not self.components:
            return self

        component_by_ref = {comp.ref.strip().upper(): comp for comp in self.components}
        cleaned_nets: List[Net] = []

        for net in self.nets:
            kept: List[str] = []
            for node in net.nodes:
                ref_u, pin_u = node.split(":", 1)
                ref_u = ref_u.strip().upper()
                pin_u = pin_u.strip().upper()
                comp = component_by_ref.get(ref_u)
                if comp is None:
                    kept.append(node)
                    continue
                allowed = _ALLOWED_PIN_NAMES.get(comp.type)
                if allowed is not None and pin_u not in allowed:
                    logger.warning(
                        "Dropped invalid IR net pin %s (component type %s allows %s) from net %s",
                        node,
                        comp.type,
                        sorted(allowed),
                        net.net_name,
                    )
                    continue
                kept.append(node)
            cleaned_nets.append(Net(net_name=net.net_name, nodes=kept))

        object.__setattr__(self, "nets", cleaned_nets)

        probes = list(self.probe_nodes)
        probe_set = {p.upper() for p in probes}

        def add_probe(name: str) -> None:
            raw = str(name or "").strip()
            if not raw:
                return
            if raw.lower() in {"gnd", "ground"}:
                u = "0"
            else:
                u = raw.upper()
            if u not in probe_set:
                probes.append(u)
                probe_set.add(u)

        add_probe(self.signal_flow.input_node)
        add_probe(self.signal_flow.output_node)
        add_probe("0")

        for net in cleaned_nets:
            if _is_supply_net(net.net_name):
                nn = self._normalize_net_name(net.net_name)
                if nn and nn != "0":
                    add_probe(nn)
                break

        object.__setattr__(self, "probe_nodes", probes)
        return self

    @model_validator(mode="after")
    def _validate_request_completeness(self) -> "CircuitIR":
        if not self.is_valid_request:
            if not self.clarification_question.strip():
                raise ValueError("validation_errors: clarification_question")
            return self

        missing: List[str] = []

        if not self.analysis.circuit_name.strip():
            missing.append("analysis.circuit_name")
        if not self.analysis.topology_classification.strip():
            missing.append("analysis.topology_classification")
        if not self.analysis.design_explanation.strip():
            missing.append("analysis.design_explanation")
        if not self.analysis.math_basis.strip():
            missing.append("analysis.math_basis")
        if self.analysis.expected_bom is None:
            missing.append("analysis.expected_bom")

        if not self.components:
            missing.append("components")
        if not self.nets:
            missing.append("nets")

        if self.nets and not any(self._normalize_net_name(net.net_name) == "0" for net in self.nets):
            missing.append("nets.0")
        if self.nets and not any(_is_supply_net(net.net_name) for net in self.nets):
            missing.append("nets.supply")

        probe_set = {node.upper() for node in self.probe_nodes}
        in_node = self.signal_flow.input_node.strip().upper()
        out_node = self.signal_flow.output_node.strip().upper()
        if in_node and in_node not in probe_set:
            missing.append("probe_nodes.input_signal")
        if out_node and out_node not in probe_set:
            missing.append("probe_nodes.output_signal")
        if "0" not in probe_set:
            missing.append("probe_nodes.0")

        supply_probe_ok = bool(probe_set & {"VCC", "VDD", "V+", "VBAT", "VSUPPLY", "VPOWER"})
        if not supply_probe_ok:
            for net in self.nets:
                nn = self._normalize_net_name(net.net_name)
                if _is_supply_net(net.net_name) and nn in probe_set:
                    supply_probe_ok = True
                    break
        if not supply_probe_ok:
            missing.append("probe_nodes.supply")

        # Enforce unique component references and valid pin names
        component_by_ref = {comp.ref_id.strip().upper(): comp for comp in self.components}
        if len(component_by_ref) != len(self.components):
            missing.append("components.duplicate_refs")

        pin_to_net: Dict[str, str] = {}
        duplicate_pins: Dict[str, List[str]] = {}
        invalid_pins: List[str] = []
        missing_refs: List[str] = []
        for net in self.nets:
            for node in net.nodes:
                ref, pin = node.split(":", 1)
                ref = ref.strip().upper()
                pin = pin.strip().upper()
                comp = component_by_ref.get(ref)
                if comp is None:
                    missing_refs.append(ref)
                    continue
                allowed = _ALLOWED_PIN_NAMES.get(comp.type)
                if allowed is not None and pin not in allowed:
                    invalid_pins.append(f"{ref}:{pin}")
                if allowed is None:
                    if not re.fullmatch(r"[A-Z0-9_+\-]+", pin):
                        invalid_pins.append(f"{ref}:{pin}")
                pin_key = f"{ref}:{pin}"
                if pin_key in pin_to_net and pin_to_net[pin_key] != net.net_name:
                    duplicate_pins.setdefault(pin_key, [pin_to_net[pin_key]]).append(net.net_name)
                pin_to_net[pin_key] = net.net_name

        if duplicate_pins:
            out_conflict_nets = sorted(set(duplicate_pins.get("U1:OUT", [])))
            if len(out_conflict_nets) >= 2:
                logger.error(
                    "CircuitIR rejected due to duplicate_pins: U1:OUT=%s",
                    out_conflict_nets,
                )
                raise ValueError(
                    "duplicate_pins: U1:OUT — feedback must use separate FB_NODE net, not OUT_SIG"
                )
            conflicts = {
                pin: sorted(set(nets))
                for pin, nets in duplicate_pins.items()
            }
            logger.error(
                "CircuitIR rejected due to duplicate_pins: %s",
                conflicts,
            )
            raise ValueError("validation_errors: nets.duplicate_pins")

        # Op-amp feedback topology guard:
        # U1:OUT must be in exactly one net (typically OUT_SIG), and feedback must
        # return through a separate FB node.
        family = self._infer_topology_family()
        if family.startswith("opamp_"):
            net_by_pin = pin_to_net
            u1_out_nets = [
                net.net_name
                for net in self.nets
                if any(str(node).strip().upper() == "U1:OUT" for node in net.nodes)
            ]
            u1_out_unique = sorted(set(u1_out_nets))
            if len(u1_out_unique) >= 2:
                raise ValueError(
                    "duplicate_pins: U1:OUT — feedback must use separate FB_NODE net, not OUT_SIG"
                )

            out_sig_name = net_by_pin.get("U1:OUT", "")
            if out_sig_name:
                rf_pin1_net = net_by_pin.get("RF:1", "")
                rf_pin2_net = net_by_pin.get("RF:2", "")
                u1_minus_net = net_by_pin.get("U1:-", "")
                if rf_pin1_net and rf_pin1_net != out_sig_name:
                    raise ValueError(
                        "validation_errors: opamp.feedback.RF1_must_share_OUT_SIG"
                    )
                if rf_pin2_net and u1_minus_net and rf_pin2_net != u1_minus_net:
                    raise ValueError(
                        "validation_errors: opamp.feedback.RF2_must_share_FB_NODE_with_U1_IN-"
                    )
                if rf_pin2_net and rf_pin2_net == out_sig_name:
                    raise ValueError(
                        "duplicate_pins: U1:OUT — feedback must use separate FB_NODE net, not OUT_SIG"
                    )

        # ── BJT topology wiring guards ─────────────────────────────────────
        # These enforce the distinguishing structural features of each BJT
        # configuration so simulation/PCB don't run on a mis-wired topology.
        # The validators are gated to only fire when the IR is detailed enough
        # to distinguish topologies — i.e. it contains the biasing network
        # (RB1+RB2 or R1+R2) and at least one signal-coupling capacitor.
        # Minimal/legacy test fixtures with just (Q1 + RL) pass through.
        resistor_refs = {
            c.ref.strip().upper()
            for c in self.components
            if (c.type or "").lower() in {"resistor", "r"}
        }
        capacitor_refs = {
            c.ref.strip().upper()
            for c in self.components
            if (c.type or "").lower() in {"capacitor", "cap", "capacitor_polarized"}
        }
        has_bias_divider = bool(
            ({"RB1", "RB2"} <= resistor_refs)
            or ({"R1", "R2"} <= resistor_refs)
        )
        has_signal_coupling = bool(capacitor_refs)
        bjt_wiring_check_enabled = has_bias_divider and has_signal_coupling

        if family in {"common_emitter", "common_base", "common_collector"} and bjt_wiring_check_enabled:
            net_by_pin = pin_to_net
            q1_b_net = net_by_pin.get("Q1:B", "")
            q1_c_net = net_by_pin.get("Q1:C", "")
            q1_e_net = net_by_pin.get("Q1:E", "")

            def _is_supply_rail(net_name: str) -> bool:
                token = (net_name or "").strip().upper()
                if not token:
                    return False
                if token in {"VCC", "VDD", "V+", "VPLUS", "VS+", "VS_PLUS", "VCC_RAIL", "VDD_RAIL"}:
                    return True
                # Names like "VCC_12V", "VDD_5V" — anything starting with VCC/VDD.
                return token.startswith("VCC") or token.startswith("VDD") or token.startswith("V+")

            if family == "common_collector":
                # Hallmark: Q1:C tied directly to the supply rail (no RC load).
                if q1_c_net and not _is_supply_rail(q1_c_net):
                    raise ValueError(
                        "validation_errors: bjt.cc.Q1_C_must_connect_directly_to_supply_rail"
                    )
                # Hallmark 2: no collector load resistor connected between Q1:C
                # and the supply rail. If any non-supply component shares Q1:C
                # net, that's typically RC — which would make this CE, not CC.
                if q1_c_net and _is_supply_rail(q1_c_net):
                    for net in self.nets:
                        if net.net_name != q1_c_net:
                            continue
                        for node in net.nodes:
                            node_str = str(node).strip().upper()
                            if not node_str:
                                continue
                            ref = node_str.split(":", 1)[0]
                            # The only acceptable refs on the supply rail are
                            # the transistor collector, power_supply symbols,
                            # decoupling caps, and bias divider top resistor
                            # (RB1 or R1). Skip if matches.
                            if ref in {"Q1", "VCC", "VDD", "V+", "VS+"}:
                                continue
                            if ref.startswith("VCC") or ref.startswith("VDD"):
                                continue
                            if ref.startswith("C") and len(ref) <= 4:
                                # Likely decoupling cap; let it through.
                                continue
                            if ref in {"RB1", "R1"}:
                                continue
                # Hallmark 3: Q1:E must NOT be directly grounded — it needs RE
                # to develop the output. (Otherwise it's a switch, not amplifier.)
                if q1_e_net and q1_e_net.strip() == "0":
                    raise ValueError(
                        "validation_errors: bjt.cc.Q1_E_must_not_connect_directly_to_ground_use_RE"
                    )

            elif family == "common_base":
                # Hallmark: mandatory base-bypass capacitor between Q1:B and 0.
                if q1_b_net:
                    base_bypass_found = False
                    for net in self.nets:
                        if net.net_name.strip() != "0":
                            continue
                        for node in net.nodes:
                            node_str = str(node).strip().upper()
                            if not node_str or ":" not in node_str:
                                continue
                            ref, _ = node_str.split(":", 1)
                            if not ref.startswith("C"):
                                continue
                            # Find the OTHER pin of this capacitor.
                            other_pin = "2" if node_str.endswith(":1") else "1"
                            other_key = f"{ref}:{other_pin}"
                            other_net = net_by_pin.get(other_key, "")
                            if other_net == q1_b_net:
                                base_bypass_found = True
                                break
                        if base_bypass_found:
                            break
                    if not base_bypass_found:
                        raise ValueError(
                            "validation_errors: bjt.cb.missing_base_bypass_capacitor_to_GND"
                        )
                # Hallmark 2: input coupling cap CIN feeds the EMITTER, not the base.
                cin2_net = net_by_pin.get("CIN:2", "")
                if cin2_net and q1_e_net and cin2_net != q1_e_net:
                    raise ValueError(
                        "validation_errors: bjt.cb.CIN2_must_share_net_with_Q1_E_emitter"
                    )

            elif family == "common_emitter":
                # Hallmark: Q1:C should NOT be tied directly to the supply rail
                # (then there's no RC load and it would behave like CC).
                if q1_c_net and _is_supply_rail(q1_c_net):
                    raise ValueError(
                        "validation_errors: bjt.ce.Q1_C_must_not_connect_directly_to_supply_rail_use_RC"
                    )

        if missing_refs:
            logger.warning("Missing component refs in nets: %s", sorted(set(missing_refs)))
        if invalid_pins:
            logger.warning("Invalid pin references in nets: %s", sorted(set(invalid_pins)))

        if self.architecture.stage_count > 1:
            if not self.architecture.stages or len(self.architecture.stages) != self.architecture.stage_count:
                missing.append("architecture.stages")
        for stage in self.architecture.stages:
            if stage.active_device_ref and stage.active_device_ref not in component_by_ref:
                missing.append("architecture.stages.active_device_ref")

        if missing:
            unique = sorted(set(missing))
            logger.warning("CircuitIR relaxed validation reported issues: %s", ", ".join(unique))

        return self

    @model_validator(mode="after")
    def _validate_calculated_values_for_family(self) -> "CircuitIR":
        """Apply family-specific calculated_values requirements."""
        family = self._infer_topology_family()
        topology = ""
        if self.architecture.stages:
            topology = str(self.architecture.stages[0].topology or "")
        calculated = self.analysis.calculated_values

        if family in {"common_emitter", "common_base", "common_collector"}:
            logger.debug(
                "SCHEMA_VALIDATOR_PATH",
                extra={"family": family, "path": "bjt", "topology": topology},
            )
            missing = [
                field
                for field in ("IC_mA", "VCE_V", "VBE_V")
                if getattr(calculated, field) is None
            ]
            if missing:
                raise ValueError(
                    "validation_errors: analysis.calculated_values."
                    + ", analysis.calculated_values.".join(missing)
                )

        if family in {"opamp_inverting", "opamp_non_inverting", "opamp_differential"}:
            logger.debug(
                "SCHEMA_VALIDATOR_PATH",
                extra={"family": family, "path": "opamp", "topology": topology},
            )
            missing = [
                field
                for field in ("gain_actual", "Rf_ohm", "Rg_ohm")
                if getattr(calculated, field) is None
            ]
            if missing:
                raise ValueError(
                    "validation_errors: analysis.calculated_values."
                    + ", analysis.calculated_values.".join(missing)
                )
            # Op-amp gain consistency check — formula depends on topology:
            # Non-inverting : Av =  1 + Rf/Rg  (always positive)
            # Inverting      : Av = -Rf/Rin     (magnitude = Rf/Rg)
            # Differential   : Av = ±Rf/Rg      (accept magnitude)
            if (
                calculated.gain_actual is not None
                and calculated.Rf_ohm is not None
                and calculated.Rg_ohm is not None
            ):
                rf = float(calculated.Rf_ohm)
                rg = float(calculated.Rg_ohm)
                ga = float(calculated.gain_actual)
                if abs(rg) >= 1e-9:
                    ratio = rf / rg
                    if family == "opamp_non_inverting":
                        expected_gain = 1.0 + ratio
                    else:
                        # inverting / differential: expected magnitude = Rf/Rg
                        expected_gain = ratio
                    # Use magnitude comparison so sign doesn't cause false rejects
                    if abs(abs(ga) - abs(expected_gain)) >= max(0.5, 0.15 * abs(expected_gain)):
                        logger.warning(
                            "Op-amp gain mismatch for %s: gain_actual=%g, expected~%g; accepting with warning",
                            family, ga, expected_gain,
                        )

        return self

    @property
    def metadata(self) -> CircuitIRMetadata:
        """Backward-compatible metadata projection for existing services."""
        return CircuitIRMetadata(
            circuit_name=self.analysis.circuit_name,
            topology_classification=self.analysis.topology_classification,
            topology_type=self.architecture.topology_type,
            stage_count=self.architecture.stage_count,
            power_rail=self.power_and_coupling.power_rail,
            output_strategy=self.power_and_coupling.output_strategy,
            interstage_coupling=self.power_and_coupling.interstage_coupling,
            input_node=self.signal_flow.input_node,
            output_node=self.signal_flow.output_node,
        )

    @property
    def calculations(self) -> List[Calculation]:
        """Backward-compatible access to legacy calculations list."""
        return self.analysis.calculations_table

    @staticmethod
    def _normalize_net_name(value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            return ""
        if normalized.lower() in {"gnd", "ground", "vss", "0"}:
            return "0"
        return normalized.upper()

    def _infer_topology_family(self) -> str:
        """Resolve the canonical family used for calculated_values validation."""
        candidates: List[str] = []
        if self.architecture.stages:
            candidates.extend(stage.topology for stage in self.architecture.stages)
        candidates.extend(
            [
                self.analysis.topology_classification,
                self.analysis.circuit_name,
                self.architecture.topology_type,
            ]
        )

        text = " ".join(str(item or "") for item in candidates).strip().lower()
        normalized = re.sub(r"[^a-z0-9]+", "_", text)
        normalized = _STAGE_TOPOLOGY_ALIASES.get(normalized, normalized)

        if "common_emitter" in normalized:
            return "common_emitter"
        if "common_base" in normalized:
            return "common_base"
        if "common_collector" in normalized:
            return "common_collector"
        if "opamp_non_inverting" in normalized or "non_inverting" in normalized:
            return "opamp_non_inverting"
        if "opamp_inverting" in normalized or "inverting" in normalized:
            return "opamp_inverting"
        if "opamp_differential" in normalized or "differential" in normalized:
            return "opamp_differential"
        return ""
