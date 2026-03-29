import re
filepath = "app/domains/circuits/ai_core/parameter_solver.py"
with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

# I see what happens! The calculation for divider uses I_div = 10 * Ib
# So R2 = vb / i_div = 1.26 / 100uA = 12.6k -> snapped to 12k or 15k!
# And R1 = (vcc - vb) / (idiv + ib). (24 - 1.26) / 110uA = 206k -> snapped to 180k!
# The snag is snapping: 
# When R1=180k and R2=30k -> VTH = 24 * 30 / 210 = 3.42V !!!
# 3.42V is hugely different from target VB = 1.26V !!
# This means the snapping strategy picked R2=30k when it should have been 12k!
# Let me look closely at _snap method. 

old_bias_method = """    def _bjt_voltage_divider_bias(self, vcc: float, ic_ma: float, rc: float = 0.0, re: float = 0.0) -> tuple[float, float]:
        rc_dc = max(rc, 1.0)
        re_dc = re if re > 0 else 0.1 * vcc / (ic_ma / 1000.0)
        ve = ic_ma / 1000.0 * re_dc
        vb = ve + 0.7
        # I_divider ~ 10 * Ib
        beta = 100
        ib = (ic_ma / 1000.0) / beta
        i_div = 10 * ib
        R2 = vb / i_div
        R1 = (vcc - vb) / (i_div + ib)
        return self._snap(R1), self._snap(R2)"""
new_bias_method = """    def _bjt_voltage_divider_bias(self, vcc: float, ic_ma: float, rc: float = 0.0, re: float = 0.0) -> tuple[float, float]:
        rc_dc = max(rc, 1.0)
        re_dc = re if re > 0 else 0.1 * vcc / (ic_ma / 1000.0)
        ve = ic_ma / 1000.0 * re_dc
        vb = ve + 0.7
        # Use a larger I_divider to make it stiffer against snapping and beta variation
        beta = 100
        ib = (ic_ma / 1000.0) / beta
        
        # Snapping can viciously shift Vth. We will calculate ideal R2 and snap it, then calculate R1 to match Vth with the snapped R2. 
        # This keeps the VTH invariant even after snapping one resistor.
        i_div_initial = 20 * ib  # stiffer divider
        r2_ideal = vb / i_div_initial
        R2 = self._snap(r2_ideal)
        
        # Recalculate i_div based on snapped R2
        i_div_actual = vb / R2
        R1 = self._snap((vcc - vb) / (i_div_actual + ib))
        
        return R1, R2"""

text = text.replace(old_bias_method, new_bias_method)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(text)
print("done!")

