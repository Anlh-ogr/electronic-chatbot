"""Repositories for chat history, summary-memory, and knowledge retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
import time
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.chat_context_models import (
    ChatModel,
    ChatSummaryModel,
    DocumentChunkModel,
    DocumentModel,
    MemoryFactModel,
    MessageModel,
)


@dataclass
class KnowledgeHit:
    chunk_id: str
    document_id: str
    source: str
    file_name: str
    content: str
    score: float
    metadata: Dict[str, Any]


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

    def create_chat(self, user_id: str, title: str = "New Chat", chat_id: Optional[str] = None) -> str:
        cid = chat_id or str(uuid.uuid4())

        def _op() -> str:
            model = ChatModel(id=cid, user_id=user_id, title=title)
            self.session.add(model)
            self.session.commit()
            return cid

        return self._with_retry(_op)

    def get_chat(self, chat_id: str) -> Optional[ChatModel]:
        return (
            self.session.query(ChatModel)
            .filter(ChatModel.id == chat_id)
            .first()
        )

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
            msg = MessageModel(
                id=mid,
                chat_id=chat_id,
                role=role,
                content=content,
                status=status,
            )
            self.session.add(msg)
            self.session.query(ChatModel).filter(ChatModel.id == chat_id).update(
                {"updated_at": datetime.utcnow()}
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
            existing = (
                self.session.query(ChatSummaryModel)
                .filter(
                    ChatSummaryModel.chat_id == chat_id,
                    ChatSummaryModel.version == version,
                )
                .first()
            )
            if existing:
                existing.summary_text = summary_text
                existing.token_estimate = token_estimate
                existing.source_message_count = source_message_count
                existing.updated_at = datetime.utcnow()
                self.session.commit()
                return existing.id

            model = ChatSummaryModel(
                id=sid,
                chat_id=chat_id,
                summary_text=summary_text,
                token_estimate=token_estimate,
                source_message_count=source_message_count,
                version=version,
            )
            self.session.add(model)
            self.session.commit()
            return sid

        return self._with_retry(_op)

    def latest_summary(self, chat_id: str) -> Optional[ChatSummaryModel]:
        return (
            self.session.query(ChatSummaryModel)
            .filter(ChatSummaryModel.chat_id == chat_id)
            .order_by(ChatSummaryModel.version.desc())
            .first()
        )

    def list_summaries(self, chat_id: str, limit: int = 20) -> List[ChatSummaryModel]:
        return (
            self.session.query(ChatSummaryModel)
            .filter(ChatSummaryModel.chat_id == chat_id)
            .order_by(ChatSummaryModel.version.desc())
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

        def _op() -> str:
            query = self.session.query(MemoryFactModel).filter(
                MemoryFactModel.user_id == user_id,
                MemoryFactModel.fact_key == fact_key,
            )
            existing = query.first()
            if existing:
                existing.fact_value = fact_value
                existing.chat_id = chat_id
                existing.confidence = confidence
                existing.source = source
                existing.is_active = True
                existing.updated_at = datetime.utcnow()
                self.session.commit()
                return existing.id

            model = MemoryFactModel(
                id=fid,
                user_id=user_id,
                chat_id=chat_id,
                fact_key=fact_key,
                fact_value=fact_value,
                confidence=confidence,
                source=source,
            )
            self.session.add(model)
            self.session.commit()
            return fid

        return self._with_retry(_op)

    def list_active_memory(self, user_id: Optional[str], limit: int = 50) -> List[MemoryFactModel]:
        query = self.session.query(MemoryFactModel).filter(MemoryFactModel.is_active.is_(True))
        if user_id is not None:
            query = query.filter(MemoryFactModel.user_id == user_id)
        return query.order_by(MemoryFactModel.updated_at.desc()).limit(limit).all()


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
