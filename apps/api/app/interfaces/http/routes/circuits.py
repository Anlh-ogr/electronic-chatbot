# .\\thesis\\electronic-chatbot\\apps\\api\\app\\interfaces\\http\\routes\\circuits.py
"""API routes cho Circuits domain - REST endpoints.

Module này cung cấp HTTP endpoints cho circuit operations:
- Generate circuit từ template / prompt
- Validate circuit theo domain rules
- Export circuit sang KiCad format (.kicad_sch, .kicad_pcb)
- Retrieve circuit information + metadata

Vietnamese:
- Trách nhiệm: Handle HTTP requests cho circuit domain operations
- Endpoints: /circuits (generate, validate, export)
- Response: Circuit data, validation results, KiCad files

English:
- Responsibility: Handle HTTP requests for circuit domain operations
- Endpoints: /circuits (generate, validate, export)
- Response: Circuit data, validation results, KiCad files
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# typing: Type hints cho request/response
# fastapi: HTTP routing, dependency injection
# pathlib: File path handling
from typing import Dict, Any, Union
from fastapi import APIRouter, Depends, HTTPException, status
from pathlib import Path

# ====== Application layer ======
from app.application.circuits.dtos import (
    GenerateFromTemplateRequest,
    GenerateFromPromptRequest,
    PromptAnalysisResponse,
    ClarifyingQuestionDTO,
    CircuitResponse,
    ValidationResponse,
    ExportCircuitRequest,
    ExportCircuitResponse,
    ExportFormat,
)
from app.application.circuits.errors import (
    CircuitNotFoundError,
    InvalidCircuitError,
    ExportError,
    TemplateGenerationError,
    ValidationServiceError,
)
from app.application.circuits.use_cases import (
    GenerateCircuitUseCase,
    ValidateCircuitUseCase,
    ExportKiCadSchUseCase,
)
from app.application.circuits.use_cases.export_kicad_pcb import ExportKiCadPCBUseCase
from app.application.circuits.prompt_analyzer import PromptAnalyzer
from app.interfaces.http.deps import (
    get_generate_circuit_use_case,
    get_validate_circuit_use_case,
    get_export_kicad_sch_use_case,
    get_export_kicad_pcb_use_case,
)
from app.infrastructure.exporters.kicad_cli_renderer import KiCadCLIRenderer


# Create router
router = APIRouter(
    prefix="/api/circuits",
    tags=["circuits"]
)


@router.post("/generate", response_model=CircuitResponse, status_code=status.HTTP_201_CREATED)
async def generate_circuit(
    request: GenerateFromTemplateRequest,
    use_case: GenerateCircuitUseCase = Depends(get_generate_circuit_use_case)
) -> CircuitResponse:
    """Generate a circuit from a parametric template.
    
    Args:
        request: Template parameters and configuration
        use_case: Injected use case
    
    Returns:
        Generated circuit information
    
    Raises:
        HTTPException: If generation fails
    """
    try:
        response = await use_case.execute(request, save=True)
        return response
    
    except TemplateGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "template_generation_failed",
                "message": e.message,
                "details": e.details
            }
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "internal_error",
                "message": str(e)
            }
        )


@router.post("/generate/from-prompt", response_model=Union[CircuitResponse, PromptAnalysisResponse], status_code=status.HTTP_200_OK)
async def generate_from_prompt(
    request: GenerateFromPromptRequest,
    use_case: GenerateCircuitUseCase = Depends(get_generate_circuit_use_case)
) -> Union[CircuitResponse, PromptAnalysisResponse]:
    """Generate a circuit from natural language prompt.
    
    If prompt is clear, generates circuit immediately.
    If prompt is ambiguous, returns clarifying questions.
    
    Args:
        request: Natural language prompt and optional parameters
        use_case: Injected use case
    
    Returns:
        CircuitResponse if clear, or PromptAnalysisResponse with questions if ambiguous
    
    Raises:
        HTTPException: If analysis or generation fails
    """
    try:
        # Analyze prompt
        analyzer = PromptAnalyzer()
        analysis = analyzer.analyze(request.prompt, request.parameters)
        
        if analysis.clarity.value == "clear":
            # Generate circuit directly
            template_request = GenerateFromTemplateRequest(
                template_id=analysis.template_id,
                parameters=analysis.parameters,
                circuit_name=request.circuit_name,
                circuit_description=request.circuit_description
            )
            response = await use_case.execute(template_request, save=True, prompt=request.prompt)
            return response
            
        elif analysis.clarity.value == "ambiguous":
            # Return clarifying questions
            return PromptAnalysisResponse(
                clarity="ambiguous",
                template_id=analysis.template_id,
                parameters=analysis.parameters,
                questions=[
                    ClarifyingQuestionDTO(
                        field=q.field,
                        question=q.question,
                        suggestions=q.suggestions,
                        required=q.required
                    ) for q in analysis.questions
                ],
                confidence=analysis.confidence,
                message=f"I detected you want a {analysis.template_id} circuit. Please provide the following information:"
            )
        else:
            # Invalid/unclear prompt
            return PromptAnalysisResponse(
                clarity="invalid",
                questions=[
                    ClarifyingQuestionDTO(
                        field=q.field,
                        question=q.question,
                        suggestions=q.suggestions,
                        required=q.required
                    ) for q in analysis.questions
                ],
                confidence=analysis.confidence,
                message="I couldn't determine what type of circuit you want. Please clarify:"
            )
    
    except TemplateGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "template_generation_failed",
                "message": e.message,
                "details": e.details
            }
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "internal_error",
                "message": str(e)
            }
        )


@router.post("/analyze-prompt", response_model=PromptAnalysisResponse)
async def analyze_prompt(
    request: GenerateFromPromptRequest
) -> PromptAnalysisResponse:
    """Analyze a prompt without generating the circuit.
    
    Useful for UX to show users what will be generated before committing.
    
    Args:
        request: Natural language prompt and optional parameters
    
    Returns:
        PromptAnalysisResponse with detected template and parameters
    """
    try:
        analyzer = PromptAnalyzer()
        analysis = analyzer.analyze(request.prompt, request.parameters)
        
        # Build message based on clarity
        if analysis.clarity.value == "clear":
            message = f"Ready to generate {analysis.template_id} with parameters: {analysis.parameters}"
        elif analysis.clarity.value == "ambiguous":
            message = f"Detected {analysis.template_id}, but need more information"
        else:
            message = "Could not determine circuit type from prompt"
        
        return PromptAnalysisResponse(
            clarity=analysis.clarity.value,
            template_id=analysis.template_id,
            parameters=analysis.parameters,
            questions=[
                ClarifyingQuestionDTO(
                    field=q.field,
                    question=q.question,
                    suggestions=q.suggestions,
                    required=q.required
                ) for q in analysis.questions
            ],
            confidence=analysis.confidence,
            message=message
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "internal_error",
                "message": str(e)
            }
        )


@router.post("/validate/{circuit_id}", response_model=ValidationResponse)
async def validate_circuit(
    circuit_id: str,
    use_case: ValidateCircuitUseCase = Depends(get_validate_circuit_use_case)
) -> ValidationResponse:
    """Validate a circuit against domain rules.
    
    Args:
        circuit_id: Circuit identifier
        use_case: Injected use case
    
    Returns:
        Validation results with violations and suggestions
    
    Raises:
        HTTPException: If validation fails or circuit not found
    """
    try:
        response = await use_case.execute(circuit_id=circuit_id)
        return response
    
    except CircuitNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "circuit_not_found",
                "message": e.message,
                "details": e.details
            }
        )
    
    except ValidationServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "validation_service_error",
                "message": e.message,
                "details": e.details
            }
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "internal_error",
                "message": str(e)
            }
        )


@router.post("/export/{circuit_id}/kicad", response_model=ExportCircuitResponse)
async def export_circuit_to_kicad(
    circuit_id: str,
    use_case: ExportKiCadSchUseCase = Depends(get_export_kicad_sch_use_case)
) -> ExportCircuitResponse:
    """Export a circuit to KiCad schematic format.
    
    Args:
        circuit_id: Circuit identifier
        use_case: Injected use case
    
    Returns:
        Export information with file path and download URL
    
    Raises:
        HTTPException: If export fails or circuit not found
    """
    try:
        request = ExportCircuitRequest(
            circuit_id=circuit_id,
            format=ExportFormat.KICAD,
            options={}
        )
        response = await use_case.execute(request)
        return response
    
    except CircuitNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "circuit_not_found",
                "message": e.message,
                "details": e.details
            }
        )
    
    except ExportError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "export_failed",
                "message": e.message,
                "details": e.details
            }
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "internal_error",
                "message": str(e)
            }
        )


@router.post("/export/{circuit_id}/pcb", response_model=ExportCircuitResponse)
async def export_circuit_to_pcb(
    circuit_id: str,
    use_case: ExportKiCadPCBUseCase = Depends(get_export_kicad_pcb_use_case)
) -> ExportCircuitResponse:
    """Export a circuit to KiCad PCB format.
    
    Args:
        circuit_id: Circuit identifier
        use_case: Injected PCB export use case
    
    Returns:
        Export information with file path and download URL
    
    Raises:
        HTTPException: If export fails or circuit not found
    """
    try:
        request = ExportCircuitRequest(
            circuit_id=circuit_id,
            format=ExportFormat.KICAD_PCB,
            options={}
        )
        response = await use_case.execute(request)
        return response
    
    except CircuitNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "circuit_not_found",
                "message": e.message,
                "details": e.details
            }
        )
    
    except ExportError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "export_failed",
                "message": e.message,
                "details": e.details
            }
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "internal_error",
                "message": str(e)
            }
        )


@router.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint for circuits API.
    
    Returns:
        Status information
    """
    return {
        "status": "healthy",
        "service": "circuits-api",
        "version": "1.0.0"
    }


