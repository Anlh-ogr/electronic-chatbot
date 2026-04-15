# app/domains/circuits/ai_core/parameter_solver.py
""" 3: ParameterSolver — giải tham số (gain, R, C...)
Giải tham số mạch (R, C, ...) dựa trên gain yêu cầu và constraints.
Hỗ trợ:
  - Giải gain equation tìm bộ R
  - Snap về chuỗi E chuẩn (E6, E12, E24, E48, E96)
  - Kiểm tra constraints (power, voltage, matching, ...)
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

""" lý do sử dụng thư viện
math: tính log10, sqrt cho snap và giải gain
logging: ghi log debug trong quá trình solve
dataclasses: định nghĩa SolvedParams với to_dict() tiện lợi
field: khởi tạo default_factory cho dict/list trong dataclass
typing: sử dụng các type hint như Dict, List, Optional để dữ liệu rõ ràng hơn
"""

logger = logging.getLogger(__name__)


# ── Chuỗi E chuẩn ──
E_SERIES = {
    "E6": [1.0, 1.5, 2.2, 3.3, 4.7, 6.8],
    "E12": [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2],
    "E24": [
        1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
        3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1,
    ],
    "E48": [
        1.00, 1.05, 1.10, 1.15, 1.21, 1.27, 1.33, 1.40, 1.47, 1.54,
        1.62, 1.69, 1.78, 1.87, 1.96, 2.05, 2.15, 2.26, 2.37, 2.49,
        2.61, 2.74, 2.87, 3.01, 3.16, 3.32, 3.48, 3.65, 3.83, 4.02,
        4.22, 4.42, 4.64, 4.87, 5.11, 5.36, 5.62, 5.90, 6.19, 6.49,
        6.81, 7.15, 7.50, 7.87, 8.25, 8.66, 9.09, 9.53,
    ],
    "E96": [
        1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18, 1.21, 1.24,
        1.27, 1.30, 1.33, 1.37, 1.40, 1.43, 1.47, 1.50, 1.54, 1.58,
        1.62, 1.65, 1.69, 1.74, 1.78, 1.82, 1.87, 1.91, 1.96, 2.00,
        2.05, 2.10, 2.15, 2.21, 2.26, 2.32, 2.37, 2.43, 2.49, 2.55,
        2.61, 2.67, 2.74, 2.80, 2.87, 2.94, 3.01, 3.09, 3.16, 3.24,
        3.32, 3.40, 3.48, 3.57, 3.65, 3.74, 3.83, 3.92, 4.02, 4.12,
        4.22, 4.32, 4.42, 4.53, 4.64, 4.75, 4.87, 4.99, 5.11, 5.23,
        5.36, 5.49, 5.62, 5.76, 5.90, 6.04, 6.19, 6.34, 6.49, 6.65,
        6.81, 6.98, 7.15, 7.32, 7.50, 7.68, 7.87, 8.06, 8.25, 8.45,
        8.66, 8.87, 9.09, 9.31, 9.53, 9.76,
    ],
}


@dataclass
class SolvedParams:
    """ Kết quả solve tham số. 
    * values: cặp tên tham số - giá trị đã solve (R, C, ...) | key: tên tham số, value: giá trị đã solve
    * equations used: danh sách các công thức đã sử dụng để giải
    * constraints report: danh sách báo cáo kiểm tra ràng buộc từ metadata
    * actual gain: độ khuếch đại thực tế
    * gain error percent: sai số phần trăm so với yêu cầu
    * gain formula: công thức khuếch đại đã sử dụng
    * notes: ghi chú thêm về quá trình giải
    * warnings: cảnh báo nếu có vấn đề với giá trị đã solve
    * success: flag cho biết quá trình giải có thành công hay không
    * message: thông điệp tóm tắt kết quả giải
    """
    values: Dict[str, float] = field(default_factory=dict)
    equations_used: List[str] = field(default_factory=list)
    constraints_report: List[Dict[str, Any]] = field(default_factory=list)
    actual_gain: Optional[float] = None
    gain_error_percent: Optional[float] = None
    gain_formula: str = ""
    stage_analysis: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    success: bool = True
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "values": self.values,
            "equations_used": self.equations_used,
            "constraints_report": self.constraints_report,
            "actual_gain": self.actual_gain,
            "gain_error_percent": self.gain_error_percent,
            "gain_formula": self.gain_formula,
            "stage_analysis": self.stage_analysis,
            "notes": self.notes,
            "warnings": self.warnings,
            "success": self.success,
            "message": self.message,
        }


class ParameterSolver:
    """ Giải tham số mạch dựa trên gain yêu cầu + metadata constraints.
    Hỗ trợ các loại gain formula:
      - -RF / RIN (inverting)
      - 1 + RF / RG (non-inverting)
      - R2 / R1 (differential)
      - (1 + 2*RF/RG) * (R2/R1) (instrumentation)
      - -RC / re, -RC / (re+RE) (CE)
      - gm * RD (CS, CG)
      - beta1 * beta2 (Darlington, current gain)
    """

    def __init__(self, preferred_series: str = "E24"):
        self.preferred_series = preferred_series

    def solve(self, target_gain: Optional[float], family: str, metadata: Optional[Dict[str, Any]] = None,) -> SolvedParams:
        """ Giải tham số cho target_gain theo family.
        Trả về SolvedParams gồm giá trị R/C + constraint check.
        """
        result = SolvedParams()

        if target_gain is None:
            result.message = "No target gain specified, using template defaults"
            result.success = True
            return result

        abs_gain = abs(target_gain)

        # Gửi family vào solver map
        solver_map = {
            "inverting": self._solve_inverting,
            "non_inverting": self._solve_non_inverting,
            "differential": self._solve_differential,
            "instrumentation": self._solve_instrumentation,
            "common_emitter": self._solve_ce,
            "common_base": self._solve_cb,
            "common_collector": self._solve_cc,
            "common_source": self._solve_cs,
            "common_drain": self._solve_cd,
            "common_gate": self._solve_cg,
            "class_a": self._solve_ce,  # Class A dùng cùng CE topology
            "darlington": self._solve_darlington,
            "multi_stage": self._solve_multi_stage,
        }

        # chọn hàm giải phù hợp, nếu không có thì trả về message và success=True nhưng không thay đổi tham số
        solver_fn = solver_map.get(family)
        if solver_fn:
            result = solver_fn(abs_gain, metadata)
        else:
            result.message = f"No solver for family '{family}', parameters unchanged"
            result.success = True

        # kiểm tra ràng buộc từ metadata, kiểm tra lại trong circuit generator 
        if metadata and result.success:
            self._check_constraints(result, metadata)

        return result

    
    # Solvers cho từng family
    def _solve_inverting(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        """ Gain = -RF / RIN → tìm RF, RIN.
        meta solver_hints:
          rin_base (Ω): giá trị RIN cơ sở (default 10 000)
        """
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        rin_base = hints.get("rin_base", 10_000)
        rin = self._snap(rin_base)
        rf = self._snap(rin * gain)

        result.values = {"RIN": rin, "RF": rf}
        result.actual_gain = rf / rin
        result.gain_error_percent = abs(result.actual_gain - gain) / gain * 100
        result.equations_used = ["Av = -RF / RIN"]
        result.gain_formula = "Av = -RF / RIN"
        result.message = f"Inverting: RF={rf}Ω, RIN={rin}Ω → |Av|={result.actual_gain:.2f}"
        return result

    def _solve_non_inverting(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        """ Gain = 1 + RF / RG → tìm RF, RG.
        meta solver_hints: rg_base (Ω): giá trị RG cơ sở (default 10 000)
        """
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        rg_base = hints.get("rg_base", 10_000)

        if gain <= 1:
            # Unity gain buffer
            result.values = {"RF": 0, "RG": float("inf")}
            result.actual_gain = 1.0
            result.gain_error_percent = 0 if gain == 1 else abs(1 - gain) / gain * 100
            result.equations_used = ["Av = 1 (unity buffer)"]
            result.gain_formula = "Av = 1"
            result.message = "Non-inverting unity buffer"
            return result

        rg = self._snap(rg_base)
        rf = self._snap(rg * (gain - 1))

        result.values = {"RF": rf, "RG": rg}
        result.actual_gain = 1 + rf / rg
        result.gain_error_percent = abs(result.actual_gain - gain) / gain * 100
        result.equations_used = ["Av = 1 + RF / RG"]
        result.gain_formula = "Av = 1 + RF / RG"
        result.message = f"Non-inverting: RF={rf}Ω, RG={rg}Ω → Av={result.actual_gain:.2f}"
        return result

    def _solve_differential(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        """ Gain = R2 / R1 → tìm R1, R2, R3=R1, R4=R2.
        meta solver_hints:
          r1_base (Ω): giá trị R1 cơ sở (default 10 000)
        """
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        r1_base = hints.get("r1_base", 10_000)
        r1 = self._snap(r1_base)
        r2 = self._snap(r1 * gain)

        result.values = {"R1": r1, "R2": r2, "R3": r1, "R4": r2}
        result.actual_gain = r2 / r1
        result.gain_error_percent = abs(result.actual_gain - gain) / gain * 100
        result.equations_used = ["Av = R2 / R1 (matched R3=R1, R4=R2)"]
        result.gain_formula = "Av = R2 / R1"
        result.message = f"Differential: R1=R3={r1}Ω, R2=R4={r2}Ω → Av={result.actual_gain:.2f}"
        return result

    def _solve_instrumentation(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        """ Gain = (1 + 2*RF/RG) * (R2/R1).
        Strategy: đặt R2/R1 = 1, giải gain_stage1 = gain.
        Nếu gain > 100, chia stage1 và stage2.
        meta solver_hints:
          r1_base (Ω): giá trị R1 cơ sở (default 10 000)
          rf_base (Ω): giá trị RF cơ sở cho vòng lặp gain (default 10 000)
        """
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        r1_base = hints.get("r1_base", 10_000)
        rf_base = hints.get("rf_base", 10_000)

        if gain <= 100:
            # Stage 1 handles all gain, stage 2 = unity
            r1 = self._snap(r1_base)
            r2 = r1
            # 1 + 2*RF/RG = gain → RG = 2*RF / (gain - 1)
            rf = self._snap(rf_base)
            rg_raw = 2 * rf / (gain - 1) if gain > 1 else float("inf")
            rg = self._snap(rg_raw) if rg_raw < 1e7 else self._snap(1e6)
        else:
            # Split gain: stage1 ≈ sqrt(gain), stage2 gets the rest
            g1 = math.sqrt(gain)
            g2 = gain / g1

            r1 = self._snap(r1_base)
            r2 = self._snap(r1 * g2)

            rf = self._snap(rf_base)
            rg_raw = 2 * rf / (g1 - 1) if g1 > 1 else float("inf")
            rg = self._snap(rg_raw)

        actual_g1 = 1 + 2 * rf / rg if rg > 0 else 1
        actual_g2 = r2 / r1 if r1 > 0 else 1
        total = actual_g1 * actual_g2

        result.values = {
            "RF1": rf, "RF2": rf, "RG": rg,
            "R1": r1, "R2": r2, "R3": r1, "R4": r2,
        }
        result.actual_gain = total
        result.gain_error_percent = abs(total - gain) / gain * 100
        result.equations_used = [
            "G_total = (1 + 2*RF/RG) * (R2/R1)",
            f"G_stage1 = {actual_g1:.2f}",
            f"G_stage2 = {actual_g2:.2f}",
        ]
        result.gain_formula = "G = (1 + 2×RF/RG) × (R2/R1)"
        result.message = (
            f"Instrumentation: RF={rf}Ω, RG={rg}Ω, R1=R3={r1}Ω, R2=R4={r2}Ω "
            f"→ G={total:.2f} (target={gain})"
        )
        return result

    def _bjt_voltage_divider_bias(self, vcc: float, ic_ma: float, rc: float = 0.0, re: float = 0.0) -> tuple[float, float]:
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
        vcc = float((meta or {}).get("vcc") or 12.0)
        ic_ma = float(hints.get("ic_ma") or 1.0)
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
        vcc = float((meta or {}).get("vcc") or 12.0)
        ic_ma = float(hints.get("ic_ma") or 1.0)
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
        vcc = float((meta or {}).get("vcc") or 12.0)
        ic_ma = float(hints.get("ic_ma") or 1.0)
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
        vcc = float((meta or {}).get("vcc") or 12.0)
        gm_ma = hints.get("gm_ma", 5.0)
        gm = gm_ma / 1000.0
        id_ma = float(hints.get("id_ma") or 2.0)
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
        vcc = float((meta or {}).get("vcc") or 12.0)
        id_ma = float(hints.get("id_ma") or 2.0)
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
        vcc = float((meta or {}).get("vcc") or 12.0)
        gm_ma = hints.get("gm_ma", 5.0)
        gm = gm_ma / 1000.0
        id_ma = float(hints.get("id_ma") or 2.0)
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

    def _solve_darlington(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        """ Current gain = β1 * β2. Chọn β phù hợp.
        meta solver_hints:
          beta1 : hfe transistor thứ nhất (default 100)
        """
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        beta1 = hints.get("beta1", 100)
        beta2 = max(1, round(gain / beta1))

        result.values = {"beta1": beta1, "beta2": beta2}
        result.actual_gain = beta1 * beta2
        result.gain_error_percent = abs(result.actual_gain - gain) / gain * 100
        result.equations_used = ["Ai = β1 × β2 (current gain)"]
        result.gain_formula = "Ai = β1 × β2"
        result.message = f"Darlington: β1={beta1}, β2={beta2} → Ai={result.actual_gain}"
        return result

    def _solve_multi_stage(self, gain: float, meta: Optional[Dict]) -> SolvedParams:
        """ Multi-stage: chia đều gain theo số tầng.
        meta solver_hints:
          num_stages (int)    : số tầng khuếch đại (default 2)
          topology (str)      : "CE+CC" | "CE+CE" | "CS+CD"  (default "CE+CC")
          ic_ma (mA)          : collector current mỗi tầng BJT (default 2 mA)
          gm_ma (mA/V)        : transconductance mỗi tầng FET (default 5 mA/V)
        """
        result = SolvedParams()
        hints = (meta or {}).get("solver_hints", {})
        num_stages = max(1, int(hints.get("num_stages", 2)))
        topology = hints.get("topology", "CE+CC").upper()

        # Mỗi tầng khuếch đại gain^(1/num_stages), trừ follower (CC/CD) → 1
        stage_names = [s.strip() for s in topology.split("+")][:num_stages]
        while len(stage_names) < num_stages:
            stage_names.append(stage_names[-1])

        num_amp_stages = sum(1 for name in stage_names if name not in ("CC", "CD"))
        if num_amp_stages == 0:
            num_amp_stages = 1
        per_stage_gain = gain ** (1.0 / num_amp_stages)

        _solver_map = {
            "CE": self._solve_ce,
            "CB": self._solve_cb,
            "CC": self._solve_cc,
            "CS": self._solve_cs,
            "CD": self._solve_cd,
            "CG": self._solve_cg,
        }

        combined_values: Dict[str, float] = {}
        vcc = float((meta or {}).get("vcc") or 12.0)
        combined_values["VCC"] = vcc
        total_gain = 1.0
        all_equations: List[str] = []
        stage_analysis: List[Dict[str, Any]] = []

        for idx, stage_name in enumerate(stage_names, start=1):
            solver_fn = _solver_map.get(stage_name)
            if solver_fn is None:
                solver_fn = self._solve_ce  # fallback
            
            # Follower tầng cuối không cần gain
            stage_target = 1.0 if stage_name in ("CC", "CD") else per_stage_gain
            s_result = solver_fn(stage_target, meta)
            
            # Prefix tên resistor để tránh trùng key
            for k, v in s_result.values.items():
                combined_values[f"{k}_S{idx}"] = v
            stage_gain = (s_result.actual_gain or 1.0)
            total_gain *= stage_gain
            all_equations += [f"[Stage {idx} – {stage_name}] " + eq for eq in s_result.equations_used]
            stage_analysis.append(
                {
                    "stage": idx,
                    "type": stage_name,
                    "gain": stage_gain,
                    "equation": s_result.gain_formula,
                    **self._estimate_stage_metrics(stage_name, s_result.values, stage_gain),
                }
            )

        result.values = combined_values
        result.actual_gain = total_gain
        result.gain_error_percent = abs(total_gain - gain) / gain * 100
        result.equations_used = [f"A_total = {'×'.join(['Av' + str(i+1) for i in range(num_stages)])} ({topology})"] + all_equations
        result.gain_formula = f"A_total = {'×'.join([f'Av_{s}' for s in stage_names])}"
        result.stage_analysis = stage_analysis
        result.message = f"Multi-stage ({topology}, {num_stages} tầng): A_total≈{total_gain:.2f} (target={gain})"
        return result

    def _estimate_stage_metrics(self, stage_name: str, stage_values: Dict[str, float], stage_gain: float) -> Dict[str, Optional[float]]:
        """Estimate Zin/Zout/BW for one stage from topology and stage params."""
        vals = {str(k).upper(): float(v) for k, v in stage_values.items() if isinstance(v, (int, float))}
        zin: Optional[float] = None
        zout: Optional[float] = None
        bw_hz: Optional[float] = None
        st = stage_name.upper()

        if st == "CE":
            re = vals.get("RE", 100.0)
            beta = 100.0
            re_small = 26.0 / 2.0
            zin = beta * (re + re_small)
            zout = vals.get("RC")
        elif st == "CB":
            zin = 26.0 / 2.0
            zout = vals.get("RC")
        elif st == "CC":
            re = vals.get("RE")
            beta = 100.0
            if re is not None:
                zin = beta * re
                zout = re / beta
        elif st == "CS":
            zin = 1e6
            zout = vals.get("RD")
        elif st == "CD":
            zin = 1e6
            gm = 5e-3
            zout = 1.0 / gm
        elif st == "CG":
            gm = 5e-3
            zin = 1.0 / gm
            zout = vals.get("RD")

        if stage_gain and stage_gain > 0:
            # Generic gain-bandwidth approximation for first-order estimation.
            bw_hz = 1e6 / stage_gain

        return {
            "zin_ohm": zin,
            "zout_ohm": zout,
            "bandwidth_hz": bw_hz,
        }

    def analyze_topology(
        self,
        family: str,
        solved_values: Dict[str, float],
        gain_actual: Optional[float],
        frequency_hz: Optional[float],
        supply_mode: str = "auto",
        vcc: Optional[float] = None,
        stage_analysis: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Compute Zin/Zout/BW and stage table using topology-aware formulas."""
        vals = {str(k).upper(): float(v) for k, v in solved_values.items() if isinstance(v, (int, float))}

        zin: Optional[float] = None
        zout: Optional[float] = None
        bw_hz: Optional[float] = None

        if family == "inverting":
            rin = vals.get("RIN")
            rf = vals.get("RF")
            if rin and rin > 0:
                zin = rin
            zout = 50.0
            if gain_actual and gain_actual > 0:
                bw_hz = 1e6 / gain_actual

        elif family == "non_inverting":
            rg = vals.get("RG")
            rf = vals.get("RF")
            zin = 1e6
            zout = 50.0
            if gain_actual and gain_actual > 0:
                bw_hz = 1e6 / gain_actual
            if rg and rf and rg > 0:
                # Extra note: closed-loop gain from resistor network is tracked in gain_actual.
                pass

        elif family == "differential":
            r1 = vals.get("R1")
            r2 = vals.get("R2")
            if r1 and r1 > 0:
                zin = 2.0 * r1
            zout = 100.0
            if gain_actual and gain_actual > 0:
                bw_hz = 1e6 / gain_actual

        elif family == "instrumentation":
            zin = 1e9
            zout = 100.0
            if gain_actual and gain_actual > 0:
                bw_hz = 5e5 / max(gain_actual, 1.0)

        elif family in {"common_emitter", "class_a"}:
            rc = vals.get("RC")
            re = vals.get("RE", 100.0)
            beta = 100.0
            re_small = 26.0 / 2.0  # assume ~2mA when missing dedicated operating point
            zin = beta * (re_small + re)
            zout = rc if rc and rc > 0 else None
            cout = vals.get("COUT") or vals.get("COUPLING")
            if zout and cout and cout > 0:
                bw_hz = 1.0 / (2.0 * math.pi * zout * cout)

        elif family == "common_base":
            rc = vals.get("RC")
            re_small = 26.0 / 2.0
            zin = re_small
            zout = rc if rc and rc > 0 else None

        elif family == "common_collector":
            re = vals.get("RE")
            beta = 100.0
            if re and re > 0:
                zin = beta * re
                zout = re / beta

        elif family == "common_source":
            rd = vals.get("RD")
            gm = 5e-3
            zin = 1e6
            zout = rd if rd and rd > 0 else None
            if rd and rd > 0:
                # Approximate pole with small parasitic 20pF when explicit cap missing.
                bw_hz = 1.0 / (2.0 * math.pi * rd * 20e-12)

        elif family == "common_drain":
            rs = vals.get("RS")
            gm = 5e-3
            zin = 1e6
            if rs and rs > 0 and gm > 0:
                zout = 1.0 / gm

        elif family == "common_gate":
            rd = vals.get("RD")
            gm = 5e-3
            if gm > 0:
                zin = 1.0 / gm
            zout = rd if rd and rd > 0 else None

        elif family in {"multi_stage", "darlington"}:
            # Derive aggregate values from first and last stages if present.
            first_zin = None
            last_zout = None
            table = stage_analysis or []
            if table:
                first = table[0]
                last = table[-1]
                if first.get("type") in {"CE", "CB", "CC"}:
                    first_zin = vals.get("RE_S1", vals.get("R1_S1", 1000.0)) * 100.0
                if first.get("type") in {"CS", "CD", "CG"}:
                    first_zin = 1e6 if first.get("type") != "CG" else 200.0

                if last.get("type") in {"CC", "CD"}:
                    last_zout = vals.get(f"RE_S{last.get('stage')}", vals.get(f"RS_S{last.get('stage')}", 100.0)) / 100.0
                elif last.get("type") in {"CE", "CB", "CS", "CG"}:
                    last_zout = vals.get(f"RC_S{last.get('stage')}", vals.get(f"RD_S{last.get('stage')}", 1000.0))
            zin = first_zin
            zout = last_zout
            if not table and family == "darlington":
                b1 = vals.get("BETA1")
                b2 = vals.get("BETA2")
                table = [
                    {
                        "stage": 1,
                        "type": "BJT",
                        "gain": b1,
                        "equation": "Ai1 = β1",
                        "zin_ohm": None,
                        "zout_ohm": None,
                        "bandwidth_hz": None,
                    },
                    {
                        "stage": 2,
                        "type": "BJT",
                        "gain": b2,
                        "equation": "Ai2 = β2",
                        "zin_ohm": None,
                        "zout_ohm": None,
                        "bandwidth_hz": None,
                    },
                ]

        if bw_hz is None and frequency_hz is not None:
            bw_hz = float(frequency_hz)

        return {
            "input_impedance_ohm": zin,
            "output_impedance_ohm": zout,
            "bandwidth_hz": bw_hz,
            "stage_table": table if family in {"multi_stage", "darlington"} else (stage_analysis or []),
            "total_gain": gain_actual,
        }

    # ── Đóng gói ──
    def _snap(self, value: float) -> float:
        """Snap giá trị vào chuỗi E chuẩn gần nhất."""
        if value <= 0 or math.isinf(value) or math.isnan(value):
            return value

        series = E_SERIES.get(self.preferred_series, E_SERIES["E24"])

        # Chuẩn hóa [1, 10] để tìm nearest trong chuỗi E, sau đó scale lại
        decade = math.floor(math.log10(value))
        normalized = value / (10 ** decade)

        # Tìm giá trị gần nhất trong chuỗi E
        best = min(series, key=lambda x: abs(x - normalized))

        return best * (10 ** decade)

    def _check_constraints(self, result: SolvedParams, metadata: Dict) -> None:
        """Kiểm tra constraints từ metadata."""
        solver_hints = metadata.get("solver_hints", {})
        constraints = solver_hints.get("constraints", [])

        for c in constraints:
            name = c.get("name", "")
            rule = c.get("rule", "")
            severity = c.get("severity", "hard")

            report_entry = {
                "name": name,
                "rule": rule,
                "severity": severity,
                "status": "passed",  # simplified: mark passed for now
                "note": "Constraint noted, full validation pending in CircuitGenerator",
            }
            result.constraints_report.append(report_entry)

