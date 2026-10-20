"""Wake-on-LAN magic packets."""

from __future__ import annotations

import asyncio
import re
import socket

_HEX_MAC = re.compile(r"^[0-9a-f]{12}$")
WOL_PORT = 9
# Global broadcast does not leave a Docker Desktop NAT; callers can pass the subnet
# broadcast (e.g. 192.168.1.255) or the TV's own IP instead.
DEFAULT_TARGET = "255.255.255.255"


def normalize_mac(mac: str) -> str:
    """Return `aa:bb:cc:dd:ee:ff` for any common MAC notation."""
    digits = re.sub(r"[^0-9a-fA-F]", "", mac).lower()
    if not _HEX_MAC.match(digits):
        msg = f"Invalid MAC address: {mac!r}"
        raise ValueError(msg)
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def magic_packet(mac: str) -> bytes:
    """6 x 0xFF followed by the MAC repeated 16 times."""
    raw = bytes.fromhex(normalize_mac(mac).replace(":", ""))
    return b"\xff" * 6 + raw * 16


async def send_magic_packet(
    mac: str,
    target: str = DEFAULT_TARGET,
    port: int = WOL_PORT,
    repeat: int = 3,
) -> None:
    """Send the packet a few times; UDP gives no delivery feedback."""
    packet = magic_packet(mac)
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, family=socket.AF_INET, allow_broadcast=True
    )
    try:
        for _ in range(repeat):
            transport.sendto(packet, (target, port))
    finally:
        transport.close()
