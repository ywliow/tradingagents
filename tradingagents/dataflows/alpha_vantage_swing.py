"""Swing-trading data via Alpha Vantage: earnings calendar and relative strength."""

import json
from datetime import datetime, timedelta
from io import StringIO

import pandas as pd

from .alpha_vantage_common import _make_api_request


def _safe_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def get_earnings_calendar(ticker: str, curr_date: str = None) -> str:
    """Earnings via Alpha Vantage EARNINGS endpoint (history) + EARNINGS_CALENDAR (forward)."""
    try:
        history_raw = _make_api_request("EARNINGS", {"symbol": ticker})
    except Exception as e:
        return f"Error retrieving Alpha Vantage earnings for {ticker}: {e}"

    if isinstance(history_raw, str):
        try:
            history = json.loads(history_raw)
        except json.JSONDecodeError:
            history = {}
    else:
        history = history_raw or {}

    quarterly = history.get("quarterlyEarnings", []) or []
    if curr_date:
        quarterly = [q for q in quarterly if q.get("reportedDate", "9999-99-99") <= curr_date]
    quarterly = sorted(quarterly, key=lambda q: q.get("reportedDate", ""), reverse=True)[:4]

    # Forward calendar — CSV across all symbols, filter for ours
    next_date = None
    next_eps = None
    try:
        cal_csv = _make_api_request("EARNINGS_CALENDAR", {"symbol": ticker, "horizon": "3month"})
        if isinstance(cal_csv, str) and cal_csv.strip().startswith("symbol"):
            cal_df = pd.read_csv(StringIO(cal_csv))
            cal_df = cal_df[cal_df["symbol"].str.upper() == ticker.upper()]
            if curr_date:
                cal_df = cal_df[cal_df["reportDate"] >= curr_date]
            if not cal_df.empty:
                row = cal_df.sort_values("reportDate").iloc[0]
                next_date = str(row.get("reportDate"))
                next_eps = row.get("estimate")
    except Exception:
        pass  # forward calendar is best-effort; history is the load-bearing part

    lines = [f"# Earnings Calendar for {ticker.upper()} (via Alpha Vantage)"]
    if curr_date:
        lines.append(f"# As of: {curr_date}\n")

    if next_date:
        if curr_date:
            try:
                days_to = (datetime.strptime(next_date, "%Y-%m-%d") - datetime.strptime(curr_date, "%Y-%m-%d")).days
                lines.append(f"## Next Earnings: {next_date} ({days_to} days away)")
            except ValueError:
                lines.append(f"## Next Earnings: {next_date}")
        else:
            lines.append(f"## Next Earnings: {next_date}")
        if next_eps and pd.notna(next_eps):
            lines.append(f"- Consensus EPS estimate: {next_eps}")
        lines.append("")
    else:
        lines.append("## Next Earnings: not announced in available data\n")

    if quarterly:
        lines.append("## Last Reports (T+1 / T+5 drift not computed by AV — use yfinance/TWS for that)")
        lines.append("| Report Date | Fiscal End | EPS Est | EPS Actual | Surprise | Surprise % |")
        lines.append("|---|---|---|---|---|---|")
        for q in quarterly:
            lines.append(
                f"| {q.get('reportedDate', 'n/a')} "
                f"| {q.get('fiscalDateEnding', 'n/a')} "
                f"| {q.get('estimatedEPS', 'n/a')} "
                f"| {q.get('reportedEPS', 'n/a')} "
                f"| {q.get('surprise', 'n/a')} "
                f"| {q.get('surprisePercentage', 'n/a')} |"
            )

    return "\n".join(lines)


def _fetch_daily_close(symbol: str, end_date: datetime, lookback_days: int = 120) -> pd.Series:
    """Fetch DAILY adjusted close prices from Alpha Vantage; return Series indexed by date."""
    raw = _make_api_request(
        "TIME_SERIES_DAILY_ADJUSTED",
        {"symbol": symbol, "outputsize": "compact"},
    )
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
    else:
        data = raw or {}

    series = data.get("Time Series (Daily)") or {}
    if not series:
        return pd.Series(dtype=float)

    rows = [(pd.Timestamp(d), _safe_float(v.get("5. adjusted close") or v.get("4. close"))) for d, v in series.items()]
    rows = [r for r in rows if r[1] is not None]
    s = pd.Series({d: c for d, c in rows}).sort_index()
    s = s[s.index <= pd.Timestamp(end_date)]
    cutoff = pd.Timestamp(end_date) - pd.Timedelta(days=lookback_days + 30)
    return s[s.index >= cutoff]


def _pct_return(s: pd.Series, days: int) -> float | None:
    if len(s) <= days:
        return None
    end = float(s.iloc[-1])
    start = float(s.iloc[-1 - days])
    if start <= 0:
        return None
    return (end / start - 1) * 100


def get_relative_strength(ticker: str, curr_date: str = None, benchmarks: str = "SPY,QQQ") -> str:
    """Compare ticker return to benchmarks over 5/20/60 trading days using AV daily adjusted."""
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d") if curr_date else datetime.utcnow()
    symbols = [ticker.upper()] + [b.strip().upper() for b in benchmarks.split(",") if b.strip()]

    rows = []
    base_returns = None
    for sym in symbols:
        try:
            s = _fetch_daily_close(sym, end_dt)
        except Exception as e:
            rows.append((sym, None, None, None, f"fetch failed: {e}"))
            continue
        if s.empty:
            rows.append((sym, None, None, None, "no data"))
            continue
        r5, r20, r60 = _pct_return(s, 5), _pct_return(s, 20), _pct_return(s, 60)
        rows.append((sym, r5, r20, r60, None))
        if sym == ticker.upper():
            base_returns = (r5, r20, r60)

    fmt = lambda v: f"{v:+.2f}%" if isinstance(v, (int, float)) else "n/a"
    lines = [f"# Relative Strength: {ticker.upper()} vs {','.join(symbols[1:])} (via Alpha Vantage)"]
    if curr_date:
        lines.append(f"# As of: {curr_date}\n")
    lines.append("| Symbol | 5d | 20d | 60d | Notes |")
    lines.append("|---|---|---|---|---|")
    for sym, r5, r20, r60, note in rows:
        lines.append(f"| {sym} | {fmt(r5)} | {fmt(r20)} | {fmt(r60)} | {note or ''} |")

    if base_returns and any(r is not None for r in base_returns):
        lines.append("\n## RS spread (ticker − benchmark)")
        lines.append("| Benchmark | 5d | 20d | 60d |")
        lines.append("|---|---|---|---|")
        for sym, r5, r20, r60, _ in rows[1:]:
            spread = lambda a, b: fmt(a - b) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else "n/a"
            lines.append(
                f"| {sym} | {spread(base_returns[0], r5)} "
                f"| {spread(base_returns[1], r20)} "
                f"| {spread(base_returns[2], r60)} |"
            )

    return "\n".join(lines)
