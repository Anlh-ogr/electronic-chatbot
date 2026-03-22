import codecs
with codecs.open('app/domains/circuits/ai_core/parameter_solver.py', 'r', 'utf-8') as f:
    text = f.read()

import re

# Find the start of def _solve_ce
start = text.find('    def _solve_ce(')
# Find the start of def _solve_darlington
end = text.find('    def _solve_darlington(')

new_methods = """    def _bjt_voltage_divider_bias(self, vcc: float, ic_ma: float, rc: float = 0.0, re: float = 0.0) -> tuple[float, float]:
        rc_dc = max(rc, 1.0)
        re_dc = max(re, 0.1 * vcc / (ic_ma / 1000.0))
        ve = ic_ma / 1000.0 * re_dc
        vb = ve + 0.7
        # I_divider ≈ 10 * Ib
        beta = 100
        ib = (ic_ma / 1000.0) / beta
        i_div = 10 * ib
        R2 = vb / i_div
        R1 = (vcc - vb) / (i_div + ib)
        return self._snap(R1), self._snap(R2)

    def _fet_voltage_divider_bias(self, vcc: float, id_ma: float, rd: float = 0.0, rs: float = 0.0) -> tuple[float, float]:
        rs_dc = max(rs, 0.1 * vcc / (id_ma / 1000.0))
        vs = id_ma / 1000.0 * rs_dc
        vgs = -2.0  # approximate
        vg = vs + vgs
        if vg <= 0:
            vg = 1.0 
        R2 = 1_000_000  # 1M
        i_div = vg / R2
        R1 = (vcc - vg) / i_div
        return self._snap(R1), self._snap(R2)

    def _solve_ce(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        vcc = float((meta or {}).get("vcc", 12.0))
        ic_ma = float(hints.get("ic_ma", 1.0))
        rc_dc = (0.45 * vcc) / (ic_ma / 1000.0)
        re_ac = 26.0 / ic_ma 
        rc = self._snap(rc_dc)
        re = self._snap(rc / gain) if gain > 0 else 0
        r1, r2 = self._bjt_voltage_divider_bias(vcc, ic_ma, rc, max(re_ac, re))

        result.values = {"RC": rc, "RE": max(self._snap(re_ac), re), "R1": r1, "R2": r2}
        result.actual_gain = rc / max(re_ac, re)
        result.gain_error_percent = abs(result.actual_gain - gain) / gain * 100 if gain > 0 else 0
        result.equations_used = ["Av ≈ RC / (re' + RE)", "re' = 26mV / Ic"]
        result.gain_formula = "Av ≈ RC / (RE + re')"
        result.message = f"CE: RC={rc}Ω, RE={max(self._snap(re_ac), re)}Ω, R1={r1}, R2={r2} → Av={result.actual_gain:.1f}"
        return result

    def _solve_cb(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        vcc = float((meta or {}).get("vcc", 12.0))
        ic_ma = float(hints.get("ic_ma", 1.0))
        re_ac = 26.0 / ic_ma
        rc_dc = (0.45 * vcc) / (ic_ma / 1000.0)
        re_dc = (0.10 * vcc) / (ic_ma / 1000.0)
        rc = self._snap(rc_dc)
        re = self._snap(re_dc)
        r1, r2 = self._bjt_voltage_divider_bias(vcc, ic_ma, rc, re)
        
        result.values = {"RC": rc, "RE": re, "R1": r1, "R2": r2}
        result.actual_gain = rc / re_ac
        result.gain_error_percent = abs(result.actual_gain - gain) / gain * 100 if gain > 0 else 0
        result.equations_used = ["Av ≈ RC / re'", "re' = 26mV / Ic(mA)"]
        result.gain_formula = "Av ≈ RC / re'"
        result.message = f"CB: RC={rc}Ω, RE={re}Ω, R1={r1}, R2={r2} → Av={result.actual_gain:.1f}"
        return result

    def _solve_cc(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        vcc = float((meta or {}).get("vcc", 12.0))
        ic_ma = float(hints.get("ic_ma", 1.0))
        re_dc = (0.50 * vcc) / (ic_ma / 1000.0)
        re = self._snap(re_dc)
        r1, r2 = self._bjt_voltage_divider_bias(vcc, ic_ma, 0.0, re)

        result.values = {"RE": re, "R1": r1, "R2": r2}
        result.actual_gain = 0.99
        result.gain_error_percent = 0.0
        result.equations_used = ["Av ≈ 1 (Emitter Follower)"]
        result.gain_formula = "Av ≈ 1"
        result.message = f"CC: RE={re}Ω, R1={r1}, R2={r2} → Av=0.99"
        return result

    def _solve_cs(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
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
        rg1, rg2 = self._fet_voltage_divider_bias(vcc, id_ma, rd, rs)

        result.values = {"RD": rd, "RS": rs, "R1": rg1, "R2": rg2}
        result.actual_gain = gm * rd
        result.gain_error_percent = abs(result.actual_gain - gain) / gain * 100 if gain > 0 else 0
        result.equations_used = ["Av ≈ gm * RD"]
        result.gain_formula = "Av ≈ gm * RD"
        result.message = f"CS: RD={rd}Ω, RS={rs}Ω, R1={rg1}, R2={rg2} → Av={result.actual_gain:.1f}"
        return result

    def _solve_cd(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        vcc = float((meta or {}).get("vcc", 12.0))
        id_ma = float(hints.get("id_ma", 2.0))
        rs_dc = (0.50 * vcc) / (id_ma / 1000.0)
        rs = self._snap(rs_dc)
        rg1, rg2 = self._fet_voltage_divider_bias(vcc, id_ma, 0.0, rs)

        result.values = {"RS": rs, "R1": rg1, "R2": rg2}
        result.actual_gain = 0.95
        result.gain_error_percent = 0.0
        result.equations_used = ["Av ≈ 1 (Source Follower)"]
        result.gain_formula = "Av ≈ 1"
        result.message = f"CD: RS={rs}Ω, R1={rg1}, R2={rg2} → Av=0.95"
        return result

    def _solve_cg(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
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
        rg1, rg2 = self._fet_voltage_divider_bias(vcc, id_ma, rd, rs)

        result.values = {"RD": rd, "RS": rs, "R1": rg1, "R2": rg2}
        result.actual_gain = gm * rd
        result.gain_error_percent = abs(result.actual_gain - gain) / gain * 100 if gain > 0 else 0
        result.equations_used = ["Av ≈ gm * RD"]
        result.gain_formula = "Av ≈ gm * RD"
        result.message = f"CG: RD={rd}Ω, RS={rs}Ω, R1={rg1}, R2={rg2} → Av={result.actual_gain:.1f}"
        return result

"""

text = text[:start] + new_methods + text[end:]

with codecs.open('app/domains/circuits/ai_core/parameter_solver.py', 'w', 'utf-8') as f:
    f.write(text)
print("Done slice patching")
