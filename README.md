<p align="center">
  <img src="custom_components/samstream/brand/icon@2x.png" width="128" alt="Samstream">
</p>

# Samstream

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![hacs validate](https://img.shields.io/badge/hacs-validate-blue)](hacs.json)

**Your Samsung TV, finally a first-class citizen in Home Assistant.**

Home Assistant's built-in Samsung integration covers the basics: power, volume, keys.
Samstream takes over the whole screen: a real remote, a touchpad, your cameras, your videos,
Frame art, and full-screen alerts, all driven by automations — then it hands the TV back
exactly where you left it.

It ships its own signed Tizen TV app (installed by Home Assistant, no sideloading tools for
you to run), a protocol library that talks to the TV directly over LAN, and an optional
local-control channel that reads the TV's live state without polling.

## Table of contents

- [Features](#features)
- [Supported devices](#supported-devices)
- [Installation](#installation)
- [Configuration](#configuration)
- [Entities](#entities)
- [Actions](#actions)
- [Use cases](#use-cases)
- [Examples](#examples)
- [Removing a TV](#removing-a-tv)
- [Data updates](#data-updates)
- [Known limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Credits](#credits)
- [License](#license)

## Features

- 🎮 **Full remote control.** D-pad, OK, Back, Home, Menu, volume and playback from HA, with
  hold-to-repeat and real long presses. Every installed app is listed and one tap away.
- 🖱️ **Touch controls.** A touchpad that drives the TV's pointer, and a keyboard that types
  straight into the TV, Arabic included.
- 📹 **Cameras on demand.** Doorbell rings, the camera pops up on the TV in a couple of
  seconds, with your message on top. Low latency, no transcoding (native H.264/H.265 via
  Home Assistant's go2rtc).
- 🎬 **Your own videos.** Play anything from HA's media library on the TV, or straight from
  HA's media browser.
- 🚨 **Messages that grab attention.** Full-screen info, warning or alert cards with sound or
  text-to-speech, and text you can update live (perfect for an AI describing who is at the
  door).
- ↩️ **Seamless takeover.** Samstream pauses what you were watching, shows the camera or
  message, then reopens the app and resumes it, or switches the TV off again if it was off.
- 🖼️ **Frame art, built in.** List, show and upload artwork on a Samsung Frame, toggle Art
  Mode, and drive it all from a dashboard with signed thumbnail links.
- 🏠 **Optional local control (no cloud, no polling).** Pair a TV once (on-screen PIN or a
  tiny LAN helper) and Home Assistant runs a local OCF/SmartThings endpoint the TV dials
  into directly — live input, volume, channel, picture/sound mode and more, pushed the
  moment they change, with a one-click release back to SmartThings.
- 🗣️ **Voice bridge.** Give each TV a webhook; anything that calls it (a Bixby capsule, the
  TV app's voice screen, a script) gets routed through HA Assist and the answer shown or
  spoken back.
- 🃏 **A dashboard card.** Pick the parts you want (remote only, cameras only, anything), in
  any order, with app logos, right to left in Arabic.
- 📦 **Zero-fuss install & updates.** HA installs the Samstream TV app for you, signed with
  your own Samsung certificate, and offers it as a regular `update` entity — no separate
  sideloading tool for the user to run.

## Supported devices

Tested on a 2023 QN800C (Tizen 9) and a 2024 Samsung Frame (Tizen 9). Samsung Tizen TVs from
2018 on should work; older models lack some features (notably local control/OCF, which needs
the TV's SmartThings service) and fall back gracefully.

Requirements on the TV:

- **Developer Mode**, so Home Assistant can install the signed TV app over `sdb`.
- A free **Samsung account** sign-in (once per Home Assistant install), to issue the
  certificate the TV app is signed with.
- **Power On with Mobile** (Wake-on-LAN) turned on, if you want Home Assistant to wake a
  sleeping TV.

## Installation

### HACS (recommended)

Not yet in the default HACS store. Add it as a custom repository:

1. HACS → the **⋮** menu (top right) → **Custom repositories**.
2. Repository: `https://github.com/Mrslimon/samstream`, category **Integration**.
3. Install **Samstream**, then restart Home Assistant.
4. **Settings → Devices & services → Add integration → Samstream.**

### Manual

1. Copy `custom_components/samstream` into your Home Assistant `config/custom_components/`
   directory.
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration → Samstream.**

## Configuration

Everything is set up through the UI; there is no YAML configuration.

**Adding a TV** (config flow):

1. Enter the TV's IP (or let discovery find it).
2. **Developer Mode:** Home Assistant checks whether it can install over `sdb`. If not, it
   shows the exact Developer Mode screen to set — including the host IP to type in, split
   into the four boxes the TV asks for, and reversed if your TV's menu language is
   right-to-left.
3. **Samsung sign-in:** sign in once with a Samsung account so Home Assistant can issue a
   certificate; it covers every Samstream TV afterwards (valid a year, renewed with a
   warning before expiry).
4. The signed Samstream TV app installs automatically.
5. **Local control (optional):** pair the TV for the low-latency, no-polling channel. Home
   Assistant tries an on-screen PIN first; if it can't reach the TV directly (e.g. Home
   Assistant in a container without host networking), it offers a small LAN helper to
   download and run once from a computer on the TV's network instead.

**Options** (Configure on an added TV), by section:

| Section | Parameters |
|---|---|
| Network | the TV's IP, Wake-on-LAN target |
| App signing | re-run the Samsung sign-in; import/export certificates |
| TV app | extra apps to pin, UI language, theme, auto-update |
| Local control | pair / reconnect / release; port and advertised host, for unusual networks |
| Voice bridge | turn the per-TV webhook on/off, show the reply on the TV |
| Playback | resume playback after a takeover; what "off" means on a Frame (fully off vs.
Art Mode) |

## Entities

One device per TV. `has_entity_name` throughout, so names read as *TV name: entity name*.

| Platform | Entities |
|---|---|
| `media_player` | The TV itself: power, volume, mute, source, app, playback keys. The
target for every [action](#actions). |
| `binary_sensor` | Developer Mode, Samstream app installed, Local control connected, TV
camera privacy shutter, Energy saving, Motion, and (local control) accessibility toggles —
Voice guide, High contrast, Colour inversion, Greyscale |
| `sensor` | Developer host IP, Current app, and (local control) Channel, Ambient light,
Sound detected, Remote battery, Wi-Fi signal, Screen orientation |
| `select` | (local control) Input, Picture mode, Sound mode, Sound output — listed by the
TV's own names |
| `switch` | Art Mode (Frame, with local control) |
| `button` | Install Samstream app, Download app logos, Return to previous, Guide, Channel
list, Sources, Menu, Home screen |
| `update` | Samstream TV app: installed version vs. the one bundled in this integration;
`install` updates it in place |
| `notify` | `notify.send_message` shows a message on the TV screen (same path as the
`show_message` action) |

Diagnostic (`select`, and most `sensor`/`binary_sensor` above) entities need local control
paired; without it they stay unavailable rather than failing.

## Actions

All target a `media_player.*` entity. Full field reference is in Developer Tools → Actions
(or `services.yaml`).

| Action | What it does |
|---|---|
| `samstream.launch_app` | Opens an app, or brings it to the front. |
| `samstream.close_app` | Closes an app; the TV returns to what was on screen before. |
| `samstream.install_app` / `uninstall_app` | Installs/removes the signed Samstream app over
Developer Mode; returns the TV's log. |
| `samstream.play_stream` | Opens Samstream and plays a camera (turning the TV on first if
needed), with an optional message overlay, picture-in-picture corner and duration. |
| `samstream.show_message` | Full-screen info/warning/alert/success card, with a sound (media
library chime or TTS) and a duration. |
| `samstream.update_message` | Changes the text shown over a camera or message, without
reloading — for a description that arrives after the camera is already up. |
| `samstream.stop_stream` | Returns to what was on before (reopens and resumes the app, or
re-powers off); pair with a presence sensor or timer. |
| `samstream.send_keys` | Presses remote keys in sequence (`KEY_HOME`, `KEY_DOWN`, ...). |
| `samstream.hold_key` | Presses and holds one key, for long-press menus or fast seeking. |
| `samstream.send_text` | Types into the TV's on-screen keyboard (open the field first). |
| `samstream.pointer` | Moves the TV's pointer and/or clicks, in apps that show one (the web
browser). |
| `samstream.open_url` | Opens a link: YouTube links play in the YouTube app, anything else
opens in the TV's browser. |
| `samstream.art_mode` | Frame: toggles between normal TV and Art Mode. |
| `samstream.list_art` / `select_art` / `upload_art` | List stored Frame artwork (with
thumbnail links, for a dashboard picker), show one by content id, or upload a new image. |
| `samstream.local_control_request` | Advanced: a raw `get`/`post`/`push`/`reply` against one
of the TV's local-control resources. Needs local control on. |

## Use cases

- **Doorbell / security:** pop the camera up on whatever the TV is already showing, with a
  message overlay, then return to exactly where you were.
- **AI-described visitors:** show the camera immediately, then update the overlay text once a
  vision model's description arrives, without reloading the stream.
- **Whole-home alerts:** a leak, a smoke alarm, someone left a door open — a full-screen
  alert card with a chime or TTS, on every TV at once if you want.
- **Frame as ambient display:** rotate curated artwork on a schedule, or drop into Art Mode
  automatically once the room goes quiet, instead of a black screen.
- **Voice replies with a screen:** route a voice assistant's spoken answer to also show as
  text on the TV it was asked near.
- **Universal remote:** drive channel, input, volume and app switching from HA scripts,
  scenes or a dashboard, including TVs HA's core integration can't reach locally.

## Examples

```yaml
automation:
  - alias: "Show the doorbell camera on the living room TV"
    trigger:
      - trigger: state
        entity_id: binary_sensor.front_door_motion
        to: "on"
    action:
      - action: samstream.play_stream
        target:
          entity_id: media_player.living_room_tv
        data:
          camera: camera.front_door
          label: "Front door"
          message: "Someone is at the door"
          duration: 30

  - alias: "Fill in the AI description once it's ready"
    trigger:
      - trigger: event
        event_type: doorbell_description_ready
    action:
      - action: samstream.update_message
        target:
          entity_id: media_player.living_room_tv
        data:
          message: "{{ trigger.event.data.description }}"

  - alias: "Frame: Art Mode once the living room goes quiet after sunset"
    trigger:
      - trigger: state
        entity_id: binary_sensor.living_room_presence
        to: "off"
        for: "00:10:00"
    condition:
      - condition: sun
        after: sunset
    action:
      - action: switch.turn_on
        target:
          entity_id: switch.living_room_frame_art_mode
```

## Removing a TV

Delete the device as usual (**Settings → Devices & services → Samstream → the TV → ⋮ →
Delete**). If local control is paired, Samstream first hands the TV back to SmartThings
(`doxm`/`pstat` ownership release) before the device disappears, so the TV is never left
owned by a Home Assistant that no longer has it configured. If the TV can't be reached at
that moment, removal still proceeds — a **Repairs** entry explains that the release couldn't
be confirmed and what to do (retry while it's awake, or remove it from the SmartThings app).

The same release happens if you just turn local control off from **Configure → Local
control → Remove**, without deleting the device.

## Data updates

- The media player and most sensors poll the TV every 10 seconds (power, volume, current
  app); the app list refreshes every 6 hours, or on demand.
- With **local control** paired, the TV dials into Home Assistant's local OCF endpoint and
  pushes state changes as they happen (input, channel, volume, picture/sound mode, and the
  diagnostic sensors above) — no polling for those.
- Camera streams and full-screen messages are event-driven (an automation call), not polled.

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
- **Local control depends on the TV's SmartThings service**, which some very old models lack
  or disable; those TVs work with everything except the local-control entities and the
  push-based updates.

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

## Troubleshooting

- **"Developer Mode needed" keeps showing up:** the host IP in the TV's Developer Mode
  screen must exactly match Home Assistant's LAN address, and the TV needs a full restart
  after you change it (see above). The repair card shown in HA spells out the exact IP and,
  for right-to-left menus, the reversed digits to type.
- **App install fails after adding a new TV to an existing certificate:** the certificate
  only covers TVs it was issued against; re-run **Configure → App signing → Sign in with
  Samsung** to extend it to the new one.
- **Local control won't connect / "not reachable":** Home Assistant must be reachable from
  the TV on the local-control port (default `5684/tcp`). In Docker, publish that port or use
  host networking; a **Repairs** entry names the exact fix for your install type (Container
  vs. Core).
- **Local control was working, then stopped:** open **Configure → Local control** again — a
  TV that reverted to unowned (a factory/network reset, or it was re-added in SmartThings)
  shows as disconnected rather than erroring; pair it again from there.
- **Pairing fails with "no server Finished from the TV", and a power cycle does not fix it:**
  the TV's own local-control security state can get stuck even while it reports no owner — a
  plain restart does not always clear it. Add the TV in the SmartThings app, then remove it
  again right away; that forces a real reset of this state that a power cycle does not. Try
  pairing again afterward.
- **A full diagnostics download** (Settings → Devices & services → Samstream → the TV → ⋮ →
  Download diagnostics) has secrets removed and is the fastest way to attach useful detail to
  a bug report.

## Development

| Path | What | Stack |
|---|---|---|
| `custom_components/samstream/` | HA integration | Python 3.14, async |
| `lib/aiosamstream/` | Protocol library (TV control, local-control/OCF client and cloud,
pure-Python sdb, wgt signing, WoL), published to PyPI | Python, `py.typed` |
| `tv-app/` | Samstream Tizen web app (AVPlay player + overlay) | TypeScript, Vite |
| `card/` | Optional Lovelace card | Lit, TypeScript |
| `tests/` | Integration tests (pytest-homeassistant-custom-component) | |

```sh
uv sync                       # lib + lint/type tools
uv run pytest lib/aiosamstream/tests
uv run ruff check . && uv run mypy lib/aiosamstream/src

cd tv-app && npm install
npm run typecheck && npm test && npm run build   # dist/ = unsigned wgt contents
```

Integration tests need Home Assistant, which does not install on native Windows:
run `uv sync --all-groups && uv run pytest` in WSL/Linux/CI, or against a dev HA instance
with `scripts/ha_dev.py test`.

Until `aiosamstream` is on PyPI, install it into the HA container with
`pip install -e lib/aiosamstream` (`scripts/ha_dev.py install-lib` does this).

See [docs/plan.md](docs/plan.md) for the fuller research notes, architecture and roadmap.

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

## License

[Apache License 2.0](LICENSE).
