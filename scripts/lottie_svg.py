"""Turn our generated Lottie JSON into a self-animating SVG (SMIL), with captions.

Home Assistant's dialogs render markdown images but run no scripts, so the
config flow and Repairs can't play Lottie; an SVG with <animate> elements plays
anywhere an <img> does (browsers and the companion apps). Handles exactly what
lottie_kit emits. Captions are real SVG text, so Arabic letters join, in Readex
Pro embedded as data URIs (an SVG used as an image loads nothing external).
"""

from __future__ import annotations

import base64
import itertools
import math
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

FONTS = (
    Path(__file__).resolve().parent.parent
    / "tv-app/node_modules/@fontsource/readex-pro/files"
)
TRIM_STEP = 2  # trim paths are sampled every few frames


def _bezier_y(x: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """Solve a CSS-style cubic bezier for progress y at time x."""
    lo, hi = 0.0, 1.0
    for _ in range(30):
        t = (lo + hi) / 2
        bx = 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t**2 * x2 + t**3
        if bx < x:
            lo = t
        else:
            hi = t
    t = (lo + hi) / 2
    return 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t**2 * y2 + t**3


def value_at(p: dict[str, Any], frame: float) -> list[float]:
    """A property's value at `frame`, with the keyframes' easing."""
    if not p.get("a"):
        k = p["k"]
        return k if isinstance(k, list) else [k]
    keys = p["k"]
    if frame <= keys[0]["t"]:
        return keys[0]["s"]
    for a, b in itertools.pairwise(keys):
        if a["t"] <= frame <= b["t"]:
            span = b["t"] - a["t"]
            x = (frame - a["t"]) / span if span else 1
            o, i = a.get("o", {"x": [0], "y": [0]}), a.get("i", {"x": [1], "y": [1]})
            y = _bezier_y(x, o["x"][0], o["y"][0], i["x"][0], i["y"][0])
            return [s + (e - s) * y for s, e in zip(a["s"], b["s"], strict=False)]
    return keys[-1]["s"]


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".") or "0"


def _clamp01(v: float) -> float:
    return min(1.0, max(0.0, v))


