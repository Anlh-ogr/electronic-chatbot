from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
    def __init__(self, *, message_id: str, chat_id: str, session_id: str) -> None:
        self._message = _FakeMessage(
            id=message_id,
            chat_id=chat_id,
            role="user",
            content="original question",
            status="completed",
            created_at=datetime.utcnow(),
        )
        self._chat = _FakeChat(id=chat_id, session_id=session_id)
        self.last_update_payload = None

    def get_message(self, message_id: str):
        if message_id != self._message.id:
            return None
        return self._message

    def get_chat(self, chat_id: str):
        if chat_id != self._chat.id:
            return None
        return self._chat

    def update_message_content(self, *, message_id: str, chat_id: str, new_content: str, status: str = "edited"):
        if message_id != self._message.id:
            return None
        if chat_id != self._message.chat_id:
            return None

        self.last_update_payload = {
            "message_id": message_id,
            "chat_id": chat_id,
            "new_content": new_content,
            "status": status,
        }

        self._message.content = new_content
        self._message.status = status
        return self._message


def _build_client(monkeypatch, repo: _FakeChatHistoryRepository) -> TestClient:
    app = FastAPI()
    app.include_router(chatbot_route.router)

    monkeypatch.setattr(chatbot_route, "SessionLocal", lambda: _FakeDbSession())
    monkeypatch.setattr(chatbot_route, "ChatHistoryRepository", lambda _db: repo)

    return TestClient(app)


def _assert_success_payload(payload, *, expected_message_id: str, expected_chat_id: str, expected_session_id: str, expected_content: str) -> None:
    assert payload["message_id"] == expected_message_id
    assert payload["chat_id"] == expected_chat_id
    assert payload["session_id"] == expected_session_id
    assert payload["content"] == expected_content
    assert payload["status"] == "edited"
    assert payload["role"] == "user"


def test_edit_message_accepts_chat_id_as_session_id(monkeypatch) -> None:
    repo = _FakeChatHistoryRepository(
        message_id="message-1",
        chat_id="chat-1",
        session_id="session-1",
    )
    client = _build_client(monkeypatch, repo)

    resp = client.patch(
        "/api/chat/messages/message-1",
        json={
            "session_id": "chat-1",
            "content": "edited question by chat id",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    _assert_success_payload(
        payload,
        expected_message_id="message-1",
        expected_chat_id="chat-1",
        expected_session_id="session-1",
        expected_content="edited question by chat id",
    )
    assert repo.last_update_payload is not None
    assert repo.last_update_payload["chat_id"] == "chat-1"


def test_edit_message_accepts_real_session_id(monkeypatch) -> None:
    repo = _FakeChatHistoryRepository(
        message_id="message-2",
        chat_id="chat-2",
        session_id="session-2",
    )
    client = _build_client(monkeypatch, repo)

    resp = client.patch(
        "/api/chat/messages/message-2",
        json={
            "session_id": "session-2",
            "content": "edited question by session id",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    _assert_success_payload(
        payload,
        expected_message_id="message-2",
        expected_chat_id="chat-2",
        expected_session_id="session-2",
        expected_content="edited question by session id",
    )
    assert repo.last_update_payload is not None
    assert repo.last_update_payload["chat_id"] == "chat-2"


def test_edit_message_accepts_missing_session_id(monkeypatch) -> None:
    repo = _FakeChatHistoryRepository(
        message_id="message-3",
        chat_id="chat-3",
        session_id="session-3",
    )
    client = _build_client(monkeypatch, repo)

    resp = client.patch(
        "/api/chat/messages/message-3",
        json={
            "content": "edited question without session id",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    _assert_success_payload(
        payload,
        expected_message_id="message-3",
        expected_chat_id="chat-3",
        expected_session_id="session-3",
        expected_content="edited question without session id",
    )
    assert repo.last_update_payload is not None
    assert repo.last_update_payload["chat_id"] == "chat-3"
