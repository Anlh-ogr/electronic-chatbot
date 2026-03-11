"""
Script sinh tự động 72 file metadata cho templates_metadata/.
Đọc từng template JSON gốc → phân tích components, nets → sinh functional metadata.
KHÔNG sửa file template gốc.

Chạy: python generate_all_metadata.py
"""

import json
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent  # apps/api/resources
TEMPLATES_DIR = BASE_DIR / "templates"
METADATA_DIR = BASE_DIR / "templates_metadata"


# ============================================================
# TEMPLATE REGISTRY: mapping template_id -> file + domain info
# ============================================================
TEMPLATE_REGISTRY: List[Dict[str, Any]] = [
    # ── BJT CE ──
    {"template_id": "BJT-CE-01", "file": "bjt_ce_voltage_amplifier.json", "category": "bjt", "family": "common_emitter", "sub": "voltage_divider"},
    {"template_id": "BJT-CE-02", "file": "bjt_ce_fixed_bias_amplifier.json", "category": "bjt", "family": "common_emitter", "sub": "fixed_bias"},
    {"template_id": "BJT-CE-03", "file": "bjt_ce_fixed_bias_degen_amplifier.json", "category": "bjt", "family": "common_emitter", "sub": "fixed_bias_degen"},
    {"template_id": "BJT-CE-04", "file": "bjt_ce_degen_unbypass_amplifier.json", "category": "bjt", "family": "common_emitter", "sub": "degen_unbypassed"},
    {"template_id": "BJT-CE-05", "file": "bjt_ce_externally_biased_amplifier.json", "category": "bjt", "family": "common_emitter", "sub": "externally_biased"},
    {"template_id": "BJT-CE-06", "file": "bjt_ce_externally_biased_bypass_amplifier.json", "category": "bjt", "family": "common_emitter", "sub": "externally_biased_bypass"},
    # ── BJT CB ──
    {"template_id": "BJT-CB-01", "file": "bjt_cb_vdiv_bypass_amplifier.json", "category": "bjt", "family": "common_base", "sub": "voltage_divider_bypass"},
    {"template_id": "BJT-CB-02", "file": "bjt_cb_vdiv_nobypass_amplifier.json", "category": "bjt", "family": "common_base", "sub": "voltage_divider_nobypass"},
    {"template_id": "BJT-CB-03", "file": "bjt_cb_fixed_bias_bypass_amplifier.json", "category": "bjt", "family": "common_base", "sub": "fixed_bias_bypass"},
    {"template_id": "BJT-CB-04", "file": "bjt_cb_externally_biased_bypass_amplifier.json", "category": "bjt", "family": "common_base", "sub": "externally_biased_bypass"},
    # ── BJT CC ──
    {"template_id": "BJT-CC-01", "file": "bjt_cc_voltage_divider_bias_buffer.json", "category": "bjt", "family": "common_collector", "sub": "voltage_divider"},
    {"template_id": "BJT-CC-02", "file": "bjt_cc_voltage_divider_bias_nocout_buffer.json", "category": "bjt", "family": "common_collector", "sub": "voltage_divider_nocout"},
    {"template_id": "BJT-CC-03", "file": "bjt_cc_fixed_bias_buffer.json", "category": "bjt", "family": "common_collector", "sub": "fixed_bias"},
    {"template_id": "BJT-CC-04", "file": "bjt_cc_externally_biased_buffer.json", "category": "bjt", "family": "common_collector", "sub": "externally_biased"},
    # ── MOSFET CS ──
    {"template_id": "FET-CS-01", "file": "mosfet_cs_vdiv_bypass_amplifier.json", "category": "mosfet", "family": "common_source", "sub": "voltage_divider_bypass"},
    {"template_id": "FET-CS-02", "file": "mosfet_cs_vdiv_unbypassed_amplifier.json", "category": "mosfet", "family": "common_source", "sub": "voltage_divider_unbypassed"},
    {"template_id": "FET-CS-03", "file": "mosfet_cs_fixedgate_bypass_amplifier.json", "category": "mosfet", "family": "common_source", "sub": "fixed_gate_bypass"},
    {"template_id": "FET-CS-04", "file": "mosfet_cs_fixedgate_unbypassed_amplifier.json", "category": "mosfet", "family": "common_source", "sub": "fixed_gate_unbypassed"},
    {"template_id": "FET-CS-05", "file": "mosfet_cs_externally_biased_bypass_amplifier.json", "category": "mosfet", "family": "common_source", "sub": "externally_biased_bypass"},
    {"template_id": "FET-CS-06", "file": "mosfet_cs_externally_biased_ac_coupled_amplifier.json", "category": "mosfet", "family": "common_source", "sub": "externally_biased_ac"},
    # ── MOSFET CD ──
    {"template_id": "FET-CD-01", "file": "mosfet_cd_vdiv_buffer.json", "category": "mosfet", "family": "common_drain", "sub": "voltage_divider"},
    {"template_id": "FET-CD-02", "file": "mosfet_cd_vdiv_nocout_buffer.json", "category": "mosfet", "family": "common_drain", "sub": "voltage_divider_nocout"},
    {"template_id": "FET-CD-03", "file": "mosfet_cd_fixedgate_buffer.json", "category": "mosfet", "family": "common_drain", "sub": "fixed_gate"},
    {"template_id": "FET-CD-04", "file": "mosfet_cd_externally_biased_buffer.json", "category": "mosfet", "family": "common_drain", "sub": "externally_biased"},
    # ── MOSFET CG ──
    {"template_id": "FET-CG-01", "file": "mosfet_cg_vdiv_amplifier.json", "category": "mosfet", "family": "common_gate", "sub": "voltage_divider"},
    {"template_id": "FET-CG-02", "file": "mosfet_cg_vdiv_gatebyp_amplifier.json", "category": "mosfet", "family": "common_gate", "sub": "voltage_divider_gatebyp"},
    {"template_id": "FET-CG-03", "file": "mosfet_cg_fixedgate_amplifier.json", "category": "mosfet", "family": "common_gate", "sub": "fixed_gate"},
    {"template_id": "FET-CG-04", "file": "mosfet_cg_fixedgate_gatebyp_amplifier.json", "category": "mosfet", "family": "common_gate", "sub": "fixed_gate_gatebyp"},
    {"template_id": "FET-CG-05", "file": "mosfet_cg_externally_biased_amplifier.json", "category": "mosfet", "family": "common_gate", "sub": "externally_biased"},
    {"template_id": "FET-CG-06", "file": "mosfet_cg_externally_biased_gatebyp_amplifier.json", "category": "mosfet", "family": "common_gate", "sub": "externally_biased_gatebyp"},
    # ── OpAmp Inverting ──
    {"template_id": "OP-01", "file": "opamp_inverting_dual_supply_core.json", "category": "opamp", "family": "inverting", "sub": "dual_supply"},
    {"template_id": "OP-02", "file": "opamp_inverting_single_supply_vref.json", "category": "opamp", "family": "inverting", "sub": "single_supply_vref"},
    {"template_id": "OP-03", "file": "opamp_inverting_single_supply_vref_ac_coupled.json", "category": "opamp", "family": "inverting", "sub": "single_supply_vref_ac"},
    {"template_id": "OP-04", "file": "opamp_inverting_single_supply_vref_ac_coupled_io.json", "category": "opamp", "family": "inverting", "sub": "single_supply_vref_ac_io"},
    # ── OpAmp Non-Inverting ──
    {"template_id": "OP-05", "file": "opamp_non_inverting_dual_supply_core.json", "category": "opamp", "family": "non_inverting", "sub": "dual_supply"},
    {"template_id": "OP-06", "file": "opamp_non_inverting_single_supply_vref.json", "category": "opamp", "family": "non_inverting", "sub": "single_supply_vref"},
    {"template_id": "OP-07", "file": "opamp_non_inverting_single_supply_vref_ac_coupled.json", "category": "opamp", "family": "non_inverting", "sub": "single_supply_vref_ac"},
    {"template_id": "OP-08", "file": "opamp_non_inverting_single_supply_vref_ac_coupled_io.json", "category": "opamp", "family": "non_inverting", "sub": "single_supply_vref_ac_io"},
    # ── OpAmp Differential ──
    {"template_id": "OP-09", "file": "opamp_differential_dual_supply_4r.json", "category": "opamp", "family": "differential", "sub": "dual_supply_4r"},
    {"template_id": "OP-10", "file": "opamp_differential_single_supply_vref_ac_coupled.json", "category": "opamp", "family": "differential", "sub": "single_supply_vref_ac"},
    # ── OpAmp Instrumentation ──
    {"template_id": "OP-11", "file": "opamp_instrumentation_3opamp_basic.json", "category": "opamp", "family": "instrumentation", "sub": "3opamp_dual_supply"},
    {"template_id": "OP-12", "file": "opamp_instrumentation_3opamp_single_supply_vref.json", "category": "opamp", "family": "instrumentation", "sub": "3opamp_single_supply"},
    {"template_id": "OP-13", "file": "opamp_instrumentation_3opamp_single_supply_vref_ac_coupled.json", "category": "opamp", "family": "instrumentation", "sub": "3opamp_single_supply_ac"},
    # ── Class A ──
    {"template_id": "CLASS-A-01", "file": "class_a_power_amp_voltage_divider_bias_full.json", "category": "power_amplifier", "family": "class_a", "sub": "voltage_divider_full"},
    {"template_id": "CLASS-A-02", "file": "class_a_power_amp_voltage_divider_bias_unbypassed_emitter.json", "category": "power_amplifier", "family": "class_a", "sub": "voltage_divider_unbypassed"},
    {"template_id": "CLASS-A-03", "file": "class_a_power_amp_fixed_bias_emitter_bypass.json", "category": "power_amplifier", "family": "class_a", "sub": "fixed_bias_bypass"},
    {"template_id": "CLASS-A-04", "file": "class_a_power_stage_externally_biased_base.json", "category": "power_amplifier", "family": "class_a", "sub": "externally_biased"},
    # ── Class AB ──
    {"template_id": "CLASS-AB-01", "file": "class_ab_push_pull_amp_diode_bias_full.json", "category": "power_amplifier", "family": "class_ab", "sub": "diode_bias_full"},
    {"template_id": "CLASS-AB-02", "file": "class_ab_push_pull_amp_diode_bias_dc_coupled.json", "category": "power_amplifier", "family": "class_ab", "sub": "diode_bias_dc"},
    {"template_id": "CLASS-AB-03", "file": "class_ab_push_pull_amp_fixed_bias_no_diodes.json", "category": "power_amplifier", "family": "class_ab", "sub": "fixed_bias_no_diodes"},
    {"template_id": "CLASS-AB-04", "file": "class_ab_push_pull_stage_externally_biased_bases.json", "category": "power_amplifier", "family": "class_ab", "sub": "externally_biased"},
    # ── Class B ──
    {"template_id": "CLASS-B-01", "file": "class_b_push_pull_amp_no_bias_full_ac_coupled.json", "category": "power_amplifier", "family": "class_b", "sub": "no_bias_ac"},
    {"template_id": "CLASS-B-02", "file": "class_b_push_pull_no_bias_dc_coupled.json", "category": "power_amplifier", "family": "class_b", "sub": "no_bias_dc"},
    {"template_id": "CLASS-B-03", "file": "class_b_push_pull_externally_biased_bases.json", "category": "power_amplifier", "family": "class_b", "sub": "externally_biased"},
    # ── Class C ──
    {"template_id": "CLASS-C-01", "file": "class_c_tuned_amp_voltage_divider_bias_full.json", "category": "power_amplifier", "family": "class_c", "sub": "voltage_divider_full"},
    {"template_id": "CLASS-C-02", "file": "class_c_tuned_amp_voltage_divider_bias_no_cin.json", "category": "power_amplifier", "family": "class_c", "sub": "voltage_divider_no_cin"},
    {"template_id": "CLASS-C-03", "file": "class_c_tuned_amp_fixed_bias.json", "category": "power_amplifier", "family": "class_c", "sub": "fixed_bias"},
    {"template_id": "CLASS-C-04", "file": "class_c_tuned_stage_externally_biased_base.json", "category": "power_amplifier", "family": "class_c", "sub": "externally_biased"},
    # ── Class D ──
    {"template_id": "CLASS-D-01", "file": "class_d_mosfet_pwm_comparator_lc_filter_full.json", "category": "power_amplifier", "family": "class_d", "sub": "pwm_comparator_lc"},
    {"template_id": "CLASS-D-02", "file": "class_d_mosfet_pwm_output_stage_no_lc_filter.json", "category": "power_amplifier", "family": "class_d", "sub": "pwm_no_lc"},
    {"template_id": "CLASS-D-03", "file": "class_d_mosfet_hbridge_external_pwm_input.json", "category": "power_amplifier", "family": "class_d", "sub": "hbridge_pwm"},
    {"template_id": "CLASS-D-04", "file": "class_d_mosfet_halfbridge_simple_lc_filter_minimal.json", "category": "power_amplifier", "family": "class_d", "sub": "halfbridge_lc"},
    # ── Darlington ──
    {"template_id": "SPECIAL-DAR-01", "file": "special_darlington_pair_voltage_divider_bias_full.json", "category": "special", "family": "darlington", "sub": "voltage_divider_full"},
    {"template_id": "SPECIAL-DAR-02", "file": "special_darlington_pair_voltage_divider_unbypassed_emitter.json", "category": "special", "family": "darlington", "sub": "voltage_divider_unbypassed"},
    {"template_id": "SPECIAL-DAR-03", "file": "special_darlington_pair_fixed_bias_emitter_bypass.json", "category": "special", "family": "darlington", "sub": "fixed_bias_bypass"},
    {"template_id": "SPECIAL-DAR-04", "file": "special_darlington_pair_externally_biased_base.json", "category": "special", "family": "darlington", "sub": "externally_biased"},
    # ── Multi-Stage ──
    {"template_id": "SPECIAL-MS-01", "file": "multi_stage_two_stage_ce_cc_full_coupling.json", "category": "special", "family": "multi_stage", "sub": "ce_cc_full"},
    {"template_id": "SPECIAL-MS-02", "file": "multi_stage_two_stage_cecc_emitter_degeneration.json", "category": "special", "family": "multi_stage", "sub": "ce_cc_degen"},
    {"template_id": "SPECIAL-MS-03", "file": "multi_stage_two_stage_cecc_fixed_bias_stage2.json", "category": "special", "family": "multi_stage", "sub": "ce_cc_fixed_s2"},
    {"template_id": "SPECIAL-MS-04", "file": "multi_stage_two_stage_cecc_externally_biased_stage2.json", "category": "special", "family": "multi_stage", "sub": "ce_cc_ext_s2"},
]


