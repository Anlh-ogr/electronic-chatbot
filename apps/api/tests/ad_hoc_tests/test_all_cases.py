import sys
import os
sys.path.insert(0, os.path.abspath("."))
from app.application.services.chatbot_service import ChatbotService
import asyncio
import json

async def run():
    queries = [
        "thiết kế mạch BJT CE amplifier. tôi cần gain 350. Nguồn 24V",
    ]
    service = ChatbotService()
    for q in queries:
        print(f"\n================ \nQuery: {q}")
        reply = await service.process_message(q, "test_user")
        print("\nREPLY TEXT:")
        print(reply.text)
        print("\nCIRCUIT DATA:")
        print(json.dumps(reply.circuit_data, indent=2))
        
if __name__ == "__main__":
    asyncio.run(run())

