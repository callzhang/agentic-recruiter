#!/usr/bin/env python3
"""
Simple favicon validator - just checks if favicon.svg exists.

Modern browsers support SVG favicons directly, so no conversion is needed.
Just ensure web/static/favicon.svg exists and is valid SVG.
"""

import os
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
SVG_PATH = PROJECT_ROOT / "web/static/favicon.svg"

def main():
    """Check if favicon.svg exists."""
    if not SVG_PATH.exists():
        print(f"❌ SVG file not found: {SVG_PATH}")
        print(f"💡 Create a favicon.svg file at {SVG_PATH}")
        return 1
    
    # Basic validation - check if it's valid XML/SVG
    try:
        with open(SVG_PATH, 'r') as f:
            content = f.read()
            if '<svg' in content and '</svg>' in content:
                print(f"✅ Favicon SVG found and appears valid: {SVG_PATH}")
                print(f"📏 File size: {SVG_PATH.stat().st_size} bytes")
                return 0
            else:
                print(f"⚠️  File exists but doesn't appear to be valid SVG")
                return 1
    except Exception as e:
        print(f"❌ Error reading SVG file: {e}")
        return 1

if __name__ == "__main__":
    exit(main())
