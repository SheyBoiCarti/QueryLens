"""Authenticated semantic boundaries and transactional version changes."""

import json
import uuid
import sqlalchemy as sa
from querylens.persistence.tables import business_metrics, catalog_labels, connections
from querylens.semantics.versions import load_semantic_context


def metric(**updates):
    return dict(
        dict(
            key="buyers",
            name="Buyers",
            table="public.customers",
            measure_column="id",
            aggregation="count",
            synonyms=["Patrons"],
        ),
        **updates,
    )


def base(env):
    return f"/api/v1/connections/{env.connection_id}"


def label(**updates):
    return dict(dict(namespace="public", table_name="customers", display_name="Clients"), **updates)


def version(env):
    with env.engine.connect() as conn:
        return conn.execute(
            sa.select(connections.c.semantic_version).where(connections.c.id == env.connection_id)
        ).scalar_one()


def test_metric_lifecycle_conflicts_and_versions(analytics_env):
    env = analytics_env
    url = base(env) + "/metrics"
    created = env.client.post(url, json=metric(), headers=env.headers)
    assert created.status_code == 201, created.text
    item = created.json()
    assert version(env) == 2
    for alias in ("  ＰＡＴＲＯＮＳ  ", " BUYERS ", "Buyers"):
        conflict = metric(key="other", name="Other", synonyms=[alias])
        assert env.client.post(url, json=conflict, headers=env.headers).status_code == 409
    assert version(env) == 2
    patch = url + "/" + item["id"]
    result = env.client.patch(patch, json={"expected_version": 1, "enabled": False}, headers=env.headers)
    assert result.status_code == 200, result.text
    assert result.json()["version"] == 2 and version(env) == 3
    assert (
        env.client.patch(patch, json={"expected_version": 1, "enabled": True}, headers=env.headers).status_code == 409
    )
    assert env.client.post(url, json=metric(key="other", name="Other"), headers=env.headers).status_code == 201
    assert (
        env.client.patch(patch, json={"expected_version": 2, "enabled": True}, headers=env.headers).status_code == 409
    )
    updated = metric(name="Clients", synonyms=["Purchasers"], description="Active clients", grain=["country"])
    result = env.client.patch(patch, json={"expected_version": 2, "dsl": updated}, headers=env.headers)
    assert result.status_code == 200, result.text
    assert result.json()["dsl"]["grain"] == ["country"] and result.json()["version"] == 3
    before = version(env)
    assert env.client.delete(patch, headers=env.headers).status_code == 200
    assert version(env) == before + 1
    assert env.snapshot.compute_hash() == env.snapshot.snapshot_hash


def test_label_replace_scopes_versions_and_visibility(analytics_env):
    env = analytics_env
    url = base(env) + "/labels"
    assert env.client.get(url).json() == {"semantic_version": 1, "labels": []}
    labels = [label(), label(column_name="country", display_name="Region")]
    response = env.client.put(url, json={"expected_semantic_version": 1, "labels": labels}, headers=env.headers)
    assert response.status_code == 200, response.text
    assert response.json()["semantic_version"] == 2
    assert all(x["version"] == 1 for x in response.json()["labels"])
    assert (
        env.client.put(url, json={"expected_semantic_version": 1, "labels": []}, headers=env.headers).status_code == 409
    )
    labels[1]["display_name"] = "Clients"  # table and column alias namespaces are independent
    response = env.client.put(url, json={"expected_semantic_version": 2, "labels": labels}, headers=env.headers)
    assert response.status_code == 200, response.text
    assert next(x for x in response.json()["labels"] if x["column_name"])["version"] == 2
    with env.engine.begin() as conn:
        conn.execute(
            catalog_labels.insert().values(
                id=str(uuid.uuid4()),
                connection_id=env.connection_id,
                namespace="secret",
                table_name="payroll",
                display_name="Hidden payroll",
            )
        )
        hidden = metric(key="secret", name="Secret", table="secret.payroll")
        conn.execute(
            business_metrics.insert().values(
                id=str(uuid.uuid4()),
                connection_id=env.connection_id,
                key="secret",
                name="Secret",
                dsl_json=json.dumps(hidden),
            )
        )
    assert "Hidden payroll" not in env.client.get(url).text
    assert "Secret" not in env.client.get(base(env) + "/metrics").text
    semantic = load_semantic_context(env.owner_id, env.snapshot)
    assert len(semantic.labels) == 2 and semantic.metrics == ()
    assert (
        env.client.put(url, json={"expected_semantic_version": 3, "labels": []}, headers=env.headers).status_code == 200
    )
    with env.engine.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(catalog_labels)).scalar_one() == 1
    assert (
        env.client.put(
            url,
            json={"expected_semantic_version": 4, "labels": [label(namespace="secret", table_name="payroll")]},
            headers=env.headers,
        ).status_code
        == 422
    )


