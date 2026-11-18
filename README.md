# Smart Money Decoder

> Reads what proven smart money is doing on Polymarket — and tells you whether the signal itself can be trusted.

[![CI](https://github.com/LianCr/smart-money-decoder/actions/workflows/check.yml/badge.svg)](https://github.com/LianCr/smart-money-decoder/actions)

**Live demo — 2026 Midterms edition:** https://smart-money-decoder.onrender.com/?src=gh

Most Polymarket tools answer one of two questions. *"Who is buying what?"* — answered for free by a dozen whale trackers. *"Should I copy them?"* — structurally broken: copiers pay detection lag, worse fills, and routinely become exit liquidity for the very wallets they follow.

Smart Money Decoder answers the two harder questions:

1. **What does this move actually mean?**
2. **Can this signal — this price, this position — even be trusted?**

And it does something almost no tool in this space does: **it keeps score on itself, in public, with backfilling made impossible by code.**

---

## What it does

**🔍 Decode a wallet.** Paste any Polymarket address. SMD finds its largest political position and runs an adversarial adjudication — a bull case, a bear case, and a reasoner that rules between them — over a deterministic fact sheet (entry price, PnL, market reaction, catalyst timeline). Output: `market_lean` + `confidence` + a sourced rationale.

**🛡 Score the signal itself.** A deterministic credibility panel — pure code, zero LLM — rates whether the price can be trusted: liquidity tier, holder concentration, participation breadth, realized volatility. Prediction-market research keeps finding wash trading and settlement manipulation in the wild; most tools relay whale signals anyway. SMD treats *"is this bait?"* as a first-class question.

**📊 Keep an honest track record.** Every judgment is archived *before* the outcome is known. When markets settle, a replay loop grades direction only and publishes hit rates by confidence bucket. Where the sample is too small, the panel says **"insufficient sample"** — it will not show you a flattering percentage it can't defend.

---

## The honesty rules

These are enforced by code and tests, not by promises:

| Rule | Enforcement |
|---|---|
| **No backfill, ever** | Settled archives are frozen; any mutation path raises `ReplayIntegrityError`. Tests assert the judgment log is byte-identical before and after replay. |
| **Direction only** | Hits are graded on direction, never PnL. No cherry-picking winners by size. |
| **NO BASIS is an answer** | When the evidence doesn't support a call, that verdict is recorded and reported separately — not silently dropped. |
| **Guards on the live path** | Deterministic guards intercept LLM narrative before users see it: fabricated citations, hallucinated date math, fear-mongering language. Triggers are logged as `guard_flags` and cross-tabulated against hit rates. |
| **Determinism is labeled** | The scoring matrix and credibility scorer are pure code (`deterministic: true`). LLM output is labeled `deterministic: false`. The payload never pretends otherwise. |

The audit that shaped this codebase — 24 findings, severity-ranked, with a live progress board — is public in [`AUDIT.md`](./AUDIT.md). The project practices the auditability it preaches.

---

## Why it exists

The Polymarket tooling ecosystem has 170+ products crowded into three lanes: whale alerts (commoditized), copy-trading bots (adversely selected by design), and AI predictors advertising accuracy numbers nobody can check. SMD's bets are the gaps between the lanes: **interpretation over alerts, auditability over claims, and signal-trust as a feature** — the one lane research validates and almost nobody builds.

Backtest on 94 settled political markets showed roughly a 10-point directional lift over coin-flip baseline; methodology and samples live in [`backtest/`](./backtest/). Treat it as promising, not proven — the public calibration panel is the ongoing, un-fakeable version of that claim.

---

## Engineering

This project started as an AI-assisted prototype — and then was rebuilt into something maintainable, deliberately and on the record:

- **A full audit first** (24 findings), then a phased hardening campaign across 17 PRs: atomic writes everywhere, CI that passes on a keyless clean clone, request-scoped logging, a router split that killed import side effects, registry-driven cache invalidation, and a single-source constants module where re-introducing a magic number turns a test red.
- **45 test files** (947 assertions on the last run, all keyless), including endpoint three-state tests, guard positive/negative pairs, and byte-hash immutability checks on the judgment log.
- **Honest failure modes**: missing keys fail loud at `/healthz` instead of half-working; the frontend never shows "failed" while the backend is still building.
- **SQL analytics over the judgment archive**: [`analytics/schema.sql`](./analytics/schema.sql) models the JSON archives as 4 relational tables; [`analytics/views.sql`](./analytics/views.sql) defines 6 views (row-level hit/miss status, scorecard summary, hit rate by confidence and by call, wallet activity, market lean drift with window functions). Served read-only at `GET /analytics` and shown on the Track Record page. Tests assert the SQL scorecard equals the Python `compute_scorecard()` on the real archive, and CI runs the same SQL on SQLite and PostgreSQL 16.
- **Docs**: [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) (mermaid system + request diagrams), [`docs/RUNBOOK.md`](./docs/RUNBOOK.md) (failure modes this project actually hit, with check / fix / verify).

Stack: FastAPI · React/Vite · Claude (adversarial adjudication) · Polymarket public Data API v2 / Gamma / CLOB (no key) · deterministic scoring core.

---

## Quickstart

```bash
git clone https://github.com/LianCr/smart-money-decoder.git
cd smart-money-decoder
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
(cd frontend && npm install)
bash scripts/check.sh       # full test suite + frontend build — passes with zero keys
cp .env.example .env        # fill in the required keys (the server needs them; the tests don't)
(cd frontend && npm run build)                 # dist/ is rebuilt per deploy, not committed
.venv/bin/uvicorn api.main:app --port 8000     # open http://localhost:8000
```

Deployment contract (Render blueprint, required keys, health checks) is documented in [`DEPLOY.md`](./DEPLOY.md). Without keys the service starts, serves cached boards, and reports exactly what's missing — it does not pretend to work.

---

## Integrations & API

### What SMD calls (outbound)

| Service | Used for | Key | If it fails |
|---|---|---|---|
| Polymarket **Data API v2** (`data-api.polymarket.com`) | trades, holders, open interest, PnL history, leaderboards | none | transient errors retried (429 backoff); `/healthz` only warns, cached boards keep serving |
| Polymarket **Gamma** (`gamma-api.polymarket.com`) | market metadata, settlement (winner from `outcomePrices`), election / theme markets | none | theme panels return empty instead of erroring the page |
| Polymarket **CLOB** (`clob.polymarket.com`) | current order book snapshot | none | panel left empty (no historical book exists, so none is invented) |
| **Anthropic Messages API** | bull / bear / reasoner adjudication, translation | `ANTHROPIC_API_KEY` (required) | uncached wallets return `502`; `/healthz` returns `503` |
| **Tavily** | news retrieval inside the catalyst window | `TAVILY_API_KEY` (required) | news panel degrades; `/healthz` returns `503` if the key is missing |
| **GitHub** (contents API + raw) | persists refreshed boards / scorecard to the `app-state` branch across ephemeral redeploys | `GITHUB_TOKEN` (optional) | falls back to the git-tracked `seed/` snapshot on cold start |
| **Redis** | cross-instance single-flight for board rebuilds | `REDIS_URL` (optional) | falls back to in-process single-flight |

The Polymarket adapter ([`fetcher/pm_backend.py`](./fetcher/pm_backend.py)) translates the public APIs into the record shapes the rest of the code already used, so the switch from the retired paid provider (Heisenberg, still selectable with `DATA_BACKEND=heisenberg`) changed no call sites. Field contracts are pinned in [`tests/test_pm_backend.py`](./tests/test_pm_backend.py).

### What SMD exposes (inbound)

FastAPI, auto-generated **OpenAPI 3.1**: interactive docs at [`/docs`](https://smart-money-decoder.onrender.com/docs), schema at [`/openapi.json`](https://smart-money-decoder.onrender.com/openapi.json). 13 routes:

| Route | What it returns | Cost |
|---|---|---|
| `GET /healthz` | real liveness: required keys present, data-layer probe, cache dirs writable (`200` / `503`, booleans only, never key values) | 0 token |
| `GET /dashboard?wallet=0x…` | full board for a wallet's main political position (`refresh=1` rebuilds) | cached: 0 · uncached: LLM calls · **rate-limited** |
| `GET /demo-wallets` | wallets with a cached board (instant) | 0 |
| `GET /recommendations` | AI-verified trader board (`refresh=1` rescans in the background, stale-while-revalidate) | 0 unless refresh |
| `GET /hot-traders` | 7-day politics leaderboard snapshot | 0 |
| `GET /scorecard` | live self-scoring: hit rate by direction, NO BASIS counted apart | 0 token (free settlement lookups) |
| `GET /confidence-replay` | hit rate by confidence bucket; read-only unless `settle=1` | 0 |
| `GET /backtest` | frozen historical backtest summary + case cards | 0 |
| `GET /market-context?wallet=…&cid=…` | market thesis for one position | cached: 0 |
| `GET /briefing?wallet=…` | long-form briefing | cached: 0 |
| `GET /election-pulse` | 2026 midterms market banner | 0 (TTL cache) |
| `GET /tech-immigration` | tech & immigration market panel | 0 (TTL cache) |
| `POST /visit` | first-party visit/event beacon, logged as one structured line; nothing stored, no third party | 0 |

Errors share one shape, `{"error": "<REASON>", "message": "…"}`, with layered status codes: `400` bad address, `404` no qualifying position, `429` rate limited, `502` upstream failure, `202` board still building.

**Auth:** none. The product is deliberately open (no sign-up). **Abuse control instead of auth:** the only endpoint that spends LLM credit, `/dashboard`, sits behind an in-memory sliding-window limiter, 30 requests / 60 s per IP plus a 500 / day global cap ([`core/ratelimit.py`](./core/ratelimit.py), tuned in [`core/config.py`](./core/config.py), tested in [`tests/test_ratelimit.py`](./tests/test_ratelimit.py)). `/visit` has its own limiter (60 / 60 s per IP). Every response carries an `x-request-id` header that matches the server log line.

### Example requests (zero-token endpoints)

```bash
BASE=https://smart-money-decoder.onrender.com   # free tier: first request after idle can take ~1 min

curl -s $BASE/healthz            # {"ok": ..., "failures": [...], "warnings": [...], "checks": {...}}
curl -s $BASE/scorecard          # {"tested": ..., "settled": ..., "hit_rate_pct": ..., "rows": [...]}
curl -s $BASE/backtest | head -c 400
curl -s "$BASE/dashboard?wallet=0xabc"   # -> 400 {"error": "INVALID_ADDRESS", ...} before any network call
```

---

## Status

MVP live. The calibration panel is honestly `pending` while early judgments await market settlement — numbers accrue as reality grades them. Next up: verified-wallet disagreement panels (F3) and the credibility wishlist (F4.1), tracked openly on the audit board.

**This is not financial advice.** SMD interprets public on-chain data and grades its own interpretations. It does not execute trades, recommend positions, or promise edge.
