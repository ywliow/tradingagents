import logging
from datetime import datetime

from ib_async import Stock

from .tws_common import TWSConnectionError, tws_connection

logger = logging.getLogger(__name__)

# Broad market proxies used for global news queries
_GLOBAL_NEWS_SYMBOLS = ["SPY", "QQQ", "DIA"]


def _fmt_dt(date_str: str, end_of_day: bool = False) -> str:
    """Convert yyyy-mm-dd to IB reqHistoricalNews format 'YYYYMMDD HH:MM:SS'."""
    time = "23:59:59" if end_of_day else "00:00:00"
    return datetime.strptime(date_str, "%Y-%m-%d").strftime(f"%Y%m%d {time}")


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    """
    Retrieve news headlines for a stock ticker via TWS reqHistoricalNews.

    Requires at least one news provider subscription in IB (e.g. Dow Jones,
    Briefing.com, Benzinga). Returns an empty result if no providers are active.

    Args:
        ticker: stock ticker symbol
        start_date: start date yyyy-mm-dd
        end_date: end date yyyy-mm-dd

    Returns:
        Formatted string with news headlines, or an informative message on failure.
    """
    try:
        with tws_connection("tws_news.get_news") as ib:
            # Discover active news providers
            providers = ib.reqNewsProviders()
            if not providers:
                return (
                    f"No news providers available in your TWS/IB account for {ticker}. "
                    "Subscribe to a news provider (e.g. Dow Jones, Briefing.com) in IB."
                )

            provider_codes = ",".join(p.code for p in providers)

            # Qualify the contract to obtain conId (required for reqHistoricalNews)
            contract = Stock(ticker.upper(), "SMART", "USD")
            qualified = ib.qualifyContracts(contract)
            if not qualified:
                return f"Could not qualify contract for '{ticker}' via TWS"

            con_id = qualified[0].conId
            headlines = ib.reqHistoricalNews(
                conId=con_id,
                providerCodes=provider_codes,
                startDateTime=_fmt_dt(start_date),
                endDateTime=_fmt_dt(end_date, end_of_day=True),
                totalResults=50,
            )
    except TWSConnectionError:
        raise
    except Exception as e:
        logger.error("[tws_news.get_news] Fetch failed for %s: %s", ticker, e)
        return f"Error fetching TWS news for '{ticker}': {e}"

    if not headlines:
        logger.warning("[tws_news.get_news] No headlines for %s (%s to %s)", ticker, start_date, end_date)
        return f"No news found for {ticker} between {start_date} and {end_date} via TWS"

    logger.info("[tws_news.get_news] Fetched %d headlines for %s (%s to %s)", len(headlines), ticker, start_date, end_date)
    lines = [f"## {ticker} News, from {start_date} to {end_date} (via TWS):\n"]
    for h in headlines:
        ts = str(h.time)[:10] if h.time else "unknown date"
        lines.append(f"### {h.headline} (source: {h.providerCode}, {ts})")
        lines.append("")

    return "\n".join(lines)


def get_global_news(curr_date: str, look_back_days: int = 7, limit: int = 50) -> str:
    """
    Retrieve broad market news via TWS by querying representative ETFs (SPY, QQQ, DIA).

    Args:
        curr_date: current date yyyy-mm-dd
        look_back_days: number of days to look back
        limit: max headlines to return

    Returns:
        Formatted string with news headlines.
    """
    from datetime import timedelta

    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_date = (curr_dt - timedelta(days=look_back_days)).strftime("%Y-%m-%d")

    try:
        with tws_connection("tws_news.get_global_news") as ib:
            providers = ib.reqNewsProviders()
            if not providers:
                return (
                    "No news providers available in your TWS/IB account. "
                    "Subscribe to a news provider (e.g. Dow Jones, Briefing.com) in IB."
                )

            provider_codes = ",".join(p.code for p in providers)

            seen = set()
            all_headlines = []

            for symbol in _GLOBAL_NEWS_SYMBOLS:
                if len(all_headlines) >= limit:
                    break
                contract = Stock(symbol, "SMART", "USD")
                qualified = ib.qualifyContracts(contract)
                if not qualified:
                    continue

                con_id = qualified[0].conId
                headlines = ib.reqHistoricalNews(
                    conId=con_id,
                    providerCodes=provider_codes,
                    startDateTime=_fmt_dt(start_date),
                    endDateTime=_fmt_dt(curr_date, end_of_day=True),
                    totalResults=limit,
                )

                for h in headlines:
                    key = h.headline.strip()
                    if key not in seen:
                        seen.add(key)
                        all_headlines.append(h)

    except TWSConnectionError:
        raise
    except Exception as e:
        logger.error("[tws_news.get_global_news] Fetch failed: %s", e)
        return f"Error fetching global news via TWS: {e}"

    if not all_headlines:
        logger.warning("[tws_news.get_global_news] No headlines found for %s to %s", start_date, curr_date)
        return f"No global news found via TWS for {start_date} to {curr_date}"

    logger.info("[tws_news.get_global_news] Fetched %d headlines for %s to %s", len(all_headlines), start_date, curr_date)
    lines = [f"## Global Market News, from {start_date} to {curr_date} (via TWS):\n"]
    for h in all_headlines[:limit]:
        ts = str(h.time)[:10] if h.time else "unknown date"
        lines.append(f"### {h.headline} (source: {h.providerCode}, {ts})")
        lines.append("")

    return "\n".join(lines)


def get_insider_transactions(symbol: str, curr_date: str = None, lookback_days: int = 30) -> str:
    """TWS does not expose insider transaction data via its API."""
    return (
        f"Insider transactions for '{symbol}' are not available via TWS/IB Gateway. "
        "Configure 'alpha_vantage' or 'yfinance' as the vendor for insider_transactions "
        "in your dataflows config."
    )
