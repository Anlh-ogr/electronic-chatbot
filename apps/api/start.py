"""Start script for FastAPI server."""

import sys
import os
from pathlib import Path

# Get the directory containing this script
script_dir = Path(__file__).parent.absolute()

# Add api directory to Python path
sys.path.insert(0, str(script_dir))

# Set working directory
os.chdir(script_dir)

if __name__ == "__main__":
    import uvicorn
    
    print("🚀 Starting Electronic Chatbot API...")
    print(f"📂 Working directory: {script_dir}")
    print("📍 Swagger UI: http://localhost:8000/docs")
    print("📍 ReDoc: http://localhost:8000/redoc")
    print("")
    
    # Import app after path is set
    from app.main import app
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )
