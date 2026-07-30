"""
core/cachefiles.py — 按日期分 key 的缓存文件选择（纯路径逻辑，零网络零依赖，可单测）。

背景：/dashboard 缓存文件名 = f"{钱包小写}_{YYYY-MM-DD}.json"。
refresh 走"今天"后，同一钱包会同时存在多份日期快照（旧 demo 快照 + 新刷新的）。
默认读取取**最新日期**那份：刷新过就看到新的，没刷新过照旧秒回旧快照（零 token）。
🔴 刷新失败时旧快照因此天然幸存 —— 绝不出现"删了好缓存、重建又失败、两头空"。
"""
import re
from pathlib import Path

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def newest_dated(cache_dir, prefix: str):
    """在 cache_dir 下找 {prefix}_{YYYY-MM-DD}.json 的最新一份。
    返回 (Path, "YYYY-MM-DD")；一份都没有（或目录不存在）返回 None。
    ISO 日期字典序即时间序；文件名日期段不合法的一律忽略（不误配别的钱包/杂物文件）。"""
    best = None
    try:
        for p in Path(cache_dir).glob(f"{prefix}_*.json"):
            d = p.stem[len(prefix) + 1:]
            if _DATE_RE.fullmatch(d) and (best is None or d > best[1]):
                best = (p, d)
    except OSError:
        return None
    return best
