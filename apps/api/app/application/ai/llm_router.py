# app/application/ai/llm_router.py
""" Đây là phần xử lý trung tâm gọi LLM Service
Điều phối multi-model theo vai trò (router, extraction, reasoning, presentation) và chế độ (AIR vs PRO).
Hai chế độ hoạt động:
  ✨ AIR (Tốc độ cao): Groq fast + Gemini Flash — yêu cầu cơ bản, R-L-C, lý thuyết
  💥 PRO (Suy luận sâu): Gemini Pro + Groq 70B fallback — yêu cầu phức tạp, đa dạng
  
Bảng model theo role ⨉ mode (khớp config thực tế):
    ┌──────────────────────────────────────────────────────────────────────────┐
    │ Role         │  AIR (primary → fallback)  │   PRO (primary → fallback)   │
    │──────────────┼────────────────────────────┼──────────────────────────────│
    │ ROUTER       │ 8b → 2.5lite → scout       │ 3.1lite → 2.5flash → 3flash  │
    │ EXTRACTION   │ 27b → maverick → 12b       │ gpt-120b → kimi-k2 → 70b     │
    │ REASONING    │ 27b → maverick → 2.5lite   │ gpt-120b → 70b → kimi-k2     │
    │ PRESENTATION │ maverick → 2.5lite → 12b   │ 3flash → 2.5flash → 70b      │
    └──────────────────────────────────────────────────────────────────────────┘

Chú thích:
 8b: llama-3.1-8b-instant              │ 2.5lite: gemini-2.5-flash-lite
 12b: gemma-3-12b-it                   │ maverick: llama-4-maverick-17b-128e-instruct
 scout: llama-4-scout-17b-16e-instruct │ 27b: gemma-3-27b-it

 3.1flash: gemini-3.1-flash-lite  │ kimi-k2: kimi-k2-instruct-0905
 2.5flash: gemini-2.5-flash       │ 70b: llama-3.3-70b-versatile
 3flash: gemini-3-flash           │ gpt-120b: openai/gpt-oss-120b
"""

from __future__ import annotations

#import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

""" Lý do sử dụng thư viện
logging: ghi lịch sử log, giúp theo dõi hoạt động của LLMRouter, đặc biệt khi có fallback hoặc lỗi.
dataclass, field: giúp định nghĩa các cấu hình model và role một cách rõ ràng, dễ quản lý và mở rộng.
Enum: định nghĩa kiểu dữ liệu tự động cho vai trò (role)
typing: cung cấp các kiểu dữ liệu rõ ràng cho hàm và cấu hình, giúp code dễ hiểu và tránh lỗi.
"""

logger = logging.getLogger(__name__)


# Helpers - Hàm đọc biến môi trường -> để gọi os.env truy cập
def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


# Enums & Config - Phần sử dụng enum & config vai trò - ổn định dữ liệu.
class LLMRole(str, Enum):
    # Pipeline thực hiện trong model
    ROUTER = "router"               # Phase1: bộ phận trực, điều phối.
    EXTRACTION = "extraction"       # Phase2: bộ thu thập thông tin.
    REASONING = "reasoning"         # Phase3: bộ suy luận, xử lý logic.
    PRESENTATION = "presentation"   # Phase4: bộ phát ngôn, trình bày.

class LLMProvider(str, Enum):
    GROQ = "groq"
    GEMINI = "gemini"

class LLMMode(str, Enum):
    AIR = "air"   # Tốc độ cao - yêu cầu cơ bản.
    PRO = "pro"   # Suy luận sâu — yêu cầu phức tạp.

@dataclass
class ModelConfig:
    # Cấu hình Model.
    provider: LLMProvider
    model_id: str
    # Groq dùng OpenAI-compatible, Gemini dùng native REST
    api_key: str = ""
    base_url: str = ""
    timeout_sec: float = 30.0
    max_tokens: int = 1024
    temperature: float = 0.0

@dataclass
class RoleConfig:
    # Model ưu tiên đi kèm danh sách dự phòng (1st->2nd->3rd).
    primary: ModelConfig
    fallbacks: List[ModelConfig] = field(default_factory=list)


