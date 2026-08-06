# Smart Money Decoder

> Reads what proven smart money is doing on Polymarket — and tells you whether the signal itself can be trusted.

[![CI](https://github.com/LianCr/smart-money-decoder/actions/workflows/check.yml/badge.svg)](https://github.com/LianCr/smart-money-decoder/actions)

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
- **36 test files**, including endpoint three-state tests, guard positive/negative pairs, and byte-hash immutability checks on the judgment log.
- **Honest failure modes**: missing keys fail loud at `/healthz` instead of half-working; the frontend never shows "failed" while the backend is still building.

Stack: FastAPI · React/Vite · Claude (adversarial adjudication) · Polymarket data via Heisenberg · deterministic scoring core.

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

## Status

MVP live. The calibration panel is honestly `pending` while early judgments await market settlement — numbers accrue as reality grades them. Next up: verified-wallet disagreement panels (F3) and the credibility wishlist (F4.1), tracked openly on the audit board.

**This is not financial advice.** SMD interprets public on-chain data and grades its own interpretations. It does not execute trades, recommend positions, or promise edge.
