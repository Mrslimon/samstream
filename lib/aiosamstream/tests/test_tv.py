import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosamstream import (
    SamstreamAuthError,
    SamstreamConnectionError,
    SamstreamTimeoutError,
    SamsungTV,
)
from aiosamstream.const import CLIENT_NAME, WS_PORT_SECURE
from samsungtvws.exceptions import ConnectionFailure, HttpApiError, UnauthorizedError

FIXTURES = Path(__file__).parent / "fixtures"


class FakeRemote:
    """Stands in for SamsungTVWSAsyncRemote; `behaviour` decides what open() does."""

    instances: list[FakeRemote] = []
    behaviour: Any = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.token = kwargs.get("token")
        self.closed = False
        FakeRemote.instances.append(self)

    async def open(self) -> None:
        behaviour = FakeRemote.behaviour
        if isinstance(behaviour, BaseException):
            raise behaviour
        if behaviour == "hang":
            await asyncio.sleep(10)
        if isinstance(behaviour, str) and behaviour.startswith("token:"):
            self.token = behaviour.removeprefix("token:")

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def remote() -> Any:
    FakeRemote.instances = []
    FakeRemote.behaviour = None
    with patch("aiosamstream.tv.SamsungTVWSAsyncRemote", FakeRemote):
        yield FakeRemote


async def test_first_pairing_returns_new_token(remote: Any) -> None:
    remote.behaviour = "token:12345678"
    tv = SamsungTV("192.168.1.11", MagicMock())

    assert await tv.pair() == "12345678"
    assert tv.token == "12345678"
    opened = remote.instances[0]
    assert opened.kwargs["port"] == WS_PORT_SECURE
    assert opened.kwargs["name"] == CLIENT_NAME
    assert opened.closed


async def test_stored_token_is_sent_and_kept(remote: Any) -> None:
    tv = SamsungTV("192.168.1.11", MagicMock(), token="stored")

    assert await tv.pair() == "stored"
    assert remote.instances[0].kwargs["token"] == "stored"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (UnauthorizedError("denied"), SamstreamAuthError),
        (ConnectionFailure("bad event"), SamstreamConnectionError),
        (OSError("unreachable"), SamstreamConnectionError),
    ],
)
async def test_pair_errors(
    remote: Any, error: Exception, expected: type[Exception]
) -> None:
    remote.behaviour = error
    with pytest.raises(expected):
        await SamsungTV("tv", MagicMock()).pair()
    assert remote.instances[0].closed


async def test_pair_times_out_when_nobody_accepts(remote: Any) -> None:
    remote.behaviour = "hang"
    with pytest.raises(SamstreamTimeoutError):
        await SamsungTV("tv", MagicMock()).pair(accept_within=0.05)


async def test_device_info() -> None:
    payload = json.loads(
        (FIXTURES / "device_info_qn800c.json").read_text(encoding="utf-8")
    )
    with patch(
        "aiosamstream.tv.SamsungTVAsyncRest.rest_device_info",
        AsyncMock(return_value=payload),
    ):
        info = await SamsungTV("192.168.1.11", MagicMock()).device_info()

    assert info.model_name == "QA65QN800CUXEG"


async def test_device_info_unreachable() -> None:
    with (
        patch(
            "aiosamstream.tv.SamsungTVAsyncRest.rest_device_info",
            AsyncMock(side_effect=HttpApiError("down")),
        ),
        pytest.raises(SamstreamConnectionError),
    ):
        await SamsungTV("tv", MagicMock()).device_info()
