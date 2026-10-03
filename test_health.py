"""Regression test: GET /health should work like /api/health (generic healthcheckers)."""
from fastapi.testclient import TestClient
import server


def test_api_health_ok():
    c = TestClient(server.app)
    r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_root_health_alias_ok():
    c = TestClient(server.app)
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
