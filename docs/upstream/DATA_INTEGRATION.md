> Upstream reference from origin/main at cf16ec0. Describes the colleague's original system, not verified capabilities or deployment guarantees of this consolidation. Root README.md is authoritative; no .env files are loaded.

# Connecting real LANL data

The platform reads three sources. Each connector has a **file** mode (CSV or JSON exports in `DATA_DIR`) and a **live** mode (calls the system directly). Start with file mode: export, drop the files in a folder, point `DATA_DIR` at it, and sync.

```bash
DATA_DIR=/secure/path/lanl-exports ../.venv/bin/python -m scripts.seed
```

Or upload files on the manager dashboard's **Data sources** page (admin only), which saves them to `DATA_DIR` and syncs.

Syncing is safe to repeat. Rows match on natural keys (division code, position code, course code, employee number), so a nightly sync updates records instead of duplicating them.

## Files

| File | From | Required columns | Useful columns |
| --- | --- | --- | --- |
| `divisions.csv` | Directory | `code` | name, parent_code, directorate, leader_email |
| `positions.csv` | Directory / HR | `code` | title, division_code, level, min_years, required_skills, required_trainings, prerequisites, is_open, fiscal_year, headcount, hiring_manager_email |
| `trainings.csv` | UTrain | `code` | title, description, category, required, delivery, source_url, duration_minutes, validity_months, skills, prerequisites, job_roles, equipment, facilities, outline |
| `trainings_<site>.csv` | Any other training site | `code` | same as above; the site name comes from the file name unless a `source_system` column is present |
| `training_sessions.csv` | UTrain | training_code, starts_at | ends_at, location, instructor, capacity |
| `employees.csv` | Oracle HR | employee_number, email | name, job_title, position_code, division_code, level, hire_date, years_experience, salary, performance_rating, manager_number, is_manager, skills, background, learning_style |
| `training_history.csv` | UTrain / HR | employee_number, training_code | status, completed_on, due_date, score, attempts |

Lists (skills, prerequisites, roles) can be separated with `;` or `,`.

## Column names don't have to match

Each connector recognizes common variants: `Emp_No`, `Employee ID` and `Z Number` all become `employee_number`; `Work Email` becomes `email`; `Reports To` becomes the manager; `Course ID` becomes the training code; `Mandatory` becomes required; `Classroom` / `ILT` delivery becomes in person; dates like `03/15/2024`, `2024-03-15` and `15-MAR-24` are all read. Salaries like `$120,000` are parsed.

For anything else, add `mapping.json` next to the files:

```json
{
  "employees": { "PERSON_NUM": "employee_number", "PRIMARY_EMAIL": "email", "SUPV_NUM": "manager_number" },
  "trainings": { "Course #": "code", "Name of Course": "title" }
}
```

Keys are entity names (`divisions`, `positions`, `trainings`, `training_sessions`, `employees`, `training_history`), values map source column to canonical field.

## Live mode

| Source | Settings | What it calls |
| --- | --- | --- |
| Directory | `DIRECTORY_MODE=live`, `DIRECTORY_API_URL`, `DIRECTORY_API_TOKEN` | `GET /divisions`, `GET /positions` (JSON lists). Swap in LDAP in `connectors/directory.py` if that's how the directory is exposed. |
| UTrain | `UTRAIN_MODE=live`, `UTRAIN_API_URL`, `UTRAIN_API_TOKEN` | `GET /courses`, `GET /sessions` |
| Oracle HR | `ORACLE_MODE=live`, `ORACLE_DSN`, `ORACLE_USER`, `ORACLE_PASSWORD`, `ORACLE_EMPLOYEE_QUERY` | Runs the query with `python-oracledb` (`pip install oracledb`). Point it at a read-only HR view. |

Live responses go through the same aliasing and `mapping.json`, so a slightly different shape still works.

## Roles

- Anyone who manages someone (appears as another employee's manager, or `is_manager` is true) gets the manager dashboard.
- Emails in `ADMIN_EMAILS` get admin.
- Everyone else is a hire.

## Sensitive data

Salary and performance ratings are only returned to managers in their own reporting chain and to admins. Keep real exports out of git (the `.gitignore` already excludes `backend/data/live/`), and use PostgreSQL with encryption at rest for anything beyond a demo.
