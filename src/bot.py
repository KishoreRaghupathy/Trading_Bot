"""
Trading Analysis Bot — Main Entry Point
Commands:
  /start          Welcome + help
  /analyze        Full technical analysis
  /entry          Entry signal
  /exit           Exit signal
  /alert          Add/list/remove price alerts
  /volume         Volume analysis
  /pnl            P&L tracker
  /watchlist      Manage watchlist
  /summary        AI market summary
  /risk           Risk calculator
  /remind         Set a reminder
  /login          Kite login URL
  /settoken       Update Kite access token
"""
import logging
import asyncio
import os
from datetime import datetime, timedelta

import pytz
from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters
)
from telegram.constants import ParseMode

import src.config as config
import src.db as db
import analyzer
import src.openai_client as openai_client
import src.kite_client as kite_client
from alerts import send_volume_warning
from src.scheduler import build_scheduler

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger(__name__)
IST = pytz.timezone(config.TIMEZONE)


# ── Auth guard ────────────────────────────────────────────────

def auth(func):
    """Decorator to restrict bot to allowed Telegram users."""
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if config.ALLOWED_USERS and uid not in config.ALLOWED_USERS:
            await update.message.reply_text("🚫 Unauthorised.")
            return
        return await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper


def _parse_args(text: str, n: int) -> list[str] | None:
    """Split command text into n parts (case-insensitive), return None if invalid."""
    parts = text.strip().split()
    if len(parts) < n:
        return None
    return [p.upper() for p in parts[:n]]


# ── /start ────────────────────────────────────────────────────

@auth
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Hey *{name}*! I'm your Trading Analysis Bot.\n\n"
        "Here's what I can do:\n\n"
        "📊 `/analyze SYMBOL EXCHANGE INTERVAL` — full TA\n"
        "   _e.g._ `/analyze NATGASMINI MCX 15m`\n\n"
        "🎯 `/entry SYMBOL EXCHANGE` — entry signal\n"
        "🚪 `/exit SYMBOL EXCHANGE` — exit signal\n"
        "🔔 `/alert add SYMBOL EXCHANGE above/below PRICE`\n"
        "📋 `/alert list` — your active alerts\n"
        "📦 `/volume SYMBOL EXCHANGE` — volume spike check\n"
        "💰 `/pnl open SYMBOL BUY/SELL QTY ENTRY SL TARGET`\n"
        "💰 `/pnl close TRADE_ID EXIT_PRICE`\n"
        "💰 `/pnl summary` — your P&L dashboard\n"
        "👁️ `/watchlist add SYMBOL EXCHANGE`\n"
        "👁️ `/watchlist show` — view watchlist\n"
        "🧠 `/summary` — AI market digest\n"
        "⚖️ `/risk SYMBOL SIDE ENTRY SL TARGET QTY`\n"
        "⏰ `/remind MESSAGE in Xm/Xh` — set reminder\n"
        "🔑 `/login` — get Kite login URL\n"
        "🔑 `/settoken TOKEN` — update access token\n",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /analyze ──────────────────────────────────────────────────

