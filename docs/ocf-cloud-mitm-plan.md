# OCF cloud MITM — capturing the SmartThings notification wire shape

**Goal.** Learn the exact CoAP/CBOR payload Samsung's cloud pushes to the TV when a
SmartThings **notification** fires, so Samstream can replay it over the local OCF
cloud (`oicseek/cloud_server.py`) and make the TV render a native popup with
**our own text** — locally, no Samsung cloud, no Matter device. This is the only
known path to *local + native + custom-text* notifications. If it fails, the
fallback stays the proven Matter leak-sensor route (plan 19f) + the Samstream
app notice.

Status: **BLOCKED — infeasible on a TV that stays in SmartThings (verified
2026-11-02).** The proxy is built and unit-tested (`oicseek/cloud_proxy.py`) and
the recon driver exists (`oicseek/phase_c_mitm.py`), but Phase C step 1 cannot
run: the Frame reports `doxm.owned == true` (owned by SmartThings), so the
Random-PIN OTM needed to install our trust_ca + redirect `cis` is refused
(`trigger_pin` → `OcfTvOwnedError`). This is the risk-2 catch-22 made concrete:
OCF ownership requires the TV be unowned (removed from SmartThings), but removing
it from SmartThings kills the notification source we wanted to capture. There is
no MITM without ownership (the TV pins its cloud cert; our cert needs our CA
installed as trust_ca, which needs ownership), and no notifications without
SmartThings. **Verdict: this path is a dead end for a TV in daily use. Fall back
to the proven Matter leak-sensor route (plan 19f) + the Samstream app notice for
custom text.** The proxy/driver are kept for reference should the ownership
constraint ever change (e.g. a spare TV one is willing to remove from SmartThings
permanently, which still only captures cloud-origin notifications — risk 1).

Related: `docs/ocf-local-protocol.md` §14 (the local cloud takeover this reuses),
memory `samstream-tv-notifications`, `samstream-tv-native-alert-matter`,
`samstream-firmware-encrypted`.

## Why MITM (and not just reading the firmware)
The app that renders the popup, `com.samsung.tv.iot-service-notification-v2`, is
.NET in-house and the firmware is AES-encrypted (keys we don't have), so the
payload contract can't be read statically. It also can't be triggered by any
non-platform app locally (message-port = 216/216 NotFoundError; `launch_on_event`
= UnknownError; see `samstream-tv-notifications`). So we learn the shape by
watching a *real* notification cross the wire, then reproduce it.

## Architecture
```
TV  ──TLS(our CA, CN=cloud UUID)──▶  cloud_proxy.py  ──TLS(verify off)──▶  Samsung real OCF cloud
         (cis → our proxy)              (relay + log)         (TV's original cis host)
```
The proxy forwards every byte unchanged **both** ways, so the TV's real OCF
sign-up/sign-in is relayed verbatim to Samsung — the TV stays a live, registered
cloud device and real notifications keep arriving. It decodes each RFC 8323
frame for logging and appends every frame (decoded + raw hex) to
`oicseek/mitm_capture.jsonl`. The frame we want is flagged `<<< NOTIFY`:
a **cloud→TV** response `2.05` carrying the **observe** option (an OBSERVE
notification / push), most likely on `/service/observe`.

`cloud_proxy.py` reuses `cloud_server.py`'s framing (validated byte-for-byte by
the round-trip test) and `samstream_ocf.cbor_*`. Upstream TLS verification is
off on purpose (Samsung's OCF cloud chains to Samsung's private CA; this is our
own device's traffic on our own LAN).

## Two risks that decide whether this can work at all
1. **Does the notification even ride the OCF cloud channel?** The Matter
   leak-sensor popup may be fired by a purely *on-device* path (built-in hub →
   trusted event → notification app), with the cloud only informed so the phone
   also pops. If so, nothing crosses the OCF `cis` channel for that event and the
   capture is empty. **Mitigation:** capture a notification that is unambiguously
   *cloud-originated and TV-targeted* — e.g. a SmartThings **Routine/Automation**
   whose action is "notify this TV", or a second cloud device's event — not only
   the local leak sensor. Try several notification sources during the capture
   window.
2. **Does OCF ownership break the account / hub?** Writing `cis` + `trust_ca`
   needs OCF owner-PSK (PIN onboarding). `docs/ocf-local-protocol.md` §10 says
   OCF ownership and SmartThings are mutually exclusive for the add-device flow.
   If taking ownership signs the TV out of its Samsung account, it stops being a
   live cloud device and no notification will be generated to capture. **Unknown
   until tried** — watch, right after redirect, whether the TV still signs in
   through the proxy with a real-looking account token and whether the phone/app
   still shows the TV online. If ownership kills the account, MITM is infeasible
   and we fall back to 19f.

## Phase C — the run (needs the user at the TV + phone; ~1 session)
Pre: `oicseek/cloud.crt`,`cloud.key` (CN = cloud UUID, `gencerts_uuid.py`),
`ca.der`, `ca.key`. Host at a fixed LAN IP; `cis` will point at it.

1. **Recon the real upstream FIRST.** Onboard as OCF owner (PIN:
   `otm_onboard.py pin`) and read `/CoapCloudConfResURI` — record the current
   `cis` host:port. **That is the proxy's `--upstream`.** (Do this before
   overwriting `cis`.)
