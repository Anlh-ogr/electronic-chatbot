"""Advanced EDA Layout Planner for Schematic Auto-Layout.

Module này chịu trách nhiệm:
1. Sắp xếp linh kiện theo signal flow và hierarchical structure
2. Phân tích circuit graph để trích xuất primary signal path
3. Phân loại nets (signal, bias, feedback, power)
4. Sử dụng block templates cho layout cấu trúc
5. Sinh wire routing với routing occupancy grid
6. Tuân theo analog circuit design rules
"""

from __future__ import annotations

from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import math
from collections import defaultdict, deque
from app.domains.circuits.entities import Circuit


# ============================================================================
# DATA MODELS
# ============================================================================

class NetType(Enum):
    """Classification of nets in the circuit."""
    PRIMARY_SIGNAL = "primary_signal"  # Vin → Vout main path
    BIAS = "bias"                      # Bias networks
    FEEDBACK = "feedback"              # Feedback paths
    POWER = "power"                    # VCC/VDD
    GROUND = "ground"                  # GND/VSS
    SECONDARY = "secondary"            # Other auxiliary nets


class BlockType(Enum):
    """Type of circuit block/stage."""
    BJT_CE = "bjt_ce"                  # BJT Common Emitter
    BJT_CC = "bjt_cc"                  # BJT Common Collector
    BJT_CB = "bjt_cb"                  # BJT Common Base
    MOSFET_CS = "mosfet_cs"            # MOSFET Common Source
    MOSFET_CD = "mosfet_cd"            # MOSFET Common Drain
    MOSFET_CG = "mosfet_cg"            # MOSFET Common Gate
    DARLINGTON = "darlington"          # Darlington pair
    OPAMP_INV = "opamp_inv"            # Op-Amp Inverting
    OPAMP_NONINV = "opamp_noninv"      # Op-Amp Non-inverting
    OPAMP_DIFF = "opamp_diff"          # Op-Amp Differential
    OPAMP_AMPLIFIER = "opamp_amplifier" # Op-Amp Amplifier
    CLASS_A = "class_a"                # Class A Power Amplifier
    CLASS_B= "class_b"                 # Class B Power Amplifier
    CLASS_AB = "class_ab"              # Class AB Power Amplifier
    CLASS_C = "class_c"                # Class C Power Amplifier
    CLASS_D = "class_d"                # Class D Power Amplifier
    DIFF_PAIR = "diff_pair"            # Differential pair
    CURRENT_MIRROR = "current_mirror"  # Current mirror
    SIMPLE_RC = "simple_rc"            # Simple RC network
    UNCLASSIFIED = "unclassified"      # Unknown block type


class CouplingType(Enum):
    """Inter-stage coupling method."""
    RC = "rc"                          # RC coupling with capacitor
    DIRECT = "direct"                  # Direct connection
    TRANSFORMER = "transformer"        # Transformer coupling
    AC = "ac"                          # AC coupling
    DC = "dc"                          # DC coupling


@dataclass
class Pin:
    """Pin on a component."""
    name: str                          # Pin name (e.g., "C", "B", "E")
    x_rel: float = 0.0                 # Relative X offset
    y_rel: float = 0.0                 # Relative Y offset
    orientation: str = "default"       # Pin orientation


@dataclass
class Component:
    """Component with geometry."""
    id: str                            # Component ID (e.g., "Q1", "R2")
    comp_type: str                     # Component type
    x: float = 0.0                     # Center X coordinate
    y: float = 0.0                     # Center Y coordinate
    width: float = 4.0                 # Width (grid units)
    height: float = 4.0                # Height (grid units)
    pins: Dict[str, Pin] = field(default_factory=dict)
    attributes: Dict[str, str] = field(default_factory=dict)


@dataclass
class Net:
    """Net (electrical connection)."""
    name: str                          # Net name
    net_type: NetType = NetType.SECONDARY
    pins: List[Tuple[str, str]] = field(default_factory=list)
    is_feedback: bool = False


@dataclass
class Block:
    """Hierarchical block (stage)."""
    id: str                            # Block ID
    block_type: BlockType              # Type of block
    x: float = 0.0                     # Center X
    y: float = 0.0                     # Center Y
    width: float = 30.0                # Bounding box width
    height: float = 25.0               # Bounding box height
    components: List[str] = field(default_factory=list)
    input_pin: Optional[Tuple[str, str]] = None
    output_pin: Optional[Tuple[str, str]] = None
    coupling_type: CouplingType = CouplingType.DIRECT
    parent_block: Optional[str] = None


@dataclass
class LayoutResult:
    """Result of layout planning."""
    components: Dict[str, Component]
    nets: Dict[str, List[List[Tuple[float, float]]]]
    blocks: Dict[str, Block]
    labels: Dict[Tuple[float, float], str] = field(default_factory=dict)
    signal_path: List[str] = field(default_factory=list)
    blocks_sequence: List[str] = field(default_factory=list)


# ============================================================================
# BLOCK TEMPLATE DEFINITIONS
# ============================================================================

