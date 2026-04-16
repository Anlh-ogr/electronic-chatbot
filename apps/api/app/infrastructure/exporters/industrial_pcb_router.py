from __future__ import annotations

import heapq
import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


GridNode = Tuple[int, int, int]  # (gx, gy, layer_idx)
PointMM = Tuple[float, float]


class IndustrialPCBRouter:
    """Industrial-style PCB router with phased optimization pipeline.

    Implemented phases:
    1. DRC-aware A* routing with obstacle map and via penalty.
    2. Multi-pass rip-up/reroute with congestion-aware cost.
    3. Differential-pair skew tuning by adding meander segments.
    4. Power integrity analysis with zone candidates and return-path scoring.
    """

    LAYERS = ("F.Cu", "B.Cu")

    def __init__(
        self,
        *,
        board_width: float,
        board_height: float,
        margin: float,
        grid_step: float = 1.27,
    ) -> None:
        self.board_width = float(board_width)
        self.board_height = float(board_height)
        self.margin = float(margin)
        self.grid_step = float(grid_step)

    def route(
        self,
        *,
        placements: Dict[str, PointMM],
        nets: Dict[str, List[str]],
        pad_positions: Dict[str, PointMM],
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
        options = dict(options or {})
        progress_cb = options.get("_progress_callback")

        clearance_mm = max(float(options.get("clearance_mm", 0.35)), 0.1)
        track_width_mm = max(float(options.get("track_width_mm", 0.25)), 0.1)
        via_penalty = max(float(options.get("via_penalty", 12.0)), 0.0)
        max_passes = max(int(options.get("industrial_passes", 3)), 1)
        diff_tolerance = max(float(options.get("diff_pair_tolerance_mm", 1.0)), 0.0)
        enable_power_zones = bool(options.get("enable_power_zones", False))
        objective_weights = self._resolve_objective_weights(options)

        self._emit_progress(
            progress_cb,
            phase="phase1_drc_astar",
            phase_index=1,
            progress=5.0,
            message="Preparing DRC-aware A* routing",
            status="running",
        )

        net_edges = self._build_net_edges(nets=nets, pad_positions=pad_positions)
        obstacle_cells = self._build_obstacle_cells(
            placements=placements,
            pad_positions=pad_positions,
            clearance_mm=clearance_mm,
        )

        phase1_routes, occupancy, phase1_report = self._phase1_astar(
            net_edges=net_edges,
            pad_positions=pad_positions,
            obstacle_cells=obstacle_cells,
            track_width_mm=track_width_mm,
            via_penalty=via_penalty,
        )

        self._emit_progress(
            progress_cb,
            phase="phase1_drc_astar",
            phase_index=1,
            progress=30.0,
            message="Phase 1 completed",
            status=phase1_report.get("status", "completed"),
            details=phase1_report,
        )

        self._emit_progress(
            progress_cb,
            phase="phase2_ripup_reroute",
            phase_index=2,
            progress=35.0,
            message="Starting rip-up/reroute optimization",
            status="running",
        )

        phase2_routes, occupancy, phase2_report = self._phase2_ripup_reroute(
            routes=phase1_routes,
            net_edges=net_edges,
            pad_positions=pad_positions,
            obstacle_cells=obstacle_cells,
            occupancy=occupancy,
            via_penalty=via_penalty,
            track_width_mm=track_width_mm,
            max_passes=max_passes,
        )

        self._emit_progress(
            progress_cb,
            phase="phase2_ripup_reroute",
            phase_index=2,
            progress=60.0,
            message="Phase 2 completed",
            status=phase2_report.get("status", "completed"),
            details=phase2_report,
        )

        self._emit_progress(
            progress_cb,
            phase="phase3_diff_pair_tuning",
            phase_index=3,
            progress=65.0,
            message="Starting differential pair tuning",
            status="running",
        )

        phase3_report = self._phase3_tune_diff_pairs(
            routes=phase2_routes,
            tolerance_mm=diff_tolerance,
            track_width_mm=track_width_mm,
        )

        self._emit_progress(
            progress_cb,
            phase="phase3_diff_pair_tuning",
            phase_index=3,
            progress=80.0,
            message="Phase 3 completed",
            status=phase3_report.get("status", "completed"),
            details=phase3_report,
        )

        self._emit_progress(
            progress_cb,
            phase="phase4_power_integrity",
            phase_index=4,
            progress=85.0,
            message="Starting power integrity checks",
            status="running",
        )

        zones, phase4_report = self._phase4_power_integrity(
            nets=nets,
            enable_power_zones=enable_power_zones,
            occupancy=occupancy,
        )

        self._emit_progress(
            progress_cb,
            phase="phase4_power_integrity",
            phase_index=4,
            progress=95.0,
            message="Phase 4 completed",
            status=phase4_report.get("status", "completed"),
            details=phase4_report,
        )

        all_segments = self._collect_segments(phase2_routes)
        metrics = self._build_metrics(
            routes=phase2_routes,
            occupancy=occupancy,
            diff_pair_report=phase3_report,
            power_report=phase4_report,
        )
        objective = self._evaluate_objective(metrics=metrics, weights=objective_weights)

        report = {
            "routing_mode": "industrial",
            "phases": {
                "phase1_drc_astar": phase1_report,
                "phase2_ripup_reroute": phase2_report,
                "phase3_diff_pair_tuning": phase3_report,
                "phase4_power_integrity": phase4_report,
            },
            "metrics": metrics,
            "objective": objective,
            "weights": objective_weights,
        }

        self._emit_progress(
            progress_cb,
            phase="completed",
            phase_index=4,
            progress=100.0,
            message="Industrial routing completed",
            status="completed",
            details={
                "objective": objective,
                "metrics": metrics,
            },
        )

        return all_segments, report, zones

    @staticmethod
    def _emit_progress(
        callback: Any,
        *,
        phase: str,
        phase_index: int,
        progress: float,
        message: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not callable(callback):
            return

        payload = {
            "phase": phase,
            "phase_index": int(phase_index),
            "total_phases": 4,
            "progress": float(progress),
            "status": str(status),
            "message": str(message),
        }
        if details is not None:
            payload["details"] = details

        try:
            callback(payload)
        except Exception:
            return

    def _phase1_astar(
        self,
        *,
        net_edges: Dict[str, List[Tuple[str, str]]],
        pad_positions: Dict[str, PointMM],
        obstacle_cells: Set[Tuple[int, int]],
        track_width_mm: float,
        via_penalty: float,
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[GridNode, int], Dict[str, Any]]:
        routes: Dict[str, Dict[str, Any]] = {}
        occupancy: Dict[GridNode, int] = defaultdict(int)

        routed_edges = 0
        failed_edges = 0
        drc_blocks = 0

        for net_name, edges in net_edges.items():
            route = {
                "segments": [],
                "paths": [],
                "length": 0.0,
                "via_count": 0,
            }

            for from_ref, to_ref in edges:
                start = pad_positions.get(from_ref)
                goal = pad_positions.get(to_ref)
                if not start or not goal:
                    failed_edges += 1
                    continue

                path = self._astar_route(
                    start_mm=start,
                    goal_mm=goal,
                    obstacle_cells=obstacle_cells,
                    occupancy=occupancy,
                    via_penalty=via_penalty,
                    congestion_weight=2.5,
                    allow_obstacle_endpoints=True,
                )
                if not path:
                    drc_blocks += 1
                    path = self._fallback_manhattan_path(start_mm=start, goal_mm=goal)

                if not path:
                    failed_edges += 1
                    continue

                segs, seg_len, seg_vias = self._path_to_segments(
                    path=path,
                    net_name=net_name,
                    width_mm=track_width_mm,
                )
                route["segments"].extend(segs)
                route["paths"].append(path)
                route["length"] += seg_len
                route["via_count"] += seg_vias
                self._add_path_to_occupancy(path, occupancy)
                routed_edges += 1

            routes[net_name] = route

        report = {
            "name": "phase1_drc_astar",
            "status": "completed",
            "routed_edges": routed_edges,
            "failed_edges": failed_edges,
            "drc_block_events": drc_blocks,
        }
        return routes, occupancy, report

    def _phase2_ripup_reroute(
        self,
        *,
        routes: Dict[str, Dict[str, Any]],
        net_edges: Dict[str, List[Tuple[str, str]]],
        pad_positions: Dict[str, PointMM],
        obstacle_cells: Set[Tuple[int, int]],
        occupancy: Dict[GridNode, int],
        via_penalty: float,
        track_width_mm: float,
        max_passes: int,
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[GridNode, int], Dict[str, Any]]:
        if max_passes <= 1:
            return routes, occupancy, {
                "name": "phase2_ripup_reroute",
                "status": "skipped",
                "passes": 0,
                "rerouted_nets": 0,
            }

        rerouted_nets_total = 0
        pass_summaries: List[Dict[str, Any]] = []

        for pass_idx in range(1, max_passes):
            net_costs = self._net_costs(routes=routes, occupancy=occupancy)
            if not net_costs:
                break

            reroute_count = max(1, len(net_costs) // 3)
            worst_nets = [name for name, _ in sorted(net_costs.items(), key=lambda item: item[1], reverse=True)[:reroute_count]]

            pass_rerouted = 0
            pass_failed = 0
            congestion_weight = 2.5 + pass_idx * 1.5

            for net_name in worst_nets:
                old_route = routes.get(net_name)
                if not old_route:
                    continue

                for old_path in old_route.get("paths", []):
                    self._remove_path_from_occupancy(old_path, occupancy)

                new_route = {
                    "segments": [],
                    "paths": [],
                    "length": 0.0,
                    "via_count": 0,
                }

                edges = net_edges.get(net_name, [])
                for from_ref, to_ref in edges:
                    start = pad_positions.get(from_ref)
                    goal = pad_positions.get(to_ref)
                    if not start or not goal:
                        pass_failed += 1
                        continue

                    path = self._astar_route(
                        start_mm=start,
                        goal_mm=goal,
                        obstacle_cells=obstacle_cells,
                        occupancy=occupancy,
                        via_penalty=via_penalty,
                        congestion_weight=congestion_weight,
                        allow_obstacle_endpoints=True,
                    )
                    if not path:
                        path = self._fallback_manhattan_path(start_mm=start, goal_mm=goal)

                    if not path:
                        pass_failed += 1
                        continue

                    segs, seg_len, seg_vias = self._path_to_segments(
                        path=path,
                        net_name=net_name,
                        width_mm=track_width_mm,
                    )
                    new_route["segments"].extend(segs)
                    new_route["paths"].append(path)
                    new_route["length"] += seg_len
                    new_route["via_count"] += seg_vias
                    self._add_path_to_occupancy(path, occupancy)

                routes[net_name] = new_route
                pass_rerouted += 1

            rerouted_nets_total += pass_rerouted
            pass_summaries.append(
                {
                    "pass": pass_idx,
                    "rerouted_nets": pass_rerouted,
                    "failed_edges": pass_failed,
                    "congestion_weight": round(congestion_weight, 3),
                }
            )

        report = {
            "name": "phase2_ripup_reroute",
            "status": "completed",
            "passes": max(0, max_passes - 1),
            "rerouted_nets": rerouted_nets_total,
            "details": pass_summaries,
        }
        return routes, occupancy, report

    def _phase3_tune_diff_pairs(
        self,
        *,
        routes: Dict[str, Dict[str, Any]],
        tolerance_mm: float,
        track_width_mm: float,
    ) -> Dict[str, Any]:
        diff_pairs = self._detect_diff_pair_nets(routes.keys())
        tuned_pairs: List[Dict[str, Any]] = []

        for net_p, net_n in diff_pairs:
            route_p = routes.get(net_p)
            route_n = routes.get(net_n)
            if not route_p or not route_n:
                continue

            len_p = float(route_p.get("length", 0.0))
            len_n = float(route_n.get("length", 0.0))
            skew = abs(len_p - len_n)

            if skew <= tolerance_mm:
                tuned_pairs.append(
                    {
                        "pair": [net_p, net_n],
                        "status": "within_tolerance",
                        "skew_mm": round(skew, 4),
                    }
                )
                continue

            short_name = net_p if len_p < len_n else net_n
            long_name = net_n if short_name == net_p else net_p
            delta = skew - tolerance_mm
            added = self._append_meander(
                route=routes[short_name],
                net_name=short_name,
                needed_extra_mm=delta,
                width_mm=track_width_mm,
            )

            tuned_pairs.append(
                {
                    "pair": [net_p, net_n],
                    "status": "tuned" if added > 0 else "unable_to_tune",
                    "short_net": short_name,
                    "long_net": long_name,
                    "skew_before_mm": round(skew, 4),
                    "added_length_mm": round(added, 4),
                }
            )

        max_skew = 0.0
        for pair in diff_pairs:
            rp = routes.get(pair[0])
            rn = routes.get(pair[1])
            if rp and rn:
                max_skew = max(max_skew, abs(float(rp.get("length", 0.0)) - float(rn.get("length", 0.0))))

        return {
            "name": "phase3_diff_pair_tuning",
            "status": "completed",
            "pair_count": len(diff_pairs),
            "max_skew_mm": round(max_skew, 4),
            "tolerance_mm": round(tolerance_mm, 4),
            "details": tuned_pairs,
        }

    def _phase4_power_integrity(
        self,
        *,
        nets: Dict[str, List[str]],
        enable_power_zones: bool,
        occupancy: Dict[GridNode, int],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        ground_nets = [name for name in nets if self._is_ground_net(name)]
        power_nets = [name for name in nets if self._is_power_net(name)]

        zones: List[Dict[str, Any]] = []
        if enable_power_zones:
            for net_name in sorted(set(ground_nets + power_nets)):
                zones.append(
                    {
                        "net": net_name,
                        "layer": "F.Cu",
                        "clearance": 0.3,
                        "polygon": [
                            (self.margin, self.margin),
                            (self.board_width - self.margin, self.margin),
                            (self.board_width - self.margin, self.board_height - self.margin),
                            (self.margin, self.board_height - self.margin),
                        ],
                    }
                )

        congested_cells = sum(1 for usage in occupancy.values() if usage > 1)
        total_cells = max(1, len(occupancy))
        congestion_ratio = congested_cells / total_cells

        # A simple return-path proxy: if no ground net is present, penalize strongly.
        return_path_penalty = 1.0 if not ground_nets else min(1.0, congestion_ratio * 2.0)
        power_penalty = 0.0
        if enable_power_zones and not zones:
            power_penalty = 1.0

        report = {
            "name": "phase4_power_integrity",
            "status": "completed",
            "ground_nets": ground_nets,
            "power_nets": power_nets,
            "zones_planned": len(zones),
            "return_path_penalty": round(return_path_penalty, 4),
            "power_integrity_penalty": round(power_penalty, 4),
        }
        return zones, report

    def _build_net_edges(
        self,
        *,
        nets: Dict[str, List[str]],
        pad_positions: Dict[str, PointMM],
    ) -> Dict[str, List[Tuple[str, str]]]:
        result: Dict[str, List[Tuple[str, str]]] = {}
        for net_name, refs in nets.items():
            available = [ref for ref in refs if ref in pad_positions]
            if len(available) < 2:
                result[net_name] = []
                continue

            ordered = [available[0]]
            remaining = available[1:]
            while remaining:
                last = ordered[-1]
                last_xy = pad_positions[last]
                nearest_idx = min(
                    range(len(remaining)),
                    key=lambda idx: self._distance(last_xy, pad_positions[remaining[idx]]),
                )
                ordered.append(remaining.pop(nearest_idx))

            result[net_name] = [
                (ordered[idx], ordered[idx + 1])
                for idx in range(len(ordered) - 1)
            ]

        return result

    def _build_obstacle_cells(
        self,
        *,
        placements: Dict[str, PointMM],
        pad_positions: Dict[str, PointMM],
        clearance_mm: float,
    ) -> Set[Tuple[int, int]]:
        blocked: Set[Tuple[int, int]] = set()
        radius = max(clearance_mm + 1.25, self.grid_step)

        for x, y in placements.values():
            blocked.update(self._circle_cells(x=x, y=y, radius_mm=radius))

        for x, y in pad_positions.values():
            blocked.update(self._circle_cells(x=x, y=y, radius_mm=clearance_mm))

        return blocked

    def _astar_route(
        self,
        *,
        start_mm: PointMM,
        goal_mm: PointMM,
        obstacle_cells: Set[Tuple[int, int]],
        occupancy: Dict[GridNode, int],
        via_penalty: float,
        congestion_weight: float,
        allow_obstacle_endpoints: bool,
    ) -> Optional[List[GridNode]]:
        start_xy = self._to_grid_point(start_mm)
        goal_xy = self._to_grid_point(goal_mm)

        start = (start_xy[0], start_xy[1], 0)
        goals = {(goal_xy[0], goal_xy[1], 0), (goal_xy[0], goal_xy[1], 1)}

        blocked = obstacle_cells
        if allow_obstacle_endpoints:
            blocked = set(obstacle_cells)
            blocked.discard(start_xy)
            blocked.discard(goal_xy)

        open_heap: List[Tuple[float, GridNode]] = []
        heapq.heappush(open_heap, (0.0, start))

        g_score: Dict[GridNode, float] = {start: 0.0}
        came_from: Dict[GridNode, GridNode] = {}

        max_iterations = 50000
        iterations = 0

        while open_heap and iterations < max_iterations:
            iterations += 1
            _, current = heapq.heappop(open_heap)
            if current in goals:
                return self._reconstruct_path(came_from, current)

            for neighbor, step_cost in self._neighbors(
                node=current,
                blocked=blocked,
                occupancy=occupancy,
                via_penalty=via_penalty,
                congestion_weight=congestion_weight,
            ):
                tentative = g_score[current] + step_cost
                if tentative >= g_score.get(neighbor, float("inf")):
                    continue

                came_from[neighbor] = current
                g_score[neighbor] = tentative
                f_score = tentative + self._heuristic(neighbor, goal_xy)
                heapq.heappush(open_heap, (f_score, neighbor))

        return None

    def _neighbors(
        self,
        *,
        node: GridNode,
        blocked: Set[Tuple[int, int]],
        occupancy: Dict[GridNode, int],
        via_penalty: float,
        congestion_weight: float,
    ) -> Iterable[Tuple[GridNode, float]]:
        gx, gy, layer = node

        # Horizontal/vertical moves on same layer.
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx = gx + dx
            ny = gy + dy
            if not self._is_inside_grid(nx, ny):
                continue
            if (nx, ny) in blocked:
                continue
            nnode = (nx, ny, layer)
            usage = occupancy.get(nnode, 0)
            step_cost = self.grid_step + congestion_weight * usage
            yield nnode, step_cost

        # Via move keeps XY and changes layer.
        other_layer = 1 - layer
        via_node = (gx, gy, other_layer)
        via_usage = occupancy.get(via_node, 0)
        yield via_node, via_penalty + congestion_weight * via_usage

    def _fallback_manhattan_path(self, *, start_mm: PointMM, goal_mm: PointMM) -> Optional[List[GridNode]]:
        sx, sy = self._to_grid_point(start_mm)
        gx, gy = self._to_grid_point(goal_mm)

        path: List[GridNode] = [(sx, sy, 0)]
        cx, cy = sx, sy

        x_step = 1 if gx >= cx else -1
        while cx != gx:
            cx += x_step
            if not self._is_inside_grid(cx, cy):
                return None
            path.append((cx, cy, 0))

        y_step = 1 if gy >= cy else -1
        while cy != gy:
            cy += y_step
            if not self._is_inside_grid(cx, cy):
                return None
            path.append((cx, cy, 0))

        return path

    def _path_to_segments(
        self,
        *,
        path: Sequence[GridNode],
        net_name: str,
        width_mm: float,
    ) -> Tuple[List[Dict[str, Any]], float, int]:
        if len(path) < 2:
            return [], 0.0, 0

        segments: List[Dict[str, Any]] = []
        length = 0.0
        via_count = 0

        for idx in range(1, len(path)):
            prev = path[idx - 1]
            curr = path[idx]

            if prev[0] == curr[0] and prev[1] == curr[1] and prev[2] != curr[2]:
                via_count += 1
                continue

            start_xy = self._to_mm_point(prev[0], prev[1])
            end_xy = self._to_mm_point(curr[0], curr[1])
            seg_len = self._distance(start_xy, end_xy)
            length += seg_len

            segments.append(
                {
                    "start": start_xy,
                    "end": end_xy,
                    "net": net_name,
                    "layer": self.LAYERS[prev[2]],
                    "width": width_mm,
                }
            )

        return segments, length, via_count

    def _add_path_to_occupancy(self, path: Sequence[GridNode], occupancy: Dict[GridNode, int]) -> None:
        for node in path:
            occupancy[node] = occupancy.get(node, 0) + 1

    def _remove_path_from_occupancy(self, path: Sequence[GridNode], occupancy: Dict[GridNode, int]) -> None:
        for node in path:
            current = occupancy.get(node, 0)
            if current <= 1:
                occupancy.pop(node, None)
            else:
                occupancy[node] = current - 1

    def _net_costs(self, *, routes: Dict[str, Dict[str, Any]], occupancy: Dict[GridNode, int]) -> Dict[str, float]:
        congested = set(node for node, usage in occupancy.items() if usage > 1)
        costs: Dict[str, float] = {}

        for net_name, route in routes.items():
            base = float(route.get("length", 0.0)) + float(route.get("via_count", 0)) * 8.0
            congestion_hits = 0
            for path in route.get("paths", []):
                for node in path:
                    if node in congested:
                        congestion_hits += 1
            costs[net_name] = base + congestion_hits * 2.5

        return costs

    def _detect_diff_pair_nets(self, net_names: Iterable[str]) -> List[Tuple[str, str]]:
        groups: Dict[str, Dict[str, str]] = defaultdict(dict)

        for name in sorted(set(net_names)):
            lname = name.lower()
            if lname.endswith("_p"):
                groups[lname[:-2]]["p"] = name
            elif lname.endswith("_n"):
                groups[lname[:-2]]["n"] = name
            elif lname.endswith("+"):
                groups[lname[:-1]]["p"] = name
            elif lname.endswith("-"):
                groups[lname[:-1]]["n"] = name

        pairs: List[Tuple[str, str]] = []
        for group in groups.values():
            if "p" in group and "n" in group:
                pairs.append((group["p"], group["n"]))
        return pairs

    def _append_meander(
        self,
        *,
        route: Dict[str, Any],
        net_name: str,
        needed_extra_mm: float,
        width_mm: float,
    ) -> float:
        if needed_extra_mm <= 0:
            return 0.0

        segments: List[Dict[str, Any]] = route.get("segments", [])
        if not segments:
            return 0.0

        last = segments[-1]
        x, y = last["end"]
        layer = last.get("layer", "F.Cu")

        added = 0.0
        loops = 0

        while added < needed_extra_mm and loops < 8:
            loops += 1
            run = min(max(self.grid_step, (needed_extra_mm - added) / 3.0), 5.0)
            amp = min(max(self.grid_step, run / 2.0), 3.0)

            x1 = self._clamp_x(x + run)
            y1 = y
            x2 = x1
            y2 = self._clamp_y(y1 + amp)
            x3 = self._clamp_x(x)
            y3 = y2

            s1 = {"start": (x, y), "end": (x1, y1), "net": net_name, "layer": layer, "width": width_mm}
            s2 = {"start": (x1, y1), "end": (x2, y2), "net": net_name, "layer": layer, "width": width_mm}
            s3 = {"start": (x2, y2), "end": (x3, y3), "net": net_name, "layer": layer, "width": width_mm}

            for seg in (s1, s2, s3):
                seg_len = self._distance(seg["start"], seg["end"])
                if seg_len <= 0:
                    continue
                segments.append(seg)
                route["length"] = float(route.get("length", 0.0)) + seg_len
                added += seg_len

            x, y = x3, y3

        return added

    def _collect_segments(self, routes: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        all_segments: List[Dict[str, Any]] = []
        for route in routes.values():
            all_segments.extend(route.get("segments", []))
        return all_segments

    def _build_metrics(
        self,
        *,
        routes: Dict[str, Dict[str, Any]],
        occupancy: Dict[GridNode, int],
        diff_pair_report: Dict[str, Any],
        power_report: Dict[str, Any],
    ) -> Dict[str, Any]:
        total_length = 0.0
        total_vias = 0
        routed_nets = 0
        for route in routes.values():
            if route.get("segments"):
                routed_nets += 1
            total_length += float(route.get("length", 0.0))
            total_vias += int(route.get("via_count", 0))

        congested_cells = sum(1 for usage in occupancy.values() if usage > 1)
        total_cells = max(1, len(occupancy))
        congestion_ratio = congested_cells / total_cells

        return {
            "routed_nets": routed_nets,
            "total_nets": len(routes),
            "completion_ratio": round(routed_nets / max(1, len(routes)), 4),
            "total_length_mm": round(total_length, 4),
            "via_count": total_vias,
            "congestion_ratio": round(congestion_ratio, 4),
            "max_diff_skew_mm": float(diff_pair_report.get("max_skew_mm", 0.0)),
            "return_path_penalty": float(power_report.get("return_path_penalty", 0.0)),
            "power_integrity_penalty": float(power_report.get("power_integrity_penalty", 0.0)),
        }

    def _resolve_objective_weights(self, options: Dict[str, Any]) -> Dict[str, float]:
        profile = str(options.get("objective_profile", "balanced")).strip().lower()

        presets: Dict[str, Dict[str, float]] = {
            "balanced": {
                "length": 0.25,
                "via": 0.2,
                "congestion": 0.2,
                "skew": 0.15,
                "return_path": 0.1,
                "power_integrity": 0.1,
            },
            "shortest": {
                "length": 0.45,
                "via": 0.2,
                "congestion": 0.15,
                "skew": 0.1,
                "return_path": 0.05,
                "power_integrity": 0.05,
            },
            "low_via": {
                "length": 0.2,
                "via": 0.45,
                "congestion": 0.15,
                "skew": 0.1,
                "return_path": 0.05,
                "power_integrity": 0.05,
            },
            "low_congestion": {
                "length": 0.2,
                "via": 0.15,
                "congestion": 0.45,
                "skew": 0.1,
                "return_path": 0.05,
                "power_integrity": 0.05,
            },
            "signal_integrity": {
                "length": 0.2,
                "via": 0.15,
                "congestion": 0.2,
                "skew": 0.25,
                "return_path": 0.1,
                "power_integrity": 0.1,
            },
        }

        weights = dict(presets.get(profile, presets["balanced"]))

        custom = options.get("objective_weights")
        if isinstance(custom, dict):
            for key in list(weights.keys()):
                value = custom.get(key)
                if value is None:
                    continue
                try:
                    weights[key] = max(float(value), 0.0)
                except (TypeError, ValueError):
                    continue

            total = sum(weights.values())
            if total > 0:
                for key in list(weights.keys()):
                    weights[key] = weights[key] / total

        return {k: round(v, 6) for k, v in weights.items()}

    def _evaluate_objective(self, *, metrics: Dict[str, Any], weights: Dict[str, float]) -> Dict[str, Any]:
        length_norm = float(metrics.get("total_length_mm", 0.0)) / max(1.0, float(metrics.get("total_nets", 1)) * 30.0)
        via_norm = float(metrics.get("via_count", 0.0)) / max(1.0, float(metrics.get("total_nets", 1)) * 3.0)
        congestion_norm = float(metrics.get("congestion_ratio", 0.0))
        skew_norm = float(metrics.get("max_diff_skew_mm", 0.0)) / 5.0
        return_norm = float(metrics.get("return_path_penalty", 0.0))
        power_norm = float(metrics.get("power_integrity_penalty", 0.0))

        normalized = {
            "length": max(length_norm, 0.0),
            "via": max(via_norm, 0.0),
            "congestion": max(congestion_norm, 0.0),
            "skew": max(skew_norm, 0.0),
            "return_path": max(return_norm, 0.0),
            "power_integrity": max(power_norm, 0.0),
        }

        score = 0.0
        for key, value in normalized.items():
            score += float(weights.get(key, 0.0)) * value

        return {
            "score": round(score, 6),
            "normalized_terms": {k: round(v, 6) for k, v in normalized.items()},
        }

    def _heuristic(self, node: GridNode, goal_xy: Tuple[int, int]) -> float:
        return (abs(node[0] - goal_xy[0]) + abs(node[1] - goal_xy[1])) * self.grid_step

    def _reconstruct_path(self, came_from: Dict[GridNode, GridNode], current: GridNode) -> List[GridNode]:
        path = [current]
        while current in came_from:
            current = came_from[current]
            path.append(current)
        path.reverse()
        return path

    def _circle_cells(self, *, x: float, y: float, radius_mm: float) -> Set[Tuple[int, int]]:
        cx, cy = self._to_grid_point((x, y))
        r = max(1, int(math.ceil(radius_mm / self.grid_step)))
        cells: Set[Tuple[int, int]] = set()

        for gx in range(cx - r, cx + r + 1):
            for gy in range(cy - r, cy + r + 1):
                if not self._is_inside_grid(gx, gy):
                    continue
                dx = gx - cx
                dy = gy - cy
                if dx * dx + dy * dy <= r * r:
                    cells.add((gx, gy))

        return cells

    def _to_grid_point(self, pt: PointMM) -> Tuple[int, int]:
        return (
            int(round(float(pt[0]) / self.grid_step)),
            int(round(float(pt[1]) / self.grid_step)),
        )

    def _to_mm_point(self, gx: int, gy: int) -> PointMM:
        return (round(gx * self.grid_step, 6), round(gy * self.grid_step, 6))

    def _is_inside_grid(self, gx: int, gy: int) -> bool:
        x = gx * self.grid_step
        y = gy * self.grid_step
        return (
            self.margin <= x <= (self.board_width - self.margin)
            and self.margin <= y <= (self.board_height - self.margin)
        )

    @staticmethod
    def _distance(a: PointMM, b: PointMM) -> float:
        return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))

    @staticmethod
    def _is_ground_net(net_name: str) -> bool:
        lname = (net_name or "").strip().lower()
        return any(token in lname for token in ("gnd", "ground", "vss", "0v"))

    @staticmethod
    def _is_power_net(net_name: str) -> bool:
        lname = (net_name or "").strip().lower()
        return any(token in lname for token in ("vcc", "vdd", "vbat", "power", "supply"))

    def _clamp_x(self, x: float) -> float:
        return max(self.margin, min(self.board_width - self.margin, x))

    def _clamp_y(self, y: float) -> float:
        return max(self.margin, min(self.board_height - self.margin, y))
