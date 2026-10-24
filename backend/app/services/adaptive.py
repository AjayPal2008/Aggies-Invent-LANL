"""The adaptive learning engine.

How a learner's experience changes over time:
  * Knowledge per skill is tracked with Bayesian Knowledge Tracing (BKT). Everyone
    starts low, so first lessons are broad and introductory.
  * Difficulty (intro -> intermediate -> advanced) follows mastery of the
    training's skills.
  * Pacing follows recent accuracy: struggling learners get smaller chunks and
    more examples, strong learners get condensed lessons.
  * Delivery method (text, visual, simulation, quiz, guided exercise) is picked
    by how well the learner actually does with each one, seeded by their stated
    learning style. It keeps exploring a little so it can change its mind.
  * Knowledge gaps are required skills (from the role and assigned trainings)
    whose mastery is under the threshold. The learning path orders trainings
    that close those gaps, respecting prerequisites.
  * Retraining cycles depend on assessment scores.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from .loader import all_trainings, positions

MODALITIES = ["video", "text", "visual", "simulation", "quiz", "exercise"]
STYLE_PRIOR = {
    "visual": "visual",
    "video": "video",
    "watching": "video",
    "reading": "text",
    "text": "text",
    "kinesthetic": "exercise",
    "hands_on": "exercise",
    "hands-on": "exercise",
    "auditory": "video",
    "simulation": "simulation",
    "practice": "quiz",
}

# BKT parameters
P_INIT, P_LEARN, P_SLIP, P_GUESS = 0.2, 0.15, 0.1, 0.2


# ---- knowledge tracing --------------------------------------------------------

def bkt_update(p_known: float, correct: bool) -> float:
    if correct:
        evidence = p_known * (1 - P_SLIP) / (p_known * (1 - P_SLIP) + (1 - p_known) * P_GUESS)
    else:
        evidence = p_known * P_SLIP / (p_known * P_SLIP + (1 - p_known) * (1 - P_GUESS))
    return min(0.999, evidence + (1 - evidence) * P_LEARN)


def _cache_covers(db: Session, emp_id: int) -> bool:
    return emp_id in db.info.get("mastery", {})


def _mastery_row(db: Session, emp: models.Employee, skill: str) -> models.Mastery:
    skill = skill.lower()
    cached = _cache_covers(db, emp.id)
    if cached:
        row = db.info["mastery"][emp.id].get(skill)
    else:
        row = db.scalar(select(models.Mastery).where(models.Mastery.employee_id == emp.id, models.Mastery.skill == skill))
    if row is None:
        prior = (emp.skills or {}).get(skill)
        row = models.Mastery(employee_id=emp.id, skill=skill, p_known=min(prior, 0.6) if prior else P_INIT, observations=0)
        db.add(row)
        if cached:
            db.info["mastery"][emp.id][skill] = row
        else:
            db.flush()
    return row


def get_mastery(db: Session, emp: models.Employee) -> dict[str, float]:
    if _cache_covers(db, emp.id):
        return {skill: round(r.p_known, 3) for skill, r in db.info["mastery"][emp.id].items()}
    rows = db.scalars(select(models.Mastery).where(models.Mastery.employee_id == emp.id))
    return {r.skill: round(r.p_known, 3) for r in rows}


def record_answer(db: Session, emp: models.Employee, training: models.Training | None, skill: str, correct: bool,
                  modality: str = "quiz", question: str = "") -> float:
    db.info.pop(f"modality:{emp.id}", None)
    row = _mastery_row(db, emp, skill)
    row.p_known = bkt_update(row.p_known, correct)
    row.observations += 1
    row.updated_at = datetime.utcnow()
    db.add(models.LearningEvent(employee_id=emp.id, training_id=training.id if training else None, kind="answer",
                                modality=modality, correct=correct, payload={"skill": skill, "question": question[:500]}))
    return row.p_known


def record_assessment_skills(db: Session, emp: models.Employee, training: models.Training, score: float,
                             skill_scores: dict[str, float] | None = None):
    """Fold an assessment result into mastery. A score is treated as several observations."""
    for skill in training.skills or []:
        frac = (skill_scores or {}).get(skill, score / 100)
        row = _mastery_row(db, emp, skill)
        # Weighted blend: an assessment counts as 4 observations at its score, older evidence decays by half.
        n, prior_weight = 4, row.observations * 0.5
        row.p_known = min(0.98, (row.p_known * prior_weight + frac * 0.95 * n) / (prior_weight + n))
        row.observations += n
        row.updated_at = datetime.utcnow()


def refresh_inferred_skills(db: Session, emp: models.Employee):
    """Employee.skills = best evidence from self-report, mastery and completed trainings."""
    skills = dict(emp.skills or {})
    if not _cache_covers(db, emp.id):
        db.flush()
    for skill, p in get_mastery(db, emp).items():
        skills[skill] = round(max(skills.get(skill, 0), p), 3)
    for a in emp.assignments:
        if a.status == "completed" and a.training:
            conf = 0.5 if a.best_score is None else min(1.0, a.best_score / 100)
            for s in a.training.skills or []:
                skills[s] = round(max(skills.get(s, 0), conf * 0.9), 3)
    emp.skills = skills


# ---- difficulty, pacing, delivery --------------------------------------------

def training_mastery(db: Session, emp: models.Employee, training: models.Training) -> float:
    m = get_mastery(db, emp)
    skills = training.skills or []
    if not skills:
        return P_INIT
    return sum(m.get(s, (emp.skills or {}).get(s, P_INIT)) for s in skills) / len(skills)


def difficulty_for(db: Session, emp: models.Employee, training: models.Training) -> str:
    level = training_mastery(db, emp, training)
    if level < 0.45:
        return "intro"
    if level < 0.75:
        return "intermediate"
    return "advanced"


def recent_accuracy(db: Session, emp: models.Employee, limit: int = 20) -> float | None:
    events = list(db.scalars(select(models.LearningEvent).where(
        models.LearningEvent.employee_id == emp.id, models.LearningEvent.correct.is_not(None)
    ).order_by(models.LearningEvent.id.desc()).limit(limit)))
    if not events:
        return None
    return sum(1 for e in events if e.correct) / len(events)


def pacing_for(db: Session, emp: models.Employee) -> dict:
    acc = recent_accuracy(db, emp)
    if acc is None:
        return {"pace": "steady", "chunk_minutes": 10, "examples_per_concept": 2, "reason": "No history yet, starting at a steady pace."}
    if acc < 0.6:
        return {"pace": "slow", "chunk_minutes": 5, "examples_per_concept": 3,
                "reason": f"Recent accuracy is {acc:.0%}; slowing down with smaller steps and more examples."}
    if acc > 0.85:
        return {"pace": "fast", "chunk_minutes": 15, "examples_per_concept": 1,
                "reason": f"Recent accuracy is {acc:.0%}; condensing material."}
    return {"pace": "steady", "chunk_minutes": 10, "examples_per_concept": 2, "reason": f"Recent accuracy is {acc:.0%}."}


def modality_scores(db: Session, emp: models.Employee) -> dict[str, float]:
    """Expected success rate per delivery method (Beta posterior mean + style prior)."""
    key = f"modality:{emp.id}"
    if key in db.info:
        return dict(db.info[key])
    wins, trials = defaultdict(int), defaultdict(int)
    for modality, correct in db.execute(select(models.LearningEvent.modality, models.LearningEvent.correct).where(
            models.LearningEvent.employee_id == emp.id, models.LearningEvent.correct.is_not(None))):
        if modality:
            trials[modality] += 1
            wins[modality] += 1 if correct else 0
    preferred = STYLE_PRIOR.get((emp.learning_style or "").lower())
    scores = {}
    for m in MODALITIES:
        prior_a, prior_b = (3, 1) if m == preferred else (1, 1)
        mean = (wins[m] + prior_a) / (trials[m] + prior_a + prior_b)
        bonus = math.sqrt(math.log(sum(trials.values()) + 2) / (trials[m] + 1)) * 0.1  # gentle exploration
        scores[m] = round(mean + bonus, 3)
    db.info[key] = scores
    return dict(scores)


def best_modality(db: Session, emp: models.Employee, training: models.Training | None = None) -> str:
    scores = modality_scores(db, emp)
    if training and (training.equipment or training.facilities):
        scores["simulation"] += 0.05  # equipment and facility procedures suit walkthroughs
    return max(scores, key=scores.get)


def learner_profile(db: Session, emp: models.Employee, training: models.Training | None = None) -> dict:
    return {
        "learning_style": emp.learning_style,
        "difficulty": difficulty_for(db, emp, training) if training else None,
        "pacing": pacing_for(db, emp),
        "modality": best_modality(db, emp, training),
        "modality_scores": modality_scores(db, emp),
        "mastery": {s: p for s, p in get_mastery(db, emp).items() if not training or s in (training.skills or [])},
    }


# ---- assignments, deadlines, retraining --------------------------------------

def default_due_date(emp: models.Employee, training: models.Training) -> date:
    today = date.today()
    if training.required and emp.is_new_hire and emp.hire_date:
        return max(today + timedelta(days=7), emp.hire_date + timedelta(days=30))
    return today + timedelta(days=30 if training.required else 60)


def _add_months(d: date, months: float) -> date:
    return d + timedelta(days=int(months * 30.44))


def schedule_retraining(a: models.Assignment, training: models.Training):
    """Set expiry, retake flag and next retraining date from the best score."""
    done = (a.completed_at or datetime.utcnow()).date()
    score = a.best_score
    validity = training.validity_months
    a.expires_at = _add_months(done, validity) if validity else None
    if score is not None and score < settings.pass_score:
        a.needs_retake = True
        a.next_retraining = date.today() + timedelta(days=settings.retake_window_days)
        return
    a.needs_retake = False
    if score is None or score >= 90:
        a.next_retraining = a.expires_at
    else:
        # Passed but shaky: refresh earlier than the formal expiry.
        a.next_retraining = _add_months(done, (validity or 12) * 0.75)


def complete_assessment(db: Session, a: models.Assignment, score: float, skill_scores: dict | None = None,
                        kind: str = "quiz") -> models.Assignment:
    """Record a quiz or interview result and update the assignment's status and retraining dates."""
    emp, t = a.employee, a.training
    a.attempts_log.append(models.AssessmentAttempt(score=score, skill_scores=skill_scores or {}, kind=kind))
    a.attempts += 1
    a.started_at = a.started_at or datetime.utcnow()
    apply_scores(a)
    record_assessment_skills(db, emp, t, score, skill_scores)
    db.add(models.LearningEvent(employee_id=emp.id, training_id=t.id, kind="assessment", payload={"score": score, "type": kind}))
    a.difficulty = difficulty_for(db, emp, t)
    refresh_inferred_skills(db, emp)
    return a


