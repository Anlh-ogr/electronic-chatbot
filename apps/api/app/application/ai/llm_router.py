# .\thesis\electronic-chatbot\apps\api\app\application\ai\llm_router.py
"""LLM Router - Bộ điều phối model cho chatbot theo 2 chế độ toàn cục.

Module này chịu trách nhiệm:
 1. Quản lý cấu hình Gemini/Vertex AI từ environment
 2. Định nghĩa LLM roles (GENERAL cho tất cả tasks)
 3. Định nghĩa LLM modes (AIR: nhanh | PRO: deep reasoning)
 4. Cung cấp get_router() singleton
 5. Routing: chatbot → (mode=AIR|PRO) → (role=GENERAL) → LLM

Nguyên tắc:
 - Singleton pattern: router dùng chung toàn hệ thống
 - Mode-first: mode quyết định chain, role chỉ để tương thích
 - Graceful degradation: nếu Vertex AI lỗi → fallback "không thể thực thi"
"""

from __future__ import annotations

import logging
import os
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

from app.application.ai.schema_utils import prepare_vertex_schema

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.application.ai.circuit_ir_schema import CircuitIR

PromptContent = Any


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()

class LLMRole(str, Enum):
    GENERAL = "general"
    # Alias tuong thich nguoc: role cu deu map ve luong chung.
    ROUTER = "general"
    EXTRACTION = "general"
    REASONING = "general"
    PRESENTATION = "general"


class LLMProvider(str, Enum):
    GEMINI = "gemini"

class LLMMode(str, Enum):
    FAST = "fast"
    THINK = "think"
    PRO = "pro"
    ULTRA = "ultra"

@dataclass
class ModelConfig:
    provider: LLMProvider
    model_id: str
    api_key: str = ""
    project_id: str = ""
    location: str = ""
    base_url: str = ""
    timeout_sec: float = 30.0
    max_tokens: int = 1024
    temperature: float = 0.0

@dataclass
class RoleConfig:
    primary: ModelConfig
    fallbacks: List[ModelConfig] = field(default_factory=list)


def _build_mode_configs() -> Dict[LLMMode, Dict[LLMRole, "RoleConfig"]]:
    project_id = (_env("Google_Cloud_Project_ID"))
    location = (
        _env("Google_Cloud_Default_Location")
        or "us-central1"
    )
    preview_location = (
        _env("Google_Cloud_Preview_Location")
        or "global"
    )
    google_key = (_env("Google_Cloud_API_Key"))

    def _first_env(names: List[str], default: str) -> str:
        for name in names:
            value = _env(name)
            if value:
                return value
        return default

    def _mode_location(mode_name: str) -> str:
        default_mode_location = preview_location if mode_name in ("Think", "Ultra") else location
        return _first_env(
            [
                f"Google_Cloud_{mode_name}_Locationx",
                f"Google_Cloud_{mode_name}_Location",
            ],
            default_mode_location,
        )

    def _first_int_env(names: List[str], default: int) -> int:
        for name in names:
            value = _env(name)
            if not value:
                continue
            try:
                return int(value)
            except ValueError:
                logger.warning("Invalid int env %s=%s, using default %s", name, value, default)
        return default

    def _first_float_env(names: List[str], default: float) -> float:
        for name in names:
            value = _env(name)
            if not value:
                continue
            try:
                return float(value)
            except ValueError:
                logger.warning("Invalid float env %s=%s, using default %s", name, value, default)
        return default

    def _google(model_envs: List[str], default: str, timeout: float, max_tokens: int, temperature: float = 0.0, model_location: str = location) -> ModelConfig:
        return ModelConfig(
            provider=LLMProvider.GEMINI,
            model_id=_first_env(model_envs, default),
            api_key=google_key,
            project_id=project_id,
            location=model_location,
            timeout_sec=timeout, max_tokens=max_tokens, temperature=temperature,
        )

    fast_timeout = _first_float_env(["Google_Cloud_Fast_Timeout_Sec"], 35.0)
    think_timeout = _first_float_env(["Google_Cloud_Think_Timeout_Sec"], 40.0)
    pro_timeout = _first_float_env(["Google_Cloud_Pro_Timeout_Sec"], 45.0)
    ultra_timeout = _first_float_env(["Google_Cloud_Ultra_Timeout_Sec"], 60.0)
    
    fast_tokens = _first_int_env(["Google_Cloud_Fast_Max_Tokens"], 8192)
    think_tokens = _first_int_env(["Google_Cloud_Think_Max_Tokens"], 12288)
    pro_tokens = _first_int_env(["Google_Cloud_Pro_Max_Tokens"], 16384)
    ultra_tokens = _first_int_env(["Google_Cloud_Ultra_Max_Tokens"], 24576)
    
    fast_model = _google(["Google_Cloud_Fast_Model"], "gemini-2.5-flash", fast_timeout, fast_tokens, model_location=_mode_location("Fast"))
    think_model = _google(["Google_Cloud_Think_Model"], "gemini-3.1-flash-lite-preview", think_timeout, think_tokens, model_location=_mode_location("Think"))
    pro_model = _google(["Google_Cloud_Pro_Model"], "gemini-2.5-pro", pro_timeout, pro_tokens, model_location=_mode_location("Pro"))
    ultra_model = _google(["Google_Cloud_Ultra_Model"], "gemini-3.1-pro-preview-customtools", ultra_timeout, ultra_tokens, model_location=_mode_location("Ultra"))
    
    fast: Dict[LLMRole, RoleConfig] = {LLMRole.GENERAL: RoleConfig(primary=fast_model, fallbacks=[think_model, pro_model, ultra_model]),}
    think: Dict[LLMRole, RoleConfig] = {LLMRole.GENERAL: RoleConfig(primary=think_model, fallbacks=[pro_model, ultra_model, fast_model]),}
    pro: Dict[LLMRole, RoleConfig] = {LLMRole.GENERAL: RoleConfig(primary=pro_model, fallbacks=[ultra_model, think_model, fast_model]),}
    ultra: Dict[LLMRole, RoleConfig] = {LLMRole.GENERAL: RoleConfig(primary=ultra_model, fallbacks=[pro_model, think_model, fast_model]),}
    
    return {
        LLMMode.FAST: fast,
        LLMMode.THINK: think,
        LLMMode.PRO: pro,
        LLMMode.ULTRA: ultra,
    }


