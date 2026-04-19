from __future__ import annotations

import ast
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class PromptSource:
    prompt_id: str
    file_path: str
    class_name: str
    function_name: str
    schema_marker: Optional[str] = None


PROMPT_SOURCES: List[PromptSource] = [
    PromptSource(
        prompt_id="nlu.extract.v1",
        file_path="apps/api/app/application/ai/nlu_service.py",
        class_name="NLUService",
        function_name="_build_extraction_prompt",
        schema_marker="nlu.v1",
    ),
    PromptSource(
        prompt_id="cmp.propose.v1",
        file_path="apps/api/app/application/services/circuit_design_orchestrator.py",
        class_name="CircuitDesignOrchestrator",
        function_name="_build_system_prompt_for_components",
        schema_marker="cmp.v1",
    ),
    PromptSource(
        prompt_id="domain.check.v1",
        file_path="apps/api/app/application/ai/chatbot_service.py",
        class_name="ChatbotService",
        function_name="_domain_check",
        schema_marker="domain.v1",
    ),
    PromptSource(
        prompt_id="chat.c.v1",
        file_path="apps/api/app/application/ai/chatbot_service.py",
        class_name="ChatbotService",
        function_name="_smart_clarification",
    ),
    PromptSource(
        prompt_id="chat.rf.v1",
        file_path="apps/api/app/application/ai/chatbot_service.py",
        class_name="ChatbotService",
        function_name="_reasoning_fallback",
    ),
    PromptSource(
        prompt_id="chat.rx.v1",
        file_path="apps/api/app/application/ai/chatbot_service.py",
        class_name="ChatbotService",
        function_name="_reasoning_explain",
    ),
    PromptSource(
        prompt_id="nlg.s.v1",
        file_path="apps/api/app/application/ai/nlg_service.py",
        class_name="NLGService",
        function_name="_llm_success_response",
    ),
    PromptSource(
        prompt_id="nlg.e.v1",
        file_path="apps/api/app/application/ai/nlg_service.py",
        class_name="NLGService",
        function_name="_llm_error_response",
    ),
    PromptSource(
        prompt_id="nlg.c.v1",
        file_path="apps/api/app/application/ai/nlg_service.py",
        class_name="NLGService",
        function_name="_llm_clarification",
    ),
    PromptSource(
        prompt_id="nlg.m.v1",
        file_path="apps/api/app/application/ai/nlg_service.py",
        class_name="NLGService",
        function_name="_llm_modify_response",
    ),
]

REQUIRED_INVENTORY_COLUMNS = [
    "prompt_id",
    "file",
    "symbol",
    "purpose",
    "input_format",
    "output_schema",
    "max_length",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _extract_prompt_text(file_abs: Path, class_name: str, function_name: str) -> Optional[str]:
    source = file_abs.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for child in node.body:
            if not isinstance(child, ast.FunctionDef) or child.name != function_name:
                continue

            # Pattern A: system = ("...")
            for stmt in child.body:
                if not isinstance(stmt, ast.Assign):
                    continue
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == "system":
                        try:
                            value = ast.literal_eval(stmt.value)
                        except Exception:
                            value = None
                        if isinstance(value, str):
                            return value

            # Pattern B: return ("...")
            for stmt in child.body:
                if not isinstance(stmt, ast.Return):
                    continue
                try:
                    value = ast.literal_eval(stmt.value)
                except Exception:
                    value = None
                if isinstance(value, str):
                    return value

    return None


def _parse_inventory_table(inventory_path: Path) -> Dict[str, Dict[str, str]]:
    lines = inventory_path.read_text(encoding="utf-8").splitlines()
    rows = [line for line in lines if line.strip().startswith("|")]
    if len(rows) < 2:
        raise RuntimeError("Inventory table missing or invalid")

    headers = [col.strip() for col in rows[0].strip().strip("|").split("|")]
    header_index = {name: idx for idx, name in enumerate(headers)}

    for required in REQUIRED_INVENTORY_COLUMNS:
        if required not in header_index:
            raise RuntimeError(f"Missing inventory column: {required}")

    inventory: Dict[str, Dict[str, str]] = {}
    for row in rows[2:]:
        cells = [col.strip() for col in row.strip().strip("|").split("|")]
        if len(cells) != len(headers):
            continue
        if not any(cells):
            continue

        record = {name: cells[idx] for name, idx in header_index.items()}
        prompt_id = record.get("prompt_id", "")
        if not prompt_id or set(prompt_id) <= {"-", ":"}:
            continue
        inventory[prompt_id] = record

    return inventory


def _git_changed_files(repo_root: Path) -> List[str]:
    base_ref = os.getenv("GITHUB_BASE_REF", "").strip()
    if base_ref:
        diff_args = ["git", "diff", "--name-only", f"origin/{base_ref}...HEAD"]
    else:
        diff_args = ["git", "diff", "--name-only", "HEAD~1", "HEAD"]

    try:
        result = subprocess.run(
            diff_args,
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    files = [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]
    return files


def main() -> int:
    repo_root = _repo_root()
    inventory_path = repo_root / "docs" / "prompts_inventory.md"

    if not inventory_path.exists():
        print("ERROR: docs/prompts_inventory.md is missing")
        return 1

    try:
        inventory = _parse_inventory_table(inventory_path)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    errors: List[str] = []
    warnings: List[str] = []

    for source in PROMPT_SOURCES:
        record = inventory.get(source.prompt_id)
        if record is None:
            errors.append(f"Missing prompt inventory entry: {source.prompt_id}")
            continue

        for key in ("purpose", "input_format", "output_schema", "max_length"):
            if not (record.get(key) or "").strip():
                errors.append(f"Prompt '{source.prompt_id}' has empty field: {key}")

        try:
            max_length = int((record.get("max_length") or "").strip())
        except ValueError:
            errors.append(f"Prompt '{source.prompt_id}' has invalid max_length")
            continue

        file_abs = repo_root / source.file_path
        if not file_abs.exists():
            errors.append(f"Prompt source file missing: {source.file_path}")
            continue

        prompt_text = _extract_prompt_text(file_abs, source.class_name, source.function_name)
        if prompt_text is None:
            errors.append(
                f"Could not extract prompt text: {source.file_path}:{source.class_name}.{source.function_name}"
            )
            continue

        prompt_length = len(prompt_text)
        if prompt_length > max_length:
            errors.append(
                f"Prompt '{source.prompt_id}' length {prompt_length} exceeds max_length {max_length}"
            )

        if source.schema_marker and source.schema_marker not in prompt_text:
            errors.append(
                f"Prompt '{source.prompt_id}' missing schema marker '{source.schema_marker}'"
            )

    changed_files = _git_changed_files(repo_root)
    if changed_files:
        changed_set = set(changed_files)
        prompt_files = {src.file_path for src in PROMPT_SOURCES}
        inventory_rel = "docs/prompts_inventory.md"

        prompt_changed = any(path in changed_set for path in prompt_files)
        inventory_changed = inventory_rel in changed_set
        if prompt_changed and not inventory_changed:
            warnings.append(
                "Prompt files changed but docs/prompts_inventory.md was not updated. "
                "Please review inventory metadata."
            )

    for warning in warnings:
        print(f"WARNING: {warning}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("Prompt governance check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
