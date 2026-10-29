"""A DTLS 1.2 ECDHE-PSK client, pure Python on `cryptography`.

The TV's secure OCF endpoint speaks CoAP over DTLS 1.2 with one cipher,
`TLS_ECDHE_PSK_WITH_AES_128_CBC_SHA256` (0xC037), and onboarding needs two
things no `python-mbedtls` build offers: a PSK identity sent as raw bytes (the
operational identity is a UUID's 16 bytes, not text) and the TLS1.2 master
secret, from which the OCF owner PSK is derived. So we do the handshake
ourselves. This is a port of `oicseek/dtls_tunnel.c`; the derivation in
`derive_owner_psk` matches its two-pass PRF byte for byte.

Only what the TV uses is implemented: DTLS 1.2, one cipher, named-curve ECDHE on
secp256r1, no client certificate (the ECDHE-PSK ServerKeyExchange is unsigned),
no session resumption, no extended master secret (not offered, so the classic
PRF derivation applies). It is synchronous and blocking; run it in an executor.
"""

from __future__ import annotations

import logging
import os
import secrets
import socket
import struct
from collections.abc import Iterator
from typing import NoReturn, Self

from cryptography.hazmat.primitives import hashes, hmac, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from aiosamstream.exceptions import OcfHandshakeError

_LOGGER = logging.getLogger(__name__)


def _fail(message: str) -> NoReturn:
    """Raise a handshake error (keeps call sites terse)."""
    raise OcfHandshakeError(message)


# Record content types and handshake message types (RFC 6347 / 5246).
_CHANGE_CIPHER_SPEC, _ALERT, _HANDSHAKE, _APPLICATION_DATA = 20, 21, 22, 23
_HELLO_VERIFY_REQUEST, _SERVER_HELLO = 3, 2
_SERVER_KEY_EXCHANGE, _SERVER_HELLO_DONE = 12, 14
_CLIENT_HELLO, _CLIENT_KEY_EXCHANGE, _FINISHED = 1, 16, 20

_DTLS_1_2 = b"\xfe\xfd"
_CIPHER_ECDHE_PSK = 0xC037
_RENEGOTIATION_SCSV = 0x00FF  # signals secure renegotiation without an extension
_SECP256R1 = 0x0017
_NAMED_CURVE = 3
_UNCOMPRESSED_POINT = 0x04
_EXT_SUPPORTED_GROUPS, _EXT_EC_POINT_FORMATS = 10, 11

_MAC_KEY_LEN, _ENC_KEY_LEN = 32, 16  # HMAC-SHA256, AES-128
_BLOCK = 16
_MAC_LEN = 32
_EXPLICIT_IV = 16
_MASTER_SECRET_LEN = 48
_VERIFY_DATA_LEN = 12
_RECORD_HEADER = 13
_HANDSHAKE_HEADER = 12
_KEY_BLOCK_LEN = 96  # 2 * (mac 32 + enc 16)

_READ_TIMEOUT = 2.0
_HANDSHAKE_RETRIES = 6
_RECV_BUFFER = 4096

_OWNER_PSK_LABEL = b"oic.sec.doxm.rdp"  # OC_OXMTYPE_RDP_STR, the derivation label
_ZERO_UUID = b"\x00" * 16


# --------------------------------------------------------------------------- #
# TLS 1.2 PRF (HMAC-SHA256) and the OCF owner-PSK derivation                   #
# --------------------------------------------------------------------------- #
def _hmac_sha256(key: bytes, data: bytes) -> bytes:
    mac = hmac.HMAC(key, hashes.SHA256())
    mac.update(data)
    return mac.finalize()


def prf(secret: bytes, label: bytes, seed: bytes, length: int) -> bytes:
    """TLS 1.2 PRF: `P_SHA256(secret, label + seed)` truncated to `length`."""
    full_seed = label + seed
    out = bytearray()
    block = full_seed  # A(0)
    while len(out) < length:
        block = _hmac_sha256(secret, block)  # A(i)
        out += _hmac_sha256(secret, block + full_seed)
    return bytes(out[:length])


