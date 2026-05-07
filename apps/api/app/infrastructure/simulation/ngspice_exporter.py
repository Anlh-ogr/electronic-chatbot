from __future__ import annotations

"""Thin adapter to generate SPICE netlists from CircuitIR.

This module wraps the application-level NgspiceCompilerService so other
infrastructure code can request a compiled SPICE deck from a CircuitIR
instance.
"""

from typing import Optional

from app.application.ai.simulation_service import NgspiceCompilerService
from app.application.ai.circuit_ir_schema import CircuitIR


class NgspiceExporter:
    """Provide a simple interface to produce a .cir deck from CircuitIR."""

    def __init__(self, executable: Optional[str] = None, timeout_seconds: int = 90) -> None:
        self._svc = NgspiceCompilerService(executable=executable, timeout_seconds=timeout_seconds)

    def generate_from_ir(self, ir: CircuitIR) -> str:
        """Return a SPICE deck string compiled from `ir`.

        The deck will include element lines, model cards and a small testbench
        that writes `output.tsv` and `output.raw` when run by `ngspice`.
        """
        return self._svc.generate_spice_deck(ir)
