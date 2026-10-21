"""Get a Samsung author + distributor certificate for sideloading on Tizen 7+ TVs.

Retail TVs only install packages signed with a Samsung distributor certificate that
lists their DUID. This is the flow Tizen Studio's Certificate Manager and
Apps2Samsung (MIT) use:

1. Sign in with a Samsung account at SignInGate. It only redirects to exactly
   `http://localhost:4794/signin/callback`, POSTing a form whose `code` field is
   URL-encoded JSON (`access_token`, `userId`, `inputEmailID`, `state`, ...).
2. Create one RSA key with an author CSR and a distributor CSR (SAN
   `URN:tizen:deviceid=<DUID>` per TV).
3. POST the CSRs to Samsung's developer CA (svdca.samsungqbe.com), then chain the
   issued certificates with Samsung's public intermediates (bundled in `ca/`).

Adding a TV later only needs a new distributor certificate; the author key stays,
so already installed apps keep upgrading.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from importlib import resources
from urllib.parse import parse_qs, quote

import aiohttp
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

from .exceptions import SamstreamError
from .signing import SigningIdentity

SIGN_IN_GATE = (
    "https://account.samsung.com/accounts/be1dce529476c1a6d407c4c7578c31bd/signInGate"
)
CLIENT_ID = "v285zxnl3h"
CALLBACK_PORT = 4794
CALLBACK_PATH = "/signin/callback"
CALLBACK_URL = f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"

AUTHOR_URL = "https://svdca.samsungqbe.com/apis/v3/authors"
DISTRIBUTOR_PROFILE_URL = "https://svdca.samsungqbe.com/apis/v1/distributors"
DISTRIBUTOR_URL = "https://svdca.samsungqbe.com/apis/v3/distributors"

_AUTHOR_CA = "vd_tizen_dev_author_ca.cer"
_DISTRIBUTOR_CA = {
    "public": "vd_tizen_dev_public2.crt",
    "partner": "vd_tizen_dev_partner2.crt",
}
_TIMEOUT = aiohttp.ClientTimeout(total=60)


class SamsungCertError(SamstreamError):
    """Samsung sign-in or certificate issuing failed."""


@dataclass(frozen=True)
class SamsungAccount:
    """What the sign-in callback hands over (short-lived)."""

    access_token: str
    user_id: str
    email: str


@dataclass(frozen=True)
class IssuedCertificates:
    """Signing identities ready for `sign_wgt`, plus the device profile."""

    author: SigningIdentity
    distributor: SigningIdentity
    duids: tuple[str, ...]
    device_profile: bytes


def new_state() -> str:
    """Return a random `state` for one sign-in (echoed back by SignInGate)."""
    return secrets.token_urlsafe(24)


def sign_in_url(state: str) -> str:
    """URL to open in a browser on the machine running the callback listener."""
    return (
        f"{SIGN_IN_GATE}?locale=&clientId={CLIENT_ID}"
        f"&redirect_uri={quote(CALLBACK_URL, safe='')}"
        f"&state={quote(state, safe='')}&tokenType=TOKEN"
    )


def parse_callback(body: str, expected_state: str) -> SamsungAccount:
    """Read the form body SignInGate POSTs to the callback URL."""
    code = parse_qs(body).get("code", [""])[0]
    try:
        payload = json.loads(code)
    except json.JSONDecodeError as err:
        msg = "Samsung sign-in sent no account data"
        raise SamsungCertError(msg) from err
    if payload.get("state") != expected_state:
        msg = "Samsung sign-in answer does not belong to this request"
        raise SamsungCertError(msg)
    account = SamsungAccount(
        access_token=str(payload.get("access_token") or ""),
        user_id=str(payload.get("userId") or ""),
        email=str(payload.get("inputEmailID") or ""),
    )
    if not account.access_token or not account.user_id:
        msg = "Samsung sign-in did not return an access token"
        raise SamsungCertError(msg)
    if not account.email:
        msg = "The Samsung account has no email address, which the certificate needs"
        raise SamsungCertError(msg)
    return account


def author_csr(key: rsa.RSAPrivateKey, name: str = "Samstream") -> bytes:
    """Build the author certificate request (PEM)."""
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    return (
        x509.CertificateSigningRequestBuilder()
        .subject_name(subject)
        .sign(key, hashes.SHA256())
        .public_bytes(Encoding.PEM)
    )


def distributor_csr(key: rsa.RSAPrivateKey, duids: list[str], email: str) -> bytes:
    """Build the distributor request listing every TV it may install on (PEM)."""
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "TizenSDK"),
            x509.NameAttribute(NameOID.EMAIL_ADDRESS, email),
        ]
    )
    names: list[x509.GeneralName] = [
        x509.UniformResourceIdentifier("URN:tizen:packageid=")
    ]
    names += [
        x509.UniformResourceIdentifier(f"URN:tizen:deviceid={duid}") for duid in duids
    ]
    return (
        x509.CertificateSigningRequestBuilder()
        .subject_name(subject)
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .sign(key, hashes.SHA256())
        .public_bytes(Encoding.PEM)
    )


def samsung_ca(file_name: str) -> x509.Certificate:
    """Load one of Samsung's public intermediate CAs bundled with the library."""
    data = (resources.files(__package__) / "ca" / file_name).read_bytes()
    return _load_certificate(data)


