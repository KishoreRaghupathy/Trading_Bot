# Trading Analysis Bot 🤖📊

A Telegram bot powered by Python, Zerodha Kite API, and OpenAI GPT for real-time
technical analysis across MCX, NSE, and crypto markets.

---

## Features

| Command | Description |
|---|---|
| `/analyze SYMBOL EXCHANGE INTERVAL` | Full TA (RSI, MACD, BB, EMA, S/R) + AI insight |
| `/entry SYMBOL EXCHANGE` | Entry zone, SL, targets, R:R |
| `/exit SYMBOL EXCHANGE` | Exit signal with reason |
| `/alert add/list/remove` | Price alerts |
| `/volume SYMBOL EXCHANGE` | Volume spike detection |
| `/pnl open/close/summary/trades` | P&L tracker |
| `/watchlist add/show/remove` | Symbol watchlist |
| `/summary` | AI end-of-day market digest |
| `/risk SYMBOL SIDE ENTRY SL TARGET QTY` | Risk calculator |
| `/remind MESSAGE in Xm/Xh` | Set a reminder |
| `/login` + `/settoken` | Zerodha Kite auth |

### Automated Alerts (no command needed)
- 🕠 **Thursday 17:30 IST** — EIA Natural Gas Storage Report reminder
- 🌅 **Mon–Fri 15:35 IST** — AI end-of-day summary for your watchlist
- ⚠️ **Every 5 min** — Stop-loss proximity warning on open trades
- 🔔 **Every minute** — Price alert checks
- 🔔 **23:30 IST Mon–Fri** — MCX session close reminder

---

## Project Structure

```
trading_bot/
├── src/
│   ├── bot.py           ← Main Telegram bot + all command handlers
│   ├── analyzer.py      ← RSI, MACD, BB, EMA, signal generation
│   ├── alerts.py        ← Price alert + SL warning logic
│   ├── scheduler.py     ← APScheduler cron jobs
│   ├── kite_client.py   ← Zerodha Kite API wrapper
│   ├── openai_client.py ← GPT-4o analysis summaries
│   ├── db.py            ← SQLite persistence (alerts, trades, watchlist)
│   └── config.py        ← Centralised env var loading
├── data/                ← SQLite DB (auto-created)
├── .vscode/
│   ├── launch.json
│   └── settings.json
├── .env                 ← Your secrets (never commit this)
├── .env.example         ← Template
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Setup

### 1. Prerequisites
- Python 3.12+
- Docker + Docker Compose
- VS Code with Python extension

### 2. Telegram Bot
1. Message [@BotFather](https://t.me/BotFather) → `/newbot`
2. Copy the token → `TELEGRAM_BOT_TOKEN` in `.env`
3. Get your Telegram user ID from [@userinfobot](https://t.me/userinfobot) → `TELEGRAM_ALLOWED_USERS`

### 3. Zerodha Kite API
1. Go to [kite.trade](https://kite.trade) → Create app
2. Set redirect URL to `https://127.0.0.1`
3. Copy API key + secret → `.env`
4. Run the bot → `/login` in Telegram → complete auth → `/settoken TOKEN`

### 4. OpenAI
1. Get API key from [platform.openai.com](https://platform.openai.com)
2. Add to `.env` → `OPENAI_API_KEY`

### 5. Configure `.env`
```bash
cp .env.example .env
# Fill in all values
```

---

## Running

### Docker (recommended)
```bash
docker compose up --build -d
docker compose logs -f
```

### Local (development)
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd src && python bot.py
```

### VS Code
- Open `Run & Debug` → select `Run Bot (local)` → press F5

---

## Example Usage

```
/analyze NATGASMINI MCX 15m
/alert add NATGASMINI MCX below 215
/pnl open NATGASMINI BUY 10 220 215 235
/risk NATGASMINI BUY 220 215 235 10
/remind Check EIA report in 30m
/watchlist add CRUDEOIL MCX
/summary
```

---

## Kite Access Token Refresh

Kite access tokens expire daily. After market open:
1. `/login` → click link → login to Zerodha
2. Copy `request_token` from redirect URL
3. `/settoken YOUR_REQUEST_TOKEN`

You can automate this with Kite's webhook or a cron job.

---

## Notes
- All analysis is for educational/informational purposes only.
- Never invest based solely on bot signals — use your own judgement.
- NATGASMINI lot size on MCX = 100 mmBtu. Factor this into risk calculations.
