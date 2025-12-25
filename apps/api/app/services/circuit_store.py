""" Đọc dữ liệu mạch từ Database Json - Phase 0-2 """
""" Không quyết định logic match, chỉ load và cung cấp dữ liệu mạch """

import json                               # đọc database json - phase 2
from pathlib import Path                  # xử lý đường dẫn file an toàn, không phụ thuộc OS
from app.core.config import settings      # gọi config - cấu hình trung tâm ứng dụng


""" CircuitStore class:  để load và truy cập dữ liệu mạch từ file JSON """
class CircuitStore:
    """ Load Json database và hiển thị các truy cập read-only """
    
    # Khởi tạo đường dẫn file json
    def __init__(self, json_path: str | Path | None = None):
        # Đặt đường dẫn mặc định nếu không cung cấp json_path -> config.DB_PATH
        self.json_path = Path(json_path) if json_path else settings.DB_PATH
        self.database: dict | None = None

        # file tồn tại?
        if not self.json_path.exists():
            raise FileNotFoundError(f"Database not found: {self.json_path}. Please check the path!")

    # Load database từ file json
    def load(self) -> "CircuitStore":
        # Đọc file json và parse thành dict
        self.database = json.loads(self.json_path.read_text(encoding="utf-8"))
        return self

    # Truy cập danh sách mạch
    @property
    def circuits(self) -> list:
        return (self.database or {}).get("circuits", [])
    
    # Truy cập metadata
    def meta(self) -> dict:
        db = self.database or {}
        return {
            "priority_order": db.get("priority_order", []),
            "fallback_response": db.get("fallback_response", ""),
            "out_of_scope": db.get("out_of_scope", {}),
            "project": db.get("project", {}),
        }