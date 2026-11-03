# Samstream: Research, Architecture and Roadmap

## Context
The goal is a Home Assistant (HA) custom integration plus a Samsung Tizen TV web app, both named **Samstream**. Together they give HA full control of the TV and let it play an RTSP camera stream on demand, with overlay text that supports Arabic and RTL (for example, a doorbell press shows the camera, then the TV goes back to the previous app). The working directory `D:\Islam\SamStream` is empty, so this is a new project with no existing code to reuse. This plan covers research findings, the architecture decision, a milestone roadmap and pitfalls. Coding starts at Milestone 1 (skeleton only) after the user answers the QA questions.

---

## 1. Research findings

### 1.1 Samsung TV control protocol (samsungtvws)
- **WebSocket:** `wss://<ip>:8002/api/v2/channels/samsung.remote.control?name=<b64 name>&token=<token>`. **Only the 8002 (TLS) endpoint issues a token.** Port 8001 never returns one, so the popup appears on every connection. The token arrives in the `ms.channel.connect` event after the user presses "Allow".
- **Popup handling:** samsungtvws can persist the token (`token_file` / `token=`). We will store it in the config entry `data`, so pairing happens once inside the config flow. We also need to:
  - keep the client `name` identical on every connection, because the TV keys trust on name plus token;
  - guide the user to set TV **Settings → General → External Device Manager → Device Connection Manager → Access Notification → "First Time Only"**;
  - tell the user to remove stale entries from the Device List.
- **REST on 8001/8002:**
  - `GET /api/v2/` returns device info: model, `wifiMac`, `PowerState` (2018+), firmware/OS, resolution.
  - `GET|POST|DELETE /api/v2/applications/{appId}` gets an app's `running`/`visible` status, launches it, or closes it.
- **Apps over WS:** `ed.installedApp.get` lists installed apps (empty or unsupported on some 2020+ firmwares). `ed.apps.launch` takes `action_type: DEEP_LINK` plus a `metaTag`, which is **how we pass the RTSP URL and overlay payload to Samstream at launch**.
- **Async support:** the library supports async (`samsungtvws[async]`, built on aiohttp and websockets), and the async REST client accepts an injected aiohttp session. HA core's own `samsungtv` integration already uses it, which shows it can meet core quality expectations.
- **Wake-on-LAN:** works only on wired LAN or with "Power On with Mobile" enabled. The MAC comes from `wifiMac` in device info.
- **Current app:** there is **no generic "foreground app" API** on modern firmware. We infer it by polling `GET /applications/{id}` for a known list of app IDs (`visible: true`). The SmartThings API can optionally report input source and app on 2018+ models.
- **Reference:** the Go project stephen-slm/samsung-tv-api implements the same endpoints, so no new capability there.

### 1.2 Installing apps remotely (sideloading)
- **Mechanism:** sideloading uses **sdb** (Smart Development Bridge, an ADB-derived protocol on TCP **26101**). The flow is:
  1. `sdb connect <ip>`
  2. `sdb push app.wgt /home/owner/share/tmp/sdk_tools/tmp/`
  3. `sdb shell 0 vd_appinstall <appId> <path>`
- **Barriers:**
  1. The TV must be in **Developer Mode**: Apps panel → type `12345` → ON → enter the **HA host's IP** → reboot. Only one host IP is allowed, so the user's dev PC and HA would fight over it.
  2. The `.wgt` must be signed with a **Samsung certificate whose distributor profile includes the TV's DUID**. Signing needs Tizen Studio's Certificate Manager and a Samsung account, so it **cannot be done inside HA**.
  3. The `sdb` binary is published for x86_64 only, so there is no aarch64 build for Raspberry Pi HA OS hosts.
- **taizn (@putdotio/taizn, Node/TS):** a solid **dev-machine** tool for package, sign, install, launch, logs and remote control. It *drives the Tizen Studio CLI and sdb*, so it needs Tizen Studio installed. It is **not** usable inside HA. We will use it for the developer workflow.
- **Conclusion:** HA can install a **pre-signed** `.wgt` by talking the sdb wire protocol directly from a small **pure-Python async sdb client**. The user signs the app once on a PC (we script this with taizn) and uploads or points HA at the signed file.
- **Alternative:** the community loader TizenBrew avoids per-TV signing, but it is unofficial.

### 1.2b Decisions from the user's answers (zero-config install, HA Container on Windows x64)
- **sdb cannot be avoided for sideloading.** The only install path without Developer Mode is publishing to the Samsung Apps store (Seller Office certification). That could be a long-term option, and the app then just becomes "install from store". We **do not need the sdb binary**: `aiosamstream` speaks the sdb wire protocol in pure Python, so it works the same in HA Container, HA OS, Pi and Windows Docker. **No add-on is needed.**
- **A single universally pre-signed `.wgt` cannot install on arbitrary retail TVs.** Samsung requires a distributor cert containing *that* TV's DUID (older or some models accept the default Tizen developer cert, but 2018+ generally does not). Plan for the easiest UX:
  1. Ship a **generic, unsigned Samstream build inside the integration** (versioned; the same app for all users, with no IP baked in).
  2. **Per-TV signing in HA (spike, Milestone 7a):**
     - read the DUID over sdb (`capability`);
     - the user does a one-time Samsung-account sign-in in the config flow (browser redirect), and HA requests the author and distributor certs;
     - HA re-signs the wgt in Python (XML-DSig `author-signature.xml` / `signature1.xml`) and installs it.
     - Prior art: community tools that generate Samsung certs without Tizen Studio, used by TizenBrew and Jellyfin-Tizen installers. **Risk:** this uses Samsung's cert endpoints unofficially.
  3. **Fallback if the spike fails:** a guided one-click PC script (taizn) that creates the cert, and the user uploads the `.p12` files to HA once. HA then signs and installs every future version itself.
- **The app finds HA without discovery hacks.** Tizen web apps have no raw UDP, so mDNS is impossible.
  - HA always launches the app via DEEP_LINK with a `metaTag` containing `{ha_url, tv_secret, payload}`. The app saves `ha_url`/secret in `localStorage`, so when HA's IP changes the next launch fixes it automatically.
  - The app's settings screen offers a **manual IP entry** fallback (TV-remote friendly, Arabic/English) and an optional /24 subnet probe of `:8123/api/samstream/ping`.
- **Versioning and updates:** `config.xml` `<widget version>` is the single source of truth.
  - The app reports `{version, capabilities}` in its WebSocket hello to HA. HA also records the version at install time.
  - An HA **`update` entity** compares the installed version with the version bundled in the integration and installs updates over sdb.
  - The binary sensor "Samstream installed" uses `GET /api/v2/applications/{appId}` (404 means not installed).
- **HA in Docker Desktop on Windows:**
  - The container is NATed, so WoL broadcast and SSDP multicast do not leave the VM by default. Plan for **unicast/directed WoL** (send to the subnet broadcast or TV IP, configurable) and a manual host entry; SSDP discovery is a bonus.
  - The TV sees sdb/WS connections from the **Windows host LAN IP**, so that IP goes into Developer Mode "Host PC IP", and the app's `ha_url` must use the Windows LAN IP (taken from HA `internal_url`, overridable in options).

