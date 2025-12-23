from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="🤖 Electronic Circuit Design Chatbot",
    description="AI hỗ trợ thiết kế mạch điện tử cơ bản (Phase 2)",
    version="2.0.0"
)

# CORS - FIX LỖI: app.add_middleware → app.add_middleware()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check + stats
@app.get("/health")
async def health():
    from app.services.circuit_store import CircuitStore
    try:
        store = CircuitStore().load()
        return {
            "status": "🟢 OK - Phase 2 Complete",
            "version": "2.0.0",
            "circuits": len(store.circuits),
            "knowledge_status": "✅ Full (BOM, formulas, notes, images)",
            "priority_order": store.meta().get("priority_order", [])
        }
    except Exception as e:
        return {"status": "❌ Error", "error": str(e)}

# Root - HTML demo
@app.get("/", response_class=HTMLResponse)
async def root():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>🤖 Electronic Circuit Chatbot</title>
    <meta charset="UTF-8">
    <style>
        body { font-family: system-ui, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #f5f7fa; }
        .container { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
        h1 { color: #1a73e8; margin-bottom: 10px; }
        textarea { width: 100%; height: 120px; font-size: 16px; padding: 15px; border: 2px solid #e0e0e0; border-radius: 12px; resize: vertical; box-sizing: border-box; }
        .buttons { margin: 15px 0; }
        button { background: #1a73e8; color: white; padding: 12px 24px; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; margin-right: 10px; }
        button:hover { background: #1557b0; }
        button.clear { background: #6c757d; }
        button.clear:hover { background: #545b62; }
        #response { margin-top: 20px; padding: 25px; background: #f8f9ff; border-radius: 12px; border-left: 5px solid #1a73e8; white-space: pre-wrap; line-height: 1.6; font-size: 15px; }
        .matched { background: #d4edda !important; border-left-color: #28a745 !important; }
        .not-matched { background: #f8d7da !important; border-left-color: #dc3545 !important; }
        .loading { color: #6c757d; font-style: italic; }
        .circuit-header { background: #e3f2fd; padding: 15px; border-radius: 8px; margin: -25px -25px 20px -25px; border-left: 4px solid #1a73e8; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 <strong>Electronic Circuit Design Chatbot</strong></h1>
        <p><em>Phase 2 Complete: Rule-based với BOM, công thức, nguyên lý đầy đủ cho 4 mạch</em></p>
        
        <textarea id="message" placeholder="Ví dụ: 'Mạch tăng áp 5V lên 12V 1A', 'Mạch giảm áp 24V xuống 5V', 'Khuếch đại đảo LM358 gain 10', 'Mạch nhạc 555'..."></textarea>
        
        <div class="buttons">
            <button onclick="sendMessage()">🚀 <strong>Tạo mạch</strong></button>
            <button class="clear" onclick="clearChat()">🗑️ Xóa</button>
            <button onclick="window.open('/docs', '_blank')">📚 API Docs</button>
        </div>
        
        <div id="response" class="loading">Nhập yêu cầu mạch để bắt đầu...</div>
    </div>
    
    <script>
        async function sendMessage() {
            const msg = document.getElementById('message').value.trim();
            if (!msg) return alert('Vui lòng nhập yêu cầu!');
            
            const responseDiv = document.getElementById('response');
            responseDiv.className = 'loading';
            responseDiv.innerHTML = '🔄 Đang phân tích yêu cầu và tìm mạch phù hợp...';
            
            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: msg})
                });
                
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                
                const data = await res.json();
                
                if (data.matched) {
                    responseDiv.className = 'matched';
                    responseDiv.innerHTML = `
                        <div class="circuit-header">
                            ✅ <strong>${data.circuit_name}</strong> 
                            <span style="float:right; color:#28a745;">
                                Score: ${data.debug.score} | 
                                Keywords: ${data.debug.matched_keywords?.length || 0}/${data.debug.total_keywords || 0}
                            </span>
                        </div>
                        <div>${data.response.replace(/\\n/g, '<br>')}</div>
                    `;
                } else {
                    responseDiv.className = 'not-matched';
                    responseDiv.innerHTML = `❌ ${data.response}`;
                }
            } catch (error) {
                responseDiv.className = 'not-matched';
                responseDiv.innerHTML = `💥 Lỗi kết nối: ${error.message}`;
            }
        }
        
        function clearChat() {
            document.getElementById('message').value = '';
            document.getElementById('response').className = 'loading';
            document.getElementById('response').innerHTML = 'Sẵn sàng nhận yêu cầu mới!';
        }
        
        // Ctrl+Enter để gửi
        document.getElementById('message').addEventListener('keydown', function(e) {
            if (e.ctrlKey && e.key === 'Enter') sendMessage();
        });
        
        // Focus textarea khi load
        document.getElementById('message').focus();
    </script>
</body>
</html>
    """

# Include API routes SAU CÙNG
from app.api.routes.chat import router as chat_router
app.include_router(chat_router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
