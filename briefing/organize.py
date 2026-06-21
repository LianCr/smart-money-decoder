"""
briefing/organize.py — B 段：第三个 AI · 诚实整理器（③调味）

产品魂所在：读 A 段的结构化简报 → 整理成人话简报。**只整理、不判断**。
- 标材质（证据类型）/ 真伪（胜率谎言、对冲非信念、市场测谎⚠️、honesty_caveat、同窗合计）。
- 🔴 绝不出现"该跟/别跟/胜率高/值得"等任何导向或下注建议——你陈列，用户裁决。
- 冷静客观，不夸大、不恐吓、不卖确定性；结尾固定"天平由你裁决"。

"整理 vs 判断"的边界 = 这个模块的命门：整理 = 把已有证据讲清楚、标好材质；判断 = 替用户称重、给倾向。
只许前者。守卫（导向词/恐吓词）硬拦后者漏入。

模型：gateway=sonnet-4.5（现用）；bedrock=sonnet-4-6（预留分支、未接凭证）。烧老师 token（1 次 LLM）。
"""

import json
import os
import re

import requests
from dotenv import load_dotenv

# 复用双向催化剂已定的守卫词表与固定结语（DRY，同一套诚实纪律）
from analyzer.dual_catalyst import DIRECTIVE_WORDS, FEAR_WORDS, FIXED_CLOSING

load_dotenv()

CLASSROOM_API_URL = "https://4dm65e698a.execute-api.us-west-2.amazonaws.com/prod/invoke"
CLASSROOM_API_KEY = os.environ.get("CLASSROOM_API_KEY")
LLM_BACKEND = os.environ.get("DUAL_CATALYST_BACKEND", "gateway")
GATEWAY_MODEL = "claude-sonnet-4.5"
BEDROCK_MODEL = "claude-sonnet-4-6"   # 🔴 4.6 非 3.5；inference-profile id 等账号开好再填
MAX_TOKENS_OUT = 1200
REQUEST_TIMEOUT = 30


ORGANIZER_PROMPT = """你是一个**诚实的简报整理员**——不是顾问、不是裁判。
下面是一份关于某聪明钱钱包某持仓的【结构化简报数据】（代码算好的事实 + 双向催化剂证据，每条带"材质类型"和"市场反应/测谎旗标"）。

任务：整理成一份**清晰、冷静、人能读的简报**，让用户看清全貌：这个交易者是谁、做了什么、价格结构、以及支持/威胁这注的双向证据（连同各自的材质类型、市场真金白银的反应、任何"市场与分类不一致"的⚠️旗标）。

🔴 铁律（违反即失败）：
- **只整理给定数据**：绝不新增事实、绝不计算、绝不推断超出数据的东西。
- **绝不判断、绝不建议**：不许出现"该跟/别跟/值得跟/胜率高/赢面大/稳/好机会/建议"等任何导向或下注倾向。你陈列，用户裁决。
- **如实标材质与真伪、让用户自己掂份量**：把这些平实呈现、不替用户称重——
  · "胜率谎言"标注（高胜率但净亏）· "对冲玩家=非单边信念" · 催化剂的材质类型
  · 市场测谎⚠️（市场反应与 LLM 正负分类不一致）· honesty_caveat · 同窗多条新闻"合计、不可归因到单条"
- **冷静客观**：不夸大、不恐吓（"致命/崩塌"等情绪词一律不许）、不卖确定性。
- 结尾必须原样写这一句：「系统已完成证据陈述，天平由你裁决。」

输出：分区简报正文（交易者画像 / 持仓动作 / 价格结构 / 双向证据），纯文本中文，不要 markdown 代码块。"""


