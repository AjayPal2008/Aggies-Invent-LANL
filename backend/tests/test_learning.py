from datetime import date, datetime, timedelta

from app import models
from app.services import adaptive


def test_bkt_moves_toward_evidence():
    p = 0.2
    up = adaptive.bkt_update(p, True)
    down = adaptive.bkt_update(p, False)
    assert up > p and down < up
    for _ in range(10):
        p = adaptive.bkt_update(p, True)
    assert p > 0.9


def _assignment(score, validity=12):
    t = models.Training(code="X", title="X", validity_months=validity, skills=[])
    a = models.Assignment(best_score=score, completed_at=datetime.utcnow())
    adaptive.schedule_retraining(a, t)
    return a


def test_retraining_cycle_depends_on_score():
    failed, shaky, strong = _assignment(60), _assignment(85), _assignment(95)
    assert failed.needs_retake and failed.next_retraining <= date.today() + timedelta(days=14)
    assert not shaky.needs_retake and shaky.next_retraining < shaky.expires_at
    assert strong.next_retraining == strong.expires_at


def test_dashboard_has_path_gaps_and_profile(client, hire):
    d = client.get("/api/me/dashboard", headers=hire).json()
    assert d["assignments"] and d["path"] and "modality" in d["profile"]
    assert d["path"][0]["reasons"]  # every step explains itself
    assert d["buckets"]["overdue"], "demo hire should have an overdue item"


def test_starts_introductory_then_adapts(client, hire):
    lesson = client.post("/api/me/trainings/ML-250/lesson", json={}, headers=hire).json()
    assert lesson["difficulty"] == "intro"
    assert {s["kind"] for s in lesson["sections"]} >= {"text", "visual", "simulation"}
    for _ in range(6):
        r = client.post("/api/me/answer", json={"training_code": "ML-250", "skill": "machine learning", "correct": True}, headers=hire).json()
    assert r["mastery"] > 0.9
    assert r["pacing"]["pace"] == "fast"


def test_lesson_respects_overrides(client, hire):
    lesson = client.post("/api/me/trainings/PY-150/lesson", json={"modality": "exercise", "difficulty": "advanced", "request": "use an analogy"},
                         headers=hire).json()
    assert lesson["modality"] == "exercise" and lesson["difficulty"] == "advanced"


def test_assessment_hides_answers_and_grades(client, hire):
    d = client.get("/api/me/dashboard", headers=hire).json()
    a = next(x for x in d["assignments"] if x["training"]["code"] == "PY-150")
    issued = client.post(f"/api/me/assignments/{a['id']}/assessment", headers=hire).json()
    assert all("answer_index" not in q for q in issued["questions"])
    r = client.post(f"/api/me/assessments/{issued['assessment_id']}/submit", json={"answers": [0] * len(issued["questions"])}, headers=hire).json()
    assert 0 <= r["score"] <= 100 and len(r["review"]) == len(issued["questions"])
    again = client.post(f"/api/me/assessments/{issued['assessment_id']}/submit", json={"answers": [0] * len(issued["questions"])}, headers=hire)
    assert again.status_code == 409


def test_calendar_and_registration(client, hire):
    events = client.get("/api/me/calendar", headers=hire).json()
    assert any(e["type"] == "due" for e in events)


def test_practice_and_tutor_work_offline(client, hire):
    q = client.post("/api/me/trainings/HPC-101/practice", json={"count": 4}, headers=hire).json()
    assert len(q["questions"]) == 4 and q["generated_by"] == "offline"
    t = client.post("/api/me/tutor", json={"message": "What is Slurm?", "training_code": "HPC-101"}, headers=hire).json()
    assert t["reply"]


def test_filters_and_sort(client, hire):
    items = client.get("/api/me/assignments?category=compliance&sort=due_date", headers=hire).json()
    assert items and all(i["training"]["category"] == "compliance" for i in items)
    dues = [i["due_date"] for i in items if i["due_date"]]
    assert dues == sorted(dues)
