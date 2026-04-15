# .\\thesis\\electronic-chatbot\\apps\\api\\app\\db\\session.py
"""Thiết lập Async Database Sessions using SQLAlchemy AsyncSession.

Module này cấu hình bất đồng bộ (async) connections tới PostgreSQL database
sử dụng SQLAlchemy AsyncSession. Mỗi HTTP request sẽ mượn một phiên làm việc
(session) riêng từ sessionmaker factory.

Vietnamese:
- Trách nhiệm: Tạo async engine, sessionmaker, session generator
- Mô hình: Async SQLAlchemy 2.0+ style
- Dependency: Dùng get_session() generator cho FastAPI Depends

English:
- Responsibility: Create async engine, sessionmaker, session generator
- Pattern: Async SQLAlchemy 2.0+ style
- Dependency: Use get_session() generator for FastAPI Depends
"""

# ====== Lý do sử dụng thư viện ======
# sqlalchemy.ext.asyncio: Async database connections
# config: Load DATABASE_URL từ environment
from app.core.config import settings
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from collections.abc import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def _normalize_async_database_url(url: str) -> str:
    """Normalize Neon/Postgres URL so SQLAlchemy asyncpg engine can consume it."""
    value = (url or "").strip()
    if not value:
        return value

    if value.startswith("postgresql://"):
        value = value.replace("postgresql://", "postgresql+asyncpg://", 1)

    if not value.startswith("postgresql+asyncpg://"):
        return value

    try:
        parsed = urlparse(value)
        query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))

        if "sslmode" in query_params and "ssl" not in query_params:
            query_params["ssl"] = query_params["sslmode"]

        query_params.pop("sslmode", None)
        query_params.pop("channel_binding", None)

        normalized_query = urlencode(query_params, doseq=True)
        return urlunparse(parsed._replace(query=normalized_query))
    except Exception:
        # Keep original value if URL normalization fails unexpectedly.
        return value


# ====== Async Engine Configuration ======
# Thiết lập bất đồng bộ (async) engine cho kết nối DB
# Echo = True để in các câu lệnh SQL ra console khi thực thi (DEBUG)
raw_database_url = (
    settings.database_url.get_secret_value()
    if hasattr(settings, "database_url")
    else "postgresql+asyncpg://localhost/db"
)

engine = create_async_engine(
    _normalize_async_database_url(raw_database_url),
    future=True,
    echo=False
)


# ====== Session Factory Configuration ======
# Tạo sessionmaker bất đồng bộ để tạo các phiên làm việc (session) với DB
# - Bind: Liên kết với engine
# - Class_: Chỉ định lớp session bất đồng bộ
# - Autoflush = False: Tắt tự động flush (gửi thay đổi đến DB) sau mỗi lệnh
# - Expire_on_commit = False: Tắt tự động hết hạn đối tượng sau khi commit
async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


# ====== Session Dependency Generator ======
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency tạo session bất đồng bộ cho từng request API.
    
    Sử dụng yield để trả lại session cho route handler.
    Sau khi request kết thúc, finally block đóng session.
    
    Usage trong FastAPI route:
        @app.get("/")
        async def route(session: AsyncSession = Depends(get_session)):
            ...
    """
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()