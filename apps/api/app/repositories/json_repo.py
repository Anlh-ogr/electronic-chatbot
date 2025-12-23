from .circuit_repo import CircuitRepo
from app.services.circuit_store import CircuitStore
from app.services.matcher import match_circuit
from typing import List

class JsonCircuitRepo(CircuitRepo):
    def __init__(self):
        self.store = CircuitStore()
        self.store.load()
        
    def list_circuits(self):
        return self.store.circuits
    
    def get_by_id(self, circuit_id: str):
        return next((cir for cir in self.store.circuits if cir["id"] == circuit_id), None)
    
    def search_by_keywords(self, message: str, priority_order: List[str]):
        return match_circuit(message, self.store.circuits, priority_order)
    
    def meta(self):
        return self.store.meta()