"""The TV's live state as its `/sec/tv/*` OCF resources report it to the cloud.

Bodies verified on a QN800C (Tizen 9) through the local cloud; see
docs/ocf-local-protocol.md section 14.7. Unknown or missing fields stay `None`,
so a model that lacks a resource simply reports less.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_TV = "x.com.samsung.tv."

CONTENT_INFO = "/sec/tv/contentinfo"
INPUT_SOURCE = "/sec/tv/inputsource"
AUDIO = "/sec/tv/audio"
SWITCH = "/sec/tv/switch/binary"
CHANNEL = "/sec/tv/channel"
PICTURE_MODE = "/sec/tv/mode/picture"
SOUND_MODE = "/sec/tv/mode/sound"
MEDIA_OUTPUT = "/sec/tv/mediaOutput"
NETWORK = "/sec/tv/networkinfo"
CONNECTION_INFO = "/devicelog/connectioninfo"
LIGHT_SENSOR = "/light/sensor/brightness/vs/0"
SOUND_DETECTION = "/sound/detection/vs/0"
CAMERA = "/sec/tv/camera/status"
ENERGY = "/capability/custom.energyType/main/0"
# The remote's battery: listed by the TV, body not seen yet (no answer captured).
BATTERY = "/sec/tv/batteryinfo"
VIRTUAL_REMOTE = "/sec/tv/virtualremote"
LAUNCH_APP = "/sec/tv/launchapp"
# The Frame lists a motion capability; its body is empty until something moves
# (field name unconfirmed). The sensor switches say which sensors are on.
MOTION = "/capability/motion/vs/0"
SENSOR_STATES = "/sensor/state/vs/0"
ORIENTATION = "/sec/tv/display/orientation"
# Accessibility settings (read); a POST opens a menu rather than setting them.
SHOW_MENU = "/sec/tv/showmenu"
# Frame: POST enters Art Mode; Art Mode then shows as the "art" app.
SWITCH_ART = "/sec/tv/switch/art"
# Not used: /devicelog/command restartThing makes the TV ask on screen to
# allow the reconnect, every time.
ART_APP = "art"

# Read once per session and observed: the state that changes as the TV is used.
STATE_RESOURCES = (
    CONTENT_INFO,
    INPUT_SOURCE,
    AUDIO,
    SWITCH,
    CHANNEL,
    PICTURE_MODE,
    SOUND_MODE,
    MEDIA_OUTPUT,
    NETWORK,
    CONNECTION_INFO,
    LIGHT_SENSOR,
    SOUND_DETECTION,
    CAMERA,
    ENERGY,
    BATTERY,
    MOTION,
    SENSOR_STATES,
    ORIENTATION,
    SHOW_MENU,
)

Choices = tuple[tuple[str, str], ...]  # (id, display name)


@dataclass(frozen=True, slots=True)
class OcfTvState:
    """Everything the cloud channel has told us so far; `None` = not reported."""

    power: bool | None = None
    volume: int | None = None
    muted: bool | None = None
    input_source: str | None = None
    input_sources: Choices = ()
    content_input: str | None = None  # "webapp", "dtv", "hdmi", ...
    content_title: str | None = None  # app name, or the programme on Live TV
    app_id: str | None = None  # Tizen app id while an app is in front
    channel_number: str | None = None
    channel_name: str | None = None
    picture_mode: str | None = None
    picture_modes: Choices = ()
    sound_mode: str | None = None
    sound_modes: Choices = ()
    sound_output: str | None = None
    sound_outputs: Choices = ()
    wifi_rssi: int | None = None
    wifi_channel: int | None = None
    wifi_dbm: int | None = None  # from the device log, real dBm
    wifi_frequency: int | None = None  # MHz
    wifi_protocol: str | None = None  # e.g. 802.11ac
    wifi_disconnects: int | None = None
    illuminance: float | None = None  # lux, the TV's ambient light sensor
    brightness_level: int | None = None
    sound_detected: str | None = None  # "noSound", "dogBarking", ...
    sound_types: tuple[str, ...] = ()
    camera_connected: bool | None = None
    energy_saving: bool | None = None
    remote_battery: int | None = None  # percent
    motion: bool | None = None
    motion_sensor_enabled: bool | None = None  # the TV's motion detection switch
    orientation: int | None = None  # 1 seen on a wall-hung Frame (landscape)
    accessibility: tuple[tuple[str, bool], ...] = ()  # (menu id, on), e.g. grayscale

    @property
    def art_mode(self) -> bool | None:
        """Frame in Art Mode (it reports Art Mode as the app in front)."""
        if self.content_input is None:
            return None
        return self.content_input == "webapp" and self.app_id == ART_APP

    def accessibility_on(self, menu_id: str) -> bool | None:
        """One accessibility setting (`voiceguide_on`, `grayscale`, ...)."""
        return dict(self.accessibility).get(menu_id)


def _text(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    return value if isinstance(value, str) and value else None


def _int(body: dict[str, Any], key: str) -> int | None:
    value = body.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bool(body: dict[str, Any], key: str) -> bool | None:
    value = body.get(key)
    return value if isinstance(value, bool) else None


def _choices(items: Any, id_key: str, name_key: str) -> Choices:
    if not isinstance(items, list):
        return ()
    out = []
    for item in items:
        if isinstance(item, dict):
            ident, name = item.get(id_key), item.get(name_key)
            if isinstance(ident, str) and ident:
                out.append((ident, name if isinstance(name, str) and name else ident))
    return tuple(out)


def _modes(body: dict[str, Any]) -> tuple[str | None, Choices]:
    return _text(body, f"{_TV}currentMode"), _choices(
        body.get(f"{_TV}supportedModes"), f"{_TV}id", f"{_TV}name"
    )


def _content(body: dict[str, Any]) -> dict[str, Any]:
    content_input = _text(body, f"{_TV}input")
    subtitle = _text(body, f"{_TV}subtitle")
    return {
        "content_input": content_input,
        "content_title": _text(body, f"{_TV}title"),
        # For apps the subtitle carries the Tizen app id; on Live TV it is text.
        "app_id": subtitle if content_input == "webapp" else None,
    }


def _input_source(body: dict[str, Any]) -> dict[str, Any]:
    current, choices = _modes(body)
    return {"input_source": current, "input_sources": choices}


def _picture(body: dict[str, Any]) -> dict[str, Any]:
    current, choices = _modes(body)
    return {"picture_mode": current, "picture_modes": choices}


def _sound(body: dict[str, Any]) -> dict[str, Any]:
    current, choices = _modes(body)
    return {"sound_mode": current, "sound_modes": choices}


def _connection(body: dict[str, Any]) -> dict[str, Any]:
    info = body.get("x.com.samsung.devicelog.connectioninfo")
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except ValueError:
            info = None
    if not isinstance(info, dict):
        return {}
    return {
        "wifi_dbm": _int(info, "ap_rssi"),
        "wifi_frequency": _int(info, "ap_freq"),
        "wifi_protocol": _text(info, "ap_protocol"),
        "wifi_disconnects": _int(info, "ap_disconnect_count"),
    }


def _light(body: dict[str, Any]) -> dict[str, Any]:
    lux = body.get("brightness.lux")
    return {
        "illuminance": float(lux)
        if isinstance(lux, int | float) and not isinstance(lux, bool)
        else None,
        "brightness_level": _int(body, "brightness.level"),
    }


def _sound_detection(body: dict[str, Any]) -> dict[str, Any]:
    types = body.get("x.com.samsung.vd.supportedSoundTypes")
    return {
        "sound_detected": _text(body, "x.com.samsung.vd.soundDetected"),
        "sound_types": tuple(x for x in types if isinstance(x, str))
        if isinstance(types, list)
        else (),
    }


def _camera(body: dict[str, Any]) -> dict[str, Any]:
    reason = _text(body, "disableReason")
    return {"camera_connected": reason != "cameraDisconnect" if reason else None}


def _battery(body: dict[str, Any]) -> dict[str, Any]:
    """Read the remote's battery percentage.

    The key is unconfirmed (no answer captured yet), so take the first 0-100
    number under a battery- or level-like key.
    """
    for key, value in body.items():
        lowered = str(key).lower()
        if (
            ("battery" in lowered or "level" in lowered)
            and isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= 100  # noqa: PLR2004
        ):
            return {"remote_battery": value}
    return {}


_MOTION_ON = {"active", "detected", "motion", "true", "on"}
_MOTION_OFF = {"inactive", "notdetected", "nomotion", "false", "off", "nomovement"}


def _motion(body: dict[str, Any]) -> dict[str, Any]:
    """Read a motion value from any motion-like key (the name is unconfirmed)."""
    for key, value in body.items():
        if "motion" not in str(key).lower():
            continue
        if isinstance(value, bool):
            return {"motion": value}
        if isinstance(value, str):
            word = value.replace(" ", "").replace("_", "").lower()
            if word in _MOTION_ON:
                return {"motion": True}
            if word in _MOTION_OFF:
                return {"motion": False}
    return {}


def _sensor_states(body: dict[str, Any]) -> dict[str, Any]:
    sensors = body.get("x.com.samsung.vd.sensorType")
    for sensor in sensors if isinstance(sensors, list) else ():
        if isinstance(sensor, dict) and "motion" in str(sensor.get("name")).lower():
            return {"motion_sensor_enabled": _bool(sensor, "enabled")}
    return {}


def _accessibility(body: dict[str, Any]) -> dict[str, Any]:
    items = body.get(f"{_TV}accessibility")
    return {
        "accessibility": tuple(
            (menu, item.get("value") in ("1", 1, True))
            for item in (items if isinstance(items, list) else ())
            if isinstance(item, dict) and isinstance(menu := item.get("menuid"), str)
        )
    }


_PARSERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    CONTENT_INFO: _content,
    INPUT_SOURCE: _input_source,
    AUDIO: lambda b: {"volume": _int(b, "volume"), "muted": _bool(b, "mute")},
    SWITCH: lambda b: {"power": _bool(b, "value")},
    CHANNEL: lambda b: {
        "channel_number": _text(b, f"{_TV}channelNumber"),
        "channel_name": _text(b, f"{_TV}channelName"),
    },
    PICTURE_MODE: _picture,
    SOUND_MODE: _sound,
    MEDIA_OUTPUT: lambda b: {
        "sound_output": _text(b, "curMediaOutput"),
        "sound_outputs": _choices(b.get("outputList"), "id", "name"),
    },
    NETWORK: lambda b: {"wifi_rssi": _int(b, "rssi"), "wifi_channel": _int(b, "ch")},
    CONNECTION_INFO: _connection,
    LIGHT_SENSOR: _light,
    SOUND_DETECTION: _sound_detection,
    CAMERA: _camera,
    ENERGY: lambda b: {"energy_saving": _bool(b, "energySavingOperation")},
    BATTERY: _battery,
    MOTION: _motion,
    SENSOR_STATES: _sensor_states,
    ORIENTATION: lambda b: {"orientation": _int(b, "orientation")},
    SHOW_MENU: _accessibility,
}


def apply(state: OcfTvState, href: str, body: Any) -> OcfTvState:
    """`state` updated with one resource body.

    Only the fields that resource owns change. A notification carries the whole
    resource, so a field it leaves empty (e.g. no channel while an app is in
    front) clears the old value.
    """
    if not isinstance(body, dict):
        return state
    parser = _PARSERS.get(href)
    fields = parser(body) if parser else {}
    return dataclasses.replace(state, **fields) if fields else state
