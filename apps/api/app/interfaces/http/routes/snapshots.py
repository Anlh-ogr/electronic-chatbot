# .\\thesis\\electronic-chatbot\\apps\\api\\app\\interfaces\\http\\routes\\snapshots.py
"""API routes cho Snapshots - Circuit version history & management.

Module này cung cấp HTTP endpoints cho snapshot (version history) operations:
- Get snapshot by ID
- List snapshots for circuit
- Get latest snapshot
- Get snapshot at specific revision
- Create snapshot (save circuit version)

Vietnamese:
- Trách nhiệm: Handle HTTP requests cho snapshot management
- Endpoints: /snapshots (get, list, create, update)
- Response: Snapshot metadata, circuit versions, change history

English:
- Responsibility: Handle HTTP requests for snapshot management
- Endpoints: /snapshots (get, list, create, update)
- Response: Snapshot metadata, circuit versions, change history
"""

# ====== Lý do sử dụng thư viện ======
# fastapi: HTTP routing, dependency injection
# typing: Type hints
# pydantic: Request/response validation
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from pydantic import BaseModel

# ====== Application layer ======
from app.application.snapshots.services import SnapshotService
from app.interfaces.http.deps import get_snapshot_service


router = APIRouter(prefix="/snapshots", tags=["snapshots"])


# ====== Response Models ======
class SnapshotMetadataResponse(BaseModel):
    """Response model cho snapshot metadata.
    
    Trả về thông tin metadata của một snapshot (version) mà không include
    full IR data (quá lớn). Client có thể dùng để list snapshots.
    """
    snapshot_id: str
    circuit_id: str
    revision: int
    timestamp: str
    author: str
    message: str
    parent_snapshot_id: str | None
    change_type: str


class SnapshotResponse(BaseModel):
    """Full snapshot response."""
    metadata: SnapshotMetadataResponse
    ir_data: dict


class DiffResponse(BaseModel):
    """Diff response."""
    from_snapshot: str
    to_snapshot: str
    components_added: List[str]
    components_removed: List[str]
    components_modified: dict
    nets_added: List[str]
    nets_removed: List[str]
    nets_modified: dict
    constraints_added: List[str]
    constraints_removed: List[str]


@router.get("/{snapshot_id}", response_model=SnapshotResponse)
async def get_snapshot(
    snapshot_id: str,
    service: SnapshotService = Depends(get_snapshot_service)
):
    """Get snapshot by ID."""
    snapshot = await service.get_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot {snapshot_id} not found"
        )
    
    return SnapshotResponse(
        metadata=SnapshotMetadataResponse(
            snapshot_id=snapshot.metadata.snapshot_id,
            circuit_id=snapshot.metadata.circuit_id,
            revision=snapshot.metadata.revision,
            timestamp=snapshot.metadata.timestamp.isoformat(),
            author=snapshot.metadata.author,
            message=snapshot.metadata.message,
            parent_snapshot_id=snapshot.metadata.parent_snapshot_id,
            change_type=snapshot.metadata.change_type.value
        ),
        ir_data=snapshot.ir_data
    )


@router.get("/circuit/{circuit_id}", response_model=List[SnapshotMetadataResponse])
async def get_circuit_history(
    circuit_id: str,
    limit: int = 10,
    service: SnapshotService = Depends(get_snapshot_service)
):
    """Get snapshot history for a circuit."""
    snapshots = await service.get_history(circuit_id, limit)
    
    return [
        SnapshotMetadataResponse(
            snapshot_id=s.metadata.snapshot_id,
            circuit_id=s.metadata.circuit_id,
            revision=s.metadata.revision,
            timestamp=s.metadata.timestamp.isoformat(),
            author=s.metadata.author,
            message=s.metadata.message,
            parent_snapshot_id=s.metadata.parent_snapshot_id,
            change_type=s.metadata.change_type.value
        )
        for s in snapshots
    ]


@router.get("/diff/{from_snapshot_id}/{to_snapshot_id}", response_model=DiffResponse)
async def get_diff(
    from_snapshot_id: str,
    to_snapshot_id: str,
    service: SnapshotService = Depends(get_snapshot_service)
):
    """Get diff between two snapshots."""
    diff = await service.compute_diff(from_snapshot_id, to_snapshot_id)
    if not diff:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or both snapshots not found"
        )
    
    return DiffResponse(
        from_snapshot=diff.from_snapshot,
        to_snapshot=diff.to_snapshot,
        components_added=diff.components_added,
        components_removed=diff.components_removed,
        components_modified=diff.components_modified,
        nets_added=diff.nets_added,
        nets_removed=diff.nets_removed,
        nets_modified=diff.nets_modified,
        constraints_added=diff.constraints_added,
        constraints_removed=diff.constraints_removed
    )


@router.post("/rollback/{circuit_id}/{target_revision}", response_model=SnapshotMetadataResponse)
async def rollback_circuit(
    circuit_id: str,
    target_revision: int,
    author: str = "system",
    service: SnapshotService = Depends(get_snapshot_service)
):
    """Rollback circuit to a previous revision."""
    snapshot = await service.rollback(circuit_id, target_revision, author)
    if not snapshot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target revision {target_revision} not found for circuit {circuit_id}"
        )
    
    return SnapshotMetadataResponse(
        snapshot_id=snapshot.metadata.snapshot_id,
        circuit_id=snapshot.metadata.circuit_id,
        revision=snapshot.metadata.revision,
        timestamp=snapshot.metadata.timestamp.isoformat(),
        author=snapshot.metadata.author,
        message=snapshot.metadata.message,
        parent_snapshot_id=snapshot.metadata.parent_snapshot_id,
        change_type=snapshot.metadata.change_type.value
    )
