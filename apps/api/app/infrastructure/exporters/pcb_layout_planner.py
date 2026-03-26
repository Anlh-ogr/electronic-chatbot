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
from collections import defaultdict, deque
from typing import Dict, Tuple, List, Set

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
        cid = comp_id.strip().lower()
        if cid.startswith("vin") or cid.startswith("input"):
            return False

        comp_type = self._component_type_value(component)
        if comp_type in ("voltage_source", "current_source"):
            return True

        power_tokens = ("vcc", "vdd", "v+", "vbat", "power", "source")
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

    def place_components(self, circuit, hints=None):
        comp_ids = list(circuit.components.keys())
        if not comp_ids:
            return {}

        # Tách fixed positions
        fixed_positions = {}
        for cid, comp in circuit.components.items():
            if hints and cid in hints:
                fixed_positions[cid] = hints[cid]
            elif (pos := self._manual_pcb_position(comp)) is not None:
                fixed_positions[cid] = pos

        # Build graph
        adjacency = self._build_adjacency_map(circuit)

        # BFS pipeline (topology-agnostic)
        power_comps  = self._find_power_comps(circuit)
        sources      = self._find_signal_sources(circuit, power_comps)
        sinks        = self._find_signal_sinks(circuit, power_comps)

        # Fallback nếu không tìm được source
        if not sources:
            # Chọn node có bậc thấp nhất ngoài power làm source
            non_power = {c for c in comp_ids if c not in power_comps and c not in fixed_positions}
            if non_power:
                sources = {min(non_power, key=lambda c: sum(adjacency.get(c, {}).values()))}

        depth_map = self._compute_signal_depth(circuit, adjacency, sources, power_comps)

        # Chỉ xếp component chưa cố định vị trí
        to_place_set = {cid for cid in comp_ids if cid not in fixed_positions}
        depth_map = {cid: d for cid, d in depth_map.items() if cid in to_place_set}
        power_comps_to_place = power_comps & to_place_set

        # Initial placement theo depth
        placements = self._depth_based_placement(circuit, depth_map, power_comps_to_place, sinks)

        # Force-directed: kéo linh kiện có liên kết về gần nhau
        left_anchors  = sources | {c for c in sources if c in placements}  # sources bên trái
        right_anchors = sinks                                              # sinks bên phải
        placements = self._force_directed(
            placements, adjacency, iterations=40,
            left_anchors=left_anchors,
            right_anchors=right_anchors,
        )

        # Symmetry cho differential pairs
        branch_map = self._detect_branches(circuit)
        diff_pairs = self._detect_differential_pairs(circuit)
        placements = self._apply_symmetry(diff_pairs, branch_map, placements)

        # Restore fixed positions
        placements.update(fixed_positions)

        return {cid: (self._snap(x), self._snap(y))
                for cid, (x, y) in placements.items()}

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
            if len(pins) < 2:
                continue

            # Sắp xếp theo nearest-neighbor từ pin đầu tiên
            ordered = [pins[0]]
            remaining = pins[1:]

            while remaining:
                last_pos = pad_positions.get(f"{ordered[-1].component_id}.{ordered[-1].pin_name}")
                if last_pos is None:
                    ordered.append(remaining.pop(0))
                    continue
                
                nearest = min(remaining, key=lambda p: self._pin_dist(p, last_pos, pad_positions))
                ordered.append(nearest)
                remaining.remove(nearest)

            for i in range(len(ordered) - 1):
                from_key = f"{ordered[i].component_id}.{ordered[i].pin_name}"
                to_key = f"{ordered[i + 1].component_id}.{ordered[i + 1].pin_name}"

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
    def _pin_dist(p, from_pos: Tuple[float, float],
                  pad_positions: Dict[str, Tuple[float, float]]) -> float:
        key = f"{p.component_id}.{p.pin_name}"
        to_pos = pad_positions.get(key)
        if to_pos is None:
            return float("inf")
        return math.hypot(to_pos[0] - from_pos[0], to_pos[1] - from_pos[1])

    @staticmethod
    def _snap(v: float, grid: float = 1.27) -> float:
        return round(v / grid) * grid

    def _build_adjacency_map(self, circuit: Circuit) -> Dict[str, Dict[str, int]]:
        """Build weighted adjacency: adjacency[a][b] = # shared nets."""
        adj: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for net in circuit.nets.values():
            comp_ids = list({ref.component_id for ref in net.connected_pins})
            for i, a in enumerate(comp_ids):
                for b in comp_ids[i + 1:]:
                    adj[a][b] += 1
                    adj[b][a] += 1
        return adj

    def _detect_branches(self, circuit: Circuit) -> Dict[str, int]:
        """Phát hiện nhánh song song dựa trên shared nets."""
        branch_map: Dict[str, int] = {}
        groups = self._classify(circuit)
        active_comps = groups.get("active", [])

        # Build net → components map
        net_to_comps: Dict[str, Set[str]] = defaultdict(set)
        for net_name, net in circuit.nets.items():
            for p in net.connected_pins:
                net_to_comps[net_name].add(p.component_id)

        parallel_groups: List[List[str]] = []
        visited_pairs: Set[frozenset] = set()

        POWER_TOKENS = ("vcc", "vdd", "v+", "gnd", "ground", "vss", "0v")

        for i, cid_a in enumerate(active_comps):
            for j, cid_b in enumerate(active_comps):
                if i >= j:
                    continue
                pair = frozenset([cid_a, cid_b])
                if pair in visited_pairs:
                    continue

                shared_nets = self._find_shared_nets([cid_a], [cid_b], net_to_comps)
                signal_shared = {n for n in shared_nets
                                 if not any(tok in n.lower() for tok in POWER_TOKENS)}
                
                if len(signal_shared) >= 2:
                    visited_pairs.add(pair)
                    found = False
                    for group in parallel_groups:
                        if cid_a in group or cid_b in group:
                            if cid_a not in group: group.append(cid_a)
                            if cid_b not in group: group.append(cid_b)
                            found = True
                            break
                    if not found:
                        parallel_groups.append([cid_a, cid_b])

        for group in parallel_groups:
            for branch_idx, cid in enumerate(group):
                branch_map[cid] = branch_idx
                
        for cid in circuit.components.keys():
            if cid not in branch_map:
                branch_map[cid] = 0
                
        return branch_map

    def _find_shared_nets(self, comps_a: List[str], comps_b: List[str],
                          net_to_comps: Dict[str, Set[str]]) -> Set[str]:
        shared = set()
        set_a = set(comps_a)
        set_b = set(comps_b)
        for net_name, comps in net_to_comps.items():
            if comps & set_a and comps & set_b:
                shared.add(net_name)
        return shared

    def _detect_differential_pairs(self, circuit: Circuit) -> Set[str]:
        """Tìm các cặp linh kiện là differential pair."""
        diff_comps: Set[str] = set()
        groups = self._classify(circuit)
        active_comps = set(groups.get("active", []))

        tail_net_map: Dict[str, List[str]] = defaultdict(list)
        for net_name, net_obj in circuit.nets.items():
            for p in net_obj.connected_pins:
                if p.pin_name in ("E", "e", "S", "s") and p.component_id in active_comps:
                    tail_net_map[net_name].append(p.component_id)

        for net_name, comps in tail_net_map.items():
            if len(comps) == 2:
                diff_comps.add(comps[0])
                diff_comps.add(comps[1])

        return diff_comps

    def _apply_symmetry(self, diff_comps: Set[str], branch_map: Dict[str, int],
                        placements: Dict[str, Tuple[float, float]]) -> Dict[str, Tuple[float, float]]:
        """Áp symmetry - đối xứng các cặp differential pair qua trục."""
        result = dict(placements)
        valid_comps = [cid for cid in diff_comps if cid in placements]
        if len(valid_comps) < 2:
            return result

        # Tính trung tâm X và Y của cả cụm differential pair
        xs = [placements[c][0] for c in valid_comps]
        ys = [placements[c][1] for c in valid_comps]
        center_x = sum(xs) / len(xs)
        center_y = sum(ys) / len(ys)
        offset = self.COMP_SPACING  # khoảng cách mỗi branch so với center

        branch0 = [c for c in valid_comps if branch_map.get(c, 0) % 2 == 0]
        branch1 = [c for c in valid_comps if branch_map.get(c, 0) % 2 == 1]
        x_step = self.COMP_SPACING

        for idx, cid in enumerate(branch0):
            result[cid] = (center_x + x_step * (idx - len(branch0)/2 + 0.5), center_y - offset / 2)
        for idx, cid in enumerate(branch1):
            result[cid] = (center_x + x_step * (idx - len(branch1)/2 + 0.5), center_y + offset / 2)
                
        return result

    def _find_power_comps(self, circuit: Circuit) -> Set[str]:
        """Tổng quát: tìm power/ground bằng cả type lẫn net name."""
        power = set()
        POWER_NET_TOKENS = ("vcc", "vdd", "v+", "vbat", "gnd", "ground", "vss", "0v")
        for cid, comp in circuit.components.items():
            t = comp.type
            if t in (ComponentType.VOLTAGE_SOURCE, ComponentType.CURRENT_SOURCE,
                     ComponentType.GROUND):
                power.add(cid)
                continue
            # Nếu component này chỉ nối với power/ground nets → cũng là power
            comp_nets = {
                net.name.lower()
                for net in circuit.nets.values()
                if any(p.component_id == cid for p in net.connected_pins)
            }
            if comp_nets and all(
                any(tok in n for tok in POWER_NET_TOKENS) for n in comp_nets
            ):
                power.add(cid)
        return power

    def _find_signal_sources(self, circuit: Circuit,
                              power_comps: Set[str]) -> Set[str]:
        """Tổng quát: tìm nguồn tín hiệu bằng tên ID + type + vị trí trong graph."""
        sources = set()
        INPUT_TOKENS = ("vin", "input", "in", "src", "source", "sig")
        for cid, comp in circuit.components.items():
            if cid in power_comps:
                continue
            cid_l = cid.strip().lower()
            # Tên gợi ý input
            if any(cid_l.startswith(t) for t in INPUT_TOKENS):
                sources.add(cid)
                continue
            # Port/connector với 1 kết nối net ngoài power → signal source
            t = comp.type
            if t in (ComponentType.VOLTAGE_SOURCE, ComponentType.CURRENT_SOURCE):
                if cid not in power_comps:
                    sources.add(cid)
        # Fallback: nếu không tìm được sources, lấy node có bậc nhỏ nhất trong graph
        return sources

    def _find_signal_sinks(self, circuit: Circuit,
                            power_comps: Set[str]) -> Set[str]:
        """Tổng quát: tìm đích tín hiệu."""
        sinks = set()
        OUTPUT_TOKENS = ("vout", "output", "out", "load", "rl", "rload", "speaker")
        for cid in circuit.components:
            if cid in power_comps:
                continue
            cid_l = cid.strip().lower()
            if any(cid_l.startswith(t) for t in OUTPUT_TOKENS):
                sinks.add(cid)
        return sinks

    def _compute_signal_depth(
        self,
        circuit: Circuit,
        adjacency: Dict[str, Dict[str, int]],
        sources: Set[str],
        power_comps: Set[str],
    ) -> Dict[str, int]:
        """
        BFS từ signal sources qua adjacency (không đi qua power rails).
        Trả về {comp_id: depth}, depth = khoảng cách BFS từ source.
        Component không đến được → depth = max_depth (đặt về phía output).
        """
        depth: Dict[str, int] = {}
        queue: deque = deque()

        for src in sources:
            depth[src] = 0
            queue.append(src)

        while queue:
            curr = queue.popleft()
            for neighbor in adjacency.get(curr, {}):
                if neighbor in power_comps:
                    continue  # bỏ qua power rail trong BFS
                if neighbor not in depth:
                    depth[neighbor] = depth[curr] + 1
                    queue.append(neighbor)

        # Fallback: component không nằm trong BFS tree
        # (isolated hoặc chỉ nối với power) → gán depth trung bình
        all_non_power = [c for c in circuit.components if c not in power_comps]
        if all_non_power and depth:
            fallback_depth = max(depth.values()) // 2
            for cid in all_non_power:
                if cid not in depth:
                    depth[cid] = fallback_depth

        return depth

    def _classify(self, circuit: Circuit) -> Dict[str, List[str]]:
        """Classify components into placement groups."""
        groups: Dict[str, List[str]] = {
            "power": [],
            "active": [],
            "passive": [],
            "io_in": [],
            "io_out": [],
        }
        
        power_comps = self._find_power_comps(circuit)
        sources = self._find_signal_sources(circuit, power_comps)
        sinks = self._find_signal_sinks(circuit, power_comps)
        
        for cid, comp in circuit.components.items():
            t = comp.type
            if cid in power_comps:
                groups["power"].append(cid)
            elif cid in sources:
                groups["io_in"].append(cid)
            elif cid in sinks:
                groups["io_out"].append(cid)
            elif t in (ComponentType.BJT, ComponentType.BJT_NPN, ComponentType.BJT_PNP,
                       ComponentType.MOSFET, ComponentType.MOSFET_N, ComponentType.MOSFET_P,
                       ComponentType.OPAMP):
                groups["active"].append(cid)
            else:
                groups["passive"].append(cid)
        return groups

    def _depth_based_placement(
        self,
        circuit: Circuit,
        depth_map: Dict[str, int],
        power_comps: Set[str],
        sinks: Set[str],
    ) -> Dict[str, Tuple[float, float]]:
        """
        Gán tọa độ ban đầu:
        - X = lerp(MARGIN, BOARD_WIDTH-MARGIN) theo depth
        - Y = phân bổ đều các comp cùng depth theo chiều dọc
        - Power comps: trải đều theo Y ở X = MARGIN+10 (left power strip)
        """
        W, H, M = self.BOARD_WIDTH, self.BOARD_HEIGHT, self.MARGIN
        usable_x0 = M + 20   # để chỗ cho power strip bên trái
        usable_x1 = W - M - 5

        placements: Dict[str, Tuple[float, float]] = {}

        if not depth_map:
            return placements

        max_depth = max(depth_map.values()) if depth_map else 1

        # Nhóm theo depth
        by_depth: Dict[int, List[str]] = defaultdict(list)
        for cid, d in depth_map.items():
            by_depth[d].append(cid)

        # Sắp xếp trong mỗi depth: active trước, passive sau
        ACTIVE_TYPES = {ComponentType.BJT, ComponentType.BJT_NPN, ComponentType.BJT_PNP,
                        ComponentType.MOSFET, ComponentType.MOSFET_N, ComponentType.MOSFET_P,
                        ComponentType.OPAMP}

        def _priority(cid: str) -> int:
            comp = circuit.components.get(cid)
            if comp and comp.type in ACTIVE_TYPES:
                return 0   # active first
            if cid in sinks:
                return 2   # output last
            return 1

        for d, members in by_depth.items():
            members.sort(key=_priority)

        # Gán tọa độ
        for d, members in sorted(by_depth.items()):
            if max_depth == 0:
                x = (usable_x0 + usable_x1) / 2
            else:
                x = usable_x0 + (d / max_depth) * (usable_x1 - usable_x0)

            n = len(members)
            for i, cid in enumerate(members):
                y = M + ((i + 0.5) / n) * (H - 2 * M)
                placements[cid] = (x, y)

        # Power comps: left vertical strip
        power_list = sorted(power_comps & set(circuit.components.keys()))
        n_pwr = len(power_list)
        for i, cid in enumerate(power_list):
            x = M + 5
            y = M + ((i + 0.5) / max(n_pwr, 1)) * (H - 2 * M)
            placements[cid] = (x, y)

        return placements

    def _force_directed(
        self,
        placements: Dict[str, Tuple[float, float]],
        adjacency: Dict[str, Dict[str, int]],
        iterations: int = 20,
        left_anchors: Set[str] = None,
        right_anchors: Set[str] = None,
    ) -> Dict[str, Tuple[float, float]]:
        """Simple spring-electric force-directed relaxation.

        Springs pull connected components together; a repulsive force
        prevents overlap. Anchors ensure signal flow direction.
        """
        pos = {cid: list(xy) for cid, xy in placements.items()}
        ids = list(pos.keys())
        n = len(ids)
        if n < 2:
            return placements

        k_attract = 0.025  # Giảm từ 0.05 -> bù lại việc tính đôi
        k_repel = 200.0
        damping = 0.8
        min_dist = self.COMP_SPACING
        
        k_anchor = 0.1  # lực kéo về vị trí anchor
        target_left_x = self.MARGIN + 10
        target_right_x = self.BOARD_WIDTH - self.MARGIN - 10

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

            # Anchor force: ghim Vin về trái, Vout về phải
            for cid in ids:
                if left_anchors and cid in left_anchors:
                    forces[cid][0] += k_anchor * (target_left_x - pos[cid][0])
                elif right_anchors and cid in right_anchors:
                    forces[cid][0] += k_anchor * (target_right_x - pos[cid][0])

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
