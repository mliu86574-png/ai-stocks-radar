"""Price, volume-flow and earnings analytics.

"Fund flow" here is estimated from daily price and volume (Chaikin money flow,
money flow index, on-balance volume, up-day vs down-day dollar volume). Exchange-
level order-flow and ETF creation data are not freely available; the page says so.
"""
from __future__ import annotations

from math import sqrt

import numpy as np
import pandas as pd


def _f(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(x) or np.isinf(x) else x


def pct_ago(s: pd.Series, days: int):
    s = s.dropna()
    if len(s) < 2:
        return None
    target = s.index[-1] - pd.Timedelta(days=days)
    if target < s.index[0]:
        return None
    past = s.asof(target)
    return _f((s.iloc[-1] / past - 1) * 100) if past else None


def ytd(s: pd.Series):
    s = s.dropna()
    if s.empty:
        return None
    prior = s[s.index < pd.Timestamp(year=s.index[-1].year, month=1, day=1)]
    return _f((s.iloc[-1] / prior.iloc[-1] - 1) * 100) if not prior.empty else None


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(100)


def performance(df: pd.DataFrame) -> dict:
    c = df["close"].dropna()
    if c.empty:
        return {}
    year = c[c.index > c.index[-1] - pd.Timedelta(days=365)]
    ma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else np.nan
    ma50 = c.rolling(50).mean().iloc[-1] if len(c) >= 50 else np.nan
    last = c.iloc[-1]
    if np.isnan(ma50) or np.isnan(ma200):
        trend = "mixed"
    elif last > ma50 > ma200:
        trend = "up"
    elif last < ma50 < ma200:
        trend = "down"
    else:
        trend = "mixed"
    rets = np.log(c).diff().dropna().iloc[-21:]
    return {"last": _f(last), "date": c.index[-1].date().isoformat(),
            "d1": _f((c.iloc[-1] / c.iloc[-2] - 1) * 100) if len(c) > 1 else None,
            "w1": pct_ago(c, 7), "m1": pct_ago(c, 30), "m3": pct_ago(c, 91), "ytd": ytd(c), "y1": pct_ago(c, 365),
            "hi52": _f(year.max()), "from_hi": _f((last / year.max() - 1) * 100),
            "vs_ma200": _f((last / ma200 - 1) * 100) if not np.isnan(ma200) else None,
            "rsi14": _f(rsi(c).iloc[-1]), "vol30": _f(rets.std() * sqrt(252) * 100), "trend": trend}


def flows(df: pd.DataFrame, n: int = 20) -> dict:
    """Volume-based flow measures over the last n sessions."""
    d = df.dropna(subset=["close", "volume"]).copy()
    if len(d) < n + 2:
        return {}
    h, l, c, v = d["high"], d["low"], d["close"], d["volume"]
    rng = (h - l).replace(0, np.nan)
    mfm = (((c - l) - (h - c)) / rng).fillna(0)
    cmf = (mfm * v).rolling(n).sum() / v.rolling(n).sum()
    tp = (h + l + c) / 3
    raw = tp * v
    pos = raw.where(tp > tp.shift(), 0.0).rolling(14).sum()
    neg = raw.where(tp < tp.shift(), 0.0).rolling(14).sum()
    mfi = 100 - 100 / (1 + pos / neg.replace(0, np.nan))
    obv = (np.sign(c.diff()).fillna(0) * v).cumsum()
    avg_vol = v.iloc[-n - 1:-1].mean()
    dv = c * v
    sign = np.sign(c.diff()).fillna(0)
    net_dv = (dv * sign).iloc[-n:].sum()
    score = 0
    cmf_last, mfi_last = _f(cmf.iloc[-1]), _f(mfi.iloc[-1])
    obv_days = _f((obv.iloc[-1] - obv.iloc[-n - 1]) / avg_vol) if avg_vol else None
    if cmf_last is not None:
        score += 1 if cmf_last > 0.05 else -1 if cmf_last < -0.05 else 0
    if obv_days is not None:
        score += 1 if obv_days > 2 else -1 if obv_days < -2 else 0
    if mfi_last is not None:
        score += 1 if mfi_last > 60 else -1 if mfi_last < 40 else 0
    label = "in" if score >= 2 else "out" if score <= -2 else "neutral"
    return {"dollar_vol": _f(dv.iloc[-1]), "dollar_vol_avg20": _f(dv.iloc[-n - 1:-1].mean()),
            "rel_vol": _f(v.iloc[-1] / avg_vol) if avg_vol else None, "cmf20": cmf_last, "mfi14": mfi_last,
            "obv_days20": obv_days, "net_flow20": _f(net_dv), "flow_score": score, "flow": label}


def flow_series(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Rolling n-day net up-minus-down dollar volume, for charts."""
    d = df.dropna(subset=["close", "volume"])
    dv = d["close"] * d["volume"] * np.sign(d["close"].diff()).fillna(0)
    return dv.rolling(n).sum()


def basket(closes: dict[str, pd.Series], symbols: list[str]) -> pd.Series:
    """Equal-weight daily-rebalanced basket, rebased to 100."""
    cols = [closes[s] for s in symbols if s in closes]
    if not cols:
        return pd.Series(dtype="float64")
    px = pd.concat(cols, axis=1).sort_index()
    rets = px.pct_change().mean(axis=1, skipna=True).fillna(0)
    return 100 * (1 + rets).cumprod()


def rebase(s: pd.Series, start: pd.Timestamp) -> pd.Series:
    s = s[s.index >= start].dropna()
    return s / s.iloc[0] * 100 if not s.empty else s


def earnings_reaction(close: pd.Series, date: str) -> float | None:
    """Close on the first session after the report vs the last close before it.

    The two-session window covers both pre-market and after-hours releases."""
    d = pd.Timestamp(date)
    before = close[close.index < d]
    after = close[close.index > d]
    if before.empty or after.empty:
        return None
    return _f((after.iloc[0] / before.iloc[-1] - 1) * 100)


def earnings_view(sym: str, close: pd.Series, nd: dict, cal: dict, today: pd.Timestamp,
                  window: int, recent: int) -> dict:
    """Upcoming date, consensus and history of surprises and price reactions."""
    surprises = nd.get("surprises") or []
    reactions = []
    for s in surprises:
        r = earnings_reaction(close, s["date"]) if close is not None and not close.empty else None
        reactions.append({**s, "reaction": r})
    moves = [abs(r["reaction"]) for r in reactions if r["reaction"] is not None]
    ed = nd.get("earnings_date") or {}
    nxt = ed.get("date")
    days = (pd.Timestamp(nxt) - today.normalize()).days if nxt else None
    upcoming = nxt is not None and 0 <= days <= window
    last = reactions[0] if reactions else None
    is_recent = bool(last and (today.normalize() - pd.Timestamp(last["date"])).days <= recent)
    return {"symbol": sym, "next_date": nxt if upcoming else None, "days": days if upcoming else None,
            "estimated": ed.get("estimated", False), **(cal.get(sym) or {}),
            "avg_move": float(np.mean(moves)) if moves else None, "beats": sum(1 for r in reactions if (r["surprise_pct"] or 0) > 0),
            "n_hist": len(reactions), "history": reactions, "recent": last if is_recent else None,
            "eps_rev_1m_pct": (nd.get("momentum") or {}).get("eps_rev_1m_pct"),
            "eps_qtr_mean": (nd.get("momentum") or {}).get("eps_qtr_mean")}
