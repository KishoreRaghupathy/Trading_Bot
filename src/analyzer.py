"""
Technical analysis engine.
Computes RSI, MACD, Bollinger Bands, EMA, Support/Resistance,
Volume spike detection, and entry/exit signal generation.
"""
import logging
import pandas as pd
import pandas_ta as ta
import numpy as np
from dataclasses import dataclass, field
from src.kite_client import get_historical, get_quote
import src.config as config

log = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    symbol: str
    exchange: str
    interval: str
    ltp: float = 0.0
    change_pct: float = 0.0

    # Trend
    ema_20: float = 0.0
    ema_50: float = 0.0
    trend: str = "NEUTRAL"          # BULLISH / BEARISH / NEUTRAL

    # Momentum
    rsi: float = 0.0
    rsi_signal: str = ""            # OVERBOUGHT / OVERSOLD / NEUTRAL
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    macd_crossover: str = ""        # BULLISH / BEARISH / NONE

    # Volatility
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_mid: float = 0.0
    bb_position: str = ""           # ABOVE_UPPER / BELOW_LOWER / INSIDE

    # Volume
    volume: int = 0
    avg_volume: int = 0
    volume_spike: bool = False

    # Levels
    support: float = 0.0
    resistance: float = 0.0

    # Signal
    signal: str = "NEUTRAL"        # BUY / SELL / NEUTRAL
    signal_reasons: list[str] = field(default_factory=list)
    entry_zone: tuple[float, float] = (0.0, 0.0)
    sl: float = 0.0
    target1: float = 0.0
    target2: float = 0.0
    risk_reward: float = 0.0

    # Open Interest (MCX futures)
    oi: int = 0
    oi_change: int = 0