# ============================================================
# FAMILY → BLOCK TYPE + GAIN + DOMAIN KNOWLEDGE
# ============================================================
FAMILY_BLOCK_MAP = {
    "common_emitter": {
        "block_type": "ce_block",
        "gain_formula": "-RC / (re + RE)",
        "gain_formula_bypass": "-RC / re",
        "roles": ["amplification"],
        "intent_keys": ["common emitter", "CE amplifier", "bjt amplifier", "voltage amplifier"],
        "required_capabilities": ["voltage_gain"],
        "compatible_extensions": ["cc_block"],
    },
    "common_base": {
        "block_type": "cb_block",
        "gain_formula": "RC / re",
        "roles": ["amplification", "current_buffer"],
        "intent_keys": ["common base", "CB amplifier", "wideband", "rf preamp"],
        "required_capabilities": ["voltage_gain", "low_input_impedance"],
        "compatible_extensions": ["cc_block"],
    },
    "common_collector": {
        "block_type": "cc_block",
        "gain_formula": "RE / (re + RE) ≈ 1",
        "roles": ["buffering", "impedance_matching"],
        "intent_keys": ["emitter follower", "common collector", "buffer", "CC"],
        "required_capabilities": ["buffering", "low_output_impedance"],
        "compatible_extensions": [],
    },
    "common_source": {
        "block_type": "cs_block",
        "gain_formula": "-gm * RD",
        "gain_formula_unbypassed": "-gm * RD / (1 + gm*RS)",
        "roles": ["amplification"],
        "intent_keys": ["common source", "CS amplifier", "MOSFET amplifier"],
        "required_capabilities": ["voltage_gain", "high_input_impedance"],
        "compatible_extensions": ["cd_block"],
    },
    "common_drain": {
        "block_type": "cd_block",
        "gain_formula": "gm*RS / (1 + gm*RS) ≈ 1",
        "roles": ["buffering", "impedance_matching"],
        "intent_keys": ["source follower", "common drain", "MOSFET buffer", "CD"],
        "required_capabilities": ["buffering", "high_input_impedance"],
        "compatible_extensions": [],
    },
    "common_gate": {
        "block_type": "cg_block",
        "gain_formula": "gm * RD",
        "roles": ["amplification", "current_buffer"],
        "intent_keys": ["common gate", "CG amplifier", "rf amplifier"],
        "required_capabilities": ["voltage_gain", "low_input_impedance"],
        "compatible_extensions": ["cd_block"],
    },
    "inverting": {
        "block_type": "inverting_block",
        "gain_formula": "-RF / RIN",
        "roles": ["amplification"],
        "intent_keys": ["inverting amplifier", "inverting opamp", "phase inversion"],
        "required_capabilities": ["voltage_gain", "phase_inversion"],
        "compatible_extensions": ["cc_block", "cd_block"],
    },
    "non_inverting": {
        "block_type": "non_inverting_block",
        "gain_formula": "1 + RF / RG",
        "roles": ["amplification", "buffering"],
        "intent_keys": ["non-inverting amplifier", "non-inverting opamp", "buffer with gain"],
        "required_capabilities": ["voltage_gain", "high_input_impedance"],
        "compatible_extensions": ["cc_block", "cd_block"],
    },
    "differential": {
        "block_type": "differential_block",
        "gain_formula": "R2 / R1",
        "roles": ["amplification", "signal_subtraction"],
        "intent_keys": ["differential amplifier", "difference amplifier", "subtractor"],
        "required_capabilities": ["differential_input", "voltage_gain"],
        "compatible_extensions": ["cc_block", "non_inverting_block"],
    },
    "instrumentation": {
        "block_type": "instrumentation_block",
        "gain_formula": "(1 + 2*RF/RG) * (R2/R1)",
        "roles": ["amplification", "measurement", "high_cmrr"],
        "intent_keys": ["instrumentation amplifier", "measurement amplifier", "3 opamp", "high CMRR"],
        "required_capabilities": ["differential_input", "high_cmrr", "precision_gain"],
        "compatible_extensions": ["cc_block", "cd_block"],
    },
    "class_a": {
        "block_type": "class_a_block",
        "gain_formula": "-RC / (re + RE)",
        "roles": ["power_amplification"],
        "intent_keys": ["class A", "class A amplifier", "power amplifier class A"],
        "required_capabilities": ["power_amplification", "full_cycle"],
        "compatible_extensions": ["cc_block"],
    },
    "class_b": {
        "block_type": "class_b_block",
        "gain_formula": "~1 (push-pull)",
        "roles": ["power_amplification", "push_pull"],
        "intent_keys": ["class B", "push-pull", "class B amplifier"],
        "required_capabilities": ["power_amplification", "push_pull"],
        "compatible_extensions": ["ce_block"],
    },
    "class_ab": {
        "block_type": "class_ab_block",
        "gain_formula": "~1 (push-pull with bias)",
        "roles": ["power_amplification", "push_pull", "low_distortion"],
        "intent_keys": ["class AB", "class AB amplifier", "push-pull low distortion"],
        "required_capabilities": ["power_amplification", "push_pull", "low_distortion"],
        "compatible_extensions": ["ce_block"],
    },
    "class_c": {
        "block_type": "class_c_block",
        "gain_formula": "tank_dependent",
        "roles": ["rf_amplification", "power_amplification"],
        "intent_keys": ["class C", "class C amplifier", "tuned amplifier", "RF power"],
        "required_capabilities": ["rf_amplification", "high_efficiency"],
        "compatible_extensions": [],
    },
    "class_d": {
        "block_type": "class_d_block",
        "gain_formula": "VDD * duty_cycle",
        "roles": ["power_amplification", "high_efficiency"],
        "intent_keys": ["class D", "class D amplifier", "switching amplifier", "PWM"],
        "required_capabilities": ["power_amplification", "high_efficiency", "switching"],
        "compatible_extensions": [],
    },
    "darlington": {
        "block_type": "darlington_block",
        "gain_formula": "beta1 * beta2 (current gain)",
        "roles": ["high_current_gain", "amplification"],
        "intent_keys": ["darlington", "darlington pair", "high current gain"],
        "required_capabilities": ["high_current_gain"],
        "compatible_extensions": ["cc_block"],
    },
    "multi_stage": {
        "block_type": "multi_stage_block",
        "gain_formula": "A_stage1 * A_stage2",
        "roles": ["high_gain_amplification"],
        "intent_keys": ["two stage", "multi stage", "CE-CC", "cascade"],
        "required_capabilities": ["voltage_gain", "low_output_impedance"],
        "compatible_extensions": [],
    },
}


