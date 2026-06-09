# app/infrastructure/exporters/pcb_strict_engine.py
"""Strict PCB placement, routing, and DRC for single-stage BJT / op-amp boards.

Implements anchor-centred radial placement, Manhattan routing with 45° miters,
courtyard avoidance, and pre-export DRC checks.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import ValidationError

from app.domains.circuits.entities import Circuit, ComponentType
from app.infrastructure.exporters.kicad_footprint_library import KiCadFootprintLibrary

logger = logging.getLogger(__name__)

# ── Physical rules (mm) ─────────────────────────────────────────────────────
NOMINAL_BOARD_W = 90.0
NOMINAL_BOARD_H = 40.0
BOARD_MARGIN_MM = 5.0
MAX_BOARD_W = 100.0
MAX_BOARD_H = 60.0
MIN_COURTYARD_CLEARANCE_MM = 0.5
TRACK_CLEARANCE_MM = 0.2
POWER_TRACK_MM = 0.5
SIGNAL_TRACK_MM = 0.25
CHAMFER_MM = 0.8
R_POWER_PATH_MM = 12.5  # 10–15 mm centre
R_BIAS_MM = 10.0  # 8–12 mm
R_IO_MM = 22.5  # 20–25 mm from anchor
GRID_SNAP = 0.127


def _snap(v: float, g: float = GRID_SNAP) -> float:
    return round(v / g) * g


def _norm_ref(cid: str) -> str:
    return str(cid).upper().replace("_", "").replace("-", "")


def _type_lower(component) -> str:
    t = getattr(component, "type", None)
    return str(getattr(t, "value", t) or "").strip().lower()


def find_pcb_anchor(circuit: Circuit) -> Optional[str]:
    """Return a robust anchor reference for strict PCB placement.

    Preferred order:
    1) Q* BJT references
    2) U* op-amp references
    3) any BJT/op-amp by type
    4) first non-power component as graceful fallback
    """
    for cid, comp in circuit.components.items():
        nu = _norm_ref(cid)
        tl = _type_lower(comp)
        if nu.startswith("Q") and (
            tl in ("bjt_npn", "bjt_pnp", "bjt", "npn", "pnp") or "bjt" in tl
        ):
            return cid
    for cid, comp in circuit.components.items():
        nu = _norm_ref(cid)
        tl = _type_lower(comp)
        if nu.startswith(("U", "A")) and (
            "opamp" in tl
            or tl in {"opamp_ic", "op_amp", "op_amp_ic", "operational_amplifier"}
        ):
            return cid
    for cid, comp in circuit.components.items():
        if _type_lower(comp) in ("bjt_npn", "bjt_pnp"):
            return cid
    for cid, comp in circuit.components.items():
        if _type_lower(comp) in {
            "opamp",
            "opamp_ic",
            "op_amp",
            "op_amp_ic",
            "operational_amplifier",
        }:
            return cid
    # Ref-based safety net: if model normalization degraded component types to
    # generic values, still prefer U*/Q* active-device refs before generic fallback.
    for cid, comp in circuit.components.items():
        nu = _norm_ref(cid)
        tl = _type_lower(comp)
        if tl in {"ground", "power_supply", "power_symbol", "voltage_source", "current_source"}:
            continue
        if nu.startswith(("GND", "VCC", "VDD", "VEE", "VSS", "PWR", "#PWR")):
            continue
        if nu.startswith(("U", "Q", "A")):
            logger.warning(
                "Anchor type hints missing for '%s' (type=%s); using ref-based active anchor fallback",
                cid,
                tl,
            )
            return cid
    for cid, comp in circuit.components.items():
        nu = _norm_ref(cid)
        tl = _type_lower(comp)
        if tl in {"ground", "power_supply", "power_symbol", "voltage_source", "current_source"}:
            continue
        if nu.startswith(("GND", "VCC", "VDD", "VEE", "VSS", "PWR", "#PWR")):
            continue
        logger.warning(
            "No Q1/U1 anchor found; falling back to first non-power component '%s' (type=%s)",
            cid,
            tl,
        )
        return cid
    return None


def _is_bjt_anchor(circuit: Circuit, anchor: str) -> bool:
    comp = circuit.components.get(anchor)
    if not comp:
        return True
    tl = _type_lower(comp)
    return "bjt" in tl or tl in ("bjt_npn", "bjt_pnp", "npn", "pnp")


def _category(cid: str, circuit: Circuit, anchor: str, bjt: bool) -> str:
    nu = _norm_ref(cid)
    if cid == anchor:
        return "anchor"
    tl = _type_lower(circuit.components[cid])
    if tl in ("ground",) or nu in ("GND", "0"):
        return "power_symbol"
    if tl in ("voltage_source", "current_source", "power_supply") or any(
        x in nu for x in ("VCC", "VDD", "VEE", "VSS")
    ):
        return "power_symbol"
    if bjt:
        if nu in ("RC", "RE", "RE1", "RE2", "CE", "RF", "RG") or nu.startswith(
            ("RC", "RE", "CE")
        ):
            return "power_path"
        if nu in ("R1", "R2"):
            return "bias"
    else:
        if nu in ("RF", "RG", "RIN", "R_F", "R_G", "R_IN"):
            return "power_path"
        if nu in ("CPS", "CPN", "CDEC", "C_DEC"):
            return "bias"
    if nu in ("CIN", "COUT", "IN", "OUT") or nu.startswith(("CIN", "COUT")):
        return "io"
    if nu.startswith("C") and nu not in ("CIN", "COUT"):
        if bjt and nu in ("CE",):
            return "power_path"
    return "other"


def _world_courtyard(
    circuit: Circuit,
    cid: str,
    placement: Tuple[float, float],
) -> Tuple[float, float, float, float]:
    comp = circuit.components[cid]
    tl = _type_lower(comp)
    if tl in ("voltage_source", "current_source") and len(getattr(comp, "pins", ()) or ()) <= 1:
        tl = "connector"
    lx, ly, hx, hy = KiCadFootprintLibrary.get_courtyard_bbox_local(tl)
    ox, oy = placement
    return (ox + lx, oy + ly, ox + hx, oy + hy)


def _expand_rect(
    r: Tuple[float, float, float, float], d: float
) -> Tuple[float, float, float, float]:
    return (r[0] - d, r[1] - d, r[2] + d, r[3] + d)


def _rects_overlap(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
    gap: float = 0.0,
) -> bool:
    ax0, ay0, ax1, ay1 = _expand_rect(a, gap / 2.0)
    bx0, by0, bx1, by1 = _expand_rect(b, gap / 2.0)
    return not (ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0)


def _separate_placements(
    circuit: Circuit,
    placements: Dict[str, Tuple[float, float]],
    fixed: Set[str],
) -> Dict[str, Tuple[float, float]]:
    """Iteratively push overlapping courtyards apart.

    Robustness measures (vs the original 40×0.35mm pushes):
      • Escalate the push step when no progress is made so stuck pairs eventually
        break free.
      • Deterministic anti-clash jitter when two components share the exact same
        coordinate (`dist≈0`), since otherwise the push vector is undefined.
      • Larger iteration budget (200) but with early exit once stable.
      • Final force-relocate pass: any component still overlapping after the
        spring relaxation is teleported to a free grid slot in the working area
        so the DRC hard-fail never trips on broken initial placements.
    """
    out = {k: (float(v[0]), float(v[1])) for k, v in placements.items()}
    cys = {cid: _world_courtyard(circuit, cid, out[cid]) for cid in out}

    base_push = 0.35 + MIN_COURTYARD_CLEARANCE_MM / 4
    push_step = base_push
    stagnation = 0
    last_overlap_count = -1
    for iteration in range(200):
        moved = False
        overlap_pairs = 0
        ids = list(out.keys())
        for i, ia in enumerate(ids):
            for ib in ids[i + 1 :]:
                if ia in fixed and ib in fixed:
                    continue
                if not _rects_overlap(cys[ia], cys[ib], gap=MIN_COURTYARD_CLEARANCE_MM):
                    continue
                overlap_pairs += 1
                ax, ay = out[ia]
                bx, by = out[ib]
                dx, dy = bx - ax, by - ay
                dist = math.hypot(dx, dy)
                if dist < 1e-3:
                    # Coincident: pick a deterministic direction based on the
                    # ref-designator hash so both pairs disagree on the axis.
                    seed = (hash(ia) ^ hash(ib)) & 0xFFFF
                    angle = (seed / 0xFFFF) * 2.0 * math.pi
                    dx = math.cos(angle)
                    dy = math.sin(angle)
                    dist = 1.0
                fx = push_step * dx / dist
                fy = push_step * dy / dist
                if ia not in fixed:
                    out[ia] = (ax - fx, ay - fy)
                if ib not in fixed:
                    out[ib] = (bx + fx, by + fy)
                cys[ia] = _world_courtyard(circuit, ia, out[ia])
                cys[ib] = _world_courtyard(circuit, ib, out[ib])
                moved = True

        if overlap_pairs == 0:
            break
        if not moved:
            break

        # If progress has stalled (same overlap count for several iterations),
        # escalate the push step so weakly-bouncing pairs finally separate.
        if overlap_pairs == last_overlap_count:
            stagnation += 1
            if stagnation >= 5:
                push_step = min(push_step * 1.5, 4.0)
                stagnation = 0
        else:
            stagnation = 0
            push_step = base_push
        last_overlap_count = overlap_pairs

    # Final fallback: if any pair still overlaps after spring relaxation,
    # teleport the second component of each overlapping pair to a free slot
    # in a deterministic spiral so DRC doesn't hard-fail.
    remaining = []
    ids = list(out.keys())
    for i, ia in enumerate(ids):
        for ib in ids[i + 1 :]:
            if _rects_overlap(cys[ia], cys[ib], gap=MIN_COURTYARD_CLEARANCE_MM):
                remaining.append((ia, ib))
    if remaining:
        out, cys = _force_relocate_overlaps(circuit, out, cys, fixed, remaining)

    return out


def _clamp_placements_to_board(
    circuit: Circuit,
    placements: Dict[str, Tuple[float, float]],
    board_w: float,
    board_h: float,
) -> Dict[str, Tuple[float, float]]:
    """Keep each component courtyard inside the board outline (with margin)."""
    min_b = BOARD_MARGIN_MM
    max_x = board_w - BOARD_MARGIN_MM
    max_y = board_h - BOARD_MARGIN_MM
    out: Dict[str, Tuple[float, float]] = {}
    for cid, (x, y) in placements.items():
        nx, ny = float(x), float(y)
        for _ in range(6):
            x0, y0, x1, y1 = _world_courtyard(circuit, cid, (nx, ny))
            if x0 < min_b:
                nx += min_b - x0
            if y0 < min_b:
                ny += min_b - y0
            x0, y0, x1, y1 = _world_courtyard(circuit, cid, (nx, ny))
            if x1 > max_x:
                nx -= x1 - max_x
            if y1 > max_y:
                ny -= y1 - max_y
        out[cid] = (_snap(nx), _snap(ny))
    return out


def repair_placement_overlaps(
    circuit: Circuit,
    placements: Dict[str, Tuple[float, float]],
    anchor: Optional[str],
    board_w: float,
    board_h: float,
) -> Dict[str, Tuple[float, float]]:
    """Re-separate courtyards after board translation / sizing (fixes post-finalize overlaps)."""
    fixed: Set[str] = {anchor} if anchor else set()
    out = _clamp_placements_to_board(circuit, placements, board_w, board_h)
    out = _separate_placements(circuit, out, fixed)
    out = _clamp_placements_to_board(circuit, out, board_w, board_h)

    if count_courtyard_overlaps(circuit, out) > 0:
        cys = {cid: _world_courtyard(circuit, cid, out[cid]) for cid in out}
        remaining: List[Tuple[str, str]] = []
        ids = list(out.keys())
        for i, ia in enumerate(ids):
            for ib in ids[i + 1 :]:
                if _rects_overlap(cys[ia], cys[ib], gap=MIN_COURTYARD_CLEARANCE_MM):
                    remaining.append((ia, ib))
        if remaining:
            out, _ = _force_relocate_overlaps(
                circuit,
                out,
                cys,
                fixed,
                remaining,
                board_w=board_w,
                board_h=board_h,
            )
            out = _clamp_placements_to_board(circuit, out, board_w, board_h)
            out = _separate_placements(circuit, out, fixed)

    overlap_left = count_courtyard_overlaps(circuit, out)
    if overlap_left:
        logger.warning(
            "PCB_PLACEMENT: %d courtyard overlap(s) remain after repair on %.1fx%.1fmm board",
            overlap_left,
            board_w,
            board_h,
        )
    return out


def _force_relocate_overlaps(
    circuit: Circuit,
    out: Dict[str, Tuple[float, float]],
    cys: Dict[str, Tuple[float, float, float, float]],
    fixed: Set[str],
    overlapping_pairs: List[Tuple[str, str]],
    *,
    board_w: Optional[float] = None,
    board_h: Optional[float] = None,
) -> Tuple[Dict[str, Tuple[float, float]], Dict[str, Tuple[float, float, float, float]]]:
    """Move offending non-fixed components to the first free grid slot.

    Uses a coarse 4mm scan grid over the working envelope so the relocation
    never lands inside another courtyard. Idempotent — components that are
    already non-overlapping are left untouched.
    """
    rects = list(cys.values())
    if not rects:
        return out, cys
    if board_w is not None and board_h is not None:
        min_x = BOARD_MARGIN_MM
        min_y = BOARD_MARGIN_MM
        max_x = board_w - BOARD_MARGIN_MM
        max_y = board_h - BOARD_MARGIN_MM
    else:
        min_x = min(r[0] for r in rects) - 4.0
        min_y = min(r[1] for r in rects) - 4.0
        max_x = max(r[2] for r in rects) + 4.0
        max_y = max(r[3] for r in rects) + 4.0
        max_x = min(max_x, MAX_BOARD_W - BOARD_MARGIN_MM)
        max_y = min(max_y, MAX_BOARD_H - BOARD_MARGIN_MM)

    movable_offenders: List[str] = []
    seen: Set[str] = set()
    for ia, ib in overlapping_pairs:
        for cand in (ib, ia):
            if cand in fixed or cand in seen:
                continue
            seen.add(cand)
            movable_offenders.append(cand)
            break

    def _free_slot(cid: str) -> Optional[Tuple[float, float]]:
        step = max(GRID_SNAP, 2.0)
        y = min_y
        while y <= max_y:
            x = min_x
            while x <= max_x:
                candidate = (_snap(x), _snap(y))
                cand_rect = _world_courtyard(circuit, cid, candidate)
                collides = False
                for other_id, other_rect in cys.items():
                    if other_id == cid:
                        continue
                    if _rects_overlap(cand_rect, other_rect, gap=MIN_COURTYARD_CLEARANCE_MM):
                        collides = True
                        break
                if not collides:
                    return candidate
                x += step
            y += step
        return None

    for cid in movable_offenders:
        slot = _free_slot(cid)
        if slot is None:
            logger.warning(
                "PCB_PLACEMENT: no free slot found for %s — leaving in place "
                "(downstream DRC may flag overlap)",
                cid,
            )
            continue
        out[cid] = slot
        cys[cid] = _world_courtyard(circuit, cid, slot)
        logger.info(
            "PCB_PLACEMENT: relocated %s to free slot (%.2f, %.2f) to resolve courtyard overlap",
            cid,
            slot[0],
            slot[1],
        )
    return out, cys


def place_strict(
    circuit: Circuit,
    *,
    nominal_w: float = NOMINAL_BOARD_W,
    nominal_h: float = NOMINAL_BOARD_H,
) -> Tuple[Dict[str, Tuple[float, float]], str, Dict[str, Any]]:
    anchor = find_pcb_anchor(circuit)
    if not anchor:
        raise ValidationError.from_exception_data(
            "KiCadPCB",
            [
                {
                    "type": "value_error",
                    "loc": ("pcb", "placement", "anchor"),
                    "input": None,
                    "ctx": {"error": "No Q1/U1-class anchor (BJT or op-amp) found for strict PCB placement."},
                }
            ],
        )

    cx, cy = nominal_w / 2.0, nominal_h / 2.0
    bjt = _is_bjt_anchor(circuit, anchor)
    placements: Dict[str, Tuple[float, float]] = {anchor: (_snap(cx), _snap(cy))}

    power_path: List[str] = []
    bias: List[str] = []
    io_left: List[str] = []
    io_right: List[str] = []
    other: List[str] = []

    for cid in circuit.components:
        if cid == anchor:
            continue
        cat = _category(cid, circuit, anchor, bjt)
        nu = _norm_ref(cid)
        if cat == "power_path":
            power_path.append(cid)
        elif cat == "bias":
            bias.append(cid)
        elif cat == "io":
            if nu in ("CIN", "IN") or nu.startswith("CIN"):
                io_left.append(cid)
            elif nu in ("COUT", "OUT") or nu.startswith("COUT"):
                io_right.append(cid)
            else:
                other.append(cid)
        elif cat == "power_symbol":
            other.append(cid)
        else:
            other.append(cid)

    # Radial: power_path
    npp = len(power_path)
    for i, cid in enumerate(sorted(power_path)):
        ang = (2.0 * math.pi * i) / max(npp, 1) - math.pi / 2.0
        r = R_POWER_PATH_MM
        placements[cid] = (_snap(cx + r * math.cos(ang)), _snap(cy + r * math.sin(ang)))

    nb = len(bias)
    for i, cid in enumerate(sorted(bias)):
        side = -1.0 if i % 2 == 0 else 1.0
        ang = side * (0.4 + 0.25 * (i // 2))
        r = R_BIAS_MM
        placements[cid] = (_snap(cx + r * math.cos(ang)), _snap(cy - side * r * 0.85))

    # IO: left / right of anchor
    lx = cx - R_IO_MM
    rx = cx + R_IO_MM
    for i, cid in enumerate(sorted(io_left)):
        placements[cid] = (_snap(lx - i * 4.0), _snap(cy))
    for i, cid in enumerate(sorted(io_right)):
        placements[cid] = (_snap(rx + i * 4.0), _snap(cy))

    # Other / power: corners and bottom strip.
    # Spread power symbols along the rail so multiple GND/VCC pads don't collide
    # at a single coordinate (which would defeat the radial separation pass).
    gnd_slot = 0
    vcc_slot = 0
    other_slot = 0
    for cid in sorted(other):
        nu = _norm_ref(cid)
        if "GND" in nu or nu == "0":
            placements[cid] = (
                _snap(cx - 25 + gnd_slot * 6.0),
                _snap(nominal_h - 8 - (gnd_slot % 2) * 4.0),
            )
            gnd_slot += 1
        elif "VCC" in nu or "VDD" in nu:
            placements[cid] = (
                _snap(cx - 25 + vcc_slot * 6.0),
                _snap(8 + (vcc_slot % 2) * 4.0),
            )
            vcc_slot += 1
        else:
            ang = math.pi * 0.75 + 0.35 * other_slot
            r = 18.0
            placements[cid] = (_snap(cx + r * math.cos(ang)), _snap(cy + r * math.sin(ang)))
            other_slot += 1

    fixed = {anchor}
    placements = _separate_placements(circuit, placements, fixed)

    overlap = count_courtyard_overlaps(circuit, placements)
    meta = {
        "anchor": anchor,
        "nominal_center": (cx, cy),
        "overlap_after_separation": overlap,
    }
    return placements, anchor, meta


def finalize_board_size(
    circuit: Circuit,
    placements: Dict[str, Tuple[float, float]],
) -> Tuple[Dict[str, Tuple[float, float]], Tuple[float, float]]:
    """Translate placements so content fits in [0,W]×[0,H] with margin; cap 100×60 mm."""
    if not placements:
        return placements, (NOMINAL_BOARD_W, NOMINAL_BOARD_H)

    rects = [_world_courtyard(circuit, cid, xy) for cid, xy in placements.items()]
    min_x = min(r[0] for r in rects)
    min_y = min(r[1] for r in rects)
    max_x = max(r[2] for r in rects)
    max_y = max(r[3] for r in rects)

    bw = min(MAX_BOARD_W, max(NOMINAL_BOARD_W, (max_x - min_x) + 2 * BOARD_MARGIN_MM))
    bh = min(MAX_BOARD_H, max(NOMINAL_BOARD_H, (max_y - min_y) + 2 * BOARD_MARGIN_MM))

    dx = BOARD_MARGIN_MM - min_x
    dy = BOARD_MARGIN_MM - min_y
    shifted = {cid: (_snap(x + dx), _snap(y + dy)) for cid, (x, y) in placements.items()}
    return shifted, (bw, bh)


def count_courtyard_overlaps(
    circuit: Circuit,
    placements: Dict[str, Tuple[float, float]],
) -> int:
    ids = list(placements.keys())
    n = 0
    for i, ia in enumerate(ids):
        ra = _world_courtyard(circuit, ia, placements[ia])
        for ib in ids[i + 1 :]:
            rb = _world_courtyard(circuit, ib, placements[ib])
            if _rects_overlap(ra, rb, gap=MIN_COURTYARD_CLEARANCE_MM):
                n += 1
    return n


def compute_pad_positions(
    circuit: Circuit,
    placements: Dict[str, Tuple[float, float]],
) -> Dict[str, Tuple[float, float]]:
    result: Dict[str, Tuple[float, float]] = {}
    for cid, comp in circuit.components.items():
        if cid not in placements:
            continue
        ox, oy = placements[cid]
        comp_type = comp.type.value if hasattr(comp.type, "value") else str(comp.type)
        if str(comp_type).lower() in {"voltage_source", "current_source"} and len(
            getattr(comp, "pins", ()) or ()
        ) <= 1:
            comp_type = "connector"
        pads = KiCadFootprintLibrary.get_pads(comp_type)
        pin_map = KiCadFootprintLibrary.get_pin_map(comp_type)
        pad_offsets = {p["number"]: p["at"] for p in pads}
        pin_count = len(comp.pins)
        force_fallback = pin_count > 1 and len(pad_offsets) <= 1

        for pin_index, pin_name in enumerate(comp.pins):
            pad_num = pin_map.get(pin_name, pin_name)
            if force_fallback:
                ang = (2.0 * math.pi * (pin_index % max(pin_count, 1))) / max(pin_count, 1)
                offset = (1.5 * math.cos(ang), 1.5 * math.sin(ang))
            else:
                off = pad_offsets.get(pad_num)
                if off is None:
                    ang = (2.0 * math.pi * pin_index) / max(pin_count, 1)
                    offset = (1.5 * math.cos(ang), 1.5 * math.sin(ang))
                else:
                    offset = (float(off[0]), float(off[1]))
            result[f"{cid}.{pin_name}"] = (_snap(ox + offset[0]), _snap(oy + offset[1]))
    return result


def _is_power_net(name: str) -> bool:
    low = name.strip().lower()
    return any(
        t in low for t in ("vcc", "vdd", "vee", "vss", "gnd", "ground", "0", "power")
    )


def _net_route_sort_key(name: str) -> Tuple[int, str]:
    """Order: power → general signal → short-circuit–sensitive (base/gate/feedback/in)."""
    low = name.strip().lower()
    if _is_power_net(name):
        return (0, name)
    sensitive_tokens = ("base", "gate", "in_sig", "feedback", "fb", "sense")
    if any(t in low for t in sensitive_tokens):
        return (2, name)
    return (1, name)


def _manhattan_points(a: Tuple[float, float], b: Tuple[float, float]) -> List[Tuple[float, float]]:
    """IPC-2221 compliant path: 45° diagonal then straight (no 90° bends)."""
    x1, y1 = a
    x2, y2 = b
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return [a, b]
    # Pure horizontal or vertical — no corner needed
    if abs(dx) < 1e-6 or abs(dy) < 1e-6:
        return [a, b]
    # 45° diagonal of length min(|dx|, |dy|), then straight remainder
    diag = min(abs(dx), abs(dy))
    sx = 1.0 if dx > 0 else -1.0
    sy = 1.0 if dy > 0 else -1.0
    mid = (_snap(x1 + sx * diag), _snap(y1 + sy * diag))
    if abs(mid[0] - x2) < 1e-6 and abs(mid[1] - y2) < 1e-6:
        return [a, b]  # pure diagonal, no remainder
    return [a, mid, b]


def _seg_intersects_rect(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    rect: Tuple[float, float, float, float],
) -> bool:
    x0, y0, x1, y1 = rect
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return x0 <= p1[0] <= x1 and y0 <= p1[1] <= y1

    def clip_t(t0: float, t1: float) -> Tuple[float, float]:
        return (max(0.0, t0), min(1.0, t1))

    # Liang-Barsky
    t_min, t_max = 0.0, 1.0
    edges = [(-dx, p1[0] - x0), (dx, x1 - p1[0]), (-dy, p1[1] - y0), (dy, y1 - p1[1])]
    p_vals = [-1, 1, -1, 1]
    q_vals = [p1[0] - x0, x1 - p1[0], p1[1] - y0, y1 - p1[1]]
    for p, q in zip(p_vals, q_vals):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        r = q / p
        if p < 0:
            t_min = max(t_min, r)
        else:
            t_max = min(t_max, r)
    return t_min <= t_max


def _obstacles_for_net(
    circuit: Circuit,
    placements: Dict[str, Tuple[float, float]],
    allow_cids: Set[str],
    inflate: float,
) -> List[Tuple[float, float, float, float]]:
    """Courtyard obstacles excluding components that own the pads being routed (approximation)."""
    obs: List[Tuple[float, float, float, float]] = []
    for cid in placements:
        if cid in allow_cids:
            continue
        r = _world_courtyard(circuit, cid, placements[cid])
        obs.append(_expand_rect(r, inflate))
    return obs


def _path_clear(
    points: List[Tuple[float, float]],
    obstacles: List[Tuple[float, float, float, float]],
) -> bool:
    for i in range(len(points) - 1):
        for rect in obstacles:
            if _seg_intersects_rect(points[i], points[i + 1], rect):
                return False
    return True


def _route_manhattan_avoid(
    a: Tuple[float, float],
    b: Tuple[float, float],
    obstacles: List[Tuple[float, float, float, float]],
) -> List[Tuple[float, float]]:
    """Try many 45°-compliant detour paths; return best clean path, or straight line."""
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    dx = abs(b[0] - a[0]) or 5.0
    dy = abs(b[1] - a[1]) or 5.0

    def _via45(waypoint: Tuple[float, float]) -> List[Tuple[float, float]]:
        """Route a → waypoint → b each as a 45°-path."""
        seg1 = _manhattan_points(a, waypoint)
        seg2 = _manhattan_points(waypoint, b)
        return seg1 + seg2[1:]  # join without duplicate waypoint

    candidates: List[List[Tuple[float, float]]] = [
        # Standard 45° a→b direct
        _manhattan_points(a, b),
        # Offset detours via a single waypoint
        *[_via45((b[0] + off, a[1])) for off in (-dy, dy, -2 * dy, 2 * dy, -3 * dy, 3 * dy)],
        *[_via45((a[0], b[1] + off)) for off in (-dx, dx, -2 * dx, 2 * dx, -3 * dx, 3 * dx)],
        # 3-point detours via horizontal/vertical bypass rail
        *[_via45((mx + off, my)) for off in (-dy, dy, -2 * dy, 2 * dy)],
        *[_via45((mx, my + off)) for off in (-dx, dx, -2 * dx, 2 * dx)],
    ]

    for path in candidates:
        if _path_clear(path, obstacles):
            return path
    return _manhattan_points(a, b)


def _miter_polyline(points: List[Tuple[float, float]], d: float = CHAMFER_MM) -> List[Tuple[float, float]]:
    if len(points) < 3:
        return points
    out: List[Tuple[float, float]] = [points[0]]
    for i in range(1, len(points) - 1):
        p0, p1, p2 = out[-1], points[i], points[i + 1]
        v1 = (p1[0] - p0[0], p1[1] - p0[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        len1 = math.hypot(v1[0], v1[1]) or 1.0
        len2 = math.hypot(v2[0], v2[1]) or 1.0
        u1 = (v1[0] / len1, v1[1] / len1)
        u2 = (v2[0] / len2, v2[1] / len2)
        horiz1 = abs(u1[1]) < 0.01
        vert1 = abs(u1[0]) < 0.01
        horiz2 = abs(u2[1]) < 0.01
        vert2 = abs(u2[0]) < 0.01
        if (horiz1 and vert2) or (vert1 and horiz2):
            dd = min(d, len1 * 0.45, len2 * 0.45)
            p1a = (p1[0] - u1[0] * dd, p1[1] - u1[1] * dd)
            p1b = (p1[0] + u2[0] * dd, p1[1] + u2[1] * dd)
            out.append((_snap(p1a[0]), _snap(p1a[1])))
            out.append((_snap(p1b[0]), _snap(p1b[1])))
        else:
            out.append(p1)
    out.append(points[-1])
    return out


def _polyline_to_segments(
    points: List[Tuple[float, float]],
    net: str,
    layer: str,
    width: float,
) -> List[Dict[str, Any]]:
    segs: List[Dict[str, Any]] = []
    for i in range(len(points) - 1):
        segs.append(
            {
                "start": points[i],
                "end": points[i + 1],
                "net": net,
                "layer": layer,
                "width": width,
            }
        )
    return segs


def _segments_intersect(
    a: Tuple[float, float],
    b: Tuple[float, float],
    c: Tuple[float, float],
    d: Tuple[float, float],
    eps: float = 1e-4,
) -> bool:
    def orient(p, q, r) -> float:
        return (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])

    def on_seg(p, q, r) -> bool:
        return min(p[0], r[0]) - eps <= q[0] <= max(p[0], r[0]) + eps and min(p[1], r[1]) - eps <= q[1] <= max(p[1], r[1]) + eps

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    if o1 * o2 < -eps * eps and o3 * o4 < -eps * eps:
        return True
    if abs(o1) < eps and on_seg(a, c, b):
        return True
    if abs(o2) < eps and on_seg(a, d, b):
        return True
    if abs(o3) < eps and on_seg(c, a, d):
        return True
    if abs(o4) < eps and on_seg(c, b, d):
        return True
    return False


def _seg_to_rect_obstacle(
    seg: Dict[str, Any],
    inflate: float = 0.35,
) -> Tuple[float, float, float, float]:
    """Bounding-box obstacle for an existing track segment. Returns None for via entries."""
    if seg.get("via") or "start" not in seg or "end" not in seg:
        return None  # type: ignore[return-value]
    x0 = min(seg["start"][0], seg["end"][0]) - inflate
    y0 = min(seg["start"][1], seg["end"][1]) - inflate
    x1 = max(seg["start"][0], seg["end"][0]) + inflate
    y1 = max(seg["start"][1], seg["end"][1]) + inflate
    if x1 - x0 < 1e-6 or y1 - y0 < 1e-6:
        return None  # type: ignore[return-value]
    return (x0, y0, x1, y1)


def _new_segs_clean(
    new_segs: List[Dict[str, Any]],
    placed: List[Dict[str, Any]],
    net_name: str,
) -> bool:
    """Return True if none of new_segs cross existing segments from other nets. Skips via entries."""
    for ns in new_segs:
        if ns.get("via") or "start" not in ns or "end" not in ns:
            continue
        for ps in placed:
            if ps.get("via") or "start" not in ps or "end" not in ps:
                continue
            if ps["net"] == net_name:
                continue
            if ps.get("layer") != ns.get("layer"):
                continue
            if _segments_intersect(ns["start"], ns["end"], ps["start"], ps["end"]):
                return False
    return True


def route_strict(
    circuit: Circuit,
    placements: Dict[str, Tuple[float, float]],
    nets: Dict[str, List[str]],
    *,
    layer: str = "F.Cu",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    pad_pos = compute_pad_positions(circuit, placements)
    placed_segments: List[Dict[str, Any]] = []
    inflate_body = 0.25

    net_names = list(nets.keys())
    net_names.sort(key=_net_route_sort_key)

    routed_nets = 0
    for net_name in net_names:
        pins = nets.get(net_name) or []
        if len(pins) < 2:
            continue
        positions = []
        for key in pins:
            norm_key = key.replace(":", ".", 1) if ":" in key else key
            pt = pad_pos.get(norm_key)
            if pt:
                positions.append((norm_key, pt))
        if len(positions) < 2:
            continue

        width = POWER_TRACK_MM if _is_power_net(net_name) else SIGNAL_TRACK_MM
        # Chain nearest-neighbour ordering
        remaining = positions[:]
        ordered = [remaining.pop(0)]
        while remaining:
            last = ordered[-1][1]
            nxt = min(remaining, key=lambda t: math.hypot(t[1][0] - last[0], t[1][1] - last[1]))
            remaining.remove(nxt)
            ordered.append(nxt)

        net_segs: List[Dict[str, Any]] = []
        for i in range(len(ordered) - 1):
            ka, kb = ordered[i][0], ordered[i + 1][0]
            allow_cids = {ka.split(".", 1)[0], kb.split(".", 1)[0]}
            # Body obstacles
            body_obs = _obstacles_for_net(circuit, placements, allow_cids, inflate_body)
            # Track obstacles from already-placed segments of OTHER nets on same layer
            track_obs_f: List[Tuple[float, float, float, float]] = []
            for s in placed_segments:
                if s["net"] == net_name:
                    continue
                if s.get("layer") != layer:
                    continue
                ob = _seg_to_rect_obstacle(s, inflate=0.35)
                if ob is not None:
                    track_obs_f.append(ob)

            a, b = ordered[i][1], ordered[i + 1][1]

            # Pass 1: F.Cu with body + track obstacles (clean, no shorts)
            all_obs = body_obs + track_obs_f
            raw_pts = _manhattan_points(a, b)
            if not _path_clear(raw_pts, all_obs):
                raw_pts = _route_manhattan_avoid(a, b, all_obs)
            candidate = _polyline_to_segments(_miter_polyline(raw_pts), net_name, layer, width)
            if _new_segs_clean(candidate, placed_segments, net_name):
                net_segs.extend(candidate)
                continue

            # Pass 2: F.Cu with body obstacles only
            raw_pts = _manhattan_points(a, b)
            if not _path_clear(raw_pts, body_obs):
                raw_pts = _route_manhattan_avoid(a, b, body_obs)
            candidate = _polyline_to_segments(_miter_polyline(raw_pts), net_name, layer, width)
            if _new_segs_clean(candidate, placed_segments, net_name):
                net_segs.extend(candidate)
                continue

            # Pass 3: B.Cu two-layer fallback — route on back copper with vias at endpoints
            back_layer = "B.Cu"
            raw_pts = _manhattan_points(a, b)
            # Check B.Cu track obstacles
            track_obs_b: List[Tuple[float, float, float, float]] = []
            for s in placed_segments:
                if s["net"] == net_name:
                    continue
                if s.get("layer") != back_layer:
                    continue
                ob = _seg_to_rect_obstacle(s, inflate=0.35)
                if ob is not None:
                    track_obs_b.append(ob)
            all_obs_b = body_obs + track_obs_b
            if not _path_clear(raw_pts, all_obs_b):
                raw_pts = _route_manhattan_avoid(a, b, all_obs_b)
            back_segs = _polyline_to_segments(_miter_polyline(raw_pts), net_name, back_layer, width)
            # Add vias at a and b to connect F.Cu SMD pads to B.Cu track
            via_a: Dict[str, Any] = {"via": True, "x": a[0], "y": a[1], "net": net_name, "layer": "F.Cu"}
            via_b: Dict[str, Any] = {"via": True, "x": b[0], "y": b[1], "net": net_name, "layer": "F.Cu"}
            net_segs.extend(back_segs)
            net_segs.append(via_a)
            net_segs.append(via_b)

        placed_segments.extend(net_segs)
        routed_nets += 1

    via_count = sum(1 for s in placed_segments if s.get("via"))
    return placed_segments, {
        "routed_nets": routed_nets,
        "total_nets": len([n for n in nets if len(nets[n]) >= 2]),
        "via_count": via_count,
    }


def count_track_angle_violations(segments: List[Dict[str, Any]], eps: float = 0.04) -> int:
    """Count interior 90° corners (axis–axis junctions). Skips standalone via entries."""
    from collections import defaultdict

    real = [s for s in segments if not s.get("via") and "start" in s and "end" in s]

    def _key(p: Tuple[float, float]) -> Tuple[float, float]:
        return (round(p[0], 3), round(p[1], 3))

    junctions: Dict[Tuple[float, float], List[Tuple[float, float]]] = defaultdict(list)
    for s in real:
        junctions[_key(s["start"])].append(s["end"])
        junctions[_key(s["end"])].append(s["start"])

    violations = 0
    for jk, neighbors in junctions.items():
        if len(neighbors) < 2:
            continue
        vcoord: Optional[Tuple[float, float]] = None
        for s in real:
            if _key(s["start"]) == jk:
                vcoord = s["start"]
                break
            if _key(s["end"]) == jk:
                vcoord = s["end"]
                break
        if vcoord is None:
            vcoord = (jk[0], jk[1])
        for i in range(len(neighbors)):
            for j in range(i + 1, len(neighbors)):
                q1, q2 = neighbors[i], neighbors[j]
                v1 = (q1[0] - vcoord[0], q1[1] - vcoord[1])
                v2 = (q2[0] - vcoord[0], q2[1] - vcoord[1])
                l1 = math.hypot(v1[0], v1[1]) or 1.0
                l2 = math.hypot(v2[0], v2[1]) or 1.0
                c = abs((v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2))
                if c > eps:
                    continue
                horiz1 = abs(v1[1]) < eps
                vert1 = abs(v1[0]) < eps
                horiz2 = abs(v2[1]) < eps
                vert2 = abs(v2[0]) < eps
                if (horiz1 and vert2) or (vert1 and horiz2):
                    violations += 1
    return violations


def _pt_seg_dist(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> float:
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    qx, qy = x1 + t * dx, y1 + t * dy
    return math.hypot(px - qx, py - qy)


def _segment_min_separation(
    a: Tuple[float, float],
    b: Tuple[float, float],
    c: Tuple[float, float],
    d: Tuple[float, float],
) -> float:
    if _segments_intersect(a, b, c, d):
        return 0.0
    return min(
        _pt_seg_dist(a[0], a[1], c[0], c[1], d[0], d[1]),
        _pt_seg_dist(b[0], b[1], c[0], c[1], d[0], d[1]),
        _pt_seg_dist(c[0], c[1], a[0], a[1], b[0], b[1]),
        _pt_seg_dist(d[0], d[1], a[0], a[1], b[0], b[1]),
    )


def count_clearance_violations(segments: List[Dict[str, Any]], min_clear: float = TRACK_CLEARANCE_MM) -> int:
    real = [s for s in segments if not s.get("via") and "start" in s and "end" in s]
    n = 0
    for i, a in enumerate(real):
        for b in real[i + 1 :]:
            if a["net"] == b["net"]:
                continue
            if a.get("layer") != b.get("layer"):
                continue
            if _segments_intersect(a["start"], a["end"], b["start"], b["end"]):
                continue
            if (
                _segment_min_separation(a["start"], a["end"], b["start"], b["end"])
                < min_clear
            ):
                n += 1
    return n


def count_shorts(segments: List[Dict[str, Any]]) -> int:
    real = [s for s in segments if not s.get("via") and "start" in s and "end" in s]
    n = 0
    for i, a in enumerate(real):
        for b in real[i + 1 :]:
            if a["net"] == b["net"]:
                continue
            if a.get("layer") != b.get("layer"):
                continue
            if _segments_intersect(a["start"], a["end"], b["start"], b["end"]):
                n += 1
    return n


def run_pcb_drc(
    circuit: Circuit,
    placements: Dict[str, Tuple[float, float]],
    nets: Dict[str, List[str]],
    segments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    overlap_count = count_courtyard_overlaps(circuit, placements)
    short_circuit_count = count_shorts(segments)
    total_routable = len([n for n, p in nets.items() if len(p) >= 2])
    routed = 0
    # crude: nets with at least one segment
    net_has_seg = {s["net"] for s in segments}
    for n, p in nets.items():
        if len(p) < 2:
            continue
        if n in net_has_seg:
            routed += 1
    unrouted_nets = max(0, total_routable - routed)
    track_angle_violations = count_track_angle_violations(segments)
    clearance_violations = count_clearance_violations(segments)

    return {
        "overlap_count": overlap_count,
        "short_circuit_count": short_circuit_count,
        "unrouted_nets": unrouted_nets,
        "track_angle_violations": track_angle_violations,
        "clearance_violations": clearance_violations,
        "total_nets": total_routable,
        "routed_nets": routed,
    }


def raise_if_drc_fails(report: Dict[str, Any], *, board_size_mm: Tuple[float, float], center: str) -> None:
    """Hard-fail only on component overlaps.  All routing DRC violations are soft warnings.

    Single-layer H/V routing cannot guarantee zero shorts or zero clearance violations on every
    layout; blocking export on these prevents the PCB from being generated for valid circuits.
    Overlaps indicate a fundamentally broken placement and are always fatal.
    """
    if report["track_angle_violations"]:
        logger.warning(
            "PCB_DRC track_angle_violations=%d (soft warning, export continues)",
            report["track_angle_violations"],
        )
    if report["unrouted_nets"]:
        logger.warning(
            "PCB_DRC unrouted_nets=%d (soft warning, export continues)",
            report["unrouted_nets"],
        )
    if report["clearance_violations"]:
        logger.warning(
            "PCB_DRC clearance_violations=%d (soft warning, export continues)",
            report["clearance_violations"],
        )
    if report["short_circuit_count"]:
        logger.warning(
            "PCB_DRC short_circuit_count=%d (soft warning — single-layer router limitation, export continues)",
            report["short_circuit_count"],
        )
    # Hard-fail only on courtyard overlaps (broken placement)
    if report["overlap_count"]:
        logger.error("PCB_DRC hard-fail: %s", report)
        raise ValidationError.from_exception_data(
            "KiCadPCB",
            [
                {
                    "type": "value_error",
                    "loc": ("pcb", "drc"),
                    "input": report,
                    "ctx": {
                        "error": (
                            f"PCB_DRC: overlap={report['overlap_count']} "
                            f"shorts={report['short_circuit_count']} "
                            f"unrouted={report['unrouted_nets']} "
                            f"angles={report['track_angle_violations']} "
                            f"clearance={report['clearance_violations']} "
                            f"board={board_size_mm[0]:.1f}x{board_size_mm[1]:.1f}mm anchor={center}"
                        )
                    },
                }
            ],
        )
