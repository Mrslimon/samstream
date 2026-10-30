# Samsung TV local OCF — implementer's reference

Everything learned (2026-10-21 → 2026-10-23) getting local OCF access to the lab TV, so the next
implementer does not re-research it. **(verified)** = exercised against the real TV; **(unverified)** /
**(inferred)** = not confirmed. Lab IPs/UUIDs are examples — never hard-code them in the integration.

Related: `docs/plan.md` milestone 18 + its "18 revision"; `oicseek/` (spike tools); project memory
`samstream-ocf-dtls-posture`.

---

## 0. TL;DR

| Question | Answer |
|---|---|
| Talk OCF to the TV locally? | **Yes** — CoAP-over-DTLS-PSK after a Random-PIN ownership transfer. |
| Send commands? | **Yes.** Actuator POSTs execute (mute/volume confirmed by eye). They answer CoAP `4.00` even when they work — treat any response as success, timeout as failure. |
| Read live state (input, volume, now-playing, power, modes)? | **No (verified).** Every `/sec/tv/*` and `/capability/*` GET **and** OBSERVE returns `4.00`, even with `owned=true` + `isop=true`. State is served only to the TV's registered Samsung cloud. The resource appearing in `/oic/res` means it EXISTS and accepts POST — not that GET returns data. Impersonating that cloud locally doesn't help: over an OCF-cloud takeover channel the same reads return **`4.01 Unauthorized`** (vs `4.00` locally) — reachable but gated behind genuine Samsung authorization. See §14. |
| What can be read locally? | Device/platform info, **real firmware version**, Wi-Fi scan (incl. the TV's own AP signal), MAC addresses + feature flags, provisioning info, security state. See §7. |
| Local OCF + SmartThings together? | **No.** One owner. SmartThings takes local ownership at setup; while we own the TV the SmartThings app can't find it. Pick one. |
| Give the TV back? | **Yes, instantly:** as owner POST `/oic/sec/pstat {"cm":1}`. No Smart Hub reset, apps kept. |
| Pure-Python DTLS? | Not with `python-mbedtls` (§11). Today a small C helper does DTLS; CoAP/CBOR is Python. |

---

## 1. Identifiers (lab QN800C — examples only)

| Item | Value | Notes |
|---|---|---|
| OCF spec level | **OIC 1.1** (not OCF 2.x) | `/oic/d`: `icv=core.1.1.0`, `dmv=res.1.1.0,sh.1.1.0`. ACL is v1 `/oic/sec/acl` (`aclist/aces`), **not** acl2. pstat has no `dos`. |
| `di` (doxm `deviceuuid`) | `a63c3d4d-5237-a426-7130-9d7e14d09624` | PBKDF2 salt + owner-PSK derivation input. |
| pstat `deviceuuid` | `df7493aa-2493-4f5d-8134-ba141066a6d4` | **Different** from `di` — don't confuse. |
| vendor / model | `vid=VD-STV-2023`, `mnmo=QA65QN800CUXEG`, Tizen 9.0 | |
| SmartThings ids | `mnId=0AJK`, `setupId=101`, `tsId=VD01` | from `/sec/provisioninginfo`. |
| controller (owner) uuid | `5f3d8a21-…` (lab) | any fixed uuid; generate one per HA install, store it. |

---

## 2. Discovery — two endpoints, both dynamic

- **Plain CoAP (UDP):** 5683 answers unicast only sometimes; reliably answers **multicast** `224.0.1.187:5683`. When silent on 5683 it still listens on a random high port it replies FROM.
- **Secure DTLS (UDP):** a random high port in `/oic/res` as the `port` of each `sec:true` link (legacy `x.org.iotivity.tls` + `p.port`, **no `eps`**). Seen 39231 / 56298 / 46067. **Changes** on power cycle, SmartThings setup, resets. **Re-discover every session; never cache.**

Recipe **(verified)**:
1. `GET coap://224.0.1.187:5683/oic/res` (CoAP NON), `IP_MULTICAST_IF` = host LAN IP.
2. **Filter replies by source IP** — other Samsung devices on the LAN answer too.
3. `/oic/res` is **block-wise**: one datagram carries only block 0 (enough to raw-scan the secure `port`). To get the full directory, do an authenticated Block2 GET over DTLS (§4).
4. doxm/pstat are readable in cleartext on the unsecured port (owned=false is a privacy answer, not proof of un-ownership — trust `devowneruuid`).

See `oicseek/discover.py`.

---

## 3. DTLS-PSK transport

- **Cipher:** `TLS-ECDHE-PSK-WITH-AES-128-CBC-SHA256`, DTLS 1.2.
- **PIN session (onboarding):** PSK identity = ASCII string `"oic.sec.doxm.rdp"`; PSK = `PBKDF2-HMAC-SHA256(PIN_ascii, salt=UUID(di).bytes, iters=1000, dklen=16)`. PIN is the 8 digits the TV shows.
- **Operational session (after ownership):** PSK identity = the controller (owner) UUID as **raw 16 bytes** (not the string form); PSK = the derived **owner PSK** (§5). Many libraries can't send a binary PSK identity — that is one reason for the C helper.
- **Owner-PSK derivation** (IoTivity RDP, done in `dtls_tunnel.c` from the PIN handshake's exported TLS1.2 master secret + randoms):
  1. `key_block = TLS12-PRF(master_secret, "key expansion", server_random + client_random, 96 bytes)`
  2. `owner_psk = TLS12-PRF(key_block, "oic.sec.doxm.rdp" + obt_uuid(16) + server_uuid(16), 16 bytes)`
  where `server_uuid = di`, `obt_uuid = controller uuid`. This 16-byte key is the durable credential — store it (`tv_cred.json`: `device_uuid`, `obt_uuid`, `owner_psk_hex`). Only the port is dynamic.

The helper `oicseek/dtls_tunnel.c` (mbedTLS 3.x) does the handshake, prints `OWNERPSK=<hex>` on stderr,
then relays CoAP datagrams over stdin/stdout framed as `[2-byte big-endian length][datagram]` (len 0 = read
timeout / end marker). Build: `gcc dtls_tunnel.c -o dtls_tunnel -lmbedtls -lmbedx509 -lmbedcrypto`.

---

## 4. CoAP / CBOR quirks (all verified)

- **Content-Format:** use `application/cbor` = **60**. The TV **4.06**s an `Accept` of `application/vnd.ocf+cbor` (10000). For onboarding POSTs the PIN-phase code uses Content-Format 10000 in the request body and it works; authenticated GETs want **no** Accept option (Accept:10000 → 4.06).
- **Separate responses:** the TV often sends an empty ACK, then a **CON** data message you must ACK yourself. Wait for the CON, match by token, send `0x60 0x00 <mid>`.
- **Block2 reassembly:** large replies (`/oic/res`, `/oic/sec/cred`) come in blocks. **The TV ties every block to the FIRST request's token** — reuse the same token for all blocks; a fresh token per block is silently ignored (this was a real bug in the first client, which returned empty data). See the fix in `oicseek/samstream_ocf.py` `_request`.
- **OBSERVE:** register with CoAP option 6 (empty value) on a GET whose header byte is `0x44` (ver1, CON, **TKL=4**) — `0x40` (TKL 0) with a 4-byte token makes the TV read the token as garbage options. Even correctly formed, `/sec/tv/*` OBSERVE returns 4.00 and never notifies (verified by switching apps for 60 s).
- **Actuator POSTs return `4.00` but EXECUTE.** `/sec/tv/audio {"mute":true/false}` and `{"volume":0-100}` visibly muted/changed volume while answering 4.00 (user-confirmed). So: treat any response (4.00 or 2.xx) as delivered; only a timeout (no response) is failure.

---

## 5. Ownership transfer (Random-PIN OTM) — the working sequence

Trigger the PIN first: plain-CoAP `POST /oic/sec/doxm {"oxmsel":1}` (CBOR, Content-Format 10000) → 2.04; the TV
shows 8 digits. PIN + ports rotate when the TV idles — wake it first. Then, **matching every reply to its own
request token** (the `otm_full.py` bug was reading one reply batch per request, so slow separate responses
landed on the next step and `owned=true` never took effect — use `oicseek/otm_onboard.py` instead):

PIN session (identity `"oic.sec.doxm.rdp"`, PSK from the PIN):
1. `POST /oic/sec/pstat {"om":4}`
2. `POST /oic/sec/doxm {"devowneruuid": <obt>}`
3. `POST /oic/sec/doxm {"rowneruuid": <obt>}`
4. `POST /oic/sec/pstat {"rowneruuid": <obt>}`
5. `POST /oic/sec/cred {"creds":[{"credtype":1,"subjectuuid":<obt>,"privatedata":{"encoding":"oic.sec.encoding.raw","data":b""}}],"rowneruuid":<obt>}` — **empty** privatedata: the device derives its own copy of the owner PSK.
6. `POST /oic/sec/doxm {"owned": true}`

Operational session (identity = obt uuid **raw bytes**, PSK = derived owner PSK):
7. `POST /oic/sec/acl {"aclist":{"aces":[{"subjectuuid":<obt>,"resources":[{"href":"*"}],"permission":31}]},"rowneruuid":<obt>}`
8. `POST /oic/sec/pstat {"tm":0,"cm":0}` — clearing `cm` (TAKE_OWNER) is what stops the auto-revert.

All return 2.04. After this, a fresh operational session reads `/oic/d` 2.05. `isop` stays false but
functional access works; optionally `POST /oic/sec/pstat {"isop":true}` → 2.04 (does NOT unlock §6 reads).

**Durability:** the saved owner PSK persists across TV power cycles (re-discover the port, reconnect, no new
PIN). Idle for ~10–20 min with no owner activity → revert to unowned; a keep-alive touching the session every
~60–90 s holds ownership indefinitely (held 22.5 min in a test). Overnight standby loses it (no keep-alive
possible) — expect to re-onboard after the TV has been off. `cm=0` (step 8) is what prevents the *short* idle revert.

---

## 6. The hard wall: `/sec/tv/*` and `/capability/*` reads return 4.00

Confirmed repeatedly, including with `owned=true` **and** `isop=true`, with ACL permission 31 on `href:"*"`,
and with every interface/accept variation (`if=oic.if.baseline|a|s|r|rw`, Accept 60, no Accept):

- GET → `4.00` (separate response, ~1.5 s later). OBSERVE → `4.00`, no notifications.
- Affected: `contentinfo` (+`/thumbnail`), `inputsource`, `inputsourcelist`, `audio`, `channel`,
  `mode/picture`, `mode/sound`, `switch/binary`, `deviceinfo`, `batteryinfo`, `thingstatus`, `onsupport`,
  `msoinfo`, all `/sec/tv/appdata/*`, all `/capability/*`.
- POST to these executes (actuator) but its response carries no body either.

**Why (root cause):** these resources are command/handlers whose readable *state* the TV serves only to its
registered Samsung cloud. Local EasySetup never reaches "registered" for us: `/EasySetupResURI` stays `ps`
0/2/4 (never done), `x.com.samsung.tcstatus=2`, `/sec/provisioninginfo` `tncagreed=false`, `published=false`.
Those fields are device-computed — writing them returns 2.04 but nothing sticks. The user's observation:
SmartThings shows "device added" (cloud registration complete); that step never happens for a local-only owner.

**So: listing in `/oic/res` ≠ readable.** The directory lists the resource because it exists and accepts POST.
A read needs the thing-agent to answer, and locally it refuses. This is not a request-format problem we can
massage away — every interface/accept combination was tried.

**Where that data actually lives:** the Samsung **cloud** (SmartThings), or local side-channels — **UPnP**
`RenderingControl` for volume/mute (§9), the Tizen WebSocket REST for device info and app list.

---

## 7. Owner reset (give the TV back to SmartThings)

As the current owner, over the operational session:

```
POST /oic/sec/pstat {"cm":1}       # 2.04
```

doxm immediately reports `owned=false`, `devowneruuid` all-zeros (RFOTM). **No Smart Hub reset, apps/settings
kept.** After this the TV reappears in the SmartThings app's "add device" scan (while we own it with
`isop=true` it is HIDDEN from that scan). `oicseek/otm_onboard.py reset <cred> <port>` does exactly this.

If a session can't be opened (ownership already lost) just skip it — the TV is already unowned. Last resort is
the TV's **Reset Smart Hub** (Settings > Support > Device Care > Self Diagnosis), but that deletes installed
apps — avoid it; `cm=1` is the clean path.

---

## 8. Readable locally (GET -> 2.05, verified) and useful IDs

| Resource | Data | HA use |
|---|---|---|
| `/oic/d` | name, model `mnmc`, `di`, OCF versions | device info (also via REST) |
| `/oic/p` | **firmware `mnfv`** `T-OSCPCUABC-0090-2220.4` + `\|ST_ENERGY`, Tizen `mnpv` 9.0, `mnmn`, `mndt` 2023-01-01, `st` clock | **firmware sensor** — REST reports `firmwareVersion:"Unknown"`, OCF is the only local source |
| `/sec/provisioninginfo` | fw build `firmwareversion` `;25.04.22`, `deviceinfo.partialSerial`, `modelCode`, `thingSW` 6.0.25, BLE addr, `mnId/setupId`, `pinlength:8` | serial, fw date, diagnostics |
| `/sec/accesspointlist` | nearby APs: `ssid`, `macAddress`, `securityType`, `encryptionType`, `channel`, `rssi`, `maxRate`, `frequency` | **Wi-Fi signal/channel/band** — match the entry whose `macAddress` == the BSSID REST reports in `device.ssid` |
| `/DevConfResURI` | device name, MACs (`bm/em/lem/pm/wm` = BT/Eth/.../WiFi), feature flags `WOWLAN BTWAKEUP BTHIDPOWERON DLNADMR VOICE TV2MOBILE MOBILE2TV` | **WoL support**, Eth MAC |
| `/WiFiConfResURI` | `swmt` modes, `swf`/`swb` bands (2.4G/5G), connected `tnn` SSID | diagnostics |
| `/oic/sec/doxm`,`/oic/sec/pstat`,`/oic/sec/cred`,`/oic/sec/acl` | ownership/provisioning/credentials | "Local access: owned" diagnostic |
| `/oic/res` | full link directory (52 links, Block2) | capability discovery |

### IDs for command payloads (from the Frame's SmartThings export; confirm keys per-TV)
`Desktop/Attributes.json` + `Commands.csv` show the real values the TV uses. POST these as the value in the
matching OCF actuator (each POST executes but answers 4.00 — verify by eye / UPnP / REST side-effect):

- **inputs** (`/sec/tv/mediaInput` or `/inputsource`): `supportedInputSourcesMap` -> `{"id":"dtv","name":"TV"}`, `HDMI1`, ... Use the `id`.
- **picture mode** (`/sec/tv/mode/picture`): ids `modeGen_589828` (AI Customisation), `modeGen_589826` (EyeComfort), `modeGen_...` (Optimised) — names vary by locale, ids are stable.
- **sound mode** (`/sec/tv/mode/sound`): `modeAmplify`, `modeStandard`.
- **audio** (`/sec/tv/audio`, verified): `{"mute":bool}`, `{"volume":0-100}`.
- **power off** (`/sec/tv/switch/binary`): `{"value":false}` (power ON needs WoL / Tizen WS 8001/8002 — OCF can't wake a sleeping TV).
- **remote key** (`/sec/tv/virtualremote`, unverified key): `{"x.com.samsung.control.remote":"KEY_..."}`.
- **launch app** (`/sec/tv/launchapp`, unverified): `{"x.com.samsung.launchapp.appId":"<id>"}`.

### Data that is cloud-only (NOT readable locally — see section 6)
`contentInfo` (title/channel/program times/thumbnail/input name), current `inputSource` +
`supportedInputSourcesMap`, current `pictureMode`/`soundMode` + supported lists, `tvChannel`/`tvChannelName`,
`mediaPlayback.playbackStatus`, `powerConsumptionReport`, energy-saving, `soundDetection`, sensor/ambient/art
state, `samsungvd.*`. These appear as SmartThings capabilities (Attributes.json) and in `/oic/res`, but their
**current value** is served by the cloud agent, which refuses local GET/OBSERVE. Available only via the
SmartThings cloud integration (mutually exclusive with local ownership — section 10).

---

## 9. Side channels that DO give live state (no OCF read needed)

- **UPnP / DLNA (port 9197):** SSDP finds `urn:schemas-upnp-org:device:MediaRenderer:1` at
  `http://<tv>:9197/dmr`. `RenderingControl` (`/upnp/control/RenderingControl1`) has **`GetVolume`,
  `SetVolume`, `GetMute`, `SetMute`** (InstanceID 0, Channel `Master`) — real volume/mute, read and write, no
  Developer Mode or OCF. `AVTransport` exists but on a TV mostly reflects DLNA push playback, not app playback.
  Resolve the control URL from the device description each session. This is milestone **18j**.
- **Tizen WebSocket REST (port 8001/8002):** `GET /api/v2/` = model, duid, PowerState, developerMode, wifiMac,
  resolution, support flags. Also the apps list and remote-key channel (what the integration already uses).
- **SmartThings cloud:** the only source for the section-8 cloud-only state.

Also advertised via SSDP: `:9110/ip_control` (IPControlService — empty action list on this TV),
`:9119/screen_sharing` (ScreenMirroring), `:7678/nservice` (DIAL).

---

## 10. Caveats to anticipate

1. **Secure port is dynamic** — re-discover every session; never cache across power cycles.
2. **Block2 token reuse** (section 4) — the #1 "reads come back empty" trap.
3. **Reply-to-step matching** — match each reply to its request token; batch readers mis-assign slow separate responses (the `otm_full.py` ownership bug).
4. **Overnight loss of ownership** — standby with no keep-alive drops it; plan to re-onboard (new PIN) after the TV has been off. A keep-alive <=90 s holds it while on.
5. **doxm `owned=false` in cleartext is a privacy answer** — check `devowneruuid` for the real state.
6. **Exclusive ownership** — adding the TV to SmartThings takes ownership with a Samsung vendor OTM
   (`oxmsel=0xff02`, owner e.g. `4113b510-...`) and locks us out; owning it hides the TV from the app. Pick one.
7. **LAN reachability glitches** — after heavy OCF traffic the TV sometimes stops answering the controller's
   ARP (both Windows and WSL); a Wi-Fi restart or a TV restart clears it. In WSL mirrored-networking, multicast
   egress and dynamic ARP are flaky — set a static neigh entry: `ip neigh replace <tv-ip> lladdr <mac> dev <if> nud permanent`.
8. **dtls_tunnel can block in pselect()** with no timeout — wrap reads with a `select` timeout (see `otm_onboard.py` `_readn`).
9. **Build/runtime deps** — `python-mbedtls` 2.28 can't do the operational handshake (fatal alert) and can't send a
   binary PSK identity or export the master secret; the mbedTLS-3.x C helper is required for both onboarding and control.
   For HA, keep OCF deps optional/lazy so a base install without them is unaffected.

---

## 11. Toward pure Python — DONE

Needed: a DTLS 1.2 client that (a) does ECDHE-PSK with a **raw-bytes** PSK identity and (b) can derive the
owner PSK (needs the TLS1.2 master secret + client/server randoms, i.e. a key-export callback). `python-mbedtls`
2.x exposes neither, so the C helper filled the gap originally.

**Now done in pure Python**, on `cryptography` (already a dependency; no C compiler, no new deps):
`lib/aiosamstream/src/aiosamstream/ocf/dtls.py` is a from-scratch DTLS 1.2 ECDHE-PSK client — we control the
whole handshake, so the binary identity is native and we compute the master secret ourselves. `derive_owner_psk`
reproduces `dtls_tunnel.c`'s two-pass PRF byte for byte. `ocf/onboard.py` layers the proven pure-Python
CoAP/CBOR (Block2 token reuse, separate-CON-response ACK, `application/cbor`) on top and drives the full
sequence (discover → trigger PIN → ownership → install CA/ACE/cis → release). `oicseek/dtls_tunnel.c` and the
`oicseek/*.py` scripts remain as the reference the port was validated against.

**Onboarding runs inside HA when HA is on the TV's network, else from the LAN.** HA in a bridge-networked
Docker container cannot reach the TV over UDP (multicast doesn't cross the bridge; unicast to 5683 is dropped
because the TV replies from a high port), and Docker Desktop on Windows delivers no UDP replies to containers at
all; with host networking on a Linux host (e.g. a VM bridged onto the LAN) HA does the whole PIN onboarding
itself. When it cannot find the TV, the setup screen offers the **LAN helper**: HA builds `samstream-onboard.pyz`
on the fly (only `exceptions`, `cbor`, `coap_tcp`, `dtls`, `onboard`, `onboard_cli` - stdlib + `cryptography`,
kept to Python 3.11 syntax) with the TV address and the bundle (address, token, cloud UUID, CA) baked in, served
through signed, expiring links (plus a Windows `.cmd` launcher). The tool owns the TV and points its `cis` at HA;
the TV then dials the cloud (TCP 5684). It prints a credential to paste back into HA so HA can later release the
TV. From a checkout the same tool is `scripts/onboard_tv.py`. `release` (or the HA "hand back" screen, when the
credential is known) does `pstat cm:1`.

---

## 12. What was NOT pursued

Making Home Assistant act as the TV's own cloud (so the TV completes registration against us and might then
serve section-6 state locally) was explored and then **declined** — not carried into the plan or the
integration. Treat the SmartThings cloud, not a local cloud replacement, as the source for cloud-only state.
The read wall in section 6 stands for a local-only owner.

---

## 13. Files

- `oicseek/samstream_ocf.py` — client: discover, DTLS via tunnel, get/post, Block2, separate-response, CBOR, `mute/set_volume` (verified) + best-effort `power/send_key/launch_app/set_input`.
- `oicseek/otm_onboard.py` — correct token-matched Random-PIN onboarding + `reset` mode.
- `oicseek/dtls_tunnel.c` — mbedTLS DTLS-PSK handshake, owner-PSK derivation, CoAP relay.
- `oicseek/discover.py` — multicast discovery, secure-port scan, PIN trigger.
- `oicseek/TV_OCF_REFERENCE.md`, `README_HA.md` — earlier notes (resource table, MQTT-bridge demo).
- `oicseek/otm_full.py` — **superseded** by otm_onboard.py (batch-reply bug); kept for its PIN-phase params.
- `oicseek/cloud_server.py` — the finished OCF-cloud takeover server (section 14): RFC 8323 CoAP-over-TCP+TLS,
  sign-up/sign-in/RD/ping, GET→2.05, fires RETRIEVE(+OBSERVE) on sign-in. Needs `cloud.crt`/`cloud.key`/`ca.der`
  from `gencerts.py`. Proved `/sec/tv/*` cloud reads are `4.01`. Supersedes the scratchpad `fakecloud2.py`.
- `oicseek/gencerts.py` — local CA + server cert (ECDSA P-256, SAN = host IP) for cloud_server.py. The CA DER
  is what the sign-up response hands the TV and what gets installed as its trust_ca during provisioning.

---

## 14. Local OCF cloud takeover — status and exact finishing recipe

**Goal:** keep the TV's live state (section-6 cloud-only attributes) **local and private** by running an OCF
cloud on the LAN that the TV registers with instead of Samsung's. HA's SmartThings integration is NOT this —
it is Samsung's cloud over HTTPS (OAuth to `api.smartthings.com` + status polling / SSE), so it is slow and
sends the data to the vendor. The local-cloud path avoids both. Open-source precedent: `plgd/hub` (Go) and
IoTivity-lite `cloud_server` (C) implement the same OCF cloud protocol; the spike here is a small Python
equivalent.

### 14.1 What already works (verified 2026-10-23)
With a server speaking CoAP-over-TCP+TLS (RFC 8323) on the LAN, our CA installed on the TV as a `trust_ca`
cred (section 5-style write), and the TV's `/CoapCloudConfResURI` pointed at it (`cis = coaps+tcp://<host>:<port>`):

1. TV opens TLS, **trusting our CA** (no Samsung cert needed) — cipher `ECDHE-ECDSA-AES256-GCM-SHA384`.
2. TV `POST /oic/account` (sign-up) with `di`, `authprovider`, `accesstoken`(=our `at`), `uid`, `devicetype:ocf_hub`.
3. On a sign-up reply shaped like IoTivity's `AccountManager.makeSignUpResponse` (keys: `accesstoken`,
   `refreshtoken`, `tokentype:"bearer"`, `expiresin`, `uid`, `redirecturi`=the cis, `certificate`=root CA DER
   bytes, `sid`=cloud uuid), the TV proceeds — **this was the unlock**; without `redirecturi`/`certificate`/`sid`
   it stalled after sign-up.
