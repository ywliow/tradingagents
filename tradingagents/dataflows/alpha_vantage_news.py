from .alpha_vantage_common import _make_api_request, format_datetime_for_api

def get_news(ticker, start_date, end_date) -> dict[str, str] | str:
    """Returns live and historical market news & sentiment data from premier news outlets worldwide.

    Covers stocks, cryptocurrencies, forex, and topics like fiscal policy, mergers & acquisitions, IPOs.

    Args:
        ticker: Stock symbol for news articles.
        start_date: Start date for news search.
        end_date: End date for news search.

    Returns:
        Dictionary containing news sentiment data or JSON string.
    """

    params = {
        "tickers": ticker,
        "time_from": format_datetime_for_api(start_date),
        "time_to": format_datetime_for_api(end_date),
    }

    return _make_api_request("NEWS_SENTIMENT", params)

def get_global_news(curr_date, look_back_days: int = 7, limit: int = 50) -> dict[str, str] | str:
    """Returns global market news & sentiment data without ticker-specific filtering.

    Covers broad market topics like financial markets, economy, and more.

    Args:
        curr_date: Current date in yyyy-mm-dd format.
        look_back_days: Number of days to look back (default 7).
        limit: Maximum number of articles (default 50).

    Returns:
        Dictionary containing global news sentiment data or JSON string.
    """
    from datetime import datetime, timedelta

    # Calculate start date
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - timedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    params = {
        "topics": "financial_markets,economy_macro,economy_monetary",
        "time_from": format_datetime_for_api(start_date),
        "time_to": format_datetime_for_api(curr_date),
        "limit": str(limit),
    }

    return _make_api_request("NEWS_SENTIMENT", params)


def get_insider_transactions(symbol: str, curr_date: str = None, lookback_days: int = 30) -> str:
    """Returns insider transactions filtered to the last `lookback_days` days.

    Args:
        symbol: Ticker symbol. Example: "IBM".
        curr_date: Upper-bound date in yyyy-mm-dd; defaults to today.
        lookback_days: Calendar days back from curr_date (default 30).

    Returns:
        JSON-shaped dict (or its string form) limited to the window. Falls back
        to raw response if filtering can't be applied.
    """
    import json
    from datetime import datetime, timedelta

    raw = _make_api_request("INSIDER_TRANSACTIONS", {"symbol": symbol})
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw
    else:
        payload = raw

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not rows:
        return json.dumps(payload) if isinstance(payload, dict) else str(payload)

    end_dt = datetime.strptime(curr_date, "%Y-%m-%d") if curr_date else datetime.utcnow()
    start_dt = end_dt - timedelta(days=lookback_days)

    def _in_window(row):
        d = row.get("transaction_date") or row.get("transactionDate") or ""
        try:
            dt = datetime.strptime(d[:10], "%Y-%m-%d")
        except ValueError:
            return False
        return start_dt <= dt <= end_dt

    filtered = [r for r in rows if _in_window(r)]
    if not filtered:
        return (
            f"No insider transactions for {symbol.upper()} in the last "
            f"{lookback_days} days ending {end_dt.strftime('%Y-%m-%d')}"
        )

    return json.dumps({"symbol": symbol.upper(), "window_days": lookback_days, "data": filtered})