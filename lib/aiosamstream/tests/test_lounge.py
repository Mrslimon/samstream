"""YouTube Lounge: bind-response parsing and the play-a-video flow."""

import json
from http import HTTPStatus
from typing import Any, Self
from unittest.mock import MagicMock

import pytest
from aiosamstream import SamstreamError, SamsungTV
from aiosamstream.lounge import parse_bind

OK = HTTPStatus.OK
CREATED = HTTPStatus.CREATED
SCREEN_ID = "be142e409f80ed500796dba3b4773aa28799db78fbcb747297bb23c47dbe45ce"
RUNNING = (
    "<service><name>YouTube</name><state>running</state>"
    f"<additionalData><screenId>{SCREEN_ID}</screenId></additionalData></service>"
)


def _bind_body(sid: str, gsession: str) -> str:
    events = [[0, ["c", sid, "", 8]], [1, ["S", gsession]], [2, ["loungeStatus", {}]]]
    chunk = json.dumps(events)
    return f"{len(chunk)}\n{chunk}"


def test_parse_bind_reads_sid_gsession_and_aid() -> None:
    sid, gsession, aid = parse_bind(_bind_body("SID123", "GS456"))
    assert sid == "SID123"
    assert gsession == "GS456"
    assert aid == 2


def test_parse_bind_handles_garbage() -> None:
    assert parse_bind("not a bind response") == (None, None, 0)


class _Resp:
    def __init__(self, status: int, text: str = "", payload: Any = None) -> None:
        self.status = status
        self._text = text
        self._payload = payload

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def text(self) -> str:
        return self._text

    async def json(self) -> Any:
        return self._payload


class FakeSession:
    """Routes the four Lounge calls by URL; records the setPlaylist request."""

    def __init__(self) -> None:
        self.playlist_body: dict[str, Any] | None = None
        self._got_screen = False

    def post(self, url: str, **kwargs: Any) -> _Resp:
        if url.endswith("/ws/apps/YouTube"):
            return _Resp(CREATED)
        if url.endswith("/get_lounge_token_batch"):
            return _Resp(OK, payload={"screens": [{"loungeToken": "TOKEN"}]})
        if url.endswith("/bc/bind"):
            if (kwargs.get("params") or {}).get("RID") == "1":
                return _Resp(OK, text=_bind_body("SID", "GS"))
            self.playlist_body = kwargs.get("data")
            return _Resp(OK)
        unexpected = f"unexpected POST {url}"
        raise AssertionError(unexpected)

    def get(self, url: str, **_: Any) -> _Resp:
        return _Resp(OK, text=RUNNING)


async def test_cast_youtube_flow_sends_setplaylist() -> None:
    session = FakeSession()
    tv = SamsungTV("192.168.1.11", session, token="t")
    await tv.cast_youtube("dQw4w9WgXcQ")
    assert session.playlist_body is not None
    assert session.playlist_body["req0__sc"] == "setPlaylist"
    assert session.playlist_body["req0_videoId"] == "dQw4w9WgXcQ"


async def test_cast_youtube_errors_without_token() -> None:
    def no_token(url: str, **_: Any) -> _Resp:
        if url.endswith("/ws/apps/YouTube"):
            return _Resp(CREATED)
        return _Resp(OK, payload={"screens": []})

    session = FakeSession()
    session.post = MagicMock(side_effect=no_token)  # type: ignore[method-assign]
    session.get = MagicMock(return_value=_Resp(OK, text=RUNNING))  # type: ignore[method-assign]
    tv = SamsungTV("192.168.1.11", session, token="t")
    with pytest.raises(SamstreamError):
        await tv.cast_youtube("dQw4w9WgXcQ")
