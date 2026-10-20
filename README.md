# inkypi-daily-quote

An [InkyPi](https://github.com/fatihak/InkyPi) plugin that shows one quote per day on an e-ink display, rotating through a list you edit from your phone.

![Daily Quote on an 800×480 panel](docs/screenshot.png)

- Exactly one new quote per day at a time you choose. It holds all day, survives reboots, and doesn't care how often InkyPi refreshes.
- Shuffle (every quote once before any repeat), in-order, or random.
- Text auto-sizes: a 10-word quote fills the panel and a 60-word quote still fits. Line breaks are balanced, quotes are curly, and output is crisp 1-bit black and white.
- Special messages on chosen dates (birthdays, holidays).
- "Show next quote" and "jump to quote #N" from the settings page.
- Landscape and portrait. Three bundled OFL fonts: serif (Lora), extra-legible sans (Atkinson Hyperlegible), and handwritten (Patrick Hand).

**Status:** actively maintained. **External APIs:** none. Works offline.

## Install

On the Pi, with InkyPi already installed:

```bash
inkypi plugin install daily_quote https://github.com/User10796/inkypi-daily-quote
```

This copies the `daily_quote/` folder into InkyPi's `src/plugins/` and restarts the service. Run the same command again to update. The repo must be public for this to work without credentials on the Pi.

## Set up

1. On your phone, open `http://<hostname>.local` (for example `http://quotes.local`). Tap **Daily Quote**.
2. Paste your quotes, one per line: `Quote text — Author`. A spaced `-` or `--` also works, and the author is optional. Lines starting with `#` are ignored, which is handy for notes like `# Scripture`.
3. Press **Update Now** to preview it on the panel. Then **Add to Playlist**:
   - **Refresh:** every **1 hour** is a good choice. The plugin only changes the quote once a day, and InkyPi skips the panel refresh when the image hasn't changed, so hourly refreshes don't flash the screen.
   - **Playlist hours:** the playlist's time window acts as quiet hours. For example, a playlist running 05:00–22:00 means no refreshes overnight.

The new quote appears at the first refresh after **New quote each day at** (default 05:00). If the playlist doesn't start until 06:00, the day's quote shows up at 06:00.

## Settings

| Field | Default | Notes |
|---|---|---|
| Quotes | — | One per line. Blank lines and exact duplicates are skipped. |
| Order | Shuffle | **Shuffle:** every quote once, then a new shuffle (never the same quote twice in a row). **In list order:** wraps around. **Random:** never the same quote twice in a row. |
| New quote each day at | 05:00 | Uses the device time zone (InkyPi Settings). |
| Font | Serif | Serif, extra-legible sans, or handwritten. |
| Border | None | None, thin line, or double line. |
| Show author | On | |
| Show date | Off | A small "Tuesday, October 20" line at the bottom. |
| Special dates | — | `MM-DD message` every year, or `YYYY-MM-DD message` once. It replaces the quote for that calendar day, and the rotation picks up the next day without skipping a quote. |
| Change the quote now | — | Enter a quote number and press Update Now or Save, or tap **Show next quote**. The chosen quote stays up for the rest of the day. Numbers count quotes, not blank or `#` lines; the form shows a preview of the quote you picked. |

The form shows a live count ("42 quotes · about 6 weeks of rotation") and warns when a quote is over 300 characters, since long quotes shrink to fit.

### Editing the list

Add, remove, or reorder quotes anytime. The quote on screen stays put unless you deleted it; then the next one takes its place right away, and tomorrow still advances normally. In shuffle mode, new quotes join the current cycle, so nothing gets skipped.

## How state is stored

InkyPi replaces an instance's saved settings every time you save the form. Storing rotation state there would reset it on every edit, so the plugin keeps its state in a small JSON file instead:

```
InkyPi/src/config/daily_quote_state/<state_key>.json
```

`state_key` is a random ID the settings form creates once per playlist instance. The file survives InkyPi updates, plugin reinstalls, and reboots, and it is deleted when you delete the instance. Delete the file yourself to restart the rotation.

## Develop

No Pi or display needed:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest                     # parsing, rotation (fake clock), layout, plugin wiring
python scripts/preview.py  # renders sample boards to previews/*.png
```

Layout:

```
daily_quote/            # the folder InkyPi installs
  daily_quote.py        # InkyPi plugin class: settings → state file → logic → image
  quote_core.py         # parsing + once-per-day rotation (pure Python, injectable clock)
  quote_render.py       # Pillow rendering: auto-fit, balanced lines, 1-bit output
  settings.html         # web UI form
  plugin-info.json, icon.png, fonts/
tests/
scripts/preview.py
```

Rendering uses Pillow directly rather than InkyPi's HTML-to-Chromium path. That is much faster on a Pi Zero 2 W and gives exact text measurement. As a result, the border options are drawn by the plugin; InkyPi's shared frame and style settings don't apply.

## Licenses

Code: MIT (see `LICENSE`). Fonts: SIL Open Font License 1.1 (`daily_quote/fonts/OFL-*.txt`).
