"""Generate app icon variants for AI Token Usage Statistics.

Renders three candidates at high resolution with supersampling, then
exports per-variant previews (256px) plus a small-size legibility strip
(48/32/16px at 1x and 3x zoom) for evaluation. The chosen variant is
later packed into a multi-size .ico by the build script.

Run:  py assets/generate_icon.py
Out:  assets/icon-previews/variant-{a,b,c}.png, preview-sheet.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

# App theme (frontend/src/app.css)
INDIGO = (99, 102, 241, 255)      # --primary
INDIGO_LIGHT = (129, 140, 248, 255)  # --primary-hover
PURPLE = (139, 92, 246, 255)      # --purple
BLUE = (59, 130, 246, 255)        # --blue
GREEN = (16, 185, 129, 255)       # --green
DARK = (15, 23, 42, 255)          # slate-900

S = 1024  # master render size (supersampled 4x of 256)
OUT = Path(__file__).parent / "icon-previews"


def vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    """Two-stop vertical gradient."""
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return grad.resize((size, size))


def rounded_bg(radius: int = 224) -> Image.Image:
    """Transparent canvas with a rounded-square background."""
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=radius, fill=255)
    return mask


def compose(bg: Image.Image, mask: Image.Image) -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(bg, (0, 0), mask)
    return img


# ── Variant A: white ascending bars on indigo→purple gradient ──

def variant_a() -> Image.Image:
    mask = rounded_bg()
    img = compose(vertical_gradient(S, INDIGO_LIGHT, PURPLE), mask)
    d = ImageDraw.Draw(img)
    # 4 rounded bars, ascending, bottom-aligned; 16px legibility: bold + white
    bar_w, gap, bottom, radius = 120, 68, 780, 60
    heights = [220, 340, 470, 620]
    total_w = 4 * bar_w + 3 * gap
    x0 = (S - total_w) // 2
    for i, h in enumerate(heights):
        x1 = x0 + i * (bar_w + gap)
        d.rounded_rectangle(
            [x1, bottom - h, x1 + bar_w, bottom], radius=radius, fill=(255, 255, 255, 255)
        )
    return img


# ── Variant B: white rising polyline with arrowhead ──

def variant_b() -> Image.Image:
    mask = rounded_bg()
    img = compose(vertical_gradient(S, INDIGO_LIGHT, PURPLE), mask)
    d = ImageDraw.Draw(img)
    pts = [(220, 760), (440, 590), (620, 660), (820, 330)]
    lw = 86
    d.line(pts, fill=(255, 255, 255, 255), width=lw, joint="curve")
    r = lw // 2
    for (x, y) in pts:
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 255))
    # arrowhead
    tip, size = (830, 260), 130
    d.polygon(
        [(tip[0], tip[1]), (tip[0] - size, tip[1] + size // 2), (tip[0] - size // 2, tip[1] + size)],
        fill=(255, 255, 255, 255),
    )
    return img


# ── Variant C: colorful bars on dark card (dashboard style) ──

def variant_c() -> Image.Image:
    mask = rounded_bg()
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(DARK, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # thin border for contrast on dark taskbars
    d.rounded_rectangle([6, 6, S - 7, S - 7], radius=218, outline=(255, 255, 255, 60), width=10)
    bar_w, gap, bottom, radius = 128, 60, 790, 64
    colors = [GREEN, BLUE, INDIGO, PURPLE]
    heights = [230, 360, 500, 650]
    total_w = 4 * bar_w + 3 * gap
    x0 = (S - total_w) // 2
    for i, (h, c) in enumerate(zip(heights, colors)):
        x1 = x0 + i * (bar_w + gap)
        d.rounded_rectangle([x1, bottom - h, x1 + bar_w, bottom], radius=radius, fill=c)
    return img


VARIANTS = {"a": variant_a, "b": variant_b, "c": variant_c}


def downscale(img: Image.Image, size: int) -> Image.Image:
    return img.resize((size, size), Image.LANCZOS)


def export_build_assets(master: Image.Image) -> None:
    """Write multi-size app.ico and tray PNG used by packaging."""
    assets = Path(__file__).resolve().parent
    ico_path = assets / "app.ico"
    sizes = [(256, 256), (48, 48), (32, 32), (16, 16)]
    master.save(ico_path, format="ICO", sizes=sizes)
    downscale(master, 32).save(assets / "tray-32.png")
    print(f"wrote {ico_path} and {assets / 'tray-32.png'}")


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    OUT.mkdir(parents=True, exist_ok=True)
    renders = {}
    for key, fn in VARIANTS.items():
        master = fn()
        renders[key] = master
        downscale(master, 256).save(OUT / f"variant-{key}.png")

    # Preview sheet: each variant's 256 render + 48/32/16 actual sizes + 3x zoom of 16px
    pad, label_h = 40, 0
    cell_w = 256 + 3 * (64 + 16) + 2 * 48 + pad * 2
    cell_h = 256 + pad * 2
    sheet = Image.new("RGBA", (cell_w * 3 + pad * 2, cell_h + pad), (24, 30, 46, 255))
    d = ImageDraw.Draw(sheet)
    x = pad
    for key in renders:
        master = renders[key]
        sheet.paste(downscale(master, 256), (x, pad), downscale(master, 256))
        cx = x + 256 + 24
        for size in (48, 32, 16):
            small = downscale(master, size)
            sheet.paste(small, (cx, pad + 256 - size), small)
            cx += size + 16
        zoom = downscale(master, 16).resize((48, 48), Image.NEAREST)
        sheet.paste(zoom, (cx, pad + 256 - 48), zoom)
        d.text((x + 4, pad + 256 + 6), f"Variant {key.upper()}", fill=(255, 255, 255, 255))
        x += cell_w + pad
    sheet.save(OUT / "preview-sheet.png")
    print(f"written to {OUT}")

    if "--export-build-assets" in argv:
        export_build_assets(renders["a"])


if __name__ == "__main__":
    main()
