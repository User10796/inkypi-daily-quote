"""Pillow rendering for the Daily Quote plugin.

Draws directly with Pillow instead of InkyPi's HTML/Chromium path: it is much
faster on a Pi Zero 2 W and makes text measurement exact. Output is pure
black and white (thresholded, never dithered), which is crisper on e-ink.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

# (quote font file, variable-font weight or None, author font file)
FONT_STYLES = {
    "serif": ("Lora[wght].ttf", 500, "Lora-Italic[wght].ttf"),
    "sans": ("AtkinsonHyperlegible-Regular.ttf", None, "AtkinsonHyperlegible-Italic.ttf"),
    "handwritten": ("PatrickHand-Regular.ttf", None, "PatrickHand-Regular.ttf"),
}
DEFAULT_FONT_STYLE = "serif"
FRAMES = ("none", "thin", "double")

# Sizes below are for a 480 px short side and scale with the panel.
BASE_SHORT_SIDE = 480
MARGIN = 40
MIN_FONT, MAX_FONT = 28, 96
FLOOR_FONT = 16  # last resort for very long quotes, below the normal minimum
AUTHOR_RATIO = 0.45
MIN_AUTHOR_FONT = 18
MAX_AUTHOR_FONT = 30
AUTHOR_GAP = 0.4  # space above the author line, as a fraction of its height
DATE_FONT = 20
LINE_SPACING = 1.18
THRESHOLD = 140


@dataclass
class Layout:
    font_size: int
    lines: list[str]


@lru_cache(maxsize=256)
def load_font(filename: str, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(os.path.join(FONTS_DIR, filename), size)
    if weight is not None:
        try:
            font.set_variation_by_axes([weight])
        except (OSError, AttributeError):
            pass  # FreeType without variation support: default weight is fine
    return font


def smart_quotes(text: str) -> str:
    """Straight quotes to curly ones; apostrophes become ’."""
    text = re.sub(r'(^|[\s(\[{\u2014\u2013-])"', "\\1\u201c", text)
    text = text.replace('"', "\u201d")
    text = re.sub(r"(^|[\s(\[{\u2014\u2013-])'", "\\1\u2018", text)
    return text.replace("'", "\u2019")


def wrap(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[str] | None:
    """Greedy word wrap. None if a single word is wider than max_width."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}" if line else word
        if font.getlength(candidate) <= max_width:
            line = candidate
            continue
        if not line or font.getlength(word) > max_width:
            return None
        lines.append(line)
        line = word
    if line:
        lines.append(line)
    return lines


def line_height(font: ImageFont.FreeTypeFont) -> int:
    ascent, descent = font.getmetrics()
    return round((ascent + descent) * LINE_SPACING)


def balance(text: str, font: ImageFont.FreeTypeFont, max_width: float, lines: list[str]) -> list[str]:
    """Narrow the wrap width as far as possible without adding a line, so
    lines come out even and the last line isn't a lone orphaned word."""
    target = len(lines)
    if target < 2:
        return lines
    lo, hi = max_width / 3, max_width
    best = lines
    for _ in range(14):
        mid = (lo + hi) / 2
        attempt = wrap(text, font, mid)
        if attempt is not None and len(attempt) <= target:
            best, hi = attempt, mid
        else:
            lo = mid
    return best


def fit_text(
    text: str,
    font_file: str,
    weight: int | None,
    box: tuple[float, float],
    min_size: int,
    max_size: int,
    floor_size: int,
    reserve=None,
) -> Layout:
    """Largest font size at which the wrapped text fits in box (w, h).

    ``reserve(size)`` is extra height needed below the text at that font
    size (the author line, which scales with the quote).
    """
    max_width, max_height = box

    def layout_at(size: int) -> list[str] | None:
        font = load_font(font_file, size, weight)
        lines = wrap(text, font, max_width)
        budget = max_height - (reserve(size) if reserve else 0)
        if lines is None or len(lines) * line_height(font) > budget:
            return None
        return lines

    lo, hi, best = min_size, max_size, None
    while lo <= hi:
        mid = (lo + hi) // 2
        lines = layout_at(mid)
        if lines is not None:
            best, lo = Layout(mid, lines), mid + 1
        else:
            hi = mid - 1

    if best is None:
        for size in range(min_size - 1, floor_size - 1, -1):
            lines = layout_at(size)
            if lines is not None:
                best = Layout(size, lines)
                break

    if best is None:
        budget = max_height - (reserve(floor_size) if reserve else 0)
        best = _truncated_layout(text, font_file, weight, (max_width, budget), floor_size)

    font = load_font(font_file, best.font_size, weight)
    best.lines = balance(" ".join(best.lines), font, max_width, best.lines)
    return best


