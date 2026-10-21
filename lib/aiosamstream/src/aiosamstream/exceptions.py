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