def derive_owner_psk(
    master_secret: bytes,
    client_random: bytes,
    server_random: bytes,
    obt_uuid: bytes,
    server_uuid: bytes,
) -> bytes:
    """Derive the 16-byte OCF owner PSK, exactly as IoTivity RDP does.

    `key_block = PRF(master_secret, "key expansion", server_random+client_random)`
    then `owner_psk = PRF(key_block, "oic.sec.doxm.rdp"+obt_uuid+server_uuid)`.
    `obt_uuid` and `server_uuid` are the raw 16 bytes of each UUID.
    """
    key_block = prf(
        master_secret, b"key expansion", server_random + client_random, _KEY_BLOCK_LEN
    )
    return prf(key_block, _OWNER_PSK_LABEL, obt_uuid + server_uuid, 16)


# --------------------------------------------------------------------------- #
# small packers                                                               #
# --------------------------------------------------------------------------- #
def _vec8(data: bytes) -> bytes:
    return bytes([len(data)]) + data


def _vec16(data: bytes) -> bytes:
    return struct.pack(">H", len(data)) + data


def _uint24(value: int) -> bytes:
    return struct.pack(">I", value)[1:]


def _seq_bytes(epoch: int, seq: int) -> bytes:
    """Return the 64-bit DTLS MAC sequence: epoch(2) + sequence(6)."""
    return struct.pack(">H", epoch) + struct.pack(">Q", seq)[2:]


