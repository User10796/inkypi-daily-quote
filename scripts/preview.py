"""Render sample boards to PNG files without a Pi or display.

    python scripts/preview.py [output_dir]

Writes one image per font style and orientation, for a short quote, a long
quote, and a date override, so layouts can be checked by eye.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from daily_quote import quote_render as qr  # noqa: E402

SAMPLES = {
    "short": ("Be the reason someone smiles today.", "Unknown"),
    "medium": (
        "Whatever you are, be a good one.",
        "Abraham Lincoln",
    ),
    "long": (
        "Two roads diverged in a wood, and I—I took the one less traveled by, "
        "and that has made all the difference. Don't be afraid to take the "
        "harder path when your heart tells you it is the right one.",
        "Robert Frost (adapted)",
    ),
}


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "previews")
    os.makedirs(out, exist_ok=True)
    for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800))):
        for style in qr.FONT_STYLES:
            for name, (text, author) in SAMPLES.items():
                image = qr.render(size, text, author, font_style=style, date_line="Tuesday, October 20")
                image.save(os.path.join(out, f"{orientation}-{style}-{name}.png"))
        override = qr.render(size, "Happy birthday, Emmy!", add_quote_marks=False, frame="double")
        override.save(os.path.join(out, f"{orientation}-override.png"))
    print(f"Wrote previews to {out}")


if __name__ == "__main__":
    main()