async def request_certificates(
    session: aiohttp.ClientSession,
    account: SamsungAccount,
    key: rsa.RSAPrivateKey,
    duids: list[str],
    *,
    privilege: str = "public",
) -> IssuedCertificates:
    """Have Samsung issue an author and a distributor certificate for `key`."""
    _check_privilege(privilege)
    author = await request_author(session, account, key)
    distributor, profile = await request_distributor(
        session, account, key, duids, privilege=privilege
    )
    return IssuedCertificates(
        author=author,
        distributor=distributor,
        duids=tuple(duids),
        device_profile=profile,
    )


async def request_author(
    session: aiohttp.ClientSession, account: SamsungAccount, key: rsa.RSAPrivateKey
) -> SigningIdentity:
    """Request the author certificate (who built the app: keep it across TVs)."""
    der = await _post_csr(
        session, AUTHOR_URL, account, ("author.csr", author_csr(key)), {}
    )
    return SigningIdentity(
        key=key, chain=(_load_certificate(der), samsung_ca(_AUTHOR_CA))
    )


async def request_distributor(
    session: aiohttp.ClientSession,
    account: SamsungAccount,
    key: rsa.RSAPrivateKey,
    duids: list[str],
    *,
    privilege: str = "public",
) -> tuple[SigningIdentity, bytes]:
    """Request a distributor certificate for `duids` (renewed when a TV is added)."""
    _check_privilege(privilege)
    fields = {"privilege_level": privilege, "developer_type": "Individual"}
    request = ("distributor.csr", distributor_csr(key, duids, account.email))
    profile = await _post_csr(
        session, DISTRIBUTOR_PROFILE_URL, account, request, fields
    )
    der = await _post_csr(session, DISTRIBUTOR_URL, account, request, fields)
    identity = SigningIdentity(
        key=key, chain=(_load_certificate(der), samsung_ca(_DISTRIBUTOR_CA[privilege]))
    )
    return identity, profile


def _check_privilege(privilege: str) -> None:
    if privilege not in _DISTRIBUTOR_CA:
        msg = f"Unknown privilege level {privilege!r}"
        raise ValueError(msg)


def certificate_duids(certificate: x509.Certificate) -> list[str]:
    """Return the DUIDs a distributor certificate covers (from its SAN URNs)."""
    try:
        san = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        )
    except x509.ExtensionNotFound:
        return []
    prefix = "URN:tizen:deviceid="
    return [
        uri.removeprefix(prefix)
        for uri in san.value.get_values_for_type(x509.UniformResourceIdentifier)
        if uri.startswith(prefix)
    ]


async def _post_csr(
    session: aiohttp.ClientSession,
    url: str,
    account: SamsungAccount,
    upload: tuple[str, bytes],
    extra: dict[str, str],
) -> bytes:
    file_name, csr = upload
    form = aiohttp.FormData()
    form.add_field("access_token", account.access_token)
    form.add_field("user_id", account.user_id)
    for name, value in extra.items():
        form.add_field(name, value)
    form.add_field("platform", "VD")
    form.add_field(
        "csr", csr, filename=file_name, content_type="application/octet-stream"
    )
    try:
        async with session.post(url, data=form, timeout=_TIMEOUT) as response:
            body = await response.read()
            status = response.status
    except (aiohttp.ClientError, TimeoutError) as err:
        msg = "Cannot reach Samsung's certificate service"
        raise SamsungCertError(msg) from err
    if status != 200:  # noqa: PLR2004
        detail = body.decode(errors="replace")[:300]
        msg = f"Samsung refused the certificate request ({status}): {detail}"
        raise SamsungCertError(msg)
    return body


def _load_certificate(data: bytes) -> x509.Certificate:
    try:
        if b"-----BEGIN" in data:
            return x509.load_pem_x509_certificate(data)
        return x509.load_der_x509_certificate(data)
    except ValueError as err:
        msg = "Samsung returned something that is not a certificate"
        raise SamsungCertError(msg) from err
