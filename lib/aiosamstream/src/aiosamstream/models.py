"""Data models returned by the library."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .wol import normalize_mac

# Model codes look like "23_OSCP_8K_T09": two-digit model year first.
_MODEL_YEAR = re.compile(r"^(\d{2})_")


def _flag(value: object) -> bool:
    return str(value).lower() == "true" or str(value) == "1"


def _text(value: object) -> str | None:
    if value is None or value in ("", "Unknown"):
        return None
    return html.unescape(str(value))


@dataclass(frozen=True, slots=True)
class AppStatus:
    """What `GET /api/v2/applications/<id>` reports for an installed app."""

    app_id: str
    name: str
    # Tizen keeps many apps preloaded, so `running` says little; `visible` is
    # the app on screen.
    running: bool
    visible: bool
    version: str | None

    @classmethod
    def from_api(cls, app_id: str, data: Mapping[str, Any]) -> AppStatus:
        """Build from the REST payload."""
        return cls(
            app_id=app_id,
            name=_text(data.get("name")) or app_id,
            running=data.get("running") is True,
            visible=data.get("visible") is True,
            version=_text(data.get("version")),
        )


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """What the TV reports on `GET http://<tv>:8001/api/v2/`."""

    uuid: str
    name: str
    model_name: str | None
    model_code: str | None
    year: int | None
    os: str | None
    firmware: str | None
    mac: str | None
    ip: str | None
    network_type: str | None
    # None on TVs older than 2018, which do not report PowerState.
    power_on: bool | None
    developer_mode: bool
    developer_ip: str | None
    token_auth: bool
    resolution: str | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> DeviceInfo:
        """Build from the REST payload; missing fields become None."""
        device: Mapping[str, Any] = data.get("device") or {}
        raw_uuid = str(device.get("udn") or device.get("id") or data.get("id") or "")
        model_code = _text(device.get("model"))
        year_match = _MODEL_YEAR.match(model_code or "")
        mac = _text(device.get("wifiMac"))
        power_state = device.get("PowerState")
        return cls(
            uuid=raw_uuid.removeprefix("uuid:"),
            name=_text(device.get("name") or data.get("name")) or "Samsung TV",
            model_name=_text(device.get("modelName")),
            model_code=model_code,
            year=2000 + int(year_match.group(1)) if year_match else None,
            os=_text(device.get("OS")),
            firmware=_text(device.get("firmwareVersion")),
            mac=normalize_mac(mac) if mac else None,
            ip=_text(device.get("ip")),
            network_type=_text(device.get("networkType")),
            power_on=None if power_state is None else power_state == "on",
            developer_mode=_flag(device.get("developerMode")),
            developer_ip=_text(device.get("developerIP")),
            token_auth=_flag(device.get("TokenAuthSupport")),
            resolution=_text(device.get("resolution")),
        )
