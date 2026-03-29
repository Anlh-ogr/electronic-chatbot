import re
filepath = "app/domains/circuits/ai_core/parameter_solver.py"
with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

# Fix _solve_ce properly. It calculated `re = rc/gain`. Then gave `max(re_ac, re)` to bias, and ALSO returned `max(re_ac, re)` as values["RE"].
# The bug: `re = self._snap(rc / gain)` might be too low. E.g. rc=11k, gain=18 -> re=611.
# It gives re to bias. Bias calculates R1/R2. Then solver returns `max(re_ac, re)`. This is correct.
# BUT wait! If `RE` is too small, DC bias sets VE = 0.6V (if RE=600, IC=1mA). That makes VE very close to VBE variance, leading to thermal instability, but for ideal model it should survive.
# Let us check `_bjt_voltage_divider_bias` again.

