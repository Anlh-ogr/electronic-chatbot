# Định nghĩa hình dạng dữ liệu đi qua API
""" Request from Frontend to Backend """
""" Response from Backend to Frontend """
""" Không dữ liệu rác, thiếu field, kiểu dữ liệu rõ ràng """

from pydantic import BaseModel, Field       # validate dữ liệu, convert dữ liệu, raise error nếu sai | mô tả field, gán default, validate nâng cao, tạo OpenAPI docs
from typing import Optional, Dict, Any      # Optional[type] khi chưa match mạch, field phụ thuộc logic | Dict[key_type, value_type] | Any: bất kỳ kiểu dữ liệu nào -> dữ liệu không rõ, nhiều thông tin (str, int, list, dict, object)

# Schemas for Chat Request
class ChatRequest(BaseModel):
    """ Input from User. """
    # Nhap yeu cau tu nguoi dung
    message: str = Field(..., min_length=1, description="Yêu cầu mạch (text)")
    
# Schemas for Chat Response
class ChatResponse(BaseModel):
    """ Output to client/UI. """
    matched: bool                               # mach tim thay hay khong? 
    circuit_id: Optional[str] = None            # id cua mach tim thay
    circuit_name: Optional[str] = None          # ten cua mach tim thay
    category: Optional[str] = None              # loai mach
    response: str                               # phan hoi tra ve
    debug: Optional[Dict[str, Any]] = None      # thong tin debug (neu co)