"""Developer CLI: `python -m aiosamstream {info,pair,wol} --host <tv>`."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
from pathlib import Path

import aiohttp

from . import SamstreamError, SamsungTV, send_magic_packet
from .wol import DEFAULT_TARGET


async def _run(args: argparse.Namespace, token: str | None) -> int:
    token_file = Path(args.token_file)
    async with aiohttp.ClientSession() as session:
        tv = SamsungTV(args.host, session, token=token)
        if args.command == "info":
            info = await tv.device_info()
            print(json.dumps(dataclasses.asdict(info), indent=2, ensure_ascii=False))
        elif args.command == "pair":
            if token:
                print("Stored token found: the TV should accept without a popup.")
            else:
                print('Accept the "Allow" popup on the TV...')
            new_token = await tv.pair(accept_within=args.wait)
            if new_token is None:
                print("This TV does not use token authentication.")
            elif new_token == token:
                print("Connected with the stored token (no popup).")
            else:
                await asyncio.to_thread(token_file.write_text, new_token, "utf-8")
                print(f"Paired, token saved to {token_file}.")
        elif args.command == "wol":
            mac = args.mac or (await tv.device_info()).mac
            if not mac:
                print("No MAC known, pass --mac.")
                return 1
            await send_magic_packet(mac, target=args.target)
            print(f"Magic packet sent to {mac} via {args.target}.")
    return 0


def main() -> int:
    """Parse arguments and run one command."""
    parser = argparse.ArgumentParser(prog="python -m aiosamstream")
    parser.add_argument("command", choices=["info", "pair", "wol"])
    parser.add_argument("--host", required=True)
    parser.add_argument("--token-file", default=".samstream-token")
    parser.add_argument("--wait", type=float, default=60, help="seconds to accept")
    parser.add_argument("--mac", help="for wol; read from the TV when omitted")
    parser.add_argument(
        "--target", default=DEFAULT_TARGET, help="wol broadcast/unicast address"
    )
    args = parser.parse_args()
    token_file = Path(args.token_file)
    token = None
    if token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
    try:
        return asyncio.run(_run(args, token))
    except SamstreamError as err:
        print(f"Error: {err}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
