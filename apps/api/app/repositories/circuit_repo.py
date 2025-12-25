# Không chứa dữ liệu, Không chứa logic match
""" Là hợp đồng (interface / abstract layer) cho các repo mạch điện. 
    JSON (phase 0-1) - Database (phase 2) - Vector DB/AI (phase 3) """

from abc import ABC, abstractmethod             # Abstract Base Class-Class trừu tượng (interface) -> tất cả repo tuân theo cùng chuẩn
from typing import List, Dict, Any, Optional    # Type hinting - Dễ đọc/review/test

# Định nghĩa interface trừu tượng cho Circuit Repository
class CircuitRepo(ABC):
    """ Data Access Layer interface (Phase 2 foundation for Postgres later)."""
    @abstractmethod
    def list_circuits(self) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def get_by_id(self, circuit_id: str) -> Optional[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def meta(self) -> Dict[str, Any]:
        pass
    
    @abstractmethod
    def search_best(self, message: str) -> Dict[str, Any]:
        """ Return: {'matched': bool, 'circuit'?: dict, 'debug'?: dict} """
        pass
    