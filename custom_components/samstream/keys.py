"""Remote key names as automations may write them."""

from __future__ import annotations


def normalize_key(command: str) -> str:
    """`home` / `key_home` / `KEY_HOME` all become `KEY_HOME`."""
    key = command.strip().upper()
    return key if key.startswith("KEY_") else f"KEY_{key}"
