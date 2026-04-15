# .\\thesis\\electronic-chatbot\\apps\\api\\app\\application\\ai\\context_router_service.py
"""Dịch vụ định tuyến ngữ cảnh (Context Router) cho xây dựng prompt LLM.

Module này cung cấp tầng định tuyến (routing layer) cho việc xây dựng prompt
với hỗ trợ retry/fallback behavior. Nó quản lý ngữ cảnh (context) từ chat history,
knowledge retrieval, và summary memory để tạo prompt tốt cho LLM.

Vietnamese:
- Trách nhiệm: Định tuyến + xây dựng context từ multiple sources
- Chức năng: Chat history, knowledge retrieval, fallback external data
- Đầu ra: Complete context dict cho prompt engineering

English:
- Responsibility: Route + build context from multiple sources
- Features: Chat history, knowledge retrieval, fallback external data
- Output: Complete context dict for prompt engineering
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# dataclasses: Định nghĩa data classes với proper typing support
# typing: Type hints cho Protocol + generic types
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol

# ====== Domain & Infrastructure layers ======
from app.infrastructure.repositories.chat_context_repository import (
    ChatHistoryRepository,
    KnowledgeHit,
    KnowledgeRepository,
    SummaryMemoryRepository,
)


# ====== External Knowledge Provider Protocol ======
class ExternalKnowledgeProvider(Protocol):
    """Fallback source for data outside the internal document index.
    
    Protocol này định nghĩa interface cho các external knowledge providers
    (ví dụ: web search, API, knowledge bases) khi nội bộ index không có dữ liệu.
    """

    def fetch(self, query: str, limit: int = 3) -> List[str]:
        """Fetch external knowledge for query."""
        ...


# ====== Context Bundle & Router Service ======
@dataclass
class ContextBundle:
    """Bundle các context pieces cho LLM prompt engineering."""
    chat_messages: List[Dict[str, str]] = field(default_factory=list)
    summary: Optional[str] = None
    memory_facts: List[Dict[str, str]] = field(default_factory=list)
    knowledge_hits: List[KnowledgeHit] = field(default_factory=list)
    external_fallback: List[str] = field(default_factory=list)


class ContextRouterService:
    """Tầng định tuyến (router layer) chuẩn bị model context với graceful fallback.
    
    Class này quản lý việc thu thập context từ multiple sources:
    - Chat history (previous messages)
    - Summary (conversation summary)
    - Memory facts (extracted entities)
    - Knowledge hits (document retrieval)
    - External fallback (web search, APIs)
    
    Responsibilities (Trách nhiệm):
    - Retrieve chat history messages
    - Compose summary from memory repository
    - Search knowledge base
    - Fallback to external providers nếu internal không đủ
    """

    def __init__(
        self,
        chat_repo: ChatHistoryRepository,
        summary_repo: SummaryMemoryRepository,
        knowledge_repo: KnowledgeRepository,
        external_provider: Optional[ExternalKnowledgeProvider] = None,
    ) -> None:
        self._chat_repo = chat_repo
        self._summary_repo = summary_repo
        self._knowledge_repo = knowledge_repo
        self._external_provider = external_provider

    def build_context(
        self,
        chat_id: str,
        user_id: Optional[str],
        query: str,
        query_embedding: Optional[List[float]],
        history_limit: int = 12,
        top_k: int = 5,
        doc_type: Optional[str] = None,
    ) -> ContextBundle:
        bundle = ContextBundle()

        messages = self._chat_repo.list_messages(chat_id=chat_id, limit=history_limit)
        bundle.chat_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.status != "deleted"
        ]

        latest_summary = self._summary_repo.latest_summary(chat_id=chat_id)
        if latest_summary is not None:
            bundle.summary = latest_summary.summary_text

        # Neon schema stores durable facts per session_id, which maps to current chat_id.
        facts = self._summary_repo.list_active_memory(user_id=chat_id, limit=20)
        bundle.memory_facts = [
            {"key": f.fact_key, "value": f.fact_value, "source": f.source}
            for f in facts
        ]

        if query_embedding:
            try:
                hits = self._knowledge_repo.semantic_search(
                    query_embedding=query_embedding,
                    top_k=top_k,
                    doc_type=doc_type,
                )
                bundle.knowledge_hits = hits
            except Exception:
                bundle.knowledge_hits = []

        # Fallback flow for external data when internal retrieval is empty.
        if not bundle.knowledge_hits and self._external_provider is not None:
            try:
                bundle.external_fallback = self._external_provider.fetch(query=query, limit=3)
            except Exception:
                bundle.external_fallback = []

        return bundle


class NullExternalKnowledgeProvider:
    """Default external provider that returns no data."""

    def fetch(self, query: str, limit: int = 3) -> List[str]:
        _ = (query, limit)
        return []
