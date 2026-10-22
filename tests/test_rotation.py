import json
import random
from datetime import datetime, time, timedelta

import pytest

from daily_quote.quote_core import Quote, select

START = datetime(2026, 10, 1, 12, 0)  # noon: past the 05:00 change time
CHANGE = time(5, 0)


def make_quotes(n):
    return [Quote(f"Quote number {i}", f"Author {i}") for i in range(1, n + 1)]


class Board:
    """Drives select() like InkyPi would, persisting state as JSON each time
    (which also proves the state survives a reboot)."""

    def __init__(self, quotes, order="shuffle", seed=1, **options):
        self.quotes = quotes
        self.order = order
        self.options = options
        self.rng = random.Random(seed)
        self.saved = None

    def refresh(self, now, **overrides):
        options = {**self.options, **overrides}
        state = json.loads(self.saved) if self.saved else None
        selection, state = select(
            self.quotes, state, now, order=self.order, change_time=CHANGE, rng=self.rng, **options
        )
        self.saved = json.dumps(state)
        return selection

    @property
    def state(self):
        return json.loads(self.saved)


def daily_quotes(board, days, start=START, step=timedelta(hours=1)):
    """The quote showing at noon on each day, refreshing every ``step``."""
    shown = []
    now = start
    end = start + timedelta(days=days)
    while now < end:
        selection = board.refresh(now)
        if now.hour == 12 and now.minute < step.total_seconds() / 60:
            shown.append(selection.quote.key)
        now += step
    return shown


@pytest.mark.parametrize("step_minutes", [7, 60, 180, 24 * 60])
def test_exactly_one_advance_per_day_regardless_of_refresh_rate(step_minutes):
    board = Board(make_quotes(20), order="sequential")
    board.refresh(START)  # picks the initial quote
    first = last_date = board.state["last_advance_date"]
    advances = 0
    now = START + timedelta(minutes=step_minutes)
    while now <= START + timedelta(days=7):
        board.refresh(now)
        if board.state["last_advance_date"] != last_date:
            advances += 1
            last_date = board.state["last_advance_date"]
        now += timedelta(minutes=step_minutes)
    assert advances == 7
    assert board.state["current_index"] == 7
    assert first == "2026-10-01" and last_date == "2026-10-08"


def test_quote_changes_at_change_time_not_midnight():
    board = Board(make_quotes(5), order="sequential")
    first = board.refresh(START.replace(hour=12)).quote
    assert board.refresh(START.replace(day=2, hour=0, minute=30)).quote == first
    assert board.refresh(START.replace(day=2, hour=4, minute=59)).quote == first
    assert board.refresh(START.replace(day=2, hour=5, minute=0)).quote != first


def test_first_run_before_change_time_advances_at_change_time():
    board = Board(make_quotes(5), order="sequential")
    assert board.refresh(START.replace(hour=4)).number == 1
    assert board.refresh(START.replace(hour=6)).number == 2


def test_reboot_mid_day_keeps_same_quote():
    board = Board(make_quotes(10))
    before = board.refresh(START.replace(hour=9)).quote
    # A reboot is a fresh process loading the saved JSON state.
    rebooted = Board(make_quotes(10), seed=999)
    rebooted.saved = board.saved
    assert rebooted.refresh(START.replace(hour=15)).quote == before


def test_pi_off_for_days_advances_once():
    board = Board(make_quotes(10), order="sequential")
    assert board.refresh(START.replace(hour=12)).number == 1
    assert board.refresh(START.replace(day=5, hour=12)).number == 2


def test_sequential_wraps_around():
    board = Board(make_quotes(3), order="sequential")
    numbers = [board.refresh(START + timedelta(days=d, hours=12)).number for d in range(7)]
    assert numbers == [1, 2, 3, 1, 2, 3, 1]


def test_shuffle_shows_every_quote_once_before_any_repeat():
    n = 12
    board = Board(make_quotes(n), order="shuffle", seed=7)
    shown = daily_quotes(board, days=n * 4)
    for cycle in range(4):
        assert len(set(shown[cycle * n:(cycle + 1) * n])) == n
    # No back-to-back repeat across cycle boundaries.
    assert all(a != b for a, b in zip(shown, shown[1:]))


def test_random_never_repeats_back_to_back():
    board = Board(make_quotes(4), order="random", seed=3)
    shown = daily_quotes(board, days=40, step=timedelta(hours=6))
    assert all(a != b for a, b in zip(shown, shown[1:]))


def test_single_quote_list():
    for order in ("sequential", "shuffle", "random"):
        board = Board(make_quotes(1), order=order)
        assert set(daily_quotes(board, days=3)) == {make_quotes(1)[0].key}


def test_empty_list_returns_empty_and_keeps_state():
    board = Board(make_quotes(3), order="sequential")
    board.refresh(START.replace(hour=12))
    saved = board.state
    board.quotes = []
    assert board.refresh(START.replace(hour=13)).kind == "empty"
    assert board.state == saved


def test_editing_list_keeps_current_quote():
    quotes = make_quotes(10)
    for order in ("sequential", "shuffle", "random"):
        board = Board(list(quotes), order=order)
        current = board.refresh(START.replace(hour=9)).quote
        # Reorder, add, and remove other quotes.
        edited = [Quote("Brand new")] + [q for q in reversed(quotes) if q != quotes[-1] or q == current]
        board.quotes = edited
        assert board.refresh(START.replace(hour=10)).quote == current