def analyse(symbol: str, exchange: str = "MCX",
            interval: str = "15m", days: int = 30) -> AnalysisResult | None:
    """Full technical analysis. Returns AnalysisResult or None on failure."""
    df = get_historical(symbol, exchange, interval, days)
    if df is None or len(df) < 50:
        log.warning("Insufficient data for %s (%s)", symbol, interval)
        return None

    result = AnalysisResult(symbol=symbol, exchange=exchange, interval=interval)

    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    vol   = df["volume"]

    # ── LTP + change ─────────────────────────────────────────
    result.ltp = float(close.iloc[-1])
    result.change_pct = float(
        (close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100
    )

    # ── EMA ─────────────────────────────────────────────────
    result.ema_20 = float(ta.ema(close, 20).iloc[-1])
    result.ema_50 = float(ta.ema(close, 50).iloc[-1])
    if result.ema_20 > result.ema_50:
        result.trend = "BULLISH"
    elif result.ema_20 < result.ema_50:
        result.trend = "BEARISH"

    # ── RSI ──────────────────────────────────────────────────
    result.rsi = round(float(ta.rsi(close, 14).iloc[-1]), 2)
    if result.rsi >= config.RSI_OVERBOUGHT:
        result.rsi_signal = "OVERBOUGHT"
    elif result.rsi <= config.RSI_OVERSOLD:
        result.rsi_signal = "OVERSOLD"
    else:
        result.rsi_signal = "NEUTRAL"

    # ── MACD ─────────────────────────────────────────────────
    macd_df = ta.macd(close)
    result.macd        = round(float(macd_df["MACD_12_26_9"].iloc[-1]), 4)
    result.macd_signal = round(float(macd_df["MACDs_12_26_9"].iloc[-1]), 4)
    result.macd_hist   = round(float(macd_df["MACDh_12_26_9"].iloc[-1]), 4)
    prev_hist = macd_df["MACDh_12_26_9"].iloc[-2]
    if prev_hist < 0 and result.macd_hist > 0:
        result.macd_crossover = "BULLISH"
    elif prev_hist > 0 and result.macd_hist < 0:
        result.macd_crossover = "BEARISH"
    else:
        result.macd_crossover = "NONE"

    # ── Bollinger Bands ───────────────────────────────────────
    bb = ta.bbands(close, length=20, std=2)
    result.bb_upper = round(float(bb["BBU_20_2.0"].iloc[-1]), 2)
    result.bb_lower = round(float(bb["BBL_20_2.0"].iloc[-1]), 2)
    result.bb_mid   = round(float(bb["BBM_20_2.0"].iloc[-1]), 2)
    if result.ltp > result.bb_upper:
        result.bb_position = "ABOVE_UPPER"
    elif result.ltp < result.bb_lower:
        result.bb_position = "BELOW_LOWER"
    else:
        result.bb_position = "INSIDE"

    # ── Volume ───────────────────────────────────────────────
    result.volume      = int(vol.iloc[-1])
    result.avg_volume  = int(vol.tail(20).mean())
    result.volume_spike = (
        result.volume >= result.avg_volume * config.VOLUME_SPIKE_MULTIPLIER
    )

    # ── Support / Resistance (pivot-based, last 20 candles) ──
    recent_high = float(high.tail(20).max())
    recent_low  = float(low.tail(20).min())
    pivot = (recent_high + recent_low + result.ltp) / 3
    result.support    = round(2 * pivot - recent_high, 2)
    result.resistance = round(2 * pivot - recent_low, 2)

    # ── OI from live quote (MCX only) ────────────────────────
    if exchange == "MCX":
        q = get_quote(symbol, exchange)
        if q:
            result.oi        = int(q.get("oi", 0))
            result.oi_change = int(q.get("oi_day_change", 0))

    # ── Signal generation ────────────────────────────────────
    bull_score = 0
    bear_score = 0
    reasons: list[str] = []

    if result.trend == "BULLISH":
        bull_score += 2
        reasons.append("EMA20 > EMA50 (bullish trend)")
    elif result.trend == "BEARISH":
        bear_score += 2
        reasons.append("EMA20 < EMA50 (bearish trend)")

    if result.rsi_signal == "OVERSOLD":
        bull_score += 2
        reasons.append(f"RSI oversold ({result.rsi})")
    elif result.rsi_signal == "OVERBOUGHT":
        bear_score += 2
        reasons.append(f"RSI overbought ({result.rsi})")

    if result.macd_crossover == "BULLISH":
        bull_score += 3
        reasons.append("MACD bullish crossover")
    elif result.macd_crossover == "BEARISH":
        bear_score += 3
        reasons.append("MACD bearish crossover")

    if result.bb_position == "BELOW_LOWER":
        bull_score += 1
        reasons.append("Price at/below lower Bollinger Band")
    elif result.bb_position == "ABOVE_UPPER":
        bear_score += 1
        reasons.append("Price at/above upper Bollinger Band")

    if result.volume_spike:
        dominant = "BUY" if bull_score > bear_score else "SELL"
        reasons.append(f"Volume spike (confirming {dominant} pressure)")

    result.signal_reasons = reasons

    if bull_score >= 4 and bull_score > bear_score:
        result.signal = "BUY"
        result.entry_zone = (
            round(result.support + (result.ltp - result.support) * 0.1, 2),
            round(result.ltp, 2)
        )
        result.sl      = round(result.support * 0.995, 2)
        result.target1 = round(result.resistance, 2)
        result.target2 = round(result.resistance + (result.resistance - result.sl) * 0.5, 2)
    elif bear_score >= 4 and bear_score > bull_score:
        result.signal = "SELL"
        result.entry_zone = (
            round(result.ltp, 2),
            round(result.resistance - (result.resistance - result.ltp) * 0.1, 2)
        )
        result.sl      = round(result.resistance * 1.005, 2)
        result.target1 = round(result.support, 2)
        result.target2 = round(result.support - (result.sl - result.support) * 0.5, 2)
    else:
        result.signal = "NEUTRAL"

    if result.signal != "NEUTRAL" and result.sl:
        risk   = abs(result.ltp - result.sl)
        reward = abs(result.target1 - result.ltp)
        result.risk_reward = round(reward / risk, 2) if risk > 0 else 0

    return result


def format_analysis(r: AnalysisResult) -> str:
    """Format AnalysisResult as a Telegram-friendly message."""
    trend_emoji = "🟢" if r.trend == "BULLISH" else "🔴" if r.trend == "BEARISH" else "⚪"
    sig_emoji   = "📈" if r.signal == "BUY" else "📉" if r.signal == "SELL" else "↔️"
    vol_tag     = " 🔥 SPIKE" if r.volume_spike else ""
    chg_tag     = f"+{r.change_pct:.2f}%" if r.change_pct >= 0 else f"{r.change_pct:.2f}%"

    lines = [
        f"*{r.symbol}* ({r.exchange}) | _{r.interval}_",
        f"LTP: `₹{r.ltp:,.2f}` {chg_tag}",
        "",
        f"{trend_emoji} *Trend:* {r.trend}",
        f"EMA20: `{r.ema_20:.2f}` | EMA50: `{r.ema_50:.2f}`",
        "",
        f"*RSI(14):* `{r.rsi}` — _{r.rsi_signal}_",
        f"*MACD:* `{r.macd}` | Hist: `{r.macd_hist}` | _{r.macd_crossover} crossover_",
        f"*BB:* `{r.bb_lower:.2f} — {r.bb_upper:.2f}` | _{r.bb_position}_",
        "",
        f"*Volume:* `{r.volume:,}` (avg `{r.avg_volume:,}`){vol_tag}",
        f"*Support:* `{r.support}` | *Resistance:* `{r.resistance}`",
    ]

    if r.exchange == "MCX" and r.oi:
        oi_chg = f"+{r.oi_change:,}" if r.oi_change >= 0 else f"{r.oi_change:,}"
        lines.append(f"*OI:* `{r.oi:,}` (change: {oi_chg})")

    lines += ["", f"{sig_emoji} *Signal: {r.signal}*"]

    if r.signal != "NEUTRAL":
        lines += [
            f"  Entry zone: `{r.entry_zone[0]} – {r.entry_zone[1]}`",
            f"  Stop-loss:  `{r.sl}`",
            f"  Target 1:   `{r.target1}`",
            f"  Target 2:   `{r.target2}`",
            f"  R:R ratio:  `{r.risk_reward}`",
        ]

    if r.signal_reasons:
        lines += ["", "*Reasons:*"]
        for reason in r.signal_reasons:
            lines.append(f"  • {reason}")

    return "\n".join(lines)
