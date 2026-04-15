# .\\thesis\\electronic-chatbot\\apps\\api\\app\\db\\chat_context_models.py
"""SQLAlchemy models cho Chat Context, Memory, và Document Retrieval.

Module này định nghĩa các database models cho chatbot context management:
- ChatModel: Session lịch sử chat
- MessageModel: Individual messages trong chat
- ChatSummaryModel: Summaries của chat sessions
- DocumentModel/DocumentChunkModel: Knowledge base documents
- MemoryFactModel: Extracted facts cho summary-augmented generation

Vietnamese:
- Trách nhiệm: Định nghĩa ORM models cho chat + knowledge management
- Scope: Chat history, summaries, document chunks, memory facts
- Relationship: Messages → Chats, Chunks → Documents, Facts → Chats

English:
- Responsibility: Define ORM models for chat + knowledge management
- Scope: Chat history, summaries, document chunks, memory facts
- Relationship: Messages → Chats, Chunks → Documents, Facts → Chats
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# sqlalchemy: Column types, constraints, relationships
# datetime: Timestamp management
# JSONB: PostgreSQL native JSON storage
from datetime import datetime
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.types import UserDefinedType

from app.db.database import Base


class Vector(UserDefinedType):
    """Minimal VECTOR type for PostgreSQL pgvector extension."""

    cache_ok = True

    def __init__(self, dim: int = 1536) -> None:
        self.dim = dim

    def get_col_spec(self, **_: object) -> str:
        return f"VECTOR({self.dim})"


class SessionModel(Base):
    __tablename__ = "sessions"

    id = Column("session_id", String(36), primary_key=True)
    client_ip = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    last_active = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    chats = relationship("ChatModel", back_populates="session", cascade="all, delete-orphan")


class ChatModel(Base):
    __tablename__ = "chats"

    id = Column("chat_id", String(36), primary_key=True)
    session_id = Column(
        String(36),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(String(255), nullable=False, default="New Chat")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    session = relationship("SessionModel", back_populates="chats")
    messages = relationship("MessageModel", back_populates="chat", cascade="all, delete-orphan")
    summaries = relationship("ChatSummaryModel", back_populates="chat", cascade="all, delete-orphan")


class MessageModel(Base):
    __tablename__ = "messages"

    id = Column("message_id", String(36), primary_key=True)
    chat_id = Column(String(36), ForeignKey("chats.chat_id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="created")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_cost = Column(Float, nullable=False, default=0.0)
    model_used = Column(String(100), nullable=True)

    chat = relationship("ChatModel", back_populates="messages")

    __table_args__ = (
        CheckConstraint("role IN ('system', 'user', 'assistant', 'tool')", name="ck_messages_role"),
        CheckConstraint(
            "status IN ('created', 'streaming', 'completed', 'failed', 'edited', 'deleted')",
            name="ck_messages_status",
        ),
    )


class ChatSummaryModel(Base):
    __tablename__ = "chat_summaries"

    id = Column("summary_id", String(36), primary_key=True)
    chat_id = Column(String(36), ForeignKey("chats.chat_id", ondelete="CASCADE"), nullable=False, index=True)
    summary_text = Column(Text, nullable=False)
    token_estimate = Column(Integer, nullable=False, default=0)
    source_message_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    chat = relationship("ChatModel", back_populates="summaries")

    @property
    def version(self) -> int:
        # Backward-compatible field used by debug endpoint.
        return 1

    @property
    def updated_at(self) -> datetime:
        return self.created_at


class MemoryFactModel(Base):
    __tablename__ = "memory_facts"

    id = Column("memory_id", String(36), primary_key=True)
    session_id = Column(
        String(36),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_id = Column(String(36), ForeignKey("chats.chat_id", ondelete="SET NULL"), nullable=True, index=True)
    fact_key = Column(String(255), nullable=False)
    fact_value = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False, default=0.5)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    @property
    def user_id(self) -> str:
        # Backward-compatible alias used by context router code paths.
        return self.session_id

    @property
    def source(self) -> str:
        # Backward-compatible field expected by ContextRouterService.
        return "chatbot"


class DocumentModel(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True)
    source = Column(String(255), nullable=False, index=True)
    file_name = Column(String(255), nullable=False)
    doc_type = Column(String(64), nullable=False, index=True)
    title = Column(String(255), nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=False, default=dict)
    checksum = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    chunks = relationship("DocumentChunkModel", back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("source", "file_name", name="uq_document_source_file"),)


class DocumentChunkModel(Base):
    __tablename__ = "document_chunks"

    id = Column(String(36), primary_key=True)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False, default=0)
    embedding = Column(Vector(1536), nullable=False)
    metadata_json = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    document = relationship("DocumentModel", back_populates="chunks")

    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),)
