from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictSchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMContractRequest(StrictSchemaModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    sv: str = Field(default="req.v1")
    tk: str = Field(..., min_length=1)
    in_: Dict[str, Any] = Field(default_factory=dict, alias="in")
    of: str = Field(default="json")


class IntentCode(str, Enum):
    CRT = "CRT"
    MOD = "MOD"
    VAL = "VAL"
    EXP = "EXP"


class TopologyCode(str, Enum):
    CE = "CE"
    CB = "CB"
    CC = "CC"
    CS = "CS"
    CD = "CD"
    CG = "CG"
    INV = "INV"
    NON = "NON"
    DIF = "DIF"
    INA = "INA"
    CLA = "CLA"
    CLAB = "CLAB"
    CLB = "CLB"
    CLC = "CLC"
    CLD = "CLD"
    DAR = "DAR"
    MST = "MST"
    UNK = "UNK"


TOPOLOGY_ALIASES = {
    "CI": "INV",
    "NI": "NON",
    "DIFF": "DIF",
}


def normalize_topology(value: str) -> str:
    return TOPOLOGY_ALIASES.get((value or "").strip().upper(), (value or "").strip().upper())


class InputModeCode(str, Enum):
    SE = "SE"
    DI = "DI"


class SupplyModeCode(str, Enum):
    AUTO = "AUTO"
    SGL = "SGL"
    DUL = "DUL"


class DevicePrefCode(str, Enum):
    AUTO = "AUTO"
    BJT = "BJT"
    MOS = "MOS"
    OPA = "OPA"


class TargetScopeCode(str, Enum):
    ALL = "ALL"
    IN = "IN"
    OUT = "OUT"
    BIAS = "BIAS"
    FB = "FB"


class ExplainDetailCode(str, Enum):
    B = "B"
    D = "D"


class EditActionCode(str, Enum):
    ADD = "ADD"
    RMV = "RMV"
    REP = "REP"
    CHV = "CHV"
    CHC = "CHC"


class NLUChannelInputV1(StrictSchemaModel):
    av: Optional[float] = None
    fq: Optional[float] = None


class NLUVoltageRangeV1(StrictSchemaModel):
    mn: Optional[float] = None
    mx: Optional[float] = None


class NLUEditOperationV1(StrictSchemaModel):
    a: EditActionCode
    t: str = ""
    p: Dict[str, Any] = Field(default_factory=dict)


class NLUIntentOutputV1(StrictSchemaModel):
    sv: str = Field(default="nlu.v1")
    it: IntentCode
    tp: TopologyCode
    gn: Optional[float] = None
    vc: Optional[float] = None
    fq: Optional[float] = None
    ic: int = Field(default=1, ge=1, le=32)
    ci: Dict[str, NLUChannelInputV1] = Field(default_factory=dict)
    vr: NLUVoltageRangeV1 = Field(default_factory=NLUVoltageRangeV1)
    im: InputModeCode = InputModeCode.SE
    hc: bool = False
    ob: bool = False
    po: bool = False
    sm: SupplyModeCode = SupplyModeCode.AUTO
    dp: DevicePrefCode = DevicePrefCode.AUTO
    xr: List[str] = Field(default_factory=list)
    eo: List[NLUEditOperationV1] = Field(default_factory=list)
    ts: TargetScopeCode = TargetScopeCode.ALL
    hcst: Dict[str, Any] = Field(default_factory=dict)
    sp: List[str] = Field(default_factory=list)
    ra: List[IntentCode] = Field(default_factory=list)
    ed: ExplainDetailCode = ExplainDetailCode.B
    ef: List[str] = Field(default_factory=list)
    cf: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("tp", mode="before")
    @classmethod
    def normalize_tp(cls, value: Any) -> str:
        if value is None:
            return "UNK"
        return normalize_topology(str(value))


class DomainCheckOutputV1(StrictSchemaModel):
    sv: str = Field(default="domain.v1")
    ok: bool


class ComponentProposalOutputV1(StrictSchemaModel):
    sv: str = Field(default="cmp.v1")
    tp: TopologyCode = TopologyCode.CE
    r1: float = Field(ge=1000.0)
    r2: float = Field(ge=1000.0)
    rc: float = Field(ge=100.0)
    re: float = Field(ge=0.0)
    v: float = Field(default=12.0, gt=0.0)
    b: float = Field(default=100.0, ge=50.0, le=300.0)


_INTENT_CODE_TO_NAME = {
    IntentCode.CRT: "create",
    IntentCode.MOD: "modify",
    IntentCode.VAL: "validate",
    IntentCode.EXP: "explain",
}
_INTENT_NAME_TO_CODE = {value: key for key, value in _INTENT_CODE_TO_NAME.items()}


_TOPOLOGY_CODE_TO_NAME = {
    TopologyCode.CE: "common_emitter",
    TopologyCode.CB: "common_base",
    TopologyCode.CC: "common_collector",
    TopologyCode.CS: "common_source",
    TopologyCode.CD: "common_drain",
    TopologyCode.CG: "common_gate",
    TopologyCode.INV: "inverting",
    TopologyCode.NON: "non_inverting",
    TopologyCode.DIF: "differential",
    TopologyCode.INA: "instrumentation",
    TopologyCode.CLA: "class_a",
    TopologyCode.CLAB: "class_ab",
    TopologyCode.CLB: "class_b",
    TopologyCode.CLC: "class_c",
    TopologyCode.CLD: "class_d",
    TopologyCode.DAR: "darlington",
    TopologyCode.MST: "multi_stage",
    TopologyCode.UNK: "unknown",
}
_TOPOLOGY_NAME_TO_CODE = {value: key for key, value in _TOPOLOGY_CODE_TO_NAME.items()}
_TOPOLOGY_NAME_TO_CODE.update(
    {
        "ci": TopologyCode.INV,
        "ni": TopologyCode.NON,
        "diff": TopologyCode.DIF,
    }
)


_SUPPLY_CODE_TO_NAME = {
    SupplyModeCode.AUTO: "auto",
    SupplyModeCode.SGL: "single_supply",
    SupplyModeCode.DUL: "dual_supply",
}
_SUPPLY_NAME_TO_CODE = {value: key for key, value in _SUPPLY_CODE_TO_NAME.items()}


_DEVICE_CODE_TO_NAME = {
    DevicePrefCode.AUTO: "auto",
    DevicePrefCode.BJT: "bjt",
    DevicePrefCode.MOS: "mosfet",
    DevicePrefCode.OPA: "opamp",
}
_DEVICE_NAME_TO_CODE = {value: key for key, value in _DEVICE_CODE_TO_NAME.items()}


_SCOPE_CODE_TO_NAME = {
    TargetScopeCode.ALL: "entire_circuit",
    TargetScopeCode.IN: "input_stage",
    TargetScopeCode.OUT: "output_stage",
    TargetScopeCode.BIAS: "bias_network",
    TargetScopeCode.FB: "feedback_loop",
}
_SCOPE_NAME_TO_CODE = {value: key for key, value in _SCOPE_CODE_TO_NAME.items()}


_EDIT_CODE_TO_NAME = {
    EditActionCode.ADD: "add_component",
    EditActionCode.RMV: "remove_component",
    EditActionCode.REP: "replace_component",
    EditActionCode.CHV: "change_value",
    EditActionCode.CHC: "change_connection",
}
_EDIT_NAME_TO_CODE = {value: key for key, value in _EDIT_CODE_TO_NAME.items()}


def intent_code_to_name(code: IntentCode) -> str:
    return _INTENT_CODE_TO_NAME.get(code, "create")


def intent_name_to_code(name: str) -> IntentCode:
    return _INTENT_NAME_TO_CODE.get((name or "").strip().lower(), IntentCode.CRT)


def topology_code_to_name(code: TopologyCode) -> str:
    return _TOPOLOGY_CODE_TO_NAME.get(code, "unknown")


def topology_name_to_code(name: str) -> TopologyCode:
    return _TOPOLOGY_NAME_TO_CODE.get((name or "").strip().lower(), TopologyCode.UNK)


def supply_code_to_name(code: SupplyModeCode) -> str:
    return _SUPPLY_CODE_TO_NAME.get(code, "auto")


def supply_name_to_code(name: str) -> SupplyModeCode:
    return _SUPPLY_NAME_TO_CODE.get((name or "").strip().lower(), SupplyModeCode.AUTO)


def device_code_to_name(code: DevicePrefCode) -> str:
    return _DEVICE_CODE_TO_NAME.get(code, "auto")


def device_name_to_code(name: str) -> DevicePrefCode:
    return _DEVICE_NAME_TO_CODE.get((name or "").strip().lower(), DevicePrefCode.AUTO)


def scope_code_to_name(code: TargetScopeCode) -> str:
    return _SCOPE_CODE_TO_NAME.get(code, "entire_circuit")


def scope_name_to_code(name: str) -> TargetScopeCode:
    return _SCOPE_NAME_TO_CODE.get((name or "").strip().lower(), TargetScopeCode.ALL)


def edit_code_to_name(code: EditActionCode) -> str:
    return _EDIT_CODE_TO_NAME.get(code, "change_value")


def edit_name_to_code(name: str) -> EditActionCode:
    return _EDIT_NAME_TO_CODE.get((name or "").strip().lower(), EditActionCode.CHV)


def build_llm_payload(task: str, input_data: Dict[str, Any], output_format: str) -> Dict[str, Any]:
    return {
        "sv": "req.v1",
        "tk": task,
        "in": input_data,
        "of": output_format,
    }
