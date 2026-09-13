"""
OviX Backend Entry Point for Nuitka/PyInstaller
This script is the entry point for the compiled executable.
It starts the FastAPI backend server.
"""

import sys
import os
from pathlib import Path

# Add the backend/src directory to the path
current_path = Path(__file__).resolve()
backend_src = current_path.parent.parent / 'src'
sys.path.insert(0, str(backend_src))

# Import and run the main FastAPI app
if __name__ == '__main__':
    import uvicorn
    from backend.api.main import app
    
    # Get configuration from environment or use defaults
    host = os.environ.get('API_HOST', '127.0.0.1')
    port = int(os.environ.get('API_PORT', '8000'))
    
    print(f"Starting OviX Backend on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
