"""Asyncpg pool for Neon Postgres access."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import asyncpg

logger = logging.getLogger(__name__)

_POOL: Optional[asyncpg.Pool] = None
_POOL_LOCK = asyncio.Lock()


def _normalize_asyncpg_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return value

    if value.startswith("postgresql+asyncpg://"):
        value = value.replace("postgresql+asyncpg://", "postgresql://", 1)

    if not value.startswith("postgresql://"):
        return value

    parsed = urlparse(value)
    query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if "sslmode" in query_params and "ssl" not in query_params:
        query_params["ssl"] = query_params["sslmode"]

    query_params.pop("sslmode", None)
    query_params.pop("channel_binding", None)

    normalized_query = urlencode(query_params, doseq=True)
    return urlunparse(parsed._replace(query=normalized_query))


def _get_neon_database_url() -> str:
    return (
        os.getenv("NEON_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or ""
    ).strip()


async def get_neon_pool() -> asyncpg.Pool:
    global _POOL
    if _POOL is not None:
        return _POOL

    async with _POOL_LOCK:
        if _POOL is not None:
            return _POOL

        raw_url = _get_neon_database_url()
        if not raw_url:
            raise RuntimeError("NEON_DATABASE_URL is not configured")

        dsn = _normalize_asyncpg_url(raw_url)
        logger.info("Initializing asyncpg pool for Neon")
        _POOL = await asyncpg.create_pool(
            dsn=dsn,
            min_size=1,
            max_size=5,
            command_timeout=60,
        )
        return _POOL


async def close_neon_pool() -> None:
    global _POOL
    if _POOL is None:
        return
    await _POOL.close()
    _POOL = None
