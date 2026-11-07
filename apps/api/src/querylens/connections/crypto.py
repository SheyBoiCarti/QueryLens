"""AES-256-GCM credential envelope encryption service (Contract C04)."""

from __future__ import annotations

import base64
import json
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from querylens.connections.keyring import get_active_key, get_key_by_id

ENVELOPE_VERSION = 1


class CredentialCryptoError(Exception):
    """Raised when encryption or decryption fails."""
    pass


def encrypt_credential(plaintext: str, connection_id: str) -> str:
    """Encrypt password using AES-256-GCM with connection ID bound into AAD."""
    key_id, key_bytes = get_active_key()
    aesgcm = AESGCM(key_bytes)
    nonce = os.urandom(12)  # 12-byte fresh nonce per encryption (C04)
    aad = f"{connection_id}:{ENVELOPE_VERSION}".encode("utf-8")

    ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), aad)

    envelope = {
        "version": ENVELOPE_VERSION,
        "key_id": key_id,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext_with_tag).decode("ascii"),
    }
    return json.dumps(envelope)


def decrypt_credential(encrypted_envelope_json: str, connection_id: str) -> str:
    """Decrypt credential envelope, verifying AAD matches connection_id."""
    try:
        envelope = json.loads(encrypted_envelope_json)
        version = envelope["version"]
        key_id = envelope["key_id"]
        nonce = base64.b64decode(envelope["nonce"])
        ciphertext_with_tag = base64.b64decode(envelope["ciphertext"])
    except Exception as e:
        raise CredentialCryptoError("Malformed credential envelope") from e

    key_bytes = get_key_by_id(key_id)
    if not key_bytes:
        raise CredentialCryptoError(f"Key ID '{key_id}' not found in keyring")

    aesgcm = AESGCM(key_bytes)
    aad = f"{connection_id}:{version}".encode("utf-8")

    try:
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext_with_tag, aad)
        return decrypted_bytes.decode("utf-8")
    except Exception as e:
        # Crucial C04 security contract: swapping ciphertext between connections fails decryption
        raise CredentialCryptoError("Credential decryption failed: invalid ciphertext, tag, or connection mismatch") from e