4. TV `POST /oic/account/session` (sign-in, `login:true`), then `/oic/ping`, `/oic/account/tokenrefresh`,
   `GET /service/observe`, `GET /x.com.samsung/device/slaves`, `GET /oic/account/profile/device`,
   `GET /x.com.samsung/group`, and `POST /oic/rd` publishing its **full 52-link resource directory**.
5. The cloud (us) issuing `GET /oic/d` down that connection returned **2.05** — reads through the cloud channel work.

### 14.2 (SUPERSEDED by 14.7) (2026-10-23 pm): cloud reads of `/sec/tv/*` return **4.01 Unauthorized**
The finishing recipe below was built into `oicseek/cloud_server.py` and run against the live TV. The TV's
`cis` and our trust_ca **persisted** from the morning session, so the TV dials our cloud on its own — no
re-onboarding needed to resume the takeover; just launch the server. Results, reproduced over 1000+ reads
across three runs:

- `GET /oic/d`, `GET /oic/p` through the cloud channel → **2.05 with full body** (device + platform info,
  incl. real `mnfv`). So our cloud GETs are well-formed and the signed-in cloud session IS honored for the
  `oic.wk.*` resources.
- **Every `/sec/tv/*` read → `4.01 Unauthorized`**, identical for one-shot RETRIEVE and for OBSERVE register.
  Tally: 808 RETRIEVEs + 214 OBSERVEs, **zero** 2.05, all 4.01. `contentinfo`, `inputsource`, `audio`,
  `switch/binary`, `channel`, `mode/picture`, `mode/sound`, `inputsourcelist`, `deviceinfo`, `mediaInput`,
  `thingstatus` — all 4.01.

