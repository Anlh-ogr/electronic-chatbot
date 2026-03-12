"""
Script đồng bộ kiểm tra trạng thái giữa templates/ và templates_metadata/.
Không sửa file template gốc. Chỉ kiểm tra và báo cáo.

Chạy: python sync_templates_metadata.py
       python sync_templates_metadata.py --fix   (tự sinh lại metadata nếu outdated)
"""

import json
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # apps/api/resources
TEMPLATES_DIR = BASE_DIR / "templates"
METADATA_DIR = BASE_DIR / "templates_metadata"
BLOCK_LIBRARY_PATH = BASE_DIR / "block_library" / "block_library.json"
SCHEMA_PATH = METADATA_DIR / "template-metadata.schema.json"


def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_block_library() -> dict:
    if BLOCK_LIBRARY_PATH.exists():
        with open(BLOCK_LIBRARY_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("blocks", {})
    return {}


def load_metadata_index() -> list:
    index_path = METADATA_DIR / "_index_metadata.json"
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            return json.load(f).get("entries", [])
    return []


def check_sync():
    """Kiểm tra đồng bộ giữa templates và metadata."""
    print("=" * 60)
    print("SYNC CHECK: templates/ ↔ templates_metadata/")
    print("=" * 60)

    # 1. Load index
    index_entries = load_metadata_index()
    index_by_tid = {e["template_id"]: e for e in index_entries}

    # 2. List template files (exclude _index*, readme)
    template_files = [
        f for f in TEMPLATES_DIR.iterdir()
        if f.suffix == ".json"
        and not f.name.startswith("_")
        and f.name != "readme.md"
    ]

    # 3. List metadata files
    meta_files = [
        f for f in METADATA_DIR.iterdir()
        if f.suffix == ".json"
        and f.name.endswith(".meta.json")
    ]

    print(f"\nTemplate files found: {len(template_files)}")
    print(f"Metadata files found: {len(meta_files)}")
    print(f"Index entries:        {len(index_entries)}")

    # 4. Check each metadata
    report = {
        "in_sync": [],
        "needs_review": [],
        "outdated": [],
        "missing_metadata": [],
        "orphan_metadata": [],
        "invalid_block_type": [],
    }

    block_lib = load_block_library()
    valid_block_types = set(block_lib.keys()) if block_lib else set()

    # Build map: template_file -> template_id
    template_file_set = {f.name for f in template_files}
    meta_template_refs = {}

    for mf in meta_files:
        with open(mf, "r", encoding="utf-8") as f:
            meta = json.load(f)

        tid = meta.get("template_id", "???")
        ref = meta.get("physical_template_ref", {})
        tfile = ref.get("template_file", "")
        stored_hash = ref.get("template_sha256", "")

        meta_template_refs[tid] = tfile

        # Check template exists
        tpath = TEMPLATES_DIR / tfile
        if not tpath.exists():
            report["needs_review"].append({
                "template_id": tid,
                "reason": f"Template file not found: {tfile}",
            })
            continue

        # Check hash
        current_hash = sha256_file(tpath)
        if current_hash != stored_hash:
            report["outdated"].append({
                "template_id": tid,
                "template_file": tfile,
                "stored_hash": stored_hash[:16] + "...",
                "current_hash": current_hash[:16] + "...",
            })
        else:
            report["in_sync"].append(tid)

        # Validate block types against library
        if valid_block_types:
            blocks = meta.get("functional_structure", {}).get("blocks", [])
            for b in blocks:
                btype = b.get("type", "")
                if btype and btype not in valid_block_types:
                    report["invalid_block_type"].append({
                        "template_id": tid,
                        "block_type": btype,
                    })

    # Check missing metadata (templates without metadata)
    meta_tfiles = set(meta_template_refs.values())
    for tf in template_files:
        if tf.name not in meta_tfiles:
            report["missing_metadata"].append(tf.name)

    # Check orphan metadata (metadata without template)
    for tid, tfile in meta_template_refs.items():
        if tfile not in template_file_set:
            report["orphan_metadata"].append({
                "template_id": tid,
                "template_file": tfile,
            })

    # Print report
    print("\n" + "-" * 40)
    print(f"✅ In sync:          {len(report['in_sync'])}")
    print(f"⚠️  Needs review:     {len(report['needs_review'])}")
    print(f"🔄 Outdated:         {len(report['outdated'])}")
    print(f"❌ Missing metadata: {len(report['missing_metadata'])}")
    print(f"🗑️  Orphan metadata:  {len(report['orphan_metadata'])}")
    print(f"📛 Invalid blocks:   {len(report['invalid_block_type'])}")

    if report["outdated"]:
        print("\n--- Outdated templates (hash mismatch) ---")
        for item in report["outdated"]:
            print(f"  {item['template_id']}: {item['template_file']}")
            print(f"    stored: {item['stored_hash']}  current: {item['current_hash']}")

    if report["missing_metadata"]:
        print("\n--- Templates missing metadata ---")
        for f in report["missing_metadata"]:
            print(f"  {f}")

    if report["orphan_metadata"]:
        print("\n--- Orphan metadata (no template) ---")
        for item in report["orphan_metadata"]:
            print(f"  {item['template_id']}: {item['template_file']}")

    if report["invalid_block_type"]:
        print("\n--- Invalid block types ---")
        for item in report["invalid_block_type"]:
            print(f"  {item['template_id']}: block_type={item['block_type']}")

    if report["needs_review"]:
        print("\n--- Needs review ---")
        for item in report["needs_review"]:
            print(f"  {item['template_id']}: {item['reason']}")

    # Write sync report
    sync_report = {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "templates_count": len(template_files),
        "metadata_count": len(meta_files),
        "in_sync": len(report["in_sync"]),
        "outdated": len(report["outdated"]),
        "missing": len(report["missing_metadata"]),
        "orphans": len(report["orphan_metadata"]),
        "invalid_blocks": len(report["invalid_block_type"]),
        "details": report,
    }

    report_path = METADATA_DIR / "_sync_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(sync_report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n📄 Sync report saved: {report_path}")

    # Check unique template_ids
    tids = [e["template_id"] for e in index_entries]
    if len(tids) != len(set(tids)):
        dups = [t for t in tids if tids.count(t) > 1]
        print(f"\n⚠️  Duplicate template_ids: {set(dups)}")

    all_ok = (
        len(report["outdated"]) == 0
        and len(report["missing_metadata"]) == 0
        and len(report["orphan_metadata"]) == 0
        and len(report["invalid_block_type"]) == 0
        and len(report["needs_review"]) == 0
    )

    if all_ok:
        print("\n✅ All checks passed!")
    else:
        print("\n⚠️  Some issues found. Run with --fix to regenerate outdated metadata.")

    return report


def fix_outdated():
    """Regenerate metadata cho các template bị outdated."""
    # Import generator
    from generate_all_metadata import TEMPLATE_REGISTRY, generate_metadata

    report = check_sync()

    outdated_tids = {item["template_id"] for item in report.get("outdated", [])}
    if not outdated_tids:
        print("\nNo outdated metadata to fix.")
        return

    print(f"\nRegenerating {len(outdated_tids)} outdated metadata files...")
    for entry in TEMPLATE_REGISTRY:
        if entry["template_id"] in outdated_tids:
            meta = generate_metadata(entry)
            if meta:
                meta_path = METADATA_DIR / f"{entry['template_id']}.meta.json"
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2, ensure_ascii=False)
                print(f"  [FIXED] {entry['template_id']}")


if __name__ == "__main__":
    if "--fix" in sys.argv:
        fix_outdated()
    else:
        check_sync()
