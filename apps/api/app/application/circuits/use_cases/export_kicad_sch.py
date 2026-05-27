"""Export circuit to KiCad schematic use case.

This module implements the business logic for exporting circuits to
KiCad .kicad_sch format and storing artifacts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

from app.application.ai.circuit_ir_schema import CircuitIR
from app.domains.circuits.entities import Circuit
from app.application.circuits.ports import (
    CircuitRepositoryPort,
    ExporterPort,
)
from app.application.circuits.dtos import (
    ExportCircuitRequest,
    ExportFormat,
    ExportCircuitResponse,
)
from app.application.circuits.errors import (
    CircuitNotFoundError,
    ExportError,
    StorageError,
)

logger = logging.getLogger(__name__)


class ExportKiCadSchUseCase:
    """Use case for exporting circuits to KiCad schematic format.
    
    This use case:
    1. Retrieves circuit from repository
    2. Optionally validates circuit before export
    3. Exports to .kicad_sch format
    4. Stores artifact to filesystem
    5. Returns download URL/path
    """
    
    def __init__(
        self,
        repository: CircuitRepositoryPort,
        exporter: ExporterPort,
        storage_path: Path,
        oracle_validator: Optional[Any] = None,
        export_repository: Optional[Any] = None,
    ):
        """Initialize use case with dependencies.
        
        Args:
            repository: Circuit repository for retrieval
            exporter: Exporter service for format conversion
            storage_path: Base path for storing exported files
        """
        self.repository = repository
        self.exporter = exporter
        self.storage_path = storage_path
        self.oracle_validator = oracle_validator
        self.export_repository = export_repository
        
        # Ensure storage path exists
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    async def execute(
        self,
        request: ExportCircuitRequest
    ) -> ExportCircuitResponse:
        """Execute circuit export to KiCad schematic.
        
        Args:
            request: Export request with circuit ID and options
            
        Returns:
            ExportCircuitResponse with file path and metadata
            
        Raises:
            CircuitNotFoundError: If circuit not found
            ExportError: If export fails
            StorageError: If file save fails
        """
        file_path: Optional[Path] = None
        try:
            # Get circuit
            circuit = await self._get_circuit(request.circuit_id)

            # SCH debug: log circuit shape received by use case
            try:
                cid = request.circuit_id or (circuit.id if getattr(circuit, 'id', None) else None)
            except Exception:
                cid = request.circuit_id
            logger.info(
                "[SCH DEBUG] UseCase fetched circuit_id=%s components=%d nets=%d",
                cid,
                len(getattr(circuit, 'components', {})),
                len(getattr(circuit, 'nets', {})),
            )
            # Debug: component/net counts and source inference
            component_count = len(getattr(circuit, 'components', {}))
            net_count = len(getattr(circuit, 'nets', {}))
            repo_name = getattr(self.repository, '__class__', type(self.repository)).__name__
            if 'Postgres' in repo_name:
                source = 'postgres'
            elif 'Memory' in repo_name or 'InMemory' in repo_name:
                source = 'memory'
            else:
                source = repo_name
            logger.debug(
                "Export start: circuit=%s component_count=%d net_count=%d source=%s",
                request.circuit_id,
                component_count,
                net_count,
                source,
            )

            # Fail fast on empty circuit
            if component_count == 0 or net_count == 0:
                raise ExportError(
                    format_type=request.format.value,
                    reason=f"Empty circuit: components={component_count}, nets={net_count}",
                )
            
            # Validate format
            if request.format != ExportFormat.KICAD:
                raise ExportError(
                    format_type=request.format.value,
                    reason="This use case only supports KiCad schematic export"
                )
            
            # Export to KiCad format
            kicad_content = await self.exporter.export(
                circuit=circuit,
                format_type=ExportFormat.KICAD
            )
            
            # Generate filename
            filename = self._generate_filename(circuit, request)
            
            # Save to storage
            file_path = await self._save_artifact(filename, kicad_content)

            # Log artifact info
            try:
                logger.debug("Export finished: file=%s size=%d", str(file_path), file_path.stat().st_size)
            except Exception:
                logger.debug("Export finished: file=%s", str(file_path))

            oracle_report = await self._run_oracle_validation(
                file_path=file_path,
                options=request.options,
            )

            layout_quality = self._extract_layout_quality_metadata()
            
            # Calculate file size
            file_size = len(kicad_content.encode('utf-8'))

            metadata: dict[str, Any] = {
                "circuit_name": circuit.name or "Unnamed",
                "component_count": len(circuit.components),
                "kicad_version": "8.0",  # Target KiCad version
                "oracle": oracle_report,
            }
            if layout_quality is not None:
                metadata["layout_quality"] = layout_quality
            
            response = ExportCircuitResponse(
                circuit_id=request.circuit_id,
                format=request.format,
                file_path=str(file_path),
                file_size=file_size,
                download_url=f"/api/circuits/{request.circuit_id}/exports/{filename}",
                metadata=metadata,
            )

            if self.export_repository is not None:
                await self.export_repository.save_export(
                    circuit_id=request.circuit_id,
                    export_type="kicad_sch",
                    file_path=str(file_path),
                    file_size=file_size,
                    status="success",
                    error_message=None,
                )

            return response
            
        except CircuitNotFoundError:
            raise
        except ExportError:
            raise
        except Exception as e:
            if self.export_repository is not None:
                await self.export_repository.save_export(
                    circuit_id=request.circuit_id,
                    export_type="kicad_sch",
                    file_path=str(file_path or ""),
                    file_size=None,
                    status="failed",
                    error_message=str(e),
                )
            raise ExportError(
                format_type=request.format.value,
                reason=str(e)
            ) from e
    
    async def _get_circuit(self, circuit_id: str) -> Circuit:
        """Retrieve circuit from repository.
        
        Args:
            circuit_id: Circuit identifier
            
        Returns:
            Circuit entity
            
        Raises:
            CircuitNotFoundError: If circuit not found
        """
        circuit = await self.repository.get(circuit_id)
        if not circuit:
            raise CircuitNotFoundError(circuit_id)
        return circuit
    
    def _generate_filename(
        self,
        circuit: Circuit,
        request: ExportCircuitRequest
    ) -> str:
        """Generate filename for exported file.
        
        Args:
            circuit: Circuit entity
            request: Export request
            
        Returns:
            Filename string
        """
        # Use circuit name or ID
        base_name = circuit.name or circuit.id

        if not base_name:
            base_name = request.circuit_id
        
        # Sanitize filename
        safe_name = "".join(c for c in base_name if c.isalnum() or c in "._- ")
        safe_name = safe_name.replace(" ", "_")
        
        # Add format extension
        extension = ".kicad_sch"

        suffix = (circuit.id or request.circuit_id or str(uuid.uuid4()))[:8]
        return f"{safe_name}_{suffix}{extension}"
    
    async def _save_artifact(
        self,
        filename: str,
        content: str
    ) -> Path:
        """Save exported content to filesystem.
        
        Args:
            filename: Name of file to save
            content: File content
            
        Returns:
            Path to saved file
            
        Raises:
            StorageError: If save fails
        """
        try:
            file_path = self.storage_path / filename
            
            # Write content
            file_path.write_text(content, encoding='utf-8')
            
            return file_path
            
        except Exception as e:
            raise StorageError(
                operation="write",
                path=str(file_path),
                reason=str(e)
            ) from e

    async def _run_oracle_validation(
        self,
        file_path: Path,
        options: Dict[str, Any],
    ) -> Dict[str, Any]:
        enabled = bool(options.get("oracle_validate", False))
        strict = bool(options.get("oracle_strict", False))

        if not enabled:
            return {
                "target": "schematic",
                "enabled": False,
                "strict": strict,
                "status": "skipped",
                "available": False,
                "passed": False,
                "backend": "kicad-cli",
                "message": "oracle validation disabled",
            }

        if self.oracle_validator is None:
            report = {
                "target": "schematic",
                "enabled": True,
                "strict": strict,
                "status": "unavailable",
                "available": False,
                "passed": False,
                "backend": "kicad-cli",
                "message": "oracle validator not configured",
            }
            if strict:
                raise ExportError(
                    format_type=ExportFormat.KICAD.value,
                    reason="Oracle validation failed in strict mode: validator unavailable",
                )
            return report

        try:
            result = await self.oracle_validator.validate_schematic(file_path)
            report = result.to_dict() if hasattr(result, "to_dict") else dict(result)
            report["enabled"] = True
            report["strict"] = strict

            if strict and report.get("status") != "passed":
                raise ExportError(
                    format_type=ExportFormat.KICAD.value,
                    reason=(
                        "Oracle validation failed in strict mode: "
                        f"{report.get('message', 'unknown error')}"
                    ),
                )

            return report
        except ExportError:
            raise
        except Exception as exc:
            report = {
                "target": "schematic",
                "enabled": True,
                "strict": strict,
                "status": "error",
                "available": True,
                "passed": False,
                "backend": "kicad-cli",
                "message": f"oracle validation error: {exc}",
            }
            if strict:
                raise ExportError(
                    format_type=ExportFormat.KICAD.value,
                    reason=(
                        "Oracle validation failed in strict mode: "
                        f"{report['message']}"
                    ),
                )
            return report

    def _extract_layout_quality_metadata(self) -> Optional[Dict[str, Any]]:
        getter = getattr(self.exporter, "get_last_layout_quality_report", None)
        if not callable(getter):
            return None

        result = getter()
        if result is None:
            return None
        if hasattr(result, "to_dict"):
            return result.to_dict()
        if isinstance(result, dict):
            return dict(result)
        return None


class KiCad8SchematicCompiler:
    """Compile validated LLM CircuitIR via the unified KiCadSchExporter pipeline."""

    def compile_to_sch(self, ir: CircuitIR) -> Dict[str, Any]:
        """Graphviz placement (pygraphviz) + orthogonal routing → KiCad 8 schematic."""
        from app.application.circuits.app_ir_adapter import app_circuit_ir_to_domain_dict
        from app.domains.circuits.ir import CircuitIRSerializer
        from app.infrastructure.exporters.kicad_sch_exporter import KiCadSchExporter

        circuit_id = str(uuid.uuid4())
        ir_dict = app_circuit_ir_to_domain_dict(ir, circuit_id=circuit_id)
        circuit = CircuitIRSerializer.to_circuit(ir_dict)

        exporter = KiCadSchExporter()
        sch_content = exporter.export_schematic_sync(circuit, placement_mode="auto")
        placements = exporter.get_last_placements()
        export_meta = exporter.get_last_export_metadata()
        master = self._infer_master_component(ir, placements)

        return {
            "schematic": sch_content,
            "placement": {
                "placed_components": list(placements.keys()),
                "placement_map": placements,
                "master_component": master,
                "zones": [],
            },
            "metadata": export_meta,
        }

    def _infer_master_component(
        self,
        ir: CircuitIR,
        placements: Dict[str, Tuple[float, float]],
    ) -> Optional[str]:
        """Prefer the active amplifying device for placement/logging, not an arbitrary first ref."""
        placed = {str(k).strip().upper() for k in placements.keys()}
        try:
            for st in ir.architecture.stages or []:
                ref = str(getattr(st, "active_device_ref", "") or "").strip().upper()
                if ref and ref in placed:
                    return ref
        except Exception:
            pass

        ranked: List[Tuple[int, str]] = []
        for comp in ir.components:
            ref = comp.ref_id.strip().upper()
            if ref not in placed:
                continue
            ct = str(comp.type or "").strip().lower()
            if ct in {"bjt_npn", "bjt_pnp", "npn", "pnp"}:
                ranked.append((0, ref))
            elif ct in {"mosfet_n", "mosfet_p"}:
                ranked.append((1, ref))
            elif ct == "opamp_ic":
                ranked.append((2, ref))
        if ranked:
            ranked.sort(key=lambda x: (x[0], x[1]))
            return ranked[0][1]

        skip_types = {"power_supply", "ground", "connector", "power_symbol"}
        for comp in ir.components:
            ref = comp.ref_id.strip().upper()
            if ref not in placed:
                continue
            if str(comp.type or "").strip().lower() in skip_types:
                continue
            return ref

        return next(iter(placements.keys()), None) if placements else None
