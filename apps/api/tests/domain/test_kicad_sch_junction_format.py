import sys
from pathlib import Path

# Ensure app package imports work when running tests from apps/api
APP_DIR = Path(__file__).resolve().parents[2] / "app"
sys.path.insert(0, str(APP_DIR))

from app.infrastructure.exporters.kicad_sch_serializer import KiCadSchSerializer


def test_junction_uses_2d_at_coordinates() -> None:
    serializer = KiCadSchSerializer()
    lines = serializer._build_junction(63.0, 68.0)
    text = "\n".join(lines)

    assert "(at 63.0 68.0)" in text
    assert "(at 63.0 68.0 0)" not in text
