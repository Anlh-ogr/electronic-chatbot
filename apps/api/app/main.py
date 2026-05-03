# .\\thesis\\electronic-chatbot\\apps\\api\\app\\main.py
"""FastAPI application entrypoint - Router setup + middleware configuration.

Module này khởi tạo FastAPI application instance + kết nối các routers từ
các phần khác nhau của hệ thống. Nó cũng mount thư mục static để serve
KiCad design files qua HTTP.

Vietnamese:
- Trách nhiệm: Khởi tạo FastAPI app, thêm routers, cấu hình middleware
- Routers: chatbot, circuits, snapshots
- Static files: Mount KiCad design outputs cho web access

English:
- Responsibility: Initialize FastAPI app, add routers, configure middleware
- Routers: chatbot, circuits, snapshots
- Static files: Mount KiCad design outputs for web access
"""

# ====== Lý do sử dụng thư viện ======
# fastapi: FastAPI framework chính
# fastapi.staticfiles: Serve static files (KiCad outputs)
# fastapi.responses: File response handling
# app.core.config: Load configuration
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.core.config import settings

# ====== Router imports ======
from app.interfaces.http.routes.chatbot import router as chatbot_router
from app.interfaces.http.routes.circuits import router as circuits_router
from app.interfaces.http.routes.snapshots import router as snapshots_router
from app.interfaces.http.deps import get_industrial_routing_job_queue


# ====== Custom Static Files Handler ======
class SafeStaticFiles(StaticFiles):
    """StaticFiles với xử lý lỗi đường dẫn không hợp lệ.
    
    Override để tránh lỗi 500 internal server error khi access
    non-existent files. Trả về 404 thay vào đó.
    """

    async def get_response(self, path, scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except (OSError, ValueError):
            # Windows raises OSError for characters like ':' in a path.
            # Treat these as invalid client paths and respond with 404.
            raise HTTPException(status_code=404)


# ====== FastAPI Application ======
app = FastAPI()
app.include_router(chatbot_router)
app.include_router(circuits_router)
app.include_router(snapshots_router)


# ====== Global Exception Handlers ======
@app.exception_handler(ValueError)
async def value_error_exception_handler(request, exc: ValueError):
    """Convert ValueError to HTTP 400 Bad Request.
    
    This catches validation errors from CircuitIR normalization/validation,
    net conflict detection, and schema enforcement failures, returning
    structured error responses instead of 500 Internal Server Error.
    """
    import logging
    from fastapi.responses import JSONResponse
    
    logger = logging.getLogger(__name__)
    logger.warning("ValueError caught by global handler: %s", str(exc))
    
    return JSONResponse(
        status_code=400,
        content={
            "error": "validation_error",
            "message": str(exc),
        },
    )


@app.on_event("startup")
async def startup_background_workers() -> None:
    """Bootstrap persistent background workers (industrial routing queue)."""
    queue = get_industrial_routing_job_queue()
    queue.ensure_started()


# ====== Health Check Endpoint ======
@app.get("/api/health")
async def api_health() -> dict[str, str]:
    """Fallback health endpoint for API status check.
    
    Returns:
        Dict với status + service information
    """
    return {
        "status": "healthy",
        "service": "electronic-chatbot-api",
    }


@app.get("/")
async def root() -> FileResponse:
    """Serve frontend homepage."""
    index_file = settings.static_path / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend index not found")
    return FileResponse(str(index_file), media_type="text/html")


@app.get("/favicon.ico")
async def favicon() -> Response:
    """Return favicon if present; otherwise no-content to avoid noisy 404 logs."""
    favicon_file = settings.static_path / "favicon.ico"
    if favicon_file.exists():
        return FileResponse(str(favicon_file), media_type="image/x-icon")
    return Response(status_code=204)


# ===== Sửa đổi tạm thời để tránh lỗi 500 khi truy cập /static/viewer/$$:0:$$ =====
from fastapi.responses import HTMLResponse

@app.get("/static/viewer/$$:0:$$")
async def kicanvas_internal_placeholder():
    return HTMLResponse("<!-- kicanvas placeholder -->", status_code=200)


@app.get("/$$:0:$$")
async def kicanvas_internal_placeholder_root():
    """KiCanvas may request this internal path from root in some embed cases."""
    return HTMLResponse("<!-- kicanvas placeholder -->", status_code=200)
# ====================================================

# Mount thư mục KiCad để đọc file thiết kế
if not settings.kicad_path.exists():
    raise RuntimeError(f"KiCad directory not found: {settings.kicad_path}")

# Mount static để serve file HTML test (có thể chỉ định qua STATIC_FILES_DIR trong .env.local)
if not settings.static_path.exists():
    raise RuntimeError(f"Static directory not found: {settings.static_path}")

app.mount(
    "/kicad-projects",
    SafeStaticFiles(directory=str(settings.kicad_path), html=False),
    name="kicad-files",
)

app.mount(
    "/static",
    SafeStaticFiles(directory=str(settings.static_path), html=True),
    name="static-files",
)