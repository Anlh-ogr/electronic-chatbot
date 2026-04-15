from __future__ import annotations

import json
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path

from app.application.circuits.dtos import ExportCircuitResponse, ExportFormat
from app.application.circuits.services import industrial_routing_job_queue as queue_mod


class _LocalEnum(Enum):
    SAMPLE = "sample"


class _ModelDumpNoMode:
    def model_dump(self):
        return {
            "when": datetime(2026, 4, 13, 10, 11, 12),
            "kind": _LocalEnum.SAMPLE,
        }


class _DictLike:
    def dict(self):
        return {
            "where": Path("artifacts/exports/pcb/test.kicad_pcb"),
            "at": date(2026, 4, 13),
            "clock": time(10, 11, 12),
        }


def test_serialize_export_response_pydantic_model_is_json_safe() -> None:
    payload = ExportCircuitResponse(
        circuit_id="circuit-1",
        format=ExportFormat.KICAD_PCB,
        file_path="artifacts/exports/pcb/test.kicad_pcb",
    )

    serialized = queue_mod._serialize_export_response(payload)

    assert isinstance(serialized, dict)
    assert isinstance(serialized.get("export_time"), str)
    decoded = json.loads(queue_mod._json_dumps(serialized))
    assert isinstance(decoded.get("export_time"), str)


def test_to_json_compatible_handles_model_dump_typeerror_and_dict_fallback() -> None:
    model_like = queue_mod._to_json_compatible(_ModelDumpNoMode())
    dict_like = queue_mod._to_json_compatible(_DictLike())

    assert model_like["when"] == "2026-04-13T10:11:12"
    assert model_like["kind"] == "sample"

    assert str(dict_like["where"]).endswith("test.kicad_pcb")
    assert dict_like["at"] == "2026-04-13"
    assert dict_like["clock"] == "10:11:12"

    json.loads(queue_mod._json_dumps(model_like))
    json.loads(queue_mod._json_dumps(dict_like))


def test_serialize_export_response_normalizes_nested_payload_types() -> None:
    nested_payload = {
        "ts": datetime(2026, 4, 13, 8, 30, 0),
        "enum": _LocalEnum.SAMPLE,
        "path": Path("artifacts/exports/pcb"),
        "items": [date(2026, 4, 13), time(8, 30, 0)],
        "set_values": {3, 1, 2},
    }

    serialized = queue_mod._serialize_export_response(nested_payload)
    decoded = json.loads(queue_mod._json_dumps(serialized))

    assert decoded["ts"] == "2026-04-13T08:30:00"
    assert decoded["enum"] == "sample"
    assert str(decoded["path"]).endswith("exports\\pcb") or str(decoded["path"]).endswith("exports/pcb")
    assert decoded["items"] == ["2026-04-13", "08:30:00"]
    assert sorted(decoded["set_values"]) == [1, 2, 3]
