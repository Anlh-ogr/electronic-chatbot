import re
from pathlib import Path

content = Path('app/domains/circuits/ai_core/parameter_solver.py').read_text(encoding='utf-8')

bias_code = \"\"\"
    def _bjt_voltage_divider_bias(self, vcc: float, ic_ma: float, re: float, beta: float = 100.0) -> tuple[float, float]:
        ve = (ic_ma / 1000.0) * re
        vb = ve + 0.7
        ib_a = (ic_ma / 1000.0) / beta
        i_div = max(10 * ib_a, 0.0005)
        r2_raw = vb / i_div
        r1_raw = (vcc - vb) / (i_div + ib_a)
        if r1_raw < 0: r1_raw = 1e6
        return self._snap(r1_raw), self._snap(r2_raw)

    def _fet_voltage_divider_bias(self, vcc: float, id_ma: float, rs: float, vgs: float = 2.0) -> tuple[float, float]:
        vs = (id_ma / 1000.0) * rs
        vg = vs + vgs
        i_div = 10e-6
        rg2_raw = vg / i_div
        rg1_raw = (vcc - vg) / i_div
        if rg1_raw < 0: rg1_raw = 1e6
        return self._snap(rg1_raw), self._snap(rg2_raw)
\"\"\"

if "_bjt_voltage_divider_bias" not in content:
    content = content.replace("    # Solvers cho t?ng family", bias_code + "\n    # Solvers cho t?ng family")

# Now rewrite CE
ce_code = \"\"\"    def _solve_ce(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        vcc = float((meta or {}).get("vcc", 12.0))
        ic_ma = float(hints.get("ic_ma", 2.0))
        bypassed = hints.get("bypassed", True)

        re = 26.0 / ic_ma
        
        # Optimize bias for max swing: V_RC = 0.45*vcc, V_RE = 0.1*vcc
        rc_dc = (0.45 * vcc) / (ic_ma / 1000.0)
        re_dc = (0.10 * vcc) / (ic_ma / 1000.0)
        
        rc = self._snap(rc_dc)
        re_ext = self._snap(re_dc)
        
        r1, r2 = self._bjt_voltage_divider_bias(vcc, ic_ma, re_ext)
        
        if bypassed:
            actual_gain = rc / re
            formula = "Av  -RC / re (CE bypassed)"
            gain_formula = "Av  -RC / re"
        else:
            actual_gain = rc / (re + re_ext)
            formula = "Av  -RC / (re + RE) (CE unbypassed)"
            gain_formula = "Av  -RC / (re + RE)"

        result.values = {"RC": rc, "RE": re_ext, "R1": r1, "R2": r2}
        result.actual_gain = actual_gain
        result.gain_error_percent = abs(actual_gain - gain) / gain * 100 if gain > 0 else 0
        result.equations_used = [formula, f"re = 26mV/{ic_ma}mA = {re:.1f}O"]
        result.gain_formula = gain_formula
        result.message = f"CE: RC={rc}O, RE={re_ext}O, R1={r1}O, R2={r2}O  |Av|{actual_gain:.1f} (IC={ic_ma}mA, {'bypassed' if bypassed else 'unbypassed'})"
        return result\"\"\"

content = re.sub(r'    def _solve_ce\(self, gain: float, meta: Optional\[Dict\]\) -> SolvedParams:[\s\S]*?return result', ce_code, content)

cb_code = \"\"\"    def _solve_cb(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        vcc = float((meta or {}).get("vcc", 12.0))
        ic_ma = float(hints.get("ic_ma", 2.0))
        re = 26.0 / ic_ma
        
        rc_dc = (0.45 * vcc) / (ic_ma / 1000.0)
        re_dc = (0.10 * vcc) / (ic_ma / 1000.0)
        rc = self._snap(rc_dc)
        re_ext = self._snap(re_dc)
        
        r1, r2 = self._bjt_voltage_divider_bias(vcc, ic_ma, re_ext)

        result.values = {"RC": rc, "RE": re_ext, "R1": r1, "R2": r2}
        result.actual_gain = rc / re
        result.gain_error_percent = abs(result.actual_gain - gain) / gain * 100 if gain > 0 else 0
        result.equations_used = ["Av  RC / re", f"re = 26mV/{ic_ma}mA = {re:.1f}O"]
        result.gain_formula = "Av  RC / re"
        result.message = f"CB: RC={rc}O, RE={re_ext}, R1={r1}, R2={r2}  Av{result.actual_gain:.1f} (IC={ic_ma}mA)"
        return result\"\"\"
content = re.sub(r'    def _solve_cb\(self, gain: float, meta: Optional\[Dict\]\) -> SolvedParams:[\s\S]*?return result', cb_code, content)

