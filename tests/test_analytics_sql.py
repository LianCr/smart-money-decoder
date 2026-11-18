"""
tests/test_analytics_sql.py — SQL analytics views (analytics/*.sql) against the real seed archive.

The key check: the SQL hit-rate view must give exactly the same numbers as the Python
source of truth, scorecard.compute_scorecard(). Two implementations of one definition
that agree on real data = the SQL can't quietly redefine "hit" (e.g. let NO BASIS in).

Runs on stdlib sqlite3 always (zero keys, zero network, like every test here).
If DATABASE_URL is set (the CI `sql-postgres` job), the same schema/views/checks also
run on PostgreSQL 16 via psycopg — proving the .sql files are portable.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from fastapi.testclient import TestClient

import scorecard
from analytics import loader
import api.main

SEED = Path("seed/data")

passed = 0
failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}: got={got!r} want={want!r}")


def python_truth(data_dir: Path) -> dict:
    old = scorecard.ARCHIVE
    scorecard.ARCHIVE = data_dir / "scorecard.json"
    try:
        return scorecard.compute_scorecard()
    finally:
        scorecard.ARCHIVE = old


def engine_checks(label: str, conn, archives: dict, truth: dict) -> None:
    loader.build(conn, archives, placeholder="%s" if label == "postgres" else "?")
    views = loader.run_all(conn)

    s = views["v_scorecard_summary"][0]
    for k in ("tested", "settled", "settled_endorsed", "nobasis_total", "nobasis_clear_in_hindsight"):
        check(f"[{label}] summary.{k} == compute_scorecard", s[k], truth[k])
    check(f"[{label}] summary.hits == compute_scorecard.direction_consistent",
          s["hits"], truth["direction_consistent"])
    want_rate = truth["hit_rate_pct"]
    got_rate = None if s["hit_rate_pct"] is None else round(s["hit_rate_pct"], 1)
    check(f"[{label}] summary.hit_rate_pct == compute_scorecard", got_rate, want_rate)

    # row-level status must match Python for every judgment, not just the totals
    py_status = {}
    for r in truth["rows"]:
        py_status.setdefault(r["status"], 0)
        py_status[r["status"]] += 1
    cur = conn.cursor()
    cur.execute("SELECT status, COUNT(*) FROM v_judgment_status GROUP BY status")
    sql_status = {k: int(v) for k, v in cur.fetchall()}
    check(f"[{label}] per-status counts == compute_scorecard rows", sql_status, py_status)

    # NO BASIS never in the hit-rate denominator
    nb = [r for r in views["v_hit_rate_by_follow_call"] if r["follow_call"] == "NO BASIS"]
    check(f"[{label}] NO BASIS settled_endorsed = 0", nb[0]["settled_endorsed"] if nb else 0, 0)

    conf = {r["confidence"] for r in views["v_hit_rate_by_confidence"]}
    check(f"[{label}] 'med' normalised into 'medium'", "med" in conf, False)
    check(f"[{label}] by-confidence judgments add up to tested",
          sum(r["judgments"] for r in views["v_hit_rate_by_confidence"]), truth["tested"])

    wa = views["v_wallet_activity"]
    wallets_expected = ({r[1].lower() for r in archives["judgments"]}
                        | {r[0].lower() for r in archives["recommendations"]}
                        | {r[0].lower() for r in archives["hot_traders"]})
    check(f"[{label}] wallet_activity covers every wallet seen", {r["wallet"] for r in wa}, wallets_expected)
    check(f"[{label}] wallet_activity judgments add up", sum(r["judgments"] for r in wa), truth["tested"])
    check(f"[{label}] wallet_activity hot-list flags = hot_traders rows",
          sum(r["on_hot_list"] for r in wa), len(archives["hot_traders"]))

    ms = views["v_market_summary"]
    check(f"[{label}] market_summary judgments add up", sum(r["judgments"] for r in ms), truth["tested"])
    check(f"[{label}] market_summary lean readings add up",
          sum(r["lean_readings"] for r in ms), len(archives["confidence_readings"]))
    by_market = {}
    for r in archives["confidence_readings"]:
        by_market.setdefault(r[2], []).append(r)
    for cid, rows in by_market.items():
        empties = sum(1 for x in rows if x[5] is None)
        rows = sorted((x for x in rows if x[5] is not None), key=lambda x: (x[1], x[0]))
        flips = sum(1 for a, b in zip(rows, rows[1:]) if a[5] != b[5])
        m = next(x for x in ms if x["cid"] == cid)
        want = (rows[0][5] if rows else None, rows[-1][5] if rows else None, flips, empties)
        got = (m["first_lean"], m["last_lean"], m["lean_flips"], m["empty_readings"])
        if got != want:
            check(f"[{label}] lean first/last/flips/empties for {cid[:10]}", got, want)
            break
    else:
        check(f"[{label}] lean first/last/flips match a Python recount for every market", True, True)


print("\n[1] seed archive — SQLite")
archives = loader.read_archives(SEED)
truth = python_truth(SEED)
check("seed has judgments to test against", len(archives["judgments"]) > 0, True)
conn = sqlite3.connect(":memory:")
engine_checks("sqlite", conn, archives, truth)
conn.close()

print("\n[2] synthetic edge cases — a miss, a NO BASIS that settled, a lean flip, empty files")
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    card = {
        "w1_c1_board": {"wallet": "0xA", "cid": "c1", "market_question": "Q1", "outcome": "Yes",
                        "market_price": 0.6, "follow_call": "ROOM LEFT", "confidence": "high",
                        "source": "board", "decided_at": 100, "final_result": "No", "settled_at": 200},
        "w1_c2_board": {"wallet": "0xa", "cid": "c2", "market_question": "Q2", "outcome": "No",
                        "market_price": 0.7, "follow_call": "CHASED", "confidence": "med",
                        "source": "board", "decided_at": 150, "final_result": "No", "settled_at": 300},
        "w2_c1_decode": {"wallet": "0xB", "cid": "c1", "market_question": "Q1", "outcome": "No",
                         "market_price": 0.4, "follow_call": "NO BASIS", "confidence": "low",
                         "source": "decode", "decided_at": 120, "final_result": "No", "settled_at": 200},
    }
    (td / "scorecard.json").write_text(json.dumps(card))
    (td / "confidence_log.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"ts": 1, "cid": "c1", "market": "Q1", "market_lean": "YES", "lean_strength": 60},
        {"ts": 2, "cid": "c1", "market": "Q1", "market_lean": "NO", "lean_strength": 70},
        {"ts": 3, "cid": "c1", "market": "Q1", "market_lean": None, "lean_strength": None},
        {"ts": 4, "cid": "c1", "market": "Q1", "market_lean": "YES", "lean_strength": 55},
    ]) + "\nnot json\n")
    a2 = loader.read_archives(td)
    t2 = python_truth(td)
    check("synthetic: Python says 1 hit / 2 settled endorsed", (t2["direction_consistent"], t2["settled_endorsed"]), (1, 2))
    c2 = sqlite3.connect(":memory:")
    engine_checks("sqlite", c2, a2, t2)
    v = loader.run_all(c2)
    check("synthetic: hit rate 50.0", v["v_scorecard_summary"][0]["hit_rate_pct"], 50.0)
    check("synthetic: NO BASIS that settled 'right' counted as clear-in-hindsight",
          v["v_scorecard_summary"][0]["nobasis_clear_in_hindsight"], 1)
    check("synthetic: wallet case folded (0xA + 0xa = one wallet)",
          [r["judgments"] for r in v["v_wallet_activity"] if r["wallet"] == "0xa"], [2])
    check("synthetic: lean YES→NO→(empty)→YES = 2 flips, empty reading not a flip",
          [r["lean_flips"] for r in v["v_market_summary"] if r["cid"] == "c1"], [2])
    check("synthetic: bad jsonl line skipped, 4 readings kept", len(a2["confidence_readings"]), 4)
    c2.close()

    empty = td / "empty"
    empty.mkdir()
    r = loader.analytics_report(empty)
    check("empty archive: summary tested=0", r["views"]["v_scorecard_summary"][0]["tested"], 0)
    check("empty archive: hit rate is null, not 0", r["views"]["v_scorecard_summary"][0]["hit_rate_pct"], None)

print("\n[3] endpoints")
client = TestClient(api.main.app)
with tempfile.TemporaryDirectory() as td:
    for f in SEED.iterdir():
        if f.is_file():
            shutil.copy(f, Path(td) / f.name)
    old = loader.DEFAULT_DATA_DIR
    loader.DEFAULT_DATA_DIR = Path(td)
    try:
        res = client.get("/analytics")
        check("GET /analytics → 200", res.status_code, 200)
        body = res.json()
        check("GET /analytics lists all views", sorted(body["views"]), sorted(loader.VIEWS))
        check("GET /analytics row_counts.judgments", body["row_counts"]["judgments"], truth["tested"])
        res = client.get("/analytics/v_hit_rate_by_confidence")
        check("GET /analytics/<view> → 200", res.status_code, 200)
        check("GET /analytics/<view> rows", len(res.json()["rows"]) > 0, True)
        res = client.get("/analytics/drop_table")
        check("unknown view → 404 UNKNOWN_VIEW (no SQL built from the path)",
              (res.status_code, res.json().get("error")), (404, "UNKNOWN_VIEW"))
    finally:
        loader.DEFAULT_DATA_DIR = old

dsn = os.environ.get("DATABASE_URL")
if dsn:
    print("\n[4] seed archive — PostgreSQL (DATABASE_URL set)")
    import psycopg
    with psycopg.connect(dsn) as pg:
        cur = pg.cursor()
        cur.execute("DROP SCHEMA IF EXISTS smd_analytics_test CASCADE")
        cur.execute("CREATE SCHEMA smd_analytics_test")
        cur.execute("SET search_path TO smd_analytics_test")
        cur.execute("SELECT version()")
        print("  ", cur.fetchone()[0])
        engine_checks("postgres", pg, archives, truth)
        cur.execute("DROP SCHEMA smd_analytics_test CASCADE")
        pg.commit()
else:
    print("\n[4] PostgreSQL skipped (DATABASE_URL unset; the CI sql-postgres job runs it)")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
