# .\\thesis\\electronic-chatbot\\apps\\api\\app\\interfaces\\http\\routes\\chatbot.py
"""API routes cho Chatbot - Chat messages + circuit export.

Module này cung cấp HTTP endpoints (routes) cho chatbot functionality:
- POST /api/chat: Gửi message, nhận response từ chatbot
- POST /api/chat/export-kicad: Export circuit_data → .kicad_sch file
- GET /api/chat/info: Thông tin hệ thống
- GET /api/chat/health: Health check endpoint

Vietnamese:
- Trách nhiệm: Handle HTTP requests cho chatbot operations
- Endpoints: chat, chat/export-kicad, chat/info, chat/health
- Response: JSON messages, generated .kicad_sch files, system info

English:
- Responsibility: Handle HTTP requests for chatbot operations
- Endpoints: chat, chat/export-kicad, chat/info, chat/health
- Response: JSON messages, generated .kicad_sch files, system info
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# asyncio: Handle concurrent chat requests
# typing: Type hints cho request/response models
# fastapi: HTTP routing, exception handling
# pydantic: Request/response validation
import asyncio
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import logging
import os
from pathlib import Path

from app.core.timezone import to_api_timestamp
from app.db.database import SessionLocal
from app.infrastructure.repositories.chat_context_repository import (
    ChatHistoryRepository,
    SummaryMemoryRepository,
)
from app.infrastructure.repositories.circuit_artifact_repository import CircuitArtifactRepository

logger = logging.getLogger(__name__)


def _env_flag(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


# ── Request/Response models ──

class ChatRequest(BaseModel):
    """Request body cho chat endpoint."""
    message: str = Field(..., min_length=1, max_length=2000, description="User message")
    mode: Optional[str] = Field(None, description="Model tier: fast | think | pro | ultra")
    session_id: Optional[str] = Field(None, description="Session ID for conversation tracking")
    user_id: Optional[str] = Field(None, description="User ID for memory/context tracking")


class ChatResponseModel(BaseModel):
    """Response body cho chat endpoint."""
    message: str = Field(..., description="Bot response (markdown)")
    success: bool = Field(True, description="Pipeline success status")
    processing_time_ms: float = Field(0, description="Processing time in ms")
    mode: str = Field("air", description="Applied chat mode")
    needs_clarification: bool = Field(False, description="Need more info from user")
    template_id: str = Field("", description="Matched template ID")
    intent: Optional[Dict[str, Any]] = Field(None, description="Parsed intent")
    pipeline: Optional[Dict[str, Any]] = Field(None, description="Pipeline result")
    params: Optional[Dict[str, Any]] = Field(None, description="Solved parameters")
    analysis: Optional[Dict[str, Any]] = Field(None, description="Structured engineering analysis")
    circuit_data: Optional[Dict[str, Any]] = Field(None, description="Circuit IR data")
    validation_error: Optional[str] = Field(None, description="IR validation/normalization error")
    suggestions: List[str] = Field(default_factory=list, description="Suggested queries")
    session_id: Optional[str] = Field(None, description="Resolved session id")
    user_message_id: Optional[str] = Field(None, description="Persisted user message id")
    assistant_message_id: Optional[str] = Field(None, description="Persisted assistant message id")
    download_url: Optional[str] = Field(None, description="Download URL for generated .kicad_sch artifact")
    spice_deck_ready: Optional[bool] = Field(None, description="Whether SPICE deck artifact is ready")
    spice_deck_url: Optional[str] = Field(None, description="Download URL for generated .cir artifact")
    spice_deck: Optional[str] = Field(None, description="Generated SPICE deck text")
    artifact_id: Optional[str] = Field(None, description="Artifact correlation id")
    self_correction_retries: Optional[int] = Field(None, description="Retries used in IR self-correction loop")
    ir_id: Optional[str] = Field(None, description="Persisted circuit_ir identifier for keep/compose flow")


class EditUserMessageRequest(BaseModel):
    """Payload to edit an existing user message in conversation history."""
    session_id: Optional[str] = Field(
        None,
        min_length=1,
        max_length=64,
        description="Optional session id / chat id for integrity check",
    )
    content: str = Field(..., min_length=1, max_length=4000, description="Edited message content")


class EditUserMessageResponse(BaseModel):
    message_id: str
    session_id: str
    chat_id: str
    role: str
    status: str
    content: str
    created_at: str


class SystemInfoResponse(BaseModel):
    """System information response."""
    name: str
    version: str
    supported_families: List[str]
    template_count: int
    gemini_enabled: bool
    features: List[str]


class DebugMessageItem(BaseModel):
    id: str
    role: str
    content: str
    status: str
    created_at: str


class DebugSummaryItem(BaseModel):
    id: str
    version: int
    source_message_count: int
    token_estimate: int
    summary_text: str
    updated_at: str


class DebugHistoryResponse(BaseModel):
    session_id: str
    message_count: int
    summary_count: int
    messages: List[DebugMessageItem]
    summaries: List[DebugSummaryItem]


class SimulationAnalysisRequest(BaseModel):
    type: str = Field(default="transient", description="Simulation type. Currently supports: transient")
    step: str = Field(default="10us", description="Transient step time")
    stop: str = Field(default="20ms", description="Transient stop time (max 20 ms)")
    start: str = Field(default="0", description="Transient start time")


class SimulationRequest(BaseModel):
    netlist: Optional[str] = Field(default="", description="SPICE netlist body without .control block")
    probes: List[str] = Field(default_factory=lambda: ["v(out)"], description="Probe vectors, e.g. v(out), i(v1)")
    analysis: SimulationAnalysisRequest = Field(default_factory=SimulationAnalysisRequest)
    circuit_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional circuit_data payload. If provided, backend auto-extracts analysis_type/tran_* /nodes_to_monitor/source_params",
    )
    analysis_type: Optional[str] = Field(default=None, description="Schema field for analysis type (transient)")
    tran_step: Optional[Any] = Field(default=None, description="Schema field for transient step")
    tran_stop: Optional[Any] = Field(default=None, description="Schema field for transient stop")
    tran_start: Optional[Any] = Field(default=None, description="Schema field for transient start")
    nodes_to_monitor: Optional[List[str]] = Field(default=None, description="Schema field for probe vectors")
    source_params: Optional[Dict[str, Any]] = Field(default=None, description="Schema field for SIN source setup")
    circuit_id: Optional[str] = Field(
        default=None,
        description="Optional circuit id used to resolve spice_deck artifact when payload has no netlist",
    )


class WaveformTraceResponse(BaseModel):
    name: str
    x: List[float]
    y: List[float]
    unit: str = ""


class WaveformResponse(BaseModel):
    x_label: str
    traces: List[WaveformTraceResponse]


class SimulationResponse(BaseModel):
    success: bool
    analysis: Dict[str, Any]
    waveform: WaveformResponse
    points: int
    execution_time_ms: float


class CompileCircuitRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=3000, description="Natural language circuit requirements")
    mode: Optional[str] = Field(None, description="Model tier: fast | think | pro | ultra")


class CompileCircuitResponse(BaseModel):
    message: str
    mode: str
    circuit_data: Dict[str, Any]
    download_url: str
    spice_deck_ready: bool
    spice_deck: str
    spice_deck_url: str
    self_correction_retries: int
    artifact_id: str


class SpiceStreamRequest(BaseModel):
    spice_deck: str = Field(..., min_length=1, description="Full SPICE deck text")


# ── Router ──

router = APIRouter(prefix="/api/chat", tags=["chatbot"])

# Singleton chatbot service
_chatbot_service = None
_simulation_service = None
_API_ROOT = Path(__file__).resolve().parents[4]
_COMPILED_DIR = _API_ROOT / "artifacts" / "compiled"


def _get_chatbot_service():
    """Lazy init chatbot service."""
    global _chatbot_service
    if _chatbot_service is None:
        from app.application.ai.chatbot_service import ChatbotService
        _chatbot_service = ChatbotService()
    return _chatbot_service


def _get_simulation_service():
    """Lazy init ngspice simulation service."""
    global _simulation_service
    if _simulation_service is None:
        from app.application.ai.simulation_service import NgSpiceSimulationService

        _simulation_service = NgSpiceSimulationService()
    return _simulation_service


# ── Endpoints ──

@router.post("")
async def chat(request: ChatRequest) -> StreamingResponse:
    """Stream chatbot response as SSE.

    Emits events:
      - `thinking`: during LLM generation
      - `circuit_ready`: single source of truth for circuit data and artifact URLs
      - `text`: final textual NLG chunk
    """

    service = _get_chatbot_service()

    async def _sse_gen():
        import json

        # initial thinking event
        yield f"event: thinking\ndata: {json.dumps({'status': 'processing'})}\n\n"

        try:
            try:
                result = await service.chat(
                    request.message,
                    session_id=request.session_id,
                    user_id=request.user_id,
                    mode=request.mode,
                )
            except Exception as llm_exc:
                # Emit explicit LLM error early so clients can stop waiting for CIR
                import json

                logger.exception("LLM generation failed during chat()")
                yield f"event: error\ndata: {json.dumps({'phase':'llm','error':'llm_generation_failed','message':str(llm_exc)})}\n\n"
                return

            if result.circuit_data:
                from app.application.ai.circuit_ir_schema import CircuitIR as _CircuitIR
                cid = result.circuit_id or result.circuit_data.get("circuit_id")

                # Strip mọi field không thuộc CircuitIR schema (circuit_id, meta, v.v.)
                _valid_keys = set(_CircuitIR.model_fields.keys())
                clean = {k: v for k, v in result.circuit_data.items() if k in _valid_keys}

                yield f"event: circuit_ready\ndata: {json.dumps({'circuit_id': cid, 'circuit_data': clean, 'sch_url': result.sch_url, 'spice_url': result.spice_url, 'session_id': result.session_id, 'user_message_id': result.user_message_id, 'assistant_message_id': result.assistant_message_id})}\n\n"
                yield f"event: render_ready\ndata: {json.dumps({'circuit_id': cid, 'sch_url': result.sch_url, 'pcb_url': None, 'ngspice_url': result.spice_url})}\n\n"

            # ── Text event: include analysis/intent/pipeline/params so the
            # right-panel tabs (Thông số, Phân tích) can be populated. ──
            text_payload: Dict[str, Any] = {
                "message": result.message,
                "mode": result.mode,
                "success": result.success,
                "processing_time_ms": round(result.processing_time_ms, 1),
            }
            if result.intent:
                text_payload["intent"] = result.intent
            if result.pipeline:
                text_payload["pipeline"] = result.pipeline
            if result.params:
                text_payload["params"] = result.params
            if result.analysis:
                text_payload["analysis"] = result.analysis
            if result.validation:
                text_payload["validation"] = result.validation
            if result.physics_validation:
                text_payload["physics_validation"] = result.physics_validation
            if result.suggestions:
                text_payload["suggestions"] = result.suggestions
            if result.template_id:
                text_payload["template_id"] = result.template_id
            if result.circuit_id or (result.circuit_data and result.circuit_data.get("circuit_id")):
                text_payload["circuit_id"] = result.circuit_id or result.circuit_data.get("circuit_id")
            yield f"event: text\ndata: {json.dumps(text_payload, ensure_ascii=False)}\n\n"

        except Exception as e:
            import json

            logger.error("Chat SSE failed", exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error':'chat_failed','message':str(e)})}\n\n"

    return StreamingResponse(_sse_gen(), media_type="text/event-stream")


@router.post("/compile-circuit", response_model=CompileCircuitResponse)
async def compile_circuit(request: CompileCircuitRequest) -> CompileCircuitResponse:
    """End-to-end compile flow: generate CircuitIR, validate, export kicad_sch and spice deck."""
    try:
        service = _get_chatbot_service()
        result = service.compile_circuit_artifacts(
            user_text=request.message,
            mode=request.mode,
            max_self_corrections=2,
        )
        return CompileCircuitResponse(**result)
    except Exception as e:
        logger.error("Compile circuit endpoint error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "compile_circuit_failed", "message": str(e)},
        )


@router.get("/compiled/{file_name}")
async def get_compiled_artifact(file_name: str) -> PlainTextResponse:
    """Serve generated .kicad_sch/.cir artifact files for frontend preview/download."""
    safe_name = Path(file_name).name
    if not safe_name.endswith((".kicad_sch", ".cir")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_file_name", "message": "Unsupported artifact extension"},
        )

    _COMPILED_DIR.mkdir(parents=True, exist_ok=True)
    artifact_path = (_COMPILED_DIR / safe_name).resolve()
    base_path = _COMPILED_DIR.resolve()
    if artifact_path.parent != base_path or not artifact_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "artifact_not_found", "message": "Artifact file not found"},
        )

    content = artifact_path.read_text(encoding="utf-8", errors="ignore")
    return PlainTextResponse(
        content=content,
        media_type="text/plain",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        },
    )


@router.post("/simulate/spice-stream")
async def simulate_spice_stream(request: SpiceStreamRequest) -> StreamingResponse:
    """Stream ngspice data points from a full SPICE deck as SSE frames."""
    from app.application.ai.simulation_service import NgspiceCompilerService

    compiler = NgspiceCompilerService()

    async def event_gen():
        async for json_line in compiler.run_simulation_stream(request.spice_deck):
            yield f"data: {json_line}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.patch("/messages/{message_id}", response_model=EditUserMessageResponse)
async def edit_user_message(
    message_id: str,
    request: EditUserMessageRequest,
) -> EditUserMessageResponse:
    """Edit a user request message and persist update to Neon database."""
    db = SessionLocal()
    try:
        chat_repo = ChatHistoryRepository(db)
        message = chat_repo.get_message(message_id)
        if message is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "message_not_found",
                    "message": f"Message '{message_id}' not found",
                },
            )

        message_chat_id = str(message.chat_id)
        chat = chat_repo.get_chat(message_chat_id)
        resolved_session_id = str(chat.session_id) if chat is not None else message_chat_id

        provided_id = str(request.session_id or "").strip()
        if provided_id and provided_id not in {message_chat_id, resolved_session_id}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "session_mismatch",
                    "message": "Message does not belong to the provided session/chat",
                },
            )

        if str(message.role).lower() != "user":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "invalid_role",
                    "message": "Only user messages can be edited",
                },
            )

        updated = chat_repo.update_message_content(
            message_id=message_id,
            chat_id=message_chat_id,
            new_content=request.content.strip(),
            status="edited",
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "message_not_found",
                    "message": f"Message '{message_id}' not found",
                },
            )

        return EditUserMessageResponse(
            message_id=str(updated.id),
            session_id=resolved_session_id,
            chat_id=message_chat_id,
            role=str(updated.role),
            status=str(updated.status),
            content=updated.content,
            created_at=to_api_timestamp(updated.created_at),
        )
    finally:
        db.close()


@router.get("/info", response_model=SystemInfoResponse)
async def system_info() -> SystemInfoResponse:
    """Thông tin hệ thống chatbot."""
    from app.core.config import settings
    service = _get_chatbot_service()
    families = service.get_supported_families()
    templates = service.get_supported_circuits()

    gemini_enabled = bool(
        (
            os.getenv("Google_Cloud_Project_ID")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
            or os.getenv("GCP_PROJECT")
            or os.getenv("Google_Cloud_API_Key")
            or os.getenv("GOOGLE_CLOUD_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or ""
        ).strip()
    )

    return SystemInfoResponse(
        name="Electronic Circuit Chatbot",
        version="1.0.0",
        supported_families=families,
        template_count=len(templates),
        gemini_enabled=gemini_enabled,
        features=[
            "NLP (Rule-based + Gemini)",
            "70+ circuit templates",
            "Parameter solving (E-series snap)",
            "Domain validation",
            "Vietnamese + English support",
            "KiCanvas schematic rendering",
            "NGSpice transient simulation",
            "Waveform streaming for web charts",
        ],
    )


@router.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check cho chatbot API."""
    return {
        "status": "healthy",
        "service": "chatbot-api",
    }


