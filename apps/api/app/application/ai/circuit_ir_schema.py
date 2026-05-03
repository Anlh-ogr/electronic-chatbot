"""Pydantic V2 schema for LLM-generated Circuit IR.

This schema is intentionally strict to keep LLM output deterministic and
machine-parseable before downstream EDA validation/compilation stages.
"""

from __future__ import annotations

from typing import List, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


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
    topology_classification: str = Field(..., description="Topology class, e.g. 'BJT Common Emitter', 'Op-Amp Inverting', 'Class AB Push-Pull', 'Complementary Push-Pull'")
    design_explanation: str = Field(..., description="Why this topology is selected and its advantages: efficiency, distortion, input/output impedance, frequency response")
    math_basis: str = Field(..., description="Core formulas and assumptions used: Ic=βIb, Av=Rc/re, output power, efficiency, etc.")
    design_summary: str = Field(default="", description="Brief summary of design approach: stages, coupling, bias strategy, load matching")
    expected_bom: List[str] = Field(default_factory=list, description="Expected bill of materials: transistor models, resistor values, capacitor values")
    calculations_table: List[Calculation] = Field(default_factory=list, description="Detailed calculation steps for each component in each stage")

    @field_validator("calculations_table", mode="before")
    @classmethod
    def _fallback_calculations_table(cls, v):
        import logging
        logger = logging.getLogger(__name__)
        # If not a list at all, replace with empty list to avoid hard failure
        if not isinstance(v, list):
            logger.warning("calculations_table malformed: expected list, got %s; using []", type(v).__name__)
            return []
        # Keep only dict entries (Calculation expects dict-like input)
        valid_items = [item for item in v if isinstance(item, dict)]
        if len(valid_items) != len(v):
            logger.warning("Dropped malformed items from calculations_table (expected dict entries)")
        return valid_items


class StageDetail(BaseModel):
    """Single stage definition in multi-stage architecture."""

    model_config = ConfigDict(extra="forbid")

    stage_index: int = Field(..., ge=1)
    function: str = Field(..., description='Examples: "Voltage Gain", "Buffer", "Current Source", "Power Output", "Impedance Matching"')
    active_device: str = Field(..., description="Active device reference or type: Q1 (BJT), U1 (Op-Amp), M1 (MOSFET), etc.")
    input_coupling: str = Field(..., description='Coupling type: "RC Coupling", "Direct Coupling", "Transformer Coupling", "AC Coupling", "Capacitive Coupling"')
    output_coupling: str = Field(..., description='Coupling type: "RC Coupling", "Direct Coupling", "Transformer Coupling", "None", "AC Coupling"')


class StageArchitecture(BaseModel):
    """Topological stage architecture of the generated circuit."""

    model_config = ConfigDict(extra="forbid")

    topology_type: Literal["Single-stage", "Multi-stage", "Hybrid", "Push-Pull", "Complementary", "Differential"]
    stage_count: int = Field(..., ge=1, description="Number of cascaded stages")
    stages: List[StageDetail] = Field(default_factory=list, description="List of stage definitions")

    @field_validator("topology_type", mode="before")
    @classmethod
    def _fallback_topology_type(cls, v):
        import logging
        logger = logging.getLogger(__name__)
        allowed = {"Single-stage", "Multi-stage", "Hybrid", "Push-Pull", "Complementary", "Differential"}
        try:
            if isinstance(v, str) and v in allowed:
                return v
        except Exception:
            pass
        logger.warning("Invalid topology_type '%s' received; defaulting to 'Single-stage'", v)
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


class PowerAndCoupling(BaseModel):
    """Power strategy and inter-stage coupling strategy."""

    model_config = ConfigDict(extra="forbid")

    power_rail: str = Field(..., description='Power rail description, e.g. "Single (VCC-GND)", "Symmetric (VCC-VEE)", "±12V Symmetric"')
    output_strategy: str = Field(..., description='Examples: "Common Load", "Push-Pull", "Complementary Push-Pull", "Differential Pair Output"')
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
        import logging
        logger = logging.getLogger(__name__)
        allowed = {"RC Coupling", "Direct Coupling", "Transformer Coupling", "AC Coupling", "Capacitive Coupling", "None"}
        if isinstance(v, str) and v in allowed:
            return v
        logger.warning("Invalid interstage_coupling '%s' received; defaulting to 'None'", v)
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

    id: str = Field(
        ...,
        validation_alias=AliasChoices("id", "ref_id"),
        description="Reference designator, e.g. R1, Q1, C2",
    )
    type: str = Field(..., description="Component type, e.g. resistor, bjt_npn, opamp, mosfet, diode, capacitor, inductor")
    value: str = Field(..., description="Nominal value or model string, e.g. 10k, 1u, TIP41C, LM741")
    model: str = Field(default="Generic", description="Compatible model name for active devices; defaults to Generic if omitted")
    standardized_value: str = Field(..., description="Nearest E-series value, e.g. 4.7k, or exact model name")
    operating_point_check: str = Field(..., description="DC operating-point verification or operating region (e.g. 'Vce=5V, Ic=100mA' or 'Active region')")
    footprint: str = Field(default="", description="KiCad footprint identifier, e.g. Package_TO_SOT_Bipolar:TO-220-3_Vertical")
    kicad_symbol: str = Field(..., description="KiCad symbol library reference, e.g. Device:R, Device:C, Transistor_BJT:TIP41C, Amplifier_Operational:LM741")
    stage: str = Field(default="", validation_alias=AliasChoices("stage", "component_stage"), description="Semantic stage identifier, e.g. '1', '2', '3'")

    @field_validator("id")
    @classmethod
    def _normalize_ref_id(cls, value: str) -> str:
        return str(value).strip().upper()

    @property
    def ref_id(self) -> str:
        """Backward-compatible alias for older call sites."""
        return self.id


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
                raise ValueError(f"Invalid node format '{raw}'. Expected 'REF:PIN'.")
            ref, pin = node.split(":", 1)
            if not ref or not pin:
                raise ValueError(f"Invalid node format '{raw}'. Expected 'REF:PIN'.")
            normalized.append(f"{ref}:{pin}")

        if not normalized:
            return []
        return normalized


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
    def _validate_request_completeness(self) -> "CircuitIR":
        if not self.is_valid_request:
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

        if self.components and any(
            not component.id.strip()
            or not component.type.strip()
            or not component.value.strip()
            or not component.standardized_value.strip()
            or not component.operating_point_check.strip()
            or not component.kicad_symbol.strip()
            for component in self.components
        ):
            missing.append("components.fields")

        if self.nets and any(not net.net_name.strip() or not net.nodes for net in self.nets):
            missing.append("nets.fields")

        if self.nets and not any(self._normalize_net_name(net.net_name) == "0" for net in self.nets):
            missing.append('nets.0')

        if missing:
            raise ValueError(
                "Valid request requires non-null fields: " + ", ".join(missing)
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
