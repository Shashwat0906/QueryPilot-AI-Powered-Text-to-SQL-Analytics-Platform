# Deploying QueryPilot (Vercel + Render)

```
Browser ──HTTPS──▶ Vercel (static React build, CDN)
   │
   └──HTTPS + CORS──▶ Render web service (FastAPI in Docker)
                          ├── business.db  SQLite, rebuilt read-only on every start
                          └── history      Render Postgres (private network only)
                                  │
                                  └──▶ Anthropic API (Claude)
```

| Piece | Where | Config file |
|---|---|---|
| Frontend | Vercel project, root directory `frontend` | [`frontend/vercel.json`](../frontend/vercel.json) |
| API | Render web service, Docker | [`render.yaml`](../render.yaml), [`backend/Dockerfile`](../backend/Dockerfile) |
| History DB | Render Postgres | [`render.yaml`](../render.yaml) |
| CI gate | GitHub Actions | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) |

## Design decisions

- **The browser calls Render directly (CORS), not through a Vercel rewrite.** A sleeping free Render service takes about a minute to wake; a proxy in between risks timing out, and it would hide the visitor's IP from the rate limiter.
- **The business database is not persisted on purpose.** It is read-only sample data generated deterministically (seed 42) in under a second, so the container rebuilds it on every start. Nothing to back up, nothing to corrupt.
- **Only history needs persistence**, and Render's free web services have an ephemeral disk that is wiped on every restart and every 15-minute sleep. History therefore lives in Render Postgres.
- **The API key lives only on Render.** The frontend has no secrets; `VITE_API_BASE_URL` is public by design.

## Production safeguards in the code

| Risk | Safeguard | Setting |
|---|---|---|
| Strangers spending your Claude credits | Hard daily caps across all visitors, counted from the persisted history (survive restarts); cache hits stay free | `DAILY_LLM_REQUEST_LIMIT=100`, `DAILY_COST_LIMIT_USD=1.00` |
| One visitor hammering the API | Per-client rate limit | `RATE_LIMIT_PER_MINUTE=10` |
| Visitors seeing each other's questions | Each browser gets an anonymous random ID; history is filtered by its SHA-256 hash; other IDs get 404 | `HISTORY_SCOPE=client` |
| Other websites calling the API from a browser | CORS allow-list (exact origins, optional regex for previews) | `CORS_ORIGINS`, `CORS_ORIGIN_REGEX` |
| Clickjacking, MIME sniffing, downgrade | `X-Frame-Options`, `nosniff`, HSTS (API); CSP + same on Vercel | `ENVIRONMENT=production` |
| Leaked credentials | Key only in Render's dashboard (`sync: false`); logs print the DB dialect only; errors never contain stack traces | — |
| Direct database access | Postgres `ipAllowList: []` = private network only | `render.yaml` |
| Broken code reaching production | Render deploys only after GitHub Actions passes | `autoDeployTrigger: checksPass` |
| History database gone (e.g. expired free Postgres) | API starts anyway with temporary history and reports `degraded`; caps fail closed | — |

These were verified locally in a production-like run: the Docker image with `PORT=10000` and `ENVIRONMENT=production`, history in PostgreSQL 16, and the frontend served with the exact `vercel.json` headers from a different origin. The results were zero CSP violations, CORS allowing only the configured origin, private history, the rate limit enforced, and no secrets in logs.

Honest limits: CORS doesn't stop scripts (the caps do); the browser ID is not a login (anyone with the ID can read that history); the rate limiter is per process (one instance is fine).

## Accounts you need

