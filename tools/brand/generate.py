#!/usr/bin/env python3
"""Generate GridLens brand vectors and raster exports from one Aperture geometry.

Requires Python, Pillow, NumPy, fontTools, and DejaVu Sans Bold.
Run from the repository root: python3 tools/brand/generate.py
The SVG wordmark is outlined so it remains stable on machines without the font.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "public" / "brand"
OUT.mkdir(parents=True, exist_ok=True)
FONT = Path(os.environ.get("GRIDLENS_WORDMARK_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
if not FONT.exists():
    raise SystemExit(f"Missing wordmark outline font: {FONT}. Set GRIDLENS_WORDMARK_FONT.")

COLORS = {
    "deep_current": "#101F2D",
    "gridlens_navy": "#17324A",
    "steel_blue": "#395A75",
    "atmosphere": "#6F879D",
    "mist": "#D5DEE5",
    "ice": "#F3F6F7",
    "white": "#FFFFFF",
}

# Geometry traced from the owner-provided brand-system reference. The white
# diamond, top slit, and bottom slit are unpainted negative space.
SHAPES = (
    ("upper-left", "284,0 0,181 0,404 127,295 284,185"),
    ("upper-right", "340,0 624,181 624,404 497,295 340,185"),
    ("lower-left", "0,404 284,580 284,402 127,295"),
    ("lower-right", "624,404 340,580 340,402 497,295"),
)

GRADIENTS = """<defs>
  <linearGradient id="ul" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#284761"/><stop offset="1" stop-color="#17324A"/></linearGradient>
  <linearGradient id="ur" x1="0" y1="0" x2="1" y2=".4"><stop stop-color="#E5F0F6"/><stop offset=".42" stop-color="#88A1B4"/><stop offset="1" stop-color="#18324A"/></linearGradient>
  <linearGradient id="ll" x1="0" y1=".2" x2="1" y2="1"><stop stop-color="#395A75"/><stop offset=".5" stop-color="#85A0B3"/><stop offset="1" stop-color="#DAE8F1"/></linearGradient>
  <linearGradient id="lr" x1="0" y1="1" x2="1" y2="0"><stop stop-color="#496B84"/><stop offset="1" stop-color="#101F2D"/></linearGradient>
</defs>"""

LIGHT_GRADIENTS = """<defs>
  <linearGradient id="ul" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#FFFFFF"/><stop offset="1" stop-color="#BFD1E0"/></linearGradient>
  <linearGradient id="ur" x1="0" y1="0" x2="1" y2=".4"><stop stop-color="#FFFFFF"/><stop offset="1" stop-color="#91ACC0"/></linearGradient>
  <linearGradient id="ll" x1="0" y1=".2" x2="1" y2="1"><stop stop-color="#B4C9D8"/><stop offset="1" stop-color="#FFFFFF"/></linearGradient>
  <linearGradient id="lr" x1="0" y1="1" x2="1" y2="0"><stop stop-color="#F3F8FA"/><stop offset="1" stop-color="#A3B9C8"/></linearGradient>
