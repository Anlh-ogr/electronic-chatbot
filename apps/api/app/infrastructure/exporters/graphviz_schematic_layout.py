# app/infrastructure/exporters/graphviz_schematic_layout.py
"""Schematic placement using Graphviz (pygraphviz).

Produces spread-out (x,y) positions in KiCad mm space with left→right flow.
Falls back gracefully when pygraphviz or the ``dot`` binary is unavailable.
"""

from __future__ import annotations

import logging
import statistics
from typing import Dict, Optional, Tuple

from app.domains.circuits.entities import Circuit
from app.infrastructure.exporters.placement.topology_anchor_offsets import (
    CE_OFFSETS,
    INV_OFFSETS,
    NONINV_OFFSETS,
)

# KiCad schematic 100-mil grid — same constant used by the exporter and
# pin resolver.  Do NOT import from agr_templates (which is 1.27 mm).
GRID_MM: float = 2.54

# KiCad A4 sheet centre in mm — U1 is anchored here so the op-amp layout
# always stays on-canvas regardless of the PyGraphviz initial positions.
_SHEET_CENTER_X: float = 148.5
_SHEET_CENTER_Y: float = 105.0

logger = logging.getLogger(__name__)

_PT_TO_MM = 25.4 / 72.0
# Scale Graphviz points → KiCad mm.
# Increased to 2.5 to give ~20-30 mm centre-to-centre spacing between
# adjacent nodes before the CE / op-amp alignment pass overrides known refs.
_LAYOUT_SCALE = 2.5


def _component_type_lower(comp) -> str:
    t = getattr(comp, "type", None)
    return str(getattr(t, "value", t) or "").strip().lower()


def _ref_norm(ref_upper: str) -> str:
    """Normalize uppercase ref for lookup: strip underscores/hyphens.

    ``C_IN`` → ``CIN``, ``R_E1`` → ``RE1``, ``C_E`` → ``CE``, etc.
    Lets the placement engine match IR-generated IDs (with underscores)
    against template keys (without underscores).
    """
    return ref_upper.replace("_", "").replace("-", "")


def _infer_rotations(circuit: Circuit, placements: Dict[str, Tuple[float, float]]) -> Dict[str, int]:
    """Assign symbol rotations using ref-name role detection (strategy §3.2).

    Role-to-rotation table (0 = vertical, 90 = horizontal):
      - Coupling caps CIN/COUT/C_IN/C_OUT, feedback Rf/Rg → 90
      - Everything else (load, bias, degeneration, bypass, power, BJT, op-amp) → 0
    """
    # Upper-cased ref → original case comp_id for lookup
    ids_upper = {str(k).upper(): k for k in circuit.components.keys()}
    rotations: Dict[str, int] = {}

    # Horizontal (90°): coupling caps and feedback passives on the signal path
    _HORIZONTAL_PREFIXES = {
        "CIN", "COUT", "C_IN", "C_OUT", "C1_IN", "C1_OUT",
        "RF", "R_F", "RG", "R_G",
    }
    _HORIZONTAL_PARTIAL = ("_CIN", "_COUT", "_IN_C", "_OUT_C")

    for ku, orig_cid in ids_upper.items():
        is_horizontal = ku in _HORIZONTAL_PREFIXES or any(
            ku.endswith(sfx) for sfx in _HORIZONTAL_PARTIAL
        )
        # Strip trailing digit: CIN1 → CIN, COUT2 → COUT
        stripped = ku.rstrip("0123456789")
        if stripped in _HORIZONTAL_PREFIXES:
            is_horizontal = True

        rotations[orig_cid] = 90 if is_horizontal else 0

    return rotations


def _find_layout_anchor(circuit: Circuit) -> Optional[str]:
    """Prefer BJT Qx, else first op-amp — used to contract spread-out dot layouts."""
    for cid, comp in circuit.components.items():
        t = _component_type_lower(comp)
        if t in {"bjt_npn", "bjt_pnp", "npn", "pnp"} or "bjt" in t:
            return cid
    for cid, comp in circuit.components.items():
        t = _component_type_lower(comp)
        if t in {"opamp", "opamp_ic"}:
            return cid
    return None


def _contract_placements_toward_anchor(
    placements: Dict[str, Tuple[float, float]],
    anchor: Optional[str],
    factor: float = 0.46,
) -> Dict[str, Tuple[float, float]]:
    if anchor is None or anchor not in placements or factor >= 0.999:
        return placements
    ax, ay = placements[anchor]
    return {k: (ax + (x - ax) * factor, ay + (y - ay) * factor) for k, (x, y) in placements.items()}


