from __future__ import annotations

import argparse
import math
import pickle
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
from sklearn.feature_selection import mutual_info_classif

# Ensure `app` package is importable when script is executed by file path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.domains.circuits.ai_core.ml_topology_selector import (
    RandomForestTopologySelector,
    _normalize_token,
)


def _api_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_model_dir() -> Path:
    return _api_root() / "resources" / "ml_models"


def _resolve_input_dataset(model_dir: Path, input_path: Path | None) -> Path:
    if input_path is not None:
        return input_path

    v4_path = model_dir / "training_data_v4.pkl"

    if v4_path.exists():
        return v4_path
    raise RuntimeError(
        "No training dataset found. Expected training_data_v4.pkl"
    )


def _load_dataset(path: Path) -> Tuple[List[List[float]], List[str], List[str], List[str], List[str], List[str]]:
    with open(path, "rb") as f:
        payload = pickle.load(f)

    required_keys = {
        "x",
        "y_topology_raw",
        "y_block_raw",
        "feature_names",
        "extra_requirement_keys",
    }
    missing = sorted(required_keys - set(payload.keys()))
    if missing:
        raise RuntimeError(f"Dataset file {path} missing keys: {missing}")

    x = [list(map(float, row)) for row in payload["x"]]
    y_topology = [str(v) for v in payload["y_topology_raw"]]
    y_block = [str(v) for v in payload["y_block_raw"]]
    raw_template_ids = payload.get("template_ids", [])
    template_ids = [str(v) for v in raw_template_ids] if raw_template_ids is not None else []
    feature_names = [str(v) for v in payload["feature_names"]]
    extra_keys = [str(v) for v in payload["extra_requirement_keys"]]
    return x, y_topology, y_block, template_ids, feature_names, extra_keys


def _save_dataset(
    path: Path,
    x: Sequence[Sequence[float]],
    y_topology: Sequence[str],
    y_block: Sequence[str],
    template_ids: Sequence[str],
    feature_names: Sequence[str],
    extra_keys: Sequence[str],
) -> None:
    payload = {
        "x": [list(map(float, row)) for row in x],
        "y_topology_raw": list(y_topology),
        "y_block_raw": list(y_block),
        "template_ids": list(template_ids),
        "feature_names": list(feature_names),
        "extra_requirement_keys": list(extra_keys),
    }
    with open(path, "wb") as f:
        pickle.dump(payload, f)


def _drop_duplicates(
    x: Sequence[Sequence[float]],
    y_topology: Sequence[str],
    y_block: Sequence[str],
    template_ids: Sequence[str],
) -> Tuple[List[List[float]], List[str], List[str], List[str], int]:
    seen = set()
    x_unique: List[List[float]] = []
    y_top_unique: List[str] = []
    y_block_unique: List[str] = []
    template_unique: List[str] = []

    duplicate_count = 0
    for row, top, block, template_id in zip(x, y_topology, y_block, template_ids):
        key = (tuple(float(v) for v in row), str(top), str(block), str(template_id))
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        x_unique.append(list(row))
        y_top_unique.append(str(top))
        y_block_unique.append(str(block))
        template_unique.append(str(template_id))

    return x_unique, y_top_unique, y_block_unique, template_unique, duplicate_count


def _clip_and_recompute_derived_features(
    row: np.ndarray,
    feature_names: Sequence[str],
    gain_idx: int,
    log_gain_idx: int,
    vcc_idx: int,
    frequency_log_idx: int,
) -> np.ndarray:
    if gain_idx >= 0:
        row[gain_idx] = max(1e-6, float(row[gain_idx]))
    if log_gain_idx >= 0 and gain_idx >= 0:
        row[log_gain_idx] = math.log10(max(1e-6, abs(float(row[gain_idx]))))
    if vcc_idx >= 0:
        row[vcc_idx] = max(0.1, float(row[vcc_idx]))
    if frequency_log_idx >= 0:
        row[frequency_log_idx] = max(0.0, float(row[frequency_log_idx]))

    for idx, name in enumerate(feature_names):
        if name == "feedback_topology":
            row[idx] = float(np.clip(row[idx], 0.0, 2.0))
            continue
        if "__" in name or name in {
            "high_cmr",
            "output_buffer",
            "power_output",
            "is_differential_input",
            "feedback_resistive_divider",
            "feedback_long_tail_pair",
            "feedback_none",
            "input_fully_differential",
            "input_single_ended",
        }:
            row[idx] = float(np.clip(row[idx], 0.0, 1.0))

    return row


