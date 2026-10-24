> Upstream reference from origin/main at cf16ec0. Describes the colleague's original system, not verified capabilities or deployment guarantees of this consolidation. Root README.md is authoritative; no .env files are loaded.

# Architecture

```
 LANL directory ─┐                          ┌─> /hire/     hire dashboard (HTML + JS)
 UTrain + other  ├─> connectors ─> sync ─> DB ─> FastAPI ──┼─> /manager/  manager dashboard
 training sites ─┤   (file | live)          │      /api    └─> /login/    shared login
 Oracle HR ──────┘                          │
                              adaptive engine, matching, insights, AI (Claude), email
```

One FastAPI process serves the JSON API under `/api` and the three static front ends. The dashboards are plain HTML and ES modules, so there's no build step; they share `shared/api.js` (API client, auth guard, UI helpers) and `shared/styles.css` (LANL navy and white).

## Backend layout

```
backend/
  app/
    main.py            app setup, static mounts, first-run data load
    config.py          every setting, overridable by env vars / .env
    database.py        SQLAlchemy engine (SQLite or PostgreSQL)
    models.py          tables
    auth.py            password + Google sign-in, JWT, role checks, team scoping
    serialize.py       row -> JSON
    connectors/        one module per source system
      base.py          CSV/JSON reading, column aliasing, mapping.json, type coercion
      directory.py     divisions and positions
      utrain.py        training catalog + sessions from every training site
      oracle_hr.py     employees + completion history
    services/
      sync.py          upsert connector data into the DB (idempotent)
      adaptive.py      knowledge tracing, difficulty, pacing, delivery method, gaps, paths, retraining
      matching.py      role fit, candidate ranking, promotion readiness, performance index
      insights.py      gap heatmap, compliance by division
      ai.py            Claude calls with structured JSON output (streaming for long documents), offline fallbacks
      documents.py     PDF/Word/text extraction, AI course building from long documents
      courseware.py    module lessons, video scripts, interview scenarios and scoring
      roles.py         job description analysis, role plans, tailoring by entry path
      demo.py          loads the sample role documents on a fresh database
      notify.py        reminder emails (preview / Resend / SMTP)
    routers/
      auth.py          /api/auth/*
      catalog.py       /api/trainings, /api/divisions, /api/positions
      hire.py          /api/me/*        the signed-in learner
      manager.py       /api/manager/*   manager role required
      admin.py         /api/admin/*     admin role required
      content.py       /api/manager/documents, /roles, /interviews   role setup and interview review
      learn.py         /api/me/modules, /interviews, /role-plan      courses, videos, interviews
  scripts/             make_sample_data.py, seed.py
  data/sample/         fictional CSV exports
  tests/               pytest suite
```

## Data model

| Table | Source | Notes |
| --- | --- | --- |
| `divisions` | Directory | Directorates are rows with no parent |
| `positions` | Directory | Required skills, trainings, years, level; `is_open` marks roles to fill |
| `trainings` | UTrain + other sites | Category, required, delivery, `source_system`, `source_url`, validity, skills, prerequisites, roles, equipment, facilities, outline |
| `training_sessions` | UTrain | Scheduled in-person classes |
| `employees` | Oracle HR | Title, level, hire date, experience, salary, rating, manager, learning style, skills |
| `assignments` | Platform (seeded from HR history) | Status, progress, due, score, attempts, expiry, next retraining, difficulty |
| `assessment_attempts` | Platform | Score and per-skill results |
| `mastery` | Platform | Per-employee, per-skill knowledge estimate |
| `learning_events` | Platform | Every lesson, answer, chat and assessment, used for adaptation |
| `sync_runs` | Platform | Audit log of imports |
| `documents`, `document_pages` | Uploads | Job descriptions, requirements and internal manuals, page by page |
| `course_modules`, `lesson_cache` | Platform | AI-built course structure and generated lessons/videos |
| `scenarios`, `interview_sessions`, `interview_responses` | Platform | Situational assessments, answers, recordings, AI and manager scores |
| `role_plan_items` | Platform | Curated training plan per role |