def test_security_and_invalid_payloads(analytics_env):
    env = analytics_env
    for suffix, method, payload in (
        ("/labels", "put", {"expected_semantic_version": 1, "labels": []}),
        ("/metrics", "post", metric()),
        ("/metrics/unknown", "patch", {"expected_version": 1, "enabled": False}),
    ):
        assert getattr(env.client, method)(base(env) + suffix, json=payload, headers={"Origin": "https://foreign.example"}).status_code == 403
        for cid in (env.foreign_connection_id, "unknown"):
            assert (
                getattr(env.client, method)(
                    f"/api/v1/connections/{cid}" + suffix, json=payload, headers=env.headers
                ).status_code
                == 404
            )
    for suffix in ("/labels", "/metrics"):
        assert env.client.get(f"/api/v1/connections/{env.foreign_connection_id}" + suffix).status_code == 404
    assert (
        env.client.patch(
            base(env) + "/metrics/unknown", json={"expected_version": 1, "enabled": False}, headers=env.headers
        ).status_code
        == 404
    )
    for synonyms in ([" "], ["x" * 101], ["x"] * 21):
        assert (
            env.client.post(base(env) + "/metrics", json=metric(synonyms=synonyms), headers=env.headers).status_code
            == 422
        )
    for labels in ([label(), label()], [label(column_name="missing")], [label(display_name=" ")]):
        assert env.client.put(
            base(env) + "/labels", json={"expected_semantic_version": 1, "labels": labels}, headers=env.headers
        ).status_code in (409, 422)


def test_legacy_loading(analytics_env):
    env = analytics_env
    data = metric()
    del data["synonyms"]
    with env.engine.begin() as conn:
        conn.execute(
            business_metrics.insert().values(
                id=str(uuid.uuid4()),
                connection_id=env.connection_id,
                key=data["key"],
                name=data["name"],
                dsl_json=json.dumps(data),
            )
        )
    response = env.client.get(base(env) + "/metrics")
    assert response.status_code == 200 and response.json()[0]["dsl"]["synonyms"] == []
    assert len(load_semantic_context(env.owner_id, env.snapshot).metrics) == 1


def test_label_alias_scopes_and_mysql_namespace(analytics_env):
    from querylens.domain.schema import TableMetadata, ColumnMetadata
    from querylens.schema.snapshots import save_snapshot

    env = analytics_env
    # Saved source catalog uses MySQL's actual database namespace.
    tables = [
        TableMetadata(
            namespace="shop",
            name=name,
            columns=[
                ColumnMetadata(name="id", canonical_type="integer", db_type="int"),
                ColumnMetadata(name="country", canonical_type="string", db_type="varchar(50)"),
            ],
        )
        for name in ("customers", "suppliers")
    ]
    snapshot = env.snapshot.model_copy(update={"engine": "mysql", "tables": tables})
    snapshot.snapshot_hash = snapshot.compute_hash()
    with env.engine.begin() as conn:
        conn.execute(connections.update().where(connections.c.id == env.connection_id).values(engine="mysql"))
    save_snapshot(snapshot)
    url = base(env) + "/labels"
    first = label(namespace="shop")
    response = env.client.put(url, json={"expected_semantic_version": 1, "labels": [first]}, headers=env.headers)
    assert response.status_code == 200, response.text
    assert response.json()["labels"][0]["namespace"] == "shop"
    # Equivalent display names conflict for tables in the same namespace.
    other = label(namespace="shop", table_name="suppliers", display_name="  ＣＬＩＥＮＴＳ ")
    assert (
        env.client.put(
            url, json={"expected_semantic_version": 2, "labels": [first, other]}, headers=env.headers
        ).status_code
        == 409
    )
    # Equivalent column names conflict only within their table.
    columns = [label(namespace="shop", column_name=c, display_name="Region") for c in ("id", "country")]
    assert (
        env.client.put(url, json={"expected_semantic_version": 2, "labels": columns}, headers=env.headers).status_code
        == 409
    )
    columns[1]["table_name"] = "suppliers"
    assert (
        env.client.put(url, json={"expected_semantic_version": 2, "labels": columns}, headers=env.headers).status_code
        == 200
    )
    assert snapshot.snapshot_hash == snapshot.compute_hash()
    assert load_semantic_context(env.owner_id, snapshot).semantic_version == 3
    # A mutation based on an old physical snapshot is rejected before writes.
    from querylens.semantics.labels import replace_labels
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as error:
        replace_labels(env.owner_id, env.snapshot, 3, [])
    assert error.value.status_code == 409
    assert version(env) == 3


