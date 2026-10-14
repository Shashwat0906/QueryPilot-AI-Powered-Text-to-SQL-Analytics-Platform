"""Application configuration.

All settings come from environment variables (or a local `.env` file) so that
secrets such as API keys never live in source code. `Settings` is a Pydantic
model, which means every value is type-checked when the app starts.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]

# USD per one million tokens: (input, output). These are *estimates* used for
# cost tracking only. Override with the MODEL_PRICING_JSON environment variable
# when prices change. Source: Anthropic pricing page (checked Oct 2026).
DEFAULT_MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-fable-5-1": {"input": 10.0, "output": 50.0},
    "claude-opus-5-5": {"input": 4.0, "output": 20.0},
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0},
    # Haiku 5.5 is tiered; this is the rate for prompts up to 100K tokens,
    # which covers every QueryPilot prompt (they are a few thousand tokens).
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50},
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env", BACKEND_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "QueryPilot"
    environment: Literal["development", "production", "test"] = "development"

    # --- Databases -------------------------------------------------------
    # The business database that users ask questions about (opened read-only).
    database_url: str = Field(default=f"sqlite:///{BACKEND_DIR / 'data' / 'business.db'}")
    # QueryPilot's own writable database for request history / metrics.
    # SQLite locally; in production point it at PostgreSQL (e.g. Render
    # Postgres) so history survives restarts. postgres:// URLs are accepted.
    metadata_database_url: str = Field(
        default=f"sqlite:///{BACKEND_DIR / 'data' / 'querypilot_meta.db'}"
    )
    # Tables the model is allowed to see and query. Empty = all user tables.
    approved_tables: Annotated[list[str], NoDecode] = ["customers", "products", "orders", "order_items"]

    # --- LLM ---------------------------------------------------------------
    # "auto" picks anthropic if ANTHROPIC_API_KEY is set, else openai if
    # OPENAI_API_KEY is set, else the offline mock provider.
    llm_provider: Literal["auto", "anthropic", "openai", "mock"] = "auto"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_base_url: str = "https://api.anthropic.com"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = 45.0
    llm_max_output_tokens: int = 1024
    model_pricing_json: str | None = None  # JSON override for DEFAULT_MODEL_PRICING
    # "llm" asks the model to summarise the real rows; "template" builds the
    # answer deterministically without an extra LLM call.
    answer_mode: Literal["llm", "template"] = "llm"
    answer_preview_rows: int = 20

    # --- Execution limits ---------------------------------------------------
    max_result_rows: int = 500
    query_timeout_seconds: float = 5.0
    max_correction_attempts: int = Field(default=2, ge=0, le=2)
    max_question_length: int = 500
    schema_sample_values: int = 12  # list distinct values for low-cardinality text cols

    # --- Cache --------------------------------------------------------------
    cache_enabled: bool = True
    cache_ttl_seconds: int = 600
    cache_max_entries: int = 256
    # Results that include any of these column names are never cached.
    cache_sensitive_columns: Annotated[list[str], NoDecode] = ["email", "phone", "password", "ssn"]

    # --- API ----------------------------------------------------------------
    # Exact origins allowed to call the API from a browser (comma-separated).
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # Optional regex for extra origins, e.g. Vercel preview deployments:
    # ^https://querypilot-[a-z0-9-]+-yourteam\.vercel\.app$
    cors_origin_regex: str | None = None
    rate_limit_per_minute: int = 30
    # Where the real client IP comes from, for per-client rate limiting.
    # Empty = the TCP peer (direct connections). Behind a proxy that sets a
    # header the client cannot forge, name it here, e.g. "X-Forwarded-For"
    # (our nginx overwrites it) or "CF-Connecting-IP". Only the LAST address in
    # the header is used, because proxies append to the right.
    client_ip_header: str = ""
    enable_api_docs: bool = True

    # --- Spend protection (public deployments) ----------------------------
    # Hard daily caps across ALL visitors, counted from the persisted request
    # log, so they survive restarts. 0 = no cap. Only apply to a real LLM.
    daily_llm_request_limit: int = 0
    daily_cost_limit_usd: float = 0.0

    # --- History privacy ----------------------------------------------------
    # "all": everyone sees all history (fine for local use).
    # "client": each browser only sees its own questions (anonymous ID sent by
    # the frontend). Not authentication - see docs/deployment.md.
    history_scope: Literal["all", "client"] = "all"

    @field_validator("approved_tables", "cache_sensitive_columns", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        # Accept both CORS_ORIGINS=https://a.app,https://b.app and a JSON list.
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [item.strip() for item in text.split(",") if item.strip()]
        return value

    # --- Derived helpers ----------------------------------------------------
    @property
    def resolved_provider(self) -> str:
        if self.llm_provider != "auto":
            return self.llm_provider
        if self.anthropic_api_key and self.anthropic_api_key.get_secret_value():
            return "anthropic"
        if self.openai_api_key and self.openai_api_key.get_secret_value():
            return "openai"
        return "mock"

    @property
    def model_pricing(self) -> dict[str, dict[str, float]]:
        pricing = dict(DEFAULT_MODEL_PRICING)
        if self.model_pricing_json:
            pricing.update(json.loads(self.model_pricing_json))
        return pricing

    @field_validator("metadata_database_url", "database_url", mode="after")
    @classmethod
    def _normalise_postgres_url(cls, value: str) -> str:
        # Render and Heroku hand out postgres:// URLs; SQLAlchemy needs a driver.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def database_type(self) -> str:
        return self.database_url.split(":", 1)[0].split("+", 1)[0]


@lru_cache
def get_settings() -> Settings:
    return Settings()
