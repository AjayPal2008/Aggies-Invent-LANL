# Hire dashboard (AJ)

Served at `/hire/`. Plain HTML + ES modules, no build step. Edit `app.js` and refresh.

- `index.html`: page shell and sidebar. Add a `<button data-view="name">` to add a page.
- `app.js`: one function per page (`overview`, `trainings`, `calendar`, `studioView`, `catalog`, `profile`), registered at the bottom with `router({...})`.
- `learning.js`: the video player, the interview-style assessment flow (typed or recorded answers with live transcription) and the role plan card.
- Lesson sections render by `kind`: `text`, `visual` (diagram steps), `simulation` (scenario + choices), `exercise` (checklist), `check`. Every interaction posts to `/api/me/answer`, which is what makes the next lesson adapt.

Endpoints used (full list at `/docs`):

| Endpoint | Used for |
| --- | --- |
| `GET /api/me/dashboard` | Overview: summary, buckets, path, gaps, learner profile |
| `GET /api/me/assignments?category&required&status&flag&sort` | My trainings list |
| `GET /api/me/calendar?start&end` | Calendar events (due, registered, available classes) |
| `POST /api/me/assignments/{id}/register` | Register for a class |
| `POST /api/me/assignments/{id}/progress` | Save progress |
| `POST /api/me/trainings/{code}/lesson` | Generate a lesson (`request`, `modality`, `difficulty` optional) |
| `POST /api/me/trainings/{code}/practice` | Practice questions |
| `POST /api/me/answer` | Record an answer, simulation choice or exercise |
| `POST /api/me/assignments/{id}/assessment`, `POST /api/me/assessments/{id}/submit` | Graded assessment |
| `POST /api/me/tutor` | Tutor chat |
| `PATCH /api/me/profile` | Learning style |
| `GET /api/trainings`, `GET /api/trainings/sources`, `GET /api/trainings/{code}` | Catalog |
| `GET /api/me/role-plan` | Role plan card on the overview |
| `GET /api/me/trainings/{code}/modules`, `POST /api/me/modules/{id}/lesson`, `POST /api/me/modules/{id}/complete` | Courses built from documents |
| `POST /api/me/trainings/{code}/video` | Video lesson for a catalog training |
| `POST /api/me/assignments/{id}/interview`, `POST /api/me/interviews/{id}/responses` (multipart, optional audio), `POST /{id}/submit`, `GET /{id}` | Interview-style assessment |
