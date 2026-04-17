from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from sklearn.feature_selection import mutual_info_classif


def _api_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_model_dir() -> Path:
    return _api_root() / "resources" / "ml_models"


def _resolve_dataset_path(model_dir: Path, dataset_path: Optional[Path]) -> Path:
    if dataset_path is not None:
        return dataset_path

    v4_path = model_dir / "training_data_v4.pkl"

    if v4_path.exists():
        return v4_path

    raise RuntimeError("No training dataset found. Expected training_data_v4.pkl.")


def _load_dataset(path: Path) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[str]]:
    with open(path, "rb") as f:
        payload = pickle.load(f)

    required_keys = {"x", "y_topology_raw", "y_block_raw", "feature_names"}
    missing = sorted(required_keys - set(payload.keys()))
    if missing:
        raise RuntimeError(f"Dataset file {path} missing keys: {missing}")

    x = np.asarray(payload["x"], dtype=np.float64)
    y_topology = np.asarray([str(v) for v in payload["y_topology_raw"]], dtype=object)
    y_block = np.asarray([str(v) for v in payload["y_block_raw"]], dtype=object)
    feature_names = [str(v) for v in payload["feature_names"]]

    if x.ndim != 2:
        raise RuntimeError(f"Expected 2D feature matrix, got shape={x.shape}")
    if len(feature_names) != x.shape[1]:
        raise RuntimeError(
            f"Feature name count mismatch: len(feature_names)={len(feature_names)} != x.shape[1]={x.shape[1]}"
        )

    return x, y_topology, y_block, feature_names


def _encode_labels(labels: Sequence[str]) -> np.ndarray:
    classes = sorted(set(str(v) for v in labels))
    index = {label: idx for idx, label in enumerate(classes)}
    return np.asarray([index[str(v)] for v in labels], dtype=np.int64)


