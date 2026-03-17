"""AI application layer utilities.

Bao gồm các thành phần chính:
- GoogleCloudClient: client gọi Google Cloud Generative Language API
- LLMRouter: điều phối model theo 2 mode Air/Pro
- NLUService: phân tích intent người dùng
- NLGService: sinh phản hồi tự nhiên
- ChatbotService: điều phối toàn bộ luồng xử lý chatbot

Nếu không có API key, hệ thống fallback sang cơ chế rule-based.
"""
