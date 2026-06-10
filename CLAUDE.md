# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

**smart-money-decoder**：输入 Polymarket 交易者钱包地址，找出其最大政治预测盘仓位，结合实时新闻生成 AI 解读卡片。只读 API，不涉及交易或私钥。

## 环境与运行

```bash
# 激活虚拟环境（所有命令都要在这个前缀下跑）
source .venv/bin/activate   # 或直接用 .venv/bin/python

# 安装依赖
.venv/bin/pip install -r requirements.txt

# 跑 mock 测试（无网络，秒出结果）
.venv/bin/python tests/test_position.py
.venv/bin/python tests/test_activity.py

# 跑完整流程（需要真实网络 + API key）
.venv/bin/python verify_activity_news.py
```

## 必填环境变量（.env）

```
TAVILY_API_KEY=...        # 新闻搜索，来自 app.tavily.com
CLASSROOM_API_KEY=...     # 课堂 AI 网关，老师分配，pending 时返回 403
```

## 架构：三层数据层 → 解码层 → 渲染层

```
fetcher/polymarket.py   →  get_top_political_position(address)
fetcher/activity.py     →  get_entry_time(address, condition_id)
fetcher/news.py         →  get_news_for_market(market_question, entry_time)
                                    ↓
analyzer/decoder.py     →  decode(position, entry_time, news)   ← 待建
                                    ↓
renderer/card.py        →  render(decoded_card)                 ← 待建
main.py                 →  串联入口                              ← 待建
```

**数据流**：
1. `polymarket.py` 发 2 次 HTTP（data-api 拿持仓，gamma-api 批量拿 tags），本地过滤出最大政治仓位（>$5,000，tag slug 含 `politics`，未结算）
2. `activity.py` 最多翻 3 页（150 条）activity 记录，本地过滤出目标市场最近一次 BUY TRADE 的时间戳
3. `news.py` 用课堂 AI 网关提取关键词（haiku-4.5），用 Tavily 搜新闻（时间窗：entry_time 前7天后3天），结果缓存在 `.cache/news/`
4. `analyzer/decoder.py`（待建）：调课堂网关 **sonnet-4-6** 生成解读卡片

## 已验证的 API 坑（别重蹈覆辙）

| 坑 | 结论 |
|----|------|
| Gamma events 多值参数 | 必须用 `[("id", id1), ("id", id2)]`，逗号分隔会返回 422 |
| Gamma/Data API category 过滤 | 参数传了被忽略，必须本地按 tag slug 过滤 |
| activity conditionId 过滤 | 服务器端失效，必须拉全量本地过滤 |
| Tavily published_date 格式 | RFC 2822（"Mon, 01 Jun 2026..."），需用 `email.utils.parsedate_to_datetime` 转换 |
| 正确 positions API 地址 | `data-api.polymarket.com`（不是 `gamma-api`） |

## 开发期开关（.env 或环境变量）

```
USE_FAKE_KEYWORDS=true    # news.py：跳过 AI 关键词提取，用占位词（课堂 key 403 时用）
USE_DECODER_CACHE=false   # decoder.py（待建）：默认关，调 prompt 时需要每次看新输出
```

## 异常设计规范

三层数据层各有自定义异常：`PolymarketAPIError` / `ActivityAPIError` / `NewsError`，全部携带 `reason`（机器读枚举）和 `message`（中文人读）。公开入口函数捕获后返回 `{"error": True, "reason": "...", "message": "..."}` 字典，不向上抛。

## 课堂 AI 网关调用方式

```python
# 不用 anthropic SDK，直接 requests.post
resp = requests.post(
    "https://4dm65e698a.execute-api.us-west-2.amazonaws.com/prod/invoke",
    headers={"Content-Type": "application/json", "x-api-key": CLASSROOM_API_KEY},
    json={"model": "claude-sonnet-4-6", "input": prompt, "maxTokens": 2000},
    timeout=15,
)
output = resp.json()["output"]   # 结果在 output 字段，不是 content[0].text
```

关键词提取と AI 解码统一用 `claude-sonnet-4.5`（点号，不是横杠）。网关只开放了 sonnet，haiku 返回 502。关键词提取 maxTokens: 100，解码 maxTokens: 2000。

## 解码层设计（analyzer/decoder.py，待实现）

**输入**（assembled dict）：
- 持仓：`market_question`, `outcome`, `entry_price`(可 None), `current_price`, `pnl_pct`, `cash_pnl`
- 时间：`entry_time`(可 None)
- 新闻：`articles`(可空列表), `time_anchored`(bool)

**输出卡片**：
- `what_bet`：AI 生成，一句大白话
- `catalyst`：AI 从 articles 里选 1-2 条，附 title + url + date
- `price_info`：代码直接填，不经 AI（防幻觉）
- `follow_advice`：AI 生成（还有空间 / 太迟了 / 错过了 + 理由）
- `confidence`：AI 按置信度矩阵判断（高 / 中 / 低）
- `warnings`：代码填，降级原因列表

**置信度矩阵**（优先级从高到低）：

| 条件 | 置信度 |
|------|--------|
| `articles` 为空 | 低（强制） |
| `pnl_pct > 60%` | 低 |
| `pnl_pct < 0%` 且（无新闻或时间未锚定） | 低 |
| `pnl_pct < 0%`（浮亏） | 中（封顶） |
| `time_anchored=False` | 中（封顶） |
| 有新闻 + anchored + `0% ≤ pnl_pct < 30%` | 高 |
| 有新闻 + anchored + `30% ≤ pnl_pct < 60%` | 中 |

**Prompt 硬约束**：新闻为空时禁止 AI 编造催化剂故事，必须如实写"无新闻支撑"。

## 当前进度（2026-06-07）

**已完成并验证**：
- `fetcher/polymarket.py`：持仓获取、政治类过滤、$5000 阈值（10 项 mock 测试通过）
- `fetcher/activity.py`：建仓时间查询、3 页翻页、BUY/TRADE 过滤（8 项 mock 测试通过）
- `fetcher/news.py`：关键词提取、Tavily 搜索、时间窗计算、文件缓存（两条时间窗分支均验证）

**正在进行**：
- 解码层 `analyzer/decoder.py` 的 prompt 逐句打磨（设计已定，尚未写代码）

**待做**：
- `analyzer/decoder.py`：AI 解码，调课堂网关 sonnet-4-6
- `renderer/card.py`：终端卡片渲染
- `main.py`：串联所有层的入口

**待解决**：
- 课堂网关已通（claude-sonnet-4.5，点号不是横杠），USE_FAKE_KEYWORDS 可改回 false ✅
- 置信度矩阵的 30%/60% 阈值需用真实仓位数据校准
- **【Bug】activity.py conditionId 不匹配**：`positions` 接口返回的 `conditionId` 与 `activity` 接口记录里的 `conditionId` 不是同一个字段语义——同一个大事件下的子市场（如 "before 2027" vs "by September 30"）各有不同 conditionId，导致 `get_entry_time()` 几乎总是返回 None。修复方向：改用 `eventSlug` 做匹配（activity 和 positions 里该字段一致），或在找到 position 的 conditionId 后先通过 Gamma API 查出同一 event 下的所有 conditionId，再逐一匹配 activity 记录。修复前需完整验证，demo 后处理。


"本项目可用命令:/checkpoint —— 整理进度并存档"