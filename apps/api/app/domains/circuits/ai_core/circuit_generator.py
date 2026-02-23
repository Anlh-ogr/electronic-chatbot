# app/domains/circuits/ai_core/circuit_generator.py
""" 4: CircuitGenerator — sinh circuit IR + validate domain
Sinh circuit IR từ TopologyPlan + SolvedParams.
Kết hợp template gốc + tham số đã solve → output cuối cùng.
"""

from __future__ import annotations

import json
import copy
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

""" lý do sử dụng thư viện
json: load/save template + circuit data
copy: deep copy template data để apply parameters
dataclass: định nghĩa cấu trúc dữ liệu kết quả sinh mạch
field: hỗ trợ default_factory cho list trong dataclass
logging: ghi log quá trình sinh mạch
path: xác định đường dẫn tới thư mục chứa templates
typing: type hints cho readability và maintainability
"""

logger = logging.getLogger(__name__)

# Path tới templates gốc
_API_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_TEMPLATES_DIR = _API_ROOT / "resources" / "templates"


@dataclass
class ValidationResult:
    """Kết quả validate."""
    passed: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class GeneratedCircuit:
    """Kết quả sinh mạch."""
    template_id: str = ""
    topology_type: str = ""
    circuit_data: Dict[str, Any] = field(default_factory=dict)
    solved_params: Dict[str, float] = field(default_factory=dict)
    gain_formula: str = ""
    actual_gain: Optional[float] = None
    validation: Optional[ValidationResult] = None
    suggested_extensions: List[Dict[str, Any]] = field(default_factory=list)
    rationale: List[str] = field(default_factory=list)
    success: bool = True
    message: str = ""
    applied_params: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "topology_type": self.topology_type,
            "circuit_data": self.circuit_data,
            "solved_params": self.solved_params,
            "gain_formula": self.gain_formula,
            "actual_gain": self.actual_gain,
            "validation": {
                "passed": self.validation.passed if self.validation else True,
                "errors": self.validation.errors if self.validation else [],
                "warnings": self.validation.warnings if self.validation else [],
            },
            "suggested_extensions": self.suggested_extensions,
            "rationale": self.rationale,
            "success": self.success,
            "message": self.message,
            "applied_params": self.applied_params,
        }


