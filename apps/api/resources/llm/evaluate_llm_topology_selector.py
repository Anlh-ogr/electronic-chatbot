from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

API_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(API_ROOT))

from app.domains.circuits.ai_core.llm_topology_selector import LLMTopologySelector


def _load_test_cases(path: Path) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as file_obj:
        payload = json.load(file_obj)

    if isinstance(payload, dict):
        if isinstance(payload.get("test_cases"), list):
            return [dict(item) for item in payload["test_cases"] if isinstance(item, dict)]
        raise ValueError("test_cases.json must contain a list or {'test_cases': [...]}.")

    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]

    raise ValueError("test_cases.json payload must be a JSON list or object.")


def _result_signature(result: Dict[str, Any]) -> str:
    selected = result.get("selected_topology")
    if selected:
        return str(selected)

    err = result.get("error") or {}
    code = err.get("code", "UNKNOWN") if isinstance(err, dict) else "UNKNOWN"
    return f"ERROR:{code}"


def _normalize_case_input(case: Dict[str, Any], prompt_version: str) -> Dict[str, Any]:
    input_json = case.get("input_json") or case.get("input")
    if not isinstance(input_json, dict):
        raise ValueError("Case must provide input_json as an object.")

    normalized = dict(input_json)
    if "prompt_version" not in normalized:
        normalized["prompt_version"] = prompt_version
    return normalized


def evaluate(
    selector: LLMTopologySelector,
    test_cases: List[Dict[str, Any]],
    *,
    prompt_version: str,
    consistency_runs: int,
) -> Dict[str, Any]:
    total = len(test_cases)
    success_count = 0
    violation_count = 0
    consistency_count = 0
    details: List[Dict[str, Any]] = []

    for idx, case in enumerate(test_cases, start=1):
        case_name = str(case.get("name") or f"case_{idx}")
        expected_topology = case.get("expected_topology")
        forbidden_topologies = set(str(v) for v in case.get("forbidden_topologies", []))

        try:
            input_json = _normalize_case_input(case, prompt_version)
            first_result = selector.select_topology(input_json)
        except Exception as exc:
            violation_count += 1
            details.append(
                {
                    "name": case_name,
                    "success": False,
                    "violation": True,
                    "consistent": False,
                    "error": str(exc),
                }
            )
            continue

        selected_topology = first_result.get("selected_topology")
        is_ok = bool(first_result.get("ok", False))

        success = is_ok
        if expected_topology is not None:
            success = success and str(selected_topology) == str(expected_topology)

        violation = (not is_ok) or (str(selected_topology) in forbidden_topologies)

        signatures = [_result_signature(first_result)]
        for _ in range(max(1, consistency_runs) - 1):
            follow_up = selector.select_topology(input_json)
            signatures.append(_result_signature(follow_up))
        consistent = len(set(signatures)) == 1

        if success:
            success_count += 1
        if violation:
            violation_count += 1
        if consistent:
            consistency_count += 1

        details.append(
            {
                "name": case_name,
                "success": success,
                "violation": violation,
                "consistent": consistent,
                "selected_topology": selected_topology,
                "expected_topology": expected_topology,
                "signature_samples": signatures,
                "result": first_result,
            }
        )

    denominator = max(1, total)
    return {
        "summary": {
            "total_cases": total,
            "success_rate": success_count / denominator,
            "violation_rate": violation_count / denominator,
            "consistency_score": consistency_count / denominator,
        },
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate LLM topology selector performance")
    parser.add_argument(
        "--test-cases",
        type=Path,
        default=Path(__file__).resolve().parent / "test_cases.json",
        help="Path to test_cases.json",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path")
    parser.add_argument("--prompt-version", type=str, default="v2", choices=["v1", "v2"])
    parser.add_argument("--consistency-runs", type=int, default=3)
    args = parser.parse_args()

    test_cases = _load_test_cases(args.test_cases)
    selector = LLMTopologySelector()

    report = evaluate(
        selector,
        test_cases,
        prompt_version=args.prompt_version,
        consistency_runs=max(1, args.consistency_runs),
    )

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as file_obj:
            json.dump(report, file_obj, indent=2, ensure_ascii=False)

    print(json.dumps(report["summary"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
