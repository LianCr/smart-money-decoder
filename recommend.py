"""
recommend.py — 扫榜推荐 · 方法 E「市场反向找大户」（免费、无 LLM、扫榜的正解源）。

为什么是正解（对比此前方法）：
  方法 A/B 从「整体 H-Score / 月榜取顶」找政治钱包 → 良率极低（实测前 25 名只 1 个能用，政治是小池子、整体最强多在体育/加密）。
  方法 E 反过来：**从政治市场反向找大户**。但实测没有"按量列政治盘"的端点（见 fetcher/markets.py 注），
  故发现走「种子扩展」：已知政治钱包 → 它的热门政治顶仓盘 → 共持大户。实测某热门盘 top15 共持人 **15/15 是政治专家**，良率≈100%。

流程：种子钱包 → get_top 热门政治盘 cid → get_market_holders 共持大户池(去重) →
  581 质量门(政治盘真赚过钱、pnl≥门槛) → 取 top 富集顶仓(15页)+48h 行为 → 打分排序 → recommendations.json。
🔴 全免费（纯 Heisenberg 数据 key，0 老师 token），只受 429 限流（已退避）。AI 精选(对 top 跑 ⑥)=方法 C，按需另跑、有 token 闸。

跑法：`.venv/bin/python -u recommend.py`（几分钟）。前端 /recommendations 直读产物 .data/recommendations.json（带 generated_at→看板显示"更新于"）。

🟡 轻量轮询（cron 一行，免费扫层、不带 ⑥；要 ⑥ 手动 ai_top>0 跑）：
    0 */6 * * * cd /path/to/smart-money-decoder && AI_TOP=0 .venv/bin/python -u recommend.py >> .data/recommend.log 2>&1
🔴 as_of 语义（2026-07-08 晚起全实时）：BRIEFING_AS_OF 默认=今天（自有 ANTHROPIC_API_KEY，
   省 token 钉死历史约束已解除）。ai_verify 恒带 fresh=1：今天已有看板缓存直接用（不重复烧），
   否则在今天重建 → 推荐卡的 ⑥ 判断永远是当天的。AI 精选 top 5。
"""
import os
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from fetcher.heisenberg import call, results, AGENTS, HeisenbergError
from fetcher.positions import get_top_political_position_hz, get_top_political_positions_hz
from fetcher.markets import get_market_holders
from fetcher.profile import _wallet360
from briefing.market_context import get_behavior_flags

from core.config import BRIEFING_AS_OF as AS_OF
OUT = Path(".data/recommendations.json")

# 种子 = 已知活跃政治钱包（演示钱包 + 方法 C 验证过的政治专家）。它们的热门顶仓盘 = 发现入口。
# 🔴 种子只决定"扫哪些盘"，不直接进推荐；真正推谁由"盘里共持大户 + 质量门"决定（种子自己也可能被选中）。
SEEDS = [
    "0x9d84ce0306f8551e02efef1680475fc0f1dc1344",  # ImJustKen（演示）
    "0x24c8cf69a0e0a17eee21f69d29752bfa32e823e1",  # debased（演示）
    "0xbaa2bcb5439e985ce4ccf815b4700027d1b92c73",  # denizz（演示）
    "0xf1ef8705e9f63c790c6fffd6329aea7011718cd6",  # 方法 C 验证过的政治专家
]


def _retry(fn, *a, **k):
    for i in range(4):
        try:
            return fn(*a, **k)
        except HeisenbergError as e:
            if "429" in str(e):
                time.sleep(3 * (i + 1))
                continue
            return None
        except Exception:
            return None
    return None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _politics_cat(cats):
    for c in cats or []:
        if "politic" in str(c.get("category", "")).lower():
            return c
    return None


DASH_URL = f"http://localhost:{os.environ.get('PORT', '8000')}/dashboard"   # Render 上 $PORT≠8000，自指本服务


