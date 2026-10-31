"""
fetcher/pm_backend.py — Polymarket 免费公开 API 后端（2026-10-30）

为什么：Heisenberg 免费 key 失效（本地与 Render 两把都 401 AUTH，官网改为"申请开通"），
整个数据层停摆。Polymarket 官方 Data API v2 / Gamma / CLOB 全部免 key，实测覆盖了我们用到的
几乎全部原语。本模块把它们的响应**翻成 Heisenberg 各 agent 的记录形状**，经
`fetcher.heisenberg.call/paginate` 的后端开关接入 → 上层调用点与既有测试缝零改动。

agent → 来源（字段契约以 tests/test_pm_backend.py 为准）：
  556 trades       ← data-api /v2/trades（user/condition/start/end，cursor 翻页）
  574 markets      ← gamma /markets（无 closed=只要未结算；closed=True=已结算；赢家由 outcomePrices=1 推出）
  568 candles      ← data-api /v2/prices-history（bucket_seconds=86400；volume 无来源→诚实 None）
  569 pnl          ← data-api /v2/user-pnl（累计已实现盈亏日序列 → 日差分）
  581 wallet360    ← data-api /v2/leaderboard?category=politics&user=（窗口 7d→week、其余→month）
  579 leaderboard  ← data-api /v2/leaderboard（不分类；单地址或 ALL 榜）
  575 insights     ← gamma 市场 + /v2/holders + /v2/oi（能算的才给，其余 None）
  572 orderbook    ← CLOB /book（只有"现在"一张快照；窗口不含现在 → 诚实返空）
  585 social / 584 F-Score / 其他 → UNSUPPORTED（上层 best-effort 吞掉）

🔴 诚实边界（红线 3 / empty_field_guide）：
  - win_rate / total_trades / sharpe：公开接口算胜率必被"赢家赎回消失"污染 → 一律 None，绝不硬算。
  - 581 反作弊旗标（sybil/timing…）无来源 → 不出现该 key（缺席≠清白，上层按缺席处理、不加分）。
  - roi = pnl / 成交额 × 100：口径是"成交额回报"，不是 Heisenberg 的投入资本回报，偏保守。
  - 581 的 15 天窗口没有对应档 → 用 month；7 天 → week。
"""
import json
import time
from datetime import datetime, timedelta, timezone

import requests

DATA = "https://data-api.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
TIMEOUT = 20
_MAX_429_RETRIES = 3
# Polymarket 协议合约（不是交易者）：holders 里会以巨额仓位出现（实测 0xa5ef… 在 Balance of Power
# No 侧挂 610 万份、在几乎每个多选项盘都是"第一大持有人"），不剔除会把集中度/头号大户算成合约。
# /v2/leaderboard?user=<它> 返回 "user is a protocol contract address" 可用来核实新地址。
PROTOCOL_ADDRESSES = {
    "0xa5ef39c3d3e10d0b270233af41cac69796b12966",   # 2026-10-30 实测（leaderboard 判定为 protocol contract）
    "0xd91e80cf2e7be2e162c6513ced06f1dd0da35296",   # NegRiskAdapter
    "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",   # CTF Exchange
    "0xc5d563a36ae78145c45a50134d48a1215220f80a",   # NegRisk CTF Exchange
    "0x4d97dcd97ec945f40cf65f87097ace5ea0476045",   # ConditionalTokens
}


def is_protocol_address(addr):
    return str(addr or "").lower() in PROTOCOL_ADDRESSES


_HTTP = requests          # 测试缝：替换成带 .get(url, params, timeout) 的 fake
_SLEEP = time.sleep       # 测试缝


def _err(reason, message):
    from fetcher.heisenberg import HeisenbergError   # 延迟 import 防环（heisenberg 也 import 本模块）
    return HeisenbergError(reason, message)


