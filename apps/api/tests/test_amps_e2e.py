import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent

if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.domains.circuits.ai_core.ai_core import AICore
from app.domains.circuits.ai_core.spec_parser import UserSpec
from app.application.ai.simulation_service import NgSpiceSimulationService

def test_all_amps():
    amp_types = [
        "common_emitter", "common_collector", "common_base", 
        "common_source", "common_drain", "common_gate", 
        "darlington", "inverting", "non_inverting", "differential", "instrumentation"
    ]
    core = AICore()
    sim_service = NgSpiceSimulationService()
    
    results = {}

    for amp in amp_types:
        print(f"\n=========================================")
        print(f"Testing Amplifier: {amp}")
        print(f"=========================================")
        
        # 1. Spec parsing/Generation
        spec = UserSpec(circuit_type=amp, gain=10, vcc=12.0)
        try:
            res = core.handle_spec(spec)
            
            if not res.success or not res.circuit:
                print(f"  [X] AI Core failed to generate circuit for {amp}: {getattr(res, 'error', 'Unknown')}")
                results[amp] = {"status": "FAILED_GENERATION", "error": getattr(res, "error", "Unknown error")}
                continue
                
            circuit = res.circuit
            
            # Check Schematic & PCB
            components = circuit.circuit_data.get("components", [])
            nets = circuit.circuit_data.get("nets", [])
            pcb_hints = circuit.circuit_data.get("pcb_hints", {})
            has_sch = len(components) > 0 and len(nets) > 0
            has_pcb = len(pcb_hints) > 0 or any(c.get("footprint") for c in components)
            
            print(f"  [+] Schematic Data: {len(components)} components, {len(nets)} nets. Valid: {has_sch}")
            print(f"  [+] PCB Data: Present: {has_pcb}")
            
            if not has_sch:
                print(f"  [!] Missing schematic data for {amp}")
            if not has_pcb:
                print(f"  [!] Missing PCB data for {amp}")
                
            # 2. Simulation
            print(f"  [*] Running NgSpice Simulation...")
            sim_result = sim_service.simulate_from_circuit_data(circuit.circuit_data)
            
            if hasattr(sim_result, 'success') and sim_result.success:
                traces = sim_result.traces
                num_traces = len(traces) if traces else 0
                print(f"  [+] Simulation SUCCESS! Traces found: {num_traces}")
                results[amp] = {"status": "SUCCESS", "has_sch": has_sch, "has_pcb": has_pcb, "sim_success": True}
            else:
                sim_error = getattr(sim_result, 'ngspice_stderr', 'Unknown error')
                print(f"  [X] Simulation FAILED: {sim_error}")
                results[amp] = {"status": "FAILED_SIMULATION", "error": sim_error}
                
        except Exception as e:
            print(f"  [X] Exception during {amp} test: {e}")
            results[amp] = {"status": "ERROR", "error": str(e)}

    print("\n\n=========================================")
    print("====== ALL AMPLIFIER TEST SUMMARY =======")
    print("=========================================")
    
    success_count = 0
    for amp, result in results.items():
        if result.get("status") == "SUCCESS":
            success_count += 1
            print(f"[SUCCESS] {amp:<18} | SCH: {result.get('has_sch')!s:<5} | PCB: {result.get('has_pcb')!s:<5} | SIM: {result.get('sim_success')}")
        else:
            print(f"[FAILED]  {amp:<18} | Status: {result.get('status')} | Error: {result.get('error')}")
            
    print(f"\nFinal Score: {success_count} / {len(amp_types)}")

if __name__ == "__main__":
    test_all_amps()