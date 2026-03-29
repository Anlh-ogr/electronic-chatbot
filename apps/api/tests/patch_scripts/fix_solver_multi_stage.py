import re

file_path = 'app/domains/circuits/ai_core/parameter_solver.py'
with open(file_path, 'r', encoding='utf-8') as f:
    text = f.read()

pattern = r'per_stage_gain\s*=\s*gain\s*\*\*\s*\(1\.0\s*/\s*num_stages\).*?while\s*len\(stage_names\)\s*<\s*num_stages:\s*stage_names\.append\(stage_names\[-1\]\)'

replacement = '''stage_names = [s.strip() for s in topology.split("+")][:num_stages]
        while len(stage_names) < num_stages:
            stage_names.append(stage_names[-1])

        num_amp_stages = sum(1 for name in stage_names if name not in ("CC", "CD"))
        if num_amp_stages == 0:
            num_amp_stages = 1
        per_stage_gain = gain ** (1.0 / num_amp_stages)

        _solver_map = {
            "CE": self._solve_ce,
            "CB": self._solve_cb,
            "CC": self._solve_cc,
            "CS": self._solve_cs,
            "CD": self._solve_cd,
            "CG": self._solve_cg,
        }'''

new_text = re.sub(pattern, replacement, text, flags=re.DOTALL)
if new_text != text:
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_text)
    print("Patch applied successfully.")
else:
    print("Pattern not found. No changes made.")
