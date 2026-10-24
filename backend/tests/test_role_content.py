"""Documents -> courses, role plans by entry path, video lessons, interview-style assessments."""
import io
from pathlib import Path

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample" / "documents"


def _role_course(client, manager):
    docs = client.get("/api/manager/documents?position_code=CCS-PL3", headers=manager).json()
    return next(d for d in docs if d["course"])


def test_demo_handbook_became_a_course(client, manager):
    d = _role_course(client, manager)
    assert d["pages"] >= 150 and d["status"] == "ready"
    c = d["course"]
    assert 8 <= len(c["modules"]) <= 15 and c["scenarios"] >= 6
    assert c["duration_minutes"] < d["reading_minutes"]  # shorter than reading it
    assert all(m["key_points"] for m in c["modules"])
    assert c["assessment_type"] in ("situational", "both")


def test_upload_pdf_builds_course_in_background(client, manager):
    pdf = (SAMPLE / "project_management_handbook.pdf").read_bytes()
    r = client.post("/api/manager/documents", headers=manager, files={"file": ("ops_manual.pdf", io.BytesIO(pdf), "application/pdf")},
                    data={"title": "Ops manual", "kind": "manual", "position_code": "CCS-PL3"})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    d = client.get(f"/api/manager/documents/{doc_id}", headers=manager).json()  # TestClient runs background tasks before returning
    assert d["status"] == "ready" and d["course"]["modules"]
    assert client.delete(f"/api/manager/documents/{doc_id}", headers=manager).status_code == 200


def test_rejects_unsupported_files(client, manager):
    r = client.post("/api/manager/documents", headers=manager, files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
                    data={"kind": "manual"})
    assert r.status_code == 400


def test_job_description_analysis(client, manager):
    a = client.post("/api/manager/roles/CCS-PL3/analyze", json={"apply_skills": False}, headers=manager).json()
    assert a["responsibilities"] and "risk management" in a["required_skills"] and a["min_years"] == 5
    assert a["plan"]


def test_plan_save_and_audience_rules(client, manager):
    plan = client.get("/api/manager/roles/CCS-PL3/plan", headers=manager).json()
    items = plan["items"]
    assert any(i["audience"] == "new_hire" for i in items), "culture onboarding is only for people new to LANL"
    items.append({"training_code": "PY-150", "phase": 3, "audience": "all", "required": False, "skip_if_years_at_least": 3, "reason": "test"})
    saved = client.put("/api/manager/roles/CCS-PL3/plan", json={"items": items}, headers=manager).json()
    assert saved["saved"] and any(i["training_code"] == "PY-150" for i in saved["items"])


def test_internal_promotion_skips_onboarding_and_completed(client, manager):
    team = client.get("/api/manager/team?sort=name", headers=manager).json()
    veteran = next(r for r in team if not r["is_new_hire"] and r["level"] == 2 and r["summary"]["completed"] >= 3)
    p = client.post("/api/manager/roles/CCS-PL3/preview", json={"employee_ids": [veteran["id"]]}, headers=manager).json()[0]
    assert p["entry_path"] in ("promotion", "transfer")
    by_code = {i["training_code"]: i for i in p["items"]}
    assert not by_code["ORI-101"]["include"]
    assert any(not i["include"] and i["why"].startswith("Already completed") for i in p["items"])
    as_new = client.post("/api/manager/roles/CCS-PL3/preview", json={"employee_ids": [veteran["id"]], "entry_paths": {str(veteran["id"]): "new_hire"}},
                         headers=manager).json()[0]
    assert as_new["entry_path"] == "new_hire"
    if veteran["years_experience"] >= 3:
        assert not {i["training_code"]: i for i in as_new["items"]}["PY-150"]["include"]  # experienced: can test out


def test_start_role_moves_person_and_assigns(client, manager):
    team = client.get("/api/manager/team?sort=name", headers=manager).json()
    person = next(r for r in team if r["level"] == 2 and r["position_code"] != "CCS-PL3")
    r = client.post("/api/manager/roles/CCS-PL3/start", json={"employee_ids": [person["id"]], "start_date": "2026-11-02"}, headers=manager).json()[0]
    assert r["assigned"]
    view = client.get(f"/api/manager/team/{person['id']}", headers=manager).json()
    e = view["employee"]
    assert e["position_code"] == "CCS-PL3" and e["entry_path"] == "promotion" and e["level"] == 3 and e["role_start_date"] == "2026-11-02"
    codes = {a["training"]["code"] for a in view["assignments"]}
    assert set(r["assigned"]) <= codes


