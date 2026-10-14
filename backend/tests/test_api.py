import uuid

from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import UNANSWERABLE, ScriptedProvider, sql_reply

TOTAL_REVENUE = (
    "SELECT ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount)), 2) AS total_revenue "
    "FROM orders o JOIN order_items oi ON oi.order_id = o.order_id "
    "WHERE o.status NOT IN ('cancelled', 'refunded')"
)


def assert_error_shape(response, status, code):
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "Traceback" not in response.text


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["schema_version"]
    uuid.UUID(r.headers["X-Request-ID"])


def test_schema_endpoint_returns_real_metadata(client):
    body = client.get("/api/schema").json()
    tables = {t["name"]: t for t in body["tables"]}
    assert set(tables) == {"customers", "products", "orders", "order_items"}
    assert tables["orders"]["primary_key"] == ["order_id"]
    assert {"column": "customer_id", "references_table": "customers",
            "references_column": "customer_id"} in tables["orders"]["foreign_keys"]
    assert tables["orders"]["row_count"] == 1600
    assert len(body["relationships"]) == 3
    assert body["database_type"] == "sqlite"


def test_query_success_flow(client):
    client.provider.queue(sql_reply(TOTAL_REVENUE, tables_used=["orders", "order_items"]))
    r = client.post("/api/query", json={"question": "What is our total revenue?"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["request_id"] == r.headers["X-Request-ID"]
    assert body["columns"] == [{"name": "total_revenue", "type": "number"}]
    assert body["row_count"] == 1 and isinstance(body["rows"][0][0], float)
    assert body["answer"] == "Grounded answer from rows."
    assert body["retry_count"] == 0
    assert body["usage"]["llm_calls"] == 2  # generation + answer
    assert body["usage"]["input_tokens"] == 1300
    assert body["usage"]["cost_status"] == "estimated"
    assert body["usage"]["estimated_cost_usd"] > 0
    assert body["timings"]["total_ms"] >= body["timings"]["db_ms"]
    assert body["cache"] == {"hit": False, "stored": True, "reason": None}


def test_cache_hit_on_repeat_and_bypass(client):
    client.provider.queue(sql_reply(TOTAL_REVENUE))
    first = client.post("/api/query", json={"question": "What is our total revenue?"}).json()
    second = client.post("/api/query", json={"question": "  what is our TOTAL revenue "}).json()
    assert second["cache"]["hit"] is True
    assert second["rows"] == first["rows"]
    assert second["usage"]["llm_calls"] == 0 and second["usage"]["cost_status"] == "no_llm_calls"
    assert second["request_id"] != first["request_id"]

    client.provider.queue(sql_reply(TOTAL_REVENUE))
    third = client.post("/api/query", json={"question": "What is our total revenue?",
                                            "use_cache": False}).json()
    assert third["cache"]["hit"] is False

    assert client.post("/api/cache/clear").json() == {"cleared_entries": 1}
    client.provider.queue(sql_reply(TOTAL_REVENUE))
    fourth = client.post("/api/query", json={"question": "What is our total revenue?"}).json()
    assert fourth["cache"]["hit"] is False


def test_failed_queries_are_not_cached(client):
    client.provider.queue(UNANSWERABLE, UNANSWERABLE)
    for _ in range(2):
        body = client.post("/api/query", json={"question": "What is the weather?"}).json()
        assert body["status"] == "unanswerable" and body["cache"]["hit"] is False


def test_retry_then_success_reported(client):
    client.provider.queue(sql_reply("SELECT SUM(total) AS t FROM orders"), sql_reply(TOTAL_REVENUE))
    body = client.post("/api/query", json={"question": "What is our total revenue?"}).json()
    assert body["status"] == "success"
    assert body["retry_count"] == 1
    assert [a["status"] for a in body["attempts"]] == ["validation_error", "success"]
    assert body["usage"]["llm_calls"] == 3


def test_destructive_sql_is_rejected(client):
    client.provider.queue(sql_reply("DROP TABLE orders"))
    body = client.post("/api/query", json={"question": "Drop the orders table"}).json()
    assert body["status"] == "rejected"
    assert body["error"]["category"] == "security"
    assert body["rows"] == [] and body["sql"] is None
    # the table is still there
    assert client.get("/api/schema").json()["tables"]


def test_invalid_request_error_shape(client):
    assert_error_shape(client.post("/api/query", json={"question": "x"}), 422, "invalid_request")
    assert_error_shape(client.post("/api/query", json={}), 422, "invalid_request")
    assert_error_shape(client.post("/api/query", json={"question": "a" * 501}), 422, "invalid_request")


def test_not_found_error_shape(client):
    assert_error_shape(client.get("/api/history/does-not-exist"), 404, "not_found")
    assert_error_shape(client.get("/api/nope"), 404, "http_error")


def test_history_and_detail(client):
    client.provider.queue(sql_reply(TOTAL_REVENUE))
    rid = client.post("/api/query", json={"question": "What is our total revenue?"}).json()["request_id"]
    client.provider.queue(sql_reply("DELETE FROM orders"))
    client.post("/api/query", json={"question": "delete orders"})

    history = client.get("/api/history").json()
    assert history["total"] == 2
    assert history["items"][0]["status"] == "rejected"  # newest first
    assert client.get("/api/history", params={"status": "success"}).json()["total"] == 1
    assert client.get("/api/history", params={"search": "revenue"}).json()["total"] == 1

    detail = client.get(f"/api/history/{rid}").json()
    assert detail["final_sql"].startswith("SELECT")
    assert detail["attempts"][0]["status"] == "success"
    assert detail["created_at"].endswith("+00:00") or detail["created_at"].endswith("Z")


def test_analytics_reflect_recorded_requests(client):
    empty = client.get("/api/analytics").json()
    assert empty["total_requests"] == 0 and empty["success_rate"] is None

    client.provider.queue(sql_reply(TOTAL_REVENUE), sql_reply("DROP TABLE orders"))
    client.post("/api/query", json={"question": "What is our total revenue?"})
    client.post("/api/query", json={"question": "drop it"})
    client.post("/api/query", json={"question": "What is our total revenue?"})  # cache hit
    data = client.get("/api/analytics").json()
    assert data["total_requests"] == 3
    assert data["successful_requests"] == 2
    assert data["rejected_requests"] == 1
    assert data["cache_hits"] == 1
    assert data["cache"]["hits"] == 1


def test_config_exposes_no_secrets(make_settings):
    settings = make_settings(llm_provider="anthropic", anthropic_api_key="sk-ant-super-secret")
    app = create_app(settings, provider=ScriptedProvider())
    with TestClient(app) as c:
        r = c.get("/api/config")
    assert r.status_code == 200
    assert "sk-ant-super-secret" not in r.text
    body = r.json()
    assert body["max_correction_attempts"] == 2
    assert body["database_name"] == "business.db"
    assert body["settings_editable"] is False


def test_rate_limit(make_settings):
    app = create_app(make_settings(rate_limit_per_minute=2), provider=ScriptedProvider([UNANSWERABLE] * 3))
    with TestClient(app) as c:
        for _ in range(2):
            assert c.post("/api/query", json={"question": "weather?"}).status_code == 200
        assert_error_shape(c.post("/api/query", json={"question": "weather?"}), 429, "rate_limited")


def test_mock_provider_end_to_end(make_settings):
    """Default offline mode: real SQL execution, clearly labelled, cost unavailable."""
    with TestClient(create_app(make_settings())) as c:
        body = c.post("/api/query", json={"question": "Which products have never been ordered?"}).json()
    assert body["status"] == "success"
    assert body["is_mock_provider"] is True
    assert body["row_count"] == 4
    assert body["usage"]["cost_status"] == "unavailable"
    assert body["usage"]["estimated_cost_usd"] is None


def test_truncated_results_carry_a_warning(make_settings):
    provider = ScriptedProvider([sql_reply("SELECT order_id FROM orders")], answer="Many orders.")
    with TestClient(create_app(make_settings(max_result_rows=10), provider=provider)) as c:
        body = c.post("/api/query", json={"question": "List every order id"}).json()
    assert body["truncated"] is True and body["row_count"] == 10
    assert any("first 10 rows" in w for w in body["warnings"])
