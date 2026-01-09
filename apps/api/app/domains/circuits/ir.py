# thesis/electronic-chatbot/apps/api/app/domains/circuits/ir.py
"""
    Circuit Intermediate Representation - Serialization layer
    IR ≠ Entity. Entity = truth in code, IR = truth for storage/transmission.
"""
from __future__ import annotations

# Giải thích thư viện
# annotations: cho phép sử dụng kiểu dữ liệu chưa được định nghĩa trong cùng module nhằm hỗ trợ kiểu dữ liệu đệ quy và tham chiếu chéo.
# typing: cung cấp các kiểu dữ liệu tổng quát như Dict, List, Optional, Tuple, Set, Any để định nghĩa kiểu dữ liệu phức tạp hơn.
# mappingproxytype: để tạo các dict bất biến, cần thiết trong trường hợp là source of truth.
# json: để xử lý dữ liệu JSON nếu cần thiết trong tương lai.
# dataclass: Sử dụng frozen để ngăn chặn việc các layer khác sửa CircuitCircuit. Hạn chế việc Source of Truth bị Phá
# datetime: để ghi lại thời gian tạo IR.
# .entities: nhập các lớp Entity như ComponentType, Component, Net, Port, Constraint
from typing import Dict, List, Any, Optional
from types import MappingProxyType
import json
from dataclasses import dataclass, field
from datetime import datetime
from .entities import (
    ComponentType, Component, Net, Port, Constraint, Circuit, ParameterValue, PinRef, PortDirection
)


@dataclass (frozen=True)
class CircuitIR:
    """CircuitIR chỉ là data, không logic"""
    circuit: Circuit
    _intent_snapshot: Dict[str, Any] = field(default_factory=dict)
    _meta: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        # Bản sao bất biến để tránh bị sửa đổi từ bên ngoài
        object.__setattr__(self, "_intent_snapshot", dict(self._intent_snapshot))
        object.__setattr__(self, "_meta", dict(self._meta))
        # Public chế độ read-only
        object.__setattr__(self, "intent_snapshot", MappingProxyType(self._intent_snapshot))
        object.__setattr__(self, "meta", MappingProxyType(self._meta))        
    
    
