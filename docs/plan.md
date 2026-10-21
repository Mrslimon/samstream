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
- **7c. Revisit app detection with the full app list.**
  - **Problem today:** 2020+ firmware does not answer `ed.installedApp.get`, so milestone 6 probes a catalog of known IDs, plus the user's "Extra app IDs" option, through `GET /api/v2/applications/<id>`. The current app is the one reporting `visible: true` (YouTube was confirmed on the QN800C).
  - **Fix:** once milestone 7's sdb client works, read the real installed list from the TV (`vd_applist` / `pkgcmd`) and feed the scan from it. Drop the catalog to a fallback for TVs without Developer Mode, and remove the need for manual extra IDs.
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
