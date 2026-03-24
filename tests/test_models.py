"""Tests for data models."""
from cybernetic.storage.models import Prediction


def test_prediction_has_position_fields():
    p = Prediction(agent_id="a1", ticker="AAPL", direction="BULLISH",
                   confidence=0.8, reasoning="test", entry_price=150.0)
    assert p.position_pct == 10.0
    assert p.position_size == 0.0
