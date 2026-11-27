"""Build the notifier and bundle it, unsigned, into the integration.

    python scripts/bundle_notifier.py

Needs the .NET SDK with the Tizen workload SDK (see global.json). HA stamps the
TV's secret into this package and signs it per installation (installer.py), so
it carries no key, no signature and no debug file.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT / "tv-app" / "notifier-dotnet"
BUILT = PROJECT / "bin" / "Release" / "tizen40" / "org.samstream.notifier-1.0.0.tpk"
TARGET = ROOT / "custom_components" / "samstream" / "bundled" / "notifier.tpk"
# Signatures from a local profile, symbols and keys never ship.
LEFT_OUT = re.compile(
    r"(^|/)(author-signature\.xml|signature\d+\.xml|shared\.key|[^/]+\.pdb)$"
)


def main() -> None:
    dotnet = shutil.which("dotnet") or "dotnet"
    # A clean build: no stale frame images or symbols in the package.
    for folder in ("bin", "obj"):
        shutil.rmtree(PROJECT / folder, ignore_errors=True)
    subprocess.run([dotnet, "build", "-c", "Release"], cwd=PROJECT, check=True)
    if not BUILT.is_file():
        sys.exit(f"no package at {BUILT.relative_to(ROOT)}")
    buffer = io.BytesIO()
    with (
        zipfile.ZipFile(BUILT) as source,
        zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for item in source.infolist():
            if not LEFT_OUT.search(item.filename):
                target.writestr(item, source.read(item))
    TARGET.write_bytes(buffer.getvalue())
    print(f"bundled {TARGET.relative_to(ROOT)} ({len(buffer.getvalue()) // 1024} KB)")


if __name__ == "__main__":
    main()
