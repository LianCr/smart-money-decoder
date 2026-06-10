"""
demo.py — 课堂演示脚本

展示三条 API 链：
  Polymarket 持仓 → Activity 建仓时间 → Tavily 新闻（含 AI 关键词提取）
"""

import os, sys, shutil
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# 使用真实 AI 关键词提取（网关已通）
os.environ["USE_FAKE_KEYWORDS"] = "false"
# 清空新闻缓存，确保 Tavily 实时发请求
if Path(".cache/news").exists():
    shutil.rmtree(".cache/news")

sys.path.insert(0, ".")
from fetcher.polymarket import get_top_political_position
from fetcher.activity   import get_entry_time
from fetcher.news       import get_news_for_market

WALLET = "0x7c3db723f1d4d8cb9c550095203b686cb11e5c6b"

def divider(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ─────────────────────────────────────────────────────────────
divider("1. Polymarket 持仓 API")
# ─────────────────────────────────────────────────────────────
print(f"请求 : GET data-api.polymarket.com/positions")
print(f"       + GET gamma-api.polymarket.com/events（批量拿 tags）")
print(f"参数 : user={WALLET[:20]}...  过滤: tag=politics, value>$5,000")
print()

position = None
try:
    position = get_top_political_position(WALLET)
    if position.get("error"):
        print(f"结果 : ❌ {position['reason']} — {position['message']}")
    else:
        entry_p = position.get("entry_price")
        pnl     = position.get("pnl_pct", 0)
        pnl_str = f"{pnl:+.1f}%" if pnl is not None else "未知"
        print(f"结果 : ✅ 找到最大政治仓位")
        print(f"  市场问题  : {position['market_question']}")
        print(f"  买入方向  : {position['outcome']}")
        print(f"  持仓价值  : ${position['position_value']:,.0f} USDC")
        print(f"  买入均价  : {entry_p if entry_p else '未知'}")
        print(f"  当前市价  : {position['current_price']:.3f}")
        print(f"  浮动盈亏  : {pnl_str}")
        res_date = position.get("resolution_date", "")
        res_date_str = res_date[:10] if res_date else "未知"
        res_criteria = position.get("resolution_criteria") or "未知"
        print(f"  结算时间  : {res_date_str}")
        print(f"  市场规则  : {res_criteria}")
except Exception as e:
    print(f"结果 : ❌ 异常 — {e}")

# ─────────────────────────────────────────────────────────────
divider("2. Polymarket Activity API")
# ─────────────────────────────────────────────────────────────
print(f"请求 : GET data-api.polymarket.com/activity")
print(f"参数 : user={WALLET[:20]}...  limit=50（最多翻3页/150条）")
print(f"过滤 : 本地匹配 conditionId + side=BUY + type=TRADE")
print()

entry_time = None
if position and not position.get("error"):
    condition_id = position.get("market_id")
    try:
        entry_time = get_entry_time(WALLET, condition_id)
        if entry_time:
            dt = datetime.fromtimestamp(entry_time, tz=timezone.utc)
            print(f"结果 : ✅ 找到建仓时间")
            print(f"  时间戳 : {entry_time}")
            print(f"  日期   : {dt.strftime('%Y-%m-%d %H:%M UTC')}")
        else:
            print(f"结果 : ⚠️  entry_time = None（系统降级）")
            print(f"  原因 : 该交易者持仓已久，建仓记录超出前150条查询范围")
            print(f"  处理 : 如实返回 None，下游新闻模块走「近30天」兜底搜索")
            print(f"         time_anchored=False，AI解读时标注「建仓时间未知」")
    except Exception as e:
        print(f"结果 : ❌ 异常 — {e}")
else:
    print("结果 : ⏭  跳过（上一步未找到仓位）")

# ─────────────────────────────────────────────────────────────
divider("3. Tavily 新闻 API")
# ─────────────────────────────────────────────────────────────
print(f"请求 : 课堂网关 → claude-sonnet-4.5 提取关键词")
print(f"       → Tavily search（topic=news）")
print(f"参数 : entry_time={'None（降级→近30天）' if not entry_time else '前7天后3天时间窗'}")
print()

news_result = None
if position and not position.get("error"):
    market_q = position["market_question"]
    print(f"市场标题  : {market_q}")
    print(f"           ↑ 来自第1段实时拉取，全程无写死数据")
    print()
    try:
        news_result = get_news_for_market(market_q, entry_time)
        if news_result.get("error"):
            print(f"结果 : ❌ {news_result['reason']} — {news_result['message']}")
        else:
            anchored = news_result["time_anchored"]
            articles = news_result["articles"]
            print(f"结果 : ✅ 新闻搜索完成")
            print(f"  搜索关键词  : {news_result['search_query']}")
            print(f"  time_anchored: {anchored}{'（时间窗锚定）' if anchored else '（降级，近30天）'}")
            print(f"  返回文章数  : {len(articles)} 条")
            print()
            for i, a in enumerate(articles, 1):
                print(f"  [{i}] {a['title'][:62]}")
                print(f"       {a['published_at']}  |  {a['source']}")
    except Exception as e:
        print(f"结果 : ❌ 异常 — {e}")
else:
    print("结果 : ⏭  跳过（上一步未找到仓位）")

print(f"\n{'='*60}")
print(f"  Demo 完成")
print(f"{'='*60}\n")
