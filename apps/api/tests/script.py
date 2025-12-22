# Create a script to test loading the circuit store and print some information
import sys
from pathlib import Path

# Add the parent directory of the `app` module to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.services.circuit_store import CircuitStore
from app.services.matcher import match_circuit
from app.services.formatter import render_circuit_answer


def main():
    # Use CircuitStore with default path
    store = CircuitStore()
    store.load()
    print("Loaded circuits:", len(store.circuits))
    print("Priority order:", store.meta().get("priority_order"))

    # Example: Match a circuit and render the result
    message = "Mạch tăng áp 5V lên 12V"
    meta = store.meta()
    result = match_circuit(message, store.circuits, meta.get("priority_order", []))

    if result["matched"]:
        rendered_text = render_circuit_answer(result["circuit"])
        print(rendered_text)
    else:
        print("No matching circuit found.")

if __name__ == "__main__":
    main()