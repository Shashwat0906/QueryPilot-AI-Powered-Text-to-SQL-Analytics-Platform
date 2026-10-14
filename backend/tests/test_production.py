"""Production-readiness: config parsing, CORS, security headers, client IPs,
history privacy, daily spend caps, schema migration, PostgreSQL history."""

import os
import sqlite3
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.routes import client_ip
from app.core.config import Settings
from app.main import create_app
from app.models.request_log import RequestLog
from app.services.history_service import HistoryService, create_metadata_engine
from tests.fakes import ScriptedProvider, sql_reply

COUNT = "SELECT COUNT(*) AS n FROM orders"


# ---------- configuration ----------
def test_list_settings_accept_comma_separated_and_json(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://querypilot.vercel.app, https://example.dev")
    assert Settings().cors_origins == ["https://querypilot.vercel.app", "https://example.dev"]
    monkeypatch.setenv("CORS_ORIGINS", '["https://a.app","https://b.app"]')
    assert Settings().cors_origins == ["https://a.app", "https://b.app"]


@pytest.mark.parametrize("url", ["postgres://u:p@host:5432/db", "postgresql://u:p@host:5432/db"])
def test_postgres_urls_get_a_driver(url):
    assert Settings(metadata_database_url=url).metadata_database_url == (
        "postgresql+psycopg://u:p@host:5432/db"
    )


# ---------- client IP ----------
def _request(headers: dict[str, str], peer: str = "10.0.0.1") -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/", "client": (peer, 1234),
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    })


def test_client_ip_uses_peer_without_trusted_header():
    assert client_ip(_request({"X-Forwarded-For": "6.6.6.6"}), "") == "10.0.0.1"


def test_client_ip_uses_last_hop_of_trusted_header():
    # "6.6.6.6" was sent by the client; the proxy appended the real address.
    req = _request({"X-Forwarded-For": "6.6.6.6, 203.0.113.9"})
    assert client_ip(req, "X-Forwarded-For") == "203.0.113.9"
    assert client_ip(_request({}), "X-Forwarded-For") == "10.0.0.1"  # header missing -> peer


# ---------- CORS + headers ----------
@pytest.fixture
def prod_client(make_settings):
    def _make(provider=None, **overrides):
        settings = make_settings(environment="production", **overrides)
        return TestClient(create_app(settings, provider=provider or ScriptedProvider()))
    return _make


def test_cors_allows_configured_origin_only(prod_client):
    c = prod_client(cors_origins=["https://querypilot.vercel.app"],
                    cors_origin_regex=r"^https://querypilot-[a-z0-9-]+\.vercel\.app$")
    preflight = {"Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type,x-client-id"}
    ok = c.options("/api/query", headers={"Origin": "https://querypilot.vercel.app", **preflight})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "https://querypilot.vercel.app"
    assert "x-client-id" in ok.headers["access-control-allow-headers"].lower()
    preview = c.options("/api/query", headers={"Origin": "https://querypilot-git-feat-x.vercel.app",
                                               **preflight})
    assert preview.status_code == 200
    evil = c.options("/api/query", headers={"Origin": "https://evil.example", **preflight})
    assert "access-control-allow-origin" not in evil.headers


def test_security_headers_and_hsts_in_production(prod_client):
    r = prod_client().get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    assert "max-age" in r.headers["strict-transport-security"]


def test_api_docs_can_be_disabled(prod_client):
    assert prod_client(enable_api_docs=False).get("/docs").status_code == 404
    assert prod_client().get("/docs").status_code == 200


# ---------- history privacy ----------
def test_client_scoped_history_hides_other_visitors(prod_client):
    provider = ScriptedProvider([sql_reply(COUNT), sql_reply(COUNT)], answer="1,600 orders.")
    c = prod_client(provider, history_scope="client", cache_enabled=False)
    alice, bob = str(uuid.uuid4()), str(uuid.uuid4())
    rid = c.post("/api/query", json={"question": "How many orders?"},
                 headers={"X-Client-ID": alice}).json()["request_id"]
    c.post("/api/query", json={"question": "Bob's question"}, headers={"X-Client-ID": bob})

    mine = c.get("/api/history", headers={"X-Client-ID": alice}).json()
    assert [i["question"] for i in mine["items"]] == ["How many orders?"]
    assert c.get(f"/api/history/{rid}", headers={"X-Client-ID": alice}).status_code == 200
    assert c.get(f"/api/history/{rid}", headers={"X-Client-ID": bob}).status_code == 404
    assert c.get("/api/history").json()["total"] == 0  # no ID -> sees nothing
    assert c.get("/api/analytics").json()["total_requests"] == 2  # aggregates stay global


def test_raw_client_id_is_never_stored(prod_client, make_settings):
    provider = ScriptedProvider([sql_reply(COUNT)], answer="ok")
    c = prod_client(provider, history_scope="client")
    raw = str(uuid.uuid4())
    c.post("/api/query", json={"question": "How many orders?"}, headers={"X-Client-ID": raw})
    stored = c.app.state.container.history.all()[0].client_id
    assert stored and stored != raw and len(stored) == 64


