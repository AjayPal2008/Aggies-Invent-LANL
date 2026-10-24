# Aggies Invent × LANL: Adaptive Training Platform

An AI-powered training platform for Los Alamos National Laboratory. It pulls every training from UTrain and LANL's other training sites into one catalog, combines it with the org directory and Oracle HR, and gives each employee a learning experience that starts broad and adapts its pacing, difficulty and delivery method to how they actually perform.

| Part | Folder | Owner |
| --- | --- | --- |
| Manager dashboard | [`manager-dashboard/`](manager-dashboard/) | Nick |
| Hire dashboard | [`hire-dashboard/`](hire-dashboard/) | AJ |
| Backend, data integration, hosting | [`backend/`](backend/) | Roa |
| Login page, styles, API client (shared) | [`shared/`](shared/) | everyone |

## Run it

Needs Python 3.11+. No Node or build step.

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd backend
../.venv/bin/python -m scripts.seed --reset
../.venv/bin/uvicorn app.main:app --reload
```

Open http://localhost:8000 and sign in with a demo account (password `demo1234`):

| Account | Sees |
| --- | --- |
| `hire@lanl.gov` | Hire dashboard (a data scientist three weeks into the job) |
| `manager@lanl.gov` | Manager dashboard for an 86-person CCS group with 4 team leads, plus their own trainings. Owns the open **Project Lead** role, which has a job description, the sample handbook and a role plan loaded |
| `admin@lanl.gov` | Everything, plus the Data sources page |

Interactive API docs (Swagger) are at http://localhost:8000/docs. Run the tests with `cd backend && ../.venv/bin/python -m pytest`.

To turn on Claude for course building, lessons, videos, interview scoring, practice questions, tutoring and skill estimates, copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`. Without a key everything still works using built-in content generated from each training's outline, and responses are labeled "offline".

## What it does

**From a 200-page document to an interactive course**
- Managers upload a role's job description, requirements and internal documents (PDF, Word or text; 200+ pages is fine). Manuals, handbooks, policies and procedures become courses: modules mapped to page ranges, objectives, the actual requirements as key points, and a bank of realistic workplace scenarios. The demo includes a 181-page sample Project Management Handbook that becomes a 15-module course (about 2 hours instead of 6+ hours of reading).
- Learners pick a style: **video** (narrated, animated lessons with captions, played in the browser), reading, visual walkthroughs, hands-on exercises, simulations or quizzes. Each module is generated from just its pages and cached per style and level.
- **The right assessment for each training.** Most trainings (policies, rules, procedures, safety and technical knowledge) use a **multiple-choice quiz**; for courses built from a document, the questions come from the document's own requirements, with plausible wrong answers. **Interview-style assessments** are used only where judgment is what's being tested, such as leading people or difficult conversations, and **both** where someone needs the rules and the judgment (ethics, the Project Lead handbook). Managers can switch any training between Quiz, Interview and Quiz + interview from the role plan.
- **Interviews** work like CASPer or an MMI: three workplace scenarios, a short read, then a timed answer per question, typed or spoken (recorded, with a live transcript). The AI scores each answer 1–9 against a rubric; managers listen or read, then confirm or override.
- **Readiness after every interview:** *Ready*, *Ready with support* or *Not ready yet*, with a 0–100 score, the reasons, competency-by-competency results, next steps and the course modules to review. It combines the interview score, the weakest competency, mastery of the training's skills and, for quiz + interview trainings, the quiz score. It updates when a manager changes the score, and shows on the hire's trainings list, the manager's interview reviews and the hire view.
- **Role plans** curate trainings per role in phases (first 2 weeks, first 30 days, first 90 days), each tagged for who it's for. Starting someone in a role tailors it: new hires get culture, policy and how-the-Lab-works onboarding; people promoted or transferring from inside skip onboarding and anything already completed and current, and get transition training instead; experienced people can test out of introductory items and start at a higher level. Managers preview each person's plan, with warnings when they're below the role's experience or level, before confirming.

**Hire dashboard**
- Overdue, upcoming, in-progress and completed trainings, with a learning path that explains why each item is next (overdue, retake, closes a skill gap, required for your role, prerequisite).
- Filter by category (safety, technical, company culture, compliance), required or optional, and status; sort by due date, title, status or category.
- Calendar of in-person classes with times and locations; register for open sessions.
- Learning studio: generate a lesson for any training in your learning style, override delivery method or level, or type a request ("use an analogy", "focus on the glovebox part"). Lessons mix reading, visual step diagrams, branching workplace simulations, guided exercises and knowledge checks.
- AI practice questions targeted at your weakest skills, a tutor chat, and graded assessments (answers stay on the server).
- Every answer updates your skill estimates, which change the next lesson's level, pace and format.

