"""
Vertex AI JSON Schema sanitizer.
Vertex AI's OpenAPI schema parser does NOT support several standard JSON Schema
keywords. This module strips or converts them before any schema reaches Vertex AI.
"""

from __future__ import annotations

import copy
import json
import logging

logger = logging.getLogger(__name__)

_UNSUPPORTED = {
    "const",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "contentEncoding",
    "contentMediaType",
    "if",
    "then",
    "else",
    "not",
    "allOf",
    "prefixItems",
    "$schema",
    "$id",
}


def sanitize_schema_for_vertex(schema: dict) -> dict:
    schema = copy.deepcopy(schema)
    _walk_sanitize(schema)
    return schema


def _walk_sanitize(node: dict) -> None:
    if not isinstance(node, dict):
        return
    if "const" in node:
        node["enum"] = [node.pop("const")]

    if "anyOf" in node and isinstance(node["anyOf"], list):
        non_null = []
        has_null = False
        for item in node["anyOf"]:
            if isinstance(item, dict) and item.get("type") == "null":
                has_null = True
                continue
            if item == {"type": "null"}:
                has_null = True
                continue
            non_null.append(item)

        if has_null:
            if len(non_null) == 1 and isinstance(non_null[0], dict):
                inner = non_null[0]
                node.pop("anyOf", None)
                node.update(inner)
                node["nullable"] = True
            else:
                node["anyOf"] = non_null
                node["nullable"] = True

    for key in _UNSUPPORTED - {"const"}:
        node.pop(key, None)
    for value in list(node.values()):
        if isinstance(value, dict):
            _walk_sanitize(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _walk_sanitize(item)


def slim_schema_for_vertex(schema: dict) -> dict:
    schema = copy.deepcopy(schema)
    _walk_slim(schema)
    return schema


def _walk_slim(node: dict) -> None:
    if not isinstance(node, dict):
        return
    for key in ("description", "title", "examples", "example"):
        node.pop(key, None)
    # inject "type" nếu node có properties/items nhưng thiếu "type"
    if "properties" in node and "type" not in node:
        node["type"] = "object"
    if "items" in node and "type" not in node:
        node["type"] = "array"
    
    
    
    for value in list(node.values()):
        if isinstance(value, dict):
            _walk_slim(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _walk_slim(item)


def prepare_vertex_schema(schema: dict, *, debug_label: str = "") -> dict:
    """Single entry point: sanitize + slim + assert no const remains."""
    result = slim_schema_for_vertex(sanitize_schema_for_vertex(schema))
    _inject_missing_types(result)
    raw = json.dumps(result)
    issues = []
    if '"const"' in raw:
        issues.append("'const' keyword found")
    if '"type": "null"' in raw or '"type":"null"' in raw:
        issues.append("'type: null' found (use nullable: true instead)")

    # kiểm tra node có properties nhưng không có type
    if _has_typeless_object(result): issues.append("object node missing type field")
    
    if issues:
        raise ValueError(
            f"[SCHEMA BUG] in '{debug_label}': {', '.join(issues)}. "
            f"Preview: {raw[:400]}"
        )

    logger.debug(
        "[schema] %s -> size=%d chars, clean=OK",
        debug_label or "schema",
        len(raw),
    )
    return result

def _inject_missing_types(node: dict) -> None:
    """Đảm bảo mọi object/array node đều có trường type."""
    if not isinstance(node, dict):
        return
    if "properties" in node and "type" not in node:
        node["type"] = "object"
    if "items" in node and "type" not in node:
        node["type"] = "array"
    for v in list(node.values()):
        if isinstance(v, dict):
            _inject_missing_types(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    _inject_missing_types(item)

def _has_typeless_object(node: dict) -> bool:
    if not isinstance(node, dict):
        return False
    if "properties" in node and "type" not in node:
        return True
    return any(
        _has_typeless_object(v) if isinstance(v, dict)
        else any(_has_typeless_object(i) for i in v if isinstance(i, dict))
        if isinstance(v, list) else False
        for v in node.values()
    )