def _get(url, params=None):
    for attempt in range(_MAX_429_RETRIES + 1):
        try:
            resp = _HTTP.get(url, params=params or {}, timeout=TIMEOUT)
        except requests.exceptions.Timeout:
            raise _err("TIMEOUT", f"Polymarket 超时 {url}")
        except requests.exceptions.RequestException as e:
            raise _err("NETWORK", f"Polymarket 网络错误 {type(e).__name__}")
        st = resp.status_code
        if st == 200:
            try:
                return resp.json()
            except ValueError:
                raise _err("NOT_JSON", f"200 但非 JSON —— {resp.text[:160]}")
        if st == 429:
            if attempt < _MAX_429_RETRIES:
                _SLEEP(2 * (attempt + 1))
                continue
            raise _err("RATE_LIMITED", "Polymarket 429 限流，退避后仍失败")
        if st >= 500:
            raise _err("SERVER", f"Polymarket {st} —— {resp.text[:160]}")
        if st == 404:
            raise _err("NOT_FOUND", f"Polymarket 404 {url}")
        raise _err("BAD_PARAMS", f"Polymarket {st} —— {resp.text[:160]}")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _iso(ts):
    """unix 秒 → tz-aware ISO（上层 fromisoformat + 与 aware 时间比较，naive 会 TypeError）。"""
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _iso_str(s):
    """Gamma 的 '2026-06-17 12:00:00+00' / '...Z' → 标准 tz-aware ISO；解析不了原样返回。"""
    if not s:
        return None
    t = str(s).strip().replace("Z", "+00:00").replace(" ", "T", 1)
    if t.endswith("+00"):
        t += ":00"
    try:
        d = datetime.fromisoformat(t)
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()
    except ValueError:
        return str(s)


def _jl(s):
    if isinstance(s, list):
        return s
    try:
        v = json.loads(s or "[]")
        return v if isinstance(v, list) else []
    except (TypeError, ValueError):
        return []


def _is_wallet(v):
    return isinstance(v, str) and v.lower().startswith("0x") and len(v) == 42


def _data(payload):
    d = payload.get("data") if isinstance(payload, dict) else payload
    return d


# ── 556 trades ────────────────────────────────────────────────────────────────

def _trade(r):
    return {"proxy_wallet": r.get("proxy_wallet"), "side": r.get("side"), "size": _f(r.get("size")),
            "price": _f(r.get("price")), "outcome": r.get("outcome"), "condition_id": r.get("condition_id"),
            "slug": r.get("slug"), "title": r.get("title"), "token_id": r.get("token_id"),
            "event_slug": r.get("event_slug"), "timestamp": _iso(r.get("timestamp"))}


def _trade_query(params):
    q = {}
    w = params.get("proxy_wallet")
    if _is_wallet(w):
        q["user"] = w
    c = params.get("condition_id")
    if c and str(c).upper() != "ALL":
        q["condition"] = c
    for src, dst in (("start_time", "start"), ("end_time", "end")):
        if params.get(src) not in (None, ""):
            q[dst] = int(float(params[src]))
    return q


def trades_all(params, max_rows=3000):
    """556 全量：cursor 翻页到 max_rows 截止（对齐 Heisenberg max_pages×200 的防爆量语义）。"""
    q = _trade_query(params)
    out, cursor = [], None
    while len(out) < max_rows:
        page_q = dict(q, limit=min(1000, max_rows - len(out)))
        if cursor:
            page_q["cursor"] = cursor
        payload = _get(f"{DATA}/v2/trades", page_q)
        rows = _data(payload) or []
        out.extend(_trade(r) for r in rows)
        pg = payload.get("pagination") or {} if isinstance(payload, dict) else {}
        cursor = pg.get("next_cursor")
        if not rows or not pg.get("has_more") or not cursor:
            break
    return out[:max_rows]


# ── 574 markets ───────────────────────────────────────────────────────────────

def _market(m):
    outs, toks, prices = _jl(m.get("outcomes")), _jl(m.get("clobTokenIds")), _jl(m.get("outcomePrices"))
    winner = None
    if m.get("closed"):
        for name, p in zip(outs, prices):
            if _f(p) == 1.0:
                winner = name
    ev = (m.get("events") or [{}])[0] or {}
    g = lambda arr, i: arr[i] if len(arr) > i else None
    return {"question": m.get("question"), "condition_id": m.get("conditionId"), "slug": m.get("slug"),
            "event_slug": ev.get("slug"), "closed": bool(m.get("closed")),
            "end_date": _iso_str(m.get("endDate")), "closed_date": _iso_str(m.get("closedTime")),
            "winning_outcome": winner,
            "side_a_outcome": g(outs, 0), "side_b_outcome": g(outs, 1),
            "side_a_token_id": g(toks, 0), "side_b_token_id": g(toks, 1),
            "volume_24h": _f(m.get("volume24hr")), "liquidity": _f(m.get("liquidityNum")),
            "created_at": _iso_str(m.get("createdAt"))}


