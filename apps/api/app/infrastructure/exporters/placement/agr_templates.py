from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .topology_classifier import PlacementFamily


GRID_MM = 1.27
STACK_STEP_GRIDS = 2
STAGE_WIDTH_GRIDS = 200


@dataclass(frozen=True)
class RoleTemplate:
    role: str
    anchor: str
    dx_grids: int
    dy_grids: int
    rotation: int
    stack_axis: str


def get_templates(family: PlacementFamily) -> Dict[str, RoleTemplate]:
    if family == PlacementFamily.OPAMP_IC:
        return _opamp_templates()
    if family in {PlacementFamily.PUSH_PULL, PlacementFamily.CLASS_D}:
        return _push_pull_templates()
    return _single_transistor_templates()


def _single_transistor_templates() -> Dict[str, RoleTemplate]:
    return {
        "coupling_in": RoleTemplate("coupling_in", "input_pin", -4, 0, 90, "y"),
        "coupling_out": RoleTemplate("coupling_out", "output_pin", 4, 0, 90, "y"),
        "bias_top": RoleTemplate("bias_top", "bias_pin", -2, -4, 0, "y"),
        "bias_bottom": RoleTemplate("bias_bottom", "bias_pin", -2, 4, 0, "y"),
        "load": RoleTemplate("load", "upper_pin", 0, -4, 0, "y"),
        "degeneration": RoleTemplate("degeneration", "lower_pin", 0, 4, 0, "y"),
        "bypass": RoleTemplate("bypass", "lower_pin", 2, 4, 90, "y"),
        "feedback": RoleTemplate("feedback", "output_pin", -2, -4, 90, "y"),
        "supply": RoleTemplate("supply", "upper_pin", 0, -8, 0, "y"),
        "ground": RoleTemplate("ground", "lower_pin", 0, 8, 0, "y"),
        "gate_drive": RoleTemplate("gate_drive", "input_pin", -6, 0, 90, "y"),
    }


def _opamp_templates() -> Dict[str, RoleTemplate]:
    return {
        "coupling_in": RoleTemplate("coupling_in", "input_pin", -4, 0, 90, "y"),
        "feedback": RoleTemplate("feedback", "inv_pin", -2, -4, 90, "y"),
        "coupling_out": RoleTemplate("coupling_out", "output_pin", 4, 0, 90, "y"),
        "supply": RoleTemplate("supply", "supply_pin", 0, -4, 0, "y"),
        "ground": RoleTemplate("ground", "ground_pin", 0, 4, 0, "y"),
    }


def _push_pull_templates() -> Dict[str, RoleTemplate]:
    return {
        "coupling_in": RoleTemplate("coupling_in", "origin", -4, 0, 90, "y"),
        "coupling_out": RoleTemplate("coupling_out", "origin", 4, 0, 90, "y"),
        "bias_top": RoleTemplate("bias_top", "origin", -2, -4, 0, "y"),
        "bias_bottom": RoleTemplate("bias_bottom", "origin", -2, 4, 0, "y"),
        "load": RoleTemplate("load", "origin", 4, 0, 0, "y"),
        "supply": RoleTemplate("supply", "origin", 0, -8, 0, "y"),
        "ground": RoleTemplate("ground", "origin", 0, 8, 0, "y"),
        "filter": RoleTemplate("filter", "origin", 6, 0, 90, "y"),
    }


__all__ = ["GRID_MM", "STACK_STEP_GRIDS", "STAGE_WIDTH_GRIDS", "RoleTemplate", "get_templates"]
