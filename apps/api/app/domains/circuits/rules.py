"""
DEPRECATED: Rule-based circuit validation has been superseded by LLM-based IR generation.

This file provides minimal stub implementations for backward compatibility only.
All new circuit design should use LLMRouter.generate_circuit_ir() for complete validation.

Old usage:
    - CircuitRulesEngine for rule-based validation (DEPRECATED)
    - RuleViolation for violations (DEPRECATED)
    - ViolationSeverity for severity levels (DEPRECATED)

New usage:
    - LLMRouter.generate_circuit_ir() for complete LLM-based design & validation
    - CircuitIR schema validation in constraint_validator.py

Do NOT add new rule-based logic. The LLM is the sole engine for circuit generation and validation.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional


class ViolationSeverity(Enum):
    """DEPRECATED: Use LLM-based validation instead."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class RuleViolation:
    """DEPRECATED: Use LLM-based validation instead."""
    rule_id: str = ""
    message: str = ""
    severity: ViolationSeverity = ViolationSeverity.WARNING
    component_id: Optional[str] = None
    violation_type: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "rule_id": self.rule_id,
            "message": self.message,
            "severity": self.severity.value,
            "component_id": self.component_id,
            "violation_type": self.violation_type,
        }


class CircuitRulesEngine:
    """DEPRECATED: Use LLMRouter.generate_circuit_ir() for LLM-based validation.
    
    This stub is kept for backward compatibility with existing services.
    All validation should now be handled by LLM at IR generation time.
    """

    def __init__(self):
        """Initialize (stub for backward compatibility)."""
        pass

    def validate(self, circuit: Any) -> List[RuleViolation]:
        """DEPRECATED: Returns empty list (all validation done by LLM).
        
        Args:
            circuit: Circuit object (ignored)
            
        Returns:
            Empty list - validation is now handled by LLM at generation time
        """
        return []

    def check(self, circuit: Any, rule_ids: Optional[List[str]] = None) -> Dict[str, List[RuleViolation]]:
        """DEPRECATED: Returns empty dict (validation done by LLM).
        
        Args:
            circuit: Circuit object (ignored)
            rule_ids: Rule IDs (ignored)
            
        Returns:
            Empty dict - validation is now handled by LLM
        """
        return {}

    def evaluate_all(self, circuit: Any) -> Dict[str, Any]:
        """DEPRECATED: Returns empty result (validation done by LLM).
        
        Args:
            circuit: Circuit object (ignored)
            
        Returns:
            Empty result dict
        """
        return {"passed": True, "violations": []}


# Backward compatibility aliases
__all__ = ["CircuitRulesEngine", "RuleViolation", "ViolationSeverity"]
