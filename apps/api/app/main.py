# create FastAPI app + include routers [page:0]
""" Tạo một đầu nối API FastAPI
 * gọi các router từ thư mục """
 
from fastapi import FastAPI
from app.api.routes import health as health_router

# Tạo app FastAPI và gọi router từ health
app = FastAPI()
app.include_router(health_router.router, prefix="/api")