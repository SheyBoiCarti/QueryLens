"""All origins share guarded publication and cleanup."""

import pytest
from querylens.execution.executor import SafeExecutor
from querylens.domain.query import QueryResult
from querylens.persistence.repositories.query_runs import QueryRunRepository
from querylens.persistence.tables import connections
from test_manual_sql_execution import submit, wait_terminal


@pytest.mark.parametrize("change", ["semantic", "policy", "physical", "cancel"])
def test_publication_rechecks_drift_and_terminal_races(analytics_env, monkeypatch, change):
    env = analytics_env

    def execute(token, query_id=None, **kwargs):
        if change == "cancel":
            QueryRunRepository().update_state(query_id, "cancelled")
        elif change == "physical":
            from querylens.schema.snapshots import save_snapshot

            snapshot = env.snapshot.model_copy(deep=True)
            snapshot.tables[0].columns.pop()
            snapshot.snapshot_hash = snapshot.compute_hash()
            save_snapshot(snapshot)
        else:
            with env.engine.begin() as conn:
                column = connections.c.semantic_version if change == "semantic" else connections.c.policy_version
                conn.execute(
                    connections.update().where(connections.c.id == env.connection_id).values({column.name: column + 1})
                )
        return QueryResult([{"name": "id", "type": "integer", "db_type": "integer"}], [{"id": 3}], 1, False, 1)

    monkeypatch.setattr(SafeExecutor, "execute", execute)
    response = submit(env, "SELECT id FROM public.customers")
    assert response.status_code == 202, response.text
    run = wait_terminal(env, response.json()["query_id"])
    assert run["status"] == ("cancelled" if change == "cancel" else "rejected"), run
    assert env.cache.get(run["query_id"], env.snapshot.snapshot_hash) is None
    stored = QueryRunRepository().get(run["query_id"], env.owner_id)
    assert stored["run_context_json"] is None


def test_manual_overload_rejects_before_creating_run(analytics_env):
    import sqlalchemy as sa
    from querylens.jobs.admission import get_admission_controller
    from querylens.persistence.tables import query_runs

    env = analytics_env
    controller = get_admission_controller()
    reservations = [
        controller.reserve(env.owner_id, env.connection_id) for _ in range(controller.per_user_waiting_limit)
    ]
    try:
        response = submit(env, "SELECT 1")
        assert response.status_code == 429
        with env.engine.connect() as conn:
            assert conn.execute(sa.select(sa.func.count()).select_from(query_runs)).scalar_one() == 0
    finally:
        for reservation in reservations:
            reservation.release()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "problem", ["missing_source", "incomplete_source", "lowered_rows", "lowered_bytes", "unexpected"]
)
async def test_worker_rechecks_source_and_limits_and_always_terminates(
    analytics_env, completed_run, monkeypatch, problem
):
    import uuid
    from querylens.config import get_settings
    from querylens.pipeline.direct import run_manual_sql_pipeline
    import querylens.pipeline.direct as direct

    env = analytics_env
    repo = QueryRunRepository()
    query_id = str(uuid.uuid4())
    source_id = None
    if problem in {"missing_source", "incomplete_source"}:
        source_id = str(uuid.uuid4())
        if problem == "incomplete_source":
            repo.create(source_id, env.owner_id, env.connection_id, "not complete")
    repo.create(query_id, env.owner_id, env.connection_id, "Edited SQL", origin="manual_sql")
    monkeypatch.setattr(SafeExecutor, "execute", lambda *a, **kw: pytest.fail("ineligible work reached executor"))
    if problem == "lowered_rows":
        monkeypatch.setattr(get_settings(), "max_max_rows", 10)
    if problem == "lowered_bytes":
        monkeypatch.setattr(get_settings(), "max_sql_bytes", 10)
    if problem == "unexpected":

        def fail(*args):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(direct, "verify_connection_ownership", fail)
    await run_manual_sql_pipeline(
        query_id, env.owner_id, env.connection_id, "SELECT id FROM public.customers", source_id
    )
    assert repo.get(query_id, env.owner_id)["status"] in {"failed", "rejected"}