def _feature_index(feature_names: Sequence[str], feature_name: str) -> int:
    return feature_names.index(feature_name) if feature_name in feature_names else -1


def _infer_input_mode_from_topology_label(topology_label: str) -> str:
    topology_token = _normalize_token(topology_label)
    if topology_token in {"differential", "instrumentation"}:
        return "differential"
    return "single_ended"


def _upgrade_feature_matrix_with_structural_columns(
    x: Sequence[Sequence[float]],
    y_topology: Sequence[str],
    y_block: Sequence[str],
    feature_names: Sequence[str],
    extra_keys: Sequence[str],
) -> Tuple[List[List[float]], List[str], bool]:
    canonical_feature_names = RandomForestTopologySelector.build_feature_names(
        extra_requirement_keys=extra_keys
    )
    needs_upgrade = list(feature_names) != canonical_feature_names or any(
        len(row) != len(canonical_feature_names) for row in x
    )
    if not needs_upgrade:
        return [list(map(float, row)) for row in x], list(canonical_feature_names), False

    current_feature_names = [str(name) for name in feature_names]
    upgraded_rows: List[List[float]] = []

    for row, top_label, block_label in zip(x, y_topology, y_block):
        row_values = list(map(float, row))
        row_map = {
            name: row_values[idx]
            for idx, name in enumerate(current_feature_names)
            if idx < len(row_values)
        }

        input_mode = _infer_input_mode_from_topology_label(str(top_label))
        input_channels = 2 if input_mode == "differential" else 1

        row_map.update(
            RandomForestTopologySelector.derive_structural_feature_map(
                circuit_family=str(top_label),
                primary_block=str(block_label),
                input_mode=input_mode,
                input_channels=input_channels,
            )
        )

        upgraded_rows.append([float(row_map.get(name, 0.0)) for name in canonical_feature_names])

    return upgraded_rows, list(canonical_feature_names), True


def _enforce_structural_feature_values(
    row: np.ndarray,
    feature_names: Sequence[str],
    topology_label: str,
    block_label: str,
) -> np.ndarray:
    input_mode = _infer_input_mode_from_topology_label(topology_label)
    input_channels = 2 if input_mode == "differential" else 1

    derived = RandomForestTopologySelector.derive_structural_feature_map(
        circuit_family=str(topology_label),
        primary_block=str(block_label),
        input_mode=input_mode,
        input_channels=input_channels,
    )

    for idx, name in enumerate(feature_names):
        if name in derived:
            row[idx] = float(derived[name])
    return row


def _ratio_true(rows: Sequence[Sequence[float]], idx: int, row_indices: Sequence[int]) -> float:
    if idx < 0 or not row_indices:
        return 0.0
    count_true = 0
    for i in row_indices:
        if float(rows[i][idx]) >= 0.5:
            count_true += 1
    return float(count_true) / float(len(row_indices))


def _compute_block_pair_mutual_info(
    x: Sequence[Sequence[float]],
    y_block: Sequence[str],
    feature_names: Sequence[str],
    positive_block: str,
    negative_block: str,
) -> List[Dict[str, Any]]:
    subset_indices = [
        idx for idx, block_name in enumerate(y_block) if block_name in {positive_block, negative_block}
    ]
    if not subset_indices:
        return []

    x_subset = np.asarray([x[idx] for idx in subset_indices], dtype=np.float64)
    y_subset = np.asarray([
        1 if y_block[idx] == positive_block else 0
        for idx in subset_indices
    ], dtype=np.int64)

    if len(set(int(v) for v in y_subset.tolist())) < 2:
        return []

    mi_scores = mutual_info_classif(x_subset, y_subset, random_state=42)
    ranking = [
        {"feature": str(name), "mi": float(score)}
        for name, score in zip(feature_names, mi_scores)
    ]
    ranking.sort(key=lambda item: item["mi"], reverse=True)
    return ranking


