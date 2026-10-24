> Upstream reference from origin/main at cf16ec0. Describes the colleague's original system, not verified capabilities or deployment guarantees of this consolidation. Root README.md is authoritative; no .env files are loaded.

# Scalability and reliability

**Requirement:** the platform must stay fast and available for LANL's 20,000+ employees, including peak periods (annual retraining deadlines, new-hire and summer-student waves), and degrade gracefully instead of crashing if load exceeds capacity.

**Short answer:** it's designed to run as several identical, stateless app servers behind a load balancer, with heavy work isolated, cached and rate-limited. We load-tested it with a 20,000-employee dataset: **1,000 people using it at the same moment** (about 5% of the Lab, several times the expected peak) got **99.97% success with 95% of employee requests answered in under 16 ms**, on a single laptop. At 2,000 simultaneous users it slowed down but **never crashed or lost data**, and adding servers is the fix.

## 1. How much traffic to plan for

| Scenario | Assumption | Simultaneous users |
| --- | --- | --- |
| Normal day | 5% of 20,000 log in, spread over 8 hours, 20-minute sessions | ~40 |
| Annual retraining deadline day | 5,000 people (25%) on one day, 15% of them in the peak hour, 30-minute sessions | ~375 |
| New-hire / summer-student wave | Orientation for 500 people in one room at once | ~500 |
| **Design target** | Everyone above at once, with headroom | **1,000** |
| Stress test | Twice the target | 2,000 |

A user clicking every 2–6 seconds generates about 0.2–0.25 requests per second, so 1,000 simultaneous users is roughly 220 requests per second.

## 2. Architecture

```
            browsers (20,000+ employees)
                       │  HTTPS
              ┌────────▼────────┐  static files, gzip, per-IP limits,
              │  nginx (LB)     │  health-aware routing, "busy" page
              └──┬──────────┬───┘
   employee &    │          │  heavy manager reports
   manager API   │          │  (bulkhead)
        ┌────────▼───┐  ┌───▼─────────┐
        │ app × N    │  │ reports × M │   identical stateless FastAPI containers,
        │ (2 workers │  │ (2 workers  │   each with its own connection pool,
        │  each)     │  │  each)      │   rate limits, AI guard and caches
        └─────┬──────┘  └──────┬──────┘
              └───────┬────────┘
              ┌───────▼────────┐        ┌──────────────┐
              │  PostgreSQL    │        │ Claude API   │  optional; offline
              │ (HA in prod)   │        │ (AI content) │  fallback always on
              └────────────────┘        └──────────────┘
```

Run it locally exactly like this: `docker compose up --build` (nginx + 2 app containers + 1 reports container + PostgreSQL). Scale with `APP_REPLICAS=4 docker compose up -d`.

## 3. Safeguards, and what happens when things go wrong

| If… | What the platform does | Where |
| --- | --- | --- |
| **Traffic spikes** (deadline day) | Load is spread across N app containers; add containers to add capacity. Each worker accepts up to 400 requests at once, then answers "busy" (503) instead of collapsing. | `docker-compose.yml`, uvicorn `--limit-concurrency` |
| **A server crashes** | nginx stops sending it traffic after 3 failures and retries safe requests on another; Docker restarts it (`restart: unless-stopped`); health checks (`/api/ready`) keep it out until it's ready. Logins survive because sessions are signed tokens, not server memory. | `deploy/nginx.conf.template`, `/api/ready` |
| **The site slows down** | Browsers see a small "Lots of people are online right now. Retrying…" banner and retry with exponential backoff and jitter (honoring `Retry-After`), so thousands of browsers don't retry in lockstep. | `shared/api.js` |
| **The database is saturated or restarting** | Connection pools are bounded (`DB_POOL_SIZE`, `DB_POOL_TIMEOUT`), dead connections are detected (`pool_pre_ping`), and a saturated pool returns a retryable 503 in seconds instead of hanging. | `app/database.py`, `app/main.py` |
| **Managers run huge reports** | Heavy roll-ups (orgs of thousands) run on separate **reports** containers (bulkhead), so they can never slow employees down. Builds are single-flight (one computes, others wait for it), capped per worker, cached (30 s; 5 min for orgs over 500 people) and fail fast when busy. | nginx `reports` upstream, `routers/manager.py` |
| **Thousands take the same training** | Generated lessons, videos and practice sets are stored per training, style and level and shared. 20,000 people taking General Employee Training cost a few dozen AI generations, not 20,000. | `ContentCache`, `LessonCache` |
| **The AI service is slow, down or rate-limited** | At most 8 AI calls in flight per worker; extra requests get built-in offline content immediately instead of queueing. After 5 consecutive failures a circuit breaker stops calling the AI for 60 seconds. The platform never depends on the AI being up. | `app/safeguards.py` (AIGuard), `services/ai.py` |
| **Someone floods or scripts the site** | Per-user limits (240 requests/min, 20 AI generations/min), per-account sign-in limits (10/min) against password guessing, plus a generous per-IP ceiling at nginx (many LANL users can share one proxy IP). | `app/safeguards.py`, nginx |
| **Huge uploads** (200+ page manuals) | 60 MB cap; text extraction happens once; course builds run in the background, two at a time per worker, so a burst of uploads queues instead of starving the server. | `routers/content.py`, `services/documents.py` |
| **A deploy goes out mid-day** | Code files are served with `no-cache` and versioned URLs, so browsers pick up the new version immediately; containers roll one at a time behind health checks. | nginx, `?v=` on assets |
| **Everyone's deadline is the same day** | Managers can spread due dates over 1–4 weeks ending at the real deadline; annual retraining is already staggered because each person's next date follows their own completion date. | "Spread due dates" in assign / change-due-date |