class CircuitGenerator:
    """ Sinh circuit data từ template gốc + tham số đã solve.
    Flow:
      1. Load template gốc (JSON)
      2. Apply solved parameters (R, C values override)
      3. Validate domain rules
      4. Trả về GeneratedCircuit
    """

    def __init__(self, templates_dir: Optional[Path] = None):
        self._templates_dir = templates_dir or _TEMPLATES_DIR

    def generate(self, template_id: str, template_file: str, solved_values: Dict[str, float],
        gain_formula: str = "", actual_gain: Optional[float] = None,
        suggested_extensions: Optional[List[Dict]] = None, rationale: Optional[List[str]] = None,
    ) -> GeneratedCircuit:
        """ Sinh circuit từ template + solved params."""

        result = GeneratedCircuit(
            template_id=template_id,
            gain_formula=gain_formula,
            actual_gain=actual_gain,
            suggested_extensions=suggested_extensions or [],
            rationale=rationale or [],
        )

        # 1. Load template gốc
        template_path = self._templates_dir / template_file
        if not template_path.exists():
            result.success = False
            result.message = f"Template file not found: {template_file}"
            return result

        with open(template_path, "r", encoding="utf-8") as f:
            template_data = json.load(f)

        result.topology_type = template_data.get("topology_type", "")

        # 2. Copy template data để apply parameters mà không mutate gốc
        circuit = copy.deepcopy(template_data)
        applied = self._apply_parameters(circuit, solved_values)
        result.circuit_data = circuit
        result.solved_params = solved_values
        result.applied_params = applied

        # 3. Validate
        validation = self._validate_circuit(circuit, template_data)
        result.validation = validation

        if not validation.passed:
            result.success = False
            result.message = f"Validation failed: {'; '.join(validation.errors)}"
        else:
            result.success = True
            warnings_text = (
                f" ({len(validation.warnings)} warnings)"
                if validation.warnings
                else ""
            )
            result.message = (
                f"Circuit generated successfully from {template_id}"
                f"{warnings_text}"
            )

        logger.info(f"CircuitGenerator: {result.message}")
        return result

    def _apply_parameters(self, circuit: Dict[str, Any], values: Dict[str, float]) -> List[str]:
        """Apply solved parameter values vào circuit components."""
        applied = []
        components = circuit.get("components", [])

        for comp in components:
            comp_id = comp.get("id", "")
            comp_type = comp.get("type", "").upper()
            params = comp.get("parameters", {})

            if comp_id in values:
                val = values[comp_id]

                if comp_type == "RESISTOR" or "resistance" in params:
                    params["resistance"] = val
                    applied.append(f"{comp_id}.resistance = {val}")

                elif comp_type == "CAPACITOR" or "capacitance" in params:
                    params["capacitance"] = val
                    applied.append(f"{comp_id}.capacitance = {val}")

                elif comp_type == "INDUCTOR" or "inductance" in params:
                    params["inductance"] = val
                    applied.append(f"{comp_id}.inductance = {val}")

            # luôn ưu tiên mapping theo comp_id đã xử lý ở trên, tránh ghi đè nếu trùng tên
            for key, val in values.items():
                if key.upper() == comp_id.upper():
                    continue  # đã xử lý, tiếp tục mapping theo id
                
                # Pattern: kiểm tra key và comp_id có match không (bỏ dấu gạch dưới, ignore case)
                if key.replace("_", "").upper() == comp_id.replace("_", "").upper():
                    if comp_type == "RESISTOR" or "resistance" in params:
                        params["resistance"] = val
                        applied.append(f"{comp_id}.resistance = {val} (mapped from {key})")

        return applied

    def _validate_circuit(self, circuit: Dict[str, Any], original: Dict[str, Any]) -> ValidationResult:
        """Validate mạch đã sinh."""
        result = ValidationResult()

        # 1: kiểm tra linh kiện (thông tin, tham số ... )
        components = circuit.get("components", [])
        if not components:
            result.errors.append("No components in circuit")
            result.passed = False
            return result

        # 2. kiểm tra kết nối: net connections phải tham chiếu đến component ids tồn tại
        comp_ids = {c["id"] for c in components}
        nets = circuit.get("nets", [])
        for net in nets:
            for conn in net.get("connections", []):
                if isinstance(conn, list) and len(conn) >= 1:
                    ref_id = conn[0]
                    if ref_id not in comp_ids:
                        result.warnings.append(
                            f"Net '{net.get('id')}' references unknown component '{ref_id}'"
                        )

        # 3: kiểm tra ports: port net references phải tồn tại trong nets
        ports = circuit.get("ports", [])
        for port in ports:
            port_id = port.get("id", "")
            net_ref = port.get("net", "")
            if net_ref:
                net_ids = {n.get("id") for n in nets}
                if net_ref not in net_ids:
                    result.warnings.append(
                        f"Port '{port_id}' references unknown net '{net_ref}'"
                    )

        # 4: kiểm tra domain-specific rules (ví dụ: resistor phải có R > 0)
        for comp in components:
            if comp.get("type", "").upper() == "RESISTOR":
                r = comp.get("parameters", {}).get("resistance", 0)
                if r <= 0:
                    result.errors.append(
                        f"Component '{comp['id']}' has invalid resistance: {r}"
                    )
                    result.passed = False

        # 5: kiểm tra constraints từ template gốc (nếu có)
        constraints = original.get("constraints", [])
        for c in constraints:
            ctype = c.get("type", "")
            target = c.get("target", "")
            if ctype == "power_rating_min":
                min_watts = c.get("min_watts", 0)
                result.warnings.append(
                    f"Constraint check: {target} power_rating >= {min_watts}W (manual verification needed)"
                )

        if result.errors:
            result.passed = False

        return result
