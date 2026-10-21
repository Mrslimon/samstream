"""SdbClient against the fake sdbd (conftest.py) over real localhost sockets."""

import base64
import struct
from typing import Any
from unittest.mock import patch

import pytest
from aiosamstream import SdbConnectionError, SdbError
from aiosamstream.sdb import KEY_COMMENT, SdbClient, android_public_key, generate_key
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

pytestmark = pytest.mark.enable_socket

APP = "SmStrm0001.Samstream"
TOOLS = "/home/owner/share/tmp/sdk_tools"
INSTALL = f"0 vd_appinstall {APP} {TOOLS}/samstream-install.wgt"


def private_key(pem: bytes) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(pem, password=None)
    assert isinstance(key, rsa.RSAPrivateKey)
    return key


def client(fake: Any) -> SdbClient:
    """Client using the key the fake verifies signatures with."""
    return SdbClient("127.0.0.1", fake.key_pem, port=fake.port, timeout=3)


@pytest.mark.parametrize("auth", ["none", "verify"])
async def test_handshake_and_shell(sdbd: Any, auth: str) -> None:
    sdbd.auth = auth
    sdbd.shell["0 getduid"] = ["EXCBZZZZGFIFJSY"]
    async with client(sdbd) as sdb:
        assert sdb.banner == "device::FAKE::0"
        assert sdb.max_data == 4096
        assert await sdb.duid() == "EXCBZZZZGFIFJSY"


async def test_public_key_fallback(sdbd: Any) -> None:
    sdbd.auth = "pubkey"
    async with client(sdbd):
        pass

    blob = sdbd.received_pubkey
    assert blob is not None
    assert blob.endswith(KEY_COMMENT.encode() + b"\x00")
    encoded = blob[: -len(KEY_COMMENT) - 1]
    assert (
        decode_android_pubkey(encoded)
        == private_key(sdbd.key_pem).public_key().public_numbers().n
    )


def test_android_public_key_layout() -> None:
    key = private_key(generate_key())
    blob = android_public_key(key)
    n = key.public_key().public_numbers().n

    assert len(blob) == 4 + 4 + 256 + 256 + 4
    assert int.from_bytes(blob[4:8], "little") * n % (1 << 32) == (1 << 32) - 1
    assert int.from_bytes(blob[-4:], "little") == 65537


async def test_capability(sdbd: Any) -> None:
    async with client(sdbd) as sdb:
        facts = await sdb.capability()

    assert facts == {"platform_version": "9.0", "sdk_toolpath": TOOLS}


async def test_duid_retries_empty_reply(sdbd: Any) -> None:
    sdbd.shell["0 getduid"] = ["", "EXCBZZZZGFIFJSY"]
    async with client(sdbd) as sdb:
        assert await sdb.duid() == "EXCBZZZZGFIFJSY"


async def test_duid_gives_up(sdbd: Any) -> None:
    sdbd.shell["0 getduid"] = ["", "", "", "x"]
    async with client(sdbd) as sdb:
        with pytest.raises(SdbError, match="No DUID"):
            await sdb.duid()


async def test_push_spans_many_frames(sdbd: Any) -> None:
    sdbd.max_data = 1024
    data = bytes(range(256)) * 700  # 175 KB: several sync chunks, many frames
    async with client(sdbd) as sdb:
        assert sdb.max_data == 1024
        await sdb.push(data, "/home/owner/file.bin")

    assert sdbd.pushed["/home/owner/file.bin"] == data


async def test_push_failure(sdbd: Any) -> None:
    sdbd.push_fail = "You cannot push files to this path"
    async with client(sdbd) as sdb:
        with pytest.raises(SdbError, match="cannot push"):
            await sdb.push(b"x", "/root/x")


async def test_install(sdbd: Any) -> None:
    sdbd.shell[INSTALL] = [
        (
            f"install {APP}\napp_id[{APP}] installing[50]\n"
            f"app_id[{APP}] installing[100]\napp_id[{APP}] install completed\n"
        )
    ]
    seen: list[str] = []
    async with client(sdbd) as sdb:
        result = await sdb.install(b"PK-wgt", APP, on_line=seen.append)

    assert sdbd.pushed[f"{TOOLS}/samstream-install.wgt"] == b"PK-wgt"
    assert result.lines[-1].endswith("install completed")
    assert seen == result.lines


async def test_install_rejected(sdbd: Any) -> None:
    sdbd.shell[INSTALL] = [
        (
            f"app_id[{APP}] install failed[118, -12], "
            "reason: Check certificate error :\n"
            ":Invalid certificate chain with certificate in signature.:<-3>\n"
        )
    ]
    async with client(sdbd) as sdb:
        with pytest.raises(SdbError) as err:
            await sdb.install(b"PK", APP)

    assert "Check certificate error" in str(err.value)
    assert "Invalid certificate chain" in str(err.value)


async def test_install_without_completion(sdbd: Any) -> None:
    sdbd.shell[INSTALL] = [f"app_id[{APP}] installing[10]\n"]
    async with client(sdbd) as sdb:
        with pytest.raises(SdbError, match="did not report completion"):
            await sdb.install(b"PK", APP)


async def test_refused_service(sdbd: Any) -> None:
    sdbd.refuse.add("shell:0 vd_applist")
    async with client(sdbd) as sdb:
        with pytest.raises(SdbError, match="refused"):
            await sdb.app_list()


async def test_uninstall_and_app_list(sdbd: Any) -> None:
    sdbd.shell["0 vd_applist"] = ["apps count: 23\n"]
    async with client(sdbd) as sdb:
        assert "apps count: 23" in await sdb.app_list()
        await sdb.uninstall("SmStrm0001.Samstream")

    assert sdbd.commands == ["0 vd_applist", "0 vd_appuninstall SmStrm0001.Samstream"]


async def test_retries_dropped_handshake(sdbd: Any) -> None:
    sdbd.drop_first_connections = 2
    with patch("aiosamstream.sdb._CONNECT_RETRY_DELAY", 0):
        async with client(sdbd) as sdb:
            assert sdb.banner == "device::FAKE::0"


async def test_unreachable() -> None:
    with (
        patch("aiosamstream.sdb._CONNECT_RETRY_DELAY", 0),
        pytest.raises(SdbConnectionError, match="Developer"),
    ):
        await SdbClient("127.0.0.1", generate_key(), port=1, timeout=1).connect()


async def test_reconnects_after_tv_closed_connection(sdbd: Any) -> None:
    sdbd.shell["echo"] = ["hi"]
    sdb = client(sdbd)
    await sdb.connect()
    await sdb.close()
    assert await sdb.shell("echo") == "hi"
    await sdb.close()


def test_rejects_non_rsa_key() -> None:
    pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with pytest.raises(TypeError):
        SdbClient("tv", pem)


def decode_android_pubkey(blob_b64: bytes) -> int:
    """Return the modulus in a base64 Android RSAPublicKey blob."""
    raw = base64.b64decode(blob_b64)
    words, _n0inv = struct.unpack("<II", raw[:8])
    return int.from_bytes(raw[8 : 8 + words * 4], "little")
