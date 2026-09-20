import logging
from datetime import datetime

logger = logging.getLogger(__name__)

import pandas as pd
from dateutil.relativedelta import relativedelta
from ib_async import Stock
from stockstats import wrap as stockstats_wrap

from .tws_common import TWSConnectionError, tws_connection

_INDICATOR_DESCRIPTIONS = {
    "close_50_sma": (
        "50 SMA: A medium-term trend indicator. "
        "Usage: Identify trend direction and serve as dynamic support/resistance. "
        "Tips: It lags price; combine with faster indicators for timely signals."
    ),
    "close_200_sma": (
        "200 SMA: A long-term trend benchmark. "
        "Usage: Confirm overall market trend and identify golden/death cross setups. "
        "Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries."
    ),
    "close_10_ema": (
        "10 EMA: A responsive short-term average. "
        "Usage: Capture quick shifts in momentum and potential entry points. "
        "Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals."
    ),
    "macd": (
        "MACD: Computes momentum via differences of EMAs. "
        "Usage: Look for crossovers and divergence as signals of trend changes. "
        "Tips: Confirm with other indicators in low-volatility or sideways markets."
    ),
    "macds": (
        "MACD Signal: An EMA smoothing of the MACD line. "
        "Usage: Use crossovers with the MACD line to trigger trades. "
        "Tips: Should be part of a broader strategy to avoid false positives."
    ),
    "macdh": (
        "MACD Histogram: Shows the gap between the MACD line and its signal. "
        "Usage: Visualize momentum strength and spot divergence early. "
        "Tips: Can be volatile; complement with additional filters in fast-moving markets."
    ),
    "rsi": (
        "RSI: Measures momentum to flag overbought/oversold conditions. "
        "Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. "
        "Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis."
    ),
    "boll": (
        "Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. "
        "Usage: Acts as a dynamic benchmark for price movement. "
        "Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals."
    ),
    "boll_ub": (
        "Bollinger Upper Band: Typically 2 standard deviations above the middle line. "
        "Usage: Signals potential overbought conditions and breakout zones. "
        "Tips: Confirm signals with other tools; prices may ride the band in strong trends."
    ),
    "boll_lb": (
        "Bollinger Lower Band: Typically 2 standard deviations below the middle line. "
        "Usage: Indicates potential oversold conditions. "
        "Tips: Use additional analysis to avoid false reversal signals."
    ),
    "atr": (
        "ATR: Averages true range to measure volatility. "
        "Usage: Set stop-loss levels and adjust position sizes based on current market volatility. "
        "Tips: It's a reactive measure, so use it as part of a broader risk management strategy."
    ),
    "vwma": (
        "VWMA: A moving average weighted by volume. "
        "Usage: Confirm trends by integrating price action with volume data. "
        "Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses."
    ),
    "mfi": (
        "MFI: The Money Flow Index is a momentum indicator that uses both price and volume to measure "
        "buying and selling pressure. "
        "Usage: Identify overbought (>80) or oversold (<20) conditions and confirm the strength of trends "
        "or reversals. "
        "Tips: Use alongside RSI or MACD to confirm signals; divergence between price and MFI can indicate "
        "potential reversals."
    ),
}


def _fetch_ohlcv_from_tws(symbol: str, end_date: str, warmup_days: int = 730) -> pd.DataFrame:
    """Fetch daily OHLCV bars from TWS and return a stockstats-compatible DataFrame."""
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    total_days = warmup_days + 60  # buffer for weekends/holidays

    if total_days <= 365:
        duration = f"{total_days} D"
    else:
        duration = f"{(total_days // 365) + 1} Y"

    with tws_connection("tws_indicator.get_indicator") as ib:
        contract = Stock(symbol.upper(), "SMART", "USD")
        bars = ib.reqHistoricalData(
            contract,
            endDateTime=end_dt.strftime("%Y%m%d 23:59:59"),
            durationStr=duration,
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
        )

    if not bars:
        logger.warning("[tws_indicator.get_indicator] No bars returned for %s (end=%s)", symbol, end_date)
        return pd.DataFrame()

    df = pd.DataFrame([
        {
            "Date": pd.Timestamp(bar.date),
            "Open": float(bar.open),
            "High": float(bar.high),
            "Low": float(bar.low),
            "Close": float(bar.close),
            "Volume": float(bar.volume),
        }
        for bar in bars
    ])

    # Prevent look-ahead bias
    df = df[df["Date"] <= pd.Timestamp(end_date)].reset_index(drop=True)
    logger.info("[tws_indicator.get_indicator] Fetched %d bars for %s (end=%s)", len(df), symbol, end_date)
    return df


def get_indicator(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int,
    interval: str = "daily",
    time_period: int = 14,
    series_type: str = "close",
) -> str:
    """
    Returns technical indicator values computed from TWS OHLCV data via stockstats.

    Args:
        symbol: ticker symbol
        indicator: indicator name (e.g. 'rsi', 'macd', 'close_50_sma')
        curr_date: current trading date in YYYY-mm-dd
        look_back_days: number of calendar days to report
        interval: unused (daily bars only via TWS); kept for API compatibility
        time_period: unused; kept for API compatibility
        series_type: unused; kept for API compatibility

    Returns:
        Formatted string with indicator values and description.
    """
    if indicator not in _INDICATOR_DESCRIPTIONS:
        raise ValueError(
            f"Indicator '{indicator}' is not supported. Choose from: {list(_INDICATOR_DESCRIPTIONS.keys())}"
        )

    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    before = curr_date_dt - relativedelta(days=look_back_days)

    # Fetch enough history so stockstats has a warm-up window (200 SMA needs 200+ days)
    warmup = max(look_back_days + 250, 730)

    try:
        df = _fetch_ohlcv_from_tws(symbol, curr_date, warmup_days=warmup)
    except TWSConnectionError:
        raise
    except Exception as e:
        return f"Error fetching TWS data for indicator '{indicator}': {e}"

    if df.empty:
        return f"No TWS OHLCV data available for {symbol}"

    try:
        sdf = stockstats_wrap(df)
        sdf["Date"] = pd.to_datetime(sdf["Date"]).dt.strftime("%Y-%m-%d")
        sdf[indicator]  # trigger stockstats calculation

        date_value_map = {
            row["Date"]: "N/A" if pd.isna(row[indicator]) else str(row[indicator])
            for _, row in sdf.iterrows()
        }
    except Exception as e:
        return f"Error computing '{indicator}' from TWS data: {e}"

    ind_string = ""
    current_dt = curr_date_dt
    while current_dt >= before:
        date_str = current_dt.strftime("%Y-%m-%d")
        value = date_value_map.get(date_str, "N/A: Not a trading day (weekend or holiday)")
        ind_string += f"{date_str}: {value}\n"
        current_dt -= relativedelta(days=1)

    return (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
        + ind_string
        + "\n\n"
        + _INDICATOR_DESCRIPTIONS.get(indicator, "No description available.")
    )
