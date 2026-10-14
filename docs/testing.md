# Testing and evaluation

## Status at a glance

| Check | Command | Result (2026-10-14) |
|---|---|---|
| Backend tests | `cd backend && python -m pytest` | **217 passed** in ~4 s (including PostgreSQL 16 history tests when `QP_TEST_POSTGRES_URL` is set) |
| Production simulation | Docker image with `PORT=10000`, `ENVIRONMENT=production`, Postgres history; frontend served with the `vercel.json` headers from another origin | No CSP violations; CORS, private history, rate limit and caps verified in a browser; no secrets in logs |
| Frontend type check | `cd frontend && npm run typecheck` | Passes (TypeScript strict mode) |
| Frontend lint | `npm run lint` | Passes with warnings treated as errors |
| Frontend build | `npm run build` | Passes; main bundle 290 KB (93 KB gzip), charts lazy-loaded |
| Docker | `docker compose up` | Stack healthy; UI, `/api` proxy, SPA routes, per-client rate limit and history persistence verified in a browser through nginx (see note below) |
| Fault-injection evaluation | `python -m scripts.fault_injection` | **37 of 39** realistic LLM mistakes caught and corrected — see below |
| Evaluation, mock provider | `python -m scripts.evaluate --provider mock` | 7/14 answered, **all 7 correct**, 0 wrong answers — see below |
| Evaluation, Claude | `python -m scripts.evaluate` | **Not yet run** (no API key in the build environment) |

No test needs an API key or makes a network call. LLM behaviour is simulated with `ScriptedProvider` (`backend/tests/fakes.py`), which returns pre-defined replies in order and records the prompts it receives, and HTTP providers are tested with `httpx.MockTransport`. Each test run builds a fresh seeded database in a temporary directory (`tests/conftest.py`).

*Docker note:* the images were first built from scratch with `docker compose up --build`. In the final review pass Docker Hub rate-limited the build sandbox, so the reviewed code, CMD and nginx config were layered onto those already-built images and the stack re-tested. No dependency or build step changed in that pass.

## What is tested

