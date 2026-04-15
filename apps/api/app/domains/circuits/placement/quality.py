from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, Iterable, List, Optional, Tuple

from app.domains.circuits.entities import Circuit, ComponentType

Point = Tuple[float, float]
Segment = Tuple[Point, Point]


@dataclass(frozen=True)
class LayoutQualityWeights:
    """Weighted objective tuned for readability and electrical correctness."""

    alignment_reward: float = 100.0
    signal_flow_reward: float = 50.0
    overlap_penalty: float = 1000.0
    crossing_penalty: float = 500.0
    center_attachment_penalty: float = 1000.0
    wire_label_overlap_penalty: float = 200.0
    spacing_penalty: float = 10.0
    wire_length_penalty: float = 10.0


@dataclass(frozen=True)
class LayoutQualityReport:
    objective: float
    component_overlap_count: int
    wire_crossing_count: int
    center_attachment_count: int
    wire_label_overlap_count: int
    spacing_shortfall: float
    wire_length: float
    alignment_reward_score: float
    signal_flow_reward_score: float

    @property
    def is_hard_valid(self) -> bool:
        return self.component_overlap_count == 0 and self.center_attachment_count == 0

    def to_dict(self) -> Dict[str, float | int | bool]:
        return {
            "objective": self.objective,
            "component_overlap_count": self.component_overlap_count,
            "wire_crossing_count": self.wire_crossing_count,
            "center_attachment_count": self.center_attachment_count,
            "wire_label_overlap_count": self.wire_label_overlap_count,
            "spacing_shortfall": self.spacing_shortfall,
            "wire_length": self.wire_length,
            "alignment_reward_score": self.alignment_reward_score,
            "signal_flow_reward_score": self.signal_flow_reward_score,
            "is_hard_valid": self.is_hard_valid,
        }


