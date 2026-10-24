> **Update (merged into `main`):** this consolidation now runs on the platform backend in `backend/app`.
> The diagnostic API, engine, resources, scripts and tests are kept as written. Its sessions are stored in the
> platform database (`DATABASE_URL`), so they work with the Docker stack. The Docker stack (`docker-compose.yml`,
> `Dockerfile`, `deploy/`), the Render blueprint and the existing learning features (quizzes, practice, lesson
> simulations, video checks) remain in place. The docs stay in `docs/`. The root README is the startup reference.

# Repository integration and verification

This is repository consolidation of existing work, not implementation of the
complete onboarding product. The root README is the verified startup authority.

## Discovery and protected history

| Component | Source location / ref | Disposition |
|---|---|---|
| Original resource/diagnostic backend | `C:/Users/write/OneDrive/Desktop/AGGIES INVENT LANL`, `onboarding-diagnostic`, `45803a8fa03914873cafb44c750db193ff1c3f17` | Retained, including extraction, review, assessment and tests |
| Colleague UI and supporting app | Sibling `Aggies-Invent-UI`, detached `cf16ec04f2e8cbce5df6a71c17966e858c4c813e`, matching `origin/main` | Original folder left intact; imported components accounted for below |
| Existing local integration | `integration/local-ui`, `48e4190` | Preserved as parent of consolidation work; not silently assumed pushed |
| This consolidation | `integration/repository-consolidation`, based on `48e4190` | Dedicated branch; only this branch authorized for push |
| Intended remote | `git@github.com:AjayPal2008/Aggies-Invent-LANL.git` | Fetch/push use a command-local HTTPS rewrite because SSH authentication failed earlier |

At discovery, all application changes were already committed in `48e4190`.
The only untracked file was `Aggies-Invent.code-workspace`; it was not modified,
stashed, moved or discarded. It points outside the repository and remains ignored
local user work. The new `Aggies-Invent-Integrated.code-workspace` is portable and
opens the backend/resources, employee UI, team-lead UI and shared assets together.
Remote references were fetched, not pulled. Existing main and onboarding refs
remain untouched. No branch deletion, reset, clean, force push or DSI installation.
The backend and upstream UI histories have unrelated roots; the existing explicit
file import is retained rather than manufacturing a conflicting unrelated-history
merge. Source refs and upstream file hashes preserve provenance.

## Layout and deliberately reconciled conflicts

- One HTTP app: `backend/app/main.py`. The diagnostic domain modules under
  `backend/` are reused by its diagnostic adapter, not alternative app entry points.
- Actual UI roots remain `hire-dashboard/`, `manager-dashboard/`, and `shared/`.
  No React/Vite scaffolding or duplicate frontend implementation was introduced.
- The empty local `frontend/` directory contains no project files and is not tracked.
- Root `scripts/` are resource/diagnostic CLIs; `backend/scripts/` are preserved
  demo-data utilities. Root README distinguishes their startup/import contexts.
- Root README supersedes upstream runtime instructions. Original README and
  architecture/data/scaling documents are archived with source notices; their
  relative links point at the original source commit. Upstream performance claims
  and hosting settings are not claimed as verified for the combined project.
- Root `.gitignore` combines both projects' exclusions and keeps live/scale data,
  learner state, caches, databases, uploads, logs and dependencies out of Git.
- Existing UI imports had no destination collisions during the earlier 80-file
  import. Subsequent adapted files are identified in the full inventory. Notable
  adaptations: environment-only config, same-origin static mounts, diagnostic
  endpoints/UI, demo notices, and Windows UTF-8/date-format fixes.
- Legacy practice now routes to the existing reviewed diagnostic. Legacy video
  quick-check and simulation client scoring hooks are disabled, leaving those
  studio elements ungraded demonstrations. No new grading/generation workflow was
  invented. Existing server APIs remain for compatibility; only the resource
  diagnostic is the verified reviewed assessment path.
- No private bank, literal answer keys, or grading implementation is bundled into
  frontend assets. Bank generation/review and grading remain backend code. Legacy
  lesson services are demo code, not verified assessment evidence.
- Both roles retain distinct interfaces. No learning plans, audio or mind-map
  features were added in this task. Existing unrelated demo features stay labeled.

## Relevant local-only files included in consolidation

- `REPOSITORY_INTEGRATION.md` and `docs/REPOSITORY_FILE_INVENTORY.json`: human and
  machine-readable inventory/disposition reports.
- `Aggies-Invent-Integrated.code-workspace`: portable workspace; older local file
  preserved separately.