@router.get("/debug/history/{session_id}", response_model=DebugHistoryResponse)
async def debug_history(
    session_id: str,
    message_limit: int = Query(50, ge=1, le=500),
    summary_limit: int = Query(20, ge=1, le=200),
) -> DebugHistoryResponse:
    """Debug endpoint: đọc lại messages/summaries theo session_id."""
    db = SessionLocal()
    try:
        chat_repo = ChatHistoryRepository(db)
        summary_repo = SummaryMemoryRepository(db)

        chat = chat_repo.get_chat(session_id)
        if not chat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "session_not_found", "message": f"Session '{session_id}' not found"},
            )

        messages = chat_repo.list_messages(chat_id=session_id, limit=message_limit)
        summaries = summary_repo.list_summaries(chat_id=session_id, limit=summary_limit)

        return DebugHistoryResponse(
            session_id=session_id,
            message_count=len(messages),
            summary_count=len(summaries),
            messages=[
                DebugMessageItem(
                    id=m.id,
                    role=m.role,
                    content=m.content,
                    status=m.status,
                    created_at=to_api_timestamp(m.created_at),
                )
                for m in messages
            ],
            summaries=[
                DebugSummaryItem(
                    id=s.id,
                    version=s.version,
                    source_message_count=s.source_message_count,
                    token_estimate=s.token_estimate,
                    summary_text=s.summary_text,
                    updated_at=to_api_timestamp(s.updated_at),
                )
                for s in summaries
            ],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Debug history endpoint error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "debug_history_unavailable", "message": str(e)},
        )
    finally:
        db.close()


