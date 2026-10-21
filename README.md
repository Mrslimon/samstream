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

## Known limitations

Samsung's TVs set some hard limits. Samstream works around what it can; these remain.

**On the TV**

- **Picture-in-picture only with Live TV and HDMI.** Over Live TV, an HDMI input or Home,
  the camera can play with the TV's own picture kept in a corner (*TV picture in a corner*);
  the camera then shows as fast pictures rather than video, since the TV has one video layer.
  A sideloaded app cannot draw over Netflix or YouTube, and Samsung's Multi View has no API,
  so over streaming apps Samstream takes the full screen, then hands it back.
- **Playback state is invisible.** The TV does not report whether the app underneath was
  playing or paused. Samstream pauses it and presses Play afterwards; a pause made through
  Home Assistant is remembered, but one made with the TV's own remote is not. Turn off
  *Resume playback afterwards* if that resumes apps you had paused.
- **Live TV and HDMI look like "the last app".** The TV keeps reporting the last app as
  visible after you switch to Live TV or an input, so going back can reopen that app instead
  of staying on Live TV.
- **Typing needs the TV's own keyboard.** *Type on TV* works in the browser and sign-in
  fields; apps with their own on-screen keyboard (YouTube) ignore it.
- **The pointer needs an app that shows one** (the web browser). Elsewhere a click opens the
  TV's own pointer panel.
- **Camera audio is not played.** Streams are video only (H.264, or H.265 where the TV
  supports it); MJPEG cameras are not supported.

**Setup**

- **Developer Mode is required** to install the TV app, and it allows **one** computer: its
  host IP must be Home Assistant's. After turning it on or changing the IP, the TV needs a
  full restart (hold the power button; on The Frame, unplug it for 30 s).
- **Right-to-left menus** (Arabic and others) can store the Developer Mode IP backwards on
  some models; Home Assistant detects this and explains the fix.
- **Samsung certificate:** a free Samsung account sign-in issues it, valid for a year
  (Home Assistant warns before it expires). Each new TV needs one more sign-in; it then
  covers every TV.
- **Waking the TV** needs *Power On with Mobile* (Wake-on-LAN) on the TV. With Home Assistant
  in Docker, discovery and Wake-on-LAN broadcasts may not reach the TV: add the TV by IP and
  set the Wake-on-LAN target under *Configure → Network*.
- **The dashboard card** appears once a TV is added (Home Assistant loads the integration
  only then).
- **App logos** come from each app's public website icon; apps without a known site keep a
  letter tile, and you can add your own image.

Tested on a 2023 QN800C (Tizen 9) and a 2024 The Frame (Tizen 9). Samsung Tizen TVs from
2018 on should work; older models lack features Samstream relies on.

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

Built with help of [Claude](https://claude.ai).

It builds on the work of others:

- [samsungtvws](https://github.com/xchwarze/samsung-tv-ws-api) for the TV's WebSocket and REST APIs.
- [Apps2Samsung](https://github.com/Apps2Samsung/Apps2Samsung) and
  [Jellyfin2Samsung](https://github.com/Jellyfin2Samsung/Samsung-Jellyfin-Installer), whose
  per-user Samsung certificate technique Samstream follows.
- [go2rtc](https://github.com/AlexxIT/go2rtc), Home Assistant's built-in camera restreamer.
- [Readex Pro](https://fonts.google.com/specimen/Readex+Pro) (SIL Open Font License) for Arabic
  and Latin text on the TV.
