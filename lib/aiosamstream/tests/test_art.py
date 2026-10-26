"""Art Mode: the art-app channel client and the Frame power-key toggle."""

import asyncio
import json
from collections import deque
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from aiosamstream import SamstreamError, SamsungTV
from aiosamstream.exceptions import SamstreamConnectionError, SamstreamTimeoutError


class _Msg:
    def __init__(self, msg_type: Any, data: str | None = None) -> None:
        self.type = msg_type
        self.data = data


class FakeWS:
    """A fake art-app websocket: replies to each request echoing its request_id.

    `replies` maps a request name to the payload the TV answers with. `ready`
    False withholds the `ms.channel.ready` frame (to exercise the open timeout).
    """

    def __init__(
        self,
        replies: dict[str, dict[str, Any]],
        *,
        ready: bool = True,
        hang_when_empty: bool = False,
    ) -> None:
        self._replies = replies
        self._hang = hang_when_empty
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self._q: deque[_Msg] = deque()
        if ready:
            ready_frame = json.dumps({"event": "ms.channel.ready"})
            self._q.append(_Msg(aiohttp.WSMsgType.TEXT, ready_frame))

    async def receive(self) -> _Msg:
        if self._q:
            return self._q.popleft()
        if self._hang:  # a dead channel that never answers, rather than closing
            await asyncio.sleep(3600)
        return _Msg(aiohttp.WSMsgType.CLOSED)

    async def send_json(self, obj: dict[str, Any]) -> None:
        self.sent.append(obj)
        data = json.loads(obj["params"]["data"])
        request = data["request"]
        if request not in self._replies:
            return  # no answer (like a dead channel)
        payload = dict(self._replies[request])
        payload["request_id"] = data["request_id"]
        payload.setdefault("event", request)
        frame = {"event": "d2d_service_message", "data": json.dumps(payload)}
        self._q.append(_Msg(aiohttp.WSMsgType.TEXT, json.dumps(frame)))

    async def close(self) -> None:
        self.closed = True


def _tv_with(ws: FakeWS) -> SamsungTV:
    session = MagicMock()
    session.ws_connect = AsyncMock(return_value=ws)
    return SamsungTV("192.168.1.22", session, token="t")


async def test_get_art_mode_on() -> None:
    ws = FakeWS({"get_artmode_status": {"value": "on"}})
    assert await _tv_with(ws).get_art_mode() is True
    assert ws.closed


async def test_get_art_mode_off() -> None:
    ws = FakeWS({"get_artmode_status": {"value": "off"}})
    assert await _tv_with(ws).get_art_mode() is False


async def test_art_list_parses_content_list() -> None:
    content = [{"content_id": "MY_F0001", "category_id": "MY-C0002"}]
    ws = FakeWS({"get_content_list": {"content_list": json.dumps(content)}})
    items = await _tv_with(ws).art_list()
    assert items == content


async def test_select_sends_content_id() -> None:
    ws = FakeWS({"select_image": {}})
    await _tv_with(ws).set_art_mode(on=True, artwork="MY_F0001")
    data = json.loads(ws.sent[0]["params"]["data"])
    assert data["request"] == "select_image"
    assert data["content_id"] == "MY_F0001"
    assert data["show"] is True


async def test_error_reply_raises() -> None:
    ws = FakeWS({"get_artmode_status": {"event": "error", "error_code": "-9"}})
    with pytest.raises(SamstreamError):
        await _tv_with(ws).get_art_mode()


async def test_open_times_out_without_ready() -> None:
    ws = FakeWS({}, ready=False)
    with pytest.raises(SamstreamConnectionError):
        async with _tv_with(ws).art():
            pass


async def test_request_times_out_on_dead_channel() -> None:
    # A channel that never answers (2024 local Frame) must time out, not hang.
    ws = FakeWS({}, hang_when_empty=True)  # ready, but never answers a request
    tv = _tv_with(ws)
    async with tv.art() as art:
        art._timeout = 0.05  # noqa: SLF001 - shorten the wait for the test
        with pytest.raises(SamstreamTimeoutError):
            await art.get_art_mode()


async def test_toggle_art_mode_presses_power() -> None:
    tv = SamsungTV("192.168.1.22", MagicMock(), token="t")
    tv.send_keys = AsyncMock()  # type: ignore[method-assign]
    await tv.toggle_art_mode()
    tv.send_keys.assert_awaited_once_with(["KEY_POWER"])
