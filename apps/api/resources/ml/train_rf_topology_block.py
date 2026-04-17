# .\thesis\electronic-chatbot\apps\api\resources\ml\train_rf_topology_block.py
"""Train Random Forest models for topology and primary block prediction.

Inputs:
- resources/templates_metadata/*.meta.json
- resources/ml_models/training_data_v4.pkl (optional canonical augmented dataset)

Outputs:
- resources/ml_models/rf_topology_model.joblib
- resources/ml_models/rf_block_model.joblib
- resources/ml_models/rf_feature_schema.json
- resources/ml_models/rf_training_report.json
- resources/ml_models/rf_diagnostic_report.json
- resources/ml_models/rf_best_params.json
- resources/ml_models/rf_feature_importance.json
- resources/ml_models/rf_evaluation_report.json
- resources/result_train_score_matplotlib/train_vs_cv_score.png
"""


from __future__ import annotations

import argparse
import json
import pickle
import random
import shutil
import sys
import joblib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import (
    GroupKFold,
    RandomizedSearchCV,
    cross_val_predict,
    cross_val_score,
    train_test_split,
)

try:
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover - optional runtime dependency
    plt = None

# Ensure `app` package is importable when script is executed by file path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.domains.circuits.ai_core.ml_topology_selector import (
    RandomForestTopologySelector,
    _normalize_token,
)


def _api_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_metadata_dir() -> Path:
    return _api_root() / "resources" / "templates_metadata"


def _default_model_dir() -> Path:
    return _api_root() / "resources" / "ml_models"


def _default_plot_dir() -> Path:
    return _api_root() / "resources" / "result_train_score_matplotlib"


def _load_metadata(metadata_dir: Path) -> List[Dict[str, Any]]:
    metadata: List[Dict[str, Any]] = []
    for path in metadata_dir.glob("*.meta.json"):
        if path.name.startswith("_"):
            continue
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "template_id" not in data:
            continue
        metadata.append(data)
    return metadata


def _gain_range_for_family(family: str) -> Tuple[float, float]:
    ranges = {
        "common_emitter": (10, 300),
        "common_base": (10, 250),
        "common_collector": (0.8, 1.2),
        "common_source": (8, 220),
        "common_drain": (0.7, 1.2),
        "common_gate": (6, 160),
        "inverting": (2, 300),
        "non_inverting": (1, 300),
        "differential": (2, 120),
        "instrumentation": (5, 1200),
        "class_a": (2, 30),
        "class_b": (0.8, 5),
        "class_ab": (0.8, 8),
        "class_c": (4, 80),
        "class_d": (0.8, 8),
        "darlington": (2, 60),
        "multi_stage": (30, 1000),
    }
    return ranges.get(family, (1, 80))


def _frequency_for_family(family: str) -> float:
    if family in {"class_c", "common_base", "common_gate"}:
        return random.uniform(100e3, 10e6)
    if family in {"class_d"}:
        return random.uniform(20e3, 500e3)
    if family in {"instrumentation", "differential"}:
        return random.uniform(10, 50e3)
    return random.uniform(20, 500e3)


def _supply_mode_from_tags(tags: Sequence[str]) -> str:
    tag_set = set(tags)
    if "single_supply" in tag_set:
        return "single_supply"
    if "dual_supply" in tag_set:
        return "dual_supply"
    return "auto"


def _device_pref_from_category(category: str) -> str:
    if category == "bjt":
        return "bjt"
    if category == "mosfet":
        return "mosfet"
    if category == "opamp":
        return "opamp"
    return "auto"


