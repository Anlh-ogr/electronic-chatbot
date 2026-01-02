""" Cấu hình kết nối DB từ .env.local để gọi URL DB
Nạp biến môi trường thông qua os truy cập hệ thống và lấy biến môi trường.

Để tránh lộ thông tin, không hardcode trực tiếp trong env.local, lấy biến 
cấu hình từ env.local thông qua lớp Settings và mã hóa thông tin nhạy cảm.
    
Dùng lru_cache để cache biến cấu hình tránh gọi nhiều lần. """

from dotenv import load_dotenv
from functools import lru_cache
from pathlib import Path
from typing import Optional
import os

from pydantic import BaseModel, SecretStr

# Nạp môi trường từ file .env.local
load_dotenv(dotenv_path=Path(".env.local"))

""" backup cấu hình cứng nếu không có biến môi trường 
dotenv_path = Path(__file__).resolve().parents[2] / ".env.local"
load_dotenv(dotenv_path=dotenv_path)
"""

""" Lớp cấu hình Settings để lấy biến môi trường từ .env.local """
class Settings(BaseModel):
    database_url: SecretStr
    kicad_files_path: Path
    static_files_path: Path

    @property
    def db_url(self) -> str:
        """Trả về chuỗi kết nối DB dưới dạng str"""
        return self.database_url.get_secret_value()

    @property
    def kicad_path(self) -> Path:
        """Trả về đường dẫn tới thư mục lưu trữ các mạch (sch, pcb, ... )"""
        return self.kicad_files_path

    @property
    def static_path(self) -> Path:
        """Trả về đường dẫn thư mục static để serve HTML test"""
        return self.static_files_path

@lru_cache()
def get_settings() -> Settings:
    url = os.getenv("DATABASE_URL")
    kicad_path = os.getenv("KICAD_PROJECTS_DIR")
    static_path_env: Optional[str] = os.getenv("STATIC_FILES_DIR")
    
    if not url:
        raise RuntimeError("DATABASE_URL not set in environment variables")

    if not kicad_path:
        raise RuntimeError("KICAD_PROJECTS_DIR not set in environment variables")

    static_path = (
        Path(static_path_env).expanduser().resolve()
        if static_path_env
        else Path(__file__).resolve().parents[1] / "static"
    )

    return Settings(
        database_url=url,
        kicad_files_path=Path(kicad_path).expanduser().resolve(),
        static_files_path=static_path,
    )
    
settings = get_settings()