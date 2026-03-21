# .\thesis\electronic-chatbot\apps\api\resources\ml\train_xgboost_topology_block.py
"""Huấn luyện các mô hình XGBoost để dự đoán họ topology và loại block.

Đầu vào:
- resources/templates_metadata/*.meta.json

Đầu ra:
- resources/ml_models/xgb_topology_model.json
- resources/ml_models/xgb_block_model.json
- resources/ml_models/xgb_feature_schema.json
- resources/ml_models/xgb_training_report.json
"""


from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

# Ensure `app` package is importable when script is executed by file path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.domains.circuits.ai_core.ml_topology_selector import (
    XGBoostTopologySelector,
    _normalize_token,
)


def _api_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_metadata_dir() -> Path:
    return _api_root() / "resources" / "templates_metadata"


def _default_model_dir() -> Path:
    return _api_root() / "resources" / "ml_models"


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


def _build_training_rows(metadata: List[Dict[str, Any]], samples_per_template: int) -> Tuple[List[Dict[str, Any]], List[str], List[str], List[str]]:
    rows: List[Dict[str, Any]] = []
    y_topology: List[str] = []
    y_block: List[str] = []

    extra_requirement_tokens: set[str] = set()

    for meta in metadata:
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

            fmap = XGBoostTopologySelector.build_feature_map(
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
            )

            rows.append(fmap)
            y_topology.append(family)
            y_block.append(primary_block)

    return rows, y_topology, y_block, sorted(extra_requirement_tokens)


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


def _softmax(logits: np.ndarray) -> np.ndarray:
    # chuyển logit -> xác suất hợp lệ. (tổng=1)
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exp_vals = np.exp(shifted)
    sums = np.sum(exp_vals, axis=1, keepdims=True)
    return exp_vals / np.maximum(sums, 1e-12)


def _build_weighted_multiclass_objective(
    labels: Sequence[int],
    num_class: int,
) -> Any:
    """Create class-balanced multiclass objective for imbalanced labels.

    Loss (weighted cross-entropy):
      L = -w_y * log(p_y)
    where w_y is inverse-frequency class weight.
    """
    counts = Counter(labels)
    total = float(len(labels))
    class_weights = np.ones(num_class, dtype=np.float64)
    for cls_idx in range(num_class):
        cls_count = float(counts.get(cls_idx, 0))
        if cls_count > 0:
            class_weights[cls_idx] = total / (num_class * cls_count)

    def objective(y_true: np.ndarray, y_pred: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        true_labels = y_true.astype(np.int32)

        if y_pred.ndim == 1:
            y_pred = y_pred.reshape(-1, num_class)

        probs = _softmax(y_pred)
        one_hot = np.eye(num_class, dtype=np.float64)[true_labels]
        sample_weights = class_weights[true_labels].reshape(-1, 1)

        # phản ánh tổn thất huấn luyện        
        grad = sample_weights * (probs - one_hot)
        hess = sample_weights * np.maximum(probs * (1.0 - probs), 1e-6)
        return grad, hess

    return objective


def train(metadata_dir: Path, model_dir: Path, samples_per_template: int, random_seed: int) -> Dict[str, Any]:
    random.seed(random_seed)

    metadata = _load_metadata(metadata_dir)
    if not metadata:
        raise RuntimeError(f"No metadata files found in {metadata_dir}")

    rows, y_topology_raw, y_block_raw, extra_keys = _build_training_rows(metadata, samples_per_template)

    feature_names = XGBoostTopologySelector.build_feature_names(extra_requirement_keys=extra_keys)
    x = _build_matrix(rows, feature_names)

    y_topology, topology_classes = _encode_labels(y_topology_raw)
    y_block, block_classes = _encode_labels(y_block_raw)

    topology_objective = _build_weighted_multiclass_objective(
        labels=y_topology,
        num_class=len(topology_classes),
    )
    block_objective = _build_weighted_multiclass_objective(
        labels=y_block,
        num_class=len(block_classes),
    )

    x_train, x_test, y_top_train, y_top_test, y_block_train, y_block_test = train_test_split(
        x,
        y_topology,
        y_block,
        test_size=0.2,
        random_state=random_seed,
        stratify=y_topology,
    )

    top_model = XGBClassifier(
        objective=topology_objective,
        num_class=len(topology_classes),
        n_estimators=220,
        max_depth=6,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.85,
        reg_lambda=1.0,
        random_state=random_seed,
        eval_metric="mlogloss",
    )

    block_model = XGBClassifier(
        objective=block_objective,
        num_class=len(block_classes),
        n_estimators=240,
        max_depth=7,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.85,
        reg_lambda=1.0,
        random_state=random_seed,
        eval_metric="mlogloss",
    )

    top_model.fit(x_train, y_top_train)
    block_model.fit(x_train, y_block_train)

    top_pred = top_model.predict(x_test)
    block_pred = block_model.predict(x_test)

    top_acc = float(accuracy_score(y_top_test, top_pred))
    block_acc = float(accuracy_score(y_block_test, block_pred))

    model_dir.mkdir(parents=True, exist_ok=True)
    top_model.save_model(model_dir / "xgb_topology_model.json")
    block_model.save_model(model_dir / "xgb_block_model.json")

    schema = {
        "feature_names": feature_names,
        "extra_requirement_keys": extra_keys,
        "topology_classes": topology_classes,
        "block_classes": block_classes,
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    with open(model_dir / "xgb_feature_schema.json", "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)

    report = {
        "metadata_samples": len(metadata),
        "training_rows": len(rows),
        "samples_per_template": samples_per_template,
        "topology_accuracy": round(top_acc, 4),
        "block_accuracy": round(block_acc, 4),
        "topology_distribution": dict(Counter(y_topology_raw)),
        "block_distribution": dict(Counter(y_block_raw)),
        "feature_count": len(feature_names),
        "model_dir": str(model_dir),
    }

    with open(model_dir / "xgb_training_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Train XGBoost models for topology/block selection")
    parser.add_argument("--metadata-dir", type=Path, default=_default_metadata_dir())
    parser.add_argument("--model-dir", type=Path, default=_default_model_dir())
    parser.add_argument("--samples-per-template", type=int, default=36)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    report = train(
        metadata_dir=args.metadata_dir,
        model_dir=args.model_dir,
        samples_per_template=args.samples_per_template,
        random_seed=args.seed,
    )

    print("=== XGBoost training completed ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