def _opamp_topology_offsets(circuit: Circuit) -> dict[str, tuple[int, int]]:
    label = (
        str(getattr(circuit, "topology_type", "") or "")
        + " "
        + str(getattr(circuit, "category", "") or "")
    ).lower()
    if "inverting" in label and "non" not in label and "non_inverting" not in label:
        return dict(INV_OFFSETS)
    return dict(NONINV_OFFSETS)


def _align_opamp_anchors(
    circuit: Circuit,
    placements: Dict[str, Tuple[float, float]],
    *,
    spacing_scale: float = 1.0,
) -> Dict[str, Tuple[float, float]]:
    """Snap key refs to §4.2 op-amp grid (inverting vs non-inverting) around U1.

    U1 is **forced to the KiCad sheet centre** (_SHEET_CENTER_X, _SHEET_CENTER_Y)
    so the entire op-amp layout is guaranteed to stay on-canvas regardless of
    where PyGraphviz initially placed the nodes.  All other components are
    placed as multiples of ``spacing_scale × GRID_MM`` relative to U1.

    ``spacing_scale = 4.0`` gives 30–40 mm between adjacent components, matching
    the CE layout density.  The IN/OUT connectors are placed just beyond the
    coupling caps so they are always on-sheet.
    """
    ids_upper = {str(k).upper(): k for k in circuit.components.keys()}
    ids_norm  = {_ref_norm(str(k).upper()): k for k in circuit.components.keys()}

    def _lookup(key: str) -> Optional[str]:
        if key in ids_upper:
            return ids_upper[key]
        return ids_norm.get(_ref_norm(key))

    # Locate U1 (prefer a component typed as opamp/opamp_ic)
    u_key = None
    for ku, orig in ids_upper.items():
        if not ku.startswith("U"):
            continue
        comp = circuit.components.get(orig)
        if comp and _component_type_lower(comp) in {"opamp", "opamp_ic"}:
            u_key = orig
            break
    if u_key is None:
        for ku, orig in ids_upper.items():
            if ku.startswith("U"):
                u_key = orig
                break
    if u_key is None:
        return placements

    tpl = _opamp_topology_offsets(circuit)
    out = dict(placements)
    # Track which comp_ids were placed by this function (must NOT be contracted).
    tpl_placed: set[str] = set()

    # ── Force U1 to the sheet centre so nothing goes off-canvas ──────────────
    # After center_placements_mm() in the exporter the layout will be re-centred;
    # anchoring U1 here keeps the whole op-amp cluster near the sheet centre
    # before the re-centring step, so extreme outliers don't distort the centroid.
    ox, oy = _SHEET_CENTER_X, _SHEET_CENTER_Y
    out[u_key] = (ox, oy)
    tpl_placed.add(u_key)

    def _set_at(comp_id: str, slot: str) -> None:
        if slot not in tpl:
            return
        gx, gy = tpl[slot]
        out[comp_id] = _apply_offset(ox, oy, gx, gy, spacing_scale)
        tpl_placed.add(comp_id)

    # Place all topology-template refs around U1 at scaled offsets
    for ref_alias, slot in (
        ("U1",             "U1"),
        ("VCC",            "VCC"),
        ("VEE",            "VEE"),
        ("GND",            "GND"),
        ("C_IN",           "CIN"),
        ("CIN",            "CIN"),
        ("C_OUT",          "COUT"),
        ("COUT",           "COUT"),
        ("R_F",            "Rf"),
        ("RF",             "Rf"),
        ("R_G",            "Rg"),
        ("RG",             "Rg"),
        ("RIN",            "Rin"),
        ("R_IN",           "Rin"),
        ("R_IN_DC",        "Rin"),
        ("C_DEC",          "CPS"),
        ("CPS",            "CPS"),
        ("CPN",            "CPN"),
        ("C_BIAS_DECOUPLE","CPN"),
        ("RGND",           "Rgnd"),
    ):
        cid = _lookup(ref_alias)
        if cid is not None and cid in out:
            _set_at(cid, slot)

    # ── IN / OUT connectors: just outside the coupling caps ───────────────────
    cin_gx  = tpl.get("CIN",  (-6, 0))[0]
    cout_gx = tpl.get("COUT", ( 5, 0))[0]
    cin_x  = _apply_offset(ox, oy, cin_gx,  0, spacing_scale)[0]
    cout_x = _apply_offset(ox, oy, cout_gx, 0, spacing_scale)[0]
    for ref_alias in ("IN",):
        cid = _lookup(ref_alias)
        if cid is not None and cid in out:
            out[cid] = (_apply_offset(cin_x,  oy, -3, 0)[0], oy)
            tpl_placed.add(cid)
    for ref_alias in ("OUT",):
        cid = _lookup(ref_alias)
        if cid is not None and cid in out:
            out[cid] = (_apply_offset(cout_x, oy,  3, 0)[0], oy)
            tpl_placed.add(cid)

    # ── Constrain only the PyGraphviz leftovers (non-template components) ─────
    # Topology-placed components keep their exact positions; everything else is
    # pulled 65% of the way toward U1 so it stays on-canvas.
    for cid, pos in list(out.items()):
        if cid in tpl_placed:
            continue   # already placed at the correct topology offset — keep it
        x, y = pos
        out[cid] = (ox + (x - ox) * 0.35, oy + (y - oy) * 0.35)

    return out


