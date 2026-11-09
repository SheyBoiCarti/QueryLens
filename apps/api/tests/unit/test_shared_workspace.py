"""Regression coverage for the application without authentication."""

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI, Depends

from querylens.auth.dependencies import get_current_user, verify_csrf_token, DEFAULT_DEV_USER
from querylens.auth.workspace import initialize_workspace
from querylens.config import Settings, get_settings
from querylens.main import create_app
from querylens.persistence.session import set_engine
from querylens.persistence.tables import metadata, users, connections


@pytest.mark.asyncio
async def test_requests_need_no_session_or_csrf_token():
    app = FastAPI()
    from querylens.api.errors import register_error_handlers
    register_error_handlers(app)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)

    @app.post('/workspace', dependencies=[Depends(verify_csrf_token)])
    async def workspace(user=Depends(get_current_user)):
        return user

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/workspace')
        assert response.status_code == 200
        assert response.json()['user_id'] == DEFAULT_DEV_USER['user_id']
        response = await client.post('/workspace', headers={'Origin': 'https://foreign.example'})
        assert response.status_code == 403


def test_login_endpoints_are_removed():
    app = create_app(Settings(_env_file=None, environment='test'))
    assert not any(path.startswith('/api/v1/auth') for path in app.openapi()['paths'])


def test_existing_connections_move_to_shared_workspace():
    engine = sa.create_engine('sqlite:///:memory:')
    metadata.create_all(engine)
    set_engine(engine)
    try:
        with engine.begin() as conn:
            conn.execute(users.insert().values(id='old-owner', email='old@example.com', password_hash='disabled'))
            conn.execute(connections.insert().values(
                id='existing', user_id='old-owner', name='Existing', engine='postgresql',
                host='db.example', port=5432, database='data', username='reader',
                encrypted_password='encrypted', allowed_tables='{}',
            ))
        initialize_workspace()
        initialize_workspace()
        with engine.connect() as conn:
            assert conn.execute(sa.select(connections.c.user_id)).scalar_one() == DEFAULT_DEV_USER['user_id']
    finally:
        set_engine(None)
        engine.dispose()