This is the key difference from the local DTLS channel (section 6), where the same resources answer `4.00`
(flat refusal). Over the cloud channel the thing-agent **does** respond, but with `4.01` = *not authorized*.
So the data is served to "the cloud", but behind an authorization our local cloud impersonator cannot produce:
the device wants a genuine Samsung-issued credential/role for those resources, which only the real SmartThings
cloud holds. A fake account with bogus `accesstoken`/`uid` is accepted for sign-in and for `oic.wk.*` but not
for the protected TV state. ~~**Verdict: the section-6 cloud-only attributes are NOT obtainable via a local cloud
takeover.**~~ **This verdict was WRONG — see 14.7: with a CN=cloud-UUID cert + the matching ACL ACE they ARE
obtainable (2.05 with full bodies, verified).** The refusal here was a subject-ACL miss, not a genuine
Samsung-issued credential requirement — it *was* an ACL problem we could massage.

### 14.3 What the server does (built, works, in the repo now: `oicseek/cloud_server.py`)
The fixes from the original recipe, all implemented and verified to behave as intended:

1. **GET → `2.05 CONTENT`, not `2.04`.** The earlier `fakecloud2.py` answered the TV's own sync GETs
   (`/service/observe`, `/x.com.samsung/device/slaves`, `/oic/account/profile/device`, `/x.com.samsung/group`)
   with `2.04 CHANGED`. Answering a CoAP GET with 2.04 is a protocol violation and was a big part of the storm:
   with 2.05 the TV gets noticeably further (it now sends `POST /oic/ping {in:8}` to set an 8-min keepalive).
