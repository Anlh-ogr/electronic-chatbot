# .\\thesis\\electronic-chatbot\\apps\\api\\app\\db\\database.py
"""Cấu hình Database - SQLAlchemy engine và connection management.

Module này cấu hình SQLAlchemy engine + declarative base cho ORM.
Nó quản lý kết nối tới PostgreSQL database với connection pooling.

Vietnamese:
- Trách nhiệm: Tạo SQLAlchemy engine, declarative base, sessionmaker
- Cấu hình: Database URL từ environment, pool size/overflow
- Tối ưu: pool_pre_ping để check connections, max_overflow cho spikes

English:
- Responsibility: Create SQLAlchemy engine, declarative base, sessionmaker
- Configuration: Database URL from environment, pool size/overflow
- Optimization: pool_pre_ping to check connections, max_overflow for spikes
"""

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from typing import Generator
from pathlib import Path
from dotenv import load_dotenv
import os


# Load .env.local from apps/api root so SessionLocal uses the same env as app runtime.
_ENV_LOCAL_PATH = Path(__file__).resolve().parents[2] / ".env.local"
if _ENV_LOCAL_PATH.exists():
    load_dotenv(_ENV_LOCAL_PATH)

# ====== Database Configuration ======
# Database URL from environment
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/electronic_chatbot"
)


def _normalize_sync_database_url(url: str) -> str:
    """Convert async SQLAlchemy URLs to sync driver URLs for sync SessionLocal."""
    value = (url or "").strip()
    if value.startswith("postgresql+asyncpg://"):
        return value.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    return value


SYNC_DATABASE_URL = _normalize_sync_database_url(DATABASE_URL)

# Create engine
engine = create_engine(
    SYNC_DATABASE_URL,
    poolclass=NullPool,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db() -> Generator:
    """Dependency for getting database session.
    
    Yields:
        Database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
