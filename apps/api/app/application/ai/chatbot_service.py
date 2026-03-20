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

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.application.ai.llm_router import LLMMode, LLMRole, get_router
from app.application.ai.context_router_service import (
    ContextRouterService,
    NullExternalKnowledgeProvider,
)
from app.application.ai.nlu_service import NLUService, CircuitIntent
from app.application.ai.nlg_service import NLGService
from app.application.ai.constraint_validator import ConstraintValidator
from app.application.ai.repair_engine import RepairEngine
from app.application.ai.simulation_service import NgSpiceSimulationService, SimulationError
from app.db.database import SessionLocal
from app.domains.circuits.ai_core import AICore
from app.domains.circuits.ai_core.spec_parser import UserSpec
from app.domains.circuits.ai_core.parameter_solver import ParameterSolver
from app.infrastructure.repositories.chat_context_repository import (
    ChatHistoryRepository,
    KnowledgeRepository,
    SummaryMemoryRepository,
)

logger = logging.getLogger(__name__)

# Path defaults
_API_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # apps/api/
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
        return d


class ChatbotService:
    """Chatbot service chính theo cơ chế mode Air/Pro."""

    def __init__(self) -> None:
        self._nlu = NLUService()
        self._nlg = NLGService()
        self._ai_core = AICore(
            metadata_dir=_METADATA_DIR,
            block_library_dir=_BLOCK_LIBRARY_DIR,
            templates_dir=_TEMPLATES_DIR,
        )
        self._router = get_router()
        self._validator = ConstraintValidator()
        self._repair = RepairEngine()
        self._electronics_domain_only = (
            os.getenv("ELECTRONICS_DOMAIN_ONLY", "true").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self._context_db_enabled = False
        self._chat_repo: Optional[ChatHistoryRepository] = None
        self._summary_repo: Optional[SummaryMemoryRepository] = None
        self._knowledge_repo: Optional[KnowledgeRepository] = None
        self._context_router: Optional[ContextRouterService] = None
        self._init_context_router()
        logger.info("ChatbotService initialized")

    def chat(
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
            if self._context_db_enabled:
                try:
                    chat_id = self._ensure_chat_session(chat_id=chat_id, user_id=resolved_user_id)
                    effective_text = self._build_effective_user_text(
                        chat_id=chat_id,
                        user_text=user_text,
                        user_id=resolved_user_id,
                    )
                    if chat_id:
                        self._persist_user_message(chat_id=chat_id, user_text=user_text)
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

            # ── GĐ 2: Branch theo intent_type ──
            if intent.intent_type == "modify":
                response = self._handle_modify(intent, response, start, mode=selected_mode)
            elif intent.intent_type == "validate":
                response = self._handle_validate(intent, response, start, mode=selected_mode)
            elif intent.intent_type == "explain":
                response = self._handle_explain(intent, response, start, mode=selected_mode)
            else:
                response = self._handle_create(intent, response, start, mode=selected_mode)

            response.mode = selected_mode.value

            if context_available_for_request and chat_id and response.message:
                self._persist_assistant_message(chat_id=chat_id, assistant_text=response.message)

            return response

        except Exception as e:
            logger.error(f"ChatbotService error: {e}", exc_info=True)
            response.success = False
            response.message = f"❌ Lỗi hệ thống: {str(e)}"

        response.processing_time_ms = (time.time() - start) * 1000
        return response

    def _init_context_router(self) -> None:
        """Initialize chat-context persistence layer if database is available."""
        try:
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

    def _disable_context_db(self, reason: Exception) -> None:
        """Hard-disable context DB after runtime failure and rollback session state."""
        for repo in (self._chat_repo, self._summary_repo, self._knowledge_repo):
            session = getattr(repo, "session", None)
            if session is None:
                continue
            try:
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

    def _persist_user_message(self, chat_id: str, user_text: str) -> None:
        if not self._chat_repo:
            return
        try:
            self._chat_repo.append_message(
                chat_id=chat_id,
                role="user",
                content=user_text,
                status="completed",
            )
        except Exception as exc:  # pragma: no cover - runtime guard
            logger.warning("Failed to persist user message: %s", exc)

    def _persist_assistant_message(self, chat_id: str, assistant_text: str) -> None:
        if not self._chat_repo:
            return
        try:
            self._chat_repo.append_message(
                chat_id=chat_id,
                role="assistant",
                content=assistant_text,
                status="completed",
            )
        except Exception as exc:  # pragma: no cover - runtime guard
            logger.warning("Failed to persist assistant message: %s", exc)

    # ------------------------------------------------------------------ #
    #  Intent handlers
    # ------------------------------------------------------------------ #

    def _handle_create(self, intent: CircuitIntent, response: ChatResponse, start: float, mode: LLMMode) -> ChatResponse:
        """Flow tạo mạch mới: NLU → Clarify? → AI Core → Validate → Repair → NLG."""

        # Clarification nếu thiếu thông tin
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

        # AI Core pipeline
        spec = self._intent_to_spec(intent)
        pipeline_result = self._ai_core.handle_spec(spec)
        response.pipeline = pipeline_result.to_dict()
        response.template_id = pipeline_result.plan.matched_template_id or "" if pipeline_result.plan else ""

        # Reasoning fallback khi AI Core thất bại
        if not pipeline_result.success:
            reasoning_text = self._reasoning_fallback(intent, pipeline_result.error, mode=mode)
            if reasoning_text:
                response.success = True
                response.message = reasoning_text
                response.processing_time_ms = (time.time() - start) * 1000
                return response

        # ── Validate + Repair loop ──
        if pipeline_result.success and pipeline_result.circuit:
            circuit = pipeline_result.circuit
            solved = pipeline_result.solved

            circuit_data = circuit.circuit_data
            solved_values = solved.values if solved else {}

            # Validate
            val_report = self._validator.validate(
                circuit_data, intent.to_dict(), solved_values,
            )
            response.validation = val_report.to_dict()

            # Repair nếu có errors
            if not val_report.passed:
                repair_result = self._repair.repair(
                    circuit_data, solved_values, intent.to_dict(), val_report,
                )
                response.repair = repair_result.to_dict()

                if repair_result.repaired:
                    circuit_data = repair_result.circuit_data
                    solved_values = repair_result.solved_params
                    response.validation = repair_result.final_report.to_dict() if repair_result.final_report else response.validation
                    logger.info(f"Repair successful: {len(repair_result.actions)} actions")

            # Enrich circuit_data with simulation schema extracted from user prompt.
            self._apply_simulation_requirements(intent, circuit_data)

            response.success = True
            response.params = solved_values
            response.circuit_data = circuit_data
            response.analysis = self._build_design_analysis(
                intent=intent,
                circuit_data=circuit_data,
                solved_values=solved_values,
                gain_formula=circuit.gain_formula,
                gain_actual=solved.actual_gain if solved else None,
                stage_analysis=(solved.stage_analysis if solved else None),
            )
            response.template_id = circuit.template_id

            # Collect warnings
            warnings = []
            if circuit.validation and circuit.validation.warnings:
                warnings.extend(circuit.validation.warnings)
            if solved and solved.warnings:
                warnings.extend(solved.warnings)
            if val_report.warnings:
                warnings.extend([v.message for v in val_report.warnings])

            response.message = self._nlg.generate_success_response(
                circuit_type=intent.circuit_type,
                gain_actual=solved.actual_gain if solved else None,
                gain_target=intent.gain_target,
                params=solved_values,
                gain_formula=circuit.gain_formula,
                warnings=warnings,
                template_id=circuit.template_id,
                simulation=(response.analysis or {}).get("simulation", {}),
                stage_table=((response.analysis or {}).get("cascading", {}) or {}).get("stage_table", []),
                mode=mode,
            )

            # Nếu user gửi câu đa ý (vừa thiết kế vừa yêu cầu giải thích), append phần explain.
            if "explain" in intent.requested_actions:
                explain_text = self._reasoning_explain(intent, mode=mode)
                if not explain_text:
                    explain_text = self._rule_based_explain(intent)
                if explain_text:
                    response.message += "\n\n---\n\n" + explain_text

            # Thêm thông tin repair vào message nếu có
            if response.repair and response.repair.get("repaired"):
                repair_summary = self._nlg.generate_repair_summary(
                    response.repair.get("actions", []),
                )
                response.message += "\n\n" + repair_summary
        else:
            response.success = False
            response.message = self._nlg.generate_error_response(
                error_msg=pipeline_result.error,
                stage=pipeline_result.stage_reached,
                circuit_type=intent.circuit_type,
                gain_target=intent.gain_target,
                vcc=intent.vcc,
                mode=mode,
            )

        response.processing_time_ms = (time.time() - start) * 1000
        return response

    def _handle_modify(self, intent: CircuitIntent, response: ChatResponse, start: float, mode: LLMMode) -> ChatResponse:
        """Flow chỉnh sửa mạch: xác định thao tác → apply lên mạch base → validate → NLG."""

        if not intent.edit_operations:
            response.needs_clarification = True
            response.success = False
            response.message = self._nlg.generate_modify_clarification(intent)
            response.processing_time_ms = (time.time() - start) * 1000
            return response

        # Nếu chưa có mạch base (circuit_type rõ) → tạo trước, rồi modify
        if intent.circuit_type and intent.circuit_type != "unknown":
            spec = self._intent_to_spec(intent)
            pipeline_result = self._ai_core.handle_spec(spec)

            if pipeline_result.success and pipeline_result.circuit:
                import copy
                circuit_data = copy.deepcopy(pipeline_result.circuit.circuit_data)
                solved = dict(pipeline_result.solved.values) if pipeline_result.solved else {}

                # Apply edit operations
                edit_log = self._apply_edits(circuit_data, intent.edit_operations)

                # Validate
                val_report = self._validator.validate(circuit_data, intent.to_dict(), solved)
                response.validation = val_report.to_dict()

                if not val_report.passed:
                    repair_result = self._repair.repair(circuit_data, solved, intent.to_dict(), val_report)
                    response.repair = repair_result.to_dict()
                    if repair_result.repaired:
                        circuit_data = repair_result.circuit_data
                        solved = repair_result.solved_params

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
                response.template_id = pipeline_result.plan.matched_template_id if pipeline_result.plan else ""
                response.pipeline = pipeline_result.to_dict()
                response.message = self._nlg.generate_modify_response(
                    intent=intent,
                    edit_log=edit_log,
                    circuit_data=circuit_data,
                    solved=solved,
                )
            else:
                response.success = False
                response.message = self._nlg.generate_error_response(
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
        if intent.circuit_type and intent.circuit_type != "unknown":
            spec = self._intent_to_spec(intent)
            pipeline_result = self._ai_core.handle_spec(spec)

            if pipeline_result.success and pipeline_result.circuit:
                solved = pipeline_result.solved.values if pipeline_result.solved else {}
                val_report = self._validator.validate(
                    pipeline_result.circuit.circuit_data, intent.to_dict(), solved,
                )
                response.validation = val_report.to_dict()
                response.success = True
                response.circuit_data = pipeline_result.circuit.circuit_data
                response.params = solved
                response.analysis = self._build_design_analysis(
                    intent=intent,
                    circuit_data=pipeline_result.circuit.circuit_data,
                    solved_values=solved,
                    gain_formula=pipeline_result.circuit.gain_formula,
                    gain_actual=(pipeline_result.solved.actual_gain if pipeline_result.solved else None),
                    stage_analysis=(pipeline_result.solved.stage_analysis if pipeline_result.solved else None),
                )
                response.message = self._nlg.generate_validation_report(val_report)
            else:
                response.success = False
                response.message = self._nlg.generate_error_response(
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
            "Bạn là bộ phân loại câu hỏi cho hệ thống thiết kế mạch điện tử. "
            'Chỉ trả lời JSON: {"is_electronics": true/false}. '
            "true nếu câu hỏi liên quan mạch điện, linh kiện, khuếch đại, nguồn, "
            "op-amp, transistor, IC, PCB, tín hiệu, lọc, dao động, ... "
            "false nếu không liên quan điện tử."
        )
        result = self._router.chat_json(
            LLMRole.GENERAL, mode=mode, system=system, user_content=user_text,
        )
        if result and result.get("is_electronics") is False:
            return (
                "⚠️ Xin lỗi, tôi chỉ hỗ trợ các câu hỏi về **thiết kế mạch điện tử** "
                "(khuếch đại, nguồn, lọc, dao động, ...). "
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

        missing_str = ", ".join(missing)
        system = (
            "Bạn là trợ lý thiết kế mạch điện tử. Người dùng đã hỏi nhưng thiếu thông tin. "
            "Hãy viết 1 đoạn ngắn (2-4 câu) bằng tiếng Việt, nhẹ nhàng hỏi lại "
            "những thông số còn thiếu, kèm ví dụ cụ thể để họ dễ trả lời. "
            "Trả về text thuần, KHÔNG JSON."
        )
        user_msg = (
            f'Câu hỏi gốc: "{user_text}"\n'
            f"Thông tin còn thiếu: {missing_str}"
        )
        return self._router.chat_text(
            LLMRole.GENERAL, mode=mode, system=system, user_content=user_msg,
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
            "Bạn là kỹ sư thiết kế mạch điện tử. "
            "Hệ thống rule-based không tìm được template phù hợp. "
            "Hãy thiết kế mạch dựa trên yêu cầu, trình bày theo 6 phần:\n"
            "1. **Bảng linh kiện** (tên, giá trị, công dụng)\n"
            "2. **Giải pháp** (topology, lý do chọn)\n"
            "3. **Chức năng mạch** (mô tả hoạt động)\n"
            "4. **Bước tính toán** (công thức, thay số, kết quả)\n"
            "5. **Thông số kỹ thuật** (bảng tóm tắt)\n"
            "6. **Kết quả kiểm tra** (nhận xét, cảnh báo)\n\n"
            "Dùng Markdown, tiếng Việt. Nếu không đủ thông tin, nêu giả định rõ ràng."
        )
        params_desc = []
        if intent.circuit_type:
            params_desc.append(f"Loại mạch: {intent.circuit_type}")
        if intent.gain_target is not None:
            params_desc.append(f"Gain mục tiêu: {intent.gain_target}")
        if intent.vcc is not None:
            params_desc.append(f"VCC: {intent.vcc}V")
        if intent.frequency is not None:
            params_desc.append(f"Tần số: {intent.frequency}Hz")
        params_str = "\n".join(params_desc) or "Không rõ thông số"

        user_msg = (
            f'Yêu cầu gốc: "{intent.raw_text}"\n'
            f"Thông số trích xuất:\n{params_str}\n"
            f"Lỗi rule-based: {error_msg}\n\n"
            f"Hãy thiết kế mạch phù hợp nhất."
        )
        logger.info(f"[LLM fallback] mode={mode.value}, intent={intent.circuit_type}, error={error_msg}")
        return self._router.chat_text(
            LLMRole.GENERAL, mode=mode, system=system, user_content=user_msg,
            max_tokens=8192,
        )

    def _reasoning_explain(self, intent: CircuitIntent, mode: LLMMode) -> Optional[str]:
        """Dùng LLM role chung giải thích mạch điện tử."""
        if not self._router.is_available(LLMRole.GENERAL, mode=mode):
            return None

        system = (
            "Bạn là kỹ sư thiết kế mạch điện tử. "
            "Giải thích chi tiết về mạch điện tử theo yêu cầu, bao gồm:\n"
            "1. **Nguyên lý hoạt động** - cách mạch hoạt động\n"
            "2. **Chức năng từng linh kiện** - vai trò của mỗi thành phần\n"
            "3. **Công thức và tính toán** - các công thức quan trọng\n"
            "4. **Ưu/nhược điểm** - khi nào nên dùng\n"
            "5. **Ứng dụng thực tế** - các ứng dụng phổ biến\n\n"
            "Dùng Markdown, tiếng Việt."
        )
        user_msg = f'Yêu cầu: "{intent.raw_text}"\nLoại mạch: {intent.circuit_type or "chưa xác định"}'
        return self._router.chat_text(
            LLMRole.GENERAL, mode=mode, system=system, user_content=user_msg,
            max_tokens=4096,
        )

    def _resolve_chat_mode(self, mode: Optional[str]) -> LLMMode:
        if mode:
            value = str(mode).strip().lower()
            if value == "pro":
                return LLMMode.PRO
            if value == "air":
                return LLMMode.AIR
        default_mode = (
            os.getenv("GoogleCloud_Default_Mode")
            or os.getenv("Google_Cloud_Default_Mode")
            or os.getenv("DEFAULT_MODE")
            or "air"
        ).strip().lower()
        return LLMMode.PRO if default_mode == "pro" else LLMMode.AIR

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
        return UserSpec(
            circuit_type=intent.circuit_type,
            gain=intent.gain_target,
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
            device_preference=intent.device_preference,
            extra_requirements=list(intent.extra_requirements),
            confidence=intent.confidence,
            source=intent.source,
            raw_text=intent.raw_text,
        )

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

        topology_metrics = ParameterSolver().analyze_topology(
            family=intent.circuit_type,
            solved_values=solved_values,
            gain_actual=gain_actual,
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

        simulation = self._maybe_auto_simulation(intent, circuit_data)

        return {
            "parameters": {
                "circuit_type": intent.circuit_type,
                "gain_target": intent.gain_target,
                "gain_actual": gain_actual,
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
                    "computed_gain": gain_actual,
                }
            },
            "simulation": simulation,
        }

    def _maybe_auto_simulation(self, intent: CircuitIntent, circuit_data: Dict[str, Any]) -> Dict[str, Any]:
        """Try transient simulation when explicitly requested or enabled by env flag."""
        if not self._should_auto_simulate(intent):
            return {"status": "skipped", "reason": "not_requested"}

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

    def _should_auto_simulate(self, intent: CircuitIntent) -> bool:
        force_env = (os.getenv("CHATBOT_AUTO_SIMULATE", "false").strip().lower() in {"1", "true", "yes", "on"})
        text = (intent.raw_text or "").lower()
        keyword = any(k in text for k in ["mô phỏng", "mo phong", "simulate", "ngspice", "waveform"])
        return force_env or keyword

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
            direction = str(p.get("direction", "")).lower()
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
            probes = ["v(in)", "v(out)"]
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
        in_ports = [p for p in ports if str(p.get("direction", "")).lower() == "input"]
        return max(1, len(in_ports))

    def _estimate_voltage_range(self, intent: CircuitIntent, circuit_data: Dict[str, Any]) -> Dict[str, Optional[float]]:
        # For single supply: [0, VCC], for dual supply: [-VCC, VCC] if available.
        if intent.vcc is None:
            return {"min": None, "max": None}
        if intent.supply_mode == "dual_supply":
            return {"min": -float(intent.vcc), "max": float(intent.vcc)}
        return {"min": 0.0, "max": float(intent.vcc)}

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
