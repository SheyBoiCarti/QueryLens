"""Natural-language HTTP journey against isolated real source fixtures."""

from llm_stub import get_fake_llm_provider
from querylens.llm.protocol import GeneratedCandidate, LLMUsage
from test_manual_sql_execution import wait_terminal


def test_full_vertical_slice_workflow(analytics_source_env):
    env = analytics_source_env
    fake = get_fake_llm_provider()
    fake.register_response(
        env.snapshot.engine, "get constant values",
        GeneratedCandidate(sql="SELECT 42 AS answer, 'querylens' AS app_name",
                           assumptions=["Direct projection"], requires_clarification=False,
                           usage=LLMUsage(prompt_tokens=50, completion_tokens=15, latency_ms=10)),
    )
    response = env.client.post(
        "/api/v1/queries", headers=env.headers,
        json={"connection_id": env.connection_id, "question": "get constant values", "max_rows": 50},
    )
    assert response.status_code == 202, response.text
    completed = wait_terminal(env, response.json()["query_id"])
    assert completed["status"] == "completed", completed
    assert completed["rows"] == [{"answer": "42", "app_name": "querylens"}]
    assert completed["max_rows"] == 50

    fake.register_response(
        env.snapshot.engine, "show me the best",
        GeneratedCandidate(sql="", assumptions=[], requires_clarification=True,
                           clarification_question="Which measure should define best?",
                           usage=LLMUsage(prompt_tokens=50, completion_tokens=15, latency_ms=10)),
    )
    response = env.client.post(
        "/api/v1/queries", headers=env.headers,
        json={"connection_id": env.connection_id, "question": "show me the best"},
    )
    assert response.status_code == 202, response.text
    import time
    for _ in range(200):
        run = env.client.get(f"/api/v1/queries/{response.json()['query_id']}").json()
        if run["status"] == "clarification_required":
            break
        assert run["status"] not in ("failed", "rejected"), run
        time.sleep(0.01)
    assert run["status"] == "clarification_required"
    assert run["clarification_question"] == "Which measure should define best?"