class BlockTemplates:
    """Predefined block layout templates."""
    
    @staticmethod
    def get_template(block_type: BlockType) -> Dict:
        """Get layout template for block type."""
        templates = {
            BlockType.BJT_CE: {
                "width": 30,
                "height": 25,
                "description": "BJT Common Emitter",
                "input_point": (-15, 0),
                "output_point": (15, -5),
                "vcc_point": (0, -10),
                "gnd_point": (0, 12),
                "power_rails": True,
            },
            BlockType.BJT_CC: {
                "width": 25,
                "height": 20,
                "description": "BJT Common Collector",
                "input_point": (-12, 2),
                "output_point": (12, 6),
                "vcc_point": (0, -8),
                "gnd_point": (0, 10),
                "power_rails": True,
            },
            BlockType.BJT_CB: {
                "width": 25,
                "height": 25,
                "description": "BJT Common Base",
                "input_point": (-12, 5),
                "output_point": (12, -5),
                "vcc_point": (0, -10),
                "gnd_point": (0, 12),
                "power_rails": True,
            },
            BlockType.MOSFET_CS: {
                "width": 30,
                "height": 25,
                "description": "MOSFET Common Source",
                "input_point": (-15, 1),
                "output_point": (15, -5),
                "vcc_point": (0, -10),
                "gnd_point": (0, 12),
                "power_rails": True,
            },
            BlockType.MOSFET_CD: {
                "width": 25,
                "height": 20,
                "description": "MOSFET Common Drain",
                "input_point": (-12, 2),
                "output_point": (12, 6),
                "vcc_point": (0, -8),
                "gnd_point": (0, 10),
                "power_rails": True,
            },
            BlockType.MOSFET_CG: {
                "width": 25,
                "height": 25,
                "description": "MOSFET Common Gate",
                "input_point": (-12, 5),
                "output_point": (12, -5),
                "vcc_point": (0, -10),
                "gnd_point": (0, 12),
                "power_rails": True,
            },
            BlockType.DARLINGTON: {
                "width": 35,
                "height": 30,
                "description": "Darlington Pair",
                "input_point": (-15, 0),
                "output_point": (15, 5),
                "vcc_point": (0, -12),
                "gnd_point": (0, 15),
                "power_rails": True,
            },
            BlockType.OPAMP_INV: {
                "width": 32,
                "height": 22,
                "description": "Op-Amp Inverting",
                "input_point": (-20, -6),
                "output_point": (15, 2),
                "vcc_point": (-2, -10),
                "gnd_point": (-2, 10),
                "power_rails": True,
            },
            BlockType.OPAMP_NONINV: {
                "width": 32,
                "height": 22,
                "description": "Op-Amp Non-Inverting",
                "input_point": (-15, -8),
                "output_point": (15, 2),
                "vcc_point": (-2, -10),
                "gnd_point": (-2, 10),
                "power_rails": True,
            },
            BlockType.OPAMP_DIFF: {
                "width": 35,
                "height": 25,
                "description": "Op-Amp Differential",
                "input_point": (-18, 0),
                "output_point": (15, 0),
                "vcc_point": (-2, -10),
                "gnd_point": (-2, 10),
                "power_rails": True,
                "symmetric": True,
            },
            
            BlockType.OPAMP_AMPLIFIER: {
                "width": 32,
                "height": 22,
                "description": "Op-Amp Amplifier",
                "input_point": (-15, 0),
                "output_point": (15, 0),
                "vcc_point": (-2, -10),
                "gnd_point": (-2, 10),
                "power_rails": True,
            },
            BlockType.CLASS_A: {
                "width": 35,
                "height": 30,
                "description": "Class A Power Amplifier",
                "input_point": (-15, 0),
                "output_point": (15, 0),
                "vcc_point": (0, -12),
                "gnd_point": (0, 15),
                "power_rails": True,
            },
            BlockType.CLASS_B: {
                "width": 45,
                "height": 40,
                "description": "Class B Power Amplifier",
                "input_point": (-20, 0),
                "output_point": (20, 0),
                "vcc_point": (0, -15),
                "gnd_point": (0, 15),
                "power_rails": True,
                "symmetric": True,
            },
            BlockType.CLASS_AB: {
                "width": 45,
                "height": 40,
                "description": "Class AB Power Amplifier",
                "input_point": (-20, 0),
                "output_point": (20, 0),
                "vcc_point": (0, -15),
                "gnd_point": (0, 15),
                "power_rails": True,
                "symmetric": True,
            },
            BlockType.CLASS_C: {
                "width": 35,
                "height": 30,
                "description": "Class C Power Amplifier",
                "input_point": (-15, 0),
                "output_point": (15, 0),
                "vcc_point": (0, -12),
                "gnd_point": (0, 15),
                "power_rails": True,
            },
            BlockType.CLASS_D: {
                "width": 45,
                "height": 35,
                "description": "Class D Power Amplifier",
                "input_point": (-20, 0),
                "output_point": (20, 0),
                "vcc_point": (0, -12),
                "gnd_point": (0, 15),
                "power_rails": True,
            },
            BlockType.DIFF_PAIR: {
                "width": 36,
                "height": 28,
                "description": "Differential Pair",
                "input_point": (-18, 2),
                "output_point": (18, 2),
                "vcc_point": (0, -12),
                "gnd_point": (0, 14),
                "power_rails": True,
                "symmetric": True,
            },
            BlockType.CURRENT_MIRROR: {
                "width": 30,
                "height": 25,
                "description": "Current Mirror",
                "input_point": (-15, 5),
                "output_point": (15, 5),
                "vcc_point": (0, -12),
                "gnd_point": (0, 12),
                "power_rails": True,
                "symmetric": True,
            },
            BlockType.SIMPLE_RC: {
                "width": 20,
                "height": 15,
                "description": "Simple RC Network",
                "input_point": (-10, 0),
                "output_point": (10, 0),
                "vcc_point": (0, 0),
                "gnd_point": (0, 8),
                "power_rails": False,
            }
        }
        
        default = {
            "width": 30,
            "height": 25,
            "description": "Generic Block",
            "input_point": (-15, 0),
            "output_point": (15, 0),
            "vcc_point": (0, -12),
            "gnd_point": (0, 12),
            "power_rails": False,
        }
        return templates.get(block_type, default)


# ============================================================================
# CIRCUIT GRAPH ANALYSIS
# ============================================================================

