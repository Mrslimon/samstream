"""Onboard a Samsung TV for local control, all in Python.

One blocking driver, `onboard_tv`, does what the `oicseek/` spike split across
`otm_onboard.py`, `acl_cloud.py` and `setcloud_sid.py` with a compiled C helper:

1. discover the TV's dynamic secure port and read its device UUID (plain CoAP);
2. take ownership over a DTLS-PSK PIN session (derives the owner PSK);
3. over the owner session, grant ourselves access and clear the idle-revert;
4. install the local cloud's CA and a cloud-UUID ACL entry, then point the TV's
   cloud address at us so it dials the HA cloud server.

`trigger_pin` makes the TV show its 8 digits; `release_tv` hands it back to
SmartThings (`pstat cm=1`). CoAP quirks handled (separate CON responses, Block2
token reuse, application/cbor) follow docs/ocf-local-protocol.md sections 4-5
and 14.7. Run these in an executor; they block.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import socket
import time
import uuid
from dataclasses import asdict, dataclass

from aiosamstream.exceptions import OcfOnboardError

from . import cbor
from .coap_tcp import (
    URI_PATH,
    URI_QUERY,
    code_text,
    encode_body,
    is_success,
    parse_body,
)
from .dtls import DtlsPskClient

_LOGGER = logging.getLogger(__name__)

GET, POST = 0x01, 0x02
_CON, _ACK = 0, 2
_EMPTY = 0x00
_CONTENT_FORMAT = 12
_BLOCK2 = 23
_APP_CBOR = 60  # the TV speaks application/cbor; it 4.06s application/vnd.ocf+cbor
_OXM_CBOR = 10000  # content-format for the plain-CoAP PIN trigger
_U8_MAX = 0xFF  # a value above this needs two bytes
_CBOR_UINT16 = 0x19  # CBOR head byte for a following uint16

_PLAIN_PORT = 5683
_PBKDF2_ITERS = 1000
_PIN_IDENTITY = b"oic.sec.doxm.rdp"

DOXM = "/oic/sec/doxm"
PSTAT = "/oic/sec/pstat"
CRED = "/oic/sec/cred"
ACL = "/oic/sec/acl"
RES = "/oic/res"
PROVISIONING = "/sec/provisioninginfo"
CLOUD_CONF = "/CoapCloudConfResURI"
EASY_SETUP = "/EasySetupResURI"

# The /sec/tv/* resources the cloud ACE must grant the cloud UUID (section 14.7).
_CLOUD_TARGETS = (
    "/sec/tv/contentinfo",
    "/sec/tv/inputsource",
    "/sec/tv/audio",
    "/sec/tv/switch/binary",
    "/sec/tv/channel",
    "/sec/tv/mode/picture",
    "/sec/tv/mode/sound",
    "/sec/tv/inputsourcelist",
    "/sec/tv/deviceinfo",
    "/sec/tv/mediaInput",
    "/sec/tv/thingstatus",
    "/sec/tv/contentinfo/thumbnail",
)
_PROV = "x.com.samsung.provisioning."
_PERM_CRUDN = 31


@dataclass(frozen=True, slots=True)
class OnboardResult:
    """What onboarding learned, enough to control and later release the TV."""

    device_uuid: str  # the TV's doxm deviceuuid (PBKDF2 salt, owner-PSK input)
    obt_uuid: str  # our controller (owner) UUID
    owner_psk_hex: str  # the derived operational PSK
    secure_port: int


@dataclass(frozen=True, slots=True)
class OnboardBundle:
    """The cloud details a LAN onboarding tool needs to point a TV at HA.

    Home Assistant shows this (base64, via `encode_bundle`); the LAN tool decodes
    it so the user never copies the CA, token and address by hand.
    """

    address: str  # the host the TV dials (HA's LAN address)
    cis: str  # coaps+tcp://host:port written to the TV
    cloud_uuid: str  # the cloud identity (server cert CN + ACL subject)
    obt_uuid: str  # HA's controller UUID, so HA can later release the TV
    token: str  # the access token the TV presents at sign-up
    ca_pem: str  # HA's cloud CA, installed on the TV as a trust anchor


def encode_bundle(bundle: OnboardBundle) -> str:
    """Pack a bundle into one copy-pasteable base64 string."""
    return base64.urlsafe_b64encode(json.dumps(asdict(bundle)).encode()).decode()


def decode_bundle(blob: str) -> OnboardBundle:
    """Read a bundle produced by `encode_bundle` (raises on malformed input)."""
    data = json.loads(base64.urlsafe_b64decode(blob.strip().encode()))
    return OnboardBundle(**{k: data[k] for k in OnboardBundle.__dataclass_fields__})


def encode_credential(result: OnboardResult) -> str:
    """Pack the owner credential so the LAN tool can hand it back to HA."""
    return base64.urlsafe_b64encode(json.dumps(asdict(result)).encode()).decode()


def decode_credential(blob: str) -> OnboardResult:
    """Read a credential produced by `encode_credential` (raises on malformed)."""
    data = json.loads(base64.urlsafe_b64decode(blob.strip().encode()))
    return OnboardResult(**{k: data[k] for k in OnboardResult.__dataclass_fields__})


# --------------------------------------------------------------------------- #
# CoAP over UDP (plain) and over DTLS                                          #
# --------------------------------------------------------------------------- #
def _uuid16(value: str) -> bytes:
    return uuid.UUID(value).bytes


def _build_coap(  # noqa: PLR0913, PLR0917
    code: int,
    token: bytes,
    message_id: bytes,
    msg_type: int,
    href: str,
    payload: bytes | None,
    query: str | None,
    block2: tuple[int, int] | None = None,
    cfmt: int = _APP_CBOR,
) -> bytes:
    options: list[tuple[int, bytes]] = [
        (URI_PATH, seg.encode()) for seg in href.strip("/").split("/") if seg
    ]
    if payload is not None:
        value = cfmt.to_bytes(2 if cfmt > _U8_MAX else 1, "big")
        options.append((_CONTENT_FORMAT, value))
    if query:
        options += [(URI_QUERY, item.encode()) for item in query.split("&") if item]
    if block2 is not None:
        num, szx = block2
        block = num << 4 | szx
        options.append((_BLOCK2, block.to_bytes(2 if block > _U8_MAX else 1, "big")))
    head = bytes([1 << 6 | (msg_type & 3) << 4 | len(token) & 0xF, code]) + message_id
    return head + token + encode_body(tuple(options), payload or b"")


@dataclass(frozen=True, slots=True)
class _Reply:
    msg_type: int
    code: int
    message_id: bytes
    token: bytes
    options: tuple[tuple[int, bytes], ...]
    payload: bytes


def _parse_coap(data: bytes) -> _Reply:
    tkl = data[0] & 0xF
    msg_type = (data[0] >> 4) & 3
    options, payload = parse_body(data[4 + tkl :])
    return _Reply(msg_type, data[1], data[2:4], data[4 : 4 + tkl], options, payload)


class _SecureCoap:
    """CoAP requests over an open DTLS session, with Block2 and separate responses."""

    def __init__(self, session: DtlsPskClient, timeout: float = 6.0) -> None:
        self._session = session
        self._timeout = timeout

    def _collect(self, packet: bytes, token: bytes) -> _Reply | None:
        self._session.send(packet)
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            try:
                datagram = self._session.recv(timeout=1.5)
            except TimeoutError:
                self._session.send(packet)  # CoAP CON retransmit (stable id/token)
                continue
            reply = _parse_coap(datagram)
            if reply.code == _EMPTY or reply.token != token:
                continue  # empty ACK or someone else's message
            if reply.msg_type == _CON:  # separate response — acknowledge it
                self._session.send(bytes([0x60, 0x00]) + reply.message_id)
            return reply
        return None

    def request(
        self,
        code: int,
        href: str,
        payload: bytes | None = None,
        query: str | None = None,
    ) -> tuple[str | None, object]:
        token = os.urandom(4)  # the TV ties Block2 follow-ups to the first token
        full = b""
        num, szx = 0, 6
        last_code: int | None = None
        while True:
            packet = _build_coap(
                code, token, os.urandom(2), _CON, href, payload, query,
                block2=(num, szx) if num else None,
            )
            reply = self._collect(packet, token)
            if reply is None:
                if full:
                    msg = f"timeout after {len(full)} bytes of {href}"
                    raise OcfOnboardError(msg)
                return None, None
            last_code = reply.code
            full += reply.payload
            block2 = [value for number, value in reply.options if number == _BLOCK2]
            if not block2:
                break
            value = int.from_bytes(block2[0], "big")
            if not (value >> 3) & 1:  # "more" bit clear: last block
                break
            szx, num = value & 7, (value >> 4) + 1
        data = cbor.loads(full) if full else None
        return (code_text(last_code) if last_code is not None else None), data

    def get(self, href: str, query: str | None = None) -> object:
        _, data = self.request(GET, href, query=query)
        return data

    def post(self, href: str, body: object, query: str | None = None) -> str | None:
        code, _ = self.request(POST, href, payload=cbor.dumps(body), query=query)
        return code


def _plain_request(
    ip: str, href: str, code: int, payload: bytes | None = None, timeout: float = 4.0
) -> _Reply | None:
    # The plain-CoAP PIN trigger uses content-format 10000 (section 5), not 60.
    packet = _build_coap(
        code, b"", os.urandom(2), _CON, href, payload, None, cfmt=_OXM_CBOR
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(packet, (ip, _PLAIN_PORT))
        datagram, _ = sock.recvfrom(8192)
    except (TimeoutError, OSError):
        return None
    finally:
        sock.close()
    return _parse_coap(datagram)


# --------------------------------------------------------------------------- #
# discovery and the PIN trigger (plain CoAP)                                   #
# --------------------------------------------------------------------------- #
def _scan_secure_port(buffer: bytes) -> int | None:
    pos = 0
    while (found := buffer.find(b"\x64port", pos)) >= 0:  # CBOR text(4) "port"
        start = found + 5
        if start < len(buffer) and buffer[start] == _CBOR_UINT16:  # uint16 follows
            return int.from_bytes(buffer[start + 1 : start + 3], "big")
        pos = found + 1
    return None


def discover(ip: str) -> tuple[int, str]:
    """Return (secure port, device UUID), read from the TV's IP over plain CoAP.

    Raises `OcfOnboardError` if the TV does not answer — it must be awake and
    reachable over UDP (from a bridge-networked Docker host it is not; see
    docs/ocf-local-protocol.md section 10). Unicast to the TV's 5683 is flaky,
    so retry it.
    """
    port = None
    for _ in range(3):
        res = _plain_request(ip, RES, GET)
        port = _scan_secure_port(res.payload) if res else None
        if port is not None:
            break
    if port is None:
        msg = f"could not find {ip}'s secure port; is the TV on and reachable?"
        raise OcfOnboardError(msg)
    doxm = _plain_request(ip, DOXM, GET)
    body = cbor.loads(doxm.payload) if doxm and doxm.payload else None
    device_uuid = body.get("deviceuuid") if isinstance(body, dict) else None
    if not isinstance(device_uuid, str):
        msg = f"could not read {ip}'s device UUID"
        raise OcfOnboardError(msg)
    return port, device_uuid


def trigger_pin(ip: str) -> None:
    """Ask the TV to show its 8-digit Random-PIN (plain CoAP `oxmsel=1`)."""
    reply = _plain_request(ip, DOXM, POST, payload=cbor.dumps({"oxmsel": 1}))
    if reply is None or not is_success(reply.code):
        msg = "the TV did not accept the PIN request; wake it and try again"
        raise OcfOnboardError(msg)


# --------------------------------------------------------------------------- #
# the onboarding driver                                                        #
# --------------------------------------------------------------------------- #
def _open(  # noqa: PLR0913
    ip: str,
    port: int,
    identity: bytes,
    psk: bytes,
    *,
    obt: bytes = b"",
    server: bytes = b"",
) -> tuple[DtlsPskClient, _SecureCoap, bytes]:
    session = DtlsPskClient(
        ip, port, identity, psk,
        obt_uuid=obt or b"\x00" * 16, server_uuid=server or b"\x00" * 16,
    )
    session.connect()
    owner_psk = session.handshake()
    return session, _SecureCoap(session), owner_psk


def onboard_tv(  # noqa: PLR0913
    ip: str,
    pin: str,
    *,
    obt_uuid: str,
    ca_der: bytes,
    cloud_uuid: str,
    cis: str,
    access_token: str,
    device_uuid: str | None = None,
    secure_port: int | None = None,
) -> OnboardResult:
    """Own the TV with `pin`, then point it at the local cloud `cis`.

    `ca_der` is the cloud CA (DER), `cloud_uuid` its UUID (the server cert CN),
    `access_token` the token the TV presents at sign-up. Returns the credential
    needed to control and later release the TV.
    """
    if secure_port is None or device_uuid is None:
        found_port, found_uuid = discover(ip)
        secure_port = secure_port or found_port
        device_uuid = device_uuid or found_uuid

    owner_psk = _take_ownership(ip, secure_port, pin, device_uuid, obt_uuid)
    _provision_cloud(
        ip, secure_port, device_uuid, obt_uuid, owner_psk, ca_der, cloud_uuid, cis,
        access_token,
    )
    return OnboardResult(device_uuid, obt_uuid, owner_psk.hex(), secure_port)


def _take_ownership(
    ip: str, port: int, pin: str, device_uuid: str, obt_uuid: str
) -> bytes:
    """Run the PIN-session ownership writes; return the derived owner PSK."""
    pin_psk = hashlib.pbkdf2_hmac(
        "sha256", pin.encode("ascii"), _uuid16(device_uuid), _PBKDF2_ITERS, dklen=16
    )
    session, coap, owner_psk = _open(
        ip, port, _PIN_IDENTITY, pin_psk,
        obt=_uuid16(obt_uuid), server=_uuid16(device_uuid),
    )
    try:
        steps = [
            (PSTAT, {"om": 4}),
            (DOXM, {"devowneruuid": obt_uuid}),
            (DOXM, {"rowneruuid": obt_uuid}),
            (PSTAT, {"rowneruuid": obt_uuid}),
            # empty privatedata: the TV derives its own copy of the owner PSK
            (CRED, {
                "creds": [{
                    "credtype": 1, "subjectuuid": obt_uuid,
                    "privatedata": {"encoding": "oic.sec.encoding.raw", "data": b""},
                }],
                "rowneruuid": obt_uuid,
            }),
            (DOXM, {"owned": True}),
        ]
        for href, body in steps:
            code = coap.post(href, body)
            _LOGGER.debug("onboard PIN %s -> %s", href, code)
            if code is None:
                msg = f"ownership step {href} got no response"
                raise OcfOnboardError(msg)
    finally:
        session.close()
    return owner_psk


def _provision_cloud(  # noqa: PLR0913, PLR0917
    ip: str,
    port: int,
    device_uuid: str,
    obt_uuid: str,
    owner_psk: bytes,
    ca_der: bytes,
    cloud_uuid: str,
    cis: str,
    access_token: str,
) -> None:
    """Over the owner session: finalize access, install CA/ACE, point `cis` at us."""
    session, coap, _ = _open(ip, port, _uuid16(obt_uuid), owner_psk)
    try:
        coap.post(ACL, {
            "aclist": {"aces": [{
                "subjectuuid": obt_uuid, "resources": [{"href": "*"}],
                "permission": _PERM_CRUDN,
            }]},
            "rowneruuid": obt_uuid,
        })
        coap.post(PSTAT, {"tm": 0, "cm": 0})  # clear TAKE_OWNER so ownership holds

        coap.post(CRED, {
            "creds": [{
                "credtype": 8, "subjectuuid": device_uuid, "credusage": "trust_ca",
                "optionaldata": {
                    "encoding": "oic.sec.encoding.der",
                    "data": ca_der,
                    "revstat": False,
                },
            }],
            "rowneruuid": obt_uuid,
        })
        _add_cloud_ace(coap, obt_uuid, cloud_uuid)
        _point_cloud(coap, cis, access_token)
    finally:
        session.close()


def _add_cloud_ace(coap: _SecureCoap, obt_uuid: str, cloud_uuid: str) -> None:
    """Add (read-modify-write) an ACE granting the cloud UUID the /sec/tv/* reads."""
    acl = coap.get(ACL)
    existing = acl.get("aclist", {}).get("aces", []) if isinstance(acl, dict) else []
    aces = [ace for ace in existing if ace.get("subjectuuid") != cloud_uuid]
    aces.append({
        "subjectuuid": cloud_uuid,
        "resources": [{"href": href} for href in _CLOUD_TARGETS] + [{"href": "*"}],
        "permission": _PERM_CRUDN,
    })
    coap.post(ACL, {"aclist": {"aces": aces}, "rowneruuid": obt_uuid},
              query="if=oic.if.baseline")


def _point_cloud(coap: _SecureCoap, cis: str, access_token: str) -> None:
    """Write `cis` after opening a provisioning session (section 14.7 kick)."""
    conf = {
        "apn": "samstream", "cis": cis, "at": access_token,
        "x.com.samsung.clientid": "samstream", "x.com.samsung.uid": "samstream",
        "x.com.samsung.refreshtoken": access_token, "x.com.samsung.iatt": 1,
    }
    for attempt in range(3):
        session_id = f"samstream{int(time.time() * 10) % 1000000:06d}"
        begin = {_PROV + "sessionid": session_id}
        agree = {_PROV + "tncagreed": True, _PROV + "sessionid": session_id}
        coap.post(PROVISIONING, begin, query="if=oic.if.a")
        coap.post(PROVISIONING, agree, query="if=oic.if.a")
        coap.post(CLOUD_CONF, conf)
        time.sleep(1)
        current = coap.get(CLOUD_CONF)
        if isinstance(current, dict) and current.get("cis") == cis:
            _LOGGER.debug("onboard: cis stored on attempt %d", attempt + 1)
            return
    msg = "the TV did not store the cloud address (cis); retry after re-provisioning"
    raise OcfOnboardError(msg)


def release_tv(
    ip: str,
    obt_uuid: str,
    owner_psk_hex: str,
    secure_port: int | None = None,
) -> None:
    """Hand the TV back to SmartThings: as owner, `POST /oic/sec/pstat {cm:1}`.

    No Smart-Hub reset; apps and settings are kept (section 7). If the owner
    session can't be opened the TV is already unowned, which is fine.
    """
    if secure_port is None:
        secure_port, _ = discover(ip)
    try:
        session, coap, _ = _open(
            ip, secure_port, _uuid16(obt_uuid), bytes.fromhex(owner_psk_hex)
        )
    except Exception as err:  # noqa: BLE001 - already unowned is acceptable
        _LOGGER.debug("release: no owner session (already released?): %s", err)
        return
    try:
        coap.post(PSTAT, {"cm": 1})
    finally:
        session.close()
