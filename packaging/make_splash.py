"""Draws src/songselector/ui/splash.png, the image shown while the app starts. Run again only to change the design.

    python packaging/make_splash.py        (needs Pillow; not an app dependency)

Colours follow the dark theme (ui/theme.py). The bottom-left corner stays empty: the status text
("Starting...", "Loading your library...") is drawn there at runtime, see text_pos in packaging/SongSelector.spec and ui/splash.py.
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH, HEIGHT = 520, 260
BACKGROUND, TEXT, DIM = '#2b2d30', '#dfe1e5', '#8c9096'
# The map's group colours: the dots stand for tracks, similar ones close together.
DOT_COLOURS = ['#589df6', '#6fcf73', '#f0b45a', '#c678dd', '#56b6c2']
FONTS = Path('C:/Windows/Fonts')


def font(names, size):
    for name in names:
        try:
            return ImageFont.truetype(str(FONTS / name), size)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    image = Image.new('RGB', (WIDTH, HEIGHT), BACKGROUND)

    # A few clusters of soft dots on the right, like the similarity map.
    dots = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(dots)
    rng = random.Random(7)
    for colour, (cx, cy) in zip(DOT_COLOURS, [(400, 70), (455, 140), (365, 165), (440, 210), (330, 95)]):
        for _ in range(16):
            angle, radius = rng.uniform(0, 2 * math.pi), abs(rng.gauss(0, 18))
            x, y, r = cx + radius * math.cos(angle), cy + radius * math.sin(angle), rng.uniform(2.5, 4.5)
            draw.ellipse((x - r, y - r, x + r, y + r), fill=colour + 'b0')
    image.paste(dots.filter(ImageFilter.GaussianBlur(0.6)), (0, 0), dots.filter(ImageFilter.GaussianBlur(0.6)))

    draw = ImageDraw.Draw(image)
    draw.text((32, 74), 'SongSelector', font=font(['segoeuisb.ttf', 'segoeuib.ttf', 'arialbd.ttf'], 38), fill=TEXT)
    draw.text((34, 128), 'Harmonic keys and audio similarity', font=font(['segoeui.ttf', 'arial.ttf'], 15), fill=DIM)
    draw.text((34, 149), 'for DJs', font=font(['segoeui.ttf', 'arial.ttf'], 15), fill=DIM)
    draw.rectangle((34, 182, 74, 184), fill=DOT_COLOURS[0])  # accent line above the status text
    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline='#3c3f41')

    out = Path(__file__).resolve().parents[1] / 'src' / 'songselector' / 'ui' / 'splash.png'
    image.save(out, optimize=True)
    print(f'Wrote {out} ({out.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    main()
