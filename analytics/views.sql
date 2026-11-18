-- analytics/views.sql — analytics views over schema.sql.
-- Portable SQL only (runs on SQLite and PostgreSQL 16; CI checks both).
--
-- Red lines carried over from scorecard.py, so SQL can't quietly say something the
-- product refuses to say:
--   * hit rate = direction of the held side vs. the settled result. No $ / follow-return.
--   * NO BASIS never enters the hit-rate numerator or denominator; it is counted apart.
--   * tests/test_analytics_sql.py asserts v_scorecard_summary == compute_scorecard().

-- Row-level status. One place defines hit/miss/pending/nobasis; every other view reads it.
-- confidence is normalised because the model wrote both 'med' and 'medium' for one bucket.
CREATE VIEW v_judgment_status AS
SELECT
    j.judgment_key,
    LOWER(j.wallet)                                   AS wallet,
    j.cid,
    j.market_question,
    j.outcome,
    j.market_price,
    j.follow_call,
    CASE LOWER(COALESCE(j.confidence_raw, ''))
        WHEN 'med'    THEN 'medium'
        WHEN 'medium' THEN 'medium'
        WHEN 'high'   THEN 'high'
        WHEN 'low'    THEN 'low'
        ELSE 'unknown'
    END                                               AS confidence,
    j.source,
    j.decided_at,
    j.settled_at,
    j.final_result,
    CASE
        WHEN j.follow_call = 'NO BASIS'               THEN 'nobasis'
        WHEN j.final_result IS NULL
          OR j.final_result NOT IN ('Yes', 'No')      THEN 'pending'
        WHEN j.final_result = j.outcome               THEN 'hit'
        ELSE 'miss'
    END                                               AS status
FROM judgments j;

-- Headline numbers. Same definitions as scorecard.compute_scorecard().
CREATE VIEW v_scorecard_summary AS
SELECT
    COUNT(*)                                                           AS tested,
    SUM(CASE WHEN final_result IS NOT NULL AND final_result <> ''
             THEN 1 ELSE 0 END)                                        AS settled,
    SUM(CASE WHEN status IN ('hit', 'miss') THEN 1 ELSE 0 END)         AS settled_endorsed,
    SUM(CASE WHEN status = 'hit' THEN 1 ELSE 0 END)                    AS hits,
    100.0 * SUM(CASE WHEN status = 'hit' THEN 1 ELSE 0 END)
          / NULLIF(SUM(CASE WHEN status IN ('hit', 'miss') THEN 1 ELSE 0 END), 0)
                                                                       AS hit_rate_pct,
    SUM(CASE WHEN status = 'nobasis' THEN 1 ELSE 0 END)                AS nobasis_total,
    SUM(CASE WHEN status = 'nobasis' AND final_result IN ('Yes', 'No')
              AND final_result = outcome THEN 1 ELSE 0 END)            AS nobasis_clear_in_hindsight,
    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END)                AS pending
FROM v_judgment_status;

-- Calibration: does "high" confidence actually settle right more often than "low"?
CREATE VIEW v_hit_rate_by_confidence AS
SELECT
    confidence,
    COUNT(*)                                                           AS judgments,
    SUM(CASE WHEN status IN ('hit', 'miss') THEN 1 ELSE 0 END)         AS settled_endorsed,
    SUM(CASE WHEN status = 'hit' THEN 1 ELSE 0 END)                    AS hits,
    100.0 * SUM(CASE WHEN status = 'hit' THEN 1 ELSE 0 END)
          / NULLIF(SUM(CASE WHEN status IN ('hit', 'miss') THEN 1 ELSE 0 END), 0)
                                                                       AS hit_rate_pct,
    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END)                AS pending,
    SUM(CASE WHEN status = 'nobasis' THEN 1 ELSE 0 END)                AS nobasis
FROM v_judgment_status
GROUP BY confidence;

-- Same cut by the call itself (ROOM LEFT vs CHASED; NO BASIS shows up with 0 settled_endorsed).
CREATE VIEW v_hit_rate_by_follow_call AS
SELECT
    follow_call,
    COUNT(*)                                                           AS judgments,
    SUM(CASE WHEN status IN ('hit', 'miss') THEN 1 ELSE 0 END)         AS settled_endorsed,
    SUM(CASE WHEN status = 'hit' THEN 1 ELSE 0 END)                    AS hits,
    100.0 * SUM(CASE WHEN status = 'hit' THEN 1 ELSE 0 END)
          / NULLIF(SUM(CASE WHEN status IN ('hit', 'miss') THEN 1 ELSE 0 END), 0)
                                                                       AS hit_rate_pct,
    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END)                AS pending,
    AVG(market_price)                                                  AS avg_price_when_judged
FROM v_judgment_status
GROUP BY follow_call;

