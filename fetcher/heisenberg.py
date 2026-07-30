"""
fetcher/heisenberg.py — Heisenberg 数据中台共享客户端（v3 简报数据地基 · 批1）

职责：所有 Heisenberg fetcher（profile/actions/price/social）共用的单一客户端。
把验证过的坑全部编码于此，下游 fetcher 不必再各自踩一遍。

🔴 已验证的坑（详见 CLAUDE.md「已验证的 API 坑」表 [Heisenberg v3] 行）：
- 单一端点、靠 agent_id 切数据源；body 必带 formatter_config.format_type="raw"。
- 参数真名因 endpoint 而异（文档不可靠）：见 AGENTS 表的 wallet_param。
- pagination.limit 上限 200，超了 404（'max' tag 校验失败）。
- 569 宽时间窗只返回前若干天 → 查结算盈亏要把窗口窄锚到结算期附近。
- 584 H-Score 无按地址 lookup（纯筛选榜）；要定位某钱包官方排名走 579。

免费 key（环境变量 HEISENBERG_API_KEY），与老师收费 gateway 无关、不烧老师 token。
"""

import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

URL = "https://narrative.agent.heisenberg.so/api/v2/semantic/retrieve/parameterized"
KEY = os.environ.get("HEISENBERG_API_KEY")
MAX_LIMIT = 200
REQUEST_TIMEOUT = 30

# agent_id + 该端点"钱包参数"的实测真名（None=该端点无钱包参数）。
# 下游 fetcher 用 AGENTS[...] 取 (agent_id, wallet_param)，避免再踩参数名坑。
AGENTS = {
    "pnl":         (569, "wallet"),          # 已实现 PnL（realized only）
    "trades":      (556, "proxy_wallet"),    # 历史成交（文档写 wallet_proxy=错，被静默忽略）
    "markets":     (574, None),              # 市场（winning_outcome/side_a,b token/closed_date）
    "candles":     (568, None),              # OHLCV K线（token_id）
    "wallet360":   (581, "proxy_wallet"),    # 60+ 指标（window_days 仅 1/3/7/15）
    "hscore":      (584, None),              # H-Score 榜（无按地址查 → 用 579）
    "leaderboard": (579, "wallet_address"),  # 官方榜（可按地址直接定位）
    "social":      (585, None),              # Social Pulse（🔴 仅实时、不进回测）
}

# 第七道守卫用：各端点"返回记录里回显钱包"的字段名（None/缺 = 不回显，无法按记录核对）。
# 实测：556/569 记录回显 proxy_wallet；579 回显 address；581 单 profile 不回显。
_RECORD_WALLET_FIELD = {
    556: "proxy_wallet",
    569: "proxy_wallet",
    579: "address",
    581: None,
}


class HeisenbergError(Exception):
    """统一异常，携带机器读 reason + 人读 message。"""
    def __init__(self, reason: str, message: str):
        self.reason = reason
        self.message = message
        super().__init__(message)


_MAX_429_RETRIES = 3          # 429 退避重试次数（总共最多发 1+3 次）
_SLEEP = time.sleep           # 可被测试 monkeypatch，避免真睡


