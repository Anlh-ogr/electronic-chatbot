"""Validate circuit use case.

This module implements the business logic for validating circuits against
domain rules and returning detailed validation results.
"""

from __future__ import annotations

from typing import List, Optional

from app.domains.circuits.entities import Circuit
from app.domains.circuits.rules import CircuitRulesEngine, RuleViolation
from app.application.circuits.ports import (
    CircuitRepositoryPort,
    ValidationServicePort,
)
from app.application.circuits.dtos import (
    ValidationResponse,
    ViolationDetail,
)
from app.application.circuits.errors import (
    CircuitNotFoundError,
    ValidationServiceError,
)
from app.application.circuits.use_cases.validate_renderability import (
    ValidateRenderability,
    RenderabilityIssue,
)


class ValidateCircuitUseCase:
    """Use case for validating circuits against domain rules.
    
    This use case:
    1. Retrieves circuit from repository (if ID provided)
    2. Runs validation using domain rules engine
    3. Collects violations and suggestions
    4. Returns detailed validation report
    """
    
    def __init__(
        self,
        repository: CircuitRepositoryPort,
        validation_service: ValidationServicePort,
    ):
        """Initialize use case with dependencies.
        
        Args:
            repository: Circuit repository for retrieval
            validation_service: Validation service using domain rules
        """
        self.repository = repository
        self.validation_service = validation_service
        self.renderability_validator = ValidateRenderability()
    
    async def execute(
        self,
        circuit_id: str,
        rules: Optional[List[str]] = None
    ) -> ValidationResponse:
        """Execute circuit validation.
        
        Args:
            circuit_id: Circuit identifier
            rules: Optional list of specific rule names
            
        Returns:
            ValidationResponse with validation results
            
        Raises:
            CircuitNotFoundError: If circuit ID not found
            ValidationServiceError: If validation fails
        """
        try:
            # Get circuit (from repo or request)
            circuit = await self._get_circuit(circuit_id)
            
            # Run domain validation
            violations = await self.validation_service.validate(
                circuit=circuit,
                rules=rules  # None = all rules
            )
            
            # Run renderability validation (application-level rules)
            renderability_issues = await self.renderability_validator.execute(circuit)
            
            # Convert both to violations
            all_violations = violations + self._renderability_to_violations(renderability_issues)
            
            # Convert violations to DTOs
            violation_dtos = self._to_violation_dtos(all_violations)
            
            # Determine overall validity
            is_valid = len(all_violations) == 0
            has_errors = any(v.severity == "error" for v in all_violations)
            has_warnings = any(v.severity == "warning" for v in all_violations)
            
            return ValidationResponse(
                circuit_id=circuit_id,
                is_valid=is_valid,
                violations=violation_dtos,
                error_count=sum(1 for v in all_violations if v.severity.value == "error"),
                warning_count=sum(1 for v in all_violations if v.severity.value == "warning"),
            )
            
        except CircuitNotFoundError:
            raise
        except Exception as e:
            raise ValidationServiceError(reason=str(e)) from e
    
    async def _get_circuit(self, circuit_id: str) -> Circuit:
        """Retrieve circuit from repository.
        
        Args:
            circuit_id: Circuit identifier
            
        Returns:
            Circuit entity
            
        Raises:
            CircuitNotFoundError: If circuit not found
        """
        circuit = await self.repository.get(circuit_id)
        if not circuit:
            raise CircuitNotFoundError(circuit_id)
        return circuit
    
    def _to_violation_dtos(
        self,
        violations: List[RuleViolation]
    ) -> List[ViolationDetail]:
        """Convert domain violations to DTOs.
        
        Args:
            violations: List of domain RuleViolation objects
            
        Returns:
            List of ViolationDetail objects
        """
        return [
            ViolationDetail(
                rule_id=v.rule_id,
                severity=v.severity.value,
                message=v.message,
                component_ids=v.component_ids or [],
                connection_ids=v.connection_ids or [],
            )
            for v in violations
        ]
    
    def _renderability_to_violations(
        self,
        issues: List[RenderabilityIssue]
    ) -> List[RuleViolation]:
        """Convert renderability issues to domain violations.
        
        Args:
            issues: List of RenderabilityIssue objects
            
        Returns:
            List of RuleViolation objects
        """
        from app.domains.circuits.rules import RuleViolation, ViolationSeverity
        
        violations = []
        for issue in issues:
            severity = ViolationSeverity.ERROR if issue.severity == 'error' else ViolationSeverity.WARNING
            
            violations.append(RuleViolation(
                rule_name="renderability_check",
                rule_id="renderability",
                message=issue.message,
                severity=severity,
                component_ids=[issue.component_id] if issue.component_id else [],
                connection_ids=[issue.net_id] if issue.net_id else [],
            ))
        
        return violations
