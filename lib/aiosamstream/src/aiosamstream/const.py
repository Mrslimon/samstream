"""Constants shared by the library."""

from typing import Final

# Tizen application id of the Samstream player (package id + app name).
SAMSTREAM_PACKAGE_ID: Final = "SmStrm0001"
SAMSTREAM_APP_ID: Final = f"{SAMSTREAM_PACKAGE_ID}.Samstream"

# Only the TLS port issues a pairing token; 8001 would re-prompt on every connect.
WS_PORT_SECURE: Final = 8002
REST_PORT: Final = 8001
SDB_PORT: Final = 26101
UPNP_PORT: Final = 9197

# Must stay identical across connections, the TV binds trust to name + token.
CLIENT_NAME: Final = "Home Assistant Samstream"
