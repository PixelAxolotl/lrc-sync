import sys, os
sys.path.insert(0, os.path.abspath(".."))

from unittest.mock import patch
from fastapi.testclient import TestClient
import server
import lrclib


def test_lookup_by_id_returns_full_record(monkeypatch):
    rec = {"id": 123, "trackName": "T", "artistName": "A", "syncedLyrics": "[00:01.00]hi"}
    monkeypatch.setattr(lrclib, "get_by_id", lambda rid: rec if rid == 123 else None)
    c = TestClient(server.app)
    r = c.get("/api/lookup", params={"id": 123})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 123
    assert body["syncedLyrics"] == "[00:01.00]hi"


def test_lookup_by_id_not_found(monkeypatch):
    monkeypatch.setattr(lrclib, "get_by_id", lambda rid: None)
    c = TestClient(server.app)
    r = c.get("/api/lookup", params={"id": 999})
    assert r.status_code == 404


def test_lookup_by_artist_track_duration(monkeypatch):
    rec = {"id": 456, "trackName": "T", "artistName": "A", "syncedLyrics": "x"}
    monkeypatch.setattr(lrclib, "lookup_record", lambda a, t, d: rec)
    c = TestClient(server.app)
    r = c.get("/api/lookup", params={"artist": "A", "track": "T", "duration": 100})
    assert r.status_code == 200
    assert r.json()["id"] == 456


def test_lookup_missing_params():
    c = TestClient(server.app)
    r = c.get("/api/lookup")
    assert r.status_code == 400