class DtlsPskClient:
    """A DTLS 1.2 ECDHE-PSK session to one secure OCF endpoint.

    `identity` is sent on the wire as-is (bytes): `b"oic.sec.doxm.rdp"` for the
    PIN session, the controller UUID's 16 raw bytes for the operational session.
    After `handshake()`, `send`/`recv` carry CoAP datagrams. For the PIN session,
    pass `obt_uuid`/`server_uuid` (raw 16 bytes) so `handshake()` returns the
    owner PSK; the operational session can leave them at their zero default.
    """

    def __init__(  # noqa: PLR0913
        self,
        ip: str,
        port: int,
        identity: bytes,
        psk: bytes,
        *,
        obt_uuid: bytes = _ZERO_UUID,
        server_uuid: bytes = _ZERO_UUID,
        timeout: float = 6.0,
    ) -> None:
        """Prepare a session; `connect` + `handshake` open it."""
        self._ip = ip
        self._port = port
        self._identity = identity
        self._psk = psk
        self._obt_uuid = obt_uuid
        self._server_uuid = server_uuid
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._records: list[tuple[int, bytes]] = []  # parsed, not yet consumed

        self._client_random = b""
        self._server_random = b""
        self._server_point = b""
        self.master_secret = b""
        self._handshake_seq = 0
        self._transcript = bytearray()
        self._flight = b""
        # Per-epoch record state: epoch 0 is plaintext, epoch 1 is after our CCS.
        self._send_epoch = 0
        self._send_seq = [0, 0]
        self._keys: dict[str, bytes] = {}

    # -- lifecycle --------------------------------------------------------- #
    def connect(self) -> None:
        """Open the UDP socket for the TV's secure port.

        Left unconnected on purpose: the TV may answer from a different source
        port than the one we sent to, and a connected socket drops those replies.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(_READ_TIMEOUT)
        self._sock = sock

    def close(self) -> None:
        """Close the socket (no close_notify: the TV re-dials every session)."""
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def __enter__(self) -> Self:
        """Open and handshake, for use as a context manager."""
        self.connect()
        self.handshake()
        return self

    def __exit__(self, *_: object) -> None:
        """Close the socket on exit."""
        self.close()

    # -- handshake --------------------------------------------------------- #
    def handshake(self) -> bytes:
        """Run the full handshake; return the derived owner PSK.

        The owner PSK is meaningful only for the PIN session (where
        `obt_uuid`/`server_uuid` were given); the operational session returns a
        derivation from zero UUIDs that the caller ignores.
        """
        if self._sock is None:
            self.connect()
        self._client_random = os.urandom(32)
        cookie = self._exchange_hello()
        self._send_second_hello(cookie)
        server_point = self._read_server_flight()
        return self._finish(server_point)

    def _exchange_hello(self) -> bytes:
        """Send the first ClientHello, return the HelloVerifyRequest cookie."""
        flight = self._record(_HANDSHAKE, self._client_hello(b""))
        for _ in range(_HANDSHAKE_RETRIES):
            self._send(flight)
            body = self._await_handshake(_HELLO_VERIFY_REQUEST)
            if body is not None:  # body: ProtocolVersion(2) + cookie<0..255>
                return body[3 : 3 + body[2]]
        _fail("no HelloVerifyRequest from the TV")

    def _send_second_hello(self, cookie: bytes) -> None:
        self._flight = self._record(_HANDSHAKE, self._client_hello(cookie))
        self._send(self._flight)

    def _read_server_flight(self) -> bytes:
        """Collect ServerHello..ServerHelloDone; return the server ECDHE point."""
        for attempt in range(_HANDSHAKE_RETRIES):
            if self._drain_server_hello() and self._server_point:
                return self._server_point
            if attempt + 1 < _HANDSHAKE_RETRIES:
                self._send(self._flight)  # retransmit our ClientHello
        _fail("incomplete ServerHello flight from the TV")

    def _drain_server_hello(self) -> bool:
        try:
            while True:
                content_type, fragment = self._next_record()
                if content_type != _HANDSHAKE:
                    continue
                for msg_type, raw, body in self._handshake_messages(fragment):
                    self._consume_hello(msg_type, raw, body)
                    if msg_type == _SERVER_HELLO_DONE:
                        return True
        except TimeoutError:
            return False

    def _consume_hello(self, msg_type: int, raw: bytes, body: bytes) -> None:
        if msg_type in (_SERVER_HELLO, _SERVER_KEY_EXCHANGE, _SERVER_HELLO_DONE):
            self._transcript += raw
        if msg_type == _SERVER_HELLO:
            self._server_random = body[2:34]  # after ProtocolVersion(2)
        elif msg_type == _SERVER_KEY_EXCHANGE:
            self._server_point = self._server_ecdh_point(body)

    @staticmethod
    def _server_ecdh_point(body: bytes) -> bytes:
        """Pull the uncompressed EC point out of an ECDHE-PSK ServerKeyExchange."""
        pos = 2 + struct.unpack_from(">H", body, 0)[0]  # skip psk_identity_hint
        if body[pos] != _NAMED_CURVE or body[pos + 1 : pos + 3] != struct.pack(
            ">H", _SECP256R1
        ):
            _fail("TV offered an unexpected ECDHE curve")
        pos += 3
        point = body[pos + 1 : pos + 1 + body[pos]]
        if not point or point[0] != _UNCOMPRESSED_POINT:
            _fail("TV sent a non-uncompressed EC point")
        return point

    def _finish(self, server_point: bytes) -> bytes:
        private = ec.generate_private_key(ec.SECP256R1())
        our_point = private.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        peer = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), server_point
        )
        shared = private.exchange(ec.ECDH(), peer)
        premaster = _vec16(shared) + _vec16(self._psk)
        self.master_secret = prf(
            premaster,
            b"master secret",
            self._client_random + self._server_random,
            _MASTER_SECRET_LEN,
        )
        self._derive_keys()

        cke_body = _vec16(self._identity) + _vec8(our_point)
        cke = self._handshake(_CLIENT_KEY_EXCHANGE, cke_body)
        self._transcript += cke
        finished = self._handshake(_FINISHED, self._verify_data(b"client finished"))
        flight = self._record(_HANDSHAKE, cke)
        flight += self._record(_CHANGE_CIPHER_SPEC, b"\x01")
        self._send_epoch = 1  # Finished onward is encrypted, in a new epoch
        flight += self._record(_HANDSHAKE, finished)
        self._transcript += finished
        self._flight = flight
        self._send(flight)
        self._await_server_finished()
        return derive_owner_psk(
            self.master_secret,
            self._client_random,
            self._server_random,
            self._obt_uuid,
            self._server_uuid,
        )

    def _await_server_finished(self) -> None:
        expected = self._verify_data(b"server finished")
        for attempt in range(_HANDSHAKE_RETRIES):
            try:
                while True:
                    content_type, fragment = self._next_record()
                    if content_type != _HANDSHAKE:
                        continue
                    for msg_type, _raw, body in self._handshake_messages(fragment):
                        if msg_type == _FINISHED:
                            if body != expected:
                                _fail("server Finished mismatch")
                            return
            except TimeoutError:
                if attempt + 1 < _HANDSHAKE_RETRIES:
                    self._send(self._flight)
        _fail("no server Finished from the TV")

    # -- handshake message building --------------------------------------- #
    def _client_hello(self, cookie: bytes) -> bytes:
        ciphers = struct.pack(">HH", _CIPHER_ECDHE_PSK, _RENEGOTIATION_SCSV)
        body = (
            _DTLS_1_2
            + self._client_random
            + _vec8(b"")  # session id
            + _vec8(cookie)
            + _vec16(ciphers)
            + _vec8(b"\x00")  # compression: null only
            + _vec16(self._extensions())
        )
        seq = 1 if cookie else 0
        message = self._framed_handshake(_CLIENT_HELLO, body, seq)
        if cookie:  # the first ClientHello (empty cookie) is not in the transcript
            self._transcript += message
        self._handshake_seq = seq + 1
        return message

    @staticmethod
    def _extensions() -> bytes:
        groups = _vec16(struct.pack(">H", _SECP256R1))
        formats = _vec8(bytes([0]))  # uncompressed point format only
        return (
            struct.pack(">H", _EXT_SUPPORTED_GROUPS)
            + _vec16(groups)
            + struct.pack(">H", _EXT_EC_POINT_FORMATS)
            + _vec16(formats)
        )

    def _handshake(self, msg_type: int, body: bytes) -> bytes:
        message = self._framed_handshake(msg_type, body, self._handshake_seq)
        self._handshake_seq += 1
        return message

    @staticmethod
    def _framed_handshake(msg_type: int, body: bytes, seq: int) -> bytes:
        return (
            bytes([msg_type])
            + _uint24(len(body))
            + struct.pack(">H", seq)
            + _uint24(0)  # fragment_offset
            + _uint24(len(body))  # fragment_length == length (unfragmented)
            + body
        )

    def _verify_data(self, label: bytes) -> bytes:
        digest = hashes.Hash(hashes.SHA256())
        digest.update(bytes(self._transcript))
        return prf(self.master_secret, label, digest.finalize(), _VERIFY_DATA_LEN)

    def _derive_keys(self) -> None:
        block = prf(
            self.master_secret,
            b"key expansion",
            self._server_random + self._client_random,
            _KEY_BLOCK_LEN,
        )
        pos = 0
        self._keys["client_mac"] = block[pos : (pos := pos + _MAC_KEY_LEN)]
        self._keys["server_mac"] = block[pos : (pos := pos + _MAC_KEY_LEN)]
        self._keys["client_key"] = block[pos : (pos := pos + _ENC_KEY_LEN)]
        self._keys["server_key"] = block[pos : pos + _ENC_KEY_LEN]

    # -- record layer ------------------------------------------------------ #
    def _record(self, content_type: int, fragment: bytes) -> bytes:
        epoch = self._send_epoch
        seq = self._send_seq[epoch]
        self._send_seq[epoch] += 1
        if epoch >= 1 and content_type != _CHANGE_CIPHER_SPEC:
            fragment = self._encrypt(content_type, epoch, seq, fragment)
        header = (
            bytes([content_type])
            + _DTLS_1_2
            + struct.pack(">H", epoch)
            + struct.pack(">Q", seq)[2:]  # 48-bit sequence number
            + struct.pack(">H", len(fragment))
        )
        return header + fragment

    def _mac(
        self, key: str, content_type: int, epoch: int, seq: int, content: bytes
    ) -> bytes:
        return _hmac_sha256(
            self._keys[key],
            _seq_bytes(epoch, seq)
            + bytes([content_type])
            + _DTLS_1_2
            + struct.pack(">H", len(content))
            + content,
        )

    def _encrypt(
        self, content_type: int, epoch: int, seq: int, content: bytes
    ) -> bytes:
        plain = content + self._mac("client_mac", content_type, epoch, seq, content)
        pad = (_BLOCK - (len(plain) + 1) % _BLOCK) % _BLOCK
        plain += bytes([pad]) * (pad + 1)
        iv = secrets.token_bytes(_EXPLICIT_IV)
        cipher = Cipher(algorithms.AES(self._keys["client_key"]), modes.CBC(iv))
        encryptor = cipher.encryptor()
        return iv + encryptor.update(plain) + encryptor.finalize()

    def _decrypt(
        self, content_type: int, epoch: int, seq: int, fragment: bytes
    ) -> bytes:
        iv, ciphertext = fragment[:_EXPLICIT_IV], fragment[_EXPLICIT_IV:]
        cipher = Cipher(algorithms.AES(self._keys["server_key"]), modes.CBC(iv))
        decryptor = cipher.decryptor()
        plain = decryptor.update(ciphertext) + decryptor.finalize()
        pad = plain[-1]
        content = plain[: -(pad + 1) - _MAC_LEN]
        mac = plain[len(content) : len(content) + _MAC_LEN]
        if mac != self._mac("server_mac", content_type, epoch, seq, content):
            _fail("bad record MAC from the TV")
        return content

    # -- datagram I/O ------------------------------------------------------ #
    def _send(self, data: bytes) -> None:
        if self._sock is None:
            _fail("socket is not open")
        self._sock.sendto(data, (self._ip, self._port))

    def _next_record(self) -> tuple[int, bytes]:
        """Return the next (content_type, plaintext fragment), decrypting epoch 1+."""
        while not self._records:
            self._read_datagram()
        return self._records.pop(0)

    def _read_datagram(self) -> None:
        if self._sock is None:
            _fail("socket is not open")
        datagram, (source_ip, source_port) = self._sock.recvfrom(_RECV_BUFFER)
        if source_ip != self._ip:
            return  # not the TV; the caller reads again
        if source_port != self._port:
            # The TV answered from another port; keep talking to that one.
            _LOGGER.debug(
                "DTLS peer %s moved %d -> %d", self._ip, self._port, source_port
            )
            self._port = source_port
        pos = 0
        while pos + _RECORD_HEADER <= len(datagram):
            content_type = datagram[pos]
            epoch = struct.unpack_from(">H", datagram, pos + 3)[0]
            seq = int.from_bytes(datagram[pos + 5 : pos + 11], "big")
            length = struct.unpack_from(">H", datagram, pos + 11)[0]
            fragment = datagram[pos + _RECORD_HEADER : pos + _RECORD_HEADER + length]
            pos += _RECORD_HEADER + length
            if content_type == _ALERT:
                _LOGGER.debug("DTLS alert from %s: %s", self._ip, fragment.hex())
                continue
            if epoch >= 1 and content_type != _CHANGE_CIPHER_SPEC:
                fragment = self._decrypt(content_type, epoch, seq, fragment)
            self._records.append((content_type, fragment))

    def _await_handshake(self, msg_type: int) -> bytes | None:
        """Return the body of the next handshake message of `msg_type`, or None."""
        try:
            while True:
                content_type, fragment = self._next_record()
                if content_type != _HANDSHAKE:
                    continue
                for found, _raw, body in self._handshake_messages(fragment):
                    if found == msg_type:
                        return body
        except TimeoutError:
            return None

    @staticmethod
    def _handshake_messages(fragment: bytes) -> Iterator[tuple[int, bytes, bytes]]:
        """Yield (msg_type, whole message bytes, body) for a handshake record."""
        pos = 0
        while pos + _HANDSHAKE_HEADER <= len(fragment):
            msg_type = fragment[pos]
            length = int.from_bytes(fragment[pos + 1 : pos + 4], "big")
            frag_off = int.from_bytes(fragment[pos + 6 : pos + 9], "big")
            frag_len = int.from_bytes(fragment[pos + 9 : pos + 12], "big")
            start = pos + _HANDSHAKE_HEADER
            body = fragment[start : start + frag_len]
            raw = fragment[pos : start + frag_len]
            pos += _HANDSHAKE_HEADER + frag_len
            if frag_off != 0 or frag_len != length:
                _fail("fragmented handshake not supported")
            yield msg_type, raw, body

    # -- application data (CoAP over DTLS) --------------------------------- #
    def send(self, datagram: bytes) -> None:
        """Encrypt and send one CoAP datagram over the session."""
        self._send(self._record(_APPLICATION_DATA, datagram))

    def recv(self, timeout: float | None = None) -> bytes:
        """Return the next CoAP datagram; raise `TimeoutError` if none in time."""
        if self._sock is not None and timeout is not None:
            self._sock.settimeout(timeout)
        while True:
            content_type, fragment = self._next_record()
            if content_type == _APPLICATION_DATA:
                return fragment
            if content_type == _ALERT:
                _fail("TV closed the DTLS session")
