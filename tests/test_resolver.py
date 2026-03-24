"""Tests for prediction resolver."""
from unittest.mock import patch, MagicMock
import pandas as pd
from datetime import date, timedelta
from cybernetic.storage.db import (
    save_agent, save_prediction, save_trade,
    get_agent, get_agent_stats, get_trade_for_prediction,
)
from cybernetic.storage.models import Agent, Prediction, Trade


def _make_agent(agent_id="test-resolver", balance=9000.0):
    return Agent(
        id=agent_id, name="Test", ticker="AAPL",
        persona_json="{}", research_report="test",
        portfolio_balance=balance,
    )


def _mock_yf_price(price):
    hist = pd.DataFrame({"Close": [price]})
    m = MagicMock()
    m.history.return_value = hist
    return m


@patch("cybernetic.agents.resolver.yf")
def test_resolve_bullish_correct(mock_yf):
    agent = _make_agent()
    save_agent(agent)
    pred = save_prediction(Prediction(
        agent_id=agent.id, ticker="AAPL", direction="BULLISH",
        confidence=0.8, reasoning="test", entry_price=100.0,
        target_date=date.today() - timedelta(days=1),
        position_pct=10.0, position_size=1000.0,
    ))
    save_trade(Trade(
        prediction_id=pred.id, agent_id=agent.id,
        side="BUY", ticker="AAPL", price=100.0, quantity=10.0, fee=1.0,
    ))
    mock_yf.Ticker.return_value = _mock_yf_price(110.0)

    from cybernetic.agents.resolver import resolve_all_pending
    resolve_all_pending()

    sell = get_trade_for_prediction(pred.id, "SELL")
    assert sell is not None
    assert sell.quantity == 10.0
    assert sell.price == 110.0
    assert round(sell.fee, 2) == round(1100.0 * 0.001, 2)  # 1.10

    updated = get_agent(agent.id)
    # 9000 + (1100 - 1.10) = 10098.90
    assert round(updated.portfolio_balance, 2) == 10098.90

    stats = get_agent_stats(agent.id)
    assert stats["correct"] == 1


@patch("cybernetic.agents.resolver.yf")
def test_resolve_bearish_correct(mock_yf):
    agent = _make_agent()
    save_agent(agent)
    pred = save_prediction(Prediction(
        agent_id=agent.id, ticker="AAPL", direction="BEARISH",
        confidence=0.8, reasoning="test", entry_price=100.0,
        target_date=date.today() - timedelta(days=1),
        position_pct=10.0, position_size=1000.0,
    ))
    save_trade(Trade(
        prediction_id=pred.id, agent_id=agent.id,
        side="SHORT_SELL", ticker="AAPL", price=100.0, quantity=10.0, fee=1.0,
    ))
    mock_yf.Ticker.return_value = _mock_yf_price(90.0)

    from cybernetic.agents.resolver import resolve_all_pending
    resolve_all_pending()

    cover = get_trade_for_prediction(pred.id, "SHORT_COVER")
    assert cover is not None
    assert round(cover.price, 2) == 110.0  # effective: 2*100-90
    assert round(cover.fee, 2) == round(1100 * 0.001, 2)

    updated = get_agent(agent.id)
    # 9000 + (1100 - 1.10) = 10098.90
    assert round(updated.portfolio_balance, 2) == 10098.90

    stats = get_agent_stats(agent.id)
    assert stats["correct"] == 1


@patch("cybernetic.agents.resolver.yf")
def test_resolve_bullish_incorrect(mock_yf):
    """BULLISH but price dropped -- incorrect, still creates SELL trade."""
    agent = _make_agent()
    save_agent(agent)
    pred = save_prediction(Prediction(
        agent_id=agent.id, ticker="AAPL", direction="BULLISH",
        confidence=0.8, reasoning="test", entry_price=100.0,
        target_date=date.today() - timedelta(days=1),
        position_pct=10.0, position_size=1000.0,
    ))
    save_trade(Trade(
        prediction_id=pred.id, agent_id=agent.id,
        side="BUY", ticker="AAPL", price=100.0, quantity=10.0, fee=1.0,
    ))
    mock_yf.Ticker.return_value = _mock_yf_price(90.0)

    from cybernetic.agents.resolver import resolve_all_pending
    resolve_all_pending()

    sell = get_trade_for_prediction(pred.id, "SELL")
    assert sell is not None
    assert sell.price == 90.0

    updated = get_agent(agent.id)
    # 9000 + (900 - 0.90) = 9899.10
    assert round(updated.portfolio_balance, 2) == 9899.10

    stats = get_agent_stats(agent.id)
    assert stats["correct"] == 0
