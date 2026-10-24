# Integrated onboarding demo

This branch combines the resource-based Python diagnostic with the colleague's
original **plain HTML/JavaScript** hire dashboard, manager dashboard, login page,
shared styles and supporting FastAPI application. It is not a React/Vite app.
The visual shell, logos, navigation, learning studio and manager pages are kept.
The diagnostic does not mark catalog assignments complete or certify mastery.

Repository consolidation is documented in [REPOSITORY_INTEGRATION.md](REPOSITORY_INTEGRATION.md),
with a complete source-file disposition inventory. Open
`Aggies-Invent-Integrated.code-workspace` for the backend and both role interfaces
in one portable VS Code workspace. The older `Aggies-Invent.code-workspace` is
local user work and is preserved separately, not required by a fresh clone.

Layout: `backend/app/` is the sole HTTP app; `backend/assessment.py` and
`backend/question_bank.py` are its reused diagnostic domain logic. `scripts/`
contains resource/bank CLIs; `backend/scripts/` contains the colleague's demo-data
utilities. `hire-dashboard/`, `manager-dashboard/`, and `shared/` are the actual
static UI roots. `Resource_File/` contains attributed reproducible source assets.
There is no active React app or second HTTP app under the empty `frontend/` folder.

## Start locally (PowerShell, from this project folder)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt

# Frontend: validate JavaScript/imports/assets and build the static bundle
.\.venv\Scripts\python.exe scripts/build_frontend.py

# Backend AND frontend: one same-origin server, no second frontend process needed
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

`backend/requirements-lock.txt` captures the verified installed versions for
optional exact environment reproduction. The extraction-only
`scripts/requirements.txt` agrees on the PDF parser version. `.env.example` is a
placeholder reference only: set variables in the terminal, never populate or
commit credential files. No environment file is loaded by the application.

Open **http://127.0.0.1:8000/login/** and choose **New hire**. The supplied
fictional demo account is `hire@lanl.gov` / `demo1234`. Choose **Diagnostic
assessment** in the original sidebar. The manager dashboard is still available
through the manager demo account. Source UI is served during development; to
serve the bundle instead, set `$env:FRONTEND_DIR = "$PWD/dist"` before starting.
Frontend syntax checking uses Node if available, or VS Code's bundled Node
runtime in `--check` mode. It does not execute learner-provided JavaScript.

The first start seeds the colleague's fictional people/catalog data into
`backend/lanl_training.db`. No credential files are read. The application is a
loopback-only local demo, not a production deployment. Configure a proper JWT
signing secret, authentication and deployment controls before hosting it.

## Set up the real diagnostic

No diagnostic questions are fabricated when a bank is missing, pending, invalid
or stale. The UI displays a setup message instead. Bank setup is an explicit
admin CLI activity; generation is **not** called by the learner API.

If no approved bank exists, after implementation run these with your existing
terminal `ANTHROPIC_API_KEY` (only the first command makes Claude calls):

```powershell
.\.venv\Scripts\python.exe scripts/generate_question_bank.py
.\.venv\Scripts\python.exe scripts/review_question_bank.py --interactive
```

Read each scenario, answer/reason explanations, evidence and prerequisite links;
manually approve the diagnostic and foundation items you intend to use.
**Structural validation is not factual validation.** The UI never gets answer
keys, grading logic, approval records, credentials or the private bank file.
Approval digests and current resource fingerprints are checked by the backend;
changing the bank/approvals during a session requires a new diagnostic.

See [ASSESSMENT_DEMO.md](ASSESSMENT_DEMO.md) for concept mapping and bank review.
The existing `backend/ai_client.py`, `question_bank.py`, `assessment.py`, resource
JSON and original CLI remain in place and are reused, not replaced by mocks.

## Diagnostic flow and persistence

- Up to eight initial application scenarios by default, round-robin across
  available approved topics, within a total 12-scenario budget. Each item includes
  a separate reasoning choice and confidence rating. Confidence adds no points.