def _print_targeted_mi_summary(mi_ranking: Sequence[Dict[str, Any]]) -> None:
    if not mi_ranking:
        print("Targeted MI analysis unavailable (insufficient class samples).")
        return

    print("=== MI(non_inverting_block vs differential_block) top-12 features ===")
    for item in mi_ranking[:12]:
        print(f"  {item['feature']}: {item['mi']:.6f}")


def _apply_targeted_op_template_augmentation(
    x_source: Sequence[Sequence[float]],
    y_top_source: Sequence[str],
    y_block_source: Sequence[str],
    template_source: Sequence[str],
    feature_names: Sequence[str],
    x_aug: List[List[float]],
    y_top_aug: List[str],
    y_block_aug: List[str],
    template_aug: List[str],
    target_template_ids: Sequence[str],
    target_samples_per_template: int,
    random_seed: int,
    target_noise_std: float,
    gain_idx: int,
    log_gain_idx: int,
    vcc_idx: int,
    frequency_log_idx: int,
) -> Dict[str, Any]:
    target_templates = [str(tid).strip() for tid in target_template_ids if str(tid).strip()]
    if not target_templates:
        return {
            "target_template_ids": [],
            "target_samples_per_template": int(target_samples_per_template),
            "targeted_samples_added": 0,
            "targeted_added_by_template": {},
            "mi_top_features": [],
        }

    mi_ranking = _compute_block_pair_mutual_info(
        x=x_source,
        y_block=y_block_source,
        feature_names=feature_names,
        positive_block="differential_block",
        negative_block="non_inverting_block",
    )
    _print_targeted_mi_summary(mi_ranking)

    idx_high_cmr = _feature_index(feature_names, "high_cmr")
    idx_extra_high_cmrr = _feature_index(feature_names, "extra_req__high_cmrr")
    idx_output_buffer = _feature_index(feature_names, "output_buffer")

    differential_indices = [
        idx for idx, block_name in enumerate(y_block_source) if block_name == "differential_block"
    ]
    target_source_indices = [
        idx for idx, template_id in enumerate(template_source) if template_id in set(target_templates)
    ]

    pre_stats = {
        "differential_high_cmr_true_ratio": _ratio_true(x_source, idx_high_cmr, differential_indices),
        "differential_extra_high_cmrr_true_ratio": _ratio_true(x_source, idx_extra_high_cmrr, differential_indices),
        "target_high_cmr_true_ratio": _ratio_true(x_source, idx_high_cmr, target_source_indices),
        "target_extra_high_cmrr_true_ratio": _ratio_true(x_source, idx_extra_high_cmrr, target_source_indices),
    }

    rng = np.random.default_rng(random_seed)
    added_by_template: Dict[str, int] = {}
    added_rows: List[List[float]] = []

    print("=== Targeted OP template augmentation ===")
    print(f"Target templates: {target_templates}")
    print(f"Target samples per template: {target_samples_per_template}")

    for template_id in target_templates:
        candidate_indices = [
            idx for idx, source_tid in enumerate(template_source) if source_tid == template_id
        ]
        if not candidate_indices:
            print(f"WARNING: No source samples found for template {template_id}")
            continue

        added_by_template[template_id] = 0
        for i in range(target_samples_per_template):
            src_idx = candidate_indices[i % len(candidate_indices)]
            row = np.asarray(x_source[src_idx], dtype=np.float64).copy()

            row = row + rng.normal(0.0, target_noise_std, size=row.shape)

            # Force clearer separation vs differential block profile.
            if idx_high_cmr >= 0:
                row[idx_high_cmr] = 0.0 if rng.random() < 0.95 else 1.0
            if idx_extra_high_cmrr >= 0:
                row[idx_extra_high_cmrr] = 0.0 if rng.random() < 0.90 else 1.0
            if idx_output_buffer >= 0:
                row[idx_output_buffer] = 1.0 if rng.random() < 0.45 else 0.0

            row = _clip_and_recompute_derived_features(
                row,
                feature_names,
                gain_idx,
                log_gain_idx,
                vcc_idx,
                frequency_log_idx,
            )
            row = _enforce_structural_feature_values(
                row,
                feature_names,
                y_top_source[src_idx],
                y_block_source[src_idx],
            )

            row_list = row.tolist()
            x_aug.append(row_list)
            y_top_aug.append(y_top_source[src_idx])
            y_block_aug.append(y_block_source[src_idx])
            template_aug.append(template_id)
            added_rows.append(row_list)
            added_by_template[template_id] += 1

    added_indices = list(range(len(x_aug) - len(added_rows), len(x_aug))) if added_rows else []
    added_stats = {
        "added_high_cmr_true_ratio": _ratio_true(x_aug, idx_high_cmr, added_indices),
        "added_extra_high_cmrr_true_ratio": _ratio_true(x_aug, idx_extra_high_cmrr, added_indices),
        "added_output_buffer_true_ratio": _ratio_true(x_aug, idx_output_buffer, added_indices),
    }

    print("Targeted augmentation pre-stats:")
    print(f"  differential high_cmr=True ratio: {pre_stats['differential_high_cmr_true_ratio']:.4f}")
    print(f"  differential extra_req__high_cmrr=True ratio: {pre_stats['differential_extra_high_cmrr_true_ratio']:.4f}")
    print(f"  target high_cmr=True ratio: {pre_stats['target_high_cmr_true_ratio']:.4f}")
    print(f"  target extra_req__high_cmrr=True ratio: {pre_stats['target_extra_high_cmrr_true_ratio']:.4f}")
    print("Targeted augmentation added-sample stats:")
    print(f"  added high_cmr=True ratio: {added_stats['added_high_cmr_true_ratio']:.4f}")
    print(f"  added extra_req__high_cmrr=True ratio: {added_stats['added_extra_high_cmrr_true_ratio']:.4f}")
    print(f"  added output_buffer=True ratio: {added_stats['added_output_buffer_true_ratio']:.4f}")

    return {
        "target_template_ids": target_templates,
        "target_samples_per_template": int(target_samples_per_template),
        "targeted_samples_added": int(sum(added_by_template.values())),
        "targeted_added_by_template": added_by_template,
        "mi_top_features": mi_ranking[:12],
        "pre_stats": pre_stats,
        "added_stats": added_stats,
    }


