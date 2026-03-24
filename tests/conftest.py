"""Shared test fixtures."""
import pytest
from unittest.mock import patch
from cybernetic.storage import db as db_module


@pytest.fixture(autouse=True)
def in_memory_db(tmp_path):
    """Use a temporary DB for every test."""
    test_db = tmp_path / "test.db"
    with patch.object(db_module, "DB_PATH", test_db), \
         patch.object(db_module, "DB_DIR", tmp_path):
        db_module.init_db()
        yield test_db