### 1.3 RTSP on Tizen
- **Playback API:** AVPlay (`webapis.avplay`, used with `<object type="application/avplayer">`) is the only native playback path for a web app. HTML5 `<video>` cannot play RTSP.
- **Privileges:** AVPlay needs no special privilege for plain playback (only `drmplay` for DRM). We need `http://tizen.org/privilege/internet`, `tv.inputdevice`, and `<access origin="*">`. There is **no `streamingtvplayer` privilege** for consumer TVs.
- **RTSP is not documented** for consumer AVPlay. Samsung's protocol docs list HTTP, HLS, DASH and Smooth Streaming, and RTP/UDP appears only in the B2B AVPlayExtension (hospitality TVs). Forum reports are mixed: `rtsp://` works on some model years and fails on others.
- **JuvoPlayer** supports RTP/RTSP, but it is a **Tizen .NET (C#) application with an FFmpeg-based demuxer**. That means native/.NET packaging and a much heavier stack. It is a good reference, but not our path.
- **Decision (needs a spike on the user's TV):**
  - **Primary:** AVPlay `open("rtsp://...")` straight to the camera, which gives the lowest latency.
  - **Fallback (planned from day 1):** HA's built-in **go2rtc** (in HA core since 2024.11) restreams RTSP as **HLS** or **MSE fMP4** over HTTP. AVPlay plays HLS reliably on all Tizen versions, and the Tizen Chromium web engine (2017+) supports MSE.
  - The integration probes which path works for each TV and stores the result.

### 1.4 HA quality scale (Platinum)
- **How tiers are declared:** a tier is set by `"quality_scale"` in `manifest.json`, backed by `quality_scale.yaml` (each rule marked `done`, `todo` or `exempt` with a reason), and checked by hassfest. There are 20 Bronze, 10 Silver, 21 Gold and 3 Platinum rules.
- **Official tiers are awarded only to core integrations.** A custom/HACS integration can **follow every rule and ship `quality_scale.yaml`**, but the badge only becomes official on core submission.
- **Platinum rules:**
  - `async-dependency`: samsungtvws[async] passes; our sdb client must be async.
  - `inject-websession`: pass `async_get_clientsession(hass)`.
  - `strict-typing`: mypy strict and a `py.typed` library.
- **Rules that matter most here:**
  - `dependency-transparency`: protocol code must live in a **separate PyPI library**, not in the integration.
  - `discovery`: SSDP/DHCP/zeroconf for Samsung TVs.
  - `reauthentication-flow`: for a revoked token.
  - `reconfiguration-flow`, `repair-issues` (e.g. "Developer Mode off", "Samstream not installed"), `diagnostics`, `entity-translations` and `exception-translations` (English plus **Arabic** `translations/ar.json`), `test-coverage` above 95%, `stale-devices`, `dynamic-devices`.
- **Conflict with the core integration:** HA core already has `samsungtv`. Running both would double-pair the TV. We should either stay standalone (and warn on conflict) or later contribute pieces upstream.

### 1.5 Node.js feasibility
- **A Node-only HA integration is impossible:** integrations are Python modules loaded in-process.
- **A Node sidecar** would mean a thin Python integration plus a Node add-on talking over HTTP/WS. Drawbacks:
  1. Add-ons run only on HA OS/Supervised, not on Container/Core installs.
  2. It breaks `async-dependency`, `dependency-transparency` (PyPI) and `strict-typing`, so **Platinum is unattainable**.
  3. It adds a process boundary: a second failure point, versioning drift and IPC latency (around 5–20 ms; negligible for latency, but heavy in complexity).
  4. It duplicates the auth and token storage logic.
- **Where Node/TS *fits*:** the TV app itself (HTML/TS), the Lovelace card (Lit + TS), and dev tooling (taizn, Vite builds, tests).

---

## 2. Audience and core features
- **Audience:** HA power users with Samsung Tizen TVs (2016+) and IP cameras (doorbell/NVR) who want cameras to interrupt the TV. They are comfortable with a one-time Developer Mode and signing setup.
- **TV control entities:**
  - `media_player` (power, volume, mute, play/pause, source = app list);
  - `remote` (send keys);
  - sensors: current app, model, firmware, IP;
  - `binary_sensor` for Samstream installed;
  - `button` for Wake-on-LAN and install Samstream;
  - an `update` entity for the Samstream app version.
- **Services:**
  - `samstream.play_stream` (url, overlay, duration, return_to_previous);
  - `samstream.show_overlay` (text, dir, position, ttl);
  - `samstream.stop_stream`;
  - `samstream.launch_app` (app_id);
  - `samstream.install_app` (wgt path).
- **TV app:** an AVPlay RTSP/HLS player with an HTML overlay (Readex Pro, bundled), auto RTL detection, a countdown ("الاستئناف خلال 3 ثوانٍ" / "Resuming in 3s"), and a persistent connection to HA for live overlay and stop commands.
- **Orchestration:** a single `play_stream` service runs this sequence: TV off → WoL → wait for REST → launch with metaTag; TV on → record current app → pause key → launch Samstream → play → on end, relaunch the previous app → play key.
- **Onboarding:** config-flow steps with an illustrated, translated Developer Mode guide, plus repairs issues when prerequisites break.

## 3. Tech stack recommendation (verdict: Python)
| Layer | Choice | Why |
|---|---|---|
| HA integration | **Python 3.13, async**, `custom_components/samstream` | Required by HA; the only route to Platinum-grade rules |
| Protocol library | **`aiosamstream`** (Python, PyPI, `py.typed`): wraps samsungtvws[async] and adds an async sdb client, app-state polling and a metaTag launcher | Satisfies `dependency-transparency`, `async-dependency`, `strict-typing` |
| TV app | **TypeScript + Vite** → Tizen web app (`config.xml`, AVPlay) | Fits the user's JS skills; AVPlay is a JS API |
| Lovelace card (later) | Lit + TypeScript | Node-native frontend |
| Dev tooling | Node: taizn (package, sign, install, logs), ESLint, Vitest; Python: uv, ruff, mypy --strict, pytest + pytest-homeassistant-custom-component | |
| Streaming fallback | HA go2rtc (HLS/MSE) | Handles TVs whose AVPlay rejects RTSP |
| HA ↔ TV app channel | Launch payload through **DEEP_LINK metaTag**; live control through the **TV app opening a WebSocket to an HA HTTP view** (`/api/samstream/ws`, per-TV secret) | Survives HA restarts; no reliance on the legacy Multiscreen SDK |

**Node.js drawbacks if chosen for the integration:** no Platinum, no Container/Core support, two runtimes to version, and duplicated auth. Rejected.

## 4. Milestone roadmap (each 1–2 days, each verifiable)
1. **Project setup (skeleton only):** monorepo with `custom_components/samstream/` (manifest, `__init__`, `const`, `config_flow` stub, `quality_scale.yaml`, `strings.json`, `translations/en.json` + `ar.json`), `lib/aiosamstream/` (pyproject, `py.typed`), `tv-app/` (Vite + TS, `config.xml`, Readex Pro woff2 + OFL license), `card/` placeholder, root tooling (ruff, mypy strict, pytest, eslint, prettier, `.editorconfig`, HACS `hacs.json`, GitHub Actions for hassfest and HACS validation). **Verify:** `pytest` runs empty, `mypy --strict` and `npm run build` both pass, hassfest passes.
2. **RTSP spike on the real TV:** a minimal TV app that plays a hard-coded `rtsp://` URL, then go2rtc HLS, through AVPlay, sideloaded with taizn. **Verify:** record latency and codec results (H.264/H.265) and confirm transparent HTML over the video plane. *This decides the primary path.*
3. **aiosamstream: connect and pair:** async WS client on 8002, token capture, device-info REST, WoL. **Verify:** a CLI script pairs once and reconnects without a popup, with unit tests on mocked WS.
4. **Config flow:** host/SSDP discovery → pair (popup) → store token/MAC; reauth and reconfigure flows; unique-entry check. **Verify:** config-flow tests at 100%; a real pairing works.
5. **Coordinator and core entities:** DataUpdateCoordinator, `media_player`, `remote`, device info, sensors, unavailable handling. **Verify:** entities in HA; power, volume and keys work.
6. **Apps:** installed-app list, current-app detection (polling known IDs), `launch_app` service, source select. **Verify:** launching works and the current-app sensor changes.
7. **Async sdb client and install:** connect, `capability` (DUID), push, `vd_appinstall`, uninstall; `binary_sensor` for installed; install button/service; repairs issue for "Developer Mode / host IP not set". **Verify:** install a PC-signed wgt from HA (in Docker on Windows) onto the TV.
7a. **Per-TV signing spike:** Python XML-DSig wgt signer; Samsung cert acquisition via account sign-in, or uploaded `.p12` as the fallback. **Verify:** HA alone turns the bundled generic wgt into an installed app on the TV. Decide between the automatic route and the upload fallback.
7b. **Versioning and `update` entity:** bundled app version vs reported or installed version; one-click update. **Verify:** bump the version → HA shows an update → install → the version matches.
8. **TV app player and settings:** AVPlay wrapper, parse the metaTag payload (persist `ha_url`/secret), manual HA IP settings screen, error and reconnect handling, auto-fallback RTSP→HLS, `config.xml` privileges. **Verify:** launching with a payload plays the stream.
9. **Overlay and Arabic/RTL:** overlay layer, `dir="auto"` + `unicode-bidi: isolate`, countdown, positions, bundled Readex Pro. **Verify:** screenshot-style test (Vitest + DOM) and a visual check with mixed Arabic/English and numbers on the TV.
10. **HA ↔ app live channel:** HA HTTP/WS view, per-TV secret, `show_overlay` and `stop_stream`, app heartbeat → `stream_active` sensor. **Verify:** live overlay updates during playback.
11. **Orchestration service:** `play_stream` state machine (off/WoL/on/pause/switch/play/end/return/resume), timeouts, concurrency lock. **Verify:** a doorbell automation works both with the TV on (in YouTube) and off.
12. **Gold/Platinum hardening:** diagnostics (redacted token), exception and icon translations, entity categories, stale devices, test coverage above 95%, mypy strict clean, docs (install, Developer Mode guide, removal). **Verify:** the `quality_scale.yaml` checklist is fully `done`/`exempt`.
13. **Lovelace card (optional):** Readex Pro, RTL, stream preview and controls.
14. **Release:** publish `aiosamstream` to PyPI (CI), HACS release, signed-wgt build script (taizn).

## 5. Edge cases and pitfalls
| Area | Risk | Mitigation |
|---|---|---|
| Pairing | Popup on every connect (port 8001 used, name changed, "Always ask" setting) | Force 8002 and a fixed name; guide the user to "First Time Only"; reauth flow |
| Token | Revoked after factory reset, device-list cleanup, or some firmware updates | Detect `ms.channel.unauthorized` → reauth flow + repair issue |
| Power | WoL fails on Wi-Fi or with deep standby; TV "off" but WS still answers (2018+ standby) | Use the REST `PowerState`; guide the user to enable "Power On with Mobile"; retries with backoff |
| Network | TV IP changes; VLANs block WoL broadcast or SSDP | DHCP discovery updates the host; let the user set the WoL broadcast address |
| RTSP | AVPlay rejects `rtsp://`; H.265 unsupported on older years; UDP blocked | go2rtc HLS fallback; force RTSP over TCP; prefer H.264 substreams |
| Latency | HLS adds 2–6 s | Prefer direct RTSP or MSE; tune the go2rtc segment length |
| Overlay | HTML not visible over the video plane (opaque body) | Transparent body plus a correct AVPlay `setDisplayRect` |
| Arabic | Wrong glyph shaping or bidi order with numbers or mixed text | Bundle Readex Pro (Arabic subset), use `dir="auto"` and bidi isolation, test on the real TV |
| Install | Developer Mode off, wrong host IP, cert lacks the DUID, no sdb on aarch64 | Pure-Python sdb client; repair issues with step-by-step guides; read the DUID in diagnostics |
| Dev Mode | Only one host IP allowed (dev PC vs HA); Dev Mode may reset after a firmware update | Document the switch; detect it and raise a repair issue |
| App detection | `ed.installedApp.get` empty on newer firmware | Fall back to probing known IDs via REST; optional SmartThings |
| Resume | The previous app won't restore its playback position (app-dependent) | Send a play key after relaunch; document best effort |
| Concurrency | Two doorbell events overlap | Per-TV asyncio lock; the newest stream replaces the old one, or both are queued |
| Core conflict | Core `samsungtv` already paired → duplicate clients and popups | Detect an existing entry and warn; the same name/token cannot be shared |
| Docker Desktop (Windows) | WoL broadcast and SSDP don't leave the NAT; the TV sees the Windows host IP | Directed/unicast WoL with a configurable target; manual host entry; Developer Mode host IP = Windows LAN IP; `ha_url` from `internal_url` |
| Signing | Generic wgt rejected ("check certificate"); Samsung cert API changes | Per-TV re-signing in HA; `.p12` upload fallback; Samsung store publication as the long-term path |
| HA URL change | The app holds a stale `ha_url` | Each HA-initiated launch re-sends `ha_url`; manual IP screen; subnet probe |
| Security | metaTag and app WS carry camera URLs with credentials | Per-TV secret; redact in diagnostics and logs; prefer go2rtc local URLs |

## 6. Verification approach
- **Python:** `pytest` with pytest-homeassistant-custom-component (mocked samsungtvws/sdb), `mypy --strict`, `ruff`, and hassfest + HACS actions in CI.
- **TV app:** Vitest for payload parsing and overlay/RTL logic; on-device checks through taizn `install` / `run` / `logs capture`.
- **End to end:** a manual doorbell automation scenario run against the real TV in both the on and off states at milestone 11.

---

## Update (after milestone 1): certificate strategy, based on Jellyfin2Samsung
Source: PatrickSt1991/Samsung-Jellyfin-Installer (MIT), `Apps2Samsung.Core/Certificate/*`, `Constants.cs`.
- **Tizen ≥ 7.0 (2023+, including the user's QN800C):** needs a Samsung distributor certificate that lists the TV's DUID.
  - **How Jelly2Sams gets one:** it **mints a cert for each user** with that user's own Samsung account. The steps:
    - the account sign-in (SignInGate, Tizen tooling client id) POSTs the token to a loopback `http://localhost:4794/signin/callback`;
    - an RSA-2048 key, an author CSR and a distributor CSR (SAN `URN:tizen:deviceid=<DUID>` per TV) are created;
    - the CSRs are posted to `svdca.samsungqbe.com` (`/apis/v3/authors`, `/apis/v1|v3/distributors`, `privilege_level=public`, `platform=VD`);
    - the results are packed into `.p12` files with the Samsung CA chain.
  - **Adding a TV:** only the distributor is regenerated, and the author key is kept. **Updates require the same author cert.**
- **Tizen 4.x–6.5:** Jelly2Sams ships a shared project cert (`Assets/Certificate/Jellyfin/*.p12` + `password.txt`). That key is effectively public, and it only works because those firmwares don't check the DUID.
- **Samstream decision:**
  - Never ship anyone's personal certificate.
  - On Tizen ≥ 7, each user's cert is created in their own HA and stored in `.storage`.
  - A dedicated, throwaway "Samstream shared" cert for 4.x–6.5 TVs is optional and decided later.
- **Open question for milestone 7a:** whether SignInGate accepts a non-localhost `redirect_uri` (HA's URL). If it doesn't, either the user uploads `.p12` files created in the VS Code Certificate Manager, or HA's own host serves the loopback callback (this works when the browser runs on the HA machine).

### Milestone 7a design, confirmed 2026-10-20 (same technique as Apps2Samsung, github.com/Apps2Samsung/Apps2Samsung, MIT)
- **The user's working cert** ("Jelly2Sams - Public") came from a one-time Samsung sign-in on 2026-09-06.
  - Author issuer: *Samsung VD Author CA*. Distributor issuer: *VD DEVELOPER Public CA Class*, with the account email and SAN `URN:tizen:deviceid=<DUID>`.
  - **Valid for 1 year.** Apps2Samsung reuses it silently afterwards, so HA must renew before `notAfter`.
- **SignInGate accepts only the exact redirect `http://localhost:4794/signin/callback`.** Every other URI tested returned HTTP 400: HA's LAN URL, `127.0.0.1`, other ports, other paths. The browser POSTs the token there, so **HA cannot receive it directly**.
- **Plan:**
  1. **Sign-in helper (default).**
     - The config flow shows a one-time code.
     - The user runs a tiny helper on any PC with a browser: `npx samstream-signin <code>` or a single exe. The helper listens on `localhost:4794`, opens Samsung sign-in, and forwards `{access_token, user_id, email}` to `POST /api/samstream/samsung_token` (authorized by the one-time code).
     - HA then reads the DUID over sdb, generates the key and CSRs, calls `svdca.samsungqbe.com`, builds the `.p12` files with the Samsung CA chain, and stores everything in `.storage`.
     - The user signs in only once a year, at renewal.
  2. **Import (no sign-in):** upload an existing Samsung `author.p12` + `distributor.p12` + password (Apps2Samsung profile folder, or a VS Code Certificate Manager *Samsung* profile). HA checks that the distributor SAN covers the TV's DUID.
  3. **Never ship anyone's certificate in the repo or the integration.**

### Streaming decision after milestone 2 (2026-10-20, QN800C on Tizen 9.0)
- **AVPlay on this TV cannot play RTSP at all.** Every variant failed with `InvalidAccessError`, and HLS through AVPlay freezes after the first frame.
- **go2rtc WebSocket MSE (fMP4 remux, video only) works:** first frame in 296 ms (H.264) and 953 ms (H.265), playing smoothly. FLAC audio breaks it, so audio must be AAC (ffmpeg transcode in go2rtc) and stays optional.
- **Architecture change:** milestone 8 plays MSE, not AVPlay. Milestone 10 adds an HA WebSocket proxy view to HA's built-in go2rtc, so the TV never talks to go2rtc directly. The proxy also avoids go2rtc's same-origin check, which rejects the TV app's `file://` origin.

### Roadmap addition (after milestone 6, 2026-10-21)
- **7c. Revisit app detection with the full app list — DONE (2026-11-03).** The coordinator reads the TV's full
  installed-app list over sdb (`async_list_apps` → `vd_applist`) whenever Developer Mode is on (`app_source="tv"`),
  so there is nothing left to probe. The REST catalog (`KNOWN_APPS`) is now only an automatic fallback for a TV
  without Developer Mode (`app_source="catalog"`). **The manual "Extra app IDs" option was REMOVED (user request,
  2026-11-03):** the field is gone from the options flow, the coordinator no longer reads it, and `async_step_network`
  strips a stored `extra_apps` from existing entries on next save. `parse_app_ids` deleted; strings/ar/en cleaned.
  - *(history) Problem was:* 2020+ firmware does not answer `ed.installedApp.get`, so milestone 6 probed a catalog
    plus a manual "Extra app IDs" option. The sdb `vd_applist` returns the real list (23 apps on the QN800C), so the
    manual option is obsolete.
  - **Also re-check:** whether the full list exposes home / Live TV / HDMI, which are "unknown" today, and whether foreground detection can avoid polling every app ID.

### Roadmap additions (2026-10-21)
- **End of 7b. TV app UI redesign**, from the user's spec:
  - **Layout:** a hero card holding the status and stream preview, an info card, and a bottom action bar.
  - **Palette:** dark security theme, #0B1420 background, #1A2636 surfaces, #3A9BD9 accent, #DC0014 for alerts only.
  - **Shape and type:** 14 px cards and 12 px buttons, never pill-shaped; Readex Pro 300/400/500/600, bundled locally.
  - **Remote and direction:** D-pad focus states, Arabic RTL with logical CSS properties.
  - **Stream overlay:** a bottom gradient (rgba(0,0,0,.6) to transparent).
  - **Release:** shipped as 0.1.0 through the new update entity.
- **15. Remote input extras (final milestone):**
  - **Text input:** `samstream.send_text`, using `SendInputString` + `SendInputEnd` for the TV's on-screen keyboard fields.
  - **Hold:** a `samstream.hold_key` action for long presses, on top of the existing `remote.send_command` `hold_secs`.
  - **Mouse:** move, left click and right click through the remote channel's `ProcessMouseDevice` (not wrapped by `samsungtvws`), plus a touchpad-style control in the Lovelace card from milestone 13.

### 7c result (2026-10-21)
- **Full list over sdb:** `vd_applist` returns every installed app (23 on the QN800C, against 7 found by the catalog). This includes regional apps like شاهد MBC, TOD by beIN, OSN+ and الشرق NOW.
- **Which ID to use:** each block has `app_id`, the store ID the REST status endpoint understands for all 23, and `app_tizen_id`, which REST rejects for system apps. We use `app_id`.
- **Fallback:** the catalog plus "Extra app IDs" is still used when sdb is unavailable (Developer Mode off).
- **Foreground check:** the last app on screen is re-checked first (one request while it stays). The full check runs only when it changes.
- **Still open:** home, Live TV and HDMI still show as "unknown". Neither the REST API nor `vd_applist` exposes them; SmartThings could, as a later option.

### Milestone 8 finding (2026-10-21), next step
- **The deep link never arrives.** On the QN800C, `ed.apps.launch` over the remote channel is ignored for the sideloaded Samstream app: DEEP_LINK and NATIVE_LAUNCH, with or without metaTag, open nothing and get no reply. So the launch payload never reaches the app. A REST `POST /api/v2/applications/SmStrm0001.Samstream` does open it, within about 1 s, but REST cannot carry data.
- **Fix (next): pull model.**
  - `play_stream` stores a pending command (stream + message) for the TV, then opens the app with a REST launch.
  - The app asks `GET /api/samstream/tv/{secret}/session` at start; the endpoint answers settings + pending command.
  - While the app is open it polls the same endpoint (every ~2 s, or later a WebSocket channel) for new or stop commands.
  - The payload parsing in `launch.ts` and the relay stay as they are; only the delivery changes.
- **Verified so far:** update 0.2.0 → 0.3.0 installed through HA, the relay works end to end in tests, and `play_stream` registers the stream in HA's go2rtc.

### Milestone 8 result and roadmap additions (2026-10-21)
- **Pull model verified on the QN800C:** `play_stream` queues the command and opens the app over REST. The app reads it from `/session` and polls every 2 s. Settings from HA (light theme) also arrive.
- **Streaming fix:** HA starts its go2rtc without the `mp4` module, so go2rtc ignores MSE requests (the TV got 0 KB). HA now runs `ffmpeg -c copy` from go2rtc's local RTSP restream to fragmented MP4 while a TV watches, sent in go2rtc's MSE WebSocket format. First data after about 1.2 s, no transcoding.
- **Overlay redesign (0.5.0):**
  - a glass status pill (pulsing LIVE badge, camera name, clock) that folds to the badge after 5 s;
  - HA's message as a floating card;
  - fit mode as a short chip at the top.
- **16. Notifications and media from HA** (after milestone 11, reusing its wake / switch / return flow):
  - **16a. Full-screen message:** `samstream.show_message` with title, body, optional icon and severity (info / warning / alert), duration or "until dismissed", and Arabic RTL. It is shown on its own screen, with no camera.
  - **16b. Message with sound:** an optional `media` field (a chime file, HA `media-source://` item or URL) or `tts` text. HA resolves it to a signed URL (TTS through HA's `tts` integration); the app plays it with an `<audio>` element while the message shows.
  - **16c. Videos from HA's media library:** make the Samstream media player browsable (`browse_media`) and support `play_media` with `media-source://` IDs. HA resolves them to a signed local URL, and the app plays MP4 / HLS with `<video>` (AVPlay as fallback). This also gives a "send to TV" option in HA's media browser.
- **17. PiP spike (camera over what you are watching):**
  - **Limit:** a Tizen web app cannot draw over another app. When Samstream comes to the front, Netflix / YouTube / Shahid move to the background (and usually pause). True PiP over streaming apps is not possible for a sideloaded app.
  - **What can work:** Samsung's TV Window API (`tizen.tvwindow`, privilege `http://tizen.org/privilege/tv.window`) shows the TV's own source (Live TV tuner or an HDMI input) inside our app. If you are watching Live TV or an HDMI device (receiver, console), Samstream can open with that source full screen and the camera in a corner, which looks the same as PiP. The spike checks whether Tizen 9 still allows it for our certificate level.
  - **For streaming apps:** the closest option is a "peek" mode. Samstream opens with the camera in a corner card over a dimmed still, then returns to the app and resumes after N seconds (milestone 11's flow). Motion triggers would use it with a short duration and a cooldown.
- **11 result (2026-10-21):** `play_stream` remembers what was on screen (fresh foreground check) and pauses that app. The new `duration` field, or `stop_stream`, returns: it reopens the app and presses Play, turns the TV off again if Samstream woke it, or closes Samstream when Home or Live TV was underneath. A second trigger keeps the first place to go back to, and a viewer who already left is not pulled back. When HA opened the camera, the app's Back key and HA's stop close Samstream (TV app 0.6.0); its home screen is only for opening Samstream from the TV's app list. App launches retry for about 10 s because the TV's REST server drops out now and then.
- **Done early from the end of the list:**
  - **Text-only updates:** `samstream.update_message` changes the text over the camera without reloading it, for example an AI description that arrives later. It does nothing if no camera is on the TV, and `play_stream` with the same camera also only updates the text.
  - **Long messages:** the card is capped at 40% of the screen height; longer text scrolls slowly, holds at each end, and scrolls back.
  - **Home source:** "Home" heads the media player's source list and presses the Home key.
- **16 result (2026-10-21), TV app 0.7.0:**
  - **`samstream.show_message`:** a full-screen card (title, scrolling message, icon and colour by severity: info / warning / alert with a pulsing ring), with an optional sound. The sound uses HA's media selector (library file or TTS), resolved and signed by HA.
  - **`media_player.play_media`:** plays media library items (`media-source://…`) and http(s) URLs full screen. OK pauses, ◀ ▶ seek 10 s, and the title and progress fade after 5 s. The media player is browsable, so HA's media browser can "play on TV".
  - **Shared take-over:** messages and videos use the same remember / pause / return flow as cameras. `duration` starts when the notice shows or the video starts, a video without `duration` returns when it ends, and `update_message` also changes a notice's text.
- **17 result (2026-10-21): PiP is not possible on the QN800C.**
  - **TV Window API:** the TV accepted the `tv.window` privilege, but when Samstream showed the TV window, the system brought Live TV itself to the front within about 1 s. Samstream moved to the background, so nothing can sit on top. The option was removed again (TV app 0.8.1).
  - **Multi View:** Samsung's Multi View has no API for apps.
  - **Detection gap:** the REST API keeps reporting the last app (e.g. YouTube) as `visible` after switching to Live TV, and Developer Mode's shell has no foreground command. So HA cannot tell Live TV from "the last app", and the return can reopen that app instead of staying on Live TV.
  - **Possible fix (later, optional):** read the input source from HA's SmartThings integration for the same TV (its media player reports the source, e.g. "TV" / "dtv").
- **13 result (2026-10-21): `custom:samstream-card`.**
  - **Card build:** Lit + TypeScript in `card/`, built by Vite into `custom_components/samstream/frontend/samstream-card.js`. HA serves it at `/samstream_files/` and adds it to every dashboard (no resource to set up); a content hash in the URL refreshes browsers after updates.
  - **What it shows:** TV state and current app with power; camera chips with message, duration, Show and Stop; a full-screen message with title, severity, duration, Show and "Update text"; an app grid (Home first, current app ringed); a remote (D-pad, OK, Back, Home, play/pause, volume, mute).
  - **Card details:** it has a visual editor (`getConfigForm`) and runs Arabic RTL from HA's language.
  - **Logos:** the TV gives no icons (`ed.apps.icon` / `ed.installedApp.get` get no answer on the QN800C) and there is no public lookup by app ID. So logos come from `/config/www/samstream/apps/`, matched by app ID, TV name or slugified name; other apps get coloured letter tiles. They show in the card, as the media player picture of the current app, and in a new **Apps** folder of the media browser (click to launch).
  - **Data:** the card reads apps over websocket (`samstream/apps`), not entity attributes.
- **SmartThings (local) research:** SmartThings-Local reaches Samsung TVs over CoAP-DTLS, but `/sec/tv/inputsource` etc. answer 4.01 without an owner credential, which would need an ownership transfer (PIN on the TV). Not pursued; the cloud SmartThings integration stays the optional way to tell Live TV from apps. Multi View: no remote key or API (KEY_MULTI_VIEW, KEY_PIP_ONOFF and others did nothing).
- **15 result (2026-10-21):**
  - **`samstream.send_text`:** types into the TV's on-screen keyboard field (`SendInputString`, UTF-8 so Arabic works), then closes it unless `done: false`.
  - **`samstream.hold_key`:** press and hold any key for N seconds.
  - **`samstream.pointer`:** relative move and left/right click via `ProcessMouseDevice`, for apps that show a pointer, such as the browser.
  - **samsungtvws compatibility:** the text payloads are built in `aiosamstream`, because HA's samsungtvws 2.7 lacks the 2.8 classes.
  - **Card:** D-pad and volume repeat while held, and OK / Back / Home / Menu send a long press after 0.6 s. New optional **Keyboard** and **Touchpad** sections: drag to move (batched every 60 ms), tap to click, hold to right-click.
  - **Play/pause fix:** play/pause now alternates Pause / Play, because the TV reports no playback state; it starts over when the app changes.
- **12 result (2026-10-21):** SSDP discovery with a confirm step, diagnostics download (redacted), translated go2rtc errors, icons for every action, developer host sensor disabled by default. `quality_scale.yaml` is filled in: everything done or exempt except the docs rules (documentation milestone). 275 tests, 97 % coverage.
- **Logo download:** a **Download app logos** button (configuration) fetches each app's public site icon onto the user's own HA, into `/config/www/samstream/apps/<app id>.png`. Sources are Google's favicon service at 256 px or the site's `apple-touch-icon`, whichever is larger; apps are matched by words in their name (`logos.LOGO_SITES`, Latin whole words and Arabic substrings). The user's own files are never replaced, and the Samstream tile uses our brand icon. Logos are not shipped in the repo (third-party trademarks). On the QN800C: 20 of 23 apps.

### Roadmap addition (2026-10-21): Advanced local things (local SmartThings over OCF)
> **Order (2026-10-27): OCF is the LAST item.** Everything that needs it waits with it and is not built
> before it: 18a–18h, 18k, 18l, 18m, the real named-input list (18i), the OCF corner fix (18e) and
> Frame artwork selection (19b). The local-cloud method is documented in `docs/ocf-local-protocol.md` §14.7;
> drafts of the CBOR/CoAP layers are parked in `oicseek/lib_draft/` (not part of the library yet).

Prepared while `oicseek/` is still a spike (not finished). This supersedes the "SmartThings (local) … Not pursued" note above and realises the "possible fix: read the input source" left open at milestones 11 and 17. `oicseek/otm_pair.py` has proven the DTLS-PSK handshake (phase 1); phase 2 (ownership) and the resource reads are what the lib will wrap. See [[samstream-tv-corner-detection]] and [[samstream-ocf-dtls-posture]].

- **Guiding principle — a capability gate, exactly like Developer Mode.**
  - **Off (the default, and whenever onboarding is absent, lost or the TV is unreachable over OCF): zero behaviour change.** Every current feature keeps using today's REST/WS paths; no new sensors appear; the existing tests must pass unchanged.
  - **On:** the coordinator *prefers* OCF data where it is richer, and new entities appear. OCF is only ever an override on top of today's logic, never a replacement that can break the off path.
  - **No new hard dependency when off:** the OCF deps (`python-mbedtls`, `cbor2`) load lazily, only when the capability is enabled, so a base install without those wheels is unaffected. `manifest.json` keeps them out of `requirements` or lists them as an optional extra.

- **What it unlocks (reliable local signals the REST/WS stack cannot give):**
  - **True input / foreground:** Live TV vs each HDMI vs Home vs a specific app, read from the TV's own OCF resources — not inferred from the laggy per-app `visible` flag. Fixes the corner-mode race measured on the QN800C (YouTube reports `visible:false` for seconds after opening; Home/Live TV/HDMI are indistinguishable from a silent app).
  - **Media playback:** title and real play/paused state → accurate `media_player` state and a real play/pause toggle (drops the "alternate Pause/Play because the TV reports no state" hack from milestone 15).
  - **Power usage:** watts / energy, if the TV's OCF stack exposes it → a power sensor.
  - Possibly current channel and a confirmation of volume/mute.

- **Architecture.**
  - New `lib/aiosamstream/ocf/` module: `/oic/res` discovery, **dynamic secure-port resolution per session** (`p.port` changes on every power cycle — never cache it across power states), a DTLS-PSK session (reuse `otm_pair.py`'s PBKDF2 PSK derivation and cipher), authenticated CBOR reads, ownership transfer (phase 2), and a thin resource→signal mapper.
  - A **"local source" abstraction in the coordinator, mirroring `app_source` ("tv"/"catalog")**: when OCF is owned and reachable, foreground/input, media and power come from OCF; otherwise the coordinator falls back to exactly today's logic.
  - `SamstreamState` stays **additive**: new optional fields (`input_source`, `media_title`, `playback_state`, `power_watts`, …) default `None`, so entities behave as now when OCF is off.
  - **Credential storage like the token/cert:** the owned credential (device UUID + PSK, plus whatever ownership yields) goes in the config entry / `.storage`, never the repo. `oicseek/tv_cred.json` is only the dev artifact.

- **Onboarding is the one write to the TV** (everything else is read or a remote key). Guard it behind an explicit user action; make re-onboarding safe; a factory reset clears it.

- **Milestones (each verifiable; start once `oicseek` finishes the lib spike):**
  - **18a. OCF client in the lib:** discover `/oic/res`, resolve the dynamic secure port, open a DTLS-PSK session, one authenticated read. **Verify:** an owned read returns 2.xx against the real TV; unit tests on mocked CBOR/DTLS.
  - **18b. Ownership transfer (otm_pair phase 2) as a library call + CLI.** **Verify:** an RFOTM TV is owned once with the on-screen PIN; re-runs reconnect with the stored credential, no PIN.
  - **18c. Resource map:** enumerate the TV's OCF resources and map which give input source, media and power. **Verify:** a documented resource→signal table for the QN800C, and a probe that prints each live.
  - **18d. Coordinator integration behind the gate:** prefer OCF for foreground/input and media when owned, fall back otherwise. **Verify:** with the toggle off every existing test passes and behaviour is identical; with it on, the source sensor tells Live TV from the last app.
  - **18e. Corner-mode fix via OCF:** `_async_corner` uses the OCF input source when available (Live TV/HDMI/Home → corner; any app → full). **Verify:** re-run the probe scenario (YouTube→full, Live TV→corner) with no transition misfire. The confirmation-sampling fallback (see [[samstream-tv-corner-detection]]) stays for the gate-off path.
  - **18f. New entities:** power sensor, media title/state, real play/pause. **Verify:** entities update live; play/pause follows actual state when OCF is on.
  - **18i interim — DONE (2026-10-27):** an *Input list* source (and card tile) sends `KEY_SOURCE`, opening the TV's own input picker on any model. The real named-input list still waits for OCF (18l).
  - **18i. Accurate inputs (from the source-button bug, 2026-10-22).** The media_player `source_list` is a FIXED list (Home, Live TV, HDMI 1–4) regardless of what the TV has; on the QN800C (no HDMI devices, no antenna — only Samsung TV Plus) those entries are dead no-ops, and single input keys (`KEY_HDMI2`, `KEY_TV`) are unreliable across models anyway. `KEY_SOURCE` works (opens the picker), so key delivery is fine. Fix with OCF: list the TV's **real** inputs and select a named input reliably. Interim option: expose a "Source" entry that just sends `KEY_SOURCE` so the user picks visually, and/or add Samsung TV Plus.
  - **18g. Onboarding config/options flow + credential storage + repairs + docs:** an "Advanced local things (local SmartThings)" toggle; turning it on runs the PIN onboarding (document how to make the TV show the PIN); a reauth/repair path when the credential is lost; a disabled-by-default "Local access: owned" diagnostic. **Release local control** (options flow + button, with a confirm): as owner, POST `/oic/sec/pstat {cm:1}` — the TV drops our ownership at once (doxm unowned, RFOTM) with **no Smart Hub reset and no lost apps**, so it can be added to SmartThings again (verified 2026-10-22: while we own it with isop=true the TV is hidden from the SmartThings app's "add device" scan; after this reset it appears). Disabling the toggle offers this step; the guided setup (milestone 22) offers it when the user wants SmartThings instead. **Verify:** enable from the UI, onboard, lose/restore the credential; disabling returns to today's behaviour; "Release" makes the TV addable in the SmartThings app.
  - **18h. Hardening:** lazy/optional OCF deps, session lifecycle and reconnection on power cycle (new dynamic port), unreachable-OCF never fails an update (falls back), diagnostics redaction, coverage/mypy bar. **Verify:** install without the OCF wheels still loads; `quality_scale.yaml` stays green.

- **18 revision (2026-10-23), after the read investigation.** Over the local owner session, every `/sec/tv/*` and `/capability/*` resource answers **4.00** to GET/OBSERVE (state is served only to the Samsung cloud), so 18c–18f as written (input/media/power *read* over local OCF) are not achievable. Local OCF stays: **commands** (POST works) + **diagnostic reads**. Live state comes from UPnP (volume/mute) and, optionally, HA's SmartThings integration. Revised work items:
  - **18j. UPnP volume/mute — DONE** (already shipped: `aiosamstream.upnp` RenderingControl, real `volume_level` / `is_volume_muted`, `volume_set` / `mute_volume`, key fallback). Original notes: The TV's DLNA renderer (`http://<tv>:9197/dmr`, found via SSDP `urn:schemas-upnp-org:device:MediaRenderer:1`) exposes `RenderingControl` (`/upnp/control/RenderingControl1`: `GetVolume`, `SetVolume`, `GetMute`, `SetMute`, InstanceID 0, Channel `Master`). Add an async SOAP client in `aiosamstream` (`upnp.py`), resolve the control URL from the device description each session, poll in the coordinator while the TV is on, and give `media_player` **real `volume_level` + `is_volume_muted`** plus `volume_set` / `mute_volume` (instead of key-press up/down only). Fall back to keys when UPnP is unreachable. **Verify:** HA shows the TV's actual volume number; setting 25 in HA moves the TV to 25; mute state follows the remote.
  - **18k. OCF diagnostic sensors (when OCF is owned).** Read-only resources that answer 2.05 locally, mapped to disabled-by-default diagnostic entities: firmware version (`/oic/p` `mnfv`, e.g. `T-OSCPCUABC-0090-2220.4`; the REST API reports `firmwareVersion: "Unknown"`) and build date (`/sec/provisioninginfo` `firmwareversion` `;25.04.22`); Wi-Fi signal/channel/band (`/sec/accesspointlist` entry whose `macAddress` matches the BSSID the REST API reports in `device.ssid`: `rssi`, `channel`, `frequency`); MAC addresses and feature flags (`/DevConfResURI`: `WOWLAN`, `BTWAKEUP`, `BTHIDPOWERON`, `DLNADMR`); partial serial / SmartThings agent version (`/sec/provisioninginfo` `deviceinfo`); "Local access: owned" from `/oic/sec/doxm`. Refresh slowly (e.g. every 10 min; Wi-Fi signal every 1 min). **Verify:** sensors populate after onboarding and survive a TV power cycle (dynamic port re-discovery).
  - **18l. OCF commands with real IDs.** Use the IDs the SmartThings export shows for this TV family as POST payload values: inputs (`dtv`, `HDMI1`… from `supportedInputSourcesMap`), picture modes (`modeGen_589826`…), sound modes (`modeAmplify`, `modeStandard`). Confirm each payload key on the QN800C (POST executes but answers 4.00, so verify by eye / by the UPnP or REST side effect), then expose `select_source` by real name, picture-mode and sound-mode `select` entities (write-only: the current mode can't be read locally, so they act as buttons/options without a state, or use SmartThings state when available). **Verify:** selecting HDMI1 / a picture mode from HA changes the TV.
  - **18m. Optional SmartThings-cloud state source.** When the user also has HA's SmartThings integration for this TV, read its entities for the state local paths can't give (current input, picture/sound mode, channel, now-playing). Gate: present → use; absent → those fields stay `None`. **Conflict:** local OCF ownership and SmartThings registration are mutually exclusive on the TV (verified 2026-10-22: SmartThings takes local ownership with its vendor OTM; while we own it the TV is hidden from the app), so the user picks **one**: local OCF (commands + diagnostics) *or* SmartThings (cloud state). The setup UX (milestone 22) explains the trade.
  - **18n. Pure-Python onboarding, LAN-run — DONE (2026-10-27).** `dtls_tunnel.c` is replaced by a from-scratch
    DTLS 1.2 ECDHE-PSK client on `cryptography` (`aiosamstream/ocf/dtls.py`; binary PSK identity + owner-PSK
    derivation, no C compiler, no new deps). `aiosamstream/ocf/onboard.py` folds the old `oicseek` scripts
    (discover → trigger PIN → Random-PIN ownership → install CA/ACE/cis → release) into one driver.
    **Onboarding is in-HA-first with a LAN fallback.** The connect step probes whether HA can reach the TV over
    UDP: if it can, it shows **"enter the 8-digit PIN"** and HA does ownership + cloud-pointing itself (seamless);
    if it can't (HA in a bridge-networked Docker container — multicast/CoAP are NAT'd, proven: no UDP path at all,
    not even known-port DTLS), it falls back to the **LAN helper** — `samstream-onboard.pyz` (+ Windows `.cmd`), built by HA with the
    settings baked in and offered as signed download links — run on a computer on the TV's LAN, which prints a
    credential the user pastes back so HA can later release the TV (`pstat cm:1`). Local control can be set up
    **during first-time setup**: ticking it on `local_offer` runs the same connect/PIN/wait screens before the
    entry exists (the cloud holds the TV under the flow id; the new entry adopts the connection). The
    options flow: intro → settings (turns local control on, cloud starts) → connect (PIN or LAN) → wait for dial-in
    → paired → troubleshooting → release. The initial config flow also **offers local control right after pairing**
    (`local_offer` step). Animations: new `connect` (Wake-on-LAN toggle) on the "Connect your Samsung TV" step and
    the offer; `pairing` on the PIN step; `paired` on success; `loading` while waiting. See
    `docs/ocf-local-protocol.md §11`. Crypto has unit tests (PRF/owner-PSK/CBC); the flows are tested with the
    dial-in mocked (both PIN and LAN modes); the DTLS handshake, an authenticated owner read, and the release are
    **verified live against the lab TV** from a LAN host.
- **Pitfalls (added to section 5):**
  | Area | Risk | Mitigation |
  |---|---|---|
  | OCF port | `p.port` changes every power cycle | Re-discover the secure port each session; never cache across power states |
  | OCF session | Standby/sleep drops the DTLS-PSK session | Reconnect with backoff; treat unreachable as "fall back to REST", never fail the coordinator update |
  | Ownership | A write to the TV; a factory reset clears it; one owner credential per onboarding | Explicit user action only; safe re-onboarding; document coexistence with the SmartThings cloud app (verify on the TV) |
  | Deps | DTLS/CoAP/CBOR all need to run on HA's Python/arch | Done in pure Python on `cryptography` (already a dep); no `python-mbedtls`, no compiled helper |

### Roadmap addition (2026-10-22): Frame Art Mode, ideas from ollo69/ha-samsungtv-smart
Researched ollo69/ha-samsungtv-smart for features we lack. Its `set_art_mode` only *toggles* art (no artwork choice); `select_picture_mode`/`select_sound_mode` and channel/source extras are **cloud SmartThings**. See [[samstream-frame-art-findings]].

- **19. Frame Art Mode.**
  - **19a. Local toggle — DONE (2026-10-22, lab Frame QA55LS03DAUXEG @ .22).** New `samstream.art_mode` action toggles a Frame between normal TV and Art Mode via `KEY_POWER` (confirmed by eye; never fully powers off). `aiosamstream` gained an **async art-app client** (`art.py`: `ArtConnection` + `SamsungTV.art()/get_art_mode()/set_art_mode()/art_list()/toggle_art_mode()`) and a `python -m aiosamstream art` probe. 8 lib tests + a service test; ruff/mypy clean.
  - **Hard limit found on the 2024 Frame:** the `com.samsung.art-app` channel is dead locally — ignores every request (status/list/set/select), no replies, no pushes, in both TV and Art states (reference `samsungtvws` 3.0.6 hangs the same way). REST `PowerState` is `"on"` in both modes, so there is **no local art-state readback** and **no local artwork selection**. The async client is kept because it is correct for Frames whose channel *is* live (older / account-linked).
  - **19b. SmartThings/OCF art control (planned).** Selecting artwork, brightness, matte, and reliable on/off + state readback need either **cloud SmartThings** (as ollo69/TheFab21 and HA core do) or the **local-OCF** path (milestone 18) if it exposes the art resources. Deliver as: `set_art_mode` with `on/off` + `artwork` (state-aware, so on/off is deterministic), a browsable **Art** folder in the media browser (thumbnail grid → `select_image`), brightness, and an art-mode binary sensor. Gate it like Developer Mode / local-OCF: absent → the KEY_POWER toggle remains the only control. **Verify:** pick an artwork from HA and see it on the Frame; art-mode sensor tracks state.
  - **19b — art picking DONE (2026-10-30, verified on the Frame @ .22).** The art-app channel answers on this Frame now (listing 12 works, `select_image` works, uploads work). Added `samstream.select_art` (content_id) and `samstream.list_art` (returns content ids, size, category and a signed 24 h thumbnail link `/api/samstream/art/<entry>/<id>`; thumbnails fetched via `get_thumbnail_list` sockets, 16 per trip, cached in memory, one retry when the socket drops while the art app wakes). Media browser gets an **Art** folder (thumbnail grid; play = show). Still open: brightness, matte, art-mode sensor from the art channel.
  - **Notifications (2026-10-30):** a `notify` entity per TV, so `notify.send_message` (title + message) shows on screen for 10 s and returns. The TV exposes no native toast: none of its 99 OCF resources is a notification, and ollo69 issue #106 found none either (SmartThings `execute` = a raw OCF request, already available as `samstream.local_control_request`).
  - **19c — BUILT (2026-10-27), needs on-device verify:** Configure → TV app shows *Turning the Frame off: Art Mode / Fully off* on Frames only (`FrameTVSupport` → `DeviceInfo.frame_tv`); *Fully off* holds KEY_POWER 3 s (`power_off(full=True)`). Also fixed: the verified turn-off no longer retries on a Frame (it reports "on" in Art Mode, so a retry flipped it back to TV). Original idea: optional setting so a power action goes to Art Mode instead of standby (ollo69 has this). Trivial once 19a/19b exist.

- **20. Cast a URL / YouTube — app-driven (2026-10-22). Built; needs on-device verify.** Goal: YouTube link → YouTube app; other URL → the TV browser. See [[samstream-cast-findings]].
  - **Why direct launch failed on the QN800C:** the remote-channel launch with a payload does nothing (neither `org.tizen.browser`+url nor a YouTube deep link), and DIAL (`:8080/ws/apps/YouTube`, needs `Origin: package:com.google.android.youtube` → 403 vs 200) only triggered a stuck **Multi View**, not playback — a bare `v=` cast no longer plays (that needs the YouTube **Lounge** protocol). Those direct-launch primitives were removed.
  - **Chosen route — launch from inside the Samstream app.** The app is privileged (`application.launch`), so Tizen **`launchAppControl`** opens apps where the remote channel cannot. HA delivers `{"action":"open", youtube|url}` over the existing `/session` pull (the path cameras already use); the TV app calls `launchAppControl(view, uri)` — forcing the YouTube app for a YouTube id, else letting the TV pick its browser — then drops to the background.
  - **Implemented:** `samstream.open_url` action (`url`), `media_player.async_open_url` (classifies via `aiosamstream.youtube_id`, delivers with `set_command`, no camera-return tracking); TV app `parseOpen` + `App.openExternal` + `main.ts` `open` dispatch + Tizen types (TV app **0.10.0**); `cast.py` `youtube_id()`. Tests: lib parser (9), TV app `parseOpen` (3), HA service test; lib ruff/mypy clean, TV app typecheck + 37 tests + build; HA tests pending CI.
  - **Verified on the TV (app 0.10.0):** a web URL opens the **browser**; a YouTube link **launches the YouTube app but to its home page — it does not play the video** (the Tizen app ignores the deep-link URI, same as DIAL). So `open_url` ships as web→browser and youtube→opens-the-app. **Playing a chosen YouTube video needs the YouTube Lounge protocol (milestone 20b).**
  - **20b. YouTube Lounge (play a specific video) — DONE (2026-10-22, verified playing on the QN800C).** A small vendored Lounge client in `aiosamstream` (`lounge.py`, no `pyytlounge` dep): `SamsungTV.cast_youtube(video_id)`; `media_player.async_open_url` routes a YouTube link to it (HA-side, no TV app). `samstream.open_url` now **plays the exact video**. 6 lib tests (bind parsing + mocked flow), ruff/mypy clean. Flow verified against the QN800C:
    1. **Launch + screenId:** `POST http://<tv>:8080/ws/apps/YouTube` (empty body, header `Origin: package:com.google.android.youtube`) → 201; then GET the same URL **while running** — the `additionalData` now includes `<screenId>…</screenId>` (and `theme`, `deviceId`). (When stopped it only shows `yumi`/`oisi`/`passiveSessionId`, no screenId.)
    2. **Lounge token:** `POST https://www.youtube.com/api/lounge/pairing/get_lounge_token_batch` form `screen_ids=<screenId>` → `screens[0].loungeToken`.
    3. **Bind:** `POST https://www.youtube.com/api/lounge/bc/bind?RID=1&VER=8&CVER=1&auth_failure_option=send_error` form `{app:web, mdx-version:3, id:<screenId>, device:REMOTE_CONTROL, ui:false, theme:cl, loungeIdToken:<token>, capabilities:"que,dsdtr,atp,vsp", magnaKey:cloudPairedDevice, name:Samstream}`. Response = length-prefixed chunks of `[[id,[type,…]]]`; event `"c"` → SID, event `"S"` → gsessionid, max id → AID.
    4. **Play:** `POST …/bc/bind` with query `{name, loungeIdToken, SID, gsessionid, AID, device:REMOTE_CONTROL, app:web, VER:8, v:2, RID:<next>}` and form `{count:1, ofs:0, req0__sc:setPlaylist, req0_videoId:<id>, req0_currentTime:0, req0_listId:""}`.
    Needs internet from HA (youtube.com). Still TODO: confirm exact RID/ofs increments (casttube source 404'd on fetch — re-find a current reference or test live). `open_url` meanwhile ships as web→browser and youtube→opens-the-app.

- **21. Multi View (lead, not yet pursued).** The milestone-20 DIAL cast unexpectedly triggered **Multi View** on the QN800C (left app + a content picker: Live TV, Browser, SmartView, Samsung TV Plus, USB/phone camera, rearrangeable). This contradicts the earlier "Multi View: no API" note (milestone 17/README) — it *can* be triggered externally. Worth investigating whether it can be opened/arranged on purpose (e.g. camera beside Live TV), which would be a better PiP than the TV-Window corner.
### Roadmap addition (2026-10-22): guided first-run setup (the very last milestone)
- **22. Guided setup UX — do this LAST, after every feature above is implemented**, so the guide covers the final feature set (Developer Mode install, per-user signing, local OCF onboarding, SmartThings options).
  - **Goal:** someone who has never heard of Developer Mode, certificates or OCF gets from "add integration" to a working TV without leaving HA or reading docs.
  - **One flow, TV and HA in step:** the config flow drives each step, and right after the bundled app is installed it **opens the Samstream app on the TV**. From then on the TV screen shows the matching instruction for each HA step (Arabic RTL too), e.g.:
    - "Allow the connection on the TV" (token popup) — the TV says *which* button to press;
    - "Developer Mode: open Apps, type 12345, set the HA IP …" with the HA IP pre-filled on screen;
    - "**A PIN will appear on this screen now — type it into Home Assistant**" before the local-OCF onboarding triggers it (and a retry if it expires);
    - Samsung account sign-in for the signing cert, with a QR code to finish on the phone.
  - **HA side:** each step shows what is happening, progress, a clear error with a fix, and "retry this step" — never restart the whole flow. Optional steps (Developer Mode, local OCF, SmartThings) can be skipped and enabled later from the options flow.
  - **Animated intro before the first step (added 2026-10-23).** The first screens of "Add integration" are a short animated walkthrough (Lottie/SVG, Arabic RTL, skippable) showing what Samstream does: cameras and messages on the TV, the remote, apps. Then one card per **optional capability**, each with what you **gain** and what you **give up**, and a toggle:
    - **Developer Mode** — gain: the Samstream TV app (cameras, full-screen messages, video from HA's media library), the full installed-app list. Give up: nothing functional; the TV shows Developer Mode is on, and the HA IP is stored in it. Needs: typing 12345 in Apps and the HA IP (shown pre-filled).
    - **Local control (OCF)** — gain: reliable input selection by name, picture/sound mode, power off, diagnostics (real firmware version, Wi-Fi signal), all local. Give up: **SmartThings control of this TV** — the TV can belong to only one of them; while Samstream owns it, the SmartThings app can't find or control it (it can be released any time from Samstream's options, no reset needed). Needs: an on-screen PIN typed into HA; if the TV was set up through SmartThings before, the Wi-Fi password may be asked.
    - **SmartThings (instead of local OCF)** — gain: live state the TV only shares with Samsung's cloud (current input, picture/sound mode, channel, what's playing). Give up: needs internet and a Samsung account; slower updates; local OCF stays off.
    - **UPnP volume/mute** — always on when reachable; no choice needed, shown as a "you also get" line.
  - **Local control (OCF) steps in the guide (added 2026-10-27; built with OCF, last).** The guide walks the
    local-cloud method from `docs/ocf-local-protocol.md` §14.7 one screen at a time, each with a check, a
    clear failure message and "retry this step":
    1. **Reachability check:** HA must accept the TV's connection on TCP 5684. HA OS/supervised: nothing
       to do. **Docker:** the guide shows the exact `ports: - "5684:5684"` line for docker-compose (or
       `network_mode: host`) and waits until a test connection succeeds.
    2. **Wake the TV** (WoL + "keep it on" note): the PIN and the secure port rotate when it idles.
    3. **PIN:** HA asks the TV to show its 8-digit PIN; the Samstream TV app first says "a PIN will appear
       now"; the user types it into HA (timeout → "show a new PIN").
    4. **Pair + point the TV at HA:** ownership, HA's certificate as trusted, the access entry, and the
       cloud address — shown as a checklist that ticks off live.
    5. **If the TV refuses the cloud address** (EasySetup not at the Wi-Fi step, typical after a TV restart
       or a SmartThings setup): the one-time phone dance — release, add the TV in the SmartThings app,
       delete it there, then back to step 3. Explained with pictures; skippable.
    6. **Confirm:** "The TV is connected to Home Assistant" once it dials in and the first live state
       (input, app, volume) shows on screen.
    7. **Trade-off reminder + release:** while local control is on, SmartThings can't see the TV;
       Options → "Release local control" gives it back without a reset.
  - **OCF onboarding robustness fix (2026-11-03, user hit it):** the PIN appeared ~30-40 s late and setup kept
    dropping to the LAN helper. Root causes + fixes: (a) `local_control_connect` ran the slow `discover`
    (unicast ×3 + multicast, up to ~24 s) BEFORE `trigger_pin`, so the PIN only fired at the end — **reordered to
    trigger the PIN first** (shows in ~1 s; it also proves reachability, so discovery no longer waits on flaky
    retries); (b) `_plain_request` parsed any datagram that arrived without matching it to the request, so a stray/
    retransmitted packet raised `CoapError` that escaped uncaught (crashing the step or forcing LAN) — **now caught →
    `None`**; (c) `trigger_pin` broke out on the first non-success reply — **now retries the `oxmsel` POST 3× and only
    then reads the owned-state**, so a one-off bad datagram is absorbed. Verified: a raw probe from the HA container
    showed the POST returns 2.04 and the DOXM GET parses (owned=false) when the TV is answering. **Caveat (TV state,
    not code):** the TV answers plain CoAP on 5683 only while awake and in its provisioning window — it idles and goes
    silent (hence step 2 wakes it and every step has retry). Tests: `lib/.../test_onboard.py` (PIN retry),
    `tests/test_local_control.py` (unreachable surfaces at the trigger).
  - **Port 5684 detection (built with OCF, last).** The integration installs via HACS on any HA, so at
    enable time it finds out whether the TV can reach HA on TCP 5684, and says exactly how to open it:
    - Read `installation_type` from `homeassistant.helpers.system_info.async_get_system_info`:
      *Home Assistant OS* / *Supervised* (core runs with host networking → port reachable as is),
      *Container* (Docker: may be bridged), *Core* (venv: host firewall only).
    - Probe: bind 5684 (or report "in use by …"); then connect from HA to `<HA LAN IP>:5684` — success
      means it is reachable from the LAN; finally confirm with the TV's own dial-in.
    - Container + probe failed → show the fix: compose `ports: - "5684:5684"` (or `network_mode: host`)
      or `docker run -p 5684:5684`, then recreate the container. Docker Desktop (Windows/macOS) also needs
      the host firewall to allow 5684. Core → open 5684 in the OS firewall. Port taken → offer another
      port (the cloud address written to the TV carries the port).
    - The user's existing laptop-based local SmartThings control (the oicseek cloud on 192.168.1.21) is
      what the integration takes over when enabled: the guide re-points the TV's cloud address to HA.
  - **Animations:** intro and step illustrations are made as **Lottie** (LottieFiles Creator in the
    browser, or After Effects + Bodymovin). The TV app plays them with `lottie-web` (SVG renderer; works on
    Chromium 56 — Rive does not, it needs WebAssembly). HA's config flow only renders markdown, so there
    the same animations ship as **animated WebP/SVG images** exported from the Lottie; a full interactive
    intro would need a small custom panel.
  - **Plain-language trade-offs everywhere:** the summary at the end lists, per capability, "on/off", what it gives, and how to change it later (options flow), so nothing is a one-way door.
  - **Finish:** a "Samstream is ready" screen on the TV (test camera / message buttons) and a summary in HA of which capabilities are on.
  - **Verify:** a fresh TV (factory reset) to working setup in one sitting with no docs; every step recoverable after a wrong action or a timeout.


Milestone X: Bixby-to-Home-Assistant Voice Bridge (Automation Studio Capsule)
Objective: Enable TV users to trigger Home Assistant automations via the Samsung remote control's microphone button using Bixby as the voice-intent frontend, while keeping HA as the execution backend.

Core Architecture:

Bixby (TV System) → Receives mic input, performs STT and intent parsing.

Automation Studio Capsule → Samsung's official cloud tool. Acts as a "shell" that forwards the parsed intent via HTTP.

Home Assistant Webhook/API → Receives the HTTP request and executes the automation.

Key Implementation Steps:

Create a Flow in Automation Studio: Include a "Capsule label" node and a "Capsule result" node.

Add an HTTP Request Node: Point it to an HA Webhook endpoint (e.g., https://<ha_url>/api/webhook/bixby_trigger).

Configure HA Automation: Create a webhook-triggered automation that listens for the request and executes the intended actions (e.g., calling OCF local control for lights or TV).

Packaging: Publish the Capsule to the Bixby Developer Center (or keep it private for testing).

User Experience: The user says, "Ask [Capsule Name] to turn all lights on" → Bixby recognizes the phrase → Capsule fires HTTP request → HA executes and returns a result → TV shows confirmation via the Capsule result node.

Constraints & Technical Boundaries (CRITICAL):

No Raw Audio: HA receives only the parsed intent/parameters, not the voice stream. HA's Assist pipeline (STT/NLU) is bypassed entirely.

Bixby Grammar Required: Users must use Bixby's invocation syntax (e.g., "Ask [Name] to..."). Natural language processing is handled by Bixby, not HA.

System-Level Limitation: This does not "replace" Bixby or hijack the mic button. It is an official, supported "bridge" that turns Bixby into a remote trigger for HA.

Deliverables:

□ Functional Automation Studio Capsule (private/test version).
□ HA Webhook endpoint and example automation.
□ Custom Bixby grammar for the Capsule ( for example xhoose the name after launching bixpy by user "Ask Home assitant X" or user can make it  "Ask Garvis X"  ").
□ Documentation for users on how to invoke the Capsule and configure the Webhook.
□ (Optional) Public Bixby Capsule submission for seamless installation.
□ Investigate the possibility of replacing bixpy entirely and passing raw audio to Home assitant


Voice bridge research results (2026-10-27)
- **Bixby capsules cannot run on a TV.** Capsule targets are `bixby-mobile`, `bixby-watch` and
  `bixby-fridge` (public submission US/KR only); on-device testing is phone-only; no Arabic. A capsule is
  still possible **on the phone** ("Hi Bixby, ask Home Assistant to …"): Bixby Developer Studio 8.x,
  `capsule.bxb` + an action model + `endpoints.bxb` with a `remote-endpoint` (or JS `http.postUrl`) to a
  **publicly reachable** URL (Nabu Casa / reverse proxy) → the Samstream voice webhook below. Private
  submission + revision ID / QR code on the phone for testing.
- **Google Assistant / Alexa on Samsung TVs** were system-level partner integrations (Settings > General >
  Voice > Voice Assistant), not an SDK. Google Assistant was removed from Samsung TVs; **Alexa built-in**
  remains on many models/markets — where offered, HA's Alexa integration (Nabu Casa) makes "Alexa, turn on
  the kitchen lights" work from the TV remote's mic with no Samstream code. Check the menu on each TV.
- **TV-native path (most promising): Samsung's VoiceInteraction API** (`webapis.voiceinteraction`, public
  privilege `http://developer.samsung.com/privilege/voicecontrol`, Tizen 6+). While the Samstream app is in
  front, the TV's assistant delivers utterances to the app: `ontitleselection(title)` receives the free
  text of "Select <words>", and `onrequestcontentcontext()` lets the app list on-screen items (title +
  aliases) to pick by voice. Plan: a Samstream "voice" screen that forwards that text to the HA voice
  endpoint (→ Assist) and shows the reply. **Verify on the QN800C:** "Select kitchen lights" reaches the
  app as text.
- **HA side (built 2026-10-27):** a per-TV voice webhook (Configure → Voice bridge) that runs the text
  through HA Assist, fires a `samstream_voice` event for automations, answers `{speech}` and can show the
  reply on that TV.

Milestone X: Research and Alternative Testing for Now Brief / Daily Board Screens
Background and Conclusion
The "Good Morning" screen you see, with three cards (including SmartThings data), is a feature called Now Brief (2024+ models) or Daily Board. It automatically activates when the TV detects a user approaching, and displays weather, memos, SmartThings device status, and other information. This is a system-level UI rendered by the Tizen system, not an OCF resource, so your local OCF control cannot inject content into it or replace it.

Research Objectives (Three Directions)

Direction 1: Verify Whether the System Screen Can Be Disabled

In the TV settings, find the "Now Brief" option under Settings > All Settings > Advanced Features (or General > Privacy on some models), and turn off "Enable with User Detection".

Test Objective: Confirm whether disabling this option completely prevents the screen from appearing when someone approaches, providing a "clean slate" for HA to trigger Samstream.

Direction 2: Verify Whether External Presence Detection + HA Trigger Can Replace It

Use a PIR sensor or Hikvision camera motion detection (already integrated into HA) to detect "someone in the room."

Test Process: HA automation triggers → determine TV status → if TV is off/asleep, wake TV and launch Samstream; if TV is on, decide whether to interrupt based on conditions.

Key Verification Point: After disabling the system Now Brief, whether Samstream can reliably occupy the screen when someone approaches, rather than Samsung's native UI.

Direction 3: Investigate the Feasibility of Daily Board SDK (Long-term)

Samsung's SDC24 introduced the Daily Board SDK for "selected partners" to add widgets. These widgets can display weather, SmartThings status, etc., and activate when the TV detects a user.

Important Limitation: This SDK is not open to ordinary third-party developers; it is a partner program. You need to investigate whether Samsung has a public application channel, or whether a similar effect can be achieved through some form of "widget JSON configuration".

Expected Outcome: If a channel exists, Samstream or HA data could potentially be displayed as a widget on the Daily Board screen. If no channel exists, this direction can be closed.

Deliverables

□ Document the location and effect of Now Brief / Daily Board settings (with screenshots).
□ Record the reliability test results of HA external presence detection + Samstream trigger (success rate, latency, failure scenarios).
□ Investigate the Daily Board SDK partner entry (whether public application is possible, required qualifications), and provide a conclusion.
Dependencies

Now Brief / Daily Board screen has been confirmed to exist on your TV model.

HA presence detection sensors are available (PIR or camera motion).

Samstream app is already installed and can be launched via HA.

### Roadmap addition (2026-10-27): security review (the FINAL step, after OCF and the guided setup)
- **23. Security review of the whole integration against `CLAUDE.md` (project security rules).** Done
  last, so it covers every feature. Each rule is checked and the result recorded here (pass / fixed /
  not applicable, with the file it concerns). Applied to Samstream:
  - **Secrets:** no tokens, certificates, `.p12`, camera URLs/credentials, owner PSKs or cloud keys in
    the repo, the TV app bundle (`tv-app/src`, built `bundled/`), the Lovelace card or logs; everything
    secret lives in config entries / `.storage`. Re-run the git-history secret scan; confirm
    `.gitignore` covers `.env*`, `*.key`, `*.p12`, `oicseek/tv_cred*.json`, `tv_state*.json`.
  - **Authentication on every HTTP view:** list every `HomeAssistantView` and webhook. Views the TV calls
    (`/api/samstream/tv/{secret}/…`: session, stream, MJPEG, settings) must reject a wrong secret with
    401/404 *before* any work, compare secrets in constant time (`hmac.compare_digest`), and only serve
    the stream belonging to that TV (resource ownership). The sign-in hand-off view and the
    frontend/card views get the same check. The voice webhook is a capability URL (64 hex chars,
    `secrets.token_hex(32)`), POST only, input length-limited.
  - **Rate limiting:** brute-force protection on the TV-secret views and the voice webhook (HA's
    `ip_ban`/login-attempt handling or a per-IP counter); don't trust `X-Forwarded-For` unless HA's
    `trusted_proxies` says so.
  - **Input validation server-side:** every action schema (voluptuous), every TV-sent JSON body,
    OCF/CoAP/CBOR parsing (length checks, no unbounded allocations), sdb packets, the voice text.
    No `pickle`/`eval` anywhere; JSON only.
  - **SSRF:** `play_stream url`, `open_url`, sound/media URLs and the cast path fetch user-supplied URLs —
    decide per action (admin-only HA actions are trusted input) and document; any URL the TV app fetches
    must stay http/https.
  - **Output / XSS:** the TV app and the card never use `innerHTML` with message text, titles, app names
    or Assist replies (use `textContent` / Lit templates); check the overlay and RTL code paths.
  - **Errors:** HTTP views and the webhook return generic messages; details only in HA logs; no stack
    traces or file paths to the TV or callers.
  - **Production exposure:** no source maps in the shipped TV app or card (`build.sourcemap: false`);
    no debug endpoints; the bundled `.wgt` holds no developer certificates.
  - **Network services:** the local OCF cloud (TCP 5684) only talks to TVs that present the expected
    identity, binds where documented, and is off unless OCF is enabled.
  - **Dependencies:** exact pins where the project pins (npm lock files committed, `aiosamstream`
    requirements bounded), and `pip-audit`/`npm audit` clean.
  - **Verify:** a written checklist in this file with every item ticked, and the security scan
    (`/security-review`) run on the final branch with no open findings.

### OCF build order (2026-10-27, started)
- **Runtime = HA runs the OCF cloud (TCP 5684, CoAP over TLS, RFC 8323).** Python's `ssl` and asyncio are enough, with no DTLS at runtime. Port `oicseek/cloud_server.py` into `aiosamstream.ocf`: framing, CBOR (`oicseek/lib_draft/cbor.py`), sign-up/sign-in/ping/rd handlers, per-TV session with GET/OBSERVE plus POST.
- **State parsers** from the captured bodies: `contentinfo` (input/title/app id), `inputsource` (supportedModes/currentMode), `audio` (volume/mute), `switch/binary`, `channel`, `mode/picture`, `mode/sound`, `mediaOutput`, `networkinfo` (rssi/ch). Picture/sound mode names come back in the TV's language (Arabic), so decode the bytes as UTF-8 properly.
- **Identity:** the CA and the end-entity cert (CN = cloud UUID, SAN = HA IP) live in HA `.storage`. Import the existing laptop identity (`oicseek/ca.key`, cloud UUID) so only `cis` has to be re-pointed at HA.
- **Onboarding:** pointing the TV at HA still needs the DTLS owner session (the oicseek tools on a PC) until a supported DTLS path exists.
- **Not yet verified:** commands (POST) over the cloud channel.
- **Privacy:** `/sec/tv/appdata/ssoservice` carries the Samsung account email. Never log it or store it, and redact it in diagnostics.

### Roadmap addition (2026-10-30): Quick Settings channel and a native TV alert (both before 22 and 23)
Found by logging the SmartThings TV plugin (WEBTVPlugin 4.IR02.0922) over adb. The plugin talks to the TV **locally**, over the same `wss://<tv>:8002/api/v2/channels/<id>` websocket we use for art.

- **19d. Quick Settings over `com.samsung.tv.mobilebff`.**
  - **Message shape:** each message is an `ms.channel.emit` with event `/sec/tv/appdata/mobilebff`. Its data is a JSON string `{"version":"0.2","id":"<cmd>","seqId":"..","lastUpdated":"","params":{..},"timeout":10000}`, and the reply carries `statusCode:"100"`.
  - **Verified from the laptop (Frame @ .22):** `get.system.info.bool`, and `get.settings.data`, which returns the whole Quick Settings menu: Picture Mode, Sound Mode, Sound Output, Game Mode (Off/On/Auto), Subtitle, Sleep Timer (Off/30/60/120/180), AI Mode, Energy Saving, Multi View, Brightness (25/50). Each entry has title, subTitle, the current index, and per-choice ids like `s/setting.layer.gamemode@On` with `actionType` toggle/list and `dim` (greyed out). The TV also pushes `event.setting.update` whenever a setting changes.
  - **Still to capture:** the **write** command. Use adb logcat of the SmartThings plugin while changing Sleep Timer, Game Mode, Sound Mode and Subtitle from the phone. Do not pin `-s ip:port`, because the wireless-debugging port changes on reconnect.
  - **Deliver:** `select` entities (picture mode, sound mode, game mode, sleep timer, sound output), switches (energy saving, AI mode), a subtitle select, and a brightness number. Each entity is created only if the TV lists that setting, and is unavailable while `dim` is true.
  - **Verify:** change each one from HA and see it on the TV. Change it on the TV and see HA update from the push.
- **19e. Native TV alert through the TV's SmartThings Hub (Matter) — DROPPED 2026-11-03 (user).** Superseded by
  the sideloaded **.NET notifier** (24a–d), which does better: a native Samsung popup with a chime **and our own
  custom text**, overlaid on whatever is playing, fully local, no phone and no SmartThings pairing. The Matter
  leak-sensor route only ever gave a fixed device-name title. Removed from scope; kept here for history only.
  - ~~The idea: Samsung TVs show a native popup with a chime when a SmartThings doorbell rings. The TV's built-in
    SmartThings Hub is a Matter controller. HA exposes a virtual doorbell to that hub through a Matter bridge, and
    `notify` presses it. The popup text is Samsung's, not ours.~~
- **Not usable as a notification:** the SmartThings "this TV needs reset" popup. That is OCF Easy Setup `sendResetProvisioningInfo` (native code in the app), sent when the TV belongs to another account. Pressing OK on the TV drops its owner. It goes in the guided setup (22) as the way to hand the TV back, never as an alert. Routine "Notify" actions only reach members' phones.

### ★ BREAKTHROUGH (2026-11-03): a sideloaded .NET app posts a native custom-text notification (with chime) — the "dead end" below is OVERTURNED for the .NET path
The 2026-11-02 verdict only closed the **web-app** route. A minimal **Tizen.NET** app (`tv-app/noti-probe-dotnet/`) calling `Tizen.Applications.Notifications.NotificationManager.Post(new Notification{Title,Content})` — privilege `http://tizen.org/privilege/notification` (public level), signed with HA's Samsung cert — **rendered a native Samsung notification in the upper-right WITH a chime and our own text** on the QN800C (Tizen 9), confirmed on screen by the user. So `feature/notification=false` gates only the **web** `tizen.notification` API; the **.NET** `NotificationManager` path is not gated and works for a public-cert app. This gives LOCAL + NATIVE + CUSTOM-TEXT notifications without Matter and without the platform-only `iot-service-notification-v2`.
- **Build/sign/install that worked:** .NET SDK 10 only (no workload); enable a NuGet source first (`dotnet nuget add source https://api.nuget.org/v3/index.json`), then `<Project Sdk="Tizen.NET.Sdk">` + `global.json` pin `Tizen.NET.Sdk 1.2.1` + TFM `tizen40` + `Tizen.NET 6.0.0.14995` → `dotnet build -c Release` emits a `.tpk`. A `.tpk` signs exactly like a `.wgt` (`aiosamstream.signing.sign_wgt` after stripping the default signatures); HA's distributor cert covers both TV DUIDs. Install via `tizen install`, launch via `sdb shell app_launcher`. Retail sdb blocks shell stdout / pull / dlog, so the probe painted its result on screen. See [[samstream-tv-notifications]].
- **New milestone — 16/19 revision: ship a `.NET` "notifier" companion app. FULL PATH PROVEN 2026-11-03.** `tv-app/notifier-dotnet` is a Tizen.NET UI app that starts an HTTP listener on `:8181` and stays resident; `GET http://<tv-ip>:8181/?title=..&content=..` makes it call `NotificationManager.Post`, and the native notification **overlays the foreground app** (confirmed over YouTube, video uninterrupted, chime + both text fields). So HA fires a TV notification with a plain HTTP GET — local, native, custom-text, non-interrupting. This is the PRIMARY notification route; Matter leak-sensor (19f) demotes to a no-sideload fallback.
  - **Gotchas proven:** the NUI drain `Timer` must be a retained field (a local gets GC'd → silently stops → "HTTP 200 but no notification"); `sdb app_launcher` can't start/trigger a sideloaded app here (queues + floods on manual open) so the app must start in-system (on-boot / user / another app's launchAppControl); NUI UI text only updates on the main thread.
  - Build/sign/install recipe + the breakthrough details in [[samstream-tv-notifications]]. Starting point = `tv-app/notifier-dotnet` (the proven HTTP notifier).

### Milestone 25 (user request, 2026-11-03): uninstall the TV apps from HA configuration
- **Goal:** from HA (options flow + a button/service), **uninstall the apps Samstream installed on the TV**
  — the web app (`SmStrm0001.Samstream`) and the notifier (`org.samstream.notifier`) — so the user can cleanly
  remove Samstream from the TV without a PC or sdb tooling. Natural cleanup counterpart to the install path, and
  needed because the two-package design means two apps to remove.
- **Mechanism:** `aiosamstream`'s sdb client already does `sdb.uninstall(app_id)` (used in installer.py's
  author-mismatch reinstall). Add `async_uninstall_package(app_id)` + a service `samstream.uninstall_app` and/or an
  options-flow step "Remove Samstream from the TV" that uninstalls both apps (confirm first), with a repairs/notice
  on success. Also offer it when the integration/entry is removed (best-effort, non-blocking). Gate behind sdb being
  reachable (Developer Mode on); clear error if not.
- **DONE (2026-11-03, needs on-device verify).** `installer.async_uninstall_package(hass, entry)` removes BOTH apps
  (`SAMSTREAM_APP_IDS = (SmStrm0001.Samstream, org.samstream.notifier)`) in one sdb session via `sdb.uninstall`;
  best-effort per app (an app that is already gone — `"was get app info failed"` — is skipped, not an error, so the
  other still comes off), returns the list actually removed, then `async_rescan_apps`. Reuses `_sdb` so an
  unreachable TV raises the same Developer-Mode repair issue the install path uses, and reuses `coordinator.installing`
  so install and uninstall can't overlap. Exposed as the `samstream.uninstall_app` **service** (media_player
  `async_uninstall_app` → response `{"removed": [...]}`), registered in `__init__.py`, with `services.yaml` +
  `strings.json` text ("Remove Samstream from the TV"). Chose a deliberate service over a one-tap button for a
  destructive action; an options-flow "remove" step and the on-entry-removal hook remain optional follow-ups. Tests:
  `test_installer.py` (removes both, skips an absent app, requires sdb).
- **Verify — DONE (2026-11-03, QN800C):** `samstream.uninstall_app` from HA removed both (`removed: [SmStrm0001.Samstream, org.samstream.notifier]`); a follow-up `install_app` reinstalled both cleanly. Full install→uninstall→reinstall cycle driven entirely from HA.

### Camera-regression learning (2026-11-03, during the on-device notifier spike)
- **Never install a hand-run `npm run build` onto a TV.** `npm run build` loads `.env.local`, which bakes
  `VITE_SPIKE_STREAMS` (dev streams at the laptop's go2rtc) into the bundle → the app's play path hits a dead
  dev stream → **"WebSocket error"** and the camera won't play. The real bundle is built by
  `scripts/bundle_tv_app.py`, which forces `VITE_SPIKE_STREAMS=""` and rejects any stream URL in the output. Fix
  was to rebuild with that script and reinstall; it also now carries the `startNotifier` change.

### Milestone 24 (to build): productionise the native .NET notifier
Starting point is the working spike in `tv-app/notifier-dotnet` (Tizen.NET, `tizen40`, HTTP listener on `:8181`, `NotificationManager.Post`). Build steps, each verifiable:

- **24a. Harden the notifier app — DONE (2026-11-03, needs on-device re-verify of the auth path).**
  - **"Encrypted, only HA can control" is a signed request, not a plain token.** Each post carries
    `?title=&content=&ts=&nonce=&sig=`, where `sig = hex(HMAC_SHA256(secret, ts "\n" nonce "\n" title "\n" content))`.
    The notifier recomputes the HMAC with its copy of the secret and refuses (401, before any work) anything
    whose signature is wrong, whose `ts` is more than 30 s from its clock, or whose `nonce` it has already seen
    inside that window (single-use → captured requests can't replay). Constant-time compare; **fail closed** —
    with no key installed, every post is refused. A plain `?token=` was rejected as the design because it is a
    bearer secret that replays if sniffed on the LAN; the HMAC gives the same "only HA" guarantee and can't be
    replayed. (True payload *confidentiality* would need AES-GCM or TLS; the notification text ends up on the
    screen anyway, so authentication — not secrecy — is the control that matters. AES-GCM over the query is a
    cheap later upgrade with the same key if wanted.)
  - **The secret is the existing per-TV `tv_secret`.** HA stamps it into the package as `res/shared.key`
    (`notifier.stamp_notifier_key`, a pure zip rewrite — no .NET toolchain in HA, mirrors `samstream.json`),
    and the notifier reads it from its resource dir. Same credential the web app's `/session` uses.
  - Kept the main-thread drain-`Timer`-as-a-field pattern (a local Timer gets GC'd — proven). Returns
    `{"ok":true}`; added **`GET /health`** (no auth) so HA can see the app is resident (24b).
  - **Built:** `tv-app/notifier-dotnet/Program.cs` (compiles to a fresh `.tpk`), `custom_components/samstream/notifier.py`
    (signer, `async_post_native`, `async_notifier_alive`, `stamp_notifier_key`), `notify.py` now tries the native
    notifier first and falls back to the on-screen notice. Tests: `tests/test_notifier.py` (sign/verify agreement,
    fresh nonce, stamp roundtrip, health, post ok/refused/unreachable) + `tests/test_notify.py` (native-first,
    fallback). Crypto agreement and the zip stamp verified standalone; ruff clean; HA-harness tests run in CI
    (not installable on native Windows). **Still to verify on the TV:** a signed GET posts; a wrong/absent/old/replayed
    `sig` is refused; `/health` answers.
- **Single app vs. without an icon (answering the user's 2026-11-03 question).** The notification path is
  **only** reachable from .NET (`NotificationManager.Post`); the web `tizen.notification` API is dead on these
  TVs (`feature/notification=false`), so the notifier cannot be merged into the HTML web app and keep working.
  "One app" therefore means one of:
  - **(A) Hybrid Tizen package** — one package id / one launcher icon containing the web UI-app + a .NET
    service-app; the web component starts the service in-package. Genuine single app and single icon. **Risk:**
    hybrid web+.NET packaging and signing on this TV is unverified, and the earlier `nodisplay`/service variants
    never started (partly the sdb-can't-launch limitation). Needs an on-device spike.
  - **(B) Two packages, behaves as one (lowest risk, recommended interim)** — keep the notifier its own tiny
    package but have the Samstream **web app auto-start it** via `launchAppControl(org.samstream.notifier)`
    (the `openExternal`/`launchAppControl` primitive already exists in `tv-app/src/app.ts`). The user only ever
    opens Samstream; the notifier rides along. HA's `/health` + re-trigger covers a kill.
  - **Without an icon** = `nodisplay="true"` (or a `service-application`): no launcher icon. Viable **only**
    coupled with a reliable auto-start (an iconless app can't be opened by hand), so it depends on (A) or (B)'s
    start path. The spike's failed `nodisplay` attempts were really launch failures (sdb can't start sideloaded
    apps), so this needs re-testing once the web app does the launching.
  - **SPIKE RESULT (2026-11-03, on the QN800C): the true single hybrid (A) is NOT possible; shipped (B) with
    the same UX.** Tizen Studio has no Web-UI + .NET hybrid: `tizen package -t wgt -r <notifier.tpk>` is rejected
    ("reference must be a web widget"), native-primary rejects a .NET build dir, and the only web hybrid template
    is WebWebUIServiceApplication (web UI + *web* JS service) — and a JS service can't post notifications. So the
    notifier ships as **its own `nodisplay` package `org.samstream.notifier`** (no launcher icon) and the web app
    **auto-starts it** — same result the user wanted: one visible icon, seamless.
    - the web app **starts the notifier and hands it the secret** on boot — `tv-app/src/notifier.ts` (`startNotifier`
      → `launchAppControl(org.samstream.notifier, extras={samstream_secret})`), wired in `main.ts`; the notifier
      reads that secret in `OnAppControlReceived`, falling back to a stamped `res/shared.key`;
    - `npm run tv:notifier` builds the `.tpk`; `tv:notifier-install` installs it (`tv-app/scripts/tizen.mjs`).
    - **UX fix (found + fixed on-device):** launching the notifier brought its NUI window to the FRONT over
      Samstream (a black screen that broke the camera, since Samstream was no longer foreground). `Window.Lower()`
      alone is unreliable (can surface Home). Fix: the notifier **re-raises Samstream** after starting
      (`AppControl … SendLaunchRequest`, needs `application.launch`), plus `Lower()` and `SetAcceptFocus(false)` and
      a brand-navy (not black) window. No loop: the web app starts the notifier only on a fresh `boot()`, never on
      the appcontrol re-raise.
    - **VERIFIED on the QN800C (2026-11-03):** signed notifier installs with HA's cert (no err 118); web app's
      `startNotifier` starts the nodisplay notifier (`/health` 200 first poll); auth fully holds
      (unsigned/bad-sig/stale → 401, valid signed → 200, replay → 401); after launch Samstream is `visible:true`
      (foreground) and a signed post overlays it with the notifier backgrounded. Signing done inside the HA
      container (keys/secret stay on the server); install from the laptop (the TV's dev-mode host). **User visual
      confirm of the overlay + camera pending.**
    - **Still open:** keep-resident across standby (a bare REST re-raise won't restart a dead notifier — only a
      fresh `boot()` does; consider `on-boot` / a health-check re-trigger), and cold `notify` before the web app
      was ever opened (the stamped `res/shared.key` covers the key; the app just needs to be running). TV app: 40
      vitest + typecheck clean. See `docs/hybrid-package.md`.
- **24b. Keep it resident — web-app auto-start VERIFIED (2026-11-03), on-boot/standby survival is the spike.** The
  Samstream **web app** calls `launchAppControl(org.samstream.notifier)` on boot (`tv-app/src/notifier.ts`,
  `main.ts`), so the notifier runs whenever Samstream has been opened — and an in-package launch sidesteps the
  "sdb can't start a sideloaded app" limitation. HA has a liveness check (`notifier.async_notifier_alive` →
  `GET /health`). **VERIFIED end-to-end 2026-11-03 (QN800C):** after HA reinstalled both apps and launched Samstream
  via `launch_app`, the notifier came up on its own (`/health` 200 within ~6 s) and `notify.send_message` posted a
  native toast — the whole chain (HA install → HA launch → notifier auto-start → signed notify → overlay) driven from
  HA. **Still to decide/verify on the TV:** survival across a standby/wake cycle; whether to add `on-boot="true"`
  and/or a shared-data-dir key so a cold `notify` works before the web app was ever opened (see
  `docs/hybrid-package.md`).
- **24c. HA `notify` integration — DONE (2026-11-03).** `custom_components/samstream/notifier.py`
  (`async_post_native`) issues the **signed** `GET http://<tv>:8181/notify?title=&content=&ts=&nonce=&sig=`
  (per-TV host + `tv_secret`; never raises — a miss falls back). `notify.py`'s `async_send_message` tries the
  native notifier first and falls back to the on-screen Samstream notice (`show_message`) when it is unreachable
  or refuses. Diagnostics redaction of
  the secret is already covered by the existing `tv_secret` redaction. Tests: `tests/test_notify.py` (native-first
  + fallback), `tests/test_notifier.py`.
- **24d. Zero-config install of the notifier — DONE (2026-11-03, needs on-device end-to-end from HA).** The unsigned notifier `.tpk` is bundled at `custom_components/samstream/bundled/notifier.tpk` (built by `dotnet build -c Release` in `tv-app/notifier-dotnet`, no `res/shared.key`, icons `res/icons/{samstream,info}.png` included). `installer._async_install` now installs it **in the same sdb session** right after the web app: `_async_install_notifier` reads the bundle, stamps `res/shared.key`=`ensure_tv_secret` (via `notifier.stamp_notifier_key`), re-signs with the per-TV HA identity (`sign_wgt` strips the build's default Tizen sigs; distributor cert already covers the DUID checked for the web app), and `sdb.install(tpk, NOTIFIER_APP_ID)` — replacing an other-author copy first. **Best-effort:** gated on signing being set up, and any failure is logged (the web-app on-screen notice is the fallback), so it never fails the install the user asked for. Build-time `.tpk` build+sign is NOT needed in HA (no .NET toolchain) — the bundle is prebuilt and HA only stamps+signs (pure zip + XML-DSig). Tests: `test_installer.py` (installed alongside, stamped+signed, failure-isolated). **ON-DEVICE VERIFIED (2026-11-03, QN800C):** `samstream.install_app` (bundled) from HA alone signed+installed BOTH apps (log: `Installed org.samstream.notifier` + `Installed SmStrm0001.Samstream`). Needed the TV's Developer Mode Host PC IP set to the HA server **192.168.1.5** (was the laptop .21); the integration raises a clear repair/error until it is.
- **24e. Polish — DONE (2026-11-03).**
  - **De-duplication:** `notify.async_send_message` drops a byte-identical `(title, message)` repeated within `DEDUP_SECONDS` (= the 10 s notice window), so an automation firing on every motion frame collapses to one post; a distinct message, or the same text after the window, still shows. Test: `test_notify.test_identical_message_is_not_repeated`.
  - **Icon/severity → style:** icon/image already carried on the signed native post (24a/24d); severity maps to the on-screen notice tone bar + colour (info/warning/alert/success) in the fallback.
  - **Localisation:** `content` is passed through verbatim; the native Samsung popup renders RTL Arabic itself, and the on-screen fallback uses `dir="auto"` + `unicode-bidi: isolate`.
  - **Standby/off behaviour (documented):** the native toast + chime render only while the TV panel is on. In standby the notifier process is suspended, so a post neither wakes the panel nor sounds — the chime is *not* a wake source. A notification sent while the TV is off falls through to HA's own channels (phone), not the TV. Waking the panel for an alert would need WoL + app relaunch (out of scope); the notifier's own survival across a wake cycle is the 24b spike.
- **Guided-setup polish (2026-11-03):** the **Developer Mode** config step now shows the exact Home Assistant IP to type into the TV's four boxes (`{ha_host_boxes}`, and `{ha_host_rtl}` in Arabic, from `ha_lan_host` + `ip_boxes`), so it is never set to the laptop by mistake — the friction that blocked the first on-device install.
- **Verify (end to end):** from HA, `notify` → native notification overlays whatever is playing on the TV with custom text + chime, no interruption; unauthenticated posts are rejected; the notifier auto-recovers after standby.

### Decision (2026-11-02, SUPERSEDED by the 2026-11-03 breakthrough above for custom text): native popup = Matter leak sensor only; direct triggering of the TV's notification app is a confirmed dead end
Empirically closed on the Frame (QA55LS03DAUXEG) with a signed probe web app running the tests in-page. `com.samsung.tv.iot-service-notification-v2` is the app that renders Samsung's native SmartThings popups (its resources are all doorbell/camera/leak assets). It cannot be triggered by any non-platform (web / partner-signed) app:
- **message-port:** 6 notification/SmartThings apps × 18 port names × trusted+untrusted = 216/216 `NotFoundError`, including against the *running* `com.samsung.tizen.smartthings-client`.
- **app-control / launch_on_event:** firing its only declared control (`operation/launch_on_event` + uri `file:///tmp/IoT_S_Notification`), explicit and implicit, with a rich payload → `UnknownError`; the target app never launched and nothing appeared on screen. That event is a reserved platform event-broker (esd) event, not publishable from the Web Device API (no `eventsystem` in `tizen.*`).
- **OCF:** the app is `use.network=false`, fed by the on-device SmartThings hub; no LAN-reachable OCF resource originates a notification render.
So the native popup can only be driven by a device event on the TV's built-in SmartThings hub → **ship 19f (Matter leak sensor) for the native popup+chime, and the Samstream app-launch notice for custom text.** (Tooling note: on this TV `appcmd_support:disabled` is normal and does not block installs; raw `sdb install` only pushes — use the Tizen IDE CLI `tizen install` for the real pkgcmd handshake. Dev-mode host = laptop 192.168.1.21; only HA's Samsung cert installs.)

### Roadmap addition (2026-10-30): native TV popup via a disposable Matter leak sensor — DROPPED 2026-11-03 (user)
**DROPPED.** This whole Matter-leak-sensor native-alert line is removed from scope. The sideloaded **.NET notifier**
(24a–d, verified on-device) does strictly better: a native Samsung popup with a chime **and arbitrary custom text**,
overlaid on the running app, with no phone, no SmartThings pairing, and no device to create/tear down. The research
below is kept only for history (it remains true: a Matter leak sensor does pop up, but only with a fixed device-name
title). See [[samstream-tv-notifications]].

- ~~**19f. Native alert.** On `notify`, present a Matter leak sensor to the TV's SmartThings hub, set it to "leak",
  let the TV pop up, then remove the device again. (title = device name, no custom text.)~~ **DROPPED — use the .NET notifier.**
  - *(history)* Eligibility tested: the TV's Notification list pops up for a **leak sensor** only (not button/doorbell/
    contact/motion/smoke); title = device name at pairing. Would have needed a minimal Matter device in the
    integration and a one-time phone pairing — all obviated by the notifier.
### Roadmap addition (2026-11-03): investigate tizen-camera-pip for the camera implementation
- **23. Investigate `dzikus/tizen-camera-pip` — DONE 2026-11-03, verdict: camera-over-content PiP is NOT achievable; keep the current renderer.** That project is a **web app like ours** and hit the **same wall milestone 17 found**: compositing live input behind the app's HTML (`show()`) makes the platform **unload the app ~2.9 s later**, in every variant. Its `camera-corner`/`source-corner` layouts use `tvwindow` (the TV's own tuner/HDMI PiP, not an arbitrary RTSP camera) and fall back; the **only reliable layout is `fullscreen`**, where it plays one camera through AVPlay's hardware decoder and, on exit, relaunches the previously-watched app by ID over the local REST API — i.e. exactly our `play_stream` + `return_to_previous`. It uses only the **public-level `tv.window`** privilege (dev cert), so no hidden capability. Independent web search confirms "you cannot [overlay] over other application unless you have ownership and source code"; true overlay needs the **platform-only `window.priority.set`** (same gate as the native-notification research — see [[samstream-tv-notifications]]), which our HA/partner cert cannot get. **Conclusion:** there is nothing to swap in for the corner logic — keep full-screen camera + return-to-previous as the cross-app path, and the native `tvwindow` corner only for the TV's own sources. Sources: github.com/dzikus/tizen-camera-pip, Tizen forum "Showing Overlay Elements over 3rd party app".

### Roadmap addition (2026-11-03): TV app visual redesign from scratch — DONE (supersedes the 7b UI spec)
- **TV app redesigned from scratch in a new theme ("Night watch"), per the user's "design from scratch / new theme" directive**, driven by the `design-taste-frontend` skill's house rules and laws (not its web draw — a fixed 1920×1080 D-pad app has no scroll scenes or responsive widths). Supersedes the old 7b spec (hero/info cards, #3A9BD9 blue, 12/14px square buttons).
  - **Idea (from the subject):** a home's porch light left on through the night. The screen is a calm dark field lit by **one warm amber accent** (`--accent` #F2A93B) on every affordance — focus ring, primary button, the ready "light" (status dot), the progress bar — that turns **red** only on an alert. Red/orange/green appear *only* as alarm signals on a full-screen notice (`data-severity`).
  - **Two themes** kept (HA `settings.theme`): dark **Night watch** (default living-room look) and light **Daybreak** (neutral daytime). Both redesigned cohesively.
  - **House rules applied:** no gradients (dropped the success radial + bottom scrim), no hairline rules (action-bar/hud-clock borders → tone steps), no eyebrow (version moved off the hero into a quiet bottom corner), no shadows on things at rest (cards separated by a tone step; shadows only on glass that truly floats over live video), pill buttons decided once, one `h1` title that says what the app is ("Your cameras on the big screen"), a heading on the home, equal margins, no empty half (left copy answered by the "watch" lens motif on the right).
  - **Type:** single family **Readex Pro** kept (serves Arabic RTL + Latin equally; a Latin-only display face would split the heading voice by language). Weights 600 display / 300 lede give the range. User offered a pairing; a unified bilingual voice is the stronger call here.
  - **Files:** `tv-app/src/styles.css` (full rewrite), `tv-app/index.html` (home restructured: wordmark header, stage with the lens motif, action bar, corner version). All JS-driven ids/classes preserved; `tv-app` typecheck + 40 vitest + production build all green. Verified by 1920×1080 headless screenshots of Home (dark/light/RTL), Notice (alert), Player overlay. **Ships on the next `tv:deploy` / HA `.wgt` rebuild — on-device visual confirm pending.**

- **19g. Camera / video doorbell — BLOCKED on the TV's built-in hub (revisit).** SmartThings accepts a Matter camera (ep 0x0142 + separate 0x0143 doorbell ep); the TV lists the doorbell but its alert toggle can't be enabled and live view is a black spinner. The hub sends VideoStreamAllocate but never ProvideOffer/SolicitOffer, even with two-way-talk declared, so no WebRTC. Likely the TV's built-in hub does not run Matter camera video yet. go2rtc (serving the Hikvision H264/PCMU stream) + a WebRTC answer path are already written. **Revisit** with a dedicated SmartThings hub (Station/Aeotec) or a later TV firmware. If it ever works, a short rendered-text video could be the notification itself (custom text + sound, native).
