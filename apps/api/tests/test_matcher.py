import sys
from pathlib import Path

# Add the parent directory of the `app` module to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.services.circuit_store import CircuitStore
from app.services.matcher import match_circuit

# Load the circuit store using default path
store = CircuitStore()
store.load()  # Load the data into the store object
meta = store.meta()

# Test cases
tests = [
    "Mạch tăng áp 5V lên 12V",
    "Mạch giảm áp 24V xuống 5V",
    "Khuếch đại đảo LM358 gain 10",
    "Mạch nhạc 555",
    "Thiết kế mạch RF 2.4GHz"
]  # Properly close the list

for t in tests:
    r = match_circuit(t, store.circuits, meta.get("priority_order", []))
    print("\nQ:", t)
    print("Matched:", r["matched"])
    if r["matched"]:
        print("-> Circuit ID:", r["circuit"].get("id"))
        print("-> Circuit Name:", r["circuit"].get("name"))
        print("Matched Keywords:", r["debug"].get("matched_keywords"))
        print("Score:", r["debug"].get("score"))
    else:
        print("No matching circuit found.")
        if "debug" in r:
            print("Debug Info:", r["debug"])