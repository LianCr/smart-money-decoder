"""
tests/test_theme_markets.py — 主题盘（2026-10-30：趋势全换美国中期选举 + Tech & Immigration）

契约：
  1. election_pulse：Gamma midterms 事件按 24h 成交量 → 横幅卡；多子盘事件取 Yes 价作各选项概率，
     只留 active 且未结算、有价格的子盘，按概率降序取前 4；单二元盘给 Yes/No
  2. election_condition_ids：从这些事件挑成交量最大的子盘 cid（扫榜发现入口），跳过已结算/无量
  3. is_election_question：选举关键词判定（midterm/senate/house/governor/election…），大小写无关、
     不误伤 "White House press secretary" 这类非选举盘
  4. tech_immigration：关键词搜索结果去重、只要 active 未结算、按量排序；top_outcome=最高价选项；
     top_holder 取第一大持有人；note 诚实声明"没有直接 H-1B/OPT 盘"
  5. 任何上游失败 → 返回空 markets（端点照常 200），绝不抛给前端
  6. TTL 缓存：同一进程 10 分钟内不重复打上游
零网络：fake _get。
"""

import sys

sys.path.insert(0, ".")

import fetcher.theme_markets as tm
from fetcher.heisenberg import HeisenbergError

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


def mk(q, cid, prices, vol, group=None, closed=False, active=True, toks='["1","2"]'):
    return {"question": q, "conditionId": cid, "groupItemTitle": group, "outcomes": '["Yes","No"]',
            "outcomePrices": prices, "volumeNum": vol, "closed": closed, "active": active, "clobTokenIds": toks}


HOUSE = {"title": "Which party will win the House in 2026?", "slug": "house-2026", "volume24hr": 2100000.0,
         "markets": [mk("Will the Democratic Party control the House?", "0xd", '["0.935","0.065"]', 17e6, "Democratic Party"),
                     mk("Will the Republican Party control the House?", "0xr", '["0.065","0.935"]', 15e6, "Republican Party"),
                     mk("Will Party A control the House?", "0xa", None, 0, "Party A", active=False),
                     mk("Old", "0xo", '["1","0"]', 9e6, "Old", closed=True)]}
TX = {"title": "Texas Senate Election Winner", "slug": "tx-senate", "volume24hr": 400000.0,
      "markets": [mk("Will the Republican win the Texas Senate race?", "0xt", '["0.8","0.2"]', 3e6)]}

calls = []


def fake_get(url, params=None):
    calls.append((url, dict(params or {})))
    if "/events" in url:
        return [HOUSE, TX]
    if "public-search" in url:
        q = (params or {}).get("q")
        if q == "gold card":
            return {"events": [{"title": "How many Gold Cards will Trump sell in 2026?", "slug": "gold-card",
                                "volume24hr": 119.0, "active": True, "closed": False,
                                "markets": [mk("<100?", "0xg1", '["0.42","0.58"]', 5000, "<100"),
                                            mk("100-500?", "0xg2", '["0.30","0.70"]', 3000, "100-500")]}]}
        if q == "deport":
            return {"events": [{"title": "How many people will Trump deport in 2026?", "slug": "deport",
                                "volume24hr": 764.0, "active": True, "closed": False,
                                "markets": [mk("<500k?", "0xp", '["0.6","0.4"]', 9000, "<500k")]},
                               {"title": "FC Barcelona vs. Deportivo Alavés", "slug": "fcb-ala", "volume24hr": 5e4,
                                "active": True, "closed": False, "markets": [mk("Barca?", "0xb", '["0.88","0.12"]', 1e5, "FC Barcelona")]},
                               {"title": "Gold dup", "slug": "gold-card", "volume24hr": 119.0, "active": True,
                                "closed": False, "markets": []},
                               {"title": "Closed one", "slug": "closed-x", "volume24hr": 9e9, "active": True,
                                "closed": True, "markets": []}]}
        if q == "best ai model":
            return {"events": [{"title": "Which company has best AI model end of 2026?", "slug": "ai-2026",
                                "volume24hr": 45000.0, "active": True, "closed": False,
                                "markets": [mk("Google?", "0xai", '["0.56","0.44"]', 9e5, "Google")]},
                               {"title": "Which company has the best AI model end of October?", "slug": "ai-oct",
                                "volume24hr": 62000.0, "active": True, "closed": False,
                                "markets": [mk("Google?", "0xao", '["0.992","0.008"]', 9e5, "Google")]}]}
        return {"events": []}
    if "/v2/holders" in url:
        return {"data": [{"holders": [{"proxy_wallet": "0x" + "1" * 40, "name": "whale", "amount": 5000.0},
                                      {"proxy_wallet": "0x" + "2" * 40, "name": "", "amount": 10.0}]}]}
    raise AssertionError(url)


