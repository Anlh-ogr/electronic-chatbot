# .\thesis\electronic-chatbot\apps\api\app\application\ai\simulation_service.py
"""NGSpice simulation service cho waveform responses.

Module này chịu trách nhiệm:
 1. Tạo SPICE netlist từ circuit_data
 2. Chạy ngspice transient simulation
 3. Parse output → WaveformTrace objects
 4. Trả về waveform cho frontend chart rendering

Nguyên tắc:
 - Adapter pattern: gọi ngspice binary thông qua subprocess
 - Deterministic: stdout/stderr capture, fixed timeout
 - Error handling: lỗi ngspice → SimulationError với detail message
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import math
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from app.application.ai.circuit_ir_schema import CircuitIR
from app.application.ai.transient_window import (
    apply_transient_window_defaults,
    parse_time_seconds,
)

logger = logging.getLogger(__name__)
def log_stage(stage_name: str, **kwargs):
    logger.info(f"[Stage {stage_name} | {kwargs}]")

class SimulationError(RuntimeError):
    """Raised when a simulation run cannot be completed."""

    def __init__(
        self,
        message: str,
        *,
        ngspice_stderr: str = "",
        ngspice_stdout: str = "",
        ngspice_log_tail: str = "",
        exit_code: Optional[int] = None,
        executable: str = "",
        attempt: str = "",
        failure_phase: str = "",
    ) -> None:
        super().__init__(message)
        self.ngspice_stderr = ngspice_stderr or ""
        self.ngspice_stdout = ngspice_stdout or ""
        self.ngspice_log_tail = ngspice_log_tail or ""
        self.exit_code = exit_code
        self.executable = executable or ""
        self.attempt = attempt or ""
        self.failure_phase = (failure_phase or "").strip() or self._infer_failure_phase(message)

    @staticmethod
    def _infer_failure_phase(message: str) -> str:
        m = str(message or "").lower()
        if "netlist is empty" in m or "does not contain" in m or "no valid spice" in m:
            return "precheck_netlist"
        if "executable not found" in m:
            return "subprocess_missing_binary"
        if "timed out" in m:
            return "subprocess_timeout"
        if "ngspice failed" in m or "exit " in m:
            return "subprocess_nonzero_exit"
        if "waveform file" in m or "samples were parsed" in m or "wrdata" in m:
            return "postprocess_waveform"
        return "simulation_error"

    @staticmethod
    def _clip(text: str, max_chars: int = 12000) -> str:
        if not text:
            return ""
        return text if len(text) <= max_chars else text[-max_chars:]

    def detail_payload(self) -> Dict[str, Any]:
        """Structured fields for HTTP / SSE responses (JSON-serializable).

        Always includes ngspice_* keys so clients never rely on presence/absence
        to detect simulation-stage failures (empty string means nothing captured).
        """
        stderr_c = self._clip(self.ngspice_stderr)
        stdout_c = self._clip(self.ngspice_stdout)
        log_c = self._clip(self.ngspice_log_tail)
        ran_cli = self.failure_phase in {
            "subprocess_nonzero_exit",
            "postprocess_waveform",
            "subprocess_timeout",
        }
        no_capture = not (stderr_c.strip() or stdout_c.strip() or log_c.strip())

        out: Dict[str, Any] = {
            "error": "simulation_failed",
            "message": str(self),
            "type": self.__class__.__name__,
            "failure_phase": self.failure_phase,
            "ngspice_stderr": stderr_c,
            "ngspice_stdout": stdout_c,
            "ngspice_log_tail": log_c,
            "ngspice_executable": self.executable or "",
            "spice_attempt": self.attempt or "",
            "ngspice_exit_code": self.exit_code,
        }

        if ran_cli and no_capture and self.failure_phase == "subprocess_nonzero_exit":
            out["diagnostic_note"] = (
                "Ngspice reported failure but stderr, stdout, and stdout.log were all empty. "
                "Try NGSPICE_EXECUTABLE pointing to the same binary you use in a terminal, "
                "or run the saved .cir from the API logs locally with ngspice -b."
            )
        elif ran_cli and no_capture and self.failure_phase == "postprocess_waveform":
            out["diagnostic_note"] = (
                "Ngspice exited 0 but waveform output was missing or could not be parsed; "
                "stdout.log tail is empty — check probe names vs netlist nodes and wrdata format."
            )
        elif self.failure_phase == "subprocess_timeout":
            out["diagnostic_note"] = (
                "Ngspice subprocess exceeded NGSPICE_TIMEOUT_SECONDS. "
                "Raise NGSPICE_TIMEOUT_SECONDS or shorten the transient window (stop/step)."
            )
        elif self.failure_phase == "precheck_netlist":
            out["diagnostic_note"] = (
                "Failed before starting ngspice (missing/empty netlist or compile error). "
                "Fix synthesis/export first; ngspice_stderr/log are not applicable."
            )
        elif self.failure_phase == "subprocess_missing_binary":
            out["diagnostic_note"] = (
                "Install ngspice or set NGSPICE_EXECUTABLE to the full path of ngspice.exe "
                "(Windows services often have no PATH)."
            )

        return out


def simulation_error_http_detail(exc: BaseException) -> Dict[str, Any]:
    """Normalize simulation failures for FastAPI `HTTPException(detail=...)`."""
    if isinstance(exc, SimulationError):
        return exc.detail_payload()
    return {
        "error": "simulation_failed",
        "type": exc.__class__.__name__,
        "message": str(exc),
        "failure_phase": "outside_ngspice_simulator",
        "ngspice_stderr": "",
        "ngspice_stdout": "",
        "ngspice_log_tail": "",
        "ngspice_executable": "",
        "spice_attempt": "",
        "ngspice_exit_code": None,
        "diagnostic_note": (
            "This exception was not raised as SimulationError (e.g. request validation, "
            "JSON/schema error, IR compile, or unrelated server bug). "
            "Expand `message` and server logs; ngspice fields are intentionally empty."
        ),
    }


@dataclass
class WaveformTrace:
    """Single waveform trace."""

    name: str
    x: List[float]
    y: List[float]
    unit: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "unit": self.unit,
        }


@dataclass
class SimulationResult:
    """Output payload returned to API layer."""

    success: bool
    analysis: Dict[str, Any]
    traces: List[WaveformTrace]
    points: int
    execution_time_ms: float
    ngspice_stdout: str = ""
    ngspice_stderr: str = ""

    def to_dict(self) -> Dict[str, Any]:
        x_label = "time_s"
        x_unit = str(self.analysis.get("x_unit", "s") or "s")
        if x_unit and x_unit != "s":
            x_label = f"time_{x_unit}"

        return {
            "success": self.success,
            "analysis": self.analysis,
            "waveform": {
                "x_label": x_label,
                "traces": [t.to_dict() for t in self.traces],
            },
            "points": self.points,
            "execution_time_ms": round(self.execution_time_ms, 2),
        }


class NgSpiceSimulationService:
    """Run transient simulations through ngspice and return waveform arrays."""

    def __init__(self, executable: Optional[str] = None, timeout_seconds: int = 60) -> None:
        self._executable = self._resolve_ngspice_executable(executable)
        env_timeout = os.getenv("NGSPICE_TIMEOUT_SECONDS")
        self._timeout_seconds = int(env_timeout) if env_timeout else timeout_seconds
        if self._timeout_seconds < 10:
            self._timeout_seconds = 10
        env_max_points = os.getenv("NGSPICE_MAX_POINTS")
        self._max_points = int(env_max_points) if env_max_points else 262144
        if self._max_points < 500:
            self._max_points = 500
        env_max_output_points = os.getenv("NGSPICE_RETURN_MAX_POINTS")
        self._max_output_points = int(env_max_output_points) if env_max_output_points else self._max_points
        if self._max_output_points < 300:
            self._max_output_points = 300

    @staticmethod
    def _resolve_ngspice_executable(explicit: Optional[str]) -> str:
        """Pick ngspice binary: arg → env → PATH → common Windows install dirs."""
        if explicit and str(explicit).strip():
            return str(explicit).strip()
        env = (os.getenv("NGSPICE_EXECUTABLE") or "").strip()
        if env:
            return env
        found = shutil.which("ngspice")
        if found:
            return found
        if os.name == "nt":
            for candidate in (
                r"C:\Program Files\Spice64\bin\ngspice.exe",
                r"C:\Program Files (x86)\Spice64\bin\ngspice.exe",
            ):
                if os.path.isfile(candidate):
                    return candidate
        return "ngspice"

    def simulate_from_circuit_data(self, circuit_data: Dict[str, Any]) -> SimulationResult:
        """Run simulation directly from circuit_data schema.

        Supported schema keys:
        - analysis_type: "transient"
        - tran_step / tran_stop / tran_start (or step_time/stop_time/start_time)
        - nodes_to_monitor: list[str]
        - source_params: {offset, amplitude, frequency, input_node}
        - spice_netlist / netlist / ngspice_netlist
        """
        if not isinstance(circuit_data, dict):
            raise SimulationError("circuit_data must be a dictionary")

        analysis_type = str(circuit_data.get("analysis_type", "transient")).strip().lower()
        if analysis_type not in {"transient", "tran"}:
            raise SimulationError("Only transient analysis is currently supported")

        netlist = self._extract_netlist(circuit_data)
        if not netlist:
            raise SimulationError("circuit_data does not contain spice_netlist/netlist/ngspice_netlist")

        probes = self._extract_nodes_to_monitor(circuit_data)
        if not probes:
            probes = self._infer_default_probes(circuit_data)

        # Always normalize to the 5 s window + frequency-aware step (Points = TimeRange × f × N).
        apply_transient_window_defaults(
            circuit_data,
            max_points=self._max_points,
            overwrite=True,
        )

        step, stop, start = self._extract_transient_window(circuit_data)
        reltol = self._extract_reltol(circuit_data)
        source_params = circuit_data.get("source_params")
        expected_gain = self._extract_expected_gain(circuit_data)

        netlist = self._inject_model_includes(netlist, circuit_data)
        netlist = self._apply_source_params(netlist, circuit_data, source_params)

        return self.simulate_transient(
            netlist=netlist,
            probes=probes,
            step=step,
            stop=stop,
            start=start,
            reltol=reltol,
            expected_gain=expected_gain,
            probe_io_hint=self._extract_signal_flow_probe_hint(circuit_data),
        )

    def _extract_signal_flow_probe_hint(self, circuit_data: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        sf = circuit_data.get("signal_flow")
        if not isinstance(sf, dict):
            return None
        ri = sf.get("input_node") or sf.get("input_net")
        ro = sf.get("output_node") or sf.get("output_net")
        if not ri or not ro:
            return None
        return (
            f"v({self._canonical_probe_node(ri)})",
            f"v({self._canonical_probe_node(ro)})",
        )

    def simulate_transient(
        self,
        netlist: str,
        probes: Optional[List[str]] = None,
        step: str = "10us",
        stop: str = "20ms",
        start: str = "0",
        reltol: str = "1e-3",
        expected_gain: Optional[float] = None,
        probe_io_hint: Optional[Tuple[str, str]] = None,
    ) -> SimulationResult:
        if not netlist or not netlist.strip():
            raise SimulationError("Netlist is empty")

        cleaned_netlist = self._normalize_netlist(netlist)
        selected_probes = self._normalize_probes(probes)
        # Remap probes that don't exactly match a netlist node to the closest
        # actual node (e.g. probe `v(OUT)` against compiled deck whose output
        # net is `out_sig` / `u1_out`). Without this, ngspice prints
        # "Error: no such vector OUT" and the waveform file is never written.
        selected_probes = self._remap_probes_to_netlist(cleaned_netlist, selected_probes)
        # Keep the I/O hint in sync with the remapped probes so gain estimation
        # can still locate the correct input/output trace by name.
        probe_io_hint = self._remap_probe_io_hint(cleaned_netlist, probe_io_hint)
        step, stop, start = self._normalize_analysis_window(step, stop, start)

        started = time.perf_counter()
        attempts = [
            (step, stop, start, False, reltol),
            (step, stop, start, True, reltol),
            (os.getenv("NGSPICE_FALLBACK_STEP", "100us"), os.getenv("NGSPICE_FALLBACK_STOP", "2ms"), "0", False, reltol),
            (os.getenv("NGSPICE_FALLBACK_STEP", "100us"), os.getenv("NGSPICE_FALLBACK_STOP", "2ms"), "0", True, reltol),
            ("200us", "500us", "0", True, reltol),
        ]

        last_error: Optional[SimulationError] = None
        process = None
        traces: List[WaveformTrace] = []
        effective_step, effective_stop = step, stop

        for att_step, att_stop, att_start, att_uic, att_reltol in attempts:
            try:
                process, traces = self._run_once(
                    cleaned_netlist,
                    selected_probes,
                    step=att_step,
                    stop=att_stop,
                    start=att_start,
                    use_uic=att_uic,
                    reltol=att_reltol,
                )
                effective_step, effective_stop = att_step, att_stop

                logger.warning(
                    "SPICE ATTEMPT SUCCESS: step=%s stop=%s uic=%s traces=%d",
                    att_step,
                    att_stop,
                    att_uic,
                    len(traces),
                )
                last_error = None
                break

            except SimulationError as exc:
                exc.attempt = (
                    f"step={att_step} stop={att_stop} start={att_start} "
                    f"uic={att_uic} reltol={att_reltol}"
                )
                last_error = exc
                diag = (
                    (exc.ngspice_stderr or "").strip()
                    or (exc.ngspice_log_tail or "").strip()
                    or (exc.ngspice_stdout or "").strip()
                )
                diag_snip = diag.replace("\r", "")[-600:] if diag else ""
                logger.warning(
                    "SPICE ATTEMPT FAIL: step=%s stop=%s uic=%s error=%s diag_tail=%s",
                    att_step,
                    att_stop,
                    att_uic,
                    str(exc)[:400],
                    diag_snip.replace("\n", "|"),
                )
                continue

        if process is None:
            logger.warning(
                "SPICE ALL ATTEMPTS EXHAUSTED: netlist_head=%s",
                cleaned_netlist.splitlines()[0]
                if cleaned_netlist
                else "<empty>",
            )
            raise last_error or SimulationError(
                "Simulation failed after all attempts",
                executable=self._executable,
            )

        elapsed = (time.perf_counter() - started) * 1000.0
        raw_points = len(traces[0].x) if traces else 0
        x_unit = self._choose_time_unit(traces[0].x[-1] if traces and traces[0].x else 0.0)
        metrics = self._estimate_gain_metrics(
            traces=traces,
            probes=selected_probes,
            expected_gain=expected_gain,
            probe_io_hint=probe_io_hint,
        )
        traces = self._downsample_traces(traces)
        points = len(traces[0].x) if traces else 0

        # Structured NGSPICE log for CI / runtime observability
        try:
            from app.core.structured_logger import log_stage

            measured_av = metrics.get("measured_av") if isinstance(metrics, dict) else None
            gain_db = None
            if isinstance(measured_av, (int, float)) and measured_av not in (0, 0.0):
                gain_db = 20.0 * math.log10(abs(float(measured_av)))

            dc_bias_v = None
            if traces:
                trace_map_lc = {t.name.lower(): t for t in traces}
                output_trace = None
                if probe_io_hint:
                    _, po = probe_io_hint[0].lower(), probe_io_hint[1].lower()
                    output_trace = trace_map_lc.get(po)
                if output_trace is None:
                    output_trace = self._pick_output_trace(
                        trace_map_lc, selected_probes, probe_io_hint=probe_io_hint
                    )
                if output_trace and output_trace.y:
                    dc_bias_v = sum(output_trace.y) / max(len(output_trace.y), 1)

            log_stage(
                "NGSPICE",
                gain_dB=round(gain_db, 3) if isinstance(gain_db, float) and math.isfinite(gain_db) else None,
                bandwidth_Hz=metrics.get("bandwidth_hz") if isinstance(metrics, dict) else None,
                phase_margin_deg=metrics.get("phase_shift_deg") if isinstance(metrics, dict) else None,
                dc_bias_v=round(dc_bias_v, 6) if isinstance(dc_bias_v, (int, float)) else None,
                sim_time_s=round(elapsed / 1000.0, 3),
            )
        except Exception:
            logger.debug("Structured NGSPICE logging skipped", exc_info=True)

        return SimulationResult(
            success=True,
            analysis={
                "type": "transient",
                "step": effective_step,
                "stop": effective_stop,
                "start": start,
                "probes": selected_probes,
                "reltol": reltol,
                "x_unit": x_unit,
                "raw_points": raw_points,
                "downsampled": points < raw_points,
                "max_output_points": self._max_output_points,
                "gain_metrics": metrics,
            },
            traces=traces,
            points=points,
            execution_time_ms=elapsed,
            ngspice_stdout=process.stdout,
            ngspice_stderr=process.stderr,
        )

    def _run_once(
        self,
        base_netlist: str,
        probes: List[str],
        step: str,
        stop: str,
        start: str,
        use_uic: bool,
        reltol: str,
    ) -> tuple[subprocess.CompletedProcess[str], List[WaveformTrace]]:
        with tempfile.TemporaryDirectory(prefix="chatbot_ngspice_") as tmp:
            workdir = Path(tmp)
            netlist_path = workdir / "simulation.cir"
            data_path = workdir / "waveform.tsv"

            full_netlist = self._build_transient_deck(
                base_netlist=base_netlist,
                probes=probes,
                output_path=data_path,
                step=step,
                stop=stop,
                start=start,
                use_uic=use_uic,
                reltol=reltol,
            )
            netlist_path.write_text(full_netlist, encoding="utf-8")

            process = self._run_ngspice(netlist_path)
            traces = self._parse_waveform_file(data_path, probes)
            return process, traces

    def _extract_netlist(self, circuit_data: Dict[str, Any]) -> Optional[str]:
        for key in ("spice_netlist", "netlist", "ngspice_netlist"):
            val = circuit_data.get(key)
            if isinstance(val, str) and val.strip():
                return val
        return None

    def _extract_nodes_to_monitor(self, circuit_data: Dict[str, Any]) -> Optional[List[str]]:
        nodes = circuit_data.get("nodes_to_monitor")
        if isinstance(nodes, list) and nodes:
            normalized: List[str] = []
            for item in nodes:
                text = str(item).strip()
                if not text:
                    continue
                lower = text.lower()
                if lower in {"0", "gnd", "ground", "vss", "v(0)", "v(gnd)", "v(ground)", "v(vss)"}:
                    continue
                if lower.startswith("v(") or lower.startswith("i("):
                    inner = text[2:-1] if text.endswith(")") else text[2:]
                    normalized.append(f"v({self._canonical_probe_node(inner)})")
                else:
                    normalized.append(f"v({self._canonical_probe_node(text)})")
            return list(dict.fromkeys(normalized))
        return None

    def _infer_default_probes(self, circuit_data: Dict[str, Any]) -> List[str]:
        """Infer a stable input/output probe pair from circuit metadata.

        The compiler emits node names from the IR net names, so the fallback
        should prefer those same names instead of generic v(in)/v(out).
        """
        candidates: List[str] = []

        def _add_node(raw: Any) -> None:
            text = str(raw or "").strip()
            if not text:
                return
            lower = text.lower()
            if lower in {"0", "gnd", "ground", "vss", "v(0)", "v(gnd)", "v(ground)", "v(vss)"}:
                return
            node = text[2:-1] if lower.startswith("v(") and text.endswith(")") else text
            node = self._canonical_probe_node(node)
            probe = f"v({node})"
            if probe not in candidates:
                candidates.append(probe)

        ports = circuit_data.get("ports")
        if isinstance(ports, list):
            for port in ports:
                if not isinstance(port, dict):
                    continue
                direction = str(port.get("direction") or port.get("type") or "").strip().lower()
                if direction not in {"input", "output"}:
                    continue
                net_name = port.get("net_name") or port.get("net") or port.get("name")
                _add_node(net_name)

        if len(candidates) < 2:
            for key in ("input_node", "input_net", "output_node", "output_net"):
                _add_node(circuit_data.get(key))

        if len(candidates) < 2:
            nets = circuit_data.get("nets")
            if isinstance(nets, list):
                for net in nets:
                    if not isinstance(net, dict):
                        continue
                    name = str(net.get("name") or net.get("net_name") or net.get("id") or "").strip().lower()
                    if any(tag in name for tag in ("vin", "input", "net_in", "in")):
                        _add_node(net.get("name") or net.get("net_name") or net.get("id"))
                    elif any(tag in name for tag in ("vout", "output", "net_out", "out")):
                        _add_node(net.get("name") or net.get("net_name") or net.get("id"))

        if len(candidates) < 2:
            for fallback in ("net_in", "net_out"):
                _add_node(fallback)

        if len(candidates) < 2:
            for fallback in ("in", "out"):
                _add_node(fallback)

        return candidates[:2] if candidates else ["v(net_in)", "v(net_out)"]

    @staticmethod
    def _canonical_probe_node(name: Any) -> str:
        text = str(name or "").strip()
        if not text:
            return "0"
        if text.lower() in {"0", "gnd", "ground", "vss"}:
            return "0"
        return re.sub(r"[^A-Za-z0-9_:+-]", "_", text).upper()

    def _extract_transient_window(self, circuit_data: Dict[str, Any]) -> Tuple[str, str, str]:
        def _coerce(v: Any, default_text: str) -> str:
            if v is None:
                return default_text
            if isinstance(v, (int, float)):
                return self._format_time_value(float(v))
            text = str(v).strip()
            return text or default_text

        step = _coerce(
            circuit_data.get("tran_step", circuit_data.get("step_time", circuit_data.get("step", "10us"))),
            "10us",
        )
        stop = _coerce(
            circuit_data.get("tran_stop", circuit_data.get("stop_time", circuit_data.get("stop", "20ms"))),
            "20ms",
        )
        start = _coerce(
            circuit_data.get("tran_start", circuit_data.get("start_time", circuit_data.get("start", "0"))),
            "0",
        )
        return step, stop, start

    def _inject_model_includes(self, netlist: str, circuit_data: Dict[str, Any]) -> str:
        include_paths: List[str] = []

        top_level_includes = circuit_data.get("model_libraries")
        if isinstance(top_level_includes, list):
            for item in top_level_includes:
                path_text = str(item).strip()
                if path_text:
                    include_paths.append(path_text)

        for comp in circuit_data.get("components", []):
            if not isinstance(comp, dict):
                continue
            params = comp.get("parameters", {})
            if not isinstance(params, dict):
                continue
            path_val = params.get("model_library")
            if isinstance(path_val, dict):
                path_val = path_val.get("value")
            path_text = str(path_val).strip() if path_val is not None else ""
            if path_text:
                include_paths.append(path_text)

        include_paths = list(dict.fromkeys(include_paths))
        if not include_paths:
            return netlist

        lines = [line.rstrip() for line in netlist.splitlines()]
        lower_lines = [line.lower().strip() for line in lines]
        existing = {line for line in lower_lines if line.startswith(".include")}
        new_include_lines: List[str] = []
        for path_text in include_paths:
            include_line = f'.include "{path_text}"'
            if include_line.lower() not in existing:
                new_include_lines.append(include_line)

        if not new_include_lines:
            return netlist

        insert_idx = 1 if lines else 0
        merged = lines[:insert_idx] + new_include_lines + lines[insert_idx:]
        return "\n".join(merged).strip() + "\n"

    def _apply_source_params(
        self,
        netlist: str,
        circuit_data: Dict[str, Any],
        source_params: Any,
    ) -> str:
        if not isinstance(source_params, dict):
            return netlist

        if re.search(r"\bSIN\s*\(", netlist, flags=re.IGNORECASE):
            return netlist

        offset = self._safe_float(source_params.get("offset"), 0.0)
        amplitude = self._safe_float(source_params.get("amplitude"), 0.1)
        frequency = self._safe_float(source_params.get("frequency"), 1000.0)
        input_node = self._resolve_input_node(circuit_data, source_params)
        stim_name = str(source_params.get("name", "VSTIM")).strip() or "VSTIM"

        stim_line = f"{stim_name} {input_node} 0 SIN({offset:g} {amplitude:g} {frequency:g})"
        lines = [line.rstrip() for line in netlist.splitlines() if line.strip()]

        end_idx = len(lines)
        for idx, line in enumerate(lines):
            if line.strip().lower() == ".end":
                end_idx = idx
                break

        lines = lines[:end_idx] + [stim_line] + lines[end_idx:]
        return "\n".join(lines).strip() + "\n"

    def _resolve_input_node(self, circuit_data: Dict[str, Any], source_params: Dict[str, Any]) -> str:
        explicit = str(source_params.get("input_node", "")).strip().lower()
        if explicit:
            return "0" if explicit in {"gnd", "ground", "0"} else explicit

        ports = circuit_data.get("ports", [])
        if isinstance(ports, list):
            for port in ports:
                if not isinstance(port, dict):
                    continue
                direction = str(port.get("direction") or port.get("type") or "").lower()
                if direction != "input":
                    continue
                net = str(port.get("net") or port.get("net_name") or "").strip().lower()
                if net:
                    return "0" if net in {"gnd", "ground", "0"} else net

        return "in"

    def _downsample_traces(self, traces: List[WaveformTrace]) -> List[WaveformTrace]:
        """Reduce points for chart transport while preserving peaks via min-max buckets."""
        if not traces:
            return traces
        points = len(traces[0].x)
        if points <= self._max_output_points:
            return traces

        ref_x = traces[0].x
        x0 = float(ref_x[0])
        x1 = float(ref_x[-1])
        span = max(x1 - x0, 1e-15)
        bucket_count = max(2, self._max_output_points // 2)
        bucket_w = span / float(bucket_count)

        bucket_indices: List[List[int]] = [[] for _ in range(bucket_count)]
        for idx, x_val in enumerate(ref_x):
            rel = float(x_val) - x0
            b = int(rel / bucket_w) if bucket_w > 0 else 0
            if b >= bucket_count:
                b = bucket_count - 1
            bucket_indices[b].append(idx)

        ordered_indices: List[int] = []
        seen: set[int] = set()
        for bucket in bucket_indices:
            if not bucket:
                continue
            ymin_i = bucket[0]
            ymax_i = bucket[0]
            ymin_v = traces[0].y[ymin_i]
            ymax_v = traces[0].y[ymax_i]
            for i in bucket:
                yv = traces[0].y[i]
                if yv < ymin_v:
                    ymin_v = yv
                    ymin_i = i
                if yv > ymax_v:
                    ymax_v = yv
                    ymax_i = i
            for i in sorted({ymin_i, ymax_i}):
                if i not in seen:
                    seen.add(i)
                    ordered_indices.append(i)

        if ordered_indices[-1] != points - 1:
            ordered_indices.append(points - 1)

        new_traces: List[WaveformTrace] = []
        for trace in traces:
            new_x = [trace.x[i] for i in ordered_indices]
            new_y = [trace.y[i] for i in ordered_indices]
            new_traces.append(WaveformTrace(name=trace.name, x=new_x, y=new_y, unit=trace.unit))
        return new_traces

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, dict):
            raw = value.get("value")
            if isinstance(raw, (int, float)):
                return float(raw)
            value = raw
        if value is None:
            return default
        text = str(value).strip().lower()
        m = re.match(r"^([+-]?\d*\.?\d+(?:e[+-]?\d+)?)", text)
        if not m:
            return default
        try:
            return float(m.group(1))
        except ValueError:
            return default

    @staticmethod
    def _choose_time_unit(stop_seconds: float) -> str:
        if stop_seconds <= 0:
            return "s"
        if stop_seconds < 1e-6:
            return "ns"
        if stop_seconds < 1e-3:
            return "us"
        if stop_seconds < 1.0:
            return "ms"
        return "s"

    def _run_ngspice(self, netlist_path: Path) -> subprocess.CompletedProcess[str]:
        command = [self._executable, "-b", "-o", "stdout.log", str(netlist_path)]
        try:
            completed = subprocess.run(
                command,
                cwd=str(netlist_path.parent),
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise SimulationError(
                "NGSpice executable not found. Set NGSPICE_EXECUTABLE or add ngspice to PATH.",
                executable=self._executable,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise SimulationError(
                f"Simulation timed out after {self._timeout_seconds}s",
                executable=self._executable,
                attempt=f"timeout_seconds={self._timeout_seconds}",
            ) from exc

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            log_tail = ""
            log_path = netlist_path.parent / "stdout.log"
            if log_path.exists():
                try:
                    log_tail = log_path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    log_tail = ""
            preview = "\n".join(
                part for part in (stderr, stdout, log_tail[-4000:] if log_tail else "") if part
            ).strip()
            raise SimulationError(
                f"NGSpice failed (exit {completed.returncode}): {preview or 'unknown error'}",
                ngspice_stderr=stderr,
                ngspice_stdout=stdout,
                ngspice_log_tail=log_tail,
                exit_code=completed.returncode,
                executable=self._executable,
            )

        return completed

    def _build_transient_deck(
        self,
        base_netlist: str,
        probes: List[str],
        output_path: Path,
        step: str,
        stop: str,
        start: str,
        use_uic: bool,
        reltol: str,
    ) -> str:
        lines = [line.rstrip() for line in base_netlist.splitlines() if line.strip()]
        if lines and lines[-1].lower() == ".end":
            lines = lines[:-1]

        wr_vectors = " ".join(probes)
        # Use relative output file name because ngspice on Windows can fail
        # silently with certain absolute-path forms in wrdata.
        wr_file = output_path.name
        control_block = [
            ".control",
            "set wr_singlescale",
            "set noaskquit",
            "option method=gear",
            "option maxord=2",
            "option gmin=1e-12",
            "option rshunt=1e12",
            f"option reltol={reltol}",
            "op",  # Compute operating point first to aid convergence
            f"tran {step} {stop} {start}" + (" uic" if use_uic else ""),
            f"wrdata {wr_file} {wr_vectors}",
            "quit",
            ".endc",
            ".end",
        ]
        return "\n".join(lines + control_block) + "\n"

    def _extract_reltol(self, circuit_data: Dict[str, Any]) -> str:
        candidates = [
            circuit_data.get("reltol"),
            (circuit_data.get("simulation_options") or {}).get("reltol") if isinstance(circuit_data.get("simulation_options"), dict) else None,
        ]
        for raw in candidates:
            if raw is None:
                continue
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            if val > 0:
                return f"{val:.9g}"
        return "1e-3"

    def _extract_expected_gain(self, circuit_data: Dict[str, Any]) -> Optional[float]:
        """Extract expected Av from payload for waveform consistency checks."""
        candidates: List[Any] = [
            circuit_data.get("gain_actual"),
            circuit_data.get("gain_target"),
            circuit_data.get("av"),
        ]

        equations = circuit_data.get("equations")
        if isinstance(equations, dict):
            gain_block = equations.get("gain")
            if isinstance(gain_block, dict):
                candidates.extend(
                    [
                        gain_block.get("computed_gain"),
                        gain_block.get("target_gain"),
                    ]
                )

        for raw in candidates:
            val = self._safe_float(raw, default=float("nan"))
            if math.isfinite(val):
                return val
        return None

    def _normalize_analysis_window(self, step: str, stop: str, start: str) -> tuple[str, str, str]:
        try:
            step_s = self._parse_time_value(step)
            stop_s = self._parse_time_value(stop)
            start_s = self._parse_time_value(start)
        except ValueError:
            return step, stop, start

        if step_s <= 0:
            step_s = 1e-6
        if stop_s <= start_s:
            stop_s = start_s + 1e-3

        points = (stop_s - start_s) / step_s
        if points > self._max_points:
            step_s = (stop_s - start_s) / float(self._max_points)

        return self._format_time_value(step_s), self._format_time_value(stop_s), self._format_time_value(start_s)

    @staticmethod
    def _parse_time_value(value: str) -> float:
        text = str(value).strip().lower()
        m = re.match(r"^([+-]?\d*\.?\d+(?:e[+-]?\d+)?)\s*([a-z]*)$", text)
        if not m:
            raise ValueError(f"Invalid time value: {value}")

        number = float(m.group(1))
        unit = m.group(2)
        scale = {
            "": 1.0,
            "s": 1.0,
            "ms": 1e-3,
            "us": 1e-6,
            "ns": 1e-9,
            "ps": 1e-12,
            "fs": 1e-15,
        }.get(unit)
        if scale is None:
            raise ValueError(f"Unsupported time unit: {unit}")
        return number * scale

    @staticmethod
    def _format_time_value(seconds: float) -> str:
        if not math.isfinite(seconds):
            return "0"
        return f"{seconds:.9g}"

    def _parse_waveform_file(self, data_path: Path, probes: List[str]) -> List[WaveformTrace]:
        workdir = data_path.parent

        def _read_stdout_log(max_chars: int = 8000) -> str:
            debug_log = workdir / "stdout.log"
            if not debug_log.exists():
                return ""
            try:
                return debug_log.read_text(encoding="utf-8", errors="ignore")[-max_chars:]
            except Exception:
                return ""

        if not data_path.exists():
            debug_text = _read_stdout_log()
            raise SimulationError(
                "Simulation finished but waveform file was not created.",
                ngspice_log_tail=debug_text,
                executable=self._executable,
                attempt="missing_wrdata_output",
            )

        x_values: List[float] = []
        y_values: List[List[float]] = [[] for _ in probes]
        with data_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                parts = re.split(r"\s+", line)
                if not parts or not self._is_float(parts[0]):
                    continue

                numeric_vals: List[float] = []
                for p in parts:
                    if self._is_float(p):
                        numeric_vals.append(float(p))
                row = self._extract_waveform_row(numeric_vals, len(probes))
                if row is None:
                    continue

                x_val, y_row = row
                if len(y_row) != len(probes):
                    continue

                x_values.append(x_val)
                for idx in range(len(probes)):
                    y_values[idx].append(y_row[idx])

        if not x_values:
            log_tail = _read_stdout_log()
            raise SimulationError(
                "No numeric waveform samples were parsed (empty tran, wrdata format mismatch, or probe mismatch).",
                ngspice_log_tail=log_tail,
                executable=self._executable,
                attempt=f"probes={probes}",
            )

        traces: List[WaveformTrace] = []
        for idx, probe in enumerate(probes):
            traces.append(
                WaveformTrace(
                    name=probe,
                    x=x_values,
                    y=y_values[idx],
                    unit=self._infer_unit(probe),
                )
            )

        return traces

    @staticmethod
    def _extract_waveform_row(values: List[float], probe_count: int) -> Optional[Tuple[float, List[float]]]:
        """Parse one ngspice wrdata row supporting both single-scale and pair formats.

        Supported row layouts:
        - single-scale: [x, y1, y2, ...]
        - pair format:  [x1, y1, x2, y2, ...] (x1 ~= x2 ~= ...)
        """
        if probe_count <= 0 or len(values) < 2:
            return None

        # Try pair format first when enough columns are present.
        if len(values) >= (2 * probe_count):
            xs = [values[2 * i] for i in range(probe_count)]
            ys = [values[2 * i + 1] for i in range(probe_count)]
            if xs:
                spread = max(xs) - min(xs)
                if abs(spread) <= max(1e-18, abs(xs[0]) * 1e-9):
                    return (sum(xs) / len(xs), ys)

        # Fallback to single-scale format.
        if len(values) >= (1 + probe_count):
            x_val = values[0]
            ys = values[1: 1 + probe_count]
            return (x_val, ys)

        return None

    @staticmethod
    def _normalize_netlist(netlist: str) -> str:
        text = netlist.strip()
        
        # Strip .control/.endc
        if ".control" in text.lower():
            text = re.sub(
                r'\.control\b.*?\.endc\b',
                '',
                text,
                flags=re.DOTALL | re.IGNORECASE
            ).strip()
        
        # Strip standalone .tran
        text = re.sub(r'(?im)^\.tran\b.*$', '', text)

        # Strip RGND (short circuit 0-0, vô nghĩa)
        text = re.sub(r'(?im)^RGND\s+0\s+0\s+\S.*$', '', text)
        
        # Strip RVCC (sẽ được inject lại bằng VVCC ở testbench)
        text = re.sub(r'(?im)^RVCC\s+\S+\s+\S+\s+\S.*$', '', text)
        
        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            raise SimulationError("Netlist is empty")

        first = lines[0].strip()
        first_token = first.split()[0] if first.split() else ""
        
        starts_like_element = bool(re.match(r"^[A-Za-z]\w*$", first_token)) and len(first.split()) >= 3
        starts_with_directive = first.startswith(".")

        # Must be a SPICE comment line; a bare word line starting with "C" is parsed as a capacitor.
        if starts_like_element or starts_with_directive:
            lines.insert(0, "* ngspice transient deck (wrapper)")

        return "\n".join(lines)

    @staticmethod
    def _normalize_probes(probes: Optional[List[str]]) -> List[str]:
        if not probes:
            return ["v(in)", "v(out)"]
        normalized: List[str] = []
        for probe in probes:
            value = str(probe).strip()
            lower = value.lower()
            if lower in {"0", "gnd", "ground", "vss", "v(0)", "v(gnd)", "v(ground)", "v(vss)"}:
                continue
            if lower.startswith("v(") or lower.startswith("i("):
                inner = value[2:-1] if value.endswith(")") else value[2:]
                value = f"v({NgSpiceSimulationService._canonical_probe_node(inner)})"
            else:
                value = f"v({NgSpiceSimulationService._canonical_probe_node(value)})"
            if value and value not in normalized:
                normalized.append(value)

        # When only one endpoint is provided, synthesize the counterpart probe.
        if len(normalized) == 1:
            p0 = normalized[0]
            p0_upper = p0.upper()
            if "VIN" in p0_upper and "VOUT" not in p0_upper:
                normalized.append(p0_upper.replace("VIN", "VOUT"))
            elif "VOUT" in p0_upper and "VIN" not in p0_upper:
                normalized.append(p0_upper.replace("VOUT", "VIN"))
            elif "NET_IN" in p0_upper and "NET_OUT" not in p0_upper:
                normalized.append(p0_upper.replace("NET_IN", "NET_OUT"))
            elif "NET_OUT" in p0_upper and "NET_IN" not in p0_upper:
                normalized.append(p0_upper.replace("NET_OUT", "NET_IN"))
            elif "INPUT" in p0_upper and "OUTPUT" not in p0_upper:
                normalized.append(p0_upper.replace("INPUT", "OUTPUT"))
            elif "OUTPUT" in p0_upper and "INPUT" not in p0_upper:
                normalized.append(p0_upper.replace("OUTPUT", "INPUT"))

        if not normalized:
            normalized = ["v(in)", "v(out)"]
        return normalized

    # Tokens that look like SPICE values (suffix-scaled numbers) — never nodes.
    _SPICE_VALUE_RE = re.compile(
        r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
        r"(?:t|g|meg|k|m|u|µ|n|p|f)?$",
        re.IGNORECASE,
    )
    # SPICE source descriptors that must be skipped when collecting nodes.
    _SPICE_SOURCE_KEYWORDS = {
        "dc", "ac", "sin", "pulse", "exp", "pwl", "sffm", "trnoise", "trrandom",
    }

    @classmethod
    def _is_value_token(cls, token: str) -> bool:
        if not token:
            return False
        if "(" in token or ")" in token or "=" in token:
            return True  # function-style values like SIN(...), R={...}
        return bool(cls._SPICE_VALUE_RE.match(token))

    @classmethod
    def _extract_netlist_nodes(cls, netlist: str) -> List[str]:
        """Return the set of node identifiers actually used in the netlist.

        Conservative tokenizer: skip comments/directives/control blocks, then for
        each element line keep the tokens between the ref designator and the
        model/value tail. The result is a de-duplicated, order-preserved list
        of node names as they appear in the deck.
        """
        if not netlist:
            return []

        nodes: List[str] = []
        seen: set[str] = set()
        in_control = False
        in_subckt = False
        for raw in netlist.splitlines():
            line = raw.strip()
            if not line or line.startswith("*"):
                continue
            lower = line.lower()
            if lower.startswith(".control"):
                in_control = True
                continue
            if lower.startswith(".endc"):
                in_control = False
                continue
            if in_control:
                continue
            if lower.startswith(".subckt"):
                in_subckt = True
                continue
            if lower.startswith(".ends"):
                in_subckt = False
                continue
            if in_subckt:
                continue  # subckt body nodes are local, not part of top circuit
            if line.startswith("."):
                continue  # directive (.model/.tran/.include/.options)
            if line.startswith("+"):
                continue  # continuation of previous element

            tokens = line.split()
            if len(tokens) < 3:
                continue
            head = tokens[0]
            prefix = head[0].upper() if head else ""

            # Determine how many of the trailing tokens are nodes (vs model/value).
            element_nodes: List[str]
            if prefix in {"R", "L"}:
                element_nodes = tokens[1:3]
            elif prefix == "C":
                element_nodes = tokens[1:3]
            elif prefix == "D":
                element_nodes = tokens[1:3]
            elif prefix in {"V", "I", "E", "F", "G", "H"}:
                element_nodes = tokens[1:3]
                # Skip source descriptors (DC, AC, SIN(...), PULSE(...), ...).
            elif prefix == "Q":
                element_nodes = tokens[1:4]
            elif prefix == "M":
                element_nodes = tokens[1:5]
            elif prefix == "J":
                element_nodes = tokens[1:4]
            elif prefix == "X":
                # Subcircuit instance: nodes appear before the subckt name,
                # which is the last non-numeric token without "=" assignments.
                trailing_idx = len(tokens)
                for idx in range(len(tokens) - 1, 0, -1):
                    tok = tokens[idx]
                    if "=" in tok:
                        continue
                    if cls._is_value_token(tok):
                        continue
                    trailing_idx = idx
                    break
                element_nodes = tokens[1:trailing_idx]
            else:
                continue

            for node in element_nodes:
                tok = node.strip()
                if not tok:
                    continue
                if tok.lower() in cls._SPICE_SOURCE_KEYWORDS:
                    continue
                if cls._is_value_token(tok):
                    continue
                key = tok.lower()
                if key in seen:
                    continue
                seen.add(key)
                nodes.append(tok)
        return nodes

    @classmethod
    def _resolve_probe_node(cls, requested: str, available: List[str]) -> Optional[str]:
        """Map a requested node name to an actual node in the netlist.

        Resolution priority:
          1. Exact case-insensitive match.
          2. Suffix variants like `_sig` (often the external signal name).
          3. Longest common substring (prefer `out_sig` over `u1_out` for "OUT").
          4. Bare prefix/contains match (the requested name is a substring of
             the actual node identifier).
        """
        if not requested or not available:
            return None
        target = requested.strip().lower()
        if not target:
            return None
        avail_lower = {n.lower(): n for n in available}

        # 1. exact
        if target in avail_lower:
            return avail_lower[target]

        # 2. canonical signal suffix (helps OUT → out_sig, IN → in_sig)
        for suffix in ("_sig", "_net", "_node"):
            candidate = f"{target}{suffix}"
            if candidate in avail_lower:
                return avail_lower[candidate]
            candidate2 = f"{suffix.lstrip('_')}_{target}"
            if candidate2 in avail_lower:
                return avail_lower[candidate2]

        # 3. node containing the requested name as a whole word component.
        # Prefer nodes that are NOT prefixed with a component ref (e.g. `u1_*`,
        # `q1_*`, `r1_*`) so the external signal net wins over an internal pin.
        whole_word_matches: List[str] = []
        substring_matches: List[str] = []
        for node_lower, node_actual in avail_lower.items():
            parts = re.split(r"[^a-z0-9]+", node_lower)
            if target in parts:
                whole_word_matches.append(node_actual)
            elif target in node_lower:
                substring_matches.append(node_actual)

        def _ranked(matches: List[str]) -> Optional[str]:
            if not matches:
                return None
            # Prefer nodes not starting with a typical component ref prefix.
            def _score(name: str) -> tuple:
                low = name.lower()
                comp_ref = bool(re.match(r"^[rcljvmqduxes]\d+[_.]", low))
                # shorter names usually mean the canonical signal net
                return (1 if comp_ref else 0, len(low), low)
            return sorted(matches, key=_score)[0]

        ranked = _ranked(whole_word_matches) or _ranked(substring_matches)
        if ranked:
            return ranked

        # 4. give up
        return None

    @classmethod
    def _remap_probes_to_netlist(cls, netlist: str, probes: List[str]) -> List[str]:
        """Filter and remap probes so each `v(...)` references a real node.

        Probes that cannot be resolved against the netlist are dropped silently
        (logged at WARNING). If everything is dropped, we synthesize a
        best-effort signal pair from the netlist node list so the simulation
        still produces something instead of failing with "no such vector".
        """
        if not probes:
            return probes
        nodes = cls._extract_netlist_nodes(netlist)
        if not nodes:
            return probes

        avail_lower = {n.lower() for n in nodes}
        remapped: List[str] = []
        seen: set[str] = set()
        unresolved: List[str] = []

        for probe in probes:
            text = str(probe).strip()
            if not text:
                continue
            lower = text.lower()
            prefix = ""
            inner = text
            if lower.startswith("v(") and text.endswith(")"):
                prefix, inner = "v", text[2:-1]
            elif lower.startswith("i(") and text.endswith(")"):
                prefix, inner = "i", text[2:-1]
            else:
                prefix, inner = "v", text

            inner = inner.strip()
            if inner.lower() in avail_lower:
                resolved = next(n for n in nodes if n.lower() == inner.lower())
            else:
                resolved = cls._resolve_probe_node(inner, nodes) or ""
                if not resolved:
                    unresolved.append(text)
                    continue

            new_probe = f"{prefix}({resolved})"
            if new_probe.lower() not in seen:
                seen.add(new_probe.lower())
                remapped.append(new_probe)

        if unresolved:
            logger.warning(
                "SPICE PROBE REMAP: dropped probes=%s (no matching node) "
                "available_nodes=%s",
                unresolved,
                nodes[:20],
            )

        if not remapped:
            # Best-effort: find one input-like + one output-like node from the
            # netlist so we always produce SOMETHING for the user.
            input_like = next(
                (n for n in nodes if re.search(r"(^|_)(in|input|vin|net_in|in_sig)(_|$)", n, re.IGNORECASE)),
                None,
            )
            output_like = next(
                (n for n in nodes if re.search(r"(^|_)(out|output|vout|net_out|out_sig)(_|$)", n, re.IGNORECASE)),
                None,
            )
            for candidate in (input_like, output_like):
                if candidate:
                    probe = f"v({candidate})"
                    if probe.lower() not in seen:
                        seen.add(probe.lower())
                        remapped.append(probe)
            if not remapped:
                # Last resort: probe the first two non-ground, non-power nodes.
                power_re = re.compile(r"^(0|gnd|ground|vss|vcc|vdd|vee|v\+|v-)$", re.IGNORECASE)
                signal_nodes = [n for n in nodes if not power_re.match(n)]
                for n in signal_nodes[:2]:
                    probe = f"v({n})"
                    if probe.lower() not in seen:
                        seen.add(probe.lower())
                        remapped.append(probe)
            logger.warning(
                "SPICE PROBE REMAP: all requested probes unresolved, "
                "fallback to %s",
                remapped,
            )
        return remapped

    @classmethod
    def _remap_probe_io_hint(
        cls, netlist: str, hint: Optional[Tuple[str, str]]
    ) -> Optional[Tuple[str, str]]:
        if not hint:
            return None
        nodes = cls._extract_netlist_nodes(netlist)
        if not nodes:
            return hint
        avail_lower = {n.lower() for n in nodes}

        def _resolve(token: str) -> str:
            text = str(token).strip()
            if not text:
                return text
            lower = text.lower()
            prefix = ""
            inner = text
            if lower.startswith("v(") and text.endswith(")"):
                prefix, inner = "v", text[2:-1]
            elif lower.startswith("i(") and text.endswith(")"):
                prefix, inner = "i", text[2:-1]
            else:
                prefix, inner = "v", text
            inner = inner.strip()
            if inner.lower() in avail_lower:
                resolved = next(n for n in nodes if n.lower() == inner.lower())
            else:
                resolved = cls._resolve_probe_node(inner, nodes) or inner
            return f"{prefix}({resolved})"

        return (_resolve(hint[0]), _resolve(hint[1]))

    @staticmethod
    def _is_float(value: str) -> bool:
        try:
            float(value)
            return True
        except ValueError:
            return False

    @staticmethod
    def _infer_unit(probe: str) -> str:
        name = probe.lower()
        if name.startswith("v("):
            return "V"
        if name.startswith("i("):
            return "A"
        return ""

    def _estimate_gain_metrics(
        self,
        traces: List[WaveformTrace],
        probes: List[str],
        expected_gain: Optional[float],
        *,
        probe_io_hint: Optional[Tuple[str, str]] = None,
    ) -> Dict[str, Any]:
        """Estimate gain/phase behavior from simulated waveforms and compare to expected Av."""
        if not traces:
            return {"status": "no_traces"}

        trace_map = {t.name.lower(): t for t in traces}
        input_trace: Optional[WaveformTrace] = None
        output_trace: Optional[WaveformTrace] = None
        if probe_io_hint:
            pi, po = probe_io_hint[0].lower(), probe_io_hint[1].lower()
            input_trace = trace_map.get(pi)
            output_trace = trace_map.get(po)
        if input_trace is None:
            input_trace = self._pick_input_trace(trace_map, probes, probe_io_hint=probe_io_hint)
        if output_trace is None:
            output_trace = self._pick_output_trace(trace_map, probes, probe_io_hint=probe_io_hint)

        if not input_trace or not output_trace:
            return {
                "status": "missing_required_probes",
                "required": ["input", "output"],
                "available": [t.name for t in traces],
            }

        sample_count = min(len(input_trace.x), len(output_trace.x), len(input_trace.y), len(output_trace.y))
        if sample_count < 8:
            return {"status": "insufficient_samples", "sample_count": sample_count}

        settle_idx = max(0, int(sample_count * 0.2))
        x_all = input_trace.x[settle_idx:sample_count]
        y_in_all = input_trace.y[settle_idx:sample_count]
        y_out_all = output_trace.y[settle_idx:sample_count]
        if len(y_in_all) < 8 or len(y_out_all) < 8:
            return {"status": "insufficient_steady_state_samples"}

        x_in, y_in, y_out = self._select_gain_measurement_window(x_all, y_in_all, y_out_all)
        if len(y_in) < 8 or len(y_out) < 8:
            return {"status": "insufficient_steady_state_samples"}

        vin_pp = self._peak_to_peak(y_in)
        vout_pp = self._peak_to_peak(y_out)
        vin_rms_ac, vout_rms_ac = self._rms_ac_pair(y_in, y_out)
        if vin_pp <= 0 and vin_rms_ac <= 1e-12:
            return {"status": "invalid_input_signal", "vin_pp": vin_pp, "vin_rms_ac": vin_rms_ac}

        gain_pp = (vout_pp / vin_pp) if vin_pp > 1e-12 else float("nan")
        gain_rms = (vout_rms_ac / vin_rms_ac) if vin_rms_ac > 1e-12 else float("nan")
        gain_abs = gain_rms if math.isfinite(gain_rms) else gain_pp
        if not math.isfinite(gain_abs):
            return {"status": "invalid_gain_estimate", "vin_pp": vin_pp, "vout_pp": vout_pp}

        corr = self._normalized_correlation(y_in, y_out)
        is_inverting = corr < 0
        measured_gain = -gain_abs if is_inverting else gain_abs
        phase_deg = 180.0 if is_inverting else 0.0

        metrics: Dict[str, Any] = {
            "status": "ok",
            "input_probe": input_trace.name,
            "output_probe": output_trace.name,
            "window_start_s": x_in[0] if x_in else 0.0,
            "measurement_samples": len(y_in),
            "vin_pp": vin_pp,
            "vout_pp": vout_pp,
            "vin_rms_ac": vin_rms_ac,
            "vout_rms_ac": vout_rms_ac,
            "gain_pp": gain_pp if math.isfinite(gain_pp) else None,
            "gain_rms": gain_rms if math.isfinite(gain_rms) else None,
            "measured_av": measured_gain,
            "measured_abs_av": gain_abs,
            "phase_shift_deg": phase_deg,
            "inverting": is_inverting,
            "correlation": corr,
        }

        if expected_gain is not None and math.isfinite(expected_gain):
            expected_abs = abs(expected_gain)
            abs_err = abs(gain_abs - expected_abs)
            rel_err_pct = (abs_err / expected_abs * 100.0) if expected_abs > 1e-12 else (0.0 if abs_err < 1e-12 else float("inf"))
            phase_ok = (expected_gain < 0 and is_inverting) or (expected_gain >= 0 and not is_inverting)
            metrics.update(
                {
                    "expected_av": expected_gain,
                    "expected_abs_av": expected_abs,
                    "abs_error": abs_err,
                    "rel_error_pct": rel_err_pct,
                    "phase_match": phase_ok,
                    "equation_match": bool(phase_ok and rel_err_pct <= 15.0),
                }
            )

        return metrics

    @staticmethod
    def _peak_to_peak(values: List[float]) -> float:
        if not values:
            return 0.0
        return max(values) - min(values)

    @classmethod
    def _select_gain_measurement_window(
        cls,
        x_vals: List[float],
        y_in: List[float],
        y_out: List[float],
        *,
        min_cycles: int = 3,
        max_cycles: int = 8,
    ) -> Tuple[List[float], List[float], List[float]]:
        """Use the last few steady-state cycles so gain is not diluted by settling."""
        n = min(len(x_vals), len(y_in), len(y_out))
        if n < 8:
            return x_vals[:n], y_in[:n], y_out[:n]

        period_s = cls._estimate_period_seconds(x_vals[:n], y_in[:n])
        if period_s is None or period_s <= 0:
            tail = max(8, n // 5)
            return x_vals[n - tail : n], y_in[n - tail : n], y_out[n - tail : n]

        t_end = float(x_vals[n - 1])
        t_start = float(x_vals[0])
        span = max(t_end - t_start, period_s)
        cycles_avail = span / period_s
        use_cycles = int(max(min_cycles, min(max_cycles, math.floor(cycles_avail))))
        window_s = use_cycles * period_s
        cut_t = t_end - window_s

        start_idx = 0
        for i in range(n):
            if float(x_vals[i]) >= cut_t:
                start_idx = i
                break
        return x_vals[start_idx:n], y_in[start_idx:n], y_out[start_idx:n]

    @staticmethod
    def _estimate_period_seconds(x_vals: List[float], y_vals: List[float]) -> Optional[float]:
        n = min(len(x_vals), len(y_vals))
        if n < 16:
            return None

        mean_y = sum(y_vals) / n
        crossings: List[float] = []
        for i in range(1, n):
            a = y_vals[i - 1] - mean_y
            b = y_vals[i] - mean_y
            if a == 0.0:
                continue
            if (a < 0.0 < b) or (a > 0.0 > b):
                t0 = float(x_vals[i - 1])
                t1 = float(x_vals[i])
                if t1 <= t0:
                    continue
                frac = abs(a) / (abs(a) + abs(b))
                crossings.append(t0 + frac * (t1 - t0))

        if len(crossings) < 3:
            return None
        periods = [crossings[i] - crossings[i - 1] for i in range(1, len(crossings))]
        periods = [p for p in periods if p > 0]
        if not periods:
            return None
        periods.sort()
        return periods[len(periods) // 2]

    @staticmethod
    def _rms_ac_pair(y_in: List[float], y_out: List[float]) -> Tuple[float, float]:
        n = min(len(y_in), len(y_out))
        if n == 0:
            return 0.0, 0.0
        mean_in = sum(y_in[:n]) / n
        mean_out = sum(y_out[:n]) / n
        acc_in = 0.0
        acc_out = 0.0
        for i in range(n):
            di = y_in[i] - mean_in
            do = y_out[i] - mean_out
            acc_in += di * di
            acc_out += do * do
        return math.sqrt(acc_in / n), math.sqrt(acc_out / n)

    @staticmethod
    def _normalized_correlation(a: List[float], b: List[float]) -> float:
        n = min(len(a), len(b))
        if n == 0:
            return 0.0

        a_mean = sum(a[:n]) / n
        b_mean = sum(b[:n]) / n
        num = 0.0
        den_a = 0.0
        den_b = 0.0
        for i in range(n):
            da = a[i] - a_mean
            db = b[i] - b_mean
            num += da * db
            den_a += da * da
            den_b += db * db

        if den_a <= 0.0 or den_b <= 0.0:
            return 0.0
        return num / math.sqrt(den_a * den_b)

    def _pick_input_trace(
        self,
        trace_map: Dict[str, WaveformTrace],
        probes: List[str],
        *,
        probe_io_hint: Optional[Tuple[str, str]] = None,
    ) -> Optional[WaveformTrace]:
        if probe_io_hint:
            key = probe_io_hint[0].lower()
            if key in trace_map:
                return trace_map[key]
        preferred = [
            "v(in)",
            "v(vin)",
            "v(net_in)",
            "v(input)",
            "v(in_sig)",
            "v(net_in_sig)",
        ]
        for key in preferred:
            if key in trace_map:
                return trace_map[key]

        for probe in probes:
            p = probe.lower()
            if any(tag in p for tag in ("vin", "input", "net_in", "in_sig")) and p in trace_map:
                return trace_map[p]

        for name, trace in trace_map.items():
            if name.startswith("v(") and any(tag in name for tag in ("vin", "input", "net_in", "in_sig")):
                return trace
        return None

    def _pick_output_trace(
        self,
        trace_map: Dict[str, WaveformTrace],
        probes: List[str],
        *,
        probe_io_hint: Optional[Tuple[str, str]] = None,
    ) -> Optional[WaveformTrace]:
        if probe_io_hint:
            key = probe_io_hint[1].lower()
            if key in trace_map:
                return trace_map[key]
        preferred = [
            "v(out)",
            "v(vout)",
            "v(net_out)",
            "v(output)",
            "v(out_sig)",
            "v(net_out_sig)",
        ]
        for key in preferred:
            if key in trace_map:
                return trace_map[key]

        for probe in probes:
            p = probe.lower()
            if any(tag in p for tag in ("vout", "output", "net_out", "out_sig")) and p in trace_map:
                return trace_map[p]

        for name, trace in trace_map.items():
            if name.startswith("v(") and any(tag in name for tag in ("vout", "output", "net_out", "out_sig")):
                return trace
        return None


class NgspiceCompilerService:
    """Compile CircuitIR to SPICE deck and stream async simulation outputs."""

    _TYPE_ALIASES: Dict[str, str] = {
        "r": "resistor",
        "res": "resistor",
        "resistor": "resistor",
        "c": "capacitor",
        "cap": "capacitor",
        "capacitor": "capacitor",
        "l": "inductor",
        "inductor": "inductor",
        "npn": "npn",
        "pnp": "pnp",
        "q_npn": "npn",
        "q_pnp": "pnp",
        "bjt": "npn",
        "bjt_npn": "npn",
        "bjt_pnp": "pnp",
        "diode": "diode",
        "d": "diode",
        "voltage_source": "voltage_source",
        "vsource": "voltage_source",
        "current_source": "current_source",
        "isource": "current_source",
        "opamp": "opamp",
        "opamp_ic": "opamp",
        "op_amp": "opamp",
        "operational_amplifier": "opamp",
    }

    _MODEL_CARDS: Dict[str, str] = {
        "QNPN": ".model QNPN NPN(BF=180 IS=1e-14 VAF=100)",
        "QPNP": ".model QPNP PNP(BF=120 IS=1e-14 VAF=80)",
        "DDEFAULT": ".model DDEFAULT D(IS=1e-14 N=1.9)",
    }

    # Ngspice subcircuits (not .model). Referenced by X-instance lines from _component_to_spice_line.
    _SUBCKT_BLOCKS: Dict[str, str] = {
        "OPAMP_DEFAULT": (
            ".subckt OPAMP_DEFAULT VP VN VOUT VCC VEE\n"
            "* Ideal differential amplifier (high gain VCVS ref VEE); suited for AC/transient teaching sims.\n"
            "E1 VOUT VEE VP VN 1MEG\n"
            ".ends OPAMP_DEFAULT"
        ),
    }

    _SUPPLY_NET_NORMALIZED: frozenset = frozenset(
        {"VCC", "VDD", "VBB", "VBAT", "VSUPPLY", "VEE", "VSS", "VPOWER", "V+"}
    )

    @staticmethod
    def _is_explicit_signal_input_net(net_name_raw: str) -> bool:
        low = str(net_name_raw or "").strip().lower()
        if low in {"in", "net_in", "vin", "input", "signal_in", "i_in", "netin", "in_sig"}:
            return True
        if low.startswith(("net_in", "input_", "vin_")):
            return True
        return False

    def __init__(self, executable: Optional[str] = None, timeout_seconds: int = 90) -> None:
        self._executable = executable or os.getenv("NGSPICE_EXECUTABLE") or "ngspice"
        env_timeout = os.getenv("NGSPICE_TIMEOUT_SECONDS")
        self._timeout_seconds = int(env_timeout) if env_timeout else timeout_seconds
        if self._timeout_seconds < 10:
            self._timeout_seconds = 10

    def generate_spice_deck(self, ir: CircuitIR) -> str:
        """Generate SPICE deck from CircuitIR with auto testbench injection."""
        pin_net_map = self._build_pin_net_map(ir)
        
        # log warning
        logger.debug("SPICE COMPILER: circuit_id=%s, components=%d, nets=%d, pin_net_map_keys=%s",
            getattr(ir.metadata, "circuit_id", "unknown"),
            len(ir.components),
            len(ir.nets),
            list(pin_net_map.keys())[:10],
        )
        
        lines: List[str] = ["* Auto-generated by NgspiceCompilerService"]
        used_models: List[str] = []

        missing_models: List[str] = []
        skipped_components: List[str] = []

        for comp in ir.components:
            ref_id = comp.ref_id.strip().upper()
            
            pin_map = pin_net_map.get(ref_id, {})
            
            spice_line, model_key = self._component_to_spice_line(comp.ref_id, comp.type, comp.value, pin_map)

            if spice_line is None:
                ctype = self._canonical_type(comp.type)
                if ctype in {"ground", "connector"}:
                    logger.debug(
                        "SPICE skip schematic-only symbol ref=%s type=%s (no branch element)",
                        comp.ref_id,
                        comp.type,
                    )
                    continue
                skipped_components.append(f"{comp.ref_id}({comp.type}) pin_map={pin_map}")
                logger.warning(
                    "SPICE SKIP COMPONENT: ref=%s type=%s value=%s pin_map=%s — không map được sang SPICE line",
                    comp.ref_id,
                    comp.type,
                    comp.value,
                    pin_map,
                )
                continue
            lines.append(spice_line)
            
            if model_key:
                if model_key not in used_models:
                    used_models.append(model_key)
                
                if model_key not in self._MODEL_CARDS and model_key not in self._SUBCKT_BLOCKS:
                    missing_models.append(model_key)

        # model debug
        if missing_models:
            logger.warning(
                "SPICE MISSING MODELS: %s",
                sorted(set(missing_models)),
            )

        seen_subckt: set[str] = set()
        for model_key in used_models:
            sub = self._SUBCKT_BLOCKS.get(model_key)
            if sub:
                if model_key not in seen_subckt:
                    lines.append(sub)
                    seen_subckt.add(model_key)
                continue
            model_line = self._MODEL_CARDS.get(model_key)
            if model_line:
                lines.append(model_line)
        
        # build testbench
        tb_lines = self._build_testbench(ir, pin_net_map)
        
        if not tb_lines:
            logger.warning(
                "SPICE TESTBENCH EMPTY: circuit_id=%s",
                getattr(ir.metadata, "circuit_id", "unknown"),
            )
        lines.extend(tb_lines)

        # summary debug
        if skipped_components:
            logger.warning(
                "SPICE COMPILER: %d/%d components bị skip: %s",
                len(skipped_components),
                len(ir.components),
                skipped_components,
            )
        
        # check if any element lines were generated
        element_lines = [
            line for line in lines
            if line
            and not line.startswith("*")
            and not line.startswith(".")
        ]
        
        if not element_lines:
            logger.warning(
                "SPICE COMPILER EMPTY: circuit_id=%s — không có element line nào được generate. pin_net_map=%s",
                getattr(ir.metadata, "circuit_id", "unknown"),
                pin_net_map,
            )
            raise SimulationError("No valid SPICE elements generated")

        # _build_testbench already ends with a single `.end`; do not append another.
        return "\n".join(lines).strip() + "\n"

    async def run_simulation_stream(self, spice_deck: str) -> AsyncGenerator[str, None]:
        """Run ngspice asynchronously and yield JSON rows for SSE clients."""
        temp_dir = tempfile.mkdtemp(prefix="ngspice_stream_")
        workdir = Path(temp_dir)
        cir_path = workdir / "temp.cir"
        raw_path = workdir / "output.raw"
        tsv_path = workdir / "output.tsv"

        try:
            cir_path.write_text(spice_deck, encoding="utf-8")
            try:
                log_stage("NGSPICE_RUN_START", timeout_seconds=self._timeout_seconds)
            except Exception:
                logger.debug("NGSPICE_RUN_START structured log failed", exc_info=True)
            yield json.dumps({"status": "queued"}, ensure_ascii=False)

            process = await asyncio.create_subprocess_exec(
                self._executable,
                "-b",
                str(cir_path.name),
                "-r",
                str(raw_path.name),
                cwd=str(workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self._timeout_seconds,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                yield json.dumps(
                    {"status": "error", "message": "ngspice execution timed out"},
                    ensure_ascii=False,
                )
                return

            if process.returncode != 0:
                yield json.dumps(
                    {
                        "status": "error",
                        "message": "ngspice failed",
                        "stderr": (stderr or b"").decode(errors="ignore")[-800:],
                        "stdout": (stdout or b"").decode(errors="ignore")[-800:],
                    },
                    ensure_ascii=False,
                )
                try:
                    log_stage("NGSPICE_RUN_END", status="error", returncode=process.returncode)
                except Exception:
                    logger.debug("NGSPICE_RUN_END structured log failed (error)", exc_info=True)
                return

            if not tsv_path.exists():
                yield json.dumps(
                    {
                        "status": "completed",
                        "message": "simulation finished but output.tsv not found",
                    },
                    ensure_ascii=False,
                )
                # explicit termination marker
                yield json.dumps({"status": "done", "message": "[DONE]"}, ensure_ascii=False)
                try:
                    log_stage("NGSPICE_RUN_END", status="no_output")
                except Exception:
                    logger.debug("NGSPICE_RUN_END structured log failed (no_output)", exc_info=True)
                return

            yielded = 0
            with tsv_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    parts = re.split(r"\s+", line)
                    numeric_vals: List[float] = []
                    for part in parts:
                        try:
                            numeric_vals.append(float(part))
                        except ValueError:
                            continue

                    if len(numeric_vals) < 2:
                        continue

                    # wrdata can output pair-wise format [t,vin,t,vout] or [t,vin,vout]
                    if len(numeric_vals) >= 4:
                        time_s = numeric_vals[0]
                        v_in = numeric_vals[1]
                        v_out = numeric_vals[3]
                    else:
                        time_s = numeric_vals[0]
                        v_in = numeric_vals[1]
                        v_out = numeric_vals[2] if len(numeric_vals) >= 3 else numeric_vals[1]

                    yielded += 1
                    yield json.dumps(
                        {
                            "status": "data",
                            "time": time_s,
                            "v_in": v_in,
                            "v_out": v_out,
                        },
                        ensure_ascii=False,
                    )

            yield json.dumps({"status": "completed", "points": yielded}, ensure_ascii=False)
            # explicit done marker to help SSE clients detect end
            yield json.dumps({"status": "done", "message": "[DONE]"}, ensure_ascii=False)
            try:
                log_stage("NGSPICE_RUN_END", status="completed", points=yielded)
            except Exception:
                logger.debug("NGSPICE_RUN_END structured log failed (completed)", exc_info=True)
        except FileNotFoundError:
            yield json.dumps(
                {
                    "status": "error",
                    "message": "ngspice executable not found",
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            yield json.dumps(
                {
                    "status": "error",
                    "message": str(exc),
                },
                ensure_ascii=False,
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _build_pin_net_map(self, ir: CircuitIR) -> Dict[str, Dict[str, str]]:
        """
        Build:
            {
                REF_ID -> {
                    PIN_NAME -> NET_NAME
                }
            }

        Read from ir.nets where each node is:
            "R1:1"
            "Q1:C"
            "U1:OUT"
        """

        pin_net_map: Dict[str, Dict[str, str]] = {}

        for net in ir.nets:
            net_name = self._normalize_net_name(net.net_name)

            logger.debug(
                "SPICE NET DEBUG: net=%s nodes=%s",
                net_name,
                net.nodes,
            )

            for node in net.nodes:

                # malformed node
                if ":" not in node:
                    logger.warning(
                        "SPICE PIN_NET: malformed node '%s' in net '%s' — missing ':'",
                        node,
                        net_name,
                    )
                    continue

                ref, pin = node.split(":", 1)

                ref = ref.strip().upper()
                pin = pin.strip().upper()

                # invalid ref/pin
                if not ref or not pin:
                    logger.warning(
                        "SPICE PIN_NET: invalid node '%s' in net '%s' — empty ref/pin",
                        node,
                        net_name,
                    )
                    continue

                if ref not in pin_net_map:
                    pin_net_map[ref] = {}

                # A physical pin can belong to exactly one SPICE net.  Overwriting
                # here silently corrupts the generated netlist, so fail before
                # producing any deck or invoking ngspice.
                if pin in pin_net_map[ref]:
                    old_net = pin_net_map[ref][pin]
                    message = (
                        f"Netlist conflict: pin {ref}.{pin} claimed by nets "
                        f"{old_net} and {net_name}. Fix the CircuitIR before simulating."
                    )
                    logger.error(
                        "SPICE PIN_NET CONFLICT: ref=%s pin=%s old_net=%s new_net=%s",
                        ref,
                        pin,
                        old_net,
                        net_name,
                    )
                    raise SimulationError(message, failure_phase="precheck_netlist")

                pin_net_map[ref][pin] = net_name

        # components without any nets
        components_without_nets = [
            comp.ref_id
            for comp in ir.components
            if comp.ref_id.strip().upper() not in pin_net_map
        ]

        if components_without_nets:
            logger.warning(
                "SPICE PIN_NET: %d component(s) without nets: %s",
                len(components_without_nets),
                components_without_nets,
            )

        logger.debug(
            "SPICE pin_net_map built: refs=%d keys=%s",
            len(pin_net_map),
            list(pin_net_map.keys())[:20],
        )

        return pin_net_map

    def _component_to_spice_line(
        self,
        ref_id: str,
        component_type: str,
        value: Any,
        pin_map: Dict[str, str],
    ) -> Tuple[Optional[str], Optional[str]]:
        
        ref = ref_id.strip().upper()
        ctype = self._canonical_type(component_type)
        
        if not ref or ctype is None:
            logger.warning(
                "SPICE COMPONENT INVALID: ref=%s component_type=%s",
                ref_id,
                component_type,
            )
            return None, None

        # passives
        if ctype in {"resistor", "capacitor", "inductor"}:
            n1, n2 = self._pick_two_nodes(pin_map)
            if not n1 or not n2:
                logger.warning(
                    "SPICE PASSIVE PIN MISSING: ref=%s ctype=%s n1=%s n2=%s pin_map=%s",
                    ref,
                    ctype,
                    n1,
                    n2,
                    pin_map,
                )
                return None, None
            
            prefix = {"resistor": "R", "capacitor": "C", "inductor": "L"}[ctype]
            comp_name = ref if ref.startswith(prefix) else f"{prefix}{ref}"
            
            return (f"{comp_name} {n1} {n2} {self._normalize_value(value)}",None,)
        
        # bjts
        if ctype in {"npn", "pnp"}:
            collector = self._pick_node(pin_map, ["C", "2"])
            base = self._pick_node(pin_map, ["B", "1"])
            emitter = self._pick_node(pin_map, ["E", "3"])
            
            if not collector or not base or not emitter:
                logger.warning(
                    "SPICE BJT PIN MISSING: ref=%s ctype=%s "
                    "collector=%s base=%s emitter=%s pin_map=%s",
                    ref,
                    ctype,
                    collector,
                    base,
                    emitter,
                    pin_map,
                )
                return None, None
            
            model = "QNPN" if ctype == "npn" else "QPNP"
            comp_name = ref if ref.startswith("Q") else f"Q{ref}"
            
            return (f"{comp_name} {collector} {base} {emitter} {model}", model)

        # diodes
        if ctype == "diode":
            anode = self._pick_node(pin_map, ["A", "1"])
            cathode = self._pick_node(pin_map, ["K", "2"])
            
            if not anode or not cathode:
                logger.warning(
                    "SPICE DIODE PIN MISSING: ref=%s "
                    "anode=%s cathode=%s pin_map=%s",
                    ref,
                    anode,
                    cathode,
                    pin_map,
                )
                return None, None
            
            comp_name = ref if ref.startswith("D") else f"D{ref}"
            
            return (f"{comp_name} {anode} {cathode} DDEFAULT", "DDEFAULT")

        # sources
        if ctype in {"voltage_source", "current_source"}:
            n_plus = self._pick_node(pin_map, ["+", "1", "P"])
            n_minus = self._pick_node(pin_map, ["-", "2", "N"])

            # Single-pin power symbols are modeled as sources referenced to ground.
            if not n_minus or n_minus == n_plus:
                n_minus = "0"
            
            if not n_plus or not n_minus:
                logger.warning(
                    "SPICE SOURCE PIN MISSING: ref=%s "
                    "n_plus=%s n_minus=%s pin_map=%s",
                    ref,
                    ctype,
                    n_plus,
                    n_minus,
                    pin_map,
                )
                return None, None
            
            source_name = ref
            
            if ctype == "voltage_source" and not source_name.startswith("V"):
                source_name = f"V{source_name}"
            
            if ctype == "current_source" and not source_name.startswith("I"):
                source_name = f"I{source_name}"
            
            return (f"{source_name} {n_plus} {n_minus} {self._normalize_source_value(value)}", None)

        if ctype == "opamp":
            vp = self._pick_node(pin_map, ["+", "IN+"])
            vn = self._pick_node(pin_map, ["-", "IN-"])
            vout = self._pick_node(pin_map, ["OUT", "OUTPUT"])
            vcc = self._pick_node(pin_map, ["VS+", "V+"])
            vee = self._pick_node(pin_map, ["VS-", "V-", "VEE"])
            if not vp or not vn or not vout:
                logger.warning(
                    "SPICE OPAMP PIN MISSING: ref=%s vp=%s vn=%s vout=%s pin_map=%s",
                    ref_id,
                    vp,
                    vn,
                    vout,
                    pin_map,
                )
                return None, None
            if not vee:
                vee = "0"
            if not vcc:
                vcc = None
                for node in pin_map.values():
                    u = str(node).upper()
                    if "VCC" in u or "VDD" in u or "RAIL" in u or "SUPPLY" in u:
                        vcc = node
                        break
                if not vcc:
                    vcc = "VCC"
                    logger.warning(
                        "SPICE OPAMP: ref=%s missing VS+; using placeholder rail node %s",
                        ref_id,
                        vcc,
                    )
            xname = ref.upper()
            if not xname.startswith("X"):
                xname = f"X{xname}"
            return (f"{xname} {vp} {vn} {vout} {vcc} {vee} OPAMP_DEFAULT", "OPAMP_DEFAULT")

        if ctype in {"ground", "connector"}:
            logger.debug(
                "SPICE schematic-only ctype=%s ref=%s (nets carry connectivity)",
                ctype,
                ref,
            )
            return None, None

        logger.warning(
            "SPICE COMPONENT UNSUPPORTED: ref=%s component_type=%s pin_map=%s",
            ref,
            ctype,
            pin_map,
        )
        return None, None

    def _build_testbench(self, ir: CircuitIR, pin_net_map: Dict[str, Dict[str, str]]) -> List[str]:
        meta = ir.metadata.model_dump() if hasattr(ir.metadata, "model_dump") else {}
        analog_mode = str(meta.get("domain", "analog")).strip().lower() != "digital"

        input_node = self._select_input_node(ir, pin_net_map)
        output_node = self._select_output_node(ir, pin_net_map)
        tran_step = str(meta.get("tran_step") or "1u")
        tran_stop = str(meta.get("tran_stop") or "5m")

        lines: List[str] = []
        # Extract voltage từ power_rail string
        power_rail_raw = str(meta.get("power_rail") or "VCC").strip()
        voltage_match = re.search(r'([+-]?\d+(?:\.\d+)?)\s*[Vv]\b', power_rail_raw)
        power_voltage = voltage_match.group(1) if voltage_match else "12"
        
        # find net VCC real in IR
        vcc_net = None
        for net in ir.nets:
            name_low = str(net.net_name).strip().lower()
            if name_low in {"vcc", "vdd", "v+", "vbat", "vsupply", "vpower"}:
                vcc_net = self._normalize_net_name(net.net_name)
                break
        
        # Inject rail DC source only if the IR does not already define V(rail)-to-0.
        # Parallel ideal voltage sources on the same nodes make the MNA singular / fail.
        if vcc_net and vcc_net not in {"0", "gnd"}:
            if not self._has_explicit_rail_voltage_to_ground(ir, pin_net_map, vcc_net):
                lines.append(f"VVCC_TB {vcc_net} 0 DC {power_voltage}")
            
        # Signal input stimulus — amplitude/frequency from IR metadata when available.
        _supply_nets = {"VCC","VDD","VBB","VBAT","VSUPPLY","V+","VCC1","VCC2","VPOWER"}
        stim_hz = meta.get("input_frequency_hz") or meta.get("frequency_hz")
        if stim_hz is None:
            calc = getattr(ir.analysis, "calculated_values", None)
            if calc is not None:
                stim_hz = getattr(calc, "bandwidth_Hz", None)
        try:
            freq_val = float(stim_hz) if stim_hz is not None else 1000.0
        except (TypeError, ValueError):
            freq_val = 1000.0
        if freq_val >= 100_000:
            tran_step = meta.get("tran_step") or "0.1u"
            tran_stop = meta.get("tran_stop") or "0.2m"
        stim_amp = str(meta.get("input_amplitude_v") or "50m")
        if analog_mode and input_node.upper() not in _supply_nets:
            lines.append(f"VTB {input_node} 0 SINE(0 {stim_amp} {freq_val:g})")

        lines.append(".control")
        lines.append("set wr_singlescale")
        lines.append("set noaskquit")
        lines.append("option method=gear")
        lines.append("option maxord=2")
        lines.append("option gmin=1e-12")
        lines.append("option rshunt=1e12")
        lines.append("op")
        lines.append(f"tran {tran_step} {tran_stop}")
        lines.append(f"wrdata output.tsv v({input_node}) v({output_node})")
        lines.append("quit")
        lines.append(".endc")
        lines.append(".end")
        return lines

    def _has_explicit_rail_voltage_to_ground(
        self,
        ir: CircuitIR,
        pin_net_map: Dict[str, Dict[str, str]],
        rail_net: str,
    ) -> bool:
        """True if a voltage_source component already ties rail_net between rail and node 0."""
        rail = self._normalize_net_name(rail_net)
        if not rail or rail == "0":
            return False
        for comp in ir.components:
            if self._canonical_type(comp.type) != "voltage_source":
                continue
            ref = comp.ref_id.strip().upper()
            pmap = pin_net_map.get(ref, {})
            n_plus = self._pick_node(pmap, ["+", "1", "P"])
            n_minus = self._pick_node(pmap, ["-", "2", "N"])
            if not n_minus or n_minus == n_plus:
                n_minus = "0"
            if self._normalize_net_name(n_plus) == rail and self._normalize_net_name(n_minus) == "0":
                return True
        return False

    def _select_input_node(self, ir: CircuitIR, pin_net_map: Dict[str, Dict[str, str]]) -> str:
        meta = ir.metadata.model_dump() if hasattr(ir.metadata, "model_dump") else {}
        explicit = str(meta.get("input_node") or meta.get("input_net") or "").strip()
        net_names = {self._normalize_net_name(n.net_name) for n in ir.nets}
        supply = self._SUPPLY_NET_NORMALIZED

        if explicit:
            normalized_explicit = self._normalize_net_name(explicit)
            if normalized_explicit in net_names and normalized_explicit not in {"0", "gnd"}:
                return normalized_explicit

        for net in ir.nets:
            name = self._normalize_net_name(net.net_name)
            if name in {"0", "gnd"}:
                continue
            if self._is_explicit_signal_input_net(net.net_name) and name.upper() not in supply:
                return name

        for comp in ir.components:
            ctype = str(comp.type or "").strip().lower()
            ref = comp.ref_id.strip().upper()
            if ctype in {"capacitor", "cap", "c"} and any(ref.startswith(p) for p in ("C1", "CIN", "C_IN", "CINPUT")):
                nets = pin_net_map.get(ref, {})
                for pin_key in ("1", "A", "P", "+"):
                    candidate = self._normalize_net_name(nets.get(pin_key, ""))
                    if candidate and candidate not in {"0", "gnd"} and candidate.upper() not in supply:
                        return candidate

        pin_map_in = pin_net_map.get("IN", {})
        for pin_key in ("1", "A", "P", "+"):
            candidate = self._normalize_net_name(pin_map_in.get(pin_key, ""))
            if candidate and candidate not in {"0", "gnd"} and candidate.upper() not in supply:
                return candidate

        if "IN_SIG" in net_names:
            return "IN_SIG"
        if "IN" in net_names:
            return "IN"

        return "in"

    def _select_output_node(self, ir: CircuitIR, pin_net_map: Dict[str, Dict[str, str]]) -> str:
        meta = ir.metadata.model_dump() if hasattr(ir.metadata, "model_dump") else {}
        explicit = str(meta.get("output_node") or meta.get("output_net") or "").strip()
        net_names = {self._normalize_net_name(n.net_name) for n in ir.nets}
        _supply = {"0", "gnd", "VCC", "VDD", "VBB", "VBAT", "VSUPPLY"}

        if explicit:
            normalized_explicit = self._normalize_net_name(explicit)
            if normalized_explicit in net_names and normalized_explicit not in _supply:
                return normalized_explicit

        # tag matching
        for net in ir.nets:
            name = self._normalize_net_name(net.net_name)
            low = str(net.net_name).strip().lower()
            if low in {"out", "out_sig", "vout", "net_out", "output", "signal_out"} and name not in _supply:
                return name
            if low.startswith(("net_out", "output_", "vout_")) and name not in _supply:
                return name

        pin_map_out = pin_net_map.get("OUT", {})
        for pin_key in ("1", "A", "P", "+"):
            candidate = self._normalize_net_name(pin_map_out.get(pin_key, ""))
            if candidate and candidate not in _supply:
                return candidate

        if "OUT_SIG" in net_names:
            return "OUT_SIG"
        if "OUT" in net_names:
            return "OUT"
        
        # Net output load resistor (ROUT) pin 1
        for ref in ("ROUT", "RL", "RLOAD", "ROUTPUT"):
            nets = pin_net_map.get(ref, {})
            for pin_key in ("1", "A", "P", "+"):
                candidate = self._normalize_net_name(nets.get(pin_key, ""))
                if candidate and candidate not in _supply:
                    return candidate
        
        # Net output coupling cap (C2, COUT) pin 2
        for comp in ir.components:
            ref = comp.ref_id.strip().upper()
            ctype = str(comp.type or "").strip().lower()
            if ctype in {"capacitor", "cap", "c"} and any (ref.startswith(p) for p in ("C2", "COUT", "C_OUT", "COUTPUT")):
                nets = pin_net_map.get(ref, {})
                for pin_key in ("2", "B", "N", "-"):
                    candidate = self._normalize_net_name(nets.get(pin_key, ""))
                    if candidate and candidate not in _supply:
                        return candidate

        # Fallback: net của collector resistor (RC, RD) pin 2
        for comp in ir.components:
            ref = comp.ref_id.strip().upper()
            if ref in ("RC", "RD", "RC1"):
                nets = pin_net_map.get(ref, {})
                for pk in ("2", "B", "N", "-"):
                    c = self._normalize_net_name(nets.get(pk, ""))
                    if c and c not in _supply:
                        return c
        
        # Generic fallback
        input_node = self._select_input_node(ir, pin_net_map)
        for net in ir.nets:
            name = self._normalize_net_name(net.net_name)
            if name not in _supply | {input_node}:
                return name

        # Find net collector (connect to Rc)
        for comp in ir.components:
            ref = comp.ref_id.strip().upper()
            if ref.startswith("RC") or ref == "RD":
                nets = pin_net_map.get(ref, {})
                for pk in ("2", "B", "N", "-"):
                    candidate = self._normalize_net_name(nets.get(pk, ""))
                    if candidate and candidate not in _supply:
                        return candidate

        return "out"

    def _canonical_type(self, component_type: str) -> Optional[str]:
        raw = str(component_type or "").strip().lower()
        if not raw:
            return None
        if raw in {"power_supply", "power", "vcc", "vdd", "vsupply", "voltage_source", "vsource"}:
            return "voltage_source"
        if raw in {"ground", "gnd", "0", "vss"}:
            return "ground"
        if raw in {"port", "connector"}:
            return "connector"
        if raw in {"opamp_ic", "op_amp", "opamp", "operational_amplifier"}:
            return "opamp"
        if raw in self._TYPE_ALIASES:
            return self._TYPE_ALIASES[raw]
        # Longest keys first; never treat single-letter aliases as substrings (e.g. "c" in "opamp_ic").
        for key, alias in sorted(self._TYPE_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True):
            if len(key) <= 1:
                if raw == key:
                    return alias
                continue
            if key in raw:
                return alias
        return None

    @staticmethod
    def _normalize_net_name(name: str) -> str:
        text = str(name or "").strip()
        if not text:
            return "0"
        if text.lower() in {"0", "gnd", "ground", "vss"}:
            return "0"
        return re.sub(r"[^A-Za-z0-9_:+-]", "_", text)

    @staticmethod
    def _pick_node(pin_map: Dict[str, str], preferred: List[str]) -> Optional[str]:
        for key in preferred:
            val = pin_map.get(key.upper())
            if val:
                return val
        if pin_map:
            return next(iter(pin_map.values()))
        return None

    @staticmethod
    def _pick_two_nodes(pin_map: Dict[str, str]) -> Tuple[Optional[str], Optional[str]]:
        first = NgspiceCompilerService._pick_node(pin_map, ["1", "+", "A", "P"])
        second = NgspiceCompilerService._pick_node(pin_map, ["2", "-", "K", "N"])
        if first and second and first != second:
            return first, second

        uniq = []
        for node in pin_map.values():
            if node not in uniq:
                uniq.append(node)
        if len(uniq) >= 2:
            return uniq[0], uniq[1]
        if len(uniq) == 1:
            return uniq[0], "0"
        return None, None

    @staticmethod
    def _normalize_value(value: Any) -> str:
        import re as _re
        text = str(value).strip()
        if not text:
            return "1k"
        # Reject pure-text values like "Signal In", "Input", "Output"
        if _re.match(r'^[A-Za-z][A-Za-z\s]+$', text) and not _re.search(r'\d', text):
            return "1k"
        # Strip trailing unit qualifiers that ngspice doesn't accept (Ohm, ohm)
        text = _re.sub(r'(?i)ohm$', '', text).strip()
        # Strip trailing 'V' from voltage-style values used on resistors (e.g. "12V" → skip)
        if _re.match(r'^\d+(\.\d+)?[Vv]$', text):
            return "1k"
        return text

    @staticmethod
    def _normalize_source_value(value: Any) -> str:
        import re as _re
        text = str(value).strip()
        if not text:
            return "DC 0"
        if text.upper().startswith(("DC", "AC", "SIN", "PULSE", "EXP", "SFFM", "PWL")):
            return text
        # Value must contain at least one digit to be a valid SPICE numeric expression.
        # Pure net-name values like "VCC" or "VDD" are not valid SPICE values.
        if not _re.search(r'\d', text):
            return "DC 12"
        return f"DC {text}"


def to_sse_event(event: str, payload: Dict[str, Any]) -> str:
    """Convert a payload dict into an SSE message block."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
