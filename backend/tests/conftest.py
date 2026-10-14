"""Shared fixtures.

The environment is configured BEFORE the app is imported so tests never touch
the developer's real database, history file or API keys.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="querypilot-tests-"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{_TMP / 'business.db'}",
        "METADATA_DATABASE_URL": f"sqlite:///{_TMP / 'meta.db'}",
        "LLM_PROVIDER": "mock",
        "ANTHROPIC_API_KEY": "",
        "OPENAI_API_KEY": "",
        "RATE_LIMIT_PER_MINUTE": "1000",
    }
)

from app.db.seed import build_database  # noqa: E402

build_database(_TMP / "business.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.db.database import create_readonly_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.schema_service import inspect_schema  # noqa: E402
from tests.fakes import ScriptedProvider  # noqa: E402

APPROVED = ["customers", "products", "orders", "order_items"]


@pytest.fixture(scope="session")
def business_db_url() -> str:
    return os.environ["DATABASE_URL"]


@pytest.fixture(scope="session")
def engine(business_db_url):
    return create_readonly_engine(business_db_url)


@pytest.fixture(scope="session")
def schema(engine):
    return inspect_schema(engine, APPROVED)


@pytest.fixture
def make_settings(tmp_path, business_db_url):
    def _make(**overrides) -> Settings:
        values = {
            "database_url": business_db_url,
            "metadata_database_url": f"sqlite:///{tmp_path / 'meta.db'}",
            "llm_provider": "mock",
            "anthropic_api_key": None,
            "openai_api_key": None,
            "rate_limit_per_minute": 1000,
            "answer_mode": "llm",
        }
        values.update(overrides)
        return Settings(**values)

    return _make


@pytest.fixture
def provider() -> ScriptedProvider:
    return ScriptedProvider(answer="Grounded answer from rows.")


@pytest.fixture
def client(make_settings, provider):
    app = create_app(make_settings(), provider=provider)
    with TestClient(app) as test_client:
        test_client.provider = provider  # type: ignore[attr-defined]
        yield test_client
