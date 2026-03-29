
path = "app/domains/circuits/ai_core/circuit_generator.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# I want to add VCC to solved_values directly inside _run_pipeline_from_plan of ai_core.py 
# or maybe parameter_solver.py should just return VCC in all methods. Let's do it in parameter_solver.py

path_ps = "app/domains/circuits/ai_core/parameter_solver.py"
with open(path_ps, "r", encoding="utf-8") as f:
    ps_content = f.read()

ps_content = ps_content.replace(
    "combined_values: Dict[str, float] = {}",
    "combined_values: Dict[str, float] = {}\n        vcc = float((meta or {}).get(\"vcc\") or 12.0)\n        combined_values[\"VCC\"] = vcc"
)

with open(path_ps, "w", encoding="utf-8") as f:
    f.write(ps_content)

print("Patch multi_stage VCC.")

