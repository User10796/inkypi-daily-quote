"""Daily Quote: one quote per day from a list managed in the InkyPi web UI."""

import json
import logging
import os
import re
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from plugins.base_plugin.base_plugin import BasePlugin

from . import quote_core as core
from . import quote_render as render

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/New_York"
STATE_DIR_NAME = "daily_quote_state"
_SAFE_KEY = re.compile(r"[^A-Za-z0-9_-]")


def _is_on(value) -> bool:
    return str(value).strip().lower() in ("true", "on", "1", "yes")


def state_dir(device_config) -> str:
    """Rotation state lives next to InkyPi's device.json (src/config/), which
    survives both InkyPi updates and reinstalling this plugin."""
    config_file = getattr(device_config, "config_file", None)
    if isinstance(config_file, str) and config_file:
        return os.path.join(os.path.dirname(config_file), STATE_DIR_NAME)
    return os.path.join(os.path.expanduser("~"), ".local", "state", "inkypi", STATE_DIR_NAME)


def state_key(settings) -> str:
    key = _SAFE_KEY.sub("", str(settings.get("state_key") or ""))[:64]
    return key or "default"


def load_state(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        logger.warning("Daily Quote: unreadable state file %s; starting fresh", path)
        return None


def save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=1)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class DailyQuote(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["font_styles"] = list(render.FONT_STYLES)
        template_params["frames"] = list(render.FRAMES)
        return template_params

    def now(self, tz):
        """Overridable clock (tests inject a fake one)."""
        return datetime.now(tz)

    def generate_image(self, settings, device_config):
        dimensions = tuple(device_config.get_resolution())
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        tz_name = device_config.get_config("timezone", default=DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo(DEFAULT_TIMEZONE)
        now = self.now(tz)

        font_style = settings.get("font_style") or render.DEFAULT_FONT_STYLE
        frame = settings.get("frame") or "none"
        quotes = core.parse_quotes(settings.get("quotes"))

        path = os.path.join(state_dir(device_config), f"{state_key(settings)}.json")
        old_state = load_state(path)
        selection, state = core.select(
            quotes,
            old_state,
            now,
            order=settings.get("order"),
            change_time=core.parse_change_time(settings.get("change_time")),
            overrides=core.parse_overrides(settings.get("date_overrides")),
            jump_to=core.parse_jump(settings.get("jump_to")),
            skip=_is_on(settings.get("skip_next")),
            command_nonce=(settings.get("command_nonce") or "").strip() or None,
        )
        if state != old_state and selection.kind != "empty":
            try:
                save_state(path, state)
            except OSError as exc:
                # Still show something; the rotation just won't persist.
                logger.error("Daily Quote: could not save state to %s: %s", path, exc)

        date_line = None
        if _is_on(settings.get("show_date")):
            date_line = f"{now:%A}, {now:%B} {now.day}"

        if selection.kind == "empty":
            return render.render_placeholder(dimensions, font_style)
        if selection.kind == "override":
            return render.render(
                dimensions,
                selection.message,
                font_style=font_style,
                add_quote_marks=False,
                date_line=date_line,
                frame=frame,
            )
        quote = selection.quote
        return render.render(
            dimensions,
            quote.text,
            quote.author if _is_on(settings.get("show_author")) else None,
            font_style=font_style,
            date_line=date_line,
            frame=frame,
        )

    def cleanup(self, settings):
        """Delete this instance's rotation state when it is removed."""
        if not settings.get("state_key"):
            return
        path = os.path.join(state_dir(self._device_config_for_cleanup()), f"{state_key(settings)}.json")
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Daily Quote: could not remove %s: %s", path, exc)

    @staticmethod
    def _device_config_for_cleanup():
        # cleanup() isn't given device_config. InkyPi's Config class exposes
        # config_file as a class attribute, so import it lazily.
        try:
            from config import Config

            return Config
        except ImportError:
            return None
