"""A tiny Lottie (bodymovin JSON) builder: shape and text layers, keyframes, easing.

Enough for flat UI animations: rectangles, ellipses, paths, fills, strokes,
trim paths, groups with their own transform, and text layers (rendered by
lottie-web with the page's fonts, so Readex Pro covers Arabic).
"""

from __future__ import annotations

from typing import Any

Value = float | list[float]
Keys = list[tuple[float, Value]]

EASE = ({"x": [0.42], "y": [0]}, {"x": [0.58], "y": [1]})
EASE_OUT = ({"x": [0.2], "y": [0]}, {"x": [0.2], "y": [1]})
POP = ({"x": [0.3], "y": [0]}, {"x": [0.4], "y": [1.6]})  # overshoots
LINEAR = ({"x": [0], "y": [0]}, {"x": [1], "y": [1]})


def hex_color(code: str, alpha: float = 1.0) -> list[float]:
    """#rrggbb as Lottie's 0-1 RGBA."""
    code = code.lstrip("#")
    return [int(code[i : i + 2], 16) / 255 for i in (0, 2, 4)] + [alpha]


def prop(
    value: Value | Keys, ease: tuple[dict[str, Any], dict[str, Any]] = EASE
) -> dict[str, Any]:
    """A static value, or keyframes [(frame, value), ...] with one easing."""
    if isinstance(value, list) and value and isinstance(value[0], tuple):
        frames = []
        keys: Keys = value  # type: ignore[assignment]
        for index, (frame, item) in enumerate(keys):
            start = item if isinstance(item, list) else [item]
            key: dict[str, Any] = {"t": frame, "s": start}
            if index < len(keys) - 1:
                key["o"], key["i"] = ease[0], ease[1]
            frames.append(key)
        return {"a": 1, "k": frames}
    return {"a": 0, "k": value}


def transform(
    position: Value | Keys = (0, 0),  # type: ignore[assignment]
    scale: Value | Keys = (100, 100),  # type: ignore[assignment]
    rotation: Value | Keys = 0,
    opacity: Value | Keys = 100,
    anchor: Value = (0, 0),  # type: ignore[assignment]
    ease: tuple[dict[str, Any], dict[str, Any]] = EASE,
) -> dict[str, Any]:
    """Layer transform ("ks")."""
    return {
        "p": prop(_list(position), ease),
        "s": prop(_list(scale), ease),
        "r": prop(rotation, ease),
        "o": prop(opacity, ease),
        "a": prop(_list(anchor)),
    }


def _list(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, list) and value and isinstance(value[0], tuple):
        return [
            (frame, list(item) if isinstance(item, tuple) else item)
            for frame, item in value
        ]
    return value


def group_transform(**kwargs: Any) -> dict[str, Any]:
    """Transform item inside a shape group."""
    ks = transform(**kwargs)
    return {"ty": "tr", **ks, "sk": prop(0), "sa": prop(0)}


def rect(
    size: Value | Keys, radius: float = 0, position: Value = (0, 0)
) -> dict[str, Any]:  # type: ignore[assignment]
    return {
        "ty": "rc",
        "d": 1,
        "s": prop(_list(size)),
        "p": prop(_list(position)),
        "r": prop(radius),
    }


def ellipse(size: Value | Keys, position: Value = (0, 0)) -> dict[str, Any]:  # type: ignore[assignment]
    return {"ty": "el", "d": 1, "s": prop(_list(size)), "p": prop(_list(position))}


def path(points: list[tuple[float, float]], *, closed: bool = False) -> dict[str, Any]:
    """Straight-segment path through points."""
    zero = [[0, 0] for _ in points]
    return {
        "ty": "sh",
        "d": 1,
        "ks": prop({"i": zero, "o": zero, "v": [list(p) for p in points], "c": closed}),
    }


def fill(color: str, opacity: Value | Keys = 100, alpha: float = 1.0) -> dict[str, Any]:
    return {"ty": "fl", "c": prop(hex_color(color, alpha)), "o": prop(opacity), "r": 1}


