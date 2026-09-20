import logging
import os
import time
from contextlib import contextmanager

from ib_async import IB

logger = logging.getLogger(__name__)

# 5 retries → 6 total connection attempts, each gap is 2 minutes
_CONNECT_RETRIES = 5
#_RETRY_DELAY_SECS = 120
_RETRY_DELAY_SECS = 1

class TWSConnectionError(Exception):
    """Raised when all TWS/IB Gateway connection attempts are exhausted."""
    pass


def _get_connection_params() -> dict:
    return {
        "host": os.getenv("TWS_HOST", "127.0.0.1"),
        "port": int(os.getenv("TWS_PORT", "7496")),
        "client_id": int(os.getenv("TWS_CLIENT_ID", "1")),
    }


@contextmanager
def tws_connection(caller: str = "unknown"):
    """Context manager that opens and cleanly closes a TWS/IB Gateway connection.

    Retries the connect() call up to _CONNECT_RETRIES times with a
    _RETRY_DELAY_SECS pause between attempts before raising TWSConnectionError.

    Args:
        caller: Name of the calling function, included in all log messages.

    Env vars:
        TWS_HOST      — default 127.0.0.1
        TWS_PORT      — default 7496 (TWS paper); IB Gateway paper=4002, live=4001
        TWS_CLIENT_ID — default 1
    """
    params = _get_connection_params()
    ib = IB()
    last_error: Exception | None = None

    for attempt in range(_CONNECT_RETRIES + 1):
        try:
            ib.connect(params["host"], params["port"], clientId=params["client_id"])
            logger.info(
                "[%s] TWS connected to %s:%s (client_id=%s) on attempt %d/%d",
                caller,
                params["host"],
                params["port"],
                params["client_id"],
                attempt + 1,
                _CONNECT_RETRIES + 1,
            )
            last_error = None
            break
        except Exception as e:
            last_error = e
            if attempt < _CONNECT_RETRIES:
                logger.warning(
                    "[%s] TWS connect attempt %d/%d failed, retrying in %ds: %s",
                    caller,
                    attempt + 1,
                    _CONNECT_RETRIES + 1,
                    _RETRY_DELAY_SECS,
                    e,
                )
                time.sleep(_RETRY_DELAY_SECS)
    else:
        raise TWSConnectionError(
            f"[{caller}] Failed to connect to TWS at {params['host']}:{params['port']} after "
            f"{_CONNECT_RETRIES + 1} attempts: {last_error}"
        ) from last_error

    try:
        yield ib
    finally:
        if ib.isConnected():
            ib.disconnect()