## Adaptive engine (`services/adaptive.py`)

- **Knowledge tracing.** Each skill has a probability the learner knows it. Answers update it with Bayesian Knowledge Tracing (learn 0.15, slip 0.1, guess 0.2). Assessment results blend in as four observations at the score. New skills start at 20%, so everyone begins with introductory material.
- **Difficulty.** Average mastery of a training's skills: under 45% intro, under 75% intermediate, otherwise advanced.
- **Pacing.** Accuracy over the last 20 answers: under 60% slows down (5-minute chunks, 3 examples per concept); over 85% speeds up.
- **Delivery method.** For text, visual, simulation, quiz and guided exercise, the engine keeps a success rate (Beta posterior, with a head start for the stated learning style) plus a small exploration bonus, and picks the best. Equipment and facility trainings lean toward simulations.
- **Knowledge gaps.** Skills required by the person's position or assigned trainings with mastery under 70%.
- **Learning path.** Scores every unfinished training (overdue +100, retake +80, due soon, already started, assigned, required for role, closes gaps weighted by how weak the skill is), pulls in missing prerequisites ahead of what needs them, and returns each step with its reasons.
- **Retraining.** Under 80: retake within 14 days. 80-89: refresher at 75% of the certification period. 90+: refresher at expiry.

## Documents to courses (`services/documents.py`, `services/courseware.py`)

1. **Upload** (`POST /api/manager/documents`): the file is stored under `UPLOAD_DIR`, text is extracted page by page (`pypdf`; Word and text files are split into ~450-word pages) and saved as `document_pages`. Scanned PDFs with no text are rejected with a message to OCR them first.
2. **Build** (background task): the whole document, with page markers, goes to Claude in one streaming request that returns a course as JSON: 4–12 modules with page ranges, summaries, objectives, key requirements and skills; 6–10 situational scenarios with questions, competencies, what a strong answer considers and red flags; and whether to assess by quiz, interview or both. A 200-page manual is roughly 100–150k tokens, well within the model's context. Without a key, the offline builder uses the document's chapter headings and its "must / shall / required" sentences.
3. **Learn** (`POST /api/me/modules/{id}/lesson`): one module's pages plus the learner profile produce either a video script (scenes with on-screen text, a visual type and narration) or a mixed lesson. Results are cached in `lesson_cache` per module, style and level, so a course is only generated once per combination; custom requests bypass the cache.
4. **Video playback** (`hire-dashboard/learning.js`): scenes play as a narrated, animated video using the browser's speech engine, with captions, speed control and a check question at the end. No video rendering service is needed; to use one later, send it the same scenes.

## Choosing the assessment (`app/assessment_rules.py`)

- `quiz` by default: policies, rules, procedures, safety and technical knowledge.
- `situational` (interview) when a training's skills or title are about leading people or judgment calls (leadership, coaching, stakeholder communication, conflict, difficult conversations).
- `both` for knowledge plus judgment (ethics). Courses built from documents: the AI picks; offline, policies, procedures and manuals get a quiz, and handbooks for lead roles that cover managing people get both.
- Managers can override any training (`PATCH /api/manager/trainings/{code}/assessment`). For `both`, the training completes only when the quiz and the interview have both passed; attempts are recorded with their kind.
- Quizzes for document-built courses (`courseware.document_quiz`) are written from the modules' key requirements. Offline, the right answer is the requirement itself, and wrong answers are versions of it with the obligation softened, the order flipped or the threshold changed.

## Readiness (`courseware.score_readiness`)

After an interview is scored, and again whenever a manager changes the score:

    readiness score = 55% interview + 20% weakest competency + 25% skill mastery
                      (quiz + interview trainings: 15% skill mastery + 10% best quiz)
    Ready               score >= 75, interview >= pass mark (5.5/9), no competency below 5
    Ready with support  score >= 55 and interview >= 4.5
    Not ready yet       otherwise

