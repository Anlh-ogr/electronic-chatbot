import sys
import os
sys.path.insert(0, r"D:\Work\thesis\electronic-chatbot\apps\api")
from app.application.ai.chatbot_service import ChatbotService
import asyncio

def test():
    service = ChatbotService()
    reply = service.chat("thiết kế mạch BJT CE amplifier. tôi cần gain 350. Nguồn 24V", session_id="user_1")
    if "sai khác" in reply.message.lower() or "khác yêu cầu" in reply.message.lower():
         print("WARNING: the message still complains about VCC difference.")
    else:
         print("SUCCESS! No VCC complaint.")
    
test()