def fill_keys(keys: list[tuple[float, str]]) -> dict[str, Any]:
    """A fill whose color animates."""
    return {
        "ty": "fl",
        "c": prop([(frame, hex_color(color)) for frame, color in keys]),
        "o": prop(100),
        "r": 1,
    }


def stroke(color: str, width: float, opacity: Value | Keys = 100) -> dict[str, Any]:
    return {
        "ty": "st",
        "c": prop(hex_color(color)),
        "o": prop(opacity),
        "w": prop(width),
        "lc": 2,
        "lj": 2,
        "ml": 4,
    }


def trim(
    start: Value | Keys = 0, end: Value | Keys = 100, offset: Value | Keys = 0
) -> dict[str, Any]:
    return {"ty": "tm", "s": prop(start), "e": prop(end), "o": prop(offset), "m": 1}


def group(*items: dict[str, Any], name: str = "g", **tr: Any) -> dict[str, Any]:
    return {"ty": "gr", "nm": name, "it": [*items, group_transform(**tr)]}


class Composition:
    """One animation; layers added later are drawn underneath earlier ones."""

    def __init__(
        self, name: str, width: int, height: int, frames: int, fps: int = 30
    ) -> None:
        self.name, self.width, self.height = name, width, height
        self.frames, self.fps = frames, fps
        self.layers: list[dict[str, Any]] = []
        self.fonts: dict[str, str] = {}

    def shape(
        self,
        name: str,
        *shapes: dict[str, Any],
        start: float = 0,
        end: float | None = None,
        **tr: Any,
    ) -> None:
        """A shape layer; transform kwargs as in `transform`."""
        self.layers.append(
            {
                "ddd": 0,
                "ind": len(self.layers) + 1,
                "ty": 4,
                "nm": name,
                "sr": 1,
                "ks": transform(**tr),
                "ao": 0,
                "shapes": list(shapes),
                "ip": start,
                "op": self.frames if end is None else end,
                "st": 0,
                "bm": 0,
            }
        )

    def text(
        self,
        name: str,
        text: str,
        *,
        size: float,
        color: str,
        font: str = "Readex Pro",
        weight: str = "Regular",
        justify: int = 2,  # 0 left, 1 right, 2 center
        start: float = 0,
        end: float | None = None,
        **tr: Any,
    ) -> None:
        """A text layer drawn with a page font (lottie-web, SVG renderer)."""
        key = f"{font.replace(' ', '')}-{weight}"
        self.fonts[key] = f"{font}|{weight}"
        document = {
            "s": size,
            "f": key,
            "t": text,
            "j": justify,
            "tr": 0,
            "lh": size * 1.2,
            "ls": 0,
            "fc": hex_color(color)[:3],
        }
        self.layers.append(
            {
                "ddd": 0,
                "ind": len(self.layers) + 1,
                "ty": 5,
                "nm": name,
                "sr": 1,
                "ks": transform(**tr),
                "ao": 0,
                "t": {
                    "d": {"k": [{"s": document, "t": 0}]},
                    "p": {},
                    "m": {"g": 1, "a": prop([0, 0])},
                    "a": [],
                },
                "ip": start,
                "op": self.frames if end is None else end,
                "st": 0,
                "bm": 0,
            }
        )

    def to_json(self) -> dict[str, Any]:
        fonts = [
            {
                "fName": key,
                "fFamily": family.split("|")[0],
                "fStyle": family.split("|")[1],
                "ascent": 75,
            }
            for key, family in self.fonts.items()
        ]
        return {
            "v": "5.7.4",
            "fr": self.fps,
            "ip": 0,
            "op": self.frames,
            "w": self.width,
            "h": self.height,
            "nm": self.name,
            "ddd": 0,
            "assets": [],
            "fonts": {"list": fonts},
            "layers": self.layers,
        }
