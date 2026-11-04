"""Shared fixtures: a small sdbd speaking the real frame protocol."""

from __future__ import annotations

import asyncio
import os
import struct
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from aiosamstream.sdb import (
    AUTH,
    AUTH_RSAPUBLICKEY,
    AUTH_SIGNATURE,
    AUTH_TOKEN,
    CLSE,
    CNXN,
    OKAY,
    OPEN,
    WRTE,
    generate_key,
)
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

HEADER = struct.Struct("<6I")


@pytest.fixture(autouse=True)
def _honour_enable_socket(request: pytest.FixtureRequest) -> None:
    """Re-allow sockets for `enable_socket` tests inside HA's test harness.

    HA's pytest plugin disables sockets in its own runtest-setup hook, which can
    run after pytest-socket applied the marker; autouse fixtures run after both.
    """
    if request.node.get_closest_marker("enable_socket") is None:
        return
    try:
        import pytest_socket  # noqa: PLC0415  # only present in the HA harness
    except ImportError:
        return
    pytest_socket.enable_socket()


@dataclass
class FakeSdbd:
    """`auth`: "none", "verify" (check the signature) or "pubkey" (reject it)."""

    auth: str = "none"
    public_key: rsa.RSAPublicKey | None = None
    max_data: int = 4096
    shell: dict[str, list[str]] = field(default_factory=dict)
    capability: str = (
        "platform_version:9.0\nsdk_toolpath:/home/owner/share/tmp/sdk_tools\n"
    )
    refuse: set[str] = field(default_factory=set)
    push_fail: str | None = None
    drop_first_connections: int = 0
    pushed: dict[str, bytes] = field(default_factory=dict)
    received_pubkey: bytes | None = None
    commands: list[str] = field(default_factory=list)
    port: int = 0
    key_pem: bytes = b""
    _server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        if self.drop_first_connections:
            self.drop_first_connections -= 1
            writer.close()
            return
        session = _Session(self, reader, writer)
        try:
            await session.run()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


class _Session:
    def __init__(
        self, fake: FakeSdbd, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.fake = fake
        self.reader = reader
        self.writer = writer
        self.next_remote = 100
        self.sync_buffers: dict[int, bytearray] = {}
        self.sync_paths: dict[int, str] = {}
        self.sync_data: dict[int, bytearray] = {}

    async def send(
        self, command: int, arg0: int, arg1: int, payload: bytes = b""
    ) -> None:
        self.writer.write(
            HEADER.pack(
                command, arg0, arg1, len(payload), sum(payload), command ^ 0xFFFFFFFF
            )
            + payload
        )
        await self.writer.drain()

    async def read(self) -> tuple[int, int, int, bytes]:
        command, arg0, arg1, length, _checksum, magic = HEADER.unpack(
            await self.reader.readexactly(24)
        )
        assert magic == command ^ 0xFFFFFFFF
        payload = await self.reader.readexactly(length) if length else b""
        return command, arg0, arg1, payload

    async def run(self) -> None:
        command, _arg0, _arg1, banner = await self.read()
        assert command == CNXN
        assert banner.startswith(b"host::")
        if self.fake.auth != "none":
            token = os.urandom(20)
            await self.send(AUTH, AUTH_TOKEN, 0, token)
            command, kind, _, signature = await self.read()
            assert (command, kind) == (AUTH, AUTH_SIGNATURE)
            if self.fake.auth == "verify":
                assert self.fake.public_key is not None
                sha1 = hashes.SHA1()  # noqa: S303  # fixed by the sdb protocol
                self.fake.public_key.verify(signature, token, padding.PKCS1v15(), sha1)
            else:
                await self.send(AUTH, AUTH_TOKEN, 0, os.urandom(20))
                command, kind, _, blob = await self.read()
                assert (command, kind) == (AUTH, AUTH_RSAPUBLICKEY)
                self.fake.received_pubkey = blob
        await self.send(CNXN, 0x01000000, self.fake.max_data, b"device::FAKE::0")

        while True:
            command, arg0, arg1, payload = await self.read()
            if command == OPEN:
                await self.open(arg0, payload.rstrip(b"\x00").decode())
            elif command == WRTE:
                await self.send(OKAY, arg1, arg0)
                await self.sync_write(arg1, arg0, payload)

    async def open(self, local: int, service: str) -> None:
        if service in self.fake.refuse:
            await self.send(CLSE, 0, local)
            return
        remote = self.next_remote
        self.next_remote += 1
        await self.send(OKAY, remote, local)
        if service == "sync:":
            self.sync_buffers[remote] = bytearray()
            return
        if service == "capability:":
            output = self.fake.capability
        else:
            command = service.removeprefix("shell:")
            self.fake.commands.append(command)
            answers = self.fake.shell.get(command, [""])
            output = answers.pop(0) if len(answers) > 1 else answers[0]
        if output:
            await self.send(WRTE, remote, local, output.encode())
            reply, _, _, _ = await self.read()
            assert reply == OKAY
        await self.send(CLSE, remote, local)

    async def sync_write(self, remote: int, local: int, payload: bytes) -> None:
        buffer = self.sync_buffers[remote]
        buffer += payload
        while len(buffer) >= 8:
            tag, length = struct.unpack("<4sI", buffer[:8])
            if len(buffer) < 8 + length:
                return
            body = bytes(buffer[8 : 8 + length])
            del buffer[: 8 + length]
            if tag == b"SEND":
                self.sync_paths[remote] = body.decode()
                self.sync_data[remote] = bytearray()
            elif tag == b"DATA":
                self.sync_data[remote] += body
            elif tag == b"DONE":
                if self.fake.push_fail:
                    reason = self.fake.push_fail.encode()
                    reply = struct.pack("<4sI", b"FAIL", len(reason)) + reason
                else:
                    self.fake.pushed[self.sync_paths[remote]] = bytes(
                        self.sync_data[remote]
                    )
                    reply = struct.pack("<4sI", b"OKAY", 0)
                await self.send(WRTE, remote, local, reply)


SDB_KEY = generate_key()


@pytest.fixture
async def sdbd() -> AsyncIterator[FakeSdbd]:
    """A running fake sdbd that verifies signatures made with SDB_KEY."""
    key = serialization.load_pem_private_key(SDB_KEY, password=None)
    assert isinstance(key, rsa.RSAPrivateKey)
    fake = FakeSdbd(public_key=key.public_key(), key_pem=SDB_KEY)
    await fake.start()
    yield fake
    await fake.stop()
