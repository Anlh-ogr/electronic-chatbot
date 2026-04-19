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
 - Graceful degradation: nếu Vertex AI lỗi → fallback rule-based
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# logging: ghi log router initialization, API availability
# os: đọc cấu hình từ environment variables
# dataclass + field: định nghĩa ModelConfig, RouterConfig value objects
# enum: định nghĩa LLMRole, LLMProvider, LLMMode enums
# typing: type safe router API, generic models support

import logging
import os
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

PromptContent = Any


def _env(name: str, default: str = "") -> str:
    """Doc bien moi truong va trim khoang trang."""
    return (os.getenv(name) or default).strip()


class LLMRole(str, Enum):
    """Role LLM. He thong hien tai dung role chung cho moi mode."""

    GENERAL = "general"
    # Alias tuong thich nguoc: role cu deu map ve luong chung.
    ROUTER = "general"
    EXTRACTION = "general"
    REASONING = "general"
    PRESENTATION = "general"


class LLMProvider(str, Enum):
    """Nha cung cap model."""

    GEMINI = "gemini"


class LLMMode(str, Enum):
    """Che do/tier model cua chatbot."""

    FAST = "fast"
    THINK = "think"
    PRO = "pro"
    ULTRA = "ultra"


@dataclass
class ModelConfig:
    """Cau hinh cho mot model trong chain."""

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
    """Cau hinh model chinh va fallback cho mot role."""

    primary: ModelConfig
    fallbacks: List[ModelConfig] = field(default_factory=list)


def _build_mode_configs() -> Dict[LLMMode, Dict[LLMRole, "RoleConfig"]]:
    """Tao cau hinh chain model cho tung mode."""

    project_id = (
        _env("Google_Cloud_Project_ID")
        or _env("GOOGLE_CLOUD_PROJECT")
        or _env("GCP_PROJECT")
    )
    location = (
        _env("Google_Cloud_Location")
        or _env("GOOGLE_CLOUD_LOCATION")
        or _env("GOOGLE_CLOUD_REGION")
        or _env("VERTEX_AI_LOCATION")
        or "asia-southeast1"
    )

    google_key = (
        _env("Google_Cloud_API_Key")
        or _env("GOOGLE_CLOUD_API_KEY")
        or _env("GEMINI_API_KEY")
    )

    def _first_env(names: List[str], default: str) -> str:
        for name in names:
            value = _env(name)
            if value:
                return value
        return default

    def _google(model_envs: List[str], default: str, timeout: float, max_tokens: int, temperature: float = 0.0) -> ModelConfig:
        return ModelConfig(
            provider=LLMProvider.GEMINI,
            model_id=_first_env(model_envs, default),
            api_key=google_key,
            project_id=project_id,
            location=location,
            timeout_sec=timeout, max_tokens=max_tokens, temperature=temperature,
        )

    fast_model = _google(["GoogleCloud_Fast_Model", "Google_Cloud_Fast_Model"], "gemini-2.5-flash-lite", 25.0, 8192)
    think_model = _google(["GoogleCloud_Think_Model", "Google_Cloud_Think_Model"], "gemini-2.5-flash", 35.0, 12288)
    pro_model = _google(["GoogleCloud_Pro_Model", "Google_Cloud_Pro_Model"], "gemini-2.0-flash-001", 45.0, 16384)
    ultra_model = _google(["GoogleCloud_Ultra_Model", "Google_Cloud_Ultra_Model"], "gemini-flash-latest", 55.0, 16384)

    fast: Dict[LLMRole, RoleConfig] = {
        LLMRole.GENERAL: RoleConfig(primary=fast_model, fallbacks=[think_model, pro_model, ultra_model]),
    }
    think: Dict[LLMRole, RoleConfig] = {
        LLMRole.GENERAL: RoleConfig(primary=think_model, fallbacks=[pro_model, ultra_model, fast_model]),
    }
    pro: Dict[LLMRole, RoleConfig] = {
        LLMRole.GENERAL: RoleConfig(primary=pro_model, fallbacks=[ultra_model, think_model, fast_model]),
    }
    ultra: Dict[LLMRole, RoleConfig] = {
        LLMRole.GENERAL: RoleConfig(primary=ultra_model, fallbacks=[pro_model, think_model, fast_model]),
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
            _env("GoogleCloud_Default_Mode")
            or _env("Google_Cloud_Default_Mode")
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
            or _env("GOOGLE_CLOUD_PROJECT")
            or _env("GCP_PROJECT")
            or _env("Google_Cloud_API_Key")
            or _env("GOOGLE_CLOUD_API_KEY")
            or _env("GEMINI_API_KEY")
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
    def chat_json(
        self,
        role: LLMRole,
        *,
        mode: Optional[LLMMode] = None,
        system: str = "",
        user_content: PromptContent = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_model: Optional[Type[BaseModel]] = None,
        max_schema_retries: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
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

        attempts = schema_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                obj = self._gemini_json(model, system, user_content, temp, tokens)
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
    def _gemini_json(self, model: ModelConfig, system: str, user_content: str, temperature: float, max_tokens: int,) -> Dict[str, Any]:
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
