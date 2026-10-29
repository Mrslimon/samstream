"""Onboard (or release) a Samsung TV for Home Assistant local control, from the LAN.

The same tool Home Assistant offers as a download (`samstream-onboard.pyz`), run
from a checkout of this repo instead. See `aiosamstream.ocf.onboard_cli`.

Usage (from a computer on the TV's network):
    uv run python scripts/onboard_tv.py onboard --tv 192.168.1.11 --bundle <BUNDLE>
    uv run python scripts/onboard_tv.py release --tv 192.168.1.11 --credential <CRED>
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib/aiosamstream/src"))

from aiosamstream.ocf.onboard_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
