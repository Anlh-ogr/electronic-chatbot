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

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class JsonLogFormatter(logging.Formatter):
	"""Format log records as JSON for CI-friendly structured capture."""

	def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - formatter logic
		payload: Dict[str, Any] = {
			"ts": datetime.now(timezone.utc).isoformat(),
			"level": record.levelname,
			"logger": record.name,
			"message": record.getMessage(),
		}
		structured = getattr(record, "structured", None)
		if isinstance(structured, dict):
			payload.update(structured)

		for key in ("stage", "topology", "family", "gain_dB", "bandwidth_Hz", "phase_margin_deg", "dc_bias_v", "circuit_id", "persisted", "ir_id", "artifact_type", "file_size_bytes", "sim_time_s", "components", "nets", "zones", "traces", "board", "board_width_mm", "board_height_mm"):
			if hasattr(record, key):
				value = getattr(record, key)
				if value is not None:
					payload[key] = value

		if record.exc_info:
			payload["exception"] = self.formatException(record.exc_info)

		return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: Optional[int] = None) -> None:
	"""Configure application logging with a JSON stream handler.

	The handler is intentionally simple so CI and local runs both receive
	machine-readable log lines.
	"""
	root = logging.getLogger()
	if root.handlers:
		return

	log_level = level or getattr(logging, (os.getenv("LOG_LEVEL") or "INFO").upper(), logging.INFO)
	root.setLevel(log_level)

	stream_handler = logging.StreamHandler(sys.stdout)
	stream_handler.setLevel(log_level)
	stream_handler.setFormatter(JsonLogFormatter())
	root.addHandler(stream_handler)

	log_file = (os.getenv("LOG_FILE") or "").strip()
	if log_file:
		file_handler = logging.FileHandler(log_file, encoding="utf-8")
		file_handler.setLevel(log_level)
		file_handler.setFormatter(JsonLogFormatter())
		root.addHandler(file_handler)

	logging.captureWarnings(True)
