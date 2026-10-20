"""Constants for the Samstream integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "samstream"

CONF_TOKEN: Final = "token"
CONF_TV_SECRET: Final = "tv_secret"
CONF_WOL_TARGET: Final = "wol_target"
CONF_HA_URL: Final = "ha_url"

# Power state only: a TV is polled cheaply over REST, volume over UPnP when on.
SCAN_INTERVAL: Final = timedelta(seconds=10)
