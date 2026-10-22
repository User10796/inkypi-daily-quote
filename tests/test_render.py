import pytest
from PIL import ImageChops, ImageOps

from daily_quote import quote_render as qr

LANDSCAPE = (800, 480)
PORTRAIT = (480, 800)

TEN_WORDS = "Be the reason someone smiles today, and every day after."
SIXTY_WORDS = (
    "Two roads diverged in a wood, and I took the one less traveled by, and "
    "that has made all the difference. Keep going when the path is steep, "
    "because the view from the top is worth every step you take. Be brave, "
    "be kind, and remember that small things done with great love can change "
    "the whole world around you."
)


def ink_box(image):
    """Bounding box of the black pixels."""
    return ImageOps.invert(image.convert("L")).getbbox()


def is_pure_black_and_white(image):
    histogram = image.convert("L").histogram()
    return sum(histogram[1:255]) == 0


def test_sample_lengths():
    assert len(TEN_WORDS.split()) == 10
    assert len(SIXTY_WORDS.split()) == 60


@pytest.mark.parametrize("size", [LANDSCAPE, PORTRAIT])
@pytest.mark.parametrize("style", list(qr.FONT_STYLES))
def test_output_is_rgb_pure_black_and_white(size, style):
    image = qr.render(size, TEN_WORDS, "Someone Kind", font_style=style)
    assert image.size == size
    assert image.mode == "RGB"
    assert is_pure_black_and_white(image)


def layout_for(text, size=LANDSCAPE, style="serif"):
    file, weight, _ = qr.FONT_STYLES[style]
    width, height = size
    scale = min(size) / qr.BASE_SHORT_SIDE
    margin = round(qr.MARGIN * scale)
    return qr.fit_text(
        f"“{text}”",
        file,
        weight,
        (width - 2 * margin, height - 2 * margin - 40),
        qr.MIN_FONT,
        qr.MAX_FONT,
        qr.FLOOR_FONT,
    )


@pytest.mark.parametrize("style", list(qr.FONT_STYLES))
def test_short_and_long_quotes_both_fill_the_panel_legibly(style):
    short = layout_for(TEN_WORDS, style=style)
    long = layout_for(SIXTY_WORDS, style=style)
    assert short.font_size >= 60  # big and bold for a short quote
    assert long.font_size >= qr.MIN_FONT  # still readable across the room
    assert short.font_size > long.font_size

    for text in (TEN_WORDS, SIXTY_WORDS):
        box = ink_box(qr.render(LANDSCAPE, text, "Author", font_style=style))
        width, height = box[2] - box[0], box[3] - box[1]
        assert width > 0.6 * LANDSCAPE[0]
        assert height > 0.4 * LANDSCAPE[1]


@pytest.mark.parametrize("size", [LANDSCAPE, PORTRAIT])
def test_ink_stays_inside_margins(size):
    for text in (TEN_WORDS, SIXTY_WORDS, "word " * 120):
        left, top, right, bottom = ink_box(qr.render(size, text, "A Rather Long Author Name"))
        margin = qr.MARGIN - 4  # glyph side bearings can poke out a hair
        assert left >= margin and top >= margin
        assert right <= size[0] - margin and bottom <= size[1] - margin


def test_very_long_quote_shrinks_below_minimum_then_truncates():
    huge = "lorem ipsum dolor sit amet " * 60
    layout = layout_for(huge)
    assert layout.font_size == qr.FLOOR_FONT
    assert layout.lines[-1].endswith("…")


def test_long_single_word_does_not_crash():
    image = qr.render(LANDSCAPE, "Supercalifragilisticexpialidocious" * 3)
    assert is_pure_black_and_white(image)


def test_balanced_lines_have_no_orphan():
    layout = layout_for("The best way to find yourself is to lose yourself in the service of others okay")
    assert len(layout.lines) >= 2
    assert len(layout.lines[-1].split()) >= 2


def test_balance_does_not_add_lines():
    font = qr.load_font("Lora[wght].ttf", 50, 500)
    text = SIXTY_WORDS
    greedy = qr.wrap(text, font, 700)
    assert len(qr.balance(text, font, 700, greedy)) == len(greedy)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("don't", "don’t"),
        ('say "hi" now', "say “hi” now"),
        ("'tis the season", "‘tis the season"),
        ("“already curly”", "“already curly”"),
    ],
)
def test_smart_quotes(raw, expected):
    assert qr.smart_quotes(raw) == expected


def test_date_line_and_frames_draw_something():
    plain = qr.render(LANDSCAPE, TEN_WORDS)
    with_date = qr.render(LANDSCAPE, TEN_WORDS, date_line="Tuesday, October 20")
    assert ImageChops.difference(plain, with_date).getbbox() is not None
    for frame in ("thin", "double"):
        framed = qr.render(LANDSCAPE, TEN_WORDS, frame=frame)
        box = ink_box(framed)
        assert box[0] < 20 and box[1] < 20  # border near the edge


def test_placeholder_renders():
    assert is_pure_black_and_white(qr.render_placeholder(LANDSCAPE))


@pytest.mark.parametrize("size", [LANDSCAPE, PORTRAIT])
@pytest.mark.parametrize("style", list(qr.FONT_STYLES))
@pytest.mark.parametrize("text", ["Be kind.", TEN_WORDS, SIXTY_WORDS])
def test_author_line_never_overlaps_date_line(size, style, text):
    """Regression: a short quote's large author line ran into the date."""
    date_line = "Wednesday, September 30"
    image = qr.render(size, text, "A Fairly Long Author Name", font_style=style, date_line=date_line)
    scale = min(size) / qr.BASE_SHORT_SIDE
    _, _, author_file = qr.FONT_STYLES[style]
    date_font = qr.load_font(author_file, max(12, round(qr.DATE_FONT * scale)))
    band_top = size[1] - round(qr.MARGIN * scale) - qr.line_height(date_font)
    band = image.crop((0, band_top, size[0], size[1]))
    left, top, right, bottom = ink_box(band)
    # Only the date's ink is in the date band (author ink would widen it).
    assert right - left <= date_font.getlength(date_line) + 4
    # And there is clear space above the band.
    above = image.crop((0, band_top - 4, size[0], band_top))
    assert ink_box(above) is None


def test_author_size_is_capped_for_short_quotes():
    image = qr.render(LANDSCAPE, "Be kind.", "Unknown")
    plain = qr.render(LANDSCAPE, "Be kind.")
    assert image.tobytes() != plain.tobytes()
    scale = 1.0
    assert qr.MAX_AUTHOR_FONT * scale < qr.MAX_FONT * qr.AUTHOR_RATIO
