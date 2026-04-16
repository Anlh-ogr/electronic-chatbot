# .\\thesis\\electronic-chatbot\\apps\\api\\app\\infrastructure\\repositories\\circuit_repository.py
"""Triển khai PostgreSQL Repository cho Mạch điện (Circuits).

Module này cung cấp adapter PostgreSQL cho circuit persistence. Nó quản lý
lưu trữ, truy vấn mạch điện bao gồm serialization IR, version management,
và circuit metadata (name, description, created_by).

Vietnamese:
- Trách nhiệm: Quản lý lưu trữ mạch điện trong PostgreSQL
- Chức năng: Save/update circuits, get by ID, list, serialize IR
- Phụ thuộc: SQLAlchemy ORM, CircuitIRSerializer

English:
- Responsibility: Manage circuit persistence in PostgreSQL
- Features: Save/update circuits, get by ID, list, IR serialization
- Dependencies: SQLAlchemy ORM, CircuitIRSerializer
"""

# ====== Lý do sử dụng thư viện ======
# typing: Type hints cho IDE support
# sqlalchemy.orm: ORM session management
# sqlalchemy: Database queries + filtering
# uuid: Generate unique circuit IDs
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc
import uuid
import logging

# ====== Domain & Application layers ======
from app.domains.circuits.entities import Circuit
from app.domains.circuits.ir import CircuitIRSerializer

# ====== Database models ======
from app.db.models import CircuitModel, SnapshotModel


logger = logging.getLogger(__name__)


# ====== PostgreSQL Circuit Repository Implementation ======
class PostgresCircuitRepository:
    """Triển khai PostgreSQL Repository cho Circuit entities.
    
    Class này quản lý circuit persistence với CircuitIRSerializer,
    hỗ trợ save/update, retrieval, listing, và IR (Intermediate Representation) management.
    
    Responsibilities (Trách nhiệm):
    - Lưu/cập nhật circuits vào PostgreSQL
    - Truy vấn circuits theo ID hoặc criteria
    - Serialize circuits thành IR for persistence
    - Maintain circuit metadata (name, description, created_by)
    """
    
    def __init__(self, session: Session):
        """Initialize repository.
        
        Args:
            session: SQLAlchemy session
        """
        self.session = session
    
    async def save(
        self,
        circuit: Circuit,
        circuit_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        created_by: str = "system"
    ) -> str:
        """Save circuit to database.
        
        Args:
            circuit: Circuit entity
            circuit_id: Optional ID (generates if not provided)
            name: Circuit name
            description: Circuit description
            created_by: Creator identifier
            
        Returns:
            Circuit ID
        """
        cid = circuit_id or str(uuid.uuid4())
        
        # Serialize circuit
        ir = CircuitIRSerializer.build_ir(circuit, circuit_id=cid)
        ir_data = CircuitIRSerializer.to_dict(ir)
        
        _ = created_by  # compatibility placeholder

        # Check if exists
        existing = self.session.query(CircuitModel).filter(
            CircuitModel.circuit_id == cid
        ).first()
        
        if existing:
            # Update
            existing.name = name or circuit.name or existing.name
            existing.description = description or existing.description
        else:
            # Create
            model = CircuitModel(
                circuit_id=cid,
                name=name or circuit.name or "Unnamed Circuit",
                description=description or "",
            )
            self.session.add(model)

        # Persist latest circuit IR into snapshots table (Neon schema source of truth).
        snapshot_model = SnapshotModel(
            snapshot_id=str(uuid.uuid4()),
            circuit_id=cid,
            message_id=None,
            circuit_data=ir_data,
        )
        self.session.add(snapshot_model)
        
        self.session.commit()
        return cid
    
    async def get_by_id(self, circuit_id: str) -> Optional[Circuit]:
        """Get circuit by ID.
        
        Args:
            circuit_id: Circuit identifier
            
        Returns:
            Circuit entity if found, None otherwise
        """
        model = self.session.query(CircuitModel).filter(
            CircuitModel.circuit_id == circuit_id
        ).first()
        
        if not model:
            return None

        latest_snapshot = (
            self.session.query(SnapshotModel)
            .filter(SnapshotModel.circuit_id == circuit_id)
            .order_by(desc(SnapshotModel.created_at), desc(SnapshotModel.snapshot_id))
            .first()
        )
        if not latest_snapshot:
            return None
        
        # Deserialize (best-effort because some runtime payloads are non-canonical IR).
        try:
            ir = CircuitIRSerializer.from_dict(latest_snapshot.circuit_data)
            return ir.circuit
        except Exception as exc:
            logger.warning("Circuit %s has non-canonical snapshot payload: %s", circuit_id, exc)
            return None
    
    async def list_all(self, limit: int = 100, offset: int = 0) -> List[dict]:
        """List all circuits with metadata.
        
        Args:
            limit: Maximum circuits to return
            offset: Offset for pagination
            
        Returns:
            List of circuit metadata dicts
        """
        models = self.session.query(CircuitModel).order_by(
            desc(CircuitModel.updated_at)
        ).limit(limit).offset(offset).all()
        
        return [
            {
                "id": m.circuit_id,
                "name": m.name,
                "description": m.description,
                "created_at": m.created_at.isoformat(),
                "updated_at": m.updated_at.isoformat(),
                "created_by": "system"
            }
            for m in models
        ]
    
    async def delete(self, circuit_id: str) -> bool:
        """Delete circuit.
        
        Args:
            circuit_id: Circuit identifier
            
        Returns:
            True if deleted, False if not found
        """
        result = self.session.query(CircuitModel).filter(
            CircuitModel.circuit_id == circuit_id
        ).delete()
        self.session.commit()
        return result > 0
