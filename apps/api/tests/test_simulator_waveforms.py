#!/usr/bin/env python
"""
Test SPICE simulator with real waveform execution.
Creates a circuit, generates SPICE deck, runs ngspice, and plots waveforms.
"""

import requests
import json
import time
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

BASE_URL = "http://localhost:8000"
API_ENDPOINT = f"{BASE_URL}/api/chat"
NGSPICE_BIN = r"E:\ngspice-45.2_64\Spice64\bin\ngspice.exe"

TEST_CIRCUITS = [
    {
        "name": "Op-Amp Inverting Amplifier",
        "request": "Design an inverting op-amp amplifier with 12V supply and gain of 10",
        "description": "Classic inverting amplifier configuration"
    },
    {
        "name": "BJT Common Emitter",
        "request": "Thiết kế mạch khuếch đại CE nguồn 12V gain 20",
        "description": "BJT common emitter amplifier"
    }
]

def parse_sse_response(response) -> Optional[Dict[str, Any]]:
    """Parse SSE response line by line and extract circuit data."""
    try:
        circuit_data = None
        
        for line in response.iter_lines():
            if not line:
                continue
            
            line = line.decode('utf-8') if isinstance(line, bytes) else line
            
            if line.startswith("event: circuit_ready"):
                continue
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    if "circuit_data" in data:
                        circuit_data = data["circuit_data"]
                        return circuit_data
                except (json.JSONDecodeError, ValueError):
                    pass
        
        return circuit_data
    except Exception as e:
        print(f"Error parsing SSE: {e}")
        return None

def get_spice_deck(spice_url: str) -> Optional[str]:
    """Fetch SPICE deck from compiled artifacts."""
    try:
        # Convert URL path to file path
        if spice_url.startswith('/'):
            spice_url = spice_url[1:]  # Remove leading slash
        
        file_path = Path(f"artifacts/compiled/{spice_url.split('/')[-1]}")
        if file_path.exists():
            with open(file_path, 'r') as f:
                return f.read()
        return None
    except Exception as e:
        print(f"Error reading SPICE deck: {e}")
        return None

def run_ngspice_simulation(spice_deck: str) -> Optional[str]:
    """Run ngspice simulation and return output data."""
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False) as f:
            f.write(spice_deck)
            spice_file = f.name
        
        # Create temp directory for outputs
        temp_dir = tempfile.mkdtemp()
        output_file = os.path.join(temp_dir, 'output.tsv')
        
        # Run ngspice
        print(f"  🔄 Running ngspice... (temp: {spice_file})")
        result = subprocess.run(
            [NGSPICE_BIN, "-b", spice_file, "-o", output_file],
            capture_output=True,
            timeout=30,
            cwd=temp_dir
        )
        
        # Read output waveform file
        if os.path.exists(output_file):
            with open(output_file, 'r') as f:
                output_data = f.read()
            
            # Parse TSV data
            lines = output_data.strip().split('\n')
            if len(lines) > 1:
                print(f"  ✅ Simulation succeeded! Generated {len(lines)} data points")
                return output_data
            else:
                print(f"  ⚠️  Simulation completed but no waveform data")
                return None
        else:
            print(f"  ❌ Simulation failed: {result.stderr.decode()[:200]}")
            return None
            
    except subprocess.TimeoutExpired:
        print(f"  ⏱️  Simulation timeout (>30s)")
        return None
    except Exception as e:
        print(f"  ❌ Simulation error: {e}")
        return None

def plot_waveform(waveform_data: str, name: str):
    """Parse and display waveform data."""
    try:
        lines = waveform_data.strip().split('\n')
        if len(lines) < 2:
            return
        
        # Parse header
        header = lines[0].split('\t')
        data_rows = [line.split('\t') for line in lines[1:]]
        
        if len(data_rows) < 3:
            print(f"  📊 Insufficient data points ({len(data_rows)} < 3)")
            return
        
        # Extract time and signal columns
        print(f"\n  📊 Waveform Data: {name}")
        print(f"     Columns: {', '.join(header)}")
        print(f"     Data points: {len(data_rows)}")
        
        # Sample data (first 5, last 5)
        print(f"\n     First 5 samples:")
        for i, row in enumerate(data_rows[:5]):
            print(f"       [{i}] {' | '.join(f'{v[:12]:>12}' for v in row)}")
        
        if len(data_rows) > 10:
            print(f"     ... ({len(data_rows) - 10} rows omitted) ...")
            print(f"     Last 5 samples:")
            for i, row in enumerate(data_rows[-5:], start=len(data_rows)-5):
                print(f"       [{i}] {' | '.join(f'{v[:12]:>12}' for v in row)}")
        
        # Statistics
        if len(header) > 1:
            try:
                # Try to convert second column to float for statistics
                values = [float(row[1]) for row in data_rows if len(row) > 1]
                if values:
                    print(f"\n     Signal Statistics:")
                    print(f"       Min: {min(values):.6f}")
                    print(f"       Max: {max(values):.6f}")
                    print(f"       Mean: {sum(values)/len(values):.6f}")
            except (ValueError, IndexError):
                pass
                
    except Exception as e:
        print(f"  Error plotting waveform: {e}")

