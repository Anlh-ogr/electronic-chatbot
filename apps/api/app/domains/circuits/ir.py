# .\thesis\electronic-chatbot\apps\api\app\domains\circuits\ir.py
""" Thông tin chung:
Đóng vai trò là lớp trung gian Circuit Intermediate Representation - IR và lớp serialization (CircuitIRSerializer).
Không phải Entity. Entity là sự thật trong code (truth in code), IR là sự thật cho lưu trữ/truyền tải (truth for storage/transmission).
Dùng để chuyển đổi, lưu trữ, truyền tải dữ liệu mạch điện tử giữa mà không chứa logic nghiệp vụ.
 * Sử dụng frozen = True đảm bảo tính bất biến tránh sửa đổi ngoài ý muốn.
 * Sử dụng thêm MappingProxyType để cung cấp dict bất biến cho các layer khác (read-only view).
 * Hỗ trợ metadata mở rộng cho Component: KiCad (library_id, symbol_name, footprint, symbol_version, render_style).
Phụ thuộc vào các đối tượng như Component, Net, Port, Constraint, Circuit, v.v.
"""


from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Dict, List, Any, Optional
from .entities import (
    ComponentType, Component, Net, Port, Constraint, Circuit, ParameterValue, PinRef, PortDirection
)

""" Lý do sử dụng thư viện
__future__ : do không thể sử dụng một class làm kiểu dữ liệu cho một biến trong chính class đó (class chưa khởi tạo xong), nên cần import từ "annotations" để hỗ trợ kiểu dữ liệu tham chiếu chéo (forward references).
dataclasses dataclass: gọi frozen = True để tạo bất biến (immutability) cho component, net, circuit. Ngăn chặn việc các layer khác sửa đổi trực tiếp các entity này, bảo vệ Source of Truth.
dataclasses field: tạo trường dữ liệu mạch định là một dict bất biến (immutable dict) để ngăn chặn việc sửa đổi trực tiếp từ bên ngoài.
mappingproxytype: frozen=True chỉ bảo vệ các biến đơn giản, có thể bị can thiệp do người. MappingProxy sẽ bọc Dict và biến nó thành read-only, mọi hành động sửa đổi đều bị báo lỗi ngay lập tức.
typing: cung cấp thông tin về kiểu dữ liệu cho các biến, hàm:
 * Dict[str, param value]: dùng key là str và value là object. VD: {"resistance": ParameterValue(1000, "Ohm")}.
 * List[str]: là danh sách chứa các chuỗi đối tượng.
 * Any: sử dụng các trường dữ liệu linh hoạt (giá trị ràng buộc), kiểu dữ liệu có thể tùy ý (int, float, str).
 * Optional[str]: biến có thể là str hoặc None. VD: {"unit": "Ohm"} hoặc {"unit": None}.
.entities: gọi các object liên quan để quản lý đối tượng, đúng cấu trúc dữ liệu, SoT cho lớp trung gian và hỗ trợ chuyển đổi object (dict ↔ entity).
"""


""" Mạch trung gian
Mạch ở dạng trung gian, là data, không có logic nghiệp vụ.
 * Gọi các object trong Circuit (name, id, component, net, port, constraint).
 * Lưu trữ ý định user (trạng thái mục tiêu, thông tin bổ sung, quay lui, v.v) dưới dạng dict.
 * Thông tin mô tả hệ thống (id, phiên bản, timestamp, revision, v.v) dưới dạng dict.
In/Out:
 * In:
    - circuit: Circuit entity (source of truth)
    - _intent_snapshot: Dict[str, Any]
    - _meta: Dict[str, Any]
 * Out:
    - trạng thái read-only : _intent_snapshot, _meta
Tạo bản sao bất biến và public read-only view để tránh bị sửa đổi từ bên ngoài.
"""
@dataclass (frozen=True)
class CircuitIR:
    circuit: Circuit
    _intent_snapshot: Dict[str, Any] = field(default_factory=dict)
    _meta: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        # Tạo bản sao bất biến
        object.__setattr__(self, "_intent_snapshot", dict(self._intent_snapshot))
        object.__setattr__(self, "_meta", dict(self._meta))
        # Tạo read-only view
        object.__setattr__(self, "intent_snapshot", MappingProxyType(self._intent_snapshot))
        object.__setattr__(self, "meta", MappingProxyType(self._meta))        


