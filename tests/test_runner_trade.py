"""Tests for runner trade execution logic."""
import json
from unittest.mock import patch, MagicMock
import pandas as pd
from cybernetic.storage.db import save_agent, get_agent, get_trade_for_prediction
from cybernetic.storage.models import Agent


def _make_agent(agent_id="test-runner", balance=10000.0):
    return Agent(
        id=agent_id, name="Test Runner", ticker="AAPL",
        persona_json=json.dumps({"analysis_system_prompt": "You are a test."}),
        research_report="test", portfolio_balance=balance,
    )


def _mock_yfinance(price=150.0):
    hist = pd.DataFrame({
        "Close": [145.0, 148.0, price],
        "High": [146.0, 149.0, price + 1],
        "Low": [144.0, 147.0, price - 1],
        "Volume": [1000000, 1100000, 1200000],
    })
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist
    return mock_ticker


@patch("yfinance.Ticker")
@patch("cybernetic.llm.create_llm_client")
@patch("cybernetic.agents.runner.push_prediction_to_cybernetic")
def test_bullish_buy_with_position_size(mock_push, mock_llm_factory, mock_yf_ticker):
    agent = _make_agent()
    save_agent(agent)
    mock_yf_ticker.return_value = _mock_yfinance(150.0)
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=json.dumps({
        "direction": "BULLISH", "confidence": 0.8,
        "reasoning": "test", "target_days": 7, "position_size": 20,
    }))
    mock_client = MagicMock()
    mock_client.get_llm.return_value = mock_llm
    mock_llm_factory.return_value = mock_client

    from cybernetic.agents.runner import run_agent_once
    pred = run_agent_once(agent.id, push_to_cybernetic=False)

    assert pred is not None
    # Single-ticker agents (max_positions=1) go all-in
    assert pred.position_pct == 100.0
    assert pred.position_size == 10000.0
    buy = get_trade_for_prediction(pred.id, "BUY")
    assert buy is not None
    assert buy.side == "BUY"
    assert round(buy.quantity, 4) == round(10000.0 / 150.0, 4)
    assert round(buy.fee, 2) == 10.0  # 0.1% of 10000
    updated = get_agent(agent.id)
    assert round(updated.portfolio_balance, 2) == round(10000.0 - 10000.0 - 10.0, 2)


@patch("yfinance.Ticker")
@patch("cybernetic.llm.create_llm_client")
@patch("cybernetic.agents.runner.push_prediction_to_cybernetic")
def test_bearish_short_sell(mock_push, mock_llm_factory, mock_yf_ticker):
    agent = _make_agent()
    save_agent(agent)
    mock_yf_ticker.return_value = _mock_yfinance(150.0)
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=json.dumps({
        "direction": "BEARISH", "confidence": 0.7,
        "reasoning": "test bearish", "target_days": 5, "position_size": 10,
    }))
    mock_client = MagicMock()
    mock_client.get_llm.return_value = mock_llm
    mock_llm_factory.return_value = mock_client

    from cybernetic.agents.runner import run_agent_once
    pred = run_agent_once(agent.id, push_to_cybernetic=False)

    assert pred is not None
    assert pred.direction == "BEARISH"
    trade = get_trade_for_prediction(pred.id, "SHORT_SELL")
    assert trade is not None
    assert trade.side == "SHORT_SELL"


@patch("yfinance.Ticker")
@patch("cybernetic.llm.create_llm_client")
@patch("cybernetic.agents.runner.push_prediction_to_cybernetic")
def test_position_size_clamped_to_min_5(mock_push, mock_llm_factory, mock_yf_ticker):
    agent = _make_agent()
    save_agent(agent)
    mock_yf_ticker.return_value = _mock_yfinance(150.0)
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=json.dumps({
        "direction": "BULLISH", "confidence": 0.8,
        "reasoning": "test", "target_days": 7, "position_size": 1,
    }))
    mock_client = MagicMock()
    mock_client.get_llm.return_value = mock_llm
    mock_llm_factory.return_value = mock_client

    from cybernetic.agents.runner import run_agent_once
    pred = run_agent_once(agent.id, push_to_cybernetic=False)

    assert pred is not None
    # Single-ticker agents (max_positions=1) go all-in regardless of requested size
    assert pred.position_pct == 100.0
    assert pred.position_size == 10000.0