- Incorrect/conflicting choices lead to one approved foundation follow-up on
  that concept when budget permits. Relevant prerequisite foundations may use
  remaining budget. Initial topic slots are reserved; questions do not repeat.
- Explanations are withheld until the diagnostic branch finishes. Results are
  available only when the entire diagnostic finishes. They report concept-level
  foundation/application/reasoning evidence, observed gaps, targeted review,
  required-training obligations separately, and explicit unassessed coverage.
- SQLite state, result reports and exact duplicate-response receipts are stored
  privately in `Resource_File/cache/assessment/sessions.sqlite3`. Sessions survive
  restarts; the browser retains only a session ID per signed-in employee.
- A write transaction and a unique `(session_id, question_id)` constraint prevent
  duplicate or concurrent submissions advancing twice. Identical retries return
  the cached reply; conflicting retries receive 409. Refresh current question if
  a network retry returns an old reply. Session access is restricted to its owner.

The API endpoints (all authenticated) are:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/diagnostic/status` | Availability/setup message |
| POST | `/api/diagnostic/sessions` | Start, with optional `initial_limit` and `budget` |
| GET | `/api/diagnostic/sessions/{id}/current` | Current learner-safe question/completion |
| POST | `/api/diagnostic/sessions/{id}/answers` | Submit stable question/answer/reason IDs and confidence |
| GET | `/api/diagnostic/sessions/{id}/results` | Completed concept-level report |

No CORS wildcard is enabled: browser assets and APIs use the same origin, so no
development proxy is needed. Do not run the static HTML through a `file://` URL.
Only the explicit UI directories are served; backend, fixtures, resources and
private database/bank paths are not mounted as static assets.

## Scope of the preserved colleague UI

The people, catalog, calendar, studio, interviews, manager metrics, and readiness
estimates are **unrelated fictional/demo features**, labeled in each dashboard's
sidebar. The old hire quiz buttons now open the real reviewed resource diagnostic;
its result screen does not use the older generated quiz scores or readiness
estimates. The legacy APIs and their tests remain for compatibility. Optional
legacy AI is disabled by default (`ENABLE_LEGACY_AI=false`) and is not required
for this integration. No learner code runner is implemented.

## Offline checks

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m unittest scripts.test_assessment scripts.test_ai_client_offline scripts.test_knowledge_pipeline -q
.\.venv\Scripts\python.exe scripts/build_frontend.py
```

API tests exercise login, start, incorrect reasoning, a different foundation
follow-up, completed results, budget/coverage, ownership, pending/revoked reviews,
restart restoration and duplicate concurrent submissions. Synthetic offline bank
fixtures live in `tests/fixtures/`, **not** in the real bank directory. No live
Claude calls or learner-provided code are executed by these tests.

## Preservation and provenance

- Original backend project: `C:/Users/write/OneDrive/Desktop/AGGIES INVENT LANL`.
- Original UI worktree: sibling `Aggies-Invent-UI`, detached at `cf16ec0`.
- Integration branch: `integration/local-ui`, created from `onboarding-diagnostic`
  with `45803a8` retained as its ancestor. Subsequent repository-only consolidation
  is on `integration/repository-consolidation`; only that branch is published.
- Eighty UI/supporting files were copied after checking for destination conflicts;
  no existing backend file was overwritten during import. No `.env` files or
  examples were imported. The original UI folder is left unchanged.
- Original UI documentation is preserved at `docs/UI_ORIGINAL_README.md` for
  provenance; this README supersedes its runtime/environment-file instructions.
- Windows fixes in the integration copy: explicit UTF-8 test reads and portable
  date formatting in the legacy interview service.

Local databases, uploads, build outputs, generated banks/results, debug files and
dependencies are ignored by Git. The existing two-folder workspace file is
preserved; the combined application can be opened directly as this project folder.
