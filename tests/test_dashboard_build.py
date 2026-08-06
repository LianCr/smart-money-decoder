"""
tests/test_dashboard_build.py — services/dashboard_build 纯数据错误契约（P0-3，零网络零 key）

背景（AUDIT P0-3 先决条件）：旧 _dashboard_impl 返回混合类型（成功 dict ‖ 错误 JSONResponse），
HTTP 自调用时被 .json() 糊平；抽成 service 层进程内直调后必须先钉死纯数据契约：
  🔴 只返回 dict、永不返回 JSONResponse、预期失败永不 raise；判别式 = "error" key 有无。
覆盖 8 个出口 + 单飞包装层：
  1/2. reason ∈ BAD_REQUEST / NO_POSITION → 错误 dict（即使 refresh=1 也不走旧板回退）
  3/4. position 上游失败：refresh/fresh 时回退旧板(带 refresh_error)/无旧板报错；否则直接报错
  5/6. briefing 返错：同上两态
  7/8. 管道异常：同上两态
  单飞：锁被占 + 普通访客有旧板 → 旧板+refresh_in_progress；否则 BUILD_IN_PROGRESS+retry_after
  成功路径：无 "error" key + 落盘缓存；缓存命中返回 dict

（原"api 层 _dashboard_status 暂无法直测"的欠条已于 T2.3 撕掉：import api.main 零副作用后，
端点层三态 + 查表矩阵在 tests/test_api_endpoints.py 直测。本文件继续钉 service 层纯数据契约。）
"""

import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, ".")

import services.dashboard_build as db

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