- `.env.example`: newly authored empty/placeholder-only reference, never copied
  from a credential file. Application settings still load no `.env` files.
- `backend/requirements-lock.txt`: installed versions recorded without upgrading
  dependencies. PDF-parser version reconciled with `scripts/requirements.txt`.
- `scripts/audit_repository.py`: value-suppressing provenance, limited secret-pattern
  and frontend answer-key/grading scan.
- `Resource_File/ATTRIBUTION.md`: existing Wikipedia URLs/license metadata and
  transformations recorded; PDF embedded third-party licenses are not independently
  audited. Existing authorship/notices and upstream logo caveat are preserved.
- `docs/upstream/`: three previously omitted upstream reference documents.
- Root README and ignore rules updated; no new product workflow was started.

## Exclusions and generated-resource decisions

Installed dependencies, `.git` metadata, runtime databases, generated learner
records/results, logs, debug responses, uploads, frontend `dist/`, and caches are
excluded. Credential paths are excluded by filename/directory before scanning;
no credential files were opened. The old external-folder workspace is preserved
but intentionally not committed. Source deployment manifests are accounted for
individually below: they describe unverified external/multi-replica hosting, not
the chosen local SQLite app, and remain available at their original Git ref.

The four Wikipedia PDFs, cleaned text and extracted article knowledge are
reproducible, attributed demo inputs and stay tracked. A missing/pending question
bank is runtime/private generated state: no bank was promoted to approved or
committed to make the demo run. `tests/fixtures/synthetic_diagnostic.json` is
explicitly synthetic test-only data outside the real bank path. Generated sessions
and personal results never enter this inventory or Git.

## Verification and remaining gaps

- Backend/UI suite: 68 tests passed; original diagnostic/extraction suite: 43
  tests passed. Four knowledge JSON resources structurally validate.
- Frontend build: seven JavaScript modules/inline scripts syntax-checked; 16
  allowlisted static assets bundled. No npm build exists in the original UI.
- Offline API fixtures verify login, start, answer/reason grading, foundation
  follow-up, results, approval enforcement, budgets, non-repetition, ownership,
  restart persistence, and duplicate concurrent submission protection.
- Limited high-confidence secret-pattern scan: zero findings. Credential files
  excluded. This is not a comprehensive secret audit; values are never printed.
- Frontend source/bundle scan: zero private key-field or client-choice grading
  references after the legacy hook reconciliation. No backend, fixture, private
  bank or database is copied by the build allowlist.
- Existing HTTP connection verified on loopback: health/login, hire/manager assets
  and diagnostic status; private resource/backend/fixture paths return 404.
- Previous Windows failures (default-encoding tests and nonportable date format)
  were already fixed in the preserved local integration; no new failures observed.
- Interactive visual browser verification remains unavailable in this environment.
  Docker/cloud/multi-replica operation is not tested or enabled by this task.
- No approved real bank currently exists: UI gives setup instructions, not
  fabricated questions. Human review and later generation remain explicit tasks.
- Full team syllabus -> personalized training -> text/audio/mind-map -> repeated
  adaptive assessment workflow is not complete. Existing demo document/role/studio
  routes are not claimed as that completed product. No response-speed mastery
  rule was added. See root README for exact local startup commands and URLs.

To reproduce the inventory/scans, run `python scripts/audit_repository.py` while
both original folders and the recorded local Git refs are available. Runtime does
not depend on the sibling UI folder. Complete per-file inventory follows and is
also available in `docs/REPOSITORY_FILE_INVENTORY.json`.

## Files already tracked at discovery (117)

