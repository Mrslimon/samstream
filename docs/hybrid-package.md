# Samstream hybrid package (one app, one icon)

**Goal (user's choice, 2026-11-03):** ship Samstream as a *single* Tizen package —
one install, one launcher icon — that contains both:

- the **web UI app** (`SmStrm0001.Samstream`, HTML/TS, the camera/message/video UI), and
- the **.NET notifier** (`SmStrm0001.Notifier`, Tizen.NET), which posts native Samsung
  notifications (title + text + chime) that overlay whatever is playing.

They must stay two *applications* because native notifications only work from .NET
(`NotificationManager.Post`); the web `tizen.notification` API is dead on these TVs
(`feature/notification=false`). A Tizen **hybrid package** bundles both under one
package id so the user sees one app.

## What is already in the repo

- Both apps share package id **`SmStrm0001`**:
  - web: `tv-app/public/config.xml` → `<tizen:application id="SmStrm0001.Samstream" package="SmStrm0001">`
  - notifier: `tv-app/notifier-dotnet/tizen-manifest.xml` → `package="SmStrm0001"`, appid `SmStrm0001.Notifier`,
    **`nodisplay="true"`** (no second icon), and `Notifier.csproj` `PackageId=SmStrm0001.Notifier`.
- The web app **starts the notifier** on boot and hands it this TV's secret:
  `tv-app/src/notifier.ts` (`startNotifier`) → `launchAppControl(SmStrm0001.Notifier, extras={samstream_secret})`,
  called from `tv-app/src/main.ts` once `samstream.json` is loaded.
- The notifier accepts that secret in `OnAppControlReceived` (key `samstream_secret`) and also reads
  a stamped `res/shared.key`; with no key it **refuses every LAN post** (fail closed).
- Build helper: `tv-app/scripts/tizen.mjs` `hybrid` step and `npm run tv:hybrid` /
  `npm run tv:hybrid-deploy`. It builds `dist/`, builds the notifier `.tpk`, then
  `tizen package -t wgt -s <profile> -r <notifier.tpk> -- dist`.

## Build it (dev machine with Tizen Studio + .NET SDK)

```
cd tv-app
npm ci
npm run tv:hybrid          # vite build + dotnet build + tizen package -r  -> dist/Samstream.wgt
TV_HOST=192.168.1.11 npm run tv:hybrid-deploy   # also install + run on the TV
```

`-r <tpk>` embeds the notifier inside the web `.wgt`. The output is a single signed
`.wgt` whose manifest lists both applications under `SmStrm0001`.

## On-device spike — what still has to be proven on the TV

This path is **unverified on the lab TVs**. Check each, on the QN800C (192.168.1.11)
and the Frame (192.168.1.22), and record the result in `docs/plan.md` (milestone 24):

1. **Hybrid builds and signs.** `tizen package -t wgt -r …` produces one `.wgt`; HA's
   signer (`aiosamstream.signing.sign_wgt`) can re-sign it per-TV. Watch for the embedded
   `.tpk` carrying its own `author-signature.xml`/`signature1.xml` — they likely must be
   stripped before HA re-signs the outer package (same as signing a standalone `.tpk`).
2. **One icon.** After install, only *Samstream* shows in the launcher (notifier is
   `nodisplay`). One entry in the app list, one uninstall.
3. **Notifier starts from the web app.** Open Samstream; confirm `SmStrm0001.Notifier`
   is running (it was started via `launchAppControl`, not `sdb` — the sideload-launch
   limitation does not apply to an in-package launch).
4. **Secret delivery.** With the web app having started it, a signed HA post to
   `http://<tv>:8181/notify?...` renders a notification; an unsigned/stale/replayed one
   gets 401. `GET /health` answers `ok`.
5. **Resident + overlay.** Switch to YouTube; the notifier (backgrounded) still posts the
   overlay notification without interrupting playback; it survives a standby/wake cycle,
   or HA's `/health` check + reopening Samstream restarts it.

## Open questions / fallbacks

- **Cold `notify` with the web app never opened.** If the notifier is started only by the
  web app, a notification sent when Samstream was never opened this boot has no secret.
  Options: (a) `on-boot="true"` auto-start in the manifest + a **stamped `res/shared.key`**
  so it has the key without the web app; (b) write the secret to the package's **shared data
  dir** (both apps share it under one package id) so the notifier reads it on every boot.
  Decide during the spike; the code already supports both a stamped key and the web-app hand-off.
- **Where HA stamps `res/shared.key` in a hybrid `.wgt`.** The notifier's resources may sit
  under a subdirectory of the hybrid. Confirm the path `Application.Current.DirectoryInfo.Resource`
  resolves to at runtime, and point `notifier.stamp_notifier_key` at the matching entry.
- **If hybrid signing/packaging fails**, fall back to two packages where the web app still
  auto-starts the notifier (same `startNotifier` code, separate install) — the only loss is
  a second (hideable) icon.
