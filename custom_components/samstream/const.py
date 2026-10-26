"""Constants for the Samstream integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "samstream"

CONF_TOKEN: Final = "token"
CONF_TV_SECRET: Final = "tv_secret"
# The TV's DUID (read over sdb once, kept for certificates covering every TV).
CONF_DUID: Final = "duid"
CONF_WOL_TARGET: Final = "wol_target"
CONF_HA_URL: Final = "ha_url"
CONF_EXTRA_APPS: Final = "extra_apps"
CONF_LANGUAGE: Final = "language"
CONF_THEME: Final = "theme"
# Install newer bundled TV apps by themselves (when the TV is on and idle).
CONF_AUTO_UPDATE: Final = "auto_update"
# Press Play on the app Samstream interrupted when going back to it.
CONF_RESUME: Final = "resume_playback"
# The Frame: what turning it off does ("art": Art Mode, "off": fully off).
CONF_FRAME_POWER: Final = "frame_power"
FRAME_POWER_MODES: Final = ("art", "off")

# TV app UI: "auto" follows the TV's own language.
LANGUAGES: Final = ("auto", "ar", "en")
THEMES: Final = ("light", "dark")
DEFAULT_LANGUAGE: Final = "auto"
DEFAULT_THEME: Final = "light"
CONF_AUTHOR_P12: Final = "author_p12"
CONF_DISTRIBUTOR_P12: Final = "distributor_p12"

ATTR_APP_ID: Final = "app_id"
ATTR_PATH: Final = "path"

# Current app sensor states when no known app is in front.
SCREEN_HOME: Final = "home"
SCREEN_OTHER: Final = "other"

# Power state only: a TV is polled cheaply over REST, volume over UPnP when on.
SCAN_INTERVAL: Final = timedelta(seconds=10)
# Installed apps rarely change; rescanning ~18 known IDs takes about 0.5 s.
APP_SCAN_INTERVAL: Final = timedelta(minutes=30)
# Samsung certificates last a year; warn (and renew on sign-in) this early.
RENEW_BEFORE: Final = timedelta(days=30)
CERT_CHECK_INTERVAL: Final = timedelta(hours=12)

# First media player source: presses the remote's Home key.
SOURCE_HOME: Final = "Home"
# Where play_stream can keep the TV's own picture (Live TV / HDMI).
CORNERS: Final = ("top_left", "top_right", "bottom_left", "bottom_right")
# play_stream tv_corner: off, on (the corner from the options) or a corner.
TV_CORNERS: Final = ("off", "on", *CORNERS)
# Options: which corner "on" uses.
CONF_TV_CORNER: Final = "tv_corner"
DEFAULT_TV_CORNER: Final = "top_right"
# Sources before the apps, and the remote key each one presses. The TV keeps
# its own names for inputs; these keys work whatever the input is called.
SOURCE_INPUTS: Final = "Input list"
SOURCE_KEYS: Final = {
    SOURCE_HOME: "KEY_HOME",
    # The TV's own input picker: works on every model, whatever inputs it has.
    SOURCE_INPUTS: "KEY_SOURCE",
    "Live TV": "KEY_TV",
    "HDMI 1": "KEY_HDMI1",
    "HDMI 2": "KEY_HDMI2",
    "HDMI 3": "KEY_HDMI3",
    "HDMI 4": "KEY_HDMI4",
}
