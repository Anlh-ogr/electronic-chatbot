from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt


def _api_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_model_dir() -> Path:
    return _api_root() / "resources" / "ml_models"


def _default_output_dir() -> Path:
    return _api_root() / "resources" / "result_train_score_matplotlib"


def _load_json_if_exists(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        return None
    return payload


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _add_report_fields(
    rows: List[Tuple[str, str]],
    section_title: str,
    report: Optional[Dict[str, Any]],
    fields: Sequence[Tuple[str, str]],
) -> None:
    rows.append((section_title, ""))
    if report is None:
        rows.append(("status", "missing"))
        return

    for field_name, label in fields:
        if field_name in report:
            rows.append((label, _format_value(report[field_name])))


def _build_rows(model_dir: Path) -> List[Tuple[str, str]]:
    training_report = _load_json_if_exists(model_dir / "rf_training_report.json")
    leakage_report = _load_json_if_exists(model_dir / "rf_leakage_report.json")
    diagnostic_report = _load_json_if_exists(model_dir / "rf_diagnostic_report.json")
    evaluation_report = _load_json_if_exists(model_dir / "rf_evaluation_report.json")

    rows: List[Tuple[str, str]] = []

    _add_report_fields(
        rows,
        "Training Summary",
        training_report,
        (
            ("metadata_samples", "metadata_samples"),
            ("training_rows", "training_rows"),
            ("samples_per_template", "samples_per_template"),
            ("feature_count", "feature_count"),
            ("topology_accuracy", "topology_accuracy"),
            ("block_accuracy", "block_accuracy"),
            ("topology_weighted_f1", "topology_weighted_f1"),
            ("block_weighted_f1", "block_weighted_f1"),
            ("topology_weighted_f1_holdout", "topology_weighted_f1_holdout"),
            ("block_weighted_f1_holdout", "block_weighted_f1_holdout"),
            ("quality_signal", "quality_signal"),
        ),
    )

    rows.append(("", ""))

    rows.append(("Leakage Summary", ""))
    if leakage_report is None:
        rows.append(("status", "missing"))
    else:
        rows.extend(
            [
                ("sample_count", _format_value(leakage_report.get("sample_count", "N/A"))),
                ("feature_count", _format_value(leakage_report.get("feature_count", "N/A"))),
                (
                    "suspect_feature_count",
                    _format_value(leakage_report.get("suspect_feature_count", "N/A")),
                ),
                (
                    "mi_threshold",
                    _format_value(leakage_report.get("thresholds", {}).get("mi_threshold", "N/A")),
                ),
                (
                    "uniqueness_threshold",
                    _format_value(leakage_report.get("thresholds", {}).get("uniqueness_threshold", "N/A")),
                ),
                (
                    "spearman_threshold",
                    _format_value(leakage_report.get("thresholds", {}).get("spearman_threshold", "N/A")),
                ),
            ]
        )

    rows.append(("", ""))

    rows.append(("Diagnostic Summary", ""))
    if diagnostic_report is None:
        rows.append(("status", "missing"))
    else:
        top = diagnostic_report.get("topology", {})
        block = diagnostic_report.get("block", {})
        rows.extend(
            [
                ("top_train_accuracy", _format_value(top.get("train_accuracy", "N/A"))),
                ("top_cv_standard_f1", _format_value(top.get("cv_standard_f1", {}).get("mean", "N/A"))),
                ("top_cv_group_f1", _format_value(top.get("cv_group_f1", {}).get("mean", "N/A"))),
                ("block_train_accuracy", _format_value(block.get("train_accuracy", "N/A"))),
                ("block_cv_standard_f1", _format_value(block.get("cv_standard_f1", {}).get("mean", "N/A"))),
                ("block_cv_group_f1", _format_value(block.get("cv_group_f1", {}).get("mean", "N/A"))),
            ]
        )

    rows.append(("", ""))

    rows.append(("Evaluation Summary", ""))
    if evaluation_report is None:
        rows.append(("status", "missing"))
    else:
        top_eval = evaluation_report.get("topology", {})
        block_eval = evaluation_report.get("block", {})
        rows.extend(
            [
                ("eval_top_weighted_f1", _format_value(top_eval.get("weighted_f1", "N/A"))),
                ("eval_block_weighted_f1", _format_value(block_eval.get("weighted_f1", "N/A"))),
                (
                    "eval_quality_signal",
                    _format_value(evaluation_report.get("quality_signal", "N/A")),
                ),
            ]
        )

    return rows


def render_table(model_dir: Path, output_path: Path, title: str) -> Path:
    rows = _build_rows(model_dir)

    height = max(6.0, 1.2 + 0.32 * len(rows))
    fig, ax = plt.subplots(figsize=(12, height))
    ax.axis("off")

    table = ax.table(
        cellText=[[metric, value] for metric, value in rows],
        colLabels=["Metric", "Value"],
        cellLoc="left",
        colLoc="left",
        loc="center",
        colWidths=[0.45, 0.55],
    )

    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.0, 1.3)

    for (row_idx, col_idx), cell in table.get_celld().items():
        if row_idx == 0:
            cell.set_facecolor("#E8EEF7")
            cell.set_text_props(weight="bold")
        elif col_idx == 0 and rows[row_idx - 1][1] == "":
            cell.set_facecolor("#F5F5F5")
            cell.set_text_props(weight="bold")

    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Render RF training result table using matplotlib")
    parser.add_argument("--model-dir", type=Path, default=_default_model_dir())
    parser.add_argument("--output-dir", type=Path, default=_default_output_dir())
    parser.add_argument("--output-name", type=str, default="rf_training_results_table.png")
    parser.add_argument("--title", type=str, default="Random Forest Training Results")
    args = parser.parse_args()

    output_path = args.output_dir / args.output_name
    saved_path = render_table(model_dir=args.model_dir, output_path=output_path, title=args.title)
    print(f"Saved matplotlib table: {saved_path}")


if __name__ == "__main__":
    main()
