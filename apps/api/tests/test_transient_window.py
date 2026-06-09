"""Unit tests for transient_window helpers."""

from app.application.ai.transient_window import (
    DISPLAY_RESOLUTION_N,
    MAX_TRAN_STOP_S,
    apply_transient_window_defaults,
    compute_ideal_point_count,
    compute_transient_stop_s,
    compute_transient_window,
    extract_frequency_hz,
    parse_time_seconds,
)


def test_parse_time_seconds_units():
    assert parse_time_seconds("10ms") == 0.01
    assert parse_time_seconds("20ms") == 0.02
    assert parse_time_seconds("5") == 5.0
    assert abs(parse_time_seconds("100us") - 1e-4) < 1e-12


def test_auto_stop_capped_at_twenty_ms():
    stop_s = compute_transient_stop_s(100.0)
    assert stop_s == MAX_TRAN_STOP_S
    assert abs(stop_s - 0.02) < 1e-12


def test_auto_stop_respects_explicit_cycles():
    stop_s = compute_transient_stop_s(1000.0, cycles=3)
    assert abs(stop_s - 0.003) < 1e-9


def test_apply_defaults_overwrites_legacy_ten_ms():
    circuit = {
        "tran_stop": "10ms",
        "tran_step": "10us",
        "source_params": {"frequency": 100.0},
    }
    apply_transient_window_defaults(circuit, overwrite=True)
    assert parse_time_seconds(circuit["tran_stop"]) == MAX_TRAN_STOP_S


def test_extract_frequency_from_source_params():
    circuit = {"source_params": {"frequency": 1200.0}}
    assert extract_frequency_hz(circuit) == 1200.0


def test_ideal_point_count_formula():
    # 5 ms @ 1 kHz, N=128 → 0.005 * 1000 * 128 = 640 (+1)
    pts = compute_ideal_point_count(0.005, 1000.0, resolution_n=DISPLAY_RESOLUTION_N)
    assert pts >= 640


def test_compute_window_always_twenty_ms():
    for freq in (100.0, 1000.0, 10000.0):
        stop_s, step_s = compute_transient_window(freq, max_points=262144)
        assert stop_s == MAX_TRAN_STOP_S
        assert stop_s / step_s <= 262144.0


def test_compute_window_points_follow_time_frequency_resolution():
    stop_s, step_s = compute_transient_window(100.0, max_points=262144)
    assert stop_s == MAX_TRAN_STOP_S
    ideal = compute_ideal_point_count(stop_s, 100.0, resolution_n=DISPLAY_RESOLUTION_N)
    actual = int(stop_s / step_s) + 1
    assert actual >= min(ideal, 262144) * 0.9
