import os

file_path = "app/domains/circuits/ai_core/circuit_generator.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target_method = content.find("def _apply_parameters(")
end_method = content.find("def ", target_method + 20)
if end_method == -1:
    end_method = len(content)
print(content[target_method:end_method])