def sha256_file(filepath: Path) -> str:
    """Tính SHA256 hash của file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_components(template: Dict) -> List[Dict]:
    """Trích danh sách components từ template."""
    return template.get("components", [])


def classify_component(comp: Dict) -> str:
    """Phân loại component thành nhóm chức năng."""
    ctype = comp.get("type", "").upper()
    cid = comp.get("id", "").upper()
    if ctype in ("BJT", "NPN", "PNP"):
        return "transistor"
    if ctype in ("MOSFET", "NMOS", "PMOS", "JFET"):
        return "transistor"
    if ctype == "OPAMP":
        return "opamp"
    if ctype == "RESISTOR" or cid.startswith("R"):
        return "resistor"
    if ctype == "CAPACITOR" or cid.startswith("C"):
        return "capacitor"
    if ctype == "INDUCTOR" or cid.startswith("L"):
        return "inductor"
    if ctype == "DIODE" or cid.startswith("D"):
        return "diode"
    if ctype in ("VOLTAGE_SOURCE", "GROUND", "PORT"):
        return "power_or_port"
    return "other"


def extract_resistor_params(template: Dict) -> List[Dict]:
    """Trích tham số resistor có thể tuning."""
    params = []
    for comp in extract_components(template):
        if classify_component(comp) == "resistor":
            cid = comp["id"]
            resistance = comp.get("parameters", {}).get("resistance", None)
            p = {
                "name": cid.lower() + "_resistance",
                "symbol": cid,
                "component_ref": cid,
                "component_type": "resistor",
                "adjustable": True,
            }
            if resistance:
                p["range"] = {"min": 100, "max": 1000000, "unit": "ohm"}
            p["preferred_series"] = "E24"
            params.append(p)
    return params


def extract_ports_from_template(template: Dict) -> Dict:
    """Trích external ports."""
    ports_data = template.get("ports", [])
    ext_inputs = []
    ext_outputs = []
    supply_ports = []

    for p in ports_data:
        pid = p.get("id", "")
        direction = p.get("direction", "")
        if direction == "input":
            polarity = "single_ended"
            role = "signal_in"
            if "POS" in pid.upper() or "+" in pid:
                polarity = "pos"
            elif "NEG" in pid.upper() or "-" in pid:
                polarity = "neg"
            ext_inputs.append({"name": pid, "role": role, "polarity": polarity})
        elif direction == "output":
            ext_outputs.append({"name": pid, "role": "signal_out", "polarity": "single_ended"})
        elif direction in ("power", "supply"):
            supply_ports.append({"name": pid, "role": "supply", "polarity": "n/a"})
        elif direction == "ground":
            supply_ports.append({"name": pid, "role": "ground", "polarity": "n/a"})

    # Fallback nếu template không có ports field
    if not ext_inputs and not ext_outputs:
        for comp in extract_components(template):
            cid = comp.get("id", "").upper()
            ctype = comp.get("type", "").upper()
            if ctype == "PORT" or "VIN" in cid:
                if "OUT" in cid:
                    ext_outputs.append({"name": comp["id"], "role": "signal_out", "polarity": "single_ended"})
                else:
                    polarity = "single_ended"
                    if "POS" in cid or "+" in cid:
                        polarity = "pos"
                    elif "NEG" in cid or "-" in cid:
                        polarity = "neg"
                    ext_inputs.append({"name": comp["id"], "role": "signal_in", "polarity": polarity})
            elif "VOUT" in cid:
                ext_outputs.append({"name": comp["id"], "role": "signal_out", "polarity": "single_ended"})
            elif ctype == "VOLTAGE_SOURCE" and "GND" not in cid:
                supply_ports.append({"name": comp["id"], "role": "supply", "polarity": "n/a"})
            elif ctype == "GROUND" or cid == "GND":
                supply_ports.append({"name": comp["id"], "role": "ground", "polarity": "n/a"})

    return {
        "external_inputs": ext_inputs,
        "external_outputs": ext_outputs,
        "supply_ports": supply_ports,
    }


def build_blocks_for_family(family: str, template: Dict, reg_entry: Dict) -> List[Dict]:
    """Xây dựng functional blocks dựa trên family."""
    finfo = FAMILY_BLOCK_MAP.get(family, {})
    block_type = finfo.get("block_type", family + "_block")
    gain = finfo.get("gain_formula", "N/A")
    roles = finfo.get("roles", ["amplification"])

    components = extract_components(template)
    comp_ids = [c["id"] for c in components if classify_component(c) not in ("power_or_port", "other")]

    if family == "instrumentation":
        # 3 blocks: 2 non-inverting + 1 differential
        input_ports = extract_ports_from_template(template)
        in_names = [p["name"] for p in input_ports["external_inputs"]]
        out_names = [p["name"] for p in input_ports["external_outputs"]]

        opamps = [c["id"] for c in components if classify_component(c) == "opamp"]
        u1 = opamps[0] if len(opamps) > 0 else "U1"
        u2 = opamps[1] if len(opamps) > 1 else "U2"
        u3 = opamps[2] if len(opamps) > 2 else "U3"

        return [
            {
                "id": "stage1",
                "type": "non_inverting_block",
                "inputs": [in_names[0]] if in_names else ["VIN_POS"],
                "outputs": [f"{u1}_OUT"],
                "internal_components": [u1, "RF1", "RG"],
                "gain_formula": "1 + RF/RG",
                "roles": ["amplification", "buffering"],
            },
            {
                "id": "stage2",
                "type": "non_inverting_block",
                "inputs": [in_names[1]] if len(in_names) > 1 else ["VIN_NEG"],
                "outputs": [f"{u2}_OUT"],
                "internal_components": [u2, "RF2", "RG"],
                "gain_formula": "1 + RF/RG",
                "roles": ["amplification", "buffering"],
            },
            {
                "id": "stage3",
                "type": "differential_block",
                "inputs": [f"{u1}_OUT", f"{u2}_OUT"],
                "outputs": out_names if out_names else ["VOUT"],
                "internal_components": [u3, "R1", "R2", "R3", "R4"],
                "gain_formula": "R2/R1",
                "roles": ["amplification", "signal_subtraction"],
            },
        ]

    if family == "multi_stage":
        # 2 blocks: CE + CC
        bjts = [c["id"] for c in components if classify_component(c) == "transistor"]
        q1 = bjts[0] if bjts else "Q1"
        q2 = bjts[1] if len(bjts) > 1 else "Q2"
        return [
            {
                "id": "stage1",
                "type": "ce_block",
                "inputs": ["VIN"],
                "outputs": [f"{q1}_COLLECTOR"],
                "internal_components": [q1],
                "gain_formula": "-RC1 / (re1 + RE1)",
                "roles": ["amplification"],
            },
            {
                "id": "stage2",
                "type": "cc_block",
                "inputs": [f"{q1}_COLLECTOR"],
                "outputs": ["VOUT"],
                "internal_components": [q2],
                "gain_formula": "~1",
                "roles": ["buffering"],
            },
        ]

    if family == "darlington":
        bjts = [c["id"] for c in components if classify_component(c) == "transistor"]
        return [
            {
                "id": "stage1",
                "type": "darlington_block",
                "inputs": ["VIN"],
                "outputs": ["VOUT"],
                "internal_components": bjts,
                "gain_formula": gain,
                "roles": roles,
            }
        ]

    # Single-block families
    input_ports = extract_ports_from_template(template)
    in_names = [p["name"] for p in input_ports["external_inputs"]] or ["VIN"]
    out_names = [p["name"] for p in input_ports["external_outputs"]] or ["VOUT"]

    block = {
        "id": "stage1",
        "type": block_type,
        "inputs": in_names,
        "outputs": out_names,
        "internal_components": comp_ids,
        "gain_formula": gain,
        "roles": roles,
    }

    # Check if bypass variant → update gain formula
    sub = reg_entry.get("sub", "")
    if "bypass" in sub and "unbypassed" not in sub and "nobypass" not in sub:
        alt_gain = finfo.get("gain_formula_bypass") or finfo.get("gain_formula")
        block["gain_formula"] = alt_gain
    elif "unbypassed" in sub or "nobypass" in sub:
        alt_gain = finfo.get("gain_formula_unbypassed") or finfo.get("gain_formula")
        block["gain_formula"] = alt_gain

    return [block]


def build_connections(blocks: List[Dict]) -> List[Dict]:
    """Xây dựng connections giữa các blocks."""
    conns = []
    for i in range(len(blocks) - 1):
        b_from = blocks[i]
        b_to = blocks[i + 1]
        conns.append({
            "from_block": b_from["id"],
            "from_port": "OUT",
            "to_block": b_to["id"],
            "to_port": "IN",
            "signal_type": "analog",
        })
    return conns


def build_pattern_signature(blocks: List[Dict], template_id: str) -> Dict:
    """Xây dựng pattern signature."""
    ordered = [b["type"] for b in blocks]
    sig_str = "|".join(ordered)
    graph_hash = hashlib.md5(sig_str.encode()).hexdigest()[:16]
    motifs = []
    if len(blocks) > 1:
        motifs.append("multi_stage")
    if any("push_pull" in b.get("roles", []) for b in blocks):
        motifs.append("push_pull")
    if any("differential" in b["type"] for b in blocks):
        motifs.append("differential_path")
    if any("non_inverting" in b["type"] for b in blocks) and any("differential" in b["type"] for b in blocks):
        motifs.append("instrumentation_motif")

    return {
        "ordered_block_types": ordered,
        "graph_hash": graph_hash,
        "motifs": motifs,
    }


def build_solver_hints(family: str, template: Dict) -> Dict:
    """Xây dựng solver hints."""
    finfo = FAMILY_BLOCK_MAP.get(family, {})
    params = extract_resistor_params(template)

    equations = []
    gain = finfo.get("gain_formula", "N/A")
    if gain != "N/A":
        equations.append({
            "id": "eq_gain",
            "expression": gain,
            "variables": [p["symbol"] for p in params[:4]],
        })

    constraints = []
    if family in ("common_emitter", "common_base", "common_collector", "class_a", "darlington"):
        constraints.append({"name": "vce_active", "rule": "VCE > 0.2V", "severity": "hard"})
        constraints.append({"name": "power_dissipation", "rule": "P_Q < P_max", "severity": "hard"})
    if family in ("common_source", "common_drain", "common_gate"):
        constraints.append({"name": "vds_saturation", "rule": "VDS > VGS - Vth", "severity": "hard"})
    if family in ("inverting", "non_inverting", "differential", "instrumentation"):
        constraints.append({"name": "output_swing", "rule": "|VOUT| < V_supply - headroom", "severity": "hard"})
        constraints.append({"name": "gbw_limit", "rule": "gain * BW < GBW", "severity": "hard"})
    if family == "instrumentation":
        constraints.append({"name": "resistor_matching", "rule": "RF1==RF2, R1/R2==R3/R4", "severity": "hard"})
        constraints.append({"name": "cmrr_min", "rule": "CMRR >= 80dB", "severity": "hard"})
    if family in ("class_b", "class_ab"):
        constraints.append({"name": "symmetry", "rule": "beta_NPN ≈ beta_PNP", "severity": "soft"})
    if family == "class_ab":
        constraints.append({"name": "bias_voltage", "rule": "V_bias ≈ 2*VBE", "severity": "hard"})
    if family == "class_c":
        constraints.append({"name": "resonance", "rule": "f = 1/(2*pi*sqrt(L*C))", "severity": "hard"})
    if family == "class_d":
        constraints.append({"name": "switching_freq", "rule": "f_sw >> 2*f_max", "severity": "hard"})

    opt_targets = []
    if family in ("class_a", "class_b", "class_ab", "class_d"):
        opt_targets.append("power_efficiency")
    if family in ("common_emitter", "inverting", "non_inverting", "instrumentation"):
        opt_targets.append("gain_accuracy")
    if family in ("common_base", "common_gate", "class_c"):
        opt_targets.append("bandwidth")

    return {
        "parameters": params,
        "equations": equations,
        "constraints": constraints,
        "optimization_targets": opt_targets,
    }


def build_validation(family: str) -> Dict:
    """Xây dựng validation rules."""
    rules = ["all_required_ports_connected", "valid_supply_domain"]
    checks = ["gain_equation_satisfiable"]
    limitations = []

    if family in ("class_b",):
        limitations.append("crossover_distortion_present")
    if family in ("class_c",):
        limitations.append("only_narrowband_rf_signals")
    if family in ("common_emitter", "common_source"):
        limitations.append("phase_inverted_output")

    return {
        "domain_rules": rules,
        "min_checks": checks,
        "known_limitations": limitations,
    }


def build_topology_tags(family: str, sub: str) -> List[str]:
    """Xây dựng topology tags."""
    tags = [family]
    if "fixed_bias" in sub:
        tags.append("fixed_bias")
    if "voltage_divider" in sub or "vdiv" in sub:
        tags.append("voltage_divider")
    if "bypass" in sub and "unbypassed" not in sub and "nobypass" not in sub:
        tags.append("bypassed")
    if "unbypassed" in sub or "nobypass" in sub:
        tags.append("unbypassed")
    if "ac" in sub:
        tags.append("ac_coupled")
    if "dc" in sub:
        tags.append("dc_coupled")
    if "externally" in sub:
        tags.append("externally_biased")
    if "dual_supply" in sub:
        tags.append("dual_supply")
    if "single_supply" in sub:
        tags.append("single_supply")
    if "vref" in sub:
        tags.append("virtual_reference")
    if "degen" in sub:
        tags.append("emitter_degeneration")
    if "diode" in sub:
        tags.append("diode_bias")
    if "gate" in sub and "fixed" in sub:
        tags.append("fixed_gate")
    if "hbridge" in sub or "fullbridge" in sub:
        tags.append("full_bridge")
    if "halfbridge" in sub:
        tags.append("half_bridge")
    if "pwm" in sub:
        tags.append("pwm")
    if "lc" in sub:
        tags.append("lc_filter")
    if "nocout" in sub:
        tags.append("no_output_cap")
    return tags


def build_use_cases(family: str) -> List[str]:
    """Xây dựng target use cases."""
    cases = {
        "common_emitter": ["audio_preamp", "general_amplification"],
        "common_base": ["rf_preamp", "wideband_amplifier"],
        "common_collector": ["impedance_matching", "output_buffer"],
        "common_source": ["high_impedance_amplification", "general_amplification"],
        "common_drain": ["impedance_matching", "output_buffer"],
        "common_gate": ["rf_amplifier", "current_buffer"],
        "inverting": ["signal_conditioning", "summing"],
        "non_inverting": ["sensor_amplification", "buffer_with_gain"],
        "differential": ["signal_subtraction", "bridge_measurement"],
        "instrumentation": ["precision_measurement", "sensor_interface", "biomedical"],
        "class_a": ["audio_power", "linear_driver"],
        "class_b": ["audio_power", "motor_driver"],
        "class_ab": ["hi_fi_audio", "audio_power"],
        "class_c": ["rf_transmitter", "oscillator_buffer"],
        "class_d": ["audio_power", "motor_driver", "power_conversion"],
        "darlington": ["high_current_switch", "relay_driver"],
        "multi_stage": ["high_gain_audio", "multi_purpose"],
    }
    return cases.get(family, ["general_purpose"])


def generate_metadata(reg_entry: Dict) -> Optional[Dict]:
    """Sinh metadata cho 1 template."""
    template_file = reg_entry["file"]
    template_path = TEMPLATES_DIR / template_file
    template_id = reg_entry["template_id"]
    family = reg_entry["family"]
    category = reg_entry["category"]
    sub = reg_entry.get("sub", "")

    if not template_path.exists():
        print(f"  [SKIP] Template file not found: {template_file}")
        return None

    # Đọc template gốc
    with open(template_path, "r", encoding="utf-8") as f:
        template = json.load(f)

    # Tính hash
    file_hash = sha256_file(template_path)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build blocks
    blocks = build_blocks_for_family(family, template, reg_entry)
    connections = build_connections(blocks)
    ports = extract_ports_from_template(template)
    pattern_sig = build_pattern_signature(blocks, template_id)
    solver = build_solver_hints(family, template)
    validation = build_validation(family)
    finfo = FAMILY_BLOCK_MAP.get(family, {})

    # Topology tags
    topo_tags = build_topology_tags(family, sub)

    # Priority score
    priority_map = {
        "common_emitter": 0.90, "common_base": 0.80, "common_collector": 0.85,
        "common_source": 0.88, "common_drain": 0.83, "common_gate": 0.78,
        "inverting": 0.92, "non_inverting": 0.93, "differential": 0.90,
        "instrumentation": 0.98, "class_a": 0.85, "class_b": 0.80,
        "class_ab": 0.88, "class_c": 0.75, "class_d": 0.82,
        "darlington": 0.78, "multi_stage": 0.88,
    }

    # Fallback rank based on sub-variant (simpler = higher rank)
    rank_hints = {"_01": 1, "_02": 2, "_03": 3, "_04": 4, "_05": 5, "_06": 6}
    fallback = 1
    for suffix, r in rank_hints.items():
        if template_id.endswith(suffix.replace("_", "-")) or template_id.endswith(suffix.replace("_", "")):
            fallback = r
            break
    # Extract last digits
    tid_parts = template_id.rsplit("-", 1)
    if len(tid_parts) > 1 and tid_parts[1].isdigit():
        fallback = int(tid_parts[1])

    gain_formula = finfo.get("gain_formula", "N/A")
    stage_count = len(blocks)

    metadata = {
        "template_id": template_id,
        "metadata_version": "v1.0.0",
        "physical_template_ref": {
            "template_file": template_file,
            "template_sha256": file_hash,
            "kicanvas_compatible": True,
        },
        "domain": {
            "category": category,
            "family": family,
            "topology_tags": topo_tags,
            "target_use_cases": build_use_cases(family),
        },
        "functional_structure": {
            "ports": ports,
            "blocks": blocks,
            "connections": connections,
            "pattern_signature": pattern_sig,
            "total_gain_formula": gain_formula,
            "stage_count": stage_count,
        },
        "planner_hints": {
            "intent_keys": finfo.get("intent_keys", [family]),
            "required_capabilities": finfo.get("required_capabilities", []),
            "optional_capabilities": finfo.get("compatible_extensions", []),
            "priority_score": priority_map.get(family, 0.70),
            "fallback_rank": fallback,
            "compatible_extensions": finfo.get("compatible_extensions", []),
        },
        "solver_hints": solver,
        "validation": validation,
        "sync": {
            "source_template_last_modified": now_iso,
            "metadata_last_modified": now_iso,
            "status": "in_sync",
        },
    }

    return metadata


def main():
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"=== Generating metadata for {len(TEMPLATE_REGISTRY)} templates ===")
    print(f"Templates dir: {TEMPLATES_DIR}")
    print(f"Metadata dir:  {METADATA_DIR}")
    print()

    success = 0
    skipped = 0

    for entry in TEMPLATE_REGISTRY:
        tid = entry["template_id"]
        meta = generate_metadata(entry)

        if meta is None:
            skipped += 1
            continue

        # Write metadata file
        meta_filename = f"{tid}.meta.json"
        meta_path = METADATA_DIR / meta_filename

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        print(f"  [OK] {tid} -> {meta_filename}")
        success += 1

    print()
    print(f"=== Done: {success} generated, {skipped} skipped ===")

    # Generate index
    index = {
        "description": "Index mapping template_id -> metadata file",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": success,
        "entries": [],
    }
    for entry in TEMPLATE_REGISTRY:
        tid = entry["template_id"]
        meta_file = f"{tid}.meta.json"
        if (METADATA_DIR / meta_file).exists():
            index["entries"].append({
                "template_id": tid,
                "metadata_file": meta_file,
                "template_file": entry["file"],
                "category": entry["category"],
                "family": entry["family"],
            })

    index_path = METADATA_DIR / "_index_metadata.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    print(f"  [OK] Index -> _index_metadata.json ({len(index['entries'])} entries)")


if __name__ == "__main__":
    main()
