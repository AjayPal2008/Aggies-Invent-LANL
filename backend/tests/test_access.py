def test_login_rejects_bad_password(client):
    r = client.post("/api/auth/login", json={"email": "hire@lanl.gov", "password": "wrong"})
    assert r.status_code == 401


def test_login_rejects_non_company_email(client):
    r = client.post("/api/auth/login", json={"email": "someone@gmail.com", "password": "demo1234"})
    assert r.status_code == 401


def test_requires_sign_in(client):
    assert client.get("/api/me/dashboard").status_code == 401


def test_hire_cannot_open_manager_routes(client, hire):
    for path in ["/api/manager/overview", "/api/manager/team", "/api/manager/positions", "/api/manager/promotions"]:
        assert client.get(path, headers=hire).status_code == 403, path


def test_manager_cannot_run_admin_routes(client, manager):
    assert client.post("/api/admin/sync", headers=manager).status_code == 403


def test_manager_hire_view_is_read_only_and_scoped(client, manager):
    team = client.get("/api/manager/team", headers=manager).json()
    view = client.get(f"/api/manager/team/{team[0]['id']}", headers=manager).json()
    assert view["read_only"] is True
    # Someone outside the manager's org is not visible.
    admin_id = client.get("/api/auth/me", headers=manager).json()["manager_id"]
    assert client.get(f"/api/manager/team/{admin_id}", headers=manager).status_code == 404


def test_hire_sees_no_salary(client, hire):
    me = client.get("/api/me/dashboard", headers=hire).json()["employee"]
    assert "salary" not in me and "performance_rating" not in me
