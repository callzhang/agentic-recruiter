#!/usr/bin/env python3
"""
Generate favicon files from SVG.

Requires: pip install cairosvg pillow

Usage: python scripts/generate_favicon.py
"""

import os
from pathlib import Path

try:
    import cairosvg
    from PIL import Image
    import io
except ImportError:
    print("⚠️  Required packages not installed.")
    print("Run: pip install cairosvg pillow")
    exit(1)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
SVG_PATH = PROJECT_ROOT / "web/static/favicon.svg"
STATIC_DIR = PROJECT_ROOT / "web/static"

def generate_png_sizes():
    """Generate PNG files in various sizes."""
    sizes = [16, 32, 48, 64, 128, 256]
    
    for size in sizes:
        png_data = cairosvg.svg2png(
            url=str(SVG_PATH),
            output_width=size,
            output_height=size
        )
        
        output_path = STATIC_DIR / f"favicon-{size}x{size}.png"
        with open(output_path, 'wb') as f:
            f.write(png_data)
        print(f"✅ Generated {output_path.name}")

def generate_ico():
    """Generate .ico file with multiple sizes."""
    sizes = [(16, 16), (32, 32), (48, 48)]
    images = []
    
    for width, height in sizes:
        png_data = cairosvg.svg2png(
            url=str(SVG_PATH),
            output_width=width,
            output_height=height
        )
        img = Image.open(io.BytesIO(png_data))
        images.append(img)
    
    ico_path = STATIC_DIR / "favicon.ico"
    images[0].save(
        ico_path,
        format='ICO',
        sizes=sizes,
        append_images=images[1:]
    )
    print(f"✅ Generated {ico_path.name}")

def main():
    if not SVG_PATH.exists():
        print(f"❌ SVG file not found: {SVG_PATH}")
        exit(1)
    
    print("🎨 Generating favicon files...")
    generate_png_sizes()
    generate_ico()
    print("✅ All favicon files generated successfully!")

if __name__ == "__main__":
    main()