def apply_scores(a: models.Assignment):
    """Status from the best attempts. Trainings assessed by both need a passing quiz AND a passing interview."""
    t = a.training
    best = {}
    for x in a.attempts_log:
        k = x.kind or "quiz"
        best[k] = max(best.get(k, 0), x.score)
    needed = ["quiz", "interview"] if t.assessment_type == "both" else (["interview"] if t.assessment_type == "situational" else ["quiz"])
    have = [best[k] for k in needed if k in best] or list(best.values())
    a.best_score = min(have) if t.assessment_type == "both" and len(have) == len(needed) else max(have)
    done = all(k in best for k in needed) or (t.assessment_type != "both" and bool(best))
    passed = done and all(best.get(k, 0) >= settings.pass_score for k in needed if k in best)
    if passed:
        if a.status != "completed" or a.needs_retake or not a.completed_at:
            a.completed_at = datetime.utcnow()  # a fresh pass restarts the retraining clock
        a.status, a.progress = "completed", 100
    else:
        a.status, a.progress = "in_progress", max(a.progress, 75 if any(v >= settings.pass_score for v in best.values()) else 50)
    schedule_retraining(a, t)
    a.needs_retake = any(v < settings.pass_score for v in best.values()) and not passed


def assignment_flags(a: models.Assignment, today: date | None = None) -> dict:
    today = today or date.today()
    overdue = a.status != "completed" and a.due_date is not None and a.due_date < today
    upcoming = a.status != "completed" and a.due_date is not None and today <= a.due_date <= today + timedelta(days=14)
    expired = a.status == "completed" and a.expires_at is not None and a.expires_at < today
    expiring = a.status == "completed" and a.expires_at is not None and today <= a.expires_at <= today + timedelta(days=60)
    return {"overdue": overdue, "upcoming": upcoming, "expired": expired, "expiring": expiring,
            "needs_retake": a.needs_retake or expired}


