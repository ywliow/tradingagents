from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.tws_common import TWSConnectionError


@tool
def get_earnings_calendar(
    ticker: Annotated[str, "Ticker symbol"],
    curr_date: Annotated[str, "Current trading date in yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve the next earnings date and recent earnings history (estimate vs actual,
    surprise %, post-earnings drift T+1 / T+5 where supported by the vendor).

    For 1-3 week swing trades this answers: is an earnings event inside the holding
    window, and how has this name behaved on prior prints.
    Uses the configured swing_signals vendor.
    """
    return route_to_vendor("get_earnings_calendar", ticker, curr_date)


@tool
def get_relative_strength(
    ticker: Annotated[str, "Ticker symbol"],
    curr_date: Annotated[str, "Current trading date in yyyy-mm-dd"] = None,
    benchmarks: Annotated[
        str, "Comma-separated benchmark tickers, e.g. 'SPY,QQQ' or 'SPY,XLK'"
    ] = "SPY,QQQ",
) -> str:
    """
    Compute % return for the ticker vs benchmarks over 5 / 20 / 60 trading days,
    plus the spread (ticker − benchmark) per window.

    Swing winners overwhelmingly outperform their benchmark and sector — use this
    to confirm leadership before taking a long swing, or to filter shorts.
    Uses the configured swing_signals vendor.
    """
    return route_to_vendor("get_relative_strength", ticker, curr_date, benchmarks)


@tool
def get_unusual_options_activity(
    ticker: Annotated[str, "Ticker symbol"],
    curr_date: Annotated[str, "Current trading date in yyyy-mm-dd"] = None,
) -> str:
    """
    Snapshot the front-month ATM option chain (±5 strikes): call/put volume,
    open interest, put/call ratios, and average implied volatility.

    Use to detect directional positioning ahead of catalysts. TWS-only — falls
    through with a clear message when TWS is not the active vendor.
    """
    try:
        return route_to_vendor("get_unusual_options_activity", ticker, curr_date)
    except TWSConnectionError as e:
        return (
            f"Options activity for '{ticker}' unavailable: TWS/IB Gateway is not "
            f"reachable ({e}). Skip this signal and proceed without options-flow input."
        )
    except RuntimeError as e:
        return (
            f"Options activity for '{ticker}' unavailable: {e}. "
            "TWS is the only supported vendor — skip this signal."
        )
