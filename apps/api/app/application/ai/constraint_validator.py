# .\thesis\electronic-chatbot\apps\api\app\application\ai\constraint_validator.py
"""Constraint Validator - Kiểm tra ràng buộc mạch điện tử.

Module này chịu trách nhiệm:
 1. Validate kết quả pipeline theo 4 chiều:
    - Structural: đủ linh kiện, kết nối hợp lệ
    - Parameter: giá trị trong phạm vi hợp lý
    - Intent: khớp với yêu cầu ban đầu (gain, vcc, topology)
    - Edit: nếu modify, thao tác được thực hiện đúng
 2. Tổng hợp violations → ValidationReport
 3. Cung cấp severity level (error | warning)

Nguyên tắc:
 - Rule-based: không dùng LLM
 - Deterministic: cùng input → cùng result
 - Granular: từng violation riêng (dễ repair)
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# logging: ghi log validation rules, violations found
# dataclass + field: định nghĩa Violation, ValidationReport value objects
# typing: type safe validator API, generic circuit support

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Violation:
    """Một vi phạm constraint."""
    code: str           # mã lỗi: "GAIN_MISMATCH", "MISSING_COMPONENT", ...
    severity: str       # "error" | "warning"
    message: str        # mô tả vi phạm
    field: str = ""     # trường liên quan: "gain", "R1.resistance", ...
    expected: Any = None
    actual: Any = None

    def to_dict(self) -> dict:
        d = {"code": self.code, "severity": self.severity, "message": self.message}
        if self.field:
            d["field"] = self.field
        if self.expected is not None:
            d["expected"] = self.expected
        if self.actual is not None:
            d["actual"] = self.actual
        return d


@dataclass
class ValidationReport:
    """Kết quả validate toàn bộ."""
    passed: bool = True
    violations: List[Violation] = field(default_factory=list)
    checked_rules: int = 0

    @property
    def errors(self) -> List[Violation]:
        return [v for v in self.violations if v.severity == "error"]

    @property
    def warnings(self) -> List[Violation]:
        return [v for v in self.violations if v.severity == "warning"]

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "errors_count": len(self.errors),
            "warnings_count": len(self.warnings),
            "checked_rules": self.checked_rules,
        }


# ── Phạm vi giá trị hợp lý cho linh kiện ──
_PARAM_RANGES = {
    "RESISTOR": {"resistance": (1.0, 10e6)},           # 1Ω – 10MΩ
    "CAPACITOR": {"capacitance": (1e-12, 10e-3)},      # 1pF – 10mF
    "INDUCTOR": {"inductance": (1e-9, 10.0)},          # 1nH – 10H
    "VOLTAGE_SOURCE": {"voltage": (0.1, 100.0)},       # 0.1V – 100V
}


class ConstraintValidator:
    """Validate GeneratedCircuit dựa trên intent constraints."""

    def validate(
        self,
        circuit_data: Dict[str, Any],
        intent_dict: Dict[str, Any],
        solved_params: Optional[Dict[str, float]] = None,
    ) -> ValidationReport:
        """Validate circuit against intent requirements.

        Args:
            circuit_data: circuit JSON từ GeneratedCircuit.circuit_data
            intent_dict: CircuitIntent.to_dict()
            solved_params: SolvedParams.values (tham số đã giải)
        """
        report = ValidationReport()
        solved_params = solved_params or {}

        self._check_structural(circuit_data, report)
        self._check_param_ranges(circuit_data, report)
        self._check_intent_match(circuit_data, intent_dict, solved_params, report)
        self._check_hard_constraints(intent_dict, solved_params, report)

        report.passed = len(report.errors) == 0
        return report

    # ------------------------------------------------------------------ #
    #  Structural checks
    # ------------------------------------------------------------------ #

    def _check_structural(self, circuit: Dict[str, Any], report: ValidationReport) -> None:
        """Kiểm tra cấu trúc cơ bản: có components, có nets, kết nối hợp lệ."""
        report.checked_rules += 1
        components = circuit.get("components", [])
        if not components:
            report.violations.append(Violation(
                code="NO_COMPONENTS", severity="error",
                message="Mạch không có linh kiện nào",
            ))
            return

        comp_ids = {c.get("id", "") for c in components}
        nets = circuit.get("nets", [])

        report.checked_rules += 1
        if not nets:
            report.violations.append(Violation(
                code="NO_NETS", severity="warning",
                message="Mạch không có kết nối (nets) nào",
            ))

        # Kiểm tra kết nối tham chiếu component hợp lệ
        report.checked_rules += 1
        for net in nets:
            for conn in net.get("connections", []):
                ref_id = conn[0] if isinstance(conn, list) and conn else ""
                if ref_id and ref_id not in comp_ids:
                    report.violations.append(Violation(
                        code="INVALID_NET_REF", severity="error",
                        message=f"Net '{net.get('name','')}' tham chiếu linh kiện '{ref_id}' không tồn tại",
                        field=f"net.{net.get('name','')}",
                    ))

    # ------------------------------------------------------------------ #
    #  Parameter range checks
    # ------------------------------------------------------------------ #

    def _check_param_ranges(self, circuit: Dict[str, Any], report: ValidationReport) -> None:
        """Kiểm tra giá trị linh kiện trong phạm vi hợp lý."""
        for comp in circuit.get("components", []):
            comp_type = comp.get("type", "").upper()
            comp_id = comp.get("id", "")
            params = comp.get("parameters", {})
            ranges = _PARAM_RANGES.get(comp_type, {})

            for param_name, (lo, hi) in ranges.items():
                val = params.get(param_name)
                if val is None:
                    continue
                # Lấy giá trị thực (có thể là dict {"value": x} hoặc float)
                if isinstance(val, dict):
                    val = val.get("value", val)
                if not isinstance(val, (int, float)):
                    continue

                report.checked_rules += 1
                if val < lo or val > hi:
                    report.violations.append(Violation(
                        code="PARAM_OUT_OF_RANGE", severity="warning",
                        message=f"{comp_id}.{param_name} = {val} ngoài phạm vi [{lo}, {hi}]",
                        field=f"{comp_id}.{param_name}",
                        expected=f"[{lo}, {hi}]",
                        actual=val,
                    ))

    # ------------------------------------------------------------------ #
    #  Intent match checks
    # ------------------------------------------------------------------ #

    def _check_intent_match(
        self,
        circuit: Dict[str, Any],
        intent: Dict[str, Any],
        solved: Dict[str, float],
        report: ValidationReport,
    ) -> None:
        """Kiểm tra kết quả có khớp yêu cầu ban đầu không."""
        # Gain mismatch
        gain_target = intent.get("gain_target")
        if gain_target is not None and gain_target > 0:
            report.checked_rules += 1
            # Tìm actual gain từ circuit_data hoặc solved
            actual_gain = circuit.get("actual_gain") or solved.get("actual_gain")
            if actual_gain is not None:
                error_pct = abs(actual_gain - gain_target) / gain_target * 100
                if error_pct > 20:
                    report.violations.append(Violation(
                        code="GAIN_MISMATCH", severity="error",
                        message=f"Gain thực tế ({actual_gain:.1f}) lệch {error_pct:.1f}% so với yêu cầu ({gain_target})",
                        field="gain",
                        expected=gain_target,
                        actual=actual_gain,
                    ))
                elif error_pct > 10:
                    report.violations.append(Violation(
                        code="GAIN_DEVIATION", severity="warning",
                        message=f"Gain thực tế ({actual_gain:.1f}) lệch {error_pct:.1f}% so với yêu cầu ({gain_target})",
                        field="gain",
                        expected=gain_target,
                        actual=actual_gain,
                    ))

        # VCC match
        vcc_target = intent.get("vcc")
        if vcc_target is not None:
            report.checked_rules += 1
            # Tìm voltage source trong circuit
            for comp in circuit.get("components", []):
                if comp.get("type", "").upper() == "VOLTAGE_SOURCE":
                    params = comp.get("parameters", {})
                    v = params.get("voltage")
                    if isinstance(v, dict):
                        v = v.get("value")
                    if v is not None and abs(v - vcc_target) > 0.5:
                        report.violations.append(Violation(
                            code="VCC_MISMATCH", severity="warning",
                            message=f"Nguồn {comp.get('id','')} = {v}V khác yêu cầu {vcc_target}V",
                            field="vcc",
                            expected=vcc_target,
                            actual=v,
                        ))
                    break

    # ------------------------------------------------------------------ #
    #  Hard constraint checks
    # ------------------------------------------------------------------ #

    def _check_hard_constraints(
        self,
        intent: Dict[str, Any],
        solved: Dict[str, float],
        report: ValidationReport,
    ) -> None:
        """Kiểm tra hard constraints từ intent."""
        constraints = intent.get("hard_constraints", {})
        if not constraints:
            return

        actual_gain = solved.get("actual_gain")

        gain_min = constraints.get("gain_min")
        if gain_min is not None and actual_gain is not None:
            report.checked_rules += 1
            if actual_gain < gain_min:
                report.violations.append(Violation(
                    code="HARD_GAIN_MIN", severity="error",
                    message=f"Gain {actual_gain:.1f} < yêu cầu tối thiểu {gain_min}",
                    field="gain",
                    expected=f">= {gain_min}",
                    actual=actual_gain,
                ))

        gain_max = constraints.get("gain_max")
        if gain_max is not None and actual_gain is not None:
            report.checked_rules += 1
            if actual_gain > gain_max:
                report.violations.append(Violation(
                    code="HARD_GAIN_MAX", severity="error",
                    message=f"Gain {actual_gain:.1f} > yêu cầu tối đa {gain_max}",
                    field="gain",
                    expected=f"<= {gain_max}",
                    actual=actual_gain,
                ))

        vcc_max = constraints.get("vcc_max")
        if vcc_max is not None:
            vcc_val = solved.get("vcc") or constraints.get("vcc")
            if vcc_val is not None:
                report.checked_rules += 1
                if vcc_val > vcc_max:
                    report.violations.append(Violation(
                        code="HARD_VCC_MAX", severity="error",
                        message=f"VCC {vcc_val}V > giới hạn tối đa {vcc_max}V",
                        field="vcc",
                        expected=f"<= {vcc_max}",
                        actual=vcc_val,
                    ))
