import sys
from pathlib import Path

import pytest

# Ensure app package imports work when running tests from apps/api
APP_DIR = Path(__file__).resolve().parents[2] / "app"
sys.path.insert(0, str(APP_DIR))

from app.application.circuits.dtos import ExportCircuitRequest, ExportFormat
from app.application.circuits.errors import ExportError
from app.application.circuits.use_cases.export_kicad_pcb import ExportKiCadPCBUseCase
from app.application.circuits.use_cases.export_kicad_sch import ExportKiCadSchUseCase
from app.domains.circuits.entities import Circuit


class _RepoStub:
    def __init__(self, circuit: Circuit) -> None:
        self._circuit = circuit

    async def get(self, circuit_id: str):
        return self._circuit


class _SchExporterStub:
    def __init__(self, content: str, quality_report: dict | None = None) -> None:
        self._content = content
        self._quality_report = quality_report

    async def export(self, circuit: Circuit, format_type: ExportFormat) -> str:
        return self._content

    def get_last_layout_quality_report(self):
        return self._quality_report


class _PcbExporterStub:
    def __init__(self, content: str) -> None:
        self._content = content

    async def export(self, circuit: Circuit, format_type: ExportFormat) -> str:
        return self._content


class _OracleReportStub:
    def __init__(self, target: str, status: str, passed: bool, message: str) -> None:
        self._payload = {
            "target": target,
            "status": status,
            "available": True,
            "passed": passed,
            "backend": "kicad-cli",
            "message": message,
            "details": {},
        }

    def to_dict(self) -> dict:
        return dict(self._payload)


class _OracleValidatorStub:
    def __init__(self, sch_status: str = "passed", pcb_status: str = "passed") -> None:
        self.sch_status = sch_status
        self.pcb_status = pcb_status

    async def validate_schematic(self, file_path: Path):
        return _OracleReportStub(
            target="schematic",
            status=self.sch_status,
            passed=self.sch_status == "passed",
            message=f"schematic status={self.sch_status}",
        )

    async def validate_pcb(self, file_path: Path):
        return _OracleReportStub(
            target="pcb",
            status=self.pcb_status,
            passed=self.pcb_status == "passed",
            message=f"pcb status={self.pcb_status}",
        )


@pytest.mark.asyncio
async def test_schematic_export_includes_oracle_and_layout_quality_metadata(tmp_path: Path) -> None:
    circuit = Circuit(name="amp_chain", id="circuit_1234")
    repo = _RepoStub(circuit)
    exporter = _SchExporterStub(
        content="(kicad_sch)",
        quality_report={
            "objective": 12.0,
            "component_overlap_count": 0,
            "center_attachment_count": 0,
            "is_hard_valid": True,
        },
    )
    oracle = _OracleValidatorStub(sch_status="passed")

    use_case = ExportKiCadSchUseCase(
        repository=repo,
        exporter=exporter,
        storage_path=tmp_path,
        oracle_validator=oracle,
    )

    request = ExportCircuitRequest(
        circuit_id="circuit_1234",
        format=ExportFormat.KICAD,
        options={"oracle_validate": True},
    )
    response = await use_case.execute(request)

    assert response.file_path is not None
    assert response.metadata["oracle"]["status"] == "passed"
    assert response.metadata["oracle"]["enabled"] is True
    assert response.metadata["layout_quality"]["is_hard_valid"] is True


@pytest.mark.asyncio
async def test_schematic_export_strict_oracle_failure_raises(tmp_path: Path) -> None:
    circuit = Circuit(name="amp_chain", id="circuit_9999")
    repo = _RepoStub(circuit)
    exporter = _SchExporterStub(content="(kicad_sch)")
    oracle = _OracleValidatorStub(sch_status="failed")

    use_case = ExportKiCadSchUseCase(
        repository=repo,
        exporter=exporter,
        storage_path=tmp_path,
        oracle_validator=oracle,
    )

    request = ExportCircuitRequest(
        circuit_id="circuit_9999",
        format=ExportFormat.KICAD,
        options={"oracle_validate": True, "oracle_strict": True},
    )

    with pytest.raises(ExportError, match="Oracle validation failed in strict mode"):
        await use_case.execute(request)


@pytest.mark.asyncio
async def test_pcb_export_soft_oracle_failure_keeps_artifact(tmp_path: Path) -> None:
    circuit = Circuit(name="amp_board", id="board_1234")
    repo = _RepoStub(circuit)
    exporter = _PcbExporterStub(content="(kicad_pcb)")
    oracle = _OracleValidatorStub(pcb_status="failed")

    use_case = ExportKiCadPCBUseCase(
        repository=repo,
        exporter=exporter,
        storage_path=tmp_path,
        oracle_validator=oracle,
    )

    request = ExportCircuitRequest(
        circuit_id="board_1234",
        format=ExportFormat.KICAD_PCB,
        options={"oracle_validate": True, "oracle_strict": False},
    )
    response = await use_case.execute(request)

    assert response.file_path is not None
    assert response.metadata["oracle"]["status"] == "failed"
    assert response.metadata["oracle"]["enabled"] is True
