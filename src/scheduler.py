"""
APScheduler jobs:
 - Every minute: check price alerts + reminders
 - Thursday 17:30 IST: EIA storage report reminder
 - Monday–Friday 15:35 IST: end-of-day market summary
 - Every 5 min: check open trade SL proximity
"""
import logging
import asyncio
from datetime import datetime
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot
import src.db as db
import alerts as alert_mgr
from src.kite_client import get_ltp
import src.openai_client as openai_client
import src.config as config

log = logging.getLogger(__name__)
IST = pytz.timezone(config.TIMEZONE)


def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=IST)

    # ── Every minute: price alerts + reminders ───────────────
    scheduler.add_job(
        _run_alert_check, "interval", minutes=1,
        id="price_alerts", args=[bot]
    )

    # ── Thursday 17:30 IST: EIA natural gas storage report ───
    scheduler.add_job(
        _eia_reminder, CronTrigger(
            day_of_week="thu", hour=17, minute=30, timezone=IST
        ),
        id="eia_reminder", args=[bot]
    )

    # ── Mon–Fri 15:35 IST: end-of-day summary ────────────────
    scheduler.add_job(
        _eod_summary, CronTrigger(
            day_of_week="mon-fri", hour=15, minute=35, timezone=IST
        ),
        id="eod_summary", args=[bot]
    )

    # ── Every 5 min: SL proximity watch on open trades ───────
    scheduler.add_job(
        _sl_watch, "interval", minutes=5,
        id="sl_watch", args=[bot]
    )

    # ── MCX close: 23:30 IST Mon–Fri ─────────────────────────
    scheduler.add_job(
        _mcx_close_alert, CronTrigger(
            day_of_week="mon-fri", hour=23, minute=30, timezone=IST
        ),
        id="mcx_close", args=[bot]
    )

    return scheduler


async def _run_alert_check(bot: Bot) -> None:
    try:
        await alert_mgr.check_price_alerts(bot)
        await alert_mgr.check_reminders(bot)
    except Exception as e:
        log.error("Alert check error: %s", e)


async def _eia_reminder(bot: Bot) -> None:
    """Send EIA natural gas storage report reminder to all users."""
    users = _all_user_ids()
    msg = (
        "📊 *EIA Natural Gas Storage Report*\n"
        "Released in ~30 minutes (10:30 AM ET / 8:00 PM IST).\n\n"
        "Current MCX NATGASMINI price:\n"
        "_Fetching…_\n\n"
        "⚡ Expect sharp moves in NATGASMINI April futures.\n"
        "• Injection > expectation → bearish\n"
        "• Withdrawal > expectation → bullish\n\n"
        "_Use /analyze NATGASMINI MCX 5m after the report for a live read._"
    )
    for uid in users:
        try:
            await bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
        except Exception as e:
            log.error("EIA reminder send failed for %s: %s", uid, e)


async def _eod_summary(bot: Bot) -> None:
    """End-of-day AI summary for each user's watchlist."""
    all_users = _all_user_ids()
    for uid in all_users:
        watchlist = db.get_watchlist(uid)
        if not watchlist:
            continue
        snapshot_lines = []
        for item in watchlist:
            ltp = get_ltp(item["symbol"], item["exchange"])
            if ltp:
                snapshot_lines.append(
                    f"{item['symbol']} ({item['exchange']}): ₹{ltp:,.2f}"
                )
        if not snapshot_lines:
            continue
        snapshot_text = "\n".join(snapshot_lines)
        summary = await openai_client.get_market_summary(snapshot_text)
        try:
            await bot.send_message(
                chat_id=uid,
                text=f"🌅 *End-of-Day Summary*\n\n{summary}",
                parse_mode="Markdown",
            )
        except Exception as e:
            log.error("EOD summary send failed for %s: %s", uid, e)


async def _sl_watch(bot: Bot) -> None:
    """Check if any open trade is near its stop-loss."""
    all_users = _all_user_ids()
    for uid in all_users:
        open_trades = db.get_open_trades(uid)
        for trade in open_trades:
            if not trade["sl"]:
                continue
            ltp = get_ltp(trade["symbol"], "MCX")
            if ltp is None:
                continue
            await alert_mgr.send_sl_warning(
                bot, uid, trade["symbol"], ltp, trade["sl"], trade["id"]
            )


async def _mcx_close_alert(bot: Bot) -> None:
    """Remind users that MCX session closes soon."""
    users = _all_user_ids()
    msg = (
        "🔔 *MCX Session Closing Soon* (23:30 IST)\n"
        "Square off or carry positions consciously.\n"
        "_Use /pnl to check today's P&L._"
    )
    for uid in users:
        try:
            await bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
        except Exception as e:
            log.error("MCX close alert failed for %s: %s", uid, e)


def _all_user_ids() -> list[int]:
    """Get distinct user IDs from the watchlist table as a proxy for active users."""
    import sqlite3
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM watchlist"
        ).fetchall()
    ids = [r["user_id"] for r in rows]
    # Also include ALLOWED_USERS as fallback
    for uid in config.ALLOWED_USERS:
        if uid not in ids:
            ids.append(uid)
    return ids