@auth
async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args or len(args) < 1:
        await update.message.reply_text(
            "Usage: `/analyze SYMBOL EXCHANGE INTERVAL`\n"
            "e.g. `/analyze NATGASMINI MCX 15m`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    symbol   = args[0].upper()
    exchange = args[1].upper() if len(args) > 1 else "MCX"
    interval = args[2].lower() if len(args) > 2 else "15m"

    msg = await update.message.reply_text(f"⏳ Analysing *{symbol}*…", parse_mode=ParseMode.MARKDOWN)

    result = await asyncio.to_thread(analyzer.analyse, symbol, exchange, interval)
    if result is None:
        await msg.edit_text("❌ Could not fetch data. Check symbol/exchange.")
        return

    text = analyzer.format_analysis(result)

    # Optionally append AI summary
    ai_summary = await openai_client.get_ai_summary(text, symbol)
    full_text = text + f"\n\n🧠 *AI Insight:*\n{ai_summary}"

    await msg.edit_text(full_text, parse_mode=ParseMode.MARKDOWN)

    # Warn on volume spike
    if result.volume_spike:
        await send_volume_warning(
            ctx.bot, update.effective_user.id,
            symbol, result.volume, result.avg_volume
        )


# ── /entry ────────────────────────────────────────────────────

@auth
async def cmd_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: `/entry SYMBOL EXCHANGE`", parse_mode=ParseMode.MARKDOWN)
        return
    symbol   = args[0].upper()
    exchange = args[1].upper() if len(args) > 1 else "MCX"

    msg = await update.message.reply_text(f"⏳ Finding entry for *{symbol}*…", parse_mode=ParseMode.MARKDOWN)
    result = await asyncio.to_thread(analyzer.analyse, symbol, exchange, "15m")
    if result is None:
        await msg.edit_text("❌ Data unavailable.")
        return

    if result.signal == "BUY":
        text = (
            f"📈 *Entry Signal: BUY {symbol}*\n\n"
            f"🟢 Confirmation: {', '.join(result.signal_reasons[:3])}\n\n"
            f"Entry zone: `{result.entry_zone[0]} – {result.entry_zone[1]}`\n"
            f"Stop-loss:  `{result.sl}`\n"
            f"Target 1:   `{result.target1}`\n"
            f"Target 2:   `{result.target2}`\n"
            f"R:R:        `{result.risk_reward}`"
        )
    elif result.signal == "SELL":
        text = (
            f"📉 *Entry Signal: SELL {symbol}*\n\n"
            f"🔴 Confirmation: {', '.join(result.signal_reasons[:3])}\n\n"
            f"Entry zone: `{result.entry_zone[0]} – {result.entry_zone[1]}`\n"
            f"Stop-loss:  `{result.sl}`\n"
            f"Target 1:   `{result.target1}`\n"
            f"Target 2:   `{result.target2}`\n"
            f"R:R:        `{result.risk_reward}`"
        )
    else:
        text = (
            f"↔️ *No clear entry for {symbol}*\n"
            f"Signal is NEUTRAL — conflicting indicators.\n"
            f"RSI: `{result.rsi}` | Trend: `{result.trend}`\n"
            f"_Wait for confluence before entering._"
        )
    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)


# ── /exit ─────────────────────────────────────────────────────

@auth
async def cmd_exit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: `/exit SYMBOL EXCHANGE`", parse_mode=ParseMode.MARKDOWN)
        return
    symbol   = args[0].upper()
    exchange = args[1].upper() if len(args) > 1 else "MCX"

    msg = await update.message.reply_text(f"⏳ Checking exit signals for *{symbol}*…", parse_mode=ParseMode.MARKDOWN)
    result = await asyncio.to_thread(analyzer.analyse, symbol, exchange, "15m")
    if result is None:
        await msg.edit_text("❌ Data unavailable.")
        return

    # Exit if opposing signal or RSI extreme
    should_exit = False
    exit_reasons = []

    if result.macd_crossover in ("BULLISH", "BEARISH"):
        should_exit = True
        exit_reasons.append(f"MACD {result.macd_crossover} crossover")
    if result.rsi_signal == "OVERBOUGHT":
        should_exit = True
        exit_reasons.append("RSI overbought — momentum fading")
    if result.rsi_signal == "OVERSOLD":
        should_exit = True
        exit_reasons.append("RSI oversold — bounce risk")
    if result.bb_position in ("ABOVE_UPPER", "BELOW_LOWER"):
        should_exit = True
        exit_reasons.append(f"Price at Bollinger extreme ({result.bb_position})")

    if should_exit:
        text = (
            f"🚪 *Exit Signal: {symbol}*\n\n"
            f"LTP: `₹{result.ltp:,.2f}`\n"
            f"Reasons to exit:\n"
            + "\n".join(f"  • {r}" for r in exit_reasons)
            + f"\n\nNearby support: `{result.support}` | Resistance: `{result.resistance}`"
        )
    else:
        text = (
            f"✅ *No exit signal yet for {symbol}*\n"
            f"LTP: `₹{result.ltp:,.2f}` | RSI: `{result.rsi}`\n"
            f"_Hold and monitor. Next resistance: `{result.resistance}`_"
        )
    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)


# ── /alert ────────────────────────────────────────────────────

