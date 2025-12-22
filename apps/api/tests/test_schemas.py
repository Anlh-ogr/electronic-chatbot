import sys
from pathlib import Path

# Add the parent directory of the `app` module to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.models.schemas import ChatRequest
print ("Testing ChatRequest and ChatResponse schemas")
print ("OK")