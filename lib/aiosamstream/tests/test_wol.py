import asyncio
import socket

import pytest
from aiosamstream.wol import magic_packet, normalize_mac, send_magic_packet


@pytest.mark.parametrize(
    "raw", ["AA:BB:CC:00:11:22", "aa-bb-cc-00-11-22", "aabb.cc00.1122", "AABBCC001122"]
)
def test_normalize_mac(raw: str) -> None:
    assert normalize_mac(raw) == "aa:bb:cc:00:11:22"


def test_invalid_mac() -> None:
    with pytest.raises(ValueError, match="Invalid MAC"):
        normalize_mac("aa:bb:cc")


def test_magic_packet_layout() -> None:
    packet = magic_packet("aa:bb:cc:00:11:22")

    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    assert packet[6:] == bytes.fromhex("aabbcc001122") * 16


# Real UDP on localhost; the HA test plugin blocks sockets unless allowed.
@pytest.mark.enable_socket
async def test_send_reaches_unicast_target() -> None:
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.setblocking(False)
    port = receiver.getsockname()[1]
    try:
        await send_magic_packet(
            "aa:bb:cc:00:11:22", target="127.0.0.1", port=port, repeat=2
        )
        loop = asyncio.get_running_loop()
        data = await asyncio.wait_for(loop.sock_recv(receiver, 1024), timeout=2)
    finally:
        receiver.close()

    assert data == magic_packet("aa:bb:cc:00:11:22")
