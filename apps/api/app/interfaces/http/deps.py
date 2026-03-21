# .\\thesis\\electronic-chatbot\\apps\\api\\app\\interfaces\\http\\deps.py
"""Dependency Injection configuration cho FastAPI.

Module này cung cấp wiring (connections) giữa use cases + adapters (port implementations).
Nó định nghĩa FastAPI dependencies để inject use cases, repositories, services
vào route handlers.

Vietnamese:
- Trách nhiệm: Wiring use cases + adapters, create dependency injection tree
- Chức năng: FastAPI Depends factories cho circuit use cases, exporters, repositories
- Scope: Request-scoped instances qua lru_cache

English:
- Responsibility: Wire use cases + adapters, create dependency injection tree
- Features: FastAPI Depends factories for circuit use cases, exporters, repositories
- Scope: Request-scoped instances via lru_cache
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# pathlib: Cross-platform path handling
# functools.lru_cache: Cache dependencies across requests
# fastapi.Depends: Dependency injection for handlers
from pathlib import Path
from functools import lru_cache
from fastapi import Depends

# ====== Domain & Application layers ======
from app.application.circuits.use_cases import (
    GenerateCircuitUseCase,
    ValidateCircuitUseCase,
    ExportKiCadSchUseCase,
)
from app.application.circuits.use_cases.export_kicad_pcb import ExportKiCadPCBUseCase
from app.application.snapshots.services import SnapshotService

# ====== Infrastructure - Repositories ======
from app.infrastructure.persistence.circuits_repo_memory import InMemoryCircuitRepository
from app.infrastructure.repositories.circuit_repository import PostgresCircuitRepository
from app.infrastructure.repositories.snapshot_repository import PostgresSnapshotRepository
from app.infrastructure.exporters.kicad_sch_exporter import KiCadSchExporter
from app.infrastructure.exporters.kicad_pcb_exporter import KiCadPCBExporter
from app.infrastructure.validation.validation_service import DomainValidationService
from app.db.database import get_db


# Singleton instances for in-memory repository (shared state)
_repository_instance = None
_exporter_instance = None
_pcb_exporter_instance = None
_validation_service_instance = None


@lru_cache
def get_repository() -> InMemoryCircuitRepository:
    """Get singleton repository instance.
    
    Returns:
        InMemoryCircuitRepository instance
    """
    global _repository_instance
    if _repository_instance is None:
        _repository_instance = InMemoryCircuitRepository()
    return _repository_instance


@lru_cache
def get_exporter() -> KiCadSchExporter:
    """Get singleton exporter instance.
    
    Returns:
        KiCadSchExporter instance
    """
    global _exporter_instance
    if _exporter_instance is None:
        _exporter_instance = KiCadSchExporter()
    return _exporter_instance


@lru_cache
def get_pcb_exporter() -> KiCadPCBExporter:
    """Get singleton PCB exporter instance.
    
    Returns:
        KiCadPCBExporter instance
    """
    global _pcb_exporter_instance
    if _pcb_exporter_instance is None:
        _pcb_exporter_instance = KiCadPCBExporter()
    return _pcb_exporter_instance


@lru_cache
def get_validation_service() -> DomainValidationService:
    """Get singleton validation service instance.
    
    Returns:
        DomainValidationService instance
    """
    global _validation_service_instance
    if _validation_service_instance is None:
        _validation_service_instance = DomainValidationService()
    return _validation_service_instance


def get_generate_circuit_use_case() -> GenerateCircuitUseCase:
    """Create GenerateCircuitUseCase with dependencies.
    
    Returns:
        Configured GenerateCircuitUseCase instance
    """
    return GenerateCircuitUseCase(
        repository=get_repository()
    )


def get_validate_circuit_use_case() -> ValidateCircuitUseCase:
    """Create ValidateCircuitUseCase with dependencies.
    
    Returns:
        Configured ValidateCircuitUseCase instance
    """
    return ValidateCircuitUseCase(
        repository=get_repository(),
        validation_service=get_validation_service()
    )


def get_export_kicad_sch_use_case() -> ExportKiCadSchUseCase:
    """Create ExportKiCadSchUseCase with dependencies.
    
    Returns:
        Configured ExportKiCadSchUseCase instance
    """
    # Storage path for exported files
    storage_path = Path("./artifacts/exports")
    
    return ExportKiCadSchUseCase(
        repository=get_repository(),
        exporter=get_exporter(),
        storage_path=storage_path
    )


def get_export_kicad_pcb_use_case() -> ExportKiCadPCBUseCase:
    """Create ExportKiCadPCBUseCase with dependencies.
    
    Returns:
        Configured ExportKiCadPCBUseCase instance
    """
    # Storage path for exported PCB files
    storage_path = Path("./artifacts/exports/pcb")
    
    return ExportKiCadPCBUseCase(
        repository=get_repository(),
        exporter=get_pcb_exporter(),
        storage_path=storage_path
    )


def get_circuit_repository(db = Depends(get_db)) -> PostgresCircuitRepository:
    """Get circuit repository with DB session.
    
    Args:
        db: Database session from dependency
        
    Returns:
        PostgresCircuitRepository instance
    """
    return PostgresCircuitRepository(db)


def get_snapshot_repository(db = Depends(get_db)) -> PostgresSnapshotRepository:
    """Get snapshot repository with DB session.
    
    Args:
        db: Database session from dependency
        
    Returns:
        PostgresSnapshotRepository instance
    """
    return PostgresSnapshotRepository(db)


def get_snapshot_service(
    snapshot_repo: PostgresSnapshotRepository = Depends(get_snapshot_repository)
) -> SnapshotService:
    """Get snapshot service with dependencies.
    
    Args:
        snapshot_repo: Snapshot repository from dependency
        
    Returns:
        SnapshotService instance
    """
    return SnapshotService(snapshot_repo)
