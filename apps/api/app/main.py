# create FastAPI app + include routers [page:0]
""" Tạo một đầu nối API FastAPI
 * gọi các router từ thư mục 
 * mount thư mục lưu trữ file thiết kế KiCad để truy cập file qua URL
"""
 
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from app.api.routes import health as health_router
from app.core.config import settings

# Tạo app FastAPI và gọi router từ health
class SafeStaticFiles(StaticFiles):
    """ StaticFiles với xử lý lỗi đường dẫn không hợp lệ 500 internet server error """

    async def get_response(self, path, scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except (OSError, ValueError):
            # Windows raises OSError for characters like ':' in a path.
            # Treat these as invalid client paths and respond with 404.
            raise HTTPException(status_code=404)


app = FastAPI()
app.include_router(health_router.router, prefix="/api")


# ===== Sửa đổi tạm thời để tránh lỗi 500 khi truy cập /static/viewer/$$:0:$$ =====
from fastapi.responses import HTMLResponse

@app.get("/static/viewer/$$:0:$$")
async def kicanvas_internal_placeholder():
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