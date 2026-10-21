"""Samsung sign-in parsing, CSRs, and certificate issuing against a fake svdca."""

import datetime as dt
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote, urlencode

import aiohttp
import pytest
from aiohttp import web
from aiosamstream import samsung_cert
from aiosamstream.samsung_cert import (
    SamsungAccount,
    SamsungCertError,
    author_csr,
    certificate_duids,
    distributor_csr,
    parse_callback,
    request_certificates,
    samsung_ca,
    sign_in_url,
)
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

pytestmark = pytest.mark.enable_socket


@pytest.fixture(autouse=True)
def _never_call_samsung(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a test would reach Samsung's real certificate service."""
    real_post = aiohttp.ClientSession.post

    def guarded(self: aiohttp.ClientSession, url: str, **kwargs: Any) -> Any:
        assert "samsungqbe.com" not in str(url), f"test tried to call {url}"
        return real_post(self, url, **kwargs)

    monkeypatch.setattr(aiohttp.ClientSession, "post", guarded)


KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ACCOUNT = SamsungAccount("token-abc", "user-1", "me@example.com")
DUIDS = ["EXCBZZZZGFIFJSY", "ABCD1234WXYZ"]


def callback_body(**fields: Any) -> str:
    payload = {
        "access_token": "token-abc",
        "userId": "user-1",
        "inputEmailID": "me@example.com",
        "state": "s1",
        **fields,
    }
    return urlencode({"code": json.dumps(payload)})


def issue(csr_pem: bytes) -> bytes:
    """Sign the CSR like Samsung's CA would (DER)."""
    csr = x509.load_pem_x509_csr(csr_pem)
    now = dt.datetime.now(dt.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Fake VD CA")]))
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=365))
    )
    for extension in csr.extensions:
        builder = builder.add_extension(extension.value, critical=extension.critical)
    return builder.sign(CA_KEY, hashes.SHA256()).public_bytes(Encoding.DER)


class FakeSvdca:
    def __init__(self) -> None:
        self.forms: dict[str, dict[str, str]] = {}
        self.fail: str | None = None
        self.garbage = False

    async def handle(self, request: web.Request) -> web.Response:
        form = await request.post()
        fields = {k: v for k, v in form.items() if isinstance(v, str)}
        upload = form["csr"]
        assert isinstance(upload, web.FileField)
        fields["csr_file"] = upload.filename
        self.forms[request.path] = fields
        if self.fail:
            return web.Response(status=400, text=self.fail)
        if self.garbage:
            return web.Response(body=b"<html>maintenance</html>")
        if request.path == "/apis/v1/distributors":
            return web.Response(body=b"<profile/>")
        return web.Response(body=issue(upload.file.read()))


@pytest.fixture
async def svdca(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FakeSvdca]:
    fake = FakeSvdca()
    app = web.Application()
    app.router.add_post("/apis/{version}/{kind}", fake.handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]  # noqa: SLF001
    base = f"http://127.0.0.1:{port}/apis"
    monkeypatch.setattr(samsung_cert, "AUTHOR_URL", f"{base}/v3/authors")
    monkeypatch.setattr(
        samsung_cert, "DISTRIBUTOR_PROFILE_URL", f"{base}/v1/distributors"
    )
    monkeypatch.setattr(samsung_cert, "DISTRIBUTOR_URL", f"{base}/v3/distributors")
    yield fake
    await runner.cleanup()


def test_sign_in_url() -> None:
    url = sign_in_url("s 1")

    assert url.startswith(samsung_cert.SIGN_IN_GATE + "?")
    assert "clientId=v285zxnl3h" in url
    assert (
        "redirect_uri=" + quote("http://localhost:4794/signin/callback", safe="") in url
    )
    assert "state=s%201" in url


def test_parse_callback() -> None:
    assert parse_callback(callback_body(), "s1") == ACCOUNT


def test_parse_callback_without_state() -> None:
    """The shape of a real sign-in answer: no state at all."""
    payload = {
        "access_token": "token-abc",
        "token_type": "bearer",
        "userId": "user-1",
        "client_id": "v285zxnl3h",
        "inputEmailID": "me@example.com",
        "close": True,
        "closedAction": "signInSuccess",
    }
    body = urlencode({"code": json.dumps(payload)})
    assert parse_callback(body, "s1") == ACCOUNT


