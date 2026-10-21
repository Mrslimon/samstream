"""Widget signing: structure, verifiable signatures, and Tizen Studio golden values."""

import base64
import datetime as dt
import hashlib
import io
import re
import zipfile

import pytest
from aiosamstream.signing import (
    SigningError,
    SigningIdentity,
    package_app_id,
    package_version,
    sign_wgt,
)
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

# `#prop` digests from a package signed by Tizen Studio (the object never varies).
TIZEN_PROP_AUTHOR = (
    "aXbSAVgmAz0GsBUeZ1UmNDRrxkWhDUVGb45dZcNRq429wX3X+x6kaXT3"
    "NdNDTSNVTU+ypkysPMGvQY10fG1EWQ=="
)
TIZEN_PROP_DISTRIBUTOR = (
    "/r5npk2VVA46QFJnejgONBEh4BWtjrtu9x/IFeLksjWyGmB/cMWKSJW"
    "Ql7aU3YRQRZ3AesG8gF7qGyvKX9Snig=="
)
DSIG = "http://www.w3.org/2000/09/xmldsig#"
CONFIG = (
    b'<?xml version="1.0"?><widget xmlns:tizen="http://tizen.org/ns/widgets" '
    b'version="0.1.0">'
    b'<tizen:application id="SmStrm0001.Samstream" package="SmStrm0001"/></widget>'
)


def _cert(
    name: str,
    key: rsa.RSAPrivateKey,
    issuer: x509.Name | None,
    signer: rsa.RSAPrivateKey,
) -> x509.Certificate:
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = dt.datetime.now(dt.UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer or subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=1))
        .sign(signer, hashes.SHA256())
    )


@pytest.fixture(scope="module")
def p12() -> tuple[bytes, x509.Certificate, x509.Certificate, x509.Certificate]:
    """author.p12-like bundle: leaf key + leaf, intermediate and root certificates."""
    root_key, mid_key, leaf_key = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(3)
    )
    root = _cert("Root CA", root_key, None, root_key)
    mid = _cert("Samsung VD Author CA", mid_key, root.subject, root_key)
    leaf = _cert("Samstream", leaf_key, mid.subject, mid_key)
    data = pkcs12.serialize_key_and_certificates(
        b"usercertificate",
        leaf_key,
        leaf,
        [mid, root],
        serialization.BestAvailableEncryption(b"secret"),
    )
    return data, leaf, mid, root


@pytest.fixture(scope="module")
def identity(
    p12: tuple[bytes, x509.Certificate, x509.Certificate, x509.Certificate],
) -> SigningIdentity:
    return SigningIdentity.from_p12(p12[0], "secret")


def make_wgt() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("config.xml", CONFIG)
        archive.writestr("index.html", b"<html></html>")
        archive.writestr("assets/", b"")
        archive.writestr("assets/main file.js", b"console.log(1)")
        archive.writestr("author-signature.xml", b"<old/>")
        archive.writestr("signature1.xml", b"<old/>")
    return out.getvalue()


def references(xml: str) -> dict[str, str]:
    return dict(
        re.findall(
            r'<Reference URI="([^"]+)">.*?<DigestValue>([^<]+)</DigestValue>', xml
        )
    )


def verify(xml: str, leaf: x509.Certificate) -> None:
    """Check the signature the way the TV does, from the serialized file text."""
    signed_info = re.search(r"<SignedInfo>.*?</SignedInfo>", xml)
    assert signed_info is not None
    canonical = signed_info.group(0).replace(
        "<SignedInfo>", f'<SignedInfo xmlns="{DSIG}">', 1
    )
    value = re.search(r"<SignatureValue>([^<]+)</SignatureValue>", xml)
    assert value is not None
    public_key = leaf.public_key()
    assert isinstance(public_key, rsa.RSAPublicKey)
    public_key.verify(
        base64.b64decode(value.group(1)),
        canonical.encode(),
        padding.PKCS1v15(),
        hashes.SHA512(),
    )


def test_identity_drops_root(
    identity: SigningIdentity,
    p12: tuple[bytes, x509.Certificate, x509.Certificate, x509.Certificate],
) -> None:
    _, leaf, mid, _root = p12
    assert identity.chain == (leaf, mid)


