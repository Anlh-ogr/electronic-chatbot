from app.services.circuit_store import CircuitStore
from app.services.matcher import match_circuit
from pathlib import Path

# Ensure the JSON file exists
json_path = "D:/Work/thesis/electronic-chatbot/apps/api/app/data/circuit_scope.json"
if not Path(json_path).exists():
    raise FileNotFoundError(f"The file '{json_path}' does not exist.")

# Load the circuit store
store = CircuitStore(json_path)  # Keep store as a CircuitStore object
store.load()  # Load the data into the store object
meta = store.meta()

# Test cases
tests = [
    "Mạch tăng áp 5V lên 12V",
    "Mạch giảm áp 24V xuống 5V",
    "Khuếch đại đảo LM358 gain 10",
    "Mạch nhạc 555",
    "Thiết kế mạch RF 2.4GHz",
]

for t in tests:
    r = match_circuit(t, store.circuits, meta.get("priority_order", []))
    print("\nQues:", t)
    if r.get("match_keys"):
        print("Matched:", True)
        print("Ans:", r["circuit"].get("id"), r["circuit"].get("name"))
        print("KeyWords:", r.get("match_keys"))
    else:
        print("Matched:", False)