class CircuitGraph:
    """Directed graph for signal path analysis."""
    
    def __init__(self):
        """Initialize circuit graph."""
        self.nodes: Dict[str, Component] = {}
        self.edges: Dict[str, List[str]] = defaultdict(list)
        self.nets: Dict[str, Net] = {}
        self.primary_signal_path: List[str] = []
        self.feedback_nets: Set[str] = set()
        
    def add_component(self, comp: Component):
        """Add component node."""
        self.nodes[comp.id] = comp
        
    def add_net(self, net: Net):
        """Add net (edge)."""
        self.nets[net.name] = net
        
    def extract_signal_path(self, vin_prefix: str = "vin", vout_prefix: str = "vout") -> List[str]:
        """Extract primary signal path from Vin to Vout using DFS.
        
        Returns:
            List of component IDs in signal path order.
        """
        # Find input and output nodes
        vin_node = None
        vout_node = None
        
        for comp_id in self.nodes.keys():
            comp_id_lower = comp_id.lower()
            if vin_prefix in comp_id_lower:
                vin_node = comp_id
            if vout_prefix in comp_id_lower:
                vout_node = comp_id
        
        if not vin_node or not vout_node:
            sorted_ids = sorted(self.nodes.keys())
            vin_node = sorted_ids[0] if sorted_ids else None
            vout_node = sorted_ids[-1] if len(sorted_ids) > 1 else None
        
        if not vin_node or not vout_node:
            return list(self.nodes.keys())
        
        # DFS to find path
        visited = set()
        path = []
        
        def dfs(node_id):
            if node_id in visited:
                return False
            visited.add(node_id)
            path.append(node_id)
            
            if node_id == vout_node:
                return True
            
            for neighbor in self.edges.get(node_id, []):
                if dfs(neighbor):
                    return True
            
            path.pop()
            return False
        
        if dfs(vin_node):
            self.primary_signal_path = path
            return path
        
        return list(self.nodes.keys())
    
    def classify_nets(self) -> Dict[str, NetType]:
        """Classify all nets by type.
        
        Returns:
            Dict mapping net_name → NetType.
        """
        classification = {}
        
        for net_name, net in self.nets.items():
            net_lower = net_name.lower()
            
            if any(kw in net_lower for kw in ("vcc", "vdd", "v+", "power")):
                classification[net_name] = NetType.POWER
            elif any(kw in net_lower for kw in ("gnd", "vss", "ground", "0v")):
                classification[net_name] = NetType.GROUND
            elif any(kw in net_lower for kw in ("vin", "input")):
                classification[net_name] = NetType.PRIMARY_SIGNAL
            elif any(kw in net_lower for kw in ("vout", "output")):
                classification[net_name] = NetType.PRIMARY_SIGNAL
            elif net.is_feedback or any(kw in net_lower for kw in ("feedback", "fdbk", "fb")):
                classification[net_name] = NetType.FEEDBACK
            elif any(kw in net_lower for kw in ("bias", "vbias", "ibias")):
                classification[net_name] = NetType.BIAS
            else:
                classification[net_name] = NetType.SECONDARY
        
        return classification


# ============================================================================
# ROUTING GRID
# ============================================================================

class RoutingGrid:
    """Grid for tracking routing occupancy."""
    
    def __init__(self, width: float, height: float, resolution: float = 1.0):
        """Initialize routing grid.
        
        Args:
            width: Grid width
            height: Grid height
            resolution: Grid cell size
        """
        self.width = width
        self.height = height
        self.resolution = resolution
        self.grid_width = int(width / resolution) + 1
        self.grid_height = int(height / resolution) + 1
        # 0=free, 1=component, 2=routed wire
        self.occupancy: List[List[int]] = [
            [0] * self.grid_width for _ in range(self.grid_height)
        ]
        
    def mark_component(self, x_center: float, y_center: float,
                      width: float, height: float):
        """Mark component bounding box as occupied."""
        x_min = int((x_center - width/2) / self.resolution)
        x_max = int((x_center + width/2) / self.resolution)
        y_min = int((y_center - height/2) / self.resolution)
        y_max = int((y_center + height/2) / self.resolution)
        
        for y in range(max(0, y_min), min(self.grid_height, y_max + 1)):
            for x in range(max(0, x_min), min(self.grid_width, x_max + 1)):
                self.occupancy[y][x] = 1


# ============================================================================
# MAIN LAYOUT PLANNER
# ============================================================================

