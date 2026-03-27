from __future__ import annotations

"""SQLite feedback store de luu lich su design sessions.

Module nay o tang Infrastructure, khong chua business rules.
"""

import json
import logging
import os
import sqlite3
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from app.application.ai.nlu_service import CircuitIntent
    from app.application.services.circuit_design_orchestrator import DesignResult

logger = logging.getLogger(__name__)


class FeedbackStore:
    """SQLite-based store cho lich su thiet ke va feedback."""

    def __init__(self, db_path: str = "app/infrastructure/db/feedback.db"):
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Khoi tao bang design_sessions neu chua ton tai."""
        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS design_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    topology TEXT,
                    gain_target REAL,
                    vcc REAL,
                    frequency REAL,
                    attempts INTEGER,
                    success INTEGER,
                    final_components TEXT,
                    feedback_history TEXT,
                    dc_metrics TEXT,
                    sim_metrics TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def save_session(
        self,
        session_id: str,
        intent: "CircuitIntent",
        result: "DesignResult",
    ) -> None:
        """Luu mot phien thiet ke vao SQLite de phan tich ve sau."""
        topology = intent.topology or ""
        gain_target = float(intent.gain_target) if intent.gain_target is not None else None
        vcc = float(intent.vcc) if intent.vcc is not None else None
        frequency = float(intent.frequency) if intent.frequency is not None else None

        final_components = result.components.to_dict() if result.components else None

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO design_sessions (
                    session_id,
                    topology,
                    gain_target,
                    vcc,
                    frequency,
                    attempts,
                    success,
                    final_components,
                    feedback_history,
                    dc_metrics,
                    sim_metrics
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    topology,
                    gain_target,
                    vcc,
                    frequency,
                    int(result.attempts),
                    1 if result.success else 0,
                    json.dumps(final_components, ensure_ascii=False),
                    json.dumps(result.feedback_history, ensure_ascii=False),
                    json.dumps(result.dc_metrics or {}, ensure_ascii=False),
                    json.dumps(result.sim_metrics or {}, ensure_ascii=False),
                ),
            )
            conn.commit()

    def get_similar_cases(
        self,
        topology: str,
        gain_target: Optional[float],
        limit: int = 3,
    ) -> List[Dict]:
        """Lay cac session thanh cong tuong tu de dung lam few-shot examples."""
        rows: List[sqlite3.Row]
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row

            if gain_target is not None and gain_target > 0:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM design_sessions
                    WHERE topology = ?
                      AND success = 1
                      AND gain_target IS NOT NULL
                      AND ABS(gain_target - ?) < (? * 0.3)
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (topology, gain_target, gain_target, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM design_sessions
                    WHERE topology = ?
                      AND success = 1
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (topology, limit),
                ).fetchall()

        return [self._row_to_dict(r) for r in rows]

    def get_failure_patterns(self, topology: str) -> List[str]:
        """Tong hop mau loi thuong gap tu cac session that bai cung topology."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT feedback_history
                FROM design_sessions
                WHERE topology = ?
                  AND success = 0
                ORDER BY created_at DESC
                """,
                (topology,),
            ).fetchall()

        unique_errors = set()
        for (feedback_history_json,) in rows:
            if not feedback_history_json:
                continue
            try:
                history = json.loads(feedback_history_json)
            except json.JSONDecodeError:
                continue

            if not isinstance(history, list):
                continue

            for item in history:
                if not isinstance(item, dict):
                    continue
                errors = item.get("errors", [])
                if isinstance(errors, list):
                    for err in errors:
                        if err:
                            unique_errors.add(str(err))
                elif errors:
                    unique_errors.add(str(errors))

        return sorted(unique_errors)

    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        """Chuyen sqlite row sang dict va parse JSON fields."""
        data = dict(row)
        for field in ("final_components", "feedback_history", "dc_metrics", "sim_metrics"):
            raw = data.get(field)
            if raw:
                try:
                    data[field] = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Khong parse duoc JSON field '%s'", field)
                    data[field] = raw
            else:
                data[field] = None
        return data