def run_test(test_case: Dict[str, str]) -> Dict[str, Any]:
    """Run single test case with real simulation."""
    name = test_case["name"]
    request_text = test_case["request"]
    description = test_case["description"]
    
    print(f"\n{'='*70}")
    print(f"🔬 Test: {name}")
    print(f"📝 Description: {description}")
    print(f"💬 Request: {request_text}")
    print('='*70)
    
    try:
        # Step 1: Create circuit
        print(f"\n1️⃣  Creating circuit via LLM...")
        response = requests.post(
            API_ENDPOINT,
            json={"message": request_text},
            stream=True,
            timeout=60
        )
        
        if response.status_code != 200:
            print(f"  ❌ HTTP {response.status_code}")
            return {"status": "Failed", "reason": f"HTTP {response.status_code}"}
        
        circuit_data = parse_sse_response(response)
        if not circuit_data:
            print(f"  ❌ No circuit_data in response")
            return {"status": "Failed", "reason": "No circuit_data in response"}
        
        print(f"  ✅ Circuit created")
        print(f"     Components: {len(circuit_data.get('components', []))}")
        print(f"     Nets: {len(circuit_data.get('nets', []))}")
        
        # Get topology classification
        topology = circuit_data.get('analysis', {}).get('topology_classification', 'Unknown')
        if not topology or topology == 'Unknown':
            topology = circuit_data.get('topology_classification', 'Unknown')
        print(f"     Topology: {topology}")
        
        # Step 2: Get SPICE deck
        print(f"\n2️⃣  Fetching SPICE netlist...")
        spice_url = circuit_data.get('spice_url') or circuit_data.get('ngspice_url')
        if not spice_url:
            print(f"  ⚠️  No SPICE URL found (trying to compile on-demand)")
            # Try to extract from analysis results
            spice_url = circuit_data.get('analysis', {}).get('spice_url')
        
        if not spice_url:
            print(f"  ❌ Could not locate SPICE URL")
            return {"status": "Failed", "reason": "No SPICE URL found"}
        
        spice_deck = get_spice_deck(spice_url)
        if not spice_deck:
            print(f"  ❌ Could not read SPICE deck")
            return {"status": "Failed", "reason": "Could not read SPICE deck"}
        
        print(f"  ✅ SPICE deck retrieved ({len(spice_deck)} bytes)")
        print(f"\n  📋 SPICE Netlist:")
        for i, line in enumerate(spice_deck.split('\n')[:15]):
            print(f"     {line}")
        if len(spice_deck.split('\n')) > 15:
            print(f"     ... ({len(spice_deck.split('\n')) - 15} more lines)")
        
        # Step 3: Run simulation
        print(f"\n3️⃣  Running ngspice simulation...")
        waveform_data = run_ngspice_simulation(spice_deck)
        
        if not waveform_data:
            print(f"  ⚠️  Simulation did not produce waveform data")
            topo = circuit_data.get('analysis', {}).get('topology_classification', 'Unknown')
            if not topo or topo == 'Unknown':
                topo = circuit_data.get('topology_classification', 'Unknown')
            return {
                "status": "Partial",
                "reason": "Simulation ran but no waveform output",
                "components": len(circuit_data.get('components', [])),
                "topology": topo
            }
        
        # Step 4: Display waveforms
        print(f"\n4️⃣  Parsing waveform output...")
        plot_waveform(waveform_data, f"{name} output")
        
        topo = circuit_data.get('analysis', {}).get('topology_classification', 'Unknown')
        if not topo or topo == 'Unknown':
            topo = circuit_data.get('topology_classification', 'Unknown')
        
        return {
            "status": "Success",
            "reason": "Simulation completed with waveform data",
            "components": len(circuit_data.get('components', [])),
            "topology": topo,
            "data_points": len(waveform_data.strip().split('\n'))
        }
        
    except requests.exceptions.Timeout:
        print(f"  ⏱️  Request timeout (>60s)")
        return {"status": "Failed", "reason": "Request timeout"}
    except Exception as e:
        print(f"  ❌ Error: {str(e)[:100]}")
        return {"status": "Failed", "reason": str(e)[:100]}

def main():
    print("\n" + "="*70)
    print("🌊 SPICE Simulator Waveform Test Suite")
    print("="*70)
    print(f"NGSpice Binary: {NGSPICE_BIN}")
    print(f"API Endpoint: {API_ENDPOINT}")
    
    # Verify ngspice exists
    if not os.path.exists(NGSPICE_BIN):
        print(f"\n❌ ERROR: NGSpice binary not found at {NGSPICE_BIN}")
        return
    
    results = []
    for i, test_case in enumerate(TEST_CIRCUITS, 1):
        result = run_test(test_case)
        results.append({
            "name": test_case["name"],
            **result
        })
        
        if i < len(TEST_CIRCUITS):
            time.sleep(3)  # Rate limiting
    
    # Summary
    print("\n" + "="*70)
    print("📊 TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for r in results if r.get("status") == "Success")
    partial = sum(1 for r in results if r.get("status") == "Partial")
    failed = sum(1 for r in results if r.get("status") == "Failed")
    
    print(f"✅ Passed (with waveforms): {passed}")
    print(f"⚠️  Partial (simulation but no waveform): {partial}")
    print(f"❌ Failed: {failed}")
    
    print(f"\nResults:")
    for result in results:
        status_icon = "✅" if result["status"] == "Success" else "⚠️" if result["status"] == "Partial" else "❌"
        print(f"\n{status_icon} {result['name']}")
        print(f"   Status: {result['status']}")
        print(f"   Reason: {result.get('reason', 'N/A')}")
        if result.get('components'):
            print(f"   Components: {result['components']}")
        if result.get('data_points'):
            print(f"   Data Points: {result['data_points']}")

if __name__ == "__main__":
    main()
