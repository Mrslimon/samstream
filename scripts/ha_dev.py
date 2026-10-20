"""Deploy the integration to a dev Home Assistant running in Docker on another machine.

Usage: uv run python scripts/ha_dev.py {sync,install-lib,restart,logs,deploy,test}

Settings come from .env.ha (gitignored):
  HA_URL, HA_TOKEN          REST API + long-lived token (restart, wait for startup)
  SSH_TARGET, SSH_KEY       ssh login on the Docker host
  HA_CONTAINER              container name (default: homeassistant)

Files are streamed with tar over ssh straight into the container, so Windows paths
and shell quoting on the Docker host never get involved.
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "samstream"
LIBRARY = ROOT / "lib" / "aiosamstream"
REMOTE_LIB = "/config/samstream-dev/aiosamstream"
LOG_MARKERS = ("samstream", "aiosamstream", "samsungtvws", "Traceback")
STARTUP_TIMEOUT = 300


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env.ha").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


ENV = load_env()
CONTAINER = ENV.get("HA_CONTAINER", "homeassistant")


def ssh(
    remote_command: str, stdin: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    key = os.path.expanduser(ENV["SSH_KEY"])
    command = [
        "ssh",
        "-i",
        key,
        "-o",
        "BatchMode=yes",
        ENV["SSH_TARGET"],
        remote_command,
    ]
    return subprocess.run(command, input=stdin, capture_output=True, check=False)


def in_container(script: str) -> str:
    """Run a POSIX shell script inside the HA container (piped, so no host quoting)."""
    result = ssh(f"docker exec -i {CONTAINER} sh", stdin=script.encode())
    output = (result.stdout + result.stderr).decode(errors="replace")
    if result.returncode != 0:
        sys.exit(f"container command failed ({result.returncode}):\n{output}")
    return output


def _skip_caches(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    parts = Path(info.name).parts
    junk = {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
    return None if junk & set(parts) or info.name.endswith(".pyc") else info


def tar_of(source: Path, arcname: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.add(source, arcname=arcname, filter=_skip_caches)
    return buffer.getvalue()


def upload(source: Path, remote_parent: str, name: str) -> None:
    """Replace remote_parent/name with the local directory."""
    in_container(f"rm -rf '{remote_parent}/{name}' && mkdir -p '{remote_parent}'")
    result = ssh(
        f"docker exec -i {CONTAINER} tar -xzf - -C {remote_parent}",
        stdin=tar_of(source, name),
    )
    if result.returncode != 0:
        sys.exit(f"upload of {name} failed:\n{result.stderr.decode(errors='replace')}")
    print(f"synced {source.relative_to(ROOT)} -> {remote_parent}/{name}")


def sync() -> None:
    upload(INTEGRATION, "/config/custom_components", "samstream")
    upload(LIBRARY, "/config/samstream-dev", "aiosamstream")


def install_lib() -> None:
    # Editable: later library edits only need `sync` + `restart`.
    print(in_container(f"uv pip install --system -e {REMOTE_LIB} 2>&1 | tail -5"))


def api(path: str, method: str = "GET") -> int:
    request = urllib.request.Request(
        ENV["HA_URL"].rstrip("/") + path,
        method=method,
        headers={
            "Authorization": f"Bearer {ENV['HA_TOKEN']}",
            "Content-Type": "application/json",
        },
        data=b"{}" if method == "POST" else None,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return int(response.status)
    except urllib.error.HTTPError as err:
        return err.code
    except urllib.error.URLError, TimeoutError, ConnectionError:
        return 0


def restart() -> None:
    print("restarting Home Assistant...")
    api("/api/services/homeassistant/restart", method="POST")
    time.sleep(10)
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if api("/api/config") == 200:
            print("Home Assistant is back up")
            return
        time.sleep(3)
    sys.exit("Home Assistant did not come back in time")


def logs(lines: int) -> None:
    output = in_container(f"tail -n {lines} /config/home-assistant.log")
    relevant = [
        line for line in output.splitlines() if any(m in line for m in LOG_MARKERS)
    ]
    print("\n".join(relevant) or "(no samstream log lines)")


TEST_SCRIPT = """
set -e
mkdir -p /work && cd /work
base64 -d <<'ARCHIVE' | tar -xzf -
{archive}
ARCHIVE
PYTEST_ARGS="{pytest_args}"
HA_VERSION=$(python3 -c "import homeassistant.const as c; print(c.__version__)")
echo "testing against Home Assistant $HA_VERSION"
# Lets uv pick the pytest-homeassistant-custom-component release made for this HA.
uv pip install --system -q --index-strategy unsafe-best-match "homeassistant==$HA_VERSION" \
    pytest-homeassistant-custom-component pytest-cov mypy -e lib/aiosamstream
# The image installs HA from /usr/src/homeassistant in a way mypy cannot follow.
HA_SRC=$(dirname "$(python3 -c 'import homeassistant, os; print(os.path.dirname(homeassistant.__file__))')")
MYPYPATH="$HA_SRC:lib/aiosamstream/src" mypy custom_components/samstream lib/aiosamstream/src
pytest -q -p no:cacheprovider ${{PYTEST_ARGS:-tests lib/aiosamstream/tests}} \
    --cov=custom_components.samstream --cov=aiosamstream --cov-report=term-missing
"""


def test(pytest_args: list[str]) -> None:
    """Run mypy + pytest in a throwaway container built from the live HA image."""
    image = ssh(f"docker inspect {CONTAINER} --format {{{{.Config.Image}}}}")
    image_name = image.stdout.decode().strip()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for part in ("pyproject.toml", "custom_components", "lib", "tests"):
            archive.add(ROOT / part, arcname=part, filter=_skip_caches)
    # Archive embedded as base64 in the script, all on stdin: no host-shell quoting.
    script = TEST_SCRIPT.format(
        archive=base64.encodebytes(buffer.getvalue()).decode(),
        pytest_args=" ".join(pytest_args),
    )
    print(f"running tests in a throwaway {image_name} container...")
    result = ssh(
        f"docker run --rm -i --entrypoint sh {image_name}", stdin=script.encode()
    )
    print((result.stdout + result.stderr).decode(errors="replace"))
    if result.returncode != 0:
        sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["sync", "install-lib", "restart", "logs", "deploy", "test"]
    )
    parser.add_argument("--since", type=int, default=2000, help="log lines to scan")
    parser.add_argument("pytest_args", nargs="*", help="test: extra pytest args")
    args = parser.parse_args()
    if args.command in {"sync", "deploy"}:
        sync()
    if args.command == "install-lib":
        install_lib()
    if args.command in {"restart", "deploy"}:
        restart()
    if args.command in {"logs", "deploy"}:
        logs(args.since)
    if args.command == "test":
        test(args.pytest_args)


if __name__ == "__main__":
    main()
