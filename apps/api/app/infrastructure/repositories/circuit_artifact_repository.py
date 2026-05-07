"""Async repository for circuit_artifacts table."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.structured_logger import log_stage


class CircuitArtifactRepository:
    """Persistence adapter for generated circuit artifacts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_artifact(
        self,
        ir_id: str,
        circuit_id: str,
        artifact_type: str,
        file_path: str,
        download_url: Optional[str],
        file_size_bytes: Optional[int] = None,
    ) -> str:
        # GUARD: Check if a valid artifact already exists for this circuit_id+ir_id+type
        # If so, skip the duplicate save and return the existing ID.
        existing = await self.session.execute(
            text(
                """
                SELECT artifact_id, file_size_bytes
                FROM circuit_artifacts
                WHERE circuit_id = :circuit_id
                  AND ir_id = :ir_id
                  AND artifact_type = :artifact_type
                  AND file_size_bytes IS NOT NULL
                LIMIT 1
                """
            ),
            {
                "circuit_id": circuit_id,
                "ir_id": ir_id,
                "artifact_type": artifact_type,
            },
        )
        existing_row = existing.mappings().first()
        if existing_row is not None:
            existing_id = existing_row.get("artifact_id")
            import logging
            logger = logging.getLogger(__name__)
            logger.info(
                f"Artifact {artifact_type} already exists for circuit_id={circuit_id}, "
                f"ir_id={ir_id} (id={existing_id}); skipping duplicate save with file_size_bytes={file_size_bytes}"
            )
            return str(existing_id)
        
        # No duplicate found; proceed with insert
        artifact_id = str(uuid.uuid4())
        await self.session.execute(
            text(
                """
                INSERT INTO circuit_artifacts (
                    artifact_id,
                    ir_id,
                    circuit_id,
                    artifact_type,
                    file_path,
                    download_url,
                    file_size_bytes
                ) VALUES (
                    :artifact_id,
                    :ir_id,
                    :circuit_id,
                    :artifact_type,
                    :file_path,
                    :download_url,
                    :file_size_bytes
                )
                """
            ),
            {
                "artifact_id": artifact_id,
                "ir_id": ir_id,
                "circuit_id": circuit_id,
                "artifact_type": artifact_type,
                "file_path": file_path,
                "download_url": download_url,
                "file_size_bytes": file_size_bytes,
            },
        )
        await self.session.commit()
        log_stage(
            "DB",
            operation="save_artifact",
            persisted=True,
            artifact_id=artifact_id,
            circuit_id=circuit_id,
            ir_id=ir_id,
            artifact_type=artifact_type,
            file_size_bytes=file_size_bytes,
        )
        return artifact_id

    async def get_artifacts_for_ir(self, ir_id: str) -> List[Dict[str, Any]]:
        rows = (
            await self.session.execute(
                text(
                    """
                    SELECT
                        artifact_id,
                        ir_id,
                        circuit_id,
                        artifact_type,
                        file_path,
                        download_url,
                        file_size_bytes,
                        kicad_version,
                        created_at
                    FROM circuit_artifacts
                    WHERE ir_id = :ir_id
                    ORDER BY created_at ASC
                    """
                ),
                {"ir_id": ir_id},
            )
        ).mappings().all()

        output: List[Dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["artifact_id"] = str(record.get("artifact_id") or "")
            record["ir_id"] = str(record.get("ir_id") or "")
            record["circuit_id"] = str(record.get("circuit_id") or "")
            output.append(record)
        return output