Other built-in efficiency: pages about a team load everyone's data in about a dozen bulk queries regardless of team size (a test fails if that regresses), responses are gzip-compressed (JSON and JS shrink 70–85%), the training catalog is cached for 60 seconds, and nginx serves the dashboards' static files so app workers only handle API calls.

## 4. Load test results

Environment: one MacBook (10 CPU cores shared by Docker **and** the load generator), Docker Desktop, PostgreSQL 16, nginx, 4 app containers and 1 reports container, 2 workers each. Dataset: **20,092 employees, 152,075 training records**, a 181-page handbook course. Each simulated user is a different employee, clicking every 2–6 seconds through the dashboard, trainings, calendar, catalog, role plan, video lessons, practice questions and answers; 3% are managers loading team reports. Command: `python -m scripts.loadtest --users 1000 --seconds 60`.

| Simultaneous users | Requests/s | Success | Employee pages p50 / p95 / p99 |
| --- | --- | --- | --- |
| 200 | 42 | 100% | 8 / 120 / 190 ms (before the bulkhead) |
| 1,000, employees only | 217 | 100% | 7 / 12 / 18 ms |
| **1,000, with managers (final build)** | **223** | **99.97%** | **9 / 15 / 26 ms** |
| 2,000 (stress, 2× target) | ~270 across two generators | 99.9% | slows to seconds when the laptop's CPUs are saturated; no crashes, no data loss |

The only failures at 1,000 users were 5 deliberate "reports busy, retry" responses for test managers with **3,000–4,000-person orgs**. Realistic teams of 80–90 people load in about 20–50 ms.

Load testing found and fixed real problems before they could reach users. Each is now covered by a test or a design rule:
- one query per person on team pages (348 → about 11 per page)
- a quadratic loop in org roll-ups (60 s → under 0.5 s)
- a cache stampede when many managers opened the same report at once
- heavy reports starving employee requests (fixed by the bulkhead)
- a race when two workers generated the same lesson at the same time
- a 93-second import of 2,000 employees (now 2 s; 20,000 employees in under a minute)

## 5. Production sizing (recommendation)

| Component | Start with | Scale when |
| --- | --- | --- |
| App containers | 3 × (2 vCPU, 2 GB), 2–4 workers each, across 2 availability zones or racks | CPU > 60% sustained or p95 > 300 ms → add containers (autoscale) |
| Reports containers | 1–2 × (2 vCPU, 4 GB) | Report p95 > 5 s |
| PostgreSQL | Managed/HA primary (4 vCPU, 16 GB) + standby, daily backups + point-in-time recovery | Read replica for reports at very large scale |
| Load balancer | nginx pair, or the platform's LB (AWS ALB, F5 on-prem) | — |
| Shared cache / limits | Redis (for rate limits and report caches shared across servers) | Once there's more than one host |
| File storage | Object storage (S3-compatible) for uploaded manuals and interview recordings | From the first production deploy |
| AI | Anthropic API with the built-in concurrency cap and offline fallback | Raise `AI_MAX_CONCURRENT` with the account's rate limits |

Connection budget: workers × containers × (pool + overflow) must stay under PostgreSQL's `max_connections` (the Docker stack uses 10 + 20 per worker and `max_connections=300`); use PgBouncer beyond that.

Availability targets: 99.9% during business hours; recovery point objective (RPO) of 15 minutes or less with point-in-time recovery; recovery time objective (RTO) under 1 hour by restoring to the standby.

## 6. Known limits and next steps

- **Shared counters across hosts:** rate limits and report caches are per worker today. On a multi-host fleet, move them to Redis (same interface in `app/safeguards.py`). nginx's per-IP limit already applies globally on one host.
- **Background jobs:** course builds run in-process with a concurrency cap. At larger scale, move them to a job queue (RQ/Celery or the cloud's equivalent) so builds survive restarts.
- **Division-level roll-ups:** orgs of thousands take about 2–10 s to compute when the cache is cold. Precomputing them every few minutes, or using SQL aggregates, would make them instant.
- **Migrations:** `init_db` adds new columns automatically for the prototype; use Alembic for production schema changes.
- **Sign-in:** replace demo passwords with LANL SSO (SAML/OIDC) in `app/auth.py`.

## 7. Try it

```bash
# 20,000-employee dataset and the full stack
cd backend && ../.venv/bin/python -m scripts.make_sample_data --staff 20000 --out data/scale20k && cd ..
APP_REPLICAS=4 NGINX_IP_RATE=5000r/s DATA_DIR=/app/backend/data/scale20k docker compose up -d --build
# 1,000 simultaneous users for a minute (raise the per-IP limit above, since the test runs from one machine)
cd backend && ../.venv/bin/python -m scripts.loadtest --users 1000 --seconds 60
# live numbers per worker (sign in as admin first)
curl -H "Authorization: Bearer <admin token>" localhost:8000/api/admin/metrics
```
