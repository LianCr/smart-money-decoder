"""
core/cachepolicy.py — 缓存失效注册表（P1-10：手写清单 → 各缓存自注册）。

旧病：强制刷新要清哪些缓存是一个硬编码 7 元素列表 + 三个跨模块私有函数 import——
新增一层缓存忘登记 = 用户点刷新拿到半新半旧的板且毫无提示。
现在：**每个缓存拥有者在自己模块 import 时 register()**，purge 遍历注册表。
新增缓存目录既不注册也不进测试豁免表 → `tests/test_cachepolicy.py` 的 lint 检查会红。

契约：
  register(name, resolver)  resolver(ctx) -> Path；ctx = {"wallet","cid","outcome","as_of"}
    四种 key 形各不相同（钱包×日期 ×4 / assemble 的 (wallet,cid,as_of,"live")→md5 /
    market_context 的 (cid,as_of,outcome,wallet)→md5 / market_thesis 的 (cid,as_of) 市场级）
    ——resolver 各自认字段，不强求统一模板。同名重复注册=覆盖（模块重载安全）。
  purge(wallet, cid, outcome, as_of) -> int
    🔴 语义与旧 _purge_wallet_caches 逐字一致：只删 resolver 算出的**那一个文件**
    （= 传入 as_of 当天的 key），旧日期快照永不碰（重建失败时它是回退底）；
    单条删除失败静默吞掉（best-effort，刷新不许因清缓存半途炸掉）。
"""

_REGISTRY: dict[str, object] = {}    # name -> resolver（有序 dict：注册顺序=遍历顺序）


def register(name: str, resolver) -> None:
    _REGISTRY[name] = resolver


def registered_names() -> list[str]:
    return list(_REGISTRY)


def purge(wallet: str, cid: str, outcome: str, as_of: str) -> int:
    ctx = {"wallet": wallet, "cid": cid, "outcome": outcome, "as_of": as_of}
    n = 0
    for resolver in _REGISTRY.values():
        try:
            p = resolver(ctx)
            if p is not None and p.exists():
                p.unlink()
                n += 1
        except Exception:
            pass
    return n
