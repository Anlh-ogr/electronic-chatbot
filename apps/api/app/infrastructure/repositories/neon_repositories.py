"""Asyncpg repositories for Neon circuit persistence."""

from __future__ import annotations

import json
import logging
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.db.neon_asyncpg import get_neon_pool

logger = logging.getLogger(__name__)


@dataclass
class CircuitRecord:
    circuit_id: str
    name: str
    topology_family: Optional[str]
    topology_variant: Optional[str]
    circuit_ir: Optional[Dict[str, Any]]
    user_session: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


class _LruCache:
    def __init__(self, max_entries: int) -> None:
        self._max_entries = max(1, int(max_entries))
        self._data: OrderedDict[str, CircuitRecord] = OrderedDict()

    def get(self, key: str) -> Optional[CircuitRecord]:
        if key not in self._data:
            return None
        value = self._data.pop(key)
        self._data[key] = value
        return value

    def set(self, key: str, value: CircuitRecord) -> None:
        if key in self._data:
            self._data.pop(key)
        self._data[key] = value
        while len(self._data) > self._max_entries:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def remove(self, key: str) -> None:
        if key in self._data:
            self._data.pop(key)


class CircuitRepository:
    """Circuit persistence using asyncpg with LRU cache (max 50)."""

    def __init__(self, *, cache_size: int = 50) -> None:
        self._cache = _LruCache(cache_size)

    async def save(
        self,
        *,
        circuit_id: Optional[str],
        name: str,
        topology_family: Optional[str],
        topology_variant: Optional[str],
        circuit_ir: Dict[str, Any],
        user_session: Optional[str],
    ) -> str:
        cid = circuit_id or str(uuid.uuid4())
        payload = json.dumps(circuit_ir, ensure_ascii=False)

        pool = await get_neon_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO circuits (
                    circuit_id,
                    name,
                    topology_family,
                    topology_variant,
                    circuit_ir,
                    created_at,
                    updated_at,
                    user_session
                ) VALUES (
                    $1, $2, $3, $4, $5::jsonb, now(), now(), $6
                )
                ON CONFLICT (circuit_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    topology_family = EXCLUDED.topology_family,
                    topology_variant = EXCLUDED.topology_variant,
                    circuit_ir = EXCLUDED.circuit_ir,
                    updated_at = now(),
                    user_session = EXCLUDED.user_session
                """,
                cid,
                name,
                topology_family,
                topology_variant,
                payload,
                user_session,
            )

            row = await conn.fetchrow(
                """
                SELECT circuit_id, name, topology_family, topology_variant,
                       circuit_ir, user_session, created_at, updated_at
                FROM circuits
                WHERE circuit_id = $1
                """,
                cid,
            )

        if row:
            record = _row_to_record(row)
            self._cache.set(cid, record)
        return cid

    async def get(self, circuit_id: str) -> Optional[CircuitRecord]:
        cached = self._cache.get(circuit_id)
        if cached is not None:
            return cached

        logger.info("Circuit cache miss for %s; fallback to Postgres", circuit_id)

        pool = await get_neon_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT circuit_id, name, topology_family, topology_variant,
                       circuit_ir, user_session, created_at, updated_at
                FROM circuits
                WHERE circuit_id = $1
                """,
                circuit_id,
            )

        if row is None:
            return None

        record = _row_to_record(row)
        self._cache.set(circuit_id, record)
        return record

    async def delete(self, circuit_id: str) -> bool:
        pool = await get_neon_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM circuits WHERE circuit_id = $1",
                circuit_id,
            )
        self._cache.remove(circuit_id)
        return result.endswith("1")

    async def list_recent(self, limit: int = 50) -> List[CircuitRecord]:
        pool = await get_neon_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT circuit_id, name, topology_family, topology_variant,
                       circuit_ir, user_session, created_at, updated_at
                FROM circuits
                ORDER BY updated_at DESC
                LIMIT $1
                """,
                int(limit),
            )
        return [_row_to_record(row) for row in rows]

    def clear_cache(self) -> None:
        self._cache.clear()


class ExportRepository:
    """Persist circuit export metadata and cleanup temp files."""

    def __init__(self) -> None:
        pass

    async def save_export(
        self,
        *,
        circuit_id: str,
        export_type: str,
        file_path: str,
        file_size: Optional[int],
        status: str,
        error_message: Optional[str] = None,
    ) -> str:
        export_id = str(uuid.uuid4())
        size = file_size
        if size is None:
            size = _safe_file_size(file_path)

        pool = await get_neon_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO circuit_exports (
                    id,
                    circuit_id,
                    export_type,
                    file_path,
                    file_size,
                    created_at,
                    status,
                    error_message
                ) VALUES (
                    $1, $2, $3, $4, $5, now(), $6, $7
                )
                """,
                export_id,
                circuit_id,
                export_type,
                file_path,
                size,
                status,
                error_message,
            )

        if status == "success":
            _delete_temp_file(file_path)

        return export_id

    async def list_exports(self, circuit_id: str) -> List[Dict[str, Any]]:
        pool = await get_neon_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, circuit_id, export_type, file_path, file_size,
                       created_at, status, error_message
                FROM circuit_exports
                WHERE circuit_id = $1
                ORDER BY created_at DESC
                """,
                circuit_id,
            )
        return [dict(row) for row in rows]


class SimulationResultRepository:
    """Persist simulation result payloads."""

    def __init__(self) -> None:
        pass

    async def save_result(
        self,
        *,
        circuit_id: str,
        sim_type: str,
        result_json: Dict[str, Any],
    ) -> str:
        sim_id = str(uuid.uuid4())
        payload = json.dumps(result_json, ensure_ascii=False)

        pool = await get_neon_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO simulation_results (
                    id,
                    circuit_id,
                    sim_type,
                    result_json,
                    created_at
                ) VALUES (
                    $1, $2, $3, $4::jsonb, now()
                )
                """,
                sim_id,
                circuit_id,
                sim_type,
                payload,
            )
        return sim_id

    async def list_results(self, circuit_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        pool = await get_neon_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, circuit_id, sim_type, result_json, created_at
                FROM simulation_results
                WHERE circuit_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                circuit_id,
                int(limit),
            )
        return [dict(row) for row in rows]


def _row_to_record(row: Any) -> CircuitRecord:
    payload = row.get("circuit_ir")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = None
    return CircuitRecord(
        circuit_id=str(row.get("circuit_id")),
        name=str(row.get("name") or ""),
        topology_family=row.get("topology_family"),
        topology_variant=row.get("topology_variant"),
        circuit_ir=payload if isinstance(payload, dict) else None,
        user_session=row.get("user_session"),
        created_at=str(row.get("created_at")) if row.get("created_at") is not None else None,
        updated_at=str(row.get("updated_at")) if row.get("updated_at") is not None else None,
    )


def _safe_file_size(file_path: str) -> Optional[int]:
    try:
        return Path(file_path).stat().st_size
    except Exception:
        return None


def _delete_temp_file(file_path: str) -> None:
    if not file_path:
        return

    path = Path(file_path)
    if not path.exists():
        return

    parts = {p.lower() for p in path.parts}
    if "compiled" not in parts and "temp" not in parts and "tmp" not in parts:
        return

    try:
        path.unlink()
        logger.info("Deleted temp artifact after DB persist: %s", str(path))
    except Exception as exc:
        logger.warning("Failed to delete temp artifact %s: %s", str(path), exc)
