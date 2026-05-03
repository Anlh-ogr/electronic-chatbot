# .\\thesis\\electronic-chatbot\\apps\\api\\app\\infrastructure\\repositories\\snapshot_repository.py
"""Triển khai PostgreSQL Repository cho Snapshot mạch điện.

Module này cung cấp adapter PostgreSQL cho SnapshotRepositoryPort. Nó quản lý
lưu trữ, truy vấn snapshot (phiên bản) của mạch điện bao gồm metadata, IR data,
và change tracking.

Vietnamese:
- Trách nhiệm: Oracles snapshots (lịch sử) mạch điện trong PostgreSQL
- Chức năng: Save, get by ID/circuit, list by revision, change tracking
- Phụ thuộc: SQLAlchemy ORM, domain entity models

English:
- Responsibility: Manage circuit snapshots (history) in PostgreSQL
- Features: Save, get by ID/circuit, list by revision, change tracking
- Dependencies: SQLAlchemy ORM, domain entity models
"""

from typing import Optional, List

# ====== Lý do sử dụng thư viện ======
# sqlalchemy.orm: ORM session management cho database operations
# sqlalchemy.desc: Sắp xếp giảm dần (descending) cho revision queries
from sqlalchemy.orm import Session
from sqlalchemy import desc
from sqlalchemy import and_, or_

# ====== Domain & Application layers ======
from app.application.snapshots.ports import SnapshotRepositoryPort
from app.domains.snapshots.entities import CircuitSnapshot, SnapshotMetadata, ChangeType

# ====== Database models ======
from app.db.models import SnapshotModel


# ====== PostgreSQL Snapshot Repository Implementation ======
class PostgresSnapshotRepository(SnapshotRepositoryPort):
    """Triển khai PostgreSQL Repository cho Snapshot mạch điện.
    
    Class này quản lý persistence cho CircuitSnapshot entities,
    bao gồm lưu trữ, truy vấn theo ID/circuit/revision, change tracking.
    
    Responsibilities (Trách nhiệm):
    - Lưu snapshots vào PostgreSQL database
    - Truy vấn snapshots theo ID, circuit, hoặc revision
    - Maintain change history với ChangeType tracking
    - Serialize/deserialize IR data
    """
    
    def __init__(self, session: Session):
        """Initialize repository.
        
        Args:
            session: SQLAlchemy session
        """
        self.session = session
    
    async def save(self, snapshot: CircuitSnapshot) -> None:
        """Save snapshot to database."""
        ir_data = snapshot.ir_data
        # Validate and normalize ir_data
        if ir_data is None:
            # Defensive: avoid inserting NULL into jsonb
            return
        try:
            if isinstance(ir_data, str):
                import json as _json

                try:
                    ir_data = _json.loads(ir_data)
                except Exception:
                    # If the string is invalid JSON, skip saving
                    return
            if not isinstance(ir_data, dict):
                try:
                    ir_data = dict(ir_data)
                except Exception:
                    return
        except Exception:
            return

        model = SnapshotModel(
            snapshot_id=snapshot.metadata.snapshot_id,
            circuit_id=snapshot.metadata.circuit_id,
            message_id=None,
            circuit_data=ir_data,
            created_at=snapshot.metadata.timestamp,
        )
        self.session.add(model)
        self.session.commit()
    
    async def get_by_id(self, snapshot_id: str) -> Optional[CircuitSnapshot]:
        """Get snapshot by ID."""
        model = self.session.query(SnapshotModel).filter(
            SnapshotModel.snapshot_id == snapshot_id
        ).first()
        
        if not model:
            return None
        
        return self._to_entity(model)
    
    async def get_by_circuit(
        self,
        circuit_id: str,
        limit: int = 10
    ) -> List[CircuitSnapshot]:
        """Get snapshots for circuit."""
        models = self.session.query(SnapshotModel).filter(
            SnapshotModel.circuit_id == circuit_id
        ).order_by(desc(SnapshotModel.created_at), desc(SnapshotModel.snapshot_id)).limit(limit).all()
        
        return [self._to_entity(m) for m in models]
    
    async def get_latest(self, circuit_id: str) -> Optional[CircuitSnapshot]:
        """Get latest snapshot."""
        model = self.session.query(SnapshotModel).filter(
            SnapshotModel.circuit_id == circuit_id
        ).order_by(desc(SnapshotModel.created_at), desc(SnapshotModel.snapshot_id)).first()
        
        if not model:
            return None
        
        return self._to_entity(model)
    
    async def get_at_revision(
        self,
        circuit_id: str,
        revision: int
    ) -> Optional[CircuitSnapshot]:
        """Get snapshot at revision."""
        model = self.session.query(SnapshotModel).filter(
            SnapshotModel.circuit_id == circuit_id
        ).order_by(SnapshotModel.created_at.asc(), SnapshotModel.snapshot_id.asc()).offset(max(revision - 1, 0)).limit(1).first()
        
        if not model:
            return None
        
        return self._to_entity(model)
    
    async def delete(self, snapshot_id: str) -> bool:
        """Delete snapshot."""
        result = self.session.query(SnapshotModel).filter(
            SnapshotModel.snapshot_id == snapshot_id
        ).delete()
        self.session.commit()
        return result > 0

    def _revision_of(self, model: SnapshotModel) -> int:
        return (
            self.session.query(SnapshotModel)
            .filter(
                SnapshotModel.circuit_id == model.circuit_id,
                or_(
                    SnapshotModel.created_at < model.created_at,
                    and_(
                        SnapshotModel.created_at == model.created_at,
                        SnapshotModel.snapshot_id <= model.snapshot_id,
                    ),
                ),
            )
            .count()
        )

    def _parent_snapshot_id(self, model: SnapshotModel) -> Optional[str]:
        parent = (
            self.session.query(SnapshotModel)
            .filter(
                SnapshotModel.circuit_id == model.circuit_id,
                or_(
                    SnapshotModel.created_at < model.created_at,
                    and_(
                        SnapshotModel.created_at == model.created_at,
                        SnapshotModel.snapshot_id < model.snapshot_id,
                    ),
                ),
            )
            .order_by(desc(SnapshotModel.created_at), desc(SnapshotModel.snapshot_id))
            .first()
        )
        return parent.snapshot_id if parent else None
    
    def _to_entity(self, model: SnapshotModel) -> CircuitSnapshot:
        """Convert model to entity."""
        revision = self._revision_of(model)
        metadata = SnapshotMetadata(
            snapshot_id=model.snapshot_id,
            circuit_id=model.circuit_id,
            revision=revision,
            timestamp=model.created_at,
            author="system",
            message="",
            parent_snapshot_id=self._parent_snapshot_id(model),
            change_type=ChangeType.CREATED if revision == 1 else ChangeType.UPDATED,
        )
        return CircuitSnapshot(metadata=metadata, ir_data=model.circuit_data)
