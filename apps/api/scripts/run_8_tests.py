import json
import urllib.request
import urllib.error
import urllib.parse
import os
from pathlib import Path

SERVER = os.environ.get('CHATBOT_API_URL', 'http://127.0.0.1:8011')
BASE = SERVER.rstrip('/')

TEMPLATES = [
    'resources/templates/bjt_ce_externally_biased_amplifier.json',
    'resources/templates/mosfet_cs_externally_biased_bypass_amplifier.json',
    'resources/templates/opamp_non_inverting_single_supply_vref.json',
    'resources/templates/opamp_differential_single_supply_vref_ac_coupled.json',
    'resources/templates/class_ab_push_pull_amp_diode_bias_full.json',
    'resources/templates/class_d_mosfet_pwm_output_stage_no_lc_filter.json',
    'resources/templates/special_darlington_pair_voltage_divider_bias_full.json',
    # Compose a 3-stage hybrid by reusing existing templates where possible
    'resources/templates/three_stage_hybrid_composed.json',
]

OUT = Path('test_results_8.json')
results = []

for tpl in TEMPLATES:
    entry = {'template': tpl}
    try:
        with open(tpl, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except FileNotFoundError:
        entry['error'] = 'template_not_found'
        results.append(entry)
        print('Missing template', tpl)
        continue

    # Add source params / desired gain hints for some templates
    if 'bjt' in tpl:
        payload.setdefault('source_params', {})['voltage'] = 12
        payload.setdefault('gain_target', 20)
    if 'mosfet' in tpl and 'class_d' not in tpl:
        payload.setdefault('source_params', {})['voltage'] = 12
        payload.setdefault('gain_target', 10)
    if 'opamp_non_inverting' in tpl:
        payload.setdefault('gain_target', 11)
    if 'opamp_differential' in tpl:
        payload.setdefault('gain_target', 5)
    if 'class_ab' in tpl or 'push_pull' in tpl:
        payload.setdefault('source_params', {})['voltage'] = 12
    if 'class_d' in tpl:
        payload.setdefault('source_params', {})['voltage'] = 12
    if 'darlington' in tpl:
        payload.setdefault('source_params', {})['voltage'] = 12

    # For the composed 3-stage template, attempt to build a simple wrapper if file missing
    if tpl.endswith('three_stage_hybrid_composed.json'):
        # try to create a simple composed circuit from other templates
        try:
            with open('resources/templates/opamp_non_inverting_single_supply_vref.json','r',encoding='utf-8') as f:
                op = json.load(f)
            with open('resources/templates/mosfet_cs_externally_biased_bypass_amplifier.json','r',encoding='utf-8') as f:
                mf = json.load(f)
            with open('resources/templates/class_ab_push_pull_amp_diode_bias_full.json','r',encoding='utf-8') as f:
                ab = json.load(f)
            # naive composition: merge components and nets, prefix ids
            composed = {'components': [], 'nets': [], 'ports': [], 'topology_type': 'three_stage_hybrid'}
            def prefix_and_extend(src, name):
                for c in src.get('components',[]):
                    nc = dict(c)
                    nc['id'] = f"{name}_{nc.get('id','') }"
                    composed['components'].append(nc)
                for n in src.get('nets',[]):
                    nn = dict(n)
                    nn['name'] = f"{name}_{nn.get('name','') }"
                    composed['nets'].append(nn)
            prefix_and_extend(op,'pre')
            prefix_and_extend(mf,'drv')
            prefix_and_extend(ab,'out')
            payload = composed
        except Exception as e:
            entry['error'] = f'compose_failed:{e}'
            results.append(entry)
            continue

    # POST export-kicad
    url = BASE + '/api/chat/export-kicad'
    body = json.dumps({'circuit_data': payload, 'circuit_id': Path(tpl).stem})
    req = urllib.request.Request(url, data=body.encode('utf-8'), headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_json = json.load(resp)
            entry['export'] = resp_json
            print('Exported', tpl, resp_json.get('url'))
    except urllib.error.HTTPError as he:
        try:
            entry['export_error'] = he.read().decode()
        except Exception:
            entry['export_error'] = str(he)
        print('Export failed', tpl, entry['export_error'])
        results.append(entry)
        continue
    except Exception as e:
        entry['export_error'] = str(e)
        results.append(entry)
        print('Export error', tpl, e)
        continue

    # Fetch kicad sch to verify
    try:
        fid = entry['export'].get('file_id')
        if fid:
            sch_url = BASE + f"/api/chat/kicad-file/{fid}.kicad_sch"
            with urllib.request.urlopen(sch_url, timeout=10) as sch_resp:
                content = sch_resp.read().decode('utf-8', errors='ignore')
                entry['kicad_size'] = len(content)
    except Exception as e:
        entry['kicad_fetch_error'] = str(e)

    # POST simulate
    sim_url = BASE + '/api/chat/simulate'
    sim_body = json.dumps({'circuit_data': payload})
    sim_req = urllib.request.Request(sim_url, data=sim_body.encode('utf-8'), headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(sim_req, timeout=120) as sresp:
            sim_resp = json.load(sresp)
            entry['simulation'] = {'success': sim_resp.get('success'), 'analysis': sim_resp.get('analysis')}
            print('Simulated', tpl, 'success=', sim_resp.get('success'))
    except urllib.error.HTTPError as he:
        try:
            entry['simulation_error'] = he.read().decode()
        except Exception:
            entry['simulation_error'] = str(he)
        print('Sim failed', tpl, entry['simulation_error'])
    except Exception as e:
        entry['simulation_error'] = str(e)
        print('Sim exception', tpl, e)

    results.append(entry)

with OUT.open('w', encoding='utf-8') as f:
    json.dump(results, f, indent=2)

print('Done. Results written to', OUT)