def _gamma_market_raw(cid, closed):
    rows = _get(f"{GAMMA}/markets", {"condition_ids": cid, "closed": "true" if closed else "false"}) or []
    return [m for m in rows if isinstance(m, dict) and bool(m.get("closed")) == closed]


def _markets(params, limit, offset):
    want_closed = str(params.get("closed", "")).lower() == "true"
    q = {"closed": "true" if want_closed else "false"}
    cid = params.get("condition_id")
    if cid:
        if not (str(cid).startswith("0x") and len(str(cid)) == 66):
            return []                                  # 探针 0x0 / 垃圾 cid：合法空结果
        q["condition_ids"] = cid
    elif params.get("market_slug"):
        q["slug"] = params["market_slug"]
    else:
        q.update(limit=limit, offset=offset)
    rows = _get(f"{GAMMA}/markets", q) or []
    # Gamma 偶尔不理 closed 过滤 → 本地再筛一次，守住"默认只要未结算"的上层语义
    return [_market(m) for m in rows if isinstance(m, dict) and bool(m.get("closed")) == want_closed]


# ── 568 candles ───────────────────────────────────────────────────────────────

def _candles(params):
    q = {"token_id": params.get("token_id"), "bucket_seconds": 86400}
    for src, dst in (("start_time", "start"), ("end_time", "end")):
        if params.get(src) not in (None, ""):
            q[dst] = int(float(params[src]))
    by_day = {}
    for p in _data(_get(f"{DATA}/v2/prices-history", q)) or []:
        iso = _iso(p.get("timestamp"))
        if iso and _f(p.get("price")) is not None:
            by_day[iso[:10]] = {"candle_time": iso, "close": _f(p.get("price")), "volume": None}
    return [by_day[d] for d in sorted(by_day)]


# ── 569 pnl ───────────────────────────────────────────────────────────────────

def _pnl(params):
    w = params.get("wallet")
    start, end = params.get("start_time"), params.get("end_time")
    days_back = 9999
    try:
        days_back = (datetime.now(timezone.utc).date() - datetime.strptime(start, "%Y-%m-%d").date()).days
    except (TypeError, ValueError):
        pass
    interval = "1m" if days_back <= 29 else "all"
    pts = (_data(_get(f"{DATA}/v2/user-pnl", {"user": w, "interval": interval, "fidelity": "1d"})) or {}).get("points") or []
    series = {}
    for p in pts:
        iso = _iso(p.get("timestamp"))
        v = _f(p.get("realized_market_pnl"))
        if iso and v is not None:
            series[iso[:10]] = v
    days = sorted(series)
    out = []
    for prev, cur in zip(days, days[1:]):
        if (start is None or cur >= start) and (end is None or cur <= end):
            out.append({"proxy_wallet": w, "date": cur, "pnl": round(series[cur] - series[prev], 6)})
    return out


# ── 579 / 581 leaderboard ─────────────────────────────────────────────────────

_PERIOD = {"1d": "day", "7d": "week", "30d": "month", "all": "all"}


def _roi(pnl, vol):
    return round(pnl / vol * 100, 4) if (pnl is not None and vol) else None


def _lb_row(r, wallet=None):
    pnl, vol = _f(r.get("pnl")), _f(r.get("volume"))
    addr = (r.get("user_id") or wallet or "")
    return {"address": addr.lower() or None, "rank": r.get("rank_pnl", r.get("rank")), "roi": _roi(pnl, vol),
            "win_rate": None, "sharpe_ratio": None, "total_pnl": pnl, "total_invested": vol,
            "total_trades": None, "markets_traded": None, "name": r.get("user_name")}


