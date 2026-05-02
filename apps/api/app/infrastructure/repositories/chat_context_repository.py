"""Repositories for chat history, summary-memory, and knowledge retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
import time
import uuid
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.chat_context_models import (
    ChatModel,
    ChatSummaryModel,
    DocumentChunkModel,
    DocumentModel,
    MemoryFactModel,
    MessageModel,
    SessionModel,
)


logger = logging.getLogger(__name__)


@dataclass
class KnowledgeHit:
    chunk_id: str
    document_id: str
    source: str
    file_name: str
    content: str
    score: float
    metadata: Dict[str, Any]


@dataclass
class ChatRecord:
    id: str
    session_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class RetryableRepository:
    """Small retry helper for transient DB failures."""

    def _with_retry(self, fn: Callable[[], Any], retries: int = 2, base_sleep: float = 0.15) -> Any:
        last_error: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                return fn()
            except Exception as exc:  # pragma: no cover - defensive runtime behavior
                last_error = exc
                if attempt >= retries:
                    raise
                time.sleep(base_sleep * (2 ** attempt))
        raise RuntimeError("Retry loop exhausted") from last_error


class ChatHistoryRepository(RetryableRepository):
    """Conversation persistence: chats + messages."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self._chat_pk_column = self._detect_chat_pk_column()

    def _detect_chat_pk_column(self) -> str:
        """Detect chat primary key column name for schema compatibility.

        Canonical schema uses chats.chat_id, but some existing environments still
        have chats.id. We support both without disabling context persistence.
        """
        try:
            rows = self.session.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'chats'
                    """
                )
            ).fetchall()
        except Exception as exc:  # pragma: no cover - runtime DB inspection guard
            logger.warning("Failed to inspect chats table columns, defaulting to chat_id: %s", exc)
            return "chat_id"

        cols = {str(row[0]).strip().lower() for row in rows}
        if "chat_id" in cols:
            return "chat_id"
        if "id" in cols:
            logger.warning("Detected legacy chats.id schema. Repository will use compatibility mode.")
            return "id"
        return "chat_id"

    def _chat_row(self, chat_id: str) -> Optional[ChatRecord]:
        pk = self._chat_pk_column
        row = self.session.execute(
            text(
                f"""
                SELECT {pk} AS chat_pk, session_id, title, created_at, updated_at
                FROM chats
                WHERE {pk} = :chat_id
                LIMIT 1
                """
            ),
            {"chat_id": chat_id},
        ).first()
        if row is None:
            return None

        return ChatRecord(
            id=str(row.chat_pk),
            session_id=str(row.session_id),
            title=str(row.title or "New Chat"),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _touch_chat(self, chat_id: str, now: datetime) -> None:
        pk = self._chat_pk_column
        self.session.execute(
            text(f"UPDATE chats SET updated_at = :now WHERE {pk} = :chat_id"),
            {"now": now, "chat_id": chat_id},
        )

    def create_chat(self, user_id: str, title: str = "New Chat", chat_id: Optional[str] = None) -> str:
        cid = chat_id or str(uuid.uuid4())
        sid = cid

        def _op() -> str:
            _ = user_id  # kept for backward compatibility with existing service signature
            now = datetime.utcnow()

            session_model = (
                self.session.query(SessionModel)
                .filter(SessionModel.id == sid)
                .first()
            )
            if session_model is None:
                self.session.add(SessionModel(id=sid, last_active=now))
            else:
                session_model.last_active = now

            existing_chat = self._chat_row(cid)
            if existing_chat is not None:
                pk = self._chat_pk_column
                self.session.execute(
                    text(f"UPDATE chats SET title = :title, updated_at = :now WHERE {pk} = :chat_id"),
                    {"title": title or existing_chat.title, "now": now, "chat_id": cid},
                )
                self.session.commit()
                return cid

            if self._chat_pk_column == "chat_id":
                model = ChatModel(id=cid, session_id=sid, title=title)
                self.session.add(model)
            else:
                self.session.execute(
                    text(
                        """
                        INSERT INTO chats (id, session_id, title, created_at, updated_at)
                        VALUES (:chat_id, :session_id, :title, :created_at, :updated_at)
                        """
                    ),
                    {
                        "chat_id": cid,
                        "session_id": sid,
                        "title": title,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            self.session.commit()
            return cid

        return self._with_retry(_op)

    def get_chat(self, chat_id: str) -> Optional[ChatRecord]:
        return self._chat_row(chat_id)

    def append_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        status: str = "created",
        message_id: Optional[str] = None,
    ) -> str:
        mid = message_id or str(uuid.uuid4())

        def _op() -> str:
            now = datetime.utcnow()
            chat = self._chat_row(chat_id)
            if chat is None:
                raise ValueError(f"Chat '{chat_id}' not found")

            msg = MessageModel(
                id=mid,
                chat_id=chat_id,
                role=role,
                content=content,
                status=status,
            )
            self.session.add(msg)
            self._touch_chat(chat_id, now)
            self.session.query(SessionModel).filter(SessionModel.id == chat.session_id).update(
                {"last_active": now}
            )
            self.session.commit()
            return mid

        return self._with_retry(_op)

    def list_messages(self, chat_id: str, limit: int = 100) -> List[MessageModel]:
        return (
            self.session.query(MessageModel)
            .filter(MessageModel.chat_id == chat_id)
            .order_by(MessageModel.created_at.asc())
            .limit(limit)
            .all()
        )

    def get_message(self, message_id: str) -> Optional[MessageModel]:
        return (
            self.session.query(MessageModel)
            .filter(MessageModel.id == message_id)
            .first()
        )

    def update_message_content(
        self,
        *,
        message_id: str,
        chat_id: Optional[str],
        new_content: str,
        status: str = "edited",
    ) -> Optional[MessageModel]:
        def _op() -> Optional[MessageModel]:
            query = self.session.query(MessageModel).filter(MessageModel.id == message_id)
            if chat_id:
                query = query.filter(MessageModel.chat_id == chat_id)

            model = query.first()
            if model is None:
                return None

            model.content = new_content
            model.status = status

            now = datetime.utcnow()
            self._touch_chat(str(model.chat_id), now)

            chat = self._chat_row(str(model.chat_id))
            if chat is not None:
                self.session.query(SessionModel).filter(SessionModel.id == chat.session_id).update(
                    {"last_active": now}
                )

            self.session.commit()
            self.session.refresh(model)
            return model

        return self._with_retry(_op)


class SummaryMemoryRepository(RetryableRepository):
    """Summary + durable facts for token-saving context building."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_summary(
        self,
        chat_id: str,
        summary_text: str,
        token_estimate: int,
        source_message_count: int,
        version: int,
    ) -> str:
        sid = str(uuid.uuid4())

        def _op() -> str:
            _ = version  # compatibility: Neon schema does not store explicit version column

            model = ChatSummaryModel(
                id=sid,
                chat_id=chat_id,
                summary_text=summary_text,
                token_estimate=token_estimate,
                source_message_count=source_message_count,
            )
            self.session.add(model)
            self.session.commit()
            return sid

        return self._with_retry(_op)

    def latest_summary(self, chat_id: str) -> Optional[ChatSummaryModel]:
        return (
            self.session.query(ChatSummaryModel)
            .filter(ChatSummaryModel.chat_id == chat_id)
            .order_by(ChatSummaryModel.created_at.desc())
            .first()
        )

    def list_summaries(self, chat_id: str, limit: int = 20) -> List[ChatSummaryModel]:
        return (
            self.session.query(ChatSummaryModel)
            .filter(ChatSummaryModel.chat_id == chat_id)
            .order_by(ChatSummaryModel.created_at.desc())
            .limit(limit)
            .all()
        )

    def upsert_memory_fact(
        self,
        fact_key: str,
        fact_value: str,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        confidence: float = 0.5,
        source: str = "model",
    ) -> str:
        fid = str(uuid.uuid4())
        session_id = (chat_id or user_id or "").strip()
        _ = source

        def _op() -> str:
            if not session_id:
                raise ValueError("session_id is required to persist memory fact")

            session_model = (
                self.session.query(SessionModel)
                .filter(SessionModel.id == session_id)
                .first()
            )
            if session_model is None:
                self.session.add(SessionModel(id=session_id, last_active=datetime.utcnow()))

            query = self.session.query(MemoryFactModel).filter(
                MemoryFactModel.session_id == session_id,
                MemoryFactModel.fact_key == fact_key,
            )
            if chat_id is not None:
                query = query.filter(MemoryFactModel.chat_id == chat_id)
            else:
                query = query.filter(MemoryFactModel.chat_id.is_(None))

            existing = query.first()
            if existing:
                existing.fact_value = fact_value
                existing.chat_id = chat_id
                existing.confidence = confidence
                existing.is_active = True
                self.session.commit()
                return existing.id

            model = MemoryFactModel(
                id=fid,
                session_id=session_id,
                chat_id=chat_id,
                fact_key=fact_key,
                fact_value=fact_value,
                confidence=confidence,
            )
            self.session.add(model)
            self.session.commit()
            return fid

        return self._with_retry(_op)

    def list_active_memory(self, user_id: Optional[str], limit: int = 50) -> List[MemoryFactModel]:
        query = self.session.query(MemoryFactModel).filter(MemoryFactModel.is_active.is_(True))
        if user_id is not None:
            # Backward-compatible: treat user_id argument as session_id for Neon schema.
            query = query.filter(MemoryFactModel.session_id == user_id)
        return query.order_by(MemoryFactModel.id.desc()).limit(limit).all()


