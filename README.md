# QueryPilot — AI-Powered Text-to-SQL Analytics Platform

Ask a business question in plain English. QueryPilot has an LLM (Claude by default) write **one read-only SQL query**, checks that query with a SQL parser, runs it on a **read-only** database connection, and answers using only the rows that came back. If the SQL fails for a fixable reason, the error is sent back to the model for a bounded number of corrections.

Every request shows the final SQL, the real result rows, each attempt the model made, the latency of each stage, the retry count, cache status, token usage and an estimated cost.

> Built as a full-stack AI engineering project: FastAPI + SQLAlchemy + sqlglot on the backend, React + TypeScript + Tailwind + Recharts on the frontend, 199 automated tests, an evaluation runner, a fault-injection evaluation, and Docker Compose for one-command local setup.

## Why this exists

Business data lives in relational databases, but getting answers out of them usually needs SQL. Non-technical people end up waiting for an analyst to answer questions like *"Which five products made the most revenue?"*. QueryPilot lets them ask directly — while treating everything the LLM writes as **untrusted input** that must be validated before it touches the database.

## Features

| Area | What it does |
|---|---|
| Natural-language querying | Schema-aware prompt → structured JSON from the LLM (SQL, explanation, tables, assumptions) |
| SQL safety | sqlglot parse tree checks (single statement, SELECT/CTE only, approved tables/columns, banned functions) **plus** a SQLite authorizer, read-only connection, timeout and row cap at runtime |
| Self-correction | Up to 2 corrections after the first attempt for syntax/schema errors; security violations are never retried |
| Wrong-answer checks | Catches queries that *run* but answer the wrong question: categorical values that don't exist (`'Completed'`, `'refund'`), revenue computed without the business rule, more rows than the question asked for |
| Grounded answers | The answer sentence is written only from returned rows; empty results say "No matching records were found." |
| Observability | Per-request ID, stage latencies, token usage, estimated cost (or *unavailable* — never invented), persisted history |
| Caching | Bounded LRU + TTL in-memory cache keyed by question, database, schema version, model and row limit |
| Analytics | Success rate, latency (avg/p95), retry rate, cache hit rate, tokens and cost — computed from real requests |
| Frontend | 7 pages: Ask, SQL viewer, Results explorer, Schema, Analytics, History, Settings. Responsive, dark, keyboard-accessible |
| Evaluation | 14 questions with independently verified answers; measures execution rate *and* correctness separately. A fault-injection run shows the pipeline catches 37 of 39 realistic LLM mistakes |

## Tech stack

- **Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, sqlglot (SQL parser), HTTPX
- **LLM:** Anthropic Claude Messages API (default `claude-sonnet-5-5`), any OpenAI-compatible API, or an offline mock
- **Database:** SQLite (default); connection layer prepared for PostgreSQL
- **Frontend:** React 19, Vite, TypeScript (strict), Tailwind CSS v4, Recharts, Lucide icons, React Router
- **Quality:** pytest (mocked LLM, no API key needed), oxlint, `tsc`, Docker + Docker Compose

## Architecture at a glance

```
Browser (React) ──/api──▶ FastAPI routes (thin)
                              │
                              ▼
                        QueryService ──▶ QueryCache (LRU+TTL)
                              │
                              ▼
                        RetryService ── loop (max 1 + 2 corrections)
                         │      │       │
              SQLGenerator  sql_validator  QueryExecutor ──▶ SQLite (read-only,
               │  (prompt)   (sqlglot AST)  (authorizer,        authorizer,
               ▼                             timeout, row cap)   query_only)
          LLMProvider (Claude / OpenAI / mock)
                              │
                              ▼
            AnswerService → cost_tracker → HistoryService (metadata SQLite)
```

Details and the request lifecycle: [docs/architecture.md](docs/architecture.md).

## Quick start (local, no Docker)

Requirements: Python 3.11+ and Node 20+.

```bash
# 1. Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env               # optional: add ANTHROPIC_API_KEY=...
python -m scripts.seed_database    # creates data/business.db (150 customers, 1,600 orders)
uvicorn app.main:app --reload --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev                        # http://localhost:5173
```

Open **http://localhost:5173**. API docs (Swagger) are at **http://localhost:8000/docs**.

## Quick start (Docker)

```bash
cp backend/.env.example backend/.env   # optional, add your API key
docker compose up --build
```

- App: **http://localhost:8080**
- API + Swagger: **http://localhost:8000/docs**

The backend container seeds the sample database on first start. The database and request history live in the `querypilot-data` volume (`docker compose down -v` resets them).

## Deploying (Vercel + Render)

The repository includes everything for a hosted demo: [`render.yaml`](render.yaml) (API in Docker + Postgres for history), [`frontend/vercel.json`](frontend/vercel.json) (static build with security headers) and a GitHub Actions CI gate. The default setup is $0 for hosting; LLM spend is capped at $1/day by default.

The step-by-step guide covers the accounts you need, the cost options, verification and rollback: [docs/deployment.md](docs/deployment.md).

## Configuring the LLM

QueryPilot reads credentials only from environment variables (`backend/.env`, which is git-ignored).

```bash
# backend/.env
ANTHROPIC_API_KEY=sk-ant-...        # get one at console.anthropic.com
ANTHROPIC_MODEL=claude-sonnet-5-5   # optional
```

With `LLM_PROVIDER=auto` (the default) the backend uses Claude if `ANTHROPIC_API_KEY` is set, otherwise an OpenAI-compatible API if `OPENAI_API_KEY` is set, otherwise the **offline mock provider**.

