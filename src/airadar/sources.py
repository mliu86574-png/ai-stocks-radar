"""Public data sources (no API keys).

* Yahoo Finance chart API - daily OHLCV for stocks and ETFs
* Nasdaq.com public API   - earnings dates and consensus (Zacks), EPS surprises,
                             institutional (13F) holdings, insider trades,
                             short interest, analyst ratings and summary data
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import pandas as pd

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
YAHOO_HOSTS = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")
NASDAQ = "https://api.nasdaq.com/api"
NASDAQ_HEADERS = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                  "Accept-Language": "en-US,en;q=0.9", "Origin": "https://www.nasdaq.com",
                  "Referer": "https://www.nasdaq.com/"}


def get_json(url: str, params: dict | None = None, headers: dict | None = None,
             retries: int = 3, pause: float = 3.0, timeout: int = 25):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as err:
            last = err
            time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} attempts: {url}") from last


# ---------------------------------------------------------------- parsing helpers
def to_num(x) -> float | None:
    """'3,376' -> 3376; '$4,181,979' -> 4181979; '(6,255,354)' -> -6255354; '79.62%' -> 79.62; 'N/A' -> None."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if not s or s.upper() in ("N/A", "NA", "--", "-"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[,$%()\s]", "", s)
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def parse_us_date(s: str | None) -> str | None:
    """'8/26/2026' or 'Nov 18, 2026' -> '2026-08-26'."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%m/%d/%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- Yahoo
def parse_yahoo_ohlcv(payload: dict) -> pd.DataFrame:
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise ValueError("empty chart result")
    r = result[0]
    ts = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    offset = (r.get("meta") or {}).get("gmtoffset", 0) or 0
    idx = pd.to_datetime([datetime.fromtimestamp(t + offset, tz=timezone.utc).date() for t in ts])
    df = pd.DataFrame({k: q.get(k) or [None] * len(ts) for k in ("open", "high", "low", "close", "volume")},
                      index=idx, dtype="float64")
    df = df.dropna(subset=["close"])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if df.empty:
        raise ValueError("no closes")
    return df


def yahoo_ohlcv(symbol: str, rng: str = "2y") -> pd.DataFrame:
    last: Exception | None = None
    for host in YAHOO_HOSTS:
        try:
            return parse_yahoo_ohlcv(get_json(f"{host}/v8/finance/chart/{urllib.parse.quote(symbol)}",
                                              {"range": rng, "interval": "1d"}))
        except Exception as err:
            last = err
    raise RuntimeError(f"Yahoo unavailable for {symbol}") from last


# ---------------------------------------------------------------- Nasdaq
def nasdaq(path: str, params: dict | None = None) -> dict:
    j = get_json(f"{NASDAQ}{path}", params, NASDAQ_HEADERS, retries=2, pause=2.0)
    if not isinstance(j, dict) or j.get("data") is None:
        raise ValueError(f"no data from {path}")
    return j["data"]


def parse_earnings_date(data: dict) -> dict:
    ann = data.get("announcement") or ""
    text = (data.get("reportText") or "").lower()
    m = re.search(r":\s*([A-Z][a-z]{2,8} \d{1,2}, \d{4})", ann)
    return {"date": parse_us_date(m.group(1)) if m else None,
            "estimated": "estimated" in text or "algorithm" in text}


def parse_surprises(data: dict) -> list[dict]:
    rows = ((data.get("earningsSurpriseTable") or {}).get("rows")) or []
    out = []
    for r in rows:
        out.append({"quarter": r.get("fiscalQtrEnd"), "date": parse_us_date(r.get("dateReported")),
                    "eps": to_num(r.get("eps")), "consensus": to_num(r.get("consensusForecast")),
                    "surprise_pct": to_num(r.get("percentageSurprise"))})
    return [o for o in out if o["date"]]


def _rows_by_label(block: dict | None, label_key: str = "positions") -> dict:
    rows = (block or {}).get("rows") or []
    return {r.get(label_key): r for r in rows}


def parse_institutional(data: dict) -> dict:
    summ = data.get("ownershipSummary") or {}
    act = _rows_by_label(data.get("activePositions"))
    new = _rows_by_label(data.get("newSoldOutPositions"))

    def sh(d, k):
        return to_num((d.get(k) or {}).get("shares"))

    def ho(d, k):
        return to_num((d.get(k) or {}).get("holders"))

    inc, dec = sh(act, "Increased Positions"), sh(act, "Decreased Positions")
    total = sh(act, "Total Institutional Shares")
    newp, sold = sh(new, "New Positions"), sh(new, "Sold Out Positions")
    net = None if inc is None or dec is None else inc - dec + (newp or 0) - (sold or 0)
    return {"inst_pct": to_num((summ.get("SharesOutstandingPCT") or {}).get("value")),
            "inst_shares": total, "inc_holders": ho(act, "Increased Positions"),
            "dec_holders": ho(act, "Decreased Positions"), "new_holders": ho(new, "New Positions"),
            "soldout_holders": ho(new, "Sold Out Positions"), "net_shares": net,
            "net_pct": None if net is None or not total else net / total * 100}


def parse_insider(data: dict) -> dict:
    trades = _rows_by_label(data.get("numberOfTrades"), "insiderTrade")
    shares = _rows_by_label(data.get("numberOfSharesTraded"), "insiderTrade")
    return {"buys_3m": to_num((trades.get("Number of Open Market Buys") or {}).get("months3")),
            "sells_3m": to_num((trades.get("Number of Sells") or {}).get("months3")),
            "net_shares_3m": to_num((shares.get("Net Activity") or {}).get("months3")),
            "net_shares_12m": to_num((shares.get("Net Activity") or {}).get("months12"))}


def parse_short_interest(data: dict) -> dict:
    rows = ((data.get("shortInterestTable") or {}).get("rows")) or []
    if not rows:
        return {}
    cur = rows[0]
    prev = rows[1] if len(rows) > 1 else {}
    si, si_prev = to_num(cur.get("interest")), to_num(prev.get("interest"))
    return {"si_date": parse_us_date(cur.get("settlementDate")), "short_interest": si,
            "days_to_cover": to_num(cur.get("daysToCover")),
            "si_change_pct": None if not si or not si_prev else (si / si_prev - 1) * 100}


def parse_summary(data: dict) -> dict:
    s = data.get("summaryData") or {}

    def v(k):
        return (s.get(k) or {}).get("value")

    return {"industry": v("Industry"), "market_cap": to_num(v("MarketCap")), "target_1y": to_num(v("OneYrTarget"))}


def parse_ratings(data: dict) -> dict:
    return {"rating": data.get("meanRatingType")}


def parse_momentum(data: dict) -> dict:
    c = data.get("changeInConsensus") or {}
    cur, month = (c.get("currentData") or {}).get("qtrMean"), (c.get("monthData") or {}).get("qtrMean")
    cur, month = to_num(cur), to_num(month)
    return {"eps_qtr_mean": cur, "eps_rev_1m_pct": None if cur is None or not month else (cur / month - 1) * 100}


def parse_calendar(data: dict) -> dict[str, dict]:
    out = {}
    for r in data.get("rows") or []:
        t = (r.get("time") or "").replace("time-", "")
        out[(r.get("symbol") or "").upper()] = {
            "time": {"pre-market": "pre", "after-hours": "after"}.get(t, "tbd"),
            "eps_forecast": to_num(r.get("epsForecast")), "n_ests": to_num(r.get("noOfEsts")),
            "last_year_eps": to_num(r.get("lastYearEPS")), "fiscal_q": r.get("fiscalQuarterEnding")}
    return out


NASDAQ_ENDPOINTS = {
    "earnings_date": ("/analyst/{s}/earnings-date", None, parse_earnings_date),
    "surprises": ("/company/{s}/earnings-surprise", None, parse_surprises),
    "institutional": ("/company/{s}/institutional-holdings",
                      {"limit": "1", "type": "TOTAL", "sortColumn": "marketValue"}, parse_institutional),
    "insider": ("/company/{s}/insider-trades", {"limit": "1", "type": "ALL"}, parse_insider),
    "short": ("/quote/{s}/short-interest", {"assetClass": "stocks"}, parse_short_interest),
    "summary": ("/quote/{s}/summary", {"assetClass": "stocks"}, parse_summary),
    "ratings": ("/analyst/{s}/ratings", None, parse_ratings),
    "momentum": ("/analyst/{s}/estimate-momentum", None, parse_momentum),
}


def nasdaq_symbol(symbol: str, kind: str):
    path, params, parser = NASDAQ_ENDPOINTS[kind]
    return parser(nasdaq(path.format(s=symbol), params))


def nasdaq_calendar(date: str) -> dict[str, dict]:
    return parse_calendar(nasdaq("/calendar/earnings", {"date": date}))
