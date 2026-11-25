# Changelog

Every release's section below is what Home Assistant shows in the update dialog.

## 0.2.6 (2026-11-26)

### ⚡ Local control is instant now, even after the TV sits quiet

If your app sensor only moved at every check interval with local control on, this fixes it.

- **Fixed:** a connected TV with nothing new to report was treated as disconnected after a
  minute. The local-control sensor turned off, its entities became unavailable and everything
  fell back to polling.
- **Fixed:** a TV that signed in again within a few seconds could get a connection that never
  subscribed to changes.
- **Better:** channel and picture and sound mode, which the TV does not push, are re-read
  over local control every 20 seconds instead of only when it connects.
- **Fixed:** `app_id` now stays the same ID that `samstream.launch_app` uses (for YouTube,
  `111299001912`) whether it comes from polling or local control. If an automation matched the
  Tizen package ID (like `9Ur5IzDKqV.TizenYouTube`), change it to the number.

Volume and mute on the media player still follow the check interval.

## 0.2.5 (2026-11-25)

### 🔔 Native TV notifications as their own action

- **New:** `samstream.show_notification` shows Samsung's corner notification, with its chime,
  over whatever is playing. Nothing pauses or closes.
- A new README with demo clips of every feature.

## 0.2.4 (2026-11-19)

- **New:** choose how often Home Assistant checks the TV (3 to 300 seconds).
- **Better:** with local control, on and off are picked up right away.
- **Better:** door cameras start faster.
- 🎨 New icon and logo.

## 0.2.3 (2026-11-10)

- 🔒 Security hardening: tighter checks on file paths and `play_stream`, no more reaching into
  go2rtc, and more secrets removed from diagnostics.

## 0.2.2 (2026-11-04)

- **Fixed:** local-control pairing finds the TV again when a retry is needed.

## 0.2.1 (2026-11-04)

- **Fixed:** camera video whose H.264 level the TV cannot play is converted automatically.
- **Better:** Left and Right in camera setup step through a fixed, ordered list from the start.
- New icon, and the license is now Apache-2.0.

## 0.1.0 (2026-11-04)

- 🎉 First public release.
