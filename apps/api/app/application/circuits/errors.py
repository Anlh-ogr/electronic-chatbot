# .\thesis\electronic-chatbot\apps\api\app\application\circuits\errors.py
"""Application layer errors cho circuits domain.

Module này chịu trách nhiệm:
 1. Định nghĩa exception custom cho application layer
 2. Represent business rule violations
 3. Provide details để trace lỗi
 4. Separate application errors từ domain/infrastructure errors

Nguyên tắc:
 - ApplicationError: base class cho tất cả app layer exceptions
 - Có message + details dict để logging/API response
 - Được throw từ use cases, caught ở interfaces (HTTP routes)
"""

from typing import Optional, Dict, Any


class ApplicationError(Exception):
    """Base exception for all application layer errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


class CircuitNotFoundError(ApplicationError):
    """Raised when a requested circuit does not exist."""
    
    def __init__(self, circuit_id: str):
        super().__init__(
            message=f"Circuit with ID '{circuit_id}' not found",
            details={"circuit_id": circuit_id}
        )


class InvalidCircuitError(ApplicationError):
    """Raised when circuit validation fails."""
    
    def __init__(self, message: str, violations: Optional[list] = None):
        super().__init__(
            message=message,
            details={"violations": violations or []}
        )


class ExportError(ApplicationError):
    """Raised when circuit export operation fails."""
    
    def __init__(self, format_type: str, reason: str):
        super().__init__(
            message=f"Failed to export circuit to {format_type}: {reason}",
            details={"format": format_type, "reason": reason}
        )


class TemplateGenerationError(ApplicationError):
    """Raised when template-based circuit generation fails."""
    
    def __init__(self, template_name: str, reason: str):
        super().__init__(
            message=f"Failed to generate circuit from template '{template_name}': {reason}",
            details={"template": template_name, "reason": reason}
        )


class SimulationError(ApplicationError):
    """Raised when circuit simulation fails."""
    
    def __init__(self, reason: str, circuit_id: Optional[str] = None):
        super().__init__(
            message=f"Simulation failed: {reason}",
            details={"reason": reason, "circuit_id": circuit_id}
        )


class StorageError(ApplicationError):
    """Raised when file storage operations fail."""
    
    def __init__(self, operation: str, path: str, reason: str):
        super().__init__(
            message=f"Storage {operation} failed for '{path}': {reason}",
            details={"operation": operation, "path": path, "reason": reason}
        )


class ValidationServiceError(ApplicationError):
    """Raised when validation service encounters an error."""
    
    def __init__(self, reason: str):
        super().__init__(
            message=f"Validation service error: {reason}",
            details={"reason": reason}
        )
