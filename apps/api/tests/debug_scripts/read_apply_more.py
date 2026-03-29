import os

file_path = "app/domains/circuits/ai_core/circuit_generator.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target = content.find("def _apply_parameters")
print(content[target+1500:target+2500])

