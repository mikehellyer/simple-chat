"""One-off script: draws the Simple-Chat app icon and exports every
size/format the platform installers need. Not part of the app itself and
not run automatically — re-run manually if the icon design ever changes.

Usage: venv/bin/python packaging/icons/generate_icon.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT_DIR = Path(__file__).parent
APP_RESOURCES = OUT_DIR.parent.parent / "src" / "simple_chat" / "gui" / "resources"
SIZE = 1024

# Two overlapping speech bubbles on a blue tile: a white one in front
# (yours) and a paler one behind it (theirs), with three typing dots.
TILE_TOP = (72, 134, 255, 255)
TILE_BOTTOM = (31, 84, 214, 255)
WHITE = (255, 255, 255, 255)
BACK = (190, 212, 255, 255)
DOT = (47, 111, 237, 255)


def draw_icon() -> Image.Image:
    tile = Image.new("RGBA", (SIZE, SIZE))
    td = ImageDraw.Draw(tile)
    for y in range(SIZE):
        t = y / SIZE
        td.line([(0, y), (SIZE, y)], fill=tuple(int(TILE_TOP[i] + (TILE_BOTTOM[i] - TILE_TOP[i]) * t) for i in range(3)) + (255,))
    mask = Image.new("L", (SIZE, SIZE), 0)
    margin = SIZE * 0.06
    ImageDraw.Draw(mask).rounded_rectangle([margin, margin, SIZE - margin, SIZE - margin], radius=SIZE * 0.22, fill=255)
    img = tile
    s = SIZE / 100

    back = _bubble(s, 30, 20, 82, 58, tail_left=False)
    front = _bubble(s, 18, 36, 72, 76, tail_left=True)
    for shape, colour in ((back, BACK), (front, WHITE)):
        shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        shadow.paste((0, 0, 30, 110), (0, int(1.6 * s)), shape)
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(SIZE * 0.018)))
        img.paste(Image.new("RGBA", (SIZE, SIZE), colour), (0, 0), shape)

    d = ImageDraw.Draw(img)
    for i in range(3):
        cx, cy, r = (33 + i * 12) * s, 56 * s, 4.2 * s
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=DOT)

    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _bubble(s: float, left: float, top: float, right: float, bottom: float, tail_left: bool) -> Image.Image:
    """A rounded speech bubble with a tail under one corner, as a mask."""
    m = Image.new("L", (SIZE, SIZE), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([left * s, top * s, right * s, bottom * s], radius=11 * s, fill=255)
    if tail_left:
        d.polygon([((left + 8) * s, (bottom - 4) * s), ((left + 2) * s, (bottom + 9) * s), ((left + 20) * s, (bottom - 2) * s)], fill=255)
    else:
        d.polygon([((right - 8) * s, (bottom - 4) * s), ((right - 2) * s, (bottom + 8) * s), ((right - 20) * s, (bottom - 2) * s)], fill=255)
    return m


def main() -> None:
    icon = draw_icon()
    master_png = OUT_DIR / "icon.png"
    icon.save(master_png)
    print(f"wrote {master_png}")

    APP_RESOURCES.mkdir(parents=True, exist_ok=True)
    icon.resize((256, 256), Image.LANCZOS).save(APP_RESOURCES / "icon.png")
    print(f"wrote {APP_RESOURCES / 'icon.png'}")

    # Windows .ico (multi-resolution)
    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    ico_path = OUT_DIR / "icon.ico"
    icon.save(ico_path, sizes=[(s, s) for s in ico_sizes])
    print(f"wrote {ico_path}")

    # Linux: a few common hicolor sizes as plain PNGs.
    for s in (16, 32, 48, 64, 128, 256, 512):
        icon.resize((s, s), Image.LANCZOS).save(OUT_DIR / f"icon_{s}.png")
    print("wrote icon_16..512.png")

    # macOS .icns: iconutil on a Mac; elsewhere Pillow's own ICNS writer is
    # good enough to commit, so CI on macOS always has a file to use.
    if sys.platform == "darwin" and shutil.which("iconutil"):
        iconset = OUT_DIR / "icon.iconset"
        iconset.mkdir(exist_ok=True)
        for s in (16, 32, 128, 256, 512):
            icon.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
            icon.resize((s * 2, s * 2), Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(OUT_DIR / "icon.icns")],
            check=True,
        )
        for f in iconset.iterdir():
            f.unlink()
        iconset.rmdir()
    else:
        icon.save(OUT_DIR / "icon.icns")
    print(f"wrote {OUT_DIR / 'icon.icns'}")


if __name__ == "__main__":
    main()