def _compact(b):
    """把结构化简报压成喂给 LLM 的精简材料（控 token，只留整理所需）。"""
    who = b.get("who_trader_profile", {})
    q, rk = who.get("quality", {}), who.get("official_rank", {})
    pol = [c for c in who.get("category_specialization", []) if "Politics" in str(c.get("category"))]
    act = (b.get("what_position_actions") or {}).get("actions", {})
    ts = (b.get("what_position_actions") or {}).get("two_side_distribution", {})
    un = (b.get("what_position_actions") or {}).get("unrealized", {})
    pc = b.get("price_context", {})

    def cat_line(c):
        pr = c.get("price_reaction", {})
        r = (f"{pr.get('direction','')}{pr.get('move_pct','')}% {pr.get('market_check','')}"
             if pr.get("available") else f"市场反应不可知({pr.get('reason','')})")
        sw = f" | {pr['same_window']}" if pr.get("same_window") else ""
        return {"材质": c.get("type"), "证据": c.get("title"), "日期": c.get("date"),
                "理由": c.get("reason"), "市场反应": r + sw}

    cats = b.get("catalysts", {})
    return {
        "市场": b.get("meta", {}).get("market"),
        "分析侧": b.get("meta", {}).get("analyzed_side"),
        "结算状态": b.get("meta", {}).get("settle"),
        "画像": {"风险分": q.get("combined_risk_score"), "flagged": q.get("flagged_metrics"),
                "曲线": q.get("equity_curve_pattern"),
                "官方榜": {"rank": rk.get("rank"), "win_rate": rk.get("win_rate"), "total_pnl": rk.get("total_pnl")},
                "政治盘专长": (pol[0] if pol else None),
                "胜率谎言提示": "高胜率但净PnL为负" if _wr_lie(rk) else None},
        "动作": {"建仓": act.get("entry_time"), "买入笔数": act.get("num_buys"),
                "均价": act.get("avg_entry_price"), "成本USD": act.get("net_cost_usd"),
                "两侧": {"对冲": ts.get("hedged"), "说明": ts.get("note")},
                "盈亏": {"金额": un.get("unrealized_pnl_usd"), "百分比": un.get("unrealized_pct"), "说明": un.get("note")}},
        "价格": {"现价": pc.get("current_price"), "隐含概率%": pc.get("implied_probability_pct"),
                "剩余空间%": pc.get("remaining_upside_pct_if_win"), "赔率": pc.get("odds_to_one"),
                "vs入场%": pc.get("price_delta_pct")},
        "正向催化剂": [cat_line(c) for c in cats.get("positive", [])],
        "负向催化剂": [cat_line(c) for c in cats.get("negative", [])],
        "天平摘要": cats.get("balance_summary"),
        "honesty_caveat": cats.get("honesty_caveat"),
    }


def _wr_lie(rk):
    try:
        return float(rk.get("win_rate", 0)) > 0.8 and float(rk.get("total_pnl", 0)) < 0
    except (TypeError, ValueError):
        return False


def _call_gateway(combined):
    resp = requests.post(CLASSROOM_API_URL,
                         headers={"Content-Type": "application/json", "x-api-key": CLASSROOM_API_KEY},
                         json={"model": GATEWAY_MODEL, "input": combined, "maxTokens": MAX_TOKENS_OUT},
                         timeout=REQUEST_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"gateway {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("output", "")


def _approx_tokens(t):
    return int(len(t) / 3.5)


def organize_briefing(briefing):
    """读结构化简报 → 整理成人话简报。返回 {text, guards, usage}。"""
    material = json.dumps(_compact(briefing), ensure_ascii=False, indent=2)
    combined = f"{ORGANIZER_PROMPT}\n\n=== 结构化简报数据 ===\n{material}"

    if LLM_BACKEND == "gateway":
        text = _call_gateway(combined)
    elif LLM_BACKEND == "bedrock":
        raise NotImplementedError("Bedrock 分支预留未接（model=claude-sonnet-4-6，非3.5）")
    else:
        raise ValueError(f"未知 LLM_BACKEND={LLM_BACKEND}")

    # 守卫：导向词（替用户判断=越界）+ 恐吓词
    directive_hits = [w for w in DIRECTIVE_WORDS if w in text]
    fear_hits = [w for w in FEAR_WORDS if w in text]
    if FIXED_CLOSING not in text:                      # 结尾固定句兜底补
        text = text.rstrip() + "\n\n" + FIXED_CLOSING

    return {
        "text": text,
        "guards": {"directive_hits": directive_hits, "fear_lexicon_hits": fear_hits},
        "usage": {"in_tokens": _approx_tokens(combined), "out_tokens": _approx_tokens(text)},
    }


if __name__ == "__main__":
    # 读 A 段缓存的结构化简报 → 整理（只烧整理器这一次 LLM）。
    from briefing.assemble import load_or_build_briefing

    KEN = "0x9d84ce0306f8551e02efef1680475fc0f1dc1344"
    b = load_or_build_briefing(KEN, "Yes", slug="starmer-out-by-may-31-2026")

    out = organize_briefing(b)
    print("=" * 82)
    print("B 段·第三个 AI 诚实整理器 · 人话简报")
    print("=" * 82)
    print(out["text"])
    print("\n" + "=" * 82)
    print("守卫:", "导向词", out["guards"]["directive_hits"] or "无",
          "· 恐吓词", out["guards"]["fear_lexicon_hits"] or "无")
    print(f"整理器 token≈{out['usage']['in_tokens']}in/{out['usage']['out_tokens']}out")
