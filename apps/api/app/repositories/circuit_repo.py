from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class CircuitRepo(ABC):
    @abstractmethod
    def list_circuits(self) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def get_by_id(self, circuit_id: str) -> Optional[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def search_by_keywords(self, message: str, priority_order: List[str]) -> Dict[str, Any]:
        pass
    
    @abstractmethod
    def meta(self) -> Dict[str, Any]:
        pass