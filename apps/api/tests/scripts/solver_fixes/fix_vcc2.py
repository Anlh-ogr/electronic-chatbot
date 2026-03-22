with open('app/domains/circuits/ai_core/parameter_solver.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace(r'(\"vcc\")', '(\"vcc\")')

with open('app/domains/circuits/ai_core/parameter_solver.py', 'w', encoding='utf-8') as f:
    f.write(text)

print('Done')
