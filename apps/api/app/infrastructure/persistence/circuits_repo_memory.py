# .\\thesis\\electronic-chatbot\\apps\\api\\app\\infrastructure\\persistence\\circuits_repo_memory.py
"""Triển khai (Repository) mạch điện trong bộ nhớ (In-Memory).

Module này cung cấp một triển khai đơn giản của CircuitRepositoryPort lưu trữ
dữ liệu mạch trong từ điển (dictionary) của bộ nhớ. Phù hợp để phát triển, kiểm thử,
và demo MVP. Dữ liệu sẽ mất khi ứng dụng khởi động lại.

Vietnamese:
- Trách nhiệm: Lưu trữ/truy vấn mạch điện trong bộ nhớ
- Kế thừa: CircuitRepositoryPort (application port)
- Phù hợp: Dev, testing, MVP
- Không phù hợp: Production, multi-instance, persistence yêu cầu

English:
- Responsibility: Store/query circuits in-memory
- Inheritance: CircuitRepositoryPort (application port)
- Suitable for: Development, testing, MVP
- Not for: Production, multi-instance, persistence requirements
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# typing: Type hints cho IDE support
# uuid: Tạo ID duy nhất cho circuits
# datetime: Lưu trữ metadata timestamps
from typing import Dict, List, Optional
import uuid
from datetime import datetime

# ====== Domain & Application layers ======
from app.domains.circuits.entities import Circuit
from app.application.circuits.ports import CircuitRepositoryPort
from app.application.circuits.dtos import (
    PaginationRequest,
    CircuitFilter,
)
from app.db.database import SessionLocal
from app.infrastructure.repositories.circuit_repository import PostgresCircuitRepository


# ====== In-Memory Repository Implementation ======
class InMemoryCircuitRepository(CircuitRepositoryPort):
    """Triển khai Repository trong bộ nhớ cho CircuitRepositoryPort.
    
    Class này lưu trữ circuits trong một dictionary với hoạt động thread-safe.
    Dữ liệu sẽ mất khi ứng dụng khởi động lại.
    
    Suitable for (Phù hợp với):
    - Development and testing
    - MVP demonstrations
    - Prototyping
    
    Not suitable for (Không phù hợp):
    - Production use
    - Multi-instance deployments
    - Data persistence requirements
    """
    
    def __init__(self):
        """Initialize empty in-memory storage."""
        self._circuits: Dict[str, Circuit] = {}
        self._lock = None  # For future async lock implementation
    
    async def save(self, circuit: Circuit) -> Circuit:
        """Save a circuit to memory.
        
        Args:
            circuit: Circuit entity to save
            
        Returns:
            Saved circuit with generated ID
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Generate ID if not present - create new Circuit with ID (frozen dataclass)
        if not circuit.id:
            from dataclasses import replace
            circuit = replace(circuit, id=str(uuid.uuid4()))
            logger.info(f"Generated new circuit ID: {circuit.id}")
        
        # Store circuit directly (metadata handling done at application layer)
        self._circuits[circuit.id] = circuit
        logger.info(f"Saved circuit {circuit.id} to repository. Total circuits: {len(self._circuits)}")
        logger.info(f"Circuit has {len(circuit.components)} components")
        
        return circuit
    
    async def get(self, circuit_id: str) -> Optional[Circuit]:
        """Retrieve a circuit by ID.
        
        Args:
            circuit_id: Circuit identifier
            
        Returns:
            Circuit if found, None otherwise
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Looking for circuit {circuit_id}. Available circuits: {list(self._circuits.keys())}")
        
        result = self._circuits.get(circuit_id)
        if result:
            logger.info(f"Found circuit {circuit_id}")
            return result

        # Fallback: hydrate from persisted snapshots in Postgres when memory cache misses.
        logger.warning(f"Circuit {circuit_id} not found in memory repository, fallback to Postgres")
        try:
            uuid.UUID(str(circuit_id))
        except Exception:
            logger.warning(f"Skip Postgres fallback for non-UUID circuit_id: {circuit_id}")
            logger.warning(f"Circuit {circuit_id} not found in repository!")
            return None

        db = SessionLocal()
        try:
            pg_repo = PostgresCircuitRepository(db)
            persisted = await pg_repo.get_by_id(circuit_id)
            if persisted is not None:
                self._circuits[circuit_id] = persisted
                logger.info(f"Loaded circuit {circuit_id} from Postgres into memory cache")
                return persisted
        except Exception as exc:
            logger.warning(f"Postgres fallback lookup failed for circuit {circuit_id}: {exc}")
        finally:
            db.close()

        logger.warning(f"Circuit {circuit_id} not found in repository!")
        return None
    
    async def list(
        self,
        filters: Optional[CircuitFilter] = None,
        pagination: Optional[PaginationRequest] = None
    ) -> List[Circuit]:
        """List circuits with optional filtering and pagination.
        
        Args:
            filters: Filter parameters
            pagination: Pagination parameters
            
        Returns:
            List of circuits matching criteria
        """
        # Start with all circuits
        circuits = list(self._circuits.values())
        
        # Apply filters
        if filters:
            circuits = self._apply_filters(circuits, filters)
        
        # Apply sorting
        if pagination and pagination.sort_by:
            circuits = self._apply_sorting(circuits, pagination)
        
        # Apply pagination
        if pagination:
            start = (pagination.page - 1) * pagination.page_size
            end = start + pagination.page_size
            circuits = circuits[start:end]
        
        return circuits
    
    async def update(self, circuit: Circuit) -> Circuit:
        """Update an existing circuit.
        
        Args:
            circuit: Circuit entity with updates
            
        Returns:
            Updated circuit
            
        Raises:
            KeyError: If circuit ID not found
        """
        if not circuit.id or circuit.id not in self._circuits:
            raise KeyError(f"Circuit {circuit.id} not found")
        
        self._circuits[circuit.id] = circuit
        return circuit
    
    async def delete(self, circuit_id: str) -> bool:
        """Delete a circuit by ID.
        
        Args:
            circuit_id: Circuit identifier
            
        Returns:
            True if deleted, False if not found
        """
        if circuit_id in self._circuits:
            del self._circuits[circuit_id]
            return True
        return False
    
    async def count(
        self,
        filters: Optional[CircuitFilter] = None
    ) -> int:
        """Count circuits matching filters.
        
        Args:
            filters: Filter parameters
            
        Returns:
            Count of matching circuits
        """
        circuits = list(self._circuits.values())
        
        if filters:
            circuits = self._apply_filters(circuits, filters)
        
        return len(circuits)
    
    def _apply_filters(
        self,
        circuits: List[Circuit],
        filters: CircuitFilter
    ) -> List[Circuit]:
        """Apply filter parameters to circuit list.
        
        Args:
            circuits: List of circuits
            filters: Filter parameters
            
        Returns:
            Filtered list
        """
        # Simplified filtering without metadata
        if filters.name:
            circuits = [
                c for c in circuits
                if filters.name.lower() in (c.name or "").lower()
            ]
        
        # Other filters disabled until metadata structure is determined
        return circuits
    
    def _apply_sorting(
        self,
        circuits: List[Circuit],
        pagination: PaginationRequest
    ) -> List[Circuit]:
        """Apply sorting to circuit list.
        
        Args:
            circuits: List of circuits
            pagination: Pagination with sort parameters
            
        Returns:
            Sorted list
        """
        reverse = pagination.sort_order == "desc"
        
        if pagination.sort_by == "name":
            circuits.sort(
                key=lambda c: c.name or "",
                reverse=reverse
            )
        # Other sorts disabled until metadata available
        
        return circuits
    
    async def clear(self) -> None:
        """Clear all circuits from memory. Useful for testing."""
        self._circuits.clear()