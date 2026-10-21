"""Sign a Tizen web app (.wgt) with an author and a distributor certificate.

Produces the same `author-signature.xml` / `signature1.xml` as Tizen Studio (W3C
widget digital signatures): SHA-512 file digests, an `#prop` object digested with
C14N 1.1, SignedInfo canonicalized with exclusive C14N and signed RSA-SHA512, and
KeyInfo carrying the leaf plus intermediates (no root). Layout reference:
PatrickSt1991/tizen-sdb (MIT).

The XML is written directly in canonical form (sorted attributes, explicit end tags,
C14N escaping, namespace declarations where a canonicalizer puts them), so the bytes
hashed here are exactly what the TV's verifier computes, without an XML library.
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
import textwrap
import warnings
import zipfile
from dataclasses import dataclass
from urllib.parse import quote

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12

from .exceptions import SamstreamError

DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
DSP_NS = "http://www.w3.org/2009/xmldsig-properties"
EXC_C14N = "http://www.w3.org/2001/10/xml-exc-c14n#"
C14N_11 = "http://www.w3.org/2006/12/xml-c14n11"
RSA_SHA512 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha512"
SHA512 = "http://www.w3.org/2001/04/xmlenc#sha512"

AUTHOR_FILE = "author-signature.xml"
DISTRIBUTOR_FILE = "signature1.xml"
_SIGNATURE_FILES = re.compile(
    r"(^|/)(author-signature|signature\d+)\.xml$", re.IGNORECASE
)
_APP_ID = re.compile(r"<tizen:application\b[^>]*\bid=\"([^\"]+)\"")


class SigningError(SamstreamError):
    """The package or the certificates cannot be used for signing."""


@dataclass(frozen=True)
class SigningIdentity:
    """A private key and its certificate chain (leaf first, no root)."""

    key: rsa.RSAPrivateKey
    chain: tuple[x509.Certificate, ...]

    @classmethod
    def from_p12(cls, data: bytes, password: str | bytes | None) -> SigningIdentity:
        """Load an author.p12 / distributor.p12 (Tizen Studio, Apps2Samsung, HA)."""
        secret = password.encode() if isinstance(password, str) else password
        try:
            # Samsung-issued certificates trip cryptography's strict-parsing warnings.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                key, leaf, extra = pkcs12.load_key_and_certificates(data, secret)
        except ValueError as err:
            msg = "Cannot open the certificate file (wrong password?)"
            raise SigningError(msg) from err
        if not isinstance(key, rsa.RSAPrivateKey) or leaf is None:
            msg = "The certificate file has no RSA key and certificate"
            raise SigningError(msg)
        intermediates = [
            cert for cert in extra if cert.subject != cert.issuer and cert != leaf
        ]
        return cls(key=key, chain=(leaf, *intermediates))


def package_app_id(wgt: bytes) -> str:
    """Return the `tizen:application` id from config.xml (e.g. SmStrm0001.Samstream)."""
    try:
        with zipfile.ZipFile(io.BytesIO(wgt)) as archive:
            config = archive.read("config.xml").decode()
    except (zipfile.BadZipFile, KeyError) as err:
        msg = "Not a Tizen web app: config.xml missing"
        raise SigningError(msg) from err
    if match := _APP_ID.search(config):
        return match.group(1)
    msg = "config.xml has no tizen:application id"
    raise SigningError(msg)


def sign_wgt(
    wgt: bytes, author: SigningIdentity, distributor: SigningIdentity
) -> bytes:
    """Return the package re-signed by `author` and `distributor`."""
    try:
        with zipfile.ZipFile(io.BytesIO(wgt)) as archive:
            files = [
                (info.filename, archive.read(info))
                for info in archive.infolist()
                if not info.is_dir() and not _SIGNATURE_FILES.search(info.filename)
            ]
    except zipfile.BadZipFile as err:
        msg = "Not a zip/.wgt package"
        raise SigningError(msg) from err

    author_xml = _signature_xml("AuthorSignature", "author", files, author)
    distributor_xml = _signature_xml(
        "DistributorSignature",
        "distributor",
        [(AUTHOR_FILE, author_xml), *files],
        distributor,
    )

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(AUTHOR_FILE, author_xml)
        archive.writestr(DISTRIBUTOR_FILE, distributor_xml)
        for name, data in files:
            archive.writestr(name, data)
    return out.getvalue()


def _signature_xml(
    signature_id: str,
    role: str,
    files: list[tuple[str, bytes]],
    identity: SigningIdentity,
) -> bytes:
    # Tizen Studio lists references sorted by path (author-signature.xml included).
    references = "".join(
        _reference(_uri(name), _digest(data), transform=None)
        for name, data in sorted(files, key=lambda item: item[0])
    )
    prop = _prop_object(signature_id, role)
    # C14N 1.1 of the Object subtree: the default namespace in scope from <Signature>
    # is rendered on it.
    prop_canonical = prop.replace("<Object ", f'<Object xmlns="{DSIG_NS}" ', 1)
    references += _reference(
        "#prop", _digest(prop_canonical.encode()), transform=C14N_11
    )
    signed_info_body = (
        f'<CanonicalizationMethod Algorithm="{EXC_C14N}"></CanonicalizationMethod>'
        f'<SignatureMethod Algorithm="{RSA_SHA512}"></SignatureMethod>'
        f"{references}"
    )
    # Exclusive C14N of SignedInfo renders the (visibly used) default namespace.
    signed_info_canonical = (
        f'<SignedInfo xmlns="{DSIG_NS}">{signed_info_body}</SignedInfo>'
    )
    signature = identity.key.sign(
        signed_info_canonical.encode(), padding.PKCS1v15(), hashes.SHA512()
    )
    certificates = "".join(
        "<X509Certificate>\n"
        + "\n".join(
            textwrap.wrap(
                base64.b64encode(cert.public_bytes(Encoding.DER)).decode(), 76
            )
        )
        + "\n</X509Certificate>"
        for cert in identity.chain
    )
    return (
        f'<Signature xmlns="{DSIG_NS}" Id="{signature_id}">'
        f"<SignedInfo>{signed_info_body}</SignedInfo>"
        f"<SignatureValue>{base64.b64encode(signature).decode()}</SignatureValue>"
        f"<KeyInfo><X509Data>{certificates}</X509Data></KeyInfo>"
        f"{prop}"
        "</Signature>"
    ).encode()


def _prop_object(signature_id: str, role: str) -> str:
    def prop(prop_id: str, element: str, uri: str | None) -> str:
        uri_attr = f' URI="{_attr(uri)}"' if uri else ""
        return (
            f'<SignatureProperty Id="{prop_id}" Target="#{signature_id}">'
            f"<dsp:{element}{uri_attr}></dsp:{element}>"
            "</SignatureProperty>"
        )

    return (
        '<Object Id="prop">'
        f'<SignatureProperties xmlns:dsp="{DSP_NS}">'
        + prop("profile", "Profile", "http://www.w3.org/ns/widgets-digsig#profile")
        + prop("role", "Role", f"http://www.w3.org/ns/widgets-digsig#role-{role}")
        + prop("identifier", "Identifier", None)
        + "</SignatureProperties></Object>"
    )


def _reference(uri: str, digest: str, *, transform: str | None) -> str:
    transforms = (
        f'<Transforms><Transform Algorithm="{transform}"></Transform></Transforms>'
        if transform
        else ""
    )
    return (
        f'<Reference URI="{_attr(uri)}">{transforms}'
        f'<DigestMethod Algorithm="{SHA512}"></DigestMethod>'
        f"<DigestValue>{digest}</DigestValue></Reference>"
    )


def _digest(data: bytes) -> str:
    return base64.b64encode(hashlib.sha512(data).digest()).decode()


def _uri(name: str) -> str:
    """Zip path as a URI the way Tizen Studio writes it (even "/" is encoded)."""
    return quote(name, safe="-._~")


def _attr(value: str) -> str:
    """Escape an attribute value the way C14N serializes it."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace('"', "&quot;")
        .replace("\t", "&#x9;")
        .replace("\n", "&#xA;")
        .replace("\r", "&#xD;")
    )
