#!/usr/bin/env python3
"""
Simple Streamlit launcher that works with VS Code debugger.
"""
import sys
import os
from pathlib import Path

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Set up environment for debugging
os.environ.update({
    "STREAMLIT_ENV": "development",
    "STREAMLIT_LOGGER_LEVEL": "debug",
    "STREAMLIT_SERVER_HEADLESS": "false",
    "STREAMLIT_SERVER_RUN_ON_SAVE": "true",
    "STREAMLIT_SERVER_ENABLE_CORS": "false",
    "PYTHONUNBUFFERED": "1",
})

if __name__ == "__main__":
    # Import and run streamlit
    import streamlit.web.cli as stcli
    
    # Set up arguments
    sys.argv = [
        "streamlit",
        "run",
        "boss_app.py",
        "--server.address=localhost",
        "--server.headless=false",
        "--server.runOnSave=true",
        "--server.enableCORS=false",
        "--logger.level=debug"
    ]
    
    # Run streamlit
    stcli.main()
