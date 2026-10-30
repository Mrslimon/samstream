"""The DTLS 1.2 ECDHE-PSK client's crypto: PRF, owner-PSK, and the CBC record.

The full handshake is exercised against the real TV (it needs a live secure
endpoint); here we pin the deterministic crypto against an independent stdlib
implementation and check the record layer round-trips.
"""

import hashlib
import hmac as _hmac

import pytest
from aiosamstream import OcfError
from aiosamstream.ocf import dtls


def _ref_prf(secret: bytes, label: bytes, seed: bytes, length: int) -> bytes:
    """TLS 1.2 P_SHA256, re-implemented with stdlib to cross-check `dtls.prf`."""
    full = label + seed
    out = b""
    block = full
    while len(out) < length:
        block = _hmac.new(secret, block, hashlib.sha256).digest()
        out += _hmac.new(secret, block + full, hashlib.sha256).digest()
    return out[:length]


def test_prf_matches_independent_implementation() -> None:
    cases = [
        (b"\x9b\xbeCk", b"master secret", b"\x00" * 64, 48),
        (b"secret-key-bytes", b"key expansion", b"\x11" * 64, 96),
        (b"k", b"client finished", b"\xaa" * 32, 12),
    ]
    for secret, label, seed, length in cases:
        result = dtls.prf(secret, label, seed, length)
        assert len(result) == length
        assert result == _ref_prf(secret, label, seed, length)


def test_owner_psk_derivation_is_the_two_pass_prf() -> None:
    master = bytes(range(48))
    client_random = bytes(range(32))
    server_random = bytes(range(32, 64))
    obt = bytes.fromhex("5f3d8a211c7b4e629a407e2b1d6c8f33")
    server = bytes.fromhex("a63c3d4d5237a42671309d7e14d09624")

    key_block = _ref_prf(master, b"key expansion", server_random + client_random, 96)
    expected = _ref_prf(key_block, b"oic.sec.doxm.rdp", obt + server, 16)
    owner = dtls.derive_owner_psk(master, client_random, server_random, obt, server)

    assert len(owner) == 16
    assert owner == expected


def test_cbc_record_round_trips() -> None:
    client = dtls.DtlsPskClient("192.0.2.1", 1, b"id", b"\x00" * 16)
    key, mac = b"\x11" * 16, b"\x22" * 32
    client._keys = {  # noqa: SLF001
        "client_key": key,
        "server_key": key,
        "client_mac": mac,
        "server_mac": mac,
    }
    content = b"\x40\x01ping /oic/res over dtls" * 3
    fragment = client._encrypt(23, 1, 7, content)  # noqa: SLF001
    # IV (16) + whole cipher blocks, nothing left in the clear.
    assert len(fragment) % 16 == 0
    assert content not in fragment
    assert client._decrypt(23, 1, 7, fragment) == content  # noqa: SLF001


def test_bad_mac_is_rejected() -> None:
    client = dtls.DtlsPskClient("192.0.2.1", 1, b"id", b"\x00" * 16)
    key, mac = b"\x11" * 16, b"\x22" * 32
    client._keys = {  # noqa: SLF001
        "client_key": key,
        "server_key": key,
        "client_mac": mac,
        "server_mac": mac,
    }
    fragment = bytearray(client._encrypt(23, 1, 0, b"tamper me"))  # noqa: SLF001
    fragment[-1] ^= 0x01
    with pytest.raises(OcfError):
        client._decrypt(23, 1, 0, bytes(fragment))  # noqa: SLF001


def test_client_hello_frames_a_valid_handshake_header() -> None:
    client = dtls.DtlsPskClient("192.0.2.1", 1, b"id", b"\x00" * 16)
    client._client_random = b"\x00" * 32  # noqa: SLF001
    message = client._client_hello(b"")  # noqa: SLF001
    assert message[0] == 1  # ClientHello
    length = int.from_bytes(message[1:4], "big")
    assert length == len(message) - 12  # body follows the 12-byte DTLS header
    assert int.from_bytes(message[6:9], "big") == 0  # fragment_offset
    assert int.from_bytes(message[9:12], "big") == length  # fragment_length
