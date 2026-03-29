import asyncio
import pytest
import pytest_asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

# Load biến môi trường từ .env.local
env_path = Path(__file__).resolve().parent.parent / '.env.local'
load_dotenv(env_path)

@pytest.mark.asyncio
async def test_neon_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ Lỗi: DATABASE_URL không tồn tại trong .env.local")
        return
        
    print(f"Đang thử kết nối tới Neon Database...")
    
    # Tạo async engine
    engine = create_async_engine(database_url, pool_pre_ping=True)
    
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
        print(f"❌ Kết nối thất bại. Chi tiết lỗi:\n{e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(test_neon_connection())


