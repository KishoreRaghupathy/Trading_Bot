"""
Alert manager.
Runs price alert checks against live quotes and sends Telegram notifications.
"""
import logging
import asyncio
from telegram import Bot
import src.db as db
from src.kite_client import get_ltp

log = logging.getLogger(__name__)


async def check_price_alerts(bot: Bot) -> None:
    """Called by scheduler every minute — checks all active price alerts."""
    alerts = db.get_active_alerts()
    if not alerts:
        return

    # Group by symbol to minimise API calls
    symbol_map: dict[str, list] = {}
    for alert in alerts:
        key = f"{alert['exchange']}:{alert['symbol']}"
        symbol_map.setdefault(key, []).append(alert)

    for key, group in symbol_map.items():
        exchange, symbol = key.split(":", 1)
        ltp = get_ltp(symbol, exchange)
        if ltp is None:
            continue

        for alert in group:
            triggered = (
                (alert["condition"] == "above" and ltp >= alert["price"]) or
                (alert["condition"] == "below" and ltp <= alert["price"])
            )
            if triggered:
                db.deactivate_alert(alert["id"])
                emoji = "🚀" if alert["condition"] == "above" else "🔻"
                msg = (
                    f"{emoji} *Price Alert Triggered!*\n"
                    f"*{symbol}* ({exchange}) LTP: `₹{ltp:,.2f}`\n"
                    f"Condition: price {alert['condition']} `₹{alert['price']:,.2f}` ✅"
                )
                try:
                    await bot.send_message(
                        chat_id=alert["user_id"],
                        text=msg,
                        parse_mode="Markdown",
                    )
                    log.info("Alert fired: %s %s %s %s", symbol, alert["condition"],
                             alert["price"], alert["user_id"])
                except Exception as e:
                    log.error("Failed to send alert: %s", e)
                await asyncio.sleep(0.1)   # Telegram rate limit


async def check_reminders(bot: Bot) -> None:
    """Send any due reminders."""
    due = db.get_due_reminders()
    for r in due:
        try:
            await bot.send_message(
                chat_id=r["user_id"],
                text=f"⏰ *Reminder*\n{r['message']}",
                parse_mode="Markdown",
            )
            db.mark_reminder_done(r["id"])
        except Exception as e:
            log.error("Reminder send failed: %s", e)


async def send_volume_warning(bot: Bot, user_id: int,
                              symbol: str, volume: int, avg_volume: int) -> None:
    """Send a standalone volume spike warning."""
    ratio = volume / avg_volume if avg_volume else 0
    await bot.send_message(
        chat_id=user_id,
        text=(
            f"🔥 *Volume Spike Alert!*\n"
            f"*{symbol}* current volume `{volume:,}` "
            f"is *{ratio:.1f}x* the 20-period average (`{avg_volume:,}`).\n"
            f"_Unusual activity detected — check the chart!_"
        ),
        parse_mode="Markdown",
    )


async def send_sl_warning(bot: Bot, user_id: int, symbol: str,
                          ltp: float, sl: float, trade_id: int) -> None:
    """Warn when LTP is within 0.5% of stop-loss."""
    dist = abs(ltp - sl) / sl * 100
    if dist <= 0.5:
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"⚠️ *Stop-Loss Warning* (Trade #{trade_id})\n"
                f"*{symbol}* LTP `₹{ltp:,.2f}` is only "
                f"`{dist:.2f}%` away from SL `₹{sl:,.2f}`!\n"
                f"_Consider reviewing your position._"
            ),
            parse_mode="Markdown",
        )
