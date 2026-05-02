# .\thesis\electronic-chatbot\apps\api\app\application\ai\chatbot_service.py
"""Dịch vụ Chatbot - Tầng điều phối theo 2 chế độ toàn cục.

Module này chịu trách nhiệm:
 1. Nhận input từ API /chat
 2. Định tuyến qua NLU (phân tích ý definition)
 3. Sinh mạch qua AI Core (planning + solving + generation)
 4. Validate với domain rules
 5. Sinh response qua NLG (Natural Language Generation)

Mode được áp dụng xuyên suốt:
 - Air (default): ưu tiên tốc độ, chi phí thấp, dùng rule-based
 - Pro: ưu tiên suy luận sâu, dùng LLM chain

Nguyên tắc:
 - Là tầng application orchestrator, KHÔNG chứa business logic
 - Business logic nằm trong domain + AI Core
 - Thread-safe: context/session isolated per request
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from app.application.ai.llm_router import LLMMode, LLMRole, get_router
from app.application.ai.llm_contracts import DomainCheckOutputV1, build_llm_payload
from app.application.ai.context_router_service import (
    ContextRouterService,
    NullExternalKnowledgeProvider,
)
from app.application.ai.nlu_service import NLUService, CircuitIntent
from app.application.ai.nlg_service import NLGService
from app.application.ai.constraint_validator import ConstraintValidator
from app.application.ai.repair_engine import RepairEngine
from app.application.ai.simulation_service import (
    NgSpiceSimulationService,
    NgspiceCompilerService,
    SimulationError,
)
from app.db.database import Base, SessionLocal, engine
from app.domains.validators import ComponentSet, DCBiasValidator, DCValidationResult
from app.domains.circuits.ai_core import AICore
from app.domains.circuits.ai_core.ai_core import CircuitIRValidator, InvalidPinConnectionError
from app.domains.circuits.ai_core.spec_parser import UserSpec
from app.domains.circuits.ai_core.parameter_solver import ParameterSolver
from app.infrastructure.repositories.chat_context_repository import (
    ChatHistoryRepository,
    KnowledgeRepository,
    SummaryMemoryRepository,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.application.ai.circuit_ir_schema import CircuitIR

# Path defaults
_API_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # apps/api/
_EMPTY = Path("/dev/null/disabled") # for AI core
# none
_METADATA_DIR = _API_ROOT / "resources" / "templates_metadata"
_BLOCK_LIBRARY_DIR = _API_ROOT / "resources" / "block_library"
_TEMPLATES_DIR = _API_ROOT / "resources" / "templates"


@dataclass
class ChatResponse:
    """Response từ chatbot."""
    message: str = ""              # NLG response text (markdown)
    intent: Optional[Dict] = None  # parsed intent
    pipeline: Optional[Dict] = None  # pipeline result
    circuit_data: Optional[Dict] = None  # circuit IR nếu thành công
    params: Optional[Dict] = None  # solved parameters
    analysis: Optional[Dict] = None  # structured engineering analysis for API
    template_id: str = ""
    success: bool = True
    processing_time_ms: float = 0
    needs_clarification: bool = False  # cần hỏi thêm?
    mode: str = "air"
    suggestions: List[str] = field(default_factory=list)
    validation: Optional[Dict] = None  # validation report
    repair: Optional[Dict] = None      # repair result (nếu đã sửa)
    physics_validation: Optional[Dict] = None
    session_id: Optional[str] = None
    user_message_id: Optional[str] = None
    assistant_message_id: Optional[str] = None
    download_url: Optional[str] = None
    spice_deck_ready: Optional[bool] = None
    spice_deck_url: Optional[str] = None
    spice_deck: Optional[str] = None
    artifact_id: Optional[str] = None
    self_correction_retries: Optional[int] = None
    ir_id: Optional[str] = None
    compiled_ir_payload: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        d = {
            "message": self.message,
            "success": self.success,
            "processing_time_ms": round(self.processing_time_ms, 1),
            "needs_clarification": self.needs_clarification,
            "mode": self.mode,
            "template_id": self.template_id,
        }
        if self.intent:
            d["intent"] = self.intent
        if self.pipeline:
            d["pipeline"] = self.pipeline
        if self.params:
            d["params"] = self.params
        if self.analysis:
            d["analysis"] = self.analysis
        if self.circuit_data:
            d["circuit_data"] = self.circuit_data
        if self.suggestions:
            d["suggestions"] = self.suggestions
        if self.validation:
            d["validation"] = self.validation
        if self.repair:
            d["repair"] = self.repair
        if self.physics_validation:
            d["physics_validation"] = self.physics_validation
        if self.session_id:
            d["session_id"] = self.session_id
        if self.user_message_id:
            d["user_message_id"] = self.user_message_id
        if self.assistant_message_id:
            d["assistant_message_id"] = self.assistant_message_id
        if self.download_url:
            d["download_url"] = self.download_url
        if self.spice_deck_ready is not None:
            d["spice_deck_ready"] = self.spice_deck_ready
        if self.spice_deck_url:
            d["spice_deck_url"] = self.spice_deck_url
        if self.spice_deck:
            d["spice_deck"] = self.spice_deck
        if self.artifact_id:
            d["artifact_id"] = self.artifact_id
        if self.self_correction_retries is not None:
            d["self_correction_retries"] = self.self_correction_retries
        if self.ir_id:
            d["ir_id"] = self.ir_id
        return d


class ClarificationRequiredError(ValueError):
    """Raised when CircuitIR indicates missing critical user parameters."""


class ChatbotService:
    """Chatbot service chính theo cơ chế mode Air/Pro."""

    def __init__(self) -> None:
        self._nlu = NLUService()
        self._nlg = NLGService()
        # block resources (metadata, templates) được load trong AICore
        self._ai_core = AICore(
            metadata_dir=_EMPTY,
            block_library_dir=_EMPTY,
            templates_dir=_EMPTY,
        )
        
        
        self._router = get_router()
        self._validator = ConstraintValidator()
        self._dc_validator = DCBiasValidator()
        self._repair = RepairEngine()
        self._enforce_physics_gate = (
            os.getenv("ENFORCE_PHYSICS_GATE", "true").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self._enforce_simulation_feedback_gate = (
            os.getenv("ENFORCE_SIMULATION_FEEDBACK_GATE", "true").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        try:
            self._simulation_retry_attempts = max(
                int(os.getenv("SIMULATION_FEEDBACK_MAX_RETRIES", "1") or "1"),
                0,
            )
        except ValueError:
            self._simulation_retry_attempts = 1
        self._electronics_domain_only = (
            os.getenv("ELECTRONICS_DOMAIN_ONLY", "true").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self._feedback_memory_enabled = (
            os.getenv("CHATBOT_FEEDBACK_MEMORY_ENABLED", "true").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self._feedback_memory_path = _API_ROOT / "resources" / "runtime" / "design_feedback_memory.json"
        self._context_db_enabled = False
        self._chat_repo: Optional[ChatHistoryRepository] = None
        self._summary_repo: Optional[SummaryMemoryRepository] = None
        self._knowledge_repo: Optional[KnowledgeRepository] = None
        self._context_router: Optional[ContextRouterService] = None
        self._init_context_router()
        logger.info("ChatbotService initialized")

    async def chat(
        self,
        user_text: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> ChatResponse:
        """Xử lý yêu cầu người dùng theo mode Air/Pro cho toàn bộ chatbot."""
        start = time.time()
        response = ChatResponse()
        chat_id = session_id
        resolved_user_id = user_id or "anonymous"
        context_available_for_request = False
        selected_mode = self._resolve_chat_mode(mode)
        response.mode = selected_mode.value
        response.message = ""

        try:
            effective_text = user_text
            user_message_id: Optional[str] = None
            if self._context_db_enabled:
                try:
                    chat_id = self._ensure_chat_session(chat_id=chat_id, user_id=resolved_user_id)
                    response.session_id = chat_id
                    effective_text = self._build_effective_user_text(
                        chat_id=chat_id,
                        user_text=user_text,
                        user_id=resolved_user_id,
                    )
                    if chat_id:
                        user_message_id = self._persist_user_message(chat_id=chat_id, user_text=user_text)
                        response.user_message_id = user_message_id
                    context_available_for_request = True
                except Exception as exc:  # pragma: no cover - runtime guard
                    logger.warning("Chat context unavailable for current request: %s", exc)
                    self._disable_context_db(exc)
                    effective_text = user_text

            # ── GĐ 0: Domain-check bằng LLM mode Air/Pro ──
            off_topic = self._domain_check(effective_text, mode=selected_mode)
            if off_topic:
                response.success = False
                response.message = off_topic
                response.processing_time_ms = (time.time() - start) * 1000
                if context_available_for_request and chat_id:
                    self._persist_assistant_message(chat_id=chat_id, assistant_text=response.message)
                return response

            # ── GĐ 1: NLU (Regex + LLM) ──
            intent = self._nlu.understand(effective_text, mode=selected_mode)
            response.intent = intent.to_dict()

            logger.info(
                f"NLU: intent_type={intent.intent_type}, type={intent.circuit_type}, "
                f"gain={intent.gain_target}, vcc={intent.vcc}, "
                f"confidence={intent.confidence:.2f}, source={intent.source}, "
                f"edit_ops={len(intent.edit_operations)}"
            )

            normalized_intent_type, used_fallback = self._normalize_intent_type(intent.intent_type)
            if used_fallback:
                intent.warnings.append(
                    f"Intent type '{intent.intent_type}' khong hop le, fallback sang '{normalized_intent_type}'"
                )
                intent.intent_type = normalized_intent_type
                response.intent = intent.to_dict()

            # ── GĐ 2: Branch theo intent_type ──
            if normalized_intent_type == "modify":
                response = self._handle_modify(intent, response, start, mode=selected_mode)
            elif normalized_intent_type == "validate":
                response = self._handle_validate(intent, response, start, mode=selected_mode)
            elif normalized_intent_type == "explain":
                response = self._handle_explain(intent, response, start, mode=selected_mode)
            else:
                response = self._handle_create(intent, response, start, mode=selected_mode)

            response.mode = selected_mode.value

            assistant_message_id: Optional[str] = None
            if context_available_for_request and chat_id and response.message:
                assistant_message_id = self._persist_assistant_message(
                    chat_id=chat_id,
                    assistant_text=response.message,
                )
                response.assistant_message_id = assistant_message_id

            if context_available_for_request and chat_id and response.success and response.circuit_data:
                self._persist_generated_circuit_snapshot(
                    chat_id=chat_id,
                    circuit_data=response.circuit_data,
                    message_id=assistant_message_id,
                    fallback_name=response.template_id,
                )

            if context_available_for_request and chat_id and response.success and response.download_url:
                await self._persist_compiled_ir_and_artifacts(
                    response=response,
                    chat_id=chat_id,
                    message_id=assistant_message_id,
                )

            if context_available_for_request and chat_id:
                self._persist_summary_and_memory_facts(chat_id=chat_id, response=response)

            return response

        except Exception as e:
            logger.error(f"ChatbotService error: {e}", exc_info=True)
            response.success = False
            response.message = f"❌ Lỗi hệ thống: {str(e)}"

        response.processing_time_ms = (time.time() - start) * 1000
        return response

    def generate_circuit_ir(
        self,
        user_text: str,
        mode: Optional[str] = None,
    ) -> Optional[CircuitIR]:
        """Generate structured CircuitIR directly from natural-language requirements."""
        from app.application.ai.circuit_ir_schema import CircuitIR

        req_text = (user_text or "").strip()
        if not req_text:
            logger.warning("generate_circuit_ir called with empty user_text")
            return None

        selected_mode = self._resolve_chat_mode(mode)

        try:
            result = self._router.generate_circuit_ir(
                req_text,
                mode=selected_mode,
                max_schema_retries=2,
            )
            if result is None:
                logger.warning("LLM did not return a valid CircuitIR object")
                return None
            ir = CircuitIR.model_validate(result)
            if not ir.is_valid_request:
                logger.info(
                    "CircuitIR requested clarification: %s",
                    ir.clarification_question or "missing critical I/O targets",
                )
            return ir
        except Exception as exc:
            logger.error("generate_circuit_ir failed: %s", exc, exc_info=True)
            return None

    def compile_circuit_artifacts(
        self,
        user_text: str,
        mode: Optional[str] = None,
        max_self_corrections: int = 2,
    ) -> Dict[str, Any]:
        """End-to-end circuit compile flow: LLM IR -> validate -> KiCad SCH -> SPICE deck."""
        from app.application.ai.circuit_ir_schema import CircuitIR
        from app.application.circuits.use_cases.export_kicad_sch import KiCad8SchematicCompiler

        req_text = (user_text or "").strip()
        if not req_text:
            raise ValueError("Yeu cau tao mach dang rong")

        selected_mode = self._resolve_chat_mode(mode)
        validator = CircuitIRValidator()
        sch_compiler = KiCad8SchematicCompiler()
        spice_compiler = NgspiceCompilerService()

        output_dir = _API_ROOT / "artifacts" / "compiled"
        output_dir.mkdir(parents=True, exist_ok=True)

        attempt_prompt = req_text
        retries_used = 0
        validated_ir: Optional[CircuitIR] = None
        last_error: Optional[Exception] = None

        for attempt in range(max_self_corrections + 1):
            try:
                ir_result = self._router.generate_circuit_ir(
                    attempt_prompt,
                    mode=selected_mode,
                    max_schema_retries=2,
                )
                if ir_result is None:
                    raise ValueError("LLM khong tra ve CircuitIR hop le")

                ir_obj = CircuitIR.model_validate(ir_result)
                if not ir_obj.is_valid_request:
                    raise ClarificationRequiredError(
                        ir_obj.clarification_question
                        or "Please provide more circuit parameters."
                    )

                ir_obj = validator.validate_and_fix_math(ir_obj)
                validator.validate_pins(ir_obj)
                validated_ir = ir_obj
                retries_used = attempt
                break
            except ClarificationRequiredError:
                raise
            except InvalidPinConnectionError as exc:
                last_error = exc
                if attempt >= max_self_corrections:
                    break
                retries_used = attempt + 1
                attempt_prompt = self._build_ir_retry_prompt(req_text, str(exc), pin_only=True)
                logger.warning("Pin validation failed, retrying IR generation (%s/%s): %s", retries_used, max_self_corrections, exc)
            except Exception as exc:
                last_error = exc
                if attempt >= max_self_corrections:
                    break
                retries_used = attempt + 1
                attempt_prompt = self._build_ir_retry_prompt(req_text, str(exc), pin_only=False)
                logger.warning("Circuit compile pre-check failed, retrying IR generation (%s/%s): %s", retries_used, max_self_corrections, exc)

        if validated_ir is None:
            raise RuntimeError(f"Khong the tao CircuitIR hop le sau {max_self_corrections + 1} lan: {last_error}")

        sch_content = sch_compiler.compile_to_sch(validated_ir)
        spice_deck = spice_compiler.generate_spice_deck(validated_ir)

        artifact_id = uuid.uuid4().hex
        sch_file_name = f"{artifact_id}.kicad_sch"
        sch_file_path = output_dir / sch_file_name
        sch_file_path.write_text(sch_content, encoding="utf-8")

        spice_file_name = f"{artifact_id}.cir"
        spice_file_path = output_dir / spice_file_name
        spice_file_path.write_text(spice_deck, encoding="utf-8")

        return {
            "message": "Circuit compiled successfully",
            "mode": selected_mode.value,
            "circuit_data": validated_ir.model_dump(mode="json"),
            "download_url": f"/api/chat/compiled/{sch_file_name}",
            "spice_deck_ready": True,
            "spice_deck": spice_deck,
            "spice_deck_url": f"/api/chat/compiled/{spice_file_name}",
            "self_correction_retries": retries_used,
            "artifact_id": artifact_id,
        }

    @staticmethod
    def _build_ir_retry_prompt(requirements: str, error_message: str, pin_only: bool) -> str:
        if pin_only:
            return (
                f"{requirements}\n\n"
                "The previous CircuitIR has invalid pin mapping. "
                f"Error: {error_message}.\n"
                "Regenerate the full CircuitIR JSON and keep all ref_id values stable. "
                "Use only valid pins for each component and keep net nodes in REF:PIN format."
            )
        return (
            f"{requirements}\n\n"
            "The previous CircuitIR failed validation. "
            f"Error: {error_message}.\n"
            "Regenerate the full CircuitIR JSON with corrected equations/components/nets while preserving the requested topology."
        )

    def _init_context_router(self) -> None:
        """Initialize chat-context persistence layer if database is available."""
        try:
            self._ensure_chat_context_schema()
            db = SessionLocal()
            self._chat_repo = ChatHistoryRepository(db)
            self._summary_repo = SummaryMemoryRepository(db)
            self._knowledge_repo = KnowledgeRepository(db)
            self._context_router = ContextRouterService(
                chat_repo=self._chat_repo,
                summary_repo=self._summary_repo,
                knowledge_repo=self._knowledge_repo,
                external_provider=NullExternalKnowledgeProvider(),
            )
            self._context_db_enabled = True
        except Exception as exc:  # pragma: no cover - runtime guard
            logger.warning("Chat context DB disabled: %s", exc)
            self._context_db_enabled = False

    @staticmethod
    def _ensure_chat_context_schema() -> None:
        """Create chat-context tables if migrations have not been applied yet."""
        from app.db.chat_context_models import (
            ChatModel,
            ChatSummaryModel,
            MemoryFactModel,
            MessageModel,
            SessionModel,
        )

        Base.metadata.create_all(
            bind=engine,
            tables=[
                ChatModel.__table__,
                MessageModel.__table__,
                ChatSummaryModel.__table__,
                MemoryFactModel.__table__,
                SessionModel.__table__,
            ],
        )

    def _disable_context_db(self, reason: Exception) -> None:
        """Hard-disable context DB after runtime failure and rollback session state."""
        for repo in (self._chat_repo, self._summary_repo, self._knowledge_repo):
            session = getattr(repo, "session", None)
            if session is None:
                continue
            try:
                if getattr(session, "is_active", False):
                    session.rollback()
            except Exception:  # pragma: no cover - defensive runtime behavior
                pass

        self._context_db_enabled = False
        self._context_router = None
        logger.warning("Chat context DB disabled for this process after error: %s", reason)

    def _ensure_chat_session(self, chat_id: Optional[str], user_id: str) -> str:
        if not self._chat_repo:
            return chat_id or ""

        resolved = chat_id or ""
        if resolved:
            existing = self._chat_repo.get_chat(resolved)
            if existing:
                return resolved

        created = self._chat_repo.create_chat(
            user_id=user_id,
            title="Chat Session",
            chat_id=resolved or None,
        )
        return created

    def _build_effective_user_text(self, chat_id: Optional[str], user_text: str, user_id: str) -> str:
        if not self._context_db_enabled or not chat_id or not self._context_router:
            return user_text

        try:
            bundle = self._context_router.build_context(
                chat_id=chat_id,
                user_id=user_id,
                query=user_text,
                query_embedding=None,
                history_limit=12,
                top_k=5,
            )
        except Exception as exc:  # pragma: no cover - runtime guard
            logger.warning("Context router unavailable for this request: %s", exc)
            session = getattr(self._chat_repo, "session", None)
            if session is not None:
                try:
                    session.rollback()
                except Exception:
                    pass
            return user_text

        if not bundle.summary and not bundle.memory_facts:
            return user_text

        memory_lines = [f"- {item['key']}: {item['value']}" for item in bundle.memory_facts[:8]]
        context_blocks: List[str] = []
        if bundle.summary:
            context_blocks.append(f"Conversation summary:\n{bundle.summary}")
        if memory_lines:
            context_blocks.append("Memory facts:\n" + "\n".join(memory_lines))

        context_text = "\n\n".join(context_blocks)
        return f"{context_text}\n\nUser request: {user_text}"

    def _persist_user_message(self, chat_id: str, user_text: str) -> Optional[str]:
        if not self._chat_repo:
            return None
        try:
            return self._chat_repo.append_message(
                chat_id=chat_id,
                role="user",
                content=user_text,
                status="completed",
            )
        except Exception as exc:  # pragma: no cover - runtime guard
            logger.warning("Failed to persist user message: %s", exc)
            return None

    def _persist_assistant_message(self, chat_id: str, assistant_text: str) -> Optional[str]:
        if not self._chat_repo:
            return None
        try:
            return self._chat_repo.append_message(
                chat_id=chat_id,
                role="assistant",
                content=assistant_text,
                status="completed",
            )
        except Exception as exc:  # pragma: no cover - runtime guard
            logger.warning("Failed to persist assistant message: %s", exc)
            return None

    def _persist_generated_circuit_snapshot(
        self,
        chat_id: str,
        circuit_data: Dict[str, Any],
        message_id: Optional[str],
        fallback_name: Optional[str] = None,
    ) -> None:
        db = SessionLocal()
        try:
            if not isinstance(circuit_data, dict) or not circuit_data:
                return

            meta = circuit_data.get("meta") if isinstance(circuit_data.get("meta"), dict) else {}
            circuit_name = (
                (meta.get("name") if isinstance(meta.get("name"), str) else None)
                or (circuit_data.get("name") if isinstance(circuit_data.get("name"), str) else None)
                or fallback_name
                or "Generated Circuit"
            )
            description = (
                meta.get("description") if isinstance(meta.get("description"), str) else None
            )

            circuit_id = str(uuid.uuid4())
            snapshot_id = str(uuid.uuid4())

            # Expose persisted circuit id back to response payload so frontend
            # can call industrial export endpoints that require circuit_id.
            meta_payload = circuit_data.get("meta")
            if not isinstance(meta_payload, dict):
                meta_payload = {}
            meta_payload["circuit_id"] = circuit_id
            circuit_data["meta"] = meta_payload
            circuit_data["circuit_id"] = circuit_id

            payload_json = json.dumps(circuit_data, ensure_ascii=False)

            db.execute(
                text(
                    """
                    INSERT INTO circuits (circuit_id, session_id, message_id, name, description)
                    VALUES (:circuit_id, :session_id, :message_id, :name, :description)
                    """
                ),
                {
                    "circuit_id": circuit_id,
                    "session_id": chat_id,
                    "message_id": message_id,
                    "name": circuit_name,
                    "description": description,
                },
            )

            db.execute(
                text(
                    """
                    INSERT INTO snapshots (snapshot_id, circuit_id, message_id, circuit_data)
                    VALUES (:snapshot_id, :circuit_id, :message_id, CAST(:circuit_data AS jsonb))
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "circuit_id": circuit_id,
                    "message_id": message_id,
                    "circuit_data": payload_json,
                },
            )

            db.commit()
        except Exception as exc:  # pragma: no cover - runtime guard
            try:
                db.rollback()
            except Exception:
                pass
            logger.error("DB Save failed, continuing in-memory: %s", exc)
        finally:
            db.close()

    def _persist_summary_and_memory_facts(self, chat_id: str, response: ChatResponse) -> None:
        if not self._chat_repo or not self._summary_repo:
            return

        try:
            messages = self._chat_repo.list_messages(chat_id=chat_id, limit=20)
            if messages:
                tail = messages[-8:]
                summary_lines = [f"{m.role}: {str(m.content)[:240]}" for m in tail]
                summary_text = "\n".join(summary_lines)
                token_estimate = max(len(summary_text) // 4, 1)
                self._summary_repo.upsert_summary(
                    chat_id=chat_id,
                    summary_text=summary_text,
                    token_estimate=token_estimate,
                    source_message_count=len(messages),
                    version=len(messages),
                )
        except Exception as exc:  # pragma: no cover - runtime guard
            logger.warning("Failed to persist chat summary: %s", exc)

        facts: Dict[str, str] = {}
        if isinstance(response.intent, dict):
            for key in ("intent_type", "circuit_type", "topology"):
                value = response.intent.get(key)
                if value is not None and str(value).strip():
                    facts[f"last_{key}"] = str(value)

        if response.template_id:
            facts["last_template_id"] = response.template_id
        facts["last_chat_success"] = "true" if response.success else "false"

        for fact_key, fact_value in facts.items():
            try:
                self._summary_repo.upsert_memory_fact(
                    fact_key=fact_key,
                    fact_value=fact_value,
                    chat_id=chat_id,
                    confidence=0.7,
                    source="chatbot",
                )
            except Exception as exc:  # pragma: no cover - runtime guard
                logger.warning("Failed to persist memory fact '%s': %s", fact_key, exc)

    # ------------------------------------------------------------------ #
    #  Intent handlers
    # ------------------------------------------------------------------ #

    def _handle_create(self, intent: CircuitIntent, response: ChatResponse, start: float, mode: LLMMode) -> ChatResponse:
        """LLM-driven circuit design flow: NLU → generate_circuit_ir() → compile → respond."""

        # ─── Step 1: Ask for clarification if insufficient parameters ───
        if intent.circuit_type == "unknown" or intent.confidence < 0.3:
            response.needs_clarification = True
            missing = []
            if intent.circuit_type == "unknown":
                missing.append("topology")
            if intent.gain_target is None:
                missing.append("gain")
            if intent.vcc is None:
                missing.append("vcc")

            smart_msg = self._smart_clarification(intent.raw_text, missing, mode=mode)
            response.message = smart_msg or self._nlg.generate_clarification(
                circuit_type=intent.circuit_type,
                missing_fields=missing,
            )
            response.success = False
            response.suggestions = [
                "Thiết kế mạch CE gain 50 dùng 12V",
                "Mạch khuếch đại common emitter gain 20",
                "OpAmp inverting gain 10",
                "Mạch class AB push-pull 12V",
            ]
            response.processing_time_ms = (time.time() - start) * 1000
            return response

        # ─── Step 2: LLM generates complete CircuitIR ───
        # The LLM is the SOLE engine for circuit generation (no ai_core rule-based fallback)
        ir_result = self._router.generate_circuit_ir(
            intent.raw_text,
            mode=mode,
            max_schema_retries=3,
            max_completeness_retries=2,
        )
        
        if ir_result is None:
            logger.error("LLM failed to generate valid CircuitIR for: %s", intent.raw_text)
            response.success = False
            response.message = (
                "❌ Hệ thống không thể sinh mạch từ yêu cầu này. "
                "Vui lòng cung cấp chi tiết hơn về topology, gain, hoặc nguồn cấp."
            )
            response.processing_time_ms = (time.time() - start) * 1000
            return response

        if not ir_result.is_valid_request:
            logger.warning("LLM returned invalid request flag: %s", ir_result.clarification_question)
            response.needs_clarification = True
            response.success = False
            response.message = ir_result.clarification_question or (
                "Yêu cầu thiếu thông tin. Vui lòng cung cấp chi tiết về yêu cầu thiết kế."
            )
            response.processing_time_ms = (time.time() - start) * 1000
            return response

        # ─── Step 3: Set circuit_data from LLM IR and proceed to compilation ───
        response.success = True
        response.circuit_data = ir_result.model_dump(mode="json")
        
        # Build a simple success message from IR analysis
        analysis = ir_result.analysis
        if analysis:
            response.message = (
                f"✅ **{analysis.circuit_name}**\n\n"
                f"**Topology**: {analysis.topology_classification}\n\n"
                f"**Giải thích**: {analysis.design_explanation}\n\n"
                f"**Công thức**: {analysis.math_basis}\n\n"
            )
            if analysis.expected_bom:
                response.message += f"**Danh sách linh kiện**: {', '.join(analysis.expected_bom)}\n\n"
        else:
            response.message = "✅ Mạch đã được thiết kế thành công."

        # ─── Step 4: Compile to KiCad and SPICE artifacts ───
        self._attach_compile_artifacts_to_response(
            response=response,
            user_text=intent.raw_text,
            mode=mode,
        )

        response.processing_time_ms = (time.time() - start) * 1000
        return response

    def _attach_compile_artifacts_to_response(
        self,
        response: ChatResponse,
        user_text: str,
        mode: LLMMode,
    ) -> None:
        """Best-effort attachment of KiCad/SPICE artifacts for frontend download/preview."""
        try:
            compiled = self.compile_circuit_artifacts(
                user_text=user_text,
                mode=mode.value,
                max_self_corrections=2,
            )
        except Exception as exc:
            logger.warning("Attach compile artifacts failed (soft): %s", exc)
            return

        response.download_url = compiled.get("download_url")
        response.spice_deck_ready = bool(compiled.get("spice_deck_ready", False))
        response.spice_deck_url = compiled.get("spice_deck_url")
        response.spice_deck = compiled.get("spice_deck")
        response.artifact_id = compiled.get("artifact_id")
        payload = compiled.get("circuit_data")
        if isinstance(payload, dict):
            response.compiled_ir_payload = payload
        retries = compiled.get("self_correction_retries")
        if isinstance(retries, int):
            response.self_correction_retries = retries

    async def _persist_compiled_ir_and_artifacts(
        self,
        *,
        response: ChatResponse,
        chat_id: str,
        message_id: Optional[str],
    ) -> None:
        """Persist validated IR and generated artifacts after successful create flow."""
        from app.application.ai.circuit_ir_schema import CircuitIR
        from app.db.session import async_session
        from app.infrastructure.repositories.circuit_artifact_repository import CircuitArtifactRepository
        from app.infrastructure.repositories.circuit_ir_repository import CircuitIRRepository

        ir_payload = response.compiled_ir_payload if isinstance(response.compiled_ir_payload, dict) else None
        if not ir_payload:
            return

        circuit_payload = response.circuit_data if isinstance(response.circuit_data, dict) else {}
        circuit_id = self._extract_circuit_id(circuit_payload)
        if not circuit_id:
            logger.warning("Skip IR persistence: missing circuit_id in response payload")
            return

        try:
            ir = CircuitIR.model_validate(ir_payload)
        except Exception as exc:
            logger.warning("Skip IR persistence: compiled payload is not valid CircuitIR (%s)", exc)
            return

        try:
            async with async_session() as session:
                ir_repo = CircuitIRRepository(session)
                artifact_repo = CircuitArtifactRepository(session)

                ir_id = await ir_repo.save_ir(
                    ir=ir,
                    circuit_id=circuit_id,
                    session_id=chat_id,
                    message_id=message_id,
                )

                sch_path = self._resolve_compiled_artifact_path(response.download_url)
                if sch_path is not None:
                    await artifact_repo.save_artifact(
                        ir_id=ir_id,
                        circuit_id=circuit_id,
                        artifact_type="kicad_sch",
                        file_path=str(sch_path),
                        download_url=response.download_url,
                        file_size_bytes=sch_path.stat().st_size,
                    )

                spice_path = self._resolve_compiled_artifact_path(response.spice_deck_url)
                if spice_path is not None:
                    await artifact_repo.save_artifact(
                        ir_id=ir_id,
                        circuit_id=circuit_id,
                        artifact_type="spice_deck",
                        file_path=str(spice_path),
                        download_url=response.spice_deck_url,
                        file_size_bytes=spice_path.stat().st_size,
                    )

                await ir_repo.update_status(ir_id, "compiled")
                response.ir_id = ir_id
        except Exception as exc:
            logger.error("DB Save failed, continuing in-memory: %s", exc)

    @staticmethod
    def _extract_circuit_id(circuit_payload: Dict[str, Any]) -> Optional[str]:
        direct = circuit_payload.get("circuit_id")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()

        meta = circuit_payload.get("meta")
        if isinstance(meta, dict):
            from_meta = meta.get("circuit_id")
            if isinstance(from_meta, str) and from_meta.strip():
                return from_meta.strip()

        return None

    @staticmethod
    def _resolve_compiled_artifact_path(download_url: Optional[str]) -> Optional[Path]:
        if not download_url:
            return None

        safe_name = Path(str(download_url)).name
        if not safe_name:
            return None

        base_dir = (_API_ROOT / "artifacts" / "compiled").resolve()
        candidate = (base_dir / safe_name).resolve()
        if candidate.parent != base_dir or not candidate.exists() or not candidate.is_file():
            return None
        return candidate

    def _handle_modify(self, intent: CircuitIntent, response: ChatResponse, start: float, mode: LLMMode) -> ChatResponse:
        """Flow chỉnh sửa mạch: xác định thao tác → apply lên mạch base → validate → NLG."""

        assumption_notes = self._apply_reasonable_defaults(intent)

        if not intent.edit_operations:
            response.needs_clarification = True
            response.success = False
            response.message = self._nlg.generate_modify_clarification(intent)
            response.processing_time_ms = (time.time() - start) * 1000
            return response

        # Nếu chưa có mạch base (circuit_type rõ) → tạo trước, rồi modify
        if intent.circuit_type and intent.circuit_type != "unknown":
            generation_intent = self._inject_feedback_hints(intent)
            spec = self._intent_to_spec(generation_intent)
            pipeline_result = self._ai_core.handle_spec(spec)

            if pipeline_result.success and pipeline_result.circuit:
                circuit_data = copy.deepcopy(pipeline_result.circuit.circuit_data)
                solved = dict(pipeline_result.solved.values) if pipeline_result.solved else {}

                # Apply edit operations
                edit_log = self._apply_edits(circuit_data, intent.edit_operations)

                gain_for_validation = self._resolve_gain_for_validation(
                    solved_values=solved,
                    fallback_gain=(pipeline_result.solved.actual_gain if pipeline_result.solved else None),
                )
                solved_for_validation = self._prepare_validation_metrics(
                    intent=intent,
                    solved_values=solved,
                    gain_actual=gain_for_validation,
                    stage_analysis=(pipeline_result.solved.stage_analysis if pipeline_result.solved else None),
                )

                # Validate
                val_report = self._validator.validate(circuit_data, intent.to_dict(), solved_for_validation)
                response.validation = val_report.to_dict()

                if not val_report.passed:
                    repair_result = self._repair.repair(circuit_data, solved, intent.to_dict(), val_report)
                    response.repair = repair_result.to_dict()
                    if repair_result.repaired:
                        circuit_data = repair_result.circuit_data
                        solved = repair_result.solved_params

                gain_for_validation = self._resolve_gain_for_validation(
                    solved_values=solved,
                    fallback_gain=(pipeline_result.solved.actual_gain if pipeline_result.solved else None),
                )
                solved_for_validation = self._prepare_validation_metrics(
                    intent=intent,
                    solved_values=solved,
                    gain_actual=gain_for_validation,
                    stage_analysis=(pipeline_result.solved.stage_analysis if pipeline_result.solved else None),
                )
                val_report = self._validator.validate(circuit_data, intent.to_dict(), solved_for_validation)
                response.validation = val_report.to_dict()

                if not val_report.passed and self._has_hard_constraint_errors(val_report):
                    failed_codes = self._extract_validation_error_codes(val_report)
                    retry_bundle = self._retry_pipeline_for_hard_constraints(
                        intent=intent,
                        failed_codes=failed_codes,
                        max_attempts=2,
                    )

                    if retry_bundle:
                        pipeline_result = retry_bundle["pipeline_result"]
                        circuit_data = copy.deepcopy(pipeline_result.circuit.circuit_data) if pipeline_result.circuit else circuit_data
                        solved = dict(pipeline_result.solved.values) if pipeline_result.solved else {}
                        edit_log = self._apply_edits(circuit_data, intent.edit_operations)

                        gain_for_validation = self._resolve_gain_for_validation(
                            solved_values=solved,
                            fallback_gain=(pipeline_result.solved.actual_gain if pipeline_result.solved else None),
                        )
                        solved_for_validation = self._prepare_validation_metrics(
                            intent=intent,
                            solved_values=solved,
                            gain_actual=gain_for_validation,
                            stage_analysis=(pipeline_result.solved.stage_analysis if pipeline_result.solved else None),
                        )
                        val_report = self._validator.validate(circuit_data, intent.to_dict(), solved_for_validation)
                        response.validation = val_report.to_dict()
                        response.pipeline = pipeline_result.to_dict()
                        response.template_id = pipeline_result.plan.matched_template_id if pipeline_result.plan else response.template_id

                if not val_report.passed and self._has_hard_constraint_errors(val_report):
                    failed_codes = self._extract_validation_error_codes(val_report)
                    alternative_bundle = self._attempt_alternative_design_for_unreasonable_constraints(
                        intent=intent,
                        failed_codes=failed_codes,
                    )
                    if alternative_bundle:
                        pipeline_result = alternative_bundle["pipeline_result"]
                        circuit_data = copy.deepcopy(pipeline_result.circuit.circuit_data) if pipeline_result.circuit else circuit_data
                        solved = dict(pipeline_result.solved.values) if pipeline_result.solved else solved
                        edit_log = self._apply_edits(circuit_data, intent.edit_operations)

                        gain_for_validation = self._resolve_gain_for_validation(
                            solved_values=solved,
                            fallback_gain=(pipeline_result.solved.actual_gain if pipeline_result.solved else None),
                        )
                        solved_for_validation = self._prepare_validation_metrics(
                            intent=intent,
                            solved_values=solved,
                            gain_actual=gain_for_validation,
                            stage_analysis=(pipeline_result.solved.stage_analysis if pipeline_result.solved else None),
                        )
                        val_report = self._validator.validate(circuit_data, intent.to_dict(), solved_for_validation)
                        response.validation = val_report.to_dict()
                        response.pipeline = pipeline_result.to_dict()
                        response.template_id = pipeline_result.plan.matched_template_id if pipeline_result.plan else response.template_id
                        response.suggestions.extend(alternative_bundle.get("relax_notes", []))

                if not val_report.passed and self._has_hard_constraint_errors(val_report):
                    failed_codes = self._extract_validation_error_codes(val_report)
                    self._record_feedback_event(
                        intent=intent,
                        stage="validate",
                        errors=[f"Hard constraints not satisfied: {', '.join(failed_codes)}"],
                        suggestions=["Dieu chinh edit operations hoac topology de dap ung hard constraints"],
                        metadata={"failed_codes": failed_codes, "flow": "modify"},
                    )
                    response.success = False
                    response.message = self._safe_error_response(
                        error_msg=f"Hard constraints not satisfied after regeneration: {', '.join(failed_codes)}",
                        stage="validate",
                        circuit_type=intent.circuit_type,
                        gain_target=intent.gain_target,
                        vcc=intent.vcc,
                        mode=mode,
                    )
                    response.processing_time_ms = (time.time() - start) * 1000
                    return response

                gain_for_validation = self._resolve_gain_for_validation(
                    solved_values=solved,
                    fallback_gain=(pipeline_result.solved.actual_gain if pipeline_result.solved else None),
                )
                physics_payload = self._run_physics_validation(
                    intent=intent,
                    solved_values=solved,
                    circuit_data=circuit_data,
                    gain_actual=gain_for_validation,
                )
                self._attach_physics_validation(response, physics_payload)
                if not physics_payload.get("passed", True):
                    local_fix = self._attempt_local_physics_autofix(
                        intent=intent,
                        solved_values=solved,
                        circuit_data=circuit_data,
                        gain_actual=gain_for_validation,
                        physics_payload=physics_payload,
                    )
                    if local_fix:
                        solved = local_fix["solved_values"]
                        circuit_data = local_fix["circuit_data"]
                        physics_payload = local_fix["physics_validation"]
                        self._attach_physics_validation(response, physics_payload)

                    retry_bundle = self._retry_pipeline_for_physics_failures(
                        intent=intent,
                        physics_payload=physics_payload,
                        max_attempts=3,
                    )
                    if retry_bundle:
                        pipeline_result = retry_bundle["pipeline_result"]
                        circuit_data = copy.deepcopy(pipeline_result.circuit.circuit_data) if pipeline_result.circuit else circuit_data
                        solved = dict(pipeline_result.solved.values) if pipeline_result.solved else {}
                        edit_log = self._apply_edits(circuit_data, intent.edit_operations)

                        gain_for_validation = self._resolve_gain_for_validation(
                            solved_values=solved,
                            fallback_gain=(pipeline_result.solved.actual_gain if pipeline_result.solved else None),
                        )
                        solved_for_validation = self._prepare_validation_metrics(
                            intent=intent,
                            solved_values=solved,
                            gain_actual=gain_for_validation,
                            stage_analysis=(pipeline_result.solved.stage_analysis if pipeline_result.solved else None),
                        )
                        val_report = self._validator.validate(circuit_data, intent.to_dict(), solved_for_validation)
                        response.validation = val_report.to_dict()
                        response.pipeline = pipeline_result.to_dict()
                        response.template_id = pipeline_result.plan.matched_template_id if pipeline_result.plan else response.template_id

                        physics_payload = self._run_physics_validation(
                            intent=intent,
                            solved_values=solved,
                            circuit_data=circuit_data,
                            gain_actual=gain_for_validation,
                        )
                        self._attach_physics_validation(response, physics_payload)

                    if not physics_payload.get("passed", True):
                        self._record_feedback_event(
                            intent=intent,
                            stage="physical_validate",
                            errors=list(physics_payload.get("errors", [])),
                            suggestions=list(physics_payload.get("suggestions", [])),
                            metadata={"flow": "modify"},
                        )
                        response.success = False
                        response.message = self._safe_error_response(
                            error_msg=(
                                "Physical validation failed: "
                                + "; ".join(physics_payload.get("errors", []))
                            ),
                            stage="physical_validate",
                            circuit_type=intent.circuit_type,
                            gain_target=intent.gain_target,
                            vcc=intent.vcc,
                            mode=mode,
                        )
                        response.processing_time_ms = (time.time() - start) * 1000
                        return response

                # Keep simulation schema consistent after edits.
                self._apply_simulation_requirements(intent, circuit_data)

                response.success = True
                response.circuit_data = circuit_data
                response.params = solved
                response.analysis = self._build_design_analysis(
                    intent=intent,
                    circuit_data=circuit_data,
                    solved_values=solved,
                    gain_formula=(pipeline_result.circuit.gain_formula if pipeline_result.circuit else ""),
                    gain_actual=(pipeline_result.solved.actual_gain if pipeline_result.solved else None),
                    stage_analysis=(pipeline_result.solved.stage_analysis if pipeline_result.solved else None),
                )
                simulation_feedback = self._evaluate_simulation_feedback(
                    intent=intent,
                    analysis=response.analysis,
                )
                self._attach_simulation_feedback(response, simulation_feedback)
                if not simulation_feedback.get("passed", True):
                    self._record_feedback_event(
                        intent=intent,
                        stage="simulation_feedback",
                        errors=list(simulation_feedback.get("errors", [])),
                        suggestions=list(simulation_feedback.get("suggestions", [])),
                        metadata={"flow": "modify"},
                    )
                    response.success = False
                    response.message = self._safe_error_response(
                        error_msg=(
                            "Simulation feedback gate failed: "
                            + "; ".join(simulation_feedback.get("errors", []))
                        ),
                        stage="simulation_feedback",
                        circuit_type=intent.circuit_type,
                        gain_target=intent.gain_target,
                        vcc=intent.vcc,
                        mode=mode,
                    )
                    response.processing_time_ms = (time.time() - start) * 1000
                    return response
                response.template_id = pipeline_result.plan.matched_template_id if pipeline_result.plan else ""
                response.pipeline = pipeline_result.to_dict()
                response.message = self._nlg.generate_modify_response(
                    intent=intent,
                    edit_log=edit_log,
                    circuit_data=circuit_data,
                    solved=solved,
                )
                response.message = self._safe_text(
                    response.message,
                    "✅ Da thuc thi yeu cau chinh sua, nhung NLG chua tra ve tom tat hop le.",
                )
                if assumption_notes:
                    response.suggestions.extend([f"Gia dinh bo sung: {note}" for note in assumption_notes])
            else:
                response.success = False
                response.message = self._safe_error_response(
                    error_msg=pipeline_result.error,
                    stage=pipeline_result.stage_reached,
                    circuit_type=intent.circuit_type,
                    gain_target=intent.gain_target,
                    vcc=intent.vcc,
                    mode=mode,
                )
        else:
            response.success = False
            response.needs_clarification = True
            response.message = (
                "⚠️ Vui lòng cho biết loại mạch bạn muốn chỉnh sửa.\n"
                "Ví dụ: \"Thêm tụ lọc vào mạch CE gain 20 dùng 12V\""
            )

        response.processing_time_ms = (time.time() - start) * 1000
        return response

    def _handle_validate(self, intent: CircuitIntent, response: ChatResponse, start: float, mode: LLMMode) -> ChatResponse:
        """Flow kiểm tra: tạo mạch → validate → báo cáo."""
        assumption_notes = self._apply_reasonable_defaults(intent)
        if intent.circuit_type and intent.circuit_type != "unknown":
            generation_intent = self._inject_feedback_hints(intent)
            spec = self._intent_to_spec(generation_intent)
            pipeline_result = self._ai_core.handle_spec(spec)

            if pipeline_result.success and pipeline_result.circuit:
                solved = pipeline_result.solved.values if pipeline_result.solved else {}
                gain_for_validation = self._resolve_gain_for_validation(
                    solved_values=solved,
                    fallback_gain=(pipeline_result.solved.actual_gain if pipeline_result.solved else None),
                )
                solved_for_validation = self._prepare_validation_metrics(
                    intent=intent,
                    solved_values=solved,
                    gain_actual=gain_for_validation,
                    stage_analysis=(pipeline_result.solved.stage_analysis if pipeline_result.solved else None),
                )
                val_report = self._validator.validate(
                    pipeline_result.circuit.circuit_data, intent.to_dict(), solved_for_validation,
                )

                if not val_report.passed and self._has_hard_constraint_errors(val_report):
                    failed_codes = self._extract_validation_error_codes(val_report)
                    retry_bundle = self._retry_pipeline_for_hard_constraints(
                        intent=intent,
                        failed_codes=failed_codes,
                        max_attempts=2,
                    )
                    if retry_bundle:
                        pipeline_result = retry_bundle["pipeline_result"]
                        solved = pipeline_result.solved.values if pipeline_result.solved else {}
                        val_report = retry_bundle["validation_report"]
                        response.pipeline = pipeline_result.to_dict()

                if not val_report.passed and self._has_hard_constraint_errors(val_report):
                    failed_codes = self._extract_validation_error_codes(val_report)
                    alternative_bundle = self._attempt_alternative_design_for_unreasonable_constraints(
                        intent=intent,
                        failed_codes=failed_codes,
                    )
                    if alternative_bundle:
                        pipeline_result = alternative_bundle["pipeline_result"]
                        solved = pipeline_result.solved.values if pipeline_result.solved else solved
                        val_report = alternative_bundle["validation_report"]
                        response.pipeline = pipeline_result.to_dict()
                        response.suggestions.extend(alternative_bundle.get("relax_notes", []))

                if not val_report.passed and self._has_hard_constraint_errors(val_report):
                    failed_codes = self._extract_validation_error_codes(val_report)
                    self._record_feedback_event(
                        intent=intent,
                        stage="validate",
                        errors=[f"Hard constraints not satisfied: {', '.join(failed_codes)}"],
                        suggestions=["Dieu chinh topology va tham so de dap ung hard constraints"],
                        metadata={"failed_codes": failed_codes, "flow": "validate"},
                    )
                    response.success = False
                    response.validation = val_report.to_dict()
                    response.message = self._safe_error_response(
                        error_msg=f"Hard constraints not satisfied after regeneration: {', '.join(failed_codes)}",
                        stage="validate",
                        circuit_type=intent.circuit_type,
                        gain_target=intent.gain_target,
                        vcc=intent.vcc,
                        mode=mode,
                    )
                    response.processing_time_ms = (time.time() - start) * 1000
                    return response

                gain_for_validation = self._resolve_gain_for_validation(
                    solved_values=solved,
                    fallback_gain=(pipeline_result.solved.actual_gain if pipeline_result.solved else None),
                )
                physics_payload = self._run_physics_validation(
                    intent=intent,
                    solved_values=solved,
                    circuit_data=pipeline_result.circuit.circuit_data,
                    gain_actual=gain_for_validation,
                )
                self._attach_physics_validation(response, physics_payload)
                if not physics_payload.get("passed", True):
                    local_fix = self._attempt_local_physics_autofix(
                        intent=intent,
                        solved_values=solved,
                        circuit_data=pipeline_result.circuit.circuit_data,
                        gain_actual=gain_for_validation,
                        physics_payload=physics_payload,
                    )
                    if local_fix:
                        solved = local_fix["solved_values"]
                        pipeline_result.circuit.circuit_data = local_fix["circuit_data"]
                        physics_payload = local_fix["physics_validation"]
                        self._attach_physics_validation(response, physics_payload)

                    retry_bundle = self._retry_pipeline_for_physics_failures(
                        intent=intent,
                        physics_payload=physics_payload,
                        max_attempts=3,
                    )
                    if retry_bundle:
                        pipeline_result = retry_bundle["pipeline_result"]
                        solved = pipeline_result.solved.values if pipeline_result.solved else {}
                        val_report = retry_bundle["validation_report"]
                        physics_payload = retry_bundle["physics_validation"]
                        response.pipeline = pipeline_result.to_dict()
                        self._attach_physics_validation(response, physics_payload)

                    if not physics_payload.get("passed", True):
                        self._record_feedback_event(
                            intent=intent,
                            stage="physical_validate",
                            errors=list(physics_payload.get("errors", [])),
                            suggestions=list(physics_payload.get("suggestions", [])),
                            metadata={"flow": "validate"},
                        )
                        response.success = False
                        response.validation = val_report.to_dict()
                        response.message = self._safe_error_response(
                            error_msg=(
                                "Physical validation failed: "
                                + "; ".join(physics_payload.get("errors", []))
                            ),
                            stage="physical_validate",
                            circuit_type=intent.circuit_type,
                            gain_target=intent.gain_target,
                            vcc=intent.vcc,
                            mode=mode,
                        )
                        response.processing_time_ms = (time.time() - start) * 1000
                        return response

                response.validation = val_report.to_dict()
                response.success = True
                response.circuit_data = pipeline_result.circuit.circuit_data
                response.params = solved
                self._apply_simulation_requirements(intent, response.circuit_data)
                response.analysis = self._build_design_analysis(
                    intent=intent,
                    circuit_data=pipeline_result.circuit.circuit_data,
                    solved_values=solved,
                    gain_formula=pipeline_result.circuit.gain_formula,
                    gain_actual=(pipeline_result.solved.actual_gain if pipeline_result.solved else None),
                    stage_analysis=(pipeline_result.solved.stage_analysis if pipeline_result.solved else None),
                )
                simulation_feedback = self._evaluate_simulation_feedback(
                    intent=intent,
                    analysis=response.analysis,
                )
                self._attach_simulation_feedback(response, simulation_feedback)
                if not simulation_feedback.get("passed", True):
                    self._record_feedback_event(
                        intent=intent,
                        stage="simulation_feedback",
                        errors=list(simulation_feedback.get("errors", [])),
                        suggestions=list(simulation_feedback.get("suggestions", [])),
                        metadata={"flow": "validate"},
                    )
                    response.success = False
                    response.message = self._safe_error_response(
                        error_msg=(
                            "Simulation feedback gate failed: "
                            + "; ".join(simulation_feedback.get("errors", []))
                        ),
                        stage="simulation_feedback",
                        circuit_type=intent.circuit_type,
                        gain_target=intent.gain_target,
                        vcc=intent.vcc,
                        mode=mode,
                    )
                    response.processing_time_ms = (time.time() - start) * 1000
                    return response
                response.message = self._nlg.generate_validation_report(val_report)
                response.message = self._safe_text(
                    response.message,
                    "✅ Da kiem tra thanh cong, nhung NLG chua tra ve bao cao hop le.",
                )
                if assumption_notes:
                    response.suggestions.extend([f"Gia dinh bo sung: {note}" for note in assumption_notes])
            else:
                response.success = False
                response.message = self._safe_error_response(
                    error_msg=pipeline_result.error,
                    stage=pipeline_result.stage_reached,
                    circuit_type=intent.circuit_type,
                    gain_target=intent.gain_target,
                    vcc=intent.vcc,
                    mode=mode,
                )
        else:
            response.success = False
            response.needs_clarification = True
            response.message = "⚠️ Vui lòng cho biết loại mạch bạn muốn kiểm tra."

        response.processing_time_ms = (time.time() - start) * 1000
        return response

    def _handle_explain(self, intent: CircuitIntent, response: ChatResponse, start: float, mode: LLMMode) -> ChatResponse:
        """Flow giải thích: dùng LLM role chung theo mode hiện tại."""
        explanation = self._reasoning_explain(intent, mode=mode)
        if explanation:
            response.success = True
            response.message = explanation
        else:
            response.success = True
            response.message = self._rule_based_explain(intent)

        response.processing_time_ms = (time.time() - start) * 1000
        return response

    # ------------------------------------------------------------------ #
    #  Edit apply helpers
    # ------------------------------------------------------------------ #

    def _apply_edits(self, circuit_data: dict, edit_ops: list) -> List[str]:
        """Apply edit operations lên circuit_data. Trả về edit log."""
        log = []
        components = circuit_data.get("components", [])

        for op in edit_ops:
            action = op.action
            target = op.target
            params = op.params

            if action == "add_component":
                new_comp = {
                    "id": target or f"NEW_{len(components)+1}",
                    "type": params.get("type", "RESISTOR").upper(),
                    "parameters": {},
                }
                if "value" in params:
                    # Determine param key from type
                    comp_type = new_comp["type"]
                    if "RESIST" in comp_type or "trở" in str(params.get("type", "")):
                        new_comp["parameters"]["resistance"] = params["value"]
                    elif "CAPAC" in comp_type or "tụ" in str(params.get("type", "")):
                        new_comp["parameters"]["capacitance"] = params["value"]
                    else:
                        new_comp["parameters"]["value"] = params["value"]
                components.append(new_comp)
                log.append(f"Thêm {new_comp['id']} ({new_comp['type']})")

            elif action == "remove_component":
                before = len(components)
                components[:] = [c for c in components if c.get("id", "").upper() != target.upper()]
                if len(components) < before:
                    log.append(f"Xóa linh kiện {target}")
                    # Remove from nets
                    for net in circuit_data.get("nets", []):
                        conns = net.get("connections", [])
                        net["connections"] = [c for c in conns if not (isinstance(c, list) and c and c[0].upper() == target.upper())]
                else:
                    log.append(f"Không tìm thấy {target} để xóa")

            elif action == "change_value":
                for comp in components:
                    if comp.get("id", "").upper() == target.upper():
                        new_val = params.get("new_value")
                        if new_val is not None:
                            p = comp.get("parameters", {})
                            # Auto-detect param key
                            for key in ["resistance", "capacitance", "inductance", "voltage"]:
                                if key in p:
                                    old_val = p[key]
                                    p[key] = new_val
                                    log.append(f"Đổi {target}.{key}: {old_val} → {new_val}")
                                    break
                            else:
                                p["value"] = new_val
                                log.append(f"Đổi {target}.value → {new_val}")
                        break

            elif action == "replace_component":
                for i, comp in enumerate(components):
                    if comp.get("id", "").upper() == target.upper():
                        new_type = params.get("new_type", comp.get("type"))
                        components[i] = {
                            "id": target,
                            "type": str(new_type).upper(),
                            "parameters": params.get("new_params", {}),
                        }
                        log.append(f"Thay thế {target} bằng {new_type}")
                        break

        circuit_data["components"] = components
        return log

    def get_supported_circuits(self) -> List[Dict[str, Any]]:
        """Trả về danh sách các loại mạch hỗ trợ."""
        templates = self._ai_core.list_templates()
        return templates

    def get_supported_families(self) -> List[str]:
        """Trả về danh sách families."""
        return self._ai_core.get_supported_families()



    # ── LLM-powered helpers ──

    @staticmethod
    def _build_llm_payload(task: str, input_data: Dict[str, Any], output_format: str) -> Dict[str, Any]:
        return build_llm_payload(task=task, input_data=input_data, output_format=output_format)

    def _domain_check(self, user_text: str, mode: LLMMode) -> Optional[str]:
        """
        Dùng LLM role chung kiểm tra nhanh: câu hỏi có liên quan điện tử không?
        Trả về message từ chối nếu off-topic, hoặc None nếu OK.
        """
        if not self._electronics_domain_only:
            return None
        if not self._router.is_available(LLMRole.GENERAL, mode=mode):
            return None  # skip nếu không có API key

        system = (
            "Ban la bo phan loai cau hoi cho he thong thiet ke mach dien tu. "
            "Tra ve duy nhat JSON theo schema domain.v1: {\"sv\":\"domain.v1\",\"ok\":true|false}. "
            "Dat ok=true chi khi cau hoi lien quan electronics, linh kien, topology, simulation hoac PCB."
        )
        payload = self._build_llm_payload(
            task="domain.check.v1",
            input_data={
                "dm": "electronics",
                "txt": user_text,
            },
            output_format="json",
        )
        result = self._router.chat_json(
            LLMRole.GENERAL,
            mode=mode,
            system=system,
            user_content=payload,
            response_model=DomainCheckOutputV1,
            max_schema_retries=2,
        )
        if result and result.get("ok") is False:
            return (
                "⚠️ Xin lỗi, tôi chỉ hỗ trợ các câu hỏi về **thiết kế mạch** "
                "(khuếch đại,BJT,mosfet, op-amp, ...). "
                "Vui lòng đặt câu hỏi liên quan đến mạch điện!"
            )
        return None

    def _smart_clarification(self, user_text: str, missing: List[str], mode: LLMMode) -> Optional[str]:
        """
        Dùng LLM role chung để sinh câu hỏi làm rõ thông minh.
        Trả về message hoặc None (fallback về template NLG).
        """
        if not self._router.is_available(LLMRole.GENERAL, mode=mode):
            return None

        system = (
            "Ban la tro ly thiet ke mach dien tu. "
            "Dung payload de dat cau hoi bo sung thong tin con thieu. "
            "Toi da 4 cau, giong dieu than thien, co vi du ngan. "
            "Tra ve markdown text, khong JSON."
        )
        payload = self._build_llm_payload(
            task="chat.c.v1",
            input_data={
                "txt": user_text,
                "miss": missing,
                "response_contract": {
                    "language": "vi",
                    "format": "markdown",
                    "max_sentences": 4,
                    "must_include_examples": True,
                },
            },
            output_format="md",
        )
        return self._router.chat_text(
            LLMRole.GENERAL, mode=mode, system=system, user_content=payload,
        )

    def _reasoning_fallback(
        self, intent: CircuitIntent, error_msg: str, mode: LLMMode,
    ) -> Optional[str]:
        """
        Khi AI Core rule-based thất bại, dùng LLM role chung theo mode hiện tại
        để suy luận trực tiếp từ intent.
        """
        if not self._router.is_available(LLMRole.GENERAL, mode=mode):
            return None

        system = (
            "Ban la ky su analog. Rule-based planner khong tim duoc template phu hop. "
            "Dung payload de tao phuong an best-effort bang tieng Viet markdown. "
            "Tuan thu response_contract trong payload va neu thieu du lieu thi neu ro gia dinh."
        )
        payload = self._build_llm_payload(
            task="chat.rf.v1",
            input_data={
                "txt": intent.raw_text,
                "err": error_msg,
                "it": {
                    "ty": intent.intent_type,
                    "ct": intent.circuit_type,
                    "tp": intent.topology,
                    "gn": intent.gain_target,
                    "vc": intent.vcc,
                    "fq": intent.frequency,
                },
                "response_contract": {
                    "language": "vi",
                    "format": "markdown",
                    "sections": [
                        "He phuong trinh khuech dai",
                        "Chuc nang",
                        "Giai phap",
                        "Tinh toan",
                        "Thong so ky thuat",
                        "Ket qua",
                    ],
                    "forbid_emoji": True,
                    "assumption_policy": "Neu thieu du lieu thi neu ro gia dinh",
                },
            },
            output_format="md",
        )
        logger.info(f"[LLM fallback] mode={mode.value}, intent={intent.circuit_type}, error={error_msg}")
        return self._router.chat_text(
            LLMRole.GENERAL, mode=mode, system=system, user_content=payload,
            max_tokens=8192,
        )

    def _reasoning_explain(self, intent: CircuitIntent, mode: LLMMode) -> Optional[str]:
        """Dùng LLM role chung giải thích mạch điện tử."""
        if not self._router.is_available(LLMRole.GENERAL, mode=mode):
            return None

        system = (
            "Ban la ky su thiet ke mach dien tu. "
            "Dung payload de giai thich mach theo response_contract, bang tieng Viet markdown, "
            "tap trung vao thong tin giup nguoi dung hieu va ap dung nhanh."
        )
        payload = self._build_llm_payload(
            task="chat.rx.v1",
            input_data={
                "txt": intent.raw_text,
                "ct": intent.circuit_type or "unknown",
                "ty": intent.intent_type,
                "response_contract": {
                    "language": "vi",
                    "format": "markdown",
                    "sections": [
                        "Nguyen ly hoat dong",
                        "Chuc nang tung linh kien",
                        "Cong thuc va tinh toan",
                        "Uu nhuoc diem",
                        "Ung dung thuc te",
                    ],
                },
            },
            output_format="md",
        )
        return self._router.chat_text(
            LLMRole.GENERAL, mode=mode, system=system, user_content=payload,
            max_tokens=4096,
        )

    def _resolve_chat_mode(self, mode: Optional[str]) -> LLMMode:
        if mode:
            value = str(mode).strip().lower()
            if value in {"air", "fast"}:
                return LLMMode.FAST
            if value == "think":
                return LLMMode.THINK
            if value == "pro":
                return LLMMode.PRO
            if value == "ultra":
                return LLMMode.ULTRA
        default_mode = (
            os.getenv("GoogleCloud_Default_Mode")
            or os.getenv("Google_Cloud_Default_Mode")
            or os.getenv("DEFAULT_MODE")
            or "fast"
        ).strip().lower()
        mode_alias = {
            "air": LLMMode.FAST,
            "fast": LLMMode.FAST,
            "think": LLMMode.THINK,
            "pro": LLMMode.PRO,
            "ultra": LLMMode.ULTRA,
        }
        return mode_alias.get(default_mode, LLMMode.FAST)

    @staticmethod
    def _normalize_intent_type(intent_type: str) -> Tuple[str, bool]:
        """Chuan hoa intent type de dam bao request stage xac dinh dung/sai ro rang."""
        allowed = {"create", "modify", "validate", "explain", "optimize", "compare"}
        value = (intent_type or "").strip().lower()
        if value in allowed:
            return value, False
        return "create", True

    @staticmethod
    def _safe_text(text: Optional[str], fallback: str) -> str:
        """Dam bao response stage luon tra ve text hop le, neu khong thi fallback."""
        if isinstance(text, str) and text.strip():
            return text
        return fallback

    def _safe_error_response(
        self,
        *,
        error_msg: str,
        stage: str,
        circuit_type: str,
        gain_target: Optional[float],
        vcc: Optional[float],
        mode: LLMMode,
    ) -> str:
        """Sinh error message va fallback khi NLG khong tra ve noi dung hop le."""
        generated = self._nlg.generate_error_response(
            error_msg=error_msg,
            stage=stage,
            circuit_type=circuit_type,
            gain_target=gain_target,
            vcc=vcc,
            mode=mode,
        )
        return self._safe_text(generated, f"❌ Loi tai buoc '{stage}': {error_msg}")

    def _apply_reasonable_defaults(self, intent: CircuitIntent) -> List[str]:
        """Apply conservative defaults for incomplete but reasonable design requests."""
        notes: List[str] = []
        raw_text = (intent.raw_text or "").lower()

        if not intent.hard_constraints.get("gain_min") and not intent.hard_constraints.get("gain_max"):
            range_match = re.search(
                r"(?:tong\s*)?gain\s*(?:trong\s*khoang|khoảng|tu|từ|xap\s*xi|xấp\s*xỉ)?\s*"
                r"(-?[0-9]+(?:\.[0-9]+)?)\s*(?:-|den|đến|to|~)\s*(-?[0-9]+(?:\.[0-9]+)?)",
                raw_text,
                re.IGNORECASE,
            )
            if range_match:
                try:
                    g1 = float(range_match.group(1))
                    g2 = float(range_match.group(2))
                    g_min = min(g1, g2)
                    g_max = max(g1, g2)
                    intent.hard_constraints["gain_min"] = g_min
                    intent.hard_constraints["gain_max"] = g_max
                    notes.append(f"Suy luan range gain tu prompt: {g_min:g}..{g_max:g}")
                except (ValueError, TypeError):
                    pass

        if (
            intent.circuit_type == "multi_stage"
            and intent.hard_constraints.get("direct_coupling_required")
            and "ce" in raw_text
            and "cc" in raw_text
        ):
            if "prefer_ce_cc_direct" not in intent.extra_requirements:
                intent.extra_requirements.append("prefer_ce_cc_direct")

        zout_max = intent.hard_constraints.get("output_impedance_max_ohm")
        if isinstance(zout_max, (int, float)) and float(zout_max) <= 100.0:
            if not intent.output_buffer:
                intent.output_buffer = True
                notes.append(f"Zout yeu cau <= {float(zout_max):g} ohm, tu bat output buffer")
            if "low_output_impedance" not in intent.extra_requirements:
                intent.extra_requirements.append("low_output_impedance")

        ctype = (intent.circuit_type or "").strip().lower()
        if not isinstance(intent.gain_target, (int, float)) or intent.gain_target <= 0:
            default_gain = 10.0
            if ctype in {"common_emitter", "common_source", "common_base", "common_collector"}:
                default_gain = 20.0
            elif ctype in {"inverting", "non_inverting", "differential", "instrumentation"}:
                default_gain = 5.0
            elif ctype in {"multi_stage", "darlington"}:
                if isinstance(intent.hard_constraints.get("gain_min"), (int, float)) and isinstance(intent.hard_constraints.get("gain_max"), (int, float)):
                    default_gain = (float(intent.hard_constraints["gain_min"]) + float(intent.hard_constraints["gain_max"])) / 2.0
                else:
                    default_gain = 24.0
            intent.gain_target = float(default_gain)
            notes.append(f"Thieu gain, he thong tu gia dinh gain_target={default_gain:g}")

        if not isinstance(intent.vcc, (int, float)) or intent.vcc <= 0:
            default_vcc = 12.0
            if intent.supply_mode == "single_supply" or intent.device_preference == "opamp":
                default_vcc = 5.0
            intent.vcc = float(default_vcc)
            notes.append(f"Thieu VCC, he thong tu gia dinh VCC={default_vcc:g}V")

        if not intent.frequency and any(tag in (intent.raw_text or "").lower() for tag in ["ac", "sin", "transient"]):
            intent.frequency = 1000.0
            notes.append("Thieu tan so kich, he thong tu gia dinh f=1kHz")

        return notes

    def _attempt_alternative_design_for_unreasonable_constraints(
        self,
        *,
        intent: CircuitIntent,
        failed_codes: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Try generating a feasible alternative by relaxing conflicting hard constraints."""
        relaxed = copy.deepcopy(intent)
        constraints = dict(relaxed.hard_constraints or {})
        relax_notes: List[str] = []

        if "HARD_GAIN_MAX" in failed_codes and "gain_max" in constraints:
            gain_max = constraints.pop("gain_max")
            if isinstance(gain_max, (int, float)):
                relaxed.gain_target = min(float(relaxed.gain_target or gain_max), float(gain_max))
                relax_notes.append(f"Rang buoc gain_max={gain_max:g} khong kha thi, de xuat muc gain gan nhat")

        if "HARD_GAIN_MIN" in failed_codes and "gain_min" in constraints:
            gain_min = constraints.pop("gain_min")
            if isinstance(gain_min, (int, float)):
                relaxed.gain_target = max(float(relaxed.gain_target or gain_min), float(gain_min))
                relax_notes.append(f"Rang buoc gain_min={gain_min:g} khong kha thi, de xuat muc gain gan nhat")

        if "HARD_VCC_MAX" in failed_codes and "vcc_max" in constraints:
            vcc_max = constraints.pop("vcc_max")
            if isinstance(vcc_max, (int, float)):
                if isinstance(relaxed.vcc, (int, float)):
                    relaxed.vcc = min(float(relaxed.vcc), float(vcc_max))
                else:
                    relaxed.vcc = float(vcc_max)
                relax_notes.append(f"Rang buoc VCC toi da {vcc_max:g}V duoc ap vao thiet ke thay the")

        if "HARD_ZOUT_MAX" in failed_codes:
            relaxed.output_buffer = True
            if "low_output_impedance" not in relaxed.extra_requirements:
                relaxed.extra_requirements.append("low_output_impedance")
            if "output_impedance_max_ohm" in constraints:
                try:
                    original_zout = float(constraints.get("output_impedance_max_ohm"))
                    relaxed_zout = max(original_zout * 1.8, 80.0)
                    constraints["output_impedance_max_ohm"] = relaxed_zout
                    relax_notes.append(
                        f"Rang buoc Zout <= {original_zout:g} ohm qua chat, de xuat phuong an kha thi voi Zout <= {relaxed_zout:g} ohm"
                    )
                except (TypeError, ValueError):
                    constraints.pop("output_impedance_max_ohm", None)
                    relax_notes.append("Khong the dam bao hard Zout ban dau, de xuat phuong an output buffer toi uu")
            else:
                relax_notes.append("Them tang buffer dau ra de cai thien Zout")

        if "HARD_DIRECT_COUPLING" in failed_codes and constraints.get("direct_coupling_required"):
            constraints.pop("direct_coupling_required", None)
            relax_notes.append("Cho phep phuong an coupling thay the do direct coupling khong kha thi")

        if not relax_notes:
            return None

        relaxed.raw_text = (
            f"{relaxed.raw_text}. Neu rang buoc ban dau mau thuan, "
            "uu tien thiet ke kha thi vat ly va de xuat phuong an gan nhat."
        )

        attempts: List[Tuple[CircuitIntent, List[str]]] = []
        primary = copy.deepcopy(relaxed)
        primary.hard_constraints = dict(constraints)
        attempts.append((primary, list(relax_notes)))

        fallback = copy.deepcopy(relaxed)
        fallback_constraints = dict(constraints)
        fallback_notes = list(relax_notes)
        dropped_any = False

        if "HARD_ZOUT_MAX" in failed_codes and "output_impedance_max_ohm" in fallback_constraints:
            prev = fallback_constraints.pop("output_impedance_max_ohm", None)
            if isinstance(prev, (int, float)):
                fallback_notes.append(
                    f"Khong the dam bao hard Zout <= {float(prev):g} ohm, chuyen sang phuong an kha thi va uu tien output buffer"
                )
                dropped_any = True

        if "HARD_GAIN_MIN" in failed_codes and "gain_min" in fallback_constraints:
            prev = fallback_constraints.pop("gain_min", None)
            if isinstance(prev, (int, float)):
                fallback_notes.append(
                    f"Khong the dam bao hard gain_min={float(prev):g}, de xuat muc gain toi uu gan nhat"
                )
                dropped_any = True

        if "HARD_GAIN_MAX" in failed_codes and "gain_max" in fallback_constraints:
            prev = fallback_constraints.pop("gain_max", None)
            if isinstance(prev, (int, float)):
                fallback_notes.append(
                    f"Khong the dam bao hard gain_max={float(prev):g}, de xuat muc gain toi uu gan nhat"
                )
                dropped_any = True

        if "HARD_DIRECT_COUPLING" in failed_codes and "direct_coupling_required" in fallback_constraints:
            fallback_constraints.pop("direct_coupling_required", None)
            fallback_notes.append("Khong the duy tri hard direct coupling, de xuat phuong an coupling kha thi")
            dropped_any = True

        if dropped_any:
            fallback.hard_constraints = fallback_constraints
            attempts.append((fallback, fallback_notes))

        best_effort_bundle: Optional[Dict[str, Any]] = None

        for candidate, notes in attempts:
            spec = self._intent_to_spec(candidate)
            retry_result = self._ai_core.handle_spec(spec)
            if not retry_result.success or not retry_result.circuit:
                continue

            retry_solved_values = retry_result.solved.values if retry_result.solved else {}
            retry_gain = self._resolve_gain_for_validation(
                solved_values=retry_solved_values,
                fallback_gain=(retry_result.solved.actual_gain if retry_result.solved else None),
            )
            retry_metrics = self._prepare_validation_metrics(
                intent=candidate,
                solved_values=retry_solved_values,
                gain_actual=retry_gain,
                stage_analysis=(retry_result.solved.stage_analysis if retry_result.solved else None),
            )
            retry_report = self._validator.validate(
                retry_result.circuit.circuit_data,
                candidate.to_dict(),
                retry_metrics,
            )
            if not retry_report.passed and self._has_hard_constraint_errors(retry_report):
                continue

            retry_physics = self._run_physics_validation(
                intent=candidate,
                solved_values=retry_solved_values,
                circuit_data=retry_result.circuit.circuit_data,
                gain_actual=retry_gain,
            )
            bundle = {
                "pipeline_result": retry_result,
                "validation_report": retry_report,
                "physics_validation": retry_physics,
                "relax_notes": [f"De xuat thay the: {note}" for note in notes],
                "intent": candidate,
            }
            if retry_physics.get("passed", False):
                return bundle

            if best_effort_bundle is None:
                best_effort_bundle = bundle

        if best_effort_bundle:
            best_effort_bundle["relax_notes"] = list(best_effort_bundle.get("relax_notes", [])) + [
                "De xuat thay the: Da tim thay cau hinh giam vi pham hard constraints, dang uu tien xu ly can bang vat ly"
            ]
            return best_effort_bundle

        return None

    def _rule_based_explain(self, intent: CircuitIntent) -> str:
        """Fallback explanation when LLM is unavailable."""
        topo = intent.circuit_type or "mạch khuếch đại"
        gain_text = f"{intent.gain_target:g}" if isinstance(intent.gain_target, (int, float)) else "chưa xác định"
        vcc_text = f"{intent.vcc:g}V" if isinstance(intent.vcc, (int, float)) else "chưa xác định"
        focus_components = ", ".join(intent.explain_focus_components) if intent.explain_focus_components else "R1, R2, RC, RE, CIN, COUT"
        detail_line = (
            f"- Mức giải thích: **chi tiết**, tập trung vào: **{focus_components}**.\n"
            if intent.explain_detail_level == "detailed"
            else ""
        )

        return (
            f"### Giải thích nhanh: {topo}\n\n"
            f"- Mục tiêu gain: **{gain_text}**\n"
            f"- Nguồn cấp: **{vcc_text}**\n"
            f"{detail_line}"
            "- Nguyên lý: tầng khuếch đại dùng linh kiện chủ động để biến thiên tín hiệu vào thành tín hiệu ra lớn hơn.\n"
            "- Với mạch CE điển hình: transistor làm việc ở vùng tuyến tính, điện trở phân cực xác lập điểm Q,"
            " và tụ ghép/tụ bypass giúp tối ưu đáp tuyến AC.\n"
            "- Vai trò linh kiện chính:"
            " R1/R2 đặt thiên áp base, RC quyết định swing điện áp và gain gần đúng, RE ổn định nhiệt và điểm làm việc,"
            " CIN chặn DC đầu vào, COUT chặn DC đầu ra."
        )

    def _intent_to_spec(self, intent: CircuitIntent) -> UserSpec:
        """Chuyển CircuitIntent → UserSpec cho AI Core (không qua text)."""
        requested_blocks = self._infer_stage_blocks_from_text(intent.raw_text)
        hard_constraints = intent.hard_constraints or {}
        coupling_pref = (
            "direct"
            if hard_constraints.get("direct_coupling_required")
            else self._infer_coupling_preference_from_text(intent.raw_text)
        )

        resolved_gain = intent.gain_target
        gain_min = hard_constraints.get("gain_min")
        gain_max = hard_constraints.get("gain_max")
        if not isinstance(resolved_gain, (int, float)) and isinstance(gain_min, (int, float)) and isinstance(gain_max, (int, float)):
            resolved_gain = (float(gain_min) + float(gain_max)) / 2.0
        elif not isinstance(resolved_gain, (int, float)) and isinstance(gain_min, (int, float)):
            resolved_gain = float(gain_min)

        return UserSpec(
            circuit_type=intent.circuit_type,
            gain=resolved_gain,
            vcc=intent.vcc,
            frequency=intent.frequency,
            input_channels=intent.input_channels,
            channel_inputs=dict(intent.channel_inputs),
            voltage_range=dict(intent.voltage_range),
            high_cmr=intent.high_cmr,
            input_mode=intent.input_mode,
            output_buffer=intent.output_buffer,
            power_output=intent.power_output,
            supply_mode=intent.supply_mode,
            coupling_preference=coupling_pref,
            device_preference=intent.device_preference,
            requested_stage_blocks=requested_blocks,
            extra_requirements=list(intent.extra_requirements),
            confidence=intent.confidence,
            source=intent.source,
            raw_text=intent.raw_text,
        )

    @staticmethod
    def _infer_stage_blocks_from_text(text: str) -> List[str]:
        raw = (text or "").lower()
        compact = re.sub(r"[^a-z]", "", raw)

        explicit_pairs = {
            "cscd": ["cs_block", "cd_block"],
            "cecc": ["ce_block", "cc_block"],
            "cecb": ["ce_block", "cb_block"],
            "cscg": ["cs_block", "cg_block"],
        }
        for key, blocks in explicit_pairs.items():
            if key in compact:
                return blocks

        token_to_block = {
            "ce": "ce_block",
            "cb": "cb_block",
            "cc": "cc_block",
            "cs": "cs_block",
            "cd": "cd_block",
            "cg": "cg_block",
        }
        tokens = re.findall(r"\b(ce|cb|cc|cs|cd|cg)\b", raw)
        ordered: List[str] = []
        for t in tokens:
            block = token_to_block[t]
            if block not in ordered:
                ordered.append(block)
        return ordered if len(ordered) >= 2 else []

    @staticmethod
    def _infer_coupling_preference_from_text(text: str) -> str:
        raw = (text or "").lower()
        if re.search(
            r"direct\s*coupl|gh[ée]p\s*tr[ựu]c\s*ti[ếe]p|kh[ôo]ng\s*(?:d[ùu]ng\s*)?t[ụu]\s*gh[ée]p|kh[ôo]ng\s*d[ùu]ng\s*t[ụu]\s*coupling",
            raw,
            re.IGNORECASE,
        ):
            return "direct"
        if re.search(r"transformer\s*coupl|gh[ée]p\s*bi[ếe]n\s*[áa]p", raw, re.IGNORECASE):
            return "transformer"
        if re.search(r"capacitor\s*coupl|ac\s*coupl|gh[ée]p\s*t[ụu]", raw, re.IGNORECASE):
            return "capacitor"
        return "auto"

    def _build_design_analysis(
        self,
        intent: CircuitIntent,
        circuit_data: Dict[str, Any],
        solved_values: Dict[str, float],
        gain_formula: str,
        gain_actual: Optional[float],
        stage_analysis: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Build structured engineering payload for API consumers."""
        input_channels = max(intent.input_channels, self._estimate_input_channels(circuit_data, intent.raw_text))
        v_range = dict(intent.voltage_range) if intent.voltage_range else self._estimate_voltage_range(intent, circuit_data)

        reported_gain = gain_actual
        composition_plan = circuit_data.get("composition_plan") if isinstance(circuit_data, dict) else None
        if isinstance(composition_plan, dict):
            target_gain = composition_plan.get("target_gain")
            if reported_gain is None and isinstance(target_gain, (int, float)) and abs(float(target_gain)) > 1.0:
                reported_gain = float(target_gain)

            stages = composition_plan.get("stages")
            if isinstance(stages, list):
                inversion_count = 0
                for stage in stages:
                    if not isinstance(stage, dict):
                        continue
                    block_name = str(stage.get("block", "")).strip().lower()
                    if any(tag in block_name for tag in ("ce", "cs", "cb", "cg", "inverting")):
                        inversion_count += 1

                if inversion_count % 2 == 1 and isinstance(reported_gain, (int, float)):
                    reported_gain = -abs(float(reported_gain))
                elif inversion_count % 2 == 0 and isinstance(reported_gain, (int, float)):
                    reported_gain = abs(float(reported_gain))

        topology_metrics = ParameterSolver().analyze_topology(
            family=intent.circuit_type,
            solved_values=solved_values,
            gain_actual=reported_gain,
            frequency_hz=intent.frequency,
            supply_mode=intent.supply_mode,
            vcc=intent.vcc,
            stage_analysis=stage_analysis,
        )
        z_in = topology_metrics.get("input_impedance_ohm")
        z_out = topology_metrics.get("output_impedance_ohm")
        bandwidth_hz = topology_metrics.get("bandwidth_hz")
        stage_table = topology_metrics.get("stage_table") or []

        if stage_table:
            stage_count = len(stage_table)
            recommended_blocks = [str(s.get("type", "stage")).lower() for s in stage_table]
        else:
            stage_count = 2 if intent.circuit_type in {"multi_stage", "darlington"} else 1
            recommended_blocks = ["single_stage"] if stage_count == 1 else ["gain_stage", "buffer_stage"]

        simulation = self._maybe_auto_simulation(circuit_data)

        return {
            "parameters": {
                "circuit_type": intent.circuit_type,
                "gain_target": intent.gain_target,
                "gain_actual": reported_gain,
                "frequency_hz": intent.frequency,
                "bandwidth_hz": bandwidth_hz,
                "vcc": intent.vcc,
                "input_impedance_ohm": z_in,
                "output_impedance_ohm": z_out,
            },
            "input_output": {
                "input_signal": {
                    "mode": intent.input_mode,
                    "channels": input_channels,
                    "channel_parameters": intent.channel_inputs,
                    "parameters": {
                        "source_voltage_range": v_range,
                        "recommended_source_impedance_ohm": z_in,
                    },
                },
                "output_signal": {
                    "buffered": intent.output_buffer,
                    "power_output": intent.power_output,
                    "voltage_range": v_range,
                    "target_load_impedance_ohm": z_out,
                },
            },
            "voltage_range": v_range,
            "cascading": {
                "enabled": stage_count > 1,
                "stage_count": stage_count,
                "recommended_blocks": recommended_blocks,
                "interstage_impedance_guidance": (
                    "Dam bao Zin(tang sau) >= 10x Zout(tang truoc) de giam suy hao bien do."
                ),
                "optimization_suggestions": [
                    "Phan bo gain theo tung tang de tranh saturation o tang dau.",
                    "Thiet ke matching tro khang lien tang theo ti le Zin/Zout >= 10.",
                    "Kiem tra cuc tri bien do tung tang de toi uu meo va noise.",
                ],
                "stage_table": stage_table,
            },
            "equations": {
                "gain": {
                    "symbolic": gain_formula,
                    "substitution": self._render_gain_substitution(gain_formula, solved_values),
                    "computed_gain": reported_gain,
                    "target_gain": intent.gain_target,
                }
            },
            "simulation": simulation,
        }

    def _prepare_validation_metrics(
        self,
        intent: CircuitIntent,
        solved_values: Dict[str, float],
        gain_actual: Optional[float],
        stage_analysis: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, float]:
        """Build enriched metrics dict so validator can check hard constraints reliably."""
        enriched = dict(solved_values or {})
        if isinstance(gain_actual, (int, float)):
            enriched["actual_gain"] = float(gain_actual)

        topology_metrics = ParameterSolver().analyze_topology(
            family=intent.circuit_type,
            solved_values=enriched,
            gain_actual=(float(gain_actual) if isinstance(gain_actual, (int, float)) else None),
            frequency_hz=intent.frequency,
            supply_mode=intent.supply_mode,
            vcc=intent.vcc,
            stage_analysis=stage_analysis,
        )
        z_out = topology_metrics.get("output_impedance_ohm")
        if isinstance(z_out, (int, float)):
            enriched["output_impedance_ohm"] = float(z_out)
        return enriched

    @staticmethod
    def _resolve_gain_for_validation(
        solved_values: Dict[str, float],
        fallback_gain: Optional[float],
    ) -> Optional[float]:
        val = solved_values.get("actual_gain") if isinstance(solved_values, dict) else None
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(fallback_gain, (int, float)):
            return float(fallback_gain)
        return None

    @staticmethod
    def _attach_physics_validation(response: ChatResponse, physics_payload: Dict[str, Any]) -> None:
        """Gan ket qua physical validation vao response va validation payload tong."""
        response.physics_validation = physics_payload
        if response.validation is None:
            response.validation = {}
        if isinstance(response.validation, dict):
            response.validation["physics"] = physics_payload

    @staticmethod
    def _attach_simulation_feedback(response: ChatResponse, payload: Dict[str, Any]) -> None:
        """Gan ket qua simulation feedback gate vao validation payload tong."""
        if response.validation is None:
            response.validation = {}
        if isinstance(response.validation, dict):
            response.validation["simulation_feedback"] = payload

    def _evaluate_simulation_feedback(
        self,
        intent: CircuitIntent,
        analysis: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Danh gia ket qua simulation va chan ket qua lech yeu cau nghiem trong."""
        if not self._enforce_simulation_feedback_gate:
            return {
                "enabled": False,
                "passed": True,
                "errors": [],
                "suggestions": ["Simulation feedback gate disabled"],
                "metrics": {},
            }

        sim = (analysis or {}).get("simulation") if isinstance(analysis, dict) else None
        if not isinstance(sim, dict):
            return {
                "enabled": True,
                "passed": False,
                "errors": ["Khong co du lieu simulation de doi chieu feedback"],
                "suggestions": ["Bat auto simulation va tra ve payload waveform/gain metrics"],
                "metrics": {},
            }

        status = str(sim.get("status") or "").strip().lower()
        errors: List[str] = []
        suggestions: List[str] = []
        metrics: Dict[str, Any] = {"status": status}

        if status == "failed":
            errors.append(f"Simulation failed: {sim.get('reason', 'unknown error')}")
            suggestions.append("Kiem tra lai netlist va dieu kien nguon cap")
        elif status == "skipped":
            errors.append(f"Simulation skipped: {sim.get('reason', 'unknown')}")
            suggestions.append("Can bo sung schema simulation hop le truoc khi tra ket qua")

        analysis_block = sim.get("analysis") if isinstance(sim.get("analysis"), dict) else {}
        gain_metrics = analysis_block.get("gain_metrics") if isinstance(analysis_block, dict) else {}
        if isinstance(gain_metrics, dict):
            metrics.update(gain_metrics)
            if gain_metrics.get("status") == "ok":
                rel_err_pct = gain_metrics.get("rel_error_pct")
                if isinstance(rel_err_pct, (int, float)) and rel_err_pct > 20.0:
                    errors.append(
                        f"Do lech gain sau mo phong {rel_err_pct:.2f}% vuot nguong 20%"
                    )
                    suggestions.append("Can tune lai tham so linh kien theo gain metrics sau mo phong")

                phase_match = gain_metrics.get("phase_match")
                if phase_match is False:
                    errors.append("Pha dau ra khong khop voi cau hinh gain ky vong")
                    suggestions.append("Kiem tra lai topology inverting/non-inverting")

            expected_gain = gain_metrics.get("expected_av")
            measured_gain = gain_metrics.get("measured_av")
            if isinstance(expected_gain, (int, float)) and isinstance(measured_gain, (int, float)):
                metrics["gain_delta"] = float(measured_gain) - float(expected_gain)

        supply_range = (analysis or {}).get("voltage_range") if isinstance(analysis, dict) else None
        if isinstance(supply_range, dict):
            metrics["supply_min"] = supply_range.get("min")
            metrics["supply_max"] = supply_range.get("max")

        if not errors and status in {"completed", "ok"}:
            return {
                "enabled": True,
                "passed": True,
                "errors": [],
                "suggestions": [],
                "metrics": metrics,
            }

        return {
            "enabled": True,
            "passed": len(errors) == 0,
            "errors": errors,
            "suggestions": list(dict.fromkeys(suggestions)),
            "metrics": metrics,
        }

    def _run_physics_validation(
        self,
        intent: CircuitIntent,
        solved_values: Dict[str, float],
        circuit_data: Dict[str, Any],
        gain_actual: Optional[float],
    ) -> Dict[str, Any]:
        """Thuc thi gate kiem tra vat ly truoc khi cho phep qua buoc tiep theo."""
        if not self._enforce_physics_gate:
            return {
                "enabled": False,
                "passed": True,
                "errors": [],
                "suggestions": ["Physics gate disabled by ENFORCE_PHYSICS_GATE"],
                "metrics": {},
            }
        # log debug vcc
        vcc_val=intent.vcc if hasattr(intent, 'vcc') else "N/a"
        logger.info(f"[physics] VCC from intent: {vcc_val}, solved_values keys: {list(solved_values.keys())}")
        
        component_set, missing_fields = self._build_component_set_for_physics(
            intent=intent,
            solved_values=solved_values,
            circuit_data=circuit_data,
        )
        if component_set is None:
            return {
                "enabled": True,
                "passed": False,
                "errors": [
                    "Khong du tham so de kiem tra vat ly: " + ", ".join(missing_fields or ["unknown"])
                ],
                "suggestions": [
                    "Bo sung tham so R1, R2, RC, RE va VCC de validator tinh Q-point"
                ],
                "metrics": {},
            }

        gain_target = intent.gain_target if intent.gain_target is not None else gain_actual
        topology_from_circuit = str(circuit_data.get("topology_type") or "").lower()
        if (intent.circuit_type or "").strip().lower() == "multi_stage" or "multi_stage" in (intent.topology or "").lower() or "two_stage" in topology_from_circuit:
            # For multi-stage chains, CE-equivalent DC check is for bias sanity only;
            # total gain target is enforced by constraint validator/simulation gate.
            gain_target = None
        result: DCValidationResult = self._dc_validator.validate_by_topology(component_set, gain_target)
        extra_checks = self._run_domain_physics_cross_checks(
            intent=intent,
            circuit_data=circuit_data,
            component_set=component_set,
        )

        errors = list(result.errors) + list(extra_checks["errors"])
        suggestions = list(result.suggestions) + list(extra_checks["suggestions"])
        metrics = dict(result.metrics)
        metrics.update(extra_checks["metrics"])

        return {
            "enabled": True,
            "passed": result.passed and len(extra_checks["errors"]) == 0,
            "errors": errors,
            "suggestions": list(dict.fromkeys(suggestions)),
            "metrics": metrics,
            "component_set": component_set.to_dict(),
        }

    def _run_domain_physics_cross_checks(
        self,
        intent: CircuitIntent,
        circuit_data: Dict[str, Any],
        component_set: ComponentSet,
    ) -> Dict[str, Any]:
        """Cross-check domain constraints that are not covered by DC equations only."""
        errors: List[str] = []
        suggestions: List[str] = []
        metrics: Dict[str, Any] = {}

        requested_models = self._extract_requested_models_from_text(intent.raw_text)
        generated_models = self._extract_generated_models(circuit_data)
        metrics["requested_models"] = requested_models
        metrics["generated_models"] = generated_models

        if requested_models:
            if not generated_models:
                errors.append(
                    "Yeu cau model linh kien cu the nhung circuit output khong khai bao model"
                )
                suggestions.append("Bo sung model linh kien trong component parameters hoac netlist")
            else:
                req_set = {m.upper() for m in requested_models}
                gen_set = {m.upper() for m in generated_models}
                if req_set.isdisjoint(gen_set):
                    errors.append(
                        f"Model linh kien khong khop yeu cau: can {', '.join(requested_models)}, thuc te {', '.join(generated_models)}"
                    )
                    suggestions.append("Tai sinh netlist dung dung model linh kien user da yeu cau")

        supply_values = self._extract_supply_voltages_from_circuit(circuit_data)
        supply_values.extend(self._extract_supply_voltages_from_netlist(self._extract_netlist(circuit_data)))
        metrics["supply_voltages"] = supply_values

        extracted_vcc = self._dc_validator._extract_vcc(circuit_data)
        metrics["extracted_vcc"] = extracted_vcc

        intent_vcc = self._extract_numeric(intent.vcc, component_set.VCC)
        metrics["intent_vcc"] = intent_vcc

        expected_vcc = intent_vcc if isinstance(intent_vcc, (int, float)) and float(intent_vcc) >= 1.0 else extracted_vcc
        if not isinstance(expected_vcc, (int, float)) or float(expected_vcc) < 1.0:
            logger.warning(
                "[physics] Extracted VCC=%.3fV is suspiciously low. Skipping physics validation to avoid false positives.",
                float(expected_vcc or 0.0),
            )
            metrics["physics_skipped"] = True
            return {
                "passed": True,
                "errors": [],
                "suggestions": [
                    "Kiem tra lai truong power_supply.voltage / VCC trong CircuitIR"
                ],
                "metrics": metrics,
            }

        if supply_values and isinstance(expected_vcc, (int, float)):
            max_supply = max(supply_values)
            min_supply = min(supply_values)
            abs_peak_supply = max(abs(float(v)) for v in supply_values)
            has_pos_supply = any(float(v) > 0.5 for v in supply_values)
            has_neg_supply = any(float(v) < -0.5 for v in supply_values)
            dual_supply_requested = self._is_dual_supply_requested(intent, supply_values)
            metrics["expected_vcc"] = expected_vcc
            metrics["max_supply"] = max_supply
            metrics["min_supply"] = min_supply
            metrics["abs_peak_supply"] = abs_peak_supply
            metrics["dual_supply_requested"] = dual_supply_requested

            if dual_supply_requested:
                if has_pos_supply and has_neg_supply:
                    if abs_peak_supply > expected_vcc + 0.75:
                        peak_text = self._format_compact_number(abs_peak_supply)
                        expected_vcc_text = self._format_compact_number(expected_vcc)
                        errors.append(
                            f"Bien nguon doi ±{peak_text}V vuot yeu cau ±{expected_vcc_text}V"
                        )
                        suggestions.append("Dong bo lai cap nguon doi ±VCC theo yeu cau")
                else:
                    # Some templates encode dual rails as a single total supply (e.g., 24V for ±12V).
                    allowed_total = 2.0 * expected_vcc + 0.75
                    if max_supply > allowed_total:
                        max_supply_text = self._format_compact_number(max_supply)
                        expected_total_text = self._format_compact_number(2.0 * expected_vcc)
                        errors.append(
                            f"Tong nguon doi {max_supply_text}V vuot muc cho phep {expected_total_text}V (2*VCC)"
                        )
                        suggestions.append("Giam tong bien do nguon doi hoac chuan hoa theo ±VCC")
            else:
                if max_supply > expected_vcc + 0.5:
                    max_supply_text = self._format_compact_number(max_supply)
                    expected_vcc_text = self._format_compact_number(expected_vcc)
                    errors.append(
                        f"Nguon cap toi da {max_supply_text}V vuot yeu cau VCC={expected_vcc_text}V"
                    )
                    suggestions.append("Dong bo lai gia tri VCC trong netlist, component va intent")

            if intent.supply_mode == "single_supply" and min_supply < -0.1:
                min_supply_text = self._format_compact_number(min_supply)
                errors.append(
                    f"Yeu cau single-supply nhung netlist dang dung nguon am {min_supply_text}V"
                )
                suggestions.append("Loai bo nguon am, chi giu +VCC/GND cho single-supply")

        topology = (intent.circuit_type or intent.topology or component_set.topology or "").strip().lower()
        is_opamp_topology = topology in {"inverting", "non_inverting"} or intent.device_preference == "opamp"
        if is_opamp_topology:
            use_single_supply = intent.supply_mode == "single_supply"
            if not use_single_supply and supply_values:
                use_single_supply = min(supply_values) >= -0.1

            if use_single_supply:
                has_virtual_ref = self._has_virtual_ground_reference(circuit_data)
                capacitor_count = self._count_components_by_type(circuit_data, "CAPACITOR")
                metrics["has_virtual_reference"] = has_virtual_ref
                metrics["capacitor_count"] = capacitor_count

                if not has_virtual_ref:
                    errors.append(
                        "Mach op-amp single-supply thieu mang bias Vref~VCC/2 (virtual ground)"
                    )
                    suggestions.append("Bo sung cau chia ap/virtual-ground de dat diem bias giua nguon")

                if intent.frequency and capacitor_count == 0:
                    errors.append(
                        "Mach co yeu cau AC nhung khong co tu ghep input/output"
                    )
                    suggestions.append("Bo sung Cin/Cout de ghep AC va chan thanh phan DC")

        return {
            "errors": errors,
            "suggestions": suggestions,
            "metrics": metrics,
        }

    def _attempt_local_physics_autofix(
        self,
        *,
        intent: CircuitIntent,
        solved_values: Dict[str, float],
        circuit_data: Dict[str, Any],
        gain_actual: Optional[float],
        physics_payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Try a deterministic rebias for BJT-style circuits before hard-failing."""
        if self._is_supply_mismatch_failure(physics_payload) and isinstance(intent.vcc, (int, float)):
            updated_solved = dict(solved_values or {})
            updated_solved["VCC"] = float(intent.vcc)
            updated_circuit = copy.deepcopy(circuit_data)
            self._apply_supply_fix_to_circuit_data(
                circuit_data=updated_circuit,
                target_vcc=float(intent.vcc),
                supply_mode=intent.supply_mode,
                allow_dual_supply=self._is_dual_supply_requested(intent),
            )
            recheck_supply = self._run_physics_validation(
                intent=intent,
                solved_values=updated_solved,
                circuit_data=updated_circuit,
                gain_actual=(intent.gain_target if isinstance(intent.gain_target, (int, float)) else gain_actual),
            )
            if recheck_supply.get("passed", False):
                return {
                    "solved_values": updated_solved,
                    "circuit_data": updated_circuit,
                    "physics_validation": recheck_supply,
                }

        if not self._is_bjt_bias_failure(intent, physics_payload):
            return None

        component_set, missing_fields = self._build_component_set_for_physics(
            intent=intent,
            solved_values=solved_values,
            circuit_data=circuit_data,
        )
        if component_set is None or missing_fields:
            return None

        patched = self._rebias_bjt_for_midpoint(
            component_set=component_set,
            gain_target=(intent.gain_target if isinstance(intent.gain_target, (int, float)) else gain_actual),
        )
        if patched is None:
            return None

        updated_solved = dict(solved_values or {})
        updated_solved.update(
            {
                "R1": float(patched.R1),
                "R2": float(patched.R2),
                "RC": float(patched.RC),
                "RE": float(patched.RE),
                "VCC": float(patched.VCC),
            }
        )

        updated_circuit = copy.deepcopy(circuit_data)
        self._apply_component_set_to_circuit_data(updated_circuit, patched)

        recheck = self._run_physics_validation(
            intent=intent,
            solved_values=updated_solved,
            circuit_data=updated_circuit,
            gain_actual=(intent.gain_target if isinstance(intent.gain_target, (int, float)) else gain_actual),
        )

        if not recheck.get("passed", False):
            return None

        return {
            "solved_values": updated_solved,
            "circuit_data": updated_circuit,
            "physics_validation": recheck,
        }

    @staticmethod
    def _is_bjt_bias_failure(intent: CircuitIntent, physics_payload: Dict[str, Any]) -> bool:
        topology = (intent.circuit_type or intent.topology or "").strip().lower()
        if topology not in {"common_emitter", "common_base", "common_collector"}:
            return False

        errors = [
            str(item).lower()
            for item in (physics_payload.get("errors", []) if isinstance(physics_payload, dict) else [])
            if str(item).strip()
        ]
        if not errors:
            return False

        keywords = ("vce", "bao hoa", "q-point", "swing")
        return any(any(k in msg for k in keywords) for msg in errors)

    @staticmethod
    def _is_supply_mismatch_failure(physics_payload: Dict[str, Any]) -> bool:
        errors = [
            str(item).lower()
            for item in (physics_payload.get("errors", []) if isinstance(physics_payload, dict) else [])
            if str(item).strip()
        ]
        if not errors:
            return False
        return any(
            ("nguon cap toi da" in msg)
            or ("single-supply" in msg and "nguon am" in msg)
            or ("bien nguon doi" in msg)
            or ("tong nguon doi" in msg)
            for msg in errors
        )

    @staticmethod
    def _apply_supply_fix_to_circuit_data(
        circuit_data: Dict[str, Any],
        target_vcc: float,
        supply_mode: str,
        allow_dual_supply: bool = False,
    ) -> None:
        if not isinstance(circuit_data, dict):
            return

        source_values: List[float] = []
        for comp in circuit_data.get("components", []):
            if not isinstance(comp, dict):
                continue
            if str(comp.get("type") or "").strip().upper() != "VOLTAGE_SOURCE":
                continue
            params = comp.get("parameters", {})
            if not isinstance(params, dict):
                continue
            raw_voltage = params.get("voltage")
            if isinstance(raw_voltage, dict):
                raw_voltage = raw_voltage.get("value")
            if isinstance(raw_voltage, (int, float)):
                source_values.append(float(raw_voltage))

        has_negative_rail = any(v < -0.1 for v in source_values)

        for comp in circuit_data.get("components", []):
            if not isinstance(comp, dict):
                continue
            if str(comp.get("type") or "").strip().upper() != "VOLTAGE_SOURCE":
                continue

            params = comp.get("parameters", {})
            if not isinstance(params, dict):
                continue

            raw_voltage = params.get("voltage")
            if isinstance(raw_voltage, dict):
                raw_voltage = raw_voltage.get("value")
            if isinstance(raw_voltage, (int, float)):
                val = float(raw_voltage)
                if allow_dual_supply:
                    # Dual-supply designs can be represented as +/-V rails or a single 2*V source.
                    if val < 0 and abs(val) > target_vcc + 0.5:
                        params["voltage"] = -float(target_vcc)
                    elif val > 0 and has_negative_rail and val > target_vcc + 0.5:
                        params["voltage"] = float(target_vcc)
                    elif val > 0 and (not has_negative_rail) and val > (2.0 * target_vcc + 0.5):
                        params["voltage"] = float(2.0 * target_vcc)
                    continue
                if (supply_mode == "single_supply" and val < 0) or (val > target_vcc + 0.5):
                    params["voltage"] = float(target_vcc)

    @staticmethod
    def _is_dual_supply_requested(intent: CircuitIntent, supply_values: Optional[List[float]] = None) -> bool:
        if str(intent.supply_mode or "").strip().lower() == "dual_supply":
            return True

        raw = (intent.raw_text or "").lower()
        dual_tokens = (
            "±",
            "+/-",
            "+ / -",
            "doi xung",
            "đối xứng",
            "nguon doi",
            "nguồn đôi",
            "split supply",
            "dual supply",
            "bipolar supply",
        )
        if any(token in raw for token in dual_tokens):
            return True

        values = supply_values or []
        has_pos = any(isinstance(v, (int, float)) and float(v) > 0.5 for v in values)
        has_neg = any(isinstance(v, (int, float)) and float(v) < -0.5 for v in values)
        return has_pos and has_neg

    def _rebias_bjt_for_midpoint(
        self,
        *,
        component_set: ComponentSet,
        gain_target: Optional[float],
    ) -> Optional[ComponentSet]:
        vcc = float(component_set.VCC)
        rc = max(float(component_set.RC), 100.0)
        beta = max(float(component_set.beta), 20.0)
        re = max(float(component_set.RE), 68.0)

        target_vce = max(vcc * 0.5, self._dc_validator.VCE_SAT + 0.8)
        if target_vce >= vcc:
            return None

        ic_target = (vcc - target_vce) / max(rc + re * (1.0 + 1.0 / beta), 1e-9)
        ic_target = max(ic_target, 0.5e-3)

        if isinstance(gain_target, (int, float)) and gain_target > 0 and ic_target > 0:
            re_small = 0.026 / ic_target
            re_gain_target = (rc / float(gain_target)) - re_small
            if re_gain_target > 0:
                re = max(re, re_gain_target)
                ic_target = (vcc - target_vce) / max(rc + re * (1.0 + 1.0 / beta), 1e-9)
                ic_target = max(ic_target, 0.5e-3)

        ib_target = ic_target / beta
        divider_current = max(12.0 * ib_target, 50e-6)
        ie_target = ic_target * (1.0 + 1.0 / beta)
        vb_target = self._dc_validator.VBE + ie_target * re
        vb_target = min(max(vb_target, 0.6), max(vcc - 0.8, 0.8))

        r2 = max(vb_target / divider_current, 1e3)
        r1 = max((vcc - vb_target) / divider_current, 1e3)

        return ComponentSet(
            R1=float(r1),
            R2=float(r2),
            RC=float(rc),
            RE=float(re),
            VCC=float(vcc),
            beta=float(beta),
            topology=component_set.topology,
        )

    @staticmethod
    def _apply_component_set_to_circuit_data(circuit_data: Dict[str, Any], component_set: ComponentSet) -> None:
        if not isinstance(circuit_data, dict):
            return

        target_values = {
            "R1": float(component_set.R1),
            "R2": float(component_set.R2),
            "RC": float(component_set.RC),
            "RD": float(component_set.RC),
            "RE": float(component_set.RE),
            "RS": float(component_set.RE),
            "VCC": float(component_set.VCC),
            "V1": float(component_set.VCC),
        }

        for comp in circuit_data.get("components", []) if isinstance(circuit_data, dict) else []:
            if not isinstance(comp, dict):
                continue

            cid = str(comp.get("id") or "").strip().upper()
            ctype = str(comp.get("type") or "").strip().upper()
            params = comp.get("parameters", {})
            if not isinstance(params, dict):
                continue

            if cid in {"R1", "R2", "RC", "RD", "RE", "RS"} and "resistance" in params:
                params["resistance"] = target_values.get(cid, params["resistance"])

            if ctype == "VOLTAGE_SOURCE" and "voltage" in params:
                params["voltage"] = float(component_set.VCC)

    @staticmethod
    def _extract_requested_models_from_text(text: str) -> List[str]:
        raw = (text or "").lower()
        known_patterns = [
            r"\blm\d{3,4}\b",
            r"\bop[-_]?0?6\b",
            r"\btl0\d{2,3}\b",
            r"\bne5532\b",
            r"\bua?741\b",
            r"\bopa\d{3,4}\b",
        ]

        detected: List[str] = []
        for pat in known_patterns:
            for match in re.findall(pat, raw, re.IGNORECASE):
                token = str(match).upper().replace("_", "-")
                if token not in detected:
                    detected.append(token)
        return detected

    def _extract_generated_models(self, circuit_data: Dict[str, Any]) -> List[str]:
        models: List[str] = []
        components = circuit_data.get("components", []) if isinstance(circuit_data, dict) else []
        for comp in components:
            if not isinstance(comp, dict):
                continue

            for key in ("model", "model_name", "part_number", "device"):
                value = comp.get(key)
                if isinstance(value, str) and value.strip():
                    token = value.strip().upper().replace("_", "-")
                    if token not in models:
                        models.append(token)

            params = comp.get("parameters", {})
            if not isinstance(params, dict):
                continue
            for key in ("model", "model_name", "part_number", "device"):
                value = params.get(key)
                if isinstance(value, dict):
                    value = value.get("value")
                if isinstance(value, str) and value.strip():
                    token = value.strip().upper().replace("_", "-")
                    if token not in models:
                        models.append(token)

        netlist = self._extract_netlist(circuit_data)
        if isinstance(netlist, str) and netlist.strip():
            for token in self._extract_requested_models_from_text(netlist):
                if token not in models:
                    models.append(token)
        return models

    @staticmethod
    def _extract_supply_voltages_from_circuit(circuit_data: Dict[str, Any]) -> List[float]:
        values: List[float] = []
        components = circuit_data.get("components", []) if isinstance(circuit_data, dict) else []
        for comp in components:
            if not isinstance(comp, dict):
                continue
            if str(comp.get("type", "")).upper() != "VOLTAGE_SOURCE":
                continue
            params = comp.get("parameters", {})
            raw = params.get("voltage") if isinstance(params, dict) else None
            if isinstance(raw, dict):
                raw = raw.get("value")
            if isinstance(raw, (int, float)):
                values.append(float(raw))
        return values

    @staticmethod
    def _extract_supply_voltages_from_netlist(netlist: Optional[str]) -> List[float]:
        if not isinstance(netlist, str) or not netlist.strip():
            return []
        values: List[float] = []
        for line in netlist.splitlines():
            text = line.strip()
            if not text or text.startswith("*"):
                continue
            match = re.match(
                r"^V\w+\s+\S+\s+\S+\s+([+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\s*[a-z]*\b",
                text,
                flags=re.IGNORECASE,
            )
            if not match:
                continue
            try:
                values.append(float(match.group(1)))
            except (TypeError, ValueError):
                continue
        return values

    @staticmethod
    def _has_virtual_ground_reference(circuit_data: Dict[str, Any]) -> bool:
        if not isinstance(circuit_data, dict):
            return False

        tokens = {"vref", "vbias", "mid", "virtual", "bias", "half_vcc", "vcm"}
        for net in circuit_data.get("nets", []):
            if not isinstance(net, dict):
                continue
            name = str(net.get("name") or net.get("id") or "").strip().lower()
            if any(tok in name for tok in tokens):
                return True

        for comp in circuit_data.get("components", []):
            if not isinstance(comp, dict):
                continue
            cid = str(comp.get("id") or "").strip().lower()
            if any(tok in cid for tok in tokens):
                return True
            params = comp.get("parameters", {})
            if not isinstance(params, dict):
                continue
            for value in params.values():
                if isinstance(value, dict):
                    value = value.get("value")
                if isinstance(value, str) and any(tok in value.lower() for tok in tokens):
                    return True
        return False

    @staticmethod
    def _count_components_by_type(circuit_data: Dict[str, Any], comp_type: str) -> int:
        if not isinstance(circuit_data, dict):
            return 0
        target = str(comp_type or "").strip().upper()
        count = 0
        for comp in circuit_data.get("components", []):
            if not isinstance(comp, dict):
                continue
            if str(comp.get("type") or "").strip().upper() == target:
                count += 1
        return count

    def _build_component_set_for_physics(
        self,
        intent: CircuitIntent,
        solved_values: Dict[str, float],
        circuit_data: Dict[str, Any],
    ) -> Tuple[Optional[ComponentSet], List[str]]:
        """Map solved values ve ComponentSet de chay DC bias validator."""
        topology = (
            (intent.circuit_type or intent.topology)
            or str(circuit_data.get("topology_type") or "")
            or "common_emitter"
        ).strip().lower()
        topology_aliases = {
            "ci": "inverting",
            "ni": "non_inverting",
            "diff": "differential",
        }
        topology = topology_aliases.get(topology, topology)

        solved_map: Dict[str, float] = {}
        for key, value in (solved_values or {}).items():
            if isinstance(value, (int, float)):
                solved_map[str(key).upper()] = float(value)

        resistor_map = self._extract_resistor_values_from_circuit_data(circuit_data)

        def pick(*names: str) -> Optional[float]:
            for name in names:
                key = name.upper()
                value = solved_map.get(key)
                if isinstance(value, (int, float)):
                    return float(value)

                # Accept common suffixed IDs from generated templates, e.g. R1A/RC1/RE2.
                solved_candidates = [
                    float(v) for k, v in solved_map.items()
                    if isinstance(v, (int, float)) and str(k).startswith(key)
                ]
                if solved_candidates:
                    return float(solved_candidates[0])

                r_value = resistor_map.get(key)
                if isinstance(r_value, (int, float)):
                    return float(r_value)

                prefixed = sorted(
                    [
                        (k, float(v))
                        for k, v in resistor_map.items()
                        if str(k).startswith(key) and isinstance(v, (int, float))
                    ],
                    key=lambda item: (len(item[0]), item[0]),
                )
                if prefixed:
                    return float(prefixed[0][1])
            return None
        
        # Fix VCC - dume
        vcc = None
        
        # Priority 1: User nhập trực tiếp trong intent (intent.vcc)
        if intent.vcc is not None and isinstance (intent.vcc, (int, float)):
            vcc = abs(float(intent.vcc))
        
        # Priority 2: Từ kết quả giải mạch (solved value/pick)
        if vcc is None:
            vcc_picked = pick("VCC", "VDD", "SUPPLY")
            if vcc_picked is not None:
                vcc = abs(float(vcc_picked))
                
        # Priority 3: Safe fallback
        if vcc is None:
            if topology in {"inverting", "non_inverting", "differential", "instrumentation"}:
                vcc = 15.0
            elif any (topo in topology for topo in ["common_", "multi_stage", "darlington", "fet", "mosfet"]):
                vcc = 12.0
            elif "class" in topology:
                vcc = 24.0
            elif "logic" in topology or "gate" in topology:
                vcc = 5.0
            else:
                vcc = 12.0
        
        beta = self._extract_numeric(pick("BETA", "BF"), 100.0)

        missing: List[str] = []

        if topology in {"inverting", "non_inverting", "differential", "instrumentation"}:
            rf = pick("RF", "R2", "RC")
            rin = pick("RIN", "RG", "R1", "RE")

            if rf is None or rin is None:
                inferred_rf, inferred_rin = self._infer_opamp_feedback_pair(resistor_map)
                rf = self._extract_numeric(rf, inferred_rf)
                rin = self._extract_numeric(rin, inferred_rin)

            if topology in {"inverting", "non_inverting"}:
                if rf is None:
                    missing.append("RF")
                if rin is None:
                    missing.append("RIN/RG")
            if vcc is None:
                missing.append("VCC")
            if missing:
                return None, missing

            # Differential/instrumentation stages may not expose explicit Rf/Rin in solved map;
            # fall back to neutral values so op-amp-specific checks can still run.
            rf = self._extract_numeric(rf, 10_000.0)
            rin = self._extract_numeric(rin, 10_000.0)

            return ComponentSet(
                R1=1.0,
                R2=1.0,
                RC=float(rf),
                RE=float(rin),
                VCC=float(vcc),
                beta=float(beta),
                topology=topology,
            ), []

        if topology == "multi_stage":
            r1 = pick("R1")
            r2 = pick("R2")
            rc = pick("RC", "RD")
            re = self._extract_numeric(pick("RE", "RS"), 0.0)

            if r1 is None or r2 is None or rc is None:
                inferred = self._infer_bjt_bias_resistors(resistor_map)
                r1 = self._extract_numeric(r1, inferred.get("R1"))
                r2 = self._extract_numeric(r2, inferred.get("R2"))
                rc = self._extract_numeric(rc, inferred.get("RC"))
                re = self._extract_numeric(re, inferred.get("RE"), 0.0)

            if r1 is None:
                missing.append("R1")
            if r2 is None:
                missing.append("R2")
            if rc is None:
                missing.append("RC")
            if vcc is None:
                missing.append("VCC")
            if missing:
                return None, missing

            # Use CE-like equivalent for stage-1 DC sanity checks in multi-stage chains.
            return ComponentSet(
                R1=float(r1),
                R2=float(r2),
                RC=float(rc),
                RE=max(float(re), 0.0),
                VCC=float(vcc),
                beta=float(beta),
                topology="common_emitter",
            ), []

        if topology in {"common_emitter", "common_base", "common_collector"}:
            r1 = pick("R1")
            r2 = pick("R2")
            rc = pick("RC", "RD")
            re = self._extract_numeric(pick("RE", "RS"), 0.0)

            if r1 is None or r2 is None or rc is None:
                inferred = self._infer_bjt_bias_resistors(resistor_map)
                r1 = self._extract_numeric(r1, inferred.get("R1"))
                r2 = self._extract_numeric(r2, inferred.get("R2"))
                rc = self._extract_numeric(rc, inferred.get("RC"))
                re = self._extract_numeric(re, inferred.get("RE"), 0.0)

            if r1 is None:
                missing.append("R1")
            if r2 is None:
                missing.append("R2")
            if rc is None:
                missing.append("RC")
            if vcc is None:
                missing.append("VCC")
            if missing:
                return None, missing

            return ComponentSet(
                R1=float(r1),
                R2=float(r2),
                RC=float(rc),
                RE=max(float(re), 0.0),
                VCC=float(vcc),
                beta=float(beta),
                topology=topology,
            ), []

        # Topology chua ho tro day du, tao bo gia tri an toan de validator tra warning pass.
        fallback_vcc = self._extract_numeric(vcc, 12.0)
        return ComponentSet(
            R1=10_000.0,
            R2=10_000.0,
            RC=1_000.0,
            RE=100.0,
            VCC=float(fallback_vcc),
            beta=float(beta),
            topology=topology,
        ), []

    @staticmethod
    def _extract_numeric(*values: Any) -> Optional[float]:
        """Lay gia tri so hop le dau tien tu danh sach gia tri ung vien."""
        for value in values:
            if isinstance(value, (int, float)):
                return float(value)
        return None

    @staticmethod
    def _format_compact_number(value: float) -> str:
        """Format so ngan gon de thong diep NLG de doc (12 thay vi 12.000)."""
        text = f"{float(value):.6f}".rstrip("0").rstrip(".")
        return text if text else "0"

    @staticmethod
    def _extract_vcc_from_circuit_data(circuit_data: Dict[str, Any]) -> Optional[float]:
        """Rut VCC tu circuit_data neu da co voltage source."""
        for comp in circuit_data.get("components", []) if isinstance(circuit_data, dict) else []:
            if not isinstance(comp, dict):
                continue
            if str(comp.get("type", "")).upper() != "VOLTAGE_SOURCE":
                continue
            params = comp.get("parameters", {})
            voltage = params.get("voltage") if isinstance(params, dict) else None
            if isinstance(voltage, dict):
                voltage = voltage.get("value")
            if isinstance(voltage, (int, float)):
                return float(voltage)
        return None

    @staticmethod
    def _extract_resistor_values_from_circuit_data(circuit_data: Dict[str, Any]) -> Dict[str, float]:
        """Extract resistor values keyed by component id from generated circuit payload."""
        values: Dict[str, float] = {}
        components = circuit_data.get("components", []) if isinstance(circuit_data, dict) else []
        for comp in components:
            if not isinstance(comp, dict):
                continue
            ctype = str(comp.get("type") or "").strip().upper()
            if ctype != "RESISTOR":
                continue

            cid = str(comp.get("id") or "").strip().upper()
            if not cid:
                continue
            params = comp.get("parameters", {})
            if not isinstance(params, dict):
                continue

            raw = params.get("resistance")
            if isinstance(raw, dict):
                raw = raw.get("value")
            if isinstance(raw, (int, float)) and float(raw) > 0:
                values[cid] = float(raw)
        return values

    @staticmethod
    def _infer_opamp_feedback_pair(resistor_map: Dict[str, float]) -> Tuple[Optional[float], Optional[float]]:
        """Infer a plausible Rf/Rin pair when IDs are not standardized."""
        if not resistor_map:
            return None, None

        known_rf = resistor_map.get("RF")
        known_rin = resistor_map.get("RIN") or resistor_map.get("RG")
        if isinstance(known_rf, (int, float)) and isinstance(known_rin, (int, float)):
            return float(known_rf), float(known_rin)

        candidates = sorted([float(v) for v in resistor_map.values() if float(v) > 0])
        if len(candidates) < 2:
            return None, None

        rin = candidates[0]
        rf = candidates[-1]
        return rf, rin

    @staticmethod
    def _infer_bjt_bias_resistors(resistor_map: Dict[str, float]) -> Dict[str, float]:
        """Infer likely R1/R2/RC/RE roles for CE/CB/CC when names are non-standard."""
        inferred: Dict[str, float] = {}
        if not resistor_map:
            return inferred

        if "R1" in resistor_map:
            inferred["R1"] = float(resistor_map["R1"])
        if "R2" in resistor_map:
            inferred["R2"] = float(resistor_map["R2"])
        if "RC" in resistor_map:
            inferred["RC"] = float(resistor_map["RC"])
        elif "RD" in resistor_map:
            inferred["RC"] = float(resistor_map["RD"])
        if "RE" in resistor_map:
            inferred["RE"] = float(resistor_map["RE"])
        elif "RS" in resistor_map:
            inferred["RE"] = float(resistor_map["RS"])

        remaining = sorted(
            [(key, float(val)) for key, val in resistor_map.items() if float(val) > 0],
            key=lambda item: item[1],
            reverse=True,
        )
        if not remaining:
            return inferred

        if "R1" not in inferred or "R2" not in inferred:
            divider_candidates = [item for item in remaining if item[1] >= 3_300.0]
            if len(divider_candidates) >= 2:
                if "R1" not in inferred:
                    inferred["R1"] = divider_candidates[0][1]
                if "R2" not in inferred:
                    inferred["R2"] = divider_candidates[1][1]

        if "RC" not in inferred:
            for _, value in remaining:
                if value not in {inferred.get("R1"), inferred.get("R2")}:
                    inferred["RC"] = value
                    break

        if "RE" not in inferred:
            ascending = sorted([val for _, val in remaining])
            for value in ascending:
                if value <= 2_200.0:
                    inferred["RE"] = value
                    break

        return inferred

    @staticmethod
    def _extract_validation_error_codes(validation_report: Any) -> List[str]:
        codes: List[str] = []
        for violation in getattr(validation_report, "errors", []) or []:
            code = str(getattr(violation, "code", "")).strip()
            if code:
                codes.append(code)
        return codes

    def _has_hard_constraint_errors(self, validation_report: Any) -> bool:
        return any(code.startswith("HARD_") for code in self._extract_validation_error_codes(validation_report))

    def _inject_feedback_hints(self, intent: CircuitIntent) -> CircuitIntent:
        """Inject concise hints learned from previous failures into generation prompt text."""
        if not self._feedback_memory_enabled:
            return intent

        hints = self._collect_feedback_hints(intent, limit=3)
        if not hints:
            return intent

        enriched = copy.deepcopy(intent)
        hint_text = "; ".join(hints)
        if "Feedback truoc do:" not in (enriched.raw_text or ""):
            enriched.raw_text = f"{enriched.raw_text}. Feedback truoc do: {hint_text}."

        if "feedback_memory_hints" not in enriched.extra_requirements:
            enriched.extra_requirements.append("feedback_memory_hints")
        return enriched

    def _collect_feedback_hints(self, intent: CircuitIntent, limit: int = 3) -> List[str]:
        if not self._feedback_memory_enabled:
            return []

        payload = self._load_feedback_memory()
        events = payload.get("events", []) if isinstance(payload, dict) else []
        if not isinstance(events, list) or not events:
            return []

        matched: List[str] = []
        intent_type = str(intent.circuit_type or "").strip().lower()
        for event in reversed(events):
            if not isinstance(event, dict):
                continue
            event_intent = event.get("intent") if isinstance(event.get("intent"), dict) else {}
            event_type = str(event_intent.get("circuit_type") or "").strip().lower()
            if intent_type and event_type and event_type != intent_type:
                continue

            for suggestion in event.get("suggestions", []) or []:
                text = str(suggestion).strip()
                if text and text not in matched:
                    matched.append(text)
                    if len(matched) >= limit:
                        return matched

        return matched

    def _record_feedback_event(
        self,
        *,
        intent: CircuitIntent,
        stage: str,
        errors: List[str],
        suggestions: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._feedback_memory_enabled:
            return

        payload = self._load_feedback_memory()
        events = payload.get("events", []) if isinstance(payload, dict) else []
        if not isinstance(events, list):
            events = []

        event = {
            "timestamp": time.time(),
            "stage": stage,
            "intent": {
                "intent_type": intent.intent_type,
                "circuit_type": intent.circuit_type,
                "topology": intent.topology,
                "vcc": intent.vcc,
                "gain_target": intent.gain_target,
                "supply_mode": intent.supply_mode,
                "device_preference": intent.device_preference,
            },
            "errors": list(dict.fromkeys([str(e).strip() for e in errors if str(e).strip()])),
            "suggestions": list(dict.fromkeys([str(s).strip() for s in suggestions if str(s).strip()])),
            "metadata": metadata or {},
        }

        if not event["errors"] and not event["suggestions"]:
            return

        events.append(event)
        payload["events"] = events[-200:]
        self._save_feedback_memory(payload)

    def _load_feedback_memory(self) -> Dict[str, Any]:
        if not self._feedback_memory_enabled:
            return {"events": []}
        try:
            if not self._feedback_memory_path.exists():
                return {"events": []}
            data = json.loads(self._feedback_memory_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception as exc:  # pragma: no cover - IO guard
            logger.warning("Unable to read feedback memory: %s", exc)
        return {"events": []}

    def _save_feedback_memory(self, payload: Dict[str, Any]) -> None:
        if not self._feedback_memory_enabled:
            return
        try:
            self._feedback_memory_path.parent.mkdir(parents=True, exist_ok=True)
            self._feedback_memory_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:  # pragma: no cover - IO guard
            logger.warning("Unable to persist feedback memory: %s", exc)

    def _build_regeneration_candidates(self, intent: CircuitIntent, failed_codes: List[str]) -> List[CircuitIntent]:
        hard_constraints = dict(intent.hard_constraints or {})

        primary = copy.deepcopy(intent)
        hints: List[str] = []
        hints.extend(self._collect_feedback_hints(intent, limit=2))

        if "HARD_DIRECT_COUPLING" in failed_codes or hard_constraints.get("direct_coupling_required"):
            hard_constraints["direct_coupling_required"] = True
            hints.append("ghép trực tiếp giữa các tầng, không dùng tụ coupling")

        if "HARD_ZOUT_MAX" in failed_codes:
            primary.output_buffer = True
            if "low_output_impedance" not in primary.extra_requirements:
                primary.extra_requirements.append("low_output_impedance")
            hints.append("tầng ra phải là follower để đạt trở kháng ra thấp")

        gain_min = hard_constraints.get("gain_min")
        gain_max = hard_constraints.get("gain_max")
        if isinstance(gain_min, (int, float)) and isinstance(gain_max, (int, float)):
            primary.gain_target = (float(gain_min) + float(gain_max)) / 2.0
            hints.append(f"tổng gain trong khoảng {gain_min} đến {gain_max}")
        elif isinstance(gain_min, (int, float)):
            primary.gain_target = max(float(primary.gain_target or gain_min), float(gain_min))

        primary.hard_constraints = hard_constraints
        if hints:
            primary.raw_text = f"{primary.raw_text}. Rang buoc bat buoc: {'; '.join(dict.fromkeys(hints))}."

        candidates = [primary]

        secondary = copy.deepcopy(primary)
        if secondary.circuit_type == "multi_stage":
            text_lower = (secondary.raw_text or "").lower()
            mosfet_chain = (secondary.device_preference == "mosfet") or ("mosfet" in text_lower) or ("cs" in text_lower and "cd" in text_lower)
            chain_hint = "CS-CD" if mosfet_chain else "CE-CC"
            secondary.raw_text = (
                f"{secondary.raw_text}. Ưu tiên topo 2 tầng {chain_hint}, tầng cuối follower, "
                "liên tầng direct coupling."
            )
            candidates.append(secondary)

        return candidates

    def _retry_pipeline_for_hard_constraints(
        self,
        intent: CircuitIntent,
        failed_codes: List[str],
        max_attempts: int = 2,
    ) -> Optional[Dict[str, Any]]:
        candidates = self._build_regeneration_candidates(intent, failed_codes)

        for candidate in candidates[:max_attempts]:
            spec = self._intent_to_spec(candidate)
            retry_result = self._ai_core.handle_spec(spec)
            if not retry_result.success or not retry_result.circuit:
                continue

            retry_solved_values = retry_result.solved.values if retry_result.solved else {}
            retry_gain = self._resolve_gain_for_validation(
                solved_values=retry_solved_values,
                fallback_gain=(retry_result.solved.actual_gain if retry_result.solved else None),
            )
            retry_metrics = self._prepare_validation_metrics(
                intent=candidate,
                solved_values=retry_solved_values,
                gain_actual=retry_gain,
                stage_analysis=(retry_result.solved.stage_analysis if retry_result.solved else None),
            )
            retry_report = self._validator.validate(
                retry_result.circuit.circuit_data,
                candidate.to_dict(),
                retry_metrics,
            )

            if retry_report.passed or not self._has_hard_constraint_errors(retry_report):
                return {
                    "pipeline_result": retry_result,
                    "validation_report": retry_report,
                    "intent": candidate,
                }

        return None

    def _retry_pipeline_for_physics_failures(
        self,
        intent: CircuitIntent,
        physics_payload: Dict[str, Any],
        max_attempts: int = 2,
    ) -> Optional[Dict[str, Any]]:
        suggestions = [
            str(item).strip()
            for item in (physics_payload.get("suggestions", []) if isinstance(physics_payload, dict) else [])
            if str(item).strip()
        ]
        errors = [
            str(item).strip()
            for item in (physics_payload.get("errors", []) if isinstance(physics_payload, dict) else [])
            if str(item).strip()
        ]

        primary = copy.deepcopy(intent)
        hint_parts: List[str] = []
        hint_parts.extend(suggestions[:3])
        hint_parts.extend(self._collect_feedback_hints(intent, limit=2))
        if errors:
            hint_parts.append("Bat buoc sua loi vat ly: " + "; ".join(errors[:2]))

        if hint_parts:
            primary.raw_text = (
                f"{primary.raw_text}. Rang buoc kiem tra vat ly bat buoc: "
                f"{'; '.join(dict.fromkeys(hint_parts))}."
            )

        candidates: List[CircuitIntent] = [primary]

        secondary = copy.deepcopy(primary)
        secondary_guidance: List[str] = [
            "Dat Q-point gan trung tam: VCE xap xi VCC/2",
            "Duy tri transistor o vung active, tranh bao hoa",
            "Dung phan cuc chia ap R1-R2 va RE khong qua nho",
        ]
        if isinstance(secondary.gain_target, (int, float)) and secondary.gain_target > 0:
            secondary_guidance.append(
                f"Toi uu gain theo Av gan {float(secondary.gain_target):g} voi emitter degeneration"
            )
        secondary.raw_text = (
            f"{secondary.raw_text}. Rang buoc bo sung: "
            f"{'; '.join(dict.fromkeys(secondary_guidance))}."
        )
        candidates.append(secondary)

        if any("VCE" in msg or "Q-point" in msg for msg in errors):
            tertiary = copy.deepcopy(primary)
            tertiary.raw_text = (
                f"{tertiary.raw_text}. Uu tien can bang DC: "
                "chon mang bias de IB du lon, VCE trong vung 0.3*VCC den 0.7*VCC, "
                "neu can thi tang RE hoac giam RC de thoat bao hoa."
            )
            candidates.append(tertiary)

        for candidate in candidates[: max(1, max_attempts)]:
            spec = self._intent_to_spec(candidate)
            retry_result = self._ai_core.handle_spec(spec)
            if not retry_result.success or not retry_result.circuit:
                continue

            retry_solved_values = retry_result.solved.values if retry_result.solved else {}
            retry_gain = self._resolve_gain_for_validation(
                solved_values=retry_solved_values,
                fallback_gain=(retry_result.solved.actual_gain if retry_result.solved else None),
            )
            retry_metrics = self._prepare_validation_metrics(
                intent=candidate,
                solved_values=retry_solved_values,
                gain_actual=retry_gain,
                stage_analysis=(retry_result.solved.stage_analysis if retry_result.solved else None),
            )
            retry_report = self._validator.validate(
                retry_result.circuit.circuit_data,
                candidate.to_dict(),
                retry_metrics,
            )
            if not retry_report.passed and self._has_hard_constraint_errors(retry_report):
                continue

            retry_physics = self._run_physics_validation(
                intent=candidate,
                solved_values=retry_solved_values,
                circuit_data=retry_result.circuit.circuit_data,
                gain_actual=retry_gain,
            )
            if retry_physics.get("passed", False):
                return {
                    "pipeline_result": retry_result,
                    "validation_report": retry_report,
                    "physics_validation": retry_physics,
                    "intent": candidate,
                }

        return None

    def _retry_pipeline_for_simulation_feedback(
        self,
        intent: CircuitIntent,
        simulation_feedback: Dict[str, Any],
        max_attempts: int = 1,
    ) -> Optional[Dict[str, Any]]:
        if max_attempts <= 0:
            return None

        errors = [
            str(item).strip()
            for item in (simulation_feedback.get("errors", []) if isinstance(simulation_feedback, dict) else [])
            if str(item).strip()
        ]
        suggestions = [
            str(item).strip()
            for item in (simulation_feedback.get("suggestions", []) if isinstance(simulation_feedback, dict) else [])
            if str(item).strip()
        ]

        candidate = copy.deepcopy(intent)
        hint_parts: List[str] = []
        hint_parts.extend(suggestions[:2])
        if errors:
            hint_parts.append("Bat buoc sua theo simulation feedback: " + "; ".join(errors[:2]))
        hint_parts.extend(self._collect_feedback_hints(intent, limit=2))
        if hint_parts:
            candidate.raw_text = f"{candidate.raw_text}. Rang buoc mo phong bat buoc: {'; '.join(dict.fromkeys(hint_parts))}."

        spec = self._intent_to_spec(candidate)
        retry_result = self._ai_core.handle_spec(spec)
        if not retry_result.success or not retry_result.circuit:
            return None

        retry_solved_values = retry_result.solved.values if retry_result.solved else {}
        retry_gain = self._resolve_gain_for_validation(
            solved_values=retry_solved_values,
            fallback_gain=(retry_result.solved.actual_gain if retry_result.solved else None),
        )
        retry_metrics = self._prepare_validation_metrics(
            intent=candidate,
            solved_values=retry_solved_values,
            gain_actual=retry_gain,
            stage_analysis=(retry_result.solved.stage_analysis if retry_result.solved else None),
        )
        retry_report = self._validator.validate(
            retry_result.circuit.circuit_data,
            candidate.to_dict(),
            retry_metrics,
        )
        if not retry_report.passed and self._has_hard_constraint_errors(retry_report):
            return None

        retry_physics = self._run_physics_validation(
            intent=candidate,
            solved_values=retry_solved_values,
            circuit_data=retry_result.circuit.circuit_data,
            gain_actual=retry_gain,
        )
        if not retry_physics.get("passed", False):
            return None

        return {
            "pipeline_result": retry_result,
            "validation_report": retry_report,
            "physics_validation": retry_physics,
            "intent": candidate,
        }

    def _maybe_auto_simulation(self, circuit_data: Dict[str, Any]) -> Dict[str, Any]:
        """Try transient simulation from generated output payload only."""
        if not self._should_auto_simulate(circuit_data):
            return {"status": "skipped", "reason": "not_requested"}

        valid_payload, reason = self._validate_simulation_payload(circuit_data)
        if not valid_payload:
            return {"status": "skipped", "reason": reason}

        try:
            sim_payload = dict(circuit_data)
            # Keep backward compatibility if generator does not provide schema fields yet.
            sim_payload.setdefault("analysis_type", "transient")
            sim_payload.setdefault("tran_step", "10us")
            sim_payload.setdefault("tran_stop", "10ms")
            sim_payload.setdefault("tran_start", "0")
            sim_payload.setdefault("nodes_to_monitor", self._default_simulation_probes(circuit_data))

            sim = NgSpiceSimulationService().simulate_from_circuit_data(sim_payload)
            sim_dict = sim.to_dict()
            return {
                "status": "completed",
                "analysis": sim_dict.get("analysis", {}),
                "points": sim_dict.get("points", 0),
                "execution_time_ms": sim_dict.get("execution_time_ms", 0),
                "probe_count": len(sim_payload.get("nodes_to_monitor", [])),
            }
        except (SimulationError, Exception) as exc:
            return {"status": "failed", "reason": str(exc)}

    def _should_auto_simulate(self, circuit_data: Dict[str, Any]) -> bool:
        """Quyet dinh co mo phong hay khong dua tren payload output da sinh."""
        force_env = (os.getenv("CHATBOT_AUTO_SIMULATE", "false").strip().lower() in {"1", "true", "yes", "on"})
        analysis_type = str(circuit_data.get("analysis_type") or "").strip().lower()
        has_nodes = bool(circuit_data.get("nodes_to_monitor"))
        has_source = isinstance(circuit_data.get("source_params"), dict)
        requested_by_payload = analysis_type == "transient" and has_nodes and has_source
        return force_env or requested_by_payload

    @staticmethod
    def _validate_simulation_payload(circuit_data: Dict[str, Any]) -> Tuple[bool, str]:
        """Kiem tra simulation stage chi nhan du lieu duoc sinh tu execution stage."""
        if not isinstance(circuit_data, dict):
            return False, "invalid_circuit_data"
        components = circuit_data.get("components", [])
        if not isinstance(components, list) or not components:
            return False, "missing_components"
        analysis_type = str(circuit_data.get("analysis_type") or "").strip().lower()
        if analysis_type and analysis_type != "transient":
            return False, f"unsupported_analysis_type:{analysis_type}"
        return True, "ok"

    def _extract_netlist(self, circuit_data: Dict[str, Any]) -> Optional[str]:
        for key in ("spice_netlist", "netlist", "ngspice_netlist"):
            value = circuit_data.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _default_simulation_probes(self, circuit_data: Dict[str, Any]) -> List[str]:
        input_probes: List[str] = []
        output_probes: List[str] = []
        ports = circuit_data.get("ports", []) if isinstance(circuit_data, dict) else []
        for p in ports:
            if not isinstance(p, dict):
                continue
            direction = str(p.get("direction") or p.get("type") or "").lower()
            net = str(p.get("net") or p.get("net_name") or "").strip()
            if not net:
                continue
            probe = f"v({net.lower()})"
            if direction == "input":
                input_probes.append(probe)
            if direction == "output":
                output_probes.append(probe)

        probes = list(dict.fromkeys(input_probes + output_probes))
        if not probes:
            probes = ["v(net_in)", "v(net_out)"]
        return list(dict.fromkeys(probes))

    def _apply_simulation_requirements(self, intent: CircuitIntent, circuit_data: Dict[str, Any]) -> None:
        """Populate circuit_data simulation schema from natural-language requirements.

        Targets:
        - analysis_type, tran_step, tran_stop, tran_start
        - nodes_to_monitor
        - source_params (offset/amplitude/frequency)
        - reltol
        - refresh netlist with injected SIN source when required
        """
        if not isinstance(circuit_data, dict):
            return

        raw = (intent.raw_text or "").lower()
        freq = float(intent.frequency) if intent.frequency else None
        amplitude = self._extract_input_amplitude_v(raw)

        # Prefer channel-specific input amplitude/frequency if present.
        if intent.channel_inputs:
            ch = intent.channel_inputs.get("CH1") or next(iter(intent.channel_inputs.values()), {})
            if isinstance(ch, dict):
                if ch.get("amplitude_v") is not None:
                    amplitude = float(ch.get("amplitude_v"))
                if ch.get("frequency_hz") is not None:
                    freq = float(ch.get("frequency_hz"))

        cycles = self._extract_cycle_count(raw)
        points_per_cycle = self._extract_points_per_cycle(raw)
        reltol = self._extract_reltol(raw)

        circuit_data["analysis_type"] = "transient"
        circuit_data.setdefault("tran_start", "0")
        circuit_data.setdefault("nodes_to_monitor", self._default_simulation_probes(circuit_data))
        if reltol is not None:
            circuit_data["reltol"] = reltol

        if freq and freq > 0:
            # stop_time = cycles / frequency
            if cycles and cycles > 0:
                stop_s = float(cycles) / float(freq)
                circuit_data["tran_stop"] = f"{stop_s:.9g}"
            else:
                circuit_data.setdefault("tran_stop", "10ms")

            # step_time = period / points_per_cycle
            if points_per_cycle and points_per_cycle > 0:
                step_s = (1.0 / float(freq)) / float(points_per_cycle)
                circuit_data["tran_step"] = f"{step_s:.9g}"
            else:
                circuit_data.setdefault("tran_step", "10us")
        else:
            circuit_data.setdefault("tran_stop", "10ms")
            circuit_data.setdefault("tran_step", "10us")

        source_params = dict(circuit_data.get("source_params") or {})
        source_params.setdefault("offset", 0.0)
        if amplitude is not None:
            source_params["amplitude"] = float(amplitude)
        else:
            source_params.setdefault("amplitude", 0.1)
        if freq is not None and freq > 0:
            source_params["frequency"] = float(freq)
        else:
            source_params.setdefault("frequency", 1000.0)
        circuit_data["source_params"] = source_params

        # Refresh netlist strings with new source/include schema so exported payload is executable.
        sim = NgSpiceSimulationService()
        base_netlist = self._extract_netlist(circuit_data)
        if isinstance(base_netlist, str) and base_netlist.strip():
            patched = sim._inject_model_includes(base_netlist, circuit_data)
            patched = sim._apply_source_params(patched, circuit_data, source_params)
            circuit_data["spice_netlist"] = patched
            circuit_data["netlist"] = patched

    @staticmethod
    def _extract_cycle_count(text: str) -> Optional[int]:
        patterns = [
            r"(\d+)\s*chu\s*k[yỳ]",
            r"(\d+)\s*cycles?",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    val = int(m.group(1))
                    if val > 0:
                        return val
                except (ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def _extract_points_per_cycle(text: str) -> Optional[int]:
        patterns = [
            r"(\d+)\s*điểm\s*m[aẫ]u\s*m[ỗo]i\s*chu\s*k[yỳ]",
            r"m[ỗo]i\s*chu\s*k[yỳ].{0,20}?(\d+)\s*điểm\s*m[aẫ]u",
            r"(\d+)\s*samples?\s*per\s*cycle",
            r"đ[ộo]\s*ph[aâ]n\s*gi[ảa]i.{0,20}?(\d+)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    val = int(m.group(1))
                    if val > 0:
                        return val
                except (ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def _extract_reltol(text: str) -> Optional[float]:
        m = re.search(r"reltol\s*[:=]?\s*([0-9]*\.?[0-9]+(?:e[-+]?\d+)?)", text, re.IGNORECASE)
        if not m:
            return None
        try:
            val = float(m.group(1))
            if val > 0:
                return val
        except (ValueError, TypeError):
            return None
        return None

    @staticmethod
    def _extract_input_amplitude_v(text: str) -> Optional[float]:
        patterns = [
            r"bi[êe]n\s*đ[ộo]\s*([0-9]+(?:\.[0-9]+)?)\s*mv",
            r"bi[êe]n\s*đ[ộo]\s*([0-9]+(?:\.[0-9]+)?)\s*v",
            r"amplitude\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\s*mv",
            r"amplitude\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\s*v",
            r"vin[^\n,;]*?([0-9]+(?:\.[0-9]+)?)\s*mv",
            r"vin[^\n,;]*?([0-9]+(?:\.[0-9]+)?)\s*v",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if not m:
                continue
            try:
                value = float(m.group(1))
            except (ValueError, TypeError):
                continue
            if "mv" in m.group(0).lower():
                return value * 1e-3
            return value
        return None

    def _estimate_input_channels(self, circuit_data: Dict[str, Any], raw_text: str) -> int:
        text = (raw_text or "").lower()
        if "multi" in text and "channel" in text:
            return 2
        if "2 kênh" in text or "2 kenh" in text or "stereo" in text:
            return 2
        ports = circuit_data.get("ports", []) if isinstance(circuit_data, dict) else []
        in_ports = [
            p for p in ports
            if isinstance(p, dict)
            and str(p.get("direction") or p.get("type") or "").lower() == "input"
        ]
        return max(1, len(in_ports))

    def _estimate_voltage_range(self, intent: CircuitIntent, circuit_data: Dict[str, Any]) -> Dict[str, Optional[float]]:
        vcc = None
        if intent.vcc is not None and isinstance (intent.vcc, (int, float)):
            vcc = abs(float(intent.vcc))
        if vcc is None:
            topology = (intent.circuit_type or intent.topology or str(circuit_data.get("topology_type") or "")).lower()
            if any(t in topology for t in ["inverting", "non_inverting", "diff", "instrumentation"]):
                vcc = 15.0
            elif "class" in topology:
                vcc = 24.0
            else:
                vcc = 12.0

        # For single supply: [0, VCC], for dual supply: [-VCC, VCC]
        if intent.supply_mode == "dual_supply":
            return {"min": -float(vcc), "max": float(vcc)}
        
        # Nguồn đơn (Single Supply)
        return {"min": 0.0, "max": float(vcc)}

    def _render_gain_substitution(self, gain_formula: str, solved_values: Dict[str, float]) -> str:
        if not gain_formula:
            return ""
        rendered = gain_formula
        # Replace longer keys first to avoid partial replacement.
        for key in sorted(solved_values.keys(), key=len, reverse=True):
            val = solved_values[key]
            if isinstance(val, (int, float)):
                rendered = rendered.replace(str(key), f"{val:g}")
        return rendered