def _rank_data(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    sorted_values = values[order]
    ranks_sorted = np.zeros_like(sorted_values, dtype=np.float64)

    start = 0
    n = len(sorted_values)
    while start < n:
        end = start + 1
        while end < n and sorted_values[end] == sorted_values[start]:
            end += 1

        # Average rank for ties using 1-based rank scale.
        avg_rank = 0.5 * (start + 1 + end)
        ranks_sorted[start:end] = avg_rank
        start = end

    ranks = np.empty_like(ranks_sorted)
    ranks[order] = ranks_sorted
    return ranks


def _safe_spearman(feature: np.ndarray, target: np.ndarray) -> float:
    if feature.size == 0 or target.size == 0:
        return 0.0
    if np.all(feature == feature[0]) or np.all(target == target[0]):
        return 0.0

    feature_rank = _rank_data(feature.astype(np.float64, copy=False))
    target_rank = _rank_data(target.astype(np.float64, copy=False))

    feature_std = float(np.std(feature_rank))
    target_std = float(np.std(target_rank))
    if feature_std <= 0.0 or target_std <= 0.0:
        return 0.0

    corr = float(np.corrcoef(feature_rank, target_rank)[0, 1])
    if np.isnan(corr):
        return 0.0
    return corr


def _build_recommendations(suspects: Sequence[Dict[str, Any]], top_k: int = 5) -> List[str]:
    if not suspects:
        return [
            "No feature crossed the configured leakage thresholds.",
            "Keep monitoring leakage report over new dataset versions.",
        ]

    top_features = ", ".join(item["feature"] for item in suspects[:top_k])
    return [
        "Investigate suspect features first: " + top_features,
        "Run ablation experiments by dropping one suspect feature at a time and compare GroupKFold weighted F1.",
        "Re-engineer or bucketize near-unique continuous features that behave like sample/template identifiers.",
    ]


def analyze_feature_leakage(
    model_dir: Path,
    dataset_path: Optional[Path],
    output_path: Path,
    mi_threshold: float,
    uniqueness_threshold: float,
    spearman_threshold: float,
    top_k_console: int,
) -> Dict[str, Any]:
    resolved_dataset_path = _resolve_dataset_path(model_dir, dataset_path)
    x, y_topology, y_block, feature_names = _load_dataset(resolved_dataset_path)

    y_topology_encoded = _encode_labels(y_topology)
    y_block_encoded = _encode_labels(y_block)

    mi_topology = mutual_info_classif(x, y_topology_encoded, random_state=42)
    mi_block = mutual_info_classif(x, y_block_encoded, random_state=42)

    sample_count = int(x.shape[0])
    result_rows: List[Dict[str, Any]] = []

    for idx, feature_name in enumerate(feature_names):
        column = x[:, idx]
        uniqueness_ratio = float(len(np.unique(column)) / max(sample_count, 1))
        spearman_topology = _safe_spearman(column, y_topology_encoded)
        spearman_block = _safe_spearman(column, y_block_encoded)

        mi_top = float(mi_topology[idx])
        mi_blk = float(mi_block[idx])
        max_mi = max(mi_top, mi_blk)
        max_abs_spearman = max(abs(spearman_topology), abs(spearman_block))

        reasons: List[str] = []
        if uniqueness_ratio >= uniqueness_threshold and max_mi >= mi_threshold:
            reasons.append("high_mutual_information_with_near_unique_values")
        if max_abs_spearman >= spearman_threshold:
            reasons.append("high_spearman_correlation_with_label")

        suspect = len(reasons) > 0
        suspicion_score = max(max_mi, max_abs_spearman, uniqueness_ratio if suspect else 0.0)

        result_rows.append(
            {
                "feature": feature_name,
                "mi_topology": mi_top,
                "mi_block": mi_blk,
                "uniqueness_ratio": uniqueness_ratio,
                "spearman_topology": float(spearman_topology),
                "spearman_block": float(spearman_block),
                "max_mi": max_mi,
                "max_abs_spearman": max_abs_spearman,
                "suspect": suspect,
                "suspect_reasons": reasons,
                "suspicion_score": suspicion_score,
            }
        )

    result_rows.sort(
        key=lambda item: (
            int(bool(item["suspect"])),
            float(item["suspicion_score"]),
            float(item["max_mi"]),
            float(item["max_abs_spearman"]),
        ),
        reverse=True,
    )

    suspects = [item for item in result_rows if item["suspect"]]

    print("=== Feature leakage ranking ===")
    print(
        "{:<4} {:<40} {:>9} {:>9} {:>9} {:>9} {:>9} {:>8}".format(
            "Rank",
            "Feature",
            "MI_top",
            "MI_blk",
            "Unique",
            "Sp_top",
            "Sp_blk",
            "Flag",
        )
    )
    for idx, item in enumerate(result_rows[:top_k_console], start=1):
        print(
            "{:<4} {:<40} {:>9.4f} {:>9.4f} {:>9.4f} {:>9.4f} {:>9.4f} {:>8}".format(
                idx,
                item["feature"][:40],
                float(item["mi_topology"]),
                float(item["mi_block"]),
                float(item["uniqueness_ratio"]),
                float(item["spearman_topology"]),
                float(item["spearman_block"]),
                "SUSPECT" if bool(item["suspect"]) else "OK",
            )
        )

    recommendations = _build_recommendations(suspects)
    report: Dict[str, Any] = {
        "dataset_path": str(resolved_dataset_path),
        "sample_count": sample_count,
        "feature_count": int(x.shape[1]),
        "thresholds": {
            "mi_threshold": float(mi_threshold),
            "uniqueness_threshold": float(uniqueness_threshold),
            "spearman_threshold": float(spearman_threshold),
        },
        "suspect_feature_count": int(len(suspects)),
        "suspect_features": suspects,
        "ranked_features": result_rows,
        "recommendations": recommendations,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"Saved leakage report: {output_path}")
    print(f"Suspect features: {len(suspects)} / {x.shape[1]}")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze potential feature leakage in RF training data")
    parser.add_argument("--model-dir", type=Path, default=_default_model_dir())
    parser.add_argument("--dataset-path", type=Path, default=None)
    parser.add_argument("--output-path", type=Path, default=None)
    parser.add_argument("--mi-threshold", type=float, default=0.5)
    parser.add_argument("--uniqueness-threshold", type=float, default=0.95)
    parser.add_argument("--spearman-threshold", type=float, default=0.9)
    parser.add_argument("--top-k-console", type=int, default=30)
    args = parser.parse_args()

    output_path = args.output_path or (args.model_dir / "rf_leakage_report.json")

    report = analyze_feature_leakage(
        model_dir=args.model_dir,
        dataset_path=args.dataset_path,
        output_path=output_path,
        mi_threshold=args.mi_threshold,
        uniqueness_threshold=args.uniqueness_threshold,
        spearman_threshold=args.spearman_threshold,
        top_k_console=args.top_k_console,
    )

    print("=== Leakage analysis completed ===")
    print(
        json.dumps(
            {
                "dataset_path": report["dataset_path"],
                "feature_count": report["feature_count"],
                "suspect_feature_count": report["suspect_feature_count"],
                "output_path": str(output_path),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
