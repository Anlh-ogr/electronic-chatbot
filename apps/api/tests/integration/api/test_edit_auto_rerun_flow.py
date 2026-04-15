from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.interfaces.http.routes import chatbot as chatbot_route


@dataclass
class _FakeMessage:
    id: str
    chat_id: str
    role: str
    content: str
    status: str
    created_at: datetime


@dataclass
class _FakeChat:
    id: str
    session_id: str


class _FakeDbSession:
    def close(self) -> None:
        return


class _FakeChatHistoryRepository:
    def __init__(self) -> None:
        self._messages = {
            "message-1": _FakeMessage(
                id="message-1",
                chat_id="chat-1",
                role="user",
                content="original request",
                status="completed",
                created_at=datetime.utcnow(),
            )
        }
        self._chats = {
            "chat-1": _FakeChat(id="chat-1", session_id="session-1"),
        }

    def get_message(self, message_id: str):
        return self._messages.get(message_id)

    def get_chat(self, chat_id: str):
        return self._chats.get(chat_id)

    def update_message_content(self, *, message_id: str, chat_id: str, new_content: str, status: str = "edited"):
        message = self._messages.get(message_id)
        if message is None:
            return None
        if message.chat_id != chat_id:
            return None

        message.content = new_content
        message.status = status
        return message


def _make_chat_result(*, message: str, session_id: str, user_message_id: str, assistant_message_id: str):
    return SimpleNamespace(
        message=message,
        success=True,
        processing_time_ms=1.0,
        mode="fast",
        needs_clarification=False,
        template_id="",
        intent={"intent_type": "create"},
        pipeline=None,
        params=None,
        analysis=None,
        circuit_data=None,
        suggestions=[],
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
    )


class _FakeChatbotService:
    def __init__(self) -> None:
        self.calls = []

    def chat(self, message: str, session_id: str | None = None, user_id: str | None = None, mode: str | None = None):
        self.calls.append(
            {
                "message": message,
                "session_id": session_id,
                "user_id": user_id,
                "mode": mode,
            }
        )

        if message == "original request":
            return _make_chat_result(
                message="assistant response for original request",
                session_id="session-1",
                user_message_id="message-1",
                assistant_message_id="assistant-1",
            )

        if message == "edited request":
            return _make_chat_result(
                message="assistant response for edited request",
                session_id=session_id or "session-1",
                user_message_id="message-2",
                assistant_message_id="assistant-2",
            )

        return _make_chat_result(
            message=f"assistant response for {message}",
            session_id=session_id or "session-1",
            user_message_id="message-x",
            assistant_message_id="assistant-x",
        )


def test_edit_then_rerun_chat_returns_new_assistant_response(monkeypatch) -> None:
    fake_repo = _FakeChatHistoryRepository()
    fake_service = _FakeChatbotService()

    app = FastAPI()
    app.include_router(chatbot_route.router)

    monkeypatch.setattr(chatbot_route, "SessionLocal", lambda: _FakeDbSession())
    monkeypatch.setattr(chatbot_route, "ChatHistoryRepository", lambda _db: fake_repo)
    monkeypatch.setattr(chatbot_route, "_chatbot_service", fake_service)

    client = TestClient(app)

    first_chat = client.post(
        "/api/chat",
        json={
            "message": "original request",
            "mode": "fast",
        },
    )

    assert first_chat.status_code == 200
    first_payload = first_chat.json()
    assert first_payload["user_message_id"] == "message-1"
    assert first_payload["assistant_message_id"] == "assistant-1"
    assert first_payload["session_id"] == "session-1"
    assert first_payload["message"] == "assistant response for original request"

    edit_resp = client.patch(
        "/api/chat/messages/message-1",
        json={
            "session_id": "session-1",
            "content": "edited request",
        },
    )

    assert edit_resp.status_code == 200
    edit_payload = edit_resp.json()
    assert edit_payload["message_id"] == "message-1"
    assert edit_payload["chat_id"] == "chat-1"
    assert edit_payload["session_id"] == "session-1"
    assert edit_payload["status"] == "edited"
    assert edit_payload["content"] == "edited request"

    rerun_chat = client.post(
        "/api/chat",
        json={
            "message": "edited request",
            "mode": "fast",
            "session_id": edit_payload["session_id"],
        },
    )

    assert rerun_chat.status_code == 200
    rerun_payload = rerun_chat.json()
    assert rerun_payload["message"] == "assistant response for edited request"
    assert rerun_payload["assistant_message_id"] == "assistant-2"
    assert rerun_payload["message"] != first_payload["message"]

    assert len(fake_service.calls) == 2
    assert fake_service.calls[1]["message"] == "edited request"
    assert fake_service.calls[1]["session_id"] == "session-1"

    edited_message = fake_repo.get_message("message-1")
    assert edited_message is not None
    assert edited_message.content == "edited request"
    assert edited_message.status == "edited"