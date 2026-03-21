# .\\thesis\\electronic-chatbot\\apps\\api\\app\\core\\logging.py
"""Cấu hình ghi log (Logging) cho hệ thống.

Module này cung cấp logger configuration cho các phần của ứng dụng:
- API request/response logging
- Error tracking
- AI inference logging (LLM calls, embeddings)
- Simulation + circuit generation logging
- Performance monitoring

Vietnamese:
- Trách nhiệm: Cấu hình + quản lý logging cho toàn bộ ứng dụng
- Phạm vi: API, errors, AI, simulations, circuits
- Lưu trữ: Logs được ghi vào file + console

English:
- Responsibility: Configure + manage logging for entire application
- Scope: API, errors, AI, simulations, circuits
- Storage: Logs written to file + console
"""

# ====== Lý do sử dụng thư viện ======
# logging: Standard Python logging framework cho structured logging
