# Trung tâm cấu hình ứng dụng
""" Path Json - ENV(dev/prod) - ON/OFF API - Test Mode """

from dataclasses import dataclass       # định nghĩa class cấu hình gọn nhẹ
from pathlib import Path                # quản lý path
import os                               # đọc biến môi trường os (phân biệt dev/prod/test)


# Gán frozen = True để tránh thay đổi thuộc tính sau khi khởi tạo trong dataclass lib
@dataclass(frozen=True)
class Setting:
    """ Central configuration for phase 0 to 2 (json database) """
    APP_ENV: str = os.getenv("APP_ENV", "local")
    # Default path DBjson : apps/api/app/data/circuit_scope.json
    DB_PATH: Path = Path(os.getenv("DB_PATH", Path(__file__).resolve().parents[1] / "data" / "circuit_scope.json"))

settings = Setting() 