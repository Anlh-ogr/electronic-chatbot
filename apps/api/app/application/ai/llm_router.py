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
You are an EDA expert generating a CircuitIR JSON for Analog Amplifiers (BJT, FET, Opamp, Class A-D, Multi-stage).
Output strictly VALID JSON ONLY. No markdown, no explanations, no code fences.

╔════════════════════════════════════════════════════════════════════════════════╗
║                            CORE DESIGN INVARIANTS                              ║
╚════════════════════════════════════════════════════════════════════════════════╝

1. Node Uniqueness (CRITICAL): A physical component pin (e.g., C2:2, Q1:1) MUST belong to EXACTLY ONE net. Never connect an INPUT/OUTPUT coupling capacitor directly to a device pin using the same net. Example: `IN` net -> C1:1; `BASE` net -> C1:2, Q1:2.
2. Power Symbols: VCC, VDD, VEE, VSS, and GND must be explicit items in `components` array with type="PowerSymbol". They have 1 pin ("1") and no footprint.
3. BJT CE Gain: If Av is specified, strictly use Split Emitter (RE1, RE2). AC bypass CE across RE2 only. RC/RE1 ≈ Av.
4. Op-Amp: Always include power supply decoupling capacitors (0.1uF) close to VCC/VEE pins.
5. FET/MOSFET: Gate draws no DC current; ensure proper DC bias resistor to GND or VDD.

╔════════════════════════════════════════════════════════════════════════════════╗
║                                SCHEMA RULES                                    ║
╚════════════════════════════════════════════════════════════════════════════════╝

R1. STRICT DATA TYPES:
    - `calculations_table` MUST be a List of Objects (List of Dictionaries). NEVER output a list of strings here.
    - `architecture.stages` MUST be a List of Objects (List of Dictionaries). NEVER output a list of strings here.
    - `signal_flow.stage_links` MUST be a List of Lists of strings (e.g., `[["1", "2"], ["2", "3"]]`).
R2. Allowed topology_type: "Single-stage", "Multi-stage", "Hybrid", "Push-Pull", "Complementary", "Differential".
R3. Allowed interstage_coupling: "RC", "Direct", "Transformer", "AC", "Capacitive", "None".
R4. Netlist format: Ground MUST be "0". Power nets must be "+12V", "-12V", etc. Nodes MUST strictly use "REF:PIN" format (e.g., "R1:1"). Never put "0" or "VCC" inside the nodes array.
R5. Math AST: `formula` must be parseable math without undefined vars. Use "0" or "N/A" for unknown numeric strings. `stage_index` is integer. `calculated_value` must be a string or number.
R6. Language: `design_explanation`, `math_basis`, and `design_summary` MUST be in Vietnamese.
R7. Fail-fast: If unable to design, set is_valid_request=false and provide clarification_question.

╔════════════════════════════════════════════════════════════════════════════════╗
║                        JSON SKELETON (DO NOT COPY VALUES)                      ║
╚════════════════════════════════════════════════════════════════════════════════╝

