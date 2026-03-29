import os
import re

file_path = "app/domains/circuits/ai_core/circuit_generator.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Debug: check how _apply_parameters matches vcc
target_method = content.find("def _apply_parameters(")
print(content[target_method:target_method+500])


