"""Draws src/songselector/ui/icon.png, the app icon (window, Linux desktop entry and AppImage). Run again only to
change the design.

    python packaging/make_icon.py        (needs Pillow; not an app dependency)

The same look as the splash screen (make_splash.py): clusters of dots in the map's group colours on the dark
theme's background, like tracks on the similarity map.
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw

SIZE, SCALE = 256, 4          # drawn 4x larger and scaled down: smooth edges without a blur
BACKGROUND, BORDER = '#2b2d30', '#3c3f41'
DOT_COLOURS = ['#589df6', '#6fcf73', '#f0b45a', '#c678dd', '#56b6c2']
CLUSTERS = [(0.62, 0.27), (0.76, 0.58), (0.45, 0.70), (0.27, 0.40), (0.47, 0.45)]   # centres, share of the size


def main():
    size = SIZE * SCALE
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin, radius = 8 * SCALE, 48 * SCALE
    draw.rounded_rectangle((margin, margin, size - margin, size - margin), radius, fill=BACKGROUND,
                           outline=BORDER, width=3 * SCALE)
    rng = random.Random(7)
    for colour, (cx, cy) in zip(DOT_COLOURS, CLUSTERS):
        for _ in range(9):
            angle, spread = rng.uniform(0, 2 * math.pi), abs(rng.gauss(0, 0.055))
            x = (cx + spread * math.cos(angle)) * size
            y = (cy + spread * math.sin(angle)) * size
            r = rng.uniform(0.022, 0.034) * size
            draw.ellipse((x - r, y - r, x + r, y + r), fill=colour)
    out = Path(__file__).resolve().parents[1] / 'src' / 'songselector' / 'ui' / 'icon.png'
    image.resize((SIZE, SIZE), Image.LANCZOS).save(out, optimize=True)
    print(f'Wrote {out} ({out.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    main()
