import csv
import json

from app.connectors.oracle_hr import _employee


def test_overview_and_team_ranking(client, manager):
    o = client.get("/api/manager/overview", headers=manager).json()
    assert o["team_size"] > 0 and o["headcount_by_fiscal_year"]
    team = client.get("/api/manager/team?sort=performance", headers=manager).json()
    scores = [r["performance_index"] for r in team]
    assert scores == sorted(scores, reverse=True) and team[0]["rank"] == 1
    lvl1 = client.get("/api/manager/team?max_level=1", headers=manager).json()
    assert all(r["level"] <= 1 for r in lvl1)


def test_assign_and_unassign(client, manager):
    team = client.get("/api/manager/team", headers=manager).json()
    eid = team[-1]["id"]
    r = client.post("/api/manager/assignments", json={"employee_ids": [eid], "training_codes": ["MEN-140"]}, headers=manager).json()
    assert r["created"] or r["skipped"]
    view = client.get(f"/api/manager/team/{eid}", headers=manager).json()
    a = next(x for x in view["assignments"] if x["training"]["code"] == "MEN-140")
    if a["status"] != "completed":
        assert client.delete(f"/api/manager/assignments/{a['id']}", headers=manager).status_code == 200
    bad = client.post("/api/manager/assignments", json={"employee_ids": [eid], "training_codes": ["NOPE-1"]}, headers=manager)
    assert bad.status_code == 400


def test_candidates_ranked_with_requirements(client, manager):
    positions = client.get("/api/manager/positions", headers=manager).json()
    r = client.get(f"/api/manager/positions/{positions[0]['code']}/candidates", headers=manager).json()
    fits = [c["fit_score"] for c in r["candidates"]]
    assert fits == sorted(fits, reverse=True)
    q = client.get(f"/api/manager/positions/{positions[0]['code']}/candidates?qualified_only=true", headers=manager).json()
    assert all(c["meets_requirements"] for c in q["candidates"])


def test_promotions_retraining_insights_reminders(client, manager):
    assert client.get("/api/manager/promotions", headers=manager).status_code == 200
    assert isinstance(client.get("/api/manager/retraining", headers=manager).json(), list)
    heat = client.get("/api/manager/insights/heatmap", headers=manager).json()
    assert heat["rows"] and heat["skills"]
    comp = client.get("/api/manager/insights/compliance", headers=manager).json()
    assert all(0 <= c["compliance_rate"] <= 100 for c in comp)
    rem = client.post("/api/manager/reminders", json={"send": True}, headers=manager).json()
    assert rem["mode"] == "preview" and rem["sent"] == 0  # preview never sends


def test_infer_skills_saves(client, manager):
    team = client.get("/api/manager/team", headers=manager).json()
    r = client.post(f"/api/manager/team/{team[0]['id']}/infer-skills", headers=manager).json()
    assert r["saved_skills"]


def test_sync_is_idempotent(client, admin):
    before = client.get("/api/admin/connectors", headers=admin).json()
    assert all(h["ok"] for h in before["health"])
    r = client.post("/api/admin/sync", headers=admin).json()
    assert r["oracle_hr"]["created"] == 0 and r["directory"]["created"] == 0


def test_real_world_column_names_are_mapped():
    row = {"Emp_No": "Z9", "Work Email": "A.B@LANL.GOV", "Full Name": "A B", "Annual Salary": "$120,000",
           "Original Hire Date": "03/15/2024", "Reports To": "Z1", "Rating": "4.5"}
    e = _employee(row)
    assert e["employee_number"] == "Z9" and e["email"] == "a.b@lanl.gov" and e["salary"] == 120000
    assert e["hire_date"].year == 2024 and e["manager_number"] == "Z1" and e["performance_rating"] == 4.5


def test_mapping_file_and_new_training_site(client, admin, data_dir):
    (data_dir / "mapping.json").write_text(json.dumps({"trainings": {"Course #": "code", "Name of Course": "title"}}))
    with (data_dir / "trainings_nucleus.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Course #", "Name of Course", "Type", "Modality"])
        w.writerow(["NUC-900", "Reactor Physics Primer", "technical", "classroom"])
    r = client.post("/api/admin/sync?source=utrain", headers=admin)
    assert r.status_code == 200, r.text
    t = client.get("/api/trainings/NUC-900", headers=admin).json()
    assert t["source_system"] == "Nucleus" and t["delivery"] == "in_person"
    (data_dir / "mapping.json").unlink()
