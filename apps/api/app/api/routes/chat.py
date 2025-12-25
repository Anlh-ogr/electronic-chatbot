# Cửa ngõ giao tiếp giữa User - toàn bộ hệ thống qua API | Không chứa logic nghiệp vụ, chỉ điều phối luồng dữ liệu
""" Định nghĩa API endpoint ( /chat)
    Nhận request từ frontend
    Gọi repository (dữ liệu + logic) - formatter (diễn đạt)
    Trả về response theo schema """


from fastapi import APIRouter, HTTPException                                # API router: Gom nhóm các API endpoint - tách router theo chức năng | HTTPException: Xử lý lỗi HTTP chuẩn 
from app.models.schemas import ChatRequest, ChatResponse                    # Schema định nghĩa cấu trúc request/response của API -> Swagger auto-generate, dễ test
from app.services.formatter import render_circuit_answer, render_fallback   # Chuyển kết quả logic -> câu trả lời cho user cuối [render_circuit_answer: match thành công | render_fallback: không match được]
from app.repositories.json_repo import JsonCircuitRepo                      # Implementation của CircuitRepo sử dụng JSON làm nguồn dữ liệu - load data + logic match + rule engine

# API endpoint
router = APIRouter()
# Singleton Endpoint repo: Load data 1 lần, tái sử dụng cho tất cả các request
repo = JsonCircuitRepo()

@router.post("/chat", response_model=ChatResponse, summary="Chat")
def chat_endpoint(req: ChatRequest):
    try:
        # Match circuit
        result = repo.search_best(req.message) # fix: lỗi repo.match_circuit không tồn tại -> repo.search_best
        meta = repo.meta()
    
        # Xu ly ca 2 truong hop
        if not result.get("matched", False):
            return ChatResponse(
                matched=False,
                response=render_fallback(meta.get("fallback_response", "")),
                debug={"reason": "no_keyword_match"}
            )
            
        # Render response
        circuit = result["circuit"]
        return ChatResponse(
            matched=True,
            circuit_id=circuit.get("id"),
            circuit_name=circuit.get("name"),
            category=circuit.get("category"),
            response=render_circuit_answer(circuit),
            debug=result.get("debug", {})
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")
    
@router.get("/circuits", summary="List circuits")
def list_circuits():
    try:
        items = repo.list_circuits()
        return {
            "total_circuits": len(items),
            # fix lỗi /circuits
            "circuits": [
                {"id": cir.get("id"), "name": cir.get("name"), "category": cir.get("category")}
                for cir in items
            ],
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")