</defs>"""


def svg(width: int, height: int, view_box: str, inner: str, *, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="{view_box}" role="img" aria-label="{escape(label)}">'
        f"<title>{escape(label)}</title>{inner}</svg>\n"
    )


def mark(mode: str) -> str:
    if mode == "gradient":
        defs, fills = GRADIENTS, [f"url(#{x})" for x in ("ul", "ur", "ll", "lr")]
    elif mode == "light-gradient":
        defs, fills = LIGHT_GRADIENTS, [f"url(#{x})" for x in ("ul", "ur", "ll", "lr")]
    elif mode == "navy":
        defs, fills = "", [COLORS["gridlens_navy"]] * 4
    elif mode == "white":
        defs, fills = "", [COLORS["white"]] * 4
    else:
        raise ValueError(mode)
    polygons = "".join(
        f'<polygon id="{name}" points="{points}" fill="{fills[i]}"/>'
        for i, (name, points) in enumerate(SHAPES)
    )
    return defs + polygons


def outlined_wordmark(fill: str) -> str:
    font = TTFont(FONT)
    cmap = font.getBestCmap()
    glyphs = font.getGlyphSet()
    hmetrics = font["hmtx"].metrics
    advance = 0
    paths = []
    for character in "GridLens":
        glyph_name = cmap[ord(character)]
        pen = SVGPathPen(glyphs)
        glyphs[glyph_name].draw(pen)
        paths.append(f'<path d="{pen.getCommands()}" transform="translate({advance},0)"/>')
        advance += hmetrics[glyph_name][0]
    return f'<g fill="{fill}" aria-hidden="true">{"".join(paths)}</g>'


def lockup(*, dark_surface: bool, stacked: bool = False) -> str:
    ink = COLORS["white"] if dark_surface else COLORS["deep_current"]
    symbol = mark("light-gradient" if dark_surface else "gradient")
    wordmark = outlined_wordmark(ink)
    if stacked:
        symbol_group = f'<g transform="translate(104 20) scale(.30)">{symbol}</g>'
        text_group = f'<g transform="translate(42 306) scale(.030 -0.030)">{wordmark}</g>'
        return svg(420, 340, "0 0 420 340", symbol_group + text_group, label="GridLens")
    symbol_group = f'<g transform="translate(22 17) scale(.22)">{symbol}</g>'
    text_group = f'<g transform="translate(176 115) scale(.034 -0.034)">{wordmark}</g>'
    return svg(550, 164, "0 0 550 164", symbol_group + text_group, label="GridLens")


def write(name: str, data: str) -> None:
    (OUT / name).write_text(data, encoding="utf-8")


def hex_rgb(value: str) -> np.ndarray:
    return np.array(tuple(bytes.fromhex(value[1:])), dtype=np.float32)


def raster_mark(canvas: Image.Image, x: float, y: float, scale: float, mode: str) -> None:
    """Paint the exact four SVG polygons into an RGBA image."""
    if mode == "gradient":
        pairs = [("#284761", "#17324A"), ("#E5F0F6", "#18324A"),
                 ("#395A75", "#DAE8F1"), ("#496B84", "#101F2D")]
    elif mode == "light-gradient":
        pairs = [("#FFFFFF", "#BFD1E0"), ("#FFFFFF", "#91ACC0"),
                 ("#B4C9D8", "#FFFFFF"), ("#F3F8FA", "#A3B9C8")]
    elif mode in ("white", "navy"):
        color = COLORS["white"] if mode == "white" else COLORS["gridlens_navy"]
        pairs = [(color, color)] * 4
    else:
        raise ValueError(mode)
    for (_, points), (start, end) in zip(SHAPES, pairs, strict=True):
        xy = [(x + float(a) * scale, y + float(b) * scale)
              for a, b in (item.split(",") for item in points.split())]
        left = max(0, int(min(p[0] for p in xy)))
        top = max(0, int(min(p[1] for p in xy)))
        right = min(canvas.width, int(max(p[0] for p in xy)) + 2)
        bottom = min(canvas.height, int(max(p[1] for p in xy)) + 2)
        width, height = right - left, bottom - top
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).polygon([(px-left, py-top) for px, py in xy], fill=255)
        t = np.linspace(0, 1, width, dtype=np.float32)[None, :, None]
        rgb = (hex_rgb(start)[None, None, :] * (1-t) + hex_rgb(end)[None, None, :] * t)
        pixels = np.broadcast_to(rgb.astype(np.uint8), (height, width, 3)).copy()
        part = Image.fromarray(pixels, "RGB").convert("RGBA")
        part.putalpha(mask)
        canvas.alpha_composite(part, (left, top))


def save_mark(name: str, size: int, mode: str) -> None:
    ratio = 2
    image = Image.new("RGBA", (size*ratio, size*ratio), (0, 0, 0, 0))
    scale = size*ratio/624
    raster_mark(image, 0, 22*scale, scale, mode)
    image.resize((size, size), Image.Resampling.LANCZOS).save(OUT / name)


def save_lockup(name: str, dark_surface: bool) -> None:
    ratio = 2  # SVG intrinsic size is 550 × 164; export at 2×.
    image = Image.new("RGBA", (1100*ratio, 328*ratio), (0, 0, 0, 0))
    scale = .22 * 2 * ratio
    raster_mark(image, 22*2*ratio, 17*2*ratio, scale,
                "light-gradient" if dark_surface else "gradient")
    font = ImageFont.truetype(FONT, round(2048 * .034 * 2 * ratio))
    ImageDraw.Draw(image).text((176*2*ratio, 115*2*ratio), "GridLens", font=font,
                               fill=COLORS["white"] if dark_surface else COLORS["deep_current"],
                               anchor="ls")
    image.resize((1100, 328), Image.Resampling.LANCZOS).save(OUT / name)


def save_app_icon(name: str, dark_surface: bool) -> None:
    size, ratio = 1024, 2
    background = COLORS["deep_current"] if dark_surface else COLORS["white"]
    image = Image.new("RGBA", (size*ratio, size*ratio), background)
    raster_mark(image, 232*ratio, 252*ratio, .897*ratio,
                "light-gradient" if dark_surface else "gradient")
    image.resize((size, size), Image.Resampling.LANCZOS).save(OUT / name)


def save_favicon(name: str, size: int) -> None:
    ratio = max(4, 256//size)
    image = Image.new("RGBA", (size*ratio, size*ratio), (0, 0, 0, 0))
    ImageDraw.Draw(image).rounded_rectangle((0, 0, size*ratio-1, size*ratio-1),
                                              radius=13/64*size*ratio, fill=COLORS["deep_current"])
    raster_mark(image, 13/64*size*ratio, 14/64*size*ratio,
                .061/64*size*ratio, "white")
    image.resize((size, size), Image.Resampling.LANCZOS).save(OUT / name)


for mode, filename in (
    ("gradient", "aperture-gradient.svg"),
    ("navy", "aperture-navy.svg"),
    ("white", "aperture-white.svg"),
):
    write(filename, svg(624, 624, "0 -22 624 624", mark(mode), label="GridLens Aperture"))

write("lockup-horizontal-navy.svg", lockup(dark_surface=False))
write("lockup-horizontal-white.svg", lockup(dark_surface=True))
write("lockup-stacked-navy.svg", lockup(dark_surface=False, stacked=True))
write("lockup-stacked-white.svg", lockup(dark_surface=True, stacked=True))

dark_icon = (
    f'<rect width="1024" height="1024" fill="{COLORS["deep_current"]}"/>'
    f'<g transform="translate(232 252) scale(.897)">{mark("light-gradient")}</g>'
)
light_icon = (
    f'<rect width="1024" height="1024" fill="{COLORS["white"]}"/>'
    f'<g transform="translate(232 252) scale(.897)">{mark("gradient")}</g>'
)
write("app-icon-dark.svg", svg(1024, 1024, "0 0 1024 1024", dark_icon, label="GridLens app icon"))
write("app-icon-light.svg", svg(1024, 1024, "0 0 1024 1024", light_icon, label="GridLens app icon"))

favicon = (
    f'<rect width="64" height="64" rx="13" fill="{COLORS["deep_current"]}"/>'
    f'<g transform="translate(13 14) scale(.061)">{mark("white")}</g>'
)
write("favicon.svg", svg(64, 64, "0 0 64 64", favicon, label="GridLens"))

save_mark("aperture-gradient-1024.png", 1024, "gradient")
save_mark("aperture-white-1024.png", 1024, "white")
save_lockup("lockup-horizontal-navy-1100.png", False)
save_lockup("lockup-horizontal-white-1100.png", True)
save_app_icon("app-icon-dark-1024.png", True)
save_app_icon("app-icon-light-1024.png", False)
for size in (512, 192, 180):
    dest = "icon-512.png" if size == 512 else "icon-192.png" if size == 192 else "apple-touch-icon-180.png"
    Image.open(OUT / "app-icon-dark-1024.png").resize((size, size), Image.Resampling.LANCZOS).save(OUT / dest)
for size in (16, 32, 48):
    save_favicon(f"favicon-{size}.png", size)
Image.open(OUT / "favicon-48.png").save(OUT / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
for source, dest in (
    ("aperture-gradient-1024.png", "aperture-gradient-1024.webp"),
    ("lockup-horizontal-navy-1100.png", "lockup-horizontal-navy-1100.webp"),
    ("lockup-horizontal-white-1100.png", "lockup-horizontal-white-1100.webp"),
    ("app-icon-dark-1024.png", "app-icon-dark-1024.webp"),
    ("app-icon-light-1024.png", "app-icon-light-1024.webp"),
):
    Image.open(OUT / source).save(OUT / dest, format="WEBP", quality=95, method=6)

(ROOT / "docs" / "design" / "brand.tokens.json").write_text(
    json.dumps({"name": "GridLens", "version": "1.0.0", "colors": COLORS, "primary_ui_color": COLORS["gridlens_navy"]}, indent=2) + "\n",
    encoding="utf-8",
)
(ROOT / "web" / "src" / "styles" / "brand-tokens.css").write_text(
    ":root {\n" + "".join(f"  --gl-{k.replace('_', '-')}: {v};\n" for k, v in COLORS.items()) + "}\n",
    encoding="utf-8",
)
(ROOT / "web" / "public" / "site.webmanifest").write_text(
    json.dumps({"name": "GridLens", "short_name": "GridLens", "start_url": "/", "display": "standalone", "background_color": COLORS["ice"], "theme_color": COLORS["gridlens_navy"], "icons": [
        {"src": "/brand/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/brand/icon-512.png", "sizes": "512x512", "type": "image/png"},
    ]}, indent=2) + "\n",
    encoding="utf-8",
)
print(f"Generated brand assets in {OUT}")
