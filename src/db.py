"""SQLite persistence — alerts, trades, watchlist."""
import sqlite3
import logging
from datetime import datetime
from src.config import DB_PATH

log = logging.getLogger(__name__)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create all tables on first run."""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS price_alerts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER NOT NULL,
            symbol    TEXT    NOT NULL,
            exchange  TEXT    NOT NULL DEFAULT 'MCX',
            condition TEXT    NOT NULL,   -- 'above' | 'below'
            price     REAL    NOT NULL,
            active    INTEGER NOT NULL DEFAULT 1,
            created_at TEXT   NOT NULL
        );

        CREATE TABLE IF NOT EXISTS trades (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            symbol     TEXT    NOT NULL,
            side       TEXT    NOT NULL,   -- 'BUY' | 'SELL'
            qty        REAL    NOT NULL,
            entry      REAL    NOT NULL,
            exit       REAL,
            sl         REAL,
            target     REAL,
            pnl        REAL,
            status     TEXT    NOT NULL DEFAULT 'OPEN',
            entered_at TEXT    NOT NULL,
            closed_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id  INTEGER NOT NULL,
            symbol   TEXT    NOT NULL,
            exchange TEXT    NOT NULL DEFAULT 'MCX',
            UNIQUE(user_id, symbol, exchange)
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            message     TEXT    NOT NULL,
            remind_at   TEXT    NOT NULL,
            triggered   INTEGER NOT NULL DEFAULT 0
        );
        """)
    log.info("Database initialised at %s", DB_PATH)


# ── Price alerts ──────────────────────────────────────────────

def add_alert(user_id: int, symbol: str, exchange: str,
              condition: str, price: float) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO price_alerts (user_id, symbol, exchange, condition, price, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, symbol.upper(), exchange.upper(),
             condition, price, datetime.now().isoformat())
        )
        return cur.lastrowid


def get_active_alerts(user_id: int | None = None) -> list[sqlite3.Row]:
    with get_conn() as conn:
        if user_id:
            return conn.execute(
                "SELECT * FROM price_alerts WHERE active=1 AND user_id=?", (user_id,)
            ).fetchall()
        return conn.execute(
            "SELECT * FROM price_alerts WHERE active=1"
        ).fetchall()


def deactivate_alert(alert_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE price_alerts SET active=0 WHERE id=?", (alert_id,))


# ── Trades / P&L ─────────────────────────────────────────────

def open_trade(user_id: int, symbol: str, side: str,
               qty: float, entry: float, sl: float | None,
               target: float | None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO trades (user_id, symbol, side, qty, entry, sl, target, entered_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, symbol.upper(), side.upper(), qty, entry, sl, target,
             datetime.now().isoformat())
        )
        return cur.lastrowid


def close_trade(trade_id: int, exit_price: float) -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT side, qty, entry FROM trades WHERE id=?", (trade_id,)
        ).fetchone()
        if not row:
            return 0.0
        mult = 1 if row["side"] == "BUY" else -1
        pnl = mult * (exit_price - row["entry"]) * row["qty"]
        conn.execute(
            "UPDATE trades SET exit=?, pnl=?, status='CLOSED', closed_at=? WHERE id=?",
            (exit_price, pnl, datetime.now().isoformat(), trade_id)
        )
        return pnl


def get_open_trades(user_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM trades WHERE user_id=? AND status='OPEN'", (user_id,)
        ).fetchall()


def get_pnl_summary(user_id: int) -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT pnl FROM trades WHERE user_id=? AND status='CLOSED'", (user_id,)
        ).fetchall()
    pnls = [r["pnl"] for r in rows if r["pnl"] is not None]
    return {
        "total_trades": len(pnls),
        "total_pnl": round(sum(pnls), 2),
        "winners": sum(1 for p in pnls if p > 0),
        "losers": sum(1 for p in pnls if p <= 0),
        "best": round(max(pnls), 2) if pnls else 0,
        "worst": round(min(pnls), 2) if pnls else 0,
    }


# ── Watchlist ─────────────────────────────────────────────────

def add_to_watchlist(user_id: int, symbol: str, exchange: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (user_id, symbol, exchange) VALUES (?, ?, ?)",
            (user_id, symbol.upper(), exchange.upper())
        )


def get_watchlist(user_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT symbol, exchange FROM watchlist WHERE user_id=?", (user_id,)
        ).fetchall()


def remove_from_watchlist(user_id: int, symbol: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM watchlist WHERE user_id=? AND symbol=?",
            (user_id, symbol.upper())
        )


# ── Reminders ─────────────────────────────────────────────────

def add_reminder(user_id: int, message: str, remind_at: datetime) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO reminders (user_id, message, remind_at) VALUES (?, ?, ?)",
            (user_id, message, remind_at.isoformat())
        )
        return cur.lastrowid


def get_due_reminders() -> list[sqlite3.Row]:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM reminders WHERE triggered=0 AND remind_at<=?", (now,)
        ).fetchall()


def mark_reminder_done(reminder_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET triggered=1 WHERE id=?", (reminder_id,)
        )