def test_concurrent_writes_serialize_on_postgres(analytics_env, analytics_postgres_url, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from querylens.persistence import session
    from querylens.persistence.tables import metadata, users, schema_snapshots

    env = analytics_env
    engine = sa.create_engine(analytics_postgres_url)
    metadata.create_all(engine)
    try:
        # Copy only disposable fixture metadata, without touching application databases.
        with env.engine.connect() as source, engine.begin() as destination:
            for table in (users, connections, schema_snapshots):
                rows = [dict(row) for row in source.execute(sa.select(table)).mappings()]
                if rows:
                    destination.execute(table.insert(), rows)
        monkeypatch.setattr(session, "_engine", engine)
        from querylens.semantics.labels import CatalogLabelInput, replace_labels
        from fastapi import HTTPException
        from threading import Barrier

        barrier = Barrier(2)

        def save_label():
            barrier.wait(timeout=10)
            try:
                replace_labels(env.owner_id, env.snapshot, 1, [CatalogLabelInput(**label())])
                return 200
            except HTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: save_label(), range(2))) == [200, 409]
        with engine.connect() as conn:
            assert (
                conn.execute(
                    sa.select(connections.c.semantic_version).where(connections.c.id == env.connection_id)
                ).scalar_one()
                == 2
            )
            assert conn.execute(sa.select(sa.func.count()).select_from(catalog_labels)).scalar_one() == 1
        # Two different keys sharing an alias must not both pass conflict detection.
        from querylens.api.metrics import create_metric
        from querylens.semantics.metrics import MetricDSL

        barrier = Barrier(2)

        def save_metric(key):
            barrier.wait(timeout=10)
            try:
                create_metric(
                    env.connection_id, MetricDSL(**metric(key=key, name=key)), {"user_id": env.owner_id}, None
                )
                return 201
            except HTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(save_metric, ("one", "two"))) == [201, 409]
        with engine.connect() as conn:
            assert (
                conn.execute(
                    sa.select(connections.c.semantic_version).where(connections.c.id == env.connection_id)
                ).scalar_one()
                == 3
            )
            assert conn.execute(sa.select(sa.func.count()).select_from(business_metrics)).scalar_one() == 1
    finally:
        engine.dispose()


def test_revoked_metadata_never_enters_prompt_or_delivery(analytics_env):
    from querylens.schema.snapshots import save_snapshot
    from querylens.pipeline.context import build_query_context

    env = analytics_env
    labels_url = base(env) + "/labels"
    metrics_url = base(env) + "/metrics"
    assert (
        env.client.put(
            labels_url,
            json={"expected_semantic_version": 1, "labels": [label(column_name="country", display_name="Territories")]},
            headers=env.headers,
        ).status_code
        == 200
    )
    created = env.client.post(
        metrics_url, json=metric(measure_column="country", name="ClassifiedRegions"), headers=env.headers
    )
    assert created.status_code == 201
    original = load_semantic_context(env.owner_id, env.snapshot)
    # Revoke a column using a new, persisted authorized snapshot.
    snapshot = env.snapshot.model_copy(deep=True)
    snapshot.tables[0].columns = [column for column in snapshot.tables[0].columns if column.name != "country"]
    snapshot.snapshot_hash = snapshot.compute_hash()
    save_snapshot(snapshot)
    assert env.client.get(labels_url).json()["labels"] == []
    assert env.client.get(metrics_url).json() == []
    assert (
        env.client.patch(
            metrics_url + "/" + created.json()["id"],
            json={"expected_version": 1, "enabled": False},
            headers=env.headers,
        ).status_code
        == 404
    )
    semantic = load_semantic_context(env.owner_id, snapshot)
    assert semantic.labels == () and semantic.metrics == ()
    # Even an accidentally retained old context is filtered against the supplied snapshot.
    prompt = build_query_context(snapshot, "Territories ClassifiedRegions", 6000, semantic_context=original)
    assert "Territories" not in prompt and "ClassifiedRegions" not in prompt and "country" not in prompt
    assert (
        env.client.put(labels_url, json={"expected_semantic_version": 3, "labels": []}, headers=env.headers).status_code
        == 200
    )
    save_snapshot(env.snapshot)
    assert env.client.get(labels_url).json()["labels"][0]["display_name"] == "Territories"
    assert env.client.get(metrics_url).json()[0]["dsl"]["name"] == "ClassifiedRegions"


