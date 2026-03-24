"""Tests for migration backfill."""
from datetime import date, timedelta
from cybernetic.storage.db import (
    save_agent, save_prediction, save_trade, get_agent,
    get_connection, _upgrade_db, get_trade_for_prediction,
    recalculate_agent_balance,
)
from cybernetic.storage.models import Agent, Prediction, Trade


def test_backfill_creates_missing_sell_trades():
    """Resolved prediction with BUY but no SELL gets backfilled."""
    agent = Agent(
        id="backfill-test", name="Test", ticker="AAPL",
        persona_json="{}", research_report="test",
        portfolio_balance=8000.0,  # broken balance
    )
    save_agent(agent)
    pred = save_prediction(Prediction(
        agent_id=agent.id, ticker="AAPL", direction="BULLISH",
        confidence=0.8, reasoning="test", entry_price=100.0,
        target_date=date.today() - timedelta(days=1),
        result="correct", exit_price=110.0,
    ))
    # Has BUY but no SELL
    save_trade(Trade(
        prediction_id=pred.id, agent_id=agent.id,
        side="BUY", ticker="AAPL", price=100.0, quantity=10.0, fee=1.0,
    ))

    # Run upgrade which should backfill
    conn = get_connection()
    _upgrade_db(conn)
    conn.close()

    sell = get_trade_for_prediction(pred.id, "SELL")
    assert sell is not None
    assert sell.quantity == 10.0
    assert sell.price == 110.0

    # Balance should be recalculated correctly
    updated = get_agent(agent.id)
    # 10000 - (1000+1) + (1100 - 1.10) = 10097.90
    assert round(updated.portfolio_balance, 2) == 10097.90


def test_backfill_skips_correct_existing_sell():
    """If SELL trade already exists with correct qty, don't modify it."""
    agent = Agent(
        id="skip-test", name="Test", ticker="AAPL",
        persona_json="{}", research_report="test",
        portfolio_balance=10000.0,
    )
    save_agent(agent)
    pred = save_prediction(Prediction(
        agent_id=agent.id, ticker="AAPL", direction="BULLISH",
        confidence=0.8, reasoning="test", entry_price=100.0,
        target_date=date.today() - timedelta(days=1),
        result="correct", exit_price=110.0,
    ))
    save_trade(Trade(
        prediction_id=pred.id, agent_id=agent.id,
        side="BUY", ticker="AAPL", price=100.0, quantity=10.0, fee=1.0,
    ))
    save_trade(Trade(
        prediction_id=pred.id, agent_id=agent.id,
        side="SELL", ticker="AAPL", price=110.0, quantity=10.0, fee=1.10,
    ))

    conn = get_connection()
    _upgrade_db(conn)
    conn.close()

    # Should still be exactly one SELL trade (not duplicated)
    from cybernetic.storage.db import get_connection as gc
    c = gc()
    count = c.execute(
        "SELECT COUNT(*) as cnt FROM trades WHERE prediction_id = ? AND side = 'SELL'",
        (pred.id,),
    ).fetchone()["cnt"]
    c.close()
    assert count == 1


def test_backfill_fixes_existing_sell_with_wrong_quantity():
    """Old resolver created SELL with wrong qty — migration should fix it."""
    agent = Agent(
        id="fix-qty-test", name="Test", ticker="AAPL",
        persona_json="{}", research_report="test",
        portfolio_balance=8000.0,
    )
    save_agent(agent)
    pred = save_prediction(Prediction(
        agent_id=agent.id, ticker="AAPL", direction="BULLISH",
        confidence=0.8, reasoning="test", entry_price=100.0,
        target_date=date.today() - timedelta(days=1),
        result="correct", exit_price=110.0,
    ))
    # BUY 10 shares
    save_trade(Trade(
        prediction_id=pred.id, agent_id=agent.id,
        side="BUY", ticker="AAPL", price=100.0, quantity=10.0, fee=1.0,
    ))
    # Old buggy SELL with wrong quantity (5 instead of 10)
    save_trade(Trade(
        prediction_id=pred.id, agent_id=agent.id,
        side="SELL", ticker="AAPL", price=110.0, quantity=5.0, fee=0.55,
    ))

    conn = get_connection()
    _upgrade_db(conn)
    conn.close()

    # SELL trade should be corrected to match BUY quantity
    sell = get_trade_for_prediction(pred.id, "SELL")
    assert sell is not None
    assert sell.quantity == 10.0
    assert sell.price == 110.0
    assert round(sell.fee, 2) == round(1100.0 * 0.001, 2)

    # Balance should be correct
    updated = get_agent(agent.id)
    # 10000 - (1000+1) + (1100-1.10) = 10097.90
    assert round(updated.portfolio_balance, 2) == 10097.90


def test_backfill_recalculates_balance_for_agent_with_no_resolved():
    """Agent with only pending predictions keeps initial balance."""
    agent = Agent(
        id="no-resolve-test", name="Test", ticker="AAPL",
        persona_json="{}", research_report="test",
        portfolio_balance=5000.0,  # wrong
    )
    save_agent(agent)
    # Pending prediction with BUY trade (not resolved)
    pred = save_prediction(Prediction(
        agent_id=agent.id, ticker="AAPL", direction="BULLISH",
        confidence=0.8, reasoning="test", entry_price=100.0,
        target_date=date.today() + timedelta(days=5),
    ))
    save_trade(Trade(
        prediction_id=pred.id, agent_id=agent.id,
        side="BUY", ticker="AAPL", price=100.0, quantity=10.0, fee=1.0,
    ))

    conn = get_connection()
    _upgrade_db(conn)
    conn.close()

    updated = get_agent(agent.id)
    # 10000 - (1000 + 1) = 8999 (only the BUY, no SELL since not resolved)
    assert round(updated.portfolio_balance, 2) == 8999.0
