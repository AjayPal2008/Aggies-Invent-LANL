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

### Where the AI's material comes from

Every library course has at least one document the AI reads; none is left with only the extrain.lanl.gov home page.

| Source | Used for |
|---|---|
| LANL public files (cdn.lanl.gov): White Rock Training Center student manuals, NFO brochures, the LANL Code of Conduct | Role and hazard courses, NFO, ethics |
| DOE orders, guides and handbooks (energy.gov): O 470.5A insider threat, O 470.7 safeguards and security, O 471.6 information security, O 471.7 CUI, O 471.1B UCNI, O 232.2A occurrence reporting, O 422.1 conduct of operations, O 414.1E quality assurance, O 413.3C project management, DOE-HDBK-1130-2022 radiological worker training, the HQ-111DE security briefing, EVM tutorial | Institutional security courses, GERT and Rad Worker, CONOPS, QA, project management |
| Federal regulations (govinfo.gov): 10 CFR 707, 810, 835, 850, 1017; 15 CFR 730; 32 CFR 2002 | Substance abuse, foreign technology transfer, radiation protection, beryllium, UCNI, export control, CUI |
| OPM supervisory training (opm.gov) | Difficult conversations, mentoring, new supervisors |
| DOE computing-center docs (NERSC, OLCF) and NumPy, Python, scikit-learn, MPI Forum | HPC onboarding, MPI, Python, machine learning |

These are the public documents LANL's own courses are based on; LANL's internal course content may differ. The
`extra_materials` section of `backend/data/library/catalog.json` lists them, and only these official hosts can be
downloaded (https, no query strings, redirects only to the same hosts). Web pages are stored as readable text.

Run `python -m scripts.import_library` (in Docker: `docker compose exec -T app python -m scripts.import_library`) to
download everything and build draft lessons. Lessons are built offline unless an Anthropic API key is set; with a key,
`--ai` builds them with Claude, and every learner's lesson, video script, quiz and interview is written by Claude
from these pages either way.

### The shared library folder (team files)

`Resource_File/library/` is committed to git so everyone has the same files. Each file in `<TRAINING-CODE>/` is
imported into that training on startup; files in `unassigned/` appear under **Unassigned** for an admin to place.
To share files you uploaded through the admin page on your computer, run `python -m scripts.export_library`, then
commit `Resource_File/library` and push. Only add files the team may share in the repository.

### Draft lessons and publishing

Built lessons are drafts until an admin publishes them. The banner at the top of the library shows how many are
published, waiting, or not built yet, with **Build missing lessons** and **Review & publish drafts** (tick the
trainings you checked, confirm, publish). Rebuilding never touches published lessons unless an admin rebuilds that
training. Until a training is published, a learner's lessons for it still draw on its source text.

### Managing each material (admin)

Every material in a training's detail window has its own buttons:

- **Open** the stored copy.
- **Rename** it.
- **Replace file** to upload a newer version (PDF, .pptx, .docx, .txt, .md). A catalog PDF keeps its LANL link, so the next sync doesn't add the old one back. Rebuild lessons afterwards.
- **Re-download** fetches the official PDF again from cdn.lanl.gov, for when LANL publishes a new revision.
- **Delete** removes it. Uploads are deleted; catalog PDFs are hidden and not re-added or re-downloaded by later syncs. Lessons already built stay until you rebuild.

## Role directory (managers)

*Roles → Role directory* lists every library role, searchable by title or skill and filterable by division. Opening a role shows:

- the job description (summary, full text the admin pastes in, and any job description files on its positions)
- the positions that use the role in that division, with level, years and prerequisites
- the skills it needs, combined from the role, its positions and its trainings
- **Trainings to assign**, grouped as institutional, division and role, with when each is due, its type, assessment and length

Pick *New hire*, *Promotion within the division* or *Moving from another division* and the list updates. Untick anything you want to leave out, then **Assign to people…** (optionally moving them into one of the role's positions), **Copy list** or **Print**. Trainings a person already has open are left as they are.

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
| `PATCH /api/library/materials/{id}` | Rename a material |
| `POST /api/library/materials/{id}/file` | Replace a material's file |
| `POST /api/library/materials/{id}/refresh` | Download a linked LANL PDF again |
| `DELETE /api/library/materials/{id}` | Delete a material |
| `GET /api/library/roles/{key}/detail?program=` | Role page: job description, skills, positions and the list for each entry path |
| `POST /api/library/roles/{key}/assign` | Assign a role's list to people (`entry_path`, `exclude`, optional `position_code`) |
| `POST /api/library/build-all` | Build draft lessons for every training with material but no lessons |
| `POST /api/library/publish-all` | `{reviewed: true, codes: [...]}` publishes those drafts |
| `POST /api/library/materials/{id}/place` | Attach an unassigned material to a training |
| `POST /api/library/trainings/{code}/build` | Build lessons from the training's materials |
| `GET /api/library/trainings/{code}/modules` | Review built modules (admin) |
| `POST /api/library/trainings/{code}/publish` | `{reviewed: true, publish: true}` publishes; `{publish: false}` returns to draft |
| `POST /api/library/divisions/{program}/requirements`, `DELETE /api/library/divisions/requirements/{id}` | Division requirements |
| `GET/POST /api/library/roles`, `PATCH /api/library/roles/{key}`, `POST /api/library/roles/{key}/requirements`, `DELETE /api/library/roles/requirements/{id}` | Roles and their technical / soft-skill requirements, shared or per division |
| `PATCH /api/library/positions/{code}` | Map a position to a library role |
| `POST /api/library/path` | What a division + role + entry path would get |
| `POST /api/library/annual-cycle` | Assign annual institutional courses, staggered |

Admins edit; managers can read the library and map positions.