tm._get = fake_get
tm._cache.clear()

print("election_pulse")
p = tm.election_pulse()
check("election_date", p["election_date"], "2026-11-03")
check("两张卡", [m["title"] for m in p["markets"]], ["Which party will win the House in 2026?", "Texas Senate Election Winner"])
house = p["markets"][0]
check("多子盘：只留活盘、概率降序", [(o["name"], o["price"]) for o in house["outcomes"]],
      [("Democratic Party", 0.935), ("Republican Party", 0.065)])
check("url", house["url"], "https://polymarket.com/event/house-2026")
check("单二元盘 Yes/No", [(o["name"], o["price"]) for o in p["markets"][1]["outcomes"]], [("Yes", 0.8), ("No", 0.2)])
check("events 查询参数", (calls[0][1].get("tag_slug"), calls[0][1].get("order"), calls[0][1].get("closed")),
      ("midterms", "volume24hr", "false"))

print("TTL 缓存")
n = len(calls)
tm.election_pulse()
check("10 分钟内不重打", len(calls), n)

print("election_condition_ids")
tm._cache.clear()
ids = tm.election_condition_ids(limit=3)
check("按量取活盘 cid，跳过已结算/无量", [c for c, _q in ids], ["0xd", "0xr", "0xt"])

print("is_election_question")
for q, want in [("Will the Republican win the Texas Senate race?", True),
                ("2026 Balance of Power: D Senate, D House", True),
                ("Which party will win the House in 2026?", True),
                ("California Governor Election Winner", True),
                ("Will the MIDTERM turnout exceed 50%?", True),
                ("Will Trump name a new White House press secretary?", False),
                ("Will the Fed cut rates in December?", False),
                ("Russia x Ukraine ceasefire by 2026?", False)]:
    check(q[:44], tm.is_election_question(q), want)

print("tech_immigration")
tm._cache.clear()
t = tm.tech_immigration(groups=(("immigration", ("gold card", "deport")), ("tech", ("best ai model",))))
check("note 诚实", "H-1B" in t["note"] and "OPT" in t["note"], True)
titles = [m["title"] for m in t["markets"]]
check("移民组在前、组内按量；去重/去已结算/去误匹配(Deportivo)", titles,
      ["How many people will Trump deport in 2026?", "How many Gold Cards will Trump sell in 2026?",
       "Which company has best AI model end of 2026?"])
check("分组标注", [m["group"] for m in t["markets"]], ["immigration", "immigration", "tech"])
gold = t["markets"][1]
check("top_outcome = 最高价选项", (gold["top_outcome"]["name"], gold["top_outcome"]["price"]), ("<100", 0.42))
check("top_holder", (gold["top_holder"]["name"], gold["top_holder"]["amount"]), ("whale", 5000.0))

print("关键词相关性")
for title, kw, want in [("How many people will Trump deport in 2026?", "deport", True),
                        ("Trump deportations exceed 1M?", "deport", True),
                        ("FC Barcelona vs. Deportivo Alavés", "deport", False),
                        ("H-1B visa fee raised to $100k?", "h-1b", True),
                        ("Will OPT be eliminated?", "opt program", False),
                        ("Will the OPT program be eliminated in 2026?", "opt program", True)]:
    check(f"{kw}: {title[:36]}", tm._title_matches(title, kw), want)

print("上游失败")
def boom(url, params=None):
    raise HeisenbergError("SERVER", "down")
tm._get = boom
tm._cache.clear()
check("election_pulse 空 markets 不抛", tm.election_pulse()["markets"], [])
check("tech_immigration 空 markets 不抛", tm.tech_immigration()["markets"], [])
check("condition_ids 空", tm.election_condition_ids(), [])

print("端点（TestClient，不进 with=不触发 lifespan）")
from fastapi.testclient import TestClient
import api.main
client = TestClient(api.main.app)
r = client.get("/election-pulse")
check("/election-pulse 上游挂也 200", (r.status_code, r.json()["markets"]), (200, []))
r = client.get("/tech-immigration")
check("/tech-immigration 上游挂也 200 + note", (r.status_code, "OPT" in r.json()["note"]), (200, True))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
