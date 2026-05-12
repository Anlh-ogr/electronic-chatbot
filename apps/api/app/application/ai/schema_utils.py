"""
Vertex AI JSON Schema sanitizer.
Vertex AI's OpenAPI schema parser does NOT support several standard JSON Schema
keywords. This module strips or converts them before any schema reaches Vertex AI.
"""

from __future__ import annotations

import json
import logging
import copy, re
from typing import Any

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

# Keys Vertex AI từ chối hoàn toàn
_VERTEX_BANNED_KEYS = {
    "$defs", "$schema", "$id", "$ref",
    "title",               # Vertex không cần title ở nested objects
    "additionalProperties",
    "exclusiveMinimum", "exclusiveMaximum",
    "contentMediaType", "contentEncoding",
    "if", "then", "else",
}

def prepare_vertex_schema(schema: dict, *, debug_label: str = "") -> dict:
    schema = copy.deepcopy(schema)

    # ── Bước 1: Thu thập $defs ────────────────────────────────────────
    defs: dict[str, Any] = schema.pop("$defs", {})

    # ── Bước 2: Inline tất cả $ref ───────────────────────────────────
    def _resolve(obj, depth=0):
        if depth > 20:  # tránh circular ref vô hạn
            return obj
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref_name = obj["$ref"].split("/")[-1]
                resolved = copy.deepcopy(defs.get(ref_name, {}))
                resolved = _resolve(resolved, depth + 1)
                # merge các key còn lại (description v.v.)
                for k, v in obj.items():
                    if k != "$ref":
                        resolved[k] = v
                return resolved
            return {k: _resolve(v, depth + 1) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_resolve(i, depth + 1) for i in obj]
        return obj

    schema = _resolve(schema)

    # ── Bước 3: Strip tất cả banned keys ────────────────────────────
    def _strip(obj):
        if isinstance(obj, dict):
            return {
                k: _strip(v)
                for k, v in obj.items()
                if k not in _VERTEX_BANNED_KEYS
            }
        if isinstance(obj, list):
            return [_strip(i) for i in obj]
        return obj

    schema = _strip(schema)

    # ── Bước 4: Flatten anyOf/oneOf nếu chỉ có 1 option ────────────
    def _flatten_single_any_of(obj):
        if isinstance(obj, dict):
            obj = {k: _flatten_single_any_of(v) for k, v in obj.items()}
            if "anyOf" in obj and len(obj["anyOf"]) == 1:
                merged = {**obj["anyOf"][0], **{k: v for k, v in obj.items() if k != "anyOf"}}
                return merged
            if "oneOf" in obj and len(obj["oneOf"]) == 1:
                merged = {**obj["oneOf"][0], **{k: v for k, v in obj.items() if k != "oneOf"}}
                return merged
        if isinstance(obj, list):
            return [_flatten_single_any_of(i) for i in obj]
        return obj

    schema = _flatten_single_any_of(schema)
    
    # ── Bước 5: Flatten anyOf [X, {type: null}] → nullable ──────────
    def _flatten_nullable(obj):
        if isinstance(obj, dict):
            obj = {k: _flatten_nullable(v) for k, v in obj.items()}
            if "anyOf" in obj and isinstance(obj["anyOf"], list):
                non_null = [x for x in obj["anyOf"] if x != {"type": "null"}
                            and not (isinstance(x, dict) and x.get("type") == "null")]
                has_null = len(non_null) < len(obj["anyOf"])
                if has_null and len(non_null) == 1 and isinstance(non_null[0], dict):
                    # Merge inner type vào node hiện tại
                    inner = dict(non_null[0])
                    rest = {k: v for k, v in obj.items() if k != "anyOf"}
                    merged = {**inner, **rest, "nullable": True}
                    return merged
            return obj
        if isinstance(obj, list):
            return [_flatten_nullable(i) for i in obj]
        return obj

    schema = _flatten_nullable(schema)

    if debug_label:
        import logging
        remaining = [k for k in _walk_keys(schema) if k in _VERTEX_BANNED_KEYS or k.startswith("$")]
        if remaining:
            logging.getLogger(__name__).error(
                "[%s] Schema vẫn còn banned keys sau cleanup: %s",
                debug_label, list(set(remaining)),
            )

    return schema

def _walk_keys(obj):
    """Yield tất cả keys trong nested dict."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for i in obj:
            yield from _walk_keys(i)

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