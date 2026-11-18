"""
analytics/loader.py — load SMD's JSON archives into a relational schema and query SQL views.

Why a projection instead of moving the app onto a database: the JSON stores in .data/
carry the product's integrity rules (atomic writes, frozen settlements, corrupt-file
quarantine). This module never writes to them. It reads them, rebuilds the tables in
schema.sql, applies views.sql, and answers questions in SQL.

Runtime engine is stdlib sqlite3 in memory: zero infra, zero keys, < 10 ms for the
current archive size. The same .sql files are applied to PostgreSQL 16 in CI
(tests/test_analytics_sql.py with DATABASE_URL set) so the SQL stays portable.

Read-only, zero network, zero LLM.
"""

import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_SQL = HERE / "schema.sql"
VIEWS_SQL = HERE / "views.sql"

# view name -> ORDER BY used when reading it (views themselves carry no order)
VIEWS = {
    "v_scorecard_summary":       "",
    "v_hit_rate_by_confidence":  "ORDER BY confidence",
    "v_hit_rate_by_follow_call": "ORDER BY follow_call",
    "v_wallet_activity":         "ORDER BY judgments DESC, board_positions DESC, wallet",
    "v_market_summary":          "ORDER BY judgments DESC, lean_readings DESC, cid",
}

DEFAULT_DATA_DIR = Path(".data")


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _read_jsonl(path: Path) -> list:
    rows = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return rows
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue            # one bad line must not hide the rest of the log
    return rows


def read_archives(data_dir: Path = DEFAULT_DATA_DIR) -> dict:
    """Return {table_name: [row tuples]} from the JSON archives. Missing files = empty tables."""
    data_dir = Path(data_dir)

    card = _read_json(data_dir / "scorecard.json", {})
    judgments = []
    if isinstance(card, dict):
        for key, r in card.items():
            if not isinstance(r, dict) or not r.get("follow_call"):
                continue
            judgments.append((
                key, r.get("wallet"), r.get("cid"), r.get("market_question"),
                r.get("outcome"), r.get("market_price"), r.get("follow_call"),
                r.get("confidence"), r.get("source"), r.get("decided_at"),
                r.get("settled_at"), r.get("final_result"),
            ))

    readings = []
    for i, r in enumerate(_read_jsonl(data_dir / "confidence_log.jsonl"), start=1):
        if not r.get("cid") or r.get("ts") is None:
            continue
        readings.append((
            i, r["ts"], r["cid"], r.get("market"), r.get("as_of"),
            r.get("market_lean"), r.get("lean_strength"), r.get("confidence"),
        ))

    recs = []
    seen = set()
    for r in (_read_json(data_dir / "recommendations.json", {}) or {}).get("candidates", []) or []:
        key = (r.get("wallet"), r.get("market_question"))
        if not all(key) or key in seen:
            continue
        seen.add(key)
        recs.append((
            r["wallet"], r["market_question"], r.get("outcome"), r.get("politics_pnl"),
            r.get("politics_win_rate"), r.get("politics_trades"), r.get("behavior"),
            r.get("score"), 1 if r.get("ai_pick") else 0, r.get("ai_confidence"),
            r.get("ai_follow_call"),
        ))

    hot = []
    seen = set()
    for r in (_read_json(data_dir / "hot_traders.json", {}) or {}).get("traders", []) or []:
        w = r.get("wallet")
        if not w or w in seen:
            continue
        seen.add(w)
        hot.append((w, r.get("weekly_politics_pnl"), r.get("trades"),
                    r.get("win_rate"), r.get("overall_rank_7d")))

    return {"judgments": judgments, "confidence_readings": readings,
            "recommendations": recs, "hot_traders": hot}


def _statements(sql_text: str) -> list:
    """Split a .sql file on ';' after dropping '--' comments (our files have no ';' in strings)."""
    lines = [ln.split("--", 1)[0] for ln in sql_text.splitlines()]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def build(conn, archives: dict, placeholder: str = "?") -> None:
    """Create tables + views on a DB-API connection and insert the archive rows.
    placeholder: '?' for sqlite3, '%s' for psycopg."""
    cur = conn.cursor()
    for stmt in _statements(SCHEMA_SQL.read_text(encoding="utf-8")):
        cur.execute(stmt)
    for table, rows in archives.items():
        if not rows:
            continue
        marks = ", ".join([placeholder] * len(rows[0]))
        cur.executemany(f"INSERT INTO {table} VALUES ({marks})", rows)
    for stmt in _statements(VIEWS_SQL.read_text(encoding="utf-8")):
        cur.execute(stmt)
    conn.commit()


def _clean(v):
    """Decimal (Postgres numeric) -> float; floats rounded for display."""
    if v is None or isinstance(v, (int, str)):
        return v
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return v


def query_view(conn, view: str) -> list:
    if view not in VIEWS:
        raise KeyError(view)
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {view} {VIEWS[view]}")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, (_clean(v) for v in row))) for row in cur.fetchall()]


def run_all(conn) -> dict:
    return {name: query_view(conn, name) for name in VIEWS}


def analytics_report(data_dir: Path = DEFAULT_DATA_DIR) -> dict:
    """Build an in-memory SQLite DB from the archives and return every view's rows."""
    archives = read_archives(data_dir)
    conn = sqlite3.connect(":memory:")
    try:
        build(conn, archives)
        views = run_all(conn)
    finally:
        conn.close()
    return {
        "engine": f"sqlite {sqlite3.sqlite_version} (in-memory, rebuilt per request)",
        "row_counts": {t: len(rows) for t, rows in archives.items()},
        "views": views,
        "note": "Hit rate = direction of the held side vs. settled result, never $ return. "
                "NO BASIS is excluded from the hit rate and counted separately.",
    }