-- Every wallet the product has seen (judged, on the board, or on the 7d leaderboard),
-- with how often it was judged and whether those judgments have been graded yet.
CREATE VIEW v_wallet_activity AS
WITH all_wallets AS (
    SELECT LOWER(wallet) AS wallet FROM judgments
    UNION
    SELECT LOWER(wallet) FROM recommendations
    UNION
    SELECT LOWER(wallet) FROM hot_traders
),
judged AS (
    SELECT
        wallet,
        COUNT(*)                                                   AS judgments,
        COUNT(DISTINCT cid)                                        AS markets_judged,
        SUM(CASE WHEN status IN ('hit', 'miss') THEN 1 ELSE 0 END) AS settled_endorsed,
        SUM(CASE WHEN status = 'hit' THEN 1 ELSE 0 END)            AS hits,
        MIN(decided_at)                                            AS first_judged_at,
        MAX(decided_at)                                            AS last_judged_at
    FROM v_judgment_status
    GROUP BY wallet
),
board AS (
    SELECT LOWER(wallet) AS wallet,
           COUNT(*)      AS board_positions,
           MAX(score)    AS best_board_score
    FROM recommendations
    GROUP BY LOWER(wallet)
)
SELECT
    w.wallet,
    COALESCE(j.judgments, 0)                                       AS judgments,
    COALESCE(j.markets_judged, 0)                                  AS markets_judged,
    COALESCE(j.settled_endorsed, 0)                                AS settled_endorsed,
    COALESCE(j.hits, 0)                                            AS hits,
    j.first_judged_at,
    j.last_judged_at,
    COALESCE(b.board_positions, 0)                                 AS board_positions,
    b.best_board_score,
    CASE WHEN h.wallet IS NULL THEN 0 ELSE 1 END                   AS on_hot_list,
    h.overall_rank_7d                                              AS hot_rank_7d,
    h.weekly_politics_pnl
FROM all_wallets w
LEFT JOIN judged j      ON j.wallet = w.wallet
LEFT JOIN board b       ON b.wallet = w.wallet
LEFT JOIN hot_traders h ON LOWER(h.wallet) = w.wallet;

-- Per market: how many judgments / wallets touched it, how it settled, and how the
-- reasoner's lean moved across readings (first vs last, flips counted with LAG).
CREATE VIEW v_market_summary AS
WITH ordered AS (
    -- readings with no lean (the reasoner returned nothing) are counted but skipped for
    -- first/last/flips, so NO -> (missing) -> NO is not reported as two flips
    SELECT
        cid,
        market_lean,
        ROW_NUMBER() OVER (PARTITION BY cid ORDER BY ts, reading_id)           AS rn_first,
        ROW_NUMBER() OVER (PARTITION BY cid ORDER BY ts DESC, reading_id DESC) AS rn_last,
        LAG(market_lean) OVER (PARTITION BY cid ORDER BY ts, reading_id)       AS prev_lean
    FROM confidence_readings
    WHERE market_lean IS NOT NULL
),
leans AS (
    SELECT
        cid,
        MAX(CASE WHEN rn_first = 1 THEN market_lean END)                       AS first_lean,
        MAX(CASE WHEN rn_last  = 1 THEN market_lean END)                       AS last_lean,
        SUM(CASE WHEN prev_lean IS NOT NULL AND prev_lean <> market_lean
                 THEN 1 ELSE 0 END)                                            AS lean_flips
    FROM ordered
    GROUP BY cid
),
readings AS (
    SELECT
        cid,
        MAX(market)                                                            AS market,
        COUNT(*)                                                               AS lean_readings,
        SUM(CASE WHEN market_lean IS NULL THEN 1 ELSE 0 END)                   AS empty_readings,
        MIN(lean_strength)                                                     AS min_lean_strength,
        MAX(lean_strength)                                                     AS max_lean_strength
    FROM confidence_readings
    GROUP BY cid
),
judged AS (
    SELECT
        cid,
        MAX(market_question)                                                   AS market_question,
        COUNT(*)                                                               AS judgments,
        COUNT(DISTINCT wallet)                                                 AS wallets,
        AVG(market_price)                                                      AS avg_price_when_judged,
        MAX(final_result)                                                      AS final_result
    FROM v_judgment_status
    GROUP BY cid
),
all_markets AS (
    SELECT cid FROM judgments
    UNION
    SELECT cid FROM confidence_readings
)
SELECT
    m.cid,
    COALESCE(j.market_question, r.market)                                      AS market,
    COALESCE(j.judgments, 0)                                                   AS judgments,
    COALESCE(j.wallets, 0)                                                     AS wallets,
    j.avg_price_when_judged,
    j.final_result,
    COALESCE(r.lean_readings, 0)                                               AS lean_readings,
    COALESCE(r.empty_readings, 0)                                              AS empty_readings,
    l.first_lean,
    l.last_lean,
    r.min_lean_strength,
    r.max_lean_strength,
    COALESCE(l.lean_flips, 0)                                                  AS lean_flips
FROM all_markets m
LEFT JOIN judged j   ON j.cid = m.cid
LEFT JOIN readings r ON r.cid = m.cid
LEFT JOIN leans l    ON l.cid = m.cid;