def _build_training_rows(
    metadata: List[Dict[str, Any]],
    samples_per_template: int,
) -> Tuple[List[Dict[str, Any]], List[str], List[str], List[str], List[str]]:
    rows: List[Dict[str, Any]] = []
    y_topology: List[str] = []
    y_block: List[str] = []
    template_ids: List[str] = []

    extra_requirement_tokens: set[str] = set()

    for meta in metadata:
        template_id = str(meta.get("template_id", "")).strip()
        if not template_id:
            continue

        domain = meta.get("domain", {})
        hints = meta.get("planner_hints", {})
        fstruct = meta.get("functional_structure", {})

        family = str(domain.get("family", "unknown"))
        category = str(domain.get("category", ""))
        tags = [str(t) for t in domain.get("topology_tags", [])]

        block_list = [
            str(block.get("type", ""))
            for block in fstruct.get("blocks", [])
            if isinstance(block, dict)
        ]
        if not block_list:
            continue

        primary_block = block_list[0]

        capabilities = [str(c) for c in hints.get("required_capabilities", [])]
        for cap in capabilities:
            extra_requirement_tokens.add(_normalize_token(cap))

        for _ in range(samples_per_template):
            gmin, gmax = _gain_range_for_family(family)
            gain = random.uniform(gmin, gmax)
            vcc = random.uniform(5.0, 24.0)
            frequency = _frequency_for_family(family)

            high_cmr = family in {"instrumentation", "differential"}
            input_mode = "differential" if family in {"instrumentation", "differential"} else "single_ended"
            output_buffer = any(b in {"cc_block", "cd_block"} for b in block_list)
            power_output = family.startswith("class_")

            supply_mode = _supply_mode_from_tags(tags)
            coupling = "capacitor" if "ac_coupled" in tags else "auto"
            device_pref = _device_pref_from_category(category)

            extra_req = list(capabilities)
            if output_buffer and random.random() < 0.4:
                extra_req.append("low_output_impedance")
            if high_cmr and random.random() < 0.6:
                extra_req.append("high_cmrr")

            fmap = RandomForestTopologySelector.build_feature_map(
                gain=gain,
                vcc=vcc,
                frequency=frequency,
                input_channels=2 if input_mode == "differential" else 1,
                high_cmr=high_cmr,
                input_mode=input_mode,
                output_buffer=output_buffer,
                power_output=power_output,
                supply_mode=supply_mode,
                coupling_preference=coupling,
                device_preference=device_pref,
                extra_requirements=extra_req,
                extra_requirement_keys=sorted(extra_requirement_tokens),
                circuit_family=family,
                primary_block=primary_block,
            )

            rows.append(fmap)
            y_topology.append(family)
            y_block.append(primary_block)
            template_ids.append(template_id)

    return rows, y_topology, y_block, template_ids, sorted(extra_requirement_tokens)


def _infer_input_mode_from_topology_label(topology_label: str) -> str:
    topology_token = _normalize_token(topology_label)
    if topology_token in {"differential", "instrumentation"}:
        return "differential"
    return "single_ended"


