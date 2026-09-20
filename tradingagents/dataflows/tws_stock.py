import logging
from datetime import datetime

import pandas as pd
from ib_async import Stock

from .tws_common import TWSConnectionError, tws_connection

logger = logging.getLogger(__name__)


def get_stock(symbol: str, start_date: str, end_date: str) -> str:
    """
    Returns daily OHLCV data for a given symbol via TWS/IB Gateway.

    Args:
        symbol: ticker symbol (e.g., 'AAPL')
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        CSV string with OHLCV data, or an error message string.
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    days = (end_dt - start_dt).days + 1

    # IB caps "N D" at 365; for longer ranges use years
    if days <= 365:
        duration = f"{days} D"
    else:
        duration = f"{(days // 365) + 1} Y"

    try:
        with tws_connection("tws_stock.get_stock") as ib:
            contract = Stock(symbol.upper(), "SMART", "USD")
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end_dt.strftime("%Y%m%d 23:59:59"),
                durationStr=duration,
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=True,
            )
    except TWSConnectionError:
        raise
    except Exception as e:
        logger.error("[tws_stock.get_stock] Data fetch failed for %s: %s", symbol, e)
        return f"Error fetching TWS stock data for '{symbol}': {e}"

    if not bars:
        logger.warning("[tws_stock.get_stock] No bars returned for %s (%s to %s)", symbol, start_date, end_date)
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

    df = pd.DataFrame([
        {
            "Date": pd.Timestamp(bar.date),
            "Open": round(float(bar.open), 2),
            "High": round(float(bar.high), 2),
            "Low": round(float(bar.low), 2),
            "Close": round(float(bar.close), 2),
            "Volume": int(bar.volume),
        }
        for bar in bars
    ])

    df = df[
        (df["Date"] >= pd.Timestamp(start_date))
        & (df["Date"] <= pd.Timestamp(end_date))
    ]
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

    if df.empty:
        logger.warning("[tws_stock.get_stock] No data in date range for %s (%s to %s)", symbol, start_date, end_date)
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

    logger.info("[tws_stock.get_stock] Fetched %d records for %s (%s to %s)", len(df), symbol, start_date, end_date)
    header = (
        f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
        f"# Total records: {len(df)}\n"
        f"# Source: TWS (Interactive Brokers)\n\n"
    )
    return header + df.to_csv(index=False)
