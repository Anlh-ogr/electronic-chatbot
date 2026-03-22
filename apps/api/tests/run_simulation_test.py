import sys
from pathlib import Path

# Ensure paths correctly resolve
sys.path.insert(0, str(Path.cwd()))
from app.domains.circuits.ai_core.ai_core import AICore
from app.domains.circuits.ai_core.spec_parser import UserSpec
from app.application.ai.simulation_service import NgSpiceSimulationService      

core = AICore(
    metadata_dir=Path('resources/templates_metadata'),
    block_library_dir=Path('resources/block_library'),
    templates_dir=Path('resources/templates')
)
sim = NgSpiceSimulationService()

test_cases = [
    ("common_emitter", 10),
    ("common_collector", 1),
    ("common_source", 5),
    ("common_drain", 1),
    ("common_base", 10),
    ("common_gate", 5),
]

fails = 0
for family, gain in test_cases:
    spec = UserSpec(circuit_type=family, gain=gain, vcc=12.0, frequency=1000.0) 
    res = core.handle_spec(spec)

    print(f"Testing {family}...")
    if not res.success or not res.circuit:
        print(f"Failed to generate {family}")
        fails += 1
        continue

    try:
        circuit_data = res.circuit.circuit_data
        if family == 'common_gate':
            print("CG COMPONENTS:", [(c['id'], c.get('type')) for c in circuit_data.get('components', [])])
        sim_res = sim.simulate_from_circuit_data(circuit_data)
        if not sim_res.success:
            print(f"Simulation FAILED for {family}: {sim_res.ngspice_stderr}")  
            fails += 1
        else:
            print(f"Simulation PASSED for {family}.")
    except Exception as e:
        print(f"Crash during simulation for {family}: {e}")
        fails += 1

print(f"Fails: {fails}")
if fails > 0:
    sys.exit(1)
