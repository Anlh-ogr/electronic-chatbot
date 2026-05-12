#!/usr/bin/env python3
"""Test op-amp and BJT amplifier designs end-to-end."""

import requests
import json
import time
from pathlib import Path

BASE_URL = "http://localhost:8000/api/chat"

TEST_CASES = [
    {
        "name": "BJT Common Emitter",
        "request": "Thiết kế mạch khuếch đại CE nguồn 12V gain 20",
        "expected_components": ["BJT", "bc547", "npn"],
    },
    {
        "name": "Op-Amp Inverting",
        "request": "Design an inverting op-amp amplifier with 12V supply and gain of 10",
        "expected_components": ["opamp", "op-amp", "lm358"],
    },
    {
        "name": "Op-Amp Non-Inverting",
        "request": "Design a non-inverting op-amp amplifier with 12V supply and gain of 5",
        "expected_components": ["opamp", "op-amp", "lm358"],
    },
]

def test_circuit(test_case):
    """Test a single circuit design."""
    name = test_case["name"]
    request_text = test_case["request"]
    
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"Request: {request_text}")
    print(f"{'='*60}")
    
    try:
        payload = {"message": request_text}
        
        # Stream SSE response
        response = requests.post(
            BASE_URL,
            json=payload,
            stream=True,
            timeout=120
        )
        
        if response.status_code != 200:
            print(f"❌ HTTP {response.status_code}")
            print(response.text[:500])
            return {"status": "failed", "error": f"HTTP {response.status_code}"}
        
        # Parse SSE events
        circuit_data = None
        circuit_id = None
        has_render = False
        
        for line in response.iter_lines():
            if not line:
                continue
            
            line = line.decode('utf-8') if isinstance(line, bytes) else line
            
            if line.startswith("event: circuit_ready"):
                continue
            elif line.startswith("data: ") and circuit_data is None:
                try:
                    data = json.loads(line[6:])
                    if "circuit_data" in data:
                        circuit_data = data["circuit_data"]
                        circuit_id = data.get("circuit_id")
                except:
                    pass
            elif line.startswith("event: render_ready"):
                has_render = True
            elif line.startswith("data: ") and has_render:
                try:
                    data = json.loads(line[6:])
                    if "sch_url" in data:
                        print(f"✅ Schematic URL: {data['sch_url']}")
                        print(f"✅ SPICE URL: {data.get('ngspice_url', 'N/A')}")
                except:
                    pass
        
        # Analyze results
        if not circuit_data:
            print(f"❌ No circuit data returned")
            return {"status": "failed", "error": "No circuit_data"}
        
        if not circuit_data.get("is_valid_request"):
            print(f"❌ Invalid request (clarification needed)")
            return {"status": "failed", "error": "Clarification required"}
        
        components = circuit_data.get("components", [])
        nets = circuit_data.get("nets", [])
        
        print(f"✅ Components: {len(components)}")
        print(f"✅ Nets: {len(nets)}")
        print(f"✅ Topology: {circuit_data.get('analysis', {}).get('topology_classification', 'Unknown')}")
        
        # Check component types
        comp_types = [str(c.get("type", "")).lower() for c in components]
        comp_values = [str(c.get("value", "")).lower() for c in components]
        all_refs = str(comp_types) + " " + str(comp_values)
        
        found_expected = False
        for expected in test_case.get("expected_components", []):
            if expected.lower() in all_refs:
                found_expected = True
                break
        
        if not found_expected:
            print(f"⚠️  Expected component type not clearly identified")
        
        # Check SPICE deck
        spice_url = circuit_data.get("spice_url")
        if spice_url:
            print(f"✅ SPICE deck available")
        
        print(f"✅ Circuit ID: {circuit_id}")
        
        return {
            "status": "passed",
            "circuit_id": circuit_id,
            "components": len(components),
            "nets": len(nets),
            "topology": circuit_data.get("analysis", {}).get("topology_classification", "Unknown"),
        }
        
    except requests.exceptions.Timeout:
        print(f"❌ Request timeout (>120s)")
        return {"status": "failed", "error": "Timeout"}
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return {"status": "failed", "error": str(e)}

def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("Op-Amp & BJT Amplifier Test Suite")
    print("="*60)
    
    results = {}
    passed = 0
    failed = 0
    
    for test_case in TEST_CASES:
        result = test_circuit(test_case)
        results[test_case["name"]] = result
        
        if result["status"] == "passed":
            passed += 1
        else:
            failed += 1
        
        time.sleep(2)  # Rate limit
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"✅ Passed: {passed}/{len(TEST_CASES)}")
    print(f"❌ Failed: {failed}/{len(TEST_CASES)}")
    
    for name, result in results.items():
        status_icon = "✅" if result["status"] == "passed" else "❌"
        print(f"\n{status_icon} {name}")
        if result["status"] == "passed":
            print(f"   Components: {result['components']}")
            print(f"   Nets: {result['nets']}")
            print(f"   Topology: {result['topology']}")
        else:
            print(f"   Error: {result['error']}")

if __name__ == "__main__":
    main()
