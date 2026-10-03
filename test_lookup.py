"""Tests for GET /api/lookup retry endpoint (lookup without re-publishing)."""
from unittest.mock import patch
from fastapi.testclient import TestClient
import server


def test_lookup_found_returns_id():
    with patch("lrclib.lookup_record", return_value={"id": 38950066}):
        c = TestClient(server.app)
        r = c.get("/api/lookup", params={
            "artist": "aiko",
            "track": "あなたの花の色",
            "duration": 240,
        })
    assert r.status_code == 200
    assert r.json()["id"] == 38950066


def test_lookup_missing_returns_404():
    with patch("lrclib.lookup_record", return_value=None):
        c = TestClient(server.app)
        r = c.get("/api/lookup", params={
            "artist": "Nobody",
            "track": "Nothing",
            "duration": 1,
        })
    assert r.status_code == 404
    assert "error" in r.json()
