# API route
from fastapi import APIRouter, HTTPException
from app.models.schemas import ChatRequest, ChatResponse
from app.services.circuit_store import CircuitStore
from app.services.matcher import match_circuit
from app.services.formatter import render_circuit_answer, render_fallback

# Tao api router
router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    try:
        # Load store an toan
        store = CircuitStore()
        store.load()
        meta = store.meta()
        
        # Match circuit
        result = match_circuit(req.message, store.circuits, meta.get("priority_order", []))
    
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
    
@router.get("/circuits", summary="Danh sách các mạch trong cơ sở dữ liệu")
async def list_circuits():
    try:
        store = CircuitStore()
        store.load()
        return {
            "total_circuits": len(store.circuits),
            "circuits": [{"id": cir["id"], "name": cir["name"], "category": cir["category"]} for cir in store.circuits]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")