| Account | Plan | What for | Card needed? |
|---|---|---|---|
| GitHub | existing | Source repo + CI (Actions is free for public repos; private repos get a monthly free allowance) | No |
| [Vercel](https://vercel.com/signup) | Hobby (free) | Frontend. Hobby is for **personal, non-commercial** use, which fits a portfolio | No |
| [Render](https://dashboard.render.com/register) | Hobby workspace (free) | API + Postgres | Not for free instances |
| [Anthropic Console](https://console.anthropic.com) | Pay-as-you-go | Claude API key | Yes, prepaid credits |

Sign in to Vercel and Render **with GitHub** so they can see the repository.

## Expected costs

Prices checked 14 Oct 2026 (USD); verify on [render.com/pricing](https://render.com/pricing) and [vercel.com/pricing](https://vercel.com/pricing) before upgrading.

| Option | Vercel | Render web | Render Postgres | Hosting total | Trade-off |
|---|---|---|---|---|---|
| **A. Free (default in `render.yaml`)** | $0 | Free | Free | **$0** | Sleeps after 15 idle min (~1 min cold start); 750 instance hours/month; **free Postgres expires after 30 days** (14-day grace, then deleted) |
| B. Persistent history | $0 | Free | Basic 256 MB `0.1c-256mb`: $6/mo + $0.30/GB | **≈ $6.30/mo** | Still sleeps; history kept permanently |
| C. Always on | $0 | Starter `0.5c-512mb`: $7/mo | $6/mo + storage | **≈ $13.30/mo** | No cold starts |

**Claude API** (separate, pay-as-you-go), `claude-sonnet-5-5` at $2 / $10 per million input / output tokens. These are estimates from measured prompt sizes:

| | Tokens (in / out) | Cost |
|---|---|---|
| Typical question (generate + answer) | ≈ 2,000 / 330 | ≈ $0.007 |
| Worst case (2 corrections + answer) | ≈ 5,600 / 830 | ≈ $0.02 |
| Repeated question (cache hit) | 0 | $0 |
| **Hard ceiling with the default caps** | | **$1/day ≈ $30/month max** |

Realistic portfolio traffic (a few dozen questions a month) costs well under $1. Set a monthly spend limit in the Anthropic Console as a second safety net. For cheaper runs use `ANTHROPIC_MODEL=claude-haiku-5-5` ($0.10 / $0.50 per MTok); measure accuracy with `python -m scripts.evaluate` first.

## Step-by-step

Nothing below happens automatically from this repository; each step is something you click.

### 1. Push the code (after review)
Commit and push to `main`. GitHub Actions runs the backend tests (including PostgreSQL) and the frontend checks. Wait for green.

### 2. Get an Anthropic API key
Console → **Billing**: add credits and **set a monthly spend limit**. Console → **API Keys** → create a key named `querypilot-render`. Keep it for step 3; never commit it.

### 3. Deploy the API on Render
1. Dashboard → **New → Blueprint** → select the `QueryPilot-AI-Powered-Text-to-SQL-Analytics-Platform` repo.
2. Render reads `render.yaml` and shows `querypilot-api` + `querypilot-db`. It asks for:
   - `ANTHROPIC_API_KEY`: paste the key.
   - `CORS_ORIGINS`: enter `https://placeholder.invalid` for now (fixed in step 5).
3. **Apply**. The first build takes a few minutes. When done, note the URL, e.g. `https://querypilot-api.onrender.com`.
4. Check: open `https://<your-api>.onrender.com/api/health`. Expect `"status":"ok"` and `"llm_configured":true`.

### 4. Deploy the frontend on Vercel
1. **Add New → Project** → import the same repo.
2. **Root Directory: `frontend`**. Framework is detected as Vite; build settings come from `vercel.json`.
3. Environment variable `VITE_API_BASE_URL` = your Render URL (no trailing slash), for Production and Preview.
4. **Deploy**. Note the URL, e.g. `https://querypilot.vercel.app` (pick the project name you want in the URL).

### 5. Connect them (CORS)
Render → `querypilot-api` → **Environment** → set `CORS_ORIGINS` to the exact Vercel URL, e.g. `https://querypilot.vercel.app`. Optional, for preview deployments: `CORS_ORIGIN_REGEX=^https://querypilot-[a-z0-9-]+-<your-vercel-team>\.vercel\.app$`. Save; Render redeploys.

### 6. Verify the live site
- [ ] Open the Vercel URL. The status dot reads "Claude connected" (after the wake-up notice if it was asleep).
- [ ] Click an example question: answer, SQL, chart and table appear.
- [ ] Ask your own question, e.g. "How many orders were cancelled?" (expected answer: 104).
- [ ] History shows your questions; a private/incognito window shows none.
- [ ] Settings shows "Daily limit: 100 new questions, or $1.00".
- [ ] Browser devtools console: no Content-Security-Policy errors.
- [ ] Analytics shows real token counts and estimated cost per question. Compare with the estimates above.
- [ ] Optional, rate-limit client IP: with `CLIENT_IP_HEADER` empty, Render's proxy is the connecting address, so the per-minute limit is shared by all visitors (conservative). Render's documentation of client-IP headers is thin; per-visitor limits would mean setting `CLIENT_IP_HEADER` to a header Render's edge sets and clients can't forge, confirmed by testing. The daily caps protect cost either way.

### 7. Before day 30 (free Postgres only)
Render emails before the free database expires. Before the 14-day grace period ends, either upgrade it to `0.1c-256mb` (option B, history kept) or create a new free database and point `METADATA_DATABASE_URL` at it (history starts empty).

If the database disappears without either, the API **keeps running**. It falls back to temporary in-memory history; `/api/health` reports `"status": "degraded", "history_storage": "temporary"`, and the status dot turns amber. If the daily caps can't be checked at runtime, new LLM questions are refused rather than allowed to run uncapped.

## Operating it

- **Logs**: Render → service → Logs (each request logs its ID, status, retries, rows, latency, cost).
- **Raise or lower caps**: change `DAILY_LLM_REQUEST_LIMIT` / `DAILY_COST_LIMIT_USD` on Render; they apply after the automatic redeploy.
- **Rotate the API key**: create a new key in the Anthropic Console, paste it into Render, then delete the old one.
- **Roll back**: Render → Deploys → pick a previous deploy → Rollback. Vercel → Deployments → Promote to Production.
- **Pause everything**: Render → Suspend service; Vercel → Settings → Pause, or delete the project.
- **Local development is unchanged**: `uvicorn` + `npm run dev`, or `docker compose up`.
