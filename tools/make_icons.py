#!/usr/bin/env python3
"""Generate assets/logo.png and assets/logo.ico (Pillow). Run from repo root or before PyInstaller."""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    assets = root / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    png = assets / "logo.png"
    ico = assets / "logo.ico"
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Install Pillow first:  pip install Pillow", file=sys.stderr)
        return 1

    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 32
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=36,
        fill=(14, 165, 233, 255),
        outline=(56, 189, 248, 255),
        width=4,
    )
    try:
        from PIL import ImageFont
        try:
            font = ImageFont.truetype("segoeui.ttf", 72)
        except OSError:
            font = ImageFont.load_default()
        draw.text((88, 96), "DV", fill=(255, 255, 255, 255), font=font)
    except Exception:
        draw.text((88, 96), "DV", fill=(255, 255, 255, 255))
    img.save(png, "PNG")
    img.save(
        ico,
        format="ICO",
        sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    print("Wrote", png, "and", ico)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
