"""Pydantic V2 schema for LLM-generated Circuit IR.

This schema is intentionally strict to keep LLM output deterministic and
machine-parseable before downstream EDA validation/compilation stages.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Calculation(BaseModel):
    """Single calculated design value produced by LLM."""

    model_config = ConfigDict(extra="forbid")

    target_component: str = Field(..., min_length=1, description="Target component reference, e.g. R1")
    formula: str = Field(..., min_length=1, description="Formula text used to derive value")
    calculated_value: float = Field(..., description="Computed numeric value")
    unit: str = Field(..., min_length=1, description="Engineering unit, e.g. ohm, V, A")
    vin: Optional[Union[float, str]] = Field(default=None, description="Input condition context, if applicable")
    vout: Optional[Union[float, str]] = Field(default=None, description="Output target/result context, if applicable")
    zin: Optional[Union[float, str]] = Field(default=None, description="Input impedance context, if applicable")
    f_cutoff: Optional[Union[float, str]] = Field(default=None, description="Cutoff frequency context, if applicable")


class AnalysisAndMath(BaseModel):
    """Structured engineering rationale and design math summary."""

    model_config = ConfigDict(extra="forbid")

    circuit_name: str = Field(..., min_length=1)
    topology_classification: str = Field(..., min_length=1)
    design_explanation: str = Field(..., min_length=1, description="Why this topology is selected and its advantages")
    math_basis: str = Field(..., min_length=1, description="Core formulas and assumptions used")
    expected_bom: List[str] = Field(default_factory=list)
    calculations_table: List[Calculation] = Field(default_factory=list)


class StageDetail(BaseModel):
    """Single stage definition in multi-stage architecture."""

    model_config = ConfigDict(extra="forbid")

    stage_index: int = Field(..., ge=1)
    function: str = Field(..., min_length=1, description='Examples: "Voltage Gain", "Buffer"')
    active_device: str = Field(..., min_length=1)
    input_coupling: str = Field(..., min_length=1)
    output_coupling: str = Field(..., min_length=1)


class StageArchitecture(BaseModel):
    """Topological stage architecture of the generated circuit."""

    model_config = ConfigDict(extra="forbid")

    topology_type: Literal["Single-stage", "Multi-stage", "Hybrid"]
    stage_count: int = Field(..., ge=1)
    stages: List[StageDetail] = Field(default_factory=list)

    @field_validator("stages")
    @classmethod
    def _stages_not_empty(cls, value: List[StageDetail]) -> List[StageDetail]:
        if not value:
            raise ValueError("stages must contain at least one stage")
        return value


class PowerAndCoupling(BaseModel):
    """Power strategy and inter-stage coupling strategy."""

    model_config = ConfigDict(extra="forbid")

    power_rail: Literal["Single (VCC-GND)", "Symmetric (VCC-VEE)"]
    output_strategy: str = Field(..., min_length=1)
    interstage_coupling: Literal[
        "RC Coupling",
        "Direct Coupling",
        "Transformer Coupling",
        "None",
    ]


class Component(BaseModel):
    """Physical/logical component entry in IR."""

    model_config = ConfigDict(extra="forbid")

    ref_id: str = Field(..., min_length=1, description="Reference designator, e.g. R1, Q1, C2")
    type: str = Field(..., min_length=1, description="Component type, e.g. resistor, bjt_npn")
    value: Union[float, int, str] = Field(..., description="Nominal value or model string")
    standardized_value: str = Field(..., min_length=1, description="Nearest E-series value, e.g. 4.7k")
    operating_point_check: str = Field(..., min_length=1, description="DC operating-point verification")
    footprint: Optional[str] = Field(default=None, description="KiCad footprint identifier")

    @field_validator("ref_id")
    @classmethod
    def _normalize_ref_id(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("ref_id must not be empty")
        return normalized


class Net(BaseModel):
    """Electrical net with pin-level node references."""

    model_config = ConfigDict(extra="forbid")

    net_name: str = Field(..., min_length=1, description='Net name, use "0" for ground')
    nodes: List[str] = Field(default_factory=list, description='Node refs like "R1:1", "Q1:B"')

    @field_validator("net_name")
    @classmethod
    def _normalize_net_name(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("net_name must not be empty")
        if normalized.lower() in {"gnd", "ground", "vss"}:
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
            raise ValueError("nodes must contain at least one node")
        return normalized


class CircuitIR(BaseModel):
    """Top-level Intermediate Representation generated by LLM."""

    model_config = ConfigDict(extra="forbid")

    is_valid_request: bool = Field(
        default=True,
        description="Set to FALSE if user input is missing critical I/O parameters.",
    )
    clarification_question: Optional[str] = Field(
        default=None,
        description="If is_valid_request is False, populate this with the clarification question.",
    )
    analysis: Optional[AnalysisAndMath] = Field(default=None)
    architecture: Optional[StageArchitecture] = Field(default=None)
    power_and_coupling: Optional[PowerAndCoupling] = Field(default=None)
    components: Optional[List[Component]] = Field(default=None)
    nets: Optional[List[Net]] = Field(default=None)
    probe_nodes: Optional[List[str]] = Field(
        default=None,
        description='Nodes for ngspice plotting, e.g. ["IN", "OUT"]',
    )

    @field_validator("components")
    @classmethod
    def _components_not_empty(cls, value: Optional[List[Component]]) -> Optional[List[Component]]:
        if value is not None and not value:
            raise ValueError("components must not be empty")
        return value

    @field_validator("nets")
    @classmethod
    def _nets_not_empty(cls, value: Optional[List[Net]]) -> Optional[List[Net]]:
        if value is not None and not value:
            raise ValueError("nets must not be empty")
        return value

    @field_validator("nets")
    @classmethod
    def _ground_net_required(cls, value: Optional[List[Net]]) -> Optional[List[Net]]:
        if value is not None and value and not any(net.net_name == "0" for net in value):
            raise ValueError('Ground net must be explicitly named "0"')
        return value

    @field_validator("probe_nodes")
    @classmethod
    def _validate_probe_nodes(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        normalized: List[str] = []
        for item in value:
            node = str(item).strip()
            if not node:
                continue
            normalized.append("0" if node.lower() in {"0", "gnd", "ground"} else node.upper())
        if not normalized:
            raise ValueError("probe_nodes must contain at least one node")
        return normalized

    @model_validator(mode="after")
    def _validate_request_completeness(self) -> "CircuitIR":
        if not self.is_valid_request:
            return self

        missing: List[str] = []
        if self.analysis is None:
            missing.append("analysis")
        if self.architecture is None:
            missing.append("architecture")
        if self.power_and_coupling is None:
            missing.append("power_and_coupling")
        if self.components is None:
            missing.append("components")
        if self.nets is None:
            missing.append("nets")
        if self.probe_nodes is None:
            missing.append("probe_nodes")

        if missing:
            raise ValueError(
                "Valid request requires non-null fields: " + ", ".join(missing)
            )

        return self

    @property
    def metadata(self) -> Dict[str, Any]:
        """Backward-compatible metadata projection for existing services."""
        if self.analysis is None or self.architecture is None or self.power_and_coupling is None:
            return {}
        return {
            "circuit_name": self.analysis.circuit_name,
            "topology_classification": self.analysis.topology_classification,
            "topology_type": self.architecture.topology_type,
            "stage_count": self.architecture.stage_count,
            "power_rail": self.power_and_coupling.power_rail,
            "output_strategy": self.power_and_coupling.output_strategy,
            "interstage_coupling": self.power_and_coupling.interstage_coupling,
        }

    @property
    def calculations(self) -> List[Calculation]:
        """Backward-compatible access to legacy calculations list."""
        if self.analysis is None:
            return []
        return self.analysis.calculations_table
