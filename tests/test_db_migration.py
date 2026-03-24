"""Tests for DB migration and schema changes."""
from cybernetic.storage.db import (
    get_connection, save_prediction, save_agent,
    get_agent_stats, resolve_prediction, _upgrade_db,
)
from cybernetic.storage.models import Agent, Prediction


def _make_agent(agent_id="test-agent"):
    return Agent(
        id=agent_id, name="Test", ticker="AAPL",
        persona_json="{}", research_report="test",
    )


def test_prediction_stores_position_fields():
    agent = _make_agent()
    save_agent(agent)
    pred = Prediction(
        agent_id=agent.id, ticker="AAPL", direction="BULLISH",
        confidence=0.8, reasoning="test", entry_price=150.0,
        position_pct=15.0, position_size=1500.0,
    )
    saved = save_prediction(pred)
    assert saved.position_pct == 15.0
    assert saved.position_size == 1500.0


def test_upgrade_lowercases_existing_results():
    agent = _make_agent()
    save_agent(agent)
    pred = save_prediction(Prediction(
        agent_id=agent.id, ticker="AAPL", direction="BULLISH",
        confidence=0.8, reasoning="test", entry_price=150.0,
    ))
    conn = get_connection()
    conn.execute("UPDATE predictions SET result = 'CORRECT' WHERE id = ?", (pred.id,))
    conn.commit()
    _upgrade_db(conn)
    conn.close()
    stats = get_agent_stats(agent.id)
    assert stats["correct"] == 1


def test_resolve_writes_lowercase():
    agent = _make_agent()
    save_agent(agent)
    pred = save_prediction(Prediction(
        agent_id=agent.id, ticker="AAPL", direction="BULLISH",
        confidence=0.8, reasoning="test", entry_price=150.0,
    ))
    resolve_prediction(pred.id, "correct", 160.0)
    stats = get_agent_stats(agent.id)
    assert stats["correct"] == 1
