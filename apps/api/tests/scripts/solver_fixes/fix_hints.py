import re

def fix_float_get(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()

    text = re.sub(r'float\(hints\.get\(\"ic_ma\",\s*1\.0\)\)', r'float(hints.get(\"ic_ma\") or 1.0)', text)
    text = re.sub(r'float\(hints\.get\(\"id_ma\",\s*2\.0\)\)', r'float(hints.get(\"id_ma\") or 2.0)', text)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)

fix_float_get('app/domains/circuits/ai_core/parameter_solver.py')
print('Fixed hints in parameter_solver.py')
