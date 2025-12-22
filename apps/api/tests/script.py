# Create a script to test loading the circuit store and print some information
import sys
from pathlib import Path

# Add the parent directory of the `app` module to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.services.circuit_store import CircuitStore


def main():
    # Use CircuitStore with default path
    store = CircuitStore()
    store.load()
    print("Loaded circuits:", len(store.circuits))
    print("Priority order:", store.meta().get("priority_order"))

if __name__ == "__main__":
    main()