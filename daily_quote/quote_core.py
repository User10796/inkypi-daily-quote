"""Parsing and once-per-day rotation logic for the Daily Quote plugin.

Pure Python with no InkyPi, Pillow, or clock dependencies: every function takes
``now`` explicitly so the rotation can be tested with a fake clock.

Rotation state is a plain JSON-serializable dict (see ``new_state``). It is
stored by the plugin in its own file rather than in InkyPi's settings dict,
because InkyPi replaces an instance's settings wholesale every time the
settings form is saved.
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

STATE_VERSION = 1

ORDERS = ("sequential", "shuffle", "random")
DEFAULT_ORDER = "shuffle"
DEFAULT_CHANGE_TIME = time(5, 0)
MAX_APPLIED_COMMANDS = 20

# Author separators: an em/en dash (spaces optional) or a spaced "-" / "--".
_SEPARATOR = re.compile(r"\s*[—–]\s*|\s+--?\s+")
_MAX_AUTHOR_WORDS = 8

_WRAPPING_QUOTES = {
    '"': '"',
    "“": "”",
    "'": "'",
    "‘": "’",
}


@dataclass(frozen=True)
class Quote:
    text: str
    author: str | None = None

    @property
    def key(self) -> str:
        """Stable identity used in persisted state (survives reordering)."""
        return f"{self.text}␟{self.author or ''}"


@dataclass(frozen=True)
class Selection:
    """What to put on the panel for this refresh."""

    kind: str  # "quote" | "override" | "empty"
    quote: Quote | None = None
    message: str | None = None
    number: int | None = None  # 1-based position of the quote in the list


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def _looks_like_author(candidate: str) -> bool:
    if not candidate or len(candidate.split()) > _MAX_AUTHOR_WORDS:
        return False
    if candidate[-1] in ".!?,;:":
        # "Be kind — always." is part of the quote, not an author.
        # A short abbreviation or initial ("Jr.", "Sr.", "C.") is allowed.
        if not re.search(r"\b[A-Z][a-z]{0,2}\.$", candidate):
            return False
    first = candidate[0]
    return first.isupper() or first.isdigit()


def split_author(line: str) -> tuple[str, str | None]:
    """Split ``Quote text — Author`` on the last separator, if it is one."""
    matches = list(_SEPARATOR.finditer(line))
    for match in reversed(matches):
        text = line[: match.start()].strip()
        author = line[match.end():].strip()
        if text and _looks_like_author(author):
            return text, author
        # Only the last separator is a candidate for the author.
        break
    return line.strip(), None


def strip_wrapping_quotes(text: str) -> str:
    """Remove one pair of quote marks wrapping the whole text, if present."""
    if len(text) >= 2 and text[0] in _WRAPPING_QUOTES:
        closing = _WRAPPING_QUOTES[text[0]]
        if text[-1] in (closing, '"', "”"):
            inner = text[1:-1].strip()
            if inner:
                return inner
    return text


def parse_quotes(raw: str | None) -> list[Quote]:
    """One quote per line. Blank lines and lines starting with ``#`` are
    ignored; exact duplicates are dropped (first one wins)."""
    quotes: list[Quote] = []
    seen: set[str] = set()
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        text, author = split_author(line)
        text = strip_wrapping_quotes(text)
        quote = Quote(text=text, author=author)
        if quote.key in seen:
            continue
        seen.add(quote.key)
        quotes.append(quote)
    return quotes


_OVERRIDE_LINE = re.compile(
    r"^(?:(?P<year>\d{4})-)?(?P<month>\d{1,2})[-/](?P<day>\d{1,2})\s+(?P<message>.+)$"
)


def parse_overrides(raw: str | None) -> dict[str, str]:
    """Lines like ``03-14 Happy birthday!`` (every year) or
    ``2026-12-25 Merry Christmas!`` (that date only).

    Returns a map from ``MM-DD`` or ``YYYY-MM-DD`` to the message. Invalid
    lines are skipped; for a repeated date the first line wins.
    """
    overrides: dict[str, str] = {}
    for line in (raw or "").splitlines():
        match = _OVERRIDE_LINE.match(line.strip())
        if not match:
            continue
        month, day = int(match["month"]), int(match["day"])
        year = int(match["year"]) if match["year"] else 2000  # leap year
        try:
            date(year, month, day)
        except ValueError:
            continue
        key = f"{month:02d}-{day:02d}"
        if match["year"]:
            key = f"{match['year']}-{key}"
        overrides.setdefault(key, match["message"].strip())
    return overrides


def override_for(overrides: dict[str, str], today: date) -> str | None:
    """A one-time (dated) override beats a yearly one."""
    return overrides.get(today.isoformat()) or overrides.get(today.strftime("%m-%d"))


def parse_change_time(raw: str | None) -> time:
    try:
        hours, minutes = (raw or "").strip().split(":")[:2]
        return time(int(hours), int(minutes))
    except (ValueError, TypeError):
        return DEFAULT_CHANGE_TIME


def parse_order(raw: str | None) -> str:
    return raw if raw in ORDERS else DEFAULT_ORDER


def parse_jump(raw) -> int | None:
    try:
        number = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 1 else None


def list_hash(keys: list[str]) -> str:
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# Rotation
# --------------------------------------------------------------------------

def new_state() -> dict:
    return {
        "version": STATE_VERSION,
        "current": None,  # Quote.key showing now
        "current_index": None,  # its position, used if it gets deleted
        "last_advance_date": None,  # ISO date of the period last advanced for
        "queue": [],  # shuffle: keys still to show this cycle
        "cycle_shown": [],  # shuffle: keys already shown this cycle
        "order": None,
        "list_hash": None,
        "applied_commands": [],  # nonces of recent jump/skip commands
    }


def period_date(now: datetime, change_time: time) -> date:
    """The quote "day" runs from change_time to change_time the next day."""
    if now.time() >= change_time:
        return now.date()
    return now.date() - timedelta(days=1)


def _normalize_state(state: dict | None) -> dict:
    fresh = new_state()
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        return fresh
    fresh.update({k: state.get(k, v) for k, v in fresh.items()})
    if not isinstance(fresh["queue"], list):
        fresh["queue"] = []
    if not isinstance(fresh["cycle_shown"], list):
        fresh["cycle_shown"] = []
    if not isinstance(fresh["applied_commands"], list):
        fresh["applied_commands"] = []
    return fresh


def _refill_queue(state: dict, keys: list[str], rng: random.Random) -> None:
    """Queue the quotes not yet shown this cycle; if every quote has been
    shown (the normal case), start a new cycle with all of them."""
    remaining = [k for k in keys if k not in state["cycle_shown"]]
    if remaining:
        rng.shuffle(remaining)
        state["queue"] = remaining
        return
    queue = list(keys)
    rng.shuffle(queue)
    # The first quote of a new cycle must not repeat the one just shown.
    if len(queue) > 1 and queue[0] == state["current"]:
        swap = rng.randrange(1, len(queue))
        queue[0], queue[swap] = queue[swap], queue[0]
    state["queue"] = queue
    state["cycle_shown"] = []


def _set_current(state: dict, keys: list[str], key: str) -> None:
    state["current"] = key
    state["current_index"] = keys.index(key)
    if key in state["queue"]:
        state["queue"].remove(key)
    if key not in state["cycle_shown"]:
        state["cycle_shown"].append(key)


def _advance(state: dict, keys: list[str], order: str, rng: random.Random) -> None:
    current = state["current"]
    if order == "sequential":
        if current in keys:
            index = (keys.index(current) + 1) % len(keys)
        elif state["current_index"] is not None:
            index = min(state["current_index"], len(keys) - 1)
        else:
            index = 0
        _set_current(state, keys, keys[index])
    elif order == "random":
        choices = [k for k in keys if k != current] or keys
        _set_current(state, keys, rng.choice(choices))
    else:  # shuffle
        if not state["queue"]:
            _refill_queue(state, keys, rng)
        _set_current(state, keys, state["queue"][0])


def _reconcile(state: dict, keys: list[str], order: str, rng: random.Random) -> None:
    """Fold a list edit or an order change into the state without moving the
    quote currently on screen (unless it was deleted)."""
    key_set = set(keys)

    if order != state["order"]:
        state["queue"] = []
        state["cycle_shown"] = [state["current"]] if state["current"] in key_set else []
        state["order"] = order

    if state["list_hash"] == list_hash(keys):
        return

    if order == "shuffle" and state["queue"]:
        known = set(state["queue"]) | set(state["cycle_shown"])
        state["queue"] = [k for k in state["queue"] if k in key_set]
        state["cycle_shown"] = [k for k in state["cycle_shown"] if k in key_set]
        # New quotes join the current cycle at random positions.
        for key in keys:
            if key not in known and key != state["current"]:
                state["queue"].insert(rng.randint(0, len(state["queue"])), key)
    else:
        state["cycle_shown"] = [k for k in state["cycle_shown"] if k in key_set]

    if state["current"] is not None and state["current"] not in key_set:
        # The quote on screen was deleted: replace it now, without counting
        # this as the day's advance.
        if order == "shuffle" and not state["queue"]:
            _refill_queue(state, keys, rng)
        _advance(state, keys, order, rng)
    elif state["current"] in key_set:
        state["current_index"] = keys.index(state["current"])

    state["list_hash"] = list_hash(keys)


def select(
    quotes: list[Quote],
    state: dict | None,
    now: datetime,
    *,
    order: str = DEFAULT_ORDER,
    change_time: time = DEFAULT_CHANGE_TIME,
    overrides: dict[str, str] | None = None,
    jump_to: int | None = None,
    skip: bool = False,
    command_nonce: str | None = None,
    rng: random.Random | None = None,
) -> tuple[Selection, dict]:
    """Decide what to show at ``now`` and return the updated state.

    Idempotent: calling this any number of times within one quote day
    advances at most once, so InkyPi's refresh interval doesn't matter. If the
    Pi was off for several days it advances once, not once per missed day.

    ``jump_to`` / ``skip`` are one-shot commands, applied only for a
    ``command_nonce`` not seen before: InkyPi re-sends the saved form values
    on every refresh, and a playlist instance can still hold an older nonce
    after "Update Now" applied a newer one.
    """
    rng = rng or random.Random()
    state = _normalize_state(state)
    order = parse_order(order)
    today = now.date()
    period = period_date(now, change_time)

    if not quotes:
        return Selection(kind="empty"), state

    keys = [q.key for q in quotes]
    by_key = {q.key: q for q in quotes}

    # A last_advance_date in the future means the clock was wrong; recover.
    last = state["last_advance_date"]
    if last is not None and last > today.isoformat():
        state["last_advance_date"] = period.isoformat()

    _reconcile(state, keys, order, rng)

    if state["current"] is None:
        _advance(state, keys, order, rng)
        state["last_advance_date"] = period.isoformat()

    command_applied = False
    if command_nonce and command_nonce not in state["applied_commands"]:
        state["applied_commands"] = (state["applied_commands"] + [command_nonce])[-MAX_APPLIED_COMMANDS:]
        if jump_to is not None and jump_to <= len(keys):
            _set_current(state, keys, keys[jump_to - 1])
            command_applied = True
        elif skip:
            _advance(state, keys, order, rng)
            command_applied = True
        if command_applied:
            # Hold the chosen quote through the rest of today.
            state["last_advance_date"] = max(period, today).isoformat()

    message = override_for(overrides or {}, today)
    if message:
        # Override days leave the rotation alone; it resumes tomorrow.
        return Selection(kind="override", message=message), state

    if state["last_advance_date"] is None or state["last_advance_date"] < period.isoformat():
        _advance(state, keys, order, rng)
        state["last_advance_date"] = period.isoformat()

    current = by_key[state["current"]]
    return Selection(kind="quote", quote=current, number=keys.index(current.key) + 1), state
