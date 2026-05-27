"""Topology intent: không default CE; metadata repo load đủ BJT/op-amp."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.application.ai.llm_router import LLMRouter
from app.application.ai.nlu_service import NLUService
from app.domains.circuits.ai_core.ai_core import AICore
from app.domains.circuits.ai_core.topology_planner import TopologyPlanner
from app.domains.circuits.ai_core.spec_parser import UserSpec

_API_ROOT = Path(__file__).resolve().parents[3]
_METADATA_DIR = _API_ROOT / "resources" / "templates_metadata"
_BLOCK_LIBRARY_DIR = _API_ROOT / "resources" / "block_library"
_TEMPLATES_DIR = _API_ROOT / "resources" / "templates"


@pytest.fixture
def nlu() -> NLUService:
    return NLUService()


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Thiết kế mạch BJT common emitter gain 50 VCC 12V", "common_emitter"),
        ("Mạch khuếch đại CE gain 40 dùng 12V", "common_emitter"),
        ("Thiết kế mạch BJT common collector buffer VCC 12V", "common_collector"),
        ("Mạch emitter follower BJT VCC 9V", "common_collector"),
        ("Thiết kế mạch BJT common base gain 20 VCC 12V", "common_base"),
        ("Mạch CB gain 15 VCC 10V", "common_base"),
        ("Op-amp đảo gain 10 VCC 15V", "inverting"),
        ("Mạch khuếch đại đảo gain 8 nguồn 12V", "inverting"),
        ("Op-amp không đảo gain 5 VCC 12V", "non_inverting"),
        ("Mạch khuếch đại không đảo gain 6 VCC 12V", "non_inverting"),
        ("Mạch khuếch đại vi sai gain 10 VCC 15V", "differential"),
        ("Differential amplifier gain 20 VCC 15V", "differential"),
    ],
)
def test_nlu_detects_explicit_topology(nlu: NLUService, text: str, expected: str) -> None:
    intent = nlu._rule_based_parse(text)
    assert intent.circuit_type == expected, f"text={text!r} got {intent.circuit_type!r}"


def test_nlu_no_default_ce_for_generic_bjt_amplifier(nlu: NLUService) -> None:
    intent = nlu._rule_based_parse("Thiết kế mạch khuếch đại BJT gain 50 VCC 12V")
    assert intent.circuit_type in {"", "unknown"} or str(intent.circuit_type).startswith("unknown")


def test_llm_router_does_not_inject_ce_default() -> None:
    raw = "Design a BJT voltage amplifier with gain 40 and 12V supply"
    augmented = LLMRouter._augment_requirements_with_defaults(raw)
    assert "common-emitter" not in augmented.lower()
    assert "common_emitter" not in augmented.lower()
    assert augmented == raw


def test_metadata_repository_loads_cc_cb_templates() -> None:
    core = AICore(
        metadata_dir=_METADATA_DIR,
        block_library_dir=_BLOCK_LIBRARY_DIR,
        templates_dir=_TEMPLATES_DIR,
    )
    repo = core._repo
    families = {m.get("domain", {}).get("family") for m in repo._metadata.values()}
    assert "common_collector" in families
    assert "common_base" in families
    assert "common_emitter" in families
    assert len(repo._metadata) >= 14


@pytest.mark.parametrize(
    "circuit_type,expected_template_prefix",
    [
        ("common_emitter", "BJT-CE"),
        ("common_collector", "BJT-CC"),
        ("common_base", "BJT-CB"),
    ],
)
def test_topology_planner_matches_bjt_template_by_family(
    circuit_type: str,
    expected_template_prefix: str,
) -> None:
    core = AICore(
        metadata_dir=_METADATA_DIR,
        block_library_dir=_BLOCK_LIBRARY_DIR,
        templates_dir=_TEMPLATES_DIR,
    )
    spec = UserSpec(
        circuit_type=circuit_type,
        gain=20.0,
        vcc=12.0,
        supply_mode="single_supply",
        raw_text=f"test {circuit_type}",
    )
    plan = TopologyPlanner().plan(spec, core._repo)
    assert plan.matched_template_id, plan.rationale
    assert str(plan.matched_template_id).startswith(expected_template_prefix), plan.matched_template_id