@router.get("/export/{circuit_id}/kicad/content")
async def get_kicad_schematic_content(
    circuit_id: str,
    use_case: ExportKiCadSchUseCase = Depends(get_export_kicad_sch_use_case)
) -> Dict[str, Any]:
    """Get KiCad schematic file content for rendering.
    
    Args:
        circuit_id: Circuit identifier
        use_case: Injected use case
    
    Returns:
        Dict with file_content (string) for KiCanvas rendering
    
    Raises:
        HTTPException: If export fails or circuit not found
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"Getting KiCad content for circuit {circuit_id}")
        
        request = ExportCircuitRequest(
            circuit_id=circuit_id,
            format=ExportFormat.KICAD,
            options={}
        )
        
        logger.info(f"Executing export use case...")
        response = await use_case.execute(request)
        logger.info(f"Export completed: {response.file_path}")
        
        # Read file content if exists
        from pathlib import Path
        if response.file_path:
            file_path = Path(response.file_path)
            logger.info(f"Checking file path: {file_path}")
            
            if file_path.exists():
                logger.info(f"File exists, reading content...")
                content = file_path.read_text(encoding='utf-8')
                logger.info(f"Content read successfully ({len(content)} chars)")
                return {
                    "circuit_id": circuit_id,
                    "file_content": content,
                    "file_path": str(file_path)
                }
            else:
                logger.error(f"File does not exist: {file_path}")
        else:
            logger.error(f"No file_path in response")
        
        raise ExportError(
            format_type="kicad_sch",
            reason="File not found after export"
        )
    
    except CircuitNotFoundError as e:
        logger.error(f"Circuit not found: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "circuit_not_found",
                "message": e.message,
                "details": e.details
            }
        )
    
    except ExportError as e:
        logger.error(f"Export error: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "export_failed",
                "message": e.message,
                "details": e.details
            }
        )
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "internal_error",
                "message": str(e)
            }
        )


@router.get("/export/{circuit_id}/kicad/file.kicad_sch")
async def get_kicad_schematic_file(
    circuit_id: str,
    use_case: ExportKiCadSchUseCase = Depends(get_export_kicad_sch_use_case)
):
    """Get raw KiCad schematic file for direct rendering by KiCanvas.
    
    Args:
        circuit_id: Circuit identifier
        use_case: Injected use case
    
    Returns:
        Raw .kicad_sch file content as text/plain
    
    Raises:
        HTTPException: If export fails or circuit not found
    """
    import logging
    from fastapi.responses import Response
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"Getting KiCad file for circuit {circuit_id}")
        
        request = ExportCircuitRequest(
            circuit_id=circuit_id,
            format=ExportFormat.KICAD,
            options={}
        )
        
        response = await use_case.execute(request)
        logger.info(f"Export completed: {response.file_path}")
        
        # Read file content if exists
        from pathlib import Path
        if response.file_path:
            file_path = Path(response.file_path)
            
            if file_path.exists():
                content = file_path.read_text(encoding='utf-8')
                logger.info(f"Returning raw .kicad_sch content ({len(content)} chars)")
                
                # Return as text/plain for direct KiCanvas consumption
                return Response(
                    content=content,
                    media_type="text/plain",
                    headers={
                        "Content-Disposition": f'inline; filename="{circuit_id}.kicad_sch"'
                    }
                )
            else:
                logger.error(f"File does not exist: {file_path}")
        else:
            logger.error(f"No file_path in response")
        
        raise ExportError(
            format_type="kicad_sch",
            reason="File not found after export"
        )
    
    except CircuitNotFoundError as e:
        logger.error(f"Circuit not found: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "circuit_not_found",
                "message": e.message
            }
        )
    
    except ExportError as e:
        logger.error(f"Export error: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "export_failed",
                "message": e.message
            }
        )
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "internal_error",
                "message": str(e)
            }
        )


@router.get("/render/{circuit_id}")
async def render_circuit(
    circuit_id: str,
    fallback: str = "auto",  # "auto", "svg", "none"
    use_case: ExportKiCadSchUseCase = Depends(get_export_kicad_sch_use_case)
) -> Dict[str, Any]:
    """Get circuit rendering information with KiCanvas primary and SVG fallback.
    
    This endpoint provides multiple rendering options:
    - Primary: KiCanvas viewer with .kicad_sch file
    - Fallback: SVG generated by kicad-cli (if available)
    
    Args:
        circuit_id: Circuit identifier
        fallback: Fallback mode - "auto" (try SVG on error), "svg" (always generate SVG), "none" (no fallback)
        use_case: Injected use case
    
    Returns:
        Dict with:
        - primary: "kicanvas"
        - kicad_sch_url: URL to .kicad_sch file for KiCanvas
        - kicad_sch_content_url: URL to get file content as JSON
        - svg_url: URL to SVG file (if fallback enabled and available)
        - svg_available: bool
        - renderer: "kicad-cli" or None
    
    Raises:
        HTTPException: If rendering fails
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"Rendering circuit {circuit_id} with fallback={fallback}")
        
        # First, export to KiCad format
        request = ExportCircuitRequest(
            circuit_id=circuit_id,
            format=ExportFormat.KICAD,
            options={}
        )
        
        export_response = await use_case.execute(request)
        
        if not export_response.file_path:
            raise ExportError(
                format_type="kicad_sch",
                reason="Export completed but no file path returned"
            )
        
        from pathlib import Path
        kicad_file = Path(export_response.file_path)
        
        if not kicad_file.exists():
            raise ExportError(
                format_type="kicad_sch",
                reason=f"Export file not found: {kicad_file}"
            )
        
        # Build response with KiCanvas as primary renderer
        response = {
            "primary": "kicanvas",
            "kicad_sch_url": f"/api/circuits/export/{circuit_id}/kicad/file.kicad_sch",
            "kicad_sch_content_url": f"/api/circuits/export/{circuit_id}/kicad/content",
            "svg_url": None,
            "svg_available": False,
            "renderer": None
        }
        
        # Try SVG fallback if requested
        should_generate_svg = fallback in ["auto", "svg"]
        
        if should_generate_svg:
            renderer = KiCadCLIRenderer()
            
            if renderer.is_available():
                logger.info("kicad-cli is available, generating SVG fallback")
                
                # Generate SVG in exports directory
                svg_output_dir = kicad_file.parent / "svg"
                svg_output_dir.mkdir(exist_ok=True)
                
                try:
                    svg_path = await renderer.render_to_svg(
                        input_kicad_sch=kicad_file,
                        output_dir=svg_output_dir
                    )
                    
                    if svg_path and svg_path.exists():
                        # Make SVG accessible via static files
                        # Assuming exports/ is mounted or accessible
                        relative_svg = svg_path.relative_to(Path("artifacts"))
                        svg_url = f"/artifacts/{relative_svg.as_posix()}"
                        
                        response["svg_url"] = svg_url
                        response["svg_available"] = True
                        response["renderer"] = "kicad-cli"
                        
                        logger.info(f"SVG fallback generated: {svg_url}")
                    else:
                        logger.warning("kicad-cli completed but no SVG generated")
                        
                except Exception as e:
                    logger.warning(f"SVG fallback generation failed: {e}")
                    # Continue without SVG - KiCanvas still works
            else:
                logger.info("kicad-cli not available, skipping SVG fallback")
        
        return response
        
    except CircuitNotFoundError as e:
        logger.error(f"Circuit not found: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "circuit_not_found",
                "message": e.message,
                "details": e.details
            }
        )
    
    except ExportError as e:
        logger.error(f"Export error: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "export_failed",
                "message": e.message,
                "details": e.details
            }
        )
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "internal_error",
                "message": str(e)
            }
        )

