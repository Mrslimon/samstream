"""App status, discovery, foreground detection, launch and close."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosamstream import KNOWN_APPS, AppStatus, SamstreamConnectionError, SamsungTV
from samsungtvws.exceptions import HttpApiError, ResponseError

YOUTUBE = {"id": "111299001912", "name": "YouTube", "running": True, "visible": False}
NETFLIX = {"id": "3201907018807", "name": "Netflix", "running": True, "visible": True}
NOT_FOUND = {"code": 404, "message": "Not found error.", "status": 404}


def tv_with(rest: MagicMock) -> SamsungTV:
    tv = SamsungTV("192.168.1.11", MagicMock())
    tv._rest = MagicMock(return_value=rest)  # type: ignore[method-assign]  # noqa: SLF001
    return tv


def rest_answering(answers: dict[str, Any]) -> MagicMock:
    """REST stub: app id -> payload, or an exception (list = successive answers)."""
    rest = MagicMock()

    async def status(app_id: str) -> Any:
        answer = answers.get(app_id, NOT_FOUND)
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    rest.rest_app_status = AsyncMock(side_effect=status)
    return rest


def test_app_status_model() -> None:
    status = AppStatus.from_api("111299001912", {**YOUTUBE, "version": "2.1.527"})

    assert status == AppStatus("111299001912", "YouTube", True, False, "2.1.527")


async def test_app_status_not_installed() -> None:
    assert await tv_with(rest_answering({})).app_status("nope") is None


async def test_app_status_retries_empty_answer() -> None:
    rest = rest_answering({"111299001912": [ResponseError("empty"), YOUTUBE]})
    with patch("aiosamstream.tv.REST_RETRY_DELAY", 0):
        status = await tv_with(rest).app_status("111299001912")

    assert status is not None
    assert status.name == "YouTube"


async def test_app_status_gives_up_after_two_empty_answers() -> None:
    rest = rest_answering({"x": [ResponseError("empty"), ResponseError("empty")]})
    with (
        patch("aiosamstream.tv.REST_RETRY_DELAY", 0),
        pytest.raises(SamstreamConnectionError),
    ):
        await tv_with(rest).app_status("x")


async def test_app_status_unreachable() -> None:
    rest = rest_answering({"x": HttpApiError("down")})
    with pytest.raises(SamstreamConnectionError):
        await tv_with(rest).app_status("x")


async def test_installed_apps_skips_unknown_and_flaky() -> None:
    rest = rest_answering(
        {
            "111299001912": YOUTUBE,
            "3201907018807": NETFLIX,
            "flaky": HttpApiError("down"),
        }
    )
    apps = await tv_with(rest).installed_apps(
        ["111299001912", "3201907018807", "x", "flaky"]
    )

    assert [app.name for app in apps] == ["YouTube", "Netflix"]


async def test_installed_apps_fails_when_tv_is_gone() -> None:
    rest = rest_answering({"a": HttpApiError("down"), "b": HttpApiError("down")})
    with pytest.raises(SamstreamConnectionError):
        await tv_with(rest).installed_apps(["a", "b"])


async def test_foreground_app() -> None:
    rest = rest_answering({"111299001912": YOUTUBE, "3201907018807": NETFLIX})
    tv = tv_with(rest)

    foreground = await tv.foreground_app(["111299001912", "3201907018807"])
    assert foreground is not None
    assert foreground.name == "Netflix"
    assert await tv.foreground_app(["111299001912"]) is None


async def test_launch_over_rest() -> None:
    rest = MagicMock(rest_app_run=AsyncMock(return_value=True))
    tv = tv_with(rest)
    with patch.object(tv, "_send_commands", AsyncMock()) as remote:
        await tv.launch_app("111299001912")

    rest.rest_app_run.assert_awaited_once_with("111299001912")
    remote.assert_not_awaited()


async def test_launch_falls_back_to_remote_channel() -> None:
    rest = MagicMock(rest_app_run=AsyncMock(return_value=NOT_FOUND))
    tv = tv_with(rest)
    with patch.object(tv, "_send_commands", AsyncMock()) as remote:
        await tv.launch_app("org.example.native")

    assert remote.await_args is not None
    command = remote.await_args.args[0][0]
    assert command.params["data"]["action_type"] == "NATIVE_LAUNCH"
    assert command.params["data"]["appId"] == "org.example.native"


async def test_launch_with_payload_uses_deep_link() -> None:
    rest = MagicMock(rest_app_run=AsyncMock())
    tv = tv_with(rest)
    with patch.object(tv, "_send_commands", AsyncMock()) as remote:
        await tv.launch_app("SmStrm0001.Samstream", meta_tag='{"url":"ws://x"}')

    assert remote.await_args is not None
    data = remote.await_args.args[0][0].params["data"]
    assert data["action_type"] == "DEEP_LINK"
    assert data["metaTag"] == '{"url":"ws://x"}'
    rest.rest_app_run.assert_not_awaited()


async def test_launch_unreachable() -> None:
    rest = MagicMock(rest_app_run=AsyncMock(side_effect=HttpApiError("down")))
    with pytest.raises(SamstreamConnectionError):
        await tv_with(rest).launch_app("111299001912")


async def test_close_app() -> None:
    rest = MagicMock(rest_app_close=AsyncMock(return_value=True))
    await tv_with(rest).close_app("111299001912")

    rest.rest_app_close.assert_awaited_once_with("111299001912")


async def test_close_app_unreachable() -> None:
    rest = MagicMock(rest_app_close=AsyncMock(side_effect=TimeoutError))
    with pytest.raises(SamstreamConnectionError):
        await tv_with(rest).close_app("111299001912")


def test_catalog_has_samstream() -> None:
    assert KNOWN_APPS["SmStrm0001.Samstream"] == "Samstream"