**Manager dashboard**
- Team overview: new hires, progress (not started / in progress / completed), overdue, retakes, expiring certifications, headcount by fiscal year.
- Manage teams of LANL's size (the demo manager has 86 people in 4 sub-teams): sub-team cards with completion and overdue roll-ups, search by name, email, title or Z number, direct-reports filter, and paging.
- Team table ranked by a performance index (assessments, HR rating, completion), filterable by level, new hires and fiscal year hired.
- Bulk actions on any selection, up to the whole org at once: assign trainings, assign every missing role requirement, change due dates, remove trainings, email reminders. Export the team to CSV.
- Read-only hire view of any team member: assignments, scores, attempts, next retraining date, gaps, skills, promotion readiness. Managers can't act as the hire, and hires can't reach any manager page or API.
- Assign trainings to one person or many, with due dates.
- Retraining: failed assessments, expiring certifications and scheduled refreshers. Email reminders with a preview before anything is sent.
- Compliance by division (safety broken out) and a knowledge-gap heatmap by role or equipment.
- Open roles: candidates across the lab ranked by AI-estimated skills, completed trainings, years of experience, level and performance, with "meets all requirements" filtering.
- Promotion readiness with the checks that pass or fail.
- Data sources page (admin): connector health, sync, and CSV/JSON upload.

## Training library (admin)

The admin library holds every required training in UTrain's three layers: **institutional** (everyone: security, cyber, ethics, policy, safety, many annual), **division** (Weapons, Science, Technology & Engineering, Operations) and **role** (technical and soft skills, shared across divisions with division-specific additions). It is seeded from public LANL sources: the 21 web-based required courses on extrain.lanl.gov, the 38 White Rock Training Center live courses with their 40 public student manuals, and the Nuclear Fundamentals Orientation. A new hire gets all three layers; an internal promotion in the same division gets only the new role's training; a move from another division adds that division's. Admins attach, rename, replace, re-download and delete PDFs and slide decks, and the AI builds lessons from them. Managers use the **Role directory** to open a role and get its job description, skills and a clean list of every training to assign for a new hire, promotion or transfer. Details: [docs/TRAINING_LIBRARY.md](docs/TRAINING_LIBRARY.md).

## Source-grounded diagnostic (AJ)

A second, stricter assessment path built from public source documents in [`Resource_File/`](Resource_File/) (computer security, ionizing radiation, nuclear fission, nuclear reactors; see [`Resource_File/ATTRIBUTION.md`](Resource_File/ATTRIBUTION.md)). Each question asks for an answer **and** the reasoning behind it, adapts to foundation questions when someone struggles, and reports concept-by-concept review priorities. Answers are graded on the server from a **manually reviewed** question bank; the browser never sees the answer key, and no AI is used for grading.

- Hire dashboard: **Diagnostic assessment** and **Diagnostic results**.
- API: `/api/diagnostic/*` (`status`, `sessions`, `current`, `answers`, `results`).
- Sessions are stored in the platform database, so they work across all app workers and Docker replicas. Set `DIAGNOSTIC_DB_PATH` to use a separate SQLite file instead.
- Setup: the reviewed bank lives in `Resource_File/cache/assessment/bank.json`, outside git. Generate it with `python scripts/generate_question_bank.py`, then review and approve each question with `python scripts/review_question_bank.py --interactive`. Until then the page explains the setup step. Full walkthrough: [ASSESSMENT_DEMO.md](ASSESSMENT_DEMO.md).
- Pipeline scripts in [`scripts/`](scripts/) cover PDF to text, knowledge extraction and validation, and bank generation and review; `python -m pytest scripts` runs their tests.

## How the adaptation works

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). In short: per-skill knowledge tracing (Bayesian Knowledge Tracing) sets difficulty; recent accuracy sets pacing; a running success rate per delivery method, seeded by the learner's stated style, picks the format; gaps are required skills below 70% mastery; retraining dates come from assessment scores.

## Scale and reliability

Built for LANL's 20,000+ employees at peak times (annual retraining deadlines, new-hire waves). It runs as identical stateless app servers behind nginx, with heavy manager reports isolated on their own servers, shared caching of generated content, rate limits, an AI circuit breaker with offline fallback, health checks, and automatic client retries. Load-tested with 20,000 employees: **1,000 simultaneous users, 99.97% success, 95% of employee requests under 16 ms** on one laptop; 2,000 users slowed but never crashed. Details, failure scenarios and production sizing: [docs/SCALABILITY.md](docs/SCALABILITY.md).

## Using real LANL data

The backend doesn't assume our column names. Drop exports from Oracle HR, UTrain and the directory into a folder, or switch a connector to live mode. See [docs/DATA_INTEGRATION.md](docs/DATA_INTEGRATION.md).

## Hosting

- **Render (free):** in Render choose New > Blueprint and pick this repo. [`render.yaml`](render.yaml) creates the web service and a free PostgreSQL database. Add `ANTHROPIC_API_KEY` and `PUBLIC_URL` in the Render dashboard.
- **Docker anywhere:** `docker compose up --build` runs the production-style stack at http://localhost:8000: nginx load balancer, 2 app containers, a reports container and PostgreSQL. Add capacity with `APP_REPLICAS=4 docker compose up -d`.
- **Database:** SQLite by default; set `DATABASE_URL` for PostgreSQL (Render, Neon and Supabase all have free tiers).

## Sample data

Everything in `backend/data/sample/` is fictional: people, emails, salaries, course codes and URLs. Directorate names follow LANL's public org chart. Dates are relative to the day you run `scripts.seed --reset`, so re-run it before a demo.

The logo in `shared/assets/` is a recreation for the prototype. Swap in the official file from LANL brand resources before presenting.
