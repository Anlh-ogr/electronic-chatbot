"""Compute transient simulation window (tran_stop / tran_step) from signal frequency."""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Optional, Tuple

MAX_TRAN_STOP_S = 0.02  # 20 ms — max simulation / display window
MIN_CYCLES = 10
# N — độ phân giải (điểm/chu kỳ); Points = TimeRange × f × N
DISPLAY_RESOLUTION_N = 128
MIN_POINTS_PER_CYCLE = 32
DEFAULT_POINTS_PER_CYCLE = DISPLAY_RESOLUTION_N
DEFAULT_MAX_POINTS = 262144


def parse_time_seconds(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        val = float(value)
        return val if math.isfinite(val) else None
    text = str(value).strip().lower()
    if not text:
        return None
    m = re.match(r"^([+-]?\d*\.?\d+(?:e[+-]?\d+)?)\s*([a-z]*)$", text)
    if not m:
        return None
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
        return None
    return number * scale


def format_time_seconds(seconds: float) -> str:
    if not math.isfinite(seconds):
        return "0"
    return f"{seconds:.9g}"


def extract_frequency_hz(circuit_data: Dict[str, Any]) -> Optional[float]:
    if not isinstance(circuit_data, dict):
        return None

    candidates = [
        circuit_data.get("input_frequency_hz"),
        circuit_data.get("frequency_hz"),
    ]
    source_params = circuit_data.get("source_params")
    if isinstance(source_params, dict):
        candidates.extend(
            [
                source_params.get("frequency"),
                source_params.get("frequency_hz"),
            ]
        )

    for raw in candidates:
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(val) and val > 0:
            return val
    return None


def compute_transient_stop_s(
    freq_hz: Optional[float],
    *,
    cycles: Optional[int] = None,
    max_stop_s: float = MAX_TRAN_STOP_S,
    min_cycles: int = MIN_CYCLES,
) -> float:
    """Return transient stop time in seconds (capped at max_stop_s, default 5 s)."""
    cap = max(max_stop_s, 1e-9)
    if not freq_hz or freq_hz <= 0:
        return cap

    period = 1.0 / float(freq_hz)
    if cycles is not None and cycles > 0:
        return min(cap, float(cycles) * period)

    # Auto: simulate the full window (up to 5 s) so the waveform toolbar can show many cycles.
    cycles_at_cap = cap * float(freq_hz)
    if cycles_at_cap < float(min_cycles):
        return min(cap, float(min_cycles) * period)
    return cap


def _target_points_per_cycle(points_per_cycle: Optional[int]) -> int:
    ppc = int(points_per_cycle or DEFAULT_POINTS_PER_CYCLE)
    return max(MIN_POINTS_PER_CYCLE, min(256, ppc))


def compute_ideal_point_count(
    time_range_s: float,
    freq_hz: Optional[float],
    *,
    resolution_n: int = DISPLAY_RESOLUTION_N,
) -> int:
    """Points = TimeRange × f × N (rounded up)."""
    span = max(float(time_range_s), 0.0)
    if not freq_hz or freq_hz <= 0 or span <= 0:
        return 0
    return int(math.ceil(span * float(freq_hz) * float(resolution_n))) + 1


def compute_transient_step_s(
    freq_hz: Optional[float],
    stop_s: float,
    *,
    points_per_cycle: Optional[int] = None,
    max_points: int = DEFAULT_MAX_POINTS,
) -> float:
    """Return step so ngspice emits ≈ TimeRange × f × N points (capped by max_points)."""
    max_pts = max(int(max_points), 100)
    span = max(float(stop_s), 1e-12)
    resolution = _target_points_per_cycle(points_per_cycle)
    ideal_points = compute_ideal_point_count(span, freq_hz, resolution_n=resolution)

    if ideal_points > 1:
        point_count = min(ideal_points, max_pts)
        step_s = span / float(max(point_count - 1, 1))
    else:
        step_s = span / float(max_pts)

    if step_s <= 0:
        step_s = span / float(max_pts)
    return max(step_s, 1e-15)


def compute_transient_window(
    freq_hz: Optional[float],
    *,
    cycles: Optional[int] = None,
    points_per_cycle: Optional[int] = None,
    max_stop_s: float = MAX_TRAN_STOP_S,
    max_points: int = DEFAULT_MAX_POINTS,
) -> Tuple[float, float]:
    """Always simulate up to max_stop_s (5 s); adapt tran_step to the point budget."""
    max_pts = max(int(max_points), 100)
    ppc = _target_points_per_cycle(points_per_cycle)
    stop_s = compute_transient_stop_s(freq_hz, cycles=cycles, max_stop_s=max_stop_s)
    step_s = compute_transient_step_s(
        freq_hz,
        stop_s,
        points_per_cycle=ppc,
        max_points=max_pts,
    )
    return stop_s, step_s


def apply_transient_window_defaults(
    circuit_data: Dict[str, Any],
    *,
    cycles: Optional[int] = None,
    points_per_cycle: Optional[int] = None,
    max_stop_s: float = MAX_TRAN_STOP_S,
    max_points: int = DEFAULT_MAX_POINTS,
    overwrite: bool = True,
) -> None:
    """Populate tran_stop / tran_step on circuit_data from frequency when possible."""
    if not isinstance(circuit_data, dict):
        return

    freq = extract_frequency_hz(circuit_data)
    stop_s, step_s = compute_transient_window(
        freq,
        cycles=cycles,
        points_per_cycle=points_per_cycle,
        max_stop_s=max_stop_s,
        max_points=max_points,
    )

    stop_text = format_time_seconds(stop_s)
    step_text = format_time_seconds(step_s)

    if overwrite or not circuit_data.get("tran_stop"):
        circuit_data["tran_stop"] = stop_text
    if overwrite or not circuit_data.get("tran_step"):
        circuit_data["tran_step"] = step_text