def _verify_one(c, fresh):
    """单候选 ⑥ 验证（就地改写 c；各线程各拿各的 c，天然线程安全）。"""
    params = {"wallet": c["wallet"]}
    if fresh:
        params["fresh"] = 1
    try:
        j = requests.get(DASH_URL, params=params, timeout=240).json()
    except Exception as e:
        print(f"  ⑥ 验证 {c['wallet'][:12]}… 失败(后端未在线?)：{e}", flush=True)
        return
    rs = (j.get("reasoning") or {}) if isinstance(j, dict) else {}
    if j.get("error") or not rs.get("confidence"):    # 看板报错 / 裁决缺失 → 不标精选（诚实降级）
        why = j.get("error") or j.get("reason") or "reasoning 无 confidence"
        print(f"  ⑥ 验证 {c['wallet'][:12]}… 未获裁决({why})——保持非精选", flush=True)
        return
    facts = rs.get("facts") or {}
    if facts.get("market_question"):          # 与看板同一注（防 max_pages/快照差异错配）
        c["market_question"] = facts["market_question"]
        c["outcome"] = facts.get("outcome", c["outcome"])
    c["ai_pick"] = True
    c["ai_confidence"] = rs.get("confidence")
    c["ai_follow_call"] = rs.get("follow_call")
    c["ai_verdict"] = rs.get("reasoning")
    c["position_type"] = facts.get("position_type")
    c["market_lean"] = rs.get("market_lean")        # 市场命题级独立倾向（同盘分歧时显示"我们倾向 X"）
    c["alignment"] = rs.get("alignment")            # 这一注 顺/逆 edge
    c["verified_as_of"] = j.get("as_of")            # ⑥ 验证锚的日期（卡片可显示数据新鲜度）
    # 🌐 顺手带走裁决文本的英文翻译（看板构建时已翻好），EN 模式推荐卡不再中英掺杂
    i18n = j.get("i18n_en") or {}
    for zh in (c.get("ai_verdict"), rs.get("pivotal_unknown")):
        if zh and i18n.get(zh):
            c.setdefault("i18n_en", {})[zh] = i18n[zh]
    print(f"  ⑥ {c['wallet'][:12]}… {rs.get('confidence')} · {rs.get('follow_call')} · lean={rs.get('market_lean')}", flush=True)


def ai_verify(cands, top=3, fresh=False, max_workers=5):
    """方法 C：对 top N 候选跑完整 ⑥（经本地 /dashboard，按(钱包,as_of)硬缓存→重复零 token）。
    🔴 烧 token（每个未缓存钱包一条完整 pipeline）；需后端在线，离线则优雅跳过、ai_pick 留 False。
    fresh=True（用户点刷新时）：传 fresh=1 → 看板在**今天**验证（今天已有缓存则直接用，不重复烧）。
    🛡 诚实守卫：只有真拿到 ⑥ 裁决（confidence 非空）才标 ai_pick —— 看板返回错误 JSON/空 reasoning
    时绝不产出"有 AI 精选徽章但信心/推理全空"的残卡（宁可不标，也不装验证过）。
    同时用看板 facts 回填 market/outcome，确保卡片显示与点开看板的 ⑥ 判断**针对同一注**（不错配）。

    ⚡ 并行（2026-07-08）：top N 并发验证，总时长 = 最慢一条而非 N 条之和（~12min → ~3min）。
    🔴 同盘锁：共持发现的钱包常押同一个盘——若并行各建 market_thesis 会重复烧且可能产出
    两份不同市场观（打破"同盘钱包共享同一份市场观"红线）。同盘候选串行（第二个直接命中
    第一个建好的 thesis 缓存），不同盘才真并行。"""
    targets = cands[:top]
    if not targets:
        return
    locks = {}
    guard = threading.Lock()

    def _market_lock(c):
        key = c.get("market_question") or c["wallet"]
        with guard:
            return locks.setdefault(key, threading.Lock())

    def _run(c):
        with _market_lock(c):
            _verify_one(c, fresh)

    with ThreadPoolExecutor(max_workers=min(max_workers, len(targets))) as ex:
        list(ex.map(_run, targets))


