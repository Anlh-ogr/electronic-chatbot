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
# enum: Support cho enum fields trong database
from sqlalchemy import Column, String, Integer, DateTime, Text, JSON, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.db.database import Base


# ====== Circuit Model ======
class CircuitModel(Base):
    """Model Database cho Circuit entities.
    
    Lưu trữ thông tin mạch điện (Circuit) gồm:
    - id: Unique circuit identifier (UUID)
    - name: Circuit name
    - description: Circuit description
    - created_at/updated_at: Timestamps
    - created_by: User/system identifier
    - ir_data: JSON serialized Circuit IR (Intermediate Representation)
    """
    __tablename__ = "circuits"
    
    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(100), default="system", nullable=False)
    
    # IR data stored as JSON
    ir_data = Column(JSON, nullable=False)
    
    # Relationships
    snapshots = relationship("SnapshotModel", back_populates="circuit", cascade="all, delete-orphan")


class ChangeTypeEnum(enum.Enum):
    """Change type enum for snapshots."""
    CREATED = "created"
    UPDATED = "updated"
    COMPONENT_ADDED = "component_added"
    COMPONENT_REMOVED = "component_removed"
    COMPONENT_MODIFIED = "component_modified"
    NET_ADDED = "net_added"
    NET_REMOVED = "net_removed"
    NET_MODIFIED = "net_modified"
    CONSTRAINT_ADDED = "constraint_added"
    CONSTRAINT_REMOVED = "constraint_removed"


class SnapshotModel(Base):
    """Snapshot database model."""
    __tablename__ = "snapshots"
    
    id = Column(String(36), primary_key=True)
    circuit_id = Column(String(36), ForeignKey("circuits.id"), nullable=False)
    revision = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    author = Column(String(100), default="system", nullable=False)
    message = Column(Text, default="", nullable=False)
    parent_snapshot_id = Column(String(36), ForeignKey("snapshots.id"), nullable=True)
    change_type = Column(SQLEnum(ChangeTypeEnum), default=ChangeTypeEnum.UPDATED, nullable=False)
    
    # Full IR data snapshot
    ir_data = Column(JSON, nullable=False)
    
    # Relationships
    circuit = relationship("CircuitModel", back_populates="snapshots")
    parent = relationship("SnapshotModel", remote_side=[id], backref="children")
