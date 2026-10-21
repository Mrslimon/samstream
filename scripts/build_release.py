"""Build the release artefacts and check every version agrees.

    uv run python scripts/build_release.py [--tag v0.1.0]

Writes to dist/:
  samstream.zip                   custom_components/samstream for HACS / manual install
  aiosamstream-<v>-py3-none-any.whl and .tar.gz   the library, for PyPI

Fails (exit 1) when versions disagree: the tag, manifest.json `version`, the
`aiosamstream==` requirement, the library's pyproject, or when the bundled TV
app / card are older than their sources. Nothing is published from here.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "samstream"
LIB = ROOT / "lib" / "aiosamstream"
DIST = ROOT / "dist"
# Development leftovers that must not ship.
SKIP_PARTS = {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}


def fail(message: str) -> None:
    print(f"release check failed: {message}", file=sys.stderr)
    sys.exit(1)


def versions() -> dict[str, str]:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    requirement = next(
        (r for r in manifest.get("requirements", []) if r.startswith("aiosamstream==")),
        "",
    )
    lib = tomllib.loads((LIB / "pyproject.toml").read_text(encoding="utf-8"))
    config = (ROOT / "tv-app" / "public" / "config.xml").read_text(encoding="utf-8")
    with zipfile.ZipFile(INTEGRATION / "bundled" / "samstream.wgt") as wgt:
        bundled = wgt.read("config.xml").decode()

    def widget_version(xml: str) -> str:
        found = re.search(r'<widget\b[^>]*\bversion="([^"]+)"', xml)
        return found.group(1) if found else ""

    return {
        "integration": manifest["version"],
        "requirement": requirement.removeprefix("aiosamstream=="),
        "library": lib["project"]["version"],
        "tv_app_source": widget_version(config),
        "tv_app_bundled": widget_version(bundled),
    }


def check(tag: str | None) -> str:
    found = versions()
    for key, value in found.items():
        print(f"  {key:15} {value}")
    if found["requirement"] != found["library"]:
        fail("manifest requires a different aiosamstream than lib/aiosamstream")
    if found["integration"] != found["library"]:
        fail("integration and library versions differ (released together)")
    if found["tv_app_source"] != found["tv_app_bundled"]:
        fail("bundled TV app is stale: run scripts/bundle_tv_app.py")
    if tag is not None and tag.removeprefix("v") != found["integration"]:
        fail(f"tag {tag} does not match version {found['integration']}")
    card = INTEGRATION / "frontend" / "samstream-card.js"
    newest = max(p.stat().st_mtime for p in (ROOT / "card" / "src").glob("*.ts"))
    if not card.is_file() or card.stat().st_mtime < newest:
        fail("built card is stale: run npm run build in card/")
    return found["integration"]


def build_zip() -> Path:
    target = DIST / "samstream.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(INTEGRATION.rglob("*")):
            if path.is_file() and not SKIP_PARTS & set(path.parts):
                # HACS unpacks the zip into custom_components/samstream/.
                archive.write(path, path.relative_to(INTEGRATION).as_posix())
    return target


def build_library() -> list[Path]:
    # Relative paths: uv rejects some absolute Windows paths here.
    subprocess.run(
        ["uv", "build", "--out-dir", "dist", "lib/aiosamstream"], check=True, cwd=ROOT
    )
    return sorted(DIST.glob("aiosamstream-*"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tag", help="git tag being released, e.g. v0.1.0")
    args = parser.parse_args()
    print("versions:")
    version = check(args.tag)
    shutil.rmtree(DIST, ignore_errors=True)
    DIST.mkdir()
    built = [build_zip(), *build_library()]
    print(f"release {version}:")
    for path in built:
        print(f"  {path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
