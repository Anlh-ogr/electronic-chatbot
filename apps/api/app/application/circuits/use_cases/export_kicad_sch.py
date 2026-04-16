"""Export circuit to KiCad schematic use case.

This module implements the business logic for exporting circuits to
KiCad .kicad_sch format and storing artifacts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import uuid

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
        try:
            # Get circuit
            circuit = await self._get_circuit(request.circuit_id)
            
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
            
            return ExportCircuitResponse(
                circuit_id=request.circuit_id,
                format=request.format,
                file_path=str(file_path),
                file_size=file_size,
                download_url=f"/api/circuits/{request.circuit_id}/exports/{filename}",
                metadata=metadata,
            )
            
        except CircuitNotFoundError:
            raise
        except ExportError:
            raise
        except Exception as e:
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
