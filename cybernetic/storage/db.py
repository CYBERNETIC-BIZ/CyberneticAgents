"""SQLite database operations for CyberneticAgents."""
import shutil
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional

from .models import Agent, Prediction, Trade

DB_DIR = Path.home() / ".cybernetic"
DB_PATH = DB_DIR / "cybernetic.db"

# Legacy path for auto-migration
_LEGACY_DB_DIR = Path.home() / ".oraculo"
_LEGACY_DB_PATH = _LEGACY_DB_DIR / "oraculo.db"


def _migrate_legacy_db() -> None:
    """Auto-migrate ~/.oraculo/oraculo.db → ~/.cybernetic/cybernetic.db if needed."""
    if DB_PATH.exists() or not _LEGACY_DB_PATH.exists():
        return
    DB_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(_LEGACY_DB_PATH), str(DB_PATH))


def get_connection() -> sqlite3.Connection:
    """Return a sqlite3 connection to the CyberneticAgents database.

    The database file is stored at ~/.cybernetic/cybernetic.db.
    WAL journal mode and foreign keys are enabled.
    """
    _migrate_legacy_db()
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _upgrade_db(conn: sqlite3.Connection) -> None:
    """Add new columns to existing tables for backward compatibility.

    Each ALTER TABLE is wrapped in try/except so it is safe to run multiple
    times (idempotent).
    """
    new_agent_columns = [
        ("description", "TEXT NOT NULL DEFAULT ''"),
        ("tools", "TEXT NOT NULL DEFAULT '[]'"),
        ("analysis_system_prompt", "TEXT NOT NULL DEFAULT ''"),
        ("comment_system_prompt", "TEXT NOT NULL DEFAULT ''"),
        ("analysis_temperature", "REAL NOT NULL DEFAULT 0.7"),
        ("comment_temperature", "REAL NOT NULL DEFAULT 0.8"),
        ("target_days", "INTEGER NOT NULL DEFAULT 7"),
        ("max_positions", "INTEGER NOT NULL DEFAULT 5"),
        ("personality", "TEXT NOT NULL DEFAULT ''"),
        ("direction_bias", "TEXT NOT NULL DEFAULT 'neutral'"),
        ("created_from", "TEXT NOT NULL DEFAULT 'manual'"),
        ("cybernetic_api_key", "TEXT NOT NULL DEFAULT ''"),
    ]
    for col_name, col_def in new_agent_columns:
        try:
            conn.execute(f"ALTER TABLE agents ADD COLUMN {col_name} {col_def}")
        except sqlite3.OperationalError:
            pass  # Column already exists

    new_prediction_columns = [
        ("position_pct", "REAL NOT NULL DEFAULT 10.0"),
        ("position_size", "REAL NOT NULL DEFAULT 0.0"),
    ]
    for col_name, col_def in new_prediction_columns:
        try:
            conn.execute(f"ALTER TABLE predictions ADD COLUMN {col_name} {col_def}")
        except sqlite3.OperationalError:
            pass

    # Rename legacy columns
    try:
        conn.execute("ALTER TABLE agents RENAME COLUMN oraculo_api_key TO cybernetic_api_key")
    except sqlite3.OperationalError:
        pass  # Already renamed or doesn't exist
    try:
        conn.execute("ALTER TABLE predictions RENAME COLUMN pushed_to_oraculo TO pushed_to_cybernetic")
    except sqlite3.OperationalError:
        pass

    # Normalize result values to lowercase
    conn.execute("UPDATE predictions SET result = LOWER(result) WHERE result IN ('CORRECT', 'INCORRECT')")
    conn.commit()

    # Backfill missing SELL/SHORT_COVER trades for resolved predictions
    resolved = conn.execute("""
        SELECT p.id, p.agent_id, p.ticker, p.direction, p.entry_price, p.exit_price
        FROM predictions p
        WHERE p.result IS NOT NULL AND p.exit_price IS NOT NULL
    """).fetchall()

    for row in resolved:
        pred_id = row["id"]
        direction = row["direction"]
        open_side = "SHORT_SELL" if direction == "BEARISH" else "BUY"
        close_side = "SHORT_COVER" if direction == "BEARISH" else "SELL"

        # Get the opening trade for quantity
        open_trade = conn.execute(
            "SELECT * FROM trades WHERE prediction_id = ? AND side = ?",
            (pred_id, open_side),
        ).fetchone()
        if not open_trade:
            continue

        quantity = open_trade["quantity"]
        entry_price = row["entry_price"]
        exit_price = row["exit_price"]

        if direction == "BEARISH":
            effective_price = 2 * entry_price - exit_price
        else:
            effective_price = exit_price

        sell_value = effective_price * quantity
        fee = sell_value * 0.001

        # Check if closing trade already exists
        existing = conn.execute(
            "SELECT id, quantity FROM trades WHERE prediction_id = ? AND side = ?",
            (pred_id, close_side),
        ).fetchone()

        if existing:
            # Fix existing closing trade if quantity doesn't match opening trade
            if abs(existing["quantity"] - quantity) > 0.0001:
                conn.execute(
                    """UPDATE trades SET price = ?, quantity = ?, fee = ?
                       WHERE id = ?""",
                    (effective_price, quantity, fee, existing["id"]),
                )
        else:
            conn.execute(
                """INSERT INTO trades (prediction_id, agent_id, side, ticker, price, quantity, fee)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (pred_id, row["agent_id"], close_side, row["ticker"],
                 effective_price, quantity, fee),
            )

    conn.commit()

    # Recalculate all agent balances from trades
    agent_ids = [r["id"] for r in conn.execute("SELECT id FROM agents").fetchall()]
    for aid in agent_ids:
        rows = conn.execute(
            "SELECT * FROM trades WHERE agent_id = ? ORDER BY created_at, id",
            (aid,),
        ).fetchall()
        balance = 10000.0
        for tr in rows:
            notional = tr["price"] * tr["quantity"]
            if tr["side"] in ("BUY", "SHORT_SELL"):
                balance -= (notional + tr["fee"])
            elif tr["side"] in ("SELL", "SHORT_COVER"):
                balance += (notional - tr["fee"])
        conn.execute("UPDATE agents SET portfolio_balance = ? WHERE id = ?", (balance, aid))
    conn.commit()


def init_db() -> None:
    """Create the agents, predictions, and trades tables if they do not exist."""
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS agents (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                ticker          TEXT NOT NULL,
                persona_json    TEXT NOT NULL,
                research_report TEXT NOT NULL,
                portfolio_balance REAL NOT NULL DEFAULT 10000.0,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                description     TEXT NOT NULL DEFAULT '',
                tools           TEXT NOT NULL DEFAULT '[]',
                analysis_system_prompt TEXT NOT NULL DEFAULT '',
                comment_system_prompt  TEXT NOT NULL DEFAULT '',
                analysis_temperature   REAL NOT NULL DEFAULT 0.7,
                comment_temperature    REAL NOT NULL DEFAULT 0.8,
                target_days     INTEGER NOT NULL DEFAULT 7,
                max_positions   INTEGER NOT NULL DEFAULT 5,
                personality     TEXT NOT NULL DEFAULT '',
                direction_bias  TEXT NOT NULL DEFAULT 'neutral',
                created_from    TEXT NOT NULL DEFAULT 'manual',
                cybernetic_api_key TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS predictions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id        TEXT NOT NULL REFERENCES agents(id),
                ticker          TEXT NOT NULL,
                direction       TEXT NOT NULL,
                confidence      REAL NOT NULL,
                reasoning       TEXT NOT NULL,
                entry_price     REAL NOT NULL,
                target_date     DATE,
                result          TEXT,
                exit_price      REAL,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at     TIMESTAMP,
                pushed_to_cybernetic INTEGER NOT NULL DEFAULT 0,
                position_pct    REAL NOT NULL DEFAULT 10.0,
                position_size   REAL NOT NULL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS trades (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction_id   INTEGER NOT NULL REFERENCES predictions(id),
                agent_id        TEXT NOT NULL REFERENCES agents(id),
                side            TEXT NOT NULL,
                ticker          TEXT NOT NULL,
                price           REAL NOT NULL,
                quantity        REAL NOT NULL,
                fee             REAL NOT NULL DEFAULT 0.0,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()
        _upgrade_db(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Agent helpers
# ---------------------------------------------------------------------------


def save_agent(agent: Agent) -> Agent:
    """Insert or replace an agent record and return it with created_at populated."""
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO agents
                (id, name, ticker, persona_json, research_report, portfolio_balance,
                 created_at, description, tools, analysis_system_prompt,
                 comment_system_prompt, analysis_temperature, comment_temperature,
                 target_days, max_positions, personality, direction_bias, created_from,
                 cybernetic_api_key)
            VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP),
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent.id,
                agent.name,
                agent.ticker,
                agent.persona_json,
                agent.research_report,
                agent.portfolio_balance,
                agent.created_at.isoformat() if agent.created_at else None,
                agent.description,
                agent.tools,
                agent.analysis_system_prompt,
                agent.comment_system_prompt,
                agent.analysis_temperature,
                agent.comment_temperature,
                agent.target_days,
                agent.max_positions,
                agent.personality,
                agent.direction_bias,
                agent.created_from,
                agent.cybernetic_api_key,
            ),
        )
        conn.commit()
        return get_agent(agent.id)  # type: ignore[return-value]
    finally:
        conn.close()


def _safe_get(row: sqlite3.Row, key: str, default=None):
    """Safely get a column value from a Row, returning *default* if missing."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def _row_to_agent(row: sqlite3.Row) -> Agent:
    """Convert a sqlite3.Row to an Agent dataclass."""
    return Agent(
        id=row["id"],
        name=row["name"],
        ticker=row["ticker"],
        persona_json=row["persona_json"],
        research_report=row["research_report"],
        portfolio_balance=row["portfolio_balance"],
        created_at=(
            datetime.fromisoformat(row["created_at"])
            if row["created_at"]
            else None
        ),
        description=_safe_get(row, "description", ""),
        tools=_safe_get(row, "tools", "[]"),
        analysis_system_prompt=_safe_get(row, "analysis_system_prompt", ""),
        comment_system_prompt=_safe_get(row, "comment_system_prompt", ""),
        analysis_temperature=_safe_get(row, "analysis_temperature", 0.7),
        comment_temperature=_safe_get(row, "comment_temperature", 0.8),
        target_days=_safe_get(row, "target_days", 7),
        max_positions=_safe_get(row, "max_positions", 5),
        personality=_safe_get(row, "personality", ""),
        direction_bias=_safe_get(row, "direction_bias", "neutral"),
        created_from=_safe_get(row, "created_from", "manual"),
        cybernetic_api_key=_safe_get(row, "cybernetic_api_key", ""),
    )


def get_agent(agent_id: str) -> Optional[Agent]:
    """Fetch a single agent by id, or None if not found."""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        row = cur.fetchone()
        return _row_to_agent(row) if row else None
    finally:
        conn.close()


def list_agents() -> List[Agent]:
    """Return every agent in the database."""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT * FROM agents ORDER BY created_at")
        return [_row_to_agent(r) for r in cur.fetchall()]
    finally:
        conn.close()


def delete_agent(agent_id: str) -> bool:
    """Delete an agent and its associated predictions and trades.

    Returns True if the agent existed and was deleted.
    """
    conn = get_connection()
    try:
        # Delete trades and predictions first (foreign key order)
        conn.execute("DELETE FROM trades WHERE agent_id = ?", (agent_id,))
        conn.execute("DELETE FROM predictions WHERE agent_id = ?", (agent_id,))
        cur = conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_agent_balance(agent_id: str, new_balance: float) -> None:
    """Update the portfolio balance for an agent."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE agents SET portfolio_balance = ? WHERE id = ?",
            (new_balance, agent_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_agent_api_key(agent_id: str, api_key: str) -> None:
    """Persist the cybernetic.biz API key for an agent."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE agents SET cybernetic_api_key = ? WHERE id = ?",
            (api_key, agent_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Prediction helpers
# ---------------------------------------------------------------------------


def _row_to_prediction(row: sqlite3.Row) -> Prediction:
    """Convert a sqlite3.Row to a Prediction dataclass."""
    return Prediction(
        id=row["id"],
        agent_id=row["agent_id"],
        ticker=row["ticker"],
        direction=row["direction"],
        confidence=row["confidence"],
        reasoning=row["reasoning"],
        entry_price=row["entry_price"],
        target_date=(
            date.fromisoformat(row["target_date"])
            if row["target_date"]
            else None
        ),
        result=row["result"],
        exit_price=row["exit_price"],
        created_at=(
            datetime.fromisoformat(row["created_at"])
            if row["created_at"]
            else None
        ),
        resolved_at=(
            datetime.fromisoformat(row["resolved_at"])
            if row["resolved_at"]
            else None
        ),
        pushed_to_cybernetic=bool(row["pushed_to_cybernetic"]),
        position_pct=row["position_pct"] if "position_pct" in row.keys() else 10.0,
        position_size=row["position_size"] if "position_size" in row.keys() else 0.0,
    )


def save_prediction(pred: Prediction) -> Prediction:
    """Insert a prediction and return it with the generated id and created_at."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO predictions
                (agent_id, ticker, direction, confidence, reasoning,
                 entry_price, target_date, result, exit_price,
                 position_pct, position_size,
                 created_at, resolved_at, pushed_to_cybernetic)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), ?, ?)
            """,
            (
                pred.agent_id,
                pred.ticker,
                pred.direction,
                pred.confidence,
                pred.reasoning,
                pred.entry_price,
                pred.target_date.isoformat() if pred.target_date else None,
                pred.result,
                pred.exit_price,
                pred.position_pct,
                pred.position_size,
                pred.created_at.isoformat() if pred.created_at else None,
                pred.resolved_at.isoformat() if pred.resolved_at else None,
                int(pred.pushed_to_cybernetic),
            ),
        )
        conn.commit()
        pred_id = cur.lastrowid

        row = conn.execute(
            "SELECT * FROM predictions WHERE id = ?", (pred_id,)
        ).fetchone()
        return _row_to_prediction(row)
    finally:
        conn.close()


def get_agent_predictions(
    agent_id: str, pending_only: bool = False
) -> List[Prediction]:
    """Return predictions for an agent, optionally only unresolved ones."""
    conn = get_connection()
    try:
        if pending_only:
            cur = conn.execute(
                """
                SELECT * FROM predictions
                WHERE agent_id = ? AND result IS NULL
                ORDER BY created_at
                """,
                (agent_id,),
            )
        else:
            cur = conn.execute(
                """
                SELECT * FROM predictions
                WHERE agent_id = ?
                ORDER BY created_at
                """,
                (agent_id,),
            )
        return [_row_to_prediction(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_recent_resolved_predictions(
    agent_id: str, limit: int = 5
) -> List[Prediction]:
    """Return the most recent resolved predictions for an agent."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT * FROM predictions
            WHERE agent_id = ? AND result IS NOT NULL
            ORDER BY resolved_at DESC
            LIMIT ?
            """,
            (agent_id, limit),
        )
        return [_row_to_prediction(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_pending_predictions() -> List[Prediction]:
    """Return predictions that are unresolved and whose target date has passed."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT * FROM predictions
            WHERE result IS NULL AND target_date <= date('now')
            ORDER BY target_date
            """
        )
        return [_row_to_prediction(r) for r in cur.fetchall()]
    finally:
        conn.close()


def resolve_prediction(
    pred_id: int, result: str, exit_price: float
) -> None:
    """Mark a prediction as resolved with the given result and exit price."""
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE predictions
            SET result = ?, exit_price = ?, resolved_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (result, exit_price, pred_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_prediction_pushed(pred_id: int) -> None:
    """Mark a prediction as successfully pushed to cybernetic.biz."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE predictions SET pushed_to_cybernetic = 1 WHERE id = ?",
            (pred_id,),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Trade helpers
# ---------------------------------------------------------------------------


def _row_to_trade(row: sqlite3.Row) -> Trade:
    """Convert a sqlite3.Row to a Trade dataclass."""
    return Trade(
        id=row["id"],
        prediction_id=row["prediction_id"],
        agent_id=row["agent_id"],
        side=row["side"],
        ticker=row["ticker"],
        price=row["price"],
        quantity=row["quantity"],
        fee=row["fee"],
        created_at=(
            datetime.fromisoformat(row["created_at"])
            if row["created_at"]
            else None
        ),
    )


def save_trade(trade: Trade) -> Trade:
    """Insert a trade and return it with the generated id and created_at."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO trades
                (prediction_id, agent_id, side, ticker, price, quantity, fee,
                 created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
            """,
            (
                trade.prediction_id,
                trade.agent_id,
                trade.side,
                trade.ticker,
                trade.price,
                trade.quantity,
                trade.fee,
                trade.created_at.isoformat() if trade.created_at else None,
            ),
        )
        conn.commit()
        trade_id = cur.lastrowid

        row = conn.execute(
            "SELECT * FROM trades WHERE id = ?", (trade_id,)
        ).fetchone()
        return _row_to_trade(row)
    finally:
        conn.close()


def get_trade_for_prediction(prediction_id: int, side: str) -> Optional[Trade]:
    """Look up a trade by prediction_id and side (e.g. 'BUY', 'SHORT_SELL')."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM trades WHERE prediction_id = ? AND side = ?",
            (prediction_id, side),
        ).fetchone()
        return _row_to_trade(row) if row else None
    finally:
        conn.close()


INITIAL_BALANCE = 10000.0


def recalculate_agent_balance(agent_id: str) -> float:
    """Replay all trades chronologically to recompute portfolio balance.

    Returns the recalculated balance.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE agent_id = ? ORDER BY created_at, id",
            (agent_id,),
        ).fetchall()

        balance = INITIAL_BALANCE
        for row in rows:
            notional = row["price"] * row["quantity"]
            if row["side"] in ("BUY", "SHORT_SELL"):
                balance -= (notional + row["fee"])
            elif row["side"] in ("SELL", "SHORT_COVER"):
                balance += (notional - row["fee"])

        conn.execute(
            "UPDATE agents SET portfolio_balance = ? WHERE id = ?",
            (balance, agent_id),
        )
        conn.commit()
        return balance
    finally:
        conn.close()


def get_open_position_cost(agent_id: str) -> float:
    """Return the total cost basis of open (unresolved) positions for an agent."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(t.price * t.quantity), 0.0) AS open_cost
            FROM trades t
            JOIN predictions p ON p.id = t.prediction_id
            WHERE t.agent_id = ? AND p.result IS NULL
            AND t.side IN ('BUY', 'SHORT_SELL')
            """,
            (agent_id,),
        ).fetchone()
        return row["open_cost"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def get_agent_stats(agent_id: str) -> dict:
    """Return summary statistics for an agent's predictions.

    Returns a dict with keys: total, resolved, correct, pending, accuracy.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                COUNT(*)                                    AS total,
                COUNT(CASE WHEN result IS NOT NULL THEN 1 END) AS resolved,
                COUNT(CASE WHEN result = 'correct' THEN 1 END) AS correct,
                COUNT(CASE WHEN result IS NULL THEN 1 END)     AS pending
            FROM predictions
            WHERE agent_id = ?
            """,
            (agent_id,),
        ).fetchone()

        total = row["total"]
        resolved = row["resolved"]
        correct = row["correct"]
        pending = row["pending"]
        accuracy = (correct / resolved * 100.0) if resolved > 0 else 0.0

        return {
            "total": total,
            "resolved": resolved,
            "correct": correct,
            "pending": pending,
            "accuracy": round(accuracy, 2),
        }
    finally:
        conn.close()
