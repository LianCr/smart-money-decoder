"""
fetcher/trades.py — 钱包展示资料 + 历史 PnL 曲线（统一看板 ① 在用，均纯展示 best-effort）。

（2026-08-03 瘦身：v2 /analyze 解读卡链路下架，本文件的 v2 建仓时间查询
（get_entry_time_v2 及 /trades 翻页/最早 BUY 实现）随之删除，见 git 历史。
正向流程的建仓时间来自 Heisenberg 数据层（fetcher/actions.py）。）
"""

import requests
from dotenv import load_dotenv

load_dotenv()

DATA_API_BASE   = "https://data-api.polymarket.com"
REQUEST_TIMEOUT = 10


# ── 对外：钱包展示资料（头像/昵称），纯展示，best-effort ───────────────────────
def get_wallet_profile(address: str) -> dict:
    """
    取钱包的展示资料（头像 / 昵称），**纯前端展示用，绝不该阻塞主流程**。

    数据源：/trades 记录里本就自带的 name / pseudonym / profileImage（与具体市场无关，
    取最近一条即可）。不新增数据层语义，只是把已有字段顺出来。

    任何失败 / 空结果 → 返回只含 address 的最小 dict，下游用地址缩写兜底。
    这里**吞掉所有异常**是刻意的：头像拿不到不该让整条解读失败。
    """
    fallback = {"address": address, "name": None, "pseudonym": None, "profile_image": None}
    try:
        resp = requests.get(
            f"{DATA_API_BASE}/trades",
            params={"user": address, "limit": 1},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return fallback
        data = resp.json()
        if not data:
            return fallback
        r = data[0]
        return {
            "address":       address,
            "name":          (r.get("name") or "").strip() or None,
            "pseudonym":     (r.get("pseudonym") or "").strip() or None,
            "profile_image": (r.get("profileImage") or "").strip() or None,
        }
    except Exception:
        return fallback


# ── 对外：钱包历史 PnL 曲线（Polymarket 主页同款），纯展示，best-effort ─────────
PNL_API_URL = "https://user-pnl-api.polymarket.com/user-pnl"


def get_wallet_pnl_history(address: str, max_points: int = 160) -> list[dict]:
    """
    取钱包历史 PnL 时间序列（Polymarket 个人主页那条曲线的数据源），**纯展示**。

    端点（2026-06-12 实探确认）：user-pnl-api，返回 [{"t": unix秒, "p": pnl}, ...]。
    按需等间隔降采样到 max_points（保留末点），减小响应体、画图也够顺滑。

    失败 / 空 / 格式不符 → 返回 []，前端就不画曲线。吞异常同 get_wallet_profile，
    曲线拿不到绝不该让整条解读失败。
    """
    try:
        resp = requests.get(
            PNL_API_URL,
            params={"user_address": address, "interval": "all", "fidelity": "1d"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not isinstance(data, list) or not data:
            return []
        series = [
            {"t": int(x["t"]), "p": float(x["p"])}
            for x in data
            if x.get("t") is not None and x.get("p") is not None
        ]
        if len(series) > max_points:
            step = len(series) / (max_points - 1)
            sampled = [series[int(i * step)] for i in range(max_points - 1)]
            sampled.append(series[-1])  # 保留末点（最新 PnL）
            series = sampled
        return series
    except Exception:
        return []
