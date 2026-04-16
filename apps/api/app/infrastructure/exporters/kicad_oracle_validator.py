from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, Optional

from app.infrastructure.exporters.kicad_cli_renderer import KiCadCLIRenderer


@dataclass(frozen=True)
class KiCadOracleReport:
    target: str
    status: str
    available: bool
    passed: bool
    backend: str = "kicad-cli"
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "status": self.status,
            "available": self.available,
            "passed": self.passed,
            "backend": self.backend,
            "message": self.message,
            "details": dict(self.details),
        }


class KiCadOracleValidator:
    """Best-effort KiCad oracle checks using kicad-cli as backend."""

    def __init__(
        self,
        renderer: Optional[KiCadCLIRenderer] = None,
        timeout_seconds: int = 30,
    ) -> None:
        self.renderer = renderer or KiCadCLIRenderer()
        self.timeout_seconds = max(5, int(timeout_seconds))

    async def validate_schematic(self, schematic_file: Path) -> KiCadOracleReport:
        if not self.renderer.is_available():
            return KiCadOracleReport(
                target="schematic",
                status="unavailable",
                available=False,
                passed=False,
                message="kicad-cli not available",
            )

        if not schematic_file.exists():
            return KiCadOracleReport(
                target="schematic",
                status="failed",
                available=True,
                passed=False,
                message="schematic file not found",
                details={"file": str(schematic_file)},
            )

        try:
            with TemporaryDirectory(prefix="kicad_oracle_sch_") as tmp:
                svg_path = await self.renderer.render_to_svg(
                    input_kicad_sch=schematic_file,
                    output_dir=Path(tmp),
                )
                passed = svg_path is not None and svg_path.exists()
                return KiCadOracleReport(
                    target="schematic",
                    status="passed" if passed else "failed",
                    available=True,
                    passed=passed,
                    message="schematic renders with kicad-cli" if passed else "kicad-cli schematic render failed",
                )
        except Exception as exc:
            return KiCadOracleReport(
                target="schematic",
                status="error",
                available=True,
                passed=False,
                message=f"schematic oracle error: {exc}",
            )

    async def validate_pcb(self, pcb_file: Path) -> KiCadOracleReport:
        if not self.renderer.is_available():
            return KiCadOracleReport(
                target="pcb",
                status="unavailable",
                available=False,
                passed=False,
                message="kicad-cli not available",
            )

        if not pcb_file.exists():
            return KiCadOracleReport(
                target="pcb",
                status="failed",
                available=True,
                passed=False,
                message="pcb file not found",
                details={"file": str(pcb_file)},
            )

        try:
            with TemporaryDirectory(prefix="kicad_oracle_pcb_") as tmp:
                output_dir = Path(tmp)
                command = [
                    self.renderer.kicad_cli_path,
                    "pcb",
                    "export",
                    "svg",
                    "--output",
                    str(output_dir),
                    str(pcb_file),
                ]

                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self.timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    await process.communicate()
                    return KiCadOracleReport(
                        target="pcb",
                        status="failed",
                        available=True,
                        passed=False,
                        message="kicad-cli pcb export timed out",
                    )

                if process.returncode != 0:
                    stderr_text = (stderr or b"").decode(errors="replace").strip()
                    return KiCadOracleReport(
                        target="pcb",
                        status="failed",
                        available=True,
                        passed=False,
                        message="kicad-cli pcb export failed",
                        details={
                            "return_code": process.returncode,
                            "stderr": stderr_text[:500],
                        },
                    )

                svg_count = len(list(output_dir.glob("*.svg")))
                passed = svg_count > 0
                return KiCadOracleReport(
                    target="pcb",
                    status="passed" if passed else "failed",
                    available=True,
                    passed=passed,
                    message="pcb exports to svg" if passed else "pcb export produced no svg",
                    details={
                        "svg_count": svg_count,
                        "stdout": (stdout or b"").decode(errors="replace")[:500],
                    },
                )
        except Exception as exc:
            return KiCadOracleReport(
                target="pcb",
                status="error",
                available=True,
                passed=False,
                message=f"pcb oracle error: {exc}",
            )