def _upgrade_feature_matrix_with_structural_columns(
    x: Sequence[Sequence[float]],
    y_topology_raw: Sequence[str],
    y_block_raw: Sequence[str],
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

    for row, top_label, block_label in zip(x, y_topology_raw, y_block_raw):
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


def _build_matrix(rows: List[Dict[str, Any]], feature_names: Sequence[str]) -> List[List[float]]:
    matrix: List[List[float]] = []
    for row in rows:
        matrix.append([float(row.get(name, 0.0)) for name in feature_names])
    return matrix


def _encode_labels(labels: Sequence[str]) -> Tuple[List[int], List[str]]:
    classes = sorted(set(labels))
    index = {label: idx for idx, label in enumerate(classes)}
    encoded = [index[label] for label in labels]
    return encoded, classes


def _save_dataset_pickle(
    path: Path,
    x: Sequence[Sequence[float]],
    y_topology_raw: Sequence[str],
    y_block_raw: Sequence[str],
    template_ids: Sequence[str],
    feature_names: Sequence[str],
    extra_keys: Sequence[str],
) -> None:
    payload = {
        "x": [list(map(float, row)) for row in x],
        "y_topology_raw": list(y_topology_raw),
        "y_block_raw": list(y_block_raw),
        "template_ids": list(template_ids),
        "feature_names": list(feature_names),
        "extra_requirement_keys": list(extra_keys),
    }
    with open(path, "wb") as f:
        pickle.dump(payload, f)


def _load_dataset_pickle(path: Path) -> Tuple[List[List[float]], List[str], List[str], List[str], List[str], List[str]]:
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

    raw_template_ids = payload.get("template_ids", [])
    template_ids = [str(v) for v in raw_template_ids] if raw_template_ids is not None else []

    return (
        [list(map(float, row)) for row in payload["x"]],
        [str(v) for v in payload["y_topology_raw"]],
        [str(v) for v in payload["y_block_raw"]],
        template_ids,
        [str(v) for v in payload["feature_names"]],
        [str(v) for v in payload["extra_requirement_keys"]],
    )


def _extract_per_class_f1(report: Dict[str, Any], classes: Sequence[str]) -> Dict[str, float]:
    per_class: Dict[str, float] = {}
    for cls_name in classes:
        entry = report.get(cls_name)
        if isinstance(entry, dict):
            per_class[cls_name] = float(entry.get("f1-score", 0.0))
    return per_class


def _per_class_accuracy(cm: np.ndarray, classes: Sequence[str]) -> Dict[str, float]:
    result: Dict[str, float] = {}
    for idx, cls_name in enumerate(classes):
        total = float(np.sum(cm[idx]))
        correct = float(cm[idx][idx])
        result[cls_name] = 0.0 if total <= 0.0 else correct / total
    return result


def _warn_low_recall(report: Dict[str, Any], classes: Sequence[str], label: str) -> None:
    for cls_name in classes:
        entry = report.get(cls_name)
        if not isinstance(entry, dict):
            continue
        recall = float(entry.get("recall", 0.0))
        if recall < 0.70:
            print(f"WARNING: [{label}] class '{cls_name}' has low recall={recall:.3f} (<0.70)")


def _rank_feature_importance(feature_names: Sequence[str], importances: Sequence[float]) -> List[Dict[str, Any]]:
    ranking = [
        {"feature": str(name), "importance": float(importance)}
        for name, importance in zip(feature_names, importances)
    ]
    ranking.sort(key=lambda item: item["importance"], reverse=True)
    return ranking


def _score_summary(scores: Sequence[float]) -> Dict[str, Any]:
    scores_array = np.asarray(scores, dtype=np.float64)
    return {
        "mean": float(np.mean(scores_array)),
        "std": float(np.std(scores_array)),
        "fold_scores": [float(v) for v in scores_array.tolist()],
    }


def _top_misclassified_template_ids(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    template_ids: np.ndarray,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    template_counts = Counter(str(tid) for tid in template_ids)
    wrong_counts = Counter(
        str(tid)
        for tid, y_true_item, y_pred_item in zip(template_ids, y_true, y_pred)
        if int(y_true_item) != int(y_pred_item)
    )

    ranked = wrong_counts.most_common(top_k)
    return [
        {
            "template_id": template_id,
            "misclassified_count": int(count),
            "samples_in_training_split": int(template_counts.get(template_id, 0)),
            "error_rate": (
                0.0
                if template_counts.get(template_id, 0) <= 0
                else float(count) / float(template_counts.get(template_id, 0))
            ),
        }
        for template_id, count in ranked
    ]


def _log_group_leakage_warning(
    label: str,
    standard_cv: Dict[str, Any],
    group_cv: Dict[str, Any],
    misclassified_templates: Sequence[Dict[str, Any]],
) -> bool:
    drop = float(standard_cv["mean"]) - float(group_cv["mean"])
    if drop <= 0.10:
        return False

    print(
        "WARNING: [{}] Potential template leakage detected. Standard CV F1={:.4f}, "
        "GroupKFold F1={:.4f}, drop={:.4f} (> 0.10)".format(
            label,
            float(standard_cv["mean"]),
            float(group_cv["mean"]),
            drop,
        )
    )
    print(f"Most frequent misclassified template_ids ({label}):")
    if not misclassified_templates:
        print("  (none)")
    for item in misclassified_templates:
        print(
            "  {template_id}: errors={misclassified_count}, samples={samples_in_training_split}, "
            "error_rate={error_rate:.3f}".format(**item)
        )
    return True


def _save_train_vs_cv_plot(diagnostic_report: Dict[str, Any], plot_dir: Path) -> Optional[Path]:
    if plt is None:
        print("WARNING: matplotlib is not available, skipping plot generation.")
        return None

    plot_dir.mkdir(parents=True, exist_ok=True)

    labels = ["Topology", "Block"]
    train_scores = [
        float(diagnostic_report["topology"]["train_accuracy"]),
        float(diagnostic_report["block"]["train_accuracy"]),
    ]
    cv_means = [
        float(diagnostic_report["topology"]["cv_f1_weighted_mean"]),
        float(diagnostic_report["block"]["cv_f1_weighted_mean"]),
    ]
    cv_stds = [
        float(diagnostic_report["topology"]["cv_f1_weighted_std"]),
        float(diagnostic_report["block"]["cv_f1_weighted_std"]),
    ]

    x_idx = np.arange(len(labels))
    width = 0.36

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(x_idx - width / 2, train_scores, width=width, label="Train Accuracy")
    ax.bar(x_idx + width / 2, cv_means, width=width, yerr=cv_stds, capsize=6, label="5-Fold GroupKFold F1")

    ax.set_xticks(x_idx)
    ax.set_xticklabels(labels)
    ax.set_ylim(0.0, 1.05)
    ax.set_ylabel("Score")
    ax.set_title("Train vs CV Score")
    ax.legend()
    ax.grid(axis="y", alpha=0.2)

    output_path = plot_dir / "rf_train_vs_cv_score.png"
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def _backup_existing_artifacts(model_dir: Path) -> None:
    backup_map = {
        "rf_topology_model.joblib": "rf_topology_model_legacy.joblib",
        "rf_block_model.joblib": "rf_block_model_legacy.joblib",
        "rf_feature_schema.json": "rf_feature_schema_legacy.json",
        "rf_evaluation_report.json": "rf_evaluation_report_legacy.json",
    }
    for source_name, backup_name in backup_map.items():
        source_path = model_dir / source_name
        backup_path = model_dir / backup_name
        if source_path.exists():
            shutil.copy2(source_path, backup_path)


def train(
    metadata_dir: Path,
    model_dir: Path,
    samples_per_template: int,
    random_seed: int,
    dataset_path: Optional[Path] = None,
) -> Dict[str, Any]:
    random.seed(random_seed)
    np.random.seed(random_seed)
    model_dir.mkdir(parents=True, exist_ok=True)
    _backup_existing_artifacts(model_dir)

    metadata = _load_metadata(metadata_dir)

    dataset_v4_path = model_dir / "training_data_v4.pkl"
    selected_dataset_path = dataset_path or (dataset_v4_path if dataset_v4_path.exists() else None)

    if selected_dataset_path is not None and selected_dataset_path.exists():
        x, y_topology_raw, y_block_raw, template_ids, feature_names, extra_keys = _load_dataset_pickle(selected_dataset_path)
        dataset_source = str(selected_dataset_path)
    else:
        if not metadata:
            raise RuntimeError(
                f"No metadata found in {metadata_dir} and no dataset file available for training"
            )

        rows, y_topology_raw, y_block_raw, template_ids, extra_keys = _build_training_rows(metadata, samples_per_template)
        feature_names = RandomForestTopologySelector.build_feature_names(extra_requirement_keys=extra_keys)
        x = _build_matrix(rows, feature_names)

        _save_dataset_pickle(
            dataset_v4_path,
            x=x,
            y_topology_raw=y_topology_raw,
            y_block_raw=y_block_raw,
            template_ids=template_ids,
            feature_names=feature_names,
            extra_keys=extra_keys,
        )
        dataset_source = str(dataset_v4_path)

    x, feature_names, feature_schema_upgraded = _upgrade_feature_matrix_with_structural_columns(
        x=x,
        y_topology_raw=y_topology_raw,
        y_block_raw=y_block_raw,
        feature_names=feature_names,
        extra_keys=extra_keys,
    )
    if feature_schema_upgraded:
        print(
            "Upgraded dataset feature schema with structural columns: "
            f"{len(feature_names)} features"
        )

    if not x:
        raise RuntimeError("Training dataset is empty")

    template_ids = [str(v).strip() for v in template_ids]
    if len(template_ids) != len(x) or any(not tid for tid in template_ids):
        raise ValueError("GroupKFold requires template_id column — add it to training data pipeline.")

    y_topology, topology_classes = _encode_labels(y_topology_raw)
    y_block, block_classes = _encode_labels(y_block_raw)

    x_array = np.asarray(x, dtype=np.float64)
    y_topology_array = np.asarray(y_topology, dtype=np.int64)
    y_block_array = np.asarray(y_block, dtype=np.int64)
    template_id_array = np.asarray(template_ids, dtype=object)

    indices = np.arange(len(x_array))
    train_indices, test_indices = train_test_split(
        indices,
        test_size=0.2,
        random_state=42,
        stratify=y_topology_array,
    )

    x_train = x_array[train_indices]
    x_test = x_array[test_indices]
    y_top_train = y_topology_array[train_indices]
    y_top_test = y_topology_array[test_indices]
    y_block_train = y_block_array[train_indices]
    y_block_test = y_block_array[test_indices]
    template_train = template_id_array[train_indices]

    if len(set(str(v) for v in template_train.tolist())) < 5:
        raise ValueError(
            "GroupKFold requires at least 5 unique template_id values in the training split."
        )

    baseline_rf_config = {
        "n_estimators": 200,
        "max_depth": 10,
        "class_weight": "balanced",
        "random_state": random_seed,
    }

    baseline_top_model = RandomForestClassifier(**baseline_rf_config)
    baseline_block_model = RandomForestClassifier(**baseline_rf_config)

    baseline_top_model.fit(x_train, y_top_train)
    baseline_block_model.fit(x_train, y_block_train)

    top_train_accuracy = float(accuracy_score(y_top_train, baseline_top_model.predict(x_train)))
    block_train_accuracy = float(accuracy_score(y_block_train, baseline_block_model.predict(x_train)))

    top_cv_standard_scores = cross_val_score(
        RandomForestClassifier(**baseline_rf_config),
        x_train,
        y_top_train,
        cv=5,
        scoring="f1_weighted",
        n_jobs=-1,
    )
    block_cv_standard_scores = cross_val_score(
        RandomForestClassifier(**baseline_rf_config),
        x_train,
        y_block_train,
        cv=5,
        scoring="f1_weighted",
        n_jobs=-1,
    )

    top_cv_group_scores = cross_val_score(
        RandomForestClassifier(**baseline_rf_config),
        x_train,
        y_top_train,
        cv=GroupKFold(n_splits=5),
        groups=template_train,
        scoring="f1_weighted",
        n_jobs=-1,
    )
    block_cv_group_scores = cross_val_score(
        RandomForestClassifier(**baseline_rf_config),
        x_train,
        y_block_train,
        cv=GroupKFold(n_splits=5),
        groups=template_train,
        scoring="f1_weighted",
        n_jobs=-1,
    )

    top_cv_standard = _score_summary(top_cv_standard_scores)
    top_cv_group = _score_summary(top_cv_group_scores)
    block_cv_standard = _score_summary(block_cv_standard_scores)
    block_cv_group = _score_summary(block_cv_group_scores)

    top_group_predictions = cross_val_predict(
        RandomForestClassifier(**baseline_rf_config),
        x_train,
        y_top_train,
        cv=GroupKFold(n_splits=5),
        groups=template_train,
        n_jobs=-1,
    )
    block_group_predictions = cross_val_predict(
        RandomForestClassifier(**baseline_rf_config),
        x_train,
        y_block_train,
        cv=GroupKFold(n_splits=5),
        groups=template_train,
        n_jobs=-1,
    )

    top_misclassified_templates = _top_misclassified_template_ids(
        y_true=y_top_train,
        y_pred=top_group_predictions,
        template_ids=template_train,
    )
    block_misclassified_templates = _top_misclassified_template_ids(
        y_true=y_block_train,
        y_pred=block_group_predictions,
        template_ids=template_train,
    )

    top_group_warning = _log_group_leakage_warning(
        label="topology",
        standard_cv=top_cv_standard,
        group_cv=top_cv_group,
        misclassified_templates=top_misclassified_templates,
    )
    block_group_warning = _log_group_leakage_warning(
        label="block",
        standard_cv=block_cv_standard,
        group_cv=block_cv_group,
        misclassified_templates=block_misclassified_templates,
    )

    top_diag_pred = baseline_top_model.predict(x_test)
    block_diag_pred = baseline_block_model.predict(x_test)

    top_diag_report = classification_report(
        y_top_test,
        top_diag_pred,
        labels=list(range(len(topology_classes))),
        target_names=topology_classes,
        output_dict=True,
        zero_division=0,
    )
    block_diag_report = classification_report(
        y_block_test,
        block_diag_pred,
        labels=list(range(len(block_classes))),
        target_names=block_classes,
        output_dict=True,
        zero_division=0,
    )

    diagnostic_report = {
        "dataset_source": dataset_source,
        "topology": {
            "train_accuracy": top_train_accuracy,
            "cv_standard_f1": top_cv_standard,
            "cv_group_f1": top_cv_group,
            "cv_f1_weighted_mean": float(top_cv_group["mean"]),
            "cv_f1_weighted_std": float(top_cv_group["std"]),
            "group_leakage_warning": top_group_warning,
            "misclassified_template_ids": top_misclassified_templates,
            "per_class_f1": _extract_per_class_f1(top_diag_report, topology_classes),
            "classification_report": top_diag_report,
        },
        "block": {
            "train_accuracy": block_train_accuracy,
            "cv_standard_f1": block_cv_standard,
            "cv_group_f1": block_cv_group,
            "cv_f1_weighted_mean": float(block_cv_group["mean"]),
            "cv_f1_weighted_std": float(block_cv_group["std"]),
            "group_leakage_warning": block_group_warning,
            "misclassified_template_ids": block_misclassified_templates,
            "per_class_f1": _extract_per_class_f1(block_diag_report, block_classes),
            "classification_report": block_diag_report,
        },
    }

    print("=== Overfitting and leakage diagnostic ===")
    print(
        "Topology  | train_acc={:.4f} | std_cv_f1={:.4f} +- {:.4f} | group_cv_f1={:.4f} +- {:.4f}".format(
            diagnostic_report["topology"]["train_accuracy"],
            diagnostic_report["topology"]["cv_standard_f1"]["mean"],
            diagnostic_report["topology"]["cv_standard_f1"]["std"],
            diagnostic_report["topology"]["cv_group_f1"]["mean"],
            diagnostic_report["topology"]["cv_group_f1"]["std"],
        )
    )
    print(
        "Block     | train_acc={:.4f} | std_cv_f1={:.4f} +- {:.4f} | group_cv_f1={:.4f} +- {:.4f}".format(
            diagnostic_report["block"]["train_accuracy"],
            diagnostic_report["block"]["cv_standard_f1"]["mean"],
            diagnostic_report["block"]["cv_standard_f1"]["std"],
            diagnostic_report["block"]["cv_group_f1"]["mean"],
            diagnostic_report["block"]["cv_group_f1"]["std"],
        )
    )
    print("Topology per-class F1 (diagnostic):")
    for class_name, f1_value in diagnostic_report["topology"]["per_class_f1"].items():
        print(f"  {class_name}: {f1_value:.4f}")
    print("Block per-class F1 (diagnostic):")
    for class_name, f1_value in diagnostic_report["block"]["per_class_f1"].items():
        print(f"  {class_name}: {f1_value:.4f}")

    with open(model_dir / "rf_diagnostic_report.json", "w", encoding="utf-8") as f:
        json.dump(diagnostic_report, f, indent=2, ensure_ascii=False)

    param_grid = {
        "n_estimators": [100, 200, 300, 500],
        "max_depth": [5, 8, 12, 15, None],
        "min_samples_split": [5, 10, 20],
        "min_samples_leaf": [2, 5, 10],
        "max_features": ["sqrt", "log2", 0.5],
        "class_weight": ["balanced", "balanced_subsample"],
    }

    top_search = RandomizedSearchCV(
        estimator=RandomForestClassifier(random_state=random_seed),
        param_distributions=param_grid,
        n_iter=30,
        cv=GroupKFold(n_splits=5),
        scoring="f1_weighted",
        n_jobs=-1,
        random_state=42,
    )
    block_search = RandomizedSearchCV(
        estimator=RandomForestClassifier(random_state=random_seed),
        param_distributions=param_grid,
        n_iter=30,
        cv=GroupKFold(n_splits=5),
        scoring="f1_weighted",
        n_jobs=-1,
        random_state=42,
    )

    top_search.fit(x_train, y_top_train, groups=template_train)
    block_search.fit(x_train, y_block_train, groups=template_train)

    top_model_full = top_search.best_estimator_
    block_model_full = block_search.best_estimator_

    best_params_report = {
        "topology_best_params": top_search.best_params_,
        "topology_best_cv_f1_weighted": float(top_search.best_score_),
        "block_best_params": block_search.best_params_,
        "block_best_cv_f1_weighted": float(block_search.best_score_),
    }

    print("=== RandomizedSearchCV best params ===")
    print(json.dumps(best_params_report, indent=2, ensure_ascii=False))

    with open(model_dir / "rf_best_params.json", "w", encoding="utf-8") as f:
        json.dump(best_params_report, f, indent=2, ensure_ascii=False)

    top_full_pred = top_model_full.predict(x_test)
    block_full_pred = block_model_full.predict(x_test)
    top_full_weighted_f1 = float(f1_score(y_top_test, top_full_pred, average="weighted"))
    block_full_weighted_f1 = float(f1_score(y_block_test, block_full_pred, average="weighted"))

    top_importances = top_model_full.feature_importances_
    block_importances = block_model_full.feature_importances_

    top_importance_ranking = _rank_feature_importance(feature_names, top_importances)
    block_importance_ranking = _rank_feature_importance(feature_names, block_importances)

    print("=== Top-20 feature importance (topology model) ===")
    for item in top_importance_ranking[:20]:
        print(f"{item['feature']}: {item['importance']:.6f}")

    print("=== Top-20 feature importance (block model) ===")
    for item in block_importance_ranking[:20]:
        print(f"{item['feature']}: {item['importance']:.6f}")

    if top_importance_ranking and top_importance_ranking[0]["importance"] > 0.4:
        print(
            "WARNING: Topology model has a feature importance > 0.4 "
            f"({top_importance_ranking[0]['feature']}={top_importance_ranking[0]['importance']:.4f})"
        )
    if block_importance_ranking and block_importance_ranking[0]["importance"] > 0.4:
        print(
            "WARNING: Block model has a feature importance > 0.4 "
            f"({block_importance_ranking[0]['feature']}={block_importance_ranking[0]['importance']:.4f})"
        )

    selected_feature_indices = [
        idx
        for idx, (top_imp, block_imp) in enumerate(zip(top_importances, block_importances))
        if float(top_imp) >= 0.005 or float(block_imp) >= 0.005
    ]
    if not selected_feature_indices:
        selected_feature_indices = list(range(len(feature_names)))

    selected_feature_names = [feature_names[idx] for idx in selected_feature_indices]

    x_train_reduced = x_train[:, selected_feature_indices]
    x_test_reduced = x_test[:, selected_feature_indices]

    top_model_reduced = RandomForestClassifier(**top_search.best_params_, random_state=random_seed)
    block_model_reduced = RandomForestClassifier(**block_search.best_params_, random_state=random_seed)

    top_model_reduced.fit(x_train_reduced, y_top_train)
    block_model_reduced.fit(x_train_reduced, y_block_train)

    top_reduced_pred = top_model_reduced.predict(x_test_reduced)
    block_reduced_pred = block_model_reduced.predict(x_test_reduced)

    top_reduced_weighted_f1 = float(f1_score(y_top_test, top_reduced_pred, average="weighted"))
    block_reduced_weighted_f1 = float(f1_score(y_block_test, block_reduced_pred, average="weighted"))

    print("=== Weighted F1 before/after feature reduction ===")
    print(
        "Topology: before={:.4f}, after={:.4f}".format(
            top_full_weighted_f1,
            top_reduced_weighted_f1,
        )
    )
    print(
        "Block: before={:.4f}, after={:.4f}".format(
            block_full_weighted_f1,
            block_reduced_weighted_f1,
        )
    )

    reduced_model_candidate_better = (
        (top_reduced_weighted_f1 + block_reduced_weighted_f1)
        >= (top_full_weighted_f1 + block_full_weighted_f1)
    )

    # Keep final persisted models as RandomizedSearchCV best estimators (task requirement).
    final_top_model = top_model_full
    final_block_model = block_model_full
    final_feature_names = feature_names
    x_test_for_eval = x_test

    feature_importance_report = {
        "topology_ranking": top_importance_ranking,
        "block_ranking": block_importance_ranking,
        "threshold": 0.005,
        "selected_feature_count": len(selected_feature_names),
        "selected_features": selected_feature_names,
        "weighted_f1_comparison": {
            "topology_before": top_full_weighted_f1,
            "topology_after": top_reduced_weighted_f1,
            "block_before": block_full_weighted_f1,
            "block_after": block_reduced_weighted_f1,
        },
        "reduced_model_candidate_better": reduced_model_candidate_better,
    }
    with open(model_dir / "rf_feature_importance.json", "w", encoding="utf-8") as f:
        json.dump(feature_importance_report, f, indent=2, ensure_ascii=False)

    top_pred = final_top_model.predict(x_test_for_eval)
    block_pred = final_block_model.predict(x_test_for_eval)

    top_acc = float(accuracy_score(y_top_test, top_pred))
    block_acc = float(accuracy_score(y_block_test, block_pred))

    top_report = classification_report(
        y_top_test,
        top_pred,
        labels=list(range(len(topology_classes))),
        target_names=topology_classes,
        output_dict=True,
        zero_division=0,
    )
    block_report = classification_report(
        y_block_test,
        block_pred,
        labels=list(range(len(block_classes))),
        target_names=block_classes,
        output_dict=True,
        zero_division=0,
    )

    top_cm = confusion_matrix(y_top_test, top_pred, labels=list(range(len(topology_classes))))
    block_cm = confusion_matrix(y_block_test, block_pred, labels=list(range(len(block_classes))))

    print("=== Classification report (topology) ===")
    print(
        classification_report(
            y_top_test,
            top_pred,
            labels=list(range(len(topology_classes))),
            target_names=topology_classes,
            zero_division=0,
        )
    )
    print("=== Classification report (block) ===")
    print(
        classification_report(
            y_block_test,
            block_pred,
            labels=list(range(len(block_classes))),
            target_names=block_classes,
            zero_division=0,
        )
    )

    top_macro_f1 = float(f1_score(y_top_test, top_pred, average="macro"))
    top_weighted_f1 = float(f1_score(y_top_test, top_pred, average="weighted"))
    block_macro_f1 = float(f1_score(y_block_test, block_pred, average="macro"))
    block_weighted_f1 = float(f1_score(y_block_test, block_pred, average="weighted"))

    top_group_weighted_f1 = float(diagnostic_report["topology"]["cv_group_f1"]["mean"])
    block_group_weighted_f1 = float(diagnostic_report["block"]["cv_group_f1"]["mean"])

    top_per_class_acc = _per_class_accuracy(top_cm, topology_classes)
    block_per_class_acc = _per_class_accuracy(block_cm, block_classes)

    print("=== Final held-out metrics ===")
    print(
        "Topology | macro_f1={:.4f}, weighted_f1={:.4f}".format(
            top_macro_f1,
            top_weighted_f1,
        )
    )
    print(
        "Block    | macro_f1={:.4f}, weighted_f1={:.4f}".format(
            block_macro_f1,
            block_weighted_f1,
        )
    )
    print("=== Canonical quality signal (GroupKFold weighted F1) ===")
    print("Topology | group_cv_weighted_f1={:.4f}".format(top_group_weighted_f1))
    print("Block    | group_cv_weighted_f1={:.4f}".format(block_group_weighted_f1))

    _warn_low_recall(top_report, topology_classes, "topology")
    _warn_low_recall(block_report, block_classes, "block")

    evaluation_report = {
        "topology": {
            "accuracy": top_acc,
            "macro_f1": top_macro_f1,
            "weighted_f1": top_group_weighted_f1,
            "weighted_f1_group_cv": top_group_weighted_f1,
            "weighted_f1_holdout": top_weighted_f1,
            "per_class_accuracy": top_per_class_acc,
            "classification_report": top_report,
            "confusion_matrix": top_cm.tolist(),
        },
        "block": {
            "accuracy": block_acc,
            "macro_f1": block_macro_f1,
            "weighted_f1": block_group_weighted_f1,
            "weighted_f1_group_cv": block_group_weighted_f1,
            "weighted_f1_holdout": block_weighted_f1,
            "per_class_accuracy": block_per_class_acc,
            "classification_report": block_report,
            "confusion_matrix": block_cm.tolist(),
        },
        "test_size": int(len(test_indices)),
        "quality_signal": "group_kfold_weighted_f1",
        "train_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    with open(model_dir / "rf_evaluation_report.json", "w", encoding="utf-8") as f:
        json.dump(evaluation_report, f, indent=2, ensure_ascii=False)

    joblib.dump(final_top_model, model_dir / "rf_topology_model.joblib")
    joblib.dump(final_block_model, model_dir / "rf_block_model.joblib")

    schema = {
        "feature_names": final_feature_names,
        "extra_requirement_keys": extra_keys,
        "topology_classes": topology_classes,
        "block_classes": block_classes,
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(model_dir / "rf_feature_schema.json", "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)

    plot_path = _save_train_vs_cv_plot(diagnostic_report, _default_plot_dir())

    report = {
        "metadata_samples": len(metadata),
        "training_rows": int(len(x_array)),
        "template_count": int(len(set(template_ids))),
        "samples_per_template": samples_per_template,
        "topology_accuracy": round(top_acc, 4),
        "block_accuracy": round(block_acc, 4),
        "topology_weighted_f1": round(top_group_weighted_f1, 4),
        "block_weighted_f1": round(block_group_weighted_f1, 4),
        "topology_weighted_f1_holdout": round(top_weighted_f1, 4),
        "block_weighted_f1_holdout": round(block_weighted_f1, 4),
        "topology_distribution": dict(Counter(y_topology_raw)),
        "block_distribution": dict(Counter(y_block_raw)),
        "feature_count": len(final_feature_names),
        "used_reduced_features": False,
        "reduced_model_candidate_better": reduced_model_candidate_better,
        "dataset_source": dataset_source,
        "quality_signal": "group_kfold_weighted_f1",
        "model_dir": str(model_dir),
        "plot_path": str(plot_path) if plot_path else None,
    }

    with open(model_dir / "rf_training_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Random Forest models for topology/block selection")
    parser.add_argument("--metadata-dir", type=Path, default=_default_metadata_dir())
    parser.add_argument("--model-dir", type=Path, default=_default_model_dir())
    parser.add_argument("--samples-per-template", type=int, default=36)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dataset-path", type=Path, default=None)
    args = parser.parse_args()

    report = train(
        metadata_dir=args.metadata_dir,
        model_dir=args.model_dir,
        samples_per_template=args.samples_per_template,
        random_seed=args.seed,
        dataset_path=args.dataset_path,
    )

    print("=== Random Forest training completed ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
