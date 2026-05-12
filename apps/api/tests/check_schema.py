from app.application.ai.schema_utils import prepare_vertex_schema
from app.application.ai.circuit_ir_schema import CircuitIR
import json

raw = CircuitIR.model_json_schema()

cleaned = prepare_vertex_schema(
    raw,
    debug_label="CircuitIR"
)

text = json.dumps(cleaned)

pattern = chr(34) + "type" + chr(34) + ": " + chr(34) + "null" + chr(34)

nulls = [
    i for i in range(len(text))
    if text[i:i+len(pattern)] == pattern
]

print(f"Con {len(nulls)} cho type null")

if nulls:
    for pos in nulls[:5]:
        start = max(0, pos - 80)
        end = pos + 120
        print("...")
        print(text[start:end])
        print("...")