# Xây dựng cấu hình Model
def _build_mode_configs() -> Dict[LLMMode, Dict[LLMRole, "RoleConfig"]]:
    # Đọc local và đưa cấu hình A/P vào từng role (fallback chain 1st-2nd-3rd).
    gemini_key = _env("GEMINI_API_KEY")
    groq_key = _env("GROQ_API_KEY")
    groq_base = "https://api.groq.com/openai/v1"    # latest version (13-Mar-2026)

    def _groq(model_env: str, default: str, timeout: float, max_tokens: int, temperature: float = 0.0) -> ModelConfig:
        return ModelConfig(
            provider=LLMProvider.GROQ, model_id=_env(model_env, default),
            api_key=groq_key, base_url=groq_base,
            timeout_sec=timeout, max_tokens=max_tokens, temperature=temperature,
        )

    def _gemini(model_env: str, default: str, timeout: float, max_tokens: int, temperature: float = 0.0) -> ModelConfig:
        return ModelConfig(
            provider=LLMProvider.GEMINI, model_id=_env(model_env, default),
            api_key=gemini_key,
            timeout_sec=timeout, max_tokens=max_tokens, temperature=temperature,
        )

    # ── AIR mode: Tốc độ cao, yêu cầu cơ bản ──
    # Groq chain: llama-4-maverick → llama-4-scout → llama-3.1-8b
    air_groq = [
        _groq("GROQ_AIR_MODEL_1", "meta-llama/llama-4-maverick-17b-128e-instruct", 15.0, 8192),
        _groq("GROQ_AIR_MODEL_2", "meta-llama/llama-4-scout-17b-16e-instruct", 15.0, 8192),
        _groq("GROQ_AIR_MODEL_3", "llama-3.1-8b-instant", 10.0, 2048),
    ]

    # Gemini chain: gemma-3-27b → gemma-3-12b → gemini-2.5-flash-lite
    air_gemini = [
        _gemini("GEMINI_AIR_MODEL_1", "google/gemma-3-27b-it", 30.0, 8192),
        _gemini("GEMINI_AIR_MODEL_2", "gemini-2.5-flash-lite", 30.0, 8192),
        _gemini("GEMINI_AIR_MODEL_3", "google/gemma-3-12b-it", 30.0, 8192),
    ]

    air: Dict[LLMRole, RoleConfig] = {
        LLMRole.ROUTER: RoleConfig(primary=air_groq[2], fallback=[air_gemini[1], air_groq[1]]),
        LLMRole.EXTRACTION: RoleConfig(primary=air_gemini[0], fallback=[air_groq[0], air_gemini[2]]),
        LLMRole.REASONING: RoleConfig(primary=air_gemini[0], fallback=[air_groq[0], air_gemini[1]]),
        LLMRole.PRESENTATION: RoleConfig(primary=air_groq[0], fallback=[air_gemini[1], air_gemini[2]]),
    }

    # ── PRO mode: Suy luận sâu, mạch phức tạp ──
    # Groq chain: gpt-oss-120b → llama-3.3-70b → kimi-k2
    pro_groq = [
        _groq("GROQ_PRO_MODEL_1", "openai/gpt-oss-120b", 30.0, 65536),
        _groq("GROQ_PRO_MODEL_2", "llama-3.3-70b-versatile", 30.0, 32768),
        _groq("GROQ_PRO_MODEL_3", "moonshotai/kimi-k2-instruct-0905", 30.0, 32768),
    ]
    # Gemini chain: gemini-3.1-flash-lite → gemini-3-flash → gemini-2.5-flash
    pro_gemini = [
        _gemini("GEMINI_PRO_MODEL_1", "gemini-3.1-flash-lite", 40.0, 16384),
        _gemini("GEMINI_PRO_MODEL_2", "gemini-3-flash", 40.0, 16384),
        _gemini("GEMINI_PRO_MODEL_3", "gemini-2.5-flash", 40.0, 16384),
    ]

    pro: Dict[LLMRole, RoleConfig] = {
        LLMRole.ROUTER: RoleConfig(primary=pro_gemini[0], fallback=[pro_gemini[2], pro_gemini[1]]),
        LLMRole.EXTRACTION: RoleConfig(primary=pro_groq[0], fallback=[pro_groq[2], pro_groq[1]]),
        LLMRole.REASONING: RoleConfig(primary=pro_groq[0], fallback=[pro_groq[1], pro_groq[2]]),
        LLMRole.PRESENTATION: RoleConfig(primary=pro_gemini[1], fallback=[pro_gemini[2], pro_groq[1]]),
    }

    return {LLMMode.AIR: air, LLMMode.PRO: pro}


