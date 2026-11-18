# Runbook

Symptom → first check → fix → how to verify. Every entry below is a failure this project has
actually hit (dates and sources in brackets), not a hypothetical list.

**First command for almost everything:**

```bash
curl -s https://smart-money-decoder.onrender.com/healthz | python3 -m json.tool
```

`/healthz` returns `ok`, `failures[]`, `warnings[]` and boolean `checks` (never key values).
`503` means the instance cannot serve uncached wallets; `200` with warnings means it can,
in a degraded mode. Every API response also carries an `x-request-id` header; search that id
in Render Logs to see the whole request.

---

## 1. `/healthz` 503 with `data_probe: false` and an `AUTH` / `INSUFFICIENT_CREDIT` failure

[2026-08-05 Heisenberg 402; 2026-10-30 Heisenberg 401; still visible on the live master
deploy on 2026-11-17]

- **Meaning:** a data key is present but unusable. Cached boards still load; any new wallet
  fails. The health check treats this the same as a missing key on purpose.
- **Check:** `checks.polymarket_backend` in the `/healthz` body. If it is missing or `false`,
  the instance is running the old Heisenberg data layer.
- **Fix:** deploy the Polymarket data layer (PR #32, `DATA_BACKEND` defaults to
  `polymarket`, no key). If you really need Heisenberg, set `DATA_BACKEND=heisenberg` and
  replace `HEISENBERG_API_KEY` in the Render environment.
- **Verify:** `/healthz` → `200`, `checks.data_probe: true`; open one uncached wallet.

## 2. `/healthz` 503: required key missing

[AUDIT P0-2: deploy looked healthy, first unknown wallet returned 502]

- **Meaning:** `ANTHROPIC_API_KEY` (or the legacy `CLASSROOM_API_KEY`) or `TAVILY_API_KEY`
  is not set.
- **Fix:** Render → service → Environment → add the key (no quotes, no trailing space) →
  Save. Render restarts the service.
- **Verify:** `/healthz` → `200`; `failures` empty.

## 3. Uncached wallet returns `502` with `NO_KEY` / `GATEWAY_ERROR`

[2026-07-08: the classroom gateway's default domain went NXDOMAIN]

- **Meaning:** the LLM call failed. `core/llm.py` prefers `ANTHROPIC_API_KEY`; the classroom
  gateway is only a fallback and its default domain no longer resolves.
- **Fix:** set `ANTHROPIC_API_KEY`. Optional: `ANTHROPIC_MODEL` to pin a model.
- **Verify:** `GET /dashboard?wallet=<new wallet>` builds (first build takes roughly a
  minute; it returns `202` while building, then `200`).

## 4. First request after idle takes ~1 minute, or the page "hangs"

[Render free tier, every demo]

- **Meaning:** the free instance sleeps after 15 minutes idle; cold start is about one minute.
  Not a bug.
- **Fix:** open the URL 5–10 minutes before a demo. An external uptime ping every 10 minutes
  keeps it warm (needs an account, e.g. UptimeRobot; not set up).
- **Verify:** `curl -o /dev/null -w "%{time_total}\n" $BASE/healthz` under 1 s.

## 5. After a redeploy, the board / scorecard looks older than yesterday

[by design of the free tier's ephemeral disk; P2-27 in AUDIT.md]

- **Meaning:** on cold start `.cache/` and `.data/` are restored from git-tracked `seed/`,
  then overlaid with the `app-state` branch bundle. Without `GITHUB_TOKEN`, refreshed state
  is never written to `app-state`, so every restart falls back to the seed snapshot.
  `confidence_log.jsonl` is not in the bundle at all (known gap P2-27): pending readings can
  be lost, settled facts cannot.
- **Check:** `checks.github_token_present` in `/healthz`; startup log lines for the seed
  restore and the GitHub state restore.
- **Fix:** set `GITHUB_TOKEN` (fine-grained PAT, this repo, Contents read/write).
- **Verify:** refresh a board, trigger a redeploy, confirm the refreshed board survives.

## 6. `/dashboard` returns `429`

[P1-15 limiter, by design]

- **Meaning:** more than 30 requests / 60 s from one IP, or more than 500 / day site-wide
  (UTC). The body says which (`RATE_LIMITED` or `DAILY_LIMIT_REACHED`) with `retry_after`.
- **Fix:** wait. To change limits, set `RATE_LIMIT_PER_IP`, `RATE_LIMIT_WINDOW_SECONDS`,
  `RATE_LIMIT_DAILY_GLOBAL` in the environment. The limiter is in-memory, so a restart
  resets the counters and more than one instance would multiply the budget.
- **Verify:** response `200` after the window.

## 7. A board keeps returning `202` (building) and never finishes

[single-flight lock; Redis optional]

- **Meaning:** another request for the same wallet holds the build lock. Normal for up to a
  couple of minutes. Without `REDIS_URL` the lock is per process (fine for one instance).
- **Check:** Render Logs for the wallet; look for an upstream timeout or LLM error inside
  the build.
- **Fix:** if the build died, the lock expires after 10 minutes (`core/dashboard_jobs.py`); retry. With `refresh=1` the old board is
  served while the new one builds (stale-while-revalidate).
- **Verify:** `200` with the board; or `200` with `refresh_error` showing the real cause.

## 8. Polymarket returns `429` / `5xx`

[public API limits]

- **Meaning:** upstream throttling or an outage. `fetcher/pm_backend.py` retries `429` up to
  3 times with backoff; `/healthz` only warns on transient reasons (it does not mark the
  instance dead, to avoid deploy flapping).
- **Fix:** nothing to do for short bursts; cached boards keep serving. Theme panels
  (`/election-pulse`, `/tech-immigration`) return empty lists instead of erroring the page.
- **Verify:** `/healthz` warnings clear on the next probe (probe result is cached 10 min).

## 9. Scorecard suddenly empty, or a `.corrupt-*` file appears in `.data/`

[atomic-writes campaign, AUDIT P0/P1 fixes]

- **Meaning:** a JSON archive failed to parse. `core/jsonstore.py` moved it aside as
  `.corrupt-<timestamp>` instead of overwriting it; the service continues with an empty
  archive and logs a warning.
- **Fix:** inspect the `.corrupt-*` file, repair it by hand, put it back. Never rebuild the
  judgment archive from memory: the no-backfill rule means a lost judgment stays lost.
- **Verify:** `GET /scorecard` and `GET /analytics/v_scorecard_summary` show the same totals.

## 10. Site loads but shows `{"detail":"Not Found"}`

[2026-10-30: Render build command was only `pip install`]

- **Meaning:** `frontend/dist` was not built; the SPA mount is skipped when it is missing.
- **Fix:** Render build command must be
  `pip install -r requirements.txt && cd frontend && npm ci && npm run build`.
- **Verify:** `/` returns the HTML page.

## 11. CI red on a PR

- `check` job: runs `bash scripts/check.sh`, the same script as local. Run it locally first;
  every test is keyless and offline, so a test that needs a real key fails here on purpose.
- `sql-postgres` job: `analytics/*.sql` used something SQLite accepts but PostgreSQL does
  not (or the reverse). Keep the SQL portable; the test prints which assertion failed.

---

### Known gap

Render's dashboard settings (branch, build command, health-check path) were set by hand on
2026-10-30 and are not read from `render.yaml`. After a settings change, compare the
dashboard against `render.yaml` and keep them identical (branch `master`,
`healthCheckPath: /healthz`).
