# .\\thesis\\electronic-chatbot\\apps\\api\\app\\db\\models.py
"""SQLAlchemy models cho Circuits + Snapshots entities.

Module này định nghĩa các database models (tables) cho circuit persistence.
Mỗi model ánh xạ (map) một domain entity vào một database table.

Entities (Thực thể):
- CircuitModel: Lưu trữ mạch điện + metadata (name, description, created_by)
- SnapshotModel: Lưu trữ version history của circuits

Vietnamese:
- Trách nhiệm: Định nghĩa SQLAlchemy ORM models
- Scope: Circuits, snapshots, circuit history
- Relationship: Snapshots liên kết với Circuits qua circuit_id

English:
- Responsibility: Define SQLAlchemy ORM models
- Scope: Circuits, snapshots, circuit history
- Relationship: Snapshots linked to Circuits via circuit_id
"""

# ====== Lý do sử dụng thư viện ======
# sqlalchemy: ORM column/relationship definitions
# datetime: Timestamps cho created_at/updated_at
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime

from app.db.database import Base


# ====== Circuit Model ======
class CircuitModel(Base):
    """Model Database cho Circuit entities.
    
    Lưu trữ thông tin mạch điện (Circuit) gồm:
    - circuit_id: Unique circuit identifier (UUID)
    - name: Circuit name
    - description: Circuit description
    - created_at/updated_at: Timestamps
    - session_id/message_id: liên kết phiên chat và message nguồn
    """
    __tablename__ = "circuits"
    
    circuit_id = Column(String(36), primary_key=True)
    session_id = Column(String(36), nullable=True, index=True)
    message_id = Column(String(36), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    snapshots = relationship("SnapshotModel", back_populates="circuit", cascade="all, delete-orphan")


class SnapshotModel(Base):
    """Snapshot database model."""
    __tablename__ = "snapshots"
    
    snapshot_id = Column(String(36), primary_key=True)
    circuit_id = Column(String(36), ForeignKey("circuits.circuit_id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(String(36), nullable=True, index=True)
    circuit_data = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    
    # Relationships
    circuit = relationship("CircuitModel", back_populates="snapshots")
