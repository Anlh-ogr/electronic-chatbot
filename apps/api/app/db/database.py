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

# ====== Lý do sử dụng thư viện ======
# sqlalchemy: ORM framework cho database operations
# os: Load DATABASE_URL từ environment variables
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from typing import Generator
import os

# ====== Database Configuration ======
# Database URL from environment
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/electronic_chatbot"
)

# Create engine
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
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