def _mark_disagreements(cands):
    """同盘分歧检测：同一市场出现正反两侧的聪明钱 → 标记，别给两边背书。
    🔴 这本身是高价值诚实信号——'聪明钱不是共识'。有独立倾向(market_lean)时附上'我们倾向 X'。"""
    by_market = {}
    for c in cands:
        by_market.setdefault(c["market_question"], []).append(c)
    for mq, group in by_market.items():
        sides = {str(c.get("outcome")).lower() for c in group}
        if len(sides) > 1:                              # 同盘出现 ≥2 个方向 = 分歧
            lean = next((c.get("market_lean") for c in group if c.get("market_lean")), None)
            for c in group:
                c["disagreement"] = True
                if lean:
                    c["disagreement_lean"] = lean       # 我们独立倾向
                    c["disagreement_with_edge"] = (str(c.get("outcome")).upper() == str(lean).upper())


def _mark_consensus(cands):
    """同侧专家共识（信号 5，与分歧对称）：同一市场同一方向 ≥2 个验证过的政治专家 → 标记。
    🔴 只在推荐层标共识、**绝不抬信心**（信心是市场级、已与钱包解耦）；是"被验证有技能者的共识"非单钱包盈亏，
    但仍有羊群/幸存者风险（且若该盘价格被鲸控，共识可能就是同一拨人）——当弱信号看。"""
    by_side = {}
    for c in cands:
        by_side.setdefault((c["market_question"], str(c.get("outcome")).lower()), []).append(c)
    for (_mq, _side), group in by_side.items():
        if len(group) >= 2:
            for c in group:
                c["consensus_count"] = len(group)


def diversify(cands, keep=8, per_market=2):
    """多样性收榜（纯代码）：打分已降序，每盘最多 per_market 个；池子本身不够多样时
    放宽补满到 keep（诚实：不造多样性，只在有得选时选得开）。"""
    out, count = [], {}
    for c in cands:
        mq = c.get("market_question")
        if count.get(mq, 0) < per_market:
            out.append(c)
            count[mq] = count.get(mq, 0) + 1
        if len(out) == keep:
            return out
    for c in cands:
        if c not in out:
            out.append(c)
            if len(out) == keep:
                break
    return out


def verify_targets(cands, top):
    """AI 精选名额跨盘优先（纯代码）：第一轮每盘取分最高的一个，占不满再按分补——
    5 个名额尽量给 5 个不同的盘，而不是同一个盘的前 5 名。"""
    seen, first, rest = set(), [], []
    for c in cands:
        mq = c.get("market_question")
        if mq not in seen:
            first.append(c)
            seen.add(mq)
        else:
            rest.append(c)
    return (first + rest)[:top]


