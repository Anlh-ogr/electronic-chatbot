import json
import pytest

from app.application.ai.schema_utils import prepare_vertex_schema


def test_circuit_ir_schema_clean() -> None:
    from app.application.ai.circuit_ir_schema import CircuitIR

    result = prepare_vertex_schema(CircuitIR.model_json_schema(), debug_label="CircuitIR")
    assert '"const"' not in json.dumps(result)


def test_llm_contract_schema_clean() -> None:
    from app.application.ai.llm_contracts import LLMContractRequest

    result = prepare_vertex_schema(
        LLMContractRequest.model_json_schema(), debug_label="LLMContractRequest"
    )
    assert '"const"' not in json.dumps(result)


def test_sanitize_converts_const_to_enum() -> None:
    from app.application.ai.schema_utils import sanitize_schema_for_vertex

    dirty = {"properties": {"sv": {"const": "req.v1", "type": "string"}}}
    clean = sanitize_schema_for_vertex(dirty)
    assert "const" not in json.dumps(clean)
    assert clean["properties"]["sv"]["enum"] == ["req.v1"]


def test_slim_removes_metadata() -> None:
    from app.application.ai.schema_utils import slim_schema_for_vertex

    noisy = {
        "title": "MySchema",
        "description": "A schema",
        "type": "object",
        "properties": {
            "x": {"title": "X", "description": "a field", "type": "string"}
        },
    }
    slim = slim_schema_for_vertex(noisy)
    assert "title" not in slim
    assert "description" not in slim
    assert "title" not in slim["properties"]["x"]


def test_optional_field_converted_to_nullable() -> None:
    from app.application.ai.schema_utils import sanitize_schema_for_vertex

    dirty = {
        "properties": {
            "gn": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
            }
        }
    }
    clean = sanitize_schema_for_vertex(dirty)
    raw = json.dumps(clean)
    assert '"type": "null"' not in raw
    assert clean["properties"]["gn"].get("nullable") is True
    assert clean["properties"]["gn"].get("type") == "string"
    assert "anyOf" not in clean["properties"]["gn"]


def test_full_circuit_ir_no_null_type() -> None:
    from app.application.ai.circuit_ir_schema import CircuitIR
    from app.application.ai.schema_utils import prepare_vertex_schema

    result = prepare_vertex_schema(CircuitIR.model_json_schema(), debug_label="CircuitIR")
    raw = json.dumps(result)
    assert '"type": "null"' not in raw
