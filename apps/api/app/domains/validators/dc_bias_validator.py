from __future__ import annotations

"""Domain validator cho phan cuc DC va do loi co ban.

Module nay nam o tang Domain, khong goi LLM va khong phu thuoc vao ngspice.
"""

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
        """Chuyen doi bo linh kien thanh dict de log/serialize."""
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
    }
    SUPPLY_COMPONENT_TYPES = {
        "VCC",
        "VDD",
        "VEE",
        "POWER",
        "POWER_SUPPLY",
        "PWR_FLAG",
        "VOLTAGE_SOURCE",
        "VSOURCE",
    }

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
            voltage = abs(float(value))
            return voltage if voltage > 1.0 else None
        if not isinstance(value, str):
            return None

        text = value.strip().replace("±", "")
        if not text:
            return None

        match = re.search(r"([+-]?\d+(?:\.\d+)?)(\s*(mv|v))?\b", text, flags=re.IGNORECASE)
        if not match:
            return None

        voltage = abs(float(match.group(1)))
        unit = (match.group(3) or "v").lower()
        if unit == "mv":
            voltage /= 1000.0
        return voltage if voltage > 1.0 else None

    @staticmethod
    def _has_bjt_topology_hint(topology: str) -> bool:
        hint = (topology or "").strip().lower()
        return any(
            token in hint
            for token in (
                "common_emitter",
                "common_base",
                "common_collector",
                "multi_stage",
                "darlington",
                "class_a",
                "class_ab",
                "class_b",
                "class_c",
            )
        )

    @classmethod
    def _extract_topology_hint(cls, ir: Any) -> str:
        candidates = [
            cls._get_field(ir, "topology"),
            cls._get_field(ir, "circuit_type"),
            cls._get_field(ir, "device_preference"),
            cls._get_field(cls._get_field(ir, "analysis"), "topology_classification"),
            cls._get_field(cls._get_field(ir, "architecture"), "topology_type"),
        ]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip().lower()
        return ""

    @classmethod
    def _default_vcc_for_topology(cls, topology: str) -> float:
        return 12.0 if cls._has_bjt_topology_hint(topology) else 15.0

    def _extract_vcc(self, ir: Any) -> float:
        """Extract VCC from a CircuitIR-like payload with sane fallbacks.

        Priority:
        1. power_supply.voltage
        2. architecture.stages.active_device_vcc
        3. power-supply components in the components list
        4. analysis/design_specs or calculations mentioning supply/VCC
        5. default 15.0V for op-amp-style requests, 12.0V for BJT-style requests
        """

        topology = self._extract_topology_hint(ir)

        power_supply = self._get_field(ir, "power_supply")
        voltage = self._coerce_voltage(self._get_field(power_supply, "voltage"))
        if voltage is not None:
            return voltage

        architecture = self._get_field(ir, "architecture")
        stages = self._get_field(architecture, "stages", [])
        if isinstance(stages, list):
            for stage in stages:
                voltage = self._coerce_voltage(self._get_field(stage, "active_device_vcc"))
                if voltage is not None:
                    return voltage

        components = self._get_field(ir, "components", [])
        if isinstance(components, list):
            for component in components:
                component_type = str(self._get_field(component, "type", "")).strip().upper()
                if component_type not in self.SUPPLY_COMPONENT_TYPES:
                    continue
                for field_name in ("voltage", "value", "vcc", "vdd"):
                    voltage = self._coerce_voltage(self._get_field(component, field_name))
                    if voltage is not None:
                        return voltage
                parameters = self._get_field(component, "parameters", {})
                if isinstance(parameters, dict):
                    for field_name in ("voltage", "value", "vcc", "vdd"):
                        voltage = self._coerce_voltage(parameters.get(field_name))
                        if voltage is not None:
                            return voltage

        analysis = self._get_field(ir, "analysis")
        for spec_list_name in ("design_specs", "calculations_table", "calculations"):
            specs = self._get_field(analysis, spec_list_name, [])
            if not isinstance(specs, list):
                continue
            for spec in specs:
                parameter = str(self._get_field(spec, "parameter", self._get_field(spec, "name", ""))).strip().lower()
                if not parameter or not any(token in parameter for token in ("supply", "vcc", "vdd", "vss", "rail")):
                    continue
                for field_name in ("value", "voltage", "calculated_value"):
                    voltage = self._coerce_voltage(self._get_field(spec, field_name))
                    if voltage is not None:
                        return voltage

        return self._default_vcc_for_topology(topology)

    def validate(self, c: ComponentSet, gain_target: Optional[float]) -> DCValidationResult:
        """Kiem tra phan cuc DC cho cau hinh BJT co mang chia ap base."""
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
                passed=False,
                errors=errors,
                suggestions=["Kiem tra lai gia tri linh kien dau vao"],
                metrics={},
            )

        vth = c.VCC * (c.R2 / (c.R1 + c.R2))
        rth = (c.R1 * c.R2) / (c.R1 + c.R2)

        ib = (vth - self.VBE) / (rth + (c.beta + 1.0) * re_eff)
        if ib < 0:
            ib = 0.0

        ic = c.beta * ib
        ie = (c.beta + 1.0) * ib
        vce = c.VCC - (ic * c.RC) - (ie * re_eff)

        av_actual = 0.0
        if ic > 0:
            re_small_signal = 0.026 / ic
            if re_small_signal > 0:
                topology = (c.topology or "").strip().lower()
                if topology == "common_collector":
                    av_actual = re_eff / (re_eff + re_small_signal)
                elif topology == "common_base":
                    av_actual = c.RC / re_small_signal
                else:
                    re_ac = max(re_eff, self.RE_AC_MIN_OHM)
                    av_actual = c.RC / (re_small_signal + re_ac)

        metrics: Dict[str, float] = {
            "VTH": float(vth),
            "RTH": float(rth),
            "IB_uA": float(ib * 1e6),
            "IC_mA": float(ic * 1e3),
            "IE_mA": float(ie * 1e3),
            "VCE": float(vce),
            "Av_actual": float(av_actual),
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
                f"Q-point lech, VCE={vce:.3f}V khong nam trong VCC/2 +- 40% ({q_center - q_band:.3f}..{q_center + q_band:.3f}V)"
            )

        ib_ua = ib * 1e6
        if ib_ua < self.IB_MIN_UA:
            errors.append(f"IB={ib_ua:.3f}uA < IB_MIN_UA={self.IB_MIN_UA:.3f}uA")
            suggestions.append("Giam R1/R2 hoac tang dong chia ap de tang IB")

        if gain_target is not None and gain_target > 0:
            rel_err = abs(av_actual - gain_target) / gain_target if gain_target != 0 else 0.0
            metrics["gain_rel_error"] = float(rel_err)
            if rel_err > self.GAIN_TOLERANCE:
                errors.append(
                    f"Do loi thuc te Av={av_actual:.3f} lech muc tieu {gain_target:.3f} qua {self.GAIN_TOLERANCE * 100:.0f}%"
                )
                if ic > 0:
                    re_small_signal = 0.026 / ic
                    rc_target = gain_target * (re_small_signal + max(re_eff, self.RE_AC_MIN_OHM))
                    suggestions.append(f"De xuat RC = {rc_target:.0f}Ohm de dat Av={gain_target:.3f}")

                    re_target = (c.RC / max(gain_target, 1e-9)) - re_small_signal
                    if re_target > self.RE_AC_MIN_OHM:
                        suggestions.append(
                            f"De xuat RE ~= {re_target:.0f}Ohm (khong bypass hoan toan) de Av gan {gain_target:.3f}"
                        )

        need_recenter = any("VCE" in e or "Q-point" in e for e in errors)
        if need_recenter:
            total_drop_res = c.RC + re_eff * (1.0 + 1.0 / max(c.beta, 1e-9))
            if total_drop_res > 0:
                ic_target = (c.VCC - (c.VCC / 2.0)) / total_drop_res
                ib_target = max(ic_target / c.beta, 1e-9)
                vth_target = self.VBE + ib_target * ((c.beta + 1.0) * re_eff)
                vth_target = min(max(vth_target, 0.05), max(c.VCC - 0.05, 0.1))
                r1_target = c.R2 * ((c.VCC / vth_target) - 1.0)
                if r1_target > 0:
                    suggestions.append(f"De xuat R1 = {r1_target:.0f}Ohm de VCE ~ VCC/2")

        passed = len(errors) == 0
        if passed:
            logger.info("DC validation passed")
        else:
            logger.warning("DC validation failed: %s", errors)

        return DCValidationResult(
            passed=passed,
            errors=errors,
            suggestions=suggestions,
            metrics=metrics,
        )

    def validate_opamp_inverting(self, Rf: float, Rin: float, gain_target: float) -> DCValidationResult:
        """Kiem tra do loi cho cau hinh op-amp inverting theo ty le Rf/Rin."""
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
            "gain_abs": float(abs(av_actual)),
            "gain_rel_error": float(rel_err),
        }

        if rel_err > self.GAIN_TOLERANCE:
            errors.append(
                f"|Rf/Rin|={abs(av_actual):.3f} lech muc tieu {gain_target:.3f} qua {self.GAIN_TOLERANCE * 100:.0f}%"
            )
            suggestions.append(f"De xuat Rf = {gain_target * Rin:.0f}Ohm (voi Rin={Rin:.0f}Ohm)")

        return DCValidationResult(
            passed=len(errors) == 0,
            errors=errors,
            suggestions=suggestions,
            metrics=metrics,
        )

    def validate_opamp_swing(self, c: ComponentSet, gain_target: Optional[float]) -> DCValidationResult:
        """Kiem tra swing dau ra co ban cho op-amp topology (khong dung VCE/Q-point BJT)."""
        errors: List[str] = []
        suggestions: List[str] = []

        if c.VCC <= 0:
            errors.append("VCC phai lon hon 0V")
            return DCValidationResult(passed=False, errors=errors, suggestions=suggestions, metrics={})

        # Rule of thumb for non rail-to-rail op-amp output swing.
        max_swing = max(c.VCC - 1.5, 0.0)
        vout_required = max(abs(float(gain_target or 2.0)) * 0.1, 0.0)

        metrics = {
            "VCC": float(c.VCC),
            "max_swing": float(max_swing),
            "vout_required": float(vout_required),
        }

        if max_swing <= 0:
            errors.append("Nguon cap qua thap de op-amp swing on dinh")
        elif vout_required > max_swing:
            errors.append(
                f"Op-amp output clipping: Vout_required={vout_required:.3f}V > max_swing={max_swing:.3f}V"
            )
            suggestions.append("Tang VCC hoac chon op-amp rail-to-rail")

        return DCValidationResult(
            passed=len(errors) == 0,
            errors=errors,
            suggestions=suggestions,
            metrics=metrics,
        )

    def validate_by_topology(self, c: ComponentSet, gain_target: Optional[float]) -> DCValidationResult:
        """Chon ham validate phu hop dua vao topology."""
        topology = (c.topology or "").strip().lower()
        topology_aliases = {
            "ci": "inverting",
            "ni": "non_inverting",
            "diff": "differential",
        }
        topology = topology_aliases.get(topology, topology)

        if topology not in self.SUPPORTED_TOPOLOGIES:
            warning = (
                f"Topology '{c.topology}' khong duoc ho tro boi DCBiasValidator, bo qua DC-bias check chi tiet"
            )
            suggestion = (
                "Topology co bo rule DC day du: " + ", ".join(sorted(self.SUPPORTED_TOPOLOGIES))
            )
            logger.warning(warning)
            return DCValidationResult(
                passed=True,
                errors=[],
                suggestions=[warning, suggestion],
                metrics={"topology_supported": 0.0, "dc_bias_skipped": 1.0},
            )

        if topology in {"common_emitter", "common_base", "common_collector"}:
            return self.validate(c, gain_target)

        if topology in {"inverting", "non_inverting"}:
            rf = c.RC
            rin = c.RE if c.RE > 0 else c.R2
            resolved_gain = gain_target if gain_target is not None else max(abs(rf / rin), 1.0)
            return self.validate_opamp_inverting(Rf=rf, Rin=rin, gain_target=resolved_gain)

        if topology in {"differential", "instrumentation"}:
            return self.validate_opamp_swing(c, gain_target)

        return DCValidationResult(
            passed=False,
            errors=[f"Topology '{c.topology}' khong co bo rule phu hop"],
            suggestions=["Kiem tra lai mapping topology va tham so component"],
            metrics={"topology_supported": 0.0},
        )
