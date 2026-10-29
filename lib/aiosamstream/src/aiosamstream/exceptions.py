"""Exceptions raised by aiosamstream."""


class SamstreamError(Exception):
    """Base error."""


class SamstreamConnectionError(SamstreamError):
    """The TV could not be reached."""


class SamstreamTimeoutError(SamstreamConnectionError):
    """The TV did not answer in time, e.g. nobody accepted the pairing popup."""


class SamstreamAuthError(SamstreamError):
    """The TV rejected or revoked the pairing token."""


class SdbError(SamstreamError):
    """An sdb (Smart Development Bridge) operation failed."""


class SdbConnectionError(SdbError):
    """sdbd did not accept a connection: Developer Mode off or another host IP."""


class OcfError(SamstreamError):
    """An OCF (local SmartThings) request failed or was refused."""


class OcfNotConnectedError(OcfError):
    """The TV is not connected to the local OCF cloud right now."""


class OcfHandshakeError(OcfError):
    """The DTLS-PSK handshake to the TV's secure endpoint failed.

    Usually a wrong or expired PIN, the TV not being in Random-PIN mode, or the
    secure port having rotated.
    """


class OcfOnboardError(OcfError):
    """Onboarding (ownership transfer or cloud provisioning) did not complete."""


class OcfTvOwnedError(OcfOnboardError):
    """The TV already has an owner (usually SmartThings), so it shows no PIN.

    It must be removed from SmartThings (or released) before it can be onboarded.
    """