@auth
async def cmd_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    uid = update.effective_user.id
    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "`/alert add SYMBOL EXCHANGE above/below PRICE`\n"
            "`/alert list`\n"
            "`/alert remove ALERT_ID`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    sub = args[0].lower()

    if sub == "add":
        if len(args) < 5:
            await update.message.reply_text(
                "Usage: `/alert add SYMBOL EXCHANGE above/below PRICE`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        symbol   = args[1].upper()
        exchange = args[2].upper()
        cond     = args[3].lower()
        try:
            price = float(args[4])
        except ValueError:
            await update.message.reply_text("❌ Invalid price.")
            return
        if cond not in ("above", "below"):
            await update.message.reply_text("Condition must be `above` or `below`.", parse_mode=ParseMode.MARKDOWN)
            return
        aid = db.add_alert(uid, symbol, exchange, cond, price)
        await update.message.reply_text(
            f"✅ Alert #{aid} set!\n"
            f"*{symbol}* ({exchange}) {cond} `₹{price:,.2f}`",
            parse_mode=ParseMode.MARKDOWN
        )

    elif sub == "list":
        rows = db.get_active_alerts(uid)
        if not rows:
            await update.message.reply_text("No active alerts.")
            return
        lines = ["*Your active alerts:*\n"]
        for r in rows:
            lines.append(
                f"#{r['id']} — *{r['symbol']}* ({r['exchange']}) "
                f"{r['condition']} `₹{r['price']:,.2f}`"
            )
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    elif sub == "remove":
        if len(args) < 2:
            await update.message.reply_text("Usage: `/alert remove ALERT_ID`", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            aid = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid alert ID.")
            return
        db.deactivate_alert(aid)
        await update.message.reply_text(f"🗑️ Alert #{aid} removed.")

    else:
        await update.message.reply_text("Unknown subcommand. Use `add`, `list`, or `remove`.", parse_mode=ParseMode.MARKDOWN)


# ── /volume ───────────────────────────────────────────────────

@auth
async def cmd_volume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: `/volume SYMBOL EXCHANGE`", parse_mode=ParseMode.MARKDOWN)
        return
    symbol   = args[0].upper()
    exchange = args[1].upper() if len(args) > 1 else "MCX"

    msg = await update.message.reply_text(f"⏳ Checking volume for *{symbol}*…", parse_mode=ParseMode.MARKDOWN)
    result = await asyncio.to_thread(analyzer.analyse, symbol, exchange, "15m")
    if result is None:
        await msg.edit_text("❌ Data unavailable.")
        return

    ratio = result.volume / result.avg_volume if result.avg_volume else 0
    emoji = "🔥" if result.volume_spike else "📊"
    text = (
        f"{emoji} *Volume Analysis: {symbol}*\n\n"
        f"Current volume: `{result.volume:,}`\n"
        f"20-period avg:  `{result.avg_volume:,}`\n"
        f"Ratio:          `{ratio:.2f}x`\n\n"
    )
    if result.volume_spike:
        text += f"⚠️ *Volume spike detected!* ({config.VOLUME_SPIKE_MULTIPLIER}x threshold)\n_Could signal a breakout or reversal._"
    else:
        text += "_Volume is within normal range._"
    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)


# ── /pnl ─────────────────────────────────────────────────────

@auth
async def cmd_pnl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    uid = update.effective_user.id
    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "`/pnl open SYMBOL BUY/SELL QTY ENTRY SL TARGET`\n"
            "`/pnl close TRADE_ID EXIT_PRICE`\n"
            "`/pnl summary`\n"
            "`/pnl trades` — open positions",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    sub = args[0].lower()

    if sub == "open":
        try:
            symbol, side, qty, entry = args[1].upper(), args[2].upper(), float(args[3]), float(args[4])
            sl     = float(args[5]) if len(args) > 5 else None
            target = float(args[6]) if len(args) > 6 else None
        except (IndexError, ValueError):
            await update.message.reply_text("Usage: `/pnl open SYMBOL BUY/SELL QTY ENTRY SL TARGET`", parse_mode=ParseMode.MARKDOWN)
            return
        tid = db.open_trade(uid, symbol, side, qty, entry, sl, target)
        await update.message.reply_text(
            f"✅ Trade #{tid} logged!\n"
            f"*{side} {symbol}* — `{qty}` lots @ `₹{entry:,.2f}`\n"
            f"SL: `{sl}` | Target: `{target}`",
            parse_mode=ParseMode.MARKDOWN
        )

    elif sub == "close":
        try:
            tid   = int(args[1])
            exit_ = float(args[2])
        except (IndexError, ValueError):
            await update.message.reply_text("Usage: `/pnl close TRADE_ID EXIT_PRICE`", parse_mode=ParseMode.MARKDOWN)
            return
        pnl = db.close_trade(tid, exit_)
        emoji = "🟢" if pnl >= 0 else "🔴"
        await update.message.reply_text(
            f"{emoji} Trade #{tid} closed.\nP&L: `₹{pnl:,.2f}`",
            parse_mode=ParseMode.MARKDOWN
        )

    elif sub == "summary":
        s = db.get_pnl_summary(uid)
        wr = (s["winners"] / s["total_trades"] * 100) if s["total_trades"] else 0
        emoji = "🟢" if s["total_pnl"] >= 0 else "🔴"
        text = (
            f"💰 *P&L Summary*\n\n"
            f"Total closed trades: `{s['total_trades']}`\n"
            f"Win rate: `{wr:.1f}%` ({s['winners']}W / {s['losers']}L)\n\n"
            f"{emoji} *Total P&L: ₹{s['total_pnl']:,.2f}*\n"
            f"Best trade: `₹{s['best']:,.2f}`\n"
            f"Worst trade: `₹{s['worst']:,.2f}`"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    elif sub == "trades":
        trades = db.get_open_trades(uid)
        if not trades:
            await update.message.reply_text("No open positions.")
            return
        lines = ["*Open Positions:*\n"]
        for t in trades:
            lines.append(
                f"#{t['id']} {t['side']} *{t['symbol']}* "
                f"qty `{t['qty']}` @ `₹{t['entry']:,.2f}` | SL `{t['sl']}`"
            )
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ── /watchlist ────────────────────────────────────────────────

@auth
async def cmd_watchlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    uid = update.effective_user.id
    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "`/watchlist add SYMBOL EXCHANGE`\n"
            "`/watchlist show`\n"
            "`/watchlist remove SYMBOL`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    sub = args[0].lower()
    if sub == "add":
        symbol   = args[1].upper() if len(args) > 1 else None
        exchange = args[2].upper() if len(args) > 2 else "MCX"
        if not symbol:
            await update.message.reply_text("Provide a symbol.")
            return
        db.add_to_watchlist(uid, symbol, exchange)
        await update.message.reply_text(f"✅ *{symbol}* ({exchange}) added to watchlist.", parse_mode=ParseMode.MARKDOWN)

    elif sub == "show":
        wl = db.get_watchlist(uid)
        if not wl:
            await update.message.reply_text("Your watchlist is empty. Use `/watchlist add`.", parse_mode=ParseMode.MARKDOWN)
            return
        lines = ["*Your Watchlist:*\n"]
        for item in wl:
            ltp = kite_client.get_ltp(item["symbol"], item["exchange"])
            price_str = f"₹{ltp:,.2f}" if ltp else "—"
            lines.append(f"• *{item['symbol']}* ({item['exchange']}) — {price_str}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    elif sub == "remove":
        symbol = args[1].upper() if len(args) > 1 else None
        if not symbol:
            await update.message.reply_text("Provide a symbol to remove.")
            return
        db.remove_from_watchlist(uid, symbol)
        await update.message.reply_text(f"🗑️ *{symbol}* removed from watchlist.", parse_mode=ParseMode.MARKDOWN)


# ── /summary ─────────────────────────────────────────────────

@auth
async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    wl = db.get_watchlist(uid)
    msg = await update.message.reply_text("🧠 Generating AI market summary…")
    if not wl:
        await msg.edit_text("Your watchlist is empty. Add symbols with `/watchlist add`.", parse_mode=ParseMode.MARKDOWN)
        return
    snapshot_lines = []
    for item in wl:
        ltp = kite_client.get_ltp(item["symbol"], item["exchange"])
        if ltp:
            snapshot_lines.append(f"{item['symbol']} ({item['exchange']}): ₹{ltp:,.2f}")
    if not snapshot_lines:
        await msg.edit_text("Could not fetch prices. Try again.")
        return
    summary = await openai_client.get_market_summary("\n".join(snapshot_lines))
    await msg.edit_text(f"🧠 *AI Market Summary*\n\n{summary}", parse_mode=ParseMode.MARKDOWN)


# ── /risk ─────────────────────────────────────────────────────

@auth
async def cmd_risk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if len(args) < 6:
        await update.message.reply_text(
            "Usage: `/risk SYMBOL SIDE ENTRY SL TARGET QTY`\n"
            "e.g. `/risk NATGASMINI BUY 220 215 235 10`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    try:
        symbol = args[0].upper()
        side   = args[1].upper()
        entry, sl, target, qty = float(args[2]), float(args[3]), float(args[4]), float(args[5])
    except ValueError:
        await update.message.reply_text("❌ Invalid values.")
        return

    risk_per_unit   = abs(entry - sl)
    reward_per_unit = abs(target - entry)
    rr              = reward_per_unit / risk_per_unit if risk_per_unit else 0
    total_risk      = risk_per_unit * qty
    total_reward    = reward_per_unit * qty

    msg = await update.message.reply_text("⚖️ Calculating…")
    ai_advice = await openai_client.get_risk_advice(symbol, side, entry, sl, target, qty)

    text = (
        f"⚖️ *Risk Calculator: {symbol} {side}*\n\n"
        f"Entry:  `₹{entry:,.2f}`\n"
        f"SL:     `₹{sl:,.2f}` (risk/unit: `₹{risk_per_unit:,.2f}`)\n"
        f"Target: `₹{target:,.2f}` (reward/unit: `₹{reward_per_unit:,.2f}`)\n"
        f"Qty:    `{qty}`\n\n"
        f"📊 *Risk:Reward = {rr:.2f}*\n"
        f"Max loss:   `₹{total_risk:,.2f}`\n"
        f"Max profit: `₹{total_reward:,.2f}`\n\n"
        f"🧠 *AI Assessment:*\n{ai_advice}"
    )
    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)


# ── /remind ───────────────────────────────────────────────────

@auth
async def cmd_remind(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Format: /remind Check EIA report in 30m
    text = " ".join(ctx.args)
    if " in " not in text:
        await update.message.reply_text(
            "Usage: `/remind MESSAGE in Xm` or `/remind MESSAGE in Xh`\n"
            "e.g. `/remind Check EIA report in 30m`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    parts = text.rsplit(" in ", 1)
    reminder_msg = parts[0].strip()
    time_str = parts[1].strip().lower()
    try:
        if time_str.endswith("m"):
            delta = timedelta(minutes=int(time_str[:-1]))
        elif time_str.endswith("h"):
            delta = timedelta(hours=int(time_str[:-1]))
        else:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Time format: `30m` or `2h`", parse_mode=ParseMode.MARKDOWN)
        return

    remind_at = datetime.now(IST).replace(tzinfo=None) + delta
    rid = db.add_reminder(update.effective_user.id, reminder_msg, remind_at)
    await update.message.reply_text(
        f"⏰ Reminder #{rid} set!\n"
        f"_{reminder_msg}_\n"
        f"At `{remind_at.strftime('%H:%M')}` IST",
        parse_mode=ParseMode.MARKDOWN
    )


# ── /login ────────────────────────────────────────────────────

@auth
async def cmd_login(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    url = kite_client.generate_login_url()
    await update.message.reply_text(
        f"🔑 *Kite Login*\n\n"
        f"Click the link to authenticate:\n{url}\n\n"
        f"After login, copy the `request_token` from the redirect URL and send:\n"
        f"`/settoken YOUR_REQUEST_TOKEN`",
        parse_mode=ParseMode.MARKDOWN
    )


@auth
async def cmd_settoken(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/settoken YOUR_REQUEST_TOKEN`", parse_mode=ParseMode.MARKDOWN)
        return
    request_token = ctx.args[0].strip()
    try:
        access_token = kite_client.complete_login(request_token)
        await update.message.reply_text(
            f"✅ Kite access token updated!\n`{access_token[:12]}…`\n_Valid until market close._",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Login failed: `{e}`", parse_mode=ParseMode.MARKDOWN)


# ── Unknown command ───────────────────────────────────────────

async def cmd_unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Unknown command. Use /start to see all commands."
    )


# ── Main ─────────────────────────────────────────────────────

def main():
    db.init_db()
    log.info("Database ready")

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Register commands
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("analyze",   cmd_analyze))
    app.add_handler(CommandHandler("entry",     cmd_entry))
    app.add_handler(CommandHandler("exit",      cmd_exit))
    app.add_handler(CommandHandler("alert",     cmd_alert))
    app.add_handler(CommandHandler("volume",    cmd_volume))
    app.add_handler(CommandHandler("pnl",       cmd_pnl))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("summary",   cmd_summary))
    app.add_handler(CommandHandler("risk",      cmd_risk))
    app.add_handler(CommandHandler("remind",    cmd_remind))
    app.add_handler(CommandHandler("login",     cmd_login))
    app.add_handler(CommandHandler("settoken",  cmd_settoken))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    # Build and start scheduler
    scheduler = build_scheduler(app.bot)
    scheduler.start()
    log.info("Scheduler started")

    # Set bot command menu
    async def post_init(application):
        await application.bot.set_my_commands([
            BotCommand("start",     "Welcome + help"),
            BotCommand("analyze",   "Full technical analysis"),
            BotCommand("entry",     "Entry signal"),
            BotCommand("exit",      "Exit signal"),
            BotCommand("alert",     "Manage price alerts"),
            BotCommand("volume",    "Volume spike check"),
            BotCommand("pnl",       "P&L tracker"),
            BotCommand("watchlist", "Manage watchlist"),
            BotCommand("summary",   "AI market digest"),
            BotCommand("risk",      "Risk calculator"),
            BotCommand("remind",    "Set a reminder"),
            BotCommand("login",     "Kite login"),
        ])
    app.post_init = post_init

    log.info("Bot polling started…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