def _leaderboard(params, limit):
    w = params.get("wallet_address")
    q = {"time_period": _PERIOD.get(str(params.get("leaderboard_period", "30d")), "month"), "sort_by": "pnl"}
    if _is_wallet(w):
        d = _data(_get(f"{DATA}/v2/leaderboard", dict(q, user=w)))
        return [_lb_row(d, w)] if isinstance(d, dict) and d else []
    rows = _data(_get(f"{DATA}/v2/leaderboard", dict(q, limit=limit))) or []
    return [_lb_row(r) for r in rows if isinstance(r, dict)]


def _wallet360(params):
    w = params.get("proxy_wallet")
    period = "week" if str(params.get("window_days")) in ("1", "3", "7") else "month"
    d = _data(_get(f"{DATA}/v2/leaderboard", {"user": w, "category": "politics", "time_period": period,
                                               "sort_by": "pnl"}))
    if not isinstance(d, dict) or not d:
        return []
    pnl, vol = _f(d.get("pnl")), _f(d.get("volume"))
    cat = {"category": "Politics", "total_pnl": pnl, "roi": _roi(pnl, vol), "win_rate": None,
           "total_trades": None, "volume": vol}
    return [{"proxy_wallet": w, "window": period, "performance_by_category": [cat]}]


# ── 575 market insights ───────────────────────────────────────────────────────

def _insights(params):
    cid = params.get("condition_id")
    raw = _gamma_market_raw(cid, False) or _gamma_market_raw(cid, True)
    if not raw:
        return []
    m = _market(raw[0])
    top1 = top10 = None
    try:
        oi = (_data(_get(f"{DATA}/v2/oi", {"condition": cid})) or [{}])[0].get("value")
        amounts = sorted((_f(h.get("amount")) or 0
                          for tok in (_data(_get(f"{DATA}/v2/holders", {"condition": cid, "limit": 20})) or [])
                          for h in (tok.get("holders") or [])
                          if not is_protocol_address(h.get("proxy_wallet"))), reverse=True)
        oi = _f(oi)
        if oi and amounts:
            top1 = round(min(1.0, amounts[0] / oi) * 100, 2)
            top10 = round(min(1.0, sum(amounts[:10]) / oi) * 100, 2)
    except Exception:
        pass
    return [{"condition_id": cid, "end_date": m["end_date"], "created_at": m["created_at"],
             "winning_side": m["winning_outcome"], "liquidity_percentile": None, "liquidity_tier": None,
             "top1_wallet_pct": top1, "top10_wallet_pct": top10, "unique_traders_7d": None,
             "volume_trend": None, "liquidity_usd": m["liquidity"], "volume_24h": m["volume_24h"]}]


# ── 572 orderbook ─────────────────────────────────────────────────────────────

def _orderbook(params):
    end = params.get("end_time")
    now_ms = int(time.time() * 1000)
    if end not in (None, "") and int(float(end)) < now_ms - 86400 * 1000:
        return []                                      # 历史簿没有免费来源：诚实返空
    b = _get(f"{CLOB}/book", {"token_id": params.get("token_id")}) or {}
    ts = _iso(int(b.get("timestamp", now_ms)) // 1000)
    return [{"token_id": params.get("token_id"), "timestamp": ts,
             "bids": json.dumps(b.get("bids") or []), "asks": json.dumps(b.get("asks") or [])}]


# ── 入口 ──────────────────────────────────────────────────────────────────────

def dispatch(agent_id, params, limit=200, offset=0):
    """Heisenberg call() 的同形替身：返回 {"data": [...]}（与 results() 契约一致）。"""
    params = params or {}
    if agent_id == 556:
        rows = trades_all(params, max_rows=offset + limit)[offset:]
    elif agent_id == 574:
        rows = _markets(params, limit, offset)
    elif agent_id == 568:
        rows = _candles(params)
    elif agent_id == 569:
        rows = _pnl(params)
    elif agent_id == 579:
        rows = _leaderboard(params, limit)
    elif agent_id == 581:
        rows = _wallet360(params)
    elif agent_id == 575:
        rows = _insights(params)
    elif agent_id == 572:
        rows = _orderbook(params)
    else:
        raise _err("UNSUPPORTED", f"agent {agent_id} 在 Polymarket 公开 API 上无对应来源")
    return {"data": rows}
