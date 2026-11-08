"""Regression specifications for the code review. Not run during remediation."""

import pytest

from querylens.domain.schema import CatalogSnapshot, ColumnMetadata, TableMetadata
from querylens.sql.identifiers import IdentifierPolicyError
from querylens.sql.policy import validate_and_bound_sql


@pytest.fixture
def restricted_catalog():
    snapshot = CatalogSnapshot(
        connection_id="review",
        engine="postgresql",
        tables=[
            TableMetadata(
                name="users",
                namespace="public",
                columns=[
                    ColumnMetadata(name="id", canonical_type="integer", db_type="INTEGER"),
                    ColumnMetadata(name="name", canonical_type="string", db_type="TEXT"),
                ],
            ),
        ],
    )
    snapshot.snapshot_hash = snapshot.compute_hash()
    return snapshot


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM private.users",
        "WITH harmless AS (SELECT 1 AS n) SELECT password_hash FROM users",
        "SELECT u.password_hash FROM users u",
        "SELECT id FROM users u WHERE EXISTS (SELECT 1 FROM private.users u)",
        "SELECT id FROM users WHERE EXISTS (WITH hidden AS (SELECT 1) SELECT id FROM hidden_table)",
        "SELECT users FROM users",
    ],
)
def test_unauthorized_physical_identifiers_are_rejected(restricted_catalog, sql):
    with pytest.raises(IdentifierPolicyError):
        validate_and_bound_sql(sql, "review", "postgresql", restricted_catalog)


def test_qualified_star_only_exposes_visible_columns(restricted_catalog):
    token = validate_and_bound_sql("SELECT u.* FROM users u", "review", "postgresql", restricted_catalog)
    assert "password_hash" not in token.canonical_sql
    assert "*" not in token.canonical_sql
    assert '"u"."id"' in token.canonical_sql
    assert '"u"."name"' in token.canonical_sql


def test_scoped_cte_and_correlated_aliases_remain_supported(restricted_catalog):
    token = validate_and_bound_sql(
        "WITH named AS (SELECT id, name FROM users) SELECT n.name FROM named n "
        "WHERE EXISTS (SELECT 1 FROM users u WHERE u.id = n.id)",
        "review",
        "postgresql",
        restricted_catalog,
    )
    assert token.canonical_sql


def test_qualified_user_function_is_not_a_builtin(restricted_catalog):
    from querylens.sql.functions import FunctionPolicyError

    with pytest.raises(FunctionPolicyError):
        validate_and_bound_sql("SELECT private.lower(name) FROM users", "review", "postgresql", restricted_catalog)