@router.post("/simulate", response_model=SimulationResponse)
async def simulate_circuit(request: SimulationRequest) -> SimulationResponse:
    """Run NGSpice transient simulation and return waveform data for frontend charts."""
    simulator = _get_simulation_service()
    try:
        if request.circuit_data is not None:
            sim_payload = dict(request.circuit_data)
            if request.analysis_type is not None:
                sim_payload["analysis_type"] = request.analysis_type
            if request.tran_step is not None:
                sim_payload["tran_step"] = request.tran_step
            if request.tran_stop is not None:
                sim_payload["tran_stop"] = request.tran_stop
            if request.tran_start is not None:
                sim_payload["tran_start"] = request.tran_start
            if request.nodes_to_monitor is not None:
                sim_payload["nodes_to_monitor"] = request.nodes_to_monitor
            if request.source_params is not None:
                sim_payload["source_params"] = request.source_params
            if request.netlist:
                sim_payload.setdefault("spice_netlist", request.netlist)

            # Step 1: payload resolution chain (backward compatible)
            netlist = (
                sim_payload.get("spice_netlist")
                or sim_payload.get("netlist")
                or sim_payload.get("ngspice_netlist")
            )
            if netlist:
                sim_payload["spice_netlist"] = netlist

            # Step 2: fallback to artifact DB
            if not sim_payload.get("spice_netlist"):
                resolved_circuit_id = (
                    str(request.circuit_id or "").strip()
                    or str(sim_payload.get("circuit_id") or "").strip()
                    or str((sim_payload.get("meta") or {}).get("circuit_id") or "").strip()
                )
                logger.info(
                    "SPICE_RESOLVE_INPUT",
                    extra={
                        "stage": "SPICE_RESOLVE_INPUT",
                        "request_circuit_id": str(request.circuit_id or "").strip(),
                        "payload_circuit_id": str(sim_payload.get("circuit_id") or "").strip(),
                        "resolved_circuit_id": resolved_circuit_id,
                    },
                )
                if resolved_circuit_id:
                    db = SessionLocal()
                    try:
                        artifact_repo = CircuitArtifactRepository(db)
                        artifact = await artifact_repo.get_by_circuit_and_type(
                            circuit_id=resolved_circuit_id,
                            artifact_type="spice_deck",
                        )
                    finally:
                        db.close()

                    if artifact is None or not str(getattr(artifact, "content", "")).strip():
                        raise HTTPException(
                            status_code=404,
                            detail=(
                                f"No spice_deck artifact for circuit_id={resolved_circuit_id}. "
                                "Call POST /api/chat first."
                            ),
                        )
                    sim_payload["spice_netlist"] = artifact.content
                    logger.info(
                        "SPICE_RESOLVE_ARTIFACT",
                        extra={
                            "stage": "SPICE_RESOLVE_ARTIFACT",
                            "circuit_id": resolved_circuit_id,
                            "artifact_id": artifact.id,
                        },
                    )
                else:
                    # Keep previous behavior as last resort when circuit_id is absent.
                    try:
                        from app.application.ai.simulation_service import NgspiceCompilerService
                        from app.application.ai.circuit_ir_schema import CircuitIR as AppCircuitIR

                        ir_dict = _template_to_ir_dict(sim_payload, normalize_power_rails=True)
                        app_ir_dict = _convert_template_ir_to_app_ir(ir_dict)
                        app_ir = AppCircuitIR.model_validate(app_ir_dict)
                        deck = NgspiceCompilerService().generate_spice_deck(app_ir)
                        sim_payload.setdefault("spice_netlist", deck)
                    except Exception as synth_exc:
                        logger.warning(
                            "Server-side netlist synthesis failed (no circuit_id, no inline netlist): %s",
                            synth_exc,
                            exc_info=True,
                        )

            result = simulator.simulate_from_circuit_data(sim_payload)
        else:
            if request.analysis.type.lower() != "transient":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "unsupported_analysis", "message": "Only transient analysis is supported"},
                )

            from app.application.ai.transient_window import (
                apply_transient_window_defaults,
                compute_transient_window,
                extract_frequency_hz,
                format_time_seconds,
            )

            netlist_only: Dict[str, Any] = {
                "source_params": request.source_params or {},
            }
            apply_transient_window_defaults(
                netlist_only,
                max_points=simulator._max_points,
                overwrite=True,
            )
            stop_s, step_s = compute_transient_window(
                extract_frequency_hz(netlist_only),
                max_points=simulator._max_points,
            )

            result = simulator.simulate_transient(
                netlist=request.netlist,
                probes=request.probes,
                step=format_time_seconds(step_s),
                stop=format_time_seconds(stop_s),
                start="0",
            )

        payload = result.to_dict()
        return SimulationResponse(**payload)
    except HTTPException:
        raise
    except Exception as e:
        from app.application.ai.simulation_service import simulation_error_http_detail

        logger.error("Simulation endpoint error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=simulation_error_http_detail(e),
        )


