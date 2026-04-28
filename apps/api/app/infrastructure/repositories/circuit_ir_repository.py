"""Async repository for circuit_irs table."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ai.circuit_ir_schema import CircuitIR


class CircuitIRRepository:
    """Persistence adapter for validated Circuit IR payloads."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_ir(
        self,
        ir: CircuitIR,
        circuit_id: str,
        session_id: Optional[str],
        message_id: Optional[str],
    ) -> str:
        ir_id = str(uuid.uuid4())
        payload = ir.model_dump(mode="json")

        topology_type = ir.architecture.topology_type if ir.architecture is not None else None
        circuit_name = ir.analysis.circuit_name if ir.analysis is not None else None
        stage_count = ir.architecture.stage_count if ir.architecture is not None else 1
        power_rail = (
            ir.power_and_coupling.power_rail
            if ir.power_and_coupling is not None
            else None
        )
        probe_nodes = ir.probe_nodes or []

        await self.session.execute(
            text(
                """
                INSERT INTO circuit_irs (
                    ir_id,
                    circuit_id,
                    session_id,
                    message_id,
                    ir_json,
                    topology_type,
                    circuit_name,
                    stage_count,
                    power_rail,
                    probe_nodes,
                    status
                ) VALUES (
                    :ir_id,
                    :circuit_id,
                    :session_id,
                    :message_id,
                    CAST(:ir_json AS jsonb),
                    :topology_type,
                    :circuit_name,
                    :stage_count,
                    :power_rail,
                    :probe_nodes,
                    :status
                )
                """
            ),
            {
                "ir_id": ir_id,
                "circuit_id": circuit_id,
                "session_id": session_id,
                "message_id": message_id,
                "ir_json": json.dumps(payload, ensure_ascii=False),
                "topology_type": topology_type,
                "circuit_name": circuit_name,
                "stage_count": stage_count,
                "power_rail": power_rail,
                "probe_nodes": probe_nodes,
                "status": "validated" if ir.is_valid_request else "failed",
            },
        )
        await self.session.commit()
        return ir_id

    async def mark_kept(self, ir_id: str, is_kept: bool) -> bool:
        result = await self.session.execute(
            text(
                """
                UPDATE circuit_irs
                SET is_kept = :is_kept
                WHERE ir_id = :ir_id
                """
            ),
            {
                "ir_id": ir_id,
                "is_kept": bool(is_kept),
            },
        )
        await self.session.commit()
        return (result.rowcount or 0) > 0

    async def get_kept_irs(self, session_id: str) -> List[Dict[str, Any]]:
        rows = (
            await self.session.execute(
                text(
                    """
                    SELECT
                        ir_id,
                        circuit_id,
                        ir_json,
                        topology_type,
                        circuit_name,
                        stage_count,
                        power_rail,
                        probe_nodes,
                        status,
                        created_at
                    FROM circuit_irs
                    WHERE session_id = :session_id
                      AND is_kept = true
                    ORDER BY created_at ASC
                    """
                ),
                {"session_id": session_id},
            )
        ).mappings().all()

        output: List[Dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            ir_json = record.get("ir_json")
            if isinstance(ir_json, str):
                try:
                    record["ir_json"] = json.loads(ir_json)
                except Exception:
                    record["ir_json"] = {}
            record["ir_id"] = str(record.get("ir_id") or "")
            record["circuit_id"] = str(record.get("circuit_id") or "")
            output.append(record)
        return output

    async def update_status(self, ir_id: str, status: str) -> bool:
        result = await self.session.execute(
            text(
                """
                UPDATE circuit_irs
                SET status = :status
                WHERE ir_id = :ir_id
                """
            ),
            {
                "ir_id": ir_id,
                "status": status,
            },
        )
        await self.session.commit()
        return (result.rowcount or 0) > 0
