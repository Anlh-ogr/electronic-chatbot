"""Mapper from CircuitSpec (JSON) to Circuit domain entities.

This module converts external CircuitSpec format to internal domain entities,
handling validation and transformation.
"""

from __future__ import annotations

from typing import Dict, Any, List
import json
from pathlib import Path

from app.domains.circuits.entities import (
    Circuit,
    Component,
    ComponentType,
    Net,
    Port,
    PortDirection,
    ParameterValue,
    PinRef,
)


class CircuitSpecMapper:
    """Mapper for converting CircuitSpec JSON to Circuit entity.
    
    Responsibilities:
    - Parse and validate CircuitSpec JSON
    - Convert to domain entities (Circuit, Component, Net, Port)
    - Handle type conversions and parameter mapping
    """
    
    @staticmethod
    def from_json(spec_json: str | dict) -> Circuit:
        """Convert CircuitSpec JSON to Circuit entity.
        
        Args:
            spec_json: CircuitSpec as JSON string or dict
            
        Returns:
            Circuit domain entity
            
        Raises:
            ValueError: If spec is invalid
            KeyError: If required fields missing
        """
        # Parse JSON if string
        if isinstance(spec_json, str):
            spec = json.loads(spec_json)
        else:
            spec = spec_json
        
        # Validate required fields
        if "version" not in spec:
            raise ValueError("CircuitSpec missing 'version' field")
        if "metadata" not in spec:
            raise ValueError("CircuitSpec missing 'metadata' field")
        if "components" not in spec:
            raise ValueError("CircuitSpec missing 'components' field")
        if "nets" not in spec:
            raise ValueError("CircuitSpec missing 'nets' field")
        
        # Extract metadata
        metadata = spec["metadata"]
        circuit_name = metadata.get("name", "Unnamed Circuit")
        circuit_type = metadata.get("type", "other")
        description = metadata.get("description", "")
        
        # Map components
        components = CircuitSpecMapper._map_components(spec["components"])
        
        # Map nets
        nets = CircuitSpecMapper._map_nets(spec["nets"])
        
        # Map ports
        ports = CircuitSpecMapper._map_ports(spec.get("ports", []))
        
        # Create Circuit entity
        circuit = Circuit(
            name=circuit_name,
            _components=components,
            _nets=nets,
            _ports=ports,
        )
        
        return circuit
    
    @staticmethod
    def from_file(file_path: str | Path) -> Circuit:
        """Load CircuitSpec from JSON file.
        
        Args:
            file_path: Path to CircuitSpec JSON file
            
        Returns:
            Circuit domain entity
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"CircuitSpec file not found: {file_path}")
        
        spec_json = path.read_text(encoding='utf-8')
        return CircuitSpecMapper.from_json(spec_json)
    
    @staticmethod
    def _map_components(components_spec: List[Dict[str, Any]]) -> Dict[str, Component]:
        """Map component specifications to Component entities.
        
        Args:
            components_spec: List of component specifications
            
        Returns:
            Dictionary of Component entities keyed by component ID
        """
        components = {}
        
        for comp_spec in components_spec:
            comp_id = comp_spec["id"]
            comp_type_str = comp_spec["type"]
            pins = comp_spec["pins"]
            
            # Map component type
            try:
                comp_type = ComponentType(comp_type_str)
            except ValueError:
                raise ValueError(f"Invalid component type: {comp_type_str}")
            
            # Map parameters
            parameters = CircuitSpecMapper._map_parameters(
                comp_spec.get("parameters", {})
            )
            
            # Create Component entity
            component = Component(
                id=comp_id,
                type=comp_type,
                pins=tuple(pins),
                parameters=parameters
            )
            
            components[comp_id] = component
        
        return components
    
    @staticmethod
    def _map_parameters(params_spec: Dict[str, Any]) -> Dict[str, ParameterValue]:
        """Map parameter specifications to ParameterValue objects.
        
        Args:
            params_spec: Parameter specifications
            
        Returns:
            Dictionary of ParameterValue objects
        """
        parameters = {}
        
        for param_name, param_data in params_spec.items():
            if isinstance(param_data, dict) and "value" in param_data:
                # Structured parameter with value and optional unit
                value = param_data["value"]
                unit = param_data.get("unit")
                parameters[param_name] = ParameterValue(value=value, unit=unit)
            else:
                # Simple value
                parameters[param_name] = ParameterValue(value=param_data)
        
        return parameters
    
    @staticmethod
    def _map_nets(nets_spec: List[Dict[str, Any]]) -> Dict[str, Net]:
        """Map net specifications to Net entities.
        
        Args:
            nets_spec: List of net specifications
            
        Returns:
            Dictionary of Net entities keyed by net ID
        """
        nets = {}
        
        for net_spec in nets_spec:
            net_id = net_spec["id"]
            pins_spec = net_spec["pins"]
            
            # Parse pins (format: "COMP_ID.pin_name")
            connected_pins = []
            for pin_str in pins_spec:
                parts = pin_str.split(".")
                if len(parts) != 2:
                    raise ValueError(
                        f"Invalid pin format '{pin_str}'. Expected 'COMP_ID.pin_name'"
                    )
                
                comp_id, pin_name = parts
                connected_pins.append(PinRef(
                    component_id=comp_id,
                    pin_name=pin_name
                ))
            
            # Create Net entity
            net = Net(
                name=net_id,
                connected_pins=tuple(connected_pins)
            )
            
            nets[net_id] = net
        
        return nets
    
    @staticmethod
    def _map_ports(ports_spec: List[Dict[str, Any]]) -> Dict[str, Port]:
        """Map port specifications to Port entities.
        
        Args:
            ports_spec: List of port specifications
            
        Returns:
            Dictionary of Port entities keyed by port ID
        """
        ports = {}
        
        for port_spec in ports_spec:
            port_id = port_spec["id"]
            port_name = port_spec["name"]
            net_name = port_spec.get("net_id")  # Changed from net_id to net_name
            direction_str = port_spec.get("direction", "input")
            
            # Map direction
            try:
                direction = PortDirection(direction_str)
            except ValueError:
                # Default to input if invalid
                direction = PortDirection.INPUT
            
            # Create Port entity
            port = Port(
                name=port_name,
                net_name=net_name,
                direction=direction
            )
            
            ports[port_name] = port  # Key by port.name, not port_id
        
        return ports
    
    @staticmethod
    def to_json(circuit: Circuit) -> str:
        """Convert Circuit entity to CircuitSpec JSON.
        
        Args:
            circuit: Circuit domain entity
            
        Returns:
            CircuitSpec JSON string
        """
        spec = {
            "version": "1.0",
            "metadata": {
                "name": circuit.name or "Unnamed Circuit",
                "type": circuit.metadata.get("type", "other"),
                "description": circuit.metadata.get("description", ""),
                "topology": circuit.metadata.get("topology", ""),
            },
            "components": [],
            "nets": [],
            "ports": []
        }
        
        # Serialize components
        for comp_id, component in circuit.components.items():
            comp_spec = {
                "id": component.id,
                "type": component.type.value,
                "pins": list(component.pins),
                "parameters": {}
            }
            
            # Serialize parameters
            for param_name, param_value in component.parameters.items():
                comp_spec["parameters"][param_name] = param_value.to_dict()
            
            spec["components"].append(comp_spec)
        
        # Serialize nets
        for net_name, net in circuit.nets.items():
            pins = [
                f"{pin.component_id}.{pin.pin_name}"
                for pin in net.connected_pins
            ]
            spec["nets"].append({
                "id": net.name,
                "pins": pins
            })
        
        # Serialize ports
        for port_id, port in circuit.ports.items():
            spec["ports"].append({
                "id": port_id,
                "name": port.name,
                "net_id": port.net_name,
                "direction": port.direction.value if port.direction else "input"
            })
        
        return json.dumps(spec, indent=2)
