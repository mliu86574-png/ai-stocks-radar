"""Offline tests. All inputs are SYNTHETIC and only mimic the shape of the Yahoo
and Nasdaq responses; they are not market data."""
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from airadar import analytics as A
from airadar import build, sources

ROOT = Path(__file__).resolve().parents[1]
TODAY = pd.Timestamp("2026-10-28")


def fake_prices(symbol, asset="stocks"):
    seed = sum(map(ord, symbol))
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-10-27", periods=520)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0006, 0.02, len(idx))))
    high = close * (1 + rng.uniform(0, 0.02, len(idx)))
    low = close * (1 - rng.uniform(0, 0.02, len(idx)))
    vol = rng.uniform(5e6, 2e7, len(idx))
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": vol}, index=idx)


def fake_nasdaq(symbol, kind):
    seed = sum(map(ord, symbol))
    if symbol == "SNOW" and kind == "insider":
        raise RuntimeError("simulated outage")
    if kind == "earnings_date":
        return {"date": (TODAY + pd.Timedelta(days=seed % 40)).date().isoformat(), "estimated": seed % 2 == 0}
    if kind == "surprises":
        return [{"quarter": f"Q{i}", "date": (TODAY - pd.Timedelta(days=91 * i + 5)).date().isoformat(),
                 "eps": 1.0 + i / 10, "consensus": 1.0, "surprise_pct": (seed % 7) - 2.0} for i in range(4)]
    if kind == "institutional":
        return {"inst_pct": 70.0, "inst_shares": 1e9, "inc_holders": 900, "dec_holders": 800, "new_holders": 50,
                "soldout_holders": 20, "net_shares": (seed % 11 - 5) * 1e6, "net_pct": (seed % 11 - 5) / 10}
    if kind == "insider":
        return {"buys_3m": 1, "sells_3m": 5, "net_shares_3m": -(seed * 1000), "net_shares_12m": -(seed * 5000)}
    if kind == "short":
        return {"si_date": "2026-10-15", "short_interest": 1e7, "days_to_cover": 2.5, "si_change_pct": seed % 9 - 4.0}
    if kind == "summary":
        return {"industry": "Semiconductors", "market_cap": seed * 1e10, "target_1y": 150.0}
    if kind == "ratings":
        return {"rating": "Buy"}
    if kind == "momentum":
        return {"eps_qtr_mean": 1.5, "eps_rev_1m_pct": 0.8}
    raise KeyError(kind)


def fake_calendar(date):
    return {"NVDA": {"time": "after", "eps_forecast": 2.49, "n_ests": 13, "last_year_eps": 1.24, "fiscal_q": "Oct/2026"}}


@pytest.fixture
def repo(tmp_path):
    shutil.copy(ROOT / "config.json", tmp_path / "config.json")
    (tmp_path / "README.md").write_text("# T\n<!-- RADAR:START -->\nSTALE\n<!-- RADAR:END -->\n")
    return tmp_path


def test_to_num_formats():
    assert sources.to_num("3,376") == 3376
    assert sources.to_num("$4,181,979") == 4181979
    assert sources.to_num("(6,255,354)") == -6255354
    assert sources.to_num("79.62%") == 79.62
    assert sources.to_num("N/A") is None


def test_parse_earnings_date_and_calendar():
    d = sources.parse_earnings_date({"announcement": "Earnings announcement* for NVDA: Nov 18, 2026",
                                     "reportText": "NVIDIA is estimated to report earnings on 11/18/2026."})
    assert d == {"date": "2026-11-18", "estimated": True}
    cal = sources.parse_calendar({"rows": [{"symbol": "AMZN", "time": "time-after-hours", "epsForecast": "$2.01",
                                            "noOfEsts": "14", "lastYearEPS": "$1.95", "fiscalQuarterEnding": "Sep/2026"}]})
    assert cal["AMZN"]["time"] == "after" and cal["AMZN"]["eps_forecast"] == 2.01


