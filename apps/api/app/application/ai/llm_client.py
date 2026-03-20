# .\\thesis\\electronic-chatbot\\apps\\api\\app\\application\\ai\\llm_client.py
"""Giao tiếp với LLM (Language Model) - OpenAI-compatible API.

Module này cung cấp client cho OpenAI-compatible LLM endpoints. Lớp
OpenAICompatibleLLMClient cung cấp phương thức chat_json() để gửi prompt
và nhận về JSON objects. Thiết kế này tách biệt phần logic gọi LLM khỏi
các phần khác của ứng dụng, cho phép dễ dàng thay thế hoặc mở rộng providers.

Vietnamese:
- Trách nhiệm: Giao tiếp với OpenAI-compatible LLM endpoints
- Chức năng: chat_json() cho JSON responses, error handling, retries
- Phụ thuộc: urllib cho HTTP requests (không cần external deps)

English:
- Responsibility: Communicate with OpenAI-compatible LLM endpoints
- Features: chat_json() for JSON responses, error handling, retries
- Dependencies: urllib for HTTP requests (no external deps needed)
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# json: Parse/generate JSON từ LLM responses
# dataclasses: Data model definitions với proper typing
# typing: Type hints cho better IDE support
# urllib: HTTP requests mà không cần external libraries
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error


# ====== LLM Client Error ======
class LLMClientError(RuntimeError):
    """Các vấn đề liên quan giao tiếp LLM."""
    
    def __init__(self, message: str, code: int = None, details: str = None):
        super().__init__(message)
        self.code = code
        self.details = details
    
    def __str__(self):
        """Hiển thị lỗi rõ ràng hơn."""
        base = super().__str__()
        if self.code is not None or self.details:
            base += f" (code={self.code})"
        return base

@dataclass(frozen=True)
class ChatMessage:
    role: str       # system: hệ thống | user: người dùng | assistant: LLM
    content: str    # nội dung hội thoại


class OpenAICompatibleLLMClient:
    """Minimal OpenAI-compatible chat-completions client.

    Works with OpenAI and many self-hosted providers that expose a compatible API.
    """

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", model: str = "gpt-4o-mini", timeout_sec: float = 20.0,) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_sec

    # * truyền keyword-only arguments để tránh lỗi khi gọi hàm
    def chat_json(self, messages: List[ChatMessage], *, temperature: float = 0.0, max_tokens: int = 600,) -> Dict[str, Any]:
        # Viết prompt yêu cầu model trả về đối tượng json duy nhất.
        url = f"{self._base_url}/chat/completions"
        
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages], # role[system|user|assistant], content[str]
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # Cung cấp đề xuất về định dạng Json.
        payload["response_format"] = {"type": "json_object"}

        # tạo request header[api+json] -> server. 
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            req = urllib.request.Request(
                url=url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                status = getattr(resp, "status", 200)
                body = resp.read().decode("utf-8", errors="replace")
        
        except urllib.error.HTTPError as er:
            body = er.read().decode("utf-8", errors="replace") if hasattr(er, "read") else str(er)
            raise LLMClientError(f"LLM HTTP {er.code}: {body}") from er
        
        except Exception as er:
            raise LLMClientError(f"LLM yêu cầu failed: {er}") from er

        # >= 400 là các lỗi HTTP.
        if status >= 400:
            raise LLMClientError(f"LLM HTTP {status}: {body}")

        try:
            data = json.loads(body)
            content = data["choices"][0]["message"]["content"]
        except Exception as er:
            raise LLMClientError(f"Invalid LLM response schema: {er}") from er

        # Xử lý kết quả từ LLM đảm bảo parse Json (xử lý cả Markdown)
        content_str = (content or "").strip()           # " "
        if content_str.startswith("```"):               # dấu ``` ở đầu/cuối (markdown)
            content_str = content_str.strip("`")        # dấu `` ở đầu/cuối

            if content_str.lower().startswith("json"):  
                content_str = content_str[4:].strip()   # lọc giữ Json thật

        try:
            obj = json.loads(content_str)
        except Exception as er:
            raise LLMClientError(f"LLM không trả về JSON hợp lệ: {er}; content={content_str[:400]}") from er
        
        # Đảm bảo LLM trả về một object JSON (không phải array, string, v.v.)
        if not isinstance(obj, dict):
            raise LLMClientError("llm JSON root phải là một object (dict)")
        return obj

    
    def chat_text(self, messages: List[ChatMessage], *, temperature: float = 0.7, max_tokens: int = 2048,) -> str:
        # Trả về raw text từ model (không parse JSON).
        url = f"{self._base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        # tạo request header[api+json] -> server.
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        
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
            err_body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
            raise LLMClientError(f"LLM HTTP {e.code}: {err_body}") from e
        except Exception as e:
            raise LLMClientError(f"LLM yêu cầu failed: {e}") from e

        try:
            data = json.loads(body)
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            raise LLMClientError(f"LLM phản hồi không hợp lệ: {e}") from e
