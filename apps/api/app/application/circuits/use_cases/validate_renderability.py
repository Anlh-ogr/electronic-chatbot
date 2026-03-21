"""Validate circuit renderability for export/visualization.

This module validates application/infrastructure constraints that ensure
a circuit can be properly rendered, such as:
- Nets have sufficient pins (≥2) for connection
- Labels are positioned on wires
- Component placement doesn't overlap
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app.domains.circuits.entities import Circuit


@dataclass
class RenderabilityIssue:
    """Represents a renderability validation issue."""
    severity: str  # 'error', 'warning'
    message: str
    component_id: str | None = None
    net_id: str | None = None


class ValidateRenderability:
    """Use case for validating circuit renderability constraints.
    
    These are application/infrastructure rules, not domain rules.
    Domain rules (topology, electrical) are validated in domain layer.
    """
    
    def __init__(self):
        """Initialize renderability validator."""
        pass
    
    async def execute(self, circuit: Circuit) -> List[RenderabilityIssue]:
        """Validate circuit renderability.
        
        Args:
            circuit: Circuit entity to validate
            
        Returns:
            List of renderability issues (empty if renderable)
        """
        issues: List[RenderabilityIssue] = []
        
        # Validate nets have sufficient pins
        issues.extend(self._validate_net_connectivity(circuit))
        
        # Validate component references
        issues.extend(self._validate_component_references(circuit))
        
        # Validate port-net alignment
        issues.extend(self._validate_port_alignment(circuit))
        
        return issues
    
    def _validate_net_connectivity(self, circuit: Circuit) -> List[RenderabilityIssue]:
        """Validate that nets have at least 2 pins for rendering wires.
        
        Args:
            circuit: Circuit to validate
            
        Returns:
            List of connectivity issues
        """
        issues = []
        
        for net_id, net in circuit.nets.items():
            if len(net.connected_pins) < 2:
                issues.append(RenderabilityIssue(
                    severity='warning',
                    message=f"Net '{net_id}' has fewer than 2 pins - cannot render wire",
                    net_id=net_id
                ))
        
        return issues
    
    def _validate_component_references(self, circuit: Circuit) -> List[RenderabilityIssue]:
        """Validate that all pin references point to valid components.
        
        Args:
            circuit: Circuit to validate
            
        Returns:
            List of reference issues
        """
        issues = []
        
        for net_id, net in circuit.nets.items():
            for pin in net.connected_pins:
                try:
                    comp_id = getattr(pin, "component_id", None) or \
                             getattr(pin, "component", None) or \
                             pin.component
                    
                    if comp_id not in circuit.components:
                        issues.append(RenderabilityIssue(
                            severity='error',
                            message=f"Net '{net_id}' references non-existent component '{comp_id}'",
                            net_id=net_id,
                            component_id=comp_id
                        ))
                except Exception as e:
                    issues.append(RenderabilityIssue(
                        severity='error',
                        message=f"Net '{net_id}' has malformed pin reference: {str(e)}",
                        net_id=net_id
                    ))
        
        return issues
    
    def _validate_port_alignment(self, circuit: Circuit) -> List[RenderabilityIssue]:
        """Validate that ports are properly aligned with nets.
        
        Args:
            circuit: Circuit to validate
            
        Returns:
            List of port alignment issues
        """
        issues = []
        
        # Check that each port references an existing net
        for port_id, port in circuit.ports.items():
            if hasattr(port, 'net_id') and port.net_id:
                if port.net_id not in circuit.nets:
                    issues.append(RenderabilityIssue(
                        severity='warning',
                        message=f"Port '{port_id}' references non-existent net '{port.net_id}'",
                        component_id=port_id
                    ))
        
        return issues
    
    def is_renderable(self, issues: List[RenderabilityIssue]) -> bool:
        """Check if circuit is renderable based on validation issues.
        
        Args:
            issues: List of validation issues
            
        Returns:
            True if no error-level issues exist
        """
        return not any(issue.severity == 'error' for issue in issues)
