#!/usr/bin/env python3
"""
briefing/market_context.py — MarketContextSynthesizer（Phase 1 MVP）

全管道：Heisenberg(falcon) 异动价格 ➔ GDELT 截面拦截(as-of) ➔ 441-token LLM 重排 ➔ 语义合成
→ Market Context JSON（timeline 卡 + 顶部宏观综述）。

🔴 七条边界焊死：
1. 因果→时间相关：price_impact 措辞"该事件前后价格变动 X%"，**绝不说"导致"**。
2. Burnham 教训：重排是文章级挑"最可能关联"，呈现为关联非 THE cause；同窗多事件标"合计不可归因"。
3. 找不到催化剂→诚实留白："价格异动 X%，未找到明确新闻催化剂"，绝不硬凑。
4. As-of 防泄漏：GDELT 文件 ≤ t_jump；568 价格窗 ≤ as_of，绝不偷看未来。
5. 数据降级：无价跳过、垃圾 slug 过滤。
6. 综述=客观宏观无判断：禁导向/恐吓词。
7. 按 (market, as_of) 缓存。
"""

import csv
import hashlib
import io
import json
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from fetcher.heisenberg import AGENTS, call, paginate, results

load_dotenv()

GKG_URL = "http://data.gdeltproject.org/gdeltv2/{stamp}.gkg.csv.zip"
C_DATE, C_SRC, C_THEMES, C_PERSONS, C_ORGS, C_TONE, C_URL = 1, 3, 7, 9, 11, 15, 4
CLASSROOM_API_URL = "https://4dm65e698a.execute-api.us-west-2.amazonaws.com/prod/invoke"
KEY = os.environ.get("CLASSROOM_API_KEY")
GATEWAY_MODEL = "claude-sonnet-4.5"
CACHE_DIR = Path(".cache/market_context")
# 新闻密度开关（默认中档：4 个跳变·阈值 5%·每跳 2 条 ≈ 10 条/盘）。仍锚在真跳变上、不破红线。
# 调密集(top=6/pick=3≈16条)更接近 Polymarket 但 +~3k token/钱包；调 top=2 回到最省的 ~6 条。
JUMP_TOP = int(os.environ.get("GMT_JUMP_TOP", "4"))
JUMP_MIN_DELTA = float(os.environ.get("GMT_JUMP_MIN_DELTA", "0.05"))
JUMP_PICK = int(os.environ.get("GMT_JUMP_PICK", "2"))          # 每个跳变 LLM 重排挑几条
# 守卫：导向词（含行为旗标可能诱发的判断词，绝不替用户拍板）
DIRECTIVE_WORDS = ["建议跟单", "建议跟", "该跟", "别跟", "该走", "值得跟", "胜率高", "稳赚", "必赢",
                   "推荐跟", "跟单价值", "充当炮灰", "压榨殆尽", "飙升", "切勿盲目"]
FEAR_WORDS = ["致命", "扼杀", "毁灭", "黑天鹅", "灾难", "崩盘", "末日"]


# ── 工具 ─────────────────────────────────────────────────────────────────────
def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _parse_ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _gkg(url):
    try:
        r = requests.get(url, timeout=60)
        if r.status_code != 200:
            return []
        z = zipfile.ZipFile(io.BytesIO(r.content))
        return list(csv.reader(io.StringIO(z.read(z.namelist()[0]).decode("utf-8", "ignore")), delimiter="\t"))
    except Exception:
        return []


def _title(url):
    seg = re.sub(r"\.(html?|php|aspx?)$", "", re.sub(r"[?#].*$", "", url).rstrip("/").split("/")[-1])
    seg = re.sub(r"[-_]([0-9a-f]{12,}|\d{6,})$", "", seg)   # 切除尾部 ID/hash
    seg = re.sub(r"^\d+[-_]?", "", seg)                     # 切除头部数字
    return re.sub(r"[-_]+", " ", seg).strip()


def _gateway(prompt, max_tokens=900):
    r = requests.post(CLASSROOM_API_URL, headers={"Content-Type": "application/json", "x-api-key": KEY},
                      json={"model": GATEWAY_MODEL, "input": prompt, "maxTokens": max_tokens}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"gateway {r.status_code}: {r.text[:160]}")
    return r.json().get("output", "")


