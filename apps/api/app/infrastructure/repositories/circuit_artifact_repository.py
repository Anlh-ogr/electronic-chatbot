"""Async repository for circuit_artifacts table."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.structured_logger import log_stage

logger = logging.getLogger(__name__)


@dataclass
class Artifact:
    id: str
    circuit_id: str
    artifact_type: str
    file_path: str
    download_url: Optional[str]
    content: str


class CircuitArtifactRepository:
    """Persistence adapter for generated circuit artifacts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _execute(self, query: Any, params: Dict[str, Any]):
        """Support both async and sync SQLAlchemy sessions."""
        maybe = self.session.execute(query, params)
        if hasattr(maybe, "__await__"):
            return await maybe
        return maybe

    async def _commit(self) -> None:
        maybe = self.session.commit()
        if hasattr(maybe, "__await__"):
            await maybe

    async def save_artifact(
        self,
        ir_id: str,
        circuit_id: str,
        artifact_type: str,
        file_path: str,
        download_url: Optional[str],
        file_size_bytes: Optional[int] = None,
        *,
        defer_commit: bool = False,
    ) -> str:
        existing = await self._execute(
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
            logger.info(
                "Artifact %s already exists for circuit_id=%s, ir_id=%s (id=%s); skipping duplicate save",
                artifact_type,
                circuit_id,
                ir_id,
                existing_id,
            )
            return str(existing_id)

        artifact_id = str(uuid.uuid4())
        await self._execute(
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
        if not defer_commit:
            await self._commit()
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
            await self._execute(
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

    async def get_by_circuit_and_type(self, circuit_id: str, artifact_type: str) -> Optional[Artifact]:
        result = await self._execute(
            text(
                """
                SELECT artifact_id, circuit_id, artifact_type, file_path, download_url
                FROM circuit_artifacts
                WHERE circuit_id = :circuit_id
                  AND artifact_type = :artifact_type
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"circuit_id": circuit_id, "artifact_type": artifact_type},
        )
        row = result.mappings().first()
        if not row:
            return None

        file_path = str(row.get("file_path") or "")
        content = ""
        if file_path:
            try:
                content = Path(file_path).read_text(encoding="utf-8")
            except Exception:
                logger.debug("Unable to read artifact file_path=%s", file_path, exc_info=True)
        return Artifact(
            id=str(row.get("artifact_id") or ""),
            circuit_id=str(row.get("circuit_id") or ""),
            artifact_type=str(row.get("artifact_type") or ""),
            file_path=file_path,
            download_url=row.get("download_url"),
            content=content,
        )
