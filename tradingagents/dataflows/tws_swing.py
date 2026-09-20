"""Swing-trading data via TWS/IB Gateway.

- get_earnings_calendar: ReportsCalEvents XML
- get_relative_strength : reuse tws_stock OHLCV
- get_unusual_options_activity: option chain stats (ATM, front-month)
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import pandas as pd
from ib_async import Option, Stock

from .tws_common import TWSConnectionError, tws_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Earnings calendar — ReportsCalEvents XML
# ---------------------------------------------------------------------------

def _parse_cal_events(xml_str: str, ticker: str, curr_date: str = None) -> str:
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        return f"Error parsing TWS ReportsCalEvents XML: {e}\n\nRaw (first 500 chars):\n{xml_str[:500]}"

    # IB calendar events vary by vendor; collect any element that looks like an earnings event
    events = []
    for evt in root.iter():
        tag = evt.tag.lower()
        if "earn" not in tag and tag not in ("event", "calevent"):
            continue
        date = (
            evt.get("Date")
            or evt.get("date")
            or evt.findtext("Date")
            or evt.findtext("EventDate")
        )
        if not date:
            continue
        kind = evt.get("Type") or evt.get("Name") or evt.tag
        eps_est = evt.get("EpsEstimate") or evt.findtext("EpsEstimate")
        eps_act = evt.get("EpsActual") or evt.findtext("EpsActual")
        events.append({"date": date[:10], "kind": kind, "est": eps_est, "act": eps_act})

    if not events:
        return f"No earnings calendar events found for {ticker.upper()} via TWS ReportsCalEvents"

    events.sort(key=lambda e: e["date"])
    cutoff = curr_date or datetime.utcnow().strftime("%Y-%m-%d")
    past = [e for e in events if e["date"] <= cutoff][-4:]
    future = [e for e in events if e["date"] > cutoff]

    lines = [f"# Earnings Calendar for {ticker.upper()} (via TWS/IB)"]
    if curr_date:
        lines.append(f"# As of: {curr_date}\n")

    if future:
        nxt = future[0]
        try:
            days_to = (datetime.strptime(nxt["date"], "%Y-%m-%d") - datetime.strptime(cutoff, "%Y-%m-%d")).days
            lines.append(f"## Next Earnings: {nxt['date']} ({days_to} days away)")
        except ValueError:
            lines.append(f"## Next Earnings: {nxt['date']}")
        if nxt.get("est"):
            lines.append(f"- Consensus EPS estimate: {nxt['est']}")
        lines.append("")
    else:
        lines.append("## Next Earnings: none in IB calendar window\n")

    if past:
        lines.append("## Last Reports")
        lines.append("| Date | Kind | EPS Est | EPS Actual |")
        lines.append("|---|---|---|---|")
        for e in past:
            lines.append(
                f"| {e['date']} | {e.get('kind') or 'n/a'} "
                f"| {e.get('est') or 'n/a'} | {e.get('act') or 'n/a'} |"
            )

    return "\n".join(lines)


def get_earnings_calendar(ticker: str, curr_date: str = None) -> str:
    """Earnings dates via TWS reqFundamentalData('ReportsCalEvents').

    Requires Reuters/Refinitiv subscription on the IB account.
    """
    try:
        with tws_connection("tws_swing.get_earnings_calendar") as ib:
            contract = Stock(ticker.upper(), "SMART", "USD")
            xml = ib.reqFundamentalData(contract, "ReportsCalEvents")
    except TWSConnectionError:
        raise
    except Exception as e:
        logger.error("[tws_swing.get_earnings_calendar] Failed for %s: %s", ticker, e)
        return f"Error retrieving TWS earnings calendar for {ticker}: {e}"

    if not xml:
        return (
            f"Empty ReportsCalEvents response for {ticker} via TWS. "
            "Ensure Reuters/Refinitiv subscription is active."
        )
    return _parse_cal_events(xml, ticker, curr_date)


# ---------------------------------------------------------------------------
# Relative strength
# ---------------------------------------------------------------------------

def _fetch_close_series(ib, symbol: str, end_dt: datetime, days: int = 120) -> pd.Series:
    contract = Stock(symbol.upper(), "SMART", "USD")
    duration = f"{days + 30} D"
    bars = ib.reqHistoricalData(
        contract,
        endDateTime=end_dt.strftime("%Y%m%d 23:59:59"),
        durationStr=duration,
        barSizeSetting="1 day",
        whatToShow="TRADES",
        useRTH=True,
    )
    if not bars:
        return pd.Series(dtype=float)
    s = pd.Series(
        {pd.Timestamp(bar.date): float(bar.close) for bar in bars}
    ).sort_index()
    return s[s.index <= pd.Timestamp(end_dt)]


def _pct_return(s: pd.Series, days: int) -> float | None:
    if len(s) <= days:
        return None
    end = float(s.iloc[-1])
    start = float(s.iloc[-1 - days])
    if start <= 0:
        return None
    return (end / start - 1) * 100


def get_relative_strength(ticker: str, curr_date: str = None, benchmarks: str = "SPY,QQQ") -> str:
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d") if curr_date else datetime.utcnow()
    symbols = [ticker.upper()] + [b.strip().upper() for b in benchmarks.split(",") if b.strip()]

    rows = []
    base_returns = None
    try:
        with tws_connection("tws_swing.get_relative_strength") as ib:
            for sym in symbols:
                try:
                    s = _fetch_close_series(ib, sym, end_dt)
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
    except TWSConnectionError:
        raise

    fmt = lambda v: f"{v:+.2f}%" if isinstance(v, (int, float)) else "n/a"
    lines = [f"# Relative Strength: {ticker.upper()} vs {','.join(symbols[1:])} (via TWS)"]
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


# ---------------------------------------------------------------------------
# Unusual options activity (TWS-only)
# ---------------------------------------------------------------------------

def _front_month_expiry(expirations: list[str], curr_date: str | None) -> str | None:
    """Pick the nearest expiration on or after curr_date (or today)."""
    cutoff = (
        datetime.strptime(curr_date, "%Y-%m-%d") if curr_date else datetime.utcnow()
    )
    parsed = []
    for e in expirations:
        try:
            parsed.append((datetime.strptime(e, "%Y%m%d"), e))
        except ValueError:
            continue
    parsed = [p for p in parsed if p[0] >= cutoff]
    if not parsed:
        return None
    parsed.sort()
    return parsed[0][1]


def _ticker_field(t, *names):
    """Pick the first non-NaN attribute among names from an ib_async Ticker."""
    for n in names:
        v = getattr(t, n, None)
        if v is not None and v == v:  # NaN check
            return v
    return None


def get_unusual_options_activity(ticker: str, curr_date: str = None) -> str:
    """Approximate unusual options activity via TWS option chain snapshot.

    Pulls the front-month expiration, samples ATM ± 5 strikes for both calls and puts,
    snapshots volume / open-interest / IV, and reports aggregates.
    """
    try:
        with tws_connection("tws_swing.get_unusual_options_activity") as ib:
            stock = Stock(ticker.upper(), "SMART", "USD")
            qualified = ib.qualifyContracts(stock)
            if not qualified:
                return f"Could not qualify contract for '{ticker}' via TWS"
            stk = qualified[0]

            spot_ticker = ib.reqMktData(stk, "", False, False)
            ib.sleep(1.5)
            spot = _ticker_field(spot_ticker, "marketPrice", "last", "close")
            ib.cancelMktData(stk)
            if spot is None or spot <= 0:
                return f"Could not retrieve spot price for {ticker} from TWS"

            chains = ib.reqSecDefOptParams(stk.symbol, "", stk.secType, stk.conId)
            if not chains:
                return f"No option chain available for {ticker} via TWS"

            chain = next(
                (c for c in chains if c.exchange == "SMART"),
                chains[0],
            )

            expiry = _front_month_expiry(sorted(chain.expirations), curr_date)
            if not expiry:
                return f"No upcoming expirations for {ticker} options"

            strikes = sorted(s for s in chain.strikes if s > 0)
            atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
            window = strikes[max(0, atm_idx - 5): atm_idx + 6]

            contracts = []
            for k in window:
                for right in ("C", "P"):
                    contracts.append(
                        Option(stk.symbol, expiry, k, right, "SMART", tradingClass=chain.tradingClass)
                    )

            qualified_opts = ib.qualifyContracts(*contracts)
            tickers = [ib.reqMktData(c, "100,101,106", False, False) for c in qualified_opts]
            ib.sleep(3.0)

            rows = []
            for t in tickers:
                vol = _ticker_field(t, "volume")
                oi = _ticker_field(t, "callOpenInterest" if t.contract.right == "C" else "putOpenInterest")
                iv = _ticker_field(t, "impliedVolatility", "modelGreeks")
                if hasattr(iv, "impliedVol"):
                    iv = iv.impliedVol
                rows.append({
                    "right": t.contract.right,
                    "strike": t.contract.strike,
                    "volume": float(vol) if vol is not None else 0.0,
                    "oi": float(oi) if oi is not None else 0.0,
                    "iv": float(iv) if isinstance(iv, (int, float)) else None,
                })

            for c in qualified_opts:
                ib.cancelMktData(c)
    except TWSConnectionError:
        raise
    except Exception as e:
        logger.error("[tws_swing.get_unusual_options_activity] Failed for %s: %s", ticker, e)
        return f"Error retrieving TWS options activity for {ticker}: {e}"

    if not rows:
        return f"No option market data returned for {ticker}"

    df = pd.DataFrame(rows)
    calls = df[df["right"] == "C"]
    puts = df[df["right"] == "P"]
    call_vol = calls["volume"].sum()
    put_vol = puts["volume"].sum()
    call_oi = calls["oi"].sum()
    put_oi = puts["oi"].sum()
    pcr_vol = put_vol / call_vol if call_vol > 0 else None
    pcr_oi = put_oi / call_oi if call_oi > 0 else None
    avg_iv = df["iv"].dropna().mean() if df["iv"].notna().any() else None

    top_vol = df.sort_values("volume", ascending=False).head(5)

    lines = [
        f"# Unusual Options Activity for {ticker.upper()} (via TWS)",
        f"# Spot: {spot:.2f}  |  Expiry sampled: {expiry}  |  Strikes: ATM ±5",
    ]
    if curr_date:
        lines.append(f"# As of: {curr_date}")
    lines.append("")
    lines.append("## Aggregates (front-month, ATM band)")
    lines.append(f"- Call volume: {int(call_vol):,}    Put volume: {int(put_vol):,}")
    lines.append(f"- Call OI: {int(call_oi):,}    Put OI: {int(put_oi):,}")
    if pcr_vol is not None:
        lines.append(f"- Put/Call volume ratio: {pcr_vol:.2f}  (>1 bearish, <0.7 bullish)")
    if pcr_oi is not None:
        lines.append(f"- Put/Call OI ratio: {pcr_oi:.2f}")
    if avg_iv is not None:
        lines.append(f"- Avg implied vol (sampled strikes): {avg_iv * 100:.1f}%")
    lines.append("")
    lines.append("## Top 5 by volume")
    lines.append("| Right | Strike | Volume | OI | IV |")
    lines.append("|---|---|---|---|---|")
    for _, r in top_vol.iterrows():
        iv_s = f"{r['iv'] * 100:.1f}%" if pd.notna(r["iv"]) else "n/a"
        lines.append(
            f"| {r['right']} | {r['strike']:.2f} | {int(r['volume']):,} | {int(r['oi']):,} | {iv_s} |"
        )
    lines.append("")
    lines.append(
        "_Note: snapshot only — IB does not provide historical option volume averages, "
        "so 'unusual' must be inferred from PCR skew, OI build-up, and IV vs underlying ATR._"
    )

    return "\n".join(lines)
