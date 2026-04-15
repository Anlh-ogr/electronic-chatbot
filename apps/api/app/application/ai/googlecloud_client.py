# .\\thesis\\electronic-chatbot\\apps\\api\\app\\application\\ai\\googlecloud_client.py
"""Client cho Vertex AI Gemini.

Module này cung cấp client gọi Gemini thông qua Vertex AI SDK
(`google-cloud-aiplatform`) và hỗ trợ 2 chế độ phản hồi:
- chat_json(): trả về dict JSON
- chat_text(): trả về text thuần

Xác thực sử dụng Application Default Credentials (ADC):
- Máy cá nhân: chạy `gcloud auth application-default login`
- Server/Cloud: gán Service Account có quyền `roles/aiplatform.user`
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# json: Parse JSON response text
# logging: Debug + error tracking
# os: đọc cấu hình project/location từ environment
# dataclasses: Data model definitions
# typing: Type hints cho IDE support
# vertexai: SDK chính để gọi Gemini qua Vertex AI
import json
import logging
import os
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, List, Optional

import vertexai
from vertexai.generative_models import (
    GenerativeModel,
    HarmBlockThreshold,
    HarmCategory,
    SafetySetting,
)

logger = logging.getLogger(__name__)


DEFAULT_PROJECT_ID = "project-2bdf5ad0-a50b-4dd6-95d"
DEFAULT_LOCATION = "asia-southeast1"

_VERTEX_INIT_LOCK = Lock()
_VERTEX_INIT_CONTEXT: Optional[tuple[str, str]] = None


def _env(names: List[str], default: str = "") -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return default


def _ensure_vertex_initialized(project_id: str, location: str) -> None:
    global _VERTEX_INIT_CONTEXT

    target = (project_id, location)
    if _VERTEX_INIT_CONTEXT == target:
        return

    with _VERTEX_INIT_LOCK:
        if _VERTEX_INIT_CONTEXT == target:
            return
        vertexai.init(project=project_id, location=location)
        _VERTEX_INIT_CONTEXT = target
        logger.info(
            "Vertex AI initialized (project=%s, location=%s)",
            project_id,
            location,
        )



class GoogleCloudClientError(RuntimeError):
    """Lỗi khi gọi Gemini qua Vertex AI."""
    pass


@dataclass(frozen=True)
class GoogleCloudMessage:
    # Message trong conversation.
    role: str       # "user" | "model"
    content: str


class GoogleCloudClient:
    """Client gọi Gemini qua Vertex AI SDK."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "gemini-2.5-flash",
        timeout_sec: float = 30.0,
        project_id: str = "",
        location: str = "",
    ) -> None:
        # Giữ tham số api_key để tương thích ngược với call-site cũ.
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_sec
        self._project_id = project_id.strip() or _env(
            ["Google_Cloud_Project_ID", "GOOGLE_CLOUD_PROJECT", "GCP_PROJECT"],
            default=DEFAULT_PROJECT_ID,
        )
        self._location = location.strip() or _env(
            [
                "Google_Cloud_Location",
                "GOOGLE_CLOUD_LOCATION",
                "GOOGLE_CLOUD_REGION",
                "VERTEX_AI_LOCATION",
            ],
            default=DEFAULT_LOCATION,
        )

        _ensure_vertex_initialized(self._project_id, self._location)
        self._model_client = GenerativeModel(self._model)

        if self._api_key:
            logger.info(
                "Google_Cloud_API_Key hiện không dùng trong Vertex AI mode; "
                "hệ thống dùng ADC."
            )

    def chat_json(
        self,
        messages: List[GoogleCloudMessage],
        *,
        system_instruction: str = "",
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> Dict[str, Any]:
        """Gọi Gemini và parse kết quả thành JSON object."""
        prompt = self._build_prompt(
            messages=messages,
            system_instruction=system_instruction,
            expect_json=True,
        )
        content_text = self._generate_text(
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._parse_json_content(content_text)

    def chat_text(
        self,
        messages: List[GoogleCloudMessage],
        *,
        system_instruction: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """Gọi Gemini và trả về text thuần."""
        prompt = self._build_prompt(
            messages=messages,
            system_instruction=system_instruction,
            expect_json=False,
        )
        return self._generate_text(
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def generate_response(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """Tương thích kiểu gọi prompt trực tiếp (single-turn)."""
        content = prompt.strip() or " "
        return self._generate_text(
            prompt=content,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _build_prompt(
        self,
        messages: List[GoogleCloudMessage],
        *,
        system_instruction: str,
        expect_json: bool,
    ) -> str:
        lines: List[str] = []

        if system_instruction.strip():
            lines.append(f"System instruction:\n{system_instruction.strip()}")

        for msg in messages:
            role = "Assistant"
            if msg.role.lower() == "user":
                role = "User"
            text = msg.content.strip()
            if text:
                lines.append(f"{role}: {text}")

        if expect_json:
            lines.append(
                "Return only a valid JSON object. "
                "Do not use markdown code fences."
            )

        if not lines:
            lines.append("User: ")

        return "\n\n".join(lines)

    def _generate_text(self, *, prompt: str, temperature: float, max_tokens: int) -> str:
        safety_settings = [
            SafetySetting(
                category=HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            ),
            SafetySetting(
                category=HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            ),
            SafetySetting(
                category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            ),
            SafetySetting(
                category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            ),
        ]

        try:
            response = self._model_client.generate_content(
                prompt,
                generation_config={
                    "temperature": float(temperature),
                    "max_output_tokens": int(max_tokens),
                    "top_p": 0.95,
                    "top_k": 40,
                },
                safety_settings=safety_settings,
            )
        except Exception as e:
            raise GoogleCloudClientError(f"Vertex AI request failed: {e}") from e

        text = self._extract_text(response)
        if not text:
            raise GoogleCloudClientError("Vertex AI returned empty content")
        return text

    def _extract_text(self, response: Any) -> str:
        text = getattr(response, "text", "")
        if isinstance(text, str) and text.strip():
            return text.strip()

        parts: List[str] = []
        try:
            for candidate in getattr(response, "candidates", []) or []:
                content = getattr(candidate, "content", None)
                for part in getattr(content, "parts", []) or []:
                    part_text = getattr(part, "text", "")
                    if part_text:
                        parts.append(str(part_text))
        except Exception:
            pass

        return "\n".join(parts).strip()

    def _parse_json_content(self, text: str) -> Dict[str, Any]:
        """Parse text thành JSON object, có xử lý markdown code fences."""
        content = text.strip()

        # Strip markdown code fences
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first line (```json) and last line (```)
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            content = "\n".join(lines).strip()

        try:
            obj = json.loads(content)
        except json.JSONDecodeError as e:
            raise GoogleCloudClientError(
                f"Vertex AI did not return valid JSON: {e}; content={content[:400]}"
            ) from e

        if not isinstance(obj, dict):
            raise GoogleCloudClientError("Vertex AI JSON root must be an object")

        return obj
