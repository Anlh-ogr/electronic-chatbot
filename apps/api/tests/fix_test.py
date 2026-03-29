with open('tests/domain/test_fail_fast_regeneration_gate.py', 'r') as f: content = f.read()
content = content.replace('monkeypatch.setattr(service, "_run_simulation_feedback"', 'monkeypatch.setattr(service, "_evaluate_simulation_feedback"')
with open('tests/domain/test_fail_fast_regeneration_gate.py', 'w') as f: f.write(content)