class LayoutPlanner:
    """Advanced EDA layout planner for schematic generation."""
    
    def __init__(
        self,
        x_start: float = 50.0,
        y_start: float = 50.0,
        grid_resolution: float = 1.0,
        component_spacing: float = 15.0,
        block_spacing: float = 40.0,
        enable_templates: bool = True,
        enable_routing_grid: bool = True,
        # Legacy parameters for backward compatibility
        x_spacing: float = 18.0,
        y_spacing: float = 14.0,
        columns: int = 5,
    ):
        """Initialize layout planner.
        
        Args:
            x_start: Starting X coordinate
            y_start: Starting Y coordinate
            grid_resolution: Routing grid resolution
            component_spacing: Spacing between components
            block_spacing: Spacing between blocks
            enable_templates: Use block templates
            enable_routing_grid: Track routing occupancy
            (Legacy params for backward compatibility)
        """
        self.x_start = x_start
        self.y_start = y_start
        self.grid_resolution = grid_resolution
        self.component_spacing = component_spacing
        self.block_spacing = block_spacing
        self.enable_templates = enable_templates
        self.enable_routing_grid = enable_routing_grid
        self.grid_snap = max(0.5, grid_resolution)
        self.min_component_spacing = 2.0
        
        # Legacy compatibility
        self.x_spacing = x_spacing
        self.y_spacing = y_spacing
        self.columns = columns
        
        self.routing_grid: Optional[RoutingGrid] = None
        self.circuit_graph: Optional[CircuitGraph] = None
        self.net_classification: Dict[str, NetType] = {}
    
    # ========================================================================
    # PUBLIC API - MAIN ENTRY POINTS
    # ========================================================================
    
    def plan_layout(self, circuit: Circuit) -> LayoutResult:
        """Plan complete layout for circuit (new comprehensive approach).
        
        Args:
            circuit: Circuit entity
            
        Returns:
            LayoutResult with components, nets, blocks, labels
        """
        # Initialize circuit graph
        self.circuit_graph = self._build_circuit_graph(circuit)
        
        # Extract signal path
        signal_path = self._extract_signal_path()
        
        # Classify nets
        self.net_classification = self._classify_nets()
        
        # Identify blocks/stages
        blocks = self._identify_blocks(signal_path)
        
        # Place blocks left-to-right
        self._place_blocks(blocks)
        
        # Place components within blocks
        components = self._place_components_within_blocks(circuit, blocks)
        
        # Route nets
        routed_nets = self._route_all_nets(circuit, components)
        
        # Generate labels
        labels = self._generate_labels(components, signal_path)
        
        return LayoutResult(
            components=components,
            nets=routed_nets,
            blocks=blocks,
            labels=labels,
            signal_path=signal_path,
            blocks_sequence=list(blocks.keys()),
        )
    
    def place_components(
        self,
        circuit: Circuit,
        spacing_scale: float = 1.0,
    ) -> Dict[str, Tuple[float, float]]:
        """Legacy API: place components in simple grid layout.
        
        Args:
            circuit: Circuit entity
            
        Returns:
            Dict mapping component_id → (x, y)
        """
        placements: Dict[str, Tuple[float, float]] = {}
        
        # Detect op-amp and choose compact profile for all circuit types.
        is_opamp = self._detect_opamp_circuit(circuit)
        use_manual_positions = False
        x_spacing, y_spacing, columns = self._compact_grid_profile(
            component_count=len(circuit.components),
            is_opamp=is_opamp,
        )
        x_spacing *= max(0.8, spacing_scale)
        y_spacing *= max(0.8, spacing_scale)
        
        power_ids: List[str] = []
        ground_ids: List[str] = []
        normal_ids: List[str] = []
        
        for comp_id, component in circuit.components.items():
            manual_pos = self._manual_position_from_render_style(component) if use_manual_positions else None
            if manual_pos is not None:
                placements[comp_id] = manual_pos
                continue
            
            if self._is_ground_component(comp_id, component):
                ground_ids.append(comp_id)
            elif self._is_power_component(comp_id, component):
                power_ids.append(comp_id)
            else:
                normal_ids.append(comp_id)

        signal_axis_ids, below_axis_ids, above_axis_ids = self._partition_components_for_signal_flow(
            normal_ids,
            circuit,
        )
        signal_axis_ids = self._enforce_signal_axis_edges(signal_axis_ids)

        # Strict signal flow axis: VIN -> Input Stage -> Amplifier -> Output -> VOUT.
        signal_axis_y = self.y_start
        grouped_axis = self._group_signal_axis_components(signal_axis_ids, circuit)
        x_cursor = self.x_start
        group_gap = max(10.0, 0.9 * x_spacing)
        for _, group_ids in grouped_axis:
            for comp_id in group_ids:
                placements[comp_id] = (x_cursor, signal_axis_y)
                x_cursor += x_spacing
            if group_ids:
                x_cursor += group_gap

        if signal_axis_ids:
            axis_xs = [placements[cid][0] for cid in signal_axis_ids]
            center_x = (min(axis_xs) + max(axis_xs)) / 2.0
            axis_start_x = min(axis_xs)
            axis_end_x = max(axis_xs)
        else:
            center_x = self.x_start + ((columns - 1) * x_spacing / 2.0)
            axis_start_x = self.x_start
            axis_end_x = self.x_start + (max(0, columns - 1) * x_spacing)

        def spread_by_axis(ids: List[str], y_value: float) -> None:
            if not ids:
                return
            if len(ids) == 1:
                placements[ids[0]] = (center_x, y_value)
                return
            usable_span = max(x_spacing, axis_end_x - axis_start_x)
            step = max(8.0, usable_span / (len(ids) - 1))
            for idx, comp_id in enumerate(ids):
                x = axis_start_x + idx * step
                placements[comp_id] = (x, y_value)

        # Enforce layers (POWER/TOP/MIDDLE/BOTTOM/GROUND) without mixing.
        top_layer_y = max(40.0, signal_axis_y - (2.0 * y_spacing))
        bottom_layer_y = signal_axis_y + (2.0 * y_spacing)

        # Non-signal components stay off the signal axis.
        spread_by_axis(above_axis_ids, top_layer_y)
        spread_by_axis(below_axis_ids, bottom_layer_y)

        # Power and ground rails with strict vertical semantics.
        rail_spacing = min(x_spacing, 18.0)
        power_layer_y = max(10.0, top_layer_y - (1.5 * y_spacing))
        ground_layer_y = bottom_layer_y + (1.5 * y_spacing)

        top_y = power_layer_y
        bottom_y = ground_layer_y

        self._place_centered_row(power_ids, top_y, center_x, rail_spacing, placements)
        self._place_centered_row(ground_ids, bottom_y, center_x, rail_spacing, placements)

        placements = self._resolve_component_overlaps(
            placements,
            min_spacing=self.min_component_spacing,
        )
        placements = self._snap_placements_to_grid(placements, self.grid_snap)
        placements = self._fit_placements_to_sheet(placements, is_opamp=is_opamp)
        placements = self._snap_placements_to_grid(placements, self.grid_snap)
        return placements

    @staticmethod
    def _snap_value(value: float, step: float) -> float:
        if step <= 0:
            return value
        return round(value / step) * step

    def _snap_point(self, point: Tuple[float, float], step: Optional[float] = None) -> Tuple[float, float]:
        grid_step = self.grid_snap if step is None else step
        x, y = point
        return (self._snap_value(x, grid_step), self._snap_value(y, grid_step))

    def _snap_placements_to_grid(
        self,
        placements: Dict[str, Tuple[float, float]],
        step: float,
    ) -> Dict[str, Tuple[float, float]]:
        return {comp_id: self._snap_point(pos, step) for comp_id, pos in placements.items()}

    def _resolve_component_overlaps(
        self,
        placements: Dict[str, Tuple[float, float]],
        min_spacing: float,
    ) -> Dict[str, Tuple[float, float]]:
        """Resolve overlapping component centers by shifting on X axis while preserving layers."""
        if len(placements) < 2:
            return placements

        adjusted = dict(placements)
        ids = list(adjusted.keys())

        for _ in range(8):
            moved = False
            for i in range(len(ids)):
                id_a = ids[i]
                xa, ya = adjusted[id_a]
                for j in range(i + 1, len(ids)):
                    id_b = ids[j]
                    xb, yb = adjusted[id_b]

                    if abs(xa - xb) < min_spacing and abs(ya - yb) < min_spacing:
                        adjusted[id_b] = (xb + min_spacing, yb)
                        moved = True
            if not moved:
                break

        return adjusted

    def _enforce_signal_axis_edges(self, signal_axis_ids: List[str]) -> List[str]:
        """Force VIN to far-left and VOUT to far-right when present."""
        if not signal_axis_ids:
            return signal_axis_ids

        ordered = list(signal_axis_ids)

        vin_ids = [cid for cid in ordered if self._is_input_component_id(cid.lower())]
        vout_ids = [cid for cid in ordered if self._is_output_component_id(cid.lower())]

        core = [cid for cid in ordered if cid not in vin_ids and cid not in vout_ids]
        return vin_ids + core + vout_ids

    def _group_signal_axis_components(
        self,
        signal_axis_ids: List[str],
        circuit: Circuit,
    ) -> List[Tuple[str, List[str]]]:
        """Group signal-axis components for visual functional separation."""
        groups: Dict[str, List[str]] = {
            "input": [],
            "coupling": [],
            "active": [],
            "load": [],
            "output": [],
            "other": [],
        }

        for comp_id in signal_axis_ids:
            component = circuit.components.get(comp_id)
            comp_type = self._component_type_value(component) if component is not None else ""
            cid = comp_id.lower()

            if self._is_input_component_id(cid):
                groups["input"].append(comp_id)
            elif self._is_output_component_id(cid):
                groups["output"].append(comp_id)
            elif self._is_coupling_component(comp_type, cid):
                groups["coupling"].append(comp_id)
            elif self._is_active_component(comp_type):
                groups["active"].append(comp_id)
            elif self._is_load_component(comp_type, cid):
                groups["load"].append(comp_id)
            else:
                groups["other"].append(comp_id)

        ordered_groups = [
            ("input", groups["input"]),
            ("coupling", groups["coupling"]),
            ("active", groups["active"]),
            ("load", groups["load"]),
            ("output", groups["output"]),
            ("other", groups["other"]),
        ]
        return ordered_groups

    def _compact_grid_profile(self, component_count: int, is_opamp: bool) -> Tuple[float, float, int]:
        """Return compact grid parameters for all circuits.

        The profile is intentionally dense to keep circuits inside KiCanvas frame.
        """
        if is_opamp:
            if component_count <= 8:
                return (10.0, 8.0, 4)
            if component_count <= 14:
                return (11.0, 9.0, 5)
            return (12.0, 9.5, 6)

        if component_count <= 6:
            return (11.0, 8.5, 4)
        if component_count <= 12:
            return (12.0, 9.0, 5)
        if component_count <= 20:
            return (13.0, 10.0, 6)
        return (14.0, 10.5, 7)

    def _sort_components_for_signal_flow(
        self,
        comp_ids: List[str],
        circuit: Circuit,
    ) -> List[str]:
        """Sort components for strict left-to-right signal flow order."""
        def rank(comp_id: str) -> Tuple[int, str]:
            component = circuit.components.get(comp_id)
            comp_type = self._component_type_value(component) if component is not None else ""
            cid = comp_id.lower()

            if self._is_input_component_id(cid):
                return (0, cid)
            if self._is_coupling_component(comp_type, cid):
                return (1, cid)
            if self._is_active_component(comp_type):
                return (2, cid)
            if self._is_load_component(comp_type, cid):
                return (3, cid)
            if self._is_output_component_id(cid):
                return (4, cid)
            return (5, cid)

        return sorted(comp_ids, key=rank)

    def _partition_components_for_signal_flow(
        self,
        comp_ids: List[str],
        circuit: Circuit,
    ) -> Tuple[List[str], List[str], List[str]]:
        """Partition components into signal-axis / below-axis / above-axis groups."""
        sorted_ids = self._sort_components_for_signal_flow(comp_ids, circuit)
        net_lookup = self._build_component_net_lookup(circuit)

        signal_axis: List[str] = []
        below_axis: List[str] = []
        above_axis: List[str] = []

        for comp_id in sorted_ids:
            component = circuit.components.get(comp_id)
            comp_type = self._component_type_value(component) if component is not None else ""
            cid = comp_id.lower()
            has_power_conn, has_ground_conn = self._component_rail_connectivity(circuit, comp_id)
            cap_role = self._classify_capacitor_role(
                comp_id,
                comp_type,
                net_lookup.get(comp_id, []),
                has_power_conn,
                has_ground_conn,
            )

            if cap_role == "decoupling":
                above_axis.append(comp_id)
                continue
            if cap_role == "bypass":
                below_axis.append(comp_id)
                continue

            if self._is_signal_axis_component(comp_type, cid):
                signal_axis.append(comp_id)
                continue

            if self._is_bias_component(comp_type, cid):
                below_axis.append(comp_id)
            else:
                above_axis.append(comp_id)

        return signal_axis, below_axis, above_axis

    def _build_component_net_lookup(self, circuit: Circuit) -> Dict[str, List[str]]:
        """Map component id to connected net names (lower-cased)."""
        net_lookup: Dict[str, List[str]] = {}
        for net in circuit.nets.values():
            nname = net.name.lower()
            for pref in net.connected_pins:
                net_lookup.setdefault(pref.component_id, []).append(nname)
        return net_lookup

    def _component_rail_connectivity(self, circuit: Circuit, comp_id: str) -> Tuple[bool, bool]:
        """Detect whether component is connected to power and/or ground components via nets."""
        has_power_conn = False
        has_ground_conn = False

        for net in circuit.nets.values():
            pin_ids = [p.component_id for p in net.connected_pins]
            if comp_id not in pin_ids:
                continue
            for other_id in pin_ids:
                if other_id == comp_id:
                    continue
                other_comp = circuit.components.get(other_id)
                if other_comp is None:
                    continue
                if self._is_power_component(other_id, other_comp):
                    has_power_conn = True
                if self._is_ground_component(other_id, other_comp):
                    has_ground_conn = True

        return has_power_conn, has_ground_conn

    @staticmethod
    def _is_input_component_id(cid: str) -> bool:
        if cid in ("vin", "input", "in"):
            return True
        return (
            cid.startswith("vin")
            or cid.endswith("_in")
            or cid.endswith(".in")
            or cid.startswith("input")
        )

    @staticmethod
    def _is_output_component_id(cid: str) -> bool:
        if cid in ("vout", "output", "out"):
            return True
        return (
            cid.startswith("vout")
            or cid.endswith("_out")
            or cid.endswith(".out")
            or cid.startswith("output")
        )

    @staticmethod
    def _is_active_component(comp_type: str) -> bool:
        return comp_type in (
            "opamp",
            "bjt",
            "bjt_npn",
            "bjt_pnp",
            "mosfet",
            "mosfet_n",
            "mosfet_p",
        )

    @staticmethod
    def _is_coupling_component(comp_type: str, cid: str) -> bool:
        if "coupl" in cid:
            return True
        if comp_type in ("capacitor", "capacitor_polarized") and any(tok in cid for tok in ("ce", "cs", "bypass", "decoup")):
            return False
        return comp_type in ("capacitor", "capacitor_polarized", "inductor", "transformer")

    @staticmethod
    def _is_load_component(comp_type: str, cid: str) -> bool:
        if any(token in cid for token in ("load", "rl", "ro", "rload")):
            return True
        return comp_type in ("speaker",)

    @staticmethod
    def _is_bias_component(comp_type: str, cid: str) -> bool:
        if any(token in cid for token in ("bias", "rb", "re", "rs", "tail", "deg")):
            return True
        return comp_type in ("resistor",)

    def _is_signal_axis_component(self, comp_type: str, cid: str) -> bool:
        if self._is_input_component_id(cid) or self._is_output_component_id(cid):
            return True
        if self._is_active_component(comp_type):
            return True
        if self._is_coupling_component(comp_type, cid):
            return True
        if self._is_load_component(comp_type, cid):
            return True
        return False

    def _fit_placements_to_sheet(
        self,
        placements: Dict[str, Tuple[float, float]],
        is_opamp: bool,
    ) -> Dict[str, Tuple[float, float]]:
        """Translate placements to stay inside a safe KiCad A4 drawing area."""
        if not placements:
            return placements

        # Keep all circuits inside a conservative safe area in KiCanvas A4.
        # This also prevents components overlapping the title block at lower-right.
        min_x_allowed, max_x_allowed = 26.0, 228.0
        min_y_allowed, max_y_allowed = 20.0, 156.0

        adjusted = dict(placements)
        xs = [p[0] for p in adjusted.values()]
        ys = [p[1] for p in adjusted.values()]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        allowed_w = max_x_allowed - min_x_allowed
        allowed_h = max_y_allowed - min_y_allowed
        width = max(1e-9, max_x - min_x)
        height = max(1e-9, max_y - min_y)

        # If layout is bigger than allowed window, scale down around center first.
        scale_x = 1.0 if width <= allowed_w else allowed_w / width
        scale_y = 1.0 if height <= allowed_h else allowed_h / height
        scale = min(scale_x, scale_y, 1.0)

        if scale < 1.0:
            cx = (min_x + max_x) / 2.0
            cy = (min_y + max_y) / 2.0
            adjusted = {
                comp_id: (cx + (x - cx) * scale, cy + (y - cy) * scale)
                for comp_id, (x, y) in adjusted.items()
            }
            xs = [p[0] for p in adjusted.values()]
            ys = [p[1] for p in adjusted.values()]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)

        dx = 0.0
        if min_x < min_x_allowed:
            dx = min_x_allowed - min_x
        if max_x + dx > max_x_allowed:
            dx += max_x_allowed - (max_x + dx)

        dy = 0.0
        if min_y < min_y_allowed:
            dy = min_y_allowed - min_y
        if max_y + dy > max_y_allowed:
            dy += max_y_allowed - (max_y + dy)

        if dx == 0.0 and dy == 0.0:
            return adjusted

        return {comp_id: (x + dx, y + dy) for comp_id, (x, y) in adjusted.items()}
    
    def plan_manhattan_routing(
        self,
        points: List[Tuple[float, float]]
    ) -> List[List[Tuple[float, float]]]:
        """Plan Manhattan routing between multiple points.
        
        Args:
            points: List of (x, y) to connect
            
        Returns:
            List of wire segments
        """
        if len(points) < 2:
            return []

        snapped_points = [self._snap_point(p) for p in points]
        ordered_points = self._order_points_for_shorter_routes(snapped_points)
        wires = []
        
        for i in range(len(ordered_points) - 1):
            x1, y1 = ordered_points[i]
            x2, y2 = ordered_points[i + 1]
            
            if x1 == x2 or y1 == y2:
                wires.append([self._snap_point((x1, y1)), self._snap_point((x2, y2))])
                continue
            
            # Choose corner orientation
            mx = sum(p[0] for p in ordered_points) / len(ordered_points)
            my = sum(p[1] for p in ordered_points) / len(ordered_points)
            corner_hv = (x2, y1)
            corner_vh = (x1, y2)
            hv_cost = abs(corner_hv[0] - mx) + abs(corner_hv[1] - my)
            vh_cost = abs(corner_vh[0] - mx) + abs(corner_vh[1] - my)
            
            corner = corner_hv if hv_cost <= vh_cost else corner_vh
            wires.append([
                self._snap_point((x1, y1)),
                self._snap_point(corner),
                self._snap_point((x2, y2)),
            ])
        
        return wires
    
    def find_junctions(
        self,
        wires: List[List[Tuple[float, float]]]
    ) -> Set[Tuple[float, float]]:
        """Find junctions where 3+ wire segments meet.
        
        Args:
            wires: List of wire segments
            
        Returns:
            Set of junction coordinates
        """
        point_count: Dict[Tuple[float, float], int] = {}
        
        for wire in wires:
            for point in wire:
                point_count[point] = point_count.get(point, 0) + 1
        
        junctions = {pt for pt, count in point_count.items() if count >= 3}
        return junctions
    
    def get_pin_position(
        self,
        pin,
        placements: Dict[str, Tuple[float, float]],
        circuit: Circuit,
        pin_offsets: Dict[str, list],
        rotations: Optional[Dict[str, int]] = None,
    ) -> Optional[Tuple[float, float]]:
        """Calculate absolute position of a pin.
        
        Args:
            pin: Pin reference with component_id and pin_name attributes
            placements: Component placement map (comp_id → (x, y))
            circuit: Circuit entity for component lookup
            pin_offsets: Map of component_type → list of (dx, dy, orientation) offsets
            
        Returns:
            (x, y) absolute pin position, or None if not found
        """
        # Extract component_id from pin
        try:
            comp_id = getattr(pin, "component_id", None) or getattr(pin, "component", None)
            if not hasattr(pin, "component_id") and not hasattr(pin, "component"):
                comp_id = pin.component if hasattr(pin, "component") else None
        except Exception:
            return None
        
        if not comp_id or comp_id not in placements:
            return None
        
        component = circuit.components.get(comp_id)
        if component is None:
            return None
        
        # Get component placement
        x, y = placements[comp_id]

        if hasattr(component, "pins") and len(component.pins) == 1 and (self._is_power_component(comp_id, component) or self._is_ground_component(comp_id, component)):
            return (x, y)
        
        # Get pin index from component's pin list
        try:
            pin_name = getattr(pin, "pin_name", None) or getattr(pin, "pin", None)
            if hasattr(component, "pins") and pin_name in component.pins:
                pin_index = component.pins.index(pin_name)
            else:
                pin_index = 0
        except Exception:
            pin_index = 0
        
        # Get pin offset from component type
        try:
            comp_type = self._component_type_value(component)
        except Exception:
            comp_type = "unknown"
        
        if comp_type not in pin_offsets:
            return (x, y)
        
        offsets = pin_offsets[comp_type]
        if pin_index >= len(offsets):
            pin_index = min(pin_index, len(offsets) - 1)
        
        dx, dy, _ = offsets[pin_index]

        # Apply symbol rotation so routing uses real pin geometry after auto-rotation.
        rot = int((rotations or {}).get(comp_id, 0)) % 360
        if rot == 90:
            dx, dy = -dy, dx
        elif rot == 180:
            dx, dy = -dx, -dy
        elif rot == 270:
            dx, dy = dy, -dx
        
        return (x + dx, y + dy)

    def infer_component_rotations(
        self,
        circuit: Circuit,
        placements: Dict[str, Tuple[float, float]],
    ) -> Dict[str, int]:
        """Infer component rotations (0/90/180/270) to reduce wire complexity.

        Rules applied:
        - Signal path preference: left-to-right
        - Power-related branches: vertical preference
        - BJT/MOSFET: default orientation with C/D up, E/S down, B/G left
        - Capacitor/Resistor: horizontal in signal path, vertical for supply/ground branches
        """
        rotations: Dict[str, int] = {}

        net_lookup: Dict[str, List[str]] = {}
        for net in circuit.nets.values():
            for pref in net.connected_pins:
                cid = pref.component_id
                net_lookup.setdefault(cid, []).append(net.name.lower())

        for comp_id, component in circuit.components.items():
            comp_type = self._component_type_value(component)
            cid = comp_id.lower()
            connected_net_names = net_lookup.get(comp_id, [])
            comp_pos = placements.get(comp_id)
            has_power_conn, has_ground_conn = self._component_rail_connectivity(circuit, comp_id)

            if comp_type in ("voltage_source", "current_source", "ground"):
                rotations[comp_id] = 90
                continue

            # 1) Hard rules for transistor families and op-amp symbols.
            if comp_type in ("bjt", "bjt_npn", "bjt_pnp", "mosfet", "mosfet_n", "mosfet_p", "opamp"):
                rotations[comp_id] = 0
                continue

            # 2) Explicit I/O facing preference on horizontal signal flow.
            if self._is_input_component_id(cid):
                rotations[comp_id] = 180
                continue
            if self._is_output_component_id(cid):
                rotations[comp_id] = 0
                continue

            has_power_net = any(any(tok in n for tok in ("vcc", "vdd", "v+", "power")) for n in connected_net_names) or has_power_conn
            has_ground_net = any(any(tok in n for tok in ("gnd", "ground", "vss", "0v")) for n in connected_net_names) or has_ground_conn
            capacitor_role = self._classify_capacitor_role(
                comp_id,
                comp_type,
                connected_net_names,
                has_power_conn,
                has_ground_conn,
            )
            is_signal_coupling = capacitor_role == "coupling"
            in_signal_axis = self._is_signal_axis_component(comp_type, cid)

            # 3) Capacitor orientation by role.
            if comp_type in ("capacitor", "capacitor_polarized"):
                if capacitor_role in ("bypass", "decoupling"):
                    rotations[comp_id] = 90
                else:
                    rotations[comp_id] = 0
                continue

            # 4) Signal-path passives stay horizontal for left-to-right readability.
            if in_signal_axis and comp_type in ("resistor", "inductor", "capacitor", "capacitor_polarized"):
                rotations[comp_id] = 0
                continue

            # 5) Resistors tied to supply rails should be vertical by convention.
            if comp_type == "resistor":
                if has_power_net and not has_ground_net:
                    rotations[comp_id] = 270
                    continue
                if has_ground_net and not has_power_net:
                    rotations[comp_id] = 90
                    continue

            # 6) Supply/ground branches should be vertical.
            if comp_type in ("resistor", "capacitor", "capacitor_polarized", "inductor") and (has_power_net or has_ground_net):
                rotations[comp_id] = 90
                continue

            # 7) Coupling parts along signal path should be horizontal.
            if is_signal_coupling:
                rotations[comp_id] = 0
                continue

            # 8) Min-bend heuristic from neighbor vector field.
            if comp_pos is None:
                rotations[comp_id] = 0
                continue

            x0, y0 = comp_pos
            sum_dx = 0.0
            sum_dy = 0.0
            for net in circuit.nets.values():
                pin_ids = [p.component_id for p in net.connected_pins]
                if comp_id not in pin_ids:
                    continue
                for other_id in pin_ids:
                    if other_id == comp_id:
                        continue
                    other_pos = placements.get(other_id)
                    if other_pos is None:
                        continue
                    sum_dx += other_pos[0] - x0
                    sum_dy += other_pos[1] - y0

            # Prefer orientation aligned with dominant connection axis.
            if abs(sum_dy) > abs(sum_dx):
                rotations[comp_id] = 90
            else:
                rotations[comp_id] = 0

        return rotations

    def _classify_capacitor_role(
        self,
        comp_id: str,
        comp_type: str,
        connected_net_names: List[str],
        has_power_conn: bool = False,
        has_ground_conn: bool = False,
    ) -> str:
        """Classify capacitor role: coupling / bypass / decoupling."""
        if comp_type not in ("capacitor", "capacitor_polarized"):
            return "other"

        cid = comp_id.lower()
        has_power_net = has_power_conn or any(any(tok in n for tok in ("vcc", "vdd", "v+", "power")) for n in connected_net_names)
        has_ground_net = has_ground_conn or any(any(tok in n for tok in ("gnd", "ground", "vss", "0v")) for n in connected_net_names)

        if has_power_net and has_ground_net:
            return "decoupling"
        if any(tok in cid for tok in ("ce", "cs", "bypass", "cbypass", "deg")):
            return "bypass"
        if any(tok in cid for tok in ("cdec", "decoup", "decoupl", "dec")):
            return "decoupling"
        if any(tok in cid for tok in ("cin", "cout", "coupl", "ac")):
            return "coupling"
        if has_ground_net and not has_power_net:
            return "bypass"
        return "coupling"
    
    # ========================================================================
    # PRIVATE IMPLEMENTATION METHODS
    # ========================================================================
    
    def _build_circuit_graph(self, circuit: Circuit) -> CircuitGraph:
        """Build directed graph from circuit."""
        graph = CircuitGraph()
        
        for comp_id, comp in circuit.components.items():
            comp_obj = Component(
                id=comp_id,
                comp_type=self._component_type_value(comp),
            )
            graph.add_component(comp_obj)
        
        return graph
    
    def _extract_signal_path(self) -> List[str]:
        """Extract primary signal path."""
        if self.circuit_graph is None:
            return []
        return self.circuit_graph.extract_signal_path()
    
    def _classify_nets(self) -> Dict[str, NetType]:
        """Classify nets by type."""
        if self.circuit_graph is None:
            return {}
        return self.circuit_graph.classify_nets()
    
    def _identify_blocks(self, signal_path: List[str]) -> Dict[str, Block]:
        """Identify blocks/stages from signal path.
        
        For now, return one block per stage in signal path.
        """
        blocks: Dict[str, Block] = {}
        
        for idx, comp_id in enumerate(signal_path):
            block = Block(
                id=f"Block_{idx}",
                block_type=BlockType.UNCLASSIFIED,
                components=[comp_id],
            )
            blocks[block.id] = block
        
        return blocks
    
    def _place_blocks(self, blocks: Dict[str, Block]):
        """Place blocks left-to-right with spacing."""
        template = BlockTemplates.get_template(BlockType.UNCLASSIFIED)
        block_width = template["width"]
        block_spacing = self.block_spacing
        
        x = self.x_start
        for block_id, block in blocks.items():
            block.x = x
            block.y = self.y_start
            x += block_width + block_spacing
    
    def _place_components_within_blocks(
        self, circuit: Circuit, blocks: Dict[str, Block]
    ) -> Dict[str, Component]:
        """Place components within their assigned blocks."""
        components: Dict[str, Component] = {}
        
        for block_id, block in blocks.items():
            for idx, comp_id in enumerate(block.components):
                if comp_id not in circuit.components:
                    continue
                
                comp = circuit.components[comp_id]
                comp_type = self._component_type_value(comp)
                
                # Offset within block
                local_x = block.x + (idx % 3) * self.component_spacing
                local_y = block.y + (idx // 3) * self.component_spacing
                
                comp_obj = Component(
                    id=comp_id,
                    comp_type=comp_type,
                    x=local_x,
                    y=local_y,
                    width=4.0,
                    height=4.0,
                )
                components[comp_id] = comp_obj
        
        return components
    
    def _route_all_nets(
        self, circuit: Circuit, components: Dict[str, Component]
    ) -> Dict[str, List[List[Tuple[float, float]]]]:
        """Route all nets using Manhattan routing."""
        routed_nets: Dict[str, List[List[Tuple[float, float]]]] = {}
        
        # For now, just return empty dict (would implement actual routing)
        return routed_nets
    
    def _generate_labels(
        self, components: Dict[str, Component], signal_path: List[str]
    ) -> Dict[Tuple[float, float], str]:
        """Generate labels for signal path and power rails."""
        labels: Dict[Tuple[float, float], str] = {}
        
        # Label input
        if signal_path:
            first_comp = components.get(signal_path[0])
            if first_comp:
                labels[(first_comp.x - 10, first_comp.y)] = "Vin"
            
            last_comp = components.get(signal_path[-1])
            if last_comp:
                labels[(last_comp.x + 10, last_comp.y)] = "Vout"
        
        return labels
    
    # ========================================================================
    # LEGACY HELPER METHODS
    # ========================================================================
    
    @staticmethod
    def _component_type_value(component) -> str:
        """Get component type as string."""
        comp_type = getattr(component, "type", None)
        if comp_type is None:
            return ""
        return getattr(comp_type, "value", str(comp_type)).lower()
    
    def _is_ground_component(self, comp_id: str, component) -> bool:
        """Check if component is ground."""
        comp_type = self._component_type_value(component)
        if comp_type == "ground":
            return True
        
        cid = comp_id.strip().lower()
        ground_tokens = ("gnd", "ground", "groud", "0v", "vss", "mass", "matt")
        return any(token in cid for token in ground_tokens)
    
    def _is_power_component(self, comp_id: str, component) -> bool:
        """Check if component is power."""
        comp_type = self._component_type_value(component)
        if comp_type in ("voltage_source", "current_source"):
            return True

        if comp_type in ("port", "connector"):
            cid_port = comp_id.strip().lower()
            return any(token in cid_port for token in ("vcc", "vdd", "v+", "vbat", "power", "source"))
        
        cid = comp_id.strip().lower()
        power_tokens = ("vcc", "vdd", "v+", "vbat", "power", "source")
        return any(token in cid for token in power_tokens)
    
    def _detect_opamp_circuit(self, circuit: Circuit) -> bool:
        """Detect if circuit uses op-amps."""
        circuit_name = (circuit.name or "").lower()
        opamp_keywords = (
            "opamp", "op-amp", "op_amp", "operational",
            "inverting", "non_inverting", "noninverting",
            "differential", "instrumentation", "in-amp"
        )
        
        if any(kw in circuit_name for kw in opamp_keywords):
            return True
        
        for comp_id, component in circuit.components.items():
            comp_type = self._component_type_value(component)
            if "opamp" in comp_type:
                return True
        
        return False
    
    def _place_centered_row(
        self,
        comp_ids: List[str],
        y: float,
        center_x: float,
        spacing: float,
        placements: Dict[str, Tuple[float, float]],
    ) -> None:
        """Place components in a centered row."""
        if not comp_ids:
            return
        
        count = len(comp_ids)
        first_x = center_x - ((count - 1) * spacing / 2.0)
        for idx, comp_id in enumerate(comp_ids):
            placements[comp_id] = (first_x + idx * spacing, y)
    
    def _manual_position_from_render_style(self, component) -> Optional[Tuple[float, float]]:
        """Get manual position from render_style."""
        render_style = getattr(component, "render_style", None)
        if not render_style:
            return None
        
        position = render_style.get("position")
        if not isinstance(position, dict):
            return None
        
        scale = 2.54
        center_x = 127.0
        center_y = 95.0
        x = center_x + (float(position.get("x", 0.0)) * scale)
        y = center_y - (float(position.get("y", 0.0)) * scale)
        return (x, y)
    
    @staticmethod
    def _order_points_for_shorter_routes(
        points: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        """Order net points by nearest-neighbor."""
        unique_points = list(dict.fromkeys(points))
        if len(unique_points) <= 2:
            return unique_points
        
        start = min(unique_points, key=lambda p: (p[0], p[1]))
        ordered = [start]
        remaining = set(unique_points)
        remaining.remove(start)
        
        while remaining:
            last = ordered[-1]
            nxt = min(remaining, key=lambda p: abs(p[0] - last[0]) + abs(p[1] - last[1]))
            ordered.append(nxt)
            remaining.remove(nxt)
        
        return ordered

