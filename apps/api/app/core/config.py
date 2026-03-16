# ./app/application/core/config.py
""" Quản lý cấu hình ứng dụng, nạp biến môi trường (env local)
Cấu hình kết nối DB, đường dẫn lưu trữ file KiCad, đường dẫn static để serve HTML test
Override cấu hình mặc định nếu biến môi trường không tồn tại, đảm bảo an toàn thông tin nhạy cảm như URL DB được mã hóa và không lộ ra ngoài.
Sử dụng lru_cache để tối ưu hiệu suất khi truy cập cấu hình nhiều lần.
"""

from dotenv import load_dotenv
from functools import lru_cache
from pathlib import Path
from typing import Optional
import os

from pydantic import BaseModel, SecretStr

""" lý do sử dụng thư viện
load_dotenv: nạp biến môi trường từ env.local -> quản lý cấu hình, tách biệt giữa code và config
lru_cache: tối ưu hiệu suất khi truy cập cấu hình nhiều lần, tránh việc đọc biến môi trường và tạo đối tượng Settings nhiều lần
Path: quản lý đường dẫn file, đảm bảo tính tương thích giữa các hệ điều hành, dễ dàng xử lý đường dẫn tuyệt đối và tương đối
Optional: cho phép biến môi trường có thể không tồn tại, cung cấp giá trị mặc định hoặc xử lý lỗi nếu cần thiết
BaseModel, SecretStr: định nghĩa lớp cấu hình, đảm bảo tính an toàn khi lưu trữ thông tin nhạy cảm như URL DB, truy cập giá trị một cách an toàn.
"""

load_dotenv(dotenv_path=Path(".env.local"))

class Settings(BaseModel):
    # Cấu hình Settings lấy biến môi trường từ .env.local

    database_url: SecretStr
    kicad_files_path: Path
    static_files_path: Path

    @property
    def db_url(self) -> str:
        # return chuỗi kết nối DB dưới dạng str
        return self.database_url.get_secret_value()

    @property
    def kicad_path(self) -> Path:
        # return đường dẫn tới thư mục lưu trữ các mạch (sch, pcb, ... )
        return self.kicad_files_path

    @property
    def static_path(self) -> Path:
        # return đường dẫn thư mục static để serve HTML test
        return self.static_files_path

@lru_cache()
def get_settings() -> Settings:
    # Cấu hình biến môi trường, đảm bảo chỉ tạo một instance Settings duy nhất trong suốt vòng đời ứng dụng
    url = os.getenv("DATABASE_URL")
    kicad_path = os.getenv("KICAD_PROJECTS_DIR")
    static_path_env: Optional[str] = os.getenv("STATIC_FILES_DIR")
    
    if not url:
        raise RuntimeError("Database Url chưa được cấu hình trong biến môi trường")

    if not kicad_path:
        raise RuntimeError("KiCad ProjectsDir chưa được cấu hình trong biến môi trường")

    static_path = (
        Path(static_path_env).expanduser().resolve()
        if static_path_env
        else Path(__file__).resolve().parents[2] / "static"
    )

    return Settings(
        database_url=url,
        kicad_files_path=Path(kicad_path).expanduser().resolve(),
        static_files_path=static_path,
    )
    
settings = get_settings()