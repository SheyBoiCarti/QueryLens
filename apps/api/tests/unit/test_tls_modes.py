"""Provider TLS modes must survive persistence and reach the actual drivers."""
import os
import ssl
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from querylens.connections.models import ConnectionCreate, ConnectionUpdate
from querylens.connections.mysql import MySQLAdapter
from querylens.connections.postgres import PostgresAdapter
from querylens.connections.registry import ConnectionRegistry
from querylens.connections.tls import mysql_tls_context, postgres_ca_file
from querylens.connections.service import ConnectionService
from querylens.persistence.tables import metadata, users


@pytest.mark.parametrize('mode,verify,hostname', [
    ('require', ssl.CERT_NONE, False),
    ('verify-ca', ssl.CERT_REQUIRED, False),
    ('verify-full', ssl.CERT_REQUIRED, True),
])
def test_mysql_context(mode, verify, hostname):
    ctx = mysql_tls_context(tls_mode=mode)
    assert ctx.verify_mode == verify
    assert ctx.check_hostname is hostname


@pytest.mark.parametrize('mode', ['require', 'verify-ca', 'verify-full'])
def test_postgres_driver_options(mode, monkeypatch):
    connect = MagicMock()
    monkeypatch.setattr('querylens.connections.postgres.validate_destination_address', lambda *a: '203.0.113.1')
    monkeypatch.setattr('querylens.connections.postgres.psycopg.connect', connect)
    PostgresAdapter.connect('db.example.com', 5432, 'db', 'reader', 'pass', tls_mode=mode)
    assert connect.call_args.kwargs['sslmode'] == mode
    assert connect.call_args.kwargs['host'] == 'db.example.com'
    assert connect.call_args.kwargs['hostaddr'] == '203.0.113.1'
    if mode == 'require':
        assert not os.path.exists(connect.call_args.kwargs['sslrootcert'])


def test_require_does_not_load_ca_or_fall_back_to_default_root():
    with postgres_ca_file('invalid-ca', 'require') as path:
        assert path.endswith('no-root.pem') and not os.path.exists(path)
    assert mysql_tls_context('invalid-ca', 'require').verify_mode == ssl.CERT_NONE


def test_registry_invalidates_pool_on_mode_change(monkeypatch):
    create = MagicMock(side_effect=[MagicMock(), MagicMock()])
    monkeypatch.setattr('querylens.connections.registry.create_engine_pool', create)
    registry = ConnectionRegistry()
    args = ('id', 'postgresql', 'db.example.com', 5432, 'db', 'reader', 'pass')
    old = registry.get_or_create(*args)
    registry.get_or_create(*args, tls_mode='require')
    old.dispose.assert_called_once()
    assert create.call_args.kwargs['tls_mode'] == 'require'


def test_modes_persist_and_test_uses_saved_mode(monkeypatch):
    engine = sa.create_engine('sqlite://')
    metadata.create_all(engine)
    dispatch = MagicMock(return_value=(True, 'PostgreSQL 17', 'Connected'))
    monkeypatch.setattr('querylens.connections.service.dispatch_test_connection', dispatch)
    with engine.begin() as conn:
        conn.execute(users.insert().values(id='owner', email='tls@test', password_hash='unused'))
        service = ConnectionService(conn)
        saved = service.create('owner', ConnectionCreate(name='DB', engine='postgresql', host='db.example.com',
            port=5432, database='db', username='reader', password='pass', tls_mode='require'))
        assert service.get('owner', saved.id).tls_mode == 'require'
        assert service.list_all('owner')[0].tls_mode == 'require'
        service.test('owner', saved.id)
        assert dispatch.call_args.kwargs['tls_mode'] == 'require'
        service.update('owner', saved.id, ConnectionUpdate(tls_mode='verify-full'))
        assert service.get('owner', saved.id).tls_mode == 'verify-full'
        service.test('owner', saved.id)
        assert dispatch.call_args.kwargs['tls_mode'] == 'verify-full'
    engine.dispose()


def test_unknown_mode_rejected():
    with pytest.raises(ValidationError):
        ConnectionUpdate(tls_mode='prefer')


@pytest.mark.parametrize('adapter', [MySQLAdapter, PostgresAdapter])
@pytest.mark.parametrize('mode', ['require', 'verify-full'])
def test_pool_uses_same_mode_as_connection_test(adapter, mode, monkeypatch):
    connect = MagicMock()
    monkeypatch.setattr(adapter, 'connect', connect)
    pool = adapter.create_pool('db.example.com', 5432, 'db', 'reader', 'pass', tls_mode=mode)
    pool.pool._creator()
    assert connect.call_args.kwargs['tls_mode'] == mode
    pool.dispose()