def _apply_offset(qx: float, qy: float, gx: int, gy: int, scale: float = 1.0) -> tuple[float, float]:
    """Convert grid-unit offset to mm and snap to 2.54 mm grid."""
    raw_x = qx + gx * GRID_MM * scale
    raw_y = qy + gy * GRID_MM * scale
    return (round(raw_x / GRID_MM) * GRID_MM, round(raw_y / GRID_MM) * GRID_MM)


def _align_common_emitter_columns(
    circuit: Circuit,
    placements: Dict[str, Tuple[float, float]],
    *,
    spacing_scale: float = 1.3,
) -> Dict[str, Tuple[float, float]]:
    """Position all CE components using CE_OFFSETS relative to Q1.

    ``spacing_scale`` stretches offsets to add breathing room without
    modifying the canonical CE_OFFSETS table (strategy §3.3).
    Scale 1.3 ≈ +2.5 mm per grid unit, keeping all results on the 2.54 mm grid.
    """
    out = dict(placements)
    ids_upper = {str(k).upper(): k for k in circuit.components.keys()}
    # Secondary lookup: normalized (no underscores) → original comp_id.
    # Handles IR-generated names like C_IN, C_OUT, C_E, R_E1, R_E2, R_C.
    ids_norm  = {_ref_norm(str(k).upper()): k for k in circuit.components.keys()}

    def _lookup(key: str) -> Optional[str]:
        """Find original comp_id by exact uppercase key or normalized key."""
        if key in ids_upper:
            return ids_upper[key]
        return ids_norm.get(_ref_norm(key))

    q_key = None
    for ku, orig in ids_upper.items():
        if ku.startswith("Q") and _component_type_lower(circuit.components[orig]) in {
            "bjt_npn", "bjt_pnp", "npn", "pnp",
        }:
            q_key = orig
            break
    if q_key is None:
        return out

    qx, qy = out[q_key]

    # --- vertical rail: VCC, collector load, emitter degens, GND -----------
    for pref in ("VCC", "RC", "RE1", "RE2", "RE", "GND"):
        cid = _lookup(pref)
        if cid is None or cid not in out:
            continue
        gx, gy = CE_OFFSETS.get(pref, (0, 0))
        out[cid] = _apply_offset(qx, qy, 0, gy, spacing_scale)

    # --- bias divider: left column -------------------------------------------
    for pref in ("R1", "R2"):
        cid = _lookup(pref)
        if cid is None or cid not in out:
            continue
        gx, gy = CE_OFFSETS.get(pref, (-3, 0))
        out[cid] = _apply_offset(qx, qy, gx, gy, spacing_scale)

    # --- coupling caps -------------------------------------------------------
    cin_gx,  cin_gy  = CE_OFFSETS.get("CIN",  (-5, 0))
    cout_gx, cout_gy = CE_OFFSETS.get("COUT", ( 5, 0))
    cin_pos  = _apply_offset(qx, qy, cin_gx,  cin_gy,  spacing_scale)
    cout_pos = _apply_offset(qx, qy, cout_gx, cout_gy, spacing_scale)

    # Accept both CIN/C_IN (with and without underscore) and legacy C1/C2
    for pref in ("CIN", "C_IN", "C1"):
        cid = _lookup(pref)
        if cid is not None and cid in out:
            out[cid] = cin_pos
    for pref in ("COUT", "C_OUT", "C2"):
        cid = _lookup(pref)
        if cid is not None and cid in out:
            out[cid] = cout_pos

    # --- bypass cap ----------------------------------------------------------
    # Accept CE, C_E, CE1, C_E1
    for pref in ("CE", "C_E", "CE1", "C_E1"):
        cid = _lookup(pref)
        if cid is not None and cid in out:
            cgx, cgy = CE_OFFSETS.get("CE", (2, 5))
            out[cid] = _apply_offset(qx, qy, cgx, cgy, spacing_scale)
            break  # place only the first match

    # --- IO connectors / ports -----------------------------------------------
    # Place connectors 6 grid units (≈ 15 mm) outside the coupling-cap centres
    # so their symbol bodies don't visually overlap the capacitor symbols.
    cin_x  = cin_pos[0]
    cout_x = cout_pos[0]
    for pref in ("IN", "OUT"):
        cid = _lookup(pref)
        if cid is None or cid not in out:
            continue
        if pref == "IN":
            out[cid] = (_apply_offset(cin_x,  qy, -6, 0)[0], qy)
        else:
            out[cid] = (_apply_offset(cout_x, qy,  6, 0)[0], qy)

    return out