def call(agent_id: int, params: dict, limit: int = MAX_LIMIT, offset: int = 0) -> dict:
    """
    发一次请求，返回原始 payload（dict）。非 200 / 网络异常 → 抛 HeisenbergError（分类 reason）。
    limit 自动钳到 200（超了服务端会 404）。
    🛡 429 内建退避重试（2s/4s/6s）：扫榜线程和看板重建**并发**打限流时，之前一个 429 就把
    整条 dashboard pipeline 炸成 DASHBOARD_PIPELINE_FAILED——数据层自己扛住瞬时限流，重试耗尽才抛。
    """
    if not KEY:
        raise HeisenbergError("NO_KEY", "缺少 HEISENBERG_API_KEY，请在 .env 配置（免费 key）")

    body = {
        "agent_id": agent_id,
        "params": params,
        "pagination": {"limit": min(limit, MAX_LIMIT), "offset": offset},
        "formatter_config": {"format_type": "raw"},
    }
    for attempt in range(_MAX_429_RETRIES + 1):
        try:
            resp = requests.post(
                URL,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"},
                json=body,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.exceptions.Timeout:
            raise HeisenbergError("TIMEOUT", f"Heisenberg agent {agent_id} 超时")
        except requests.exceptions.RequestException as e:
            raise HeisenbergError("NETWORK", f"Heisenberg 网络异常：{e}")
        if resp.status_code == 429 and attempt < _MAX_429_RETRIES:
            _SLEEP(2 * (attempt + 1))
            continue
        break

    sc = resp.status_code
    if sc == 401:
        raise HeisenbergError("AUTH", "401 认证失败 —— HEISENBERG_API_KEY 错或没设对（Bearer）")
    if sc == 403:
        raise HeisenbergError("FORBIDDEN", "403 —— key 无权限/未激活")
    if sc == 400:
        raise HeisenbergError("BAD_PARAMS", f"400 参数错（字段名/取值）—— {resp.text[:200]}")
    if sc == 422:
        raise HeisenbergError("VALIDATION", f"422 参数校验失败 —— {resp.text[:200]}")
    if sc == 429:
        raise HeisenbergError("RATE_LIMITED", "429 限流 —— 放慢/重试")
    if sc >= 500:
        raise HeisenbergError("SERVER", f"{sc} 服务端错 —— {resp.text[:160]}")
    if sc != 200:
        raise HeisenbergError("UNEXPECTED", f"{sc} —— {resp.text[:160]}")

    try:
        payload = resp.json()
    except ValueError:
        raise HeisenbergError("NOT_JSON", f"200 但返回非 JSON —— {resp.text[:160]}")

    _verify_wallet_match(agent_id, params, payload)   # 🛡 第七道守卫（见下）
    return payload


def _verify_wallet_match(agent_id: int, params: dict, payload: dict) -> None:
    """
    🛡 数据层第七道守卫：防"返回对象 ≠ 请求对象"的静默污染
    （参数名写错→静默返全局流 / 缓存串号 / 分页串结果）。

    触发条件**不依赖参数 key 名**（防的就是 key 名写错）：只要 params 里出现"钱包地址样的值"
    （0x 开头、42 长），且该端点回显钱包字段，就核对返回每条记录的钱包 == 请求钱包（大小写归一）。
    不符 → 抛 WALLET_MISMATCH，**绝不静默返回**。
    """
    rec_field = _RECORD_WALLET_FIELD.get(agent_id)
    if not rec_field:
        return
    requested = [str(v).lower() for v in params.values()
                 if isinstance(v, str) and v.lower().startswith("0x") and len(v) == 42]
    if not requested:                      # 没按钱包查（或 proxy_wallet="ALL" 全局，合法）
        return
    for r in results(payload):
        if not isinstance(r, dict):
            continue
        got = r.get(rec_field)
        if got is not None and str(got).lower() not in requested:
            raise HeisenbergError(
                "WALLET_MISMATCH",
                f"🛡返回对象钱包({got}) ≠ 请求钱包{requested}（agent {agent_id}）"
                f"——疑似参数名写错/静默全局流/串号，已拦截，绝不把假数据喂给上层")


def results(payload: dict) -> list:
    """从 payload 抠记录列表（data.results / data 为 list / 兜底）。"""
    if not isinstance(payload, dict):
        return payload if isinstance(payload, list) else []
    d = payload.get("data")
    if isinstance(d, dict):
        return d.get("results", []) or []
    return d if isinstance(d, list) else []


def paginate(agent_id: int, params: dict, max_pages: int = 30, sleep: float = 0.15) -> list:
    """翻页拉全量（每页 200，返回不足 200 即停；max_pages 防爆量）。"""
    out = []
    for i in range(max_pages):
        page = results(call(agent_id, params, limit=MAX_LIMIT, offset=i * MAX_LIMIT))
        out.extend(page)
        if len(page) < MAX_LIMIT:
            break
        time.sleep(sleep)
    return out


# ── 冒烟测：确认客户端端到端能用（免费 key，不烧老师 token）─────────────────────
if __name__ == "__main__":
    KEN = "0x9d84ce0306f8551e02efef1680475fc0f1dc1344"   # ImJustKen（已验证样本）
    SLUG = "starmer-out-by-may-31-2026"

    print("批1 地基客户端冒烟测 · 免费 key、不烧老师 token\n")

    # 1) 579 按地址查官方榜（验 wallet_address 参数 + 错误分类正常）
    agent, wp = AGENTS["leaderboard"]
    rs = results(call(agent, {wp: KEN, "leaderboard_period": "30d"}))
    if rs:
        r = rs[0]
        print(f"① 579 Leaderboard ✓  ImJustKen 30d: rank={r.get('rank')} "
              f"pnl={r.get('total_pnl')} win_rate={r.get('win_rate')}")
    else:
        print("① 579 返回空（检查）")

    # 2) 574 按 slug 拿市场（验 markets + 结算字段）
    agent, _ = AGENTS["markets"]
    rs = results(call(agent, {"market_slug": SLUG, "closed": "True"}))
    if rs:
        m = rs[0]
        token = m.get("side_a_token_id")
        print(f"② 574 Markets ✓  '{m.get('question','')[:34]}' 赢={m.get('winning_outcome')} "
              f"结算={str(m.get('closed_date',''))[:10]}")
    else:
        token = None
        print("② 574 返回空（检查）")

    # 3) 568 K线拿一个 close（验 candles + limit≤200 钳制）
    if token:
        agent, _ = AGENTS["candles"]
        rs = results(call(agent, {"token_id": token, "interval": "1d",
                                  "start_time": "1779000000", "end_time": "1780300799"}))
        if rs:
            rs = sorted(rs, key=lambda x: str(x.get("candle_time", "")))
            print(f"③ 568 Candles ✓  最后一根 close={rs[-1].get('close')} @ {rs[-1].get('candle_time')}")
        else:
            print("③ 568 返回空（检查）")

    # 4) limit 钳制自检（传 500 不该 404，应被钳到 200）
    try:
        call(AGENTS["pnl"][0], {"wallet": KEN, "granularity": "1d",
                                "start_time": "2026-05-01", "end_time": "2026-05-15"}, limit=500)
        print("④ limit=500 自动钳到 200 ✓（没 404）")
    except HeisenbergError as e:
        print(f"④ limit 钳制异常：{e.reason} {e.message}")

    print("\n地基客户端就绪，批2/3/4 的 profile/actions/price fetcher 可在此之上建。")
