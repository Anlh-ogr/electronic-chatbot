from datetime import datetime, timezone

from app.core.timezone import APP_TIMEZONE, now_app, to_api_timestamp


def test_now_app_has_vietnam_offset() -> None:
    now = now_app()
    assert now.tzinfo == APP_TIMEZONE
    assert now.utcoffset().total_seconds() == 7 * 3600


def test_to_api_timestamp_legacy_utc_naive() -> None:
    # Simulates row written with datetime.utcnow() before timezone fix.
    naive_utc = datetime(2026, 5, 17, 8, 30, 0)
    out = to_api_timestamp(naive_utc)
    assert out is not None
    assert out.endswith("+07:00")
    assert "15:30:00" in out


def test_to_api_timestamp_aware_utc() -> None:
    aware = datetime(2026, 5, 17, 8, 30, 0, tzinfo=timezone.utc)
    out = to_api_timestamp(aware)
    assert out == "2026-05-17T15:30:00+07:00"
