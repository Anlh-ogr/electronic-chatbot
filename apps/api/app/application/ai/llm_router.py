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
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, Union, Tuple
from app.application.ai.circuit_ir_schema import CircuitIR
from pydantic import BaseModel, ValidationError

from app.application.ai.schema_utils import prepare_vertex_schema

response_schema = prepare_vertex_schema(
    CircuitIR.model_json_schema(),
    debug_label="CircuitIR"
)


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.application.ai.circuit_ir_schema import CircuitIR

PromptContent = Any

_VERTEX_OUTPUT_TOKEN_CAP = 65535

def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()

def _cap_vertex_output_tokens(value: Optional[int]) -> int:
    try:
        requested = int(value) if value is not None else _VERTEX_OUTPUT_TOKEN_CAP
    except (TypeError, ValueError):
        requested = _VERTEX_OUTPUT_TOKEN_CAP
    if requested <= 0:
        requested = _VERTEX_OUTPUT_TOKEN_CAP
    return requested

# LLM role: quan ly vai tro cua model (vd: general, reasoning, extraction)
class LLMRole(str, Enum):
    GENERAL = "general"
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
    timeout_sec: float = 300.0
    max_tokens: int = _VERTEX_OUTPUT_TOKEN_CAP
    temperature: float = 0.0

@dataclass
class RoleConfig:
    primary: ModelConfig
    fallbacks: List[ModelConfig] = field(default_factory=list)


