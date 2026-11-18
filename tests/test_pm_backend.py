"""
tests/test_pm_backend.py — Polymarket 免费公开 API 后端（2026-10-30，替换失效的 Heisenberg key）

契约 = 把 Polymarket Data API v2 / Gamma / CLOB 的响应翻成 Heisenberg 各 agent 的记录形状，
上层调用点零改动（字段契约见 fetcher/pm_backend.py 头注）。逐 agent 钉死：
  556 trades   → proxy_wallet/side/size/price/outcome/condition_id/slug + tz-aware ISO timestamp；
                 "ALL" 不下发过滤；窗口 start/end 透传；cursor 翻页到 max_rows 截止
  574 markets  → 无 closed=只要未结算（已结算返空）；closed=True 才给已结算；winning_outcome 由 outcomePrices=1 推出
  568 candles  → 按日 bucket；candle_time ISO；同日去重取最后一点；volume 诚实 None
  569 pnl      → 日序列已实现盈亏差分，只回窗口内的天
  581 wallet360→ performance_by_category=[Politics]，roi=pnl/volume×100，win_rate/total_trades 诚实 None，反作弊旗标不造
  579 leaderboard → 单地址 / ALL 榜，address 小写
  585 / 584   → UNSUPPORTED（上层 best-effort 吞掉）
  错误分类 → HeisenbergError reason（RATE_LIMITED 重试、SERVER、BAD_PARAMS、TIMEOUT）
零网络：fake session.get 按 URL 前缀路由。
"""

import json
import sys

sys.path.insert(0, ".")

import fetcher.pm_backend as pm
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


class Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeHTTP:
    """routes: [(url_substring, callable(params)->(status, body))]，记录每次调用。"""
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        for sub, fn in self.routes:
            if sub in url:
                st, body = fn(dict(params or {}))
                return Resp(st, body)
        return Resp(404, {"error": "no route"})


def use(routes):
    f = FakeHTTP(routes)
    pm._HTTP = f
    pm._SLEEP = lambda s: None
    return f


W = "0x" + "ab" * 20
CID = "0x" + "cd" * 32

print("556 trades")
pages = [
    {"data": [{"proxy_wallet": W, "side": "BUY", "size": 10.0, "price": 0.4, "outcome": "Yes",
               "condition_id": CID, "slug": "s", "title": "T", "token_id": "1", "timestamp": 1793196554}],
     "pagination": {"has_more": True, "next_cursor": "c2"}},
    {"data": [{"proxy_wallet": W, "side": "SELL", "size": 5.0, "price": 0.6, "outcome": "No",
               "condition_id": CID, "slug": "s", "title": "T", "token_id": "2", "timestamp": 1793196600}],
     "pagination": {"has_more": False}},
]
f = use([("/v2/trades", lambda p: (200, pages[1] if p.get("cursor") == "c2" else pages[0]))])
rs = pm.trades_all({"proxy_wallet": W, "condition_id": "ALL", "start_time": "100", "end_time": "200"}, max_rows=3000)
check("翻两页拿全", len(rs), 2)
check("user 下发", f.calls[0][1].get("user"), W)
check("ALL 不下发 condition", "condition" in f.calls[0][1], False)
check("窗口透传", (f.calls[0][1].get("start"), f.calls[0][1].get("end")), (100, 200))
check("第二页带 cursor", f.calls[1][1].get("cursor"), "c2")
check("timestamp tz-aware ISO", rs[0]["timestamp"], "2026-10-28T14:09:14+00:00")
check("字段齐", (rs[0]["side"], rs[0]["size"], rs[0]["price"], rs[0]["outcome"], rs[0]["condition_id"]),
      ("BUY", 10.0, 0.4, "Yes", CID))
f = use([("/v2/trades", lambda p: (200, pages[0]))])
rs = pm.trades_all({"proxy_wallet": "ALL", "condition_id": CID}, max_rows=1)
check("max_rows 截断", len(rs), 1)
check("ALL 钱包不下发 user", "user" in f.calls[0][1], False)
check("condition 下发", f.calls[0][1].get("condition"), CID)