def test_signed_package_layout(identity: SigningIdentity) -> None:
    signed = sign_wgt(make_wgt(), identity, identity)
    with zipfile.ZipFile(io.BytesIO(signed)) as archive:
        names = archive.namelist()
        assert names == [
            "author-signature.xml",
            "signature1.xml",
            "config.xml",
            "index.html",
            "assets/main file.js",
        ]
        assert archive.read("assets/main file.js") == b"console.log(1)"
        assert b"<old/>" not in archive.read("author-signature.xml")


def test_references_and_digests(identity: SigningIdentity) -> None:
    signed = sign_wgt(make_wgt(), identity, identity)
    archive = zipfile.ZipFile(io.BytesIO(signed))
    author = archive.read("author-signature.xml").decode()
    distributor = archive.read("signature1.xml").decode()

    def digest(data: bytes) -> str:
        return base64.b64encode(hashlib.sha512(data).digest()).decode()

    author_refs = references(author)
    assert list(author_refs) == [
        "assets%2Fmain%20file.js",
        "config.xml",
        "index.html",
        "#prop",
    ]
    assert author_refs["config.xml"] == digest(CONFIG)
    assert author_refs["#prop"] == TIZEN_PROP_AUTHOR

    distributor_refs = references(distributor)
    assert list(distributor_refs) == [
        "assets%2Fmain%20file.js",
        "author-signature.xml",
        "config.xml",
        "index.html",
        "#prop",
    ]
    assert distributor_refs["author-signature.xml"] == digest(author.encode())
    assert distributor_refs["#prop"] == TIZEN_PROP_DISTRIBUTOR
    assert 'Id="AuthorSignature"' in author
    assert "role-distributor" in distributor


def test_signatures_verify_and_carry_chain(
    identity: SigningIdentity,
    p12: tuple[bytes, x509.Certificate, x509.Certificate, x509.Certificate],
) -> None:
    _, leaf, mid, _root = p12
    signed = sign_wgt(make_wgt(), identity, identity)
    archive = zipfile.ZipFile(io.BytesIO(signed))
    for name in ("author-signature.xml", "signature1.xml"):
        xml = archive.read(name).decode()
        verify(xml, leaf)
        embedded = [
            x509.load_der_x509_certificate(base64.b64decode(re.sub(r"\s", "", block)))
            for block in re.findall(
                r"<X509Certificate>(.*?)</X509Certificate>", xml, re.DOTALL
            )
        ]
        assert embedded == [leaf, mid]


def test_wrong_password(
    p12: tuple[bytes, x509.Certificate, x509.Certificate, x509.Certificate],
) -> None:
    with pytest.raises(SigningError, match="password"):
        SigningIdentity.from_p12(p12[0], "nope")


def test_p12_without_key(
    p12: tuple[bytes, x509.Certificate, x509.Certificate, x509.Certificate],
) -> None:
    cert_only = pkcs12.serialize_key_and_certificates(
        None, None, None, [p12[1]], serialization.NoEncryption()
    )
    with pytest.raises(SigningError, match="no RSA key"):
        SigningIdentity.from_p12(cert_only, None)


def test_package_app_id() -> None:
    assert package_app_id(make_wgt()) == "SmStrm0001.Samstream"


def test_package_version() -> None:
    assert package_version(make_wgt()) == "0.1.0"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("config.xml", b"<widget/>")
    with pytest.raises(SigningError, match="no widget version"):
        package_version(out.getvalue())


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ({"index.html": b"x"}, "config.xml missing"),
        ({"config.xml": b"<widget/>"}, "no tizen"),
    ],
)
def test_package_app_id_errors(content: dict[str, bytes], message: str) -> None:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in content.items():
            archive.writestr(name, data)
    with pytest.raises(SigningError, match=message):
        package_app_id(out.getvalue())


def test_not_a_zip(identity: SigningIdentity) -> None:
    with pytest.raises(SigningError):
        sign_wgt(b"not a zip", identity, identity)
    with pytest.raises(SigningError):
        package_app_id(b"not a zip")