# ---- gaps and learning paths --------------------------------------------------

def required_skills(db: Session, emp: models.Employee) -> dict[str, list[str]]:
    """skill -> reasons it is required."""
    reasons: dict[str, list[str]] = defaultdict(list)
    if emp.position_code:
        pos = positions(db).get(emp.position_code)
        if pos:
            for s in pos.required_skills or []:
                reasons[s].append(f"role: {pos.title}")
    for a in emp.assignments:
        for s in a.training.skills or []:
            reasons[s].append(f"assigned: {a.training.code}")
    return reasons


def knowledge_gaps(db: Session, emp: models.Employee) -> list[dict]:
    mastery = get_mastery(db, emp)
    trainings = all_trainings(db)
    gaps = []
    for skill, why in required_skills(db, emp).items():
        p = mastery.get(skill, (emp.skills or {}).get(skill, 0.0))
        if p < settings.mastery_threshold:
            gaps.append({
                "skill": skill,
                "mastery": round(p, 3),
                "severity": "high" if p < 0.4 else "medium",
                "why": sorted(set(why)),
                "trainings": [t.code for t in trainings if skill in (t.skills or [])],
            })
    return sorted(gaps, key=lambda g: g["mastery"])


def _relevant(t: models.Training, emp: models.Employee) -> bool:
    roles = set(t.job_roles or [])
    return not roles or "all" in roles or emp.position_code in roles or emp.job_title in roles


