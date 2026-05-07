from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("elpis.structured")


def log_stage(stage: str, **fields: Any) -> None:
    """Emit a structured log entry for a pipeline stage.

    The entry is emitted at INFO level with a JSON payload that includes
    the stage name and provided fields.
    """
    try:
        logger.info(stage, extra={"stage": stage, "structured": {"stage": stage, **(fields or {})}})
    except Exception:
        # Fallback to human-readable log if JSON serialization fails
        logger.info("%s %s", stage, str(fields))
