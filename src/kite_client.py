"""Zerodha Kite Connect wrapper — historical data + live quotes."""
import logging
from datetime import datetime, timedelta
from functools import lru_cache
import pandas as pd
from kiteconnect import KiteConnect
import src.config as config

log = logging.getLogger(__name__)

_kite: KiteConnect | None = None


def get_kite() -> KiteConnect:
    global _kite
    if _kite is None:
        _kite = KiteConnect(api_key=config.KITE_API_KEY)
        if config.KITE_ACCESS_TOKEN:
            _kite.set_access_token(config.KITE_ACCESS_TOKEN)
        log.info("KiteConnect initialised")
    return _kite


def update_access_token(access_token: str) -> None:
    """Call after completing Kite login flow."""
    global _kite
    kite = get_kite()
    kite.set_access_token(access_token)
    log.info("Kite access token updated")


@lru_cache(maxsize=512)
def _resolve_instrument_token(symbol: str, exchange: str) -> int | None:
    """Resolve symbol to Kite instrument token (cached per session)."""
    try:
        instruments = get_kite().instruments(exchange)
        for inst in instruments:
            if inst["tradingsymbol"] == symbol.upper():
                return inst["instrument_token"]
    except Exception as e:
        log.error("instrument lookup failed: %s", e)
    return None


def get_historical(symbol: str, exchange: str, interval: str,
                   days: int = 30) -> pd.DataFrame | None:
    """
    Fetch OHLCV candles from Kite.

    interval: '5minute' | '15minute' | '60minute' | 'day' etc.
    Returns DataFrame with columns: date, open, high, low, close, volume
    """
    kite_interval = config.INTERVAL_MAP.get(interval, interval)
    token = _resolve_instrument_token(symbol, exchange)
    if token is None:
        log.warning("No token for %s:%s", exchange, symbol)
        return None
    try:
        to_dt   = datetime.now()
        from_dt = to_dt - timedelta(days=days)
        records = get_kite().historical_data(
            instrument_token=token,
            from_date=from_dt,
            to_date=to_dt,
            interval=kite_interval,
            continuous=False,
        )
        if not records:
            return None
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception as e:
        log.error("historical_data error for %s: %s", symbol, e)
        return None


def get_ltp(symbol: str, exchange: str) -> float | None:
    """Get last traded price."""
    try:
        key = f"{exchange}:{symbol}"
        data = get_kite().ltp([key])
        return data[key]["last_price"]
    except Exception as e:
        log.error("ltp error for %s: %s", symbol, e)
        return None


def get_quote(symbol: str, exchange: str) -> dict | None:
    """Get full quote including OHLC, volume, OI."""
    try:
        key = f"{exchange}:{symbol}"
        return get_kite().quote([key]).get(key)
    except Exception as e:
        log.error("quote error for %s: %s", symbol, e)
        return None


def generate_login_url() -> str:
    return get_kite().login_url()


def complete_login(request_token: str) -> str:
    """Exchange request token for access token."""
    data = get_kite().generate_session(
        request_token, api_secret=config.KITE_API_SECRET
    )
    access_token = data["access_token"]
    update_access_token(access_token)
    return access_token
