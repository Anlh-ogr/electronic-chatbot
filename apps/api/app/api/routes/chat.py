# API route
from fastapi import APIRouter
from app.models.schemas import ChatRequest, ChatResponse
from app.services.matcher import match_circuit
from app.services.formatter import render_circuit_answer, render_fallback

# Tao api router
router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    from app.main import store
    
    meta = store.meta()
    result = match_circuit(request.message, store.circuits, meta["priority_order"])
    
    if not result["matched"]:
        return ChatResponse(
            matched=False,
            response=render_fallback(meta.get("fallback_responses", "Mình chưa hiểu rõ... bạn nói gì.")),
            debug={"reason": "No matching circuit found"}
        )
        
    circuit = result["circuit"]
    return ChatResponse(
        matched=True,
        circuit_id=circuit["id"],
        circuit_name=circuit["name"],
        category=circuit["category"],
        response=render_circuit_answer(circuit),
        debug=result["debug"]
    )