2. **Reads fire the instant the TV signs in — not on `/oic/rd`.** Critical correction to the original recipe:
   on a *reconnect* the TV does **not** re-publish `/oic/rd` (it published once, in the morning; our server
   restart doesn't make it republish). So gating the reads on `/oic/rd` meant they never fired. Fire them
   right after `POST /oic/account/session`, back-to-back, no inter-read sleep, inline on that connection's recv
   thread (so a torn-down socket can't crash a side thread, which was the old threaded-probe bug). The server
   still ALSO fires on `/oic/rd` if a publish does arrive.
3. **RETRIEVE + OBSERVE the device's resources** right after sign-in (what plgd/hub's coap-gateway and IoTivity
   cloud do: retrieve each published resource and observe it). `OBSERVE_READS=1` env toggles register-observe.
4. **Never close from our side; answer `/oic/ping` instantly.** Proactive cloud reads measurably calmed the
   storm (connection lifetime 0.4 s → ~1.7–3.0 s) but did **not** stop it — the TV still tears down and
   reconnects every ~2 s. Stopping the storm entirely would need the right content in the sync-GET responses
   (we return empty `{}`), but since the reads are 4.01 regardless, it would not change the verdict.

Success signal (for reference): a `/sec/tv/contentinfo` answered `2.05` with a CBOR body. We never saw it; we
saw `4.01` every time.

### 14.3b Reconnect storm SOLVED (2026-10-30)
Two causes, found by logging every message both ways (`aiosamstream.ocf` at debug):
1. **Token refresh loop.** After each sign-in the TV sent `POST /oic/account/tokenrefresh`; a successful
   refresh makes its cloud client sign out and dial again (same as TizenRT `st_things`
   `handle_refresh_token_cb` -> `force_session_stop` + `log_in_out_to_cloud`). `expiresin` 3600 and -1 both
   triggered it; **`expiresin` = 1 year** stops it.
2. **Keep-alive reply.** The TV then hung up right after `POST /oic/ping {in: 8}`: answer ping **`2.03 Valid`
   with no body** (IoTivity's KeepAliveResource), not `2.04 {}`.
With both, one connection holds for minutes. Answering `/x.com.samsung/device/slaves` or
`/oic/account/profile/device` with guessed content brings the storm back (the TV parses them); keep `{}`.
Pushes on the TV's own `/service/observe` subscription (6 payload shapes) drew no reaction.

### 14.4 Preconditions each run
- **If the TV is already dialing the cloud** (cis + our trust_ca persist from a prior run — they survived a full
  day and a network change in the 2026-10-23 pm session), just launch the server: `py -3.11 oicseek/cloud_server.py`
  on the host whose IP the cis points at, with `cloud.crt`/`cloud.key`/`ca.der` beside it (set `CLOUD_IP` if the
  host IP differs from the cert SAN). Confirm with `netstat -an | findstr :5684` — the TV connects within ~20 s.
  Re-onboarding (below) is only needed to first point the TV at us, or after the TV has been off overnight.
- TV reachable over OCF (if its stack is wedged from a prior run, power-cycle the TV).
- Reset owner (`otm_onboard.py reset`) then re-PIN (`otm_onboard.py pin`) — ownership is needed to write the
  trust_ca cred and the `cis`. The `cis` write only "takes" (EasySetup `ps` -> 4, TV starts dialing) when
  EasySetup `ps` is already 2 (Wi-Fi step done). After a TV restart `ps` resets to 0 and the TV will NOT dial;
  the reliable way to get `ps=2` is: release ownership, add the TV in the SmartThings app (which runs the Wi-Fi
  step), delete it there, then re-PIN — `ps` stays 2 and the cloud write triggers the dial. (A local
  `/WiFiConfResURI` + `cn` write did NOT advance past `ps=1` even with the correct Wi-Fi password.)
- Point `cis` at the server; keep our CA installed as trust_ca.

### 14.5 Caveat
This was explored in-session and left unfinished by choice. It is legitimate interop with your own device on
your own network (the TV is redirected to a server you run; no third party is involved). If section 14.3 step 3
does not stop the reconnect storm, the next reference to mine is `plgd/hub`'s coap-gateway handling of a device
right after `/oic/rd` — replicate whatever it does there.

### 14.6 WHY the cloud reads are 4.01, and the authorization fix (2026-10-23 pm, part 2)
**The 4.01 is standard OCF cloud access control, not a Samsung token check.** Two facts settle it:

1. **The token is not the gate.** OCF Cloud Security Spec §3.1.1: *"An Access Token is a string while the OCF
   Device has no internal logic based on its contents and only forwards the token as-is."* So our bogus
   `accesstoken`/`uid` is not why `/sec/tv/*` is refused — the device never validates token contents.
2. **The gate is a subject-ACL miss.** OCF Cloud Security Spec §5.x: *"For the purposes of access control, the
   Device shall identify the OCF Cloud using the OCF Cloud UUID in the Common Name field of the End-Entity
   certificate used to authenticate the OCF Cloud,"* and the OBT/AMS *"set[s] the OCF Cloud UUID as the
   'subject' Property for the new ACL2 entries"* (wildcard or per-resource). Our fake-cloud TLS cert had
   `CN=192.168.1.21` (an IP, not a UUID), so the TV could not map our connection to a cloud identity and fell
   through to the **anon wildcard ACE**. Reading the live ACL as owner confirmed it exactly: the `subjectuuid:"*"`
   ACE grants RETRIEVE (perm 2) on **only** `/oic/res`, `/oic/d`, `/oic/p` — which is precisely the set that
   returned 2.05, while everything else returned 4.01. (The owner's own `subjectuuid:<obt>` `href:"*"` perm-31
   ACE is what we authenticate as on the LOCAL DTLS channel, and `/sec/tv/*` is still 4.00 there — see the
   residual-doubt note below.)

**The fix, and what was installed on the TV (all verified present via owner read-back):**
- `oicseek/gencerts_uuid.py` — reissue the cloud end-entity cert with **CN = the cloud UUID**
  `5a4d5153-7473-4f52-8d73-616d73747265` (keeps SAN = host IP so TLS still validates); saves `ca.key` too.
  Because `gencerts.py` never saved the CA key, this regenerates the CA, so the new CA must be re-installed as
  the TV's `trust_ca`.
- `oicseek/acl_cloud.py` (run in WSL, owner session) — installs the new CA as a `trust_ca` cred (credtype 8,
  credusage `trust_ca`) and adds an ACE `{subjectuuid: <cloud UUID>, resources: [/sec/tv/* …, {"href":"*"}],
  permission: 31}` via read-modify-write (keeps the existing anon ACEs). Both writes returned 2.04 and the ACE
  reads back present.

**BLOCKER that stopped the final observation:** to see whether the CN=UUID cert + the cloud-UUID ACE flip
`/sec/tv/*` to 2.05, the TV has to dial our cloud again so it presents against the new cert. It stopped dialing:
a stray partial `POST /CoapCloudConfResURI {"sid":…}` (don't send `sid` — it makes the whole update not apply
`cis`) knocked out the `cis`, and re-writing `cis` now returns 2.04 **but does not stick** because EasySetup is
at `ps=4`; a `cis` write only takes at `ps=2`, and `ps` is device-computed (local writes don't stick — §14.4).
So finishing needs the **ps=2 re-provision dance** (release ownership `cm=1` → add the TV in the SmartThings app
so it runs the Wi-Fi step → delete it there → re-PIN), then re-install trust_ca + ACE (new owner PSK) and
re-point `cis`. That needs the phone; left for a session with the user present.

**Residual doubt (why this might still not work even once authorized):** on the LOCAL DTLS channel we ARE the
owner with a `href:"*"` perm-31 ACE, yet `/sec/tv/*` is 4.00 — i.e. the Samsung thing-agent refuses regardless
of ACL there. The cloud channel is clearly different (4.01, and it honours the anon ACE for the wk resources),
so the cloud-UUID ACE is the right next lever — but it is still possible the thing-agent imposes a further
"am I a fully-registered SmartThings cloud" gate beyond OCF ACL. **RESOLVED — there is no further gate; see 14.7.**

---

### 14.7 RESOLVED and VERIFIED (2026-10-23, later pm): the local cloud DOES read `/sec/tv/*` (2.05)

The 14.6 fix works. With (a) the cloud end-entity cert carrying `CN = <cloud UUID>` and (b) an ACL ACE whose
`subjectuuid` is that same cloud UUID with `permission: 31`, the TV's cloud-channel reads of **all 11 `/sec/tv/*`
resources return `2.05` with full CBOR bodies** — deterministically, on every one of the ~2 s reconnects:

```
CONNECT c1 from ('192.168.1.11', 43284)
  [c1] TLS TLSv1.2 ECDHE-ECDSA-AES256-GCM-SHA384
  [c1] <= /sec/tv/contentinfo    2.05  input=webapp title='YouTube' subtitle='9Ur5IzDKqV.TizenYouTube'
  [c1] <= /sec/tv/inputsource    2.05  currentMode='dtv'
  [c1] <= /sec/tv/audio          2.05  volume=40 mute=False
  [c1] <= /sec/tv/switch/binary  2.05  value=True
  [c1] <= /sec/tv/channel        2.05  channelNumber='154' channelName='Al-Majd3'
  [c1] <= /sec/tv/mode/sound     2.05  currentMode='modeStandard'
  [c1] <= /sec/tv/inputsourcelist 2.05
  [c1] <= /sec/tv/deviceinfo     2.05  bt/ble/wifi/eth/p2p macs, udn=6309477c-…
  [c1] <= /sec/tv/mode/picture   2.05  FILMMAKER MODE / أفلام / اقتصادي …
  [c1] <= /sec/tv/mediaInput     2.05  sources=[{sourceName:'TV', status:True}]
  [c1] <= /sec/tv/thingstatus    2.05  state=''
```

**The one extra blocker that made the 14.6 attempt look impossible: the `cis` write is silently dropped unless a
provisioning session is open first.** A bare `POST /CoapCloudConfResURI` returns `2.04` and stores **nothing**
(verified across 8 payload shapes, with/without `sid`, with `if=oic.if.baseline`/`oic.if.ll`, and `PUT` → `4.00`).
The device ACKs but discards. It only persists after opening a session on `/sec/provisioninginfo`:

1. `POST /sec/provisioninginfo {"x.com.samsung.provisioning.sessionid": <sid>}` — interface **`if=oic.if.a`**
2. `POST /sec/provisioninginfo {"x.com.samsung.provisioning.tncagreed": true, "x.com.samsung.provisioning.sessionid": <sid>}` — `if=oic.if.a`
3. `POST /CoapCloudConfResURI {"apn","cis","at","x.com.samsung.clientid","x.com.samsung.uid","x.com.samsung.refreshtoken","x.com.samsung.iatt"}`

After step 3 the `cis` reads back **stored** (`cis='coaps+tcp://192.168.1.21:5684'`) and EasySetup `ps` advanced
**2 → 8**; the TV then dials the cloud. Repeat steps 1–3 up to ~3 times — in this run the first two attempts only
stuck the `cis`, and the third also flipped `ps`, after which the server saw the TLS dial within seconds.
Do **not** put `sid` in the CoapCloudConf body (it makes the update not apply; the cloud identity comes from the
cert CN). Ownership (owner-PSK DTLS session) is required for all of the above.

**Revised conclusion:** the section-6 cloud-only attributes ARE obtainable locally — no Samsung-issued
credential, no "fully-registered SmartThings cloud" gate. The `4.01`s in 14.2 were purely the missing
subject-ACE for the cloud UUID. `oicseek/cloud_server.py` + the CN=UUID cert + the cloud-UUID ACE + the
provisioning-session kick together give a working local OCF cloud that serves the TV's live state.

**Caveat that still stands:** the TV holds `cis` now, so it will keep dialling `coaps+tcp://192.168.1.21:5684`
and reconnecting every ~2 s for as long as the server is up (the reconnect storm of 14.3 is unchanged). If you
don't want the TV pointed at the local cloud, clear `cis` (or leave the server down) — the TV falls back to
failing cloud connects.
