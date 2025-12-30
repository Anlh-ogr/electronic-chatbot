""" Cấu hình kết nối DB từ .env.local để gọi URL DB
Nạp biến môi trường thông qua os truy cập hệ thống và lấy biến môi trường.

Để tránh lộ thông tin, không hardcode trực tiếp trong env.local, lấy biến 
cấu hình từ env.local thông qua lớp Settings và mã hóa thông tin nhạy cảm.
    
Dùng lru_cache để cache biến cấu hình tránh gọi nhiều lần. """

from dotenv import load_dotenv
import os
from pathlib import Path
from pydantic import BaseModel, SecretStr
from functools import lru_cache

# Nạp môi trường từ file .env.local
load_dotenv(dotenv_path=Path(".env.local"))

""" backup cấu hình cứng nếu không có biến môi trường 
dotenv_path = Path(__file__).resolve().parents[2] / ".env.local"
load_dotenv(dotenv_path=dotenv_path)
"""

""" Lớp cấu hình Settings để lấy biến môi trường từ .env.local """
class Settings(BaseModel):
    database_url: SecretStr
    
    @property
    def db_url(self) -> str:
        """ Trả về chuỗi kết nối DB dưới dạng str """
        return self.database_url.get_secret_value()

@lru_cache()
def get_settings() -> Settings:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set in environment variables")
    return Settings(database_url=url)

settings = get_settings()