def scan(per_market=10, gate_pnl=2000.0, enrich_top=14, keep=8, ai_top=5, as_of=None):
    """as_of=None → BRIEFING_AS_OF（现默认=今天，全实时）。
    ai_verify 恒 fresh=1：⑥ 验证永远锚当天（当天已有缓存不重复烧）。"""
    as_of = as_of or AS_OF
    # 0) 579 月榜（交叉信号 bonus 用）
    b579 = _retry(lambda: results(call(AGENTS["leaderboard"][0],
                  {"wallet_address": "ALL", "leaderboard_period": "30d"}))) or []
    addrs579 = {str(r.get("address", "")).lower() for r in b579}

    # 1) 种子 → 热门政治盘 cid（去重）。🎨 多样性（2026-07-09）：每个种子取前 3 个
    #    政治盘（原来只取最大 1 个 → 4 个种子高度重叠、全部候选挤在同 2-3 个盘，榜面单调）
    markets = {}
    for w in SEEDS:
        for pos in _retry(get_top_political_positions_hz, w, as_of=as_of, n=3, max_pages=15) or []:
            markets.setdefault(pos["market_id"], pos["market_question"])
        time.sleep(0.5)
    print(f"种子 {len(SEEDS)} → 热门政治盘 {len(markets)} 个", flush=True)

    # 2) 每盘 → 共持大户 → 钱包池（去重，记最大净持仓 + 来源盘）
    pool, pool_mkt = {}, {}
    for cid, q in markets.items():
        for w, v in _retry(get_market_holders, cid, as_of=as_of, top_n=per_market) or []:
            if v > pool.get(w, 0):
                pool[w], pool_mkt[w] = v, q
        time.sleep(0.3)
    print(f"共持大户池(去重) {len(pool)} 个钱包", flush=True)

    # 3) 质量门：581 政治专长，政治盘真赚过钱且 pnl≥门槛 → 富集名单（按政治 pnl 降序）
    graded = []
    for w in pool:
        res = _retry(_wallet360, w) or (None, [])
        pol = _politics_cat(res[1])
        pp = _f(pol.get("total_pnl")) if pol else None
        if pol and (pp or 0) >= gate_pnl:
            graded.append((w, pol, pp))
        time.sleep(0.22)
    graded.sort(key=lambda x: -(x[2] or 0))
    print(f"政治专家(pnl≥{gate_pnl:.0f}) {len(graded)} 个 → 富集顶仓+行为 top {enrich_top}", flush=True)

    # 4) 只对 top enrich_top 跑昂贵的 顶仓(15页)+48h 行为，组装候选
    cands = []
    for w, pol, pp in graded[:enrich_top]:
        time.sleep(0.4)
        pos = _retry(get_top_political_position_hz, w, as_of=as_of, max_pages=15)
        if not pos or pos.get("error"):
            print(f"  · {w[:12]}… 政治 pnl={pp:.0f} 但无未结算政治顶仓(跳)", flush=True)
            continue
        time.sleep(0.3)
        bf = _retry(get_behavior_flags, w, pos["market_id"], as_of) or {}
        beh = bf.get("flag")
        in579 = w.lower() in addrs579
        # 🔴 打分：被验证的体量+胜率为主，ROI 封顶防小样本高方差盖过真鲸鱼（实测 21 注/306% ROI 曾压过 $1.26M 鲸鱼）。
        roi = _f(pol.get("roi")) or 0
        trades = _f(pol.get("total_trades")) or 0
        win = _f(pol.get("win_rate")) or 0
        score = (pp or 0) / 20000.0 + min(roi, 40.0)
        if trades >= 50:                # 胜率只在注数够、不是运气时才加分
            score += (win - 0.5) * 20
        if in579:
            score += 15
        if beh == "ADD":
            score += 12
        elif beh == "EXIT":
            score -= 40                 # 主力撤退=别推
        cands.append({
            "wallet": w, "market_question": pos["market_question"], "outcome": pos["outcome"],
            "politics_pnl": pp, "politics_win_rate": _f(pol.get("win_rate")),
            "politics_roi": pol.get("roi"), "politics_trades": pol.get("total_trades"),
            "source_market": pool_mkt.get(w), "cross_ref_579": in579,
            "behavior": beh, "behavior_fact": bf.get("fact"),
            "score": round(score, 1), "ai_pick": False,
        })
        print(f"  ★ {w[:12]}… 政治 pnl={pp:.0f} win={pol.get('win_rate')} "
              f"{'∩579 ' if in579 else ''}{beh} · {pos['market_question'][:34]} {pos['outcome']}", flush=True)

    cands.sort(key=lambda c: -c["score"])
    cands = diversify(cands, keep=keep)           # 🎨 每盘最多 2 个进榜（有得选时）

    # 方法 C：对 top ai_top 跑 ⑥ AI 验证（烧 token、需后端在线；ai_top=0 关闭）
    if ai_top:
        targets = verify_targets(cands, ai_top)   # 🎨 精选名额跨盘优先
        print(f"\n方法 C：对 {len(targets)} 个候选（跨盘优先）跑 ⑥ AI 验证…", flush=True)
        ai_verify(targets, top=ai_top, fresh=True)
    _mark_disagreements(cands)        # 同盘分歧检测（纯代码，0 token）
    _mark_consensus(cands)            # 同侧专家共识（弱信号，与分歧对称）

    OUT.parent.mkdir(parents=True, exist_ok=True)
    method = "E_market_reverse_ai_verified" if ai_top else "E_market_reverse"
    i18n_en = {}                                  # 🌐 汇总各候选的翻译 → 顶层，前端一次注册
    for c in cands:
        i18n_en.update(c.pop("i18n_en", {}) or {})
    OUT.write_text(json.dumps({"as_of": as_of, "generated_at": int(time.time()),
                               "method": method, "candidates": cands, "i18n_en": i18n_en},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ 市场反向 · 政治专家候选 {len(cands)} 个写入 {OUT}", flush=True)
    return cands


if __name__ == "__main__":
    scan(ai_top=int(os.environ.get("AI_TOP", "5")))   # 轮询设 AI_TOP=0 关 ⑥（纯免费扫层）
