# .\\thesis\\electronic-chatbot\\apps\\api\\app\\application\\ai\\googlecloud_client.py
"""Client cho Google Cloud Generative Language API.

Module này cung cấp client gọi Google Generative Language API (`generateContent`)
và hỗ trợ multiple response modes: chat_json (JSON responses) và chat_text (text).
Tích hợp với Google AI Studio credentials để authentication với Google models.

Vietnamese:
- Trách nhiệm: Giao tiếp với Google Generative Language API
- Chức năng: chat_json() cho JSON, chat_text() cho text responses
- Phụ thuộc: urllib, json (built-in), logging

English:
- Responsibility: Communicate with Google Generative Language API
- Features: chat_json() for JSON, chat_text() for text responses
- Dependencies: urllib, json (built-in), logging
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# json: Parse/generate JSON từ API responses
# logging: Debug API calls + error tracking
# urllib: HTTP requests cho Google API
# dataclasses: Data model definitions
# typing: Type hints cho better IDE support
import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any, Dict, List

logger = logging.getLogger(__name__)



class GoogleCloudClientError(RuntimeError):
    """Lỗi khi gọi Google Cloud API."""
    pass


@dataclass(frozen=True)
class GoogleCloudMessage:
    # Message trong conversation.
    role: str       # "user" | "model"
    content: str


class GoogleCloudClient:
    """REST client cho Google Generative Language API."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash-lite",
        timeout_sec: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_sec

    def chat_json(
        self,
        messages: List[GoogleCloudMessage],
        *,
        system_instruction: str = "",
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> Dict[str, Any]:
        """Gọi API và parse kết quả thành JSON object."""
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self._model}:generateContent?key={self._api_key}"
        )

        # Build request payload
        payload: Dict[str, Any] = {
            "contents": self._build_contents(messages),
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        headers = {"Content-Type": "application/json"}

        # Send request
        try:
            req = urllib.request.Request(
                url=url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise GoogleCloudClientError(
                f"Google Cloud HTTP {e.code}: {err_body[:500]}"
            ) from e
        except Exception as e:
            raise GoogleCloudClientError(f"Google Cloud request failed: {e}") from e

        # Parse response
        try:
            data = json.loads(body)
            candidate = data["candidates"][0]
            content_text = candidate["content"]["parts"][0]["text"]
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise GoogleCloudClientError(
                f"Invalid Google Cloud response: {e}; body={body[:500]}"
            ) from e

        # Parse content as JSON
        return self._parse_json_content(content_text)

    def chat_text(
        self,
        messages: List[GoogleCloudMessage],
        *,
        system_instruction: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """Gọi API và trả về text thuần (không parse JSON)."""
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self._model}:generateContent?key={self._api_key}"
        )

        payload: Dict[str, Any] = {
            "contents": self._build_contents(messages),
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        headers = {"Content-Type": "application/json"}

        try:
            req = urllib.request.Request(
                url=url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise GoogleCloudClientError(
                f"Google Cloud HTTP {e.code}: {err_body[:500]}"
            ) from e
        except Exception as e:
            raise GoogleCloudClientError(f"Google Cloud request failed: {e}") from e

        try:
            data = json.loads(body)
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise GoogleCloudClientError(
                f"Invalid Google Cloud response: {e}"
            ) from e

    def _build_contents(self, messages: List[GoogleCloudMessage]) -> List[Dict]:
        """Chuyển messages sang format `contents` của Google API."""
        contents = []
        for msg in messages:
            contents.append({
                "role": msg.role,
                "parts": [{"text": msg.content}],
            })
        return contents

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
                f"Google Cloud did not return valid JSON: {e}; content={content[:400]}"
            ) from e

        if not isinstance(obj, dict):
            raise GoogleCloudClientError("Google Cloud JSON root must be an object")

        return obj
