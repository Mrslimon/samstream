"""The local OCF cloud's identity: a private CA and the server certificate.

The TV trusts the CA (installed as a `trust_ca` credential during onboarding)
and maps the connection to its cloud ACL entry by the UUID in the server
certificate's Common Name (OCF Cloud Security, clause 5). The SAN carries the
address the TV dials, so the certificate is re-issued when that changes.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import ssl
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

_CA_NAME = "Samstream Local Cloud CA"
_VALID = dt.timedelta(days=3650)
_PEM = serialization.Encoding.PEM


@dataclass(frozen=True, slots=True)
class CloudIdentity:
    """The cloud UUID plus the CA that signs its server certificates (PEM)."""

    cloud_uuid: str
    ca_cert_pem: bytes
    ca_key_pem: bytes

    @property
    def ca_der(self) -> bytes:
        """The CA certificate in DER, as the sign-up reply hands it to the TV."""
        cert = x509.load_pem_x509_certificate(self.ca_cert_pem)
        return cert.public_bytes(serialization.Encoding.DER)


def _key_pem(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        _PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def generate_identity(cloud_uuid: str | None = None) -> CloudIdentity:
    """Create a CA (ECDSA P-256) for a new cloud UUID. Blocking (key generation)."""
    cloud_uuid = cloud_uuid or str(uuid.uuid4())
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _CA_NAME)])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + _VALID)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return CloudIdentity(cloud_uuid, cert.public_bytes(_PEM), _key_pem(key))


def load_identity(ca_cert: bytes, ca_key_pem: bytes, cloud_uuid: str) -> CloudIdentity:
    """Load an existing identity (e.g. a PC-run cloud's), CA in DER or PEM."""
    cert = (
        x509.load_pem_x509_certificate(ca_cert)
        if ca_cert.lstrip().startswith(b"-----")
        else x509.load_der_x509_certificate(ca_cert)
    )
    key = serialization.load_pem_private_key(ca_key_pem, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        msg = "the CA key must be an EC key"
        raise TypeError(msg)
    public = cert.public_key()
    if (
        not isinstance(public, ec.EllipticCurvePublicKey)
        or public.public_numbers() != key.public_key().public_numbers()
    ):
        msg = "the CA key does not match the CA certificate"
        raise ValueError(msg)
    str(uuid.UUID(cloud_uuid))  # validates
    return CloudIdentity(cloud_uuid, cert.public_bytes(_PEM), _key_pem(key))


def issue_server_certificate(identity: CloudIdentity, host: str) -> tuple[bytes, bytes]:
    """Issue (chain PEM, key PEM) with CN = cloud UUID, SAN = the dialled host."""
    ca_cert = x509.load_pem_x509_certificate(identity.ca_cert_pem)
    ca_key = serialization.load_pem_private_key(identity.ca_key_pem, password=None)
    if not isinstance(ca_key, ec.EllipticCurvePrivateKey):
        msg = "the CA key must be an EC key"
        raise TypeError(msg)
    try:
        san: x509.GeneralName = x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        san = x509.DNSName(host)
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, identity.cloud_uuid)])
        )
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + _VALID)
        .add_extension(x509.SubjectAlternativeName([san]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    return cert.public_bytes(_PEM) + identity.ca_cert_pem, _key_pem(key)


def server_ssl_context(chain_pem: bytes, key_pem: bytes) -> ssl.SSLContext:
    """Build a TLS 1.2+ server context for the cloud port. Blocking (file I/O).

    `load_cert_chain` only reads files, so the PEMs pass through a private
    temporary directory that is removed straight after.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with tempfile.TemporaryDirectory(prefix="samstream-ocf-") as folder:
        cert_path = Path(folder) / "cloud.crt"
        key_path = Path(folder) / "cloud.key"
        cert_path.write_bytes(chain_pem)
        key_path.touch(mode=0o600)
        key_path.write_bytes(key_pem)
        context.load_cert_chain(cert_path, key_path)
    return context
