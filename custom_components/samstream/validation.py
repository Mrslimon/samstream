"""The schema library: Home Assistant 2026.10 moved from voluptuous to probatio.

probatio is a voluptuous fork with the same API, so the integration imports it
as `vol` from here and runs on both (hacs.json still allows 2026.5).
"""

try:
    import probatio as vol  # type: ignore[import-not-found,unused-ignore]
except ImportError:  # Home Assistant before 2026.10
    import voluptuous as vol  # type: ignore[no-redef,unused-ignore]

__all__ = ["vol"]
