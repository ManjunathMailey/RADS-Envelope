r"""
Brand assets for the landing page: favicon (SVG + 32 px PNG) and the Open Graph image (1200x630).

    .\.venv-data\Scripts\python.exe data_tools\brand_assets.py

The mark is a bracket around a dot: a range around a point, i.e. the Certainty Envelope.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "web" / "static" / "brand"
INK, BLUE, BG, MUTED = (29, 29, 31), (0, 113, 227), (245, 245, 247), (110, 110, 115)
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
       '<rect width="24" height="24" rx="6" fill="#f5f5f7"/>'
       '<path d="M8.5 4.5H5.5v15h3M15.5 4.5h3v15h-3" fill="none" stroke="#1d1d1f" stroke-width="2" '
       'stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="12" r="2.6" fill="#0071e3"/></svg>\n')


def mark(draw, x, y, s, bg=None):
    """Draw the mark in a 24-unit box at (x, y) with unit size s."""
    u = lambda v: v * s
    if bg:
        draw.rounded_rectangle([x, y, x + u(24), y + u(24)], radius=u(6), fill=bg)
    w = max(1, round(u(2)))
    for pts in (((8.5, 4.5), (5.5, 4.5), (5.5, 19.5), (8.5, 19.5)), ((15.5, 4.5), (18.5, 4.5), (18.5, 19.5), (15.5, 19.5))):
        draw.line([(x + u(a), y + u(b)) for a, b in pts], fill=INK, width=w, joint="curve")
    draw.ellipse([x + u(12 - 2.6), y + u(12 - 2.6), x + u(12 + 2.6), y + u(12 + 2.6)], fill=BLUE)


def font(name, size):
    try:
        return ImageFont.truetype(rf"C:\Windows\Fonts\{name}", size)
    except OSError:
        return ImageFont.load_default()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "favicon.svg").write_text(SVG, encoding="utf-8")
    big = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    mark(ImageDraw.Draw(big), 0, 0, 256 / 24, bg=BG)
    big.resize((32, 32), Image.LANCZOS).save(OUT / "favicon-32.png")

    og = Image.new("RGB", (1200, 630), BG)
    d = ImageDraw.Draw(og)
    mark(d, 96, 150, 6)                                     # 144 px mark
    d.text((96, 330), "RADS-Envelope", font=font("segoeuib.ttf", 92), fill=INK)
    d.text((100, 455), "LI-RADS reports that never contradict the rules,", font=font("segoeui.ttf", 38), fill=MUTED)
    d.text((100, 505), "and say exactly what is still uncertain.", font=font("segoeui.ttf", 38), fill=MUTED)
    og.save(OUT / "og.png", optimize=True)
    for f in sorted(OUT.iterdir()):
        print(f.name, f.stat().st_size)


if __name__ == "__main__":
    main()