# 
class LLMRouter:
    """
    Multi-model orchestrator.

    Gọi model phù hợp cho từng vai trò, tự động fallback khi lỗi (429, timeout, ...).

    Usage::

        router = LLMRouter()
        result = router.chat_json(LLMRole.ROUTER, system="...", user_content="...")
        text   = router.chat_text(LLMRole.PRESENTATION, system="...", user_content="...")
    """

    def __init__(self) -> None:
        self._mode_configs = _build_mode_configs()
        mode_str = _env("DEFAULT_MODE", "air").lower()
        self._default_mode = LLMMode.PRO if mode_str == "pro" else LLMMode.AIR
        self._groq_available = bool(_env("GROQ_API_KEY"))
        self._gemini_available = bool(_env("GEMINI_API_KEY"))
        logger.info(
            f"LLMRouter initialized: mode={self._default_mode.value}, "
            f"groq={'yes' if self._groq_available else 'no'}, "
            f"gemini={'yes' if self._gemini_available else 'no'}"
        )

    # ── Public API ──

    def chat_json(
        self,
        role: LLMRole,
        *,
        mode: Optional[LLMMode] = None,
        system: str = "",
        user_content: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Gọi LLM cho role, trả về parsed JSON dict.
        Tự động fallback. Trả None nếu cả primary + fallback đều lỗi.
        """
        cfg = self._get_config(role, mode)
        if not cfg:
            logger.error(f"No config for role {role}")
            return None

        # Try primary
        result = self._try_call_json(cfg.primary, system, user_content, temperature, max_tokens)
        if result is not None:
            return result

        # Try fallback chain (2nd, 3rd, ...)
        for fb in cfg.fallbacks:
            logger.info(f"[{role.value}] Trying fallback ({fb.model_id})")
            result = self._try_call_json(fb, system, user_content, temperature, max_tokens)
            if result is not None:
                return result

        logger.warning(f"[{role.value}] All models failed, returning None")
        return None

    def chat_text(
        self,
        role: LLMRole,
        *,
        mode: Optional[LLMMode] = None,
        system: str = "",
        user_content: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        """
        Gọi LLM cho role, trả về raw text.
        Tự động fallback. Trả None nếu tất cả đều lỗi.
        """
        cfg = self._get_config(role, mode)
        if not cfg:
            logger.error(f"No config for role {role}")
            return None

        result = self._try_call_text(cfg.primary, system, user_content, temperature, max_tokens)
        if result is not None:
            return result

        for fb in cfg.fallbacks:
            logger.info(f"[{role.value}] Trying fallback ({fb.model_id})")
            result = self._try_call_text(fb, system, user_content, temperature, max_tokens)
            if result is not None:
                return result

        logger.warning(f"[{role.value}] All models failed, returning None")
        return None

    def is_available(self, role: LLMRole, mode: Optional[LLMMode] = None) -> bool:
        """Kiểm tra xem role có model nào khả dụng (có API key) không."""
        cfg = self._get_config(role, mode)
        if not cfg:
            return False
        if cfg.primary.api_key:
            return True
        return any(fb.api_key for fb in cfg.fallbacks)

    def get_status(self) -> Dict[str, Any]:
        """Trả về trạng thái các model theo mode."""
        status: Dict[str, Any] = {
            "default_mode": self._default_mode.value,
            "groq_available": self._groq_available,
            "gemini_available": self._gemini_available,
            "modes": {},
        }
        for mode, configs in self._mode_configs.items():
            status["modes"][mode.value] = {}
            for role, cfg in configs.items():
                status["modes"][mode.value][role.value] = {
                    "chain": [
                        {
                            "model": f"{m.provider.value}/{m.model_id}",
                            "has_key": bool(m.api_key),
                            "tier": "primary" if i == 0 else f"fallback_{i}",
                        }
                        for i, m in enumerate([cfg.primary] + cfg.fallbacks)
                    ],
                }
        return status

    # ── Internal call helpers ──

    def _get_config(self, role: LLMRole, mode: Optional[LLMMode]) -> Optional[RoleConfig]:
        """Lấy RoleConfig theo mode (fallback về default mode nếu None)."""
        m = mode if mode is not None else self._default_mode
        return self._mode_configs.get(m, {}).get(role)

    def _try_call_json(
        self, model: ModelConfig, system: str, user_content: str,
        temperature: Optional[float], max_tokens: Optional[int],
    ) -> Optional[Dict[str, Any]]:
        """Gọi 1 model, trả JSON dict hoặc None nếu lỗi."""
        if not model.api_key:
            return None
        temp = temperature if temperature is not None else model.temperature
        tokens = max_tokens if max_tokens is not None else model.max_tokens
        try:
            if model.provider == LLMProvider.GROQ:
                return self._groq_json(model, system, user_content, temp, tokens)
            else:
                return self._gemini_json(model, system, user_content, temp, tokens)
        except Exception as e:
            logger.warning(f"[{model.provider.value}/{model.model_id}] JSON call failed: {e}")
            return None

    def _try_call_text(
        self, model: ModelConfig, system: str, user_content: str,
        temperature: Optional[float], max_tokens: Optional[int],
    ) -> Optional[str]:
        """Gọi 1 model, trả text hoặc None nếu lỗi."""
        if not model.api_key:
            return None
        temp = temperature if temperature is not None else model.temperature
        tokens = max_tokens if max_tokens is not None else model.max_tokens
        try:
            if model.provider == LLMProvider.GROQ:
                return self._groq_text(model, system, user_content, temp, tokens)
            else:
                return self._gemini_text(model, system, user_content, temp, tokens)
        except Exception as e:
            logger.warning(f"[{model.provider.value}/{model.model_id}] Text call failed: {e}")
            return None

    # ── Groq (OpenAI-compatible) calls ──

    def _groq_json(
        self, model: ModelConfig, system: str, user_content: str,
        temperature: float, max_tokens: int,
    ) -> Dict[str, Any]:
        from app.application.ai.llm_client import (
            OpenAICompatibleLLMClient, ChatMessage,
        )
        client = OpenAICompatibleLLMClient(
            api_key=model.api_key,
            base_url=model.base_url,
            model=model.model_id,
            timeout_sec=model.timeout_sec,
        )
        messages = []
        if system:
            messages.append(ChatMessage(role="system", content=system))
        messages.append(ChatMessage(role="user", content=user_content))
        return client.chat_json(messages, temperature=temperature, max_tokens=max_tokens)

    def _groq_text(
        self, model: ModelConfig, system: str, user_content: str,
        temperature: float, max_tokens: int,
    ) -> str:
        from app.application.ai.llm_client import (
            OpenAICompatibleLLMClient, ChatMessage,
        )
        client = OpenAICompatibleLLMClient(
            api_key=model.api_key,
            base_url=model.base_url,
            model=model.model_id,
            timeout_sec=model.timeout_sec,
        )
        messages = []
        if system:
            messages.append(ChatMessage(role="system", content=system))
        messages.append(ChatMessage(role="user", content=user_content))
        return client.chat_text(messages, temperature=temperature, max_tokens=max_tokens)

    # ── Gemini calls ──

    def _gemini_json(
        self, model: ModelConfig, system: str, user_content: str,
        temperature: float, max_tokens: int,
    ) -> Dict[str, Any]:
        from app.application.ai.gemini_client import GeminiClient, GeminiMessage
        client = GeminiClient(
            api_key=model.api_key,
            model=model.model_id,
            timeout_sec=model.timeout_sec,
        )
        messages = [GeminiMessage(role="user", content=user_content)]
        return client.chat_json(
            messages, system_instruction=system,
            temperature=temperature, max_tokens=max_tokens,
        )

    def _gemini_text(
        self, model: ModelConfig, system: str, user_content: str,
        temperature: float, max_tokens: int,
    ) -> str:
        from app.application.ai.gemini_client import GeminiClient, GeminiMessage
        client = GeminiClient(
            api_key=model.api_key,
            model=model.model_id,
            timeout_sec=model.timeout_sec,
        )
        messages = [GeminiMessage(role="user", content=user_content)]
        return client.chat_text(
            messages, system_instruction=system,
            temperature=temperature, max_tokens=max_tokens,
        )


# ── Singleton ──

_router: Optional[LLMRouter] = None


def get_router() -> LLMRouter:
    """Trả về singleton LLMRouter."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
