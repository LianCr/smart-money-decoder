# Smart Money Decoder

A Python tool that tracks large political bettors on [Polymarket](https://polymarket.com), finds their biggest position, and explains **why** they likely made that bet — using real news from around the time they entered.

## What it does

Given a wallet address, the tool:

1. **Finds the biggest political position** — scans all holdings, filters to politics markets with value > $5,000 USDC
2. **Locates the entry time** — searches recent trade activity to find when they first bought in
3. **Fetches relevant news** — uses AI to extract search keywords from the market title, then pulls news articles from the ±7 day window around the entry date
4. **Generates an analysis card** *(coming soon)* — AI explains the trade in plain language, links it to news catalysts, and assesses confidence

## Demo output

```
============================================================
  1. Polymarket 持仓 API
============================================================
结果 : ✅ 找到最大政治仓位
  市场问题  : Iran closes its airspace by June 8?
  买入方向  : Yes
  持仓价值  : $256,171 USDC
  买入均价  : 0.9847
  当前市价  : 0.999
  浮动盈亏  : +1.4%
  结算时间  : 2026-05-31
  市场规则  : This market will resolve to "Yes" if Iran initiates
              a major closure of its airspace...

============================================================
  3. Tavily 新闻 API
============================================================
  搜索关键词  : Iran airspace closes
  返回文章数  : 5 条

  [1] Israel says it has struck Iran after taking missile fire
       2026-06-08  |  www.politico.com
  ...
```

## Setup

**Requirements:** Python 3.10+

```bash
# 1. Clone and create virtual environment
git clone https://github.com/YOUR_USERNAME/smart-money-decoder.git
cd smart-money-decoder
python -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure API keys
cp .env.example .env
# Edit .env and fill in your keys
```

**Required API keys** (add to `.env`):

| Key | Where to get it |
|-----|----------------|
| `TAVILY_API_KEY` | [app.tavily.com](https://app.tavily.com) |
| `CLASSROOM_API_KEY` | Classroom AI gateway (instructor-provided) |

## Run

```bash
# Full demo (requires real network + API keys)
python demo.py

# Unit tests (no network needed)
python tests/test_position.py
python tests/test_activity.py
```

## Architecture

```
fetcher/
  polymarket.py   →  get_top_political_position(address)
  activity.py     →  get_entry_time(address, condition_id)
  news.py         →  get_news_for_market(market_question, entry_time)
                              ↓
analyzer/
  decoder.py      →  decode(position, entry_time, news)     [coming soon]
                              ↓
renderer/
  card.py         →  render(decoded_card)                   [coming soon]
```

**Data flow:**
- `polymarket.py` makes 2 HTTP calls: `data-api.polymarket.com` for positions, `gamma-api.polymarket.com` for event tags and resolution rules
- `activity.py` paginates up to 150 trade records to find the earliest buy timestamp; returns `None` gracefully if not found
- `news.py` calls the classroom AI gateway to extract 2–4 keywords from the market title, then searches Tavily with a time-windowed query; caches results in `.cache/news/`

## Development notes

**`USE_FAKE_KEYWORDS=true`** — skips the AI keyword extraction step (useful when the classroom gateway is unavailable). Set in `.env` or as an environment variable before running.

**`time_anchored`** — `True` if news results are pinned to the entry date window; `False` if the entry time wasn't found and the search fell back to the last 30 days. Downstream analysis will note this distinction.

**Known limitation:** For very active traders, the entry time may not be found within the 150-record lookup window, triggering the graceful fallback described above.
