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


ORGANIZER_PROMPT = """你是一个**诚实的证据综合员**——不是顾问、不是裁判。
上方界面已用数据卡片向用户展示了【交易者画像、持仓动作、价格结构】的全部硬数字。**你绝不重复这些数字。**

下面给你这注的【双向催化剂证据】（每条带材质类型 + 市场真金白银的反应/测谎旗标）和玩家姿态(定性)。

任务：**只写卡片表达不了的东西**——把正反证据的张力、材质对比、市场测谎的矛盾，综合成 2–3 段短文，帮用户看清这副天平的"质感"：
- 支持侧 vs 威胁侧各是什么**材质**的证据（如"支持方多是周边压力，威胁方是当事人亲口表态"），材质轻重让用户自己掂。
- 哪些催化剂的**市场反应与其分类矛盾**（⚠️测谎）、这矛盾意味着什么张力（如"他否认下台，市场反而给'下台'定价"）。
- 诚实提示（拿不到价 / 同窗多条合计不可归因）。

🔴 铁律（违反即失败）：
- **绝不复述画像/动作/价格的任何数字**：rank/胜率/累计盈亏/均价/现价/浮盈亏 等一律不得出现，卡片已展示。也**不要**"一、交易者画像/二、持仓动作"这类重复卡片的分节。
- **只用给定证据，绝不编造**。
- **绝不判断、绝不建议**：不许"该跟/别跟/值得/胜率高/稳/好机会"等任何倾向。你综合张力，用户裁决。
- 冷静客观，不夸大不恐吓（"致命/崩塌"等情绪词禁用）。
- 结尾必须另起一行原样写：「系统已完成证据陈述，天平由你裁决。」

输出：纯文本中文，不要 markdown 代码块；可用极简小标题，但绝不重复卡片内容。"""


def _compact(b):
    """喂给整理器的精简材料：**不含画像/动作/价格的硬数字**（避免它复述卡片），
    只给定性姿态 + 双向催化剂（材质+市场反应）+ 诚实标注。"""
    who = b.get("who_trader_profile", {})
    rk = who.get("official_rank", {})
    pol = any("Politics" in str(c.get("category", "")) for c in who.get("category_specialization", []))
    ts = (b.get("what_position_actions") or {}).get("two_side_distribution", {})

    def cat_line(c):
        pr = c.get("price_reaction", {})
        r = (f"{pr.get('direction','')}{pr.get('move_pct','')}% {pr.get('market_check','')}"
             if pr.get("available") else "市场反应不可知")
        sw = " [同窗多条·合计不可归因到单条]" if pr.get("same_window") else ""
        return {"材质": c.get("type"), "证据": c.get("title"), "理由": c.get("reason"), "市场反应": r + sw}

    cats = b.get("catalysts", {})
    return {
        "市场": b.get("meta", {}).get("market"),
        "分析侧": b.get("meta", {}).get("analyzed_side"),
        "结算": b.get("meta", {}).get("settle"),
        "玩家姿态_定性勿复述数字": {
            "建仓类型": "两边对冲(非单边信念)" if ts.get("hedged") else "单边建仓(信念注)",
            "胜率谎言": _wr_lie(rk),
            "政治盘专长": pol,
        },
        "正向催化剂": [cat_line(c) for c in cats.get("positive", [])],
        "负向催化剂": [cat_line(c) for c in cats.get("negative", [])],
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