{
  "is_valid_request": true,
  "_thought_process_": "<Short internal reasoning/calculations>",
  "analysis": {
    "circuit_name": "<Contextual name>",
    "topology_classification": "<e.g., Common Source / Differential>",
    "design_explanation": "<Vietnamese explanation>",
    "math_basis": "<Vietnamese formulas>",
    "design_summary": "<Vietnamese summary>",
    "expected_bom": ["<Part1>", "<Part2>"],
    "calculations_table": [
      {
        "target_component": "<ID>",
        "formula": "<Math>",
        "calculated_value": "4700",
        "unit": "<e.g., Ohm>",
        "vin": "0", "vout": "0", "zin": "0", "f_cutoff": "0",
        "component_stage": "1"
      }
    ]
  },
  "architecture": {
    "topology_type": "<See R2>",
    "stage_count": 1,
    "stages": [
      {
        "stage_index": 1,
        "function": "<e.g., Voltage Gain>",
        "active_device": "<ID>",
        "input_coupling": "<See R3>",
        "output_coupling": "<See R3>"
      }
    ]
  },
  "power_and_coupling": {
    "power_rail": "<e.g., Single +12V>",
    "output_strategy": "<e.g., Single-ended>",
    "interstage_coupling": "<See R3>"
  },
  "signal_flow": {
    "input_node": "IN",
    "output_node": "OUT",
    "main_chain": ["1", "2"],
    "stage_links": [
      ["1", "2"]
    ]
  },
  "components": [
    {
      "id": "R1",
      "type": "<resistor|capacitor|bjt_npn|mosfet_n|opamp|PowerSymbol>",
      "value": "10k",
      "standardized_value": "10k",
      "model": "Generic",
      "operating_point_check": "Vce=5V",
      "stage": "1",
      "footprint": "<KiCad footprint>",
      "kicad_symbol": "Device:R"
    }
  ],
  "nets": [
    {"net_name": "VCC", "nodes": ["VCC:1", "R1:1"]},
    {"net_name": "0", "nodes": ["GND:1", "R2:2"]}
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

            # If the line contains multiple comma-separated key:value pairs, parse them all.
            text = str(raw_item or "").strip()
            if ":" in text and "," in text:
                parts = [p.strip() for p in text.split(",") if p.strip()]
                any_parsed = False
                for part in parts:
                    parsed = LLMRouter._split_key_value_entry(part)
                    if parsed is None:
                        continue
                    any_parsed = True
                    key, value = parsed
                    if current and key == starter_key:
                        _flush_current()
                    current[key] = LLMRouter._coerce_scalar_value(
                        value,
                        as_number=bool(numeric_keys and key in numeric_keys),
                        as_int=bool(integer_keys and key in integer_keys),
                    )
                if any_parsed:
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

        # If we couldn't parse any objects from key:value style lines, try another
        # heuristic: the model sometimes emits a flattened sequence of tokens
        # alternating header/key names and values (e.g. ['target_component','Rc','formula','Rc/(re+RE1)',...]).
        if not objects:
            tokens: List[str] = [str(x).strip() for x in items if x is not None and str(x).strip()]
            if tokens:
                # Find indices where a starter_key occurrence repeats so we can derive header length.
                lower_tokens = [t.lower() for t in tokens]
                try:
                    starter_l = starter_key.lower()
                    indices = [i for i, t in enumerate(lower_tokens) if t == starter_l]
                except Exception:
                    indices = []

                if len(indices) >= 2 and indices[0] == 0:
                    header_len = indices[1] - indices[0]
                    if header_len > 1 and len(tokens) % header_len == 0:
                        header = tokens[0:header_len]
                        chunks = [tokens[i : i + header_len] for i in range(0, len(tokens), header_len)]
                        for chunk in chunks:
                            d: Dict[str, Any] = {}
                            for j, h in enumerate(header):
                                key = h
                                value = chunk[j]
                                d[key] = LLMRouter._coerce_scalar_value(
                                    value,
                                    as_number=bool(numeric_keys and key in numeric_keys),
                                    as_int=bool(integer_keys and key in integer_keys),
                                )
                            objects.append(d)

                # Fallback: try to interpret pairs as alternating key/value
                if not objects and len(tokens) >= 2 and len(tokens) % 2 == 0:
                    evens = tokens[0::2]
                    odds = tokens[1::2]
                    # If even-position tokens are unique keys, assume a single flattened record
                    if len(set(evens)) == len(evens) and len(evens) > 1 and all(
                        re.fullmatch(r"[A-Za-z_ ][A-Za-z0-9_ ]{0,40}", e) for e in evens
                    ):
                        d: Dict[str, Any] = {}
                        for k, v in zip(evens, odds):
                            d[k] = LLMRouter._coerce_scalar_value(
                                v,
                                as_number=bool(numeric_keys and k in numeric_keys),
                                as_int=bool(integer_keys and k in integer_keys),
                            )
                        objects.append(d)
                    else:
                        # Otherwise fall back to creating small single-key dicts so we don't lose data
                        possible = True
                        for i in range(0, min(20, len(tokens)), 2):
                            if not re.fullmatch(r"[A-Za-z_ ][A-Za-z0-9_ ]{0,40}", tokens[i]):
                                possible = False
                                break
                        if possible:
                            for i in range(0, len(tokens), 2):
                                k = tokens[i]
                                v = tokens[i + 1]
                                objects.append({k: LLMRouter._coerce_scalar_value(
                                    v,
                                    as_number=bool(numeric_keys and k in numeric_keys),
                                    as_int=bool(integer_keys and k in integer_keys),
                                )})

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
