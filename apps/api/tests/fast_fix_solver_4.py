import re
filepath = "app/domains/circuits/ai_core/parameter_solver.py"
with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

# I miscopied the text. `re_dc = max(re, 0.1 * vcc / (ic_ma / 1000.0))` is still in there.
def patch():
    start_idx = text.find("def _bjt_voltage_divider_bias")
    if start_idx == -1: return text
    end_idx = text.find("def _fet_voltage_divider_bias", start_idx)
    
    new_method = """def _bjt_voltage_divider_bias(self, vcc: float, ic_ma: float, rc: float = 0.0, re: float = 0.0) -> tuple[float, float]:
        rc_dc = max(rc, 1.0)
        re_dc = re if re > 0 else (0.1 * vcc / (ic_ma / 1000.0))
        ve = (ic_ma / 1000.0) * re_dc
        vb = ve + 0.7
        beta = 100.0
        ib = (ic_ma / 1000.0) / beta
        
        i_div_initial = 20.0 * ib
        r2_ideal = vb / i_div_initial
        R2 = self._snap(r2_ideal)
        
        i_div_actual = vb / R2
        R1 = self._snap((vcc - vb) / (i_div_actual + ib))
        
        return float(R1), float(R2)

    """
    return text[:start_idx] + new_method + text[end_idx:]

new_text = patch()
with open(filepath, "w", encoding="utf-8") as f:
    f.write(new_text)
print("patched")

