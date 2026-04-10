import asyncio
import pytest
import pytest_asyncio
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

# Load biến môi trường từ .env.local
env_path = Path(__file__).resolve().parent.parent / '.env.local'
load_dotenv(env_path)


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

@pytest.mark.asyncio
async def test_neon_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.fail("DATABASE_URL không tồn tại trong .env.local")
        
    print(f"Đang thử kết nối tới Neon Database...")
    async_database_url = _normalize_async_database_url(database_url)
    
    # Tạo async engine
    engine = create_async_engine(async_database_url, pool_pre_ping=True)
    
    try:
        async with engine.connect() as conn:
            # Query lấy version của PostgreSQL
            version_result = await conn.execute(text("SELECT version()"))
            version = version_result.scalar_one()
            
            # Query lấy danh sách các tables trong public schema
            tables_result = await conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            ))
            tables = [row[0] for row in tables_result.fetchall()]
            
            print("✅ Kết nối đến Neon Database THÀNH CÔNG!")
            print(f"📌 Thông tin version: {version}")
            print(f"📂 Các bảng hiện có trong Database (public schema): {tables if tables else 'Chưa có bảng nào'}")
            
    except Exception as e:
        pytest.fail(f"Kết nối thất bại. Chi tiết lỗi: {e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(test_neon_connection())


