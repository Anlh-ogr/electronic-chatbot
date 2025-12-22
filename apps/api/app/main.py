# main 
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.services.circuit_store import CircuitStore
from app.api.routes.chat import router as chat_router

app = FastAPI(title="Electronic Chatbot API", version="1.0.0")
app.include_router(chat_router, prefix="/api")

# CORS cho frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load Database ngay khi khởi động ứng dụng (start server)
store = CircuitStore()
store.load()

# Health check
@app.get("/health")
def health():
    return {"status": "ok", "circuit": len(store.circuits)}

# Include API routes
from app.api.routes.chat import router as chat_router
app.include_router(chat_router, prefix="/api")  # API routes 
