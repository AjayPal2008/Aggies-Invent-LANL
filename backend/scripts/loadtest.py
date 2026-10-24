"""Peak-traffic load test.

Simulates many employees using the platform at once, each signed in as a different person,
clicking through realistic pages with pauses in between (think time), plus a share of managers.

    python -m scripts.loadtest --users 1000 --seconds 60 --url http://localhost:8000

Tokens are minted with JWT_SECRET (default dev secret) so the test doesn't hammer the login endpoint.
Run it against a stack loaded with the 20,000-employee dataset:
    python -m scripts.make_sample_data --staff 20000 --out data/scale20k
    DATA_DIR=/app/backend/data/scale20k docker compose up -d --build
"""
from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import httpx
import jwt

HIRE_FLOW = [  # (weight, method, path builder, body builder, label)
    (5, "GET", lambda s: "/api/me/dashboard", None, "dashboard"),
    (3, "GET", lambda s: "/api/me/assignments?sort=due_date", None, "assignments"),
    (2, "GET", lambda s: "/api/me/calendar", None, "calendar"),
    (2, "GET", lambda s: "/api/trainings", None, "catalog"),
    (2, "GET", lambda s: "/api/me/role-plan", None, "role plan"),
    (2, "POST", lambda s: f"/api/me/trainings/{random.choice(s['codes'])}/practice", lambda s: {"count": 5}, "practice (AI)"),
    (1, "POST", lambda s: f"/api/me/modules/{random.choice(s['modules'])}/lesson", lambda s: {"modality": random.choice(["video", "text"])}, "module lesson (AI)"),
    (4, "POST", lambda s: "/api/me/answer", lambda s: {"training_code": random.choice(s["codes"]), "skill": random.choice(s["skills"]),
                                                       "correct": random.random() < 0.7, "modality": "quiz"}, "answer"),
]
MANAGER_FLOW = [
    (3, "GET", lambda s: "/api/manager/team?page=0&page_size=50", None, "mgr team"),
    (2, "GET", lambda s: "/api/manager/overview", None, "mgr overview"),
    (1, "GET", lambda s: "/api/manager/org", None, "mgr org"),
    (1, "GET", lambda s: "/api/manager/retraining", None, "mgr retraining"),
]


def token(secret: str, emp_id: int) -> str:
    return jwt.encode({"sub": str(emp_id), "role": "x", "exp": datetime.now(timezone.utc) + timedelta(hours=2)}, secret, algorithm="HS256")


async def user(client, secret, emp_id, flow, shared, deadline, stats, think):
    headers = {"Authorization": f"Bearer {token(secret, emp_id)}", "Accept-Encoding": "gzip"}
    weights = [w for w, *_ in flow]
    await asyncio.sleep(random.random() * think[1])  # stagger arrivals
    while time.monotonic() < deadline:
        _, method, path, body, label = random.choices(flow, weights)[0]
        t0 = time.perf_counter()
        try:
            r = await client.request(method, path(shared), json=body(shared) if body else None, headers=headers)
            code = r.status_code
        except httpx.HTTPError as exc:
            code = type(exc).__name__
        stats["lat"][label].append((time.perf_counter() - t0) * 1000)
        stats["codes"][code] += 1
        await asyncio.sleep(random.uniform(*think))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--users", type=int, default=500)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--managers", type=float, default=0.05, help="share of users who are managers")
    ap.add_argument("--think", type=float, nargs=2, default=[2.0, 6.0], help="min/max seconds between clicks")
    ap.add_argument("--employees", type=int, default=20000)
    ap.add_argument("--secret", default="change-me-in-production-use-a-long-random-string")
    a = ap.parse_args()

    limits = httpx.Limits(max_connections=a.users + 50, max_keepalive_connections=a.users + 50)
    async with httpx.AsyncClient(base_url=a.url, timeout=60, limits=limits) as client:
        h = {"Authorization": f"Bearer {token(a.secret, 2)}"}
        catalog = (await client.get("/api/trainings", headers=h)).json()
        codes = [t["code"] for t in catalog]
        skills = sorted({s for t in catalog for s in t["skills"]}) or ["safety"]
        doc = next(t["code"] for t in catalog if t["from_document"])
        modules = [m["id"] for m in (await client.get(f"/api/me/trainings/{doc}/modules", headers=h)).json()["modules"]]
        shared = {"codes": codes, "skills": skills, "modules": modules}
        managers = [2, 3, 4, 5, 6, 7]
        stats = {"lat": defaultdict(list), "codes": Counter()}
        deadline = time.monotonic() + a.seconds
        tasks = []
        for i in range(a.users):
            if random.random() < a.managers:
                tasks.append(user(client, a.secret, random.choice(managers), MANAGER_FLOW, shared, deadline, stats, a.think))
            else:
                tasks.append(user(client, a.secret, random.randint(8, a.employees), HIRE_FLOW, shared, deadline, stats, a.think))
        t0 = time.monotonic()
        await asyncio.gather(*tasks)
        elapsed = time.monotonic() - t0

    allv = [v for vals in stats["lat"].values() for v in vals]
    pct = lambda vals, p: sorted(vals)[min(len(vals) - 1, int(len(vals) * p))] if vals else 0  # noqa: E731
    total = sum(stats["codes"].values())
    ok = sum(n for c, n in stats["codes"].items() if isinstance(c, int) and c < 400)
    print(f"\n{a.users} concurrent users for {elapsed:.0f}s, think time {a.think[0]}-{a.think[1]}s")
    print(f"requests: {total}  ({total / elapsed:.0f}/s)   success: {ok / total:.2%}   status: {dict(stats['codes'])}")
    print(f"latency overall  p50 {pct(allv, .5):.0f} ms   p95 {pct(allv, .95):.0f} ms   p99 {pct(allv, .99):.0f} ms")
    print(f"{'endpoint':22} {'count':>7} {'p50':>7} {'p95':>7} {'p99':>7}")
    for label, vals in sorted(stats["lat"].items(), key=lambda kv: -len(kv[1])):
        print(f"{label:22} {len(vals):7d} {pct(vals, .5):6.0f}ms {pct(vals, .95):6.0f}ms {pct(vals, .99):6.0f}ms")
    print(f"mean {statistics.mean(allv):.0f} ms")


if __name__ == "__main__":
    asyncio.run(main())
