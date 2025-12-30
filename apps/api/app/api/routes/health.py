""" Tạo API router 
 * chịu trách nhiệm các endpoint kiểm tra hệ thống """
 
 
from fastapi import APIRouter
router = APIRouter()

# Khai báo endpoint bằng router.get() để kiểm tra hệ thống
@router.get("/health", summary="Service health check")
async def health() -> dict[str,str]:
    """ Endpoint kiểm tra hệ thống trả về trạng thái OK """
    return {"status": "ok"}
