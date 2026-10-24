"""Central settings. Everything can be overridden with environment variables or a .env file."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"), extra="ignore")

    app_name: str = "LANL Adaptive Training Platform"
    frontend_dir: str = str(REPO_DIR)  # Set FRONTEND_DIR to dist for the built bundle (scripts/build_frontend.py).
    database_url: str = f"sqlite:///{BACKEND_DIR / 'lanl_training.db'}"
    # Connection pool per worker process (PostgreSQL). Total connections = workers x replicas x (pool + overflow).
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 10  # seconds to wait for a free connection before failing fast
    # Load sample data on first start. Turn off when several workers start at once (Docker runs scripts.prestart instead).
    auto_seed: bool = True

    # Auth
    jwt_secret: str = "change-me-in-production-use-a-long-random-string"
    jwt_expire_minutes: int = 60 * 8
    allowed_email_domains: str = "lanl.gov"  # comma separated
    google_client_id: str = ""  # set to enable Google sign-in
    demo_password: str = "demo1234"  # password given to seeded demo accounts
    admin_emails: str = "admin@lanl.gov"  # comma separated; these accounts can run syncs and uploads

    # AI
    anthropic_api_key: str = ""
    # Source-grounded diagnostic (AJ's engine). The reviewed bank stays out of git.
    diagnostic_bank_path: str = str(REPO_DIR / "Resource_File" / "cache" / "assessment" / "bank.json")
    # Empty = store diagnostic sessions in the platform database (DATABASE_URL). A path keeps a separate SQLite file.
    diagnostic_db_path: str = ""
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"

    # Connectors: "file" reads CSV/JSON exports, "live" calls the real system.
    data_dir: str = str(BACKEND_DIR / "data" / "sample")
    directory_mode: str = "file"
    directory_api_url: str = ""
    directory_api_token: str = ""

    utrain_mode: str = "file"
    utrain_api_url: str = ""
    utrain_api_token: str = ""

    oracle_mode: str = "file"
    oracle_dsn: str = ""
    oracle_user: str = ""
    oracle_password: str = ""
    oracle_employee_query: str = (
        "SELECT employee_id, email, full_name, job_title, division_code, job_level, "
        "hire_date, years_experience, salary, performance_rating, manager_id, is_manager "
        "FROM hr_employees_v"
    )

    # Email reminders: preview | resend | smtp
    public_url: str = "http://localhost:8000"
    email_mode: str = "preview"
    email_from: str = "LANL Training <training@lanl.gov>"
    resend_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # Uploaded documents and interview recordings
    upload_dir: str = str(BACKEND_DIR / "uploads")
    max_upload_mb: int = 60

    # Traffic safeguards
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 240  # normal API calls per signed-in user
    rate_limit_ai_per_minute: int = 20  # AI generation calls per user (lessons, videos, practice, tutor, interviews)
    rate_limit_login_per_minute: int = 10  # login attempts per IP address
    ai_max_concurrent: int = 8  # AI calls in flight per worker; extra requests get offline content instead of waiting
    ai_queue_wait_seconds: float = 3.0
    ai_breaker_failures: int = 5  # consecutive AI failures that pause AI calls
    ai_breaker_seconds: int = 60
    max_builds_concurrent: int = 2  # document-to-course builds at once per worker

    # Training policy
    pass_score: float = 80.0
    mastery_threshold: float = 0.7
    retake_window_days: int = 14
    interview_pass: float = 5.5  # out of 9, like CASPer-style scales

    @property
    def email_domains(self) -> list[str]:
        return [d.strip().lower() for d in self.allowed_email_domains.split(",") if d.strip()]


settings = Settings()
