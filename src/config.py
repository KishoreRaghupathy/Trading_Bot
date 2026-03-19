"""Central configuration loaded from .env"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USERS: set[int] = {
    int(uid.strip())
    for uid in os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",")
    if uid.strip()
}

# ── Zerodha ───────────────────────────────────────────────────
KITE_API_KEY: str = os.environ["KITE_API_KEY"]
KITE_API_SECRET: str = os.environ["KITE_API_SECRET"]
KITE_ACCESS_TOKEN: str = os.getenv("KITE_ACCESS_TOKEN", "")

# ── OpenAI ────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")

# ── App ───────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
DB_PATH: str = os.getenv("DB_PATH", "data/trading_bot.db")
TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Kolkata")

# ── Alert thresholds ─────────────────────────────────────────
VOLUME_SPIKE_MULTIPLIER: float = float(os.getenv("VOLUME_SPIKE_MULTIPLIER", "2.0"))
RSI_OVERBOUGHT: float = float(os.getenv("RSI_OVERBOUGHT", "70"))
RSI_OVERSOLD: float = float(os.getenv("RSI_OVERSOLD", "30"))

# ── Kite exchange-to-segment mapping ─────────────────────────
EXCHANGE_MAP = {
    "MCX": "MCX",
    "NSE": "NSE",
    "NFO": "NFO",
    "BSE": "BSE",
    "CDS": "CDS",
    "BFO": "BFO",
}

# ── Interval label -> Kite interval ──────────────────────────
INTERVAL_MAP = {
    "1m":  "minute",
    "3m":  "3minute",
    "5m":  "5minute",
    "10m": "10minute",
    "15m": "15minute",
    "30m": "30minute",
    "1h":  "60minute",
    "1d":  "day",
}
