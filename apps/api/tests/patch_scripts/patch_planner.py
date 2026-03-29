
import re

path = "app/domains/circuits/ai_core/topology_planner.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

pattern = r"is_opamp = spec.circuit_type in {\\\"inverting\\\", \\\"non_inverting\\\", \\\"differential\\\", \\\"instrumentation\\\"}\n        if not is_opamp and spec.circuit_type != \\\"multi_stage\\\" and spec.gain is not None and spec.gain >= 100:\n            plan.rationale.append"
replacement = r"""is_opamp = spec.circuit_type in {"inverting", "non_inverting", "differential", "instrumentation"}
        if not is_opamp and spec.circuit_type != "multi_stage" and spec.gain is not None and spec.gain >= 100:
            plan.rationale.append"""

new_text = re.sub(pattern, replacement, text)

with open(path, "w", encoding="utf-8") as f:
    f.write(new_text)

print("Patch 2 applied.")

