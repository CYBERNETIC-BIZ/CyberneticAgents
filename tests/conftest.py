"""Shared test fixtures."""
from unittest.mock import patch

import pytest

from cybernetic.spend import reset_guard_cache
from cybernetic.storage import db as db_module


@pytest.fixture(autouse=True)
def isolate_live_spend(tmp_path, monkeypatch):
    """Keep tests off live APIs and off the shared spend ledger."""
    reset_guard_cache()
    monkeypatch.setenv("CYBERNETIC_SPEND_LEDGER", str(tmp_path / "spend.json"))
    monkeypatch.setenv("CYBERNETIC_SKIP_LIVE_DECISIONS", "1")
    monkeypatch.delenv("CYBERNETIC_LIVE_CALLS", raising=False)
    monkeypatch.delenv("CYBERNETIC_LAYA_LIVE", raising=False)
    monkeypatch.delenv("CYBERNETIC_SPEND_CONTINUE", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    yield
    reset_guard_cache()


@pytest.fixture(autouse=True)
def in_memory_db(tmp_path):
    """Use a temporary DB for every test."""
    test_db = tmp_path / "test.db"
    with patch.object(db_module, "DB_PATH", test_db), \
         patch.object(db_module, "DB_DIR", tmp_path):
        db_module.init_db()
        yield test_db
