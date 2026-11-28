# Playback probe (reference)

Contributed by [@Blacksuite](https://github.com/Blacksuite).

Samsung TVs don't tell anyone whether the app on screen is playing or paused. This
small headless .NET service gets that state by watching the TV's video decoder.

## How it works

The decoder raises a hardware interrupt named `sdp_dv` in `/proc/interrupts`, and any
app can read that file. The service samples the counter every 250 ms, averages the
rate over one second, and sorts it into three states:

| State | Measured rate (QE55Q64D, Tizen 9) | Threshold |
|---|---|---|
| `playing` | ~50 per second | 38 or more |
| `paused` | ~24 per second | 14 or more |
| `none` | 0 | below 14 |

It POSTs `{"state": "...", "rate": N}` to a Home Assistant webhook whenever the state
changes, plus a heartbeat every 30 s. Because it reads the decoder directly, it works
with every app (Netflix, YouTube, Plex, Live TV, HDMI) without asking the app anything.

## Notes

- **The thresholds need calibrating.** They were measured on one model. On another
  TV, check the `rate` field in the webhook payload while playing and while paused,
  then adjust `PlayingAbove` and `PausedAbove`.
- **Short blips.** You get a paused reading of about 0.5 s when video starts or stops,
  and trailers play on their own. Add a short `for:` on the automations that use it.
- **Starting it.** `on-boot` and `auto-restart` are set, but after a full TV restart
  the service didn't always come back. A one-line web app that calls
  `tizen.application.launch("org.samstream.playbackprobe")` fixes that. Home Assistant
  opens that app whenever the heartbeat stops arriving.
- **The webhook URL** is a constant in `Program.cs`. Set it before building. In
  Samstream it would fit naturally into the existing notifier: it could expose the
  state on its `:8181` listener instead.

## Home Assistant side (example)

```yaml
triggers:
  - trigger: webhook
    webhook_id: CHANGE_ME
    allowed_methods: [POST]
    local_only: true
conditions:
  - condition: template
    value_template: "{{ trigger.json.state in ['none', 'paused', 'playing'] }}"
actions:
  - action: input_select.select_option
    target:
      entity_id: input_select.tv_video_state
    data:
      option: "{{ trigger.json.state }}"
```