def test_parse_callback_state_as_form_field() -> None:
    account = {"access_token": "t", "userId": "u", "inputEmailID": "e"}
    body = urlencode({"code": json.dumps(account), "state": "s1"})
    assert parse_callback(body, "s1").user_id == "u"
    with pytest.raises(SamsungCertError, match="does not belong"):
        parse_callback(body, "other")


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (callback_body(state="other"), "does not belong"),
        (callback_body(access_token=""), "no access token|did not return"),
        (callback_body(inputEmailID=""), "no email"),
        ("code=not-json", "no account data"),
        ("code=%5B1%5D", "no account data"),
        ("", "no account data"),
    ],
)
def test_parse_callback_errors(body: str, message: str) -> None:
    with pytest.raises(SamsungCertError, match=message):
        parse_callback(body, "s1")


def test_csrs() -> None:
    author = x509.load_pem_x509_csr(author_csr(KEY))
    distributor = x509.load_pem_x509_csr(distributor_csr(KEY, DUIDS, "me@example.com"))

    assert author.is_signature_valid
    assert (
        author.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        == "Samstream"
    )
    assert distributor.is_signature_valid
    email = distributor.subject.get_attributes_for_oid(NameOID.EMAIL_ADDRESS)[0].value
    assert email == "me@example.com"
    san = distributor.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    assert san.value.get_values_for_type(x509.UniformResourceIdentifier) == [
        "URN:tizen:packageid=",
        "URN:tizen:deviceid=EXCBZZZZGFIFJSY",
        "URN:tizen:deviceid=ABCD1234WXYZ",
    ]


async def test_request_certificates(svdca: FakeSvdca) -> None:
    async with aiohttp.ClientSession() as session:
        issued = await request_certificates(session, ACCOUNT, KEY, DUIDS)

    author_form = svdca.forms["/apis/v3/authors"]
    assert author_form == {
        "access_token": "token-abc",
        "user_id": "user-1",
        "platform": "VD",
        "csr_file": "author.csr",
    }
    distributor_form = svdca.forms["/apis/v3/distributors"]
    assert distributor_form["privilege_level"] == "public"
    assert distributor_form["developer_type"] == "Individual"
    assert svdca.forms["/apis/v1/distributors"] == distributor_form

    assert issued.device_profile == b"<profile/>"
    assert issued.duids == tuple(DUIDS)
    assert issued.author.chain[1] == samsung_ca("vd_tizen_dev_author_ca.cer")
    assert issued.distributor.chain[1] == samsung_ca("vd_tizen_dev_public2.crt")
    assert certificate_duids(issued.distributor.chain[0]) == DUIDS
    assert certificate_duids(issued.author.chain[0]) == []
    assert issued.author.key is KEY


async def test_partner_level(svdca: FakeSvdca) -> None:
    async with aiohttp.ClientSession() as session:
        issued = await request_certificates(
            session, ACCOUNT, KEY, DUIDS, privilege="partner"
        )

    assert svdca.forms["/apis/v3/distributors"]["privilege_level"] == "partner"
    assert issued.distributor.chain[1] == samsung_ca("vd_tizen_dev_partner2.crt")


async def test_unknown_privilege() -> None:
    with pytest.raises(ValueError, match="privilege"):
        async with aiohttp.ClientSession() as session:
            await request_certificates(
                session, ACCOUNT, KEY, DUIDS, privilege="platform"
            )


async def test_samsung_refuses(svdca: FakeSvdca) -> None:
    svdca.fail = '{"error":"access_token expired"}'
    with pytest.raises(SamsungCertError, match=r"400.*expired"):
        async with aiohttp.ClientSession() as session:
            await request_certificates(session, ACCOUNT, KEY, DUIDS)


async def test_not_a_certificate(svdca: FakeSvdca) -> None:
    svdca.garbage = True
    with pytest.raises(SamsungCertError, match="not a certificate"):
        async with aiohttp.ClientSession() as session:
            await request_certificates(session, ACCOUNT, KEY, DUIDS)


async def test_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AUTHOR_URL", "DISTRIBUTOR_PROFILE_URL", "DISTRIBUTOR_URL"):
        monkeypatch.setattr(samsung_cert, name, "http://127.0.0.1:1/apis/x")
    with pytest.raises(SamsungCertError, match="Cannot reach"):
        async with aiohttp.ClientSession() as session:
            await request_certificates(session, ACCOUNT, KEY, DUIDS)
