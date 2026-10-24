"""Peak-traffic safeguards: rate limits, AI guard, busy database, caching, staggering, health."""
from datetime import date, timedelta

import pytest
from sqlalchemy import exc as sa_exc

from app.config import settings
from app.routers.manager import staggered_due
from app.safeguards import AIGuard, limiter


@pytest.fixture
def tight_limits(monkeypatch):
    limiter.reset()
    monkeypatch.setattr(settings, "rate_limit_ai_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 3)
    yield
    limiter.reset()


def test_ai_generation_is_rate_limited_per_user(client, hire, tight_limits):
    codes = [client.post("/api/me/trainings/GEN-100/practice", json={"count": 3}, headers=hire).status_code for _ in range(3)]
    assert codes[:2] == [200, 200] and codes[2] == 429
    r = client.post("/api/me/trainings/GEN-100/practice", json={"count": 3}, headers=hire)
    assert r.headers.get("Retry-After")
    assert client.get("/api/me/dashboard", headers=hire).status_code == 200  # normal browsing still works


def test_login_attempts_are_limited_per_account(client, tight_limits):
    codes = [client.post("/api/auth/login", json={"email": "hire@lanl.gov", "password": "wrong"}).status_code for _ in range(4)]
    assert codes[:3] == [401, 401, 401] and codes[3] == 429
    # Other people on the same network can still sign in.
    assert client.post("/api/auth/login", json={"email": "manager@lanl.gov", "password": "demo1234"}).status_code == 200


def test_every_demo_account_signs_in(client):
    limiter.reset()
    homes = {}
    for email in ("hire@lanl.gov", "manager@lanl.gov", "admin@lanl.gov", "  Manager@LANL.gov "):
        r = client.post("/api/auth/login", json={"email": email, "password": "demo1234"})
        assert r.status_code == 200, (email, r.text)
        homes[email.strip().lower()] = r.json()["home"]
        me = client.get("/api/auth/me", headers={"Authorization": "Bearer " + r.json()["token"]})
        assert me.status_code == 200
    assert homes == {"hire@lanl.gov": "/hire/", "manager@lanl.gov": "/manager/", "admin@lanl.gov": "/manager/"}


def test_ai_circuit_breaker_opens_after_failures(monkeypatch):
    monkeypatch.setattr(settings, "ai_breaker_failures", 3)
    g = AIGuard()
    for _ in range(3):
        assert g.acquire()
        g.release(False)
    assert not g.acquire()  # breaker open: callers get offline content right away
    g.open_until = 0
    assert g.acquire()
    g.release(True)


def test_ai_guard_sheds_when_saturated(monkeypatch):
    monkeypatch.setattr(settings, "ai_max_concurrent", 1)
    monkeypatch.setattr(settings, "ai_queue_wait_seconds", 0.05)
    g = AIGuard()
    assert g.acquire()
    assert not g.acquire()  # second caller doesn't wait in a pile-up
    g.release(True)


def test_busy_database_returns_retryable_503(client):
    from app.main import app

    def boom():
        raise sa_exc.TimeoutError("QueuePool limit reached")

    app.add_api_route("/api/test-db-busy", boom)
    r = client.get("/api/test-db-busy")
    assert r.status_code == 503 and r.headers["Retry-After"] == "5"


def test_shared_content_cache(client, hire):
    limiter.reset()
    first = client.post("/api/me/trainings/HAZ-150/video", json={}, headers=hire).json()
    second = client.post("/api/me/trainings/HAZ-150/video", json={}, headers=hire).json()
    # Offline content isn't pinned (so AI is retried once it's available); with AI on, the second call is a cache hit.
    assert first["scenes"] and second["scenes"]


def test_staggered_due_dates():
    deadline = date.today() + timedelta(days=60)
    dates = [staggered_due(deadline, i, 10, 4) for i in range(10)]
    assert dates == sorted(dates) and dates[-1] == deadline and dates[0] == deadline - timedelta(days=28)
    assert len(set(dates)) > 5
    soon = date.today() + timedelta(days=3)
    assert all(d >= date.today() + timedelta(days=7) for d in (staggered_due(soon, i, 5, 2) for i in range(5)))
    assert staggered_due(deadline, 0, 1, 4) == deadline


def test_bulk_assign_staggers(client, manager):
    limiter.reset()
    team = client.get("/api/manager/team?sort=name", headers=manager).json()[:12]
    deadline = (date.today() + timedelta(days=45)).isoformat()
    client.post("/api/manager/assignments", json={"employee_ids": [r["id"] for r in team], "training_codes": ["COM-320"],
                                                  "due_date": deadline, "stagger_weeks": 2}, headers=manager)
    dues = set()
    for r in team:
        a = next((x for x in client.get(f"/api/manager/team/{r['id']}", headers=manager).json()["assignments"]
                  if x["training"]["code"] == "COM-320" and x["status"] != "completed"), None)
        if a:
            dues.add(a["due_date"])
    assert len(dues) > 3 and max(dues) == deadline


def test_health_ready_and_metrics(client, admin, manager):
    limiter.reset()
    assert client.get("/api/health").json()["ok"]
    assert client.get("/api/ready").json()["ready"]
    m = client.get("/api/admin/metrics", headers=admin).json()
    assert m["requests"] > 0 and "routes" in m and "ai" in m
    assert client.get("/api/admin/metrics", headers=manager).status_code == 403


def test_responses_are_compressed(client, manager):
    limiter.reset()
    r = client.get("/api/manager/team", headers={**manager, "Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