def test_parse_institutional_net():
    data = {"ownershipSummary": {"SharesOutstandingPCT": {"value": "79.62%"}},
            "activePositions": {"rows": [{"positions": "Increased Positions", "holders": "3,376", "shares": "672,459,247"},
                                         {"positions": "Decreased Positions", "holders": "2,583", "shares": "412,972,236"},
                                         {"positions": "Total Institutional Shares", "holders": "6,326", "shares": "19,188,669,480"}]},
            "newSoldOutPositions": {"rows": [{"positions": "New Positions", "holders": "280", "shares": "176,542,201"},
                                             {"positions": "Sold Out Positions", "holders": "123", "shares": "30,289,141"}]}}
    r = sources.parse_institutional(data)
    assert r["net_shares"] == 672459247 - 412972236 + 176542201 - 30289141
    assert r["net_pct"] == pytest.approx(r["net_shares"] / 19188669480 * 100)


def test_flows_detect_accumulation():
    idx = pd.bdate_range(end="2026-10-27", periods=60)
    close = pd.Series(np.linspace(100, 130, 60), index=idx)
    df = pd.DataFrame({"high": close + 1, "low": close - 1, "close": close + 0.8, "volume": 1e6}, index=idx)
    f = A.flows(df)
    assert f["cmf20"] > 0.05 and f["obv_days20"] > 2 and f["flow"] == "in" and f["net_flow20"] > 0


def test_earnings_reaction_window():
    idx = pd.to_datetime(["2026-08-25", "2026-08-26", "2026-08-27"])
    close = pd.Series([100.0, 101.0, 110.0], index=idx)
    assert A.earnings_reaction(close, "2026-08-26") == pytest.approx(10.0)


def test_basket_equal_weight():
    idx = pd.bdate_range("2026-01-01", periods=3)
    a = pd.Series([100, 110, 110], index=idx, dtype=float)
    b = pd.Series([100, 90, 90], index=idx, dtype=float)
    assert A.basket({"A": a, "B": b}, ["A", "B"]).iloc[-1] == pytest.approx(100)


def test_full_build(repo):
    res = build.build(repo, fake_prices, fake_nasdaq, fake_calendar, today=TODAY, pause=0)
    page = (repo / "docs" / "index.html").read_text()
    assert "AI Stocks Radar" in page and "美股 AI 雷达" in page and "window.DATA=" in page
    nvda = next(e for e in res["earnings"] if e["symbol"] == "NVDA")
    assert nvda["time"] == "after" and nvda["eps_forecast"] == 2.49
    assert all(e["next_date"] is None or e["days"] >= 0 for e in res["earnings"])
    status = {s["item"]: s for s in res["status"]}
    assert status["insider"]["ok"] == "failed" or "missing" in status["insider"]["note"]
    assert "STALE" not in (repo / "README.md").read_text()
    assert (repo / "data" / "stocks.csv").exists() and (repo / "data" / "nasdaq_cache.json").exists()


def test_cache_used_when_nasdaq_fails(repo):
    build.build(repo, fake_prices, fake_nasdaq, fake_calendar, today=TODAY, pause=0)

    def down(*_a):
        raise RuntimeError("down")
    res = build.build(repo, fake_prices, down, down, today=TODAY, pause=0)
    st = {s["item"]: s["ok"] for s in res["status"]}
    assert st["summary"] == "cached"
    assert any(e["next_date"] for e in res["earnings"])


def test_build_survives_everything_down(repo):
    def down(*_a, **_k):
        raise RuntimeError("down")
    build.build(repo, down, down, down, today=TODAY, pause=0)
    assert (repo / "docs" / "index.html").exists()


def test_parse_nasdaq_history():
    df = sources.parse_nasdaq_history({"tradesTable": {"rows": [
        {"date": "10/27/2026", "close": "$217.94", "volume": "84,799,700", "open": "$218.31", "high": "$219.19", "low": "$215.53"},
        {"date": "10/26/2026", "close": "$216.00", "volume": "90,829,290", "open": "$213.105", "high": "$217.75", "low": "$212.61"}]}})
    assert list(df["close"]) == [216.0, 217.94] and df["volume"].iloc[-1] == 84799700
