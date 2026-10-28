"""Build: fetch -> analytics -> docs/index.html, data files and README block.

Run from the repository root:  python -m airadar.build
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from . import analytics as A
from . import dashboard, narrative, sources

ROOT = Path(__file__).resolve().parents[2]
START, END = "<!-- RADAR:START -->", "<!-- RADAR:END -->"


def _warn(msg):
    print(f"warning: {msg}", file=sys.stderr)


def _r(x, dp=2):
    return None if x is None else round(float(x), dp)


def _points(s: pd.Series, days: int | None = None, dp: int = 2) -> list:
    s = s.dropna()
    if s.empty:
        return []
    if days:
        s = s[s.index >= s.index[-1] - pd.Timedelta(days=days)]
    return [[d.strftime("%Y-%m-%d"), round(float(v), dp)] for d, v in s.items()]


def build(root: Path = ROOT, get_prices: Callable = sources.ohlcv,
          get_nasdaq: Callable = sources.nasdaq_symbol, get_calendar: Callable = sources.nasdaq_calendar,
          today: pd.Timestamp | None = None, pause: float = 0.25) -> dict:
    cfg = json.loads((root / "config.json").read_text())
    today = today or pd.Timestamp.now(tz="UTC").tz_localize(None)
    data = root / "data"
    data.mkdir(exist_ok=True)
    (root / "docs").mkdir(exist_ok=True)
    cache_path = data / "nasdaq_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    status: list[dict] = []
    stocks_cfg, etfs_cfg = cfg["stocks"], cfg.get("etfs", [])
    symbols = [s["symbol"] for s in stocks_cfg]

    # ------------------------------------------------ prices
    prices: dict[str, pd.DataFrame] = {}
    failed = []
    etf_syms = {e["symbol"] for e in etfs_cfg}
    for sym in symbols + [e["symbol"] for e in etfs_cfg]:
        try:
            prices[sym] = get_prices(sym, "etf" if sym in etf_syms else "stocks")
        except Exception as err:
            _warn(f"prices {sym}: {err}")
            failed.append(sym)
    status.append({"source": "Yahoo Finance", "item": "daily prices",
                   "ok": "ok" if not failed else ("failed" if len(failed) == len(symbols) + len(etfs_cfg) else "partial"),
                   "note": f"{len(prices)} ok" + (f"; failed: {', '.join(failed)}" if failed else "")})

    # ------------------------------------------------ Nasdaq per symbol, with last-good cache
    nd: dict[str, dict] = {s: {} for s in symbols}
    for kind in sources.NASDAQ_ENDPOINTS:
        ok = cached = bad = 0
        for sym in symbols:
            try:
                val = get_nasdaq(sym, kind)
                nd[sym][kind] = val
                cache.setdefault(sym, {})[kind] = {"value": val, "fetched": today.date().isoformat()}
                ok += 1
            except Exception as err:
                hit = cache.get(sym, {}).get(kind)
                if hit:
                    nd[sym][kind] = hit["value"]
                    cached += 1
                else:
                    bad += 1
                _warn(f"nasdaq {kind} {sym}: {err}")
            if pause:
                time.sleep(pause)
        status.append({"source": "Nasdaq.com", "item": kind,
                       "ok": "ok" if cached + bad == 0 else ("failed" if ok + cached == 0 else "cached"),
                       "note": f"{ok} fresh, {cached} cached, {bad} missing"})

    # ------------------------------------------------ earnings calendar for the upcoming dates
    window = cfg.get("earnings_window_days", 75)
    dates = sorted({(nd[s].get("earnings_date") or {}).get("date") for s in symbols} - {None})
    dates = [d for d in dates if 0 <= (pd.Timestamp(d) - today.normalize()).days <= window]
    cal: dict[str, dict] = {}
    cal_ok = cal_bad = 0
    for d in dates:
        try:
            day = get_calendar(d)
            cache.setdefault("_calendar", {})[d] = day
            cal_ok += 1
        except Exception as err:
            day = cache.get("_calendar", {}).get(d, {})
            cal_bad += 1
            _warn(f"calendar {d}: {err}")
        for sym, row in day.items():
            if sym in symbols and (nd[sym].get("earnings_date") or {}).get("date") == d:
                cal[sym] = row
        if pause:
            time.sleep(pause)
    status.append({"source": "Nasdaq.com", "item": "earnings calendar",
                   "ok": "ok" if cal_bad == 0 else "cached", "note": f"{cal_ok} dates fresh, {cal_bad} from cache"})
    # keep the cache small: drop calendar days in the past
    cache["_calendar"] = {d: v for d, v in cache.get("_calendar", {}).items() if d >= today.date().isoformat()}

    # ------------------------------------------------ per-stock rows
    closes = {s: df["close"] for s, df in prices.items()}
    stocks = []
    for s in stocks_cfg:
        sym = s["symbol"]
        df = prices.get(sym)
        row = {**s}
        if df is not None:
            row.update(A.performance(df))
            row.update(A.flows(df))
        for kind in ("institutional", "insider", "short", "summary", "ratings"):
            v = nd[sym].get(kind)
            if isinstance(v, dict):
                row.update(v)
        stocks.append(row)
    earnings = [A.earnings_view(s, closes.get(s), nd[s], cal, today, window, cfg.get("recent_window_days", 21))
                for s in symbols]
    earnings.sort(key=lambda e: (e["next_date"] or "9999", e["symbol"]))
    etfs = []
    for e in etfs_cfg:
        df = prices.get(e["symbol"])
        etfs.append({**e, **(A.performance(df) if df is not None else {}), **(A.flows(df) if df is not None else {})})

    # ------------------------------------------------ baskets and chart payload
    bench = cfg.get("benchmark", "QQQ")
    basket = A.basket(closes, symbols)
    basket_perf = A.performance(pd.DataFrame({"close": basket})) if not basket.empty else {}
    bench_perf = A.performance(prices[bench]) if bench in prices else {}
    start = basket.index[-1] - pd.Timedelta(days=730) if not basket.empty else None
    series = {}
    if start is not None:
        series["basket"] = _points(A.rebase(basket, start))
        if bench in closes:
            series["bench"] = _points(A.rebase(closes[bench], start))
        if "SPY" in closes:
            series["spy"] = _points(A.rebase(closes["SPY"], start))
    group_lines = []
    if not basket.empty:
        ytd0 = basket[basket.index < pd.Timestamp(year=basket.index[-1].year, month=1, day=1)]
        y_start = ytd0.index[-1] if not ytd0.empty else basket.index[0]
        for g, names in cfg["groups"].items():
            b = A.basket(closes, [s["symbol"] for s in stocks_cfg if s["group"] == g])
            if not b.empty:
                group_lines.append({"name": names, "data": _points(A.rebase(b, y_start))})
        if bench in closes:
            group_lines.append({"name": bench, "data": _points(A.rebase(closes[bench], y_start))})
    flow_parts = [A.flow_series(prices[s]) for s in symbols if s in prices]
    if flow_parts:
        series["flow"] = _points(pd.concat(flow_parts, axis=1).sum(axis=1, min_count=1) / 1e9, 400, 2)

    def bars(key, rows, scale=1.0, dp=2, reverse=True):
        rows = [(r["symbol"], r.get(key)) for r in rows if r.get(key) is not None]
        rows.sort(key=lambda x: x[1], reverse=reverse)
        return [{"k": k, "v": round(v * scale, dp)} for k, v in rows]

    payload = {
        "bench": bench, "series": series, "groups": group_lines,
        "bars": {
            "moves": bars("avg_move", [e for e in earnings if e["next_date"]], dp=1),
            "flow": bars("net_flow20", stocks, 1e-9),
            "relvol": bars("rel_vol", stocks),
            "inst": bars("net_pct", stocks),
            "perf": [{"k": s["symbol"], "m1": _r(s.get("m1"), 1), "ytd": _r(s.get("ytd"), 1)}
                     for s in sorted(stocks, key=lambda s: s.get("ytd") or -1e9, reverse=True)],
        },
    }
    text = {"overview": narrative.overview(stocks, basket_perf, bench_perf, bench, earnings),
            "earnings": narrative.earnings_text(earnings)}
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    ctx = {"updated": updated, "stocks": stocks, "groups": cfg["groups"], "etfs": etfs, "earnings": earnings,
           "basket_perf": basket_perf, "bench_perf": bench_perf, "bench": bench, "text": text,
           "status": status, "payload": payload}

    # ------------------------------------------------ outputs
    (root / "docs" / "index.html").write_text(dashboard.render(ctx), encoding="utf-8")
    cols = ["symbol", "group", "last", "d1", "w1", "m1", "ytd", "from_hi", "rsi14", "trend", "market_cap", "dollar_vol",
            "rel_vol", "net_flow20", "cmf20", "mfi14", "obv_days20", "flow", "inst_pct", "net_pct", "net_shares_3m",
            "days_to_cover", "si_change_pct", "rating", "target_1y"]
    pd.DataFrame(stocks).reindex(columns=cols).to_csv(data / "stocks.csv", index=False)
    (data / "earnings.json").write_text(json.dumps(earnings, indent=1, default=str), encoding="utf-8")
    if closes:
        pd.DataFrame(closes).sort_index().to_csv(data / "closes.csv", index_label="date")
    cache_path.write_text(json.dumps(cache, indent=1, default=str), encoding="utf-8")
    (data / "status.json").write_text(json.dumps({"updated": updated, "sources": status}, indent=1), encoding="utf-8")
    readme = root / "README.md"
    if readme.exists():
        update_readme(readme, readme_block(earnings, stocks, basket_perf, bench_perf, bench, updated))
    return {"stocks": stocks, "earnings": earnings, "etfs": etfs, "status": status, "basket": basket}


def readme_block(earnings, stocks, bp, bench_p, bench, updated) -> str:
    def p(x):
        return "–" if x is None else f"{x:+.1f}%"

    lines = [f"AI basket (equal weight): **{p(bp.get('d1'))}** on the day, **{p(bp.get('ytd'))}** YTD "
             f"vs {bench} {p(bench_p.get('ytd'))}.", "", "**Next earnings**", "",
             "| Date | Company | Timing | EPS consensus | Typical move |", "|---|---|---|---:|---:|"]
    for e in [e for e in earnings if e["next_date"]][:8]:
        when = {"pre": "before open", "after": "after close"}.get(e.get("time", "tbd"), "TBC")
        cons = "–" if e.get("eps_forecast") is None else f"{e['eps_forecast']:.2f}"
        mv = "–" if e.get("avg_move") is None else f"±{e['avg_move']:.1f}%"
        lines.append(f"| {e['next_date']} | {e['symbol']} | {when} | {cons} | {mv} |")
    flows_in = [s["symbol"] for s in stocks if s.get("flow") == "in"]
    flows_out = [s["symbol"] for s in stocks if s.get("flow") == "out"]
    lines += ["", f"**Volume-based flow signals:** inflow {', '.join(flows_in) or 'none'}; "
              f"outflow {', '.join(flows_out) or 'none'}.", "", f"_Last updated {updated} UTC._"]
    return "\n".join(lines)


def update_readme(readme: Path, block: str) -> None:
    text = readme.read_text(encoding="utf-8")
    new = f"{START}\n{block}\n{END}"
    if START in text and END in text:
        text = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: new, text, flags=re.S)
    else:
        text += "\n" + new + "\n"
    readme.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    res = build()
    print("status:")
    for s in res["status"]:
        print(f"  {s['source']:14} {s['item']:18} {s['ok']:7} {s['note']}")
