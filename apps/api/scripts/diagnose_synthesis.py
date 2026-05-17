import json, traceback, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEMPLATES = [
    'resources/templates/bjt_ce_externally_biased_amplifier.json',
    'resources/templates/mosfet_cs_externally_biased_bypass_amplifier.json',
    'resources/templates/opamp_non_inverting_single_supply_vref.json',
    'resources/templates/opamp_differential_single_supply_vref_ac_coupled.json',
    'resources/templates/class_ab_push_pull_amp_diode_bias_full.json',
    'resources/templates/class_d_mosfet_pwm_output_stage_no_lc_filter.json',
    'resources/templates/special_darlington_pair_voltage_divider_bias_full.json',
]

from app.interfaces.http.routes.chatbot import _template_to_ir_dict
from app.domains.circuits.ir import CircuitIRSerializer
from app.application.ai.simulation_service import NgspiceCompilerService
from app.application.ai.circuit_ir_schema import CircuitIR as AppCircuitIR

for tpl in TEMPLATES:
    print('---', tpl)
    try:
        with open(tpl,'r',encoding='utf-8') as f:
            payload = json.load(f)
    except Exception as e:
        print('LOAD ERROR', e)
        continue
    try:
        ir_dict = _template_to_ir_dict(payload, normalize_power_rails=True)
        app_ir = AppCircuitIR.model_validate(ir_dict)
        deck = NgspiceCompilerService().generate_spice_deck(app_ir)
        print('DECK LENGTH', len(deck))
        print(deck.splitlines()[:10])
    except Exception as e:
        print('GEN ERROR', type(e), e)
        traceback.print_exc()
        continue
