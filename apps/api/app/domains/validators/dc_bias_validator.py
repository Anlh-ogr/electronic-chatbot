from __future__ import annotations

""" Domain validator cho phan cuc DC va do loi co ban. Module nay nam o tang Domain, khong goi LLM va khong phu thuoc vao ngspice. """

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

@dataclass
class ComponentSet:
    """Bo linh kien do LLM de xuat."""
    R1: float
    R2: float
    RC: float
    RE: float
    VCC: float
    beta: float = 100.0
    topology: str = "common_emitter"

    def to_dict(self) -> dict:
        return {
            "R1": float(self.R1),
            "R2": float(self.R2),
            "RC": float(self.RC),
            "RE": float(self.RE),
            "VCC": float(self.VCC),
            "beta": float(self.beta),
            "topology": self.topology,
        }


@dataclass
class DCValidationResult:
    """Ket qua kiem tra DC domain-level."""

    passed: bool
    errors: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)


class DCBiasValidator:
    """Kiem tra dinh luat vat ly o tang Domain."""

    VBE: float = 0.7
    VCE_SAT: float = 0.3
    VCE_MIN_RATIO: float = 0.25
    GAIN_TOLERANCE: float = 0.25
    IB_MIN_UA: float = 1.0
    RE_AC_MIN_OHM: float = 1e-3
    
    SUPPORTED_TOPOLOGIES = {
        "common_emitter",
        "common_base",
        "common_collector",
        "inverting",
        "non_inverting",
        "differential",
        "instrumentation",
        "common_source",
        "common_drain",
        "common_gate",
        "class_a", "class_ab", "class_b", "class_c", "class_d",
        "darlington",
        "multi_stage",
    }
    
    SUPPLY_COMPONENT_TYPES = {
        "VCC", "VDD", "VEE", "POWER", "POWER_SUPPLY",
        "PWR_FLAG", "VOLTAGE_SOURCE", "VSOURCE",
    }

    SWING_DROPOUT: dict = {
        "opamp_standard": (1.5, 1.5),   # LM741, LM358, UA741 — non-RRO
        "opamp_rro":      (0.1, 0.1),   # TL071, OPA2134, LMV358 — rail-to-rail
        "bjt_ce":         (0.3, 0.3),   # VCE_sat
        "bjt_cc":         (0.7, 0.3),   # VBE drop (emitter follower)
        "bjt_cb":         (0.5, 0.5),   # VCB_sat
        "fet_cs":         (0.5, 0.5),   # VDS_sat
        "fet_cd":         (1.0, 0.5),   # VGS threshold (source follower)
        "fet_cg":         (0.5, 0.5),
        "class_a":        (0.3, 0.3),
        "class_ab":       (0.5, 0.5),
        "class_b":        (0.5, 0.5),
        "class_c":        (0.5, 0.5),
        "class_d":        (0.2, 0.2),   # switching + LC filter
        "darlington":     (1.4, 0.3),   # 2×VBE_sat
        "multi_stage":    (0.3, 0.3),   # tầng output cuối (CE)
    }
    
    _TOPO_TO_DROPOUT_KEY: dict = {
        "inverting":        "opamp_standard",
        "non_inverting":    "opamp_standard",
        "differential":     "opamp_standard",
        "instrumentation":  "opamp_standard",
        "common_emitter":   "bjt_ce",
        "common_collector": "bjt_cc",
        "common_base":      "bjt_cb",
        "common_source":    "fet_cs",
        "common_drain":     "fet_cd",
        "common_gate":      "fet_cg",
        "class_a":          "class_a",
        "class_ab":         "class_ab",
        "class_b":          "class_b",
        "class_c":          "class_c",
        "class_d":          "class_d",
        "darlington":       "darlington",
        "multi_stage":      "multi_stage",
    }
    
    _TOPOLOGY_ALIASES: dict = {
        "ci":           "inverting",
        "ni":           "non_inverting",
        "diff":         "differential",
        "ce":           "common_emitter",
        "cc":           "common_collector",
        "cb":           "common_base",
        "cs":           "common_source",
        "cd":           "common_drain",
        "cg":           "common_gate",
        "class_a_bjt":  "class_a",
        "class_ab_bjt": "class_ab",
    }
    
    
    # -- helpers --
    @staticmethod
    def _get_field(source: Any, field_name: str, default: Any = None) -> Any:
        if source is None:
            return default
        if isinstance(source, dict):
            return source.get(field_name, default)
        return getattr(source, field_name, default)

    @classmethod
    def _coerce_voltage(cls, value: Any) -> Optional[float]:
        if isinstance(value, dict):
            return cls._coerce_voltage(value.get("value"))
        if isinstance(value, (int, float)):
            v = abs(float(value))
            return v if v > 1.0 else None
        if not isinstance(value, str):
            return None
        
        text = value.strip().replace("±", "")
        if not text:
            return None
        
        m = re.search(r"([+-]?\d+(?:\.\d+)?)(\s*(mv|v))?\b", text, flags=re.IGNORECASE)
        if not m:
            return None
        
        v = abs(float(m.group(1)))
        if (m.group(3) or "v").lower() == "mv":
            v /= 1000.0
        
        return v if v > 1.0 else None

    @classmethod
    def _normalize_topology(cls, raw: str) -> str:
        """Chuẩn hóa alias ngắn → tên đầy đủ."""
        t = (raw or "").strip().lower()
        return cls._TOPOLOGY_ALIASES.get(t, t)

    @staticmethod
    def _has_bjt_topology_hint(topology: str) -> bool:
        hint = (topology or "").strip().lower()
        
        return any(t in hint for t in (
            "common_emitter", "common_base", "common_collector",
            "multi_stage", "darlington",
            "class_a", "class_ab", "class_b", "class_c",
    ))
    
    @classmethod
    def _extract_topology_hint(cls, ir: Any) -> str:
        for candidate in [
            cls._get_field(ir, "topology"),
            cls._get_field(ir, "circuit_type"),
            cls._get_field(ir, "device_preference"),
            cls._get_field(cls._get_field(ir, "analysis"), "topology_classification"),
            cls._get_field(cls._get_field(ir, "architecture"), "topology_type"),
        ]:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip().lower()
        return ""

    @classmethod
    def _default_vcc_for_topology(cls, topology: str) -> float:
        return 12.0 if cls._has_bjt_topology_hint(topology) else 15.0


    # -- vcc extraction --
    def _extract_vcc(self, ir: Any) -> float:
        topology = self._extract_topology_hint(ir)

        ps = self._get_field(ir, "power_supply")
        v = self._coerce_voltage(self._get_field(ps, "voltage"))
        if v is not None:
            return v

        arch = self._get_field(ir, "architecture")
        for stage in self._get_field(arch, "stages", []) or []:
            v = self._coerce_voltage(self._get_field(stage, "active_device_vcc"))
            if v is not None:
                return v

        for comp in self._get_field(ir, "components", []) or []:
            if str(self._get_field(comp, "type", "")).strip().upper() not in self.SUPPLY_COMPONENT_TYPES:
                continue
            for fn in ("voltage", "value", "vcc", "vdd"):
                v = self._coerce_voltage(self._get_field(comp, fn))
                if v is not None:
                    return v
            params = self._get_field(comp, "parameters", {})
            if isinstance(params, dict):
                for fn in ("voltage", "value", "vcc", "vdd"):
                    v = self._coerce_voltage(params.get(fn))
                    if v is not None:
                        return v

        analysis = self._get_field(ir, "analysis")
        for sln in ("design_specs", "calculations_table", "calculations"):
            for spec in self._get_field(analysis, sln, []) or []:
                param = str(
                    self._get_field(spec, "parameter",
                    self._get_field(spec, "name", ""))
                ).strip().lower()
                if not any(t in param for t in ("supply", "vcc", "vdd", "vss", "rail")):
                    continue
                for fn in ("value", "voltage", "calculated_value"):
                    v = self._coerce_voltage(self._get_field(spec, fn))
                    if v is not None:
                        return v

        return self._default_vcc_for_topology(topology)
    
    # -- core validation --
    def validate(self, c: ComponentSet, gain_target: Optional[float]) -> DCValidationResult:
        # Kiem tra phan cuc DC cho BJT co mang chia ap base.
        errors: List[str] = []
        suggestions: List[str] = []

        if c.VCC <= 0:
            errors.append("VCC phai lon hon 0V")
        if c.R1 <= 0 or c.R2 <= 0 or c.RC <= 0:
            errors.append("R1, R2, RC phai lon hon 0")
        if c.beta <= 0:
            errors.append("beta phai lon hon 0")

        re_eff = c.RE if c.RE > 0 else 1e-9

        if errors:
            return DCValidationResult(
                passed=False, errors=errors,
                suggestions=["Kiem tra lai gia tri linh kien dau vao"],
                metrics={},
            )

        vth = c.VCC * (c.R2 / (c.R1 + c.R2))
        rth = (c.R1 * c.R2) / (c.R1 + c.R2)
        ib = max((vth - self.VBE) / (rth + (c.beta + 1.0) * re_eff), 0.0)
        ic = c.beta * ib
        ie = (c.beta + 1.0) * ib
        vce = c.VCC - ic * c.RC - ie * re_eff

        av_actual = 0.0
        if ic > 0:
            re_ss = 0.026 / ic
            topology = self._normalize_topology(c.topology)
            if topology == "common_collector":
                av_actual = re_eff / (re_eff + re_ss)
            elif topology == "common_base":
                av_actual = c.RC / re_ss
            else:
                av_actual = c.RC / (re_ss + max(re_eff, self.RE_AC_MIN_OHM))

        metrics: Dict[str, float] = {
            "VTH": vth, "RTH": rth,
            "IB_uA": ib * 1e6, "IC_mA": ic * 1e3, "IE_mA": ie * 1e3,
            "VCE": vce, "Av_actual": av_actual,
        }

        if vce < self.VCE_SAT:
            errors.append(f"VCE={vce:.3f}V < VCE_SAT={self.VCE_SAT:.3f}V, transistor de bao hoa")

        min_vce = c.VCC * self.VCE_MIN_RATIO
        if vce < min_vce:
            errors.append(f"VCE={vce:.3f}V < {self.VCE_MIN_RATIO:.2f}*VCC={min_vce:.3f}V, khong du swing")

        q_center = c.VCC / 2.0
        q_band = q_center * 0.4
        if abs(vce - q_center) > q_band:
            errors.append(
                f"Q-point lech, VCE={vce:.3f}V khong nam trong "
                f"VCC/2 ±40% ({q_center - q_band:.3f}..{q_center + q_band:.3f}V)"
            )

        if ib * 1e6 < self.IB_MIN_UA:
            errors.append(f"IB={ib * 1e6:.3f}uA < IB_MIN_UA={self.IB_MIN_UA:.3f}uA")
            suggestions.append("Giam R1/R2 hoac tang dong chia ap de tang IB")

        if gain_target and gain_target > 0:
            rel_err = abs(av_actual - gain_target) / gain_target
            metrics["gain_rel_error"] = rel_err
            if rel_err > self.GAIN_TOLERANCE:
                errors.append(
                    f"Av={av_actual:.3f} lech muc tieu {gain_target:.3f} "
                    f"qua {self.GAIN_TOLERANCE * 100:.0f}%"
                )
                if ic > 0:
                    re_ss = 0.026 / ic
                    rc_t = gain_target * (re_ss + max(re_eff, self.RE_AC_MIN_OHM))
                    suggestions.append(f"De xuat RC = {rc_t:.0f}Ohm de dat Av={gain_target:.3f}")
                    re_t = (c.RC / max(gain_target, 1e-9)) - re_ss
                    if re_t > self.RE_AC_MIN_OHM:
                        suggestions.append(f"De xuat RE ~= {re_t:.0f}Ohm de Av gan {gain_target:.3f}")

        if any("VCE" in e or "Q-point" in e for e in errors):
            total = c.RC + re_eff * (1.0 + 1.0 / max(c.beta, 1e-9))
            if total > 0:
                ic_t = (c.VCC / 2.0) / total
                ib_t = max(ic_t / c.beta, 1e-9)
                vth_t = min(max(self.VBE + ib_t * (c.beta + 1.0) * re_eff, 0.05), max(c.VCC - 0.05, 0.1))
                r1_t = c.R2 * ((c.VCC / vth_t) - 1.0)
                if r1_t > 0:
                    suggestions.append(f"De xuat R1 = {r1_t:.0f}Ohm de VCE ~ VCC/2")

        passed = len(errors) == 0
        (logger.info if passed else logger.warning)(
            "DC validation %s%s", "passed" if passed else "failed: ", "" if passed else errors
        )
        return DCValidationResult(passed=passed, errors=errors, suggestions=suggestions, metrics=metrics)


    def validate_opamp_inverting(self, Rf: float, Rin: float, gain_target: float) -> DCValidationResult:
        # Kiem tra do loi cho op-amp inverting theo ty le Rf/Rin.
        errors: List[str] = []
        suggestions: List[str] = []

        if Rin <= 0 or Rf <= 0:
            errors.append("Rf va Rin phai lon hon 0")
            return DCValidationResult(passed=False, errors=errors, suggestions=[], metrics={})
        if gain_target <= 0:
            errors.append("gain_target cho op-amp phai lon hon 0")
            return DCValidationResult(passed=False, errors=errors, suggestions=[], metrics={})

        av_actual = -Rf / Rin
        rel_err = abs(abs(av_actual) - gain_target) / gain_target
        metrics = {
            "Av_actual": float(av_actual),
            "gain_abs": abs(av_actual),
            "gain_rel_error": rel_err,
        }

        if rel_err > self.GAIN_TOLERANCE:
            errors.append(
                f"|Rf/Rin|={abs(av_actual):.3f} lech muc tieu {gain_target:.3f} "
                f"qua {self.GAIN_TOLERANCE * 100:.0f}%"
            )
            suggestions.append(f"De xuat Rf = {gain_target * Rin:.0f}Ohm (voi Rin={Rin:.0f}Ohm)")

        return DCValidationResult(
            passed=len(errors) == 0, errors=errors,
            suggestions=suggestions, metrics=metrics,
        )

    def validate_output_swing(self,c: ComponentSet,gain_target: Optional[float],*,vss: Optional[float] = None,vin_peak: Optional[float] = None,vout_required: Optional[float] = None,) -> DCValidationResult:
        # Kiem tra swing dau ra theo vat ly thuc te — ap dung cho MOI ho linh kien.
        # BJT CE/CB/CC, FET CS/CD/CG, Op-amp, Class A/AB/B/C/D, Darlington, Multi-stage đều dùng chung hàm này.
        errors: List[str] = []
        suggestions: List[str] = []

        if c.VCC <= 0:
            errors.append(f"VCC phai lon hon 0V (nhan duoc: {c.VCC}V)")
            return DCValidationResult(passed=False, errors=errors, suggestions=suggestions, metrics={})

        # 1. Dropout theo topology
        topology = self._normalize_topology(c.topology)
        # FIX 1: dùng self.SWING_DROPOUT (không có dấu gạch đầu)
        # FIX 4: tra _TOPO_TO_DROPOUT_KEY là class attr, không phải local var
        dropout_key = self._TOPO_TO_DROPOUT_KEY.get(topology, "opamp_standard")
        dropout_hi, dropout_lo = self.SWING_DROPOUT[dropout_key]

        # 2. Max swing theo cấu hình nguồn
        if vss is not None and vss > 0:
            max_swing = min(
                max(c.VCC - dropout_hi, 0.0),
                max(vss   - dropout_lo, 0.0),
            )
            supply_desc = f"±{c.VCC}V"
        else:
            max_swing = max((c.VCC - dropout_hi - dropout_lo) / 2.0, 0.0)
            supply_desc = f"{c.VCC}V"

        # 3. Vout yêu cầu
        if vout_required is not None:
            v_req = abs(float(vout_required))
            v_req_src = "IR"
        elif vin_peak is not None and gain_target and gain_target > 0:
            v_req = abs(float(vin_peak)) * float(gain_target)
            v_req_src = f"|Vin|×|Av|={vin_peak}V×{gain_target}"
        else:
            v_req = 0.0
            v_req_src = "unknown"
            if gain_target and gain_target > 0:
                suggestions.append(
                    "Khong co Vin de tinh Vout_required — "
                    "swing check bi bo qua, chi xac nhan VCC hop le"
                )

        metrics: Dict[str, float] = {
            "VCC": float(c.VCC),
            "VSS_abs": float(vss) if vss is not None else 0.0,
            "dropout_hi": float(dropout_hi),
            "dropout_lo": float(dropout_lo),
            "max_swing": float(max_swing),
            "vout_required": float(v_req),
        }

        logger.debug(
            "[swing] topology=%s key=%s supply=%s dropout=(%.2f,%.2f) "
            "max_swing=%.3fV vout_req=%.3fV src=%s",
            topology, dropout_key, supply_desc,
            dropout_hi, dropout_lo, max_swing, v_req, v_req_src,
        )

        # 4. Kiểm tra
        if max_swing <= 0:
            errors.append(
                f"Nguon cap qua thap (VCC={c.VCC}V, supply={supply_desc}): "
                f"khong du swing sau dropout {dropout_hi}V+{dropout_lo}V"
            )
            suggestions.append(
                f"Tang VCC len it nhat {dropout_hi + dropout_lo + 1.0:.1f}V"
            )
        elif v_req > 0 and v_req > max_swing:
            errors.append(
                f"Output clipping [{topology}]: "
                f"Vout_yeu_cau={v_req:.3f}V > max_swing={max_swing:.3f}V "
                f"(supply={supply_desc}, dropout={dropout_hi}V/{dropout_lo}V)"
            )
            suggestions.append(
                f"Tang VCC len it nhat {v_req + dropout_hi:.1f}V "
                f"hoac chon linh kien co dropout thap hon"
            )

        return DCValidationResult(
            passed=len(errors) == 0,
            errors=errors, suggestions=suggestions, metrics=metrics,
        )

    def validate_by_topology(self,c: ComponentSet,gain_target: Optional[float],*,vss: Optional[float] = None,vin_peak: Optional[float] = None,vout_required: Optional[float] = None,) -> DCValidationResult:
        # Dispatch validate dung theo topology. self._TOPO_TO_DROPOUT_KEY thay vì local var.
        topology = self._normalize_topology(c.topology)
        swing_kwargs = dict(vss=vss, vin_peak=vin_peak, vout_required=vout_required)
       
        # ── BJT CE/CB/CC + Darlington: DC bias đầy đủ + swing ──
        if topology in {"common_emitter", "common_base", "common_collector", "darlington"}:
            result = self.validate(c, gain_target)
            swing = self.validate_output_swing(c, gain_target, **swing_kwargs)
            result.errors.extend(swing.errors)
            result.suggestions.extend(swing.suggestions)
            result.metrics.update(swing.metrics)
            result.passed = len(result.errors) == 0
            return result

        # ── Op-amp inverting/non-inverting: Rf/Rin ratio + swing ──
        if topology in {"inverting", "non_inverting"}:
            rf  = c.RC
            rin = c.RE if c.RE > 0 else c.R2
            resolved_gain = (
                gain_target if gain_target is not None
                else max(abs(rf / rin) if rin > 0 else 1.0, 1.0)
            )
            result = self.validate_opamp_inverting(Rf=rf, Rin=rin, gain_target=resolved_gain)
            swing = self.validate_output_swing(c, resolved_gain, **swing_kwargs)
            result.errors.extend(swing.errors)
            result.suggestions.extend(swing.suggestions)
            result.metrics.update(swing.metrics)
            result.passed = len(result.errors) == 0
            return result
        
        # Mọi topology còn lại: chỉ swing check
        # differential, instrumentation, FET CS/CD/CG, class_a/ab/b/c/d, multi_stage
        if topology in self._TOPO_TO_DROPOUT_KEY:
            return self.validate_output_swing(c, gain_target, **swing_kwargs)
        
        # ── Topology chưa map được: skip + warning, không block pipeline ──
        warning = (
            f"Topology '{c.topology}' chua co rule DC, bo qua DC-bias check. "
            f"Co rule day du: {', '.join(sorted(self.SUPPORTED_TOPOLOGIES))}"
        )
        logger.warning(warning)
        return DCValidationResult(
            passed=True, errors=[],
            suggestions=[warning],
            metrics={"topology_supported": 0.0, "dc_bias_skipped": 1.0},
        )