class Svg:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.frames = data["op"]
        self.duration = self.frames / data["fr"]

    def _time(self, frame: float) -> float:
        return min(1.0, max(0.0, frame / self.frames))

    def animate(
        self, attr: str, p: dict[str, Any], fmt: Any, *, transform: str | None = None
    ) -> str:
        """SMIL for a keyframed property; holds before/after its keys, eased between."""
        keys = p["k"]
        times, values, splines = [], [], []
        if keys[0]["t"] > 0:
            times.append(0.0)
            values.append(fmt(keys[0]["s"]))
            splines.append("0 0 1 1")
        for index, key in enumerate(keys):
            times.append(self._time(key["t"]))
            values.append(fmt(key["s"]))
            if index < len(keys) - 1:
                o, i = (
                    key.get("o", {"x": [0], "y": [0]}),
                    key.get("i", {"x": [1], "y": [1]}),
                )
                splines.append(
                    f"{_fmt(_clamp01(o['x'][0]))} {_fmt(_clamp01(o['y'][0]))} "
                    f"{_fmt(_clamp01(i['x'][0]))} {_fmt(_clamp01(i['y'][0]))}"
                )
        if times[-1] < 1:
            times.append(1.0)
            values.append(values[-1])
            splines.append("0 0 1 1")
        # keyTimes must strictly increase for spline mode; nudge duplicates.
        for n in range(1, len(times)):
            if times[n] <= times[n - 1]:
                times[n] = times[n - 1] + 1e-4
        times[-1] = 1.0
        common = (
            f'dur="{_fmt(self.duration)}s" repeatCount="indefinite" calcMode="spline" '
            f'keyTimes="{";".join(f"{t:.4f}" for t in times)}" '
            f'keySplines="{";".join(splines)}" values="{";".join(values)}"'
        )
        if transform:
            return f'<animateTransform attributeName="transform" type="{transform}" {common}/>'
        return f'<animate attributeName="{attr}" {common}/>'

    def sampled(self, attr: str, fn: Any) -> str:
        frames = list(range(0, int(self.frames) + 1, TRIM_STEP))
        values = [fn(f) for f in frames]
        times = [self._time(f) for f in frames]
        times[-1] = 1.0
        return (
            f'<animate attributeName="{attr}" dur="{_fmt(self.duration)}s" repeatCount="indefinite" '
            f'keyTimes="{";".join(f"{t:.4f}" for t in times)}" values="{";".join(values)}"/>'
        )

    def visibility(self, start: float, end: float) -> str:
        if start <= 0 and end >= self.frames:
            return ""
        times, values = ["0"], ["hidden" if start > 0 else "visible"]
        if start > 0:
            times.append(f"{self._time(start):.4f}")
            values.append("visible")
        if end < self.frames:
            times.append(f"{self._time(end):.4f}")
            values.append("hidden")
        return (
            f'<animate attributeName="visibility" dur="{_fmt(self.duration)}s" repeatCount="indefinite" '
            f'calcMode="discrete" keyTimes="{";".join(times)}" values="{";".join(values)}"/>'
        )

    # ---- transforms -----------------------------------------------------------------

    def wrap(self, ks: dict[str, Any], inner: str, extra: str = "") -> str:
        """translate(p) rotate(r) scale(s) translate(-a) as nested groups + opacity."""
        anchor = value_at(ks["a"], 0)
        body = f'<g transform="translate({_fmt(-anchor[0])},{_fmt(-anchor[1])})">{inner}</g>'
        parts = [
            ("s", "scale", lambda v: f"{_fmt(v[0] / 100)} {_fmt(v[1] / 100)}"),
            ("r", "rotate", lambda v: _fmt(v[0])),
            ("p", "translate", lambda v: f"{_fmt(v[0])} {_fmt(v[1])}"),
        ]
        for key, kind, fmt in parts:
            p = ks[key]
            if p.get("a"):
                body = f"<g>{self.animate('', p, fmt, transform=kind)}{body}</g>"
            else:
                v = value_at(p, 0)
                identity = (kind == "scale" and v[:2] == [100, 100]) or (
                    kind != "scale" and not any(v[:2])
                )
                if not identity:
                    body = f'<g transform="{kind}({fmt(v)})">{body}</g>'
        o = ks["o"]
        if o.get("a"):
            return f"<g>{self.animate('opacity', o, lambda v: _fmt(v[0] / 100))}{extra}{body}</g>"
        opacity = value_at(o, 0)[0] / 100
        attr = f' opacity="{_fmt(opacity)}"' if opacity < 1 else ""
        return f"<g{attr}>{extra}{body}</g>"

    # ---- shapes ---------------------------------------------------------------------

    @staticmethod
    def color(c: list[float]) -> str:
        return "#{:02x}{:02x}{:02x}".format(
            *tuple(round(_clamp01(x) * 255) for x in c[:3])
        )

    def shapes(self, items: list[dict[str, Any]]) -> str:
        fill_attr, stroke_attr, anims, trim = 'fill="none"', "", "", None
        for it in items:
            if it["ty"] == "fl":
                c = it["c"]
                fill_attr = f'fill="{self.color(value_at(c, 0))}"'
                if c.get("a"):
                    anims += self.animate("fill", c, self.color)
            elif it["ty"] == "st":
                stroke_attr = (
                    f'stroke="{self.color(value_at(it["c"], 0))}" stroke-width="{_fmt(value_at(it["w"], 0)[0])}" '
                    'stroke-linecap="round" stroke-linejoin="round"'
                )
            elif it["ty"] == "tm":
                trim = it
        out = []
        # Lottie draws the first shape on top; SVG draws the last on top.
        for it in reversed(items):
            kind = it["ty"]
            if kind == "gr":
                inner = [x for x in it["it"] if x["ty"] != "tr"]
                tr = next(x for x in it["it"] if x["ty"] == "tr")
                out.append(self.wrap(tr, self.shapes(inner)))
                continue
            if kind not in ("rc", "el", "sh"):
                continue
            geometry = self.geometry(it)
            dash = ""
            if trim is not None:
                dash = ' pathLength="100"' + self.trim_attrs(trim)
            # Animations of the fill go on every shape of the group.
            out.append(
                geometry.replace(
                    "/>",
                    f" {fill_attr} {stroke_attr}{dash}>{anims}{self.trim_anims(trim)}</{geometry.split()[0][1:]}>",
                    1,
                )
            )
        return "".join(out)

    def geometry(self, it: dict[str, Any]) -> str:
        kind = it["ty"]
        if kind == "rc":
            w, h = value_at(it["s"], 0)
            x, y = value_at(it["p"], 0)
            r = value_at(it["r"], 0)[0]
            return f'<rect x="{_fmt(x - w / 2)}" y="{_fmt(y - h / 2)}" width="{_fmt(w)}" height="{_fmt(h)}" rx="{_fmt(r)}"/>'
        if kind == "el":
            w, h = value_at(it["s"], 0)
            x, y = value_at(it["p"], 0)
            rx, ry = w / 2, h / 2
            # Lottie ellipses start at 12 o'clock and run clockwise (matters for trims).
            return (
                f'<path d="M{_fmt(x)},{_fmt(y - ry)} A{_fmt(rx)},{_fmt(ry)} 0 1 1 {_fmt(x)},{_fmt(y + ry)} '
                f'A{_fmt(rx)},{_fmt(ry)} 0 1 1 {_fmt(x)},{_fmt(y - ry)} Z"/>'
            )
        k = it["ks"]["k"]
        d = (
            "M"
            + " L".join(f"{_fmt(px)},{_fmt(py)}" for px, py in k["v"])
            + (" Z" if k["c"] else "")
        )
        return f'<path d="{d}"/>'

    def _dash(self, trim: dict[str, Any], frame: float) -> tuple[float, float]:
        s = value_at(trim["s"], frame)[0]
        e = value_at(trim["e"], frame)[0]
        o = value_at(trim["o"], frame)[0] / 360 * 100
        return max(e - s, 0.0), -(s + o)

    def trim_attrs(self, trim: dict[str, Any]) -> str:
        length, offset = self._dash(trim, 0)
        return (
            f' stroke-dasharray="{_fmt(length)} 200" stroke-dashoffset="{_fmt(offset)}"'
        )

    def trim_anims(self, trim: dict[str, Any] | None) -> str:
        if trim is None or not any(trim[k].get("a") for k in ("s", "e", "o")):
            return ""
        return self.sampled(
            "stroke-dasharray", lambda f: f"{_fmt(self._dash(trim, f)[0])} 200"
        ) + self.sampled("stroke-dashoffset", lambda f: _fmt(self._dash(trim, f)[1]))

    # ---- layers ---------------------------------------------------------------------

    def text_layer(self, layer: dict[str, Any]) -> str:
        doc = layer["t"]["d"]["k"][0]["s"]
        anchor = {0: "start", 1: "end", 2: "middle"}[doc["j"]]
        weight = 500  # the one embedded weight
        return (
            f'<text text-anchor="{anchor}" font-size="{_fmt(doc["s"])}" font-weight="{weight}" '
            f'fill="{self.color(doc["fc"])}">{escape(doc["t"])}</text>'
        )

    def body(self) -> str:
        out = []
        for layer in reversed(self.data["layers"]):
            inner = (
                self.shapes(layer["shapes"])
                if layer["ty"] == 4
                else self.text_layer(layer)
            )
            out.append(
                self.wrap(layer["ks"], inner, self.visibility(layer["ip"], layer["op"]))
            )
        return "".join(out)


