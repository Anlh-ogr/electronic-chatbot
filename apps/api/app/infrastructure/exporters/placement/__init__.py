"""Deterministic schematic placement helpers for exporters."""

from .topology_classifier import PlacementFamily, classify, classify_stage
from .role_inferrer import infer_roles
from .agr_templates import RoleTemplate, get_templates
from .geometry_manager import GeometryManager
from .pin_resolver import resolve_pins, rotate_offsets
from .coordinate_solver import (
    GRID_MM,
    ComponentSpec,
    PlacedComponent,
    PlacementResult,
    solve_stage,
)
from .multistage_composer import compose
from .topology_anchor_offsets import (
    TOPOLOGY_ANCHOR_OFFSETS,
    CE_OFFSETS,
    CB_OFFSETS,
    CC_OFFSETS,
    INV_OFFSETS,
    NONINV_OFFSETS,
)

__all__ = [
    "GeometryManager",
    "PlacementFamily",
    "classify",
    "classify_stage",
    "infer_roles",
    "RoleTemplate",
    "get_templates",
    "resolve_pins",
    "rotate_offsets",
    "GRID_MM",
    "ComponentSpec",
    "PlacedComponent",
    "PlacementResult",
    "solve_stage",
    "compose",
    "TOPOLOGY_ANCHOR_OFFSETS",
    "CE_OFFSETS",
    "CB_OFFSETS",
    "CC_OFFSETS",
    "INV_OFFSETS",
    "NONINV_OFFSETS",
]