class LayoutQualityEvaluator:
    """Evaluate placement/routing quality with a unified objective function."""

    _CENTER_ALLOWED_TYPES = {
        ComponentType.GROUND,
        ComponentType.VOLTAGE_SOURCE,
        ComponentType.CURRENT_SOURCE,
        ComponentType.PORT,
        ComponentType.CONNECTOR,
    }

    def __init__(
        self,
        weights: Optional[LayoutQualityWeights] = None,
        center_epsilon: float = 0.15,
        alignment_tolerance: float = 0.75,
        label_clearance: float = 1.27,
    ) -> None:
        self.weights = weights or LayoutQualityWeights()
        self.center_epsilon = center_epsilon
        self.alignment_tolerance = alignment_tolerance
        self.label_clearance = label_clearance

    def evaluate_schematic(
        self,
        circuit: Circuit,
        placements: Dict[str, Point],
        wires: List[Dict],
        pin_positions: Dict[Tuple[str, str], Point],
        label_positions: Optional[Iterable[Point]] = None,
        min_component_spacing: float = 2.0,
    ) -> LayoutQualityReport:
        overlap_count, spacing_shortfall = self._component_overlap_and_spacing(
            placements,
            min_component_spacing,
        )
        segments = self._extract_segments(wires)
        crossing_count = self._count_wire_crossings(segments)
        wire_length = self._wire_length(segments)
        center_attachment_count = self._count_center_attachment_violations(
            circuit,
            placements,
            pin_positions,
        )
        wire_label_overlap_count = self._count_wire_label_overlaps(
            segments,
            label_positions or (),
        )
        alignment_reward = self._alignment_reward(circuit, placements)
        signal_flow_reward = self._signal_flow_reward(circuit, placements)

        objective = (
            self.weights.overlap_penalty * overlap_count
            + self.weights.crossing_penalty * crossing_count
            + self.weights.center_attachment_penalty * center_attachment_count
            + self.weights.wire_label_overlap_penalty * wire_label_overlap_count
            + self.weights.spacing_penalty * spacing_shortfall
            + self.weights.wire_length_penalty * wire_length
            - self.weights.alignment_reward * alignment_reward
            - self.weights.signal_flow_reward * signal_flow_reward
        )

        return LayoutQualityReport(
            objective=objective,
            component_overlap_count=overlap_count,
            wire_crossing_count=crossing_count,
            center_attachment_count=center_attachment_count,
            wire_label_overlap_count=wire_label_overlap_count,
            spacing_shortfall=spacing_shortfall,
            wire_length=wire_length,
            alignment_reward_score=alignment_reward,
            signal_flow_reward_score=signal_flow_reward,
        )

    def _component_overlap_and_spacing(
        self,
        placements: Dict[str, Point],
        min_spacing: float,
    ) -> Tuple[int, float]:
        ids = list(placements.keys())
        overlap_count = 0
        spacing_shortfall = 0.0

        for i in range(len(ids)):
            x1, y1 = placements[ids[i]]
            for j in range(i + 1, len(ids)):
                x2, y2 = placements[ids[j]]
                dist = math.hypot(x2 - x1, y2 - y1)
                if dist < min_spacing:
                    overlap_count += 1
                    spacing_shortfall += max(0.0, min_spacing - dist)

        return overlap_count, spacing_shortfall

    def _extract_segments(self, wires: List[Dict]) -> List[Segment]:
        segments: List[Segment] = []
        for wire in wires:
            points = wire.get("points", [])
            for idx in range(len(points) - 1):
                a = points[idx]
                b = points[idx + 1]
                if a == b:
                    continue
                segments.append((a, b))
        return segments

    def _wire_length(self, segments: List[Segment]) -> float:
        total = 0.0
        for (x1, y1), (x2, y2) in segments:
            total += math.hypot(x2 - x1, y2 - y1)
        return total

    def _count_wire_crossings(self, segments: List[Segment]) -> int:
        crossings = 0
        for i in range(len(segments)):
            for j in range(i + 1, len(segments)):
                if self._segments_cross(segments[i], segments[j]):
                    crossings += 1
        return crossings

    def _count_center_attachment_violations(
        self,
        circuit: Circuit,
        placements: Dict[str, Point],
        pin_positions: Dict[Tuple[str, str], Point],
    ) -> int:
        violations = 0

        for net in circuit.nets.values():
            if len(net.connected_pins) < 2:
                continue

            for pin_ref in net.connected_pins:
                component = circuit.components.get(pin_ref.component_id)
                center = placements.get(pin_ref.component_id)
                if component is None or center is None:
                    continue

                if len(component.pins) <= 1:
                    continue
                if component.type in self._CENTER_ALLOWED_TYPES:
                    continue

                pin_pos = pin_positions.get((pin_ref.component_id, pin_ref.pin_name))
                if pin_pos is None:
                    violations += 1
                    continue

                if math.hypot(pin_pos[0] - center[0], pin_pos[1] - center[1]) <= self.center_epsilon:
                    violations += 1

        return violations

    def _count_wire_label_overlaps(
        self,
        segments: List[Segment],
        label_positions: Iterable[Point],
    ) -> int:
        overlaps = 0
        for label in label_positions:
            for segment in segments:
                if self._point_to_segment_distance(label, segment) <= self.label_clearance:
                    overlaps += 1
                    break
        return overlaps

    def _alignment_reward(self, circuit: Circuit, placements: Dict[str, Point]) -> float:
        by_type: Dict[ComponentType, List[Point]] = {}
        for comp_id, component in circuit.components.items():
            if comp_id not in placements:
                continue
            if component.type in self._CENTER_ALLOWED_TYPES:
                continue
            by_type.setdefault(component.type, []).append(placements[comp_id])

        reward = 0.0
        for points in by_type.values():
            if len(points) < 2:
                continue
            for idx in range(len(points)):
                x1, y1 = points[idx]
                for jdx in range(idx + 1, len(points)):
                    x2, y2 = points[jdx]
                    if abs(x1 - x2) <= self.alignment_tolerance or abs(y1 - y2) <= self.alignment_tolerance:
                        reward += 1.0

        return reward

    def _signal_flow_reward(self, circuit: Circuit, placements: Dict[str, Point]) -> float:
        input_nodes: List[str] = []
        output_nodes: List[str] = []

        for comp_id in placements:
            cid = comp_id.lower()
            if "vin" in cid or cid.startswith("input") or cid.endswith("_in"):
                input_nodes.append(comp_id)
            if "vout" in cid or cid.startswith("output") or cid.endswith("_out"):
                output_nodes.append(comp_id)

        reward = 0.0
        if input_nodes and output_nodes:
            for src in input_nodes:
                for dst in output_nodes:
                    if placements[dst][0] > placements[src][0]:
                        reward += 1.0

        for net in circuit.nets.values():
            xs = [
                placements[p.component_id][0]
                for p in net.connected_pins
                if p.component_id in placements
            ]
            if len(xs) >= 2 and max(xs) - min(xs) >= 1.0:
                reward += 0.15

        return reward

    @staticmethod
    def _segments_cross(s1: Segment, s2: Segment) -> bool:
        (x1, y1), (x2, y2) = s1
        (x3, y3), (x4, y4) = s2

        endpoints_1 = {(x1, y1), (x2, y2)}
        endpoints_2 = {(x3, y3), (x4, y4)}
        if endpoints_1 & endpoints_2:
            return False

        s1_vertical = x1 == x2
        s2_vertical = x3 == x4

        if s1_vertical == s2_vertical:
            return False

        if s1_vertical:
            xv = x1
            yh = y3
            return (
                min(y1, y2) < yh < max(y1, y2)
                and min(x3, x4) < xv < max(x3, x4)
            )

        xv = x3
        yh = y1
        return (
            min(y3, y4) < yh < max(y3, y4)
            and min(x1, x2) < xv < max(x1, x2)
        )

    @staticmethod
    def _point_to_segment_distance(point: Point, segment: Segment) -> float:
        px, py = point
        (x1, y1), (x2, y2) = segment
        dx = x2 - x1
        dy = y2 - y1

        if dx == 0 and dy == 0:
            return math.hypot(px - x1, py - y1)

        t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return math.hypot(px - proj_x, py - proj_y)
