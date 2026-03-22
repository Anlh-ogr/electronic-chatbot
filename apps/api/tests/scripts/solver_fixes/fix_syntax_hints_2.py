import re

with open('app/domains/circuits/ai_core/parameter_solver.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('(\\\"ic_ma\\\")', '(\"ic_ma\")')
text = text.replace('(\\\"id_ma\\\")', '(\"id_ma\")')

with open('app/domains/circuits/ai_core/parameter_solver.py', 'w', encoding='utf-8') as f:
    f.write(text)

print('Syntax string fixed properly')
