"""Protection for peak periods (annual retraining deadlines, new-hire waves).

  RateLimiter     per-user and per-IP request budgets, stricter for logins and AI generation
  Metrics         request counts, status codes, latency percentiles, AI usage, for /api/admin/metrics
  AIGuard         caps AI calls in flight and trips a circuit breaker when the AI service keeps failing;
                  callers then get offline content instead of piling up and timing out

These are per worker process. In the Docker stack, nginx adds a global per-IP limit in front of all
workers; for a fleet of servers, move the counters to Redis (same interface).
"""
from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse

from .config import settings

AI_PATHS = [re.compile(p) for p in (
    r"^/api/me/trainings/[^/]+/(lesson|practice|video)$",
    r"^/api/me/modules/\d+/lesson$",
    r"^/api/me/tutor$",
    r"^/api/me/assignments/\d+/(assessment|interview)$",
    r"^/api/me/interviews/\d+/submit$",
    r"^/api/manager/roles/[^/]+/analyze$",
    r"^/api/manager/team/\d+/infer-skills$",
    r"^/api/manager/documents$",
)]


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def _user_key(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        return "u:" + jwt.decode(auth[7:], settings.jwt_secret, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        return None


class RateLimiter:
    """Sliding one-minute window per key."""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float = 60.0) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False, max(1, int(window - (now - q[0])) + 1)
            q.append(now)
            return True, 0

    def reset(self):
        with self._lock:
            self._hits.clear()


class Metrics:
    def __init__(self):
        self.started = time.time()
        self.lock = threading.Lock()
        self.requests = 0
        self.in_flight = 0
        self.status = defaultdict(int)
        self.latency: dict[str, deque] = defaultdict(lambda: deque(maxlen=2000))
        self.counters = defaultdict(int)

    def group(self, path: str) -> str:
        path = re.sub(r"/\d+", "/{id}", path)
        parts = path.split("/")
        return "/".join(parts[:4]) if path.startswith("/api") else "static"

    def snapshot(self) -> dict:
        with self.lock:
            groups = {}
            for g, d in self.latency.items():
                vals = sorted(d)
                if vals:
                    groups[g] = {"count": len(vals), "p50_ms": round(vals[len(vals) // 2], 1),
                                 "p95_ms": round(vals[int(len(vals) * 0.95) - 1 if len(vals) > 1 else 0], 1),
                                 "max_ms": round(vals[-1], 1)}
            return {"uptime_seconds": int(time.time() - self.started), "requests": self.requests, "in_flight": self.in_flight,
                    "status": dict(self.status), "routes": dict(sorted(groups.items(), key=lambda kv: -kv[1]["count"])[:30]),
                    "counters": dict(self.counters)}


limiter = RateLimiter()
metrics = Metrics()


async def traffic_middleware(request: Request, call_next):
    path = request.url.path
    start = time.perf_counter()
    status = 500
    with metrics.lock:
        metrics.requests += 1
        metrics.in_flight += 1
    try:
        blocked = _check_limits(request, path) if settings.rate_limit_enabled and path.startswith("/api") else None
        response = blocked or await call_next(request)
        if request.method != "GET" and path.startswith("/api/manager") and response.status_code < 400:
            bump_manager_version(_user_key(request))  # their dashboards show the change right away
        status = response.status_code
        return response
    finally:
        ms = (time.perf_counter() - start) * 1000
        with metrics.lock:
            metrics.in_flight -= 1
            metrics.latency[metrics.group(path)].append(ms)
            metrics.status[f"{status // 100}xx"] += 1


def _check_limits(request: Request, path: str):
    ip = _client_ip(request)
    if path == "/api/auth/login" or path == "/api/auth/google":
        # Per IP (generous, since a whole room or building can share one IP) to stop floods...
        ok, wait = limiter.allow(f"login-ip:{ip}", settings.rate_limit_login_per_minute * 6)
        # (per-account limits are checked in the login handler, where the email is known)
        if not ok:
            metrics.counters["rate_limited_login"] += 1
            return _too_many("Too many sign-in attempts. Wait a minute and try again.", wait)
        return None
    who = _user_key(request) or f"ip:{ip}"
    if request.method != "GET" and any(p.match(path) for p in AI_PATHS):
        ok, wait = limiter.allow(f"ai:{who}", settings.rate_limit_ai_per_minute)
        if not ok:
            metrics.counters["rate_limited_ai"] += 1
            return _too_many("You're generating content very quickly. Give it a minute and try again.", wait)
    ok, wait = limiter.allow(f"api:{who}", settings.rate_limit_per_minute)
    if not ok:
        metrics.counters["rate_limited_api"] += 1
        return _too_many("Too many requests. Slow down for a moment.", wait)
    return None


def _too_many(message: str, retry_after: int):
    return JSONResponse({"detail": message}, status_code=429, headers={"Retry-After": str(retry_after)})


class AIGuard:
    """Limits concurrent AI calls and stops calling a failing AI service for a while."""

    def __init__(self):
        self.sem = threading.BoundedSemaphore(settings.ai_max_concurrent)
        self.lock = threading.Lock()
        self.failures = 0
        self.open_until = 0.0

    def acquire(self) -> bool:
        if time.time() < self.open_until:
            metrics.counters["ai_breaker_open"] += 1
            return False
        if not self.sem.acquire(timeout=settings.ai_queue_wait_seconds):
            metrics.counters["ai_shed_busy"] += 1
            return False
        metrics.counters["ai_calls"] += 1
        return True

    def release(self, ok: bool):
        self.sem.release()
        with self.lock:
            if ok:
                self.failures = 0
            else:
                self.failures += 1
                metrics.counters["ai_failures"] += 1
                if self.failures >= settings.ai_breaker_failures:
                    self.open_until = time.time() + settings.ai_breaker_seconds
                    self.failures = 0
                    metrics.counters["ai_breaker_trips"] += 1

    def state(self) -> dict:
        return {"breaker_open": time.time() < self.open_until, "max_concurrent": settings.ai_max_concurrent}


ai_guard = AIGuard()
build_slots = threading.BoundedSemaphore(settings.max_builds_concurrent)


# ---- shared generated content -------------------------------------------------------

def cached_content(db, key: str, build, variants: int = 1):
    """Return stored content for key, generating and storing it once.

    variants > 1 keeps several versions (e.g. practice sets) and serves one at random, so repeat
    practice isn't identical while still capping AI calls.
    """
    import random

    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from . import models

    keys = [f"{key}#{i}" for i in range(variants)]
    rows = {r.key: r for r in db.scalars(select(models.ContentCache).where(models.ContentCache.key.in_(keys)))}
    missing = [k for k in keys if k not in rows]
    if missing and (len(rows) == 0 or random.random() < 0.5):
        content = build()
        if content.get("generated_by") != "offline":  # don't pin offline fallbacks; try AI again next time
            try:
                with db.begin_nested():
                    db.add(models.ContentCache(key=missing[0], content=content))
            except IntegrityError:
                pass  # another worker stored it first
        metrics.counters["content_cache_miss"] += 1
        return {**content, "cached": False}
    metrics.counters["content_cache_hit"] += 1
    return {**random.choice(list(rows.values())).content, "cached": True}


class TTLCache:
    """Tiny per-process cache for hot read-only responses, with single-flight:
    when many requests miss the same key at once, one builds it and the rest wait for that result
    (no stampede of identical heavy queries at the top of a busy hour)."""

    def __init__(self, seconds: float, max_entries: int = 300):
        self.seconds, self.data, self.lock = seconds, {}, threading.Lock()
        self.key_locks: dict = {}
        self.max_entries = max_entries

    def get(self, key, build, ttl: float | None = None):
        hit = self._fresh(key)
        if hit is not None:
            return hit[1]
        with self.lock:
            key_lock = self.key_locks.setdefault(key, threading.Lock())
        with key_lock:
            hit = self._fresh(key)  # someone else may have built it while we waited
            if hit is not None:
                metrics.counters["report_cache_waited"] += 1
                return hit[1]
            value = build()
            with self.lock:
                self.data[key] = (time.monotonic(), value, ttl or self.seconds)
                if len(self.data) > self.max_entries:  # keep memory bounded: drop the oldest fifth
                    for k in sorted(self.data, key=lambda k: self.data[k][0])[: self.max_entries // 5]:
                        self.data.pop(k, None)
                        self.key_locks.pop(k, None)
            return value

    def _fresh(self, key):
        with self.lock:
            hit = self.data.get(key)
        return hit if hit and time.monotonic() - hit[0] < hit[2] else None

    def clear(self):
        with self.lock:
            self.data.clear()


catalog_cache = TTLCache(60)

# Heavy manager reports: at most this many build at once per worker; extra requests get a quick
# "busy, retry" instead of queueing up work that keeps burning CPU after the browser has given up.
report_slots = threading.BoundedSemaphore(2)
REPORT_WAIT_SECONDS = 8

manager_cache = TTLCache(30)
_manager_versions: dict[str, int] = defaultdict(int)


def manager_version(manager_id: int) -> int:
    return _manager_versions[f"u:{manager_id}"]


def bump_manager_version(user_key: str | None):
    if user_key:
        _manager_versions[user_key] += 1
