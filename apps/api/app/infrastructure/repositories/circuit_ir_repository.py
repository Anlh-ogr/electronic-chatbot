"""Async repository for circuit_irs table."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.structured_logger import log_stage

from app.application.ai.circuit_ir_schema import CircuitIR


logger = logging.getLogger(__name__)


class CircuitIRRepository:
    """Persistence adapter for validated Circuit IR payloads."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_circuit_exists(
        self,
        circuit_id: str,
        circuit_name: str,
        session_id: Optional[str] = None,
        message_id: Optional[str] = None,
        ir: Optional[CircuitIR] = None,
    ) -> str:
        """Ensure parent row in circuits table exists before inserting into circuit_irs.
        
        This satisfies the FK constraint circuit_irs.circuit_id -> circuits.circuit_id.
        Returns circuit_id if inserted, or if row already exists.
        """
        circuit_name = self._generated_name_if_unnamed(circuit_name, ir)

        # Check if circuit already exists
        result = await self.session.execute(
            text("SELECT circuit_id FROM circuits WHERE circuit_id = :circuit_id"),
            {"circuit_id": circuit_id},
        )
        existing = result.scalar()
        if existing:
            logger.debug("Circuit already exists: circuit_id=%s", circuit_id)
            return circuit_id
        
        # Insert parent circuit row
        await self.session.execute(
            text(
                """
                INSERT INTO circuits (
                    circuit_id,
                    session_id,
                    message_id,
                    name,
                    description,
                    created_at,
                    updated_at
                ) VALUES (
                    :circuit_id,
                    :session_id,
                    :message_id,
                    :name,
                    :description,
                    now(),
                    now()
                )
                """
            ),
            {
                "circuit_id": circuit_id,
                "session_id": session_id,
                "message_id": message_id,
                "name": circuit_name or "Unnamed Circuit",
                "description": "Auto-generated circuit from IR persistence",
            },
        )
        await self.session.commit()
        logger.info(
            "Circuit row inserted successfully: circuit_id=%s, name=%s",
            circuit_id,
            circuit_name,
        )
        return circuit_id

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
        circuit_name = self._generated_name_if_unnamed(circuit_name, ir)
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
        log_stage(
            "DB",
            operation="save_ir",
            persisted=True,
            ir_id=ir_id,
            circuit_id=circuit_id,
            topology_type=topology_type,
            stage_count=stage_count,
            probe_count=len(probe_nodes),
        )
        return ir_id

    def _generated_name_if_unnamed(self, name: Optional[str], ir: Optional[CircuitIR]) -> str:
        current = str(name or "").strip()
        if current and current.lower() != "unnamed":
            return current
        if ir is None:
            return "Unnamed Circuit"

        family = self._extract_topology_family(ir)
        gain_target = self._extract_gain_target(ir)
        generated = f"{family.replace('_', ' ').title()} – Gain {gain_target}x"
        logger.info("Generated circuit name from IR: %s", generated)
        return generated

    def _extract_topology_family(self, ir: CircuitIR) -> str:
        topology = getattr(ir, "topology", None)
        family = str(getattr(topology, "family", "") or "").strip()
        if family:
            return family.removeprefix("opamp_")

        if ir.architecture is not None and ir.architecture.stages:
            stage_topology = str(ir.architecture.stages[0].topology or "").strip()
            if stage_topology:
                return stage_topology.removeprefix("opamp_")

        text = " ".join(
            [
                str(getattr(ir.analysis, "topology_classification", "") or ""),
                str(getattr(ir.analysis, "circuit_name", "") or ""),
            ]
        ).lower()
        normalized = text.replace("-", "_").replace(" ", "_")
        for family in (
            "common_emitter",
            "common_base",
            "common_collector",
            "non_inverting",
            "inverting",
            "differential",
        ):
            if family in normalized:
                return family
        return "circuit"

    def _extract_gain_target(self, ir: CircuitIR) -> str:
        topology = getattr(ir, "topology", None)
        raw = getattr(topology, "gain_target", None)
        if raw is None and ir.analysis is not None:
            raw = getattr(ir.analysis.calculated_values, "gain_actual", None)
        if raw is None:
            return "N/A"
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return str(raw)
        if value.is_integer():
            return str(int(value))
        return f"{value:g}"

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
        log_stage(
            "DB",
            operation="update_status",
            persisted=True,
            ir_id=ir_id,
            status=status,
        )
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