def _truncated_layout(text, font_file, weight, box, size) -> Layout:
    font = load_font(font_file, size, weight)
    max_width, max_height = box
    max_lines = max(1, int(max_height // line_height(font)))
    words = text.split()
    while words:
        candidate = " ".join(words) + "\u2026"
        lines = wrap(candidate, font, max_width)
        if lines is not None and len(lines) <= max_lines:
            return Layout(size, lines)
        words.pop()
    return Layout(size, ["\u2026"])


def _draw_frame(draw: ImageDraw.ImageDraw, size: tuple[int, int], frame: str, scale: float) -> None:
    if frame not in ("thin", "double"):
        return
    width, height = size
    inset = round(14 * scale)
    stroke = max(2, round(3 * scale))
    draw.rectangle([inset, inset, width - 1 - inset, height - 1 - inset], outline=0, width=stroke)
    if frame == "double":
        inner = inset + stroke + max(3, round(5 * scale))
        draw.rectangle(
            [inner, inner, width - 1 - inner, height - 1 - inner], outline=0, width=max(1, stroke // 2)
        )


def render(
    size: tuple[int, int],
    text: str,
    author: str | None = None,
    *,
    font_style: str = DEFAULT_FONT_STYLE,
    add_quote_marks: bool = True,
    date_line: str | None = None,
    frame: str = "none",
) -> Image.Image:
    """Render a quote (or an override message) to an RGB image of pure
    black and white pixels."""
    width, height = size
    scale = min(width, height) / BASE_SHORT_SIDE
    quote_file, weight, author_file = FONT_STYLES.get(font_style, FONT_STYLES[DEFAULT_FONT_STYLE])

    margin = round(MARGIN * scale)
    if frame in ("thin", "double"):
        margin += round(10 * scale)

    body = smart_quotes(text)
    if add_quote_marks:
        body = f"\u201c{body}\u201d"

    date_font = load_font(author_file, max(12, round(DATE_FONT * scale)))
    date_height = line_height(date_font) if date_line else 0

    min_author = max(12, round(MIN_AUTHOR_FONT * scale))
    max_author = max(min_author, round(MAX_AUTHOR_FONT * scale))

    def author_size_for(quote_size: int) -> int:
        return min(max_author, max(min_author, round(quote_size * AUTHOR_RATIO)))

    def author_block_for(quote_size: int) -> int:
        if not author:
            return 0
        font = load_font(author_file, author_size_for(quote_size))
        return round(line_height(font) * (1 + AUTHOR_GAP))

    box_w = width - 2 * margin
    box_h = height - 2 * margin - date_height
    layout = fit_text(
        body,
        quote_file,
        weight,
        (box_w, box_h),
        max(12, round(MIN_FONT * scale)),
        max(14, round(MAX_FONT * scale)),
        max(10, round(FLOOR_FONT * scale)),
        reserve=author_block_for,
    )
    quote_font = load_font(quote_file, layout.font_size, weight)
    quote_lh = line_height(quote_font)

    author_text = author_font = None
    author_block = 0
    if author:
        author_size = author_size_for(layout.font_size)
        author_font = load_font(author_file, author_size)
        author_text = f"\u2014 {smart_quotes(author)}"
        while author_size > min_author and author_font.getlength(author_text) > box_w:
            author_size -= 1
            author_font = load_font(author_file, author_size)
        author_block = round(line_height(author_font) * (1 + AUTHOR_GAP))

    canvas = Image.new("L", size, 255)
    draw = ImageDraw.Draw(canvas)

    block_height = len(layout.lines) * quote_lh + author_block
    usable_top, usable_bottom = margin, height - margin - date_height
    y = usable_top + max(0, (usable_bottom - usable_top - block_height) // 2)

    ascent, descent = quote_font.getmetrics()
    pad = (quote_lh - (ascent + descent)) // 2
    for line in layout.lines:
        line_width = quote_font.getlength(line)
        draw.text(((width - line_width) / 2, y + pad), line, font=quote_font, fill=0)
        y += quote_lh

    if author_text:
        a_width = author_font.getlength(author_text)
        widest = max(quote_font.getlength(line) for line in layout.lines)
        # Right-align under the quote block (or the margin, whichever is nearer).
        right = min(width - margin, (width + widest) / 2)
        x = max(margin, right - a_width)
        draw.text((x, y + round(line_height(author_font) * AUTHOR_GAP)), author_text, font=author_font, fill=0)

    if date_line:
        d_width = date_font.getlength(date_line)
        draw.text(((width - d_width) / 2, height - margin - date_height), date_line, font=date_font, fill=0)

    _draw_frame(draw, size, frame, scale)

    bw = canvas.point(lambda p: 255 if p >= THRESHOLD else 0, mode="1")
    return bw.convert("RGB")


def render_placeholder(size: tuple[int, int], font_style: str = DEFAULT_FONT_STYLE) -> Image.Image:
    return render(
        size,
        "Add quotes in the InkyPi app to get started.",
        font_style=font_style,
        add_quote_marks=False,
    )
