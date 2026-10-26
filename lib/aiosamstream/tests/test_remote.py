"""Remote keys over a kept-open connection, and power on/off logic."""

import base64
from collections.abc import Iterator
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosamstream import (
    DeviceInfo,
    SamstreamAuthError,
    SamstreamConnectionError,
    SamstreamError,
    SamsungTV,
)
from samsungtvws.exceptions import ConnectionFailure, UnauthorizedError
from samsungtvws.remote import SendRemoteKey

ON = DeviceInfo.from_api({"device": {"PowerState": "on", "name": "TV"}})


class FakeRemote:
    """One TV connection; `script` holds what each send_commands call does."""

    opened = 0
    script: list[Any] = []
    sent: list[list[Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.token = kwargs.get("token")
        self.alive = False

    async def open(self) -> None:
        FakeRemote.opened += 1
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    async def send_commands(self, commands: list[Any], key_press_delay: float) -> None:
        outcome = FakeRemote.script.pop(0) if FakeRemote.script else None
        if isinstance(outcome, BaseException):
            self.alive = False
            raise outcome
        FakeRemote.sent.append(commands)

    async def close(self) -> None:
        self.alive = False


@pytest.fixture(autouse=True)
def remote() -> Iterator[type[FakeRemote]]:
    FakeRemote.opened = 0
    FakeRemote.script = []
    FakeRemote.sent = []
    with patch("aiosamstream.tv.SamsungTVWSAsyncRemote", FakeRemote):
        yield FakeRemote


def tv() -> SamsungTV:
    return SamsungTV("192.168.1.11", MagicMock(), token="token")


async def test_keys_reuse_one_connection(remote: type[FakeRemote]) -> None:
    client = tv()
    await client.send_keys(["KEY_VOLUP"])
    await client.send_keys(["KEY_MUTE", "KEY_MUTE"], repeats=2)

    assert remote.opened == 1
    assert len(remote.sent[1]) == 4
    assert remote.sent[0][0].params["DataOfCmd"] == "KEY_VOLUP"


async def test_hold_key(remote: type[FakeRemote]) -> None:
    await tv().send_keys(["KEY_POWER"], hold=2)

    expected = SendRemoteKey.hold("KEY_POWER", 2)
    assert [type(c) for c in remote.sent[0]] == [type(c) for c in expected]


async def test_send_text(remote: type[FakeRemote]) -> None:
    client = tv()
    await client.send_text("مرحبا Samstream")
    await client.send_text("no close", done=False)

    typed, end = remote.sent[0]
    assert typed.params["TypeOfRemote"] == "SendInputString"
    assert base64.b64decode(typed.params["Cmd"]).decode() == "مرحبا Samstream"
    assert end.params == {"TypeOfRemote": "SendInputEnd"}
    assert len(remote.sent[1]) == 1


async def test_pointer(remote: type[FakeRemote]) -> None:
    client = tv()
    await client.move_pointer(12, -5)
    await client.click()
    await client.click("right")

    move = remote.sent[0][0].params
    assert move["TypeOfRemote"] == "ProcessMouseDevice"
    assert move["Position"] == {"x": 12, "y": -5, "Time": "0"}
    assert [s[0].params["Cmd"] for s in remote.sent[1:]] == ["LeftClick", "RightClick"]


async def test_reconnects_once_after_drop(remote: type[FakeRemote]) -> None:
    remote.script = [ConnectionFailure("closed by TV")]
    await tv().send_keys(["KEY_HOME"])

    assert remote.opened == 2
    assert len(remote.sent) == 1


async def test_gives_up_after_second_failure(remote: type[FakeRemote]) -> None:
    remote.script = [OSError("down"), OSError("still down")]
    with pytest.raises(SamstreamConnectionError):
        await tv().send_keys(["KEY_HOME"])


async def test_revoked_token(remote: type[FakeRemote]) -> None:
    remote.script = [UnauthorizedError("revoked")]
    with pytest.raises(SamstreamAuthError):
        await tv().send_keys(["KEY_HOME"])


async def test_close_drops_connection(remote: type[FakeRemote]) -> None:
    client = tv()
    await client.send_keys(["KEY_HOME"])
    await client.close()
    await client.send_keys(["KEY_HOME"])

    assert remote.opened == 2


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        (ON, True),
        (replace(ON, power_on=False), False),
        (replace(ON, power_on=None), True),
        (SamstreamConnectionError("off"), False),
    ],
)
async def test_is_on(info: Any, expected: bool) -> None:
    client = tv()
    side_effect = info if isinstance(info, Exception) else None
    with patch.object(
        client, "device_info", AsyncMock(return_value=info, side_effect=side_effect)
    ):
        assert await client.is_on() is expected


async def test_power_on_from_standby_presses_power(remote: type[FakeRemote]) -> None:
    client = tv()
    standby = replace(ON, power_on=False)
    with (
        patch.object(client, "device_info", AsyncMock(return_value=standby)),
        patch("aiosamstream.tv.send_magic_packet", AsyncMock()) as wol,
    ):
        await client.power_on("aa:bb:cc:00:11:22")
        await client.power_on(None)

    assert remote.sent[0][0].params["DataOfCmd"] == "KEY_POWER"
    # Wake-on-LAN too, in case the TV ignored the key (it never turns it off).
    wol.assert_awaited_once_with("aa:bb:cc:00:11:22", target="255.255.255.255")
    assert len(remote.sent) == 2


async def test_wake_on_lan_only(remote: type[FakeRemote]) -> None:
    with patch("aiosamstream.tv.send_magic_packet", AsyncMock()) as wol:
        await tv().wake_on_lan("aa:bb:cc:00:11:22", "192.168.1.255")
    wol.assert_awaited_once_with("aa:bb:cc:00:11:22", target="192.168.1.255")
    assert remote.sent == []


async def test_power_on_when_unreachable_uses_wol(remote: type[FakeRemote]) -> None:
    client = tv()
    with (
        patch.object(
            client, "device_info", AsyncMock(side_effect=SamstreamConnectionError)
        ),
        patch("aiosamstream.tv.send_magic_packet", AsyncMock()) as wol,
    ):
        await client.power_on("aa:bb:cc:00:11:22", wol_target="192.168.1.255")

    wol.assert_awaited_once_with("aa:bb:cc:00:11:22", target="192.168.1.255")
    assert remote.sent == []


async def test_power_on_already_on_does_nothing(remote: type[FakeRemote]) -> None:
    client = tv()
    with patch.object(client, "device_info", AsyncMock(return_value=ON)):
        await client.power_on("aa:bb:cc:00:11:22")

    assert remote.sent == []


async def test_power_on_without_mac() -> None:
    client = tv()
    with (
        patch.object(
            client, "device_info", AsyncMock(side_effect=SamstreamConnectionError)
        ),
        pytest.raises(SamstreamError, match="MAC"),
    ):
        await client.power_on(None)


async def test_power_off(remote: type[FakeRemote]) -> None:
    await tv().power_off()

    assert remote.sent[0][0].params["DataOfCmd"] == "KEY_POWER"


async def test_full_power_off_holds_power(remote: type[FakeRemote]) -> None:
    await tv().power_off(full=True)
    expected = SendRemoteKey.hold("KEY_POWER", 3.0)
    assert [type(c) for c in remote.sent[0]] == [type(c) for c in expected]