# ── ① Heisenberg：找显著价格跳变（≤ as_of，边界4）──────────────────────────────
def find_price_jumps(token, as_of, min_delta=0.08, top=2):
    end = int(datetime.strptime(as_of, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=23, minute=59).timestamp())
    start = end - 30 * 86400
    rs = results(call(AGENTS["candles"][0], {"token_id": token, "interval": "1d",
                                             "start_time": str(start), "end_time": str(end)}))
    rs = sorted(rs, key=lambda r: str(r.get("candle_time", "")))
    closes = [(str(r.get("candle_time", ""))[:10], _f(r.get("close"))) for r in rs if _f(r.get("close")) is not None]
    jumps = []
    for i in range(1, len(closes)):
        d0, p0 = closes[i - 1]
        d1, p1 = closes[i]
        if d1 > as_of:                                   # 边界4：绝不取 as_of 之后
            break
        if abs(p1 - p0) >= min_delta:
            jumps.append({"date": d1, "p_before": round(p0, 4), "p_after": round(p1, 4),
                          "delta": round(p1 - p0, 4)})
    jumps.sort(key=lambda j: -abs(j["delta"]))
    return jumps[:top]


# ── ② GDELT 截面（≤ t_jump，边界4）+ ③ 硬过滤 + LLM 重排（边界1/2/3）──────────────
def gdelt_for_jump(entity_terms, t_jump, outcome_label):
    day0 = datetime.strptime(t_jump, "%Y-%m-%d")
    seen, cand = set(), []
    for dd in range(2, -1, -1):                          # [t_jump-2d, t_jump]，全 ≤ t_jump
        day = (day0 - timedelta(days=dd)).strftime("%Y%m%d")
        for t in ("094500", "194500"):
            for row in _gkg(GKG_URL.format(stamp=day + t)):
                if len(row) <= C_TONE:
                    continue
                blob = (row[C_PERSONS] + " " + row[C_ORGS] + " " + row[C_URL]).lower()
                if not any(e in blob for e in entity_terms):
                    continue
                u = re.sub(r"[?#].*$", "", row[C_URL]).lower()
                ti = _title(row[C_URL])
                if u in seen or len(ti) < 12:             # 边界5：去重 + 滤垃圾 slug
                    continue
                seen.add(u)
                cand.append({"title": ti, "src": row[C_SRC], "date": row[C_DATE][:8],
                             "url": row[C_URL].strip(),       # 文章链接(DocumentIdentifier)，供统一看板 ⑤ 可点击
                             "tone": _f(row[C_TONE].split(",")[0]) if "," in row[C_TONE] else None})
    if not cand:
        return []                                        # 边界3：无候选 → 上层留白
    # LLM 重排（边界1/2：挑最可能关联、时间相关非因果）
    prompt = (
        f"某预测市场「{outcome_label}」在某日价格发生显著跳变。下面是该跳变**之前/当日**的相关新闻标题。\n"
        f"请挑出 1-{JUMP_PICK} 条**最可能与这次价格跳变时间上关联**的新闻（重大事件/硬结果），"
        "🔴 只判时间关联、**不要断定因果**。每条给**简体中文**客观一句话事实陈述(fact)。无强关联就返回空数组。\n"
        '只输出 JSON：[{"title":"逐字来自下方","source":"","fact":"简体中文客观一句话,不用导致/必然等词"}]\n\n标题：\n'
        + "\n".join(f"- [{c['src']}] {c['title']}" for c in cand[:25])
    )
    out = _gateway(prompt, 600)
    m = re.search(r"\[.*\]", out, re.DOTALL)
    picked = []
    if m:
        try:
            for p in json.loads(m.group(0))[:JUMP_PICK]:
                # 回填日期/来源（从候选里按标题匹配）
                src = next((c for c in cand if str(p.get("title", ""))[:20] in c["title"]), None)
                picked.append({"title": p.get("title"), "source": p.get("source") or (src["src"] if src else ""),
                               "date": src["date"] if src else "", "fact": p.get("fact", ""),
                               "url": src["url"] if src else ""})
        except json.JSONDecodeError:
            pass
    return picked, len(cand), len(prompt) + len(out)


