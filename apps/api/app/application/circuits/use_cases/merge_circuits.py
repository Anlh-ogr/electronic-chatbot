"""Use case for composing multiple kept CircuitIR payloads into one merged circuit."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.application.ai.circuit_ir_schema import CircuitIR
from app.application.ai.llm_router import LLMRole, get_router
from app.application.circuits.use_cases.export_kicad_sch import KiCad8SchematicCompiler
from app.domains.circuits.ai_core.ai_core import CircuitIRValidator
from app.infrastructure.repositories.circuit_artifact_repository import CircuitArtifactRepository
from app.infrastructure.repositories.circuit_ir_repository import CircuitIRRepository
from app.infrastructure.repositories.composition_repository import CompositionRepository


class MergeCircuitsUseCase:
    """Compose multiple kept circuit IRs into one merged architecture."""

    def __init__(
        self,
        *,
        circuit_ir_repo: CircuitIRRepository,
        artifact_repo: CircuitArtifactRepository,
        composition_repo: CompositionRepository,
        output_dir: Optional[Path] = None,
    ) -> None:
        self._circuit_ir_repo = circuit_ir_repo
        self._artifact_repo = artifact_repo
        self._composition_repo = composition_repo
        self._router = get_router()
        self._validator = CircuitIRValidator()
        self._compiler = KiCad8SchematicCompiler()
        self._output_dir = output_dir or (Path(__file__).resolve().parents[4] / "artifacts" / "compiled")

    async def execute(
        self,
        *,
        session_id: str,
        chat_id: Optional[str],
        ir_ids: Optional[List[str]] = None,
        coupling_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        kept_rows = await self._circuit_ir_repo.get_kept_irs(session_id)
        if not kept_rows:
            raise ValueError("No kept IRs found for this session")

        if ir_ids:
            wanted = {str(value) for value in ir_ids}
            kept_rows = [row for row in kept_rows if str(row.get("ir_id")) in wanted]
            if len(kept_rows) != len(wanted):
                raise ValueError("Some requested ir_ids are not marked as kept in this session")

        if len(kept_rows) < 2:
            raise ValueError("Need at least two kept IRs to compose")

        kept_rows.sort(key=lambda row: row.get("created_at"))

        resolved_coupling = (coupling_hint or "RC Coupling").strip() or "RC Coupling"
        composition_id = await self._composition_repo.create_composition(
            session_id=session_id,
            chat_id=chat_id,
            coupling_method=resolved_coupling,
        )

        for stage_order, row in enumerate(kept_rows):
            await self._composition_repo.add_member(
                composition_id=composition_id,
                ir_id=str(row.get("ir_id")),
                stage_order=stage_order,
            )

        stage_irs = [row.get("ir_json") for row in kept_rows]
        merge_payload = {
            "instruction": "Merge the following circuit IRs via the best coupling method.",
            "stage_irs": stage_irs,
            "user_coupling_hint": resolved_coupling,
        }

        merge_system_prompt = (
            "You are an EDA composition engine. Merge the provided stage_irs into one complete CircuitIR. "
            "Preserve full electrical connectivity, include required coupling/bias components, and produce "
            "one physically plausible final IR."
        )

        merged_obj = self._router.chat_json(
            LLMRole.GENERAL,
            system=merge_system_prompt,
            user_content=merge_payload,
            response_model=CircuitIR,
            max_schema_retries=2,
        )
        if merged_obj is None:
            raise RuntimeError("LLM merge failed to return a valid CircuitIR")

        merged_ir = CircuitIR.model_validate(merged_obj)
        if not merged_ir.is_valid_request:
            raise ValueError(
                merged_ir.clarification_question
                or "Merged IR is not valid; more constraints are required"
            )

        merged_ir = self._validator.validate_and_fix_math(merged_ir)
        self._validator.validate_pins(merged_ir)

        base_circuit_id = str(kept_rows[0].get("circuit_id") or "")
        if not base_circuit_id:
            raise ValueError("Cannot resolve base circuit_id from kept IR set")

        merged_ir_id = await self._circuit_ir_repo.save_ir(
            ir=merged_ir,
            circuit_id=base_circuit_id,
            session_id=session_id,
            message_id=None,
        )

        sch_content = self._compiler.compile_to_sch(merged_ir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        sch_file_name = f"{uuid.uuid4().hex}.kicad_sch"
        sch_file_path = self._output_dir / sch_file_name
        sch_file_path.write_text(sch_content, encoding="utf-8")
        download_url = f"/api/chat/compiled/{sch_file_name}"

        await self._artifact_repo.save_artifact(
            ir_id=merged_ir_id,
            circuit_id=base_circuit_id,
            artifact_type="kicad_sch",
            file_path=str(sch_file_path),
            download_url=download_url,
            file_size_bytes=sch_file_path.stat().st_size,
        )
        await self._circuit_ir_repo.update_status(merged_ir_id, "compiled")

        merge_notes = None
        if merged_ir.analysis is not None:
            merge_notes = merged_ir.analysis.design_explanation

        await self._composition_repo.update_merged_ir(
            composition_id=composition_id,
            merged_ir_json=merged_ir.model_dump(mode="json"),
            merged_ir_id=merged_ir_id,
            merge_notes=merge_notes,
        )

        return {
            "composition_id": composition_id,
            "merged_ir_id": merged_ir_id,
            "download_url": download_url,
            "merge_notes": merge_notes,
        }
