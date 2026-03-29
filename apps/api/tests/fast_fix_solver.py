import re
filepath = "app/domains/circuits/ai_core/parameter_solver.py"
with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

# Fix 1: ensure `_bjt_voltage_divider_bias` uses exact RE passed if it is > 0, to avoid silently assuming a larger RE and causing VCE collapse in validation.
old_bjt_bias = """    def _bjt_voltage_divider_bias(self, vcc: float, ic_ma: float, rc: float = 0.0, re: float = 0.0) -> tuple[float, float]:
        rc_dc = max(rc, 1.0)
        re_dc = max(re, 0.1 * vcc / (ic_ma / 1000.0))
        ve = ic_ma / 1000.0 * re_dc"""
new_bjt_bias = """    def _bjt_voltage_divider_bias(self, vcc: float, ic_ma: float, rc: float = 0.0, re: float = 0.0) -> tuple[float, float]:
        rc_dc = max(rc, 1.0)
        re_dc = re if re > 0 else 0.1 * vcc / (ic_ma / 1000.0)
        ve = ic_ma / 1000.0 * re_dc"""
        
# Fix 2: remove duplicate strings we might have injected in earlier manual attempts
text = text.replace("if re > 0: ve = (ic_ma / 1000.0) * re  # Use actual RE provided if available", "")

text = text.replace(old_bjt_bias, new_bjt_bias)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(text)
print("done")

