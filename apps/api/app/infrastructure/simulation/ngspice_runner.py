from __future__ import annotations

"""Infrastructure runner de mo phong ngspice va phan tich dang song.

Module nay chi do luong va bao cao, khong quyet dinh thiet ke.
"""

import logging
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from statistics import median
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from app.domain.validators.dc_bias_validator import ComponentSet

logger = logging.getLogger(__name__)


@dataclass
class SimulationConfig:
    """Thong so mo phong transient."""

    vin_amplitude: float = 0.01
    frequency: float = 1000.0
    duration_cycles: int = 5
    step_size_factor: float = 0.01


@dataclass
class SimResult:
    """Ket qua mo phong va danh gia dang song."""

    passed: bool
    errors: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    waveform_data: Dict[str, List[float]] = field(default_factory=dict)
    metrics: Dict[str, float] = field(default_factory=dict)
    netlist_used: str = ""


class NgspiceRunner:
    """Infrastructure layer de chay ngspice va phan tich ket qua."""

    CLIPPING_RATIO: float = 0.90
    THD_LIMIT_PCT: float = 5.0
    GAIN_TOLERANCE: float = 0.20

    def run(
        self,
        components: "ComponentSet",
        topology: str,
        gain_target: Optional[float],
        sim_config: Optional[SimulationConfig] = None,
        ngspice_path: str = "ngspice",
    ) -> SimResult:
        """Thuc thi pipeline build netlist -> run ngspice -> parse -> analyze."""
        cfg = sim_config or SimulationConfig()
        netlist = self._build_netlist(components=components, topology=topology, sim_config=cfg)

        raw_output = self._execute_ngspice(netlist=netlist, ngspice_path=ngspice_path)
        if raw_output is None:
            logger.warning("Ngspice khong san sang hoac khong nam trong PATH")
            return SimResult(
                passed=False,
                errors=["Ngspice not available"],
                suggestions=["Cai ngspice hoac kiem tra PATH"],
                waveform_data={},
                metrics={},
                netlist_used=netlist,
            )

        if raw_output.startswith("__NGSPICE_ERROR__"):
            err = raw_output.replace("__NGSPICE_ERROR__", "", 1).strip()
            return SimResult(
                passed=False,
                errors=[f"Ngspice execution failed: {err}"],
                suggestions=["Kiem tra netlist va model spice"],
                waveform_data={},
                metrics={},
                netlist_used=netlist,
            )

        waveform = self._parse_raw_output(raw_output)
        if not waveform.get("time") or not waveform.get("vin") or not waveform.get("vout"):
            return SimResult(
                passed=False,
                errors=["Khong parse duoc du lieu dang song tu ngspice"],
                suggestions=["Kiem tra node ten in/out trong netlist"],
                waveform_data=waveform,
                metrics={},
                netlist_used=netlist,
            )

        analyzed = self._analyze_waveform(waveform=waveform, components=components, gain_target=gain_target)
        analyzed.netlist_used = netlist
        return analyzed

    def _build_netlist(
        self,
        components: "ComponentSet",
        topology: str,
        sim_config: SimulationConfig,
    ) -> str:
        """Tao netlist SPICE theo topology co ban."""
        freq = max(sim_config.frequency, 1.0)
        step = 1.0 / (freq * max(1.0 / max(sim_config.step_size_factor, 1e-4), 10.0))
        stop = sim_config.duration_cycles / freq

        topo = (topology or components.topology or "common_emitter").strip().lower()
        vcc = max(components.VCC, 0.1)

        if topo in {"common_emitter", "common_base", "common_collector"}:
            return (
                "* CE Amplifier\n"
                f"VCC vcc 0 {vcc}\n"
                f"Vin in 0 SIN(0 {sim_config.vin_amplitude} {freq})\n"
                f"R1 vcc base {components.R1}\n"
                f"R2 base 0 {components.R2}\n"
                f"RC vcc col {components.RC}\n"
                f"RE emit 0 {max(components.RE, 1e-3)}\n"
                "Q1 col base emit BC547\n"
                "Cin in base 10u\n"
                f".model BC547 NPN(BF={max(components.beta, 10.0)})\n"
                f".tran {step:.9g} {stop:.9g}\n"
                ".control\n"
                "run\n"
                "set filetype=ascii\n"
                "wrdata __WAVEFORM_FILE__ time v(in) v(col)\n"
                "quit\n"
                ".endc\n"
                ".end\n"
            )

        if topo in {"inverting", "non_inverting"}:
            rin = max(components.RE if components.RE > 0 else components.R2, 100.0)
            rf = max(components.RC, 100.0)
            vref = vcc / 2.0
            return (
                "* Opamp inverting/non-inverting proxy\n"
                f"VCC vcc 0 {vcc}\n"
                "VEE vee 0 0\n"
                f"Vin in 0 SIN(0 {sim_config.vin_amplitude} {freq})\n"
                f"VREF vref 0 {vref}\n"
                "* Proxy model dung nguon phu thuoc de tranh phu thuoc model opamp\n"
                f"EOP out 0 VALUE = {{ (v(vref)-v(in))*({rf}/{rin}) + v(vref) }}\n"
                f"Rin in neg {rin}\n"
                f"Rf out neg {rf}\n"
                "Rbias neg vref 1e9\n"
                f".tran {step:.9g} {stop:.9g}\n"
                ".control\n"
                "run\n"
                "set filetype=ascii\n"
                "wrdata __WAVEFORM_FILE__ time v(in) v(out)\n"
                "quit\n"
                ".endc\n"
                ".end\n"
            )

        return (
            "* Generic pass-through topology\n"
            f"Vin in 0 SIN(0 {sim_config.vin_amplitude} {freq})\n"
            "E1 out 0 in 0 1\n"
            f".tran {step:.9g} {stop:.9g}\n"
            ".control\n"
            "run\n"
            "set filetype=ascii\n"
            "wrdata __WAVEFORM_FILE__ time v(in) v(out)\n"
            "quit\n"
            ".endc\n"
            ".end\n"
        )

    def _execute_ngspice(self, netlist: str, ngspice_path: str) -> Optional[str]:
        """Ghi netlist tam, chay ngspice batch mode va doc waveform text."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cir_path = os.path.join(temp_dir, "design.cir")
            wave_path = os.path.join(temp_dir, "waveform.out")

            rendered_netlist = netlist.replace("__WAVEFORM_FILE__", f'"{wave_path.replace("\\", "/")}"')
            with open(cir_path, "w", encoding="utf-8") as f:
                f.write(rendered_netlist)

            try:
                proc = subprocess.run(
                    [ngspice_path, "-b", cir_path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except FileNotFoundError:
                return None
            except subprocess.TimeoutExpired:
                return "__NGSPICE_ERROR__timeout after 30s"
            except Exception as exc:  # pragma: no cover
                return f"__NGSPICE_ERROR__{exc}"

            if proc.returncode != 0:
                message = (proc.stderr or proc.stdout or "unknown ngspice error").strip()
                return f"__NGSPICE_ERROR__{message}"

            if not os.path.exists(wave_path):
                message = (proc.stdout or "").strip()
                return f"__NGSPICE_ERROR__missing waveform output file. {message}"

            with open(wave_path, "r", encoding="utf-8", errors="ignore") as wf:
                return wf.read()

    def _parse_raw_output(self, raw_output: str) -> Dict[str, List[float]]:
        """Parse file wrdata cua ngspice thanh waveform dict."""
        time_values: List[float] = []
        vin_values: List[float] = []
        vout_values: List[float] = []

        for line in raw_output.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("*") or stripped.startswith("#"):
                continue

            parts = stripped.replace(",", " ").split()
            values: List[float] = []
            for token in parts:
                try:
                    values.append(float(token))
                except ValueError:
                    values = []
                    break

            if not values:
                continue

            if len(values) >= 6:
                # wrdata time vin vout thuong cho dang: x1 y1 x2 y2 x3 y3
                time_values.append(values[0])
                vin_values.append(values[3])
                vout_values.append(values[5])
            elif len(values) == 4:
                time_values.append(values[0])
                vin_values.append(values[1])
                vout_values.append(values[3])
            elif len(values) == 3:
                time_values.append(values[0])
                vin_values.append(values[1])
                vout_values.append(values[2])
            elif len(values) == 2:
                time_values.append(values[0])
                vin_values.append(values[1])
                vout_values.append(values[1])

        return {"time": time_values, "vin": vin_values, "vout": vout_values}

    def _analyze_waveform(
        self,
        waveform: Dict[str, List[float]],
        components: "ComponentSet",
        gain_target: Optional[float],
    ) -> SimResult:
        """Danh gia clipping, THD va do loi do duoc tu waveform."""
        time_values = waveform.get("time", [])
        vin_values = waveform.get("vin", [])
        vout_values = waveform.get("vout", [])

        errors: List[str] = []
        suggestions: List[str] = []

        if len(time_values) < 10 or len(vin_values) != len(vout_values):
            return SimResult(
                passed=False,
                errors=["Du lieu waveform khong hop le"],
                suggestions=["Tang thoi gian mo phong hoac giam buoc thoi gian"],
                waveform_data=waveform,
                metrics={},
            )

        vin_peak = max(abs(v) for v in vin_values)
        vout_dc = sum(vout_values) / len(vout_values)
        vout_ac = [v - vout_dc for v in vout_values]
        vout_peak = max(abs(v) for v in vout_ac)

        metrics: Dict[str, float] = {
            "vin_peak": float(vin_peak),
            "vout_peak": float(vout_peak),
            "vout_dc": float(vout_dc),
        }

        if vin_peak <= 1e-12:
            errors.append("Tin hieu vao qua nho, khong do duoc gain")
            return SimResult(
                passed=False,
                errors=errors,
                suggestions=["Tang bien do vin_amplitude trong SimulationConfig"],
                waveform_data=waveform,
                metrics=metrics,
            )

        gain_measured = vout_peak / vin_peak
        metrics["gain_measured"] = float(gain_measured)

        available_swing = max((components.VCC / 2.0) * self.CLIPPING_RATIO, 1e-6)
        if vout_peak > available_swing:
            errors.append(
                f"Co dau hieu clipping: vout_peak={vout_peak:.4f}V > {available_swing:.4f}V"
            )
            scale = available_swing / max(vout_peak, 1e-12)
            new_vin = max(vin_peak * scale * 0.9, 1e-4)
            suggestions.append(f"Giam Vin xuong {new_vin:.3f}V hoac chinh lai Q-point")

        dt_candidates = [
            time_values[i + 1] - time_values[i]
            for i in range(len(time_values) - 1)
            if time_values[i + 1] > time_values[i]
        ]
        sample_rate = 1.0 / median(dt_candidates) if dt_candidates else 0.0

        thd_ratio = self._calc_thd(vout_ac, sample_rate) if sample_rate > 0 else 0.0
        thd_pct = thd_ratio * 100.0
        metrics["thd_pct"] = float(thd_pct)

        if thd_pct > self.THD_LIMIT_PCT:
            errors.append(f"THD={thd_pct:.2f}% vuot nguong {self.THD_LIMIT_PCT:.2f}%")
            suggestions.append("Tang RE hoac giam RC de mo rong vung tuyen tinh")

        if gain_target is not None and gain_target > 0:
            gain_rel_error = abs(gain_measured - gain_target) / gain_target
            metrics["gain_rel_error"] = float(gain_rel_error)
            if gain_rel_error > self.GAIN_TOLERANCE:
                errors.append(
                    f"Gain do duoc {gain_measured:.3f} lech muc tieu {gain_target:.3f} qua {self.GAIN_TOLERANCE * 100:.0f}%"
                )
                if gain_measured > 1e-12:
                    rc_new = components.RC * (gain_target / gain_measured)
                    suggestions.append(
                        f"RC hien tai cho Av={gain_measured:.1f}, can RC={rc_new:.0f}Ohm"
                    )

        return SimResult(
            passed=len(errors) == 0,
            errors=errors,
            suggestions=suggestions,
            waveform_data=waveform,
            metrics=metrics,
        )

    def _calc_thd(self, signal: List[float], sample_rate: float) -> float:
        """Tinh THD bang FFT, tra ty le 0.0-1.0."""
        if not signal or sample_rate <= 0:
            return 0.0

        import numpy as np

        x = np.asarray(signal, dtype=float)
        if x.size < 16:
            return 0.0

        x = x - np.mean(x)
        if np.max(np.abs(x)) < 1e-15:
            return 0.0

        spectrum = np.fft.rfft(x)
        mags = np.abs(spectrum)
        if mags.size < 3:
            return 0.0

        mags[0] = 0.0
        fundamental_idx = int(np.argmax(mags))
        fundamental_amp = mags[fundamental_idx]
        if fundamental_idx <= 0 or fundamental_amp <= 1e-15:
            return 0.0

        harmonic_power = 0.0
        max_idx = mags.size - 1
        for h in range(2, 8):
            idx = fundamental_idx * h
            if idx > max_idx:
                break
            harmonic_power += float(mags[idx] ** 2)

        thd = math.sqrt(max(harmonic_power, 0.0)) / float(fundamental_amp)
        return float(max(thd, 0.0))
