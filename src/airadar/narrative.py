"""Bilingual commentary filled from the computed numbers."""
from __future__ import annotations

WEEKDAY_ZH = "一二三四五六日"


def _p(x, dp=1):
    return "n/a" if x is None else f"{x:+.{dp}f}%"


def _bn(x):
    return "n/a" if x is None else f"${x / 1e9:+,.1f}bn"


def _when(e: dict) -> tuple[str, str]:
    t = e.get("time", "tbd")
    return ({"pre": "before the open", "after": "after the close"}.get(t, "time TBC"),
            {"pre": "盘前", "after": "盘后"}.get(t, "时间待定"))


def overview(stocks: list[dict], basket_perf: dict, bench_perf: dict, bench: str,
             earnings: list[dict]) -> tuple[str, str]:
    n = len(stocks)
    ranked = sorted([s for s in stocks if s.get("m1") is not None], key=lambda s: s["m1"], reverse=True)
    lead, lag = ranked[:2], ranked[-2:][::-1]
    inflow = [s for s in stocks if s.get("flow") == "in"]
    outflow = [s for s in stocks if s.get("flow") == "out"]
    big_in = max(stocks, key=lambda s: s.get("net_flow20") or -1e30, default=None)
    big_out = min(stocks, key=lambda s: s.get("net_flow20") or 1e30, default=None)
    en = [f"The equal-weight AI basket ({n} stocks) moved {_p(basket_perf.get('d1'), 2)} on the day, "
          f"{_p(basket_perf.get('m1'))} over one month and {_p(basket_perf.get('ytd'))} year to date, "
          f"against {_p(bench_perf.get('ytd'))} for {bench}."]
    zh = [f"AI 股票等权篮子（{n} 只）当日 {_p(basket_perf.get('d1'), 2)}，近一月 {_p(basket_perf.get('m1'))}，"
          f"年初至今 {_p(basket_perf.get('ytd'))}，同期 {bench} 为 {_p(bench_perf.get('ytd'))}。"]
    if ranked:
        en.append("One-month leaders: " + ", ".join(f"{s['symbol']} ({_p(s['m1'])})" for s in lead)
                  + "; laggards: " + ", ".join(f"{s['symbol']} ({_p(s['m1'])})" for s in lag) + ".")
        zh.append("近一月领涨：" + "、".join(f"{s['symbol']}（{_p(s['m1'])}）" for s in lead)
                  + "；落后：" + "、".join(f"{s['symbol']}（{_p(s['m1'])}）" for s in lag) + "。")
    en.append(f"Volume-based flow signals: {len(inflow)} inflow, {len(outflow)} outflow, "
              f"{n - len(inflow) - len(outflow)} neutral.")
    zh.append(f"量价资金信号：{len(inflow)} 只流入，{len(outflow)} 只流出，{n - len(inflow) - len(outflow)} 只中性。")
    if big_in and big_in.get("net_flow20") is not None:
        en.append(f"Largest estimated 20-day net inflow: {big_in['symbol']} ({_bn(big_in['net_flow20'])}); "
                  f"largest outflow: {big_out['symbol']} ({_bn(big_out['net_flow20'])}).")
        zh.append(f"20 日估算净流入最多：{big_in['symbol']}（{_bn(big_in['net_flow20'])}）；"
                  f"净流出最多：{big_out['symbol']}（{_bn(big_out['net_flow20'])}）。")
    soon = [e for e in earnings if e.get("days") is not None and e["days"] <= 14][:5]
    if soon:
        en.append("Next to report: " + ", ".join(
            f"{e['symbol']} {e['next_date'][5:]} {_when(e)[0]}" for e in soon) + ".")
        zh.append("即将发布财报：" + "、".join(
            f"{e['symbol']}（{e['next_date'][5:]} {_when(e)[1]}）" for e in soon) + "。")
    return " ".join(en), "".join(zh)


def earnings_text(earnings: list[dict]) -> tuple[str, str]:
    up = [e for e in earnings if e.get("next_date")]
    rec = sorted([e for e in earnings if e.get("recent")], key=lambda e: e["recent"]["date"], reverse=True)[:6]
    en, zh = [], []
    if up:
        e = up[0]
        en.append(f"{len(up)} tracked companies have a report date in the window; next is {e['symbol']} on "
                  f"{e['next_date']} ({_when(e)[0]}).")
        zh.append(f"观察池中有 {len(up)} 家公司在时间窗口内发布财报；最近一家是 {e['symbol']}，{e['next_date']}（{_when(e)[1]}）。")
        moves = sorted([e for e in up if e.get("avg_move") is not None], key=lambda e: e["avg_move"], reverse=True)[:3]
        if moves:
            en.append("Biggest typical post-earnings moves among them: " + ", ".join(
                f"{e['symbol']} ±{e['avg_move']:.1f}%" for e in moves) + ".")
            zh.append("其中历史财报后平均波动最大的是：" + "、".join(f"{e['symbol']} ±{e['avg_move']:.1f}%" for e in moves) + "。")
    if rec:
        en.append("Recently reported: " + ", ".join(
            f"{e['symbol']} (EPS surprise {_p(e['recent']['surprise_pct'])}, stock {_p(e['recent']['reaction'])})" for e in rec) + ".")
        zh.append("近期已发布：" + "、".join(
            f"{e['symbol']}（EPS 超预期 {_p(e['recent']['surprise_pct'])}，股价 {_p(e['recent']['reaction'])}）" for e in rec) + "。")
    if not en:
        return "No earnings dates available.", "暂无财报日期数据。"
    return " ".join(en), "".join(zh)