| File | Tests | Covers |
|---|---|---|
| `test_sql_validator.py` | 51 | Valid SELECT/CTE/recursive CTE/UNION/window/subquery; rejection of every write/DDL/admin statement, writes inside CTEs, `SELECT INTO`, multiple statements, internal and unapproved tables, dangerous functions; unknown tables/columns are *recoverable*; **wrong categorical values** (`'Completed'`, `'refund'`, `'Bangalore'`) are caught |
| `test_canonical_sql.py` | 31 | The SQL re-rendered by the validator returns **identical rows** to the original for every reference query plus SQLite-specific constructs (integer division, `\|\|`, LIKE/GLOB, date modifiers, window frames, `EXCEPT`, `NULLS LAST`, …) |
| `test_result_checks.py` | 20 | Detecting how many items a question asks for ("top five", "which two", a singular "which segment … the most") without misreading "last six months" or "more than 3 items"; the revenue business-rule check and its exemptions |
| `test_retry_service.py` | 14 | Success, recovery from validator/database errors, exhaustion after exactly 3 attempts, security violations never retried, malformed JSON, unanswerable, provider outage; **too many rows corrected**, warning on the last attempt, **wrong value corrected before execution**, **revenue rule enforced** |
| `test_query_executor.py` | 11 | Column types, row cap, empty results, timeout, the authorizer blocking unsafe SQL even without the validator, sanitized errors, read-only connection |
| `test_cache_service.py` | 11 | Hit/miss, copies, normalization, key changes with database/schema/model/row limit/scope/**prompt version/answer mode**, TTL, LRU, schema invalidation, sensitive columns, disabled, clear |
| `test_llm_providers.py` | 19 | Response parsing, Anthropic forced tool use + usage, OpenAI JSON mode, safe error messages, grounded answers; the mock **refuses constraints it can't apply** and **honours requested numbers** |
| `test_api.py` | 15 | All endpoints, error envelopes, cache flow, history, analytics, no secrets in config, rate limit, mock end to end, **row-limit warning** |
| `test_cost_and_analytics.py` | 6 | Cost over every call, unavailable ≠ $0, analytics aggregation |
| `test_production.py` | 18 | Comma-separated/JSON env lists, `postgres://` URLs, client IP from the last trusted proxy hop, CORS allow-list and preview regex, security headers/HSTS, docs toggle, per-browser history isolation and hashed IDs, daily request and cost caps (cache hits exempt, mock exempt, fail closed), schema migration of an old history DB, history on SQLite **and real PostgreSQL**, startup with an unreachable history DB |
| `test_evaluation.py` | 21 | Reference SQL valid, comparator rules, **reference answers recomputed independently in Python**, fault injection catches all mechanical mistakes |

Frontend: no automated UI test suite. The UI is checked by type-checking, linting, building, and browser screenshots of all 7 pages (desktop, collapsed sidebar, 390 px mobile) with no console errors.

## Is the expected answer itself right?

`backend/eval/dataset.json` has 14 questions, each with hand-written reference SQL. During the review every expected answer was **recomputed in plain Python from raw rows** (no SQL aggregation): all 14 agree, and there are no ties at any "top N" boundary, so each ranking has one correct answer. A test keeps the three most error-prone ones (total revenue, units in completed orders, cancelled orders) checked permanently.

One finding: the exact decimal total revenue is **455,614.725**, exactly on a half cent. SQLite has no decimal type, so money is stored as floating point and `ROUND(…, 2)` returns 455,614.72, while decimal half-up rounding gives .73. Results are compared with a one-cent tolerance for this reason.

## Why queries ran but returned wrong answers

The first mock evaluation had **2 questions that executed without error but returned wrong answers**. Root cause in both: keyword matching that dropped constraints from the question.

| Question | What went wrong |
|---|---|
| "…the **five** customers who placed the most orders, with their **customer IDs**" | Rule ignored N (returned 10 rows) and omitted the requested IDs |
| "How many **units** … sold in **completed** orders?" | "category" triggered the revenue rule: wrong measure, and the revenue status filter instead of `status = 'completed'` (1,476 units vs the correct 1,446) |

The same failure class — a valid query that silently answers a slightly different question — is the main risk with a real LLM too. The review added checks so that whole classes of these mistakes are detected and corrected, not just the two examples:

1. **Categorical value check** (`sql_validator._validate_categorical_literals`): a string compared with a small categorical column must be one of its real values. Catches `'Completed'`, `'refund'`, `'Bangalore'`, which otherwise run and return 0 rows or inflate totals.
2. **Business-rule check** (`result_checks.check_revenue_rule`): revenue computed without the order-status rule is sent back for correction instead of silently counting refunds.
3. **Result-shape check** (`result_checks.check_row_count`): more rows than the question asked for ("top five", "which segment … the most") triggers a correction; on the last attempt the result is kept with a visible warning.
4. **Prompt rules** (`sql_generator.SYSTEM_PROMPT`, version 2): honour every constraint, never substitute a metric, explicit filters override default rules, return identifiers for rankings. Can't be unit-tested without a real model.
5. **Mock provider** (`mock-rules-v2`): rules declare which constraints they can apply; anything else means "not answerable" rather than a guess. Requested N and "last N months" are honoured.

## Fault-injection evaluation (measures the safety net)

`backend/scripts/fault_injection.py` takes each correct reference query, injects one realistic LLM mistake, and plays it through the real retry loop as the model's first answer. A fake model returns the correct query only if the pipeline asks for a correction. Results are in [`backend/eval/results/fault-injection.md`](../backend/eval/results/fault-injection.md).

Same script, same mistakes, run against the code before and after the review:

| Mistake injected | Cases | Caught before | Caught after | Detected by |
|---|---|---|---|---|
| Categorical value in the wrong case (`'Completed'`) | 9 | 0 | **9** | `unknown_value` |
| Near-miss categorical value (`'refund'`, `'complete'`) | 9 | 0 | **9** | `unknown_value` |
| Misspelled column (`quantity` → `qty`) | 8 | 8 | 8 | `unknown_column` |
| Forgot the revenue status rule | 7 | 0 | **7** | `business_rule_violation` |
| Ignored the requested number of rows | 4 | 0 | **4** | `row_count_mismatch` |
| Off-by-one date range | 1 | 0 | 0 | — |
| Counted rows instead of summing units | 1 | 0 | 0 | — |
| **Mistakes that changed the answer** | | **8 of 36 (22%)** | **37 of 39 (95%)** | |

(Before the review, 3 injected mistakes happened to produce the same rows; after it, those are caught before execution, hence 36 vs 39.)

The two misses are purely semantic: the query is valid, uses real values and follows the rules, but means something slightly different. Detecting those requires knowing the user's intent; this is exactly what the real-model evaluation is for.

## Evaluation with the mock provider

| Metric | Before review | After review |
|---|---|---|
| Questions answered | 8 / 14 | 7 / 14 |
| Correct results | 6 / 14 (43%) | **7 / 14 (50%)** |
| **Executed but wrong** | **2** | **0** |
| Correct among answered | 75% | **100%** |

The mock only has rules for the seven example questions, so 50% is its coverage ceiling on this dataset, not an accuracy figure. Rules were deliberately **not** added for the other evaluation questions: that would train the mock on the test and make the number meaningless. Full output: [`backend/eval/results/mock-sample.md`](../backend/eval/results/mock-sample.md).

How results are compared (`scripts/evaluate.py` → `results_match`): equal row counts; each compared expected column must match some returned column by value (names may differ, extra columns allowed); rows are then compared as tuples so values stay paired; numbers within $0.011 or 1e-6 relative.

### To measure Claude

```bash
cd backend && source .venv/bin/activate
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
python -m scripts.evaluate
```

Writes `eval/results/anthropic-<timestamp>.md/.json`. Until this is run, **no accuracy figure for Claude should be claimed.**

## Running everything

```bash
cd backend && source .venv/bin/activate
python -m pytest
python -m scripts.fault_injection
python -m scripts.evaluate --provider mock

cd ../frontend
npm run typecheck && npm run lint && npm run build
```
