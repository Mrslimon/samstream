"""Onboard (or release) a Samsung TV for Home Assistant local control, from the LAN.

When Home Assistant cannot reach the TV over UDP, onboarding is done from a
computer on the TV's own network. Home Assistant hands out the details as a
one-line bundle (address, token, cloud UUID and CA), or bakes them into the
downloadable `samstream-onboard.pyz`; this tool takes ownership of the TV with
the on-screen PIN and points its cloud at Home Assistant. It then prints a
credential to paste back into Home Assistant so it can hand the TV back later.

Only the standard library, `cryptography` and the onboarding modules are
imported, so the tool also runs from a zip without the rest of the package.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from aiosamstream.exceptions import OcfError

from .onboard import (
    decode_bundle,
    decode_credential,
    discover,
    encode_credential,
    onboard_tv,
    release_tv,
    trigger_pin,
)


def _read_arg(value: str) -> str:
    """Return the value, or the file contents if it is given as @path."""
    if value.startswith("@"):
        return Path(value[1:]).read_text(encoding="utf-8").strip()
    return value.strip()


def _onboard(args: argparse.Namespace) -> int:
    bundle = decode_bundle(_read_arg(args.bundle))
    ca_der = x509.load_pem_x509_certificate(bundle.ca_pem.encode()).public_bytes(
        serialization.Encoding.DER
    )

    print(f"[*] looking for the TV at {args.tv} ...")
    port, device_uuid = discover(args.tv)
    print(f"[+] found it (secure port {port}, device {device_uuid})")

    print("[*] asking the TV to show its PIN ...")
    trigger_pin(args.tv)
    pin = args.pin or input("    Enter the 8-digit PIN shown on the TV: ").strip()

    print("[*] taking ownership and pointing the TV at Home Assistant ...")
    result = onboard_tv(
        args.tv,
        pin,
        obt_uuid=bundle.obt_uuid,
        ca_der=ca_der,
        cloud_uuid=bundle.cloud_uuid,
        cis=bundle.cis,
        access_token=bundle.token,
        device_uuid=device_uuid,
        secure_port=port,
    )
    credential = encode_credential(result)
    print("\n[=] DONE. The TV is now connecting to Home Assistant.")
    print("    Paste this credential into Home Assistant (so it can hand the TV")
    print("    back to SmartThings later), then select Submit there:\n")
    print(f"    {credential}\n")
    if args.credential_out:
        Path(args.credential_out).write_text(credential, encoding="utf-8")
        print(f"    (also saved to {args.credential_out})")
    return 0


def _release(args: argparse.Namespace) -> int:
    result = decode_credential(_read_arg(args.credential))
    print(f"[*] releasing {args.tv} back to SmartThings ...")
    release_tv(args.tv, result.obt_uuid, result.owner_psk_hex)
    print("[=] released — the TV is addable in the SmartThings app again.")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    tv: str | None = None,
    bundle: str | None = None,
) -> int:
    """Run the tool; `tv` and `bundle` are defaults baked in by Home Assistant."""
    parser = argparse.ArgumentParser(prog="samstream-onboard")
    sub = parser.add_subparsers(dest="command")

    on = sub.add_parser("onboard", help="own the TV and point it at Home Assistant")
    on.add_argument("--tv", required=tv is None, default=tv, help="the TV's IP")
    on.add_argument(
        "--bundle",
        required=bundle is None,
        default=bundle,
        help="the bundle shown by Home Assistant (or @file)",
    )
    on.add_argument("--pin", help="the PIN (otherwise you are prompted)")
    on.add_argument("--credential-out", help="also save the credential to this file")

    rel = sub.add_parser("release", help="hand the TV back to SmartThings")
    rel.add_argument("--tv", required=tv is None, default=tv, help="the TV's IP")
    rel.add_argument(
        "--credential", required=True, help="the credential from onboard (or @file)"
    )

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments and tv is not None and bundle is not None:
        arguments = ["onboard"]  # the downloaded tool: just run it
    args = parser.parse_args(arguments)
    if args.command is None:
        parser.error("choose onboard or release")
    try:
        return _onboard(args) if args.command == "onboard" else _release(args)
    except OcfError as err:
        print(f"[!] {err}", file=sys.stderr)
        return 1
