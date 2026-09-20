"""Swing-trading data via yfinance: earnings calendar and relative strength."""

from datetime import datetime, timedelta
from typing import Annotated

import pandas as pd
import yfinance as yf

from .stockstats_utils import yf_retry


def get_earnings_calendar(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date in yyyy-mm-dd"] = None,
) -> str:
    """Return next earnings date, last 4 surprises, and post-earnings drift behavior.

    Drift = close N trading days after earnings vs. close on earnings day,
    measured for both T+1 and T+5 to capture short-horizon swing setups.
    """
    try:
        t = yf.Ticker(ticker.upper())
        cutoff = pd.Timestamp(curr_date) if curr_date else pd.Timestamp.utcnow().tz_localize(None)

        ed = yf_retry(lambda: t.get_earnings_dates(limit=12))
        if ed is None or ed.empty:
            return f"No earnings data found for '{ticker}' via yfinance"

        ed = ed.copy()
        if ed.index.tz is not None:
            ed.index = ed.index.tz_localize(None)
        ed = ed.sort_index()

        future = ed[ed.index > cutoff]
        past = ed[ed.index <= cutoff].tail(4)

        lines = [f"# Earnings Calendar for {ticker.upper()} (via yfinance)"]
        if curr_date:
            lines.append(f"# As of: {curr_date}\n")

        if not future.empty:
            nxt = future.iloc[0]
            nxt_dt = future.index[0]
            days_to = (nxt_dt - cutoff).days
            lines.append(f"## Next Earnings: {nxt_dt.strftime('%Y-%m-%d')} ({days_to} days away)")
            est = nxt.get("EPS Estimate")
            if pd.notna(est):
                lines.append(f"- Consensus EPS estimate: {est}")
            lines.append("")
        else:
            lines.append("## Next Earnings: not announced in available data\n")

        if not past.empty:
            lines.append("## Last Reports & Post-Earnings Drift")
            lines.append("| Report Date | EPS Est | EPS Actual | Surprise % | T+1 % | T+5 % |")
            lines.append("|---|---|---|---|---|---|")

            history_start = (past.index.min() - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
            history_end = (cutoff + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            try:
                px = yf_retry(lambda: t.history(start=history_start, end=history_end))
                if px.index.tz is not None:
                    px.index = px.index.tz_localize(None)
                px = px[["Close"]].copy()
            except Exception:
                px = pd.DataFrame()

            for ts, row in past.iterrows():
                est = row.get("EPS Estimate")
                act = row.get("Reported EPS")
                surprise = row.get("Surprise(%)")
                t1, t5 = "n/a", "n/a"
                if not px.empty:
                    after = px[px.index >= ts]
                    if len(after) >= 2:
                        base = float(after.iloc[0]["Close"])
                        if base > 0:
                            t1 = f"{(float(after.iloc[1]['Close']) / base - 1) * 100:.2f}"
                            if len(after) >= 6:
                                t5 = f"{(float(after.iloc[5]['Close']) / base - 1) * 100:.2f}"
                lines.append(
                    f"| {ts.strftime('%Y-%m-%d')} "
                    f"| {est if pd.notna(est) else 'n/a'} "
                    f"| {act if pd.notna(act) else 'n/a'} "
                    f"| {surprise if pd.notna(surprise) else 'n/a'} "
                    f"| {t1} | {t5} |"
                )

        return "\n".join(lines)

    except Exception as e:
        return f"Error retrieving earnings calendar for {ticker} via yfinance: {e}"


def _pct_return(close: pd.Series, days: int) -> float | None:
    if len(close) <= days:
        return None
    end = float(close.iloc[-1])
    start = float(close.iloc[-1 - days])
    if start <= 0:
        return None
    return (end / start - 1) * 100


def get_relative_strength(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date in yyyy-mm-dd"] = None,
    benchmarks: Annotated[str, "comma-separated benchmark tickers"] = "SPY,QQQ",
) -> str:
    """Compare ticker total return to benchmarks over 5 / 20 / 60 trading days."""
    end_dt = (
        datetime.strptime(curr_date, "%Y-%m-%d")
        if curr_date else datetime.utcnow()
    )
    start_dt = end_dt - timedelta(days=120)

    symbols = [ticker.upper()] + [b.strip().upper() for b in benchmarks.split(",") if b.strip()]
    end_str = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    start_str = start_dt.strftime("%Y-%m-%d")

    rows = []
    base_returns = None
    for sym in symbols:
        try:
            tk = yf.Ticker(sym)
            df = yf_retry(lambda: tk.history(start=start_str, end=end_str))
        except Exception as e:
            rows.append((sym, None, None, None, f"fetch failed: {e}"))
            continue
        if df is None or df.empty:
            rows.append((sym, None, None, None, "no data"))
            continue
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df[df.index <= pd.Timestamp(end_dt)]
        if df.empty:
            rows.append((sym, None, None, None, "no data on/before curr_date"))
            continue
        close = df["Close"]
        r5, r20, r60 = _pct_return(close, 5), _pct_return(close, 20), _pct_return(close, 60)
        rows.append((sym, r5, r20, r60, None))
        if sym == ticker.upper():
            base_returns = (r5, r20, r60)

    fmt = lambda v: f"{v:+.2f}%" if isinstance(v, (int, float)) else "n/a"
    lines = [f"# Relative Strength: {ticker.upper()} vs {','.join(symbols[1:])} (via yfinance)"]
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
