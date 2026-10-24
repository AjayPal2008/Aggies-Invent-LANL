# Manager dashboard (Nick)

Served at `/manager/`. Plain HTML + ES modules, no build step. Edit `app.js` and refresh.

- `index.html`: page shell and sidebar. Add a `<button data-view="name">` to add a page.
- `roles.js`: the **Role plans** and **Interview reviews** pages (documents, AI-built courses, plan editor, start people in a role, review recordings and scores).
- `app.js`: one function per page (`overview`, `team`, `assign`, `retraining`, `insights`, `roles`, `promotions`, `data`), registered at the bottom with `router({...})`.
- Shared pieces come from `/shared/api.js` (API client, `modal`, `toast`, `bar`, `statusBadge`, date helpers) and `/shared/styles.css`.

Only managers and admins can open this page; hires are redirected to `/hire/`, and every `/api/manager/*` call is checked on the server too.

Endpoints used (full list at `/docs`):

| Endpoint | Page |
| --- | --- |
| `GET /api/manager/overview` | Overview KPIs, status, headcount by fiscal year |
| `GET /api/manager/team?q&under&direct_only&new_hires_only&min_level&max_level&fiscal_year_hired&sort` | Team table and ranking (`under` = one team lead's sub-team) |
| `GET /api/manager/org` | Sub-team cards with roll-ups |
| `GET /api/manager/team.csv` | Export |
| `GET /api/manager/team/{id}` | Read-only hire view |
| `PATCH /api/manager/assignments/{id}` | Change one due date |
| `POST /api/manager/assignments/bulk-due-date`, `/bulk-remove`, `/role-requirements` | Bulk actions on selected people |
| `POST /api/manager/assignments` / `DELETE /api/manager/assignments/{id}` | Assign / remove trainings |
| `GET /api/manager/retraining?days=` | Expiring and retakes |
| `POST /api/manager/reminders` | Email reminders (`send: false` previews) |
| `GET /api/manager/insights/heatmap?group_by=position|equipment`, `GET /api/manager/insights/compliance` | Compliance and gaps |
| `GET /api/manager/positions`, `GET /api/manager/positions/{code}/candidates` | Open roles and candidates |
| `GET /api/manager/promotions` | Promotion readiness |
| `POST /api/manager/team/{id}/infer-skills` | AI skill estimate |
| `/api/admin/*` | Data sources page (admin only) |
| `GET/POST /api/manager/roles`, `PATCH /api/manager/roles/{code}` | Role list, create, edit |
| `POST /api/manager/documents` (multipart), `GET /api/manager/documents?position_code=`, `POST /{id}/build`, `DELETE /{id}` | Upload and manage role documents |
| `POST /api/manager/roles/{code}/analyze` | Job description analysis and suggested plan |
| `GET/PUT /api/manager/roles/{code}/plan` | Role plan |
| `POST /api/manager/roles/{code}/preview`, `/start` | Tailored plan per person; move them into the role |
| `GET /api/manager/people/search?q=` | Find anyone at LANL to bring into a role |
| `GET /api/manager/interviews`, `GET /{id}`, `POST /{id}/review`, `GET /responses/{id}/audio` | Interview reviews |
