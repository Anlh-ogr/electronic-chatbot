# .\\thesis\\electronic-chatbot\\apps\\api\\app\\infrastructure\\validation\\validation_service.py
"""Dịch vụ xác thực (Validation Service) dùng mô-đun rules của domain.

Module này triển khai ValidationServicePort bằng cách ủy quyền cho CircuitRulesEngine
ở tầng domain. Nó cung cấp mối ghép tách biệt (clean separation) giữa application layer
và logic xác thực ở domain.

Vietnamese:
- Trách nhiệm chính: Xác thực mạch điện theo quy tắc domain
- Phụ thuộc: Domain rules engine, application ports

English:
- Primary responsibility: Validate circuits against domain rules
- Dependencies: Domain rules engine, application ports
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# typing: Type hints cho IDE support và type checking
from typing import List, Optional

# ====== Domain & Application layers ======
from app.domains.circuits.entities import Circuit
from app.domains.circuits.rules import CircuitRulesEngine, RuleViolation
from app.application.circuits.ports import ValidationServicePort


# ====== Adapter Service ======
class DomainValidationService(ValidationServicePort):
    """Dịch vụ xác thực dùng mô-đun quy tắc (Rules Engine) của domain.
    
    Adapter này wraps CircuitRulesEngine để cung cấp ValidationServicePort.
    Thực hiện mối ghép tách biệt giữa application + domain layer.
    
    Responsibilities (Trách nhiệm):
    - Ủy quyền xác thực cho domain rules engine
    - Áp dụng bộ quy tắc trên các tập hợp circuits
    - Trả lại danh sách violations nếu có lỗi
    """
    
    def __init__(self):
        """Initialize validation service with rules engine."""
        self.rules_engine = CircuitRulesEngine()
    
    async def validate(
        self,
        circuit: Circuit,
        rules: Optional[List[str]] = None
    ) -> List[RuleViolation]:
        """Validate circuit against domain rules.
        
        Args:
            circuit: Circuit entity to validate
            rules: Optional list of specific rule names to apply.
                   If None, all rules are applied.
        
        Returns:
            List of rule violations found
        """
        # Use domain rules engine
        violations = self.rules_engine.validate_circuit(circuit)
        
        # Filter by specific rules if requested
        if rules:
            violations = [v for v in violations if v.rule_id in rules]
        
        return violations
