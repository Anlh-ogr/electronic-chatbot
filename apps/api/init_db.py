"""Neon schema health-check script.

This script is intentionally NON-DESTRUCTIVE:
- Does not drop tables
- Does not create/alter schema
- Only verifies connectivity + required tables
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def _normalize_async_database_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return value

    if value.startswith("postgresql://"):
        value = value.replace("postgresql://", "postgresql+asyncpg://", 1)

    if not value.startswith("postgresql+asyncpg://"):
        return value

    parsed = urlparse(value)
    query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if "sslmode" in query_params and "ssl" not in query_params:
        query_params["ssl"] = query_params["sslmode"]

    query_params.pop("sslmode", None)
    query_params.pop("channel_binding", None)

    normalized_query = urlencode(query_params, doseq=True)
    return urlunparse(parsed._replace(query=normalized_query))


async def check_neon_schema() -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env.local")

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is missing in .env.local")

    async_url = _normalize_async_database_url(database_url)
    engine = create_async_engine(async_url, pool_pre_ping=True, future=True)

    required_tables = {
        "sessions",
        "chats",
        "messages",
        "chat_summaries",
        "memory_facts",
        "circuits",
        "snapshots",
    }

    try:
        async with engine.connect() as conn:
            db_info = await conn.execute(text("SELECT current_database(), current_user"))
            db_name, db_user = db_info.one()
            print(f"Connected: database={db_name}, user={db_user}")

            table_rows = await conn.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
            """))
            existing_tables = {row[0] for row in table_rows.fetchall()}

            missing = sorted(required_tables - existing_tables)
            if missing:
                raise RuntimeError(f"Missing required tables: {missing}")

            print("Schema check passed. Required Neon tables are present.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_neon_schema())