def test_noop_versions_and_payload_bounds(analytics_env):
    env = analytics_env
    url = base(env) + "/metrics"
    created = env.client.post(url, json=metric(), headers=env.headers).json()
    response = env.client.patch(
        url + "/" + created["id"], json={"expected_version": 1, "enabled": True}, headers=env.headers
    )
    assert response.status_code == 200 and response.json()["version"] == 1 and version(env) == 2
    for payload in (
        {"expected_version": 1},
        {"expected_version": 1, "dsl": None},
        {"expected_version": 1, "enabled": "false"},
    ):
        assert env.client.patch(url + "/" + created["id"], json=payload, headers=env.headers).status_code == 422
    for update in (dict(display_name="x" * 201), dict(description="x" * 2001)):
        assert (
            env.client.put(
                base(env) + "/labels",
                json={"expected_semantic_version": 2, "labels": [label(**update)]},
                headers=env.headers,
            ).status_code
            == 422
        )
    assert env.client.post(url, json=metric(description="x" * 1001), headers=env.headers).status_code == 422
    assert version(env) == 2


async def test_pipeline_sends_authorized_labels_and_complete_synonym_metric(analytics_env, monkeypatch):
    from querylens.llm.protocol import GeneratedCandidate, LLMUsage
    from querylens.llm.provider import LLMProvider
    from querylens.persistence.repositories.query_runs import QueryRunRepository
    from querylens.pipeline.orchestrator import run_query_pipeline
    from querylens.execution.executor import SafeExecutor

    env = analytics_env
    data = metric(
        description="People by region",
        grain=["country"],
        units="people",
        filters=[dict(column="country", operator="neq", value="unknown")],
    )
    response = env.client.post(base(env) + "/metrics", json=data, headers=env.headers)
    assert response.status_code == 201
    dsl = response.json()["dsl"]
    assert (
        env.client.put(
            base(env) + "/labels",
            json={"expected_semantic_version": 2, "labels": [label(display_name="Client directory")]},
            headers=env.headers,
        ).status_code
        == 200
    )
    prompts = []

    class ProviderSpy(LLMProvider):
        async def generate(self, question, dialect, schema_context, timeout_sec=15.0):
            prompts.append(schema_context)
            return GeneratedCandidate(
                requires_clarification=True,
                clarification_question="Which period?",
                usage=LLMUsage(prompt_tokens=100, completion_tokens=10),
            )

    def no_source(*args, **kwargs):
        raise AssertionError("This prompt test must not perform source I/O")

    monkeypatch.setattr(SafeExecutor, "execute", no_source)
    query_id = str(uuid.uuid4())
    repo = QueryRunRepository()
    repo.create(query_id, env.owner_id, env.connection_id, "Patrons by country")
    await run_query_pipeline(query_id, env.owner_id, env.connection_id, "Patrons by country", provider=ProviderSpy())
    assert repo.get(query_id, env.owner_id)["status"] == "clarification_required"
    assert len(prompts) == 1
    from querylens.semantics.metrics import MetricDSL

    assert MetricDSL(**dsl).model_dump_json() in prompts[0]
    assert "Client directory" in prompts[0] and "TABLE public.customers:" in prompts[0]
