# Changelog

Every release's section below is what Home Assistant shows in the update dialog.

## 0.3.0 (2026-11-28)

### 🪟 The camera in a corner, over what you are watching

**This changes what `play_stream` does by default.** When something is already playing, the camera
now appears in a bordered box in a corner. Nothing pauses or closes, the remote keeps working, and
the box goes away after `duration`, or after 30 seconds.

- **To keep the full-screen camera:** turn off *Show cameras in a corner* under
  **Configure → Cameras**, or add `corner: false` to the action. The dashboard card has a
  *Full screen* tick box.
- **Settings** (Configure → Cameras): corner, box size, time on screen, text position and text
  size. The defaults are top right, a large box and large text. An action can set `corner`,
  `corner_position` and `corner_size`.
- **The TV app must update too** (0.14.0). With *auto-update* on it installs by itself; otherwise
  accept the *Samstream TV app* update, or press **Install Samstream app**. Until then the camera
  opens full screen.
- The old *TV picture in a corner* mode (Live TV and HDMI only) is replaced. Automations that
  still send `tv_corner` keep working: `off` means full screen, a corner name picks the corner.
- With the TV off the camera opens full screen, and so does the Home screen when local control
  can tell it apart.

The box shows about 8 pictures a second without sound, and the TV remote cannot close it. Tried on
a QN800C over YouTube, Live TV and HDMI; **Netflix, The Frame and other models are untried**. If
nothing appears on your TV, use `corner: false` and please open an issue.

### 💬 Text over cameras

- Messages over a camera now sit at the **bottom** of the screen instead of the middle. Position
  (bottom, middle, top) and size (normal, large, extra large) are settings. In the corner box the
  text is at the top or the bottom.

### 🔊 Optical soundbars (a test for issue #5)

With local control on and the sound going to the **optical** output, the volume slider is now hidden
and only volume up and down are offered, because the TV reports volume 0 there. The media player
also has `sound_output` and `sound_output_type` attributes. **Not yet confirmed on a real optical
soundbar.**

## 0.2.8 (2026-11-26)

### 🔢 Local control accepts shorter TV PINs

- **Fixed:** local control setup rejected any PIN that was not 8 digits. A 2026 S90H shows
  **4 digits**, and setup now accepts 4 to 8.

Confirmed by a user: local control sets up on that S90H. TVs with an 8-digit PIN work as before.

Also: the README now shows how to [play a camera only when the TV is already
on](https://github.com/Mrslimon/samstream#-any-home-assistant-camera-on-your-tv).

## 0.2.7 (2026-11-26)

### ↩️ Back to your HDMI input after the camera

For TVs with local control on (the *Local control connected* sensor is on):

- **Fixed:** after a camera, message or video over **HDMI or Live TV**, the TV now switches back
  to that input, both when Home Assistant ends it and when you press Back. Before, it could
  reopen the last app or stay on an empty screen.
- **Fixed:** *TV picture in a corner* is no longer turned off because the TV still listed the
  last app as visible while an input was on screen.

Confirmed by a user on an S90H: returning to the previous screen works as expected.

Without local control nothing changes: Samsung does not tell Home Assistant which input is on.

Also: the `npx samstream-signin` sign-in helper is now on npm (the command used to fail with
a 404).

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
