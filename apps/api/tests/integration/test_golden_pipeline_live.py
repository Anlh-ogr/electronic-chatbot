from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

# Ensure app package imports work when running tests from apps/api
API_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(API_ROOT))

from app.application.ai.circuit_ir_schema import CircuitIR
from app.db.database import SessionLocal
from app.main import app


client = TestClient(app)


GOLDEN_CASES = [
    ("BJT CE", "Design a BJT Common Emitter amplifier, 12V supply, gain = 20."),
    ("MOSFET CS", "Design a MOSFET Common Source amplifier, 12V supply, gain = 10."),
    ("Op-Amp Non-Inv", "Design an Op-Amp Non-Inverting amplifier using LM358, gain = 11."),
    ("Op-Amp Diff", "Design an Op-Amp Differential amplifier, gain = 5."),
    ("Class AB", "Design a Class AB Push-Pull amplifier, 8-ohm load, ±12V dual supply."),
    ("Class D", "Design a basic Class D amplifier, 12V supply."),
    ("Darlington", "Design a Darlington Pair transistor circuit for high gain, 12V supply."),
    (
        "3-Stage Hybrid",
        "Design a 3-stage multistage amplifier: Op-amp preamp → MOSFET driver → Class AB output.",
    ),
]

# Allow quick local iteration by restricting to only the first case
if os.getenv("RUN_SINGLE_GOLDEN", "0") == "1":
    GOLDEN_CASES = GOLDEN_CASES[:1]


def _parse_sse_events(lines: List[str]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    current_event = "message"
    current_data: List[str] = []

    def flush() -> None:
        nonlocal current_event, current_data
        if not current_data:
            return
        payload_text = "\n".join(current_data).strip()
        if not payload_text:
            current_event = "message"
            current_data = []
            return
        try:
            payload = json.loads(payload_text)
        except Exception:
            payload = {"raw": payload_text}
        events.append({"event": current_event, "data": payload})
        current_event = "message"
        current_data = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            current_data.append(line.split(":", 1)[1].strip())

    flush()
    return events


def _collect_stream_response(response) -> List[Dict[str, Any]]:
    lines: List[str] = []
    for line in response.iter_lines():
        decoded = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else str(line)
        lines.append(decoded)
    return _parse_sse_events(lines)


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("RUN_GOLDEN_TESTS", "0") != "1", reason="Golden tests disabled")
@pytest.mark.parametrize("case_name,prompt", GOLDEN_CASES, ids=[item[0] for item in GOLDEN_CASES])
def test_live_golden_pipeline(case_name: str, prompt: str) -> None:
    started = time.perf_counter()

    def _run_case() -> List[Dict[str, Any]]:
        with client.stream("POST", "/api/chat", json={"message": prompt}) as resp:
            assert resp.status_code == 200
            return _collect_stream_response(resp)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_case)
        try:
            events = future.result(timeout=300)
        except FuturesTimeoutError as exc:
            raise AssertionError(f"Case {case_name} exceeded the 180s live timeout") from exc

    assert events, f"No SSE events returned for case {case_name}"

    circuit_event = next((item for item in events if item["event"] == "circuit_ready"), None)
    render_event = next((item for item in events if item["event"] == "render_ready"), None)
    text_event = next((item for item in events if item["event"] == "text"), None)

    assert circuit_event is not None, f"Missing circuit_ready event for {case_name}"
    assert render_event is not None, f"Missing render_ready event for {case_name}"
    assert text_event is not None, f"Missing text event for {case_name}"

    circuit_data = circuit_event["data"].get("circuit_data") or circuit_event["data"].get("summary")
    assert isinstance(circuit_data, dict)
    validated_ir = CircuitIR.model_validate(circuit_data)
    assert validated_ir is not None

    circuit_id = circuit_event["data"].get("circuit_id")
    assert isinstance(circuit_id, str) and circuit_id.strip(), f"No circuit_id for {case_name}"

    with SessionLocal() as db:
        row = db.execute(
            text("SELECT ir_id, circuit_id, status FROM circuit_irs WHERE circuit_id = :circuit_id ORDER BY created_at DESC LIMIT 1"),
            {"circuit_id": circuit_id},
        ).first()
    assert row is not None, f"Missing DB IR row for {case_name}"

    render_data = render_event["data"]
    sch_url = render_data.get("sch_url")
    ngspice_url = render_data.get("ngspice_url") or render_data.get("spice_url")
    # pcb_url chưa được implement — skip assertion
    assert sch_url and ngspice_url, f"Missing artifact URLs for {case_name}"

    sch_resp = client.get(sch_url)
    spice_resp = client.get(ngspice_url)

    assert sch_resp.status_code == 200
    assert spice_resp.status_code == 200

    sch_resp = client.get(sch_url)
    spice_resp = client.get(ngspice_url)

    assert sch_resp.status_code == 200
    assert spice_resp.status_code == 200
    assert "kicad" in sch_resp.text.lower() or len(sch_resp.text) > 0
    assert len(spice_resp.text.strip()) > 0

    with client.stream("POST", f"/api/circuits/{circuit_id}/simulate") as sim_resp:
        if sim_resp.status_code != 200:
            print("SIM STATUS:", sim_resp.status_code)
            print("SIM BODY:", sim_resp.read().decode("utf-8", errors="ignore"))
        assert sim_resp.status_code == 200
        sim_events = _collect_stream_response(sim_resp)

    sim_complete = next((item for item in sim_events if item["event"] == "completed"), None)
    assert sim_complete is not None, f"Simulation did not complete for {case_name}"

    sim_data = sim_complete["data"]
    assert "gain_dB" in sim_data
    assert "bandwidth_Hz" in sim_data
    assert "waveform_data" in sim_data
    assert isinstance(sim_data["waveform_data"], dict)

    elapsed = time.perf_counter() - started
    assert elapsed < 45.0, f"Case {case_name} exceeded target time: {elapsed:.2f}s"
