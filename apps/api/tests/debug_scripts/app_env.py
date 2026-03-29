import json
from app.application.services.chatbot_service import ChatbotService
from app.domains.circuits.ai_core.workflow_engine import AICoreWorkflow
import asyncio

async def test():
    service = ChatbotService()
    reply = await service.process_message("thiết kế mạch BJT CE amplifier. tôi cần gain 350. Nguồn 24V", "user_1")
    print(reply)
    
asyncio.run(test())

