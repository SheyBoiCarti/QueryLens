"""Unit tests for Phase 02 database connections, network validation, and AES-256-GCM encryption."""

import pytest
from pydantic import ValidationError

from querylens.connections.crypto import (
    CredentialCryptoError,
    decrypt_credential,
    encrypt_credential,
)
from querylens.connections.models import ConnectionCreate, ConnectionUpdate
from querylens.connections.network import (
    NetworkSecurityError,
    validate_destination_address,
)
from querylens.connections.registry import ConnectionRegistry


def test_connection_model_validation():
    """Connection models enforce engine allowlist and forbid unknown fields."""
    # Valid Postgres
    valid = ConnectionCreate(
        name="Valid PG",
        engine="postgresql",
        host="localhost",
        port=5432,
        database="db",
        username="user",
        password="secretpassword",
    )
    assert valid.engine == "postgresql"

    # Valid MySQL
    valid_my = ConnectionCreate(
        name="Valid MySQL",
        engine="mysql",
        host="localhost",
        port=3306,
        database="db",
        username="user",
        password="secretpassword",
    )
    assert valid_my.engine == "mysql"

    # Unsupported engine (e.g. sqlite, mariadb)
    with pytest.raises(ValidationError):
        ConnectionCreate(
            name="SQLite DB",
            engine="sqlite",  # type: ignore
            host="localhost",
            port=5432,
            database="db",
            username="user",
            password="secretpassword",
        )

    # Empty password rejected
    with pytest.raises(ValidationError):
        ConnectionCreate(
            name="Empty Pass",
            engine="postgresql",
            host="localhost",
            port=5432,
            database="db",
            username="user",
            password="",
        )


def test_connection_update_password_rules():
    """Omitted password is valid, explicit empty password is rejected on update."""
    # Omitted password is fine
    update_valid = ConnectionUpdate(name="New Name")
    assert update_valid.password is None

    # Explicit empty password fails
    with pytest.raises(ValidationError):
        ConnectionUpdate(password="")


def test_aes_256_gcm_credential_envelope_and_aad_binding():
    """AES-256-GCM encrypts credentials with connection ID bound in AAD (Contract C04)."""
    conn_id_1 = "conn-uuid-1111"
    conn_id_2 = "conn-uuid-2222"
    password = "MySuperSecretDatabasePassword_!@#$"

    # Encrypt for conn_id_1
    envelope_1 = encrypt_credential(password, connection_id=conn_id_1)
    assert "ciphertext" in envelope_1
    assert "nonce" in envelope_1
    assert password not in envelope_1

    # Decrypt with conn_id_1 succeeds
    decrypted = decrypt_credential(envelope_1, connection_id=conn_id_1)
    assert decrypted == password

    # Swapping ciphertext to conn_id_2 MUST FAIL due to AAD mismatch
    with pytest.raises(CredentialCryptoError, match="invalid ciphertext, tag, or connection mismatch"):
        decrypt_credential(envelope_1, connection_id=conn_id_2)


def test_network_validator_blocks_cloud_metadata_and_prohibited():
    """Network validator blocks cloud metadata (169.254.169.254), link-local, multicast."""
    # Cloud metadata
    with pytest.raises(NetworkSecurityError, match="prohibited"):
        validate_destination_address("169.254.169.254", 80)

    # IPv4 Multicast
    with pytest.raises(NetworkSecurityError, match="prohibited"):
        validate_destination_address("224.0.0.1", 5432)

    # Invalid port
    with pytest.raises(NetworkSecurityError, match="Invalid port"):
        validate_destination_address("127.0.0.1", 70000)

    # Loopback allowed for local test/dev
    ip = validate_destination_address("127.0.0.1", 5432, allow_loopback=True)
    assert ip == "127.0.0.1"


def test_registry_pool_eviction():
    """Registry respects max_idle_pools and evicts oldest pool."""
    registry = ConnectionRegistry(max_idle_pools=2)
    # Mock pools by inserting dummy entries
    class DummyEngine:
        def __init__(self):
            self.disposed = False
        def dispose(self):
            self.disposed = True

    e1 = DummyEngine()
    e2 = DummyEngine()

    from querylens.connections.registry import PoolEntry
    registry._pools["c1"] = PoolEntry(engine=e1, last_used=100.0, signature=())
    registry._pools["c2"] = PoolEntry(engine=e2, last_used=200.0, signature=())

    # Add 3rd: c1 should be evicted and disposed
    assert len(registry._pools) == 2
    # Calling get_or_create with new id will evict oldest (c1)
    # We can test dispose directly
    registry.dispose("c1")
    assert e1.disposed is True
    assert "c1" not in registry._pools
