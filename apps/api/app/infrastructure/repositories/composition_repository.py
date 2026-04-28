"""Async repository for circuit composition orchestration."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class CompositionRepository:
    """Persistence adapter for circuit_compositions and composition_members."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_composition(
        self,
        session_id: Optional[str],
        chat_id: Optional[str],
        coupling_method: str,
    ) -> str:
        composition_id = str(uuid.uuid4())
        await self.session.execute(
            text(
                """
                INSERT INTO circuit_compositions (
                    composition_id,
                    session_id,
                    chat_id,
                    coupling_method,
                    status
                ) VALUES (
                    :composition_id,
                    :session_id,
                    :chat_id,
                    :coupling_method,
                    'merging'
                )
                """
            ),
            {
                "composition_id": composition_id,
                "session_id": session_id,
                "chat_id": chat_id,
                "coupling_method": coupling_method,
            },
        )
        await self.session.commit()
        return composition_id

    async def add_member(self, composition_id: str, ir_id: str, stage_order: int) -> None:
        await self.session.execute(
            text(
                """
                INSERT INTO composition_members (
                    member_id,
                    composition_id,
                    ir_id,
                    stage_order
                ) VALUES (
                    :member_id,
                    :composition_id,
                    :ir_id,
                    :stage_order
                )
                ON CONFLICT (composition_id, ir_id)
                DO UPDATE SET stage_order = EXCLUDED.stage_order
                """
            ),
            {
                "member_id": str(uuid.uuid4()),
                "composition_id": composition_id,
                "ir_id": ir_id,
                "stage_order": stage_order,
            },
        )
        await self.session.commit()

    async def get_composition_with_members(self, composition_id: str) -> Dict[str, Any]:
        comp_row = (
            await self.session.execute(
                text(
                    """
                    SELECT
                        composition_id,
                        session_id,
                        chat_id,
                        merged_ir_json,
                        merged_ir_id,
                        coupling_method,
                        status,
                        merge_notes,
                        created_at,
                        updated_at
                    FROM circuit_compositions
                    WHERE composition_id = :composition_id
                    """
                ),
                {"composition_id": composition_id},
            )
        ).mappings().first()

        if comp_row is None:
            return {}

        members = (
            await self.session.execute(
                text(
                    """
                    SELECT
                        cm.member_id,
                        cm.ir_id,
                        cm.stage_order,
                        ci.circuit_id,
                        ci.circuit_name,
                        ci.topology_type,
                        ci.stage_count,
                        ci.ir_json,
                        ci.created_at
                    FROM composition_members cm
                    JOIN circuit_irs ci ON ci.ir_id = cm.ir_id
                    WHERE cm.composition_id = :composition_id
                    ORDER BY cm.stage_order ASC
                    """
                ),
                {"composition_id": composition_id},
            )
        ).mappings().all()

        result = dict(comp_row)
        payload = result.get("merged_ir_json")
        if isinstance(payload, str):
            try:
                result["merged_ir_json"] = json.loads(payload)
            except Exception:
                result["merged_ir_json"] = None

        result["composition_id"] = str(result.get("composition_id") or "")
        if result.get("merged_ir_id") is not None:
            result["merged_ir_id"] = str(result.get("merged_ir_id"))

        normalized_members: List[Dict[str, Any]] = []
        for row in members:
            item = dict(row)
            item["member_id"] = str(item.get("member_id") or "")
            item["ir_id"] = str(item.get("ir_id") or "")
            item["circuit_id"] = str(item.get("circuit_id") or "")
            if isinstance(item.get("ir_json"), str):
                try:
                    item["ir_json"] = json.loads(item["ir_json"])
                except Exception:
                    item["ir_json"] = {}
            normalized_members.append(item)

        result["members"] = normalized_members
        return result

    async def update_merged_ir(
        self,
        composition_id: str,
        merged_ir_json: Dict[str, Any],
        merged_ir_id: str,
        merge_notes: Optional[str] = None,
    ) -> bool:
        result = await self.session.execute(
            text(
                """
                UPDATE circuit_compositions
                SET merged_ir_json = CAST(:merged_ir_json AS jsonb),
                    merged_ir_id = :merged_ir_id,
                    merge_notes = COALESCE(:merge_notes, merge_notes),
                    status = 'compiled',
                    updated_at = now()
                WHERE composition_id = :composition_id
                """
            ),
            {
                "composition_id": composition_id,
                "merged_ir_json": json.dumps(merged_ir_json, ensure_ascii=False),
                "merged_ir_id": merged_ir_id,
                "merge_notes": merge_notes,
            },
        )
        await self.session.commit()
        return (result.rowcount or 0) > 0
