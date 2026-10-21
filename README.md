# Samstream

**Your Samsung TV, finally a first-class citizen in Home Assistant.**

Home Assistant's built-in Samsung integration covers the basics: power, volume, keys.
Samstream takes over the whole screen: a real remote, a touchpad, your cameras, your videos
and full-screen alerts, all driven by automations, then it hands the TV back exactly where
you left it.

- 🎮 **Full remote control.** D-pad, OK, Back, Home, Menu, volume and playback from HA, with
  hold-to-repeat and real long presses. Every installed app is listed and one tap away.
- 🖱️ **Touch controls.** A touchpad that drives the TV's pointer, and a keyboard that types
  straight into the TV, Arabic included.
- 📹 **Cameras on demand.** Doorbell rings, the camera pops up on the TV in a couple of
  seconds, with your message on top. Low latency, no transcoding.
- 🎬 **Your own videos.** Play anything from HA's media library on the TV, or straight from
  HA's media browser.
- 🚨 **Messages that grab attention.** Full-screen info, warning or alert cards with sound or
  text-to-speech, and text you can update live (perfect for an AI describing who is at the door).
- ↩️ **Seamless takeover.** Samstream pauses what you were watching, shows the camera or
  message, then reopens the app and resumes it, or switches the TV off again if it was off.
- 🃏 **A dashboard card.** Pick the parts you want (remote only, cameras only, anything), in any
  order, with app logos, right to left in Arabic.
- 📦 **Zero fuss install.** HA installs the Samstream TV app for you, signed with your own
  Samsung certificate, and keeps it up to date.

Status: **feature complete, preparing the first release** (full documentation follows). See
[docs/plan.md](docs/plan.md) for research, architecture, roadmap and results.

## Layout

| Path | What | Stack |
|---|---|---|
| `custom_components/samstream/` | HA integration | Python 3.14, async |
| `lib/aiosamstream/` | Protocol library (TV control, pure-Python sdb, wgt signing, WoL), published to PyPI | Python, `py.typed` |
| `tv-app/` | Samstream Tizen web app (AVPlay player + overlay) | TypeScript, Vite |
| `card/` | Optional Lovelace card | Lit, TypeScript |
| `tests/` | Integration tests (pytest-homeassistant-custom-component) | |

## Development

```sh
uv sync                       # lib + lint/type tools
uv run pytest lib/aiosamstream/tests
uv run ruff check . && uv run mypy lib/aiosamstream/src

cd tv-app && npm install
npm run typecheck && npm test && npm run build   # dist/ = unsigned wgt contents
```

Integration tests need Home Assistant, which does not install on native Windows:
run `uv sync --all-groups && uv run pytest` in WSL or rely on CI.

Until `aiosamstream` is on PyPI, install it into the HA container with
`pip install -e lib/aiosamstream` (`scripts/ha_dev.py install-lib` does this).

## Credits

Samstream was coded with the help of [Claude](https://claude.ai), Anthropic's AI assistant,
working with the author: Claude wrote most of the code and tests, and the author directed the
design and tested every step on a real Samsung TV.

It builds on the work of others:

- [samsungtvws](https://github.com/xchwarze/samsung-tv-ws-api) for the TV's WebSocket and REST APIs.
- [Apps2Samsung](https://github.com/Apps2Samsung/Apps2Samsung) and
  [Jellyfin2Samsung](https://github.com/Jellyfin2Samsung/Samsung-Jellyfin-Installer), whose
  per-user Samsung certificate technique Samstream follows.
- [go2rtc](https://github.com/AlexxIT/go2rtc), Home Assistant's built-in camera restreamer.
- [Readex Pro](https://fonts.google.com/specimen/Readex+Pro) (SIL Open Font License) for Arabic
  and Latin text on the TV.
