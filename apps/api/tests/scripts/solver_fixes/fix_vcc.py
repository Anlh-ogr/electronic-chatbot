import re

with open('app/domains/circuits/ai_core/parameter_solver.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = re.sub(r'vcc = float\(\(meta or \{\}\)\.get\(\"vcc\",\s*12\.0\)\)', r'vcc = float((meta or {}).get(\"vcc\") or 12.0)', c)

with open('app/domains/circuits/ai_core/parameter_solver.py', 'w', encoding='utf-8') as f:
    f.write(c)

print('Fixed!')
