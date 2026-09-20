import logging
import xml.etree.ElementTree as ET
from datetime import datetime

from ib_async import Stock

from .tws_common import TWSConnectionError, tws_connection

logger = logging.getLogger(__name__)


def _build_coa_map(root: ET.Element) -> dict:
    """Build a coaCode → description lookup from the COAMap element."""
    coa_map = {}
    for item in root.iter("mapItem"):
        code = item.get("coaCode", "")
        desc = item.get("coaDesc", "")
        if code:
            coa_map[code] = desc or code
    return coa_map


def _parse_snapshot(xml_str: str, ticker: str) -> str:
    """Extract overview ratios from a ReportSnapshot XML string."""
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        return f"Error parsing TWS ReportSnapshot XML: {e}\n\nRaw (first 500 chars):\n{xml_str[:500]}"

    lines = [
        f"# Company Fundamentals for {ticker.upper()} (via TWS/IB)",
        f"# Report type: ReportSnapshot (Reuters/Refinitiv)\n",
    ]

    # Company general info
    for path, label in [
        (".//CoName", "Company Name"),
        (".//Ticker", "Ticker"),
        (".//ExchangeCode", "Exchange"),
        (".//SICDesc", "Industry"),
        (".//ISIN", "ISIN"),
    ]:
        elem = root.find(path)
        if elem is not None and elem.text and elem.text.strip():
            lines.append(f"{label}: {elem.text.strip()}")

    # Ratio groups
    for group in root.iter("Group"):
        group_id = group.get("ID", "")
        for ratio in group.findall("Ratio"):
            field = ratio.get("FieldName", "")
            rtype = ratio.get("Type", "")
            period = ratio.get("Period", "")
            val = ratio.text
            if val and val.strip() and val.strip() not in ("-", ""):
                parts = [field]
                if rtype:
                    parts.append(rtype)
                if period:
                    parts.append(period)
                label = " / ".join(parts)
                lines.append(f"{label}: {val.strip()}")

    return "\n".join(lines)


def _parse_financial_statement(
    xml_str: str,
    stmt_type: str,
    freq: str,
    curr_date: str,
    ticker: str,
    label: str,
) -> str:
    """
    Extract one statement type from a ReportsFinStatements XML string.

    stmt_type: "BAL" | "INC" | "CAS"
    freq:      "quarterly" | "annual"
    """
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        return f"Error parsing TWS ReportsFinStatements XML: {e}\n\nRaw (first 500 chars):\n{xml_str[:500]}"

    coa_map = _build_coa_map(root)

    # Period container varies by vendor XML version; try both tag names
    period_tag = "AnnualPeriods" if freq.lower() == "annual" else "InterimPeriods"
    periods_elem = root.find(f".//{period_tag}")
    if periods_elem is None:
        return f"No {freq} periods found in TWS financial data for {ticker}"

    # Collect periods, filter to curr_date to prevent look-ahead bias
    periods = periods_elem.findall("FiscalPeriod")
    if curr_date:
        # EndDate may be "YYYY-MM-DD" or "YYYYMMDD"
        cutoff = curr_date.replace("-", "")
        periods = [
            p for p in periods
            if p.get("EndDate", "").replace("-", "") <= cutoff
        ]

    if not periods:
        return f"No {freq} fiscal periods available on or before {curr_date} for {ticker}"

    # Sort descending and take the 4 most recent
    periods = sorted(
        periods,
        key=lambda p: p.get("EndDate", "").replace("-", ""),
        reverse=True,
    )[:4]

    header = (
        f"# {label} for {ticker.upper()} ({freq})\n"
        f"# Source: TWS (Interactive Brokers) / Reuters Fundamentals\n\n"
    )

    result_lines = []
    for period in periods:
        end_date = period.get("EndDate", "unknown")

        # Statement element may be a direct child or nested under a Statements wrapper
        stmt = period.find(f"Statement[@Type='{stmt_type}']")
        if stmt is None:
            stmt = period.find(f".//Statement[@Type='{stmt_type}']")
        if stmt is None:
            continue

        result_lines.append(f"Period ending {end_date}:")
        for item in stmt.iter():
            code = item.get("coaCode", "")
            if not code:
                continue
            val = item.text
            if val and val.strip() and val.strip() not in ("-", ""):
                desc = coa_map.get(code, code)
                result_lines.append(f"  {desc}: {val.strip()}")

    if not result_lines:
        return header + f"No {stmt_type} statement data found for {ticker}"

    return header + "\n".join(result_lines)


def _req_fundamental(ticker: str, report_type: str) -> str:
    """Call reqFundamentalData and return the raw XML string."""
    with tws_connection("tws_fundamentals._req_fundamental") as ib:
        contract = Stock(ticker.upper(), "SMART", "USD")
        xml = ib.reqFundamentalData(contract, report_type)
    if not xml:
        logger.error("[tws_fundamentals._req_fundamental] Empty response for %s/%s — check Reuters/Refinitiv subscription", ticker, report_type)
        raise ValueError(
            f"Empty response from TWS reqFundamentalData({report_type}) for {ticker}. "
            "Ensure you have an active Reuters/Refinitiv subscription."
        )
    logger.info("[tws_fundamentals._req_fundamental] Fetched %s for %s (%d bytes)", report_type, ticker, len(xml))
    return xml


def get_fundamentals(ticker: str, curr_date: str = None) -> str:
    """Retrieve company fundamentals overview via TWS reqFundamentalData(ReportSnapshot).

    Requires an active Reuters/Refinitiv Fundamentals subscription in IB.
    """
    try:
        xml = _req_fundamental(ticker, "ReportSnapshot")
    except TWSConnectionError:
        raise
    except Exception as e:
        logger.error("[tws_fundamentals.get_fundamentals] Failed for %s: %s", ticker, e)
        return f"Error retrieving TWS fundamentals for {ticker}: {e}"

    return _parse_snapshot(xml, ticker)


def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    """Retrieve balance sheet via TWS reqFundamentalData(ReportsFinStatements)."""
    try:
        xml = _req_fundamental(ticker, "ReportsFinStatements")
    except TWSConnectionError:
        raise
    except Exception as e:
        logger.error("[tws_fundamentals.get_balance_sheet] Failed for %s: %s", ticker, e)
        return f"Error retrieving TWS balance sheet for {ticker}: {e}"

    return _parse_financial_statement(xml, "BAL", freq, curr_date, ticker, "Balance Sheet")


def get_cashflow(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    """Retrieve cash flow statement via TWS reqFundamentalData(ReportsFinStatements)."""
    try:
        xml = _req_fundamental(ticker, "ReportsFinStatements")
    except TWSConnectionError:
        raise
    except Exception as e:
        logger.error("[tws_fundamentals.get_cashflow] Failed for %s: %s", ticker, e)
        return f"Error retrieving TWS cash flow for {ticker}: {e}"

    return _parse_financial_statement(xml, "CAS", freq, curr_date, ticker, "Cash Flow Statement")


def get_income_statement(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    """Retrieve income statement via TWS reqFundamentalData(ReportsFinStatements)."""
    try:
        xml = _req_fundamental(ticker, "ReportsFinStatements")
    except TWSConnectionError:
        raise
    except Exception as e:
        logger.error("[tws_fundamentals.get_income_statement] Failed for %s: %s", ticker, e)
        return f"Error retrieving TWS income statement for {ticker}: {e}"

    return _parse_financial_statement(xml, "INC", freq, curr_date, ticker, "Income Statement")
