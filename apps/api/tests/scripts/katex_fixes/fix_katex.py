import re

def fix_katex(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()

    text = text.replace('v_out(t) = {av:.4g} * v_in(t)', '\{out}(t) = {av:.4g} \cdot v_{in}(t)\$')
    text = text.replace('v_in(t) = V_in_pk*sin(2*pi*f*t) => v_out(t) = {av_abs:.4g}*V_in_pk*sin(2*pi*f*t + {phi_deg})', '\{in}(t) = V_{in\_pk}\sin(2\pi ft)\$ => \{out}(t) = {av_abs:.4g}V_{in\_pk}\sin(2\pi ft + {phi_deg}^{\circ})\$')

    text = text.replace('v_out(t) = A_v * v_in(t)', '\{out}(t) = A_v \cdot v_{in}(t)\$')
    text = text.replace('v_in(t) = V_in_pk * sin(2*pi*f*t)', '\{in}(t) = V_{in\_pk}\sin(2\pi ft)\$')
    text = text.replace('v_out(t) = |A_v|*V_in_pk*sin(2*pi*f*t + phi)', '\{out}(t) = |A_v|V_{in\_pk}\sin(2\pi ft + \phi)\$')

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)

fix_katex('app/application/ai/nlg_service.py')
print('Fixed Katex syntax')
