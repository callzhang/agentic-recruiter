#!/usr/bin/env python3
"""
Debug script for Streamlit development.
Provides enhanced debugging capabilities for the Boss直聘 application.
"""
import os
import sys
import subprocess
from pathlib import Path

def setup_debug_environment():
    """Setup debug environment variables."""
    debug_env = {
        "STREAMLIT_ENV": "development",
        "STREAMLIT_LOGGER_LEVEL": "debug",
        "STREAMLIT_SERVER_HEADLESS": "false",
        "STREAMLIT_SERVER_RUN_ON_SAVE": "true",
        "STREAMLIT_SERVER_ENABLE_CORS": "false",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(Path.cwd()),
    }
    
    for key, value in debug_env.items():
        os.environ[key] = value
        print(f"Set {key}={value}")

def run_streamlit_debug():
    """Run Streamlit in debug mode."""
    print("🚀 Starting Streamlit in DEBUG mode...")
    print("📍 URL: http://localhost:8501")
    print("🔧 Debug features enabled:")
    print("   - Auto-reload on file changes")
    print("   - Debug logging enabled")
    print("   - CORS disabled for development")
    print("   - Error details shown")
    print("\n" + "="*50)
    
    # Streamlit command with debug options
    cmd = [
        "/opt/homebrew/bin/streamlit", "run", "boss_app.py",
        "--server.port=8501",
        "--server.address=localhost",
        "--server.headless=false",
        "--server.runOnSave=true",
        "--server.enableCORS=false",
        "--logger.level=debug",
        "--global.developmentMode=true",
        "--global.showErrorDetails=true"
    ]
    
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\n🛑 Streamlit debug session stopped by user")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error running Streamlit: {e}")
        sys.exit(1)

if __name__ == "__main__":
    setup_debug_environment()
    run_streamlit_debug()
