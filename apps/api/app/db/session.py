""" Thiết lập kết nối bất đồng bộ với cơ sở dữ liệu (Database) sử dụng SQLAlchemy.
Sử dụng engine cho cả app và session tạo mới theo từng request rồi đóng lại bằng 
dependency `yield/finally` theo chuẩn """

# Gọi cấu hình config để lấy DATABASE_URL
from app.core.config import settings

# Thiết lập kết nối với bất đồng bộ - khởi tạo engine, sessionmaker, transaction để tạo session gọi DB
""" Đầu tiên, cần tạo một engine để kết nối đến DB_URL, chịu trách nhiệm quản lý pool kết nối.
    Tiếp theo, viết một factory thiết lập cấu hình engine tạo session. 
    Cuối cùng, viết transaction để thêm, sửa, xóa truy vấn trong DB và trả về phiên làm việc (session). """
from sqlalchemy.ext.asyncio import  create_async_engine, AsyncSession, async_sessionmaker

# Thiết lập cấu trúc bất đồng bộ với sqlalchemy để kết nối DB
""" Sử dụng async def để định nghĩa hàm và generator() lấy `yield` để trả về giá trị.
    Mỗi request (lần gọi API) sẽ mượn một phiên làm việc (session) riêng. """
from collections.abc import AsyncGenerator

""" Engine kết nối DB URL
 * Default Future = True để sử dụng các tính năng mới của SQLAlchemy 2.0
 * Echo = True để in các câu lệnh SQL ra console khi thực thi (DEBUG)
"""
engine = create_async_engine(settings.db_url, future=True, echo=False)


""" Tạo sessionmaker bất đồng bộ để tạo các phiên làm việc (session) với DB
* Bind liên kết với engine
* Class_ chỉ định lớp session bất đồng bộ
* Autoflush = False để tắt tự động flush (gửi thay đổi đến DB) sau mỗi lệnh
* Expire_on_commit = False để tắt tự động hết hạn đối tượng sau khi commit
"""
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


""" Dependency tạo session bất đồng bộ cho từng request API
 * yield kết quả phiên - trong route
 * finally đóng session sau khi xong request
"""
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()