print("574 markets")
open_m = {"question": "Q?", "conditionId": CID, "slug": "q", "closed": False, "endDate": "2026-11-04T04:59:00Z",
          "closedTime": None, "outcomes": '["Yes", "No"]', "outcomePrices": '["0.7", "0.3"]',
          "clobTokenIds": '["111", "222"]', "events": [{"slug": "ev"}]}
closed_m = dict(open_m, closed=True, closedTime="2026-06-17 12:00:00+00", outcomePrices='["0", "1"]')
f = use([("gamma-api.polymarket.com/markets", lambda p: (200, [open_m] if p.get("closed") == "false" else [closed_m]))])
r = pm.dispatch(574, {"condition_id": CID})
m = r["data"][0]
check("默认查未结算", f.calls[-1][1].get("closed"), "false")
check("字段映射", (m["question"], m["condition_id"], m["slug"], m["event_slug"], m["closed"]), ("Q?", CID, "q", "ev", False))
check("side token", (m["side_a_outcome"], m["side_a_token_id"], m["side_b_outcome"], m["side_b_token_id"]),
      ("Yes", "111", "No", "222"))
check("end_date ISO", m["end_date"][:10], "2026-11-04")
check("未结算无赢家", m["winning_outcome"], None)
r = pm.dispatch(574, {"condition_id": CID, "closed": "True"})
m = r["data"][0]
check("closed=True 下发 true", f.calls[-1][1].get("closed"), "true")
check("赢家=价格1那侧", m["winning_outcome"], "No")
check("closed_date ISO 可 fromisoformat", m["closed_date"][:10], "2026-06-17")
f = use([("gamma-api.polymarket.com/markets", lambda p: (200, [closed_m] if p.get("closed") == "false" else []))])
check("Gamma 漏给已结算 → 默认查询仍返空", pm.dispatch(574, {"condition_id": CID})["data"], [])
f = use([("gamma-api.polymarket.com/markets", lambda p: (200, [open_m]))])
pm.dispatch(574, {"market_slug": "q"})
check("market_slug → slug", f.calls[-1][1].get("slug"), "q")
pm.dispatch(574, {"closed": "False"}, limit=200, offset=400)
check("列表翻页 offset", (f.calls[-1][1].get("limit"), f.calls[-1][1].get("offset")), (200, 400))
check("0x0 探针返空 200", pm.dispatch(574, {"condition_id": "0x0"}, limit=10)["data"] is not None, True)

print("568 candles")
f = use([("/v2/prices-history", lambda p: (200, {"data": [
    {"timestamp": 1792800000, "price": 0.66}, {"timestamp": 1792886400, "price": 0.65},
    {"timestamp": 1792890000, "price": 0.67}]}))])
r = pm.dispatch(568, {"token_id": "111", "interval": "1d", "start_time": "1792800000", "end_time": "1792900000"})
check("bucket=1d", f.calls[-1][1].get("bucket_seconds"), 86400)
check("同日去重取末点", [(c["candle_time"][:10], c["close"]) for c in r["data"]],
      [("2026-10-24", 0.66), ("2026-10-25", 0.67)])
check("volume 诚实 None", r["data"][0]["volume"], None)

print("569 pnl")
day = 86400
pts = [{"timestamp": 1790899200 + i * day, "realized_market_pnl": v} for i, v in enumerate([100, 150, 150, 90])]
f = use([("/v2/user-pnl", lambda p: (200, {"data": {"points": pts}}))])
r = pm.dispatch(569, {"wallet": W, "granularity": "1d", "start_time": "2026-10-04", "end_time": "2026-10-05"})
check("窗口内日差分", [x["pnl"] for x in r["data"]], [0.0, -60.0])
check("回显钱包", r["data"][0]["proxy_wallet"], W)

