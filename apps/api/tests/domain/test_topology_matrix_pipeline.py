import sys
from pathlib import Path

import pytest

# Ensure app package imports work when running tests from apps/api
APP_DIR = Path(__file__).resolve().parents[2] / "app"
sys.path.insert(0, str(APP_DIR))

from app.domains.circuits.ai_core.ai_core import AICore
from app.domains.circuits.ai_core.metadata_repo import MetadataRepository
from app.domains.circuits.ai_core.spec_parser import UserSpec


API_ROOT = Path(__file__).resolve().parents[2]
METADATA_DIR = API_ROOT / "resources" / "templates_metadata"
BLOCK_LIBRARY_DIR = API_ROOT / "resources" / "block_library"
TEMPLATES_DIR = API_ROOT / "resources" / "templates"


@pytest.fixture(scope="session")
def repo() -> MetadataRepository:
    r = MetadataRepository(metadata_dir=METADATA_DIR, block_library_dir=BLOCK_LIBRARY_DIR)
    r.load()
    return r


@pytest.fixture(scope="session")
def core() -> AICore:
    return AICore(
        metadata_dir=METADATA_DIR,
        block_library_dir=BLOCK_LIBRARY_DIR,
        templates_dir=TEMPLATES_DIR,
    )


def _families_from_metadata(repo: MetadataRepository) -> list[str]:
    families = {
        (m.get("domain") or {}).get("family")
        for m in repo.load_all()
        if (m.get("domain") or {}).get("family")
    }
    return sorted(str(f) for f in families)


def _spec_for_family(family: str) -> UserSpec:
    gain = 10.0
    if family in {"common_collector", "common_drain", "class_b", "class_ab"}:
        gain = 1.0
    if family == "multi_stage":
        gain = 25.0

    spec = UserSpec(
        circuit_type=family,
        gain=gain,
        vcc=12.0,
        frequency=1000.0,
        raw_text=f"auto test family={family} gain={gain}",
    )

    if family == "multi_stage":
        spec.requested_stage_blocks = ["cs_block", "cd_block"]
        spec.coupling_preference = "direct"
        spec.device_preference = "mosfet"
        spec.raw_text = "thiet ke 2 tang CS-CD direct coupling, gain 20-30"

    return spec


def test_metadata_and_block_library_chain_consistency(repo: MetadataRepository) -> None:
    assert len(repo.load_all()) > 0
    assert len(repo.get_all_block_types()) > 0

    for meta in repo.load_all():
        fs = meta.get("functional_structure", {})
        ordered = ((fs.get("pattern_signature") or {}).get("ordered_block_types") or [])
        if not ordered:
            continue

        # Every block referenced by metadata must exist in block library.
        for block in ordered:
            assert repo.get_block_definition(block) is not None, (
                f"Missing block definition '{block}' for template {meta.get('template_id')}"
            )

        # Adjacent block chain should respect successor/predecessor compatibility.
        for idx in range(len(ordered) - 1):
            src = ordered[idx]
            dst = ordered[idx + 1]
            src_def = repo.get_block_definition(src) or {}
            dst_def = repo.get_block_definition(dst) or {}

            successors = src_def.get("compatible_successors", [])
            predecessors = dst_def.get("compatible_predecessors", [])

            succ_ok = ("any" in successors) or (dst in successors)
            pred_ok = ("any" in predecessors) or (src in predecessors)
            assert succ_ok or pred_ok, (
                f"Incompatible adjacency '{src}' -> '{dst}' in template {meta.get('template_id')}"
            )


@pytest.mark.parametrize("family", _families_from_metadata(MetadataRepository(metadata_dir=METADATA_DIR, block_library_dir=BLOCK_LIBRARY_DIR)))
def test_pipeline_family_matrix_from_metadata(core: AICore, family: str) -> None:
    spec = _spec_for_family(family)
    result = core.handle_spec(spec)

    assert result.plan is not None, f"No plan produced for family={family}"
    assert result.plan.mode != "no_match", f"No-match plan for family={family}: {result.error}"
    assert result.success, f"Pipeline failed for family={family}: stage={result.stage_reached}, error={result.error}"
    assert result.circuit is not None, f"No circuit generated for family={family}"
    assert bool((result.circuit.circuit_data or {}).get("components")), (
        f"Generated circuit has no components for family={family}"
    )
