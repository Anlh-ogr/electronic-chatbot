# 
from app.services.circuit_store import CircuitStore

def main():
    # Use the correct absolute path to the JSON file
    store = CircuitStore("D:/Work/thesis/electronic-chatbot/apps/api/app/data/circuit_scope.json")
    db = store.load()
    print("Loaded circuits:", len(store.circuits))
    print("Priority order:", store.meta().get("priority_order"))
    
if __name__ == "__main__":
    main()