from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Ensure app package imports work when running script directly from apps/api
API_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(API_ROOT))

from app.domains.circuits.ai_core.ai_core import AICore
from app.domains.circuits.ai_core.metadata_repo import MetadataRepository
from app.domains.circuits.ai_core.spec_parser import UserSpec


METADATA_DIR = API_ROOT / "resources" / "templates_metadata"
BLOCK_LIBRARY_DIR = API_ROOT / "resources" / "block_library"
TEMPLATES_DIR = API_ROOT / "resources" / "templates"


def _families_from_metadata(repo: MetadataRepository) -> List[str]:
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
        raw_text=f"coverage test family={family} gain={gain}",
    )

    if family == "multi_stage":
        spec.requested_stage_blocks = ["cs_block", "cd_block"]
        spec.coupling_preference = "direct"
        spec.device_preference = "mosfet"
        spec.raw_text = "thiet ke 2 tang CS-CD direct coupling, gain 20-30"

    return spec


def _extract_metadata_blocks(meta: Dict) -> Set[str]:
    fs = meta.get("functional_structure", {})
    ordered = ((fs.get("pattern_signature") or {}).get("ordered_block_types") or [])
    return {str(b) for b in ordered if b}


def _extract_result_blocks(result) -> Set[str]:
    blocks: Set[str] = set()
    if result.plan and result.plan.blocks:
        blocks.update(str(b) for b in result.plan.blocks if b)

    if result.plan and result.plan.matched_metadata:
        blocks.update(_extract_metadata_blocks(result.plan.matched_metadata))

    return blocks


def build_coverage_report() -> Tuple[Dict, str]:
    repo = MetadataRepository(metadata_dir=METADATA_DIR, block_library_dir=BLOCK_LIBRARY_DIR)
    repo.load()
    core = AICore(metadata_dir=METADATA_DIR, block_library_dir=BLOCK_LIBRARY_DIR, templates_dir=TEMPLATES_DIR)

    families = _families_from_metadata(repo)
    all_metadata_blocks: Set[str] = set()
    for meta in repo.load_all():
        all_metadata_blocks.update(_extract_metadata_blocks(meta))

    family_rows: List[Dict] = []
    covered_families: Set[str] = set()
    covered_blocks: Set[str] = set()

    for family in families:
        spec = _spec_for_family(family)
        result = core.handle_spec(spec)

        success = bool(result.success and result.circuit)
        if success:
            covered_families.add(family)
            covered_blocks.update(_extract_result_blocks(result))

        family_rows.append(
            {
                "family": family,
                "success": success,
                "stage_reached": result.stage_reached,
                "error": result.error,
                "template_id": (result.plan.matched_template_id if result.plan else ""),
                "mode": (result.plan.mode if result.plan else ""),
            }
        )

    uncovered_families = sorted(set(families) - covered_families)
    uncovered_blocks = sorted(all_metadata_blocks - covered_blocks)

    family_coverage_pct = (len(covered_families) / len(families) * 100.0) if families else 100.0
    topology_coverage_pct = (len(covered_blocks) / len(all_metadata_blocks) * 100.0) if all_metadata_blocks else 100.0

    report = {
        "summary": {
            "total_families": len(families),
            "covered_families": len(covered_families),
            "family_coverage_pct": round(family_coverage_pct, 2),
            "total_metadata_blocks": len(all_metadata_blocks),
            "covered_metadata_blocks": len(covered_blocks),
            "topology_coverage_pct": round(topology_coverage_pct, 2),
        },
        "uncovered": {
            "families": uncovered_families,
            "metadata_blocks": uncovered_blocks,
        },
        "families": family_rows,
    }

    lines: List[str] = []
    lines.append("# Topology Coverage Report")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Family coverage: {len(covered_families)}/{len(families)} ({family_coverage_pct:.2f}%)")
    lines.append(
        f"- Topology-block coverage: {len(covered_blocks)}/{len(all_metadata_blocks)} ({topology_coverage_pct:.2f}%)"
    )
    lines.append("")
    lines.append("## Uncovered Families")
    if uncovered_families:
        for fam in uncovered_families:
            lines.append(f"- {fam}")
    else:
        lines.append("- None")

    lines.append("")
    lines.append("## Uncovered Topology Blocks")
    if uncovered_blocks:
        for blk in uncovered_blocks:
            lines.append(f"- {blk}")
    else:
        lines.append("- None")

    lines.append("")
    lines.append("## Family Results")
    lines.append("| Family | Success | Stage | Template | Mode | Error |")
    lines.append("|---|---:|---|---|---|---|")
    for row in family_rows:
        err = (row["error"] or "").replace("|", "/")
        lines.append(
            f"| {row['family']} | {'yes' if row['success'] else 'no'} | {row['stage_reached']} | "
            f"{row['template_id']} | {row['mode']} | {err} |"
        )

    markdown = "\n".join(lines)
    return report, markdown


def main() -> None:
    report, markdown = build_coverage_report()

    out_dir = Path(__file__).resolve().parents[2] / "artifacts" / "coverage"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "topology_coverage.json"
    md_path = out_dir / "topology_coverage.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")

    print(f"Coverage report written: {json_path}")
    print(f"Coverage report written: {md_path}")


if __name__ == "__main__":
    main()
