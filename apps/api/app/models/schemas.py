from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

# Schemas for Chat Request
class ChatRequest(BaseModel):
    # Nhap yeu cau tu nguoi dung
    message: str = Field(..., min_length=1, description="Nhập yêu cầu của bạn")
    
# Schemas for Chat Response
class ChatResponse(BaseModel):
    matched: bool                               # mach tim thay hay khong? 
    circuit_id: Optional[str] = None            # id cua mach tim thay
    circuit_name: Optional[str] = None          # ten cua mach tim thay
    category: Optional[str] = None              # loai mach
    response: str                               # phan hoi tra ve
    debug: Optional[Dict[str, Any]] = None      # thong tin debug (neu co)