cc_code = \"\"\"    def _solve_cc(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        vcc = float((meta or {}).get("vcc", 12.0))
        ic_ma = float(hints.get("ic_ma", 5.0)) # CC usually runs a bit hotter
        
        # CC: V_RE  VCC/2 for max swing
        re_dc = (0.5 * vcc) / (ic_ma / 1000.0)
        re_ext = self._snap(re_dc)
        
        r1, r2 = self._bjt_voltage_divider_bias(vcc, ic_ma, re_ext)

        result.values = {"RE": re_ext, "R1": r1, "R2": r2}
        result.actual_gain = 1.0
        result.gain_error_percent = 0
        result.equations_used = ["Av  1 (emitter follower)"]
        result.gain_formula = "Av  1"
        result.message = f"CC: RE={re_ext}O, R1={r1}, R2={r2}  Av1"
        return result\"\"\"
content = re.sub(r'    def _solve_cc\(self, gain: float, meta: Optional\[Dict\]\) -> SolvedParams:[\s\S]*?return result', cc_code, content)

cs_code = \"\"\"    def _solve_cs(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        vcc = float((meta or {}).get("vcc", 12.0))
        gm_ma = hints.get("gm_ma", 5.0)
        gm = gm_ma / 1000.0
        id_ma = float(hints.get("id_ma", 2.0))
        
        rd_dc = (0.45 * vcc) / (id_ma / 1000.0)
        rs_dc = (0.10 * vcc) / (id_ma / 1000.0)
        rd = self._snap(rd_dc)
        rs = self._snap(rs_dc)
        
        rg1, rg2 = self._fet_voltage_divider_bias(vcc, id_ma, rs)
        
        actual_gain = gm * rd
        result.values = {"RD": rd, "RS": rs, "R1": rg1, "R2": rg2}
        result.actual_gain = actual_gain
        result.gain_error_percent = abs(actual_gain - gain) / gain * 100 if gain > 0 else 0
        result.equations_used = ["Av  gm * RD"]
        result.gain_formula = "Av  gm * RD"
        result.message = f"CS: RD={rd}O, RS={rs}O, R1={rg1}, R2={rg2}  |Av|{actual_gain:.1f} (gm={gm_ma}mA/V)"
        return result\"\"\"
content = re.sub(r'    def _solve_cs\(self, gain: float, meta: Optional\[Dict\]\) -> SolvedParams:[\s\S]*?return result', cs_code, content)

cd_code = \"\"\"    def _solve_cd(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        vcc = float((meta or {}).get("vcc", 12.0))
        id_ma = float(hints.get("id_ma", 5.0))
        
        rs_dc = (0.5 * vcc) / (id_ma / 1000.0)
        rs = self._snap(rs_dc)
        
        rg1, rg2 = self._fet_voltage_divider_bias(vcc, id_ma, rs)

        result.values = {"RS": rs, "R1": rg1, "R2": rg2}
        result.actual_gain = 1.0
        result.gain_error_percent = 0
        result.equations_used = ["Av  1 (source follower)"]
        result.gain_formula = "Av  1"
        result.message = f"CD: RS={rs}O, R1={rg1}, R2={rg2}  Av1"
        return result\"\"\"
content = re.sub(r'    def _solve_cd\(self, gain: float, meta: Optional\[Dict\]\) -> SolvedParams:[\s\S]*?return result', cd_code, content)

cg_code = \"\"\"    def _solve_cg(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        vcc = float((meta or {}).get("vcc", 12.0))
        gm_ma = hints.get("gm_ma", 5.0)
        gm = gm_ma / 1000.0
        id_ma = float(hints.get("id_ma", 2.0))
        
        rd_dc = (0.45 * vcc) / (id_ma / 1000.0)
        rs_dc = (0.10 * vcc) / (id_ma / 1000.0)
        rd = self._snap(rd_dc)
        rs = self._snap(rs_dc)
        
        rg1, rg2 = self._fet_voltage_divider_bias(vcc, id_ma, rs)

        result.values = {"RD": rd, "RS": rs, "R1": rg1, "R2": rg2}
        result.actual_gain = gm * rd
        result.gain_error_percent = abs(result.actual_gain - gain) / gain * 100 if gain > 0 else 0
        result.equations_used = ["Av  gm * RD"]
        result.gain_formula = "Av  gm * RD"
        result.message = f"CG: RD={rd}O, RS={rs}O, R1={rg1}, R2={rg2}  Av{result.actual_gain:.1f} (gm={gm_ma}mA/V)"
        return result\"\"\"
content = re.sub(r'    def _solve_cg\(self, gain: float, meta: Optional\[Dict\]\) -> SolvedParams:[\s\S]*?return result', cg_code, content)

Path('app/domains/circuits/ai_core/parameter_solver.py').write_text(content, encoding='utf-8')
print("Patched!")