def test_module_lessons_video_and_cache(client, hire, manager):
    d = _role_course(client, manager)
    hire_id = client.get("/api/auth/me", headers=hire).json()["id"]
    client.post("/api/manager/assignments", json={"employee_ids": [hire_id], "training_codes": [d["course"]["code"]]}, headers=manager)
    mods = client.get(f"/api/me/trainings/{d['course']['code']}/modules", headers=hire).json()
    m = mods["modules"][0]["id"]
    v = client.post(f"/api/me/modules/{m}/lesson", json={"modality": "video"}, headers=hire).json()
    assert v["kind"] == "video" and len(v["scenes"]) >= 4 and all(s["narration"] for s in v["scenes"]) and v["check_question"]
    again = client.post(f"/api/me/modules/{m}/lesson", json={"modality": "video"}, headers=hire).json()
    assert again.get("cached")
    text = client.post(f"/api/me/modules/{m}/lesson", json={"modality": "simulation"}, headers=hire).json()
    assert text["kind"] == "lesson" and text["sections"]
    done = client.post(f"/api/me/modules/{m}/complete", headers=hire).json()
    assert done["done"] == 1 and done["progress"] > 0
    catalog_video = client.post("/api/me/trainings/GEN-100/video", json={}, headers=hire).json()
    assert catalog_video["kind"] == "video" and catalog_video["scenes"]


def test_interview_assessment_flow(client, hire, manager):
    d = _role_course(client, manager)
    dash = client.get("/api/me/dashboard", headers=hire).json()
    a = next(x for x in dash["assignments"] if x["training"]["code"] == d["course"]["code"])
    s = client.post(f"/api/me/assignments/{a['id']}/interview", headers=hire).json()
    assert len(s["scenarios"]) == 3 and all(sc["questions"] for sc in s["scenarios"])
    assert "strong_response" not in s["scenarios"][0]  # rubric stays hidden while answering
    good = ("First I would pause the work because safety and the requirement come before the schedule. I'd talk privately with the "
            "team member to understand why, tell my supervisor, be honest with the customer, document it, and fix the root cause.")
    for sc in s["scenarios"]:
        for qi, _ in enumerate(sc["questions"]):
            files = {"audio": ("a.webm", io.BytesIO(b"fake-audio"), "audio/webm")} if qi == 0 else None
            r = client.post(f"/api/me/interviews/{s['session_id']}/responses", headers=hire, files=files,
                            data={"scenario_id": sc["id"], "question_index": qi, "mode": "audio" if files else "text",
                                  "transcript": good, "seconds_used": 60})
            assert r.status_code == 200, r.text
    res = client.post(f"/api/me/interviews/{s['session_id']}/submit", headers=hire).json()
    assert res["overall"] is not None and res["competencies"] and res["scenarios"][0]["strong_response"]
    assert client.post(f"/api/me/interviews/{s['session_id']}/submit", headers=hire).status_code == 409

    # Manager reviews, hears the recording, and overrides the score.
    listing = client.get("/api/manager/interviews", headers=manager).json()
    assert any(x["id"] == s["session_id"] for x in listing)
    detail = client.get(f"/api/manager/interviews/{s['session_id']}", headers=manager).json()
    rid = next(r["id"] for sc in detail["scenarios"] for r in sc["responses"] if r["has_audio"])
    audio = client.get(f"/api/manager/interviews/responses/{rid}/audio", headers=manager)
    assert audio.status_code == 200 and audio.content == b"fake-audio"
    rev = client.post(f"/api/manager/interviews/{s['session_id']}/review", json={"overall": 4, "notes": "Talk about escalation."},
                      headers=manager).json()
    assert rev["manager_overall"] == 4 and rev["status"] == "reviewed"
    after = client.get(f"/api/me/interviews/{s['session_id']}", headers=hire).json()
    assert after["final"] == 4 and not after["passed"] and after["assignment"]["flags"]["needs_retake"]


def test_hire_cannot_reach_role_setup(client, hire):
    assert client.get("/api/manager/documents", headers=hire).status_code == 403
    assert client.get("/api/manager/interviews", headers=hire).status_code == 403
    assert client.post("/api/manager/roles/CCS-PL3/start", json={"employee_ids": [1]}, headers=hire).status_code == 403


def test_document_file_access(client, hire, manager):
    d = _role_course(client, manager)
    assert client.get(f"/api/documents/{d['id']}/file", headers=manager).status_code == 200
    jd = next(x for x in client.get("/api/manager/documents?position_code=CCS-PL3", headers=manager).json() if x["kind"] == "job_description")
    assert client.get(f"/api/documents/{jd['id']}/file", headers=hire).status_code == 403  # not a course they're assigned


def test_assessment_types_fit_the_training(client, manager):
    cat = {t["code"]: t["assessment_type"] for t in client.get("/api/trainings", headers=manager).json()}
    # Policies, rules, safety and technical knowledge: multiple choice.
    for code in ("GEN-100", "CYB-110", "SEC-120", "HAZ-150", "RAD-101", "PY-150", "ORI-101", "EXP-140"):
        assert cat[code] == "quiz", code
    # Leading people and judgment calls: interview. Ethics: both.
    assert cat["COM-320"] == "situational" and cat["SUP-500"] == "situational" and cat["ETH-130"] == "both"
    assert sum(1 for v in cat.values() if v == "quiz") > len(cat) * 0.7


