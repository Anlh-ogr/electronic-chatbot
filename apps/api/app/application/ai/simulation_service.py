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

# ====== Lý do sử dụng thư viện ======
# json: parse .control block output, serialize waveform result
# os + subprocess: gọi ngspice binary, chn environment
# re: parse ngspice tplot output, extract number từ text
# tempfile: tạo temp file cho netlist, lưu safe
# time + math: timing, conversion giữa units
# dataclass: định nghĩa WaveformTrace, SimulationResult value objects
# pathlib: xử lý file paths cross-platform
# typing: type safe simulation service API

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from app.application.ai.circuit_ir_schema import CircuitIR


class SimulationError(RuntimeError):
    """Raised when a simulation run cannot be completed."""


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
        self._executable = executable or os.getenv("NGSPICE_EXECUTABLE") or "ngspice"
        env_timeout = os.getenv("NGSPICE_TIMEOUT_SECONDS")
        self._timeout_seconds = int(env_timeout) if env_timeout else timeout_seconds
        if self._timeout_seconds < 10:
            self._timeout_seconds = 10
        env_max_points = os.getenv("NGSPICE_MAX_POINTS")
        self._max_points = int(env_max_points) if env_max_points else 2500
        if self._max_points < 500:
            self._max_points = 500
        env_max_output_points = os.getenv("NGSPICE_RETURN_MAX_POINTS")
        self._max_output_points = int(env_max_output_points) if env_max_output_points else 1200
        if self._max_output_points < 300:
            self._max_output_points = 300

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
        )

    def simulate_transient(
        self,
        netlist: str,
        probes: Optional[List[str]] = None,
        step: str = "10us",
        stop: str = "10ms",
        start: str = "0",
        reltol: str = "1e-3",
        expected_gain: Optional[float] = None,
    ) -> SimulationResult:
        if not netlist or not netlist.strip():
            raise SimulationError("Netlist is empty")

        cleaned_netlist = self._normalize_netlist(netlist)
        selected_probes = self._normalize_probes(probes)
        step, stop, start = self._normalize_analysis_window(step, stop, start)

        started = time.perf_counter()
        attempts = [
            (step, stop, start, False, reltol),
            (step, stop, start, True, reltol),
            (os.getenv("NGSPICE_FALLBACK_STEP", "100us"), os.getenv("NGSPICE_FALLBACK_STOP", "2ms"), "0", False, reltol),
            (os.getenv("NGSPICE_FALLBACK_STEP", "100us"), os.getenv("NGSPICE_FALLBACK_STOP", "2ms"), "0", True, reltol),
            ("200us", "500us", "0", True, reltol),
        ]

        last_timeout_error: Optional[SimulationError] = None
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
                break
            except SimulationError as exc:
                if "timed out" in str(exc).lower():
                    last_timeout_error = exc
                    continue
                raise

        if process is None:
            raise last_timeout_error or SimulationError("Simulation timed out")

        elapsed = (time.perf_counter() - started) * 1000.0
        raw_points = len(traces[0].x) if traces else 0
        traces = self._downsample_traces(traces)
        points = len(traces[0].x) if traces else 0
        x_unit = self._choose_time_unit(traces[0].x[-1] if traces and traces[0].x else 0.0)
        metrics = self._estimate_gain_metrics(traces=traces, probes=selected_probes, expected_gain=expected_gain)

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
                text = str(item).strip().lower()
                if not text:
                    continue
                if text.startswith("v(") or text.startswith("i("):
                    normalized.append(text)
                else:
                    normalized.append(f"v({text})")
            return list(dict.fromkeys(normalized))
        return None

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
            circuit_data.get("tran_stop", circuit_data.get("stop_time", circuit_data.get("stop", "10ms"))),
            "10ms",
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
        if not traces:
            return traces
        points = len(traces[0].x)
        if points <= self._max_output_points:
            return traces

        step = max(1, points // self._max_output_points)
        sampled_indices = list(range(0, points, step))
        if sampled_indices[-1] != points - 1:
            sampled_indices.append(points - 1)

        new_traces: List[WaveformTrace] = []
        for trace in traces:
            new_x = [trace.x[i] for i in sampled_indices]
            new_y = [trace.y[i] for i in sampled_indices]
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
                "NGSpice executable not found. Set NGSPICE_EXECUTABLE or add ngspice to PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise SimulationError("Simulation timed out") from exc

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            debug_text = "\n".join([part for part in [stderr, stdout] if part])
            raise SimulationError(f"NGSpice failed: {debug_text or 'unknown error'}")

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
        if not data_path.exists():
            debug_log = data_path.parent / "stdout.log"
            debug_text = ""
            if debug_log.exists():
                try:
                    debug_text = debug_log.read_text(encoding="utf-8", errors="ignore")[-1200:]
                except Exception:
                    debug_text = ""
            if debug_text:
                raise SimulationError(
                    "Simulation finished but waveform file was not created. ngspice log tail:\n"
                    + debug_text
                )
            raise SimulationError("Simulation finished but waveform file was not created")

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
            raise SimulationError("No numeric waveform samples were parsed")

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
        if ".control" in text.lower():
            raise SimulationError("Please provide a netlist without .control/.endc block")

        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            raise SimulationError("Netlist is empty")

        # SPICE treats the first line as the title. If users paste a netlist
        # that starts with an element (e.g. V1 ...), that element is ignored.
        # Add a synthetic title in that case.
        first = lines[0].strip()
        first_token = first.split()[0] if first.split() else ""
        starts_like_element = bool(re.match(r"^[A-Za-z]\w*$", first_token)) and len(first.split()) >= 3
        starts_with_directive = first.startswith(".")

        if starts_like_element or starts_with_directive:
            lines.insert(0, "Chatbot transient simulation")

        return "\n".join(lines)

    @staticmethod
    def _normalize_probes(probes: Optional[List[str]]) -> List[str]:
        if not probes:
            return ["v(in)", "v(out)"]
        normalized: List[str] = []
        for probe in probes:
            value = str(probe).strip().lower()
            if value and value not in normalized:
                normalized.append(value)

        # When only one endpoint is provided, synthesize the counterpart probe.
        if len(normalized) == 1:
            p0 = normalized[0]
            if "vin" in p0 and "vout" not in p0:
                normalized.append(p0.replace("vin", "vout"))
            elif "vout" in p0 and "vin" not in p0:
                normalized.append(p0.replace("vout", "vin"))
            elif "net_in" in p0 and "net_out" not in p0:
                normalized.append(p0.replace("net_in", "net_out"))
            elif "net_out" in p0 and "net_in" not in p0:
                normalized.append(p0.replace("net_out", "net_in"))
            elif "input" in p0 and "output" not in p0:
                normalized.append(p0.replace("input", "output"))
            elif "output" in p0 and "input" not in p0:
                normalized.append(p0.replace("output", "input"))

        if not normalized:
            normalized = ["v(in)", "v(out)"]
        return normalized

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
    ) -> Dict[str, Any]:
        """Estimate gain/phase behavior from simulated waveforms and compare to expected Av."""
        if not traces:
            return {"status": "no_traces"}

        trace_map = {t.name.lower(): t for t in traces}
        input_trace = self._pick_input_trace(trace_map, probes)
        output_trace = self._pick_output_trace(trace_map, probes)

        if not input_trace or not output_trace:
            return {
                "status": "missing_required_probes",
                "required": ["input", "output"],
                "available": [t.name for t in traces],
            }

        sample_count = min(len(input_trace.x), len(output_trace.x), len(input_trace.y), len(output_trace.y))
        if sample_count < 8:
            return {"status": "insufficient_samples", "sample_count": sample_count}

        start_idx = max(0, int(sample_count * 0.2))
        x_in = input_trace.x[start_idx:sample_count]
        y_in = input_trace.y[start_idx:sample_count]
        y_out = output_trace.y[start_idx:sample_count]
        if len(y_in) < 8 or len(y_out) < 8:
            return {"status": "insufficient_steady_state_samples"}

        vin_pp = self._peak_to_peak(y_in)
        vout_pp = self._peak_to_peak(y_out)
        if vin_pp <= 0:
            return {"status": "invalid_input_signal", "vin_pp": vin_pp}

        gain_abs = vout_pp / vin_pp
        corr = self._normalized_correlation(y_in, y_out)
        is_inverting = corr < 0
        measured_gain = -gain_abs if is_inverting else gain_abs
        phase_deg = 180.0 if is_inverting else 0.0

        metrics: Dict[str, Any] = {
            "status": "ok",
            "input_probe": input_trace.name,
            "output_probe": output_trace.name,
            "window_start_s": x_in[0] if x_in else 0.0,
            "vin_pp": vin_pp,
            "vout_pp": vout_pp,
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

    def _pick_input_trace(self, trace_map: Dict[str, WaveformTrace], probes: List[str]) -> Optional[WaveformTrace]:
        preferred = [
            "v(in)", "v(vin)", "v(net_in)", "v(input)",
        ]
        for key in preferred:
            if key in trace_map:
                return trace_map[key]

        for probe in probes:
            p = probe.lower()
            if any(tag in p for tag in ("vin", "input", "net_in", "in)")) and p in trace_map:
                return trace_map[p]

        for name, trace in trace_map.items():
            if name.startswith("v(") and any(tag in name for tag in ("vin", "input", "net_in", "in)")):
                return trace
        return None

    def _pick_output_trace(self, trace_map: Dict[str, WaveformTrace], probes: List[str]) -> Optional[WaveformTrace]:
        preferred = [
            "v(out)", "v(vout)", "v(net_out)", "v(output)",
        ]
        for key in preferred:
            if key in trace_map:
                return trace_map[key]

        for probe in probes:
            p = probe.lower()
            if any(tag in p for tag in ("vout", "output", "net_out", "out)")) and p in trace_map:
                return trace_map[p]

        for name, trace in trace_map.items():
            if name.startswith("v(") and any(tag in name for tag in ("vout", "output", "net_out", "out)")):
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
    }

    _MODEL_CARDS: Dict[str, str] = {
        "QNPN": ".model QNPN NPN(BF=180 IS=1e-14 VAF=100)",
        "QPNP": ".model QPNP PNP(BF=120 IS=1e-14 VAF=80)",
        "DDEFAULT": ".model DDEFAULT D(IS=1e-14 N=1.9)",
    }

    def __init__(self, executable: Optional[str] = None, timeout_seconds: int = 90) -> None:
        self._executable = executable or os.getenv("NGSPICE_EXECUTABLE") or "ngspice"
        env_timeout = os.getenv("NGSPICE_TIMEOUT_SECONDS")
        self._timeout_seconds = int(env_timeout) if env_timeout else timeout_seconds
        if self._timeout_seconds < 10:
            self._timeout_seconds = 10

    def generate_spice_deck(self, ir: CircuitIR) -> str:
        """Generate SPICE deck from CircuitIR with auto testbench injection."""
        pin_net_map = self._build_pin_net_map(ir)
        lines: List[str] = ["* Auto-generated by NgspiceCompilerService"]
        used_models: List[str] = []

        for comp in ir.components:
            line, model_key = self._component_to_spice_line(comp.ref_id, comp.type, comp.value, pin_net_map.get(comp.ref_id.strip().upper(), {}))
            if line:
                lines.append(line)
            if model_key and model_key not in used_models:
                used_models.append(model_key)

        for model_key in used_models:
            model_line = self._MODEL_CARDS.get(model_key)
            if model_line:
                lines.append(model_line)

        lines.extend(self._build_testbench(ir, pin_net_map))
        lines.append(".end")
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
                return

            if not tsv_path.exists():
                yield json.dumps(
                    {
                        "status": "completed",
                        "message": "simulation finished but output.tsv not found",
                    },
                    ensure_ascii=False,
                )
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
        mapping: Dict[str, Dict[str, str]] = {}
        for net in ir.nets:
            normalized_net = self._normalize_net_name(net.net_name)
            for node in net.nodes:
                if ":" not in node:
                    continue
                raw_ref, raw_pin = node.split(":", 1)
                ref = raw_ref.strip().upper()
                pin = raw_pin.strip().upper()
                if not ref or not pin:
                    continue
                mapping.setdefault(ref, {})[pin] = normalized_net
        return mapping

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
            return None, None

        if ctype in {"resistor", "capacitor", "inductor"}:
            n1, n2 = self._pick_two_nodes(pin_map)
            if not n1 or not n2:
                return None, None
            prefix = {"resistor": "R", "capacitor": "C", "inductor": "L"}[ctype]
            comp_name = ref if ref.startswith(prefix) else f"{prefix}{ref}"
            return f"{comp_name} {n1} {n2} {self._normalize_value(value)}", None

        if ctype in {"npn", "pnp"}:
            collector = self._pick_node(pin_map, ["C", "2"])
            base = self._pick_node(pin_map, ["B", "1"])
            emitter = self._pick_node(pin_map, ["E", "3"])
            if not collector or not base or not emitter:
                return None, None
            model = "QNPN" if ctype == "npn" else "QPNP"
            comp_name = ref if ref.startswith("Q") else f"Q{ref}"
            return f"{comp_name} {collector} {base} {emitter} {model}", model

        if ctype == "diode":
            anode = self._pick_node(pin_map, ["A", "1"])
            cathode = self._pick_node(pin_map, ["K", "2"])
            if not anode or not cathode:
                return None, None
            comp_name = ref if ref.startswith("D") else f"D{ref}"
            return f"{comp_name} {anode} {cathode} DDEFAULT", "DDEFAULT"

        if ctype in {"voltage_source", "current_source"}:
            n_plus = self._pick_node(pin_map, ["+", "1", "P"])
            n_minus = self._pick_node(pin_map, ["-", "2", "N"])
            if not n_plus or not n_minus:
                return None, None
            source_name = ref
            if ctype == "voltage_source" and not source_name.startswith("V"):
                source_name = f"V{source_name}"
            if ctype == "current_source" and not source_name.startswith("I"):
                source_name = f"I{source_name}"
            return f"{source_name} {n_plus} {n_minus} {self._normalize_source_value(value)}", None

        return None, None

    def _build_testbench(self, ir: CircuitIR, pin_net_map: Dict[str, Dict[str, str]]) -> List[str]:
        meta = ir.metadata if isinstance(ir.metadata, dict) else {}
        analog_mode = str(meta.get("domain", "analog")).strip().lower() != "digital"

        input_node = self._select_input_node(ir, pin_net_map)
        output_node = self._select_output_node(ir, pin_net_map)
        tran_step = str(meta.get("tran_step") or "1u")
        tran_stop = str(meta.get("tran_stop") or "5m")

        lines: List[str] = []
        if analog_mode:
            lines.append(f"VTB {input_node} 0 SINE(0 1 1k)")

        lines.append(f".tran {tran_step} {tran_stop}")
        lines.append(".control")
        lines.append("run")
        lines.append(f"wrdata output.tsv v({input_node}) v({output_node})")
        lines.append("write output.raw")
        lines.append("quit")
        lines.append(".endc")
        return lines

    def _select_input_node(self, ir: CircuitIR, pin_net_map: Dict[str, Dict[str, str]]) -> str:
        meta = ir.metadata if isinstance(ir.metadata, dict) else {}
        explicit = str(meta.get("input_node") or meta.get("input_net") or "").strip()
        if explicit:
            return self._normalize_net_name(explicit)

        for net in ir.nets:
            name = self._normalize_net_name(net.net_name)
            low = str(net.net_name).strip().lower()
            if any(tag in low for tag in ("in", "vin", "input")) and name not in {"0", "gnd"}:
                return name

        for net in ir.nets:
            name = self._normalize_net_name(net.net_name)
            if name not in {"0", "gnd"}:
                return name

        return "in"

    def _select_output_node(self, ir: CircuitIR, pin_net_map: Dict[str, Dict[str, str]]) -> str:
        meta = ir.metadata if isinstance(ir.metadata, dict) else {}
        explicit = str(meta.get("output_node") or meta.get("output_net") or "").strip()
        if explicit:
            return self._normalize_net_name(explicit)

        for net in ir.nets:
            name = self._normalize_net_name(net.net_name)
            low = str(net.net_name).strip().lower()
            if any(tag in low for tag in ("out", "vout", "output")) and name not in {"0", "gnd"}:
                return name

        input_node = self._select_input_node(ir, pin_net_map)
        for net in ir.nets:
            name = self._normalize_net_name(net.net_name)
            if name not in {"0", "gnd", input_node}:
                return name

        return "out"

    def _canonical_type(self, component_type: str) -> Optional[str]:
        raw = str(component_type or "").strip().lower()
        if not raw:
            return None
        if raw in self._TYPE_ALIASES:
            return self._TYPE_ALIASES[raw]
        for key, alias in self._TYPE_ALIASES.items():
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
        text = str(value).strip()
        if not text:
            return "1k"
        return text

    @staticmethod
    def _normalize_source_value(value: Any) -> str:
        text = str(value).strip()
        if not text:
            return "DC 0"
        if text.upper().startswith(("DC", "AC", "SIN", "PULSE", "EXP", "SFFM", "PWL")):
            return text
        return f"DC {text}"


def to_sse_event(event: str, payload: Dict[str, Any]) -> str:
    """Convert a payload dict into an SSE message block."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