@pytest.mark.asyncio
async def test_queued_cancellation_releases_reservation(analytics_env):
    import asyncio
    import uuid
    from querylens.jobs.admission import get_admission_controller
    from querylens.pipeline.direct import run_manual_sql_pipeline

    env = analytics_env
    controller = get_admission_controller()
    blocker = controller.acquire(env.owner_id, env.connection_id)
    reservation = controller.reserve(env.owner_id, env.connection_id)
    query_id = str(uuid.uuid4())
    repo = QueryRunRepository()
    repo.create(query_id, env.owner_id, env.connection_id, "Edited SQL", origin="manual_sql")
    task = asyncio.create_task(
        run_manual_sql_pipeline(query_id, env.owner_id, env.connection_id, "SELECT 1", reservation=reservation)
    )
    await asyncio.sleep(0.02)
    assert repo.get(query_id, env.owner_id)["status"] == "queued"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert repo.get(query_id, env.owner_id)["status"] == "cancelled"
    assert reservation.state == "released"
    assert controller._waiting_global == 0
    blocker.release()


@pytest.mark.asyncio
async def test_inflight_cancellation_holds_lease_until_dbapi_cleanup(analytics_env, monkeypatch):
    import asyncio
    import threading
    import uuid
    from querylens.config import get_settings
    from querylens.jobs.admission import get_admission_controller
    from querylens.pipeline.direct import run_manual_sql_pipeline

    env = analytics_env
    started, finish = threading.Event(), threading.Event()

    def execute(*args, **kwargs):
        started.set()
        assert finish.wait(3)
        return QueryResult([], [], 0, False, 1)

    monkeypatch.setattr(SafeExecutor, "execute", execute)
    monkeypatch.setattr(get_settings(), "cleanup_timeout_sec", 0.03)
    controller = get_admission_controller()
    reservation = controller.reserve(env.owner_id, env.connection_id)
    query_id = str(uuid.uuid4())
    repo = QueryRunRepository()
    repo.create(query_id, env.owner_id, env.connection_id, "Edited SQL", origin="manual_sql")
    task = asyncio.create_task(
        run_manual_sql_pipeline(query_id, env.owner_id, env.connection_id, "SELECT 1", reservation=reservation)
    )
    try:
        for _ in range(200):
            if started.is_set():
                break
            await asyncio.sleep(0.005)
        assert started.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert controller._active_global == 1
        assert repo.get(query_id, env.owner_id)["status"] == "cancelled"
    finally:
        finish.set()
    for _ in range(200):
        if controller._active_global == 0:
            break
        await asyncio.sleep(0.005)
    assert controller._active_global == 0
    assert reservation.state == "released"
    assert env.cache.get(query_id, env.snapshot.snapshot_hash) is None


def test_natural_language_uses_shared_publication_and_context(analytics_env, monkeypatch):
    from llm_stub import get_fake_llm_provider
    from querylens.llm.protocol import GeneratedCandidate

    env = analytics_env
    get_fake_llm_provider().register_response(
        "postgresql", "list IDs", GeneratedCandidate(sql="SELECT id FROM public.customers")
    )
    monkeypatch.setattr(
        SafeExecutor,
        "execute",
        lambda *a, **kw: QueryResult(
            [{"name": "id", "type": "integer", "db_type": "integer"}], [{"id": 9}], 1, False, 1
        ),
    )
    response = env.client.post(
        "/api/v1/queries", headers=env.headers, json={"connection_id": env.connection_id, "question": "list IDs"}
    )
    assert response.status_code == 202
    run = wait_terminal(env, response.json()["query_id"])
    assert run["status"] == "completed", run
    assert run["origin"] == "natural_language"
    import json

    assert (
        json.loads(QueryRunRepository().get(run["query_id"], env.owner_id)["run_context_json"])["author_limit"] is None
    )
    assert run["rows"] == [{"id": 9}]


def test_missing_llm_configuration_is_displayed_on_submitted_prompt(analytics_env, monkeypatch):
    from querylens.config import get_settings
    from querylens.llm.live import get_live_llm_provider
    import querylens.pipeline.orchestrator as orchestrator

    env = analytics_env
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", None)
    monkeypatch.setattr(settings, "llm_model", "")
    monkeypatch.setattr(settings, "llm_api_key", None)
    monkeypatch.setattr(orchestrator, "get_live_llm_provider", get_live_llm_provider)
    monkeypatch.setattr(SafeExecutor, "execute", lambda *a, **kw: pytest.fail("unconfigured query executed"))
    response = env.client.post(
        "/api/v1/queries", headers=env.headers,
        json={"connection_id": env.connection_id, "question": "List customers"},
    )
    assert response.status_code == 202, response.text
    run = wait_terminal(env, response.json()["query_id"])
    assert run["status"] == "failed", run
    assert run["error_code"] == "CONFIG_ERROR"
    assert run["safe_message"] == (
        "The LLM is not configured. Please configure the provider, model, and API key, then try again."
    )