class patched:
    """monkeypatch 若干 db 模块属性，退出时还原。"""
    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self):
        self.old = {k: getattr(db, k) for k in self.kw}
        for k, v in self.kw.items():
            setattr(db, k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            setattr(db, k, v)


def pos_err(reason):
    return {"error": True, "reason": reason, "message": f"{reason} 的人读消息"}


POS_OK = {"market_id": "0xcid", "outcome": "Yes", "market_question": "Will X win?",
          "near_settled": None, "held_price": 0.55}
B_OK = {"catalysts": {}, "price_context": {"current_price": 60}, "meta": {"settle": None},
        "who_trader_profile": {}, "what_position_actions": {}}
TODAY = date.today().isoformat()


class _FakeFeed:
    def held_token(self, cid, outcome): return "tok"
    def gamma_meta(self, slug): return ("官方结算规则", "gamma context")
    def build_news_stream(self, g, t, tok, as_of): return []
    def build_market_news_stream(self, g, pool, tok, as_of): return []
    def price_series(self, tok, as_of): return []


def _base(tmp, **extra):
    """所有场景共用的安静化 patch：缓存进 tempdir、纯函数替身、零网络零 token。"""
    kw = dict(
        DASHBOARD_CACHE=Path(tmp) / "dashboard",
        REASONER_CACHE=Path(tmp) / "reasoner",
        BOARD_AI_CACHE=Path(tmp) / "board_ai",
        BRIEFING_CACHE=Path(tmp) / "briefing",
        attach_i18n_en=lambda d: False,
        _purge_wallet_caches=lambda *a, **k: 0,
        _market_slug=lambda cid: "some-slug",
    )
    kw.update(extra)
    return kw


def _success_patches(tmp, **extra):
    """完整成功路径的替身全家桶。"""
    kw = _base(
        tmp,
        get_top_political_position_hz=lambda w, as_of=None: dict(POS_OK),
        load_or_build_briefing=lambda *a, **k: dict(B_OK),
        get_behavior_flags=lambda *a, **k: {"flag": None},
        build_market_context=lambda *a, **k: {"market_context": {"timeline_events": []}},
        board_feed=_FakeFeed(),
        _board_ai_cached=lambda *a, **k: ("世界综述", "这一注在赌什么"),
        social_pulse=lambda *a, **k: {},
        _reasoner_cached=lambda *a, **k: {"follow_call": "ROOM LEFT", "confidence": "中", "facts": {}},
        build_market_thesis=lambda *a, **k: {"confidence": "高", "market_lean": "YES",
                                             "lean_strength": "strong", "pivotal_unknown": None,
                                             "rationale": "理由", "shared_pool": None,
                                             "guard_flags": [{"code": "FEAR_WORDS", "field": "rationale",
                                                              "message": "命中"}],
                                             # F4：575/568 结构化数据（可信度分的唯一原料）
                                             "input_trust": {
                                                 "price": {"raw": {"liquidity_percentile": 99.0,
                                                                   "top1_wallet_pct": 10.0,
                                                                   "top10_wallet_pct": 40.0,
                                                                   "unique_traders_7d": 1000,
                                                                   "volume_trend": "Stable", "flags": [],
                                                                   "market_age_days": 30},
                                                           "days_to_resolution": 42},
                                                 "vol": {"vol": 0.03},
                                                 "book": {"raw": {"spread": 0.01,
                                                                  "min_side_depth_usd": 50000.0},
                                                          "line": "盘口"},
                                                 "lines": []}},
        map_wallet=lambda thesis, outcome: {"alignment": "顺 edge"},
        get_wallet_profile=lambda w: {"name": "tester"},
        get_wallet_pnl_history=lambda w: [],
        scorecard=SimpleNamespace(record_judgment=lambda **k: None),
        # F4：回验档案替身（真 compute 会读 .data/ 业务文件，测试不许碰）
        confidence_replay=SimpleNamespace(compute=lambda: {"guard_cross": {
            "flagged": {"n": 0, "hits": 0, "insufficient": True, "hit_rate_pct": None},
            "clean": {"n": 0, "hits": 0, "insufficient": True, "hit_rate_pct": None}}}),
    )
    kw.update(extra)
    return kw


def _stale_file(cache_dir: Path, wallet: str, as_of="2026-01-01"):
    cache_dir.mkdir(parents=True, exist_ok=True)
    board = {"wallet": wallet, "as_of": as_of, "reasoning": {"confidence": "中"}, "i18n_en": {}}
    (cache_dir / f"{wallet}_{as_of}.json").write_text(json.dumps(board), encoding="utf-8")
    return board


def _is_pure_error(out, reason):
    return isinstance(out, dict) and out.get("error") == reason and "message" in out


# ── 出口 1/2：调用方/数据事实问题 → 错误 dict，refresh 也不走旧板回退 ────────────
print("出口 1/2：BAD_REQUEST / NO_POSITION")
with tempfile.TemporaryDirectory() as tmp:
    with patched(**_base(tmp, get_top_political_position_hz=lambda w, as_of=None: pos_err("INVALID_ADDRESS"))):
        out = db.build_dashboard("0x" + "1" * 40)
        check("INVALID_ADDRESS → 纯错误 dict", _is_pure_error(out, "INVALID_ADDRESS"), True)
        check("错误 dict 就是 dict（不是 JSONResponse）", type(out) is dict, True)
    for reason in sorted(db.NO_POSITION_REASONS):
        with patched(**_base(tmp, get_top_political_position_hz=lambda w, as_of=None, r=reason: pos_err(r))):
            out = db.build_dashboard("0x" + "2" * 40)
            check(f"{reason} → 纯错误 dict", _is_pure_error(out, reason), True)
    # 分类优先于旧板回退：INVALID_ADDRESS + refresh=1 + 有旧板 → 仍是错误 dict
    w = "0x" + "3" * 40
    cache = Path(tmp) / "dashboard"
    _stale_file(cache, w)
    with patched(**_base(tmp, get_top_political_position_hz=lambda x, as_of=None: pos_err("INVALID_ADDRESS"))):
        out = db.build_dashboard(w, refresh=1)
        check("INVALID_ADDRESS + refresh + 有旧板 → 不回退旧板", _is_pure_error(out, "INVALID_ADDRESS"), True)
    check("reason 集合导出：INVALID_ADDRESS ∈ BAD_REQUEST", "INVALID_ADDRESS" in db.BAD_REQUEST_REASONS, True)
    check("reason 集合导出：NO_POSITION 4 员", len(db.NO_POSITION_REASONS), 4)

# ── 出口 3/4：position 上游失败 ───────────────────────────────────────────────
print("出口 3/4：position 上游失败")
with tempfile.TemporaryDirectory() as tmp:
    base = _base(tmp, get_top_political_position_hz=lambda w, as_of=None: pos_err("API_TIMEOUT"))
    with patched(**base):
        out = db.build_dashboard("0x" + "4" * 40)                    # 无 refresh/fresh
        check("上游失败(无 refresh) → 纯错误 dict", _is_pure_error(out, "API_TIMEOUT"), True)
        out = db.build_dashboard("0x" + "4" * 40, refresh=1)         # refresh 但无旧板
        check("上游失败(refresh,无旧板) → 纯错误 dict", _is_pure_error(out, "API_TIMEOUT"), True)
        w = "0x" + "5" * 40
        _stale_file(Path(tmp) / "dashboard", w)
        out = db.build_dashboard(w, refresh=1)                       # refresh + 有旧板
        check("上游失败(refresh,有旧板) → 回退旧板", out.get("wallet"), w)
        check("回退旧板带 refresh_error", out.get("refresh_error"), "API_TIMEOUT: API_TIMEOUT 的人读消息")
        check("回退旧板不带 error key", "error" in out, False)

# ── 出口 5/6：briefing 返错 ──────────────────────────────────────────────────
print("出口 5/6：briefing 返错")
with tempfile.TemporaryDirectory() as tmp:
    base = _base(tmp,
                 get_top_political_position_hz=lambda w, as_of=None: dict(POS_OK),
                 load_or_build_briefing=lambda *a, **k: {"error": "上游简报挂了"})
    with patched(**base):
        out = db.build_dashboard("0x" + "6" * 40)
        check("briefing 错(无 fresh) → BRIEFING_BUILD_FAILED", _is_pure_error(out, "BRIEFING_BUILD_FAILED"), True)
        w = "0x" + "7" * 40
        _stale_file(Path(tmp) / "dashboard", w)                      # 旧日期 → fresh=1 不命中缓存
        out = db.build_dashboard(w, fresh=1)
        check("briefing 错(fresh,有旧板) → 回退旧板", out.get("refresh_error"), "BRIEFING_BUILD_FAILED: 上游简报挂了")

# ── 出口 7/8：管道异常 ───────────────────────────────────────────────────────
print("出口 7/8：管道异常")
with tempfile.TemporaryDirectory() as tmp:
    def _boom(*a, **k):
        raise RuntimeError("行为流炸了")
    base = _success_patches(tmp, get_behavior_flags=_boom)
    with patched(**base):
        out = db.build_dashboard("0x" + "8" * 40)
        check("管道异常(无 refresh) → DASHBOARD_PIPELINE_FAILED", _is_pure_error(out, "DASHBOARD_PIPELINE_FAILED"), True)
        check("异常类型进 message", "RuntimeError" in out.get("message", ""), True)
        w = "0x" + "9" * 40
        _stale_file(Path(tmp) / "dashboard", w)
        out = db.build_dashboard(w, fresh=1)
        check("管道异常(fresh,有旧板) → 回退旧板", "refresh_error" in out and "error" not in out, True)

# ── 成功路径 + 缓存命中：无 "error" key（判别式的另一半）─────────────────────────
print("成功路径 / 缓存命中")
with tempfile.TemporaryDirectory() as tmp:
    with patched(**_success_patches(tmp)):
        w = "0x" + "a" * 40
        out = db.build_dashboard(w)
        check("成功板是 dict 且无 error key", isinstance(out, dict) and "error" not in out, True)
        check("成功板 confidence 来自 market_thesis", out["reasoning"]["confidence"], "高")
        check("成功板 confidence_source 标注", out["reasoning"]["confidence_source"], "market_thesis")
        check("🛡 guard_flags 从 thesis 透传进 ⑥", out["reasoning"]["guard_flags"][0]["code"], "FEAR_WORDS")
        check("P1-7：LLM 裁决标 deterministic:false", out["reasoning"]["deterministic"], False)
        # F4：可信度分是顶层一等公民、纯代码 deterministic:true、不碰 ⑥ 判断
        check("F4：payload 出顶层 credibility", out["credibility"]["deterministic"], True)
        check("F4：硬指标全好 → 100/A", (out["credibility"]["score"], out["credibility"]["tier"]), (100, "A"))
        check("F4：days_to_resolution 透传", out["credibility"]["days_to_resolution"], 42)
        check("F4：self_check 样本不足如实标注",
              next(s for s in out["credibility"]["subs"] if s["key"] == "self_check")["raw"]["insufficient"], True)
        check("F4：credibility 不写回 ⑥（confidence 原样）", out["reasoning"]["confidence"], "高")
        cache_file = Path(tmp) / "dashboard" / f"{w}_{db.BRIEFING_AS_OF}.json"
        check("成功板落盘缓存", cache_file.exists(), True)
        out2 = db.build_dashboard(w)                                 # 第二次 → 缓存命中
        check("缓存命中返回 dict 且无 error key", isinstance(out2, dict) and "error" not in out2, True)
        check("缓存命中 wallet 一致", out2.get("wallet"), w)

    # market_thesis 挂 → 退回 v2 矩阵：deterministic 如实标 True（纯代码矩阵）
    def _thesis_boom(*a, **k):
        raise RuntimeError("thesis 炸了")
    with patched(**_success_patches(tmp, build_market_thesis=_thesis_boom)):
        out = db.build_dashboard("0x" + "f" * 40)
        check("thesis 挂 → fallback_v2_matrix", out["reasoning"]["confidence_source"], "fallback_v2_matrix")
        check("fallback 路径 deterministic:true（v2 矩阵纯代码）", out["reasoning"]["deterministic"], True)
        # F4：LLM 降级时 credibility 照常在场——只是原料缺 → score:null 诚实卡（绝不装数）
        check("F4：fallback 路径 credibility 仍在", out["credibility"]["deterministic"], True)
        check("F4：原料缺 → score null 非 0 非 100", out["credibility"]["score"], None)

# ── 单飞包装层 get_dashboard ─────────────────────────────────────────────────
print("单飞包装层")
with tempfile.TemporaryDirectory() as tmp:
    held = SimpleNamespace(enter=lambda w, a: SimpleNamespace(acquired=False, release=lambda: None))
    with patched(**_base(tmp), _FLIGHT=held):
        out = db.get_dashboard("0x" + "b" * 40)                      # 锁被占 + 无旧板
        check("锁被占+无旧板 → BUILD_IN_PROGRESS", out.get("error"), db.BUILD_IN_PROGRESS)
        check("BUILD_IN_PROGRESS 带 retry_after", out.get("retry_after"), 3)
        w = "0x" + "c" * 40
        _stale_file(Path(tmp) / "dashboard", w)
        out = db.get_dashboard(w)                                    # 锁被占 + 普通访客有旧板
        check("锁被占+普通访客 → 旧板", out.get("wallet"), w)
        check("旧板带 refresh_in_progress", out.get("refresh_in_progress"), True)
        out = db.get_dashboard(w, refresh=1)                         # refresh 不将就旧板
        check("锁被占+refresh → 仍 BUILD_IN_PROGRESS(前端轮询)", out.get("error"), db.BUILD_IN_PROGRESS)

    released = []
    ok_lease = SimpleNamespace(acquired=True, release=lambda: released.append(1))
    with patched(**_base(tmp), _FLIGHT=SimpleNamespace(enter=lambda w, a: ok_lease),
                 build_dashboard=lambda w, refresh=0, fresh=0: {"wallet": w, "built": True}):
        out = db.get_dashboard("0x" + "d" * 40, fresh=1)
        check("抢到锁 → 真跑 build_dashboard", out.get("built"), True)
        check("build 结束必释放锁", released, [1])

    def _build_boom(w, refresh=0, fresh=0):
        raise RuntimeError("build 崩")
    released2 = []
    with patched(**_base(tmp),
                 _FLIGHT=SimpleNamespace(enter=lambda w, a: SimpleNamespace(
                     acquired=True, release=lambda: released2.append(1))),
                 build_dashboard=_build_boom):
        try:
            db.get_dashboard("0x" + "e" * 40)
        except RuntimeError:
            pass
        check("build 意外 raise 也释放锁(finally)", released2, [1])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
