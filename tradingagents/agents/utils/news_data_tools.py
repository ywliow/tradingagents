from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor

@tool
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve news data for a given ticker symbol.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    return route_to_vendor("get_news", ticker, start_date, end_date)

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of days to look back"] = 7,
    limit: Annotated[int, "Maximum number of articles to return"] = 5,
) -> str:
    """
    Retrieve global news data.
    Uses the configured news_data vendor.
    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back (default 7)
        limit (int): Maximum number of articles to return (default 5)
    Returns:
        str: A formatted string containing global news data
    """
    return route_to_vendor("get_global_news", curr_date, look_back_days, limit)

@tool
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current trading date in yyyy-mm-dd; used as the upper bound for filtering"] = None,
    lookback_days: Annotated[int, "how many calendar days back from curr_date to include"] = 30,
) -> str:
    """
    Retrieve insider transactions for the last `lookback_days` calendar days.
    Uses the configured news_data vendor. Default 30d — the swing-trade window
    where insider clusters carry signal; older transactions are typically noise.

    Args:
        ticker (str): Ticker symbol of the company
        curr_date (str): Current trading date, yyyy-mm-dd. Filter upper bound.
        lookback_days (int): How many days back to include (default 30).
    Returns:
        str: A report of insider transaction data filtered to the window
    """
    return route_to_vendor("get_insider_transactions", ticker, curr_date, lookback_days)
