# Training library (admin)

The library holds every training LANL requires and the source material the AI builds lessons from. It mirrors how UTrain assigns training in three layers.

| Layer | Who gets it | Examples (public LANL sources) |
| --- | --- | --- |
| **Institutional** | Everyone at LANL, regardless of role, level or experience. New hires take the onboarding courses once; annual courses repeat for everyone. | Initial Security Training (62676), Annual Security Refresher Briefing (1425), Initial Information Security Briefing (9369) and its refresher (47075), DOE Insider Threat Awareness (31112), LANL Ethics Training (27392), Substance Abuse Policy (42095), Incident Reporting and Protective Actions (10922), Export Control Fundamentals (21208) and Annual Refresher (52144), from [extrain.lanl.gov](https://extrain.lanl.gov/) |
| **Division** | Everyone in one of LANL's three program areas: **Weapons**, **Science, Technology & Engineering**, **Operations**. | Weapons: Nuclear Fundamentals Orientation Modules 1–2, Classified Matter Protection (16028), Protecting UCNI (22925) |
| **Role** | Everyone entering a role: technical and soft-skill training. Roles are defined once and shared across divisions, with division-specific additions. | Project Lead: Project Management Fundamentals, Earned Value, QA, Leading Difficult Conversations, Mentoring; in Weapons also NFO Module 3. Craft worker: Ladder, Fall Protection, Confined Space Awareness, Forklift, Crane (White Rock Training Center, [lanl.gov/engage/training/its](https://www.lanl.gov/engage/training/its)) |

## New hires vs internal moves

| Entering a role as | Institutional | Division | Role |
| --- | --- | --- | --- |
| New hire (new to LANL) | ✓ onboarding courses | ✓ | ✓ |
| Internal promotion or transfer, same division | — continues on the annual cycle | — already done | ✓ |
| Internal move from another division | — continues on the annual cycle | ✓ the new division's | ✓ |

Refresher courses (e.g. 47075 refreshes 9369) are never part of onboarding; they come round on the annual cycle. Anything already completed and current is skipped, and experienced people can test out of items with a years-of-experience threshold. Managers preview each person's plan before confirming (**Role plans → Start people in this role**), and anyone can preview a division + role + entry path in **Training library → Plan preview**.

Divisions from the directory map to a program through their directorate (e.g. ALDWE → Weapons, ALDSCT → STE, ALDFO → Operations). Positions map to a library role by title, or explicitly (`PATCH /api/library/positions/{code}`).

## Materials and lessons

- Each training lists its materials: public PDFs linked from LANL's pages, plus anything an admin uploads (PDF, PowerPoint `.pptx`, Word `.docx`, text).
- **Import** downloads linked PDFs into the admin library and extracts their text. Only `https://cdn.lanl.gov/files/*.pdf` is fetched, with no redirects, a size limit, a PDF signature check and SHA-256 de-duplication (adapted from AJ's ITS importer). Files go to `UPLOAD_DIR`, never into git; original document terms apply and no redistribution license is inferred.
- **Build lessons** turns the training's richest material into modules, video lessons, quizzes and interview scenarios (Claude with an API key; a structure-based offline builder without one). The modules attach to the training itself, so its title, layer, schedule and assessment type stay as the admin set them.
- **Review & publish.** Built lessons start as a draft that learners can't see (no modules, no document quiz). An admin opens *Review & publish*, checks each module's summary and key points against the source pages, ticks the confirmation and publishes. Rebuilding puts the training back into draft. Publishing can be reversed with *Take back to draft*.
- The 43 public PDFs in the library come to about 3,200 pages.

```bash
cd backend
../.venv/bin/python -m scripts.import_library          # import all linked PDFs (about 250 MB)
../.venv/bin/python -m scripts.import_library --build  # and build offline lessons for each
```

## Annual cycle

**Run annual cycle** assigns this year's annual institutional courses to everyone who isn't current, spreading due dates over up to 8 weeks before the deadline so 20,000 people don't all log in the same night. Running it twice doesn't duplicate anything.

## What is and isn't official

Course titles, numbers and material links come from public LANL pages. The **division and role assignments are draft defaults** for the prototype, not LANL's official training matrices: LANL asks employees to get their local matrix from their Group Training Coordinator or Division Administrator. Admins edit every assignment in the library. The sample courses used by roles (for example PM-200 or COM-320) are fictional placeholders until real division courses are added.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/library` | Everything: counts, programs with divisions and requirements, trainings with materials, roles |
| `POST /api/library/trainings`, `PATCH /api/library/trainings/{code}` | Create / edit a training (layer, audience, frequency, assessment type) |
| `POST /api/library/materials/import` | Import linked public PDFs (all, or one training) |
| `POST /api/library/trainings/{code}/materials` | Upload a PDF, `.pptx`, `.docx` or text |
| `POST /api/library/trainings/{code}/build` | Build lessons from the training's materials |
| `GET /api/library/trainings/{code}/modules` | Review built modules (admin) |
| `POST /api/library/trainings/{code}/publish` | `{reviewed: true, publish: true}` publishes; `{publish: false}` returns to draft |
| `POST /api/library/divisions/{program}/requirements`, `DELETE /api/library/divisions/requirements/{id}` | Division requirements |
| `GET/POST /api/library/roles`, `PATCH /api/library/roles/{key}`, `POST /api/library/roles/{key}/requirements`, `DELETE /api/library/roles/requirements/{id}` | Roles and their technical / soft-skill requirements, shared or per division |
| `PATCH /api/library/positions/{code}` | Map a position to a library role |
| `POST /api/library/path` | What a division + role + entry path would get |
| `POST /api/library/annual-cycle` | Assign annual institutional courses, staggered |

Admins edit; managers can read the library and map positions.