class LLMRouter:
    """Dieu phoi model theo mode, tu dong fallback khi goi that bai."""

    def __init__(self) -> None:
        self._mode_configs = _build_mode_configs()
        mode_str = (
            _env("Google_Cloud_Default_Mode")
            or _env("DEFAULT_MODE", "fast")
        ).lower()
        mode_alias = {
            "air": LLMMode.FAST,
            "fast": LLMMode.FAST,
            "think": LLMMode.THINK,
            "pro": LLMMode.PRO,
            "ultra": LLMMode.ULTRA,
        }
        self._default_mode = mode_alias.get(mode_str, LLMMode.FAST)
        self._gemini_available = bool(
            _env("Google_Cloud_Project_ID")
            or _env("Google_Cloud_API_Key")
        )
        try:
            self._json_schema_retries = max(0, int(_env("LLM_JSON_SCHEMA_MAX_RETRIES", "2") or "2"))
        except ValueError:
            self._json_schema_retries = 2
        logger.info(
            f"LLMRouter initialized: mode={self._default_mode.value}, "
            f"gemini={'yes' if self._gemini_available else 'no'}"
        )

    # ── Public API ──
    def chat_json(self,role: LLMRole,*,mode: Optional[LLMMode] = None,system: str = "",user_content: PromptContent = "",temperature: Optional[float] = None,max_tokens: Optional[int] = None,response_model: Optional[Type[BaseModel]] = None,max_schema_retries: Optional[int] = None,) -> Optional[Dict[str, Any]]:
        config = self._get_config(role, mode)
        if not config:
            logger.error(f"Không có cấu hình cho role {role}")
            return None

        normalized_user_content = self._normalize_user_content(user_content)
        retries = self._json_schema_retries if max_schema_retries is None else max(0, max_schema_retries)

        result = self._try_call_json(
            config.primary,
            system,
            normalized_user_content,
            temperature,
            max_tokens,
            response_model=response_model,
            schema_retries=retries,
        )
        if result is not None:
            return result

        for fallback in config.fallbacks:
            logger.info(f"[{role.value}] Trying fallback ({fallback.model_id})")
            result = self._try_call_json(
                fallback,
                system,
                normalized_user_content,
                temperature,
                max_tokens,
                response_model=response_model,
                schema_retries=retries,
            )
            if result is not None:
                return result

        logger.warning(f"[{role.value}] Tất cả model lỗi, returning None")
        return None

    def chat_text(self, role: LLMRole, *, mode: Optional[LLMMode] = None, system: str = "", user_content: PromptContent = "", temperature: Optional[float] = None, max_tokens: Optional[int] = None,) -> Optional[str]:
        config = self._get_config(role, mode)
        if not config:
            logger.error(f"Không có cấu hình cho role {role}")
            return None

        normalized_user_content = self._normalize_user_content(user_content)

        result = self._try_call_text(config.primary, system, normalized_user_content, temperature, max_tokens)
        if result is not None:
            return result

        for fallback in config.fallbacks:
            logger.info(f"[{role.value}] Trying fallback ({fallback.model_id})")
            result = self._try_call_text(fallback, system, normalized_user_content, temperature, max_tokens)
            if result is not None:
                return result

        logger.warning(f"[{role.value}] Tất cả model lỗi, returning None")
        return None

    def generate_circuit_ir(self,requirements: str,*,mode: Optional[LLMMode] = None,max_schema_retries: Optional[int] = None,max_completeness_retries: int = 2,) -> Optional["CircuitIR"]:
        """Generate CircuitIR JSON via Gemini and parse directly to CircuitIR.
        
        Implements a two-level retry strategy:
        1. Schema retries (via chat_json) - fix JSON parsing errors
        2. Completeness retries - ensure all required fields are populated
        """
        from app.application.ai.circuit_ir_schema import CircuitIR

        req_text = (requirements or "").strip()
        if not req_text:
            logger.warning("generate_circuit_ir received empty requirements")
            return None

        system_prompt = """
You are an Electronic Design Automation expert specializing in Analog Amplifier Architectures (BJT, FET, Opamp, Class A/B/AB/C/D, Darlington, Multi-stage).
Your ONLY job is to generate a complete, physically-plausible CircuitIR JSON object.
Every response must be VALID JSON ONLY. No markdown, no explanations, no code fences.

╔════════════════════════════════════════════════════════════════════════════════╗
║                    MANDATORY OUTPUT STRUCTURE (ALL REQUIRED)                   ║
╚════════════════════════════════════════════════════════════════════════════════╝

When is_valid_request=true, you MUST populate ALL of these fields with actual data:
✓ analysis: (object) Circuit name, topology, design explanation, math basis, BOM, calculations
✓ architecture: (object) Topology type, stage count, list of stages with active devices
✓ power_and_coupling: (object) Power rail, output strategy, interstage coupling
✓ components: (array) Complete component list with refs, types, values, footprints
✓ nets: (array) All electrical nets with pin-level node references
✓ probe_nodes: (array) Nodes for waveform plotting, e.g. ["IN", "OUT", "VCC"]

FAILURE TO POPULATE ALL REQUIRED FIELDS WHEN is_valid_request=true IS NOT ACCEPTABLE.
If you cannot generate a complete circuit, set is_valid_request=false with clarification_question.

╔════════════════════════════════════════════════════════════════════════════════╗
║                            DESIGN RULES                                        ║
╚════════════════════════════════════════════════════════════════════════════════╝

Rule 1 - Schema Enforcement (STRICT):
- `topology_type` MUST BE EXACTLY ONE OF: "Single-stage", "Multi-stage", "Hybrid", "Push-Pull", "Complementary", "Differential". DO NOT invent other names.
- `interstage_coupling` MUST BE EXACTLY ONE OF: "RC Coupling", "Direct Coupling", "Transformer Coupling", "AC Coupling", "Capacitive Coupling", "None".
- ALL node strings inside `nets[].nodes` MUST contain a colon ":". E.g., do NOT put "0" or "VCC" inside `nodes`. Use "GND:1" or "VCC:1" if routing to a power port component.

Rule 2 - Component Specifications:
- Every component must have: id, type, value, standardized_value, operating_point_check, footprint, kicad_symbol
- CRITICAL: Resistors must have values like "10k", Capacitors like "10uF".
- kicad_symbol MUST be a valid KiCad library reference (e.g., "Device:R", "Transistor_BJT:BC547").

Rule 3 - Complete Netlist Definition:
- Ground net MUST be named exactly "0" in `net_name`.
- Power supply nets must be named "+12V", "-12V", "VCC" in `net_name`.
- INSIDE the `nodes` array, EVERY single item MUST follow `REF:PIN` format.
  - Correct: `{"net_name": "0", "nodes": ["R1:2", "C1:2"]}`
  - FATAL ERROR: `{"net_name": "0", "nodes": ["R1:2", "0"]}` (node "0" violates REF:PIN)

Rule 4 - Topology-Specific Requirements:
- For Class C: MUST include LC tank circuit tuned to fo. Bias below cutoff.
- For Class D: MUST include PWM/Gate driver IC and output LC filter.
- For Op-Amp Differential: 4 matched resistors for CMRR.

Rule 5 - Calculation Formulas (AST Parseable):
- Arrays like `stages` and `calculations_table` MUST contain valid JSON objects.
- `formula` MUST be a valid, parseable math string.
    - DO NOT use undefined variables. If you use "Vcc", it must be clear and present in the circuit context.
    - Do NOT split one object into multiple text rows, markdown rows, or pseudo-YAML lines.
    - Do NOT use empty strings for unknown numeric context; use "0" or "N/A".
    - `calculated_value` MUST be numeric.
    - `stage_index` MUST be an integer.
    - `vin`, `vout`, `zin`, `f_cutoff`, and `component_stage` MUST stay as strings.
    - Example calculation object:
        {"target_component": "Rc", "formula": "Vcc / 2", "calculated_value": 6, "unit": "V", "vin": "0", "vout": "0", "zin": "0", "f_cutoff": "0", "component_stage": "1"}

Rule 6 - Language Policy:
- analysis.design_explanation, analysis.math_basis, and analysis.design_summary MUST be written in Vietnamese.

╔════════════════════════════════════════════════════════════════════════════════╗
║                   JSON SKELETON (Topology-Agnostic Template)                   ║
╚════════════════════════════════════════════════════════════════════════════════╝
DO NOT COPY THESE VALUES. THIS IS ONLY TO SHOW THE EXACT JSON STRUCTURE AND TYPES.
REPLACE ALL PLACEHOLDERS (<...>) WITH ACTUAL DESIGN DATA BASED ON USER REQUEST.

{
  "is_valid_request": true,
  "analysis": {
    "circuit_name": "<Generate appropriate name based on request>",
    "topology_classification": "<e.g. Common Emitter / Non-Inverting / Push-Pull>",
    "design_explanation": "<Vietnamese: Giải thích nguyên lý chi tiết mạch này>",
    "math_basis": "<Vietnamese: Liệt kê các công thức tính toán liên quan>",
    "design_summary": "<Vietnamese: Tóm tắt thông số và chức năng>",
    "expected_bom": ["<Part1>", "<Part2>", "<Value1>", "<Value2>"],
    "calculations_table": [
      {
        "target_component": "<Component ID, e.g. R1>",
        "formula": "<Parseable Math, e.g. (Vcc - Vce) / Ic>",
                "calculated_value": 4700,
        "unit": "<Unit, e.g. Ohm>",
        "vin": "<Number or '0' if N/A>",
        "vout": "<Number or '0' if N/A>",
        "zin": "<Number or '0' if N/A>",
        "f_cutoff": "<Number or '0' if N/A>",
                "component_stage": "1"
      }
    ]
  },
  "architecture": {
    "topology_type": "<MUST BE: Single-stage, Multi-stage, Hybrid, Push-Pull, Complementary, or Differential>",
    "stage_count": 1,
    "stages": [
      {
                "stage_index": 1,
        "function": "<Function, e.g. Voltage Gain>",
        "active_device": "<ID of active device, e.g. Q1, U1>",
        "input_coupling": "<MUST BE: RC Coupling, Direct Coupling, Transformer Coupling, AC Coupling, Capacitive Coupling, or None>",
        "output_coupling": "<MUST BE: RC Coupling, Direct Coupling, Transformer Coupling, AC Coupling, Capacitive Coupling, or None>"
      }
    ]
  },
  "power_and_coupling": {
    "power_rail": "<e.g. Symmetric ±15V or Single +12V>",
    "output_strategy": "<e.g. Single-ended or Push-Pull>",
    "interstage_coupling": "<MUST BE: RC Coupling, Direct Coupling, Transformer Coupling, AC Coupling, Capacitive Coupling, or None>"
  },
  "components": [
    {
      "id": "<e.g. R1, Q1, U1>",
      "type": "<e.g. resistor, capacitor, bjt_npn, opamp>",
      "value": "<e.g. 10k, 100uF, BC547>",
      "standardized_value": "<e.g. 10k>",
      "model": "<e.g. Generic, BC547>",
      "operating_point_check": "<e.g. Vce=5V, Ic=1mA>",
      "footprint": "<Valid KiCad Footprint>",
      "kicad_symbol": "<Valid KiCad Symbol, e.g. Device:R>"
    }
  ],
  "nets": [
    {"net_name": "<e.g. VCC>", "nodes": ["<REF:PIN>", "<REF:PIN>"]},
    {"net_name": "0", "nodes": ["<REF:PIN>", "<REF:PIN>"]}
  ],
  "probe_nodes": ["IN", "OUT"]
}

NOW GENERATE A COMPLETE CircuitIR FOR THE USER REQUEST BELOW:
""".strip()

        for retry_attempt in range(max_completeness_retries + 1):
            request_payload = {
                "task": "circuit.ir.generate.v1",
                "requirements": req_text,
                "retry_attempt": retry_attempt,
                "output_contract": {
                    "format": "json",
                    "strict": True,
                    "schema_name": "CircuitIR",
                },
            }

            obj = self.chat_json(
                LLMRole.GENERAL,
                mode=mode,
                system=system_prompt,
                user_content=request_payload,
                response_model=CircuitIR,
                max_schema_retries=max_schema_retries,
            )
            
            if obj is None:
                logger.warning("chat_json returned None at retry attempt %d/%d", retry_attempt, max_completeness_retries)
                continue

            try:
                ir = CircuitIR.model_validate(obj)
                
                # Check completeness: if is_valid_request=True, ALL required fields must be non-null
                if ir.is_valid_request:
                    missing_fields = []
                    if ir.analysis is None:
                        missing_fields.append("analysis")
                    if ir.architecture is None:
                        missing_fields.append("architecture")
                    if ir.power_and_coupling is None:
                        missing_fields.append("power_and_coupling")
                    if ir.components is None or not ir.components:
                        missing_fields.append("components")
                    if ir.nets is None or not ir.nets:
                        missing_fields.append("nets")
                    if ir.probe_nodes is None or not ir.probe_nodes:
                        missing_fields.append("probe_nodes")
                    
                    if missing_fields:
                        logger.warning(
                            "CircuitIR incomplete at retry %d/%d: missing fields [%s]",
                            retry_attempt,
                            max_completeness_retries,
                            ", ".join(missing_fields),
                        )
                        if retry_attempt < max_completeness_retries:
                            # Retry with explicit reminder
                            continue
                        else:
                            logger.error(
                                "CircuitIR completeness validation failed after %d retries. Missing: %s",
                                max_completeness_retries + 1,
                                ", ".join(missing_fields),
                            )
                            return None
                
                logger.info("CircuitIR generated successfully (attempt %d/%d)", retry_attempt + 1, max_completeness_retries + 1)
                return ir
                
            except ValidationError as exc:
                logger.warning("CircuitIR validation failed at retry %d/%d: %s", retry_attempt, max_completeness_retries, exc)
                if retry_attempt < max_completeness_retries:
                    continue
                else:
                    return None

        logger.error("Failed to generate valid CircuitIR after %d completeness retries", max_completeness_retries + 1)
        return None

    def is_available(self, role: LLMRole, mode: Optional[LLMMode] = None) -> bool:
        config = self._get_config(role, mode)
        if not config:
            return False
        return bool(config.primary.model_id)

    def get_status(self) -> Dict[str, Any]:
        status: Dict[str, Any] = {
            "default_mode": self._default_mode.value,
            "gemini_available": self._gemini_available,
            "modes": {},
        }

        for mode, configs in self._mode_configs.items():
            status["modes"][mode.value] = {}
            for role, config in configs.items():
                status["modes"][mode.value][role.value] = {
                    "chain": [
                        {
                            "model": f"{m.provider.value}/{m.model_id}",
                            "has_key": bool(m.api_key),
                            "project_configured": bool(m.project_id),
                            "location": m.location or "asia-southeast1",
                            "tier": "primary" if i == 0 else f"fallback_{i}",
                        }
                        for i, m in enumerate([config.primary] + config.fallbacks)
                    ],
                }
        return status

    @staticmethod
    def _normalize_user_content(user_content: PromptContent) -> str:
        if isinstance(user_content, str):
            return user_content
        if isinstance(user_content, (dict, list)):
            return json.dumps(user_content, ensure_ascii=False)
        return str(user_content)

    @staticmethod
    def _normalize_json_payload(payload: Any, response_model: Optional[Type[BaseModel]]) -> Any:
        if not isinstance(payload, dict) or response_model is None:
            return payload

        if getattr(response_model, "__name__", "") != "CircuitIR":
            return payload

        normalized = dict(payload)
        analysis = normalized.get("analysis")
        if isinstance(analysis, dict):
            analysis_copy = dict(analysis)
            analysis_copy["calculations_table"] = LLMRouter._normalize_flat_object_list(
                analysis_copy.get("calculations_table"),
                starter_key="target_component",
                numeric_keys={"calculated_value"},
            )
            normalized["analysis"] = analysis_copy

        architecture = normalized.get("architecture")
        if isinstance(architecture, dict):
            architecture_copy = dict(architecture)
            architecture_copy["stages"] = LLMRouter._normalize_flat_object_list(
                architecture_copy.get("stages"),
                starter_key="stage_index",
                integer_keys={"stage_index"},
            )
            normalized["architecture"] = architecture_copy

        return normalized

    @staticmethod
    def _normalize_flat_object_list(
        items: Any,
        *,
        starter_key: str,
        numeric_keys: Optional[set[str]] = None,
        integer_keys: Optional[set[str]] = None,
    ) -> Any:
        if not isinstance(items, list) or not items:
            return items
        # Handle mixed payloads robustly: keep valid dict objects, parse key:value strings,
        # and ignore unrelated stray scalar lines instead of failing whole normalization.
        objects: List[Dict[str, Any]] = []
        current: Dict[str, Any] = {}

        def _flush_current() -> None:
            nonlocal current
            if current:
                objects.append(current)
                current = {}

        for raw_item in items:
            if isinstance(raw_item, dict):
                _flush_current()
                normalized_dict: Dict[str, Any] = {}
                for key, value in raw_item.items():
                    key_str = str(key)
                    normalized_dict[key_str] = LLMRouter._coerce_scalar_value(
                        value,
                        as_number=bool(numeric_keys and key_str in numeric_keys),
                        as_int=bool(integer_keys and key_str in integer_keys),
                    )
                objects.append(normalized_dict)
                continue

            if not isinstance(raw_item, str):
                _flush_current()
                continue

            parsed = LLMRouter._split_key_value_entry(raw_item)
            if parsed is None:
                # Stray text line (e.g. "AC Coupling") - ignore instead of poisoning the list.
                continue

            key, value = parsed
            if current and key == starter_key:
                _flush_current()

            current[key] = LLMRouter._coerce_scalar_value(
                value,
                as_number=bool(numeric_keys and key in numeric_keys),
                as_int=bool(integer_keys and key in integer_keys),
            )

        _flush_current()

        return objects if objects else items

    @staticmethod
    def _split_key_value_entry(raw_item: str) -> Optional[tuple[str, str]]:
        text = str(raw_item or "").strip()
        if not text:
            return None
        if text.startswith("- "):
            text = text[2:].strip()
        if ":" not in text:
            return None

        key, value = text.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            return None
        return key, value

    @staticmethod
    def _coerce_scalar_value(raw_value: Any, *, as_number: bool = False, as_int: bool = False) -> Any:
        text = str(raw_value or "").strip()
        if not text:
            return ""

        if as_int and re.fullmatch(r"[+-]?\d+", text):
            try:
                return int(text)
            except ValueError:
                return text

        if as_number and re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text):
            try:
                return float(text)
            except ValueError:
                return text

        return text


    # ── Internal call helpers ──
    def _get_config(self, role: LLMRole, mode: Optional[LLMMode]) -> Optional[RoleConfig]:
        resolved_mode = mode if mode is not None else self._default_mode
        configs = self._mode_configs.get(resolved_mode, {})
        return configs.get(role) or configs.get(LLMRole.GENERAL)

    def _try_call_json(
        self,
        model: ModelConfig,
        system: str,
        user_content: str,
        temperature: Optional[float],
        max_tokens: Optional[int],
        response_model: Optional[Type[BaseModel]],
        schema_retries: int,
    ) -> Optional[Dict[str, Any]]:
        temp = temperature if temperature is not None else model.temperature
        tokens = max_tokens if max_tokens is not None else model.max_tokens
        response_schema = (
            prepare_vertex_schema(
                response_model.model_json_schema(),
                debug_label=response_model.__name__,
            )
            if response_model is not None
            else None
        )

        attempts = schema_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                obj = self._gemini_json(
                    model,
                    system,
                    user_content,
                    temp,
                    tokens,
                    response_schema=response_schema,
                )
            except Exception as e:
                logger.warning(
                    "[%s/%s] JSON call failed (attempt %s/%s): %s",
                    model.provider.value,
                    model.model_id,
                    attempt,
                    attempts,
                    e,
                )
                continue

            if response_model is None:
                return obj

            try:
                validated = response_model.model_validate(obj)
                return validated.model_dump(mode="json")
            except ValidationError as e:
                normalized_obj = self._normalize_json_payload(obj, response_model)
                if normalized_obj is not obj:
                    try:
                        validated = response_model.model_validate(normalized_obj)
                        logger.info(
                            "[%s/%s] JSON payload normalized successfully on attempt %s/%s",
                            model.provider.value,
                            model.model_id,
                            attempt,
                            attempts,
                        )
                        return validated.model_dump(mode="json")
                    except ValidationError as normalized_error:
                        logger.warning(
                            "[%s/%s] JSON schema validation failed after normalization (attempt %s/%s): %s",
                            model.provider.value,
                            model.model_id,
                            attempt,
                            attempts,
                            normalized_error,
                        )
                logger.warning(
                    "[%s/%s] JSON schema validation failed (attempt %s/%s): %s",
                    model.provider.value,
                    model.model_id,
                    attempt,
                    attempts,
                    e,
                )

        return None

    def _try_call_text(self, model: ModelConfig, system: str, user_content: str,
                             temperature: Optional[float], max_tokens: Optional[int],) -> Optional[str]:
        temp = temperature if temperature is not None else model.temperature
        tokens = max_tokens if max_tokens is not None else model.max_tokens
        
        try:
            return self._gemini_text(model, system, user_content, temp, tokens)
        except Exception as e:
            logger.warning(f"[{model.provider.value}/{model.model_id}] Text failed: {e}")
            return None

    
    # ── Google Cloud calls ──
    def _gemini_json(
        self,
        model: ModelConfig,
        system: str,
        user_content: str,
        temperature: float,
        max_tokens: int,
        *,
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from app.application.ai.googlecloud_client import GoogleCloudClient, GoogleCloudMessage
        
        client = GoogleCloudClient(api_key=model.api_key,
                                   model=model.model_id,
                                   timeout_sec=model.timeout_sec,
                                   project_id=model.project_id,
                                   location=model.location,)
        
        messages = [GoogleCloudMessage(role="user", content=user_content)]
        
        return client.chat_json(
            messages, system_instruction=system,
            temperature=temperature, max_tokens=max_tokens,
            response_schema=response_schema,
        )

    def _gemini_text(self, model: ModelConfig, system: str, user_content: str, temperature: float, max_tokens: int,) -> str:
        from app.application.ai.googlecloud_client import GoogleCloudClient, GoogleCloudMessage
        
        client = GoogleCloudClient(api_key=model.api_key,
                                   model=model.model_id,
                                   timeout_sec=model.timeout_sec,
                                   project_id=model.project_id,
                                   location=model.location,)
        
        messages = [GoogleCloudMessage(role="user", content=user_content)]
        
        return client.chat_text(
            messages, system_instruction=system,
            temperature=temperature, max_tokens=max_tokens,
        )


# Singleton router
_router: Optional[LLMRouter] = None

def get_router() -> LLMRouter:
    """Tra ve singleton LLMRouter."""

    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