def augment_dataset(
    model_dir: Path,
    input_path: Path | None,
    output_path: Path,
    noise_std: float,
    edge_case_count: int,
    random_seed: int,
    targeted_only: bool,
    upgrade_structural_features_only: bool,
    target_template_ids: Sequence[str],
    target_samples_per_template: int,
    target_noise_std: float,
) -> Dict[str, Any]:
    np.random.seed(random_seed)

    source_path = _resolve_input_dataset(model_dir, input_path)
    x, y_topology, y_block, template_ids, feature_names, extra_keys = _load_dataset(source_path)

    x, feature_names, structural_schema_upgraded = _upgrade_feature_matrix_with_structural_columns(
        x=x,
        y_topology=y_topology,
        y_block=y_block,
        feature_names=feature_names,
        extra_keys=extra_keys,
    )

    template_ids = [str(v).strip() for v in template_ids]
    if len(template_ids) != len(x) or any(not tid for tid in template_ids):
        raise ValueError("GroupKFold requires template_id column — add it to training data pipeline.")

    if upgrade_structural_features_only:
        _save_dataset(
            output_path,
            x=x,
            y_topology=y_topology,
            y_block=y_block,
            template_ids=template_ids,
            feature_names=feature_names,
            extra_keys=extra_keys,
        )

        summary = {
            "source_dataset": str(source_path),
            "output_dataset": str(output_path),
            "upgrade_structural_features_only": True,
            "structural_schema_upgraded": bool(structural_schema_upgraded),
            "feature_count": int(len(feature_names)),
            "sample_count": int(len(x)),
            "template_count": int(len(set(template_ids))),
        }
        print(f"Loaded dataset: {source_path}")
        print(f"Structural schema upgraded: {structural_schema_upgraded}")
        print(f"Feature count: {len(feature_names)}")
        print(f"Sample count preserved: {len(x)}")
        print(f"Saved upgraded dataset: {output_path}")
        return summary

    original_count = len(x)
    x, y_topology, y_block, template_ids, duplicate_count = _drop_duplicates(
        x,
        y_topology,
        y_block,
        template_ids,
    )
    dedup_count = len(x)

    topology_counts = Counter(y_topology)
    minority_threshold = 0.1 * len(y_topology)
    minority_classes = {
        cls_name for cls_name, count in topology_counts.items() if count < minority_threshold
    }

    gain_idx = feature_names.index("gain") if "gain" in feature_names else -1
    log_gain_idx = feature_names.index("log_gain") if "log_gain" in feature_names else -1
    vcc_idx = feature_names.index("vcc") if "vcc" in feature_names else -1
    frequency_log_idx = feature_names.index("frequency_log") if "frequency_log" in feature_names else -1

    x_aug = [list(row) for row in x]
    y_top_aug = list(y_topology)
    y_block_aug = list(y_block)
    template_aug = list(template_ids)

    noisy_added = 0
    edge_added = 0
    if not targeted_only:
        for row, top, block, template_id in zip(x, y_topology, y_block, template_ids):
            if top not in minority_classes:
                continue

            noisy_row = np.asarray(row, dtype=np.float64)
            noisy_row = noisy_row + np.random.normal(0.0, noise_std, size=noisy_row.shape)
            noisy_row = _clip_and_recompute_derived_features(
                noisy_row,
                feature_names,
                gain_idx,
                log_gain_idx,
                vcc_idx,
                frequency_log_idx,
            )
            noisy_row = _enforce_structural_feature_values(
                noisy_row,
                feature_names,
                top,
                block,
            )

            x_aug.append(noisy_row.tolist())
            y_top_aug.append(top)
            y_block_aug.append(block)
            template_aug.append(template_id)
            noisy_added += 1

        class_to_indices: Dict[str, List[int]] = {}
        class_to_primary_block: Dict[str, str] = {}
        for idx, top in enumerate(y_topology):
            class_to_indices.setdefault(top, []).append(idx)

        for cls_name, indices in class_to_indices.items():
            block_counter = Counter(y_block[idx] for idx in indices)
            class_to_primary_block[cls_name] = block_counter.most_common(1)[0][0]

        classes = sorted(class_to_indices.keys())
        per_class_target = int(math.ceil(edge_case_count / max(len(classes), 1)))

        for cls_name in classes:
            indices = class_to_indices[cls_name]
            if not indices:
                continue

            for i in range(per_class_target):
                src_idx = indices[i % len(indices)]
                new_row = np.asarray(x[src_idx], dtype=np.float64)

                if gain_idx >= 0:
                    new_row[gain_idx] = float(new_row[gain_idx]) * np.random.uniform(0.8, 1.2)
                if vcc_idx >= 0:
                    new_row[vcc_idx] = float(new_row[vcc_idx]) * np.random.uniform(0.85, 1.15)
                if frequency_log_idx >= 0:
                    base_freq = 10.0 ** float(new_row[frequency_log_idx])
                    varied_freq = max(1.0, base_freq * np.random.uniform(0.7, 1.3))
                    new_row[frequency_log_idx] = math.log10(varied_freq)

                new_row = _clip_and_recompute_derived_features(
                    new_row,
                    feature_names,
                    gain_idx,
                    log_gain_idx,
                    vcc_idx,
                    frequency_log_idx,
                )
                new_row = _enforce_structural_feature_values(
                    new_row,
                    feature_names,
                    cls_name,
                    class_to_primary_block[cls_name],
                )

                x_aug.append(new_row.tolist())
                y_top_aug.append(cls_name)
                y_block_aug.append(class_to_primary_block[cls_name])
                template_aug.append(template_ids[src_idx])
                edge_added += 1

        if edge_added < edge_case_count:
            deficit = edge_case_count - edge_added
            for i in range(deficit):
                cls_name = classes[i % len(classes)]
                src_idx = class_to_indices[cls_name][0]
                row = np.asarray(x[src_idx], dtype=np.float64)
                row = row + np.random.normal(0.0, noise_std, size=row.shape)
                row = _clip_and_recompute_derived_features(
                    row,
                    feature_names,
                    gain_idx,
                    log_gain_idx,
                    vcc_idx,
                    frequency_log_idx,
                )
                row = _enforce_structural_feature_values(
                    row,
                    feature_names,
                    cls_name,
                    class_to_primary_block[cls_name],
                )
                x_aug.append(row.tolist())
                y_top_aug.append(cls_name)
                y_block_aug.append(class_to_primary_block[cls_name])
                template_aug.append(template_ids[src_idx])
                edge_added += 1

    targeted_summary = _apply_targeted_op_template_augmentation(
        x_source=x,
        y_top_source=y_topology,
        y_block_source=y_block,
        template_source=template_ids,
        feature_names=feature_names,
        x_aug=x_aug,
        y_top_aug=y_top_aug,
        y_block_aug=y_block_aug,
        template_aug=template_aug,
        target_template_ids=target_template_ids,
        target_samples_per_template=target_samples_per_template,
        random_seed=random_seed,
        target_noise_std=target_noise_std,
        gain_idx=gain_idx,
        log_gain_idx=log_gain_idx,
        vcc_idx=vcc_idx,
        frequency_log_idx=frequency_log_idx,
    )

    _save_dataset(
        output_path,
        x=x_aug,
        y_topology=y_top_aug,
        y_block=y_block_aug,
        template_ids=template_aug,
        feature_names=feature_names,
        extra_keys=extra_keys,
    )

    new_distribution = dict(Counter(y_top_aug))

    print(f"Loaded dataset: {source_path}")
    print(f"Structural schema upgraded: {structural_schema_upgraded}")
    print(f"Original samples: {original_count}")
    print(f"Duplicate rows found: {duplicate_count}")
    print(f"Samples after dedup: {dedup_count}")
    print(f"Minority classes (<10%): {sorted(minority_classes)}")
    print(f"Noisy samples added: {noisy_added}")
    print(f"Edge-case samples added: {edge_added}")
    print(f"Targeted OP samples added: {targeted_summary['targeted_samples_added']}")
    print(f"Targeted OP added by template: {targeted_summary['targeted_added_by_template']}")
    print(f"Unique template IDs: {len(set(template_aug))}")
    print(f"Saved augmented dataset: {output_path}")
    print("New class distribution:")
    for cls_name in sorted(new_distribution.keys()):
        print(f"  {cls_name}: {new_distribution[cls_name]}")

    return {
        "source_dataset": str(source_path),
        "output_dataset": str(output_path),
        "structural_schema_upgraded": bool(structural_schema_upgraded),
        "original_samples": original_count,
        "duplicates_removed": duplicate_count,
        "samples_after_dedup": dedup_count,
        "noisy_samples_added": noisy_added,
        "edge_case_samples_added": edge_added,
        "targeted_samples_added": targeted_summary["targeted_samples_added"],
        "targeted_added_by_template": targeted_summary["targeted_added_by_template"],
        "targeted_target_template_ids": targeted_summary["target_template_ids"],
        "targeted_samples_per_template": targeted_summary["target_samples_per_template"],
        "targeted_pre_stats": targeted_summary.get("pre_stats", {}),
        "targeted_added_stats": targeted_summary.get("added_stats", {}),
        "targeted_mi_top_features": targeted_summary.get("mi_top_features", []),
        "final_samples": len(x_aug),
        "template_count": len(set(template_aug)),
        "class_distribution": new_distribution,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Augment Random Forest training dataset")
    parser.add_argument("--model-dir", type=Path, default=_default_model_dir())
    parser.add_argument("--input-path", type=Path, default=None)
    parser.add_argument("--output-path", type=Path, default=None)
    parser.add_argument("--noise-std", type=float, default=0.05)
    parser.add_argument("--edge-case-count", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--targeted-only", action="store_true")
    parser.add_argument("--upgrade-structural-features-only", action="store_true")
    parser.add_argument("--target-template-ids", type=str, default="OP-10,OP-11")
    parser.add_argument("--target-samples-per-template", type=int, default=150)
    parser.add_argument("--target-noise-std", type=float, default=0.02)
    args = parser.parse_args()

    default_output_name = "training_data_v4.pkl"
    output_path = args.output_path or (args.model_dir / default_output_name)
    target_template_ids = [
        token.strip() for token in str(args.target_template_ids).split(",") if token.strip()
    ]

    summary = augment_dataset(
        model_dir=args.model_dir,
        input_path=args.input_path,
        output_path=output_path,
        noise_std=args.noise_std,
        edge_case_count=args.edge_case_count,
        random_seed=args.seed,
        targeted_only=args.targeted_only,
        upgrade_structural_features_only=args.upgrade_structural_features_only,
        target_template_ids=target_template_ids,
        target_samples_per_template=args.target_samples_per_template,
        target_noise_std=args.target_noise_std,
    )
    print(summary)


if __name__ == "__main__":
    main()
