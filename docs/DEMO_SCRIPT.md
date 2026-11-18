# Demo script (~3 minutes, voice over screen recording)

Spoken English, about 380 words at a normal pace. Brackets are what is on screen; they are
not read aloud. Numbers in `{braces}` are read off the screen on the day, never memorised,
because the live archive keeps growing.

## Before recording

- [ ] PR #32 (Polymarket data layer) is merged and deployed; `/healthz` returns `200`.
- [ ] Open https://smart-money-decoder.onrender.com 5–10 minutes early (free tier cold start ~1 min).
- [ ] Click one "cached" wallet once so the board opens instantly on camera.
- [ ] Tabs ready: home board · one wallet board · Track Record · `/docs` · GitHub repo
      (`analytics/views.sql`, Actions tab).
- [ ] Do not press "refresh" on camera: it spends model credit and takes about a minute.

---

## 0:00 – 0:20 · The problem

[Home board, election banner visible]

> This is Smart Money Decoder, a side project I built and deployed on my own. Polymarket
> whale trackers tell you who bought what. Copy-trading tools tell you to follow them,
> which mostly makes you their exit liquidity. I wanted to answer two harder questions:
> what does this move actually mean, and can the signal itself be trusted?

## 0:20 – 1:10 · Decode a wallet

[Click a cached wallet from the board. Scroll slowly: position → market → credibility → reasoning.]

> I pick a wallet from the board. The backend pulls its largest political position from
> Polymarket's public APIs: trades, holders, price history. Everything up to here is
> deterministic code.
>
> This panel is the credibility score: liquidity, holder concentration, participation,
> volatility. Pure code, no model. It answers "is this price even worth trusting?"
>
> Then three model calls argue it out: a bull case, a bear case, and a reasoner that rules
> between them, using only retrieved articles. Guards in code strip fabricated citations
> and bad date math before anything reaches the screen. The result is a lean and a
> confidence, labelled as non-deterministic.

## 1:10 – 2:00 · Keeping score on itself

[Track Record page: scorecard numbers, then the SQL breakdown panel below it.]

> The part I care most about: every judgment is archived before the market settles, and
> code makes backfilling impossible. Right now it has {N} judgments, {S} settled. The hit
> rate is direction only, never dollar returns, and "no basis" answers are counted
> separately instead of quietly dropped.
>
> Below that, the same archive is loaded into relational tables and broken down with SQL
> views: hit rate by confidence bucket and by type of call. The sample is still tiny, and
> the page says so instead of showing a flattering percentage.

## 2:00 – 2:40 · Engineering underneath

[`/docs` page, scroll the route list. Then GitHub: `analytics/views.sql`, then the Actions tab with both jobs green.]

> It's FastAPI with auto-generated OpenAPI docs: {R} routes (15 once the analytics PR is live). The one endpoint that spends
> model credit is rate-limited per IP with a daily global cap, and the health check
> really probes the data layer, so a dead key shows up as a 503 instead of a page that
> looks fine and fails later.
>
> The SQL views are tested against the Python scorecard: same archive, same numbers, or CI
> goes red. CI runs the whole suite with zero API keys, and runs the same SQL on SQLite
> and on a real PostgreSQL 16 container.

## 2:40 – 3:00 · Close

[Back to the home board.]

> The short version: interpretation over alerts, and a product that grades itself in
> public. Code and docs are on my GitHub, including the runbook and the audit I did on my
> own codebase. Thanks for watching.

---

## Likely follow-up questions (not in the recording)

- **Why no database?** One instance, small data, ephemeral disk. JSON with atomic writes,
  restored from git on cold start. SQL is a read-only projection, so there is no second
  source of truth to drift.
- **Why is the hit rate 100%?** Because n is tiny. That is exactly why the page shows the
  sample size next to it.
- **What broke in production?** The paid data key died (401/402), the health check caught
  it as a 503, and the fix was swapping to Polymarket's free public APIs behind the same
  record shape so no call site changed. See `docs/RUNBOOK.md` entry 1.