class KnowledgeRepository(RetryableRepository):
    """Document metadata and chunk-level semantic retrieval."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _vector_literal(values: List[float]) -> str:
        # Safe literal builder for numeric embeddings passed to CAST(... AS vector).
        return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"

    def upsert_document(
        self,
        source: str,
        file_name: str,
        doc_type: str,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        checksum: Optional[str] = None,
    ) -> str:
        did = str(uuid.uuid4())
        metadata = metadata or {}

        def _op() -> str:
            existing = (
                self.session.query(DocumentModel)
                .filter(DocumentModel.source == source, DocumentModel.file_name == file_name)
                .first()
            )
            if existing:
                existing.doc_type = doc_type
                existing.title = title
                existing.metadata_json = metadata
                existing.checksum = checksum
                existing.updated_at = datetime.utcnow()
                self.session.commit()
                return existing.id

            doc = DocumentModel(
                id=did,
                source=source,
                file_name=file_name,
                doc_type=doc_type,
                title=title,
                metadata_json=metadata,
                checksum=checksum,
            )
            self.session.add(doc)
            self.session.commit()
            return did

        return self._with_retry(_op)

    def upsert_chunk(
        self,
        document_id: str,
        chunk_index: int,
        content: str,
        embedding: List[float],
        token_count: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        cid = str(uuid.uuid4())
        metadata = metadata or {}

        def _op() -> str:
            existing = (
                self.session.query(DocumentChunkModel)
                .filter(
                    DocumentChunkModel.document_id == document_id,
                    DocumentChunkModel.chunk_index == chunk_index,
                )
                .first()
            )
            if existing:
                existing.content = content
                existing.embedding = embedding
                existing.token_count = token_count
                existing.metadata_json = metadata
                self.session.commit()
                return existing.id

            chunk = DocumentChunkModel(
                id=cid,
                document_id=document_id,
                chunk_index=chunk_index,
                content=content,
                embedding=embedding,
                token_count=token_count,
                metadata_json=metadata,
            )
            self.session.add(chunk)
            self.session.commit()
            return cid

        return self._with_retry(_op)

    def semantic_search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        doc_type: Optional[str] = None,
    ) -> List[KnowledgeHit]:
        embedding_literal = self._vector_literal(query_embedding)

        sql = """
        SELECT
            c.id AS chunk_id,
            c.document_id AS document_id,
            d.source AS source,
            d.file_name AS file_name,
            c.content AS content,
            (1 - (c.embedding <=> CAST(:embedding AS vector))) AS score,
            c.metadata AS metadata
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE (:doc_type IS NULL OR d.doc_type = :doc_type)
        ORDER BY c.embedding <=> CAST(:embedding AS vector)
        LIMIT :top_k
        """

        rows = self.session.execute(
            text(sql),
            {
                "embedding": embedding_literal,
                "doc_type": doc_type,
                "top_k": top_k,
            },
        ).fetchall()

        return [
            KnowledgeHit(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                source=row.source,
                file_name=row.file_name,
                content=row.content,
                score=float(row.score),
                metadata=dict(row.metadata or {}),
            )
            for row in rows
        ]
