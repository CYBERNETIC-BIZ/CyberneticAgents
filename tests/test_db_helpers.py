"""Tests for new DB helper functions."""
from cybernetic.storage.db import (
    save_agent, save_prediction, save_trade,
    get_trade_for_prediction, recalculate_agent_balance, get_agent,
)
from cybernetic.storage.models import Agent, Prediction, Trade


def _make_agent(agent_id="test-agent", balance=10000.0):
    return Agent(
        id=agent_id, name="Test", ticker="AAPL",
        persona_json="{}", research_report="test",
        portfolio_balance=balance,
    )


def test_get_trade_for_prediction():
    agent = _make_agent()
    save_agent(agent)
    pred = save_prediction(Prediction(
        agent_id=agent.id, ticker="AAPL", direction="BULLISH",
        confidence=0.8, reasoning="test", entry_price=150.0,
    ))
    save_trade(Trade(
        prediction_id=pred.id, agent_id=agent.id,
        side="BUY", ticker="AAPL", price=150.0, quantity=10.0, fee=1.5,
    ))
    result = get_trade_for_prediction(pred.id, "BUY")
    assert result is not None
    assert result.quantity == 10.0


def test_get_trade_for_prediction_returns_none():
    assert get_trade_for_prediction(9999, "BUY") is None


def test_recalculate_long_trade():
    """BUY $1000 at $100 (10 shares), SELL at $110."""
    agent = _make_agent()
    save_agent(agent)
    pred = save_prediction(Prediction(
        agent_id=agent.id, ticker="AAPL", direction="BULLISH",
        confidence=0.8, reasoning="test", entry_price=100.0,
    ))
    save_trade(Trade(
        prediction_id=pred.id, agent_id=agent.id,
        side="BUY", ticker="AAPL", price=100.0, quantity=10.0, fee=1.0,
    ))
    save_trade(Trade(
        prediction_id=pred.id, agent_id=agent.id,
        side="SELL", ticker="AAPL", price=110.0, quantity=10.0, fee=1.10,
    ))
    recalculate_agent_balance(agent.id)
    updated = get_agent(agent.id)
    # 10000 - (1000+1) + (1100-1.10) = 10097.90
    assert round(updated.portfolio_balance, 2) == 10097.90


def test_recalculate_short_trade():
    """SHORT_SELL at $100, SHORT_COVER effective price $110 (market dropped to $90)."""
    agent = _make_agent()
    save_agent(agent)
    pred = save_prediction(Prediction(
        agent_id=agent.id, ticker="AAPL", direction="BEARISH",
        confidence=0.8, reasoning="test", entry_price=100.0,
    ))
    save_trade(Trade(
        prediction_id=pred.id, agent_id=agent.id,
        side="SHORT_SELL", ticker="AAPL", price=100.0, quantity=10.0, fee=1.0,
    ))
    # SHORT_COVER: effective_price = 2*100-90 = 110 (stored as trade.price)
    save_trade(Trade(
        prediction_id=pred.id, agent_id=agent.id,
        side="SHORT_COVER", ticker="AAPL", price=110.0, quantity=10.0, fee=1.10,
    ))
    recalculate_agent_balance(agent.id)
    updated = get_agent(agent.id)
    # 10000 - (1000+1) + (1100-1.10) = 10097.90
    assert round(updated.portfolio_balance, 2) == 10097.90


def test_recalculate_no_trades():
    agent = _make_agent()
    save_agent(agent)
    recalculate_agent_balance(agent.id)
    assert get_agent(agent.id).portfolio_balance == 10000.0
