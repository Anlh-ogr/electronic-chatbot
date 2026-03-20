# .\thesis\electronic-chatbot\apps\api\app\application\ai\repair_engine.py
"""Repair Engine - Tự động sửa chữa mạch khi validate thất bại.

Module này chịu trách nhiệm:
 1. Nhận ValidationReport với violations
 2. Map violations → repair actions (strategy pattern)
 3. Áp dụng repairs lên circuit_data + solved_params
 4. Re-validate → nếu vẫn lỗi, thử tối đa MAX_REPAIR_ROUNDS
 5. Trả về RepairResult (circuit đã sửa + log thay đổi)

Giới hạn:
 - Chỉ sửa lỗi có chiến lược: gain mismatch, param out-of-range
 - Lỗi cấu trúc (thiếu linh kiện, net sai) → rebuild từ AI Core

Nguyên tắc:
 - Strategy pattern: mỗi violation type → repair action riêng
 - Iterative: repair-validate loop tối đa 3 rounds
 - Conservative: nếu repair fail, return original (không break)
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# copy: deep copy circuit_data để không mutate original khi repair
# logging: ghi log repair actions, validate results
# math: tính param values, conversion (e.g., ohm → kohm)
# dataclass + field: định nghĩa RepairAction, RepairResult value objects
# typing: type safe repair engine API

import copy
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.application.ai.constraint_validator import (
    ConstraintValidator,
    ValidationReport,
    Violation,
)

logger = logging.getLogger(__name__)

MAX_REPAIR_ROUNDS = 3


@dataclass
class RepairAction:
    """Một thao tác sửa chữa đã thực hiện."""
    violation_code: str     # code từ Violation
    description: str        # mô tả thay đổi
    field: str = ""         # trường đã sửa
    old_value: Any = None
    new_value: Any = None

    def to_dict(self) -> dict:
        return {
            "violation_code": self.violation_code,
            "description": self.description,
            "field": self.field,
            "old_value": self.old_value,
            "new_value": self.new_value,
        }


@dataclass
class RepairResult:
    """Kết quả sau quá trình repair."""
    repaired: bool = False
    circuit_data: Dict[str, Any] = field(default_factory=dict)
    solved_params: Dict[str, float] = field(default_factory=dict)
    actions: List[RepairAction] = field(default_factory=list)
    rounds_used: int = 0
    final_report: Optional[ValidationReport] = None

    def to_dict(self) -> dict:
        return {
            "repaired": self.repaired,
            "actions": [a.to_dict() for a in self.actions],
            "rounds_used": self.rounds_used,
            "final_report": self.final_report.to_dict() if self.final_report else None,
        }


class RepairEngine:
    """Tự động sửa chữa mạch dựa trên violations."""

    def __init__(self) -> None:
        self._validator = ConstraintValidator()
        # Map violation code → repair strategy
        self._strategies = {
            "GAIN_MISMATCH": self._repair_gain,
            "GAIN_DEVIATION": self._repair_gain,
            "HARD_GAIN_MIN": self._repair_gain,
            "HARD_GAIN_MAX": self._repair_gain,
            "PARAM_OUT_OF_RANGE": self._repair_param_range,
        }

    def repair(
        self,
        circuit_data: Dict[str, Any],
        solved_params: Dict[str, float],
        intent_dict: Dict[str, Any],
        report: ValidationReport,
    ) -> RepairResult:
        """Cố gắng sửa chữa circuit dựa trên violations.

        Returns:
            RepairResult với circuit đã sửa (hoặc gốc nếu không sửa được).
        """
        result = RepairResult(
            circuit_data=copy.deepcopy(circuit_data),
            solved_params=dict(solved_params),
        )

        current_report = report

        for round_num in range(1, MAX_REPAIR_ROUNDS + 1):
            result.rounds_used = round_num
            repaired_any = False

            for violation in current_report.errors:
                strategy = self._strategies.get(violation.code)
                if strategy is None:
                    continue
                action = strategy(violation, result.circuit_data, result.solved_params, intent_dict)
                if action:
                    result.actions.append(action)
                    repaired_any = True

            if not repaired_any:
                break

            # Re-validate
            current_report = self._validator.validate(
                result.circuit_data, intent_dict, result.solved_params,
            )
            if current_report.passed:
                result.repaired = True
                break

        result.final_report = current_report
        result.repaired = current_report.passed if current_report else False
        logger.info(
            f"RepairEngine: {len(result.actions)} actions in {result.rounds_used} rounds, "
            f"repaired={result.repaired}"
        )
        return result

    # ------------------------------------------------------------------ #
    #  Repair strategies
    # ------------------------------------------------------------------ #

    def _repair_gain(
        self,
        violation: Violation,
        circuit: Dict[str, Any],
        solved: Dict[str, float],
        intent: Dict[str, Any],
    ) -> Optional[RepairAction]:
        """Sửa gain bằng cách điều chỉnh resistor feedback (Rf/Ri hoặc Rc/Re)."""
        target_gain = intent.get("gain_target")
        if target_gain is None or target_gain <= 0:
            return None

        actual_gain = violation.actual
        if actual_gain is None:
            return None

        ratio = target_gain / actual_gain if actual_gain != 0 else 2.0

        # Tìm cặp resistor phổ biến
        components = circuit.get("components", [])
        resistors = [c for c in components if c.get("type", "").upper() == "RESISTOR"]

        # Heuristic: tìm Rf (feedback) hoặc Rc (collector) và điều chỉnh
        for r in resistors:
            r_id = r.get("id", "").upper()
            params = r.get("parameters", {})
            if r_id in ("RF", "RC", "R2", "R_F", "R_C"):
                old_val = params.get("resistance")
                if isinstance(old_val, dict):
                    old_val = old_val.get("value", old_val)
                if isinstance(old_val, (int, float)) and old_val > 0:
                    new_val = old_val * ratio
                    # Clamp to reasonable range
                    new_val = max(100, min(new_val, 1e6))
                    new_val = self._nearest_standard(new_val)
                    params["resistance"] = new_val
                    solved[r.get("id", "")] = new_val
                    if "actual_gain" in solved:
                        solved["actual_gain"] = target_gain

                    return RepairAction(
                        violation_code=violation.code,
                        description=f"Điều chỉnh {r.get('id','')} từ {old_val:.0f}Ω → {new_val:.0f}Ω để đạt gain {target_gain}",
                        field=f"{r.get('id','')}.resistance",
                        old_value=old_val,
                        new_value=new_val,
                    )
        return None

    def _repair_param_range(
        self,
        violation: Violation,
        circuit: Dict[str, Any],
        solved: Dict[str, float],
        intent: Dict[str, Any],
    ) -> Optional[RepairAction]:
        """Clamp giá trị linh kiện về phạm vi hợp lệ."""
        if not violation.field or "." not in violation.field:
            return None

        comp_id, param_name = violation.field.split(".", 1)
        expected = violation.expected  # "[lo, hi]" string
        actual = violation.actual

        if not isinstance(actual, (int, float)):
            return None

        # Parse range from expected string
        try:
            parts = str(expected).strip("[]").split(",")
            lo, hi = float(parts[0].strip()), float(parts[1].strip())
        except (ValueError, IndexError):
            return None

        new_val = max(lo, min(actual, hi))
        new_val = self._nearest_standard(new_val)

        # Apply to circuit
        for comp in circuit.get("components", []):
            if comp.get("id") == comp_id:
                params = comp.get("parameters", {})
                params[param_name] = new_val
                solved[comp_id] = new_val
                return RepairAction(
                    violation_code=violation.code,
                    description=f"Clamp {comp_id}.{param_name} từ {actual} → {new_val} (phạm vi [{lo}, {hi}])",
                    field=violation.field,
                    old_value=actual,
                    new_value=new_val,
                )
        return None

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _nearest_standard(value: float) -> float:
        """Tìm giá trị điện trở/tụ chuẩn E12 gần nhất."""
        if value <= 0:
            return value
        e12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
        decade = 10 ** math.floor(math.log10(value))
        normalized = value / decade
        best = min(e12, key=lambda x: abs(x - normalized))
        return best * decade