@router.post("/simulate/stream")
async def simulate_circuit_stream(request: SimulationRequest) -> StreamingResponse:
    """Run simulation with SSE progress events for near real-time chatbot UX."""
    from app.application.ai.simulation_service import simulation_error_http_detail, to_sse_event

    simulator = _get_simulation_service()

    async def event_gen():
        yield to_sse_event("progress", {"status": "queued", "message": "Simulation queued"})
        await asyncio.sleep(0)
        yield to_sse_event("progress", {"status": "running", "message": "Running ngspice"})
        await asyncio.sleep(0)

        try:
            if request.circuit_data is not None:
                sim_payload = dict(request.circuit_data)
                if request.analysis_type is not None:
                    sim_payload["analysis_type"] = request.analysis_type
                if request.tran_step is not None:
                    sim_payload["tran_step"] = request.tran_step
                if request.tran_stop is not None:
                    sim_payload["tran_stop"] = request.tran_stop
                if request.tran_start is not None:
                    sim_payload["tran_start"] = request.tran_start
                if request.nodes_to_monitor is not None:
                    sim_payload["nodes_to_monitor"] = request.nodes_to_monitor
                if request.source_params is not None:
                    sim_payload["source_params"] = request.source_params
                if request.netlist:
                    sim_payload.setdefault("spice_netlist", request.netlist)

                # Step 1: payload resolution chain
                netlist = (
                    sim_payload.get("spice_netlist")
                    or sim_payload.get("netlist")
                    or sim_payload.get("ngspice_netlist")
                )
                if netlist:
                    sim_payload["spice_netlist"] = netlist

                # Step 2: fallback to artifact DB
                if not sim_payload.get("spice_netlist"):
                    resolved_circuit_id = (
                        str(request.circuit_id or "").strip()
                        or str(sim_payload.get("circuit_id") or "").strip()
                        or str((sim_payload.get("meta") or {}).get("circuit_id") or "").strip()
                    )
                    if resolved_circuit_id:
                        try:
                            db = SessionLocal()
                            try:
                                artifact_repo = CircuitArtifactRepository(db)
                                artifact = await artifact_repo.get_by_circuit_and_type(
                                    circuit_id=resolved_circuit_id,
                                    artifact_type="spice_deck",
                                )
                            finally:
                                db.close()
                            if artifact and str(getattr(artifact, "content", "")).strip():
                                sim_payload["spice_netlist"] = artifact.content
                                logger.info(
                                    "SPICE_RESOLVE_ARTIFACT (stream)",
                                    extra={"stage": "SPICE_RESOLVE_ARTIFACT", "circuit_id": resolved_circuit_id},
                                )
                        except Exception:
                            logger.debug("Artifact lookup failed in stream path", exc_info=True)

                # Step 3: server-side synthesis fallback
                if not sim_payload.get("spice_netlist"):
                    try:
                        from app.application.ai.simulation_service import NgspiceCompilerService
                        from app.application.ai.circuit_ir_schema import CircuitIR as AppCircuitIR

                        ir_dict = _template_to_ir_dict(sim_payload, normalize_power_rails=True)
                        app_ir_dict = _convert_template_ir_to_app_ir(ir_dict)
                        app_ir = AppCircuitIR.model_validate(app_ir_dict)
                        deck = NgspiceCompilerService().generate_spice_deck(app_ir)
                        sim_payload.setdefault("spice_netlist", deck)
                    except Exception as synth_exc:
                        logger.warning(
                            "Server-side netlist synthesis failed in stream path: %s",
                            synth_exc,
                            exc_info=True,
                        )

                result = simulator.simulate_from_circuit_data(sim_payload)
            else:
                if request.analysis.type.lower() != "transient":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={"error": "unsupported_analysis", "message": "Only transient analysis is supported"},
                    )

                from app.application.ai.transient_window import (
                    apply_transient_window_defaults,
                    format_time_seconds,
                    compute_transient_window,
                    extract_frequency_hz,
                )

                netlist_only: Dict[str, Any] = {
                    "source_params": request.source_params or {},
                }
                apply_transient_window_defaults(
                    netlist_only,
                    max_points=simulator._max_points,
                    overwrite=True,
                )
                stop_s, step_s = compute_transient_window(
                    extract_frequency_hz(netlist_only),
                    max_points=simulator._max_points,
                )
                step = format_time_seconds(step_s)
                stop = format_time_seconds(stop_s)

                result = simulator.simulate_transient(
                    netlist=request.netlist,
                    probes=request.probes,
                    step=step,
                    stop=stop,
                    start="0",
                )

            yield to_sse_event("result", result.to_dict())
        except Exception as exc:
            yield to_sse_event("error", simulation_error_http_detail(exc))

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/templates")
async def list_templates(category: Optional[str] = None) -> Dict[str, Any]:
    """Liệt kê templates có sẵn."""
    service = _get_chatbot_service()
    templates = service.get_supported_circuits()

    if category:
        templates = [t for t in templates if t.get("category") == category]

    return {
        "total": len(templates),
        "templates": templates,
    }


# ── KiCad Export ── #

# In-memory cache for exported KiCad schematics (simple dict, production would use Redis/TTL)
import uuid as _uuid
_kicad_cache: Dict[str, str] = {}

class ExportKicadRequest(BaseModel):
    """Request body cho KiCad export."""
    circuit_data: Dict[str, Any] = Field(..., description="Circuit data from pipeline")
    circuit_id: Optional[str] = Field(None, description="Circuit UUID for exporter context")


