# Create a script to test loading the circuit store and print some information
from app.services.circuit_store import CircuitStore

def main():
    # Use CircuitStore with default path
    store = CircuitStore()
    store.load()
    print("Loaded circuits:", len(store.circuits))
    print("Priority order:", store.meta().get("priority_order"))
    
if __name__ == "__main__":
    main()