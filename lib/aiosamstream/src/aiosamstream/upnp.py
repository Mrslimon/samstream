"""Absolute volume and mute through the TV's UPnP media renderer (port 9197).

The remote-control WebSocket only has volume *keys*; UPnP RenderingControl is the
only local way to read the level or set an exact value.
"""

from __future__ import annotations

import re

import aiohttp

from .const import UPNP_PORT
from .exceptions import SamstreamConnectionError, SamstreamError

_SERVICE = "urn:schemas-upnp-org:service:RenderingControl:1"
_CONTROL_PATH = "/upnp/control/RenderingControl1"
_ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
    '<u:{action} xmlns:u="{service}"><InstanceID>0</InstanceID>'
    "<Channel>Master</Channel>{arguments}</u:{action}></s:Body></s:Envelope>"
)
MAX_VOLUME = 100


class RenderingControl:
    """Minimal SOAP client for GetVolume/SetVolume/GetMute/SetMute."""

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        *,
        port: int = UPNP_PORT,
        timeout: float = 5.0,
    ) -> None:
        """Address the renderer on the TV; nothing is sent until a call."""
        self._url = f"http://{host}:{port}{_CONTROL_PATH}"
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def get_volume(self) -> int:
        """Return the volume, 0-100."""
        return int(await self._call("GetVolume", result="CurrentVolume"))

    async def set_volume(self, volume: int) -> None:
        """Set an exact volume, clamped to 0-100."""
        level = max(0, min(MAX_VOLUME, volume))
        await self._call("SetVolume", f"<DesiredVolume>{level}</DesiredVolume>")

    async def get_mute(self) -> bool:
        """Return True when muted."""
        return await self._call("GetMute", result="CurrentMute") == "1"

    async def set_mute(self, *, mute: bool) -> None:
        """Mute or unmute."""
        await self._call("SetMute", f"<DesiredMute>{int(mute)}</DesiredMute>")

    async def _call(self, action: str, arguments: str = "", result: str = "") -> str:
        body = _ENVELOPE.format(action=action, service=_SERVICE, arguments=arguments)
        headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"{_SERVICE}#{action}"',
        }
        try:
            async with self._session.post(
                self._url, data=body, headers=headers, timeout=self._timeout
            ) as response:
                text = await response.text()
                status = response.status
        except (aiohttp.ClientError, TimeoutError) as err:
            msg = f"UPnP {action} failed: TV unreachable"
            raise SamstreamConnectionError(msg) from err
        if status != 200:  # noqa: PLR2004
            fault = re.search(r"<errorDescription>([^<]*)", text)
            msg = f"UPnP {action} rejected: {fault.group(1) if fault else status}"
            raise SamstreamError(msg)
        if not result:
            return ""
        match = re.search(rf"<{result}>([^<]*)</{result}>", text)
        if match is None:
            msg = f"UPnP {action}: no {result} in response"
            raise SamstreamError(msg)
        return match.group(1)