def test_manager_can_change_assessment_type(client, manager):
    r = client.patch("/api/manager/trainings/CYB-110/assessment", json={"assessment_type": "both"}, headers=manager)
    assert r.status_code == 200 and r.json()["assessment_type"] == "both"
    assert client.get("/api/trainings/CYB-110", headers=manager).json()["assessment_type"] == "both"
    assert client.patch("/api/manager/trainings/CYB-110/assessment", json={"assessment_type": "essay"}, headers=manager).status_code == 400
    client.patch("/api/manager/trainings/CYB-110/assessment", json={"assessment_type": "quiz"}, headers=manager)


def test_hire_cannot_change_assessment_type(client, hire):
    assert client.patch("/api/manager/trainings/CYB-110/assessment", json={"assessment_type": "quiz"}, headers=hire).status_code == 403


def test_document_course_quiz_uses_its_own_rules(client, hire, manager):
    d = _role_course(client, manager)
    code = d["course"]["code"]
    key_points = {k for m in d["course"]["modules"] for k in m["key_points"]}
    q = client.post(f"/api/me/trainings/{code}/practice", json={"count": 6}, headers=hire).json()["questions"]
    assert len(q) == 6
    for x in q:
        assert x["options"][x["answer_index"]] in key_points  # the right answer is a real requirement from the document
        assert len(set(x["options"])) == len(x["options"])


def test_quiz_plus_interview_needs_both_and_scores_readiness(client, hire, manager):
    d = _role_course(client, manager)
    code = d["course"]["code"]
    client.patch(f"/api/manager/trainings/{code}/assessment", json={"assessment_type": "both"}, headers=manager)
    hire_id = client.get("/api/auth/me", headers=hire).json()["id"]
    client.post("/api/manager/assignments", json={"employee_ids": [hire_id], "training_codes": [code]}, headers=manager)
    a = next(x for x in client.get("/api/me/dashboard", headers=hire).json()["assignments"] if x["training"]["code"] == code)

    # Ace the quiz: still not complete until the interview is done too.
    issued = client.post(f"/api/me/assignments/{a['id']}/assessment", headers=hire).json()
    from app.database import SessionLocal
    from app import models
    with SessionLocal() as db:
        ev = db.get(models.LearningEvent, issued["assessment_id"])
        answers = [q["answer_index"] for q in ev.payload["questions"]]
    quiz = client.post(f"/api/me/assessments/{issued['assessment_id']}/submit", json={"answers": answers}, headers=hire).json()
    assert quiz["score"] == 100 and quiz["assignment"]["status"] != "completed"

    s = client.post(f"/api/me/assignments/{a['id']}/interview", headers=hire).json()
    strong = ("First I'd pause the work, because the safety requirement comes before the schedule. I'd talk privately with the team "
              "member to understand why, involve my supervisor, be honest with the customer and stakeholders about the delay, "
              "document it per procedure, and follow up on the root cause with the team so it doesn't happen again.")
    for sc in s["scenarios"]:
        for qi, _ in enumerate(sc["questions"]):
            client.post(f"/api/me/interviews/{s['session_id']}/responses", headers=hire,
                        data={"scenario_id": sc["id"], "question_index": qi, "mode": "text", "transcript": strong, "seconds_used": 90})
    res = client.post(f"/api/me/interviews/{s['session_id']}/submit", headers=hire).json()
    assert res["readiness"] in ("ready", "ready_with_support", "not_ready")
    det = res["readiness_detail"]
    assert det["label"] and det["summary"] and det["next_steps"] and "interview" in det["inputs"]
    assert det["inputs"]["quiz_best"] == 100
    assert 0 <= res["readiness_score"] <= 100

    # A manager's low override drops readiness and reopens the training.
    rev = client.post(f"/api/manager/interviews/{s['session_id']}/review", json={"overall": 3, "notes": "Let's practice escalation."},
                      headers=manager).json()
    assert rev["readiness"] == "not_ready" and rev["readiness_detail"]["inputs"]["scored_by"] == "manager"
    after = client.get(f"/api/me/interviews/{s['session_id']}", headers=hire).json()
    assert after["readiness"] == "not_ready" and after["assignment"]["status"] != "completed"
    # And a strong override makes them ready, completing the training.
    rev = client.post(f"/api/manager/interviews/{s['session_id']}/review", json={"overall": 8.5}, headers=manager).json()
    assert rev["readiness"] == "ready"
    assert client.get(f"/api/me/interviews/{s['session_id']}", headers=hire).json()["assignment"]["status"] == "completed"
