"""Unified LLM → CircuitIR → placement (Graphviz/CoordinateSolver) → KiCad compiler."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.application.ai.circuit_ir_schema import CircuitIR
from app.application.circuits.app_ir_adapter import (
    app_circuit_ir_to_domain_dict,
    llm_ir_to_validator_circuit_data,
)
from app.application.circuits.dtos import ExportFormat
from app.application.circuits.use_cases.export_kicad_sch import KiCad8SchematicCompiler
from app.domains.circuits.ir import CircuitIRSerializer
from app.infrastructure.exporters.kicad_pcb_exporter import KiCadPCBExporter

if TYPE_CHECKING:
    from app.application.ai.nlu_service import CircuitIntent

logger = logging.getLogger(__name__)


@dataclass
class UnifiedPipelineResult:
    """Result of the shared create/modify/validate/retry design pipeline."""

    success: bool
    ir: Optional[CircuitIR] = None
    circuit_data: Dict[str, Any] = field(default_factory=dict)
    compiled: Dict[str, Any] = field(default_factory=dict)
    solved_values: Dict[str, float] = field(default_factory=dict)
    validator_circuit_data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    flow: str = "create"


def solve_component_values(intent: "CircuitIntent") -> Dict[str, float]:
    """Run ParameterSolver for intent topology/gain (same as create-flow hint source)."""
    family = (intent.circuit_type or "").strip()
    gain = intent.gain_target
    if not family or family == "unknown" or gain is None:
        return {}

    try:
        from app.domains.circuits.ai_core.parameter_solver import ParameterSolver

        solved = ParameterSolver(preferred_series="E24").solve(
            target_gain=float(gain),
            family=family,
            metadata={
                "vcc": float(intent.vcc) if intent.vcc is not None else 12.0,
                "solver_hints": {},
            },
        )
    except Exception as exc:
        logger.warning("ParameterSolver failed in unified pipeline: %s", exc)
        return {}

    if not solved or not solved.success or not solved.values:
        return {}
    return {str(k): float(v) for k, v in solved.values.items() if isinstance(v, (int, float))}


def augment_requirements_with_solver(intent: "CircuitIntent", base_text: str) -> str:
    """Prepend ParameterSolver hints (shared by all intent flows)."""
    import math

    raw = (base_text or "").strip()
    family = (intent.circuit_type or "").strip()
    gain = intent.gain_target
    if not raw or not family or family == "unknown" or gain is None:
        return raw

    try:
        from app.domains.circuits.ai_core.parameter_solver import ParameterSolver

        solved = ParameterSolver(preferred_series="E24").solve(
            target_gain=float(gain),
            family=family,
            metadata={
                "vcc": float(intent.vcc) if intent.vcc is not None else 12.0,
                "solver_hints": {},
            },
        )
    except Exception as exc:
        logger.warning("ParameterSolver hint failed: %s", exc)
        return raw

    if not solved or not solved.success or not solved.values:
        return raw

    def _fmt_ohm(val: float) -> str:
        if not math.isfinite(val) or val <= 0:
            return str(val)
        if val >= 1_000_000:
            return f"{val / 1_000_000:.2f}MΩ"
        if val >= 1_000:
            return f"{val / 1_000:.2f}kΩ"
        return f"{val:.0f}Ω"

    lines = [
        raw,
        "",
        f"--- PRE-COMPUTED COMPONENT VALUES (ParameterSolver, family={family}, gain={gain}) ---",
        "Anchor component values on these results; do not invent unrelated resistor values.",
    ]
    for name, val in solved.values.items():
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        if math.isfinite(fval) and fval > 0:
            lines.append(f"  - {name} = {_fmt_ohm(fval)}")
    lines.append("--- END PRE-COMPUTED VALUES ---")
    return "\n".join(lines)


def build_llm_requirements(
    intent: "CircuitIntent",
    *,
    flow: str = "create",
    extra_prompt: str = "",
    edit_operation_lines: Optional[List[str]] = None,
) -> str:
    """Compose LLM requirements text for any intent flow."""
    parts: List[str] = [(intent.raw_text or "").strip()]
    flow_norm = (flow or "create").strip().lower()

    if flow_norm == "modify" and edit_operation_lines:
        parts.append("\n--- MODIFY OPERATIONS (must apply exactly) ---")
        parts.extend(edit_operation_lines)
        parts.append("--- END MODIFY OPERATIONS ---")

    if extra_prompt.strip():
        parts.append(extra_prompt.strip())

    merged = "\n".join(p for p in parts if p)
    return augment_requirements_with_solver(intent, merged)


def export_pcb_artifact(
    ir: CircuitIR,
    *,
    circuit_id: str,
    output_dir,
) -> Optional[str]:
    """Export .kicad_pcb via KiCadPCBExporter (strict placement/router). Returns URL path."""
    try:
        ir_dict = app_circuit_ir_to_domain_dict(ir, circuit_id=circuit_id)
        circuit = CircuitIRSerializer.to_circuit(ir_dict)
        exporter = KiCadPCBExporter()

        async def _run() -> str:
            return await exporter.export(circuit, ExportFormat.KICAD_PCB)

        pcb_content = asyncio.run(_run())
        pcb_name = f"{circuit_id}.kicad_pcb"
        pcb_path = output_dir / pcb_name
        pcb_path.write_text(pcb_content, encoding="utf-8")
        return f"/api/chat/compiled/{pcb_name}"
    except Exception as exc:
        logger.warning("PCB export failed in unified pipeline (soft): %s", exc)
        return None


def compile_ir_to_artifacts(
    ir: CircuitIR,
    *,
    circuit_id: Optional[str] = None,
    output_dir=None,
    export_pcb: bool = True,
) -> Dict[str, Any]:
    """CircuitIR → SCH (Graphviz/CoordinateSolver) + SPICE + optional PCB."""
    from app.application.ai.simulation_service import NgspiceCompilerService

    if output_dir is None:
        from pathlib import Path

        output_dir = Path(__file__).resolve().parents[3] / "artifacts" / "compiled"
    output_dir.mkdir(parents=True, exist_ok=True)

    cid = circuit_id or str(uuid.uuid4())
    artifact_id = uuid.uuid4().hex

    sch_result = KiCad8SchematicCompiler().compile_to_sch(ir)
    sch_content = sch_result["schematic"] if isinstance(sch_result, dict) else sch_result
    placement_data = sch_result.get("placement", {}) if isinstance(sch_result, dict) else {}
    sch_meta = sch_result.get("metadata", {}) if isinstance(sch_result, dict) else {}

    spice_deck = NgspiceCompilerService().generate_spice_deck(ir)

    sch_file_name = f"{artifact_id}.kicad_sch"
    (output_dir / sch_file_name).write_text(sch_content, encoding="utf-8")

    spice_file_name = f"{artifact_id}.cir"
    (output_dir / spice_file_name).write_text(spice_deck, encoding="utf-8")

    circuit_data = ir.model_dump(mode="json")
    if placement_data:
        circuit_data["placement"] = placement_data
    # Do not inject extra fields into CircuitIR payload; schema is strict.
    # circuit_id is returned as a top-level field in the API response.

    pcb_url = export_pcb_artifact(ir, circuit_id=cid, output_dir=output_dir) if export_pcb else None

    sch_bytes = len(sch_content.encode("utf-8")) if isinstance(sch_content, str) else None
    return {
        "circuit_data": circuit_data,
        "circuit_id": cid,
        "artifact_id": artifact_id,
        "download_url": f"/api/chat/compiled/{sch_file_name}",
        "sch_url": f"/api/chat/compiled/{sch_file_name}",
        "pcb_url": pcb_url,
        "spice_deck_ready": True,
        "spice_deck": spice_deck,
        "spice_deck_url": f"/api/chat/compiled/{spice_file_name}",
        "metadata": {
            **sch_meta,
            "file_size_bytes": sch_bytes,
            "pipeline": "llm_ir_graphviz_coordinate_solver_compiler",
        },
        "validator_circuit_data": llm_ir_to_validator_circuit_data(circuit_data),
    }
