"""Async repository for circuit_artifacts table."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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
