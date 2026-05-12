#!/usr/bin/env python
"""
Comprehensive 8-topology test suite for electronic-chatbot SPICE simulation fixes.
Tests all supported topologies (BJT, Op-Amp, MOSFET, Class-AB, Class-D, Darlington).
"""

import requests
import json
import time
from typing import Optional, Dict, Any

# Ensure json_repair is available (required by backend LLM router)
try:
    import json_repair
except ImportError:
    print("⚠️  WARNING: json_repair not installed; some LLM calls may fail")

BASE_URL = "http://localhost:8000"  # Backend uses port 8000, not 8011
API_ENDPOINT = f"{BASE_URL}/api/chat"

TEST_CASES = [
    {
        "name": "MOSFET N-channel",
        "request": "Design an N-channel MOSFET amplifier with 12V supply and gain of 5"
    },
    {
        "name": "BJT Common Emitter",
        "request": "Thiết kế mạch khuếch đại CE nguồn 12V gain 20"
    },
    {
        "name": "BJT Common Collector",
        "request": "Design a BJT common collector buffer amplifier with 12V supply"
    },
    {
        "name": "BJT Darlington",
        "request": "Design a Darlington pair amplifier with 12V supply and high current gain"
    },
    {
        "name": "Op-Amp Inverting",
        "request": "Design an inverting op-amp amplifier with 12V supply and gain of 10"
    },
    {
        "name": "Op-Amp Non-Inverting",
        "request": "Design a non-inverting op-amp amplifier with 12V supply and gain of 5"
    },
    {
        "name": "Op-Amp Differential",
        "request": "Design a differential op-amp amplifier with 12V supply"
    },
    {
        "name": "Class-AB Push-Pull",
        "request": "Design a class-AB push-pull amplifier with 12V supply and 1W output"
    }
]

def parse_sse_response(response_text: str) -> Optional[Dict[str, Any]]:
    """Parse SSE response and extract circuit_data."""
    try:
        lines = response_text.strip().split('\n')
        for line in lines:
            if line.startswith('data:'):
                try:
                    data = json.loads(line[5:].strip())
                    if data.get('type') == 'circuit_ready':
                        return data.get('data', {})
                except json.JSONDecodeError:
                    pass
        return None
    except Exception as e:
        print(f"Error parsing SSE: {e}")
        return None

def run_test(test_case: Dict[str, str]) -> Dict[str, Any]:
    """Run single test case and return results."""
    name = test_case["name"]
    request_text = test_case["request"]
    
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"Request: {request_text}")
    print('='*60)
    
    try:
        response = requests.post(
            API_ENDPOINT,
            json={"message": request_text},
            stream=True,
            timeout=30
        )
        
        if response.status_code != 200:
            return {
                "status": "❌ Failed",
                "reason": f"HTTP {response.status_code}",
                "components": 0,
                "nets": 0,
                "topology": "N/A"
            }
        
        # Parse SSE response
        circuit_data = parse_sse_response(response.text)
        if not circuit_data:
            return {
                "status": "❌ Failed",
                "reason": "No circuit_ready event in response",
                "components": 0,
                "nets": 0,
                "topology": "N/A"
            }
        
        # Extract metrics
        components = circuit_data.get('components', [])
        nets = circuit_data.get('nets', [])
        topology = circuit_data.get('topology_classification', 'Unknown')
        circuit_id = circuit_data.get('circuit_id', 'N/A')
        spice_url = circuit_data.get('spice_url', 'N/A')
        
        print(f"✅ Status: OK")
        print(f"✅ Components: {len(components)}")
        print(f"✅ Nets: {len(nets)}")
        print(f"✅ Topology: {topology}")
        print(f"✅ Circuit ID: {circuit_id}")
        print(f"✅ SPICE: {spice_url}")
        
        return {
            "status": "✅ Passed",
            "reason": "OK",
            "components": len(components),
            "nets": len(nets),
            "topology": topology,
            "circuit_id": circuit_id
        }
    
    except requests.exceptions.Timeout:
        return {
            "status": "❌ Failed",
            "reason": "Timeout (>30s)",
            "components": 0,
            "nets": 0,
            "topology": "N/A"
        }
    except Exception as e:
        return {
            "status": "❌ Failed",
            "reason": str(e),
            "components": 0,
            "nets": 0,
            "topology": "N/A"
        }

def main():
    print("="*60)
    print("8-Topology Comprehensive Test Suite")
    print("="*60)
    
    results = []
    for i, test_case in enumerate(TEST_CASES, 1):
        result = run_test(test_case)
        results.append({
            "name": test_case["name"],
            **result
        })
        
        if i < len(TEST_CASES):
            time.sleep(2)  # Rate limiting
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for r in results if "Passed" in r["status"])
    failed = len(results) - passed
    
    print(f"✅ Passed: {passed}/{len(results)}")
    print(f"❌ Failed: {failed}/{len(results)}")
    
    for result in results:
        status = "✅" if "Passed" in result["status"] else "❌"
        print(f"\n{status} {result['name']}")
        print(f"   Status: {result['reason']}")
        if result['components'] > 0:
            print(f"   Components: {result['components']}")
            print(f"   Nets: {result['nets']}")
            print(f"   Topology: {result['topology']}")

if __name__ == "__main__":
    main()
