"""The onboarding CoAP layer: packet round-trips, port scan, and request quirks.

The DTLS handshake and the live ownership writes need the real TV, so here the
CoAP request logic (separate CON responses, Block2 token reuse) runs against a
fake session that stands in for an open DTLS channel.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence

from aiosamstream.ocf import cbor, onboard
from aiosamstream.ocf.coap_tcp import encode_body

GET, POST = onboard.GET, onboard.POST
_BLOCK2 = onboard._BLOCK2  # noqa: SLF001

Responder = Callable[[onboard._Reply], list[bytes]]  # noqa: SLF001


def test_build_and_parse_round_trip() -> None:
    body = cbor.dumps({"om": 4})
    packet = onboard._build_coap(  # noqa: SLF001
        POST, b"\x01\x02\x03\x04", b"\xab\xcd", onboard._CON, "/oic/sec/pstat",  # noqa: SLF001
        body, "if=oic.if.a",
    )
    reply = onboard._parse_coap(packet)  # noqa: SLF001
    assert reply.code == POST
    assert reply.token == b"\x01\x02\x03\x04"
    assert reply.message_id == b"\xab\xcd"
    assert reply.payload == body
    paths = [value for number, value in reply.options if number == onboard.URI_PATH]
    assert paths == [b"oic", b"sec", b"pstat"]
    queries = [value for number, value in reply.options if number == onboard.URI_QUERY]
    assert queries == [b"if=oic.if.a"]


def test_scan_secure_port_finds_the_tls_port() -> None:
    # CBOR text(4) "port" then a uint16 (0x19) carrying 39231.
    buffer = b"....\x64port\x19\x99\x3f...."
    assert onboard._scan_secure_port(buffer) == 39231  # noqa: SLF001
    assert onboard._scan_secure_port(b"no port here") is None  # noqa: SLF001


def _response(
    token: bytes,
    code: int,
    payload: bytes,
    options: Sequence[tuple[int, bytes]] = (),
) -> bytes:
    head = bytes([1 << 6 | 0 << 4 | len(token), code]) + os.urandom(2)  # CON
    return head + token + encode_body(tuple(options), payload)


class _FakeSession:
    """Stands in for an open DTLS session: echoes canned replies for each request."""

    def __init__(self, responder: Responder) -> None:
        self._responder = responder
        self.queue: list[bytes] = []
        self.acks = 0

    def send(self, datagram: bytes) -> None:
        reply = onboard._parse_coap(datagram)  # noqa: SLF001
        if reply.code == 0:  # an empty ACK we sent for a separate response
            self.acks += 1
            return
        self.queue.extend(self._responder(reply))

    def recv(self, timeout: float | None = None) -> bytes:
        if not self.queue:
            raise TimeoutError
        return self.queue.pop(0)


def test_separate_response_is_acked_and_decoded() -> None:
    def responder(request: onboard._Reply) -> list[bytes]:
        empty_ack = bytes([0x60, 0x00]) + request.message_id  # ACK, code 0.00
        con = _response(request.token, 0x45, cbor.dumps({"owned": True}))  # 2.05
        return [empty_ack, con]

    session = _FakeSession(responder)
    coap = onboard._SecureCoap(session)  # noqa: SLF001
    code, data = coap.request(GET, "/oic/sec/doxm")

    assert code == "2.05"
    assert data == {"owned": True}
    assert session.acks == 1  # we acknowledged the separate CON response


def test_block2_reassembles_using_the_first_token() -> None:
    first_block = b"A" * 64
    second_block = b"B" * 16
    tokens: list[bytes] = []

    def responder(request: onboard._Reply) -> list[bytes]:
        tokens.append(request.token)
        block2 = [value for number, value in request.options if number == _BLOCK2]
        if not block2:  # block 0: more-bit set, szx 6 (1024)
            option = [(_BLOCK2, bytes([(0 << 4) | (1 << 3) | 6]))]
            return [_response(request.token, 0x45, first_block, option)]
        option = [(_BLOCK2, bytes([(1 << 4) | 6]))]  # block 1: more-bit clear
        return [_response(request.token, 0x45, second_block, option)]

    session = _FakeSession(responder)
    coap = onboard._SecureCoap(session)  # noqa: SLF001
    code, _ = coap.request(GET, "/oic/res")

    assert code == "2.05"
    assert len(tokens) == 2
    assert tokens[0] == tokens[1]  # the TV ties follow-up blocks to the first token


def test_post_encodes_cbor_with_content_format() -> None:
    sent: list[bytes] = []

    def responder(request: onboard._Reply) -> list[bytes]:
        sent.append(request.payload)
        has_cf = any(number == onboard._CONTENT_FORMAT for number, _ in request.options)  # noqa: SLF001
        assert has_cf
        return [_response(request.token, 0x44, b"")]  # 2.04 CHANGED

    session = _FakeSession(responder)
    coap = onboard._SecureCoap(session)  # noqa: SLF001
    code = coap.post("/oic/sec/pstat", {"cm": 1})

    assert code == "2.04"
    assert cbor.loads(sent[0]) == {"cm": 1}
