-- analytics/schema.sql — relational model over SMD's JSON archives.
--
-- The app's source of truth stays the JSON stores in .data/ (atomic writes, no-backfill
-- rules in scorecard.py). This schema is a read-only projection for SQL analytics:
-- analytics/loader.py rebuilds it from those files on every request.
--
-- Portability contract: this file and views.sql must run unchanged on SQLite (runtime,
-- in-process, zero infra) and PostgreSQL 16 (verified in CI). So: no engine-specific
-- functions, booleans stored as 0/1 INTEGER, epoch seconds as BIGINT.

-- One archived AI judgment per (wallet, market, source). Mirrors .data/scorecard.json.
CREATE TABLE judgments (
    judgment_key     TEXT PRIMARY KEY,           -- "<wallet>_<cid>_<source>" (archive key)
    wallet           TEXT NOT NULL,
    cid              TEXT NOT NULL,              -- Polymarket condition id
    market_question  TEXT,
    outcome          TEXT,                       -- side the wallet holds: Yes / No
    market_price     DOUBLE PRECISION,           -- price of that side when judged
    follow_call      TEXT NOT NULL,              -- ROOM LEFT / CHASED / NO BASIS
    confidence_raw   TEXT,                       -- as written by the model (high/medium/med/low)
    source           TEXT NOT NULL,              -- board / decode
    decided_at       BIGINT,                     -- epoch s, set once, never overwritten
    settled_at       BIGINT,                     -- epoch s when the settlement was recorded
    final_result     TEXT                        -- Yes / No once settled, else NULL
);

-- Every market-lean reading the reasoner produced. Mirrors .data/confidence_log.jsonl.
CREATE TABLE confidence_readings (
    reading_id       INTEGER PRIMARY KEY,        -- line number in the jsonl
    ts               BIGINT NOT NULL,
    cid              TEXT NOT NULL,
    market           TEXT,
    as_of            TEXT,
    market_lean      TEXT,                       -- YES / NO
    lean_strength    INTEGER,                    -- 0-100
    confidence_raw   TEXT
);

-- Current recommendation board. Mirrors .data/recommendations.json["candidates"].
CREATE TABLE recommendations (
    wallet             TEXT NOT NULL,
    market_question    TEXT NOT NULL,
    outcome            TEXT,
    politics_pnl       DOUBLE PRECISION,
    politics_win_rate  DOUBLE PRECISION,
    politics_trades    INTEGER,
    behavior           TEXT,
    score              DOUBLE PRECISION,
    ai_pick            INTEGER,                  -- 0/1
    ai_confidence      TEXT,
    ai_follow_call     TEXT,
    PRIMARY KEY (wallet, market_question)
);

-- 7-day politics leaderboard snapshot. Mirrors .data/hot_traders.json["traders"].
CREATE TABLE hot_traders (
    wallet              TEXT PRIMARY KEY,
    weekly_politics_pnl DOUBLE PRECISION,
    trades              INTEGER,
    win_rate            DOUBLE PRECISION,
    overall_rank_7d     INTEGER
);
