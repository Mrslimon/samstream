"""Certificates HA signs the Samstream TV app with (one set per HA installation).

Kept in private storage: the RSA keys never leave this machine. The author key is
reused when TVs are added, so updates of an installed app stay possible.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from aiosamstream.samsung_cert import certificate_duids
from aiosamstream.signing import SigningIdentity
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_STORE_VERSION = 1
_STORE_KEY = f"{DOMAIN}.signing"

SOURCE_SAMSUNG = "samsung"
SOURCE_IMPORT = "import"


@dataclass(frozen=True)
class SigningSetup:
    """Author + distributor identities and where they came from."""

    author: SigningIdentity
    distributor: SigningIdentity
    source: str
    email: str | None = None

    @property
    def duids(self) -> list[str]:
        """TVs the distributor certificate allows installs on."""
        return certificate_duids(self.distributor.chain[0])

    @property
    def expires(self) -> dt.datetime:
        """When the first of the two certificates stops being valid."""
        return min(
            self.author.chain[0].not_valid_after_utc,
            self.distributor.chain[0].not_valid_after_utc,
        )

    def covers(self, duid: str) -> bool:
        """Tell whether packages signed with this setup install on that TV."""
        return duid in self.duids


def _store(hass: HomeAssistant) -> Store[dict[str, object]]:
    return Store(hass, _STORE_VERSION, _STORE_KEY, private=True)


def _key_pem(key: rsa.RSAPrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _identity_to_dict(identity: SigningIdentity) -> dict[str, object]:
    return {
        "key": _key_pem(identity.key),
        "chain": [
            cert.public_bytes(serialization.Encoding.PEM).decode()
            for cert in identity.chain
        ],
    }


def _identity_from_dict(data: dict[str, object]) -> SigningIdentity:
    key = serialization.load_pem_private_key(str(data["key"]).encode(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        msg = "Stored signing key is not RSA"
        raise TypeError(msg)
    chain = data["chain"]
    if not isinstance(chain, list):
        msg = "Stored certificate chain is malformed"
        raise TypeError(msg)
    certs = tuple(x509.load_pem_x509_certificate(str(pem).encode()) for pem in chain)
    return SigningIdentity(key=key, chain=certs)


async def async_load_signing(hass: HomeAssistant) -> SigningSetup | None:
    """Return the stored signing setup, if app signing was set up."""
    data = await _store(hass).async_load()
    if not data:
        return None
    author = data.get("author")
    distributor = data.get("distributor")
    if not isinstance(author, dict) or not isinstance(distributor, dict):
        return None
    return await hass.async_add_executor_job(
        _setup_from_dict, data, author, distributor
    )


def _setup_from_dict(
    data: dict[str, object],
    author: dict[str, object],
    distributor: dict[str, object],
) -> SigningSetup:
    email = data.get("email")
    return SigningSetup(
        author=_identity_from_dict(author),
        distributor=_identity_from_dict(distributor),
        source=str(data.get("source", SOURCE_IMPORT)),
        email=str(email) if email else None,
    )


async def async_save_signing(hass: HomeAssistant, setup: SigningSetup) -> None:
    """Persist a signing setup (replaces the previous one)."""
    await _store(hass).async_save(
        {
            "source": setup.source,
            "email": setup.email,
            "author": _identity_to_dict(setup.author),
            "distributor": _identity_to_dict(setup.distributor),
        }
    )