""" Bộ chuyển đổi Object ↔ Mạch trung gian (Circuit IR)
- Bộ đóng gói & truyền tải dữ liệu (ir <-> dict)
  * to_dict (ir)
  * from_dict (data)
- Xác thực cấu trúc dữ liệu (schema validation)
  * validate_schema (ir_dict)
- Bộ kết nối nghiệp vụ (domain mapping/assembler)
  * to_circuit (ir_dict)
  * build_ir (circuit)
- Kiểm thử (test helper)
  * serialize
  * deserialize
  * roundtrip_test  
"""
@dataclass(frozen=True)
class CircuitIRSerializer:
    """ Chuyển đổi một đối tượng CircuitIR thành dict (dạng JSON-serializable) để lưu trữ hoặc truyền tải.
        Input:
         - ir: CircuitIR (đối tượng trung gian chứa thông tin mạch điện, meta, intent, các thành phần mạch)
        Output:
         - dict: Dict[str, Any] với các trường: meta, intent_snapshot, components, nets, ports, constraints
           * meta: thông tin mô tả mạch (id, version, tên, ...)
           * intent_snapshot: trạng thái ý định của user (dict)
           * components: danh sách các linh kiện (mỗi linh kiện là dict)
           * nets: danh sách các lưới kết nối (mỗi lưới là dict)
           * ports: danh sách các cổng vào/ra (mỗi cổng là dict)
           * constraints: danh sách các ràng buộc (mỗi ràng buộc là dict)
        Hàm này sẽ gọi các hàm helper để chuyển từng thành phần sang dict.
    """
    @staticmethod
    def to_dict(ir: CircuitIR) -> Dict[str, Any]:
        circuit = ir.circuit
        result = {
            "meta": dict(ir.meta),
            "intent_snapshot": dict(ir.intent_snapshot),
            "components": [
                CircuitIRSerializer._components_to_dict(comp)
                for comp in circuit.components.values() 
            ],
            "nets": [
                CircuitIRSerializer._nets_to_dict(net)
                for net in circuit.nets.values()
            ],
            "ports": [
                CircuitIRSerializer._ports_to_dict(port)
                for port in circuit.ports.values()
            ],
            "constraints": [
                CircuitIRSerializer._constraints_to_dict(constraint)
                for constraint in circuit.constraints.values()
            ]
        }
        # Thêm template metadata nếu có
        if circuit.topology_type is not None:
            result["topology_type"] = circuit.topology_type
        if circuit.category is not None:
            result["category"] = circuit.category
        if circuit.template_id is not None:
            result["template_id"] = circuit.template_id
        if circuit.tags:
            result["tags"] = list(circuit.tags)
        if circuit.description is not None:
            result["description"] = circuit.description
        if circuit.parametric is not None:
            result["parametric"] = dict(circuit.parametric)
        if circuit.pcb_hints is not None:
            result["pcb_hints"] = dict(circuit.pcb_hints)
        return result
    
    # đưa thông tin linh kiện vào dict (bao gồm KiCad metadata nếu có)
    def _components_to_dict(comp: Component) -> Dict[str, Any]:
        result = {
            "id": comp.id,
            "type": comp.type.value,
            "pins": list(comp.pins),
            "parameters": {
                key: {"value": val.value, "unit": val.unit} 
                for key, val in comp.parameters.items()              
            }
        }
        # Thêm KiCad metadata nếu có
        if comp.library_id:
            result["library_id"] = comp.library_id
        if comp.symbol_name:
            result["symbol_name"] = comp.symbol_name
        if comp.footprint:
            result["footprint"] = comp.footprint
        if comp.symbol_version:
            result["symbol_version"] = comp.symbol_version
        if comp.render_style and len(comp.render_style) > 0:
            result["render_style"] = dict(comp.render_style)
        
        return result
    # đưa thông tin net vào dict
    def _nets_to_dict(net: Net) -> Dict[str, Any]:
        return {
            "name": net.name,
            "connected_pins": [{
                "component_id": ref.component_id,
                "pin_name": ref.pin_name
            } for ref in net.connected_pins ]
        }
    # đưa thông tin port vào dict
    def _ports_to_dict(port: Port) -> Dict[str, Any]:
        return {
            "name": port.name,
            "net_name": port.net_name,
            "direction": port.direction.value if port.direction else None
        }
    # đưa thông tin ràng buộc vào dict    
    def _constraints_to_dict(constraint: Constraint) -> Dict[str, Any]:
        result = {
            "name": constraint.name,
            "value": constraint.value,
            "unit": constraint.unit
        }
        # Thêm các trường tùy chọn nếu có
        if constraint.constraint_type is not None:
            result["constraint_type"] = constraint.constraint_type
        if constraint.target is not None:
            result["target"] = constraint.target
        if constraint.min_value is not None:
            result["min_value"] = constraint.min_value
        if constraint.max_value is not None:
            result["max_value"] = constraint.max_value
        return result


    """ Chuyển đổi một dict (dữ liệu IR đã được serialize) thành đối tượng CircuitIR.
        Input:
         - data: Dict[str, Any] (dữ liệu IR, gồm các trường: meta, intent_snapshot, components, nets, ports, constraints)
        Output:
         - CircuitIR: đối tượng trung gian chứa thông tin mạch, meta, intent, các thành phần mạch
        Quá trình:
         - Kiểm tra hợp lệ schema của dict đầu vào (nếu sai sẽ raise ValueError)
         - Chuyển dict thành các entity (Circuit, Component, Net, Port, Constraint)
         - Tạo đối tượng CircuitIR từ các entity và thông tin meta, intent
    """
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
    
    
    """ Kiểm tra schema của dict IR (dạng JSON/dict) và trả về danh sách lỗi nếu có.
    Hàm này sẽ gọi các hàm kiểm tra thành phần con để xác thực từng phần của IR:
     * meta
     * components
     * nets
     * ports
     * constraints
    Trả về: Danh sách lỗi (nếu không có lỗi, trả về list rỗng)
    """
    @staticmethod
    def validate_schema(ir_data: Dict[str, Any]) -> List[str]:
        errors: list[str] = []  # lưu trữ lỗi
        
        CircuitIRSerializer.__validate_required_sections(ir_data, errors)
        CircuitIRSerializer._validate_meta(ir_data.get("meta"), errors)
        CircuitIRSerializer._validate_components(ir_data.get("components"), errors)
        CircuitIRSerializer._validate_nets(ir_data.get("nets"), errors)
        CircuitIRSerializer._validate_ports(ir_data.get("ports"), errors)
        CircuitIRSerializer._validate_constraints(ir_data.get("constraints"), errors)
        return errors

    # Kiểm tra IR có đủ các phần bắt buộc không (meta, components, nets, ports, constraints). Nếu thiếu phần nào sẽ thêm lỗi vào errors.
    def __validate_required_sections(ir_data: dict[str, Any], errors: list[str]) -> None:
        required = {"meta", "components", "nets", "ports", "constraints"}
        missing = required - ir_data.keys()
        for section in missing:
            errors.append(f"IR thiếu phần bắt buộc: '{section}'")
    # kiểm tra trường meta: phải là dict, có đủ trường version, schema_version, circuit_name
    def _validate_meta(meta: Any, errors: list[str]) -> None:
        if not isinstance(meta, dict):
            errors.append("meta phải là dict")
            return
        for key in ("version", "schema_version", "circuit_name"):
            if key not in meta:
                errors.append(f"meta phải chứa '{key}'")
    # Kiểm tra trường components: phải là list, mỗi phần tử là dict có id, type (hợp lệ), pins (list), parameters (nếu có là dict)
    def _validate_components(components: Any, errors: list[str]) -> None:
        if not isinstance(components, list):
            errors.append("components phải là một danh sách")
            return
        # Kiểm tra từng component
        for i, comp in enumerate(components):
            if not isinstance(comp, dict):
                errors.append(f"component[{i}] phải là dict")
                continue
            # kiểm tra id
            if "id" not in comp:
                errors.append(f"component[{i}] thiếu 'id'")
            # kiểm tra type hợp lệ
            if "type" not in comp:
                errors.append(f"component[{i}] thiếu 'type'")
            else:
                try:
                    ComponentType(comp["type"])
                except ValueError:
                    errors.append(
                        f"component[{i}].type='{comp['type']}' không hợp lệ. "
                        f"Phải là một trong: {[e.value for e in ComponentType]}"
                    )
            # kiểm tra pins
            if "pins" not in comp:
                errors.append(f"component[{i}] thiếu 'pins'")
            elif not isinstance(comp["pins"], list):
                errors.append(f"component[{i}].pins phải là một danh sách")
            # kiểm tra parameters nếu có
            if "parameters" in comp and not isinstance(comp["parameters"], dict):
                errors.append(f"component[{i}].parameters phải là dict")
            
            # Kiểm tra KiCad metadata nếu có (optional)
            if "library_id" in comp and comp["library_id"] is not None and not isinstance(comp["library_id"], str):
                errors.append(f"component[{i}].library_id phải là str")
            if "symbol_name" in comp and comp["symbol_name"] is not None and not isinstance(comp["symbol_name"], str):
                errors.append(f"component[{i}].symbol_name phải là str")
            if "footprint" in comp and comp["footprint"] is not None and not isinstance(comp["footprint"], str):
                errors.append(f"component[{i}].footprint phải là str")
            if "symbol_version" in comp and comp["symbol_version"] is not None and not isinstance(comp["symbol_version"], str):
                errors.append(f"component[{i}].symbol_version phải là str")
            if "render_style" in comp and comp["render_style"] is not None and not isinstance(comp["render_style"], dict):
                errors.append(f"component[{i}].render_style phải là dict")
    # Kiểm tra trường nets: phải là list, mỗi phần tử là dict có name, connected_pins (list các dict có component_id, pin_name)
    def _validate_nets(nets: Any, errors: list[str]) -> None:
        if not isinstance(nets, list):
            errors.append("nets phải là một danh sách")
            return
        # Kiểm tra từng net
        for i, net in enumerate(nets):
            if not isinstance(net, dict):
                errors.append(f"net[{i}] phải là dict")
                continue
            # kiểm tra name
            if "name" not in net:
                errors.append(f"net[{i}] thiếu 'name'")
            # kiểm tra connected_pins(list)
            if "connected_pins" not in net:
                errors.append(f"net[{i}] thiếu 'connected_pins'")
                continue
            if not isinstance(net["connected_pins"], list):
                errors.append(f"net[{i}].connected_pins phải là danh sách")
                continue
            # kiểm tra từng connected_pin
            for j, conn in enumerate(net["connected_pins"]):
                if not isinstance(conn, dict):
                    errors.append(f"net[{i}].connected_pins[{j}] phải là dict")
                    continue
                if "component_id" not in conn:
                    errors.append(f"net[{i}].connected_pins[{j}] thiếu 'component_id'")
                if "pin_name" not in conn:
                    errors.append(f"net[{i}].connected_pins[{j}] thiếu 'pin_name'")
    # Kiểm tra trường ports: phải là list, mỗi phần tử là dict có name, net_name, direction (nếu có)
    def _validate_ports(ports: Any, errors: list[str]) -> None:
        if not isinstance(ports, list):
            errors.append("ports phải là một danh sách")
            return
        # Kiểm tra từng port
        for i, port in enumerate(ports):
            if not isinstance(port, dict):
                errors.append(f"port[{i}] phải là dict")
                continue
            # kiểm tra name và net_name
            if "name" not in port:
                errors.append(f"port[{i}] thiếu 'name'")
            if "net_name" not in port:
                errors.append(f"port[{i}] thiếu 'net_name'")
            # kiểm tra direction nếu có
            if "direction" in port and port["direction"] is not None:
                try:
                    PortDirection(port["direction"])
                except ValueError:
                    errors.append(f"port[{i}].direction='{port['direction']}' không hợp lệ. "
                                  f"Phải là một trong: {[e.value for e in PortDirection]}")
    # Kiểm tra trường constraints: phải là list, mỗi phần tử là dict có đủ trường name, value
    def _validate_constraints(constraints: Any, errors: list[str]) -> None:
        if not isinstance(constraints, list):
            errors.append("constraints phải là một danh sách")
        # Kiểm tra từng constraint
        for i, constraint in enumerate(constraints):
            if not isinstance(constraint, dict):
                errors.append(f"constraint[{i}] phải là dict")
                continue
            # kiểm tra name và value
            if "name" not in constraint:
                errors.append(f"constraint[{i}] thiếu 'name'")
            if "value" not in constraint:
                errors.append(f"constraint[{i}] thiếu 'value'")
    
    
   
    """ Chuyển đổi dict IR (dạng JSON/dict) thành entity Circuit.
        Input:
         - ir_data: Dict[str, Any] (dữ liệu IR, gồm các trường: meta, components, nets, ports, constraints)
        Output:
         - Circuit: đối tượng Circuit entity (dùng trong domain)
        Quá trình:
         - Kiểm tra schema đầu vào (nếu thiếu trường bắt buộc sẽ raise lỗi)
         - Dùng các helper để chuyển từng phần (components, nets, ports, constraints) thành dict các entity tương ứng
         - Tạo đối tượng Circuit từ các entity đã build và thông tin meta
    """
    @staticmethod
    def to_circuit(ir_data: Dict[str, Any]) -> Circuit:
        CircuitIRSerializer._validate_schema(ir_data)
        components = CircuitIRSerializer._build_components(ir_data["components"])
        nets = CircuitIRSerializer._build_nets(ir_data["nets"])
        ports = CircuitIRSerializer._build_ports(ir_data["ports"])
        constraints = CircuitIRSerializer._build_constraints(ir_data["constraints"])

        # Khôi phục template metadata từ ir_data nếu có
        tags_raw = ir_data.get("tags", [])
        tags = tuple(tags_raw) if isinstance(tags_raw, list) else ()

        return Circuit(
            name=ir_data["meta"].get("circuit_name", "unnamed"),
            id=ir_data["meta"].get("circuit_id"),
            _components=components,
            _nets=nets,
            _ports=ports,
            _constraints=constraints,
            topology_type=ir_data.get("topology_type"),
            category=ir_data.get("category"),
            template_id=ir_data.get("template_id"),
            tags=tags,
            description=ir_data.get("description"),
            parametric=ir_data.get("parametric"),
            pcb_hints=ir_data.get("pcb_hints"),
        )
        
    
    """ Tạo đối tượng CircuitIR từ entity Circuit.
    Chức năng:
     - Đóng gói entity Circuit cùng thông tin ý định (intent_snapshot) và meta (id, revision, version, timestamp, tên mạch) thành CircuitIR bất biến.
    Input:
     - circuit: Circuit (entity gốc, source of truth)
     - intent_snapshot: dict trạng thái ý định của user (tùy chọn)
     - circuit_id: mã định danh duy nhất cho mạch (tùy chọn, tự sinh nếu không có)
     - revision: số phiên bản/revision của mạch (mặc định 1)
    Output:
     - CircuitIR: đối tượng trung gian bất biến, chứa circuit, intent_snapshot, meta
    Quá trình:
     - Sinh circuit_id nếu chưa có
     - Tạo dict meta với các trường: circuit_id, revision, version, schema_version, created_at, circuit_name
     - Trả về CircuitIR với các trường đã đóng gói
    """
    @staticmethod
    def build_ir(
        circuit: Circuit,
        intent_snapshot: Optional[Dict[str, Any]] = None,
        circuit_id: Optional[str] = None,
        revision: int = 1,
    ) -> CircuitIR:
        
        # Tạo circuit_id nếu không có (s-ms sinh 1000 lần/s)
        if circuit_id is None:
            circuit_id = circuit.id or f"circuit-{int(datetime.utcnow().timestamp()*1000)}"
        
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

    # kiểm tra tất cả phần bắt buộc cùng lúc
    def _validate_schema(ir_data: Dict[str, Any]) -> List[str]:
        required = {"meta", "components", "nets", "ports", "constraints"}
        missing = required - ir_data.keys()
        if missing:
            raise ValueError(f"IR thiếu phần bắt buộc: {', '.join(missing)}")
    # xây dựng các linh kiện từ dict      
    def _build_components(comp_data: list[dict]) -> dict[str, Component]:
        components = {} # lưu trữ linh kiện
        for data in comp_data:
            comp = Component(
                id=data["id"],
                type=ComponentType(data["type"]),
                pins=tuple(data["pins"]),
                parameters={
                    key: ParameterValue(value=val["value"], unit=val.get("unit"))
                    for key, val in data.get("parameters", {}).items()
                },
                # KiCad metadata (optional)
                library_id=data.get("library_id"),
                symbol_name=data.get("symbol_name"),
                footprint=data.get("footprint"),
                symbol_version=data.get("symbol_version"),
                render_style=data.get("render_style", {})
            )
            components[comp.id] = comp
        return components
    # xây dựng các kết nối từ dict
    def _build_nets(net_data: list[dict]) -> dict[str, Net]:
        nets = {}   # lưu trữ lưới kết nối
        for data in net_data:
            net = Net(
                name=data["name"],
                connected_pins=tuple(
                    PinRef(
                        component_id=conect["component_id"],
                        pin_name=conect["pin_name"]
                    )
                    for conect in data["connected_pins"]
                )
            )
            nets[net.name] = net
        return nets
    # xây dựng các port từ dict
    def _build_ports(port_data: list[dict]) -> dict[str, Port]:
        ports = {}
        for data in port_data:
            direction = data.get("direction")
            port = Port(
                name=data["name"],
                net_name=data["net_name"],
                direction=PortDirection(direction) if direction else None
            )
            ports[port.name] = port
        return ports
    # xây dựng các ràng buộc từ dict
    def _build_constraints(constraint_data: list[dict]) -> dict[str, Constraint]:
        constraints = {}    # lưu trữ ràng buộc
        for data in constraint_data:
            constraint = Constraint(
                name=data["name"],
                value=data["value"],
                unit=data.get("unit"),
                constraint_type=data.get("constraint_type"),
                target=data.get("target"),
                min_value=data.get("min_value"),
                max_value=data.get("max_value"),
            )
            constraints[constraint.name] = constraint
        return constraints
    
    
    """ Chuyển entity Circuit thành dict (dạng JSON-serializable) với lớp bọc trung gian IR.
    Chức năng:
     - Đóng gói entity Circuit thành CircuitIR, sau đó chuyển thành dict để lưu trữ hoặc truyền tải (có thể dùng cho JSON).
    Input:
     - circuit: Circuit (entity gốc, source of truth)
    Output:
     - dict: Dict[str, Any] với các trường: meta, intent_snapshot, components, nets, ports, constraints
    Quá trình:
     - Tạo CircuitIR từ entity Circuit (gọi build_ir)
     - Chuyển CircuitIR thành dict (gọi to_dict)
     - Trả về dict kết quả
    """
    @staticmethod
    def serialize(circuit: Circuit) -> Dict[str, Any]:
        ir = CircuitIRSerializer.build_ir(circuit)
        return CircuitIRSerializer.to_dict(ir)
    
    
    """ Chuyển đổi dict IR (dạng JSON/dict) thành entity Circuit.
    Chức năng:
     - Phục hồi lại đối tượng Circuit từ dict IR đã serialize (thường dùng cho test hoặc import/export).
    Input:
     - ir_data: dict (dạng {meta, components, nets, ports, constraints})
    Output:
     - Circuit: entity domain Circuit
    Quá trình:
     - Kiểm tra schema dict đầu vào (nếu sai raise lỗi)
     - Giải mã từng phần: components, nets, ports, constraints từ dict sang entity tương ứng
     - Lắp ráp các phần thành Circuit và trả về
    """
    @staticmethod
    def deserialize(ir_data: Dict[str, Any]) -> Circuit:
        CircuitIRSerializer._validate_schema(ir_data)
        
        components = CircuitIRSerializer._deserialize_component(ir_data["components"])
        nets = CircuitIRSerializer._deserialize_net(ir_data["nets"])
        ports = CircuitIRSerializer._deserialize_port(ir_data["ports"])
        constraints = CircuitIRSerializer._deserialize_constraint(ir_data["constraints"])
        
        return CircuitIRSerializer._assemble_circuit(
            meta=ir_data["meta"],
            components=components,
            nets=nets,
            ports=ports,
            constraints=constraints,
            ir_data=ir_data,
        )
        
    # giải mã component từ dict
    def _deserialize_component(data: list[dict]) -> dict[str, Component]:
        components = {}
        for comp_data in data:
            comp = Component(
                id=comp_data["id"],
                type=ComponentType(comp_data["type"]),
                pins=tuple(comp_data["pins"]),
                parameters={
                    key: ParameterValue(value=val["value"], unit=val.get("unit"))
                    for key, val in comp_data.get("parameters", {}).items()
                },
                # KiCad metadata (optional)
                library_id=comp_data.get("library_id"),
                symbol_name=comp_data.get("symbol_name"),
                footprint=comp_data.get("footprint"),
                symbol_version=comp_data.get("symbol_version"),
                render_style=comp_data.get("render_style", {})
            )
            components[comp.id] = comp
        return components
    # giải mã net từ dict
    def _deserialize_net(data: list[dict]) -> dict[str, Net]:
        nets = {}
        for net_data in data:
            net = Net(
                name=net_data["name"],
                connected_pins=tuple(
                    PinRef(
                        component_id=pin["component_id"],
                        pin_name=pin["pin_name"]
                    )
                    for pin in net_data["connected_pins"]
                )
            )
            nets[net.name] = net
        return nets
    # giải mã port từ dict
    def _deserialize_port(data: list[dict]) -> dict[str, Port]:
        ports = {}
        for port_data in data:
            direction = port_data.get("direction")
            port = Port(
                name=port_data["name"],
                net_name=port_data["net_name"],
                direction=PortDirection(direction) if direction else None
            )
            ports[port.name] = port
        return ports
    # giải mã constraint từ dict
    def _deserialize_constraint(data: list[dict]) -> dict[str, Constraint]:
        constraints = {}
        for const_data in data:
            constraint = Constraint(
                name=const_data["name"],
                value=const_data["value"],
                unit=const_data.get("unit"),
                constraint_type=const_data.get("constraint_type"),
                target=const_data.get("target"),
                min_value=const_data.get("min_value"),
                max_value=const_data.get("max_value"),
            )
            constraints[constraint.name] = constraint
        return constraints
    # lắp ráp Circuit từ các phần đã giải mã
    def _assemble_circuit(
        meta: dict,
        components: dict,
        nets: dict,
        ports: dict,
        constraints: dict,
        ir_data: Optional[dict] = None,
    ) -> Circuit:
        # Khôi phục template metadata từ ir_data nếu có
        extra = {}
        if ir_data:
            tags_raw = ir_data.get("tags", [])
            extra = {
                "topology_type": ir_data.get("topology_type"),
                "category": ir_data.get("category"),
                "template_id": ir_data.get("template_id"),
                "tags": tuple(tags_raw) if isinstance(tags_raw, list) else (),
                "description": ir_data.get("description"),
                "parametric": ir_data.get("parametric"),
                "pcb_hints": ir_data.get("pcb_hints"),
            }
    
        return Circuit(
            name=meta.get("circuit_name", "unnamed"),
            id=meta.get("circuit_id"),
            _components=components,
            _nets=nets,
            _ports=ports,
            _constraints=constraints,
            **extra,
        )
    
    
    
    """ Test helper kiểm tra tính toàn vẹn serialization/deserialization.
    Chức năng:
     - Kiểm tra quá trình chuyển đổi Circuit → IR dict → Circuit → IR dict có giữ nguyên dữ liệu không (ngoại trừ trường timestamp).
    Input:
     - circuit: Circuit (entity gốc)
    Output:
     - bool: True nếu dữ liệu không thay đổi qua các bước chuyển đổi, False nếu có sai lệch hoặc lỗi.
    Quá trình:
     - Chuyển Circuit thành IR (build_ir), rồi thành dict (to_dict)
     - Chuyển dict thành IR (from_dict), rồi lại thành dict (to_dict)
     - So sánh hai dict kết quả (bỏ qua trường created_at trong meta)
     - Trả về True nếu giống nhau, False nếu khác hoặc có lỗi
    """
    @staticmethod
    def roundtrip_test(circuit: Circuit) -> bool:
        try:
            # Circuit → IR → dict (lần 1)
            ir1 = CircuitIRSerializer.build_ir(circuit)
            dict1 = CircuitIRSerializer.to_dict(ir1)
            # dict → IR (lần 2)
            ir2 = CircuitIRSerializer.from_dict(dict1)
            # IR → dict (lần 2)
            dict2 = CircuitIRSerializer.to_dict(ir2)
            
            # So sánh hai dict, bỏ qua trường created_at trong meta
            dict1_copy = dict(dict1)
            dict2_copy = dict(dict2)
            # loại bỏ created_at để so sánh
            dict1_copy["meta"] = dict(dict1_copy.get("meta", {})) # gán lại bản sao
            dict2_copy["meta"] = dict(dict2_copy.get("meta", {}))
            dict1_copy["meta"].pop("created_at", None)
            dict2_copy["meta"].pop("created_at", None)
            
            return dict1_copy == dict2_copy
        
        except Exception as e:
            print(f"Lỗi trong roundtrip_test: {e}")
            return False