def _template_to_ir_dict(circuit_data: Dict[str, Any], normalize_power_rails: bool = False) -> Dict[str, Any]:
    """
    Chuyển template circuit_data (từ circuit_generator) sang IR dict
    mà CircuitIRSerializer.to_circuit() hiểu được.

    Template format:
      components[].kicad.{library_id, symbol_name, footprint}
      components[].parameters.resistance = 47000
      nets[].id, nets[].connections = [["R1","1"], ["Q1","C"]]
      ports[].id, ports[].direction, ports[].net

    IR format:
      components[].library_id, .symbol_name, .footprint (flat)
      components[].parameters.resistance = { "value": 47000 }
      nets[].name, .connected_pins = [{"component_id":"R1","pin_name":"1"}]
      ports[].name, .net_name, .direction
    """
    power_rail_ids = set()

    def _normalize_component_id(comp: Dict[str, Any], index: int) -> str:
        candidates = [
            comp.get("id"),
            comp.get("ref"),
            comp.get("ref_id"),
            comp.get("component_id"),
            comp.get("name"),
        ]
        comp_type = str(comp.get("type", "component")).strip().lower().replace(" ", "_")
        prefix_map = {
            "resistor": "R",
            "capacitor": "C",
            "inductor": "L",
            "power_supply": "V",
            "voltage_source": "V",
            "current_source": "I",
            "ground": "GND",
            "connector": "X",
            "bjt_npn": "Q",
            "bjt_pnp": "Q",
            "mosfet_n": "M",
            "mosfet_p": "M",
            "jfet_n": "J",
            "jfet_p": "J",
            "opamp_ic": "U",
        }
        fallback = f"{prefix_map.get(comp_type, 'X')}{index + 1}"
        for candidate in candidates:
            text = str(candidate or "").strip().upper()
            if text:
                return text
        return fallback

    # Components
    ir_components = []
    seen_component_ids = set()
    for idx, comp in enumerate(circuit_data.get("components", [])):
        kicad_info = comp.get("kicad", {})
        comp_id = _normalize_component_id(comp, idx)
        suffix = 2
        base_comp_id = comp_id
        while comp_id in seen_component_ids or not comp_id:
            comp_id = f"{base_comp_id}_{suffix}"
            suffix += 1
        seen_component_ids.add(comp_id)
        comp_type = comp.get("type", "resistor").strip().lower()
        if comp_type in {"powersymbol", "power_symbol", "power symbol"}:
            comp_type = "power_symbol"
        # Normalize common legacy/short aliases to canonical IR types
        if comp_type in {"power", "pwr", "vcc", "vdd", "vss", "vee", "vccg", "power_supply"}:
            comp_type = "power_symbol"
        if comp_type in {"power_port", "pwr_port", "vcc_port", "gnd_port"}:
            comp_type = "port"
        if comp_type in {"gnd", "ground", "0", "vss"}:
            comp_type = "ground"
        if comp_type in {"op-amp", "op_amp", "opamp", "op amp"}:
            comp_type = "opamp"

        # Merge template position into render_style so manual coordinates can be honored.
        render_style = dict(comp.get("render_style", {}) or {})
        template_pos = comp.get("position")
        if isinstance(template_pos, dict):
            if "x" in template_pos and "y" in template_pos:
                render_style.setdefault("position", {
                    "x": template_pos.get("x", 0),
                    "y": template_pos.get("y", 0),
                })
            if "pcb_x" in template_pos and "pcb_y" in template_pos:
                render_style.setdefault("pcb_position", {
                    "x": template_pos.get("pcb_x"),
                    "y": template_pos.get("pcb_y"),
                })

        # For schematic readability, normalize rail sources (VCC/VDD/VSS/VEE) to one-pin symbols.
        pins = list(comp.get("pins", []))
        rail_id_norm = str(comp_id).strip().upper()
        is_power_rail_source = (
            comp_type in {"voltage_source", "current_source"}
            and rail_id_norm in {"VCC", "VDD", "VSS", "VEE"}
        )
        if comp_type == "power_symbol":
            power_rail_ids.add(str(comp_id).strip().upper())
            pins = ["1"]
        if normalize_power_rails and is_power_rail_source:
            power_rail_ids.add(str(comp_id).strip().upper())
            pins = ["1"]

        # Convert parameters: raw value → {"value": v}
        ir_params = {}
        source_params = dict(comp.get("parameters", {}) or {})

        if comp_type == "resistor" and "resistance" not in source_params:
            fallback_resistance = comp.get("resistance") or comp.get("standardized_value") or comp.get("value")
            if fallback_resistance not in (None, ""):
                source_params["resistance"] = fallback_resistance
        elif comp_type == "capacitor" and "capacitance" not in source_params:
            fallback_capacitance = comp.get("capacitance") or comp.get("standardized_value") or comp.get("value")
            if fallback_capacitance not in (None, ""):
                source_params["capacitance"] = fallback_capacitance
        elif comp_type == "inductor" and "inductance" not in source_params:
            fallback_inductance = comp.get("inductance") or comp.get("standardized_value") or comp.get("value")
            if fallback_inductance not in (None, ""):
                source_params["inductance"] = fallback_inductance
        elif comp_type == "voltage_source" and "voltage" not in source_params:
            fallback_voltage = comp.get("voltage") or comp.get("value") or comp.get("standardized_value")
            if fallback_voltage not in (None, ""):
                source_params["voltage"] = fallback_voltage

        for key, val in source_params.items():
            # Normalize dict-shaped param values and ensure scalar values are stringified
            if isinstance(val, dict) and "value" in val:
                v = val.get("value")
                u = val.get("unit")
                ir_params[key] = {"value": str(v) if v is not None else "", "unit": u}
            else:
                ir_params[key] = {"value": str(val) if val is not None else ""}

        # Ensure top-level component 'value' and standardized_value are strings for strict schemas
        comp_value = comp.get("value")
        standardized = comp.get("standardized_value") or comp.get("std_value")
        if comp_value is not None:
            ir_comp_value = str(comp_value)
        elif "value" in ir_params:
            ir_comp_value = str(ir_params.get("value", {}).get("value", ""))
        else:
            ir_comp_value = ""
        if standardized is not None:
            ir_standardized = str(standardized)
        else:
            ir_standardized = ir_comp_value

        ir_comp = {
            "id": comp_id,
            "type": comp_type,
            "pins": pins,
            "parameters": ir_params,
            "value": ir_comp_value,
            "standardized_value": ir_standardized,
            "operating_point_check": comp.get("operating_point_check", ""),
            "kicad_symbol": kicad_info.get("symbol_name") or comp.get("kicad_symbol") or "",
            "library_id": kicad_info.get("library_id"),
            "symbol_name": kicad_info.get("symbol_name"),
            "footprint": None if comp_type == "power_symbol" else kicad_info.get("footprint"),
            "symbol_version": kicad_info.get("symbol_version"),
            "render_style": render_style,
        }
        ir_components.append(ir_comp)

    # Nets
    ir_nets = []
    for idx, net in enumerate(circuit_data.get("nets", []) or []):
        connected_pins = []
        # Support both template-style connections and CircuitIR-style nodes.
        net_connections = list(net.get("connections", []) or [])
        if not net_connections:
            for node in net.get("nodes", []) or []:
                text = str(node or "").strip()
                if ":" not in text:
                    continue
                ref, pin = text.split(":", 1)
                ref = ref.strip()
                pin = pin.strip()
                if ref and pin:
                    net_connections.append([ref, pin])

        for conn in net_connections:
            if isinstance(conn, list) and len(conn) >= 2:
                component_id = conn[0]
                component_key = str(component_id).strip().upper()
                pin_name = str(conn[1])

                if component_key in power_rail_ids:
                    # Drop negative rail terminal links for one-pin power symbols.
                    if pin_name in {"-", "2", "neg", "NEG", "n", "N"}:
                        continue
                    pin_name = "1"

                connected_pins.append({
                    "component_id": component_id,
                    "pin_name": pin_name,
                })
            elif isinstance(conn, dict):
                conn_copy = dict(conn)
                component_id = conn_copy.get("component_id")
                component_key = str(component_id or "").strip().upper()
                pin_name = str(conn_copy.get("pin_name", ""))
                if component_key in power_rail_ids:
                    if pin_name in {"-", "2", "neg", "NEG", "n", "N"}:
                        continue
                    conn_copy["pin_name"] = "1"
                connected_pins.append(conn_copy)  # already in IR format

        # Remove duplicate pin refs after rail normalization to satisfy Net invariants.
        deduped: List[Dict[str, str]] = []
        seen = set()
        for cp in connected_pins:
            comp_id = str(cp.get("component_id", "")).strip()
            pin = str(cp.get("pin_name", "")).strip()
            if not comp_id or not pin:
                continue
            key = (comp_id, pin)
            if key in seen:
                continue
            seen.add(key)
            deduped.append({"component_id": comp_id, "pin_name": pin})
        connected_pins = deduped

        # Normalize name: prefer explicit 'name' or common aliases, otherwise synthesize a stable name
        raw_name = net.get("name") or net.get("net_name") or net.get("id") or net.get("netName") or ""
        name = str(raw_name or "").strip()
        if not name:
            # try to derive from first connected pin, else synthesize index-based name
            if connected_pins:
                first = connected_pins[0]
                comp = first.get("component_id") or first.get("component") or "NET"
                pin = first.get("pin_name") or first.get("pin") or "1"
                name = f"{comp}_{pin}".upper()
            else:
                name = f"NET_{idx+1}"

        # Skip invalid empty nets to avoid Net entity hard-fail during export.
        if connected_pins:
            ir_nets.append({
                "name": name,
                "connected_pins": connected_pins,
            })

    # Ports
    ir_ports = []
    for port in circuit_data.get("ports", []):
        ir_ports.append({
            "name": port.get("name") or port.get("id", ""),
            "net_name": port.get("net_name") or port.get("net", ""),
            "direction": (port.get("direction") or "input").lower(),
        })

    # Constraints
    ir_constraints = []
    for constr in circuit_data.get("constraints", []):
        if isinstance(constr, dict) and "name" in constr:
            ir_constraints.append(constr)
        elif isinstance(constr, dict):
            # constraint dạng {"component": "R1", "param": "power_rating", ...}
            ir_constraints.append({
                "name": constr.get("component", "") + "_" + constr.get("param", ""),
                "value": constr.get("condition", ""),
                "target": constr.get("component"),
            })

    # Backfill missing pins from net connectivity for AI-generated skeletons.
    pins_by_component = {}
    for comp in ir_components:
        comp_id = comp.get("id", "")
        if comp_id:
            pins_by_component[comp_id] = list(comp.get("pins", []))

    for net in ir_nets:
        for conn in net.get("connected_pins", []):
            component_id = conn.get("component_id")
            pin_name = str(conn.get("pin_name", "")).strip()
            if not component_id or not pin_name:
                continue
            if component_id not in pins_by_component:
                pins_by_component[component_id] = []
            if pin_name not in pins_by_component[component_id]:
                pins_by_component[component_id].append(pin_name)

    # Create placeholder connector components for references present in nets but missing in components.
    known_component_ids = {str(comp.get("id", "")).strip() for comp in ir_components if comp.get("id")}
    for component_id, inferred_pins in pins_by_component.items():
        if component_id in known_component_ids:
            continue
        fallback_pins = inferred_pins or ["1"]
        ir_components.append({
            "id": component_id,
            "type": "connector",
            "pins": fallback_pins,
            "parameters": {},
            "value": "",
            "standardized_value": "",
            "operating_point_check": "",
            "kicad_symbol": "Connector:Conn_01x01",
            "library_id": None,
            "symbol_name": "Conn_01x01",
            "footprint": None,
            "symbol_version": None,
            "render_style": {},
        })
        known_component_ids.add(component_id)

    single_pin_types = {"connector", "port", "ground", "voltage_source", "current_source"}
    for comp in ir_components:
        comp_id = comp.get("id", "")
        comp_type = str(comp.get("type", "")).lower()
        pins = pins_by_component.get(comp_id, list(comp.get("pins", [])))

        if not pins:
            pins = ["1"] if comp_type in single_pin_types else ["1", "2"]

        if comp_type not in single_pin_types and len(pins) < 2:
            if "2" not in pins:
                pins.append("2")
            elif "1" not in pins:
                pins.insert(0, "1")

        comp["pins"] = pins

    return {
        "meta": {
            "version": "1.0",
            "schema_version": "1.0",
            "circuit_name": circuit_data.get("topology_type", "circuit"),
        },
        "components": ir_components,
        "nets": ir_nets,
        "ports": ir_ports,
        "constraints": ir_constraints,
        "topology_type": circuit_data.get("topology_type"),
        "category": circuit_data.get("category"),
        "tags": circuit_data.get("tags", []),
    }


