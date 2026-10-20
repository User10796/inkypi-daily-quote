"""End-to-end through the InkyPi plugin class with a fake device config."""

import json
import os
from datetime import datetime, timedelta

import pytest

from daily_quote import daily_quote as dq

QUOTES = "\n".join(f"Quote number {i} — Author {i}" for i in range(1, 11))


class FakeDeviceConfig:
    def __init__(self, tmp_path, orientation="horizontal", timezone="America/New_York"):
        self.config_file = str(tmp_path / "config" / "device.json")
        self._config = {"orientation": orientation, "timezone": timezone}

    def get_resolution(self):
        return [800, 480]

    def get_config(self, key=None, default=None):
        return self._config.get(key, default)


class ClockedPlugin(dq.DailyQuote):
    def __init__(self):
        super().__init__({"id": "daily_quote"})
        self.fake_now = None

    def now(self, tz):
        return self.fake_now.replace(tzinfo=tz)


@pytest.fixture
def plugin():
    p = ClockedPlugin()
    p.fake_now = datetime(2026, 10, 20, 12, 0)
    return p


def settings(**extra):
    base = {
        "quotes": QUOTES,
        "order": "sequential",
        "change_time": "05:00",
        "font_style": "serif",
        "show_author": "true",
        "frame": "none",
        "state_key": "abc123",
    }
    base.update(extra)
    return base


def state_file(tmp_path, key="abc123"):
    return tmp_path / "config" / dq.STATE_DIR_NAME / f"{key}.json"


def current_number(tmp_path, key="abc123"):
    return json.loads(state_file(tmp_path, key).read_text())["current_index"] + 1


def test_generates_panel_sized_image_and_persists_state(plugin, tmp_path):
    image = plugin.generate_image(settings(), FakeDeviceConfig(tmp_path))
    assert image.size == (800, 480)
    assert image.mode == "RGB"
    assert state_file(tmp_path).exists()
    assert current_number(tmp_path) == 1


def test_vertical_orientation_renders_portrait(plugin, tmp_path):
    image = plugin.generate_image(settings(), FakeDeviceConfig(tmp_path, orientation="vertical"))
    assert image.size == (480, 800)


def test_saving_the_form_does_not_reset_rotation(plugin, tmp_path):
    """InkyPi replaces the settings dict on save; state lives in its own
    file keyed by state_key, so the rotation carries on."""
    device = FakeDeviceConfig(tmp_path)
    for day in range(3):
        plugin.fake_now = datetime(2026, 10, 20 + day, 12, 0)
        plugin.generate_image(settings(), device)
    assert current_number(tmp_path) == 3
    resaved = settings(font_style="sans")  # a brand-new dict, as InkyPi sends
    plugin.fake_now = datetime(2026, 10, 22, 13, 0)
    plugin.generate_image(resaved, device)
    assert current_number(tmp_path) == 3


def test_seven_days_hourly_through_plugin(plugin, tmp_path):
    device = FakeDeviceConfig(tmp_path)
    start = datetime(2026, 10, 20, 12, 0)
    seen = []
    for hour in range(7 * 24 + 1):
        plugin.fake_now = start + timedelta(hours=hour)
        plugin.generate_image(settings(), device)
        seen.append(current_number(tmp_path))
    assert seen[0] == 1 and seen[-1] == 8
    assert sum(1 for a, b in zip(seen, seen[1:]) if a != b) == 7


def test_jump_command_via_settings(plugin, tmp_path):
    device = FakeDeviceConfig(tmp_path)
    plugin.generate_image(settings(), device)
    plugin.generate_image(settings(jump_to="6", command_nonce="1700000000000"), device)
    assert current_number(tmp_path) == 6
    plugin.fake_now += timedelta(hours=1)
    plugin.generate_image(settings(jump_to="6", command_nonce="1700000000000"), device)
    assert current_number(tmp_path) == 6


def test_skip_command_via_settings(plugin, tmp_path):
    device = FakeDeviceConfig(tmp_path)
    plugin.generate_image(settings(), device)
    plugin.generate_image(settings(skip_next="true", command_nonce="n1"), device)
    assert current_number(tmp_path) == 2


def test_separate_instances_have_separate_state(plugin, tmp_path):
    device = FakeDeviceConfig(tmp_path)
    plugin.generate_image(settings(state_key="one"), device)
    plugin.generate_image(settings(state_key="two", jump_to="9", command_nonce="z"), device)
    assert current_number(tmp_path, "one") == 1
    assert current_number(tmp_path, "two") == 9


def test_state_key_is_sanitized(plugin, tmp_path):
    plugin.generate_image(settings(state_key="../../etc/passwd"), FakeDeviceConfig(tmp_path))
    assert state_file(tmp_path, "etcpasswd").exists()


def test_missing_state_key_uses_default(plugin, tmp_path):
    s = settings()
    del s["state_key"]
    plugin.generate_image(s, FakeDeviceConfig(tmp_path))
    assert state_file(tmp_path, "default").exists()


def test_empty_list_renders_placeholder_without_state(plugin, tmp_path):
    image = plugin.generate_image(settings(quotes="  \n"), FakeDeviceConfig(tmp_path))
    assert image.size == (800, 480)
    assert not state_file(tmp_path).exists()


def test_override_and_date_line(plugin, tmp_path):
    device = FakeDeviceConfig(tmp_path)
    normal = plugin.generate_image(settings(), device)
    override = plugin.generate_image(settings(date_overrides="10-20 Happy birthday!"), device)
    dated = plugin.generate_image(settings(show_date="true"), device)
    assert normal.tobytes() != override.tobytes()
    assert normal.tobytes() != dated.tobytes()


def test_bad_timezone_falls_back(plugin, tmp_path):
    image = plugin.generate_image(settings(), FakeDeviceConfig(tmp_path, timezone="Mars/Olympus"))
    assert image.size == (800, 480)


def test_corrupt_state_file_starts_fresh(plugin, tmp_path):
    path = state_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    plugin.generate_image(settings(), FakeDeviceConfig(tmp_path))
    assert current_number(tmp_path) == 1


def test_unwritable_state_dir_still_renders(plugin, tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(dq, "save_state", boom)
    image = plugin.generate_image(settings(), FakeDeviceConfig(tmp_path))
    assert image.size == (800, 480)


def test_cleanup_removes_state_file(plugin, tmp_path, monkeypatch):
    device = FakeDeviceConfig(tmp_path)
    plugin.generate_image(settings(), device)
    monkeypatch.setattr(dq.DailyQuote, "_device_config_for_cleanup", staticmethod(lambda: device))
    plugin.cleanup(settings())
    assert not state_file(tmp_path).exists()
    plugin.cleanup(settings())  # already gone: no error


def test_state_dir_fallback_without_config_file():
    class NoFile:
        pass

    assert dq.state_dir(NoFile()).endswith(os.path.join("inkypi", dq.STATE_DIR_NAME))


def test_settings_template_params():
    params = dq.DailyQuote({"id": "daily_quote"}).generate_settings_template()
    assert params["font_styles"] == ["serif", "sans", "handwritten"]
