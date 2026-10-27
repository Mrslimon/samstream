"""Generate Samstream's Lottie animations (loading, pairing, Developer Mode guide).

Usage: uv run python scripts/make_animations.py
Writes tv-app/src/animations/*.json. Captions are NOT drawn in the animations
(lottie-web draws text letter by letter, which breaks Arabic joining): each
step is a Lottie marker, and the page shows that step's caption itself.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lottie_kit import (
    EASE_OUT,
    LINEAR,
    POP,
    Composition,
    ellipse,
    fill,
    fill_keys,
    group,
    path,
    rect,
    stroke,
    trim,
)
from lottie_svg import to_svg

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tv-app" / "src" / "animations"
# Animated SVGs for Home Assistant's dialogs (config flow, Repairs).
SVG_OUT = ROOT / "custom_components" / "samstream" / "frontend" / "animations"

ACCENT = "#2e86d6"
ACCENT_SOFT = "#cfe3f6"
INK = "#18202b"
MUTED = "#667487"
WELL = "#e9edf2"
SURFACE = "#ffffff"
SCREEN = "#0b1420"
SCREEN_TILE = "#1a2636"
SUCCESS = "#1fa463"
REMOTE = "#2a2f36"
REMOTE_KEY = "#454c56"


def loading() -> Composition:
    """Three dots bouncing in turn, the familiar loader (1.2 s loop)."""
    c = Composition("loading", 300, 150, 36)
    for index in range(3):
        delay = index * 6
        c.shape(
            f"dot{index}",
            group(ellipse([34, 34]), fill(ACCENT)),
            position=[
                (delay, (90 + index * 60, 92)),
                (delay + 8, (90 + index * 60, 58)),
                (delay + 16, (90 + index * 60, 92)),
            ],
            opacity=[(delay, 45), (delay + 8, 100), (delay + 16, 45)],
            scale=[(delay, (90, 90)), (delay + 8, (105, 105)), (delay + 16, (90, 90))],
        )
    return c


def _tv_icon(x: float, y: float) -> dict:
    return group(
        group(rect([150, 96], 14), stroke(INK, 7), name="screen"),
        group(path([(-34, 66), (34, 66)]), stroke(INK, 7), name="stand"),
        group(path([(0, 48), (0, 66)]), stroke(INK, 7), name="neck"),
        name="tv",
        position=(x, y),
    )


def _home_icon(x: float, y: float) -> dict:
    return group(
        group(
            path(
                [(-56, 6), (0, -48), (56, 6), (40, 6), (40, 54), (-40, 54), (-40, 6)],
                closed=True,
            ),
            stroke(INK, 7),
        ),
        group(rect([26, 34], 4, position=(0, 37)), fill(ACCENT)),
        name="home",
        position=(x, y),
    )


def pairing() -> Composition:
    """TV and Home Assistant with signal dots between; then a check pops.

    Markers: "connecting" (0-90, loop it while pairing) then "paired" (90-150).
    """
    c = Composition("pairing", 600, 300, 150)
    # Check badge (top): pops in at 95.
    c.shape(
        "check",
        group(
            path([(-18, 0), (-5, 13), (20, -14)]),
            stroke(SURFACE, 9),
            trim(end=[(105, 0), (125, 100)]),
            name="tick",
        ),
        group(ellipse([84, 84]), fill(SUCCESS), name="badge"),
        position=(300, 150),
        scale=[(90, (0, 0)), (105, (100, 100))],
        ease=POP,
        start=90,
    )
    for index in range(5):
        x = 230 + index * 35
        offset = index * 8
        c.shape(
            f"dot{index}",
            group(ellipse([16, 16]), fill(ACCENT)),
            position=(x, 150),
            scale=[
                (offset, (60, 60)),
                (offset + 15, (130, 130)),
                (offset + 30, (60, 60)),
                (offset + 45, (60, 60)),
                (offset + 60, (130, 130)),
                (offset + 75, (60, 60)),
            ],
            opacity=[
                (offset, 30),
                (offset + 15, 100),
                (offset + 30, 30),
                (90, 30),
                (98, 0),
            ],
            end=100,
        )
    c.shape("tv", _tv_icon(0, 0), position=(120, 140))
    c.shape("home", _home_icon(0, 0), position=(480, 140))
    c.markers = [("connecting", 0, 90), ("paired", 90, 60)]  # type: ignore[attr-defined]
    return c


def connect() -> Composition:
    """A TV settings toggle flipping on — the Wake-on-LAN step of connecting.

    No text (lottie-web draws it letter by letter, which breaks Arabic joining):
    a faux settings row with a toggle a pointer taps from off to on.
    """
    c = Composition("connect", 600, 300, 72)
    off, on = 487, 523  # the knob's x when off / on; it slides at frame 24-30
    # Pointer: moves in from the corner and presses the toggle.
    c.shape(
        "cursor",
        group(ellipse([26, 26]), fill(INK), name="dot"),
        position=[(0, (620, 250)), (18, (505, 150)), (72, (505, 150))],
        scale=[(18, (100, 100)), (24, (66, 66)), (30, (100, 100))],
        opacity=[(0, 0), (8, 100), (60, 100), (70, 0)],
        ease=EASE_OUT,
    )
    c.shape(
        "knob",
        group(ellipse([30, 30]), fill(SURFACE), stroke(MUTED, 2), name="k"),
        position=[(0, (off, 150)), (24, (off, 150)), (30, (on, 150)), (72, (on, 150))],
        ease=POP,
    )
    c.shape(
        "pill",
        group(
            rect([74, 40], 20),
            fill_keys([(0, WELL), (24, WELL), (30, ACCENT), (72, ACCENT)]),
            name="track",
        ),
        position=(505, 150),
    )
    c.shape("label1", group(rect([150, 14], 7), fill(MUTED)), position=(360, 128))
    c.shape("label2", group(rect([96, 14], 7), fill(WELL)), position=(333, 160))
    c.shape(
        "panel",
        group(rect([300, 150], 24), fill(SURFACE), name="fill"),
        group(rect([300, 150], 24), stroke(WELL, 5), name="edge"),
        position=(420, 150),
    )
    c.shape("tv", _tv_icon(0, 0), position=(135, 150))
    return c


def paired() -> Composition:
    """A success check that pops in — shown when the TV has connected to HA."""
    c = Composition("paired", 300, 200, 60)
    c.shape(
        "check",
        group(
            path([(-24, 2), (-7, 19), (28, -20)]),
            stroke(SURFACE, 12),
            trim(end=[(10, 0), (40, 100)]),
            name="tick",
        ),
        group(ellipse([120, 120]), fill(SUCCESS), name="badge"),
        position=(150, 100),
        scale=[(0, (0, 0)), (16, (115, 115)), (24, (100, 100))],
        ease=POP,
        start=0,
    )
    return c


# ---- Developer Mode guide -------------------------------------------------------------
# 960x540 @30 fps. TV on the left, the remote on the right; five steps, each a marker.
W, H = 960, 540
TV_X, TV_Y, TV_W, TV_H = 370, 250, 600, 338
REMOTE_X, REMOTE_Y = 815, 270
STEPS = [  # name, start, length
    ("open_apps", 0, 100),
    ("press_123", 100, 90),
    ("type_12345", 190, 170),
    ("switch_on", 360, 160),
    ("hold_power", 520, 200),
    ("turn_on", 720, 170),
]
FRAMES = 890
# Restart: Power held 5 s (150 frames) from HOLD_START, then pressed again to turn on.
HOLD_START, HOLD_END, POWER_ON = 545, 695, 745


def _press(frame: float) -> list:
    """Scale keys for a quick button press at `frame`."""
    return [(frame - 1, (100, 100)), (frame + 4, (82, 82)), (frame + 10, (100, 100))]


def _ripple(
    c: Composition, name: str, x: float, y: float, frames: list[float], size: float = 46
) -> None:
    """Accent rings expanding from a remote button at each press."""
    for index, frame in enumerate(frames):
        c.shape(
            f"{name}_ripple{index}",
            group(ellipse([size, size]), stroke(ACCENT, 4)),
            position=(x, y),
            scale=[(frame, (60, 60)), (frame + 18, (170, 170))],
            opacity=[(frame, 100), (frame + 18, 0)],
            ease=EASE_OUT,
            start=frame,
            end=frame + 19,
        )


def _remote(c: Composition) -> None:
    ok_presses = [40, 70, 495]
    nav_presses = [20, 460, 478]
    num_presses = [130, 160]
    power_press = POWER_ON
    _ripple(c, "num", REMOTE_X + 26, REMOTE_Y + 110, num_presses, 40)
    _ripple(c, "ok", REMOTE_X, REMOTE_Y - 40, ok_presses)
    _ripple(c, "power", REMOTE_X, REMOTE_Y - 175, [HOLD_START, power_press], 36)
    # The 5-second hold: a ring fills around Power while a countdown runs.
    c.shape(
        "hold_ring",
        group(
            ellipse([54, 54]),
            stroke(ACCENT, 6),
            trim(end=[(HOLD_START, 0), (HOLD_END, 100)]),
        ),
        position=(REMOTE_X, REMOTE_Y - 175),
        ease=LINEAR,
        start=HOLD_START,
        end=HOLD_END + 10,
    )
    for second in range(5):
        shown = HOLD_START + second * 30
        c.text(
            f"count{second}",
            str(5 - second),
            size=30,
            color=ACCENT,
            weight="Medium",
            position=(REMOTE_X, REMOTE_Y - 222),
            start=shown,
            end=shown + 30,
        )
    c.text(
        "num_label",
        "123",
        size=15,
        color=SURFACE,
        weight="Medium",
        position=(REMOTE_X + 26, REMOTE_Y + 115),
    )
    keys = [
        # name, shape, position, presses
        ("power", ellipse([30, 30]), (0, -175), [power_press]),  # see hold below
        ("mic", ellipse([26, 26]), (0, -125), []),
        ("ok", ellipse([46, 46]), (0, -40), ok_presses),
        ("back", ellipse([30, 30]), (-30, 50), []),
        ("home", ellipse([30, 30]), (30, 50), []),
        ("play", ellipse([30, 30]), (-26, 110), []),
        ("num", ellipse([40, 40]), (26, 110), num_presses),
        ("vol", rect([30, 64], 15), (-28, 168), []),
        ("ch", rect([30, 64], 15), (28, 168), []),
    ]
    for name, shape, (dx, dy), presses in keys:
        color = ACCENT if name in {"num", "ok"} else REMOTE_KEY
        scale: object = (100, 100)
        if name == "power":
            # Held down for the whole 5 s, then a normal press to turn on.
            scale = [
                (HOLD_START - 1, (100, 100)),
                (HOLD_START + 4, (82, 82)),
                (HOLD_END, (82, 82)),
                (HOLD_END + 6, (100, 100)),
                *_press(power_press),
            ]
        elif presses:
            scale = [k for frame in presses for k in _press(frame)]
        # The power symbol: a ring open at the top with a line through the gap.
        glyph = (
            [
                group(
                    ellipse([15, 15]),
                    stroke(SURFACE, 2.6),
                    trim(start=10, end=90),
                    name="power_ring",
                ),
                group(
                    path([(0, -10), (0, -2)]), stroke(SURFACE, 2.6), name="power_bar"
                ),
            ]
            if name == "power"
            else []
        )
        c.shape(
            f"key_{name}",
            *glyph,
            group(
                shape,
                fill(color)
                if name != "num"
                else fill_keys(
                    [
                        (0, REMOTE_KEY),
                        (95, REMOTE_KEY),
                        (105, ACCENT),
                        (175, ACCENT),
                        (185, REMOTE_KEY),
                    ]
                ),
            ),
            position=(REMOTE_X + dx, REMOTE_Y + dy),
            scale=scale,
        )
    # D-pad ring around OK, with a nudge on navigation presses.
    c.shape(
        "dpad",
        group(ellipse([118, 118]), stroke(REMOTE_KEY, 22)),
        position=(REMOTE_X, REMOTE_Y - 40),
        scale=[k for frame in nav_presses for k in _press(frame)],
    )
    c.shape(
        "remote_body",
        group(rect([124, 452], 62), fill(REMOTE)),
        position=(REMOTE_X, REMOTE_Y),
    )


def _home_bar(c: Composition) -> None:
    """Step 1: the Home bar, focus moves to Apps, then it opens."""
    top = TV_Y + TV_H / 2 - 62
    left = TV_X - TV_W / 2 + 70
    end = 100
    c.text(
        "apps_label",
        "Apps",
        size=17,
        color=SURFACE,
        weight="Medium",
        position=(left, top + 6),
        opacity=[(80, 100), (95, 0)],
        end=end,
    )
    for index in range(6):
        x = left + index * 92
        tile_color = (
            fill_keys([(0, SCREEN_TILE), (18, SCREEN_TILE), (24, ACCENT)])
            if index == 0
            else fill(SCREEN_TILE)
        )
        c.shape(
            f"bar_tile{index}",
            group(rect([80, 52], 10), tile_color),
            position=(x, top),
            scale=[
                (18, (100, 100)),
                (26, (112, 112)),
                (40, (112, 112)),
                (46, (100, 100)),
            ]
            if index == 0
            else (100, 100),
            opacity=[(80, 100), (95, 0)],
            end=end,
        )


def _apps_grid(c: Composition) -> None:
    """Step 2: the Apps panel (shown until the dialog in step 4)."""
    start, end = 85, 380
    left, top = TV_X - 200, TV_Y - 80
    for row in range(2):
        for col in range(5):
            index = row * 5 + col
            appear = start + index * 2
            c.shape(
                f"app{index}",
                group(rect([70, 70], 14), fill(SCREEN_TILE)),
                position=(left + col * 100, top + row * 100),
                opacity=[(appear, 0), (appear + 8, 100), (360, 100), (375, 25)],
                scale=[(appear, (80, 80)), (appear + 10, (100, 100))],
                start=start,
                end=end,
            )
    c.text(
        "apps_title",
        "Apps",
        size=24,
        color=SURFACE,
        weight="Medium",
        justify=0,
        position=(TV_X - TV_W / 2 + 34, TV_Y - TV_H / 2 + 44),
        opacity=[(start, 0), (start + 10, 100)],
        start=start,
        end=end,
    )


def _keypad(c: Composition) -> None:
    """Step 3: the on-screen number pad; 1 2 3 4 5 light up and fill the dots."""
    start, end = 180, 365
    presses = [205, 232, 259, 286, 313]
    cx, cy = TV_X + 150, TV_Y + 20
    labels = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", ""]
    for index, label in enumerate(labels):
        row, col = divmod(index, 3)
        x, y = cx + (col - 1) * 58, cy + (row - 1.5) * 50
        press = presses[int(label) - 1] if label in "12345" and label else None
        color = (
            fill_keys(
                [
                    (0, WELL),
                    (press - 2, WELL),
                    (press, ACCENT),
                    (press + 14, ACCENT),
                    (press + 20, WELL),
                ]
            )
            if press
            else fill(WELL)
        )
        if label:
            c.text(
                f"pad_label{label}",
                label,
                size=22,
                color=INK,
                weight="Medium",
                position=(x, y + 8),
                opacity=[(start, 0), (start + 10, 100), (350, 100), (362, 0)],
                start=start,
                end=end,
            )
        c.shape(
            f"pad_key{index}",
            group(rect([50, 42], 9), color),
            position=(x, y),
            scale=_press(press) if press else (100, 100),
            opacity=[(start, 0), (start + 10, 100), (350, 100), (362, 0)],
            start=start,
            end=end,
        )
    for index, press in enumerate(presses):
        c.shape(
            f"pin_dot{index}",
            group(
                ellipse([14, 14]),
                fill_keys([(0, MUTED), (press, MUTED), (press + 3, ACCENT)]),
            ),
            position=(cx - 64 + index * 32, cy - 128),
            scale=[
                (press, (100, 100)),
                (press + 5, (150, 150)),
                (press + 12, (100, 100)),
            ],
            opacity=[(start, 0), (start + 10, 100), (350, 100), (362, 0)],
            start=start,
            end=end,
        )
    c.shape(
        "pad_panel",
        group(rect([210, 300], 18), fill(SURFACE)),
        position=[
            (start, (cx, cy + 260)),
            (start + 14, (cx, cy - 10)),
            (350, (cx, cy - 10)),
            (362, (cx, cy + 260)),
        ],
        ease=EASE_OUT,
        start=start,
        end=end,
    )


# The Host PC IP field is four boxes, one per part, typed one after another.
EXAMPLE_IP = ("192", "168", "1", "5")
IP_BOX_W, IP_BOX_GAP = 66, 20
IP_TYPED = (412, 428, 444, 460)  # when each part appears


def _ip_boxes(c: Composition, x: float, y: float, fade: list, *, rtl: bool) -> None:
    """The four IP boxes, the focus moving along as each part is typed.

    On a TV whose menu is right-to-left (Arabic) the boxes run the other way:
    the parts go in reversed (5 1 168 192), or the TV stores the IP backwards.
    """
    parts = EXAMPLE_IP[::-1] if rtl else EXAMPLE_IP
    step = IP_BOX_W + IP_BOX_GAP
    xs = [x + (n - 1.5) * step for n in range(4)]
    start, end = 365, 525
    if rtl:
        # A right-to-left arrow above the boxes, beside the field's label.
        c.shape(
            "dlg_ip_rtl",
            group(path([(160, 0), (40, 0)]), stroke(ACCENT, 3)),
            group(path([(50, -8), (40, 0), (50, 8)]), stroke(ACCENT, 3)),
            position=(x, y - 32),
            opacity=fade,
            start=start,
            end=end,
        )
    for n, (bx, part) in enumerate(zip(xs, parts, strict=True)):
        typed = IP_TYPED[n]
        c.text(
            f"dlg_ip_part{n}",
            part,
            size=22,
            color=INK,
            weight="Medium",
            position=(bx, y + 8),
            opacity=[(0, 0), (typed, 0), (typed + 3, 100), (505, 100), (515, 0)],
            start=start,
            end=end,
        )
    for n in range(3):
        c.shape(
            f"dlg_ip_dot{n}",
            group(ellipse([5, 5]), fill(MUTED)),
            position=(x + (n - 1) * step, y + 14),
            opacity=fade,
            start=start,
            end=end,
        )
    # Focus: an accent frame that jumps to the next box after each part.
    focus = [(0, (xs[0], y))]
    for n in range(3):  # hold, then jump quickly to the next box
        focus += [(IP_TYPED[n] + 5, (xs[n], y)), (IP_TYPED[n] + 9, (xs[n + 1], y))]
    c.shape(
        "dlg_ip_focus",
        group(rect([IP_BOX_W, 46], 8), stroke(ACCENT, 4)),
        position=focus,
        opacity=[(0, 0), (404, 0), (408, 100), (472, 100), (476, 0)],
        ease=EASE_OUT,
        start=start,
        end=end,
    )
    for n, bx in enumerate(xs):
        c.shape(
            f"dlg_ip_box{n}",
            group(rect([IP_BOX_W, 46], 8), stroke(MUTED, 3)),
            position=(bx, y),
            opacity=fade,
            start=start,
            end=end,
        )


def _dialog(c: Composition, *, rtl: bool = False) -> None:
    """Step 4: Developer mode On, the HA IP typed in four boxes, OK."""
    start, end = 365, 525
    cx, cy = TV_X, TV_Y
    fade = [(start, 0), (start + 10, 100), (505, 100), (515, 0)]
    # OK button (highlighted when pressed at 495).
    c.text(
        "dlg_ok_label",
        "OK",
        size=18,
        color=INK,
        weight="Medium",
        position=(cx + 120, cy + 96),
        opacity=fade,
        start=start,
        end=end,
    )
    c.shape(
        "dlg_ok",
        group(rect([120, 40], 20), fill_keys([(0, WELL), (488, WELL), (495, ACCENT)])),
        position=(cx + 120, cy + 90),
        scale=_press(495),
        opacity=fade,
        start=start,
        end=end,
    )
    _ip_boxes(c, cx - 20, cy + 30, fade, rtl=rtl)
    # Toggle: knob slides right and the track turns accent at 395.
    c.shape(
        "dlg_knob",
        group(ellipse([30, 30]), fill(SURFACE)),
        position=[(390, (cx + 108, cy - 40)), (400, (cx + 140, cy - 40))],
        opacity=fade,
        start=start,
        end=end,
    )
    c.shape(
        "dlg_track",
        group(rect([74, 38], 19), fill_keys([(0, MUTED), (392, MUTED), (400, ACCENT)])),
        position=(cx + 124, cy - 40),
        scale=_press(395),
        opacity=fade,
        start=start,
        end=end,
    )
    c.text(
        "dlg_title",
        "Developer mode",
        size=26,
        color=INK,
        weight="Medium",
        justify=0,
        position=(cx - 180, cy - 92),
        opacity=fade,
        start=start,
        end=end,
    )
    c.text(
        "dlg_on",
        "On",
        size=20,
        color=INK,
        justify=0,
        position=(cx - 180, cy - 33),
        opacity=fade,
        start=start,
        end=end,
    )
    c.text(
        "dlg_ip_label",
        "Host PC IP",
        size=16,
        color=MUTED,
        justify=0,
        position=(cx - 184, cy - 2),
        opacity=fade,
        start=start,
        end=end,
    )
    c.shape(
        "dlg_card",
        group(rect([420, 260], 20), fill(SURFACE)),
        position=(cx, cy),
        scale=[(start, (90, 90)), (start + 12, (100, 100))],
        opacity=fade,
        ease=EASE_OUT,
        start=start,
        end=end,
    )


def _restart(c: Composition) -> None:
    """Steps 5-6: hold Power 5 s until the TV is off, then turn it on: Samsung, Tizen OS."""
    boot = POWER_ON + 12
    # Boot screen: SAMSUNG in the middle, "Tizen OS" in the corner, then the picture.
    c.text(
        "boot_tizen",
        "Tizen OS",
        size=18,
        color="#c9d1db",
        justify=1,
        position=(TV_X + TV_W / 2 - 24, TV_Y + TV_H / 2 - 22),
        opacity=[
            (boot + 25, 0),
            (boot + 40, 100),
            (FRAMES - 30, 100),
            (FRAMES - 15, 0),
        ],
        start=boot,
    )
    c.text(
        "boot_samsung",
        "SAMSUNG",
        size=44,
        color=SURFACE,
        weight="Medium",
        position=(TV_X, TV_Y + 16),
        opacity=[(boot, 0), (boot + 18, 100), (FRAMES - 30, 100), (FRAMES - 15, 0)],
        start=boot,
    )
    c.shape(
        "blackout",
        group(rect([TV_W, TV_H], 6), fill("#000000")),
        position=(TV_X, TV_Y),
        opacity=[
            (HOLD_END - 10, 0),
            (HOLD_END + 4, 100),
            (FRAMES - 30, 100),
            (FRAMES - 10, 0),
        ],
        start=HOLD_END - 12,
    )


def developer_mode(*, rtl: bool = False) -> Composition:
    """The guide; `rtl` types the IP parts reversed, as an Arabic TV menu needs."""
    c = Composition("developer-mode", W, H, FRAMES)
    _remote(c)
    _restart(c)
    _dialog(c, rtl=rtl)
    _keypad(c)
    _apps_grid(c)
    _home_bar(c)
    # TV: screen, bezel, stand.
    c.shape(
        "tv_screen", group(rect([TV_W, TV_H], 6), fill(SCREEN)), position=(TV_X, TV_Y)
    )
    c.shape(
        "tv_bezel",
        group(rect([TV_W + 16, TV_H + 16], 12), fill(INK)),
        position=(TV_X, TV_Y),
    )
    c.shape(
        "tv_stand",
        group(rect([180, 10], 5), fill(INK)),
        group(rect([16, 30], 2, position=(0, -18)), fill(INK)),
        position=(TV_X, TV_Y + TV_H / 2 + 40),
    )
    c.markers = [(name, start, length) for name, start, length in STEPS]  # type: ignore[attr-defined]
    return c


def lottie(comp: Composition) -> dict:
    data = comp.to_json()
    data["markers"] = [
        {"tm": t, "cm": name, "dr": d} for name, t, d in getattr(comp, "markers", [])
    ]
    return data


def write(comp: Composition) -> Path:
    data = lottie(comp)
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{comp.name}.json"
    target.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return target


CAPTIONS = {
    "en": [
        "Open Apps from Home",
        "In Apps, press the 123 button",
        "Type 1 2 3 4 5 on the number pad",
        "Switch it On, type Home Assistant's IP, one part per box, then OK",
        "Hold Power for 5 seconds until the TV turns off",
        "Turn the TV on again: Samsung and Tizen OS appear",
    ],
    "ar": [
        "افتح التطبيقات من الشاشة الرئيسية",
        "في التطبيقات، اضغط زر 123",
        "اكتب 1 2 3 4 5 على لوحة الأرقام",
        "فعّله، واكتب عنوان Home Assistant بالعكس (المربعات معكوسة)، ثم موافق",
        "اضغط على زر التشغيل 5 ثوانٍ حتى ينطفئ التلفاز",
        "شغّل التلفاز من جديد، فيظهر Tizen OS في الزاوية",
    ],
}


def write_svg(name: str, svg: str) -> Path:
    SVG_OUT.mkdir(parents=True, exist_ok=True)
    target = SVG_OUT / name
    target.write_text(svg, encoding="utf-8")
    return target


if __name__ == "__main__":
    for build in (loading, pairing, paired, connect, developer_mode):
        path_written = write(build())
        print(f"{path_written.name}: {path_written.stat().st_size} bytes")
    data = {
        p.stem: json.loads(p.read_text(encoding="utf-8")) for p in OUT.glob("*.json")
    }
    written = [
        write_svg("pairing.svg", to_svg(data["pairing"], display_width=360)),
        write_svg("paired.svg", to_svg(data["paired"], display_width=160)),
        write_svg("connect.svg", to_svg(data["connect"], display_width=360)),
        write_svg("loading.svg", to_svg(data["loading"], display_width=120)),
    ]
    for lang, captions in CAPTIONS.items():
        rtl = lang == "ar"
        guide = lottie(developer_mode(rtl=True)) if rtl else data["developer-mode"]
        written.append(
            write_svg(
                f"developer-mode.{lang}.svg",
                to_svg(guide, captions=captions, rtl=rtl),
            )
        )
    for item in written:
        print(f"{item.name}: {item.stat().st_size} bytes")
