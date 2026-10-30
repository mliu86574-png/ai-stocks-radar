# AI Stocks Radar

A daily, automated radar for US AI stocks: when each company reports, what the market expects, where money appears to be flowing, how institutions, insiders and short sellers are positioned, and how the group is performing. Free public data only, rebuilt twice every weekday by GitHub Actions.

> 中文简介：美股 AI 股票雷达，每个交易日自动更新两次。看板包括：财报日历（日期、盘前/盘后、EPS 一致预期、预期修正、近 4 季超预期记录、历史财报后股价波动）、资金流向（基于量价的 20 日净流入估算、CMF、MFI、OBV、相对成交量，以及半导体/软件/AI 主题 ETF）、机构与空头（13F 机构增减持、内部人买卖、空头回补天数）和行情表现（等权 AI 篮子 vs 纳指，四个细分板块）。支持中英文切换。

**Live dashboard:** https://mliu86574-png.github.io/ai-stocks-radar/

## Latest

<!-- RADAR:START -->
AI basket (equal weight): **-3.6%** on the day, **+49.5%** YTD vs QQQ +16.4%.

**Next earnings**

| Date | Company | Timing | EPS consensus | Typical move |
|---|---|---|---:|---:|
| 2026-11-02 | AAPL | after close | 1.98 | ±3.4% |
| 2026-11-02 | PLTR | after close | 0.33 | ±12.6% |
| 2026-11-03 | AMD | after close | 1.68 | ±11.0% |
| 2026-11-03 | ANET | after close | 0.99 | ±8.3% |
| 2026-11-03 | SMCI | after close | 1.04 | ±18.6% |
| 2026-11-04 | ARM | after close | 0.22 | ±2.8% |
| 2026-11-09 | CEG | before open | 3.90 | ±4.7% |
| 2026-11-17 | NVDA | after close | 2.49 | ±3.0% |

**Volume-based flow signals:** inflow AAPL; outflow NVDA, MU, ARM, GOOGL, META, NOW, SNOW, ANET, DELL, SMCI, CEG.

_Last updated 2026-10-30 22:23 UTC._
<!-- RADAR:END -->

## What it covers

| Section | Contents | Source |
|---|---|---|
| Overview | Equal-weight AI basket vs Nasdaq-100 and S&P 500; four sub-groups (chips, platforms & cloud, AI software, servers/network/power); auto summary | Yahoo Finance |
| Earnings calendar | Next report date and countdown, before-open/after-close, EPS consensus and number of estimates, year-ago EPS, one-month estimate revision, beats in the last four quarters, typical post-earnings move, recently reported results with stock reaction | Nasdaq.com (Zacks), Yahoo Finance |
| Fund flows | Dollar volume, relative volume, estimated 20-day net flow, Chaikin money flow, money flow index, on-balance volume, combined signal; the same for sector and theme ETFs (SMH, SOXX, IGV, AIQ, BOTZ, QQQ, SPY) | Yahoo Finance |
| Institutions, insiders & shorts | Institutional ownership, 13F net change, holders increasing/decreasing and new/sold-out, insider net shares over three months, short interest days to cover and change | Nasdaq.com |
| Performance | Price, returns, distance from 52-week high, RSI, trend, analyst consensus, distance to the one-year target | Yahoo Finance, Nasdaq.com |

The stock list and groups live in [`config.json`](config.json); edit it to track different names.

## About "fund flows"

True order-flow and ETF creation/redemption data are not free. This page estimates flows from daily price and volume, using standard indicators:

- **Estimated net flow (20D):** dollar volume on up days minus dollar volume on down days over 20 sessions.
- **CMF 20:** Chaikin money flow; above +0.05 suggests accumulation, below −0.05 distribution.
- **MFI 14:** money flow index; above 60 strong, below 40 weak.
- **OBV 20D:** change in on-balance volume over 20 sessions, measured in days of average volume.
- **Signal:** inflow or outflow when at least two of CMF, MFI and OBV agree.

Institutional changes come from quarterly 13F filings, which lag by up to 45 days after quarter end.

## How it works

```
GitHub Actions (weekdays 12:40 and 21:40 UTC, and on every code push)
  └─ python -m airadar.build
       ├─ sources.py    Yahoo chart API (OHLCV); Nasdaq.com earnings, 13F, insider, short interest, ratings
       ├─ analytics.py  returns, trend, volume-flow indicators, baskets, post-earnings reactions
       ├─ narrative.py  English and Chinese summaries filled from the numbers
       └─ dashboard.py  docs/index.html (ECharts, EN/中文 toggle)
  └─ commit data/, docs/, README.md
GitHub Pages serves docs/
```

If a Nasdaq request fails, the last successful value is reused from `data/nasdaq_cache.json` and marked as cached on the page. Tests in `tests/` run offline on synthetic data, including outage and cache cases.

```bash
pip install -e ".[dev]"
pytest
python -m airadar.build
```

## Notes

- Prices are daily and delayed. Earnings dates marked "est." are projected from past reporting patterns until the company confirms them.
- Personal, non-commercial project. Data belong to their providers.
- For information only. Not investment advice.

## License

MIT