The mock provider is *not* an LLM: it recognises the seven example questions with small hand-written rules and returns pre-written SQL. If a question adds a condition the rule can't apply (a year, a status, a segment…), it says it can't answer rather than guessing. That SQL still goes through validation and runs against the real database, so results are genuine, and the UI labels it clearly as "Offline mock". It exists so the app and tests run without an API key. Any other question returns "not answerable" until a real key is configured.

See [`backend/.env.example`](backend/.env.example) for every setting (row limit, timeout, retry limit, cache TTL, rate limit, model prices).

## API

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Application and database health |
| GET | `/api/schema` | Approved schema: tables, columns, types, keys, relationships |
| POST | `/api/query` | Generate, validate and execute SQL for a question |
| GET | `/api/history` | Previous requests (filter by `status`, `search`; paginated) |
| GET | `/api/history/{request_id}` | One request with all attempts |
| GET | `/api/analytics` | Aggregated performance, retry, cache and cost metrics |
| GET | `/api/config` | Safe configuration (never secrets) |
| POST | `/api/cache/clear` | Empty the result cache |

```bash
curl -X POST http://localhost:8000/api/query \
  -H 'Content-Type: application/json' \
  -d '{"question": "Show the top five products by revenue."}'
```

Real request/response examples: [docs/api.md](docs/api.md).

## Tests and evaluation

```bash
cd backend && source .venv/bin/activate
python -m pytest                          # 217 tests, mocked LLM, ~4 s
QP_TEST_POSTGRES_URL=postgresql://… python -m pytest   # also run the PostgreSQL history tests
python -m scripts.fault_injection         # does the pipeline catch LLM mistakes?
python -m scripts.evaluate                # eval with the configured provider
python -m scripts.evaluate --provider mock

cd ../frontend
npm run typecheck && npm run lint && npm run build
```

What is tested and the measured results: [docs/testing.md](docs/testing.md).

## Project structure

```
backend/
  app/
    main.py              FastAPI app factory, request IDs, error envelopes
    api/routes.py        thin HTTP layer
    core/                config, errors, rate limiter, dependency container
    db/                  read-only engine, seed data, business notes
    models/              request log ORM model
    schemas/api.py       Pydantic request/response models
    services/            schema, LLM providers, generator, validator, executor,
                         retry, answer, cache, cost, history, analytics, query
  scripts/               seed_database.py, evaluate.py
  eval/                  dataset.json + sample results
  tests/                 pytest suite
frontend/
  src/
    pages/               the 7 pages
    components/          PipelineTrace, SqlBlock, ResultsTable, ResultChart, ...
    layouts/ hooks/ context/ services/ types/ utils/
docs/                    architecture, database, api, testing, interview prep
docker-compose.yml
```

## Limitations (honest list)

- **Real-LLM accuracy has not been measured in this repository yet.** All automated tests use a scripted fake LLM, and the committed evaluation run uses the mock provider. Run `python -m scripts.evaluate` with your API key to get real numbers.
- The cache, rate limiter and in-memory stats are **per process**: lost on restart, not shared across instances. History is persisted (SQLite locally, PostgreSQL when deployed).
- On a public deployment, history privacy uses an anonymous per-browser ID, not accounts: anyone holding a browser's ID can read that browser's history.
- The *business* database is SQLite. A PostgreSQL path for it exists in the connection layer and executor but is **not tested** (PostgreSQL *is* tested for the history database).
- No user accounts: the cache key has a `scope` slot for user/auth context, currently always `anonymous`.
- Answers in `llm` mode send up to 20 result rows to the LLM provider. Don't point QueryPilot at data you can't share with your provider.
- Purely semantic mistakes — a valid query with an off-by-one date range or the wrong aggregate — are not detected (2 of 39 in the fault-injection run). Only an evaluation against the real model can measure how often they happen.
- The wrong-answer checks are tuned to this schema: the revenue rule check is specific to this sales data, and value checks only cover small categorical columns (≤ 12 distinct values).
- SQLite stores money as floating point, so sums can differ from exact decimal arithmetic by a cent on half-cent boundaries.
- Column validation for unqualified columns is deliberately permissive inside complex nested queries; the database itself is the final check (its errors trigger a correction).

## Troubleshooting

| Problem | Fix |
|---|---|
| UI says "Backend offline" | Start the backend on port 8000, or set `VITE_API_PROXY_TARGET` for `npm run dev` |
| `Business database not found` | `cd backend && python -m scripts.seed_database` |
| Only the example questions work | You're in offline mock mode — add `ANTHROPIC_API_KEY` to `backend/.env` and restart |
| `LLM provider returned HTTP 401` | API key is wrong or revoked |
| `HTTP 404: model or endpoint not found` | Check `ANTHROPIC_MODEL` is a model your key can use |
| HTTP 429 from QueryPilot | Local rate limit (`RATE_LIMIT_PER_MINUTE`, default 30/min per client) |
| Docker ports only work on this machine | By design: compose binds 8080/8000 to `127.0.0.1`. Change the `ports:` entries to expose them |
| Port 8000/5173/8080 in use | Stop the other process or change the port in the command / `docker-compose.yml` |
| Reset everything | `rm backend/data/*.db && python -m scripts.seed_database` (Docker: `docker compose down -v`) |

## Documentation

- [Architecture and request lifecycle](docs/architecture.md)
- [Database schema and ER diagram](docs/database.md)
- [API reference with real examples](docs/api.md)
- [Testing and evaluation results](docs/testing.md)
- [Deployment guide: Vercel + Render](docs/deployment.md)
- [Interview preparation guide](docs/interview-preparation.md)
