"""RenderingControl against a real local HTTP server speaking the TV's SOAP."""

import re
from collections.abc import AsyncIterator

import aiohttp
import pytest
from aiohttp import web
from aiosamstream import SamstreamConnectionError, SamstreamError
from aiosamstream.upnp import RenderingControl

pytestmark = pytest.mark.enable_socket


class FakeRenderer:
    def __init__(self) -> None:
        self.volume = 38
        self.mute = False
        self.fail = False

    async def handle(self, request: web.Request) -> web.Response:
        action = request.headers["SOAPACTION"].split("#")[1].strip('"')
        body = await request.text()
        if self.fail:
            fault = "<errorDescription>Action Failed</errorDescription>"
            return web.Response(status=500, text=fault)
        if action == "GetVolume":
            out = f"<CurrentVolume>{self.volume}</CurrentVolume>"
        elif action == "GetMute":
            out = f"<CurrentMute>{int(self.mute)}</CurrentMute>"
        elif action == "SetVolume":
            match = re.search(r"<DesiredVolume>(\d+)<", body)
            assert match
            self.volume = int(match.group(1))
            out = ""
        else:
            match = re.search(r"<DesiredMute>(\d)<", body)
            assert match
            self.mute = match.group(1) == "1"
            out = ""
        return web.Response(text=f"<s:Envelope><s:Body>{out}</s:Body></s:Envelope>")


@pytest.fixture
async def renderer() -> AsyncIterator[tuple[FakeRenderer, RenderingControl]]:
    fake = FakeRenderer()
    app = web.Application()
    app.router.add_post("/upnp/control/RenderingControl1", fake.handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]  # noqa: SLF001
    async with aiohttp.ClientSession() as session:
        yield fake, RenderingControl("127.0.0.1", session, port=port)
    await runner.cleanup()


async def test_read_and_set_volume(
    renderer: tuple[FakeRenderer, RenderingControl],
) -> None:
    fake, control = renderer

    assert await control.get_volume() == 38
    await control.set_volume(55)
    assert fake.volume == 55
    await control.set_volume(250)
    assert fake.volume == 100


async def test_mute(renderer: tuple[FakeRenderer, RenderingControl]) -> None:
    fake, control = renderer

    assert await control.get_mute() is False
    await control.set_mute(mute=True)
    assert fake.mute is True
    assert await control.get_mute() is True


async def test_soap_fault(renderer: tuple[FakeRenderer, RenderingControl]) -> None:
    fake, control = renderer
    fake.fail = True

    with pytest.raises(SamstreamError, match="Action Failed"):
        await control.get_volume()


async def test_unreachable() -> None:
    async with aiohttp.ClientSession() as session:
        control = RenderingControl("127.0.0.1", session, port=1, timeout=2)
        with pytest.raises(SamstreamConnectionError):
            await control.get_volume()
