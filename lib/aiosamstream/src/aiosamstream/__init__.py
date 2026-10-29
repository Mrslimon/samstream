"""Async client for Samsung Tizen TVs and the Samstream player app."""

from .apps import KNOWN_APPS, YOUTUBE_APP_ID, ListedApp, parse_app_list
from .art import ArtConnection
from .cast import youtube_id
from .const import SAMSTREAM_APP_ID
from .exceptions import (
    OcfError,
    OcfNotConnectedError,
    OcfTvOwnedError,
    SamstreamAuthError,
    SamstreamConnectionError,
    SamstreamError,
    SamstreamTimeoutError,
    SdbConnectionError,
    SdbError,
)
from .models import AppStatus, DeviceInfo
from .sdb import InstallResult, SdbClient, generate_key
from .tv import SamsungTV
from .wol import send_magic_packet

__all__ = [
    "KNOWN_APPS",
    "SAMSTREAM_APP_ID",
    "YOUTUBE_APP_ID",
    "AppStatus",
    "ArtConnection",
    "DeviceInfo",
    "InstallResult",
    "ListedApp",
    "OcfError",
    "OcfNotConnectedError",
    "OcfTvOwnedError",
    "SamstreamAuthError",
    "SamstreamConnectionError",
    "SamstreamError",
    "SamstreamTimeoutError",
    "SamsungTV",
    "SdbClient",
    "SdbConnectionError",
    "SdbError",
    "generate_key",
    "parse_app_list",
    "send_magic_packet",
    "youtube_id",
]
