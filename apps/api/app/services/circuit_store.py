# Read database first when server starts
import json
from pathlib import Path

# create class call json file
class CircuitStore:
    # Initialize with path to json file
    def __init__(self, json_path: str = None):
        # Set default path if json_path is not provided
        default_path = Path(__file__).parent.parent / "data" / "circuit_scope.json"
        self.json_path = Path(json_path) if json_path else default_path
        self.database = None

        # Check if the file exists
        if not self.json_path.exists():
            raise FileNotFoundError(f"The file '{self.json_path}' does not exist. Please check the path.")

    # Load json file
    def load(self):
        # Ensure self.json_path is a Path object
        if not isinstance(self.json_path, Path):
            self.json_path = Path(self.json_path)
        self.database = json.loads(self.json_path.read_text(encoding="utf-8"))
        return self.database

    # Property to get circuits from database
    @property
    def circuits(self):
        return self.database.get("circuits", []) if self.database else []
    
    
    def meta(self):
        if not self.database:
            return {}
        return { "priority_order": self.database.get("priority_order", []),
                 "fallback_response": self.database.get("fallback_response", ""),
                 "out_of_scope": self.database.get("out_of_scope", {}) }