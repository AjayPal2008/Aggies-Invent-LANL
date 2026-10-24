"""Which kind of assessment fits a training.

  quiz         facts, policies, rules, procedures, technical skills: multiple choice is the right check
  situational  leading people and judgment calls ("how would you handle..."): interview-style scenarios
  both         knowledge plus judgment (e.g. ethics): a quiz first, then a short interview

Most trainings are quizzes. Managers can change any training in the role plan.
"""
from __future__ import annotations

VALID = {"quiz", "situational", "both"}
ALIASES = {"interview": "situational", "scenario": "situational", "casper": "situational", "mmi": "situational",
           "sjt": "situational", "multiple choice": "quiz", "mc": "quiz", "test": "quiz", "exam": "quiz"}

# Skills that are about people and judgment, not knowing a rule.
JUDGMENT_SKILLS = {"leadership", "coaching", "stakeholder communication", "conflict resolution", "team leadership",
                   "decision making", "judgment", "mentoring", "communication"}
JUDGMENT_WORDS = ("leading", "leadership", "conversation", "conflict", "supervisor", "mentoring", "coaching", "managing people")
# Knowledge plus judgment.
BOTH_SKILLS = {"ethics", "integrity"}


def choose(explicit: str | None = None, skills: list[str] | None = None, title: str = "") -> str:
    v = (explicit or "").strip().lower()
    if v in VALID:
        return v
    if v in ALIASES:
        return ALIASES[v]
    skills = {s.lower() for s in (skills or [])}
    t = title.lower()
    if skills & JUDGMENT_SKILLS or any(w in t for w in JUDGMENT_WORDS):
        return "situational"
    if skills & BOTH_SKILLS:
        return "both"
    return "quiz"
