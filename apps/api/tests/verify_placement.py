#!/usr/bin/env python3
"""Verify placement data is captured."""

import json
import requests

# Get the first test circuit
payload = {'message': 'Design a simple BJT common emitter amplifier with 12V supply'}
response = requests.post('http://localhost:8000/api/chat', json=payload, stream=True, timeout=180)

circuit_data = None
for line in response.iter_lines(decode_unicode=True):
    if line.startswith('data: '):
        try:
            data = json.loads(line[6:])
            if 'circuit_data' in data:
                circuit_data = data['circuit_data']
                break
        except:
            pass

if circuit_data:
    print(f"Components: {len(circuit_data.get('components', []))}")
    print(f"Component types: {set(c.get('component_type') for c in circuit_data.get('components', []))}")
    print(f"Nets: {len(circuit_data.get('nets', []))}")
    print(f"Placement data present: {'placement' in circuit_data}")
    if 'placement' in circuit_data:
        print(f"Components placed: {len(circuit_data['placement'].get('placed_components', []))}")
        print(f"Placed component refs: {circuit_data['placement'].get('placed_components', [])[:5]}")
else:
    print("ERROR: circuit_data not found in response")
