# .\\thesis\\electronic-chatbot\\apps\\api\\app\\infrastructure\\exporters\\kicad_sch_serializer.py
"""Công cụ tuần tự hóa sơ đồ mạch KiCad (s-expression format).

Module này chuyển đổi Circuit entities + layout information thành
KiCad .kicad_sch s-expression format. Nó xử lý lib_symbols, symbol instances,
wires, labels, nets để tạo schematic đầy đủ theo KiCad 8+ standard.

Chức năng:
- Trách nhiệm: Chuyển đổi Circuit → KiCad schematic s-expression
- Đầu ra: lib_symbols, (symbol ...), (wire ...), (label ...) blocks
- Tiêu chuẩn: KiCad 8 / KiCanvas compatibility
"""

from __future__ import annotations

# ====== Lý do sử dụng thư viện ======
# typing: Type hints cho s-expression generation
# datetime: Timestamps cho schematic metadata
from typing import Dict, Tuple
from datetime import datetime

# ====== Domain & Infrastructure layers ======
from app.domains.circuits.entities import Circuit
from app.domains.circuits.ir import CircuitIR
from app.infrastructure.exporters.kicad_symbol_library import KiCadSymbolLibrary


# ====== Schematic Serializer ======
class KiCadSchSerializer:
    """Tuần tự hóa sơ đồ mạch thành KiCad .kicad_sch s-expression format.
    
    Class này chuyển đổi Circuit entities + layout info (positions, connections)
    thành s-expression text format đúng với tiêu chuẩn KiCad 8.
    
    Responsibilities (Trách nhiệm):
    - Chuyển đổi Circuit + layout → KiCad s-expression
    - Tạo lib_symbols blocks cho components
    - Tạo symbol instances, wires, labels
    - Đảm bảo tương thích KiCad 8 / KiCanvas
    """
    
    # ====== KiCad Format Configuration ======
    KICAD_VERSION = "20231120"
    GENERATOR_VERSION = "8.0"
    
    def __init__(self):
        """Initialize serializer."""
        self._root_uuid: str = ""
    
    def serialize(
        self,
        ir: CircuitIR,
        placements: Dict[str, Tuple[float, float]],
        wires: list,
        junctions: set,
        rotations: Dict[str, int] | None = None,
    ) -> str:
        """Serialize CircuitIR with layout to KiCad format.
        
        Args:
            ir: Circuit intermediate representation
            placements: Component positions (comp_id -> (x, y))
            wires: Wire routing information
            junctions: Junction points for wire connections
            
        Returns:
            KiCad .kicad_sch file content as string
        """
        circuit = ir.circuit
        
        # Generate root UUID
        self._root_uuid = self._generate_uuid()
        
        lines = []
        
        # Header
        lines.extend(self._build_header(circuit))
        lines.append("")
        
        # Library symbols
        lines.extend(self._build_lib_symbols(circuit))
        lines.append("")
        
        # Component instances
        for comp_id, component in circuit.components.items():
            pos = placements.get(comp_id, (50.0, 50.0))
            rot = 0 if rotations is None else int(rotations.get(comp_id, 0))
            symbol_lines = self._build_symbol_instance(
                comp_id, component, pos[0], pos[1], rot
            )
            lines.extend(symbol_lines)
            lines.append("")
        
        # Wires
        for wire_data in wires:
            lines.extend(self._build_wire(wire_data))
        
        # Junctions
        for jx, jy in junctions:
            lines.extend(self._build_junction(jx, jy))
        
        # Global labels for ports
        x_label, y_label = 20, 50
        for idx, port in enumerate(circuit.ports.values()):
            label_lines = self._build_global_label(
                port, x_label, y_label + idx * 10
            )
            lines.extend(label_lines)
            lines.append("")
        
        # Footer
        lines.extend(self._build_footer())
        
        return "\n".join(lines)
    
    def _build_header(self, circuit: Circuit) -> list[str]:
        """Build KiCad schematic header.
        
        Args:
            circuit: Circuit entity
            
        Returns:
            List of header lines
        """
        circuit_name = circuit.name or "Unnamed Circuit"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        lines = [
            '(kicad_sch',
            f'  (version {self.KICAD_VERSION})',
            f'  (generator "electronic-chatbot")',
            f'  (generator_version "{self.GENERATOR_VERSION}")',
            f'  (uuid "{self._root_uuid}")',
            '  (paper "A4")',
            '',
            '  (title_block',
            f'    (title "{circuit_name}")',
            f'    (comment 3 "Generated: {timestamp}")',
            '  )',
        ]
        
        return lines
    
    def _build_lib_symbols(self, circuit: Circuit) -> list[str]:
        """Build lib_symbols block with minimal symbol definitions.
        
        Args:
            circuit: Circuit entity
            
        Returns:
            List of lib_symbols lines
        """
        lines = ['  (lib_symbols']

        # Resolve symbol per component ID so VCC/VDD voltage sources can use VCC symbol.
        used_symbols: Dict[str, tuple[str, Dict]] = {}
        for comp_id, component in circuit.components.items():
            comp_type = component.type.value
            symbol_def = KiCadSymbolLibrary.get_symbol_def(comp_type, comp_id, len(component.pins))
            lib_id = symbol_def['lib_id']
            if lib_id not in used_symbols:
                used_symbols[lib_id] = (comp_type, symbol_def)

        for lib_id in sorted(used_symbols.keys()):
            comp_type, symbol_def = used_symbols[lib_id]
            lib_id = symbol_def['lib_id']
            ref_prefix = symbol_def['ref_prefix']
            pin_defs = symbol_def['pins']
            graphics_lines = symbol_def['graphics']
            
            # Extract symbol name (e.g., "Device:R" -> "R")
            symbol_name = lib_id.split(':')[-1]
            
            if symbol_def.get('is_power'):
                lines.append(f'    (symbol "{lib_id}" (power)')
            else:
                lines.append(f'    (symbol "{lib_id}"')
            lines.append('      (pin_numbers hide)')
            lines.append('      (pin_names (offset 0))')
            lines.append('      (exclude_from_sim no) (in_bom yes) (on_board yes)')
            lines.append(f'      (property "Reference" "{ref_prefix}" (at 0 2.54 0) (effects (font (size 1.27 1.27))))')
            lines.append(f'      (property "Value" "{comp_type}" (at 0 -2.54 0) (effects (font (size 1.27 1.27))))')
            lines.append('      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))')
            lines.append('      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))')
            lines.append(f'      (property "Description" "{comp_type}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))')
            lines.append(f'      (property "ki_keywords" "{comp_type}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))')
            lines.append(f'      (property "ki_fp_filters" "*" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))')
            
            # Symbol body graphics - USE REAL POLYLINES/CIRCLES FROM LIBRARY
            lines.append(f'      (symbol "{symbol_name}_0_1"')
            lines.extend(graphics_lines)  # Add detailed graphics!
            lines.append('      )')
            
            # Symbol pins
            pin_type = symbol_def.get('pin_type', 'passive')
            pin_length = symbol_def.get('pin_length', 2.0)
            lines.append(f'      (symbol "{symbol_name}_1_1"')
            for idx, (px, py, orientation) in enumerate(pin_defs):
                lines.append(
                    f'        (pin {pin_type} line (at {px} {py} {orientation}) '
                    f'(length {pin_length}) (name "~" (effects (font (size 1.27 1.27)))) '
                    f'(number "{idx + 1}" (effects (font (size 1.27 1.27)))))'
                )
            lines.append('      )')
            lines.append('    )')
        
        lines.append('  )')
        
        return lines
    
    def _build_symbol_instance(
        self,
        comp_id: str,
        component,
        x: float,
        y: float,
        rotation: int = 0,
    ) -> list[str]:
        """Build symbol instance s-expression.
        
        Args:
            comp_id: Component identifier
            component: Component entity
            x, y: Position coordinates
            
        Returns:
            List of symbol instance lines
        """
        symbol_def = KiCadSymbolLibrary.get_symbol_def(component.type.value, comp_id, len(component.pins))
        lib_id = symbol_def['lib_id']
        ref = component.id
        value = self._get_component_value(component)
        uuid = self._generate_uuid()
        
        lines = [
            f'  (symbol (lib_id "{lib_id}")',
            f'    (at {x} {y} {rotation})',
            '    (unit 1) (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)',
            '    (fields_autoplaced yes)',
            f'    (uuid "{uuid}")',
            f'    (property "Reference" "{ref}" (at {x+2.0} {y+1.7} 0)',
            '      (effects (font (size 1.27 1.27)))',
            '    )',
            f'    (property "Value" "{value}" (at {x+2.0} {y-1.7} 0)',
            '      (effects (font (size 1.27 1.27)))',
            '    )',
            f'    (property "Footprint" "" (at {x} {y} 0)',
            '      (effects (font (size 1.27 1.27)) (hide yes))',
            '    )',
            f'    (property "Datasheet" "" (at {x} {y} 0)',
            '      (effects (font (size 1.27 1.27)) (hide yes))',
            '    )',
            f'    (property "Description" "{component.type.value}" (at {x} {y} 0)',
            '      (effects (font (size 1.27 1.27)) (hide yes))',
            '    )',
        ]
        
        # Pin UUIDs
        for pin_idx in range(len(component.pins)):
            lines.append(f'    (pin "{pin_idx + 1}" (uuid "{self._generate_uuid()}"))')
        
        # Instances block
        instance_path = f'"/{self._root_uuid}"'
        lines.append('    (instances')
        lines.append(f'      (project "" (path {instance_path} (reference "{ref}") (unit 1)))')
        lines.append('    )')
        lines.append('  )')
        
        return lines
    
    def _build_wire(self, wire_data: dict) -> list[str]:
        """Build wire s-expression.
        
        Args:
            wire_data: Dictionary with 'points' key containing list of (x, y) tuples
            
        Returns:
            List of wire lines
        """
        points = wire_data.get('points', [])
        if len(points) < 2:
            return []
        
        lines = []
        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i+1]
            lines.extend([
                '  (wire',
                f'    (pts (xy {x1} {y1}) (xy {x2} {y2}))',
                '    (stroke (width 0) (type default))',
                f'    (uuid "{self._generate_uuid()}")',
                '  )'
            ])
        
        return lines
    
    def _build_junction(self, x: float, y: float) -> list[str]:
        """Build junction s-expression.
        
        Args:
            x, y: Junction coordinates
            
        Returns:
            List of junction lines
        """
        lines = [
            '  (junction',
            # KiCad junction uses 2D coordinates only: (at x y)
            f'    (at {x} {y})',
            '    (diameter 0) (color 0 0 0 0)',
            f'    (uuid "{self._generate_uuid()}")',
            '  )',
        ]
        
        return lines
    
    def _build_global_label(self, port, x: float, y: float) -> list[str]:
        """Build global label s-expression.
        
        Args:
            port: Port entity
            x, y: Label position
            
        Returns:
            List of label lines
        """
        shape = "input" if port.direction and port.direction.value == "input" else "output"
        
        lines = [
            f'  (global_label "{port.name}" (shape {shape}) (at {x} {y} 0)',
            '    (fields_autoplaced yes)',
            '    (effects (font (size 1.27 1.27)))',
            f'    (uuid "{self._generate_uuid()}")',
            f'    (property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at {x} {y} 0)',
            '      (effects (font (size 1.27 1.27)) (hide yes))',
            '    )',
            '  )',
        ]
        
        return lines
    
    def _build_footer(self) -> list[str]:
        """Build KiCad schematic footer.
        
        Returns:
            List of footer lines
        """
        lines = [
            '  (sheet_instances',
            '    (path "/" (page "1"))',
            '  )',
            ')',
        ]
        
        return lines
    
    def _get_component_value(self, component) -> str:
        """Extract component value from parameters.
        
        Args:
            component: Component entity
            
        Returns:
            Value string with unit
        """
        # Try to get value from parameters
        if "value" in component.parameters:
            param = component.parameters["value"]
            unit = param.unit or ""
            return f"{param.value}{unit}"
        
        # Component-specific parameters
        param_map = {
            "resistance": "Ω",
            "capacitance": "F",
            "inductance": "H",
            "voltage": "V",
            "current": "A",
        }
        
        for param_name, default_unit in param_map.items():
            if param_name in component.parameters:
                param = component.parameters[param_name]
                unit = param.unit or default_unit
                return f"{param.value}{unit}"
        
        # Model parameter
        if "model" in component.parameters:
            param = component.parameters["model"]
            return f"{param.value}"
        
        return component.type.value
    
    def _generate_uuid(self) -> str:
        """Generate UUID for KiCad elements.
        
        Returns:
            UUID string
        """
        import uuid
        return str(uuid.uuid4())