# ── ②b 钱包近 48h 真实动作流 → 三态行为旗标（最高权重信号·事实陈述不下判断）─────────
def get_behavior_flags(wallet, cid, as_of):
    """信念增强(加仓) / 主力撤退(减仓) / 没动。措辞=事实，判断留给用户（红线#3）。"""
    if not wallet:
        return None
    end = datetime.strptime(as_of, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=23, minute=59, second=59)
    try:
        trades = paginate(AGENTS["trades"][0],
                          {"proxy_wallet": wallet, "condition_id": cid,
                           "start_time": str(int((end - timedelta(hours=48)).timestamp())),
                           "end_time": str(int(end.timestamp()))}, max_pages=10)
    except Exception:
        return None

    def agg(hours):
        cut = end - timedelta(hours=hours)
        b = s = 0
        bu = su = 0.0
        for tr in trades:
            ts = _parse_ts(tr.get("timestamp"))
            if not ts or ts < cut:
                continue
            cost = (_f(tr.get("size")) or 0) * (_f(tr.get("price")) or 0)
            if str(tr.get("side", "")).upper() == "BUY":
                b += 1
                bu += cost
            elif str(tr.get("side", "")).upper() == "SELL":
                s += 1
                su += cost
        return {"buys": b, "sells": s, "buy_usd": round(bu, 0), "sell_usd": round(su, 0)}

    w3, w24, w48 = agg(3), agg(24), agg(48)
    if w24["sells"] >= 3 or (w24["sell_usd"] > w24["buy_usd"] and w24["sell_usd"] > 500):
        flag = "EXIT"
        fact = f"过去 24h 出现大额 SELL 流：{w24['sells']} 笔、合计 ${w24['sell_usd']:,.0f}，持仓在缩小"
        note = "动态行为：主力在分批减仓/获利了结（事实陈述，是否跟随由你裁决）"
    elif w3["buys"] >= 3 or w3["buy_usd"] > 1000 or (w24["sell_usd"] == 0 and w24["buys"] >= 3 and w24["buy_usd"] > 1000):
        flag = "ADD"
        fact = (f"过去 3h {w3['buys']} 笔 BUY(${w3['buy_usd']:,.0f}) / 24h {w24['buys']} 笔 BUY(${w24['buy_usd']:,.0f})"
                "，长期持仓刚被新一轮加仓激活")
        note = "动态行为：信念增强/加仓（事实陈述，跟单价值由你裁决）"
    else:
        flag = "STATIC"
        fact = f"近 48h 仅 {w48['buys']} 买 / {w48['sells']} 卖，无显著动作（沉闷持仓）"
        note = "动态行为：基本没动"
    return {"flag": flag, "fact": fact, "honest_note": note, "windows": {"3h": w3, "24h": w24, "48h": w48}}


