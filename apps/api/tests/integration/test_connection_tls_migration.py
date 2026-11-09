"""Existing connections retain verification when TLS mode support is installed."""
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from querylens import config


def test_tls_migration_preserves_existing_connections(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    settings = config.Settings(_env_file=None, environment='test', metadata_database_url=database_url)
    monkeypatch.setattr(config, '_global_settings', settings)
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / 'alembic.ini'))
    cfg.set_main_option('script_location', str(root / 'migrations'))
    command.upgrade(cfg, '0003_everyday_analytics')
    engine = sa.create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO users(id,email,password_hash) VALUES ('u','migration@test','hash')"))
        conn.execute(sa.text("""INSERT INTO connections(id,user_id,name,engine,host,port,database,username,encrypted_password)
            VALUES ('c','u','DB','postgresql','db.example.com',5432,'db','reader','encrypted')"""))
    command.upgrade(cfg, 'head')
    with engine.connect() as conn:
        assert conn.execute(sa.text('SELECT tls_mode FROM connections')).scalar_one() == 'verify-full'
        assert conn.execute(sa.text('SELECT encrypted_password FROM connections')).scalar_one() == 'encrypted'
    command.downgrade(cfg, '0003_everyday_analytics')
    assert 'tls_mode' not in {c['name'] for c in sa.inspect(engine).get_columns('connections')}
    command.upgrade(cfg, 'head')
    with engine.connect() as conn:
        assert conn.execute(sa.text('SELECT tls_mode FROM connections')).scalar_one() == 'verify-full'
    engine.dispose()
