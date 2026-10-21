"""Build the TV app and bundle it, unsigned, into the integration.

    uv run python scripts/bundle_tv_app.py

HA signs this package per installation (see installer.py), so it carries no
signature and no local settings: VITE_SPIKE_STREAMS is forced empty (process env
wins over .env.local in Vite), and the result is checked for stream URLs.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TV_APP = ROOT / "tv-app"
DIST = TV_APP / "dist"
TARGET = ROOT / "custom_components" / "samstream" / "bundled" / "samstream.wgt"
# Anything that looks like a camera URL or credentials must not ship.
FORBIDDEN = re.compile(rb"rtsp://|://[^/\s\"']+:[^/\s\"']+@")


def main() -> None:
    npm = shutil.which("npm") or "npm"
    env = {**os.environ, "VITE_SPIKE_STREAMS": ""}
    subprocess.run([npm, "run", "build"], cwd=TV_APP, env=env, check=True)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(DIST.rglob("*")):
            relative = path.relative_to(DIST).as_posix()
            if path.is_dir() or relative.endswith(".wgt") or relative.startswith("."):
                continue
            if relative in {"author-signature.xml", "signature1.xml"}:
                continue
            data = path.read_bytes()
            if FORBIDDEN.search(data):
                sys.exit(f"refusing to bundle: {relative} contains a stream URL")
            archive.writestr(relative, data)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(buffer.getvalue())
    print(f"bundled {TARGET.relative_to(ROOT)} ({len(buffer.getvalue()) // 1024} KB)")


if __name__ == "__main__":
    main()
