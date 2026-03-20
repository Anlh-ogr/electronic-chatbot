# .\\thesis\\electronic-chatbot\\apps\\api\\app\\core\\config.py
"""Quản lý cấu hình (Configuration) ứng dụng.

Module này quản lý toàn bộ cấu hình ứng dụng bằng cách nạp biến môi trường.
Nó cấu hình:
- Kết nối Database (DB_URL, connection pool)
- Đường dẫn lưu trữ file KiCad
- Đường dẫn static files để serve HTML test
- Credentials cho Google API, LLM providers
- Feature flags

Sử dụng pydantic.BaseModel + lru_cache để tối ưu hiệu suất và đảm bảo
thông tin nhạy cảm (URLs, tokens) được bảo vệ.

Vietnamese:
- Trách nhiệm: Tải + validate configuration từ environment
- Bảo mật: Mã hóa SecretStr cho passwords/tokens
- Tối ưu: lru_cache để avoid re-reading env variables

English:
- Responsibility: Load + validate configuration from environment variables
- Security: Encrypted SecretStr for passwords/tokens
- Optimization: lru_cache to avoid re-reading env variables
"""

# ====== Lý do sử dụng thư viện ======
# dotenv: Load environment variables từ .env files
# lru_cache: Cache configuration objects để tối ưu hiệu suất
# pathlib: Cross-platform path handling
# pydantic: Configuration validation + type checking
from dotenv import load_dotenv
from functools import lru_cache
from pathlib import Path
from typing import Optional
import os

from pydantic import BaseModel, SecretStr

# ====== Load Configuration ======
load_dotenv(dotenv_path=Path(".env.local"))


# ====== Settings Configuration Class ======
class Settings(BaseModel):
    """Cấu hình (Settings) cho ứng dụng.
    
    Class này kế thừa pydantic.BaseModel để tự động validate
    environment variables với type checking.
    """
    
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