# ── ④ 语义合成 ───────────────────────────────────────────────────────────────
def synthesize(cid, as_of, entity_terms, outcome="Yes", wallet=None):
    m = (results(call(AGENTS["markets"][0], {"condition_id": cid})) or
         results(call(AGENTS["markets"][0], {"condition_id": cid, "closed": "True"})))[0]
    q = m.get("question", "")
    token = m["side_a_token_id"] if str(m.get("side_a_outcome")).lower() == outcome.lower() else m["side_b_token_id"]
    side_label = f"{q} · {outcome}"

    behavior = get_behavior_flags(wallet, cid, as_of)     # 巨鲸近48h动作流 = 最高权重信号

    jumps = find_price_jumps(token, as_of, min_delta=JUMP_MIN_DELTA, top=JUMP_TOP)
    events, tok_used = [], 0
    for j in jumps:
        cats_res = gdelt_for_jump(entity_terms, j["date"], side_label)
        cats, ncand, t = (cats_res if cats_res else ([], 0, 0))
        tok_used += t
        sign = "+" if j["delta"] >= 0 else ""
        impact = f"{outcome} 价格变动 {sign}{j['delta']*100:.0f}%（{j['p_before']*100:.0f}% → {j['p_after']*100:.0f}%）"
        if cats:                                          # 同窗多条 → 标合计不可归因（边界2）
            multi = " · 同窗多条,合计不可归因到单条" if len(cats) > 1 else ""
            for c in cats:
                events.append({
                    "timestamp": j["date"], "type": "catalyst", "title": c["title"], "source": c["source"],
                    "url": c.get("url", ""),
                    "price_impact_string": impact, "fact_summary": c["fact"],
                    "temporal_note": "该事件与价格变动时间相关，非确证因果" + multi,
                })
        else:                                             # 边界3：诚实留白（行为感知=内幕/薄盘）
            blank = "价格异动，但该时间窗 GDELT 三层洗不出对题公开新闻"
            if behavior and behavior["flag"] == "ADD":
                blank += "——而该钱包同期大举加仓：有人重金押注却无任何公开事实支撑，无法用公开信息解释此异动（可能内幕抢跑/薄盘控盘，系统无法证实，散户慎之）。"
            else:
                blank += "（可能抢跑/薄盘/内幕，系统无法证实）。"
            events.append({
                "timestamp": j["date"], "type": "price_only", "title": None, "source": None,
                "price_impact_string": impact, "fact_summary": blank,
                "temporal_note": "未归因（无强关联新闻）",
            })

    # 巨鲸动作同轴陈列进时间线（最高权重，事实陈述）
    if behavior and behavior["flag"] != "STATIC":
        events.append({
            "timestamp": as_of, "type": "behavior",
            "title": f"巨鲸动作旗标 · {behavior['flag']}", "source": "Heisenberg 556 Trades",
            "price_impact_string": None, "fact_summary": behavior["fact"],
            "temporal_note": behavior["honest_note"],
        })

    # 顶部宏观综述（巨鲸行为=最高权重输入；客观无判断；守卫）
    facts = "；".join(e["fact_summary"] for e in events if e.get("title") or e.get("type") == "behavior")
    summary = ""
    if facts:
        beh = f"【钱包动态行为·最高权重线索】{behavior['fact']}。" if behavior else ""
        sp = (f"市场「{q}」。{beh}以下为已锁定 as-of({as_of}) 的客观事实。"
              f"写一段 ≤140 字**简体中文冷静客观宏观综述**：**把巨鲸动作作为最重要线索如实点出**，再陈列新闻局势；"
              f"**绝不给投资判断或倾向**（禁该跟/别跟/胜率/值得/跟单价值/edge/炮灰等词），不夸大不恐吓。\n事实：{facts}")
        summary = _gateway(sp, 320).strip()
        tok_used += len(sp) + len(summary) * 2
    bad = [w for w in DIRECTIVE_WORDS + FEAR_WORDS if w in summary]
    if bad:
        summary = "（综述含导向/恐吓词已被守卫拦下，待修）"

    return {
        "market_context": {
            "market_id": cid, "market_slug": m.get("slug"), "market_question": q,
            "analyzed_side": outcome, "as_of": as_of, "wallet": wallet,
            "behavioral_flag": behavior,                  # 三态行为旗标（信念增强/主力撤退/没动）
            "ai_experimental_summary": summary,
            "timeline_events": events,
            "_audit": {"jumps_found": len(jumps), "events": len(events),
                       "behavior": behavior["flag"] if behavior else None,
                       "teacher_tokens_approx": int(tok_used / 3.5),
                       "boundaries": "因果→时间相关 · 无催化剂留白(行为感知内幕) · 价格窗≤as_of · 行为=事实非判断 · 综述无判断"},
        }
    }


def load_or_build(cid, as_of, entity_terms, outcome="Yes", wallet=None):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(f"{cid}|{as_of}|{outcome}|{(wallet or '').lower()}".encode()).hexdigest()
    p = CACHE_DIR / f"{key}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    obj = synthesize(cid, as_of, entity_terms, outcome, wallet=wallet)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return obj


if __name__ == "__main__":
    # 节点：Starmer out by June 30（6/19 Burnham 跳变,已知真相）· as_of=6/20 · 钱包=ImJustKen
    CID = "0xbee2cd40473495f713c69b9dfbce9fc2837fa4011568222c83c83bb773e35053"
    ENTITY = ["starmer", "burnham", "labour"]            # 实体扩展(含 Burnham,破粒度错配)
    WALLET = "0x9d84ce0306f8551e02efef1680475fc0f1dc1344"
    print("MarketContextSynthesizer · Starmer out by June 30 · as_of=2026-06-20 · +巨鲸行为流\n")
    obj = load_or_build(CID, "2026-06-20", ENTITY, "Yes", wallet=WALLET)
    print(json.dumps(obj, ensure_ascii=False, indent=2))