def test_removing_current_quote_replaces_it_without_using_up_the_day():
    quotes = make_quotes(5)
    board = Board(list(quotes), order="sequential")
    board.refresh(START.replace(hour=12))
    board.refresh(START.replace(day=2, hour=12))  # showing #2
    board.quotes = [q for q in quotes if q != quotes[1]]
    # #3 slides into #2's place and is shown now.
    assert board.refresh(START.replace(day=2, hour=13)).quote == quotes[2]
    # Tomorrow still advances once.
    assert board.refresh(START.replace(day=3, hour=12)).quote == quotes[3]


def test_shuffle_edit_mid_cycle_still_shows_everything_once():
    quotes = make_quotes(8)
    board = Board(list(quotes), order="shuffle", seed=11)
    shown = daily_quotes(board, days=3)
    extra = [Quote("Added later 1"), Quote("Added later 2")]
    board.quotes = list(quotes) + extra
    shown += daily_quotes(board, days=7, start=START + timedelta(days=3))
    assert sorted(shown) == sorted(q.key for q in quotes + extra)


def test_changing_order_keeps_current_quote():
    board = Board(make_quotes(6), order="sequential")
    current = board.refresh(START.replace(hour=12)).quote
    board.order = "shuffle"
    assert board.refresh(START.replace(hour=13)).quote == current
    following = daily_quotes(board, days=5, start=START + timedelta(days=1))
    assert current.key not in following  # rest of the new cycle excludes it


def test_date_override_only_on_its_date_and_rotation_resumes():
    board = Board(make_quotes(5), order="sequential", overrides={"10-02": "Happy birthday!"})
    assert board.refresh(START.replace(hour=12)).number == 1
    day2 = board.refresh(START.replace(day=2, hour=12))
    assert day2.kind == "override" and day2.message == "Happy birthday!"
    # The override day doesn't consume a quote.
    assert board.refresh(START.replace(day=3, hour=12)).number == 2
    assert board.refresh(START.replace(day=4, hour=12)).number == 3


def test_override_is_by_calendar_date_not_quote_day():
    board = Board(make_quotes(3), order="sequential", overrides={"10-02": "Party"})
    board.refresh(START.replace(hour=12))
    # 00:30 on Oct 2 is still Oct 1's quote day, but it is Oct 2.
    assert board.refresh(START.replace(day=2, hour=0, minute=30)).kind == "override"
    assert board.refresh(START.replace(day=3, hour=0, minute=30)).kind == "quote"


def test_jump_to_applies_once_and_holds_for_the_day():
    board = Board(make_quotes(10), order="sequential")
    board.refresh(START.replace(hour=8))
    assert board.refresh(START.replace(hour=9), jump_to=7, command_nonce="a").number == 7
    # InkyPi keeps sending the same saved values; nothing changes.
    assert board.refresh(START.replace(hour=10), jump_to=7, command_nonce="a").number == 7
    # Tomorrow continues from the jumped-to quote.
    assert board.refresh(START.replace(day=2, hour=12), jump_to=7, command_nonce="a").number == 8


def test_jump_before_change_time_holds_through_that_day():
    board = Board(make_quotes(10), order="sequential")
    board.refresh(START.replace(hour=12))
    assert board.refresh(START.replace(day=2, hour=4), jump_to=5, command_nonce="x").number == 5
    assert board.refresh(START.replace(day=2, hour=6)).number == 5
    assert board.refresh(START.replace(day=3, hour=6)).number == 6


def test_jump_out_of_range_is_ignored():
    board = Board(make_quotes(3), order="sequential")
    board.refresh(START.replace(hour=12))
    assert board.refresh(START.replace(hour=13), jump_to=9, command_nonce="b").number == 1


def test_skip_advances_once_per_nonce():
    board = Board(make_quotes(10), order="sequential")
    board.refresh(START.replace(hour=12))
    assert board.refresh(START.replace(hour=13), skip=True, command_nonce="s1").number == 2
    assert board.refresh(START.replace(hour=14), skip=True, command_nonce="s1").number == 2
    assert board.refresh(START.replace(hour=15), skip=True, command_nonce="s2").number == 3


def test_stale_nonce_from_playlist_settings_is_not_reapplied():
    """Update Now applies nonce n2; the playlist instance still holds n1,
    which was applied earlier. Re-sending n1 must do nothing."""
    board = Board(make_quotes(10), order="sequential")
    board.refresh(START.replace(hour=12))
    board.refresh(START.replace(hour=13), jump_to=4, command_nonce="n1")
    assert board.refresh(START.replace(hour=14), jump_to=8, command_nonce="n2").number == 8
    assert board.refresh(START.replace(hour=15), jump_to=4, command_nonce="n1").number == 8


def test_clock_jumping_backwards_recovers():
    board = Board(make_quotes(10), order="sequential")
    # A Pi without network time can boot with a far-future clock.
    board.refresh(datetime(2030, 1, 1, 12))
    assert board.refresh(START.replace(hour=12)).kind == "quote"
    first = board.refresh(START.replace(hour=13)).number
    assert board.refresh(START.replace(day=2, hour=12)).number == first + 1


def test_corrupt_or_old_state_starts_fresh():
    quotes = make_quotes(3)
    for bad in (None, {}, {"version": 0}, {"version": 1, "queue": "nope", "cycle_shown": 5}):
        selection, state = select(quotes, bad, START.replace(hour=12), order="sequential")
        assert selection.number == 1
        assert state["version"] == 1
