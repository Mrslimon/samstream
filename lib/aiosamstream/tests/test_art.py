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


class _UploadWS(FakeWS):
    """Answers `send_image` with a `ready_to_use` socket, then `image_added`."""

    def __init__(self, conn_info: dict[str, Any], content_id: str) -> None:
        super().__init__({})
        self._conn_info = conn_info
        self._content_id = content_id

    async def send_json(self, obj: dict[str, Any]) -> None:
        self.sent.append(obj)
        data = json.loads(obj["params"]["data"])
        if data["request"] != "send_image":
            return
        ready = {
            "event": "ready_to_use",
            "request_id": data["request_id"],
            "conn_info": json.dumps(self._conn_info),
        }
        added = {"event": "image_added", "content_id": self._content_id}
        for payload in (ready, added):
            frame = {"event": "d2d_service_message", "data": json.dumps(payload)}
            self._q.append(_Msg(aiohttp.WSMsgType.TEXT, json.dumps(frame)))


async def test_upload_pushes_bytes_and_returns_content_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks: list[bytes] = []

    class FakeSock:
        def settimeout(self, timeout: float) -> None:
            pass

        def connect(self, address: tuple[str, int]) -> None:
            assert address == ("10.0.0.9", 12345)

        def sendall(self, data: bytes) -> None:
            chunks.append(data)

        def close(self) -> None:
            pass

    monkeypatch.setattr("aiosamstream.art.socket.socket", lambda *_: FakeSock())
    ws = _UploadWS({"ip": "10.0.0.9", "port": 12345, "secured": False}, "MY_F0099")
    image = b"\x89PNG\r\n\x1a\npixels"
    content_id = await _tv_with(ws).art_upload(image, file_type="png")

    assert content_id == "MY_F0099"
    # The 4-byte length prefix, the JSON header, then the image bytes.
    assert len(chunks) == 3
    assert chunks[2] == image
    sent = json.loads(ws.sent[0]["params"]["data"])
    assert sent["request"] == "send_image"
    assert sent["file_size"] == len(image)


class _ThumbWS(FakeWS):
    """Answers `get_thumbnail_list` with a socket address (a d2d reply)."""

    def __init__(self, conn_info: dict[str, Any]) -> None:
        super().__init__({"get_thumbnail_list": {"conn_info": json.dumps(conn_info)}})


def _record(file_id: str, body: bytes, num: int, total: int) -> bytes:
    header = json.dumps(
        {
            "fileID": file_id,
            "fileType": "jpg",
            "fileLength": len(body),
            "num": num,
            "total": total,
        }
    ).encode()
    return len(header).to_bytes(4, "big") + header + body


class _ReadSock:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def settimeout(self, timeout: float) -> None:
        pass

    def connect(self, address: tuple[str, int]) -> None:
        assert address == ("10.0.0.9", 2345)

    def recv(self, size: int) -> bytes:
        chunk, self._data = self._data[:size], self._data[size:]
        return chunk

    def close(self) -> None:
        pass


async def test_thumbnails_read_every_record(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _record("MY_F0001", b"one", 0, 2) + _record("MY_F0002", b"two", 1, 2)
    monkeypatch.setattr("aiosamstream.art.socket.socket", lambda *_: _ReadSock(stream))
    ws = _ThumbWS({"ip": "10.0.0.9", "port": 2345})
    thumbs = await _tv_with(ws).art_thumbnails(["MY_F0001", "MY_F0002", "MY_F0001"])
    assert thumbs == {"MY_F0001": (b"one", "jpg"), "MY_F0002": (b"two", "jpg")}
    sent = json.loads(ws.sent[0]["params"]["data"])
    assert sent["content_id_list"] == [
        {"content_id": "MY_F0001"},
        {"content_id": "MY_F0002"},
    ]


async def test_thumbnails_tolerate_skipped_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The TV skips store art it has no thumbnail for: num 1 never comes.
    for stream in (
        _record("MY_F0001", b"one", 0, 3) + _record("MY_F0003", b"three", 2, 3),
        _record("MY_F0001", b"one", 0, 3),  # then a clean close
    ):
        monkeypatch.setattr(
            "aiosamstream.art.socket.socket", lambda *_, s=stream: _ReadSock(s)
        )
        ws = _ThumbWS({"ip": "10.0.0.9", "port": 2345})
        thumbs = await _tv_with(ws).art_thumbnails(["MY_F0001", "SAM-S1", "MY_F0003"])
        assert "MY_F0001" in thumbs
        assert "SAM-S1" not in thumbs


async def test_thumbnails_refuse_a_short_or_huge_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = _ThumbWS({"ip": "10.0.0.9", "port": 2345})
    huge = json.dumps({"fileID": "x", "fileLength": 1 << 30, "total": 1}).encode()
    for stream in (b"\x00\x00", len(huge).to_bytes(4, "big") + huge):
        monkeypatch.setattr(
            "aiosamstream.art.socket.socket", lambda *_, s=stream: _ReadSock(s)
        )
        with pytest.raises(SamstreamConnectionError):
            await _tv_with(_ThumbWS({"ip": "10.0.0.9", "port": 2345})).art_thumbnails(
                ["x"]
            )
    assert await _tv_with(ws).art_thumbnails([]) == {}


async def test_thumbnails_need_a_socket() -> None:
    ws = FakeWS({"get_thumbnail_list": {"conn_info": "{}"}})
    with pytest.raises(SamstreamError):
        await _tv_with(ws).art_thumbnails(["MY_F0001"])


async def test_art_select_shows_it() -> None:
    ws = FakeWS({"select_image": {}})
    await _tv_with(ws).art_select("MY_F0001")
    sent = json.loads(ws.sent[0]["params"]["data"])
    assert (sent["request"], sent["content_id"], sent["show"]) == (
        "select_image",
        "MY_F0001",
        True,
    )


async def test_mattes_parse_styles_and_colours() -> None:
    styles = json.dumps([{"matte_type": "none"}, {"matte_type": "shadowbox"}, {}])
    colours = json.dumps(
        [{"color": "sand", "R": 164, "G": 145, "B": 113}, {"color": "broken"}]
    )
    ws = FakeWS(
        {"get_matte_list": {"matte_type_list": styles, "matte_color_list": colours}}
    )
    async with _tv_with(ws).art() as art:
        assert await art.mattes() == (["none", "shadowbox"], {"sand": (164, 145, 113)})


async def test_mattes_tolerate_garbage() -> None:
    ws = FakeWS({"get_matte_list": {"matte_type_list": "{not json"}})
    async with _tv_with(ws).art() as art:
        assert await art.mattes() == ([], {})


async def test_select_with_matte_changes_the_border_first() -> None:
    ws = FakeWS({"change_matte": {}, "select_image": {}})
    await _tv_with(ws).art_select("MY_F0001", matte="shadowbox_sand")
    sent = [json.loads(m["params"]["data"]) for m in ws.sent]
    assert [s["request"] for s in sent] == ["change_matte", "select_image"]
    assert sent[0]["matte_id"] == "shadowbox_sand"