print("581 wallet360")
f = use([("/v2/leaderboard", lambda p: (200, {"data": {"user_id": W, "pnl": 5000.0, "volume": 20000.0, "rank_pnl": 12}}))])
r = pm.dispatch(581, {"proxy_wallet": W, "window_days": "7"})
rec = r["data"][0]
check("7d→week + politics", (f.calls[-1][1].get("time_period"), f.calls[-1][1].get("category")), ("week", "politics"))
cats = rec["performance_by_category"]
check("Politics 类", cats[0]["category"], "Politics")
check("pnl", cats[0]["total_pnl"], 5000.0)
check("roi=pnl/volume×100", cats[0]["roi"], 25.0)
check("胜率诚实 None（红线3）", cats[0]["win_rate"], None)
check("反作弊旗标不造", "sybil_risk_flag" in rec, False)
pm.dispatch(581, {"proxy_wallet": W, "window_days": "15"})
check("15d→month", f.calls[-1][1].get("time_period"), "month")
f = use([("/v2/leaderboard", lambda p: (200, {"data": {"user_id": W, "pnl": 0.0, "volume": 0.0}}))])
check("零成交 roi None", pm.dispatch(581, {"proxy_wallet": W, "window_days": "7"})["data"][0]["performance_by_category"][0]["roi"], None)

print("579 leaderboard")
f = use([("/v2/leaderboard", lambda p: (200, {"data": {"user_id": W.upper().replace("0X", "0x"), "pnl": 10.0, "volume": 100.0, "rank_pnl": 7}}))])
r = pm.dispatch(579, {"wallet_address": W, "leaderboard_period": "30d"})
check("单地址", (r["data"][0]["address"], r["data"][0]["rank"], r["data"][0]["total_pnl"]), (W, 7, 10.0))
check("30d→month 不分类", (f.calls[-1][1].get("time_period"), "category" in f.calls[-1][1]), ("month", False))
f = use([("/v2/leaderboard", lambda p: (200, {"data": [{"user_id": W, "rank": 1, "pnl": 9.0, "volume": 90.0}]}))])
r = pm.dispatch(579, {"wallet_address": "ALL", "leaderboard_period": "7d"}, limit=100)
check("ALL 榜", (len(r["data"]), f.calls[-1][1].get("time_period"), f.calls[-1][1].get("limit")), (1, "week", 100))

print("575 集中度剔除协议合约")
CONTRACT = "0xa5ef39c3d3e10d0b270233af41cac69796b12966"
check("已知协议合约", pm.is_protocol_address(CONTRACT.upper().replace("0X", "0x")), True)
check("普通钱包", pm.is_protocol_address(W), False)
f = use([("gamma-api.polymarket.com/markets", lambda p: (200, [open_m] if p.get("closed") == "false" else [])),
         ("/v2/oi", lambda p: (200, {"data": [{"value": 1000.0}]})),
         ("/v2/holders", lambda p: (200, {"data": [{"holders": [{"proxy_wallet": CONTRACT, "amount": 900.0},
                                                                {"proxy_wallet": W, "amount": 100.0}]}]}))])
ins = pm.dispatch(575, {"condition_id": CID})["data"][0]
check("top1 不算合约", ins["top1_wallet_pct"], 10.0)

print("不支持的 agent")
for a in (585, 584, 596):
    try:
        pm.dispatch(a, {})
        check(f"{a} 抛", False, True)
    except HeisenbergError as e:
        check(f"{a} UNSUPPORTED", e.reason, "UNSUPPORTED")

print("错误分类")
n = {"i": 0}
def flaky(p):
    n["i"] += 1
    return (429, {}) if n["i"] < 3 else (200, {"data": {"user_id": W, "pnl": 1.0, "volume": 1.0}})
use([("/v2/leaderboard", flaky)])
check("429 退避后成功", pm.dispatch(579, {"wallet_address": W, "leaderboard_period": "30d"})["data"][0]["total_pnl"], 1.0)
for status, reason in ((500, "SERVER"), (400, "BAD_PARAMS"), (429, "RATE_LIMITED")):
    use([("/v2/leaderboard", lambda p, s=status: (s, {"error": "x"}))])
    try:
        pm.dispatch(579, {"wallet_address": W, "leaderboard_period": "30d"})
        check(f"{status} 抛", False, True)
    except HeisenbergError as e:
        check(f"{status} → {reason}", e.reason, reason)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