def layout_schematic_with_pygraphviz(circuit: Circuit) -> Optional[Tuple[Dict[str, Tuple[float, float]], Dict[str, int]]]:
    """Return placements (mm) and rotations using ``dot`` layout, or None if unavailable."""
    try:
        import pygraphviz as pgv  # type: ignore
    except ImportError:
        logger.debug("pygraphviz not installed; skipping graphviz schematic layout")
        return None

    comp_ids = list(circuit.components.keys())
    if len(comp_ids) < 2:
        return None

    try:
        G = pgv.AGraph(strict=False, directed=True)
        G.graph_attr.update(
            rankdir="LR",
            ranksep="1.0",    # ~10–12 mm rank separation — topology alignment overrides key refs
            nodesep="0.8",    # ~8 mm node separation within rank
            splines="polyline",
            concentrate="false",
        )
        G.node_attr.update(shape="box", fixedsize="false", fontsize="10")

        for cid in comp_ids:
            G.add_node(cid)

        for net in circuit.nets.values():
            refs = sorted({pin.component_id for pin in net.connected_pins})
            if len(refs) < 2:
                continue
            # Chain edges — keeps graph sparse for dot.
            for i in range(len(refs) - 1):
                a, b = refs[i], refs[i + 1]
                if a != b and not G.has_edge(a, b):
                    G.add_edge(a, b)

        if G.number_of_edges() == 0:
            return None

        G.layout(prog="dot")

        placements: Dict[str, Tuple[float, float]] = {}
        for cid in comp_ids:
            try:
                n = G.get_node(cid)
            except Exception:
                continue
            pos_s = n.attr.get("pos")
            if not pos_s:
                continue
            parts = str(pos_s).split(",")
            if len(parts) != 2:
                continue
            x_pt, y_pt = float(parts[0]), float(parts[1])
            x_mm = x_pt * _PT_TO_MM * _LAYOUT_SCALE
            y_mm = -y_pt * _PT_TO_MM * _LAYOUT_SCALE
            placements[cid] = (x_mm, y_mm)

        if len(placements) < len(comp_ids):
            return None

        # Topology-aware alignment: place known refs at exact grid positions
        # relative to the active device (Q1 or U1).
        #
        # spacing_scale = 4.0  →  target 30–40 mm centre-to-centre spacing:
        #   vertical pair (3 units): 3 × 4 × 2.54 = 30.5 mm  ✓ 3 cm
        #   CIN/COUT (5 units):      5 × 4 × 2.54 = 50.8 mm  ✓ 5 cm from Q1
        #
        # Non-overridden components keep their PyGraphviz coordinates; the
        # reduced ranksep/nodesep keeps them from straying too far.
        anchor = _find_layout_anchor(circuit)
        placements = _contract_placements_toward_anchor(placements, anchor, factor=1.0)
        placements = _align_common_emitter_columns(circuit, placements, spacing_scale=4.0)
        placements = _align_opamp_anchors(circuit, placements, spacing_scale=4.0)
        rotations = _infer_rotations(circuit, placements)
        return placements, rotations
    except Exception as exc:
        logger.warning("Graphviz schematic layout failed (%s); falling back to legacy placement", exc)
        return None


def center_placements_mm(
    placements: Dict[str, Tuple[float, float]],
    *,
    target_cx: float | None = None,
    target_cy: float | None = None,
    margin: float = 16.0,
    paper_w: float = 297.0,
    paper_h: float = 210.0,
) -> Dict[str, Tuple[float, float]]:
    """Translate placements so their bbox centroid sits at ``SHEET_CENTER``, then clamp to margins."""
    from app.infrastructure.exporters.placement_constants import SHEET_CENTER

    if target_cx is None:
        target_cx = SHEET_CENTER[0]
    if target_cy is None:
        target_cy = SHEET_CENTER[1]
    if not placements:
        return placements
    xs = [p[0] for p in placements.values()]
    ys = [p[1] for p in placements.values()]
    cx = statistics.mean(xs)
    cy = statistics.mean(ys)
    dx = target_cx - cx
    dy = target_cy - cy
    out: Dict[str, Tuple[float, float]] = {}
    for k, (x, y) in placements.items():
        nx = x + dx
        ny = y + dy
        nx = max(margin, min(paper_w - margin, nx))
        ny = max(margin, min(paper_h - margin, ny))
        out[k] = (nx, ny)
    return out
