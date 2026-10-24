"""End-to-end API checks with synthetic fixtures outside the real bank directory."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.main import app
from app.services.diagnostic import SessionStore, get_store


@pytest.fixture
def diagnostic(client, tmp_path, monkeypatch):
    fixture = json.loads((Path(__file__).resolve().parents[2] / "tests/fixtures/synthetic_diagnostic.json").read_text(encoding="utf-8"))
    bank, source = fixture["bank"], fixture["source"]
    path = tmp_path / "sessions.sqlite3"
    provider = lambda: (bank, source)
    store = SessionStore(path, provider)
    app.dependency_overrides[get_store] = lambda: store
    monkeypatch.setattr("backend.ai_client.generate", lambda *a, **k: pytest.fail("No live AI calls permitted"))
    monkeypatch.setattr("app.services.ai._get_client", lambda: pytest.fail("No legacy live AI permitted"))
    yield store, bank, source, path, provider
    app.dependency_overrides.pop(get_store, None)


def payload(bank, question, *, correct=True, reasoning=True):
    private = next(q for q in bank["questions"] if q["id"] == question["id"])
    return {"question_id": question["id"],
            "answer_id": private["correct_option_id"] if correct else next(o["id"] for o in private["options"] if o["id"] != private["correct_option_id"]),
            "reason_id": private["why"]["correct_option_id"] if reasoning else next(o["id"] for o in private["why"]["options"] if o["id"] != private["why"]["correct_option_id"]),
            "confidence": "guessing"}


def assert_private_absent(response):
    text = json.dumps(response)
    for key in ("correct_option_id", "correct_answer_id", "correct_reason_id", "review", "snapshot", "bank", "responses", "request_digest"):
        assert '"' + key + '":' not in text


def test_start_wrong_answer_foundation_restart_results(client, hire, diagnostic):
    store, bank, _, path, provider = diagnostic
    started = client.post("/api/diagnostic/sessions", headers=hire, json={"initial_limit": 1, "budget": 2})
    assert started.status_code == 201
    issued = started.json()
    sid = issued["session_id"]
    assert_private_absent(issued)
    assert "explanation" not in json.dumps(issued)
    response = client.post(f"/api/diagnostic/sessions/{sid}/answers", headers=hire,
                           json=payload(bank, issued["question"], correct=True, reasoning=False))
    assert response.status_code == 200
    follow = response.json()
    assert not follow["branch_complete"] and follow["feedback"] == []
    assert follow["question"]["level"] == "foundation"
    assert follow["question"]["id"] != issued["question"]["id"]
    assert "explanation" not in json.dumps(follow)
    assert client.get(f"/api/diagnostic/sessions/{sid}/results", headers=hire).status_code == 409
    # A new store object reconstructs the same pending branch from SQLite.
    app.dependency_overrides[get_store] = lambda: SessionStore(path, provider)
    restored = client.get(f"/api/diagnostic/sessions/{sid}/current", headers=hire).json()
    assert restored["question"] == follow["question"]
    result = client.post(f"/api/diagnostic/sessions/{sid}/answers", headers=hire,
                         json=payload(bank, follow["question"]))
    done = result.json()
    assert result.status_code == 200 and done["complete"] and done["question"] is None
    assert done["branch_complete"] and len(done["feedback"]) == 2
    assert_private_absent(done)
    report = client.get(f"/api/diagnostic/sessions/{sid}/results", headers=hire).json()
    assert_private_absent(report)
    tested = next(o for o in report["objectives"] if o["objective_id"] == issued["question"]["objective_id"])
    assert tested["status"] == "needs review"
    assert tested["evidence"] == {"foundation": "positive", "application": "positive", "reasoning": "incorrect", "foundation_reasoning": "positive"}
    assert report["review_priority"] and report["required_training"]
    assert any(o["status"] == "not assessed" for o in report["objectives"])
    with store.connection() as db:
        saved = json.loads(db.execute("SELECT report FROM diagnostic_sessions WHERE id=?", (sid,)).fetchone()[0])
    assert saved["questions_answered"] == 2


def test_duplicate_concurrent_submission_advances_once(client, hire, diagnostic):
    _, bank, _, _, _ = diagnostic
    issued = client.post("/api/diagnostic/sessions", headers=hire, json={"initial_limit": 2, "budget": 4}).json()
    sid = issued["session_id"]
    body = payload(bank, issued["question"])
    url = f"/api/diagnostic/sessions/{sid}/answers"
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: client.post(url, headers=hire, json=body), range(2)))
    assert all(r.status_code == 200 for r in replies)
    assert replies[0].json() == replies[1].json()
    assert client.get(f"/api/diagnostic/sessions/{sid}/current", headers=hire).json()["answered"] == 1
    changed = {**body, "confidence": "very sure"}
    assert client.post(url, headers=hire, json=changed).status_code == 409


def test_ownership_auth_and_invalid_choices(client, hire, manager, diagnostic):
    _, bank, _, _, _ = diagnostic
    assert client.post("/api/diagnostic/sessions", json={}).status_code == 401
    issued = client.post("/api/diagnostic/sessions", headers=hire, json={}).json()
    sid = issued["session_id"]
    assert client.get(f"/api/diagnostic/sessions/{sid}/current", headers=manager).status_code == 404
    assert client.get(f"/api/diagnostic/sessions/{sid}/results", headers=manager).status_code == 404
    body = payload(bank, issued["question"])
    assert client.post(f"/api/diagnostic/sessions/{sid}/answers", headers=hire, json={**body, "answer_id": "unknown"}).status_code == 409
    assert client.post(f"/api/diagnostic/sessions/{sid}/answers", headers=hire, json={**body, "confidence": "certain"}).status_code == 422
    assert client.get(f"/api/diagnostic/sessions/{sid}/current", headers=hire).json()["answered"] == 0


def test_unapproved_bank_setup_and_revoked_approval(client, hire, diagnostic):
    _, bank, _, _, _ = diagnostic
    issued = client.post("/api/diagnostic/sessions", headers=hire, json={}).json()
    for question in bank["questions"]:
        question["review"] = {"status": "pending"}
    status = client.get("/api/diagnostic/status", headers=hire).json()
    assert not status["available"] and "manually review" in status["message"]
    response = client.post("/api/diagnostic/sessions", headers=hire, json={})
    assert response.status_code == 409 and "question" not in response.json()
    assert client.get(f"/api/diagnostic/sessions/{issued['session_id']}/current", headers=hire).status_code == 409


def test_budget_coverage_nonrepetition_and_required_training_separate(client, hire, diagnostic):
    _, bank, _, _, _ = diagnostic
    current = client.post("/api/diagnostic/sessions", headers=hire, json={"initial_limit": 8, "budget": 12}).json()
    sid, seen = current["session_id"], set()
    while not current["complete"]:
        q = current["question"]
        assert q["id"] not in seen
        seen.add(q["id"])
        response = client.post(f"/api/diagnostic/sessions/{sid}/answers", headers=hire, json=payload(bank, q, correct=False))
        assert response.status_code == 200
        current = response.json()
    report = client.get(f"/api/diagnostic/sessions/{sid}/results", headers=hire).json()
    assert report["questions_answered"] == 12 and len(seen) == 12
    assert all(c["tested"] == 2 for c in report["article_coverage"].values())
    assert all(o["completion"] == "not evaluated by this diagnostic" for o in report["required_training"])
    assert any(o["status"] == "insufficient evidence" for o in report["objectives"])


def test_private_project_files_are_not_static_routes(client):
    for url in ("/Resource_File/cache/assessment/bank.json", "/backend/ai_client.py", "/tests/fixtures/synthetic_diagnostic.json"):
        assert client.get(url).status_code == 404


def test_sessions_can_live_in_the_platform_database(client, hire):
    """Default mode: sessions are stored in DATABASE_URL, shared by every worker and replica."""
    fixture = json.loads((Path(__file__).resolve().parents[2] / "tests/fixtures/synthetic_diagnostic.json").read_text(encoding="utf-8"))
    bank, source = fixture["bank"], fixture["source"]
    store = SessionStore(None, lambda: (bank, source))
    assert store.path is None
    app.dependency_overrides[get_store] = lambda: store
    try:
        issued = client.post("/api/diagnostic/sessions", headers=hire, json={"initial_limit": 1, "budget": 2}).json()
        sid = issued["session_id"]
        r = client.post(f"/api/diagnostic/sessions/{sid}/answers", headers=hire, json=payload(bank, issued["question"]))
        assert r.status_code == 200
        # A fresh store object (another worker) sees the same session.
        other = SessionStore(None, lambda: (bank, source))
        app.dependency_overrides[get_store] = lambda: other
        assert client.get(f"/api/diagnostic/sessions/{sid}/current", headers=hire).json()["answered"] == 1
        from app.database import engine
        from sqlalchemy import text
        with engine.connect() as c:
            assert c.execute(text("SELECT COUNT(*) FROM diagnostic_sessions WHERE id=:i"), {"i": sid}).scalar() == 1
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_randomized_ten_budget_persists_history(client, hire, diagnostic):
    store, bank, source, path, provider = diagnostic
    issued = client.post("/api/diagnostic/sessions", headers=hire,
                         json={"initial_limit": 10, "budget": 10, "randomize": True}).json()
    sid = issued["session_id"]
    with store.connection() as db:
        snapshot = json.loads(db.execute("SELECT snapshot FROM diagnostic_sessions WHERE id=?", (sid,)).fetchone()["snapshot"])
        assert snapshot["random_seed"] is not None
    seen = []
    while not issued["complete"]:
        question = issued["question"]
        assert question["id"] not in seen
        seen.append(question["id"])
        app.dependency_overrides[get_store] = lambda: SessionStore(path, provider)
        restored = client.get(f"/api/diagnostic/sessions/{sid}/current", headers=hire).json()
        assert restored["question"] == question
        response = client.post(f"/api/diagnostic/sessions/{sid}/answers", headers=hire,
                               json=payload(bank, question, correct=False))
        assert response.status_code == 200
        issued = response.json()
    report = client.get(f"/api/diagnostic/sessions/{sid}/results", headers=hire).json()
    assert len(seen) <= 10
    assert len(report["answer_history"]) == len(seen)
    assert report["answers_correct"] == 0
    assert all(not row["answer_correct"] for row in report["answer_history"])
    assert_private_absent(report)


def test_overview_latest_completed_owner_scoped_and_persistent(client, hire, manager, diagnostic):
    store, bank, source, path, provider = diagnostic
    url = "/api/diagnostic/latest-completed"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=hire).json() == {"available": False, "report": None}
    issued = client.post("/api/diagnostic/sessions", headers=hire,
                         json={"initial_limit": 1, "budget": 2}).json()
    sid = issued["session_id"]
    follow = client.post(f"/api/diagnostic/sessions/{sid}/answers", headers=hire,
                         json=payload(bank, issued["question"], correct=False)).json()
    assert client.get(url, headers=hire).json()["available"] is False
    done = client.post(f"/api/diagnostic/sessions/{sid}/answers", headers=hire,
                       json=payload(bank, follow["question"])).json()
    assert done["complete"]
    # An unfinished newer session must not displace completed evidence.
    client.post("/api/diagnostic/sessions", headers=hire, json={"initial_limit": 1, "budget": 2})
    # Historical dashboard evidence remains available even if the current bank changes.
    app.dependency_overrides[get_store] = lambda: SessionStore(path, lambda: (_ for _ in ()).throw(ValueError("bank unavailable")))
    result = client.get(url, headers=hire).json()
    assert result["available"]
    report = result["report"]
    assert report["session_id"] == sid
    assert report["questions_answered"] == 2
    assert report["answers_correct"] == 1
    assert report["review_priority"]
    assert report["objectives"]
    assert_private_absent(result)
    assert client.get(url, headers=manager).json()["available"] is False