_RANGES = {
    "latin": "U+0000-00FF,U+2000-206F",
    "arabic": "U+0600-06FF,U+0750-077F,U+FB50-FDFF,U+FE70-FEFF",
}


def font_css(subsets: tuple[str, ...]) -> str:
    """Readex Pro Medium for the given subsets, as data URIs."""
    faces = []
    for subset in subsets:
        raw = (FONTS / f"readex-pro-{subset}-500-normal.woff2").read_bytes()
        faces.append(
            f"@font-face{{font-family:'Readex Pro';unicode-range:{_RANGES[subset]};"
            f"src:url(data:font/woff2;base64,{base64.b64encode(raw).decode()}) format('woff2')}}"
        )
    return "".join(faces)


def wrap_lines(text: str, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines


def to_svg(
    data: dict[str, Any],
    *,
    captions: list[str] | None = None,
    rtl: bool = False,
    background: str = "#f3f5f8",
    caption_color: str = "#18202b",
    display_width: int = 480,
    caption_size: float = 38,
    chars_per_line: int = 38,
) -> str:
    """The SVG text. `captions` (one per marker) go in a band under the drawing."""
    svg = Svg(data)
    w, h = data["w"], data["h"]
    band = 0
    caption_svg = ""
    if captions:
        markers = data.get("markers", [])
        line_height = caption_size * 1.3
        texts = [wrap_lines(c, chars_per_line) for c in captions]
        lines_max = max(len(t) for t in texts)
        band = int(line_height * lines_max + caption_size * 1.2)
        for marker, lines in zip(markers, texts, strict=True):
            y0 = h + (band - line_height * len(lines)) / 2 + caption_size * 0.85
            spans = "".join(
                f'<tspan x="{w / 2}" y="{_fmt(y0 + n * line_height)}">{escape(line)}</tspan>'
                for n, line in enumerate(lines)
            )
            direction = ' direction="rtl"' if rtl else ""
            text = (
                f'<text text-anchor="middle" font-size="{_fmt(caption_size)}" font-weight="500" '
                f'fill="{caption_color}"{direction}>{spans}</text>'
            )
            caption_svg += f"<g>{svg.visibility(marker['tm'], marker['tm'] + marker['dr'])}{text}</g>"
    total_h = h + band
    has_text = bool(captions) or any(layer["ty"] == 5 for layer in data["layers"])
    subsets = ("latin", "arabic") if rtl else ("latin",)
    style = f"<style>{font_css(subsets)}</style>" if has_text else ""
    height = math.ceil(display_width * total_h / w)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{display_width}" height="{height}" '
        f'viewBox="0 0 {w} {total_h}" font-family="\'Readex Pro\',Tahoma,sans-serif">'
        f"{style}"
        f'<rect width="{w}" height="{total_h}" rx="24" fill="{background}"/>'
        f"{svg.body()}{caption_svg}</svg>"
    )
