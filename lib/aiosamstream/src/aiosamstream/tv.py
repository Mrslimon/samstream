"""Samsung TV control: pairing and device information."""

from __future__ import annotations

import asyncio

import aiohttp
from samsungtvws.async_remote import SamsungTVWSAsyncRemote
from samsungtvws.async_rest import SamsungTVAsyncRest
from samsungtvws.exceptions import ConnectionFailure, HttpApiError, UnauthorizedError
from websockets.exceptions import WebSocketException

from .const import CLIENT_NAME, REST_PORT, WS_PORT_SECURE
from .exceptions import (
    SamstreamAuthError,
    SamstreamConnectionError,
    SamstreamTimeoutError,
)
from .models import DeviceInfo

DEFAULT_TIMEOUT = 10.0
# Long enough for someone to walk to the TV and press "Allow".
PAIRING_TIMEOUT = 60.0


class SamsungTV:
    """One Samsung TV, addressed by host, sharing the caller's aiohttp session."""

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        *,
        token: str | None = None,
        name: str = CLIENT_NAME,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Create a client; nothing is sent until a method is awaited."""
        self.host = host
        self._session = session
        self._token = token
        self._name = name
        self._timeout = timeout

    @property
    def token(self) -> str | None:
        """Pairing token; persist it so the TV only asks once."""
        return self._token

    async def device_info(self) -> DeviceInfo:
        """Read model, network and Developer Mode details (no pairing needed)."""
        rest = SamsungTVAsyncRest(
            self.host, session=self._session, port=REST_PORT, timeout=self._timeout
        )
        try:
            data = await rest.rest_device_info()
        except (HttpApiError, TimeoutError) as err:
            msg = f"Cannot reach {self.host}:{REST_PORT}"
            raise SamstreamConnectionError(msg) from err
        return DeviceInfo.from_api(data)

    async def pair(self, accept_within: float = PAIRING_TIMEOUT) -> str | None:
        """Open the remote channel, triggering the "Allow" popup if not yet trusted.

        Returns the token to persist; None on TVs that do not use token auth.
        A stored token is sent along, so a trusted client connects silently.
        """
        remote = SamsungTVWSAsyncRemote(
            host=self.host,
            port=WS_PORT_SECURE,
            token=self._token,
            name=self._name,
            timeout=self._timeout,
        )
        try:
            async with asyncio.timeout(accept_within):
                await remote.open()
        except UnauthorizedError as err:
            msg = "The TV denied access"
            raise SamstreamAuthError(msg) from err
        except TimeoutError as err:
            msg = f"No answer from {self.host} within {accept_within:.0f}s"
            raise SamstreamTimeoutError(msg) from err
        except (ConnectionFailure, OSError, WebSocketException) as err:
            msg = f"Cannot open the remote channel on {self.host}:{WS_PORT_SECURE}"
            raise SamstreamConnectionError(msg) from err
        finally:
            await remote.close()

        self._token = remote.token
        return self._token
