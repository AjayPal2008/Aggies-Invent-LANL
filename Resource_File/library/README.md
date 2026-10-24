# Shared training library folder

Every file here is imported into the admin **Training library** when the app starts, on every computer, so the
whole team has the same materials. The AI builds each training's lessons, videos, quizzes and interview
scenarios from them.

- Put a file in the folder named after its training code: `UT-4464/HAZWOPER refresher.pdf`, `PM-200/Project handbook.pptx`.
- Not sure which training? Put it in `unassigned/`. An admin places it from **Library → Training library → Unassigned**.
- Accepted: `.pdf`, `.pptx`, `.docx`, `.txt`, `.md`. Scanned PDFs need OCR first.
- To copy everything uploaded through the admin page on your computer into this folder:
  `docker compose exec -T app python -m scripts.export_library` (Docker) or
  `cd backend && ../.venv/bin/python -m scripts.export_library`, then commit and push.

Only add material the team is allowed to share in this repository: public documents or internal material cleared
for the project. Public LANL, DOE and federal sources the catalog links to are downloaded on demand instead
(`python -m scripts.import_library`) and are not stored here.
