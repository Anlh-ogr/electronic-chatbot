#  .\thesis\electronic-chatbot\apps\api\app\application\circuits\use_cases\export_kicad_pcb.py


"""Export circuit to KiCad PCB use case.

This module implements the business logic for exporting circuits to
KiCad .kicad_pcb format and storing artifacts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import uuid

from app.domains.circuits.entities import Circuit
from app.domains.circuits.ir import CircuitIRSerializer
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


class ExportKiCadPCBUseCase:
    """Use case for exporting circuits to KiCad PCB format.
    
    This use case:
    1. Retrieves circuit from repository
    2. Exports to .kicad_pcb format
    3. Stores artifact to filesystem
    4. Returns download URL/path
    """
    
    def __init__(
        self,
        repository: CircuitRepositoryPort,
        exporter: ExporterPort,
        storage_path: Path,
    ):
        """Initialize use case with dependencies.
        
        Args:
            repository: Circuit repository for retrieval
            exporter: PCB exporter service for format conversion
            storage_path: Base path for storing exported files
        """
        self.repository = repository
        self.exporter = exporter
        self.storage_path = storage_path
        
        # Ensure storage path exists
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    async def execute(
        self,
        request: ExportCircuitRequest
    ) -> ExportCircuitResponse:
        """Execute circuit export to KiCad PCB.
        
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
            if request.format != ExportFormat.KICAD_PCB:
                raise ExportError(
                    format_type=request.format.value,
                    reason="This use case only supports KiCad PCB export"
                )
            
            # Export to KiCad PCB format
            pcb_content = await self.exporter.export(
                circuit=circuit,
                format_type=ExportFormat.KICAD_PCB
            )
            
            # Generate filename
            filename = self._generate_filename(circuit, request)
            
            # Save to storage
            file_path = await self._save_artifact(filename, pcb_content)
            
            # Calculate file size
            file_size = len(pcb_content.encode('utf-8'))
            
            return ExportCircuitResponse(
                circuit_id=request.circuit_id,
                format=request.format,
                file_path=str(file_path),
                file_size=file_size,
                download_url=f"/api/circuits/{request.circuit_id}/exports/pcb/{filename}",
                metadata={
                    "circuit_name": circuit.name or "Unnamed",
                    "component_count": len(circuit.components),
                    "kicad_version": "8.0",  # Target KiCad version
                }
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
        """Generate filename for exported PCB file.
        
        Args:
            circuit: Circuit entity
            request: Export request
            
        Returns:
            Filename with .kicad_pcb extension
        """
        # Sanitize circuit name for filename
        name = circuit.name or "circuit"
        name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        
        # Generate unique suffix
        unique_id = str(uuid.uuid4())[:8]
        
        return f"{name}_{unique_id}.kicad_pcb"
    
    async def _save_artifact(
        self,
        filename: str,
        content: str
    ) -> Path:
        """Save exported content to filesystem.
        
        Args:
            filename: Target filename
            content: File content as string
            
        Returns:
            Full file path
            
        Raises:
            StorageError: If save fails
        """
        try:
            file_path = self.storage_path / filename
            file_path.write_text(content, encoding='utf-8')
            return file_path
        except Exception as e:
            raise StorageError(
                operation="save_pcb_artifact",
                reason=str(e)
            ) from e