# ---------- daily spend caps ----------
def test_daily_request_cap_blocks_new_llm_calls_but_not_cache(prod_client):
    provider = ScriptedProvider([sql_reply(COUNT), sql_reply(COUNT)], answer="1,600 orders.")
    c = prod_client(provider, daily_llm_request_limit=1)
    assert c.post("/api/query", json={"question": "How many orders?"}).status_code == 200
    blocked = c.post("/api/query", json={"question": "Count all orders please"})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "daily_limit_reached"
    # The already-answered question is served from cache at no cost.
    again = c.post("/api/query", json={"question": "How many orders?"})
    assert again.status_code == 200 and again.json()["cache"]["hit"] is True


def test_daily_cost_cap(prod_client):
    provider = ScriptedProvider([sql_reply(COUNT)], answer="ok", tokens=(400_000, 100_000))
    c = prod_client(provider, daily_cost_limit_usd=0.50)  # first call costs ~$1.8 (est.)
    assert c.post("/api/query", json={"question": "How many orders?"}).status_code == 200
    assert c.post("/api/query", json={"question": "Another question"}).status_code == 429


def test_caps_do_not_apply_to_the_offline_mock(prod_client, make_settings):
    with TestClient(create_app(make_settings(daily_llm_request_limit=1))) as c:
        for _ in range(3):
            r = c.post("/api/query", json={"question": "What is our total revenue?", "use_cache": False})
            assert r.status_code == 200


# ---------- schema migration ----------
def test_old_history_database_gets_new_column(tmp_path):
    path = tmp_path / "old_meta.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE request_logs (request_id VARCHAR(36) PRIMARY KEY, created_at DATETIME, "
        "question TEXT, status VARCHAR(20), error_code VARCHAR(64), error_message TEXT, "
        "error_category VARCHAR(32), final_sql TEXT, explanation TEXT, answer TEXT, attempts JSON, "
        "tables_used JSON, assumptions JSON, row_count INTEGER, retry_count INTEGER, "
        "llm_calls INTEGER, provider VARCHAR(32), model VARCHAR(64), input_tokens INTEGER, "
        "output_tokens INTEGER, estimated_cost_usd FLOAT, cost_status VARCHAR(20), "
        "generation_ms FLOAT, db_ms FLOAT, total_ms FLOAT, cache_hit BOOLEAN)"
    )
    conn.commit()
    conn.close()
    HistoryService(create_metadata_engine(f"sqlite:///{path}"))
    columns = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(request_logs)")}
    assert "client_id" in columns


# ---------- PostgreSQL ----------
def _log(**kw) -> RequestLog:
    base = dict(request_id=str(uuid.uuid4()), created_at=datetime.now(timezone.utc), question="q",
                status="success", attempts=[{"number": 1}], tables_used=["orders"], assumptions=[],
                retry_count=0, llm_calls=2, provider="anthropic", model="m", input_tokens=10,
                output_tokens=5, estimated_cost_usd=0.01, cost_status="estimated",
                generation_ms=1.0, db_ms=1.0, total_ms=2.0, cache_hit=False, client_id="abc")
    base.update(kw)
    return RequestLog(**base)


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_history_backends(backend, tmp_path):
    if backend == "postgres":
        url = os.environ.get("QP_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("set QP_TEST_POSTGRES_URL to run against PostgreSQL")
        url = Settings(metadata_database_url=url).metadata_database_url
    else:
        url = f"sqlite:///{tmp_path / 'meta.db'}"
    history = HistoryService(create_metadata_engine(url))
    history.clear()
    history.record(_log(question="mine"))
    history.record(_log(question="cached", llm_calls=0, estimated_cost_usd=0.0, cache_hit=True))
    history.record(_log(question="other", client_id="xyz"))

    items, total = history.list(client_id="abc", search="MIN")  # case-insensitive search
    assert total == 1 and items[0].question == "mine"
    assert items[0].attempts == [{"number": 1}]  # JSON round-trips
    assert items[0].created_at.tzinfo is not None or backend == "sqlite"
    count, cost = history.usage_today()
    assert count == 2 and cost == pytest.approx(0.02)  # cache hit (0 LLM calls) not counted
    history.clear()


# ---------- resilience ----------
def test_unreachable_history_db_degrades_instead_of_crashing(make_settings):
    settings = make_settings(metadata_database_url="postgresql://nobody@127.0.0.1:1/missing")
    with TestClient(create_app(settings, provider=ScriptedProvider([sql_reply(COUNT)], answer="ok"))) as c:
        health = c.get("/api/health").json()
        assert health["status"] == "degraded" and health["history_storage"] == "temporary"
        assert c.post("/api/query", json={"question": "How many orders?"}).status_code == 200


def test_daily_caps_fail_closed_when_usage_cannot_be_read(prod_client, monkeypatch):
    c = prod_client(ScriptedProvider([sql_reply(COUNT)], answer="ok"), daily_llm_request_limit=5)

    def broken():
        raise RuntimeError("database down")

    monkeypatch.setattr(c.app.state.container.history, "usage_today", broken)
    r = c.post("/api/query", json={"question": "How many orders?"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "usage_unavailable"