def _build_mode_configs() -> Dict[LLMMode, Dict[LLMRole, "RoleConfig"]]:
    project_id = (_env("Google_Cloud_Project_ID"))
    location = _env("Google_Cloud_Default_Location") or "asia-southeast1"
    us_location = _env("Google_Cloud_US_Location") or "us-central1"
    google_key = (_env("Google_Cloud_API_Key"))

    def _first_env(names: List[str], default: str) -> str:
        for name in names:
            value = _env(name)
            if value:
                return value
        return default

    def _mode_location(mode_name: str) -> str:
        SAFE_DEFAULTS = {
            "Fast": "asia-southeast1",
            "Think": "asia-southeast1",
            "Pro": us_location,
            "Ultra": us_location,
            "Fast_Fallback": "asia-southeast1",
            "Think_Fallback": us_location,
            "Pro_Fallback": "asia-southeast1",
            "Ultra_Fallback": us_location,
        }
        return _first_env(
            [f"Google_Cloud_{mode_name}_Location"],
            SAFE_DEFAULTS.get(mode_name, location),
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

    def _google(
        model_envs: List[str],
        default: str,
        timeout: float,
        max_tokens: int,
        temperature: float = 0.0,
        model_location: str = location,
    ) -> ModelConfig:
        return ModelConfig(
            provider=LLMProvider.GEMINI,
            model_id=_first_env(model_envs, default),
            api_key=google_key,
            project_id=project_id,
            location=model_location,
            timeout_sec=timeout,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def _mode_google(mode_name: str, *, default_model: str, default_timeout: float) -> ModelConfig:
        return _google(
            [f"Google_Cloud_{mode_name}_Model"],
            default_model,
            _first_float_env([f"Google_Cloud_{mode_name}_Timeout_Sec"], default_timeout),
            _first_int_env([f"Google_Cloud_{mode_name}_Max_Tokens"], _VERTEX_OUTPUT_TOKEN_CAP),
            model_location=_mode_location(mode_name),
        )

    def _fallback_google(mode_name: str, *, default_model: str, default_timeout: float) -> ModelConfig:
        prefix = f"{mode_name}_Fallback"
        return _google(
            [f"Google_Cloud_{prefix}_Model"],
            default_model,
            _first_float_env(
                [f"Google_Cloud_{prefix}_Timeout_Sec", f"Google_Cloud_{mode_name}_Timeout_Sec"],
                default_timeout,
            ),
            _first_int_env(
                [f"Google_Cloud_{prefix}_Max_Tokens", f"Google_Cloud_{mode_name}_Max_Tokens"],
                _VERTEX_OUTPUT_TOKEN_CAP,
            ),
            model_location=_mode_location(prefix),
        )

    fast_model = _mode_google("Fast", default_model="gemini-2.5-flash", default_timeout=120.0)
    think_model = _mode_google("Think", default_model="gemini-2.5-flash", default_timeout=150.0)
    pro_model = _mode_google("Pro", default_model="gemini-2.5-pro", default_timeout=240.0)
    ultra_model = _mode_google("Ultra", default_model="gemini-2.5-pro", default_timeout=300.0)

    fast_fallback = _fallback_google("Fast", default_model="gemini-2.5-flash", default_timeout=120.0)
    think_fallback = _fallback_google("Think", default_model="gemini-2.5-pro", default_timeout=150.0)
    pro_fallback = _fallback_google("Pro", default_model="gemini-2.5-flash", default_timeout=240.0)
    ultra_fallback = _fallback_google("Ultra", default_model="gemini-2.5-pro", default_timeout=300.0)

    def _fallback_chain(*candidates: ModelConfig) -> List[ModelConfig]:
        """Giữ thứ tự env; bỏ trùng lặp liên tiếp (cho phép retry cùng model/region)."""
        chain: List[ModelConfig] = []
        seen: set[tuple[str, str]] = set()
        for cfg in candidates:
            key = (cfg.model_id, cfg.location)
            if key in seen:
                continue
            seen.add(key)
            chain.append(cfg)
        return chain

    fast: Dict[LLMRole, RoleConfig] = {
        LLMRole.GENERAL: RoleConfig(
            primary=fast_model,
            fallbacks=_fallback_chain(fast_fallback),
        ),
    }
    think: Dict[LLMRole, RoleConfig] = {
        LLMRole.GENERAL: RoleConfig(
            primary=think_model,
            fallbacks=_fallback_chain(think_fallback),
        ),
    }
    pro: Dict[LLMRole, RoleConfig] = {
        LLMRole.GENERAL: RoleConfig(
            primary=pro_model,
            fallbacks=_fallback_chain(pro_fallback),
        ),
    }
    ultra: Dict[LLMRole, RoleConfig] = {
        LLMRole.GENERAL: RoleConfig(
            primary=ultra_model,
            fallbacks=_fallback_chain(ultra_fallback),
        ),
    }
    
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
            self._json_schema_retries = max(0, int(_env("LLM_JSON_SCHEMA_MAX_RETRIES", "1") or "1"))
        except ValueError:
            self._json_schema_retries = 2
        logger.info(
            f"LLMRouter initialized: mode={self._default_mode.value}, "
            f"gemini={'yes' if self._gemini_available else 'no'}"
        )

    # ── Public API ──
    
    # chon model - gui request llm - validate Json - retry schema - fallback model (model not working)
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

    def generate_circuit_ir(self, requirements: str, *, mode: Optional[LLMMode] = None, max_schema_retries: Optional[int] = None, max_completeness_retries: int = 2) -> Optional[Union["CircuitIR", Dict[str, Any]]]:
        """Generate CircuitIR JSON via Gemini and parse directly to CircuitIR.

        Implements a two-level retry strategy:
        1. Schema retries (via chat_json) - fix JSON parsing errors
        2. Validation retries - fix schema/physics failures

        Returns a structured error dict on final validation failure.
        """
        from app.application.ai.circuit_ir_schema import CircuitIR

        req_text = self._augment_requirements_with_defaults(requirements)
        if not req_text:
            logger.warning("generate_circuit_ir received empty requirements")
            return None

        system_prompt = """
            You are an EDA expert generating CircuitIR JSON for amplifier designs.
            Focus only on BJT NPN and op-amp circuits.

            Output STRICTLY VALID JSON ONLY.
            No markdown.
            No explanations.
            No code fences.

            LOCALIZATION + FORMULA POLICY (applies to ALL human-readable string fields):
            - All descriptive/explanatory fields written for the end-user MUST be in Vietnamese (tiếng Việt). This includes (but is not limited to):
              `analysis.circuit_name`, `analysis.topology_classification`, `analysis.design_summary`,
              `analysis.design_explanation`, `analysis.math_basis`, `analysis.notes`,
              `power_and_coupling.*` description strings, and any `notes`/`message`/`reason` text.
            - Keep ALL identifiers (component refs like R1, Q1, U1, net names like VCC, GND, OUT, model strings like LM358/QNPN, units like V/A/Hz/Ω/F/H, JSON keys, enum strings) in their original ASCII form. DO NOT translate identifiers, units, or enums.
            - Any mathematical formula appearing inside descriptive fields MUST be written in KaTeX-compatible LaTeX:
                • inline: `$A_v = 1 + R_f/R_g$`
                • display: `$$A_v = 1 + \\dfrac{R_f}{R_g}$$`
              Do NOT use Markdown code fences or plain `=`/`*`/`/` for formulas in description text. Always use `$...$` (or `$$...$$`) delimiters so KaTeX auto-render can typeset them.
            - Numeric values inside `calculated_values` stay as plain JSON numbers (no LaTeX, no units in the value itself).

            SUPPORTED FOCUS:
            - BJT NPN: common_emitter, common_collector, common_base
            - Op-Amp: inverting, non_inverting, differential

            INFERENCE POLICY:
            - Do NOT default to common_emitter when topology is unspecified.
            - Infer topology only from explicit names or strong cues (e.g. "emitter follower" -> common_collector, "inverting op-amp" -> inverting).
            - If topology is ambiguous after reading the request, set is_valid_request=false and ask which supported topology is intended.
            - Supported BJT: common_emitter, common_collector, common_base. Supported op-amp: inverting, non_inverting, differential.
            - Only return is_valid_request=false when the request is not an amplifier request, or when topology/device cannot be determined.

            RULES:
            1. Every circuit must include explicit power_supply and ground.
            2. Ground net name must be "0".
            3. Use REF:PIN format only.
            4. Required connectors: IN and OUT (signal nets may be named IN_SIG / OUT_SIG only if those net_name values match signal_flow and probe_nodes).
            5. Pin naming:
            - BJT: Q1:B, Q1:C, Q1:E
            - OpAmp: U1:+, U1:-, U1:OUT, U1:VS+, U1:VS-
            - Resistor: R1:1, R1:2
            - Capacitor: C1:1, C1:2
            - Power rail symbols (type power_supply): ONLY pin "1" exists in IR. Connect VCC:1 (or VDD:1) to the positive rail net (e.g. VCC). NEVER emit VCC:2, VDD:2, or any second pin on power_supply — the negative reference is implicit via the separate ground net "0" and/or GND:1.
            - Ground symbol (type ground): ONLY GND:1 on net "0".
            - Connector: IN:1, OUT:1
            - probe_nodes must repeat those same net_name spellings for signals, rail, and "0" (see rule 15).
            6. Allowed component types only:
            - bjt_npn
            - opamp_ic
            - resistor
            - capacitor
            - power_supply
            - ground
            - connector
            Do not introduce MOSFET, class-D, Darlington, or other non-BJT/non-op-amp device families.
            7. Allowed roles only:
            - bias_top
            - bias_bottom
            - load
            - degeneration
            - bypass_cap
            - coupling_in
            - coupling_out
            - feedback
            - supply
            - ground
            - unknown_passive
            8. All values must include units.
            9. Do not create floating nets, duplicate nets, or unused components.
            10. architecture.topology_type must be "Single-stage".
            11. architecture.stage_count must be 1.
            12. For common_emitter with gain requirement, use RE1 + RE2 and bypass CE across RE2 only.
            13. For op-amp circuits, include 0.1uF decoupling from VS+ to 0 and from VS- to 0 when dual supply is used.
            14. Keep output compact.
            15. signal_flow.input_node and signal_flow.output_node MUST equal the actual small-signal net_name strings in nets[] and MUST each appear in probe_nodes (exact SPICE node spellings).
            16. Each physical pin must belong to exactly one net. Never assign the same component pin to two different nets.
            17. For BJT common-emitter AC coupling capacitors, use these exact pin/net assignments:
            - CIN:1 → IN_SIG (external input)
            - CIN:2 → BASE_Q1 (connects to Q1:B / BJT base node)
            - COUT:1 → COLLECTOR_Q1 (connects to Q1:C / BJT collector node)
            - COUT:2 → OUT_SIG (external output)
            Never put CIN:1, CIN:2, COUT:1, or COUT:2 on more than one net.
            18. For BJT common_collector (emitter follower):
            - Q1:C MUST connect directly to VCC. DO NOT place any collector load resistor (no RC) between Q1:C and VCC.
            - Q1:B → BASE_Q1 (shared by RB1:2 and RB2:1 and CIN:2).
            - Q1:E → EMITTER_Q1 (shared by RE:1 and COUT:1).
            - COUT:1 → EMITTER_Q1, COUT:2 → OUT_SIG. Output is taken from the emitter; voltage gain ≈ 1.
            19. For BJT common_base:
            - Q1:E → EMITTER_Q1 (shared by CIN:2 and RE:1). Input is injected at the emitter via CIN.
            - Q1:B → BASE_Q1 (shared by RB1:2 and RB2:1). MANDATORY base-bypass capacitor: CB:1 → BASE_Q1, CB:2 → 0. Without CB, the stage is NOT common-base.
            - Q1:C → COLLECTOR_Q1 (shared by RC:2 and COUT:1). Output is taken from the collector.
            - CIN:1 → IN_SIG, CIN:2 → EMITTER_Q1. COUT:1 → COLLECTOR_Q1, COUT:2 → OUT_SIG.
            20. For opamp_inverting:
            - U1:+ → 0 (non-inverting input tied directly to ground reference).
            - RIN:1 → IN_SIG, RIN:2 → U1_INV_IN.
            - RF:1 → OUT_SIG (feedback path FROM output), RF:2 → U1_INV_IN (summing junction).
            - U1:- → U1_INV_IN. U1:OUT → OUT_SIG.
            - Av = -RF/RIN. The signal path is DC-coupled — DO NOT add CIN/COUT AC coupling caps for op-amp circuits.
            21. For opamp_non_inverting:
            - U1:+ → IN_SIG. U1:- → U1_INV_IN.
            - RG:1 → 0, RG:2 → U1_INV_IN.
            - RF:1 → OUT_SIG, RF:2 → U1_INV_IN.
            - U1:OUT → OUT_SIG.
            - Av = 1 + RF/RG. DC-coupled signal path — DO NOT add AC coupling caps.
            22. For opamp_differential:
            - Inputs are IN_PLUS_SIG and IN_MINUS_SIG (both small-signal). Output is OUT_SIG.
            - R1:1 → IN_MINUS_SIG, R1:2 → U1_INV_IN. R2:1 → U1_INV_IN, R2:2 → OUT_SIG.
            - R3:1 → IN_PLUS_SIG, R3:2 → U1_NON_INV_IN. R4:1 → U1_NON_INV_IN, R4:2 → 0.
            - U1:- → U1_INV_IN. U1:+ → U1_NON_INV_IN. U1:OUT → OUT_SIG.
            - For balanced differential gain, MUST satisfy R1 = R3 (input pair matched) AND R2 = R4 (feedback/ground pair matched). Av_diff = R2/R1.
            - signal_flow.input_node MAY name either IN_PLUS_SIG or IN_MINUS_SIG; ensure probe_nodes lists BOTH.
            23. Op-amp decoupling caps (rule 13 expansion):
            - Single supply: 1 × 0.1uF cap from VCC to 0.
            - Dual supply: 1 × 0.1uF cap from VS+ (positive rail) to 0 AND 1 × 0.1uF cap from VS- (negative rail) to 0.
            These decoupling caps are NOT counted as signal-path coupling capacitors — they are local supply bypass only.

            EXPECTED COMPONENT INVENTORY (per topology, minimum required count — fewer than this is invalid):
            - common_emitter:   1×bjt_npn (Q1) + 4×resistor (RB1, RB2, RC, RE OR RE1+RE2 per rule 12) + 2×capacitor coupling (CIN, COUT) + 1×capacitor bypass (CE across RE2) + 1×voltage_source (VTB or VIN) + 1×power_supply (VCC) + 1×ground
            - common_collector: 1×bjt_npn (Q1) + 3×resistor (RB1, RB2, RE)                          + 2×capacitor coupling (CIN, COUT)                                       + 1×voltage_source              + 1×power_supply              + 1×ground   [NO RC, NO bypass cap]
            - common_base:      1×bjt_npn (Q1) + 4×resistor (RB1, RB2, RC, RE)                      + 2×capacitor coupling (CIN, COUT) + 1×capacitor base-bypass (CB to GND) + 1×voltage_source              + 1×power_supply              + 1×ground
            - opamp_inverting:     1×opamp_ic (U1) + 2×resistor (RIN, RF)                + 1×capacitor decoupling (0.1uF VCC→0) [+ 1 more if dual supply] + 1×voltage_source + 1×power_supply + 1×ground   [NO signal-path coupling caps]
            - opamp_non_inverting: 1×opamp_ic (U1) + 2×resistor (RG, RF)                 + 1×capacitor decoupling [+ 1 if dual]                          + 1×voltage_source + 1×power_supply + 1×ground   [NO signal-path coupling caps]
            - opamp_differential:  1×opamp_ic (U1) + 4×resistor (R1, R2, R3, R4 matched pairs R1=R3, R2=R4) + 1×capacitor decoupling [+ 1 if dual]      + 1×voltage_source + 1×power_supply + 1×ground   [NO signal-path coupling caps]

            JSON SHAPE:
            {
            "is_valid_request": true,
            "analysis": {
                "circuit_name": "",
                "topology_classification": "",
                "design_summary": "",
                "calculated_values": {
                "gain_dB": 0.0,
                "bandwidth_Hz": 0.0,
                "input_impedance_ohm": 0.0,
                "output_impedance_ohm": 0.0,
                "IC_mA": 0.0,
                "VCE_V": 0.0
                }
            },
            "architecture": {
                "topology_type": "Single-stage",
                "stage_count": 1,
                "stages": [
                {
                    "id": "S1",
                    "topology": "",
                    "active_device_ref": ""
                }
                ]
            },
            "power_and_coupling": {
                "power_rail": "",
                "output_strategy": ""
            },
            "signal_flow": {
                "input_node": "IN",
                "output_node": "OUT",
                "main_chain": ["S1"]
            },
            "components": [
                {
                "ref": "",
                "type": "",
                "value": "",
                "model": "",
                "role": "",
                "topology_stage": 0
                }
            ],
            "nets": [
                {
                "net_name": "",
                "nodes": []
                }
            ],
            "probe_nodes": []
            }

            Generate the complete CircuitIR JSON for the user request.
            """.strip()

        last_error_fields: List[str] = []
        last_error_message = ""

        for retry_attempt in range(max_completeness_retries + 1):
            request_payload: Dict[str, Any] = {
                "task": "circuit.ir.generate.v1",
                "requirements": req_text,
                "retry_attempt": retry_attempt,
                "output_contract": {
                    "format": "json",
                    "strict": True,
                    "schema_name": "CircuitIR",
                },
            }
            if last_error_fields:
                request_payload["validation_feedback"] = {
                    "failed_fields": last_error_fields,
                    "message": last_error_message,
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
                logger.warning(
                    "chat_json returned None at retry attempt %d/%d",
                    retry_attempt,
                    max_completeness_retries,
                )
                continue

            try:
                ir = CircuitIR.model_validate(obj)
                logger.info(
                    "CircuitIR generated successfully (attempt %d/%d)",
                    retry_attempt + 1,
                    max_completeness_retries + 1,
                )
                return ir

            except ValidationError as exc:
                last_error_message = str(exc)
                last_error_fields = self._extract_validation_fields(exc)
                if "nets.duplicate_pins" in last_error_fields:
                    logger.error("CircuitIR rejected due to duplicate_pins — retrying generation")
                logger.warning(
                    "CircuitIR validation failed at retry %d/%d: %s",
                    retry_attempt,
                    max_completeness_retries,
                    last_error_message,
                )
                if retry_attempt < max_completeness_retries:
                    continue
                return {
                    "error": "circuit_ir_validation_failed",
                    "fields": last_error_fields,
                    "message": last_error_message,
                }

        logger.error(
            "Failed to generate valid CircuitIR after %d completeness retries",
            max_completeness_retries + 1,
        )
        if last_error_fields:
            return {
                "error": "circuit_ir_validation_failed",
                "fields": last_error_fields,
                "message": last_error_message,
            }
        return None

    @staticmethod
    def _augment_requirements_with_defaults(requirements: str) -> str:
        """Giữ nguyên requirements — không inject default CE."""
        return (requirements or "").strip()

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
                            "location": m.location or "(not set)",
                            "tier": "primary" if i == 0 else f"fallback_{i}",
                        }
                        for i, m in enumerate([config.primary] + config.fallbacks)
                    ],
                }
        return status

    @staticmethod
    def _extract_validation_fields(exc: ValidationError) -> List[str]:
        fields: List[str] = []
        for err in exc.errors():
            loc = err.get("loc", []) or []
            msg = str(err.get("msg", ""))
            if "validation_errors:" in msg:
                suffix = msg.split("validation_errors:", 1)[1]
                for item in suffix.split(","):
                    field = item.strip()
                    if field:
                        fields.append(field)
                continue
            if loc:
                if loc[0] in {"__root__", "__base__"}:
                    continue
                fields.append(".".join(str(part) for part in loc))
        if not fields:
            return []
        return sorted(set(fields))

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
                starter_key="id",
            )
            normalized["architecture"] = architecture_copy

        normalized["nets"] = LLMRouter._repair_duplicate_opamp_output_nets(normalized.get("nets"))

        return normalized

    @staticmethod
    def _repair_duplicate_opamp_output_nets(raw_nets: Any) -> Any:
        """Auto-heal common LLM wiring error: U1:OUT duplicated across two nets.

        We keep the OUT pin on the most likely output net (prefers names containing
        `OUT`) and remove that same pin from any other net to satisfy
        `nets.duplicate_pins` validation.
        """
        if not isinstance(raw_nets, list):
            return raw_nets

        nets: List[Dict[str, Any]] = []
        for net in raw_nets:
            if not isinstance(net, dict):
                nets.append(net)
                continue
            copied = dict(net)
            nodes = copied.get("nodes")
            copied["nodes"] = list(nodes) if isinstance(nodes, list) else []
            nets.append(copied)

        occurrences: Dict[str, List[Tuple[int, int, str]]] = {}
        for net_idx, net in enumerate(nets):
            net_name = str(net.get("net_name") or "")
            for node_idx, node in enumerate(net.get("nodes", [])):
                parsed = LLMRouter._parse_pin_ref(node)
                if parsed is None:
                    continue
                ref, pin = parsed
                if not ref.startswith("U") or not LLMRouter._is_opamp_output_pin(pin):
                    continue
                pin_key = f"{ref}:{pin}"
                occurrences.setdefault(pin_key, []).append((net_idx, node_idx, net_name))

        changed = False
        for pin_key, uses in occurrences.items():
            if len(uses) <= 1:
                continue
            keep_entry = max(uses, key=lambda x: (1 if "OUT" in x[2].upper() else 0, -x[0]))
            keep_net_idx, _, keep_net_name = keep_entry
            for net_idx, node_idx, _ in uses:
                if net_idx == keep_net_idx:
                    continue
                node_list = nets[net_idx].get("nodes", [])
                if 0 <= node_idx < len(node_list):
                    node_list[node_idx] = None
                    changed = True
            logger.warning(
                "Auto-healed duplicate op-amp output pin %s by keeping it on net '%s'",
                pin_key,
                keep_net_name,
            )

        if not changed:
            return raw_nets

        for net in nets:
            node_list = net.get("nodes", [])
            if isinstance(node_list, list):
                net["nodes"] = [n for n in node_list if isinstance(n, str) and str(n).strip()]
        return nets

    @staticmethod
    def _parse_pin_ref(node: Any) -> Optional[Tuple[str, str]]:
        text = str(node or "").strip()
        if not text:
            return None
        if ":" in text:
            ref, pin = text.split(":", 1)
        elif "." in text:
            ref, pin = text.split(".", 1)
        else:
            return None
        ref = ref.strip().upper()
        pin = pin.strip().upper()
        if not ref or not pin:
            return None
        return ref, pin

    @staticmethod
    def _is_opamp_output_pin(pin: str) -> bool:
        return pin in {"OUT", "OUTPUT", "VO", "VOUT", "O"}

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

    def _try_call_json(self,model: ModelConfig,system: str,user_content: str,temperature: Optional[float],max_tokens: Optional[int],response_model: Optional[Type[BaseModel]],schema_retries: int,) -> Optional[Dict[str, Any]]:
        temp = temperature if temperature is not None else model.temperature
        tokens = _cap_vertex_output_tokens(max_tokens if max_tokens is not None else model.max_tokens)
        response_schema = (
            prepare_vertex_schema(response_model.model_json_schema(), debug_label=response_model.__name__)
            if response_model is not None else None
        )

        attempts = schema_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                obj = self._gemini_json(model, system, user_content, temp, tokens, response_schema=response_schema)
            except Exception as e:
                err_str = str(e)
                
                if "Unsupported region" in err_str or "global" in err_str.lower():
                    logger.error(
                        "[%s/%s] Region %s không hỗ trợ vertexai — chỉ dùng "
                        "us-central1 hoặc asia-southeast1: %s",
                        model.provider.value,
                        model.model_id,
                        model.location,
                        err_str[:200],
                    )
                    return None
                
                if "has no field named" in err_str and ("$defs" in err_str or "additionalProperties" in err_str):
                    logger.error(
                        "[%s/%s] Schema Vertex không hợp lệ — cần fix schema_utils.py\nFull error: %s",
                        model.provider.value, model.model_id, err_str[:600],   # ← thêm err_str vào đây
                    )
                    return None
                
                logger.warning(
                    "[%s/%s] JSON call failed (attempt %s/%s): %s",
                    model.provider.value, model.model_id, attempt, attempts, err_str[:200],
                )
                continue

            if response_model is None:
                return obj

            try:
                validated = response_model.model_validate(obj)
                return validated.model_dump(mode="json")
            except ValidationError as e:
                validation_fields = self._extract_validation_fields(e)
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
                        normalized_fields = self._extract_validation_fields(normalized_error)
                        if (
                            getattr(response_model, "__name__", "") == "CircuitIR"
                            and "nets.duplicate_pins" in normalized_fields
                        ):
                            logger.error("CircuitIR rejected due to duplicate_pins — retrying generation")
                            return normalized_obj
                        logger.warning(
                            "[%s/%s] JSON schema validation failed after normalization (attempt %s/%s): %s",
                            model.provider.value,
                            model.model_id,
                            attempt,
                            attempts,
                            normalized_error,
                        )
                if (
                    getattr(response_model, "__name__", "") == "CircuitIR"
                    and "nets.duplicate_pins" in validation_fields
                ):
                    logger.error("CircuitIR rejected due to duplicate_pins — retrying generation")
                    return obj
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
        tokens = _cap_vertex_output_tokens(max_tokens if max_tokens is not None else model.max_tokens)
        
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
        import json, json_repair
        
        client = GoogleCloudClient(
            api_key=model.api_key, model=model.model_id,
            timeout_sec=model.timeout_sec, project_id=model.project_id, location=model.location,
        )
        messages = [GoogleCloudMessage(role="user", content=user_content)]

        try:
            return client.chat_json(
                messages, system_instruction=system,
                temperature=temperature, max_tokens=max_tokens,
                response_schema=response_schema,
            )
        except json.JSONDecodeError as jde:
            raw = getattr(jde, "doc", None)  # json.JSONDecodeError có attr .doc = raw string
            if raw and len(raw) > 50:
                try:
                    repaired = json_repair.repair_json(raw, return_objects=True)
                    if isinstance(repaired, dict) and repaired:
                        logger.info("[%s/%s] JSON repaired from JSONDecodeError",
                                    model.provider.value, model.model_id)
                        return repaired
                except Exception:
                    pass
            raise

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