The result includes a one-line summary, next steps (mentor pairing and a 30-day check-in for "with support"; review and redo by a date for "not ready"), each competency's status, and the course modules behind the lowest-scored scenarios.

## Interview-style assessments

- `POST /api/me/assignments/{id}/interview` picks 3 scenarios the person hasn't seen (catalog trainings get a scenario bank written the first time). The rubric is never sent to the browser while answering.
- Answers are typed or spoken. Spoken answers are recorded (MediaRecorder) and transcribed live by the browser (Web Speech API, supported in Chrome, Edge and Safari); learners can correct the transcript. Recordings are stored for the manager.
- Scoring: Claude rates each answer 1–9 against its rubric (reasoning and priorities, not polish), plus competencies and strengths/improvements. Offline, a heuristic scores coverage of the rubric. The 1–9 score maps onto the 0–100 scale so the pass mark (5.5) lines up with 80, which keeps retake and refresher rules the same as quizzes.
- Managers review in **Interview reviews**: play recordings, read transcripts and the rubric, and set the final score. Their score replaces the AI's for pass/fail and retraining.

## Role plans (`services/roles.py`)

- `role_plan_items`: training, phase (1 = first 2 weeks, 2 = 30 days, 3 = 90 days), audience (`all`, `new_hire`, `internal`, `promotion`, `transfer`), required, and an optional years-of-experience threshold to skip.
- Default plan when none is saved: lab-wide required safety and compliance for everyone (auto-skipped when current), culture onboarding for new hires only, the role's required trainings, courses built from the role's documents, leadership transition trainings for lead roles, and anything that teaches a required skill not yet covered.
- `POST /api/manager/roles/{code}/analyze` reads the role's job description and requirements and suggests skills, minimum years, prerequisites, a plan and topics no training covers yet.
- Entry path is detected (hired in the last 120 days with no previous role = new hire; moving up a level = promotion; otherwise transfer) and can be overridden. Starting a role records the previous position, entry path and start date, assigns the tailored plan with due dates by phase, and raises starting mastery on the role's skills for experienced people.

## Matching (`services/matching.py`)

- **Performance index** (0-100): 50% average assessment score, 30% HR rating, 20% completion rate.
- **Role fit**: 45% skill coverage, 25% required trainings completed, 15% years of experience, 15% performance index. "Meets requirements" means years, level (within one), all required trainings and all required skills.
- **Promotion readiness**: rating at least 4, nothing overdue, average assessment at least 85, plus the years and trainings for the next higher role in the division.

## AI (`services/ai.py`)

Uses the Anthropic Python SDK with `claude-opus-5-5`, JSON-schema structured output for lessons, questions and skills, and server-side refusal fallbacks (`fallbacks: "default"`). Any error, refusal or missing key falls back to deterministic content built from the training outline, so demos never break. The system prompt keeps LANL safety culture front and center and forbids inventing procedure numbers or limits.

## Scale

- `auth.team_ids` reads the reporting graph (`id`, `manager_id`) in one query and walks it in memory, so a 5-level org costs the same as a flat one.
- `services/loader.load_people` loads a set of people with assignments, trainings, sessions, attempts and managers using `selectinload` (a few `IN` queries, chunked at 900 ids), and `prefetch` caches the training catalog, positions and per-person skill mastery on the request's session (`db.info`). The adaptive, matching and insights functions read those caches when present.
- Lab-wide candidate search narrows to eligible levels in SQL before loading anyone.
- Sync preloads existing rows by natural key and hashes the shared demo password once.
- `tests/test_team_management.py` fails if a team page goes over 30 queries.

## Security

- JWT bearer tokens, 8-hour expiry. Set a long random `JWT_SECRET` in production.
- Company email domain enforced on every login path. Google sign-in verifies the ID token with Google and requires a matching employee record.
- Roles: hire < manager < admin. Manager routes check the role server-side and scope every query to the manager's reporting chain. Hires never receive salary or HR rating.
- API keys only live on the server.
- For production at LANL, replace password login with lab SSO (SAML/OIDC) in `auth.py`; the rest of the app only needs the verified email.
