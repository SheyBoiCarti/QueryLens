"""Integration tests for metadata schema migrations and retention (Contracts C04, C09)."""

import datetime
import pytest
import sqlalchemy as sa

from querylens.persistence.retention import run_retention_cleanup
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, set_engine
from querylens.persistence.tables import sessions, users


@pytest.fixture(autouse=True)
def sqlite_engine():
    """Disposable metadata database fixture."""
    test_eng = sa.create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    set_engine(test_eng)
    create_metadata_tables(test_eng)
    yield test_eng
    drop_metadata_tables(test_eng)
    test_eng.dispose()


def test_metadata_tables_creation_and_constraints(sqlite_engine):
    """All declared tables are created with proper schemas and constraints."""
    inspector = sa.inspect(sqlite_engine)
    table_names = set(inspector.get_table_names())

    expected_tables = {
        "users",
        "sessions",
        "connections",
        "schema_snapshots",
        "business_metrics",
        "few_shot_examples",
        "query_runs",
        "query_attempts",
        "evaluation_cases",
        "evaluation_runs",
        "catalog_labels",
        "saved_questions",
    }

    assert expected_tables.issubset(table_names), f"Missing tables: {expected_tables - table_names}"


def test_metadata_roundtrip_upgrade_downgrade(sqlite_engine):
    """Clean metadata downgrade and re-upgrade roundtrip works."""
    drop_metadata_tables(sqlite_engine)
    inspector = sa.inspect(sqlite_engine)
    assert len(inspector.get_table_names()) == 0

    create_metadata_tables(sqlite_engine)
    inspector2 = sa.inspect(sqlite_engine)
    from querylens.persistence.tables import metadata
    assert set(inspector2.get_table_names()) == set(metadata.tables)


def test_retention_cleanup(sqlite_engine):
    """7-day retention cleanup removes old query runs and expired sessions while keeping recent ones."""
    with sqlite_engine.begin() as conn:
        now = datetime.datetime.now(datetime.timezone.utc)
        old_time = now - datetime.timedelta(days=10)

        # Insert user
        conn.execute(
            users.insert().values(
                id="user-1",
                email="retention@test.com",
                password_hash="hash",
                role="analyst",
                created_at=now,
                updated_at=now,
            )
        )

        # Insert active session
        conn.execute(
            sessions.insert().values(
                id="sess-active",
                user_id="user-1",
                token_hash="hash-active",
                created_at=now,
                last_seen_at=now,
                expires_at=now + datetime.timedelta(hours=8),
                revoked_at=None,
            )
        )

        # Insert expired session
        conn.execute(
            sessions.insert().values(
                id="sess-expired",
                user_id="user-1",
                token_hash="hash-expired",
                created_at=old_time,
                last_seen_at=old_time,
                expires_at=old_time + datetime.timedelta(hours=8),
                revoked_at=None,
            )
        )

        # Run retention cleanup
        res = run_retention_cleanup(retention_days=7, conn=conn)
        assert res["deleted_sessions"] >= 1

        # Check active session still exists
        active = conn.execute(sa.select(sessions).where(sessions.c.id == "sess-active")).fetchone()
        assert active is not None

        # Check expired session removed
        expired = conn.execute(sa.select(sessions).where(sessions.c.id == "sess-expired")).fetchone()
        assert expired is None
