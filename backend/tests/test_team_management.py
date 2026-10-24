from sqlalchemy import event

from app.database import engine


class QueryCounter:
    def __init__(self):
        self.n = 0

    def __enter__(self):
        event.listen(engine, "before_cursor_execute", self._count)
        return self

    def __exit__(self, *exc):
        event.remove(engine, "before_cursor_execute", self._count)

    def _count(self, *args, **kwargs):
        self.n += 1


def test_demo_manager_has_a_lanl_sized_org(client, manager):
    org = client.get("/api/manager/org", headers=manager).json()
    assert 80 <= org["team_size"] <= 95
    assert org["groups"], "large org should have sub-teams under team leads"
    assert sum(g["size"] for g in org["groups"]) <= org["team_size"]


def test_team_pages_use_constant_queries(client, manager):
    """Pages must not run one query per person (that's what makes big teams slow on hosted Postgres)."""
    for path in ["/api/manager/team", "/api/manager/overview", "/api/manager/promotions", "/api/manager/retraining",
                 "/api/manager/insights/heatmap", "/api/manager/org"]:
        with QueryCounter() as q:
            assert client.get(path, headers=manager).status_code == 200
        assert q.n < 30, f"{path} ran {q.n} queries"


def test_search_sub_team_and_direct_filters(client, manager):
    everyone = client.get("/api/manager/team", headers=manager).json()
    lead = client.get("/api/manager/org", headers=manager).json()["groups"][0]
    sub = client.get(f"/api/manager/team?under={lead['lead']['id']}", headers=manager).json()
    assert len(sub) == lead["size"] and len(sub) < len(everyone)
    assert all(r["id"] == lead["lead"]["id"] or r["sub_team"]["id"] == lead["lead"]["id"] for r in sub)
    direct = client.get("/api/manager/team?direct_only=true", headers=manager).json()
    assert all(r["sub_team"] is None for r in direct)
    name = everyone[5]["name"].split()[-1]
    found = client.get(f"/api/manager/team?q={name}", headers=manager).json()
    assert found and all(name.lower() in (r["name"] + r["email"] + r["job_title"]).lower() for r in found)


def test_bulk_actions(client, manager):
    team = client.get("/api/manager/team?sort=name", headers=manager).json()
    ids = [r["id"] for r in team[:20]]
    r = client.post("/api/manager/assignments", json={"employee_ids": ids, "training_codes": ["MEN-140"]}, headers=manager).json()
    assert len(r["created"]) + len(r["skipped"]) == 20
    moved = client.post("/api/manager/assignments/bulk-due-date",
                        json={"employee_ids": ids, "training_codes": ["MEN-140"], "due_date": "2030-01-15"}, headers=manager).json()
    assert moved["changed"] >= 1
    view = client.get(f"/api/manager/team/{ids[0]}", headers=manager).json()
    a = next(x for x in view["assignments"] if x["training"]["code"] == "MEN-140")
    if a["status"] != "completed":
        assert a["due_date"] == "2030-01-15"
        one = client.patch(f"/api/manager/assignments/{a['id']}", json={"due_date": "2030-02-01"}, headers=manager).json()
        assert one["due_date"] == "2030-02-01"
    removed = client.post("/api/manager/assignments/bulk-remove", json={"employee_ids": ids, "training_codes": ["MEN-140"]}, headers=manager).json()
    assert removed["removed"] >= 1
    role = client.post("/api/manager/assignments/role-requirements", json={"employee_ids": ids}, headers=manager)
    assert role.status_code == 200
    again = client.post("/api/manager/assignments/role-requirements", json={"employee_ids": ids}, headers=manager).json()
    assert again["created"] == []  # nothing left missing


def test_bulk_actions_refuse_people_outside_the_org(client, manager):
    outsider = client.get("/api/auth/me", headers=manager).json()["manager_id"]
    r = client.post("/api/manager/assignments/bulk-due-date", json={"employee_ids": [outsider], "due_date": "2030-01-01"}, headers=manager)
    assert r.status_code == 404


def test_export_csv(client, manager):
    r = client.get("/api/manager/team.csv", headers=manager)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    org = client.get("/api/manager/org", headers=manager).json()
    assert lines[0].startswith("employee_number,name") and len(lines) == org["team_size"] + 1


def test_hire_cannot_use_team_management(client, hire):
    assert client.get("/api/manager/org", headers=hire).status_code == 403
    assert client.get("/api/manager/team.csv", headers=hire).status_code == 403
    assert client.post("/api/manager/assignments/bulk-remove", json={"employee_ids": [1], "training_codes": ["X"]}, headers=hire).status_code == 403
