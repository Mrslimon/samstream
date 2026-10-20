import aiosamstream
from aiosamstream.const import CLIENT_NAME, WS_PORT_SECURE


def test_public_api() -> None:
    assert aiosamstream.SAMSTREAM_APP_ID.endswith(".Samstream")
    assert issubclass(aiosamstream.SamstreamAuthError, aiosamstream.SamstreamError)


def test_pairing_constants() -> None:
    assert WS_PORT_SECURE == 8002
    assert CLIENT_NAME
