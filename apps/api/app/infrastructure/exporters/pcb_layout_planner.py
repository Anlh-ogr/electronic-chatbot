# .\thesis\electronic-chatbot\apps\api\app\infrastructure\exporters\pcb_layout_planner.py
"""PCB layout planner cho sắp xếp linh kiện trên board.

Module này chịu trách nhiệm:
1. Phân loại linh kiện theo nhóm power/ground/normal
2. Đặt linh kiện tự động theo vùng board
3. Chuẩn hóa tọa độ theo grid snap
4. Tạo pad position phục vụ route track
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, Tuple, List

from app.domains.circuits.entities import Circuit, ComponentType
from app.infrastructure.exporters.kicad_footprint_library import KiCadFootprintLibrary


class PCBLayoutPlanner:
    """Planner tự động cho PCB placement.

    Strategy:
    1. Phân nhóm linh kiện
    2. Đặt theo vùng board
    3. Snap grid
    4. Sinh vị trí pad tuyệt đối
    """
    
    # Board parameters (mm)
    BOARD_WIDTH = 120.0
    BOARD_HEIGHT = 80.0
    MARGIN = 15.0
    COMP_SPACING = 15.0  # minimum spacing between component centres

    @staticmethod
    def _component_type_value(component) -> str:
        comp_type = getattr(component, "type", None)
        if comp_type is None:
            return ""
        return getattr(comp_type, "value", str(comp_type)).lower()

    def _is_ground_component(self, comp_id: str, component) -> bool:
        comp_type = self._component_type_value(component)
        if comp_type == "ground":
            return True

        cid = comp_id.strip().lower()
        ground_tokens = ("gnd", "ground", "groud", "0v", "vss", "mass", "matt")
        return any(token in cid for token in ground_tokens)

    def _is_power_component(self, comp_id: str, component) -> bool:
        comp_type = self._component_type_value(component)
        if comp_type in ("voltage_source", "current_source"):
            return True

        cid = comp_id.strip().lower()
        power_tokens = ("vcc", "vdd", "v+", "vin", "vbat", "power", "source")
        return any(token in cid for token in power_tokens)

    def _place_centered_row(
        self,
        comp_ids: List[str],
        y: float,
        center_x: float,
    ) -> Dict[str, Tuple[float, float]]:
        if not comp_ids:
            return {}

        row: Dict[str, Tuple[float, float]] = {}
        count = len(comp_ids)
        first_x = center_x - ((count - 1) * self.COMP_SPACING / 2.0)
        for idx, comp_id in enumerate(comp_ids):
            row[comp_id] = (first_x + idx * self.COMP_SPACING, y)
        return row

    def _manual_pcb_position(self, component) -> Tuple[float, float] | None:
        render_style = getattr(component, "render_style", None)
        if not render_style:
            return None

        position = render_style.get("pcb_position")
        if not isinstance(position, dict):
            return None

        try:
            return (float(position.get("x")), float(position.get("y")))
        except (TypeError, ValueError):
            return None

    # ── Public API ─────────────────────────────────────────────

    def place_components(
        self,
        circuit: Circuit,
        hints: Dict[str, Tuple[float, float]] = None,
    ) -> Dict[str, Tuple[float, float]]:
        """Plan component placement on PCB.

        Returns  comp_id -> (x_mm, y_mm)  in board coordinates.
        """
        comp_ids = list(circuit.components.keys())
        if not comp_ids:
            return {}

        placements: Dict[str, Tuple[float, float]] = {}
        fixed_positions: Dict[str, Tuple[float, float]] = {}

        power_ids: List[str] = []
        ground_ids: List[str] = []
        normal_ids: List[str] = []

        for comp_id, component in circuit.components.items():
            if hints and comp_id in hints:
                fixed_positions[comp_id] = hints[comp_id]
                continue

            manual_pos = self._manual_pcb_position(component)
            if manual_pos is not None:
                fixed_positions[comp_id] = manual_pos
                continue

            if self._is_ground_component(comp_id, component):
                ground_ids.append(comp_id)
            elif self._is_power_component(comp_id, component):
                power_ids.append(comp_id)
            else:
                normal_ids.append(comp_id)

        # Place normal components row-major: left -> right, then top -> bottom.
        usable_left = self.MARGIN
        usable_right = self.BOARD_WIDTH - self.MARGIN
        usable_top = self.MARGIN + self.COMP_SPACING
        usable_bottom = self.BOARD_HEIGHT - self.MARGIN - self.COMP_SPACING

        normal_count = len(normal_ids)
        if normal_count > 0:
            width = max(1.0, usable_right - usable_left)
            max_cols_by_spacing = max(1, int(width // self.COMP_SPACING) + 1)
            cols = min(max_cols_by_spacing, max(1, int(math.ceil(math.sqrt(normal_count)))))
            rows = int(math.ceil(normal_count / cols))

            x_step = width / max(1, cols - 1)
            y_step = max(1.0, usable_bottom - usable_top) / max(1, rows - 1)

            for idx, comp_id in enumerate(normal_ids):
                col = idx % cols
                row = idx // cols
                x = usable_left + col * x_step
                y = usable_top + row * y_step
                placements[comp_id] = (x, y)

        center_x = self.BOARD_WIDTH / 2.0
        placements.update(self._place_centered_row(power_ids, self.MARGIN, center_x))
        placements.update(self._place_centered_row(ground_ids, self.BOARD_HEIGHT - self.MARGIN, center_x))

        placements.update(fixed_positions)

        placements = {
            cid: (self._snap(x), self._snap(y))
            for cid, (x, y) in placements.items()
        }

        return placements

    def plan_nets(
        self,
        circuit: Circuit,
    ) -> Dict[str, List[str]]:
        """Extract net connectivity using domain pin names.

        Returns  net_name -> ["Q1.C", "R1.1", …]
        """
        nets: Dict[str, List[str]] = {}
        for net_name, net in circuit.nets.items():
            pins = [f"{ref.component_id}.{ref.pin_name}"
                    for ref in net.connected_pins]
            if pins:
                nets[net_name] = pins
        return nets

    def plan_tracks(
        self,
        circuit: Circuit,
        placements: Dict[str, Tuple[float, float]],
        nets: Dict[str, List[str]],
    ) -> List[Dict]:
        """Plan PCB track routing (point-to-point between actual pad positions).

        Adds footprint pad offsets to component origins for accurate routing.
        """
        tracks: List[Dict] = []

        # Pre-compute absolute pad positions per component
        pad_positions = self._compute_pad_positions(circuit, placements)

        for net_name, net in circuit.nets.items():
            pins = list(net.connected_pins)
            for i in range(len(pins) - 1):
                from_key = f"{pins[i].component_id}.{pins[i].pin_name}"
                to_key = f"{pins[i + 1].component_id}.{pins[i + 1].pin_name}"

                from_pos = pad_positions.get(from_key)
                to_pos = pad_positions.get(to_key)
                if from_pos and to_pos:
                    tracks.append({
                        "start": from_pos,
                        "end": to_pos,
                        "net": net_name,
                        "layer": "F.Cu",
                        "width": 0.25,
                    })
        return tracks

    # ── Internal helpers ───────────────────────────────────────

    @staticmethod
    def _snap(v: float, grid: float = 1.27) -> float:
        return round(v / grid) * grid

    def _build_adjacency(self, circuit: Circuit) -> Dict[str, Dict[str, int]]:
        """Build weighted adjacency: adjacency[a][b] = # shared nets."""
        adj: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for net in circuit.nets.values():
            comp_ids = list({ref.component_id for ref in net.connected_pins})
            for i, a in enumerate(comp_ids):
                for b in comp_ids[i + 1:]:
                    adj[a][b] += 1
                    adj[b][a] += 1
        return adj

    def _classify(self, circuit: Circuit) -> Dict[str, List[str]]:
        """Classify components into placement groups."""
        groups: Dict[str, List[str]] = {
            "power": [],
            "active": [],
            "passive": [],
            "io": [],
        }
        for cid, comp in circuit.components.items():
            t = comp.type
            if t in (ComponentType.VOLTAGE_SOURCE, ComponentType.CURRENT_SOURCE,
                     ComponentType.GROUND):
                groups["power"].append(cid)
            elif t in (ComponentType.BJT, ComponentType.BJT_NPN, ComponentType.BJT_PNP,
                       ComponentType.MOSFET, ComponentType.MOSFET_N, ComponentType.MOSFET_P,
                       ComponentType.OPAMP):
                groups["active"].append(cid)
            elif t in (ComponentType.RESISTOR, ComponentType.CAPACITOR,
                       ComponentType.CAPACITOR_POLARIZED, ComponentType.INDUCTOR,
                       ComponentType.DIODE):
                groups["passive"].append(cid)
            else:
                groups["io"].append(cid)
        return groups

    def _initial_placement(
        self,
        comp_ids: List[str],
        groups: Dict[str, List[str]],
        adjacency: Dict[str, Dict[str, int]],
        circuit: Circuit,
    ) -> Dict[str, Tuple[float, float]]:
        """Create initial placement by placing each group in its zone then
           ordering components within each group by connectivity (BFS-like)."""
        placements: Dict[str, Tuple[float, float]] = {}
        W, H, M = self.BOARD_WIDTH, self.BOARD_HEIGHT, self.MARGIN

        # Zone rectangles  (x_min, y_min, x_max, y_max)
        zones = {
            "power": (M, M, M + 20, H - M),                 # left strip
            "io":    (W - M - 20, M, W - M, H - M),          # right strip
            "active": (M + 25, M + 5, W - M - 25, H - M - 5),  # centre
            "passive": (M + 25, M + 5, W - M - 25, H - M - 5), # centre (interleaved)
        }

        for group_name in ("power", "active", "passive", "io"):
            members = groups.get(group_name, [])
            if not members:
                continue

            # Sort members by total connectivity (most connected first)
            members.sort(key=lambda c: sum(adjacency.get(c, {}).values()), reverse=True)

            zx0, zy0, zx1, zy1 = zones[group_name]
            zw = zx1 - zx0
            zh = zy1 - zy0

            # Lay out in a grid within the zone
            n = len(members)
            cols = max(1, int(math.ceil(math.sqrt(n * zw / max(zh, 1)))))
            rows = max(1, math.ceil(n / cols))
            dx = zw / max(cols, 1)
            dy = zh / max(rows, 1)

            for idx, cid in enumerate(members):
                c = idx % cols
                r = idx // cols
                px = zx0 + dx * (c + 0.5)
                py = zy0 + dy * (r + 0.5)
                placements[cid] = (px, py)

        return placements

    def _force_directed(
        self,
        placements: Dict[str, Tuple[float, float]],
        adjacency: Dict[str, Dict[str, int]],
        iterations: int = 20,
    ) -> Dict[str, Tuple[float, float]]:
        """Simple spring-electric force-directed relaxation.

        Springs pull connected components together; a repulsive force
        prevents overlap.
        """
        pos = {cid: list(xy) for cid, xy in placements.items()}
        ids = list(pos.keys())
        n = len(ids)
        if n < 2:
            return placements

        k_attract = 0.05
        k_repel = 200.0
        damping = 0.8
        min_dist = self.COMP_SPACING

        for _ in range(iterations):
            forces: Dict[str, List[float]] = {cid: [0.0, 0.0] for cid in ids}

            # Repulsive forces (all pairs)
            for i in range(n):
                for j in range(i + 1, n):
                    a, b = ids[i], ids[j]
                    dx = pos[b][0] - pos[a][0]
                    dy = pos[b][1] - pos[a][1]
                    dist = math.hypot(dx, dy) or 0.1
                    if dist < min_dist * 3:
                        f = k_repel / (dist * dist)
                        fx = f * dx / dist
                        fy = f * dy / dist
                        forces[a][0] -= fx
                        forces[a][1] -= fy
                        forces[b][0] += fx
                        forces[b][1] += fy

            # Attractive forces (connected pairs)
            for a in ids:
                for b, weight in adjacency.get(a, {}).items():
                    if b not in pos:
                        continue
                    dx = pos[b][0] - pos[a][0]
                    dy = pos[b][1] - pos[a][1]
                    dist = math.hypot(dx, dy) or 0.1
                    f = k_attract * weight * dist
                    fx = f * dx / dist
                    fy = f * dy / dist
                    forces[a][0] += fx
                    forces[a][1] += fy

            # Apply forces with damping and clamping inside board bounds
            for cid in ids:
                pos[cid][0] += forces[cid][0] * damping
                pos[cid][1] += forces[cid][1] * damping
                pos[cid][0] = max(self.MARGIN, min(self.BOARD_WIDTH - self.MARGIN, pos[cid][0]))
                pos[cid][1] = max(self.MARGIN, min(self.BOARD_HEIGHT - self.MARGIN, pos[cid][1]))

        return {cid: (xy[0], xy[1]) for cid, xy in pos.items()}

    def _compute_pad_positions(
        self,
        circuit: Circuit,
        placements: Dict[str, Tuple[float, float]],
    ) -> Dict[str, Tuple[float, float]]:
        """Compute absolute (x, y) for every pad reference "comp_id.pin_name".

        Uses footprint pad offsets from the library so tracks connect to
        actual pad centres rather than component origins.
        """
        result: Dict[str, Tuple[float, float]] = {}

        for cid, comp in circuit.components.items():
            if cid not in placements:
                continue
            ox, oy = placements[cid]
            comp_type = comp.type.value if hasattr(comp.type, 'value') else str(comp.type)
            if str(comp_type).lower() in {"voltage_source", "current_source"} and len(getattr(comp, "pins", ()) or ()) <= 1:
                comp_type = "connector"

            pads = KiCadFootprintLibrary.get_pads(comp_type)
            pin_map = KiCadFootprintLibrary.get_pin_map(comp_type)

            # Build pad_number -> offset
            pad_offsets = {p["number"]: p["at"] for p in pads}

            # For each pin the circuit knows about, resolve to pad offset
            for pin_name in comp.pins:
                pad_num = pin_map.get(pin_name, pin_name)
                offset = pad_offsets.get(pad_num, (0, 0))
                result[f"{cid}.{pin_name}"] = (ox + offset[0], oy + offset[1])

        return result
