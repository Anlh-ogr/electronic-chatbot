# Xương sống hạ tầng (Entry Point) - Backend FastAPI
""" Tạo ứng dụng FastAPI 
    Gắn middleware (CORS, auth, logging...)
    Gắn các API router (chat, admin, auth, stats...) 
    Được ASGI server (uvicorn) gọi đầu tiên để chạy dịch vụ """


from fastapi import FastAPI                             # FastAPI core - tạo ứng dụng web [Routing, Dependency Injection, Validation(Pydantic), OpenAPI/Swagger, Async support...]
from fastapi.middleware.cors import CORSMiddleware      # Cho phép frontend (domain khác) gọi API backend -> [Origin, Method, Header]
from app.api.routes.chat import router as chat_router   # Import API router từ module chat -> tránh trùng router khác

# app = Container [routes, middleware, config]
app = FastAPI(
    title="Electronic Circuit Design Chatbot",
    version="2.0.0",
    description="Rule-based + Knowledge base (Phase 2)"
)

# CORS - FIX LỖI: app.add_middleware → app.add_middleware()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # Khi lên production -> Chỉ định domain frontend cụ thể
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Đăng ký router
@app.get("/health")
def health():
    # Import trong hàm để tránh vòng lặp import
    from app.repositories.json_repo import JsonCircuitRepo
    repo = JsonCircuitRepo()
    meta = repo.meta()
    
    return {
        "status": "Complete",
        "db": "json",
        "circuits": len(repo.list_circuits()),
        "phase": (meta.get("project") or {}).get("phase"),
    }

app.include_router(chat_router, prefix="/api", tags=["chat"])