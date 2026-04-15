from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy import text

from app.application.circuits.dtos import ExportCircuitRequest, ExportFormat
from app.db.session import async_session

try:
    from redis import asyncio as redis_async
except Exception:  # pragma: no cover - optional dependency guard
    redis_async = None


logger = logging.getLogger(__name__)


JobRunner = Callable[[ExportCircuitRequest], Awaitable[Any]]


def _coerce_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _to_json_compatible(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, (datetime, date, time)):
        return value.isoformat()

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {str(key): _to_json_compatible(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_to_json_compatible(item) for item in value]

    if hasattr(value, "model_dump"):
        try:
            return _to_json_compatible(value.model_dump(mode="json"))
        except TypeError:
            return _to_json_compatible(value.model_dump())

    if hasattr(value, "dict"):
        return _to_json_compatible(value.dict())

    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(_to_json_compatible(value), ensure_ascii=False)


def _serialize_export_response(payload: Any) -> Dict[str, Any]:
    serialized = _to_json_compatible(payload)
    if isinstance(serialized, dict):
        return serialized
    if serialized is None:
        return {}
    return {"value": serialized}


class IndustrialRoutingJobQueue:
    """Postgres-backed persistent queue for industrial PCB routing jobs."""

    def __init__(
        self,
        *,
        max_concurrency: int = 1,
        redis_url: Optional[str] = None,
        redis_queue_key: str = "industrial_routing_jobs:queue",
    ) -> None:
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()
        self._default_runner: Optional[JobRunner] = None
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._runner_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))
        self._resume_started = False
        self._redis_url = (redis_url or "").strip() or None
        self._redis_queue_key = (
            str(redis_queue_key or "industrial_routing_jobs:queue").strip()
            or "industrial_routing_jobs:queue"
        )
        self._redis_client: Any = None
        self._redis_client_lock = asyncio.Lock()
        self._redis_worker_task: Optional[asyncio.Task] = None
        self._redis_last_error: Optional[str] = None

    def set_default_runner(self, runner: JobRunner) -> None:
        self._default_runner = runner

    def ensure_started(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        if not self._resume_started:
            self._resume_started = True
            loop.create_task(self._resume_pending_jobs())

        self._ensure_backend_worker(loop)

    def _uses_redis_backend(self) -> bool:
        return bool(self._redis_url) and redis_async is not None

    def _ensure_backend_worker(self, loop: asyncio.AbstractEventLoop) -> None:
        if not self._uses_redis_backend():
            return

        task = self._redis_worker_task
        if task is None or task.done():
            self._redis_worker_task = loop.create_task(self._redis_worker_loop())

    async def submit(
        self,
        *,
        circuit_id: str,
        request: ExportCircuitRequest,
    ) -> Dict[str, Any]:
        self.ensure_started()
        await self._ensure_schema()

        job_id = str(uuid.uuid4())
        request_payload = self._request_to_payload(request)

        async with async_session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO industrial_routing_jobs (
                        job_id,
                        circuit_id,
                        request_payload,
                        status,
                        progress_payload
                    ) VALUES (
                        :job_id,
                        :circuit_id,
                        CAST(:request_payload AS jsonb),
                        'queued',
                        CAST(:progress_payload AS jsonb)
                    )
                    """
                ),
                {
                    "job_id": job_id,
                    "circuit_id": circuit_id,
                    "request_payload": _json_dumps(request_payload),
                    "progress_payload": _json_dumps(
                        {
                            "phase": "queued",
                            "phase_index": 0,
                            "total_phases": 4,
                            "progress": 0.0,
                            "message": "Job queued",
                        }
                    ),
                },
            )
            await session.commit()

        await self._enqueue_job(job_id)
        payload = await self.get_status(job_id)
        if payload is None:
            return {
                "job_id": job_id,
                "circuit_id": circuit_id,
                "status": "queued",
            }
        return payload

    async def get_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        await self._ensure_schema()
        row = await self._fetch_job_row(job_id)
        if row is None:
            return None
        return self._row_to_status_dict(row)

    async def get_result(self, job_id: str) -> Optional[Dict[str, Any]]:
        await self._ensure_schema()
        row = await self._fetch_job_row(job_id)
        if row is None:
            return None
        payload = self._row_to_status_dict(row)
        payload["result"] = _coerce_dict(row.get("result_payload")) if row.get("result_payload") else None
        return payload

    async def _resume_pending_jobs(self) -> None:
        await self._ensure_schema()

        async with async_session() as session:
            await session.execute(
                text(
                    """
                    UPDATE industrial_routing_jobs
                    SET status = 'queued',
                        updated_at = now(),
                        error = CASE
                            WHEN error IS NULL OR error = '' THEN 'Recovered after service restart'
                            ELSE error
                        END
                    WHERE status = 'running'
                    """
                )
            )
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT job_id
                        FROM industrial_routing_jobs
                        WHERE status = 'queued'
                        ORDER BY created_at ASC
                        """
                    )
                )
            ).mappings().all()
            await session.commit()

        for row in rows:
            jid = str(row.get("job_id") or "").strip()
            if jid:
                await self._enqueue_job(jid)

    async def _enqueue_job(self, job_id: str) -> None:
        self.ensure_started()

        if self._uses_redis_backend():
            client = await self._get_redis_client()
            if client is not None:
                try:
                    await client.lpush(self._redis_queue_key, job_id)
                    return
                except Exception as exc:
                    logger.warning(
                        "Redis enqueue failed for job %s, fallback to in-process queue: %s",
                        job_id,
                        exc,
                    )
                    self._redis_client = None

        await self._schedule_job(job_id)

    async def _get_redis_client(self) -> Optional[Any]:
        if not self._uses_redis_backend():
            return None

        async with self._redis_client_lock:
            if self._redis_client is not None:
                return self._redis_client

            if redis_async is None:  # pragma: no cover - guarded by _uses_redis_backend
                return None

            try:
                client = redis_async.from_url(self._redis_url, decode_responses=False)
                await client.ping()
                self._redis_client = client
                self._redis_last_error = None
                return client
            except Exception as exc:
                error_text = str(exc)
                if error_text != self._redis_last_error:
                    logger.warning("Redis connection unavailable, using in-process queue fallback: %s", exc)
                    self._redis_last_error = error_text
                self._redis_client = None
                return None

    async def _redis_worker_loop(self) -> None:
        while True:
            try:
                client = await self._get_redis_client()
                if client is None:
                    await asyncio.sleep(1.0)
                    continue

                item = await client.brpop(self._redis_queue_key, timeout=1)
                if item is None:
                    continue

                _, raw_job_id = item
                if isinstance(raw_job_id, bytes):
                    job_id = raw_job_id.decode("utf-8", errors="ignore").strip()
                else:
                    job_id = str(raw_job_id or "").strip()

                if not job_id:
                    continue

                await self._run_job(job_id=job_id)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Redis worker loop error (fallback remains active): %s", exc)
                self._redis_client = None
                await asyncio.sleep(1.0)

    async def _schedule_job(self, job_id: str) -> None:
        async with self._runner_lock:
            existing = self._active_tasks.get(job_id)
            if existing is not None and not existing.done():
                return

            task = asyncio.create_task(self._run_job(job_id=job_id))
            self._active_tasks[job_id] = task

            def _cleanup(_: asyncio.Task, jid: str = job_id) -> None:
                self._active_tasks.pop(jid, None)

            task.add_done_callback(_cleanup)

    async def _run_job(self, *, job_id: str) -> None:
        async with self._semaphore:
            if not await self._set_job_running(job_id):
                return

            row = await self._fetch_job_row(job_id)
            if row is None:
                return

            request = self._payload_to_request(_coerce_dict(row.get("request_payload")))
            if request is None:
                await self._set_job_failed(job_id, "Invalid request payload")
                return

            if self._default_runner is None:
                await self._set_job_failed(job_id, "Queue runner is not configured")
                return

            request.options = dict(request.options or {})
            request.options["_progress_callback"] = self._make_progress_callback(job_id)

            try:
                result = await self._default_runner(request)
                result_payload = _serialize_export_response(result)

                await self._set_job_completed(job_id, result_payload)

            except Exception as exc:
                await self._set_job_failed(job_id, str(exc))

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return

        async with self._schema_lock:
            if self._schema_ready:
                return

            async with async_session() as session:
                await session.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS industrial_routing_jobs (
                            job_id VARCHAR(36) PRIMARY KEY,
                            circuit_id VARCHAR(36) NOT NULL,
                            request_payload JSONB NOT NULL,
                            status VARCHAR(32) NOT NULL,
                            progress_payload JSONB NULL,
                            result_payload JSONB NULL,
                            error TEXT NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                            started_at TIMESTAMPTZ NULL,
                            finished_at TIMESTAMPTZ NULL,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        )
                        """
                    )
                )
                await session.execute(
                    text(
                        """
                        CREATE INDEX IF NOT EXISTS idx_industrial_routing_jobs_status
                        ON industrial_routing_jobs (status)
                        """
                    )
                )
                await session.execute(
                    text(
                        """
                        CREATE INDEX IF NOT EXISTS idx_industrial_routing_jobs_created_at
                        ON industrial_routing_jobs (created_at DESC)
                        """
                    )
                )
                await session.commit()

            self._schema_ready = True

    async def _fetch_job_row(self, job_id: str) -> Optional[Dict[str, Any]]:
        async with async_session() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT
                            job_id,
                            circuit_id,
                            status,
                            request_payload,
                            progress_payload,
                            result_payload,
                            error,
                            created_at,
                            started_at,
                            finished_at
                        FROM industrial_routing_jobs
                        WHERE job_id = :job_id
                        """
                    ),
                    {"job_id": job_id},
                )
            ).mappings().first()
        if row is None:
            return None
        return dict(row)

    def _row_to_status_dict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "job_id": str(row.get("job_id") or ""),
            "circuit_id": str(row.get("circuit_id") or ""),
            "status": str(row.get("status") or "unknown"),
            "created_at": _to_iso(row.get("created_at")),
            "started_at": _to_iso(row.get("started_at")),
            "finished_at": _to_iso(row.get("finished_at")),
            "error": row.get("error"),
            "progress": _coerce_dict(row.get("progress_payload")) if row.get("progress_payload") else None,
        }

    async def _set_job_running(self, job_id: str) -> bool:
        async with async_session() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE industrial_routing_jobs
                    SET status = 'running',
                        started_at = now(),
                        updated_at = now(),
                        error = NULL,
                        progress_payload = CAST(:progress_payload AS jsonb)
                    WHERE job_id = :job_id
                      AND status = 'queued'
                    """
                ),
                {
                    "job_id": job_id,
                    "progress_payload": _json_dumps(
                        {
                            "phase": "starting",
                            "phase_index": 0,
                            "total_phases": 4,
                            "progress": 1.0,
                            "message": "Industrial routing started",
                        }
                    ),
                },
            )
            await session.commit()

        updated_rows = int(result.rowcount or 0)
        return updated_rows != 0

    async def _set_job_completed(self, job_id: str, result_payload: Dict[str, Any]) -> None:
        async with async_session() as session:
            await session.execute(
                text(
                    """
                    UPDATE industrial_routing_jobs
                    SET status = 'completed',
                        result_payload = CAST(:result_payload AS jsonb),
                        finished_at = now(),
                        updated_at = now(),
                        error = NULL,
                        progress_payload = CAST(:progress_payload AS jsonb)
                    WHERE job_id = :job_id
                    """
                ),
                {
                    "job_id": job_id,
                    "result_payload": _json_dumps(result_payload),
                    "progress_payload": _json_dumps(
                        {
                            "phase": "completed",
                            "phase_index": 4,
                            "total_phases": 4,
                            "progress": 100.0,
                            "message": "Industrial routing completed",
                        }
                    ),
                },
            )
            await session.commit()

    async def _set_job_failed(self, job_id: str, error_text: str) -> None:
        await self._update_status(
            job_id=job_id,
            status_value="failed",
            finished=True,
            error_text=error_text,
            progress_payload={
                "phase": "failed",
                "phase_index": 0,
                "total_phases": 4,
                "progress": 0.0,
                "message": error_text,
            },
        )

    async def _update_progress(self, job_id: str, progress_payload: Dict[str, Any]) -> None:
        async with async_session() as session:
            await session.execute(
                text(
                    """
                    UPDATE industrial_routing_jobs
                    SET progress_payload = CAST(:progress_payload AS jsonb),
                        updated_at = now()
                    WHERE job_id = :job_id
                    """
                ),
                {
                    "job_id": job_id,
                    "progress_payload": _json_dumps(progress_payload),
                },
            )
            await session.commit()

    async def _update_status(
        self,
        *,
        job_id: str,
        status_value: str,
        progress_payload: Optional[Dict[str, Any]] = None,
        started: bool = False,
        finished: bool = False,
        clear_error: bool = False,
        error_text: Optional[str] = None,
    ) -> None:
        updates = ["status = :status_value", "updated_at = now()"]
        params: Dict[str, Any] = {
            "job_id": job_id,
            "status_value": status_value,
        }

        if started:
            updates.append("started_at = now()")
        if finished:
            updates.append("finished_at = now()")
        if clear_error:
            updates.append("error = NULL")
        if error_text is not None:
            updates.append("error = :error_text")
            params["error_text"] = error_text
        if progress_payload is not None:
            updates.append("progress_payload = CAST(:progress_payload AS jsonb)")
            params["progress_payload"] = _json_dumps(progress_payload)

        sql = f"UPDATE industrial_routing_jobs SET {', '.join(updates)} WHERE job_id = :job_id"
        async with async_session() as session:
            await session.execute(text(sql), params)
            await session.commit()

    def _make_progress_callback(self, job_id: str) -> Callable[[Dict[str, Any]], None]:
        def _callback(payload: Dict[str, Any]) -> None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            loop.create_task(self._update_progress(job_id, dict(payload or {})))

        return _callback

    @staticmethod
    def _request_to_payload(request: ExportCircuitRequest) -> Dict[str, Any]:
        clean_options: Dict[str, Any] = {}
        for key, value in dict(request.options or {}).items():
            if callable(value):
                continue
            if str(key).startswith("_"):
                continue
            clean_options[str(key)] = value

        return {
            "circuit_id": request.circuit_id,
            "format": str(request.format.value),
            "options": clean_options,
        }

    @staticmethod
    def _payload_to_request(payload: Dict[str, Any]) -> Optional[ExportCircuitRequest]:
        circuit_id = str(payload.get("circuit_id") or "").strip()
        format_name = str(payload.get("format") or "").strip() or ExportFormat.KICAD_PCB.value
        options = _coerce_dict(payload.get("options"))

        if not circuit_id:
            return None

        try:
            fmt = ExportFormat(format_name)
        except ValueError:
            fmt = ExportFormat.KICAD_PCB

        return ExportCircuitRequest(
            circuit_id=circuit_id,
            format=fmt,
            options=options,
        )
