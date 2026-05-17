"""Schematic connectivity debug and validation layer.

Sits between the placement/routing output and the KiCad serializer.
Validates electrical connectivity without modifying the pipeline.

Insertion point in KiCadSchExporter.export():
    after  _filter_short_wires (final)
    before _find_junctions

Usage:
    from app.infrastructure.exporters.connectivity_validator import ConnectivityValidator

    report = ConnectivityValidator(circuit, placements, rotations, pin_positions, wires).validate()
    report.log_all()            # structured DEBUG output
    artifact = report.to_json() # machine-readable JSON
"""

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from app.domains.circuits.entities import Circuit
from app.infrastructure.exporters.placement.pin_resolver import (
    PIN_LIBRARY,
    canonical_pin_name,
    pin_offset_for_instance,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  Data structures                                                             #
# --------------------------------------------------------------------------- #

PinKey = str          # "R1:1", "Q1:B", "U1:+" — human-readable ref:pin
Point  = Tuple[float, float]


@dataclass
class WireSegment:
    """One orthogonal wire segment with electrical context."""
    start:         Point
    end:           Point
    net_name:      Optional[str]
    attached_pins: List[PinKey] = field(default_factory=list)


@dataclass
class PinInfo:
    """Fully resolved information for a single pin."""
    key:            PinKey        # "R1:1"
    comp_id:        str
    pin_name:       str
    net_name:       Optional[str]
    raw_offset:     Point         # library offset (before rotation)
    rotated_offset: Point         # offset after symbol rotation
    absolute_pos:   Point         # origin + rotated_offset


@dataclass
class ConnectivityReport:
    """Full structured report produced by ConnectivityValidator."""

    # --- raw resolved geometry ---
    component_positions: Dict[str, Tuple[float, float]]    # comp_id → (x, y)
    pin_positions:       Dict[str, Tuple[float, float]]    # "R1:1" → (x, y)

    # --- wires ---
    wire_segments: List[WireSegment]

    # --- nets ---
    resolved_nets:    Dict[str, List[PinKey]]     # net → all declared pins
    connected_pins:   Dict[str, List[PinKey]]     # net → physically reached pins
    missing_pins:     Dict[str, List[PinKey]]     # net → pins NOT on any wire
    fragmented_nets:  Dict[str, List[List[PinKey]]]  # net → list of islands

    # --- violations ---
    orphan_pins:        List[PinKey]               # pins on no wire, any net
    connectivity_ok:    bool

    # --- human-readable ---
    tree_text: str = ""

    # ------------------------------------------------------------------ #
    def log_all(self) -> None:
        """Emit the full report at DEBUG level (compact, one section at a time)."""
        if not logger.isEnabledFor(logging.DEBUG):
            return
        self._log_pin_positions()
        self._log_wire_segments()
        self._log_net_report()
        self._log_orphans()
        self._log_fragments()
        self._log_tree()

    def _log_pin_positions(self) -> None:
        logger.debug("[CONN] === Pin-to-Net resolved coordinates ===")
        for pk, pos in sorted(self.pin_positions.items()):
            net = self._net_of(pk)
            logger.debug("[CONN] %s -> %s @ (%.2f, %.2f)", pk, net or "?NONE?", pos[0], pos[1])

    def _log_wire_segments(self) -> None:
        logger.debug("[CONN] === Wire segments ===")
        for ws in self.wire_segments:
            logger.debug(
                "[CONN] WIRE %s  start=(%.2f,%.2f) end=(%.2f,%.2f)  attached=%s",
                ws.net_name or "?",
                ws.start[0], ws.start[1],
                ws.end[0], ws.end[1],
                ws.attached_pins,
            )

    def _log_net_report(self) -> None:
        logger.debug("[CONN] === Net connectivity report ===")
        for net, expected in sorted(self.resolved_nets.items()):
            connected = self.connected_pins.get(net, [])
            missing   = self.missing_pins.get(net, [])
            status    = "OK" if not missing else "INCOMPLETE"
            logger.debug("[CONN] NET %s [%s]  expected=%d  connected=%d  missing=%s",
                         net, status, len(expected), len(connected), missing or "none")

    def _log_orphans(self) -> None:
        if self.orphan_pins:
            logger.debug("[CONN] === Orphan pins (electrically disconnected) ===")
            for pk in sorted(self.orphan_pins):
                net = self._net_of(pk)
                logger.debug("[CONN] ORPHAN  %s  net=%s", pk, net or "unassigned")

    def _log_fragments(self) -> None:
        fragmented = {n: frags for n, frags in self.fragmented_nets.items() if len(frags) > 1}
        if fragmented:
            logger.debug("[CONN] === Fragmented nets ===")
            for net, frags in sorted(fragmented.items()):
                logger.debug("[CONN] NET %s  fragments=%d", net, len(frags))
                for i, frag in enumerate(frags):
                    label = chr(ord("A") + i)
                    logger.debug("[CONN]   Fragment %s: %s", label, frag)

    def _log_tree(self) -> None:
        if self.tree_text:
            logger.debug("[CONN] === Connectivity tree ===\n%s", self.tree_text)

    def _net_of(self, pin_key: PinKey) -> Optional[str]:
        for net, pins in self.resolved_nets.items():
            if pin_key in pins:
                return net
        return None

    # ------------------------------------------------------------------ #
    def to_json(self) -> str:
        """Serialise to a machine-readable JSON artifact (Req 9)."""
        def _fmt_pt(p: Point) -> dict:
            return {"x": round(p[0], 4), "y": round(p[1], 4)}

        return json.dumps(
            {
                "component_positions": {
                    k: _fmt_pt(v) for k, v in self.component_positions.items()
                },
                "pin_positions": {
                    k: _fmt_pt(v) for k, v in self.pin_positions.items()
                },
                "wire_segments": [
                    {
                        "start":         _fmt_pt(ws.start),
                        "end":           _fmt_pt(ws.end),
                        "net_name":      ws.net_name,
                        "attached_pins": ws.attached_pins,
                    }
                    for ws in self.wire_segments
                ],
                "resolved_nets": {k: sorted(v) for k, v in self.resolved_nets.items()},
                "connected_pins": {k: sorted(v) for k, v in self.connected_pins.items()},
                "missing_pins":   {k: sorted(v) for k, v in self.missing_pins.items()},
                "fragmented_nets": {
                    k: [sorted(frag) for frag in v]
                    for k, v in self.fragmented_nets.items()
                },
                "orphan_pins":     sorted(self.orphan_pins),
                "connectivity_ok": self.connectivity_ok,
                "connectivity_tree": self.tree_text,
            },
            indent=2,
            ensure_ascii=False,
        )


# --------------------------------------------------------------------------- #
#  Core validator                                                              #
# --------------------------------------------------------------------------- #

_SNAP_TOL = 0.01  # mm — two points are "same" if closer than this


class ConnectivityValidator:
    """Validates electrical connectivity of a fully placed schematic.

    All inputs are the final outputs of the placement/routing pipeline
    (after snapping, filtering, power-flag injection).

    Parameters
    ----------
    circuit       : domain Circuit entity (nets, components, ports)
    placements    : comp_id → (x_mm, y_mm) — symbol origins
    rotations     : comp_id → rotation_deg
    pin_positions : (comp_id, pin_name) → (x_mm, y_mm) — absolute
    wires         : list of {"points": [(x,y), (x,y), ...]} dicts
    """

    def __init__(
        self,
        circuit:       Circuit,
        placements:    Dict[str, Tuple[float, float]],
        rotations:     Dict[str, int],
        pin_positions: Dict[Tuple[str, str], Tuple[float, float]],
        wires:         List[dict],
    ) -> None:
        self._circuit       = circuit
        self._placements    = placements
        self._rotations     = rotations
        self._pin_positions = pin_positions        # (comp_id, pin_name) → (x, y)
        self._wires         = wires

        # derived caches, built lazily by validate()
        self._pin_to_net:   Dict[Tuple[str, str], str] = {}       # (cid, pname) → net
        self._net_to_pins:  Dict[str, List[Tuple[str, str]]] = {} # net → [(cid, pname)]
        self._wire_segs:    List[WireSegment]      = []
        self._pt_to_pins:   Dict[FrozenSet, List[PinKey]] = {}    # frozenset({pt}) → [pin_key]
        self._uf:           _UnionFind             = _UnionFind()

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def validate(self) -> ConnectivityReport:
        """Run all checks and return a ConnectivityReport."""
        self._build_pin_to_net()
        self._build_wire_segments()
        self._build_point_index()
        self._build_union_find()

        resolved_nets  = self._build_resolved_nets()
        connected_pins = self._build_connected_pins()
        missing_pins   = {
            net: [p for p in declared if p not in connected_pins.get(net, [])]
            for net, declared in resolved_nets.items()
        }
        orphan_pins    = self._detect_orphans()
        frags          = self._detect_fragments(resolved_nets)
        tree_text      = self._render_tree(resolved_nets)

        # Connectivity is OK when no net has missing pins and no orphans
        ok = not any(missing_pins.values()) and not orphan_pins

        # Flatten pin_positions for the report (string keys)
        pp_str: Dict[str, Tuple[float, float]] = {
            f"{cid}:{pname}": pos
            for (cid, pname), pos in self._pin_positions.items()
        }

        return ConnectivityReport(
            component_positions=dict(self._placements),
            pin_positions=pp_str,
            wire_segments=self._wire_segs,
            resolved_nets=resolved_nets,
            connected_pins=connected_pins,
            missing_pins=missing_pins,
            fragmented_nets=frags,
            orphan_pins=orphan_pins,
            connectivity_ok=ok,
            tree_text=tree_text,
        )

    # ------------------------------------------------------------------ #
    #  Requirement 3: rotated pin debug (called separately, no overhead)  #
    # ------------------------------------------------------------------ #

    def log_rotated_pin_debug(self) -> None:
        """Req 3 — emit raw vs rotated vs absolute pin coords for every component.

        Only executed when logger is at DEBUG level.
        """
        if not logger.isEnabledFor(logging.DEBUG):
            return
        for comp_id, component in self._circuit.components.items():
            rot  = int(self._rotations.get(comp_id, 0))
            ox, oy = self._placements.get(comp_id, (0.0, 0.0))
            ctype = str(getattr(component.type, "value", component.type))
            raw_base = PIN_LIBRARY.get(ctype.lower(), {})
            if not raw_base or rot == 0:
                continue
            logger.debug("[CONN:ROT] %s (type=%s rot=%d°):", comp_id, ctype, rot)
            for pname, raw_off in raw_base.items():
                canon = canonical_pin_name(ctype, pname)
                rot_off = pin_offset_for_instance(ctype, pname, rot)
                abs_pos = (ox + rot_off[0], oy + rot_off[1])
                logger.debug(
                    "[CONN:ROT]   pin %-4s  raw=(% .2f, % .2f)  "
                    "rot=(% .2f, % .2f)  abs=(% .2f, % .2f)",
                    canon,
                    raw_off[0], raw_off[1],
                    rot_off[0], rot_off[1],
                    abs_pos[0],  abs_pos[1],
                )

    # ------------------------------------------------------------------ #
    #  Internal builders                                                   #
    # ------------------------------------------------------------------ #

    def _build_pin_to_net(self) -> None:
        p2n: Dict[Tuple[str, str], str] = {}
        n2p: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        for net in self._circuit.nets.values():
            net_name = str(net.name or "")
            for pref in net.connected_pins:
                key = (pref.component_id, pref.pin_name)
                p2n[key] = net_name
                n2p[net_name].append(key)
        self._pin_to_net  = p2n
        self._net_to_pins = dict(n2p)

    def _build_wire_segments(self) -> None:
        """Decompose each wire dict into individual point-pairs (Req 4)."""
        segs: List[WireSegment] = []
        for wire in self._wires:
            pts = wire.get("points", [])
            for i in range(len(pts) - 1):
                p1 = _round_pt(pts[i])
                p2 = _round_pt(pts[i + 1])
                if _pt_eq(p1, p2):
                    continue
                attached = (
                    self._pins_at(p1) + self._pins_at(p2)
                )
                net_name = self._net_for_attached(attached)
                segs.append(WireSegment(start=p1, end=p2, net_name=net_name,
                                        attached_pins=attached))
        self._wire_segs = segs

    def _build_point_index(self) -> None:
        """Map each wire endpoint (as frozen pt) → list of PinKeys that sit there."""
        pt_pins: Dict[FrozenSet, List[PinKey]] = defaultdict(list)
        for (cid, pname), pos in self._pin_positions.items():
            rounded = _round_pt(pos)
            frozen  = _freeze(rounded)
            pt_pins[frozen].append(f"{cid}:{pname}")
        self._pt_to_pins = dict(pt_pins)

    def _build_union_find(self) -> None:
        """Build UF over all pin positions, union-ing them via wire connectivity."""
        all_keys = [f"{c}:{p}" for (c, p) in self._pin_positions]
        uf = _UnionFind()
        for k in all_keys:
            uf.make(k)

        # Build adjacency: pin_key → set of adjacent pin_keys via wires
        pt_to_keys: Dict[FrozenSet, List[PinKey]] = self._pt_to_pins

        # Wire-endpoint → reachable endpoints via one wire
        # We union all pins that share a connected wire path using BFS on segments
        pt_adj: Dict[FrozenSet, Set[FrozenSet]] = defaultdict(set)
        for ws in self._wire_segs:
            f1 = _freeze(_round_pt(ws.start))
            f2 = _freeze(_round_pt(ws.end))
            pt_adj[f1].add(f2)
            pt_adj[f2].add(f1)

        # BFS: for each point, union all reachable points via wire graph
        visited_pts: Set[FrozenSet] = set()
        all_pts = set(pt_adj.keys()) | set(pt_to_keys.keys())
        for start_pt in all_pts:
            if start_pt in visited_pts:
                continue
            # BFS to find connected component
            queue: List[FrozenSet] = [start_pt]
            component: List[FrozenSet] = []
            seen: Set[FrozenSet] = set()
            while queue:
                cur = queue.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                component.append(cur)
                for nb in pt_adj.get(cur, set()):
                    if nb not in seen:
                        queue.append(nb)
            visited_pts.update(seen)
            # union all pins in this wire-connected component together
            representative: Optional[PinKey] = None
            for pt in component:
                for pk in pt_to_keys.get(pt, []):
                    uf.make(pk)
                    if representative is None:
                        representative = pk
                    else:
                        uf.union(representative, pk)

        # Also union coincident pins on the same net (KiCad implicit connection).
        # Without this, two pins at the same point with no wire form separate UF
        # roots and get reported as fragments even though they are electrically
        # connected by physical overlap.
        for net_name, pt_dict in self._coincident_net_points().items():
            for frozen, pks in {f: pt_to_keys.get(f, []) for f in pt_dict}.items():
                rep: Optional[PinKey] = None
                for pk in pks:
                    uf.make(pk)
                    if rep is None:
                        rep = pk
                    else:
                        uf.union(rep, pk)

        self._uf = uf

    def _build_resolved_nets(self) -> Dict[str, List[PinKey]]:
        result: Dict[str, List[PinKey]] = {}
        for net_name, pins in self._net_to_pins.items():
            result[net_name] = [f"{cid}:{pname}" for (cid, pname) in pins]
        return result

    def _coincident_net_points(self) -> Dict[str, Set[FrozenSet]]:
        """For each net, collect the set of grid points where ≥2 of its pins share
        the same location.  KiCad treats coincident pins as electrically connected
        even without an explicit wire, so the validator must recognise this.
        """
        # net → { frozen_point → [pin_keys at that point] }
        net_pt_map: Dict[str, Dict[FrozenSet, List[PinKey]]] = defaultdict(lambda: defaultdict(list))
        for (cid, pname), net_name in self._pin_to_net.items():
            pos = self._pin_positions.get((cid, pname))
            if pos is None:
                continue
            frozen = _freeze(_round_pt(pos))
            net_pt_map[net_name][frozen].append(f"{cid}:{pname}")

        # Return only points where ≥2 pins meet (genuine coincident connection)
        result: Dict[str, Set[FrozenSet]] = {}
        for net_name, pt_dict in net_pt_map.items():
            result[net_name] = {f for f, pks in pt_dict.items() if len(pks) >= 2}
        return result

    def _build_connected_pins(self) -> Dict[str, List[PinKey]]:
        """Determine which declared pins are physically reachable via wires
        OR connected by coincident placement (KiCad rule: pins at the same
        grid point within the same net are electrically connected).
        """
        coincident = self._coincident_net_points()
        connected: Dict[str, List[PinKey]] = defaultdict(list)
        for (cid, pname), net_name in self._pin_to_net.items():
            pk  = f"{cid}:{pname}"
            pos = self._pin_positions.get((cid, pname))
            if pos is None:
                continue
            frozen = _freeze(_round_pt(pos))
            on_wire = any(
                _freeze(_round_pt(ws.start)) == frozen or _freeze(_round_pt(ws.end)) == frozen
                for ws in self._wire_segs
            )
            # Accept coincident placement within same net (no explicit wire needed)
            coincident_ok = frozen in coincident.get(net_name, set())
            # Accept single-pin nets (power symbols, ports with one declared node)
            single_node   = len(self._net_to_pins.get(net_name, [])) <= 1
            if on_wire or coincident_ok or single_node:
                connected[net_name].append(pk)
        return dict(connected)

    def _detect_orphans(self) -> List[PinKey]:
        """Req 6 — pins on a net (≥2 nodes) that are neither on a wire endpoint
        nor coincident with another same-net pin (KiCad implicit connection).
        """
        coincident = self._coincident_net_points()
        wire_pts = {
            _freeze(_round_pt(ws.start)) for ws in self._wire_segs
        } | {
            _freeze(_round_pt(ws.end)) for ws in self._wire_segs
        }
        orphans: List[PinKey] = []
        for (cid, pname), net_name in self._pin_to_net.items():
            if len(self._net_to_pins.get(net_name, [])) < 2:
                continue
            pos = self._pin_positions.get((cid, pname))
            if pos is None:
                orphans.append(f"{cid}:{pname}")
                continue
            frozen = _freeze(_round_pt(pos))
            if frozen not in wire_pts and frozen not in coincident.get(net_name, set()):
                orphans.append(f"{cid}:{pname}")
        return sorted(orphans)

    def _detect_fragments(
        self, resolved_nets: Dict[str, List[PinKey]]
    ) -> Dict[str, List[List[PinKey]]]:
        """Req 7 — for each net, find distinct UF islands among its declared pins."""
        frags: Dict[str, List[List[PinKey]]] = {}
        for net_name, pins in resolved_nets.items():
            by_root: Dict[PinKey, List[PinKey]] = defaultdict(list)
            for pk in pins:
                root = self._uf.find(pk) if self._uf.contains(pk) else pk
                by_root[root].append(pk)
            if len(by_root) > 1:
                frags[net_name] = [sorted(group) for group in by_root.values()]
            else:
                frags[net_name] = [sorted(pins)]
        return frags

    def _render_tree(self, resolved_nets: Dict[str, List[PinKey]]) -> str:
        """Req 8 — human-readable connectivity tree."""
        lines: List[str] = []
        for net_name in sorted(resolved_nets):
            pins = sorted(resolved_nets[net_name])
            lines.append(net_name)
            for i, pk in enumerate(pins):
                connector = "└── " if i == len(pins) - 1 else "├── "
                pos = self._pin_positions.get(
                    tuple(pk.split(":", 1)) if ":" in pk else (pk, ""),  # type: ignore[arg-type]
                    None,
                )
                coord = f" @ ({pos[0]:.1f}, {pos[1]:.1f})" if pos else ""
                lines.append(f"  {connector}{pk}{coord}")
            lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _pins_at(self, pt: Point) -> List[PinKey]:
        return self._pt_to_pins.get(_freeze(pt), [])

    def _net_for_attached(self, attached: List[PinKey]) -> Optional[str]:
        for pk in attached:
            parts = pk.split(":", 1)
            if len(parts) == 2:
                key = (parts[0], parts[1])
                net = self._pin_to_net.get(key)
                if net:
                    return net
        return None


# --------------------------------------------------------------------------- #
#  Union-Find (path-compressed, union-by-rank)                                #
# --------------------------------------------------------------------------- #

class _UnionFind:
    def __init__(self) -> None:
        self._parent: Dict[PinKey, PinKey] = {}
        self._rank:   Dict[PinKey, int]    = {}

    def make(self, k: PinKey) -> None:
        if k not in self._parent:
            self._parent[k] = k
            self._rank[k]   = 0

    def contains(self, k: PinKey) -> bool:
        return k in self._parent

    def find(self, k: PinKey) -> PinKey:
        if self._parent[k] != k:
            self._parent[k] = self.find(self._parent[k])
        return self._parent[k]

    def union(self, a: PinKey, b: PinKey) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1


# --------------------------------------------------------------------------- #
#  Geometric helpers                                                           #
# --------------------------------------------------------------------------- #

def _round_pt(p: Point) -> Point:
    return (round(p[0], 4), round(p[1], 4))


def _pt_eq(a: Point, b: Point) -> bool:
    return math.hypot(a[0] - b[0], a[1] - b[1]) < _SNAP_TOL


def _freeze(p: Point) -> FrozenSet:
    return frozenset({p})


# --------------------------------------------------------------------------- #
#  Public API shortcut for exporter                                            #
# --------------------------------------------------------------------------- #

def run_connectivity_validation(
    circuit:       Circuit,
    placements:    Dict[str, Tuple[float, float]],
    rotations:     Dict[str, int],
    pin_positions: Dict[Tuple[str, str], Tuple[float, float]],
    wires:         List[dict],
    *,
    emit_debug_log: bool = True,
) -> ConnectivityReport:
    """Build validator, run all checks, log results, return report.

    Designed to be called as a single line from KiCadSchExporter.
    Never raises — validation failures are recorded in the report, not exceptions.
    """
    try:
        v = ConnectivityValidator(circuit, placements, rotations, pin_positions, wires)
        v.log_rotated_pin_debug()
        report = v.validate()
        if emit_debug_log:
            report.log_all()
        if not report.connectivity_ok:
            logger.warning(
                "[CONN] Connectivity issues detected — orphans=%d  incomplete_nets=%s  fragments=%s",
                len(report.orphan_pins),
                [n for n, m in report.missing_pins.items() if m] or "none",
                [n for n, f in report.fragmented_nets.items() if len(f) > 1] or "none",
            )
        return report
    except Exception as exc:
        logger.debug("[CONN] Validator raised unexpectedly: %s", exc, exc_info=True)
        return ConnectivityReport(
            component_positions={},
            pin_positions={},
            wire_segments=[],
            resolved_nets={},
            connected_pins={},
            missing_pins={},
            fragmented_nets={},
            orphan_pins=[],
            connectivity_ok=False,
            tree_text="",
        )


__all__ = [
    "ConnectivityValidator",
    "ConnectivityReport",
    "WireSegment",
    "run_connectivity_validation",
]