- `.gitignore`
- `ASSESSMENT_DEMO.md`
- `README.md`
- `Resource_File/Computer_security.pdf`
- `Resource_File/Ionizing_radiation.pdf`
- `Resource_File/Nuclear_fission.pdf`
- `Resource_File/Nuclear_reactor.pdf`
- `Resource_File/extracted_knowledge/Computer_security.json`
- `Resource_File/extracted_knowledge/Ionizing_radiation.json`
- `Resource_File/extracted_knowledge/Nuclear_fission.json`
- `Resource_File/extracted_knowledge/Nuclear_reactor.json`
- `Resource_File/raw_text/Computer_security.txt`
- `Resource_File/raw_text/Ionizing_radiation.txt`
- `Resource_File/raw_text/Nuclear_fission.txt`
- `Resource_File/raw_text/Nuclear_reactor.txt`
- `backend/ai_client.py`
- `backend/app/__init__.py`
- `backend/app/assessment_rules.py`
- `backend/app/auth.py`
- `backend/app/config.py`
- `backend/app/connectors/__init__.py`
- `backend/app/connectors/base.py`
- `backend/app/connectors/directory.py`
- `backend/app/connectors/oracle_hr.py`
- `backend/app/connectors/utrain.py`
- `backend/app/database.py`
- `backend/app/main.py`
- `backend/app/models.py`
- `backend/app/routers/__init__.py`
- `backend/app/routers/admin.py`
- `backend/app/routers/auth.py`
- `backend/app/routers/catalog.py`
- `backend/app/routers/content.py`
- `backend/app/routers/diagnostic.py`
- `backend/app/routers/hire.py`
- `backend/app/routers/learn.py`
- `backend/app/routers/manager.py`
- `backend/app/safeguards.py`
- `backend/app/serialize.py`
- `backend/app/services/__init__.py`
- `backend/app/services/adaptive.py`
- `backend/app/services/ai.py`
- `backend/app/services/courseware.py`
- `backend/app/services/demo.py`
- `backend/app/services/diagnostic.py`
- `backend/app/services/documents.py`
- `backend/app/services/insights.py`
- `backend/app/services/loader.py`
- `backend/app/services/matching.py`
- `backend/app/services/notify.py`
- `backend/app/services/roles.py`
- `backend/app/services/sync.py`
- `backend/assessment.py`
- `backend/data/sample/divisions.csv`
- `backend/data/sample/documents/documents.json`
- `backend/data/sample/documents/project_lead_job_description.txt`
- `backend/data/sample/documents/project_management_handbook.pdf`
- `backend/data/sample/employees.csv`
- `backend/data/sample/positions.csv`
- `backend/data/sample/training_history.csv`
- `backend/data/sample/training_sessions.csv`
- `backend/data/sample/trainings.csv`
- `backend/data/sample/trainings_esh_training_portal.csv`
- `backend/data/sample/trainings_hpc_training_site.csv`
- `backend/data/sample/trainings_leadership_development.csv`
- `backend/data/sample/trainings_plutonium_facility_training.csv`
- `backend/data/sample/trainings_security_education_portal.csv`
- `backend/prompts.py`
- `backend/pytest.ini`
- `backend/question_bank.py`
- `backend/requirements.txt`
- `backend/scripts/loadtest.py`
- `backend/scripts/make_sample_data.py`
- `backend/scripts/make_sample_handbook.py`
- `backend/scripts/prestart.py`
- `backend/scripts/seed.py`
- `backend/tests/conftest.py`
- `backend/tests/test_access.py`
- `backend/tests/test_diagnostic_api.py`
- `backend/tests/test_frontend_wiring.py`
- `backend/tests/test_learning.py`
- `backend/tests/test_manager_and_data.py`
- `backend/tests/test_role_content.py`
- `backend/tests/test_safeguards.py`
- `backend/tests/test_team_management.py`
- `docs/UI_ORIGINAL_README.md`
- `hire-dashboard/README.md`
- `hire-dashboard/app.js`
- `hire-dashboard/diagnostic.js`
- `hire-dashboard/index.html`
- `hire-dashboard/learning.js`
- `manager-dashboard/README.md`
- `manager-dashboard/app.js`
- `manager-dashboard/index.html`
- `manager-dashboard/roles.js`
- `scripts/build_frontend.py`
- `scripts/extract_knowledge.py`
- `scripts/generate_question_bank.py`
- `scripts/pdf_to_text.py`
- `scripts/requirements.txt`
- `scripts/review_question_bank.py`
- `scripts/run_diagnostic.py`
- `scripts/test_ai_client.py`
- `scripts/test_ai_client_offline.py`
- `scripts/test_assessment.py`
- `scripts/test_knowledge_pipeline.py`
- `scripts/validate_knowledge.py`
- `shared/api.js`
- `shared/assets/apple-touch-icon.png`
- `shared/assets/favicon-32.png`
- `shared/assets/lanl-icon-192.png`
- `shared/assets/lanl-icon.png`
- `shared/assets/lanl-logo-white.svg`
- `shared/assets/lanl-logo.svg`
- `shared/login/index.html`
- `shared/styles.css`
- `tests/fixtures/synthetic_diagnostic.json`

## Complete upstream file dispositions (93 files)