@dataclass(frozen=True)
class CircuitIRSerializer:
    """
        Chuyển đổi giữa Circuit Entity và Circuit IR (dạng dict JSON)
        Cũng bao gồm xác thực lược đồ IR cơ bản
    """
    
    @staticmethod
    def to_dict(ir: CircuitIR) -> Dict[str, Any]:
        circuit = ir.circuit
        return {
            "meta": ir.meta,
            "intent_snapshot": ir.intent_snapshot,
            "components": [
                {
                    "id": comp.id,
                    "type": comp.type.value,
                    "pins": list(comp.pins),
                    
                    """ 
                        ParameterValue là entity object
                        JSON serializer không hiểu
                        DB layer / frontend sẽ chết
                    """
                    "parameters": {
                        key: {"value": val.value, "unit": val.unit} 
                        for key, val in comp.parameters.items()              
                    }
                }
                for comp in circuit.components.values() 
            ],
            "nets": [
                {
                    "name": net.name,
                    
                    # net.connected_pins là PinRef, không phải tuple
                    "connected_pins": [
                        {
                            "component_id": ref.component_id, 
                            "pin": ref.pin_name
                        }
                        for ref in net.connected_pins
                    ]
                }
                for net in circuit.nets.values()
            ],
            "ports": [
                {
                    "name": port.name,
                    "net_name": port.net_name,
                    "direction": port.direction.value if port.direction else None
                }
                for port in circuit.ports.values()
            ],
            "constraints": [
                {
                    "name": constraint.name,
                    "value": constraint.value,
                    "unit": constraint.unit
                }
                for constraint in circuit.constraints.values()
            ]
        }
        
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> CircuitIR:
        errors = CircuitIRSerializer.validate_schema(data)
        if errors:
            raise ValueError(f"IR schema không hợp lệ: {errors}")
        
        return CircuitIR(
            circuit=CircuitIRSerializer.to_circuit(data),
            _intent_snapshot=data.get("intent_snapshot", {}),
            _meta=data["meta"]
        )
    

    @staticmethod
    def to_circuit(ir_data: Dict[str, Any]) -> Circuit:
        """Chuyển đổi IR JSON → Entity"""
        # Validate schema shape (không validate logic điện)
        required_sections = ["meta", "components", "nets", "ports", "constraints"]
        for section in required_sections:
            if section not in ir_data:
                raise ValueError(f"IR thiếu phần bắt buộc: {section}")
        
        # Xây dựng lại components
        components = {}
        for comp_data in ir_data["components"]:
            component = Component(
                id=comp_data["id"],
                type=ComponentType(comp_data["type"]),
                pins=tuple(comp_data["pins"]),
                
                # Giống lỗi như to_dict"""
                parameters={
                    key: ParameterValue(value=val["value"], unit=val.get("unit"))
                    for key, val in comp_data.get("parameters", {}).items()
                }
            )
            components[component.id] = component
        
        # Xây dựng lại nets. Trong entities là tuple
        nets = {}
        for net_data in ir_data["nets"]:
            net = Net(
                name=net_data["name"],
                connected_pins=tuple(
                    PinRef(
                        component_id=conn["component_id"],
                        pin_name=conn["pin"]
                    )
                    for conn in net_data["connected_pins"]
                )
            )
            nets[net.name] = net
        
        # Xây dựng lại ports
        ports = {}
        for port_data in ir_data["ports"]:
            direction = port_data.get("direction")
            port = Port(
                name=port_data["name"],
                net_name=port_data["net_name"],
                direction=PortDirection(direction) if direction else None
            )
            ports[port.name] = port
        
        # Xây dựng lại constraints
        constraints = {}
        for constraint_data in ir_data["constraints"]:
            constraint = Constraint(
                name=constraint_data["name"],
                value=constraint_data["value"],
                unit=constraint_data.get("unit")
            )
            constraints[constraint.name] = constraint
        
        # Tạo Circuit
        circuit = Circuit(
            name=ir_data["meta"].get("circuit_name", "unnamed"),
            _components=components,
            _nets=nets,
            _ports=ports,
            _constraints=constraints
        )
        
        return circuit
    
    @staticmethod
    def validate_schema(ir_data: Dict[str, Any]) -> List[str]:
        """Xác thực hình dạng lược đồ IR - không validate logic điện"""
        errors = []
        
        # Kiểm tra các phần bắt buộc
        required_sections = ["meta", "components", "nets", "ports", "constraints"]
        for section in required_sections:
            if section not in ir_data:
                errors.append(f"IR thiếu phần bắt buộc: '{section}'")
        
        # Kiểm chứng meta
        if "meta" in ir_data:
            meta = ir_data["meta"]
            if "version" not in meta:
                errors.append("meta phải chứa 'version'")
            if "schema_version" not in meta:
                errors.append("meta phải chứa 'schema_version'")
            if "circuit_name" not in meta:
                errors.append("meta phải chứa 'circuit_name'")
        
        # Kiểm chứng cấu trúc linh kiện + enum
        if "components" in ir_data:
            if not isinstance(ir_data["components"], list):
                errors.append("components phải là một danh sách")
            else:
                for i, comp in enumerate(ir_data["components"]):
                    if "id" not in comp:
                        errors.append(f"component[{i}] thiếu 'id'")
                    if "type" not in comp:
                        errors.append(f"component[{i}] thiếu 'type'")
                    else:
                        # Kiểm chứng enum ComponentType
                        try:
                            ComponentType(comp["type"])
                        except ValueError:
                            errors.append(f"component[{i}].type='{comp['type']}' không hợp lệ. "
                                          f"Phải là một trong: {[e.value for e in ComponentType]}")
                    if "pins" not in comp:
                        errors.append(f"component[{i}] thiếu 'pins'")
                    elif not isinstance(comp["pins"], list):
                        errors.append(f"component[{i}].pins phải là một danh sách")
                    if "parameters" in comp and not isinstance(comp["parameters"], dict):
                        errors.append(f"component[{i}].parameters phải là dict")
        
        # Kiểm chứng cấu trúc nets
        if "nets" in ir_data:
            if not isinstance(ir_data["nets"], list):
                errors.append("nets phải là một danh sách")
            else:
                for i, net in enumerate(ir_data["nets"]):
                    if "name" not in net:
                        errors.append(f"net[{i}] thiếu 'name'")
                    if "connected_pins" not in net:
                        errors.append(f"net[{i}] thiếu 'connected_pins'")
                        continue
                    if not isinstance(net["connected_pins"], list):
                        errors.append(f"net[{i}].connected_pins phải là danh sách")
                        continue
                    for j, conn in enumerate(net["connected_pins"]):
                        if not isinstance(conn, dict):
                            errors.append(f"net[{i}].connected_pins[{j}] phải là dict")
                            continue
                        if "component_id" not in conn:
                            errors.append(f"net[{i}].connected_pins[{j}] thiếu 'component_id'")
                        if "pin" not in conn:
                            errors.append(f"net[{i}].connected_pins[{j}] thiếu 'pin'")
        
        # Kiểm chứng cấu trúc ports
        if "ports" in ir_data:
            if not isinstance(ir_data["ports"], list):
                errors.append("ports phải là một danh sách")
            else:
                for i, port in enumerate(ir_data["ports"]):
                    if not isinstance(port, dict):
                        errors.append(f"port[{i}] phải là dict")
                        continue
                    if "name" not in port:
                        errors.append(f"port[{i}] thiếu 'name'")
                    if "net_name" not in port:
                        errors.append(f"port[{i}] thiếu 'net_name'")
                    # Kiểm chứng enum PortDirection (nếu có)
                    if "direction" in port and port["direction"] is not None:
                        try:
                            PortDirection(port["direction"])
                        except ValueError:
                            errors.append(f"port[{i}].direction='{port['direction']}' không hợp lệ. "
                                          f"Phải là một trong: {[e.value for e in PortDirection]}")
        
        # Kiểm chứng cấu trúc constraints
        if "constraints" in ir_data:
            if not isinstance (ir_data["constraints"], list):
                errors.append("constraints phải là một danh sách")
            else:
                for i, constraint in enumerate(ir_data["constraints"]):
                    if not isinstance(constraint, dict):
                        errors.append(f"constraint[{i}] phải là dict")
                        continue
                    if "name" not in constraint:
                        errors.append(f"constraint[{i}] thiếu 'name'")
                    if "value" not in constraint:
                        errors.append(f"constraint[{i}] thiếu 'value'")
        
        return errors
    
    @staticmethod
    def serialize(ir_data: Dict[str, Any]) -> str:
        """Serialize IR to chuỗi JSON"""
        return json.dumps(ir_data, indent=2)
    
    @staticmethod
    def deserialize(json_str: str) -> Dict[str, Any]:
        """Deserialize chuỗi JSON thành IR"""
        return json.loads(json_str)
    
    @staticmethod
    def build_ir(
        circuit: Circuit,
        intent_snapshot: Optional[Dict[str, Any]] = None,
        circuit_id: Optional[str] = None,
        revision: int = 1,
    ) -> CircuitIR:
        """
        Tạo CircuitIR từ Circuit entity.
        
        Args:
            circuit: Circuit entity (source of truth)
            intent_snapshot: Snapshot của user intent đã parse
            circuit_id: ID duy nhất của mạch (để track trong DB/session)
            revision: Số revision (tăng dần khi mạch thay đổi)
        """
        # Tạo circuit_id nếu không có (s-ms sinh 1000 lần/s)
        if circuit_id is None:
            circuit_id = f"circuit-{int(datetime.utcnow().timestamp()*1000)}"
        
        return CircuitIR(
            circuit=circuit,
            _intent_snapshot=intent_snapshot or {},
            _meta={
                "circuit_id": circuit_id,
                "revision": revision,
                "version": "1.0",
                "schema_version": "1.0",
                "created_at": datetime.utcnow().isoformat() + "Z", # utc 0
                "circuit_name": circuit.name
            }
        )
    
    # Test serialization
    @staticmethod
    def roundtrip_test(circuit: Circuit) -> bool:
        """
        Test helper: Circuit → IR dict → Circuit → IR dict
        Đảm bảo không mất dữ liệu qua serialization.
        
        Returns:
            True nếu round-trip thành công
        """
        try:
            # Circuit → IR → dict
            ir1 = CircuitIRSerializer.build_ir(circuit)
            dict1 = CircuitIRSerializer.to_dict(ir1)
            
            # dict → IR → Circuit
            ir2 = CircuitIRSerializer.from_dict(dict1)
            
            # Circuit → IR → dict (lần 2)
            dict2 = CircuitIRSerializer.to_dict(ir2)
            
            # So sánh dict1 và dict2 (bỏ qua timestamp)
            dict1_copy = dict(dict1)
            dict2_copy = dict(dict2)
            dict1_copy["meta"].pop("created_at", None)
            dict2_copy["meta"].pop("created_at", None)
            
            return dict1_copy == dict2_copy
        except Exception as e:
            print(f"Round-trip failed: {e}")
            return False
