"""OpenAI GPT integration for natural-language market analysis."""
import logging
from openai import AsyncOpenAI
import src.config as config

log = logging.getLogger(__name__)
_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    return _client


SYSTEM_PROMPT = """You are an expert Indian commodity and equity trader assistant.
You analyse technical indicators for MCX futures (NATGASMINI, Crude, Gold),
NSE equity/F&O, and crypto. Always be concise. Use ₹ for INR.
Format responses for Telegram (use bold *text*, italic _text_, and emojis).
Never give direct buy/sell advice — frame everything as analytical observation.
"""


async def get_ai_summary(analysis_text: str, symbol: str) -> str:
    """Ask GPT to summarise a technical analysis dict into readable insight."""
    try:
        resp = await get_client().chat.completions.create(
            model=config.OPENAI_MODEL,
            max_tokens=500,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Give a concise trading insight for *{symbol}* "
                        f"based on this analysis:\n\n{analysis_text}\n\n"
                        "Include: trend bias, key levels to watch, and a risk note."
                    ),
                },
            ],
        )
        return resp.choices[0].message.content or "No summary generated."
    except Exception as e:
        log.error("OpenAI error: %s", e)
        return "_AI summary unavailable right now._"


async def get_risk_advice(symbol: str, side: str, entry: float,
                          sl: float, target: float, qty: float) -> str:
    """GPT risk/reward commentary on a proposed trade."""
    rr = abs(target - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
    try:
        resp = await get_client().chat.completions.create(
            model=config.OPENAI_MODEL,
            max_tokens=300,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Trade setup for {symbol}:\n"
                        f"Side: {side}, Entry: {entry}, SL: {sl}, "
                        f"Target: {target}, Qty: {qty}, R:R = {rr:.2f}\n"
                        "Give a brief risk assessment in 3-4 bullet points."
                    ),
                },
            ],
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        log.error("OpenAI risk advice error: %s", e)
        return "_AI risk assessment unavailable._"


async def get_market_summary(watchlist_data: str) -> str:
    """End-of-day AI summary for the user's watchlist."""
    try:
        resp = await get_client().chat.completions.create(
            model=config.OPENAI_MODEL,
            max_tokens=600,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Here is today's market snapshot for my watchlist:\n\n"
                        f"{watchlist_data}\n\n"
                        "Give a crisp end-of-day summary: what moved, why it matters, "
                        "and what to watch tomorrow. Use bullet points."
                    ),
                },
            ],
        )
        return resp.choices[0].message.content or "No summary."
    except Exception as e:
        log.error("OpenAI market summary error: %s", e)
        return "_AI market summary unavailable._"
