# Luồng kết nối giữa data -> logic -> kết quả
""" Là Implementation của CircuitRepo sử dụng JSON làm nguồn dữ liệu """

from typing import List, Dict, Any, Optional                     # Type hint -> Mô tả cấu trúc dữ liệu mạch điện                   
from app.repositories.circuit_repo import CircuitRepo            # Sử dụng Abstract Class - interface trừu tượng để định nghĩa các method trong circuit_repo [list_circuits, get_by_id, meta, search_best]
from app.services.circuit_store import CircuitStore              # Chịu trách nhiệm load Json, cache, validate -> không trực tiếp đọc file mà để CircuitStore lo
from app.services.matcher import match_circuit                   # Điểm kết nối data <-> logic: Hàm match_circuit thực hiện logic so khớp keyword và chấm điểm


class JsonCircuitRepo(CircuitRepo):
    """ CircuitRepo implementation backed by JSON file (Phase 2). """
    def __init__(self):
        self.store = CircuitStore().load()
        
    def list_circuits(self) -> List[Dict[str, Any]]:
        return self.store.circuits
    
    def get_by_id(self, circuit_id: str) -> Optional[Dict[str, Any]]:
        return next((cir for cir in self.store.circuits if cir.get("id") == circuit_id), None)
    
    def meta(self) -> Dict[str, Any]:
        return self.store.meta()
    
    
    def search_best(self, message: str) -> Dict[str, Any]:
        meta =  self.store.meta()
        return match_circuit(message, self.store.circuits, meta.get("priority_order", []))
