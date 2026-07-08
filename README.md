# Smart Money Decoder

Decode the political bets of [Polymarket](https://polymarket.com) "smart money" — and put the decoder's judgment on trial against history.

Paste a wallet address; the tool finds the trader's largest political position, reconstructs the news around when they entered, and generates an AI **interpretation card** that answers one question: *should you follow this bet?* A second view, **Track Record**, replays that same decoder at historical points in time and scores its calls against how the markets actually resolved.

Read-only public APIs throughout — **no trading, no private keys.**

---

## What it does now (v3)

The product has grown from "paste a wallet" into a **recommendation-first political-bets dashboard**:

- **🏠 Recommendation homepage** — instead of waiting for you to find a wallet, the system **works backwards from hot political markets to their biggest co-holders** (a known political trader → the markets they're actually in → the whales on the other side), quality-gates them as genuine political specialists, and surfaces a feed of wallets worth watching. A scrolling ticker shows **this week's top political-profit traders**. (`recommend.py`, `hot_traders.py`, `fetcher/markets.py`)
- **📊 Unified board (①–⑥)** — one screen per wallet: identity & size · the bet (what it is) · live odds · whale 48h behavior flow · three-source catalysts (news × social, *fact vs. emotion* kept visually distinct) · **Edge/Reasoning**.
- **🎯 Market-level confidence, not wallet-anchored** — the key redesign. Confidence used to be driven by the wallet's P&L, which produced contradictions (two wallets betting opposite sides of the *same* market got opposite confidence). Now a **market-level adversarial pass** (one agent argues YES, one argues NO, a neutral reasoner adjudicates) yields **a single shared confidence per market**; each wallet is then mapped onto it as *with-edge* or *against-edge*. Confidence is **discounted by how trustworthy its inputs are** — price depth & whale-concentration (575 Market Insights), the outcome token's realized volatility (568), and time-to-resolution — on the principle *"confidence is capped by your most trustworthy anchor; two weak signals agreeing isn't confidence."* When two smart-money wallets disagree on a market, the board says so rather than endorsing both. (`analyzer/market_thesis.py`)
- **🧾 Honest scorecard** — every call is logged and, once markets resolve, checked for **direction hit/miss** (never copy-trade ROI — that would re-import survivorship bias).

The two views below (**Decode card** + **Track Record backtest**) are the original v2 experience, now the archival/secondary tabs.

---

## 🎬 Demo

Watch the walkthrough: paste a wallet, watch the pipeline decode a live political bet, then see the decoder's track record put on trial against history. Click the thumbnail to play on YouTube.

[![Smart Money Decoder — demo walkthrough](https://img.youtube.com/vi/egFu1kzgWrs/maxresdefault.jpg)](https://youtu.be/egFu1kzgWrs)

---

## Two views

### 1. Decode — real-time interpretation
Given a wallet, the pipeline runs end-to-end:

1. **Largest political position** — scans all holdings, filters to politics markets (tag-based) with value > $5,000 USDC.
2. **Entry time** — queries the wallet's trades for that specific market to find the first buy (with a full-activity fallback).
3. **Time-windowed news** — AI extracts search keywords from the market title, then pulls articles from the ±7/3-day window around the entry date (Tavily).
4. **AI decode** — `claude-sonnet-4.5` produces a card: *what the bet is*, the *catalyst* (sourced news), *edge analysis*, a **follow call** (`ROOM LEFT` / `CHASED` / `NO BASIS`), confidence, and warnings.

The card header also shows the wallet's avatar/nickname and an all-time **cumulative PnL chart**, both best-effort (never block the analysis).

### 2. Track Record — historical backtest
For each *resolved* political market the wallet held, the decoder is **replayed at T-7 and T-1** (seven days and one day before resolution) using the price and entry context as of that moment. Its verdict (follow / avoid) is compared to the **real settlement outcome** → ✓ hit / ✗ miss. Results aggregate across multiple wallets sourced from the Polymarket volume leaderboard.

Each sample carries a **difficulty score** (`1 − |entry_price − 0.5| × 2`): a bet entered near 0.5 is a *Coin-Flip*, one entered near 0/1 is *Near-Settled* — so an easy call isn't mistaken for a brilliant one.

> **Honest framing:** a wallet's *true win rate* is **not reliably computable** from public APIs — losing positions leave no on-chain signal and vanish from the positions endpoint, so any win rate would be inflated. The backtest therefore measures **the decoder's accuracy** (its call vs. reality), not the wallet's P&L. See `backtest/final_samples.md` for the curated case studies (e.g., two "Starmer out" bets the wallet lost, where the decoder correctly read the news and declined to follow).

---

## Architecture

```
fetcher/                          data layer (read-only HTTP)
  polymarket.py   →  get_top_political_position(address)        positions + politics filter + $5k
  trades.py       →  get_entry_time_v2 / get_wallet_profile / get_wallet_pnl_history
  activity.py     →  get_entry_time(address, condition_id)      legacy fallback
  news.py         →  get_news_for_market(question, entry_time)  keywords + Tavily + cache
                              ↓
analyzer/decoder.py →  decode_position(assembled, as_of=None)   sonnet-4.5 + guards
renderer/card.py    →  terminal card (price_info filled by code, not AI)
                              ↓
main.py             →  CLI entry
api/main.py         →  FastAPI: GET /analyze, GET /backtest
frontend/           →  Vite + React single page (Decode / Track Record tabs)

backtest/                         offline backtest pipeline (sealed)
  full_activity.py →  fetch_full_activity(wallet, start, end)   independent pagination
  resolution.py   →  get_market_resolution(condition_id)        conditionId → real outcome
  snapshot.py     →  get_price_at(token_id, ts)                 historical price (CLOB)
  pipeline.py     →  run_backtest / run_backtest_multi          replay decoder, aggregate
```

**Stack:** Python 3.10+ · FastAPI · React + Vite · `claude-sonnet-4.5` (via a gateway) · Tavily.

**External data sources:** `data-api.polymarket.com` (positions / activity / trades), `gamma-api.polymarket.com` (events, resolution), `clob.polymarket.com` (historical prices), `user-pnl-api.polymarket.com` (PnL curve), `lb-api.polymarket.com/volume` (leaderboard), Tavily (news).

---

## Setup

```bash
git clone https://github.com/LianCr/smart-money-decoder.git
cd smart-money-decoder
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in your keys
```

**Required keys** (in `.env`):

| Key | Where to get it |
|-----|-----------------|
| `TAVILY_API_KEY` | [app.tavily.com](https://app.tavily.com) |
| `CLASSROOM_API_KEY` | AI gateway (instructor-provided) |

---

## Run

```bash
# CLI — one wallet, full pipeline → terminal card
python main.py 0x7c3db723f1d4d8cb9c550095203b686cb11e5c6b

# Web — backend + frontend
uvicorn api.main:app --port 8000          # http://localhost:8000
cd frontend && npm install && npm run dev # http://localhost:5173

# Backtest pipeline (offline; writes .cache/backtest/result.json, served by /backtest)
python -m backtest.pipeline <wallet> <n>                          # single wallet
python -m backtest.pipeline multi <per_wallet> <total_cap> <w1> <w2> ...   # aggregate

# Unit tests (no network)
python tests/test_position.py      # positions / political filter
python tests/test_activity.py      # entry-time pagination
python tests/test_trades.py        # trades-based entry time
python tests/test_full_activity.py # backtest pagination
python tests/test_resolution.py    # conditionId → outcome parsing
```

---

## Design principles

- **Anti-fabrication is enforced in code, not just prompts.** The decoder runs a confidence matrix *before* the model, then rejects any output that tampers with the verdict, invents a catalyst when no news was found, or computes durations/dates the contract never provided (`DURATION_COMPUTED`, `FABRICATED_CATALYST`, `CONFIDENCE_TAMPERED`, …).
- **Prices are filled by code, never by the AI** — the model interprets, it never reports numbers.
- **Graceful degradation over wrong answers.** A missing entry time returns `None` (and `time_anchored=False`) rather than a fabricated match; auxiliary data (avatar, PnL curve) is best-effort and never blocks the core analysis.

## Verified API gotchas

Hard-won lessons baked into the code (full table in `CLAUDE.md`):

| Gotcha | Resolution |
|--------|------------|
| `activity` server-side `conditionId` filter | broken — pull all and filter locally |
| `gamma` won't return resolved markets | must pass `closed=true` |
| `gamma` `outcomes`/`outcomePrices` | JSON-encoded strings — `json.loads` them |
| Backtest replay of historical dates | decoder needs `as_of` so its "today" matches the snapshot, else it computes bogus durations |
| Tavily `published_date` | RFC 2822 — parse with `email.utils` |

---

## Status

Both views are fully working on real data. The backtest pipeline is sealed; the Track Record view is served from a precomputed result (multi-wallet aggregate). Known limits: short-fuse markets are filtered out (no T-7 price history), and high-conviction wallets tend to enter at extreme prices, so samples skew toward *Near-Settled* difficulty — surfaced honestly rather than hidden.

*This project analyzes public data for educational purposes. Nothing here is investment advice.*
