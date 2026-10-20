"""Async client for Samsung Tizen TVs and the Samstream player app."""

from .apps import KNOWN_APPS
from .const import SAMSTREAM_APP_ID
from .exceptions import (
    SamstreamAuthError,
    SamstreamConnectionError,
    SamstreamError,
    SamstreamTimeoutError,
    SdbError,
)
from .models import AppStatus, DeviceInfo
from .tv import SamsungTV
from .wol import send_magic_packet

__all__ = [
    "KNOWN_APPS",
    "SAMSTREAM_APP_ID",
    "AppStatus",
    "DeviceInfo",
    "SamstreamAuthError",
    "SamstreamConnectionError",
    "SamstreamError",
    "SamstreamTimeoutError",
    "SamsungTV",
    "SdbError",
    "send_magic_packet",
]