def recommend_path(db: Session, emp: models.Employee, limit: int = 12) -> list[dict]:
    """Ordered list of what to do next, with the reason for each step."""
    gaps = {g["skill"]: g for g in knowledge_gaps(db, emp)}
    by_code = {t.code: t for t in all_trainings(db)}
    assigned = {a.training.code: a for a in emp.assignments}
    completed = {c for c, a in assigned.items() if a.status == "completed" and not assignment_flags(a)["needs_retake"]}

    scored: dict[str, tuple[float, list[str]]] = {}
    for code, t in by_code.items():
        a = assigned.get(code)
        if code in completed:
            continue
        reasons, score = [], 0.0
        if a:
            f = assignment_flags(a)
            if f["overdue"]:
                score += 100; reasons.append("overdue")
            if f["needs_retake"]:
                score += 80; reasons.append("retake needed")
            if a.due_date:
                days = (a.due_date - date.today()).days
                score += max(0, 40 - days); reasons.append(f"due {a.due_date.isoformat()}")
            if a.status == "in_progress":
                score += 10; reasons.append("already started")
            score += 30; reasons.append("assigned")
        covered = [s for s in t.skills or [] if s in gaps]
        if covered:
            score += 15 * len(covered) + sum(20 * (1 - gaps[s]["mastery"]) for s in covered)
            reasons.append("closes gaps: " + ", ".join(covered))
        if t.required and _relevant(t, emp):
            score += 25; reasons.append("required for your role")
        if score > 0:
            scored[code] = (score, reasons)

    # Pull in missing prerequisites ahead of what needs them.
    order: list[str] = []
    seen: set[str] = set()

    def visit(code: str, chain: tuple = ()):
        if code in seen or code in chain or code not in by_code:
            return
        for pre in by_code[code].prerequisites or []:
            if pre not in completed:
                if pre not in scored:
                    scored[pre] = (0.0, [f"prerequisite for {code}"])
                visit(pre, chain + (code,))
        seen.add(code)
        order.append(code)

    for code, _ in sorted(scored.items(), key=lambda kv: -kv[1][0]):
        visit(code)

    path = []
    for code in order[:limit]:
        t = by_code[code]
        a = assigned.get(code)
        path.append({
            "training_code": code,
            "title": t.title,
            "category": t.category,
            "delivery": t.delivery,
            "assigned": a is not None,
            "assignment_id": a.id if a else None,
            "difficulty": difficulty_for(db, emp, t),
            "suggested_modality": best_modality(db, emp, t),
            "priority": round(scored[code][0], 1),
            "reasons": scored[code][1],
        })
    return path