| Upstream file | Combined target / resolution |
|---|---|
| `.dockerignore` | Excluded: no Docker deployment verified; preserve via source commit. |
| `.env.example` | Credential template not read/copied; new empty/placeholder-only template authored locally. |
| `.gitignore` | Combined with existing root rules; added live-data, scale-data, database and runtime exclusions. |
| `Dockerfile` | Excluded: original deployment omits integrated resources/persistence and is not the verified startup. |
| `Ionizing_radiation.json` | Excluded duplicate/empty upstream root artifact; canonical populated JSON is under Resource_File/extracted_knowledge/. |
| `Ionizing_radiation.pdf` | Combined with the existing Resource_File/Ionizing_radiation.pdf; compare hashes below. |
| `README.md` | `docs/UI_ORIGINAL_README.md`: identical |
| `backend/app/__init__.py` | `backend/app/__init__.py`: identical |
| `backend/app/assessment_rules.py` | `backend/app/assessment_rules.py`: identical |
| `backend/app/auth.py` | `backend/app/auth.py`: identical |
| `backend/app/config.py` | `backend/app/config.py`: deliberately combined/adapted; see integration report |
| `backend/app/connectors/__init__.py` | `backend/app/connectors/__init__.py`: identical |
| `backend/app/connectors/base.py` | `backend/app/connectors/base.py`: identical |
| `backend/app/connectors/directory.py` | `backend/app/connectors/directory.py`: identical |
| `backend/app/connectors/oracle_hr.py` | `backend/app/connectors/oracle_hr.py`: identical |
| `backend/app/connectors/utrain.py` | `backend/app/connectors/utrain.py`: identical |
| `backend/app/database.py` | `backend/app/database.py`: identical |
| `backend/app/main.py` | `backend/app/main.py`: deliberately combined/adapted; see integration report |
| `backend/app/models.py` | `backend/app/models.py`: identical |
| `backend/app/routers/__init__.py` | `backend/app/routers/__init__.py`: identical |
| `backend/app/routers/admin.py` | `backend/app/routers/admin.py`: identical |
| `backend/app/routers/auth.py` | `backend/app/routers/auth.py`: identical |
| `backend/app/routers/catalog.py` | `backend/app/routers/catalog.py`: identical |
| `backend/app/routers/content.py` | `backend/app/routers/content.py`: identical |
| `backend/app/routers/hire.py` | `backend/app/routers/hire.py`: identical |
| `backend/app/routers/learn.py` | `backend/app/routers/learn.py`: identical |
| `backend/app/routers/manager.py` | `backend/app/routers/manager.py`: identical |
| `backend/app/safeguards.py` | `backend/app/safeguards.py`: identical |
| `backend/app/serialize.py` | `backend/app/serialize.py`: identical |
| `backend/app/services/__init__.py` | `backend/app/services/__init__.py`: identical |
| `backend/app/services/adaptive.py` | `backend/app/services/adaptive.py`: identical |
| `backend/app/services/ai.py` | `backend/app/services/ai.py`: deliberately combined/adapted; see integration report |
| `backend/app/services/courseware.py` | `backend/app/services/courseware.py`: deliberately combined/adapted; see integration report |
| `backend/app/services/demo.py` | `backend/app/services/demo.py`: identical |
| `backend/app/services/documents.py` | `backend/app/services/documents.py`: identical |
| `backend/app/services/insights.py` | `backend/app/services/insights.py`: identical |
| `backend/app/services/loader.py` | `backend/app/services/loader.py`: identical |
| `backend/app/services/matching.py` | `backend/app/services/matching.py`: identical |
| `backend/app/services/notify.py` | `backend/app/services/notify.py`: identical |
| `backend/app/services/roles.py` | `backend/app/services/roles.py`: identical |
| `backend/app/services/sync.py` | `backend/app/services/sync.py`: identical |
| `backend/data/sample/divisions.csv` | `backend/data/sample/divisions.csv`: identical |
| `backend/data/sample/documents/documents.json` | `backend/data/sample/documents/documents.json`: identical |
| `backend/data/sample/documents/project_lead_job_description.txt` | `backend/data/sample/documents/project_lead_job_description.txt`: identical |
| `backend/data/sample/documents/project_management_handbook.pdf` | `backend/data/sample/documents/project_management_handbook.pdf`: identical |
| `backend/data/sample/employees.csv` | `backend/data/sample/employees.csv`: identical |
| `backend/data/sample/positions.csv` | `backend/data/sample/positions.csv`: identical |
| `backend/data/sample/training_history.csv` | `backend/data/sample/training_history.csv`: identical |
| `backend/data/sample/training_sessions.csv` | `backend/data/sample/training_sessions.csv`: identical |
| `backend/data/sample/trainings.csv` | `backend/data/sample/trainings.csv`: identical |
| `backend/data/sample/trainings_esh_training_portal.csv` | `backend/data/sample/trainings_esh_training_portal.csv`: identical |
| `backend/data/sample/trainings_hpc_training_site.csv` | `backend/data/sample/trainings_hpc_training_site.csv`: identical |
| `backend/data/sample/trainings_leadership_development.csv` | `backend/data/sample/trainings_leadership_development.csv`: identical |
| `backend/data/sample/trainings_plutonium_facility_training.csv` | `backend/data/sample/trainings_plutonium_facility_training.csv`: identical |
| `backend/data/sample/trainings_security_education_portal.csv` | `backend/data/sample/trainings_security_education_portal.csv`: identical |
| `backend/pytest.ini` | `backend/pytest.ini`: identical |
| `backend/requirements.txt` | `backend/requirements.txt`: deliberately combined/adapted; see integration report |
| `backend/scripts/loadtest.py` | `backend/scripts/loadtest.py`: identical |
| `backend/scripts/make_sample_data.py` | `backend/scripts/make_sample_data.py`: identical |
| `backend/scripts/make_sample_handbook.py` | `backend/scripts/make_sample_handbook.py`: identical |
| `backend/scripts/prestart.py` | `backend/scripts/prestart.py`: identical |
| `backend/scripts/seed.py` | `backend/scripts/seed.py`: identical |
| `backend/tests/conftest.py` | `backend/tests/conftest.py`: deliberately combined/adapted; see integration report |
| `backend/tests/test_access.py` | `backend/tests/test_access.py`: identical |
| `backend/tests/test_frontend_wiring.py` | `backend/tests/test_frontend_wiring.py`: deliberately combined/adapted; see integration report |
| `backend/tests/test_learning.py` | `backend/tests/test_learning.py`: identical |
| `backend/tests/test_manager_and_data.py` | `backend/tests/test_manager_and_data.py`: identical |
| `backend/tests/test_role_content.py` | `backend/tests/test_role_content.py`: identical |
| `backend/tests/test_safeguards.py` | `backend/tests/test_safeguards.py`: identical |
| `backend/tests/test_team_management.py` | `backend/tests/test_team_management.py`: identical |
| `deploy/nginx.conf.template` | Excluded with original Docker deployment; no alternate app root introduced. |
| `docker-compose.yml` | Excluded: original multi-replica deployment is outside the verified single-host SQLite diagnostic scope. |
| `docs/ARCHITECTURE.md` | `docs/upstream/ARCHITECTURE.md`: deliberately combined/adapted; see integration report |
| `docs/DATA_INTEGRATION.md` | `docs/upstream/DATA_INTEGRATION.md`: deliberately combined/adapted; see integration report |
| `docs/SCALABILITY.md` | `docs/upstream/SCALABILITY.md`: deliberately combined/adapted; see integration report |
| `hire-dashboard/README.md` | `hire-dashboard/README.md`: identical |
| `hire-dashboard/app.js` | `hire-dashboard/app.js`: deliberately combined/adapted; see integration report |
| `hire-dashboard/index.html` | `hire-dashboard/index.html`: deliberately combined/adapted; see integration report |
| `hire-dashboard/learning.js` | `hire-dashboard/learning.js`: deliberately combined/adapted; see integration report |
| `manager-dashboard/README.md` | `manager-dashboard/README.md`: identical |
| `manager-dashboard/app.js` | `manager-dashboard/app.js`: identical |
| `manager-dashboard/index.html` | `manager-dashboard/index.html`: deliberately combined/adapted; see integration report |
| `manager-dashboard/roles.js` | `manager-dashboard/roles.js`: identical |
| `render.yaml` | Excluded: cloud deployment is not configured/verified in this consolidation. |
| `shared/api.js` | `shared/api.js`: identical |
| `shared/assets/apple-touch-icon.png` | `shared/assets/apple-touch-icon.png`: identical |
| `shared/assets/favicon-32.png` | `shared/assets/favicon-32.png`: identical |
| `shared/assets/lanl-icon-192.png` | `shared/assets/lanl-icon-192.png`: identical |
| `shared/assets/lanl-icon.png` | `shared/assets/lanl-icon.png`: identical |
| `shared/assets/lanl-logo-white.svg` | `shared/assets/lanl-logo-white.svg`: identical |
| `shared/assets/lanl-logo.svg` | `shared/assets/lanl-logo.svg`: identical |
| `shared/login/index.html` | `shared/login/index.html`: identical |
| `shared/styles.css` | `shared/styles.css`: identical |