2. **Install trust + identity** exactly as §14.6/§14.7: add our CA as a
   `trust_ca` cred and an ACL ACE `{subjectuuid: <cloud UUID>, href:"*",
   permission:31}` (`acl_cloud.py`).
3. **Redirect `cis` to the proxy** via the provisioning-session kick (§14.7):
   `POST /sec/provisioninginfo` sessionid (if=oic.if.a) → tncagreed → `POST
   /CoapCloudConfResURI {cis: coaps+tcp://<host>:<LISTEN_PORT>, at, …}` (NO `sid`).
   Repeat up to ~3× until `cis` reads back stored and EasySetup `ps` → 8.
4. **Start the proxy:** `py -3.11 oicseek/cloud_proxy.py --upstream <real-host:port>
   --listen 5684`. Confirm the TV dials in (`CONNECT c1 …`, both TLS lines).
5. **Generate notifications to capture** (several kinds, note wall-clock each):
   trip the Matter leak sensor; run a SmartThings Routine that notifies the TV;
   any appliance/device alert. Watch the proxy log for `<<< NOTIFY` and the TV
   screen for the popup; correlate timestamps.
6. **Analyse** `mitm_capture.jsonl`: isolate the `notify:true` frames that
   coincide with an on-screen popup; the `payload` is the contract (resource
   path, keys, device-type/capability, text field). That is what
   `cloud_server.py` must emit on `/service/observe` to fire a popup locally.
7. **Teardown / hand back:** release ownership `pstat {cm:1}` (`otm_onboard.py
   reset`) so the TV returns to Samsung's cloud + SmartThings (restores 19f).

## Phase D — replay (next session, local only)
Teach `cloud_server.py` to push the captured frame shape on `/service/observe`
(it already registers the TV's observe at sign-in; add an outbound OBSERVE
notification with an incrementing seq). Fill `device/slaves` / profile with the
minimal device the contract references. Fire it; confirm a native popup with our
text. Then fold the minimal pieces into the integration.

## Files
- `oicseek/cloud_proxy.py` — the MITM relay (this plan). Built + unit-tested.
- `oicseek/cloud_server.py` — local cloud impersonator; the Phase-D replay host.
- `oicseek/acl_cloud.py`, `gencerts_uuid.py`, `otm_onboard.py`, `setcloud_sid.py`
  — trust/ownership/cis tooling (see §14 of the local-protocol doc).
- `oicseek/mitm_capture.jsonl` — capture output (created at run time; gitignored).
