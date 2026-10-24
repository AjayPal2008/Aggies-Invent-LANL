"""Database tables.

Source of truth for each table:
  Division, Position          <- LANL organizational directory
  Training, TrainingSession   <- UTrain and the other LANL training sites
  Employee                    <- Oracle HR (title, salary, performance, experience)
  Assignment ... LearningEvent <- owned by this platform
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class Division(Base):
    __tablename__ = "divisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    parent_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    directorate: Mapped[str | None] = mapped_column(String(200), nullable=True)
    leader_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    program: Mapped[str | None] = mapped_column(String(16), nullable=True)  # weapons | ste | operations


class Position(Base):
    """A job role. `is_open` marks roles a manager needs filled."""

    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    division_code: Mapped[str] = mapped_column(String(32), index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    min_years: Mapped[float] = mapped_column(Float, default=0)
    required_skills: Mapped[list] = mapped_column(JSON, default=list)
    required_trainings: Mapped[list] = mapped_column(JSON, default=list)  # training codes
    prerequisites: Mapped[list] = mapped_column(JSON, default=list)  # free-text (degrees, clearances)
    is_open: Mapped[bool] = mapped_column(Boolean, default=False)
    hiring_manager_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    headcount: Mapped[int] = mapped_column(Integer, default=1)
    library_role: Mapped[str | None] = mapped_column(String(48), nullable=True)  # training library role key


class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    job_title: Mapped[str] = mapped_column(String(200), default="")
    position_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    division_code: Mapped[str] = mapped_column(String(32), index=True, default="")
    level: Mapped[int] = mapped_column(Integer, default=1)
    hire_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    years_experience: Mapped[float] = mapped_column(Float, default=0)
    salary: Mapped[float | None] = mapped_column(Float, nullable=True)
    performance_rating: Mapped[float | None] = mapped_column(Float, nullable=True)  # 1-5
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default="hire")  # hire | manager | admin
    password_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    learning_style: Mapped[str] = mapped_column(String(32), default="unknown")
    skills: Mapped[dict] = mapped_column(JSON, default=dict)  # skill -> 0..1 confidence
    background: Mapped[str] = mapped_column(Text, default="")  # resume / prior experience text
    # How they came into their current role; decides which onboarding they get.
    entry_path: Mapped[str | None] = mapped_column(String(16), nullable=True)  # new_hire | promotion | transfer
    previous_position_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    role_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Personal accessibility settings (text size, contrast, captions, extra time...). Only the person sees these.
    accessibility: Mapped[dict] = mapped_column(JSON, default=dict)

    manager: Mapped["Employee | None"] = relationship(remote_side="Employee.id")
    assignments: Mapped[list["Assignment"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan", foreign_keys="Assignment.employee_id")

    @property
    def is_new_hire(self) -> bool:
        return bool(self.hire_date and (date.today() - self.hire_date).days <= 365)


class Training(Base):
    __tablename__ = "trainings"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="technical")  # safety|technical|culture|compliance
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery: Mapped[str] = mapped_column(String(16), default="online")  # online|in_person|hybrid
    source_system: Mapped[str] = mapped_column(String(64), default="UTrain")
    source_url: Mapped[str] = mapped_column(String(500), default="")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    validity_months: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = never expires
    skills: Mapped[list] = mapped_column(JSON, default=list)
    prerequisites: Mapped[list] = mapped_column(JSON, default=list)  # training codes
    job_roles: Mapped[list] = mapped_column(JSON, default=list)  # position codes or titles
    equipment: Mapped[list] = mapped_column(JSON, default=list)
    facilities: Mapped[list] = mapped_column(JSON, default=list)
    outline: Mapped[str] = mapped_column(Text, default="")  # topics, one per line
    # quiz for technical skills; situational = interview-style scenarios (CASPer/MMI); both = quiz then interview
    assessment_type: Mapped[str] = mapped_column(String(16), default="quiz")
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)  # set for AI-built courses
    # Training library (admin): which layer requires it, who it applies to, how often it repeats.
    layer: Mapped[str | None] = mapped_column(String(16), nullable=True)  # institutional | division | role
    audience: Mapped[str] = mapped_column(String(16), default="all")  # all | new_hire (initial onboarding only)
    frequency: Mapped[str] = mapped_column(String(16), default="once")  # once | annual
    course_number: Mapped[str] = mapped_column(String(32), default="")  # UTrain course number
    refresher_of: Mapped[str | None] = mapped_column(String(32), nullable=True)  # code of the initial course this refreshes
    # Lessons built from library materials stay drafts until an admin reviews and publishes them.
    lessons_status: Mapped[str] = mapped_column(String(16), default="published")  # draft | published

    sessions: Mapped[list["TrainingSession"]] = relationship(back_populates="training", cascade="all, delete-orphan")


class TrainingSession(Base):
    """A scheduled in-person or live class."""

    __tablename__ = "training_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    training_id: Mapped[int] = mapped_column(ForeignKey("trainings.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    location: Mapped[str] = mapped_column(String(200), default="")
    instructor: Mapped[str] = mapped_column(String(200), default="")
    capacity: Mapped[int] = mapped_column(Integer, default=20)

    training: Mapped[Training] = relationship(back_populates="sessions")


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("employee_id", "training_id", name="uq_assignment"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    training_id: Mapped[int] = mapped_column(ForeignKey("trainings.id"), index=True)
    assigned_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="not_started")  # not_started|in_progress|completed
    progress: Mapped[float] = mapped_column(Float, default=0)  # 0..100
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_retraining: Mapped[date | None] = mapped_column(Date, nullable=True)
    best_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    needs_retake: Mapped[bool] = mapped_column(Boolean, default=False)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("training_sessions.id"), nullable=True, index=True)
    difficulty: Mapped[str] = mapped_column(String(16), default="intro")  # intro|intermediate|advanced

    employee: Mapped[Employee] = relationship(back_populates="assignments", foreign_keys=[employee_id])
    training: Mapped[Training] = relationship()
    session: Mapped[TrainingSession | None] = relationship()
    attempts_log: Mapped[list["AssessmentAttempt"]] = relationship(back_populates="assignment", cascade="all, delete-orphan")


class AssessmentAttempt(Base):
    __tablename__ = "assessment_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    taken_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    skill_scores: Mapped[dict] = mapped_column(JSON, default=dict)  # skill -> fraction correct
    kind: Mapped[str] = mapped_column(String(16), default="quiz")  # quiz | interview

    assignment: Mapped[Assignment] = relationship(back_populates="attempts_log")


class Mastery(Base):
    """Per-skill knowledge estimate (Bayesian Knowledge Tracing)."""

    __tablename__ = "mastery"
    __table_args__ = (UniqueConstraint("employee_id", "skill", name="uq_mastery"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    skill: Mapped[str] = mapped_column(String(100))
    p_known: Mapped[float] = mapped_column(Float, default=0.2)
    observations: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LearningEvent(Base):
    """Every interaction the adaptive engine learns from."""

    __tablename__ = "learning_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    training_id: Mapped[int | None] = mapped_column(ForeignKey("trainings.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))  # lesson|answer|chat|assessment|feedback
    modality: Mapped[str | None] = mapped_column(String(32), nullable=True)  # text|visual|simulation|quiz|exercise
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)


class Document(Base):
    """An uploaded job description, role requirements file or internal manual (PDF/text)."""

    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(300), default="")
    kind: Mapped[str] = mapped_column(String(32), default="manual")  # job_description | requirements | manual | policy | procedure
    position_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    words: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="uploaded")  # uploaded|extracted|generating|ready|failed
    error: Mapped[str] = mapped_column(Text, default="")
    generated_by: Mapped[str] = mapped_column(String(64), default="")
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)  # job description analysis results
    training_code: Mapped[str | None] = mapped_column(String(32), nullable=True)  # library training this material belongs to

    page_texts: Mapped[list["DocumentPage"]] = relationship(cascade="all, delete-orphan", order_by="DocumentPage.page")


class DocumentPage(Base):
    __tablename__ = "document_pages"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")


class CourseModule(Base):
    """One module of a course the AI built from a document."""

    __tablename__ = "course_modules"
    id: Mapped[int] = mapped_column(primary_key=True)
    training_id: Mapped[int] = mapped_column(ForeignKey("trainings.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    page_start: Mapped[int] = mapped_column(Integer, default=1)
    page_end: Mapped[int] = mapped_column(Integer, default=1)
    objectives: Mapped[list] = mapped_column(JSON, default=list)
    key_points: Mapped[list] = mapped_column(JSON, default=list)
    skills: Mapped[list] = mapped_column(JSON, default=list)


class LessonCache(Base):
    """Generated lesson/video content, reused for learners at the same level and style."""

    __tablename__ = "lesson_cache"
    __table_args__ = (UniqueConstraint("module_id", "modality", "difficulty", name="uq_lesson_cache"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("course_modules.id"), index=True)
    modality: Mapped[str] = mapped_column(String(16))
    difficulty: Mapped[str] = mapped_column(String(16))
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Scenario(Base):
    """A workplace situation used in interview-style assessments."""

    __tablename__ = "scenarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    training_id: Mapped[int] = mapped_column(ForeignKey("trainings.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    situation: Mapped[str] = mapped_column(Text)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    competencies: Mapped[list] = mapped_column(JSON, default=list)
    strong_response: Mapped[list] = mapped_column(JSON, default=list)  # what a strong answer considers
    red_flags: Mapped[list] = mapped_column(JSON, default=list)
    source_pages: Mapped[str] = mapped_column(String(64), default="")


class RolePlanItem(Base):
    """One training in a role's curated plan, with who it applies to and when."""

    __tablename__ = "role_plan_items"
    __table_args__ = (UniqueConstraint("position_code", "training_code", name="uq_role_plan"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    position_code: Mapped[str] = mapped_column(String(32), index=True)
    training_code: Mapped[str] = mapped_column(String(32))
    phase: Mapped[int] = mapped_column(Integer, default=2)  # 1 = first 2 weeks, 2 = first 30 days, 3 = first 90 days
    audience: Mapped[str] = mapped_column(String(16), default="all")  # all | new_hire | internal | promotion | transfer
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    skip_if_years_at_least: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")


class InterviewSession(Base):
    """A situational (CASPer/MMI-style) assessment attempt."""

    __tablename__ = "interview_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    scenario_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="in_progress")  # in_progress | submitted | scored | reviewed
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    overall: Mapped[float | None] = mapped_column(Float, nullable=True)  # 1-9
    competency_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    feedback: Mapped[dict] = mapped_column(JSON, default=dict)
    scored_by: Mapped[str] = mapped_column(String(64), default="")
    manager_overall: Mapped[float | None] = mapped_column(Float, nullable=True)
    manager_notes: Mapped[str] = mapped_column(Text, default="")
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    # Readiness after the interview: ready | ready_with_support | not_ready, a 0-100 score, and the reasons
    readiness: Mapped[str | None] = mapped_column(String(24), nullable=True)
    readiness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    readiness_detail: Mapped[dict] = mapped_column(JSON, default=dict)

    responses: Mapped[list["InterviewResponse"]] = relationship(cascade="all, delete-orphan", order_by="InterviewResponse.id")
    assignment: Mapped[Assignment] = relationship()


class InterviewResponse(Base):
    __tablename__ = "interview_responses"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id"))
    question_index: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(8), default="text")  # text | audio
    transcript: Mapped[str] = mapped_column(Text, default="")
    audio_path: Mapped[str] = mapped_column(String(500), default="")
    seconds_used: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 1-9
    feedback: Mapped[str] = mapped_column(Text, default="")


class ContentCache(Base):
    """Generated content shared by everyone at the same level and style (catalog lessons, videos, practice sets).

    At a lab-wide deadline thousands of people take the same training; this turns thousands of AI
    calls into a handful.
    """

    __tablename__ = "content_cache"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TrainingMaterial(Base):
    """A PDF, slide deck, video or link attached to a library training. The AI builds lessons from these."""

    __tablename__ = "training_materials"
    __table_args__ = (UniqueConstraint("training_code", "url", name="uq_material_url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    training_code: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="pdf")  # pdf | pptx | docx | video | link
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(600), default="")  # original public source, if any
    status: Mapped[str] = mapped_column(String(16), default="linked")  # linked | imported | failed | uploaded
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)  # local copy, text extracted
    sha256: Mapped[str] = mapped_column(String(64), default="")
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")


class DivisionRequirement(Base):
    """A training every employee in a program (Weapons, STE, Operations) needs."""

    __tablename__ = "division_requirements"
    __table_args__ = (UniqueConstraint("program", "training_code", name="uq_division_req"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    program: Mapped[str] = mapped_column(String(16), index=True)
    training_code: Mapped[str] = mapped_column(String(32))
    phase: Mapped[int] = mapped_column(Integer, default=1)
    reason: Mapped[str] = mapped_column(Text, default="")


class LibraryRole(Base):
    """A role defined once and reused across divisions (e.g. Project Lead in Weapons and in STE)."""

    __tablename__ = "library_roles"
    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    family: Mapped[str] = mapped_column(String(48), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    programs: Mapped[list] = mapped_column(JSON, default=list)  # divisions that have this role


class RoleRequirement(Base):
    """A training for a role. program=None applies in every division; otherwise only in that division."""

    __tablename__ = "role_requirements"
    __table_args__ = (UniqueConstraint("role_key", "program", "training_code", name="uq_role_req"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    role_key: Mapped[str] = mapped_column(String(48), index=True)
    program: Mapped[str | None] = mapped_column(String(16), nullable=True)
    training_code: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16), default="technical")  # technical | soft
    phase: Mapped[int] = mapped_column(Integer, default=2)
    reason: Mapped[str] = mapped_column(Text, default="")
