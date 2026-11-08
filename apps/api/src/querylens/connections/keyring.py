"""Keyring management for AES-256-GCM credential encryption (Contract C04)."""

from __future__ import annotations

import json
import os

# Development fallback key (exactly 32 bytes)
DEV_DEFAULT_KEY = b"querylens_dev_32_bytes_key_00001"
DEV_DEFAULT_KEY_ID = "dev-key-1"

_keyring: dict[str, bytes] = {DEV_DEFAULT_KEY_ID: DEV_DEFAULT_KEY}
_active_key_id: str = DEV_DEFAULT_KEY_ID


def load_keyring(keys_file: str | None = None, active_key_id: str | None = None) -> None:
    """Load keys from JSON file or fall back to development key."""
    global _keyring, _active_key_id

    if keys_file and not os.path.isfile(keys_file):
        raise ValueError("Configured credential keyring file does not exist")
    if keys_file and os.path.exists(keys_file):
        with open(keys_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        keys_dict = data.get("keys", {})
        loaded: dict[str, bytes] = {}
        for k_id, k_val in keys_dict.items():
            # Support hex or raw ascii (must be 32 bytes)
            try:
                b = bytes.fromhex(k_val)
            except ValueError:
                b = k_val.encode("utf-8")
            if len(b) != 32:
                raise ValueError(f"Key {k_id} must be exactly 32 bytes, got {len(b)}")
            loaded[k_id] = b

        if not loaded:
            raise ValueError(f"Keyring file {keys_file} contains no valid keys")
        _keyring = loaded

        if active_key_id:
            if active_key_id not in _keyring:
                raise ValueError(f"Active key ID '{active_key_id}' not found in keyring {keys_file}")
            _active_key_id = active_key_id
        else:
            _active_key_id = list(_keyring.keys())[0]
    else:
        _keyring = {DEV_DEFAULT_KEY_ID: DEV_DEFAULT_KEY}
        _active_key_id = DEV_DEFAULT_KEY_ID


def get_active_key() -> tuple[str, bytes]:
    """Return (active_key_id, 32_byte_key)."""
    return _active_key_id, _keyring[_active_key_id]


def get_key_by_id(key_id: str) -> bytes | None:
    """Return key by key ID."""
    return _keyring.get(key_id)