def _convert_template_ir_to_app_ir(ir_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Create a minimal application-level CircuitIR dict from the template IR.

    The goal is to populate the required fields of the strict pydantic model
    with sensible defaults so the compiler can run. This is intentionally
    permissive and provides reasonable fallbacks.

    Topology detection: choose `architecture.stages[0].topology` based on the
    first detected active device (op-amp → non_inverting, BJT → common_emitter,
    MOSFET → common_source) so the compiler produces a correct deck for non-BJT
    designs (e.g. LM358 non-inverting amplifier).
    """
    meta = ir_dict.get("meta", {}) or {}
    components = ir_dict.get("components", []) or []
    nets = ir_dict.get("nets", []) or []
    ports = ir_dict.get("ports", []) or []

    # Detect topology hint up-front so it can drive both stage topology and
    # the choice of active_device_ref.
    topology_hint_raw = str(
        ir_dict.get("topology_type")
        or meta.get("topology_type")
        or meta.get("topology")
        or ""
    ).lower()

    # Map components
    app_components = []
    first_active: Optional[str] = None
    first_active_kind: Optional[str] = None
    for idx, c in enumerate(components):
        ref = str(c.get("id") or c.get("ref") or f"X{idx+1}").strip().upper()
        ctype = str(c.get("type") or "resistor").strip()
        # normalize some common aliases
        if "bjt" in ctype.lower():
            ctype_norm = "bjt_npn"
        elif "cap" in ctype.lower():
            ctype_norm = "capacitor"
        elif "ind" in ctype.lower():
            ctype_norm = "inductor"
        elif "opamp" in ctype.lower() or "op_amp" in ctype.lower() or "op-amp" in ctype.lower():
            ctype_norm = "opamp_ic"
        elif ctype.lower() in {"gnd", "ground"}:
            ctype_norm = "ground"
        elif ctype.lower() in {"vcc", "vdd", "voltage_source", "power_symbol"}:
            ctype_norm = "power_supply"
        else:
            ctype_norm = ctype.lower()

        params = c.get("parameters", {}) or {}
        # value extraction
        value = c.get("value") or ""
        if not value:
            # common param keys
            for key in ("resistance", "capacitance", "inductance", "voltage"):
                if key in params:
                    pv = params.get(key)
                    if isinstance(pv, dict):
                        value = pv.get("value", "")
                    else:
                        value = pv
                    break

        # model fallback (required by schema)
        model = "GENERIC"
        if "model" in params:
            mv = params.get("model")
            if isinstance(mv, dict):
                model = str(mv.get("value") or mv.get("model") or "GENERIC")
            else:
                model = str(mv)
        elif ctype_norm.startswith("bjt"):
            model = "QNPN"
        elif ctype_norm.startswith("mosfet"):
            model = "MOSFET"

        if first_active is None and ctype_norm.startswith(("bjt", "mosfet", "opamp")):
            first_active = ref
            if ctype_norm.startswith("opamp"):
                first_active_kind = "opamp"
            elif ctype_norm.startswith("bjt"):
                first_active_kind = "bjt"
            elif ctype_norm.startswith("mosfet"):
                first_active_kind = "mosfet"

        app_components.append({
            "ref": ref,
            "type": ctype_norm,
            "value": str(value or ""),
            "model": str(model),
            "role": c.get("role") or "unknown_passive",
            "topology_stage": int(c.get("topology_stage") or 0),
            "standardized_value": c.get("standardized_value") or c.get("std_value") or "",
            "operating_point_check": c.get("operating_point_check", ""),
            "footprint": c.get("footprint") or c.get("kicad", {}).get("footprint", ""),
            "kicad_symbol": c.get("kicad", {}).get("symbol_name", ""),
        })

    # Map nets
    app_nets = []
    for n in nets:
        name = n.get("name") or n.get("net_name") or n.get("id") or ""
        nodes = []
        for cp in n.get("connected_pins", []) or []:
            comp_id = str(cp.get("component_id") or cp.get("component") or "").strip()
            pin = str(cp.get("pin_name") or cp.get("pin") or "").strip()
            if comp_id and pin:
                nodes.append(f"{comp_id}:{pin}".upper())
        if nodes:
            app_nets.append({"net_name": name or nodes[0].replace(":", "_") , "nodes": nodes})

    # Ports → probe nodes (must match actual net_name strings for ngspice wrdata)
    probe_nodes: List[str] = ["0"]
    seen_probe: set[str] = {"0"}

    def _add_probe_node(name: str) -> None:
        u = str(name or "").strip().upper()
        if not u:
            return
        if u not in seen_probe:
            seen_probe.add(u)
            probe_nodes.append(u)

    for n in app_nets:
        nn = str(n.get("net_name") or "").strip().upper()
        nodes_upper = [str(x).upper() for x in (n.get("nodes") or [])]
        if any(x.startswith("IN:") for x in nodes_upper):
            _add_probe_node(nn or "IN")
        if any(x.startswith("OUT:") for x in nodes_upper):
            _add_probe_node(nn or "OUT")
        low = nn.lower()
        if low in {"vcc", "vdd", "v+", "vbat", "vsupply", "vpower"}:
            _add_probe_node(nn)

    for p in ports:
        pname = str(p.get("name") or p.get("id") or "").upper()
        if pname in {"VIN", "VOUT"}:
            _add_probe_node("IN" if pname == "VIN" else "OUT")

    if len(probe_nodes) <= 1:
        for fallback in ("IN", "OUT", "VCC"):
            _add_probe_node(fallback)

    # Fill minimal analysis/architecture/power/signal_flow
    analysis = {
        "circuit_name": meta.get("circuit_name") or meta.get("version") or "generated_circuit",
        "topology_classification": ir_dict.get("topology_type") or meta.get("topology_type") or "unknown",
        "design_explanation": "",
        "math_basis": "",
        "expected_bom": [],
        "calculations_table": [],
        "calculated_values": {"gain_dB": 0.0, "bandwidth_Hz": 0.0, "input_impedance_ohm": 0.0, "output_impedance_ohm": 0.0},
    }

    # Pick stage topology that matches the actual active device family so the
    # compiler emits the right deck (X-subckt for op-amp, Q line for BJT, ...).
    def _infer_stage_topology() -> str:
        # 1. Honor explicit topology hint from meta/ir_dict when usable.
        hint = topology_hint_raw
        if hint:
            if "non_invert" in hint or "non-invert" in hint or "noninvert" in hint:
                return "non_inverting"
            if "invert" in hint and "non" not in hint:
                return "inverting"
            if "differential" in hint or "diff_amp" in hint:
                return "differential"
            if "common_emitter" in hint or "common-emitter" in hint or hint == "ce":
                return "common_emitter"
            if "common_collector" in hint or "common-collector" in hint or hint == "cc":
                return "common_collector"
            if "common_base" in hint or "common-base" in hint or hint == "cb":
                return "common_base"
            if "common_source" in hint or "common-source" in hint or hint == "cs":
                return "common_source"
            if "common_drain" in hint or "common-drain" in hint or hint == "cd":
                return "common_drain"
        # 2. Infer from detected active device family.
        if first_active_kind == "opamp":
            return "non_inverting"
        if first_active_kind == "mosfet":
            return "common_source"
        if first_active_kind == "bjt":
            return "common_emitter"
        return "unknown"

    stage_topology = _infer_stage_topology()
    architecture = {
        "topology_type": "Single-stage",
        "stage_count": 1,
        "stages": [{
            "id": "S1",
            "topology": stage_topology,
            "active_device_ref": first_active or (app_components[0]["ref"] if app_components else ""),
        }],
    }

    power_and_coupling = {"power_rail": "Single (VCC-GND)", "output_strategy": "Common Load", "interstage_coupling": "None"}

    signal_flow = {"input_node": "IN", "output_node": "OUT", "main_chain": [], "stage_links": []}

    return {
        "is_valid_request": True,
        "clarification_question": "",
        "analysis": analysis,
        "architecture": architecture,
        "power_and_coupling": power_and_coupling,
        "signal_flow": signal_flow,
        "components": app_components,
        "nets": app_nets,
        "probe_nodes": list({n for n in probe_nodes}),
    }


@router.post("/export-kicad")
async def export_kicad(request: ExportKicadRequest):
    """
    Export circuit_data → KiCad .kicad_sch string.

    Trả về JSON { file_id, url } để frontend dùng url cho KiCanvas src.
    """
    try:
        from app.domains.circuits.ir import CircuitIRSerializer
        from app.infrastructure.exporters.kicad_sch_exporter import KiCadSchExporter
        from app.application.circuits.dtos import ExportFormat

        # 1. Convert template JSON → IR dict
        ir_dict = _template_to_ir_dict(request.circuit_data, normalize_power_rails=True)
        if request.circuit_id:
            ir_dict.setdefault("meta", {})["circuit_id"] = request.circuit_id
        
        # 2. Build Circuit entity
        circuit = CircuitIRSerializer.to_circuit(ir_dict)

        # 3. Export to .kicad_sch
        exporter = KiCadSchExporter()
        kicad_content = await exporter.export(circuit, ExportFormat.KICAD)

        # 4. Store in cache and return URL
        file_id = str(_uuid.uuid4())
        _kicad_cache[file_id] = kicad_content

        # Keep cache small (max 20 entries)
        if len(_kicad_cache) > 20:
            oldest = list(_kicad_cache.keys())[0]
            del _kicad_cache[oldest]

        return {
            "file_id": file_id,
            "url": f"/api/chat/kicad-file/{file_id}.kicad_sch",
            "size": len(kicad_content),
        }

    except ValueError as ve:
        # Validation errors (net conflicts, schema violations, etc.) → HTTP 400
        logger.warning("KiCad export validation error: %s", str(ve))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "export_validation_failed", "message": str(ve)},
        )
    except Exception as e:
        logger.error(f"KiCad export error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "export_failed", "message": str(e)},
        )


class ExportByCircuitIdRequest(BaseModel):
    circuit_id: str = Field(..., min_length=1)


@router.post("/export-kicad/by-id")
async def export_kicad_by_id(request: ExportByCircuitIdRequest):
    """Export artifacts for a stored circuit identifier.

    This looks up the compiled artifact cache or compiled directory and
    returns stable URLs for KiCanvas. It also persists a minimal artifact
    record to the artifacts repository.
    """
    cid = request.circuit_id
    # First check in in-memory cache
    content = _kicad_cache.get(cid)
    sch_url = None
    pcb_url = None
    ngspice_url = None

    if content:
        # cached schematic
        sch_name = f"{cid}.kicad_sch"
        _COMPILED_DIR.mkdir(parents=True, exist_ok=True)
        ( _COMPILED_DIR / sch_name ).write_text(content, encoding="utf-8")
        sch_url = f"/api/chat/kicad-file/{cid}.kicad_sch"

    # check for pcb and spice files in compiled dir
    candidates = list(_COMPILED_DIR.glob(f"{cid}*")) if _COMPILED_DIR.exists() else []
    for p in candidates:
        if p.suffix == ".kicad_pcb":
            pcb_url = f"/api/chat/pcb-file/{p.stem}.kicad_pcb"
        if p.suffix == ".cir":
            ngspice_url = f"/api/chat/compiled/{p.name}"

    # persist artifact metadata
    try:
        db = SessionLocal()
        repo = CircuitArtifactRepository(db)
        if sch_url:
            repo.create_artifact(circuit_id=cid, artifact_type="sch", filename=f"{cid}.kicad_sch", url=sch_url)
        if pcb_url:
            repo.create_artifact(circuit_id=cid, artifact_type="pcb", filename=p.stem if 'p' in locals() else '', url=pcb_url)
        if ngspice_url:
            repo.create_artifact(circuit_id=cid, artifact_type="spice", filename=p.name if 'p' in locals() else '', url=ngspice_url)
    except Exception:
        logger.exception("Failed to persist artifact metadata for export-kicad")
    finally:
        try:
            db.close()
        except Exception:
            pass

    if not any([sch_url, pcb_url, ngspice_url]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "export_not_found", "message": f"No compiled artifacts found for {cid}"})

    return {"sch_url": sch_url, "pcb_url": pcb_url, "ngspice_url": ngspice_url}


@router.post("/export-pcb")
async def export_pcb(request: ExportKicadRequest):
    """
    Export circuit_data → KiCad .kicad_pcb string.

    Trả về JSON { file_id, url } để frontend download PCB file.
    """
    try:
        from app.domains.circuits.ir import CircuitIRSerializer
        from app.infrastructure.exporters.kicad_pcb_exporter import KiCadPCBExporter
        from app.application.circuits.dtos import ExportFormat

        # 1. Convert template JSON → IR dict
        ir_dict = _template_to_ir_dict(request.circuit_data, normalize_power_rails=True)
        if request.circuit_id:
            ir_dict.setdefault("meta", {})["circuit_id"] = request.circuit_id
        
        # 2. Build Circuit entity
        circuit = CircuitIRSerializer.to_circuit(ir_dict)

        # 3. Export to .kicad_pcb
        exporter = KiCadPCBExporter()
        pcb_content = await exporter.export(circuit, ExportFormat.KICAD_PCB)

        # 4. Store in cache and return URL
        file_id = str(_uuid.uuid4())
        _kicad_cache[f"pcb_{file_id}"] = pcb_content

        # Keep cache small (max 20 entries)
        if len(_kicad_cache) > 20:
            oldest = list(_kicad_cache.keys())[0]
            del _kicad_cache[oldest]

        return {
            "file_id": file_id,
            "url": f"/api/chat/pcb-file/{file_id}.kicad_pcb",
            "size": len(pcb_content),
        }

    except ValueError as ve:
        # Validation errors (net conflicts, schema violations, etc.) → HTTP 400
        logger.warning("PCB export validation error: %s", str(ve))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "export_validation_failed", "message": str(ve)},
        )
    except Exception as e:
        logger.error(f"PCB export error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "pcb_export_failed", "message": str(e)},
        )


@router.get("/pcb-file/{file_id}.kicad_pcb")
async def get_pcb_file(file_id: str) -> PlainTextResponse:
    """
    Serve exported .kicad_pcb file by ID.
    """
    content = _kicad_cache.get(f"pcb_{file_id}")
    if content is None:
        raise HTTPException(status_code=404, detail="PCB file not found or expired")
    return PlainTextResponse(content=content, media_type="text/plain")


@router.get("/kicad-file/{file_id}.kicad_sch")
async def get_kicad_file(file_id: str) -> PlainTextResponse:
    """
    Serve exported .kicad_sch file by ID.
    KiCanvas sẽ fetch URL này qua attribute src.
    """
    content = _kicad_cache.get(file_id)
    if content is None:
        raise HTTPException(status_code=404, detail="File not found or expired")
    return PlainTextResponse(content=content, media_type="text/plain")
