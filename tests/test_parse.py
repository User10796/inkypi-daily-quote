from datetime import date, time

import pytest

from daily_quote.quote_core import (
    DEFAULT_CHANGE_TIME,
    Quote,
    override_for,
    parse_change_time,
    parse_jump,
    parse_overrides,
    parse_quotes,
    split_author,
)


@pytest.mark.parametrize(
    "line, text, author",
    [
        ("Be kind. — Ian Maclaren", "Be kind.", "Ian Maclaren"),
        ("Be kind.—Ian Maclaren", "Be kind.", "Ian Maclaren"),
        ("Be kind. – Ian Maclaren", "Be kind.", "Ian Maclaren"),
        ("Be kind. - Ian Maclaren", "Be kind.", "Ian Maclaren"),
        ("Be kind. -- Ian Maclaren", "Be kind.", "Ian Maclaren"),
        ("Oh, the places you'll go! — Dr. Seuss", "Oh, the places you'll go!", "Dr. Seuss"),
        ("Trust in the Lord — Proverbs 3:5", "Trust in the Lord", "Proverbs 3:5"),
        ("Courage — the first virtue — Aristotle", "Courage — the first virtue", "Aristotle"),
        # Not authors: lowercase, sentence punctuation, too many words.
        ("Be kind — always", "Be kind — always", None),
        ("Be kind — Always.", "Be kind — Always.", None),
        ("Do it — One Two Three Four Five Six Seven Eight Nine", "Do it — One Two Three Four Five Six Seven Eight Nine", None),
        # Hyphenated words are not separators.
        ("A well-known saying", "A well-known saying", None),
        ("No author here", "No author here", None),
    ],
)
def test_split_author(line, text, author):
    assert split_author(line) == (text, author)


def test_parse_quotes_skips_blanks_comments_and_duplicates():
    raw = """
    # Week 1
    "Be kind." — Ian Maclaren

    Be kind. — Ian Maclaren
    Keep going
    Keep going
    """
    assert parse_quotes(raw) == [Quote("Be kind.", "Ian Maclaren"), Quote("Keep going")]


def test_parse_quotes_strips_wrapping_quote_marks_only():
    assert parse_quotes("“Hello”")[0].text == "Hello"
    assert parse_quotes("'Hello'")[0].text == "Hello"
    assert parse_quotes('He said "hi" today')[0].text == 'He said "hi" today'


def test_parse_quotes_empty():
    assert parse_quotes("") == []
    assert parse_quotes(None) == []
    assert parse_quotes("\n  \n# only a comment\n") == []


def test_parse_overrides():
    raw = """
    03-14 Happy birthday, Emmy!
    3/15 Ides
    2026-12-25 Merry Christmas!
    02-30 not a date
    garbage line
    03-14 second line for same date is ignored
    """
    overrides = parse_overrides(raw)
    assert overrides == {
        "03-14": "Happy birthday, Emmy!",
        "03-15": "Ides",
        "2026-12-25": "Merry Christmas!",
    }
    assert override_for(overrides, date(2027, 3, 14)) == "Happy birthday, Emmy!"
    assert override_for(overrides, date(2026, 12, 25)) == "Merry Christmas!"
    assert override_for(overrides, date(2027, 12, 25)) is None
    assert override_for(overrides, date(2027, 3, 16)) is None


def test_parse_overrides_feb_29_allowed():
    assert parse_overrides("02-29 Leap day!") == {"02-29": "Leap day!"}


def test_dated_override_beats_yearly():
    overrides = parse_overrides("12-25 Yearly\n2026-12-25 This year")
    assert override_for(overrides, date(2026, 12, 25)) == "This year"


@pytest.mark.parametrize(
    "raw, expected",
    [("05:00", time(5, 0)), ("6:30", time(6, 30)), ("23:59:00", time(23, 59)), ("", DEFAULT_CHANGE_TIME), ("25:00", DEFAULT_CHANGE_TIME), (None, DEFAULT_CHANGE_TIME)],
)
def test_parse_change_time(raw, expected):
    assert parse_change_time(raw) == expected


@pytest.mark.parametrize("raw, expected", [("3", 3), (" 12 ", 12), ("", None), ("0", None), ("-2", None), ("x", None), (None, None)])
def test_parse_jump(raw, expected):
    assert parse_jump(raw) == expected
