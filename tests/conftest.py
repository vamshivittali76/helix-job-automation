"""Isolate DB to a temp file for every test."""

import pytest

import src.tracker.db as db


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "helix_test.db")
    db.init_db()
    yield tmp_path / "helix_test.db"
