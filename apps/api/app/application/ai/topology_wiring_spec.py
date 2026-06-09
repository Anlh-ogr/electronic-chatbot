"""Single source of truth for BJT/Op-Amp topology wiring characteristics.

All downstream consumers (LLM prompt, IR validation, wiring repair, rule engine)
derive their topology knowledge from these dataclasses.  Adding a new topology or
changing a wiring rule requires only editing this file.

Topology coverage
-----------------
BJT NPN  : common_emitter (CE), common_base (CB), common_collector (CC)
Op-Amp   : opamp_inverting (INV), opamp_non_inverting (NON), opamp_differential (DIFF)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WiringHallmark:
    """A single must-be-true structural property of the wired circuit."""
    code: str                   # machine-readable error code when violated
    description: str            # human-readable explanation
    severity: str = "error"     # "error" | "warning"


@dataclass(frozen=True)
class TopoWiringSpec:
    """Wiring specification for one amplifier topology."""
    family: str                         # canonical key used throughout the system
    device_type: str                    # "bjt_npn" | "opamp_ic"
    phase_inverted: bool                # True = 180° phase shift output vs input
    gain_formula: str                   # e.g. "Av = -RC / (re + RE)"
    gain_sign: str                      # "negative" | "positive" | "unity"
    zin_char: str                       # "very_high" | "high" | "medium" | "low" | "very_low"
    zout_char: str                      # same scale
    typical_use: str                    # one-line description

    # Structural wiring facts (used by LLM prompt, validation, repair)
    signal_in_pin: str                  # physical pin where AC signal enters, e.g. "Q1:B"
    signal_out_pin: str                 # physical pin where AC signal exits, e.g. "Q1:C"
    shared_pin: str                     # pin/terminal that is AC-grounded (the "common" one)
    shared_pin_ac_ground: bool          # True → shared_pin must be bypassed to GND for AC

    # Component inventory (minimum required, in addition to VCC/GND)
    required_resistors: Tuple[str, ...]
    required_coupling_caps: Tuple[str, ...]
    required_bypass_caps: Tuple[str, ...]

    # Ordered wiring instructions for LLM prompt (rule text)
    wiring_instructions: Tuple[str, ...]

    # Machine-checkable hallmarks for IR validation
    hallmarks: Tuple[WiringHallmark, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Topology definitions
# ---------------------------------------------------------------------------


TOPOLOGY_SPECS: Dict[str, TopoWiringSpec] = {

    # ── BJT: Common Emitter ────────────────────────────────────────────────
    "common_emitter": TopoWiringSpec(
        family="common_emitter",
        device_type="bjt_npn",
        phase_inverted=True,
        gain_formula="Av = -RC / (re + RE)",
        gain_sign="negative",
        zin_char="medium",
        zout_char="medium",
        typical_use="High voltage+current gain; general-purpose small-signal amplifier",
        signal_in_pin="Q1:B",
        signal_out_pin="Q1:C",
        shared_pin="Q1:E",
        shared_pin_ac_ground=True,    # CE capacitor bypasses RE to GND for AC
        required_resistors=("RB1", "RB2", "RC", "RE"),
        required_coupling_caps=("CIN", "COUT"),
        required_bypass_caps=("CE",),
        wiring_instructions=(
            "Signal enters at Base via CIN: CIN:1 → IN_SIG, CIN:2 → BASE_Q1.",
            "Q1:B → BASE_Q1 (shared by RB1:2 and RB2:1 and CIN:2).",
            "Q1:C → COLLECTOR_Q1 (shared by RC:2 and COUT:1). Output taken from collector.",
            "Q1:E → EMITTER_Q1 (shared by RE1:1). RE1 and RE2 in series for DC stability.",
            "Emitter bypass: CE:1 → EMITTER_Q1, CE:2 → 0. CE short-circuits RE2 for AC → full gain.",
            "COUT:1 → COLLECTOR_Q1, COUT:2 → OUT_SIG.",
            "Phase: output is INVERTED 180° relative to input (Av is negative).",
        ),
        hallmarks=(
            WiringHallmark(
                code="bjt.ce.Q1_C_must_not_connect_directly_to_supply_rail_use_RC",
                description="CE: Q1:C must have RC load to VCC, not connect directly to supply rail.",
            ),
            WiringHallmark(
                code="bjt.ce.CIN2_must_share_net_with_Q1_B",
                description="CE: CIN:2 must connect to Q1:B (signal enters at Base).",
            ),
        ),
    ),

    # ── BJT: Common Base ──────────────────────────────────────────────────
    "common_base": TopoWiringSpec(
        family="common_base",
        device_type="bjt_npn",
        phase_inverted=False,
        gain_formula="Av = RC / re",
        gain_sign="positive",
        zin_char="very_low",
        zout_char="medium",
        typical_use="Low Zin, high bandwidth RF/wideband amplifier; minimises Miller effect",
        signal_in_pin="Q1:E",
        signal_out_pin="Q1:C",
        shared_pin="Q1:B",
        shared_pin_ac_ground=True,    # CB capacitor bypasses Base to GND for AC
        required_resistors=("RB1", "RB2", "RC", "RE"),
        required_coupling_caps=("CIN", "COUT"),
        required_bypass_caps=("CB",),
        wiring_instructions=(
            "Signal enters at Emitter via CIN: CIN:1 → IN_SIG, CIN:2 → EMITTER_Q1.",
            "Q1:E → EMITTER_Q1 (shared by CIN:2 and RE:1).",
            "Base is the COMMON terminal: Q1:B → BASE_Q1 (shared by RB1:2, RB2:1).",
            "MANDATORY base-bypass capacitor: CB:1 → BASE_Q1, CB:2 → 0. "
            "Without CB the Base is not AC-grounded and the stage is NOT common-base.",
            "Q1:C → COLLECTOR_Q1 (shared by RC:2 and COUT:1). Output taken from Collector.",
            "COUT:1 → COLLECTOR_Q1, COUT:2 → OUT_SIG.",
            "Phase: output is NON-INVERTED (same phase) relative to input.",
        ),
        hallmarks=(
            WiringHallmark(
                code="bjt.cb.missing_base_bypass_capacitor_to_GND",
                description="CB: mandatory capacitor between Q1:B and GND (0) is missing.",
            ),
            WiringHallmark(
                code="bjt.cb.CIN2_must_share_net_with_Q1_E_emitter",
                description="CB: CIN:2 must connect to Q1:E (signal enters at Emitter, NOT Base).",
            ),
        ),
    ),

    # ── BJT: Common Collector ─────────────────────────────────────────────
    "common_collector": TopoWiringSpec(
        family="common_collector",
        device_type="bjt_npn",
        phase_inverted=False,
        gain_formula="Av ≈ RE / (re + RE) ≈ 1",
        gain_sign="unity",
        zin_char="very_high",
        zout_char="very_low",
        typical_use="Voltage buffer / impedance matcher; Av ≈ 1 (emitter follower)",
        signal_in_pin="Q1:B",
        signal_out_pin="Q1:E",
        shared_pin="Q1:C",
        shared_pin_ac_ground=True,    # Collector ties to VCC (AC ground)
        required_resistors=("RB1", "RB2", "RE"),
        required_coupling_caps=("CIN", "COUT"),
        required_bypass_caps=(),       # no bypass cap needed
        wiring_instructions=(
            "Signal enters at Base via CIN: CIN:1 → IN_SIG, CIN:2 → BASE_Q1.",
            "Q1:B → BASE_Q1 (shared by RB1:2, RB2:1, CIN:2).",
            "Collector is the COMMON terminal: Q1:C MUST connect directly to VCC. "
            "DO NOT place any collector load resistor (no RC) between Q1:C and VCC.",
            "Q1:E → EMITTER_Q1 (shared by RE:1 and COUT:1). Output taken from Emitter.",
            "COUT:1 → EMITTER_Q1, COUT:2 → OUT_SIG.",
            "Phase: output is NON-INVERTED (same phase), Av ≈ 1.",
        ),
        hallmarks=(
            WiringHallmark(
                code="bjt.cc.Q1_C_must_connect_directly_to_supply_rail",
                description="CC: Q1:C must be tied directly to VCC (no RC load).",
            ),
            WiringHallmark(
                code="bjt.cc.Q1_E_must_not_connect_directly_to_ground_use_RE",
                description="CC: Q1:E must connect to RE (not directly to GND).",
            ),
        ),
    ),

    # ── Op-Amp: Inverting ─────────────────────────────────────────────────
    "opamp_inverting": TopoWiringSpec(
        family="opamp_inverting",
        device_type="opamp_ic",
        phase_inverted=True,
        gain_formula="Av = -Rf / Rin",
        gain_sign="negative",
        zin_char="medium",            # Zin = Rin
        zout_char="very_low",
        typical_use="Inverting gain; summing amplifier; sign inversion",
        signal_in_pin="U1:-",
        signal_out_pin="U1:OUT",
        shared_pin="U1:+",
        shared_pin_ac_ground=True,    # non-inverting input tied to GND
        required_resistors=("RIN", "RF"),
        required_coupling_caps=(),     # DC-coupled; no signal-path AC caps
        required_bypass_caps=(),
        wiring_instructions=(
            "Signal path is DC-coupled — DO NOT add CIN/COUT AC coupling caps.",
            "U1:+ → 0 (non-inverting input tied directly to ground reference).",
            "RIN:1 → IN_SIG, RIN:2 → U1_INV_IN (virtual ground summing junction).",
            "RF:1 → OUT_SIG (feedback FROM output), RF:2 → U1_INV_IN.",
            "U1:- → U1_INV_IN. U1:OUT → OUT_SIG.",
            "Av = -Rf/Rin. Phase: output INVERTED 180° relative to input.",
        ),
        hallmarks=(
            WiringHallmark(
                code="opamp.inv.U1_plus_must_be_grounded",
                description="INV: U1:+ must connect to GND (0).",
            ),
            WiringHallmark(
                code="opamp.inv.RF1_must_share_OUT_SIG",
                description="INV: RF:1 must be on OUT_SIG net (feedback from output).",
            ),
        ),
    ),

    # ── Op-Amp: Non-Inverting ─────────────────────────────────────────────
    "opamp_non_inverting": TopoWiringSpec(
        family="opamp_non_inverting",
        device_type="opamp_ic",
        phase_inverted=False,
        gain_formula="Av = 1 + Rf / Rg",
        gain_sign="positive",
        zin_char="very_high",         # Zin = op-amp input impedance
        zout_char="very_low",
        typical_use="Non-inverting gain; sensor amplifier; high-impedance buffer",
        signal_in_pin="U1:+",
        signal_out_pin="U1:OUT",
        shared_pin="U1:-",
        shared_pin_ac_ground=False,   # inverting input feeds feedback network, not GND
        required_resistors=("RG", "RF"),
        required_coupling_caps=(),
        required_bypass_caps=(),
        wiring_instructions=(
            "Signal path is DC-coupled — DO NOT add CIN/COUT AC coupling caps.",
            "U1:+ → IN_SIG (signal into non-inverting input).",
            "U1:- → U1_INV_IN (connected to feedback divider).",
            "RG:1 → 0, RG:2 → U1_INV_IN.",
            "RF:1 → OUT_SIG, RF:2 → U1_INV_IN.",
            "U1:OUT → OUT_SIG.",
            "Av = 1 + Rf/Rg. Phase: output NON-INVERTED (same phase).",
        ),
        hallmarks=(
            WiringHallmark(
                code="opamp.non_inv.U1_plus_must_be_IN_SIG",
                description="NON-INV: U1:+ must connect to IN_SIG (not GND).",
            ),
        ),
    ),

    # ── Op-Amp: Differential ─────────────────────────────────────────────
    "opamp_differential": TopoWiringSpec(
        family="opamp_differential",
        device_type="opamp_ic",
        phase_inverted=False,         # amplifies difference V2-V1
        gain_formula="Av = R2 / R1  (when R1=R3, R2=R4)",
        gain_sign="positive",
        zin_char="medium",
        zout_char="very_low",
        typical_use="Difference amplifier; rejects common-mode noise; measurement/instrumentation",
        signal_in_pin="U1:+",         # V2 (non-inverting) and U1:- (V1) both used
        signal_out_pin="U1:OUT",
        shared_pin="",
        shared_pin_ac_ground=False,
        required_resistors=("R1", "R2", "R3", "R4"),
        required_coupling_caps=(),
        required_bypass_caps=(),
        wiring_instructions=(
            "Signal path is DC-coupled — DO NOT add AC coupling caps.",
            "V1 (inverting input): R1:1 → IN_MINUS_SIG, R1:2 → U1_INV_IN.",
            "Feedback: R2:1 → U1_INV_IN, R2:2 → OUT_SIG.",
            "V2 (non-inverting input): R3:1 → IN_PLUS_SIG, R3:2 → U1_NON_INV_IN.",
            "Ground divider: R4:1 → U1_NON_INV_IN, R4:2 → 0.",
            "U1:- → U1_INV_IN. U1:+ → U1_NON_INV_IN. U1:OUT → OUT_SIG.",
            "MUST satisfy R1 = R3 (input pair) AND R2 = R4 (feedback pair) for balanced gain.",
            "Av_diff = R2/R1. Amplifies only the difference (V2 - V1).",
        ),
        hallmarks=(
            WiringHallmark(
                code="opamp.diff.R1_R3_must_be_equal",
                description="DIFF: R1 = R3 (input resistors must match for CMRR).",
                severity="warning",
            ),
            WiringHallmark(
                code="opamp.diff.R2_R4_must_be_equal",
                description="DIFF: R2 = R4 (feedback resistors must match for CMRR).",
                severity="warning",
            ),
        ),
    ),
}


# ---------------------------------------------------------------------------
# Alias resolution
# ---------------------------------------------------------------------------

_ALIASES: Dict[str, str] = {
    "ce": "common_emitter",
    "common-emitter": "common_emitter",
    "cb": "common_base",
    "common-base": "common_base",
    "cc": "common_collector",
    "common-collector": "common_collector",
    "emitter_follower": "common_collector",
    "emitter-follower": "common_collector",
    "inverting": "opamp_inverting",
    "inv": "opamp_inverting",
    "opamp_inv": "opamp_inverting",
    "non_inverting": "opamp_non_inverting",
    "non-inverting": "opamp_non_inverting",
    "noninverting": "opamp_non_inverting",
    "non_inv": "opamp_non_inverting",
    "differential": "opamp_differential",
    "diff": "opamp_differential",
    "vi_sai": "opamp_differential",
}


def get_spec(family: str) -> Optional[TopoWiringSpec]:
    """Return the TopoWiringSpec for *family* (or its alias), or None."""
    key = str(family).strip().lower().replace(" ", "_").replace("-", "_")
    canonical = _ALIASES.get(key, key)
    return TOPOLOGY_SPECS.get(canonical)


def all_families() -> List[str]:
    return list(TOPOLOGY_SPECS.keys())


def bjt_families() -> List[str]:
    return [f for f, s in TOPOLOGY_SPECS.items() if s.device_type == "bjt_npn"]


def opamp_families() -> List[str]:
    return [f for f, s in TOPOLOGY_SPECS.items() if s.device_type == "opamp_ic"]


# ---------------------------------------------------------------------------
# LLM prompt helpers
# ---------------------------------------------------------------------------

def build_wiring_rules_block(families: Optional[List[str]] = None) -> str:
    """Return numbered wiring rules text suitable for injection into an LLM system prompt."""
    targets = families if families else list(TOPOLOGY_SPECS.keys())
    lines: List[str] = []
    rule_num = 17
    for fam in targets:
        spec = TOPOLOGY_SPECS.get(fam)
        if spec is None:
            continue
        label = fam.replace("_", " ").title()
        lines.append(f"            {rule_num}. For {fam} ({label}):")
        for instr in spec.wiring_instructions:
            lines.append(f"            - {instr}")
        rule_num += 1
    return "\n".join(lines)


def build_inventory_block() -> str:
    """Return the EXPECTED COMPONENT INVENTORY section for the LLM prompt."""
    lines: List[str] = []
    for fam, spec in TOPOLOGY_SPECS.items():
        r = ", ".join(spec.required_resistors) if spec.required_resistors else "—"
        cin = ", ".join(spec.required_coupling_caps) if spec.required_coupling_caps else "none"
        byp = ", ".join(spec.required_bypass_caps) if spec.required_bypass_caps else "none"
        dev = "1×bjt_npn (Q1)" if spec.device_type == "bjt_npn" else "1×opamp_ic (U1)"
        cap_note = f"coupling: ({cin}), bypass: ({byp})"
        lines.append(f"            - {fam}: {dev} + resistors ({r}) + caps [{cap_note}] + 1×power_supply + 1×ground")
    return "\n".join(lines)
