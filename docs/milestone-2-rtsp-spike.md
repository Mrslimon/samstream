# Milestone 2 – RTSP spike on QA65QN800CUXEG (2023, Tizen 7.0)

Goal: find out which stream path AVPlay plays on this TV, how fast it starts, and whether
Arabic overlay text renders correctly over video.

## 1. Developer Mode (once)
1. TV: open **Apps**, press `1 2 3 4 5` on the remote (on-screen keypad if needed).
2. Developer mode **On**, Host PC IP = the machine running sdb: the dev laptop **192.168.1.21**
   now, and later the HA server **192.168.1.5** when HA installs the app itself. Only one at a time.
3. Restart the TV: hold the power button until the logo appears.

## 2. Samsung certificate (once, stays on this laptop)
Tizen 7.0+ rejects packages that are not signed with a Samsung distributor certificate
containing this TV's DUID, the default Tizen certificate is not enough.

1. Connect: `C:\tizen-studio\tools\sdb.exe connect <TV_IP>:26101`, then
   `C:\tizen-studio\tools\sdb.exe devices` should list the TV.
2. VS Code → Command Palette → **Tizen: Certificate Manager** → create a **Samsung** certificate
   for **TV**, profile name **`samstream`**, new author certificate, sign in with your Samsung
   account, distributor privilege **Public**, and pick the connected TV (adds its DUID).
3. Never copy the `.p12` files or passwords into this repo (`*.p12` is gitignored).

### Findings (2026-10-20, TV reports Tizen platform 9.0)
- A **Tizen** certificate profile (VS Code "samstream": Tizen developer author + default Tizen
  distributor) is rejected: `install failed[118, -12] Check certificate error: Invalid certificate chain`.
- The **Samsung** certificate minted by Apps2Samsung ("Jelly2Sams - Public", made with the user's
  Samsung account and covering this TV's DUID) signs Samstream fine and installs. The certificate is
  bound to the TV, not to the app, so the Jelly2Sams-style per-user minting works for Samstream.
- Local signing: `tv-app/.signing/profiles.xml` (gitignored) + `TIZEN_PROFILES_PATH` / `TIZEN_PROFILE`
  in `.env.local`; `npm run tv:deploy` switches the CLI profile file only while packaging.
- Retail firmware: `sdb dlog` returns nothing and `sdb shell 0 debug <app>` hangs, so read results from
  the on-screen panel.

## 3. Optional HLS fallback (go2rtc on the laptop)
Download the go2rtc Windows binary and create `go2rtc.yaml` next to it:

```yaml
streams:
  door: rtsp://USER:PASS@192.168.1.6:554/Streaming/channels/101
```

Run it and check `http://192.168.1.5:1984/` in a browser. The spike's third entry plays
`http://192.168.1.5:1984/api/stream.m3u8?src=door`.

## 4. Build and deploy
```sh
cd tv-app
# set TV_HOST=<TV_IP> in .env.local
npm run tv:deploy        # build → tizen package (profile samstream) → install → run
```

Remote: **← / →** switch stream, **1–3** jump, **OK** replay, **Back** exit.
The panel at the top left shows state, time to first frame, codec and resolution, and errors.
Logs: `C:\tizen-studio\tools\sdb.exe dlog | findstr samstream`

## 5. Results (fill in)
Camera (Hikvision, HIK Media Server V4.83.800): 101 = H.264 High@5.0 (packetization-mode=0)
+ PCMU audio; 102 = H.265 + PCMU audio.

| # | Stream | Plays? | First frame (ms) | Codec / resolution | Error |
|---|---|---|---|---|---|
| 1 | RTSP cam 101 direct | no | | | `prepare failed: InvalidAccessError` |
| 2 | RTSP go2rtc, no auth | no | | | same |
| 3 | RTSP go2rtc, video only | no | | | same |
| 4 | HTTP MP4 go2rtc | no | | | |
| 5 | HLS go2rtc (AVPlay) | yes, slow | ~4 s by eye (old timer said 60751) | video/x-h264 1488x1664 | `PLAYER_MSG_BITRATE_CHANGE 192000`; second run: first frame 4381 ms, then picture appeared frozen |
| 6 | RTSP cam 102 H.265 | no | | | same |
| 7 | MSE go2rtc main H.264, video only | **yes, smooth** | **296** | avc1 (High), 1488x1664 | 1st try: `websocket error`, because go2rtc rejected `origin=file://`; fixed with `api.origin: "*"` |
| 8 | MSE go2rtc sub H.265, video only | **yes, smooth** | **953** | hvc1 | |
| 9 | MSE go2rtc main H.264 + FLAC audio | no (black) | | `avc1.640029,flac` | data buffers (rx about 850 KB) but nothing renders: this TV's MSE does not decode FLAC |
| 10 | HLS go2rtc (AVPlay) | first frame, then freezes | 2962 | | |
| 11 | HLS go2rtc, low-latency buffering | first frame, then freezes | 6408 | | |

## Decision (milestone 2 done)
- **Camera playback = go2rtc WebSocket MSE into a `<video>` element, video only.** It remuxes the
  camera's own H.264/H.265 with no transcoding, and the first frame arrives in about 0.3–1 s. AVPlay is kept only for plain HTTP media.
- **Audio** needs AAC: go2rtc + ffmpeg `door: [rtsp://…, "ffmpeg:door#audio=aac"]`. FLAC (go2rtc's default
  PCMU conversion) does not play. This is a later, optional milestone.
- **Relay in production:** the integration proxies the TV's WebSocket through an HA HTTP view
  (`/api/samstream/stream?…`, per-TV secret) to HA's built-in go2rtc (`127.0.0.1:11984/api/ws?src=…`).
  That means no extra service, no origin problem, and no go2rtc port exposed. An external go2rtc/Frigate URL is an option.
- **Direct RTSP (WASM sockets + WASM Player)** is not needed for now, given these results.

**Conclusion so far:** consumer AVPlay on this TV has no RTSP support at all (it fails even on a clean,
auth-free, video-only go2rtc RTSP feed). We need a relay (go2rtc) or a WASM RTSP client.
**Pitfall for the integration:** any go2rtc that the TV app talks to over WebSocket must allow
the `file://` origin (`api: origin: "*"`), and HA's built-in go2rtc does not expose this.

Also check:
- [x] Arabic line at the bottom: letters joined, order correct, "3" and "101" in place
- [x] Overlay visible on top of video (not hidden behind the video plane)
- [x] Fit / Fill (crop) / Stretch work (AVPlay); persistence across restarts: check
- [ ] Back exits cleanly; reopening the app plays again
