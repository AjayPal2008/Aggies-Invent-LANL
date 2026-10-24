"""Lessons, videos and interview-style assessments built from course material.

Video lessons are returned as scenes (on-screen text, a visual, and narration).
The hire dashboard plays them as narrated, animated videos with captions using
the browser's speech engine, so there is no video rendering service to pay for.
To use a hosted AI video service later, render the same scenes there.
"""
from __future__ import annotations

import json
import random
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from . import ai
from .documents import document_text

MODULE_TEXT_LIMIT = 400_000  # characters of source text sent for one module


# ---- source material ------------------------------------------------------------

def module_source(db: Session, module: models.CourseModule) -> str:
    t = db.get(models.Training, module.training_id)
    if t.document_id:
        doc = db.get(models.Document, t.document_id)
        return document_text(doc, module.page_start, module.page_end, MODULE_TEXT_LIMIT)
    return "\n".join([module.summary, *module.key_points])


def training_source(t: models.Training) -> str:
    return f"{t.title}\n{t.description}\nTopics:\n{t.outline}\nSkills: {', '.join(t.skills or [])}"


# ---- video lessons ------------------------------------------------------------------

VIDEO_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "visual": {"type": "string", "enum": ["title", "bullets", "diagram", "checklist", "quote", "scenario"]},
                    "on_screen": {"type": "array", "items": {"type": "string"}},
                    "narration": {"type": "string"},
                },
                "required": ["heading", "visual", "on_screen", "narration"],
                "additionalProperties": False,
            },
        },
        "takeaways": {"type": "array", "items": {"type": "string"}},
        "check_question": {
            "type": "object",
            "properties": {"question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}},
                           "answer_index": {"type": "integer"}, "explanation": {"type": "string"}},
            "required": ["question", "options", "answer_index", "explanation"],
            "additionalProperties": False,
        },
    },
    "required": ["title", "scenes", "takeaways", "check_question"],
    "additionalProperties": False,
}


def video_lesson(emp: models.Employee, title: str, source: str, key_points: list[str], profile: dict, request: str = "",
                 skill: str = "") -> dict:
    diff = profile.get("difficulty") or "intro"
    pace = (profile.get("pacing") or {}).get("pace", "steady")
    n_scenes = {"slow": "8-10", "steady": "6-8", "fast": "4-6"}.get(pace, "6-8")
    prompt = (
        f"Make a short explainer video script for this learner from the source material below.\n"
        f"Learner: {emp.job_title}, level {emp.level}, {emp.years_experience:g} years experience. Difficulty: {diff}. Pace: {pace}.\n"
        f"{'Learner request: ' + request if request else ''}\n"
        f"Write {n_scenes} scenes. Each scene has a heading, a visual type, 1-5 short on-screen lines (under 12 words each; for "
        "'diagram' these are the ordered steps, for 'scenario' the situation then the right move), and narration of 40-90 "
        "spoken words in a warm, plain voice. Open with why it matters for their job, teach the actual requirements, include "
        "one realistic workplace example as a 'scenario' scene, and end with a recap. At intro level define terms; at "
        "advanced level focus on judgment calls and edge cases. Add 3-5 takeaways and one check question.\n\n"
        f"<source title=\"{title}\">\n{source}\n</source>"
    )
    data = ai.call_json_long(prompt, VIDEO_SCHEMA, max_tokens=12000)
    if data:
        data["generated_by"] = settings.ai_model
        return data
    return _offline_video(title, source, key_points, diff, skill)


def _offline_video(title: str, source: str, key_points: list[str], diff: str, skill: str) -> dict:
    points = [k for k in key_points if k][:6] or [s for s in re.split(r"(?<=[.!?])\s+", source) if 40 < len(s) < 220][:5] or [title]
    scenes = [{"heading": title, "visual": "title", "on_screen": [title, "What you need to know, in a few minutes"],
               "narration": f"In this video we'll cover {title.lower()}. Instead of reading the whole document, you'll get the "
                            "requirements that matter for your job, a real example, and a quick recap."}]
    scenes.append({"heading": "The essentials", "visual": "bullets", "on_screen": [_short(p) for p in points[:4]],
                   "narration": "Here are the essentials. " + " ".join(points[:3])})
    for p in points[:3]:
        scenes.append({"heading": "What this means for you", "visual": "quote", "on_screen": [_short(p, 18)],
                       "narration": f"The document says: {p} In practice, that means you check this before the work starts, "
                                    "and if something doesn't match, you stop and ask."})
    scenes.append({"heading": "How it fits together", "visual": "diagram",
                   "on_screen": ["Plan the work", "Check the requirement", "Do the work", "Verify and document"],
                   "narration": "Put together, the flow is simple: plan the work, check the requirement, do the work, then verify and document it."})
    scenes.append({"heading": "A real situation", "visual": "scenario",
                   "on_screen": ["A deadline is close and a step was skipped", "Right move: pause, fix it, tell your lead"],
                   "narration": "Imagine a deadline is tomorrow and you find out a required step was skipped. The right move is to pause, "
                                "fix it, and tell your lead, even if it costs a day."})
    scenes.append({"heading": "Recap", "visual": "checklist", "on_screen": [_short(p) for p in points[:4]],
                   "narration": "To recap: " + " ".join(_short(p) + "." for p in points[:3]) + " When in doubt, stop and ask."})
    if diff == "advanced":
        scenes = [scenes[0], *scenes[2:]]
    return {
        "title": title, "scenes": scenes, "takeaways": [_short(p) for p in points[:4]] + ["When in doubt, stop and ask."],
        "check_question": {"question": f"A step required by \"{_short(points[0], 14)}\" was skipped and the deadline is tomorrow. What do you do?",
                           "options": ["Pause the work and correct it before delivery", "Deliver on time and fix it later",
                                       "Ask a teammate to keep quiet about it", "Remove the step from the plan"],
                           "answer_index": 0, "explanation": "Requirements protect people and the mission; schedule pressure doesn't change them."},
        "generated_by": "offline",
        "skill": skill,
    }


def _short(text: str, words: int = 12) -> str:
    w = re.sub(r"\s+", " ", text).strip().split()
    return " ".join(w[:words]) + ("…" if len(w) > words else "")


# ---- module lessons ---------------------------------------------------------------

def module_lesson(db: Session, emp: models.Employee, module: models.CourseModule, profile: dict, request: str = "") -> dict:
    """Lesson for one module in the learner's style. Cached per (module, style, level) unless customized."""
    modality, diff = profile["modality"], profile["difficulty"]
    cache = None if request else db.scalar(select(models.LessonCache).where(
        models.LessonCache.module_id == module.id, models.LessonCache.modality == modality, models.LessonCache.difficulty == diff))
    if cache:
        return {**cache.content, "cached": True}
    t = db.get(models.Training, module.training_id)
    source = module_source(db, module)
    skill = (module.skills or t.skills or [t.category])[0]
    if modality == "video":
        content = video_lesson(emp, module.title, source, module.key_points, profile, request, skill)
        content["kind"] = "video"
    else:
        # Reuse the general lesson generator with this module's pages as the material.
        shadow = models.Training(code=t.code, title=f"{t.title}: {module.title}", description=module.summary,
                                 category=t.category, delivery=t.delivery, source_system=t.source_system, source_url=t.source_url,
                                 skills=module.skills or t.skills, outline="\n".join(module.key_points) or module.title,
                                 equipment=t.equipment, facilities=t.facilities)
        content = ai.generate_lesson(emp, shadow, profile, request, source=source[:120_000])
        content["kind"] = "lesson"
    content.update({"module_id": module.id, "module_title": module.title, "pages": f"{module.page_start}-{module.page_end}",
                    "difficulty": diff, "modality": modality})
    if not request and content.get("generated_by") != "offline":
        from sqlalchemy.exc import IntegrityError

        try:  # two workers can generate the same lesson at the same moment; keep the first
            with db.begin_nested():
                db.add(models.LessonCache(module_id=module.id, modality=modality, difficulty=diff, content=content))
        except IntegrityError:
            pass
    elif not request:
        # Offline content is cheap to rebuild; store it so repeat views are instant, but let AI replace it later.
        existing = db.scalar(select(models.LessonCache).where(models.LessonCache.module_id == module.id,
                                                               models.LessonCache.modality == modality, models.LessonCache.difficulty == diff))
        if existing is None:
            from sqlalchemy.exc import IntegrityError

            try:
                with db.begin_nested():
                    db.add(models.LessonCache(module_id=module.id, modality=modality, difficulty=diff, content=content))
            except IntegrityError:
                pass
    return content


# ---- scenarios ----------------------------------------------------------------------

SCENARIOS_SCHEMA = {
    "type": "object",
    "properties": {"scenarios": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "title": {"type": "string"}, "situation": {"type": "string"},
            "questions": {"type": "array", "items": {"type": "string"}},
            "competencies": {"type": "array", "items": {"type": "string"}},
            "strong_response": {"type": "array", "items": {"type": "string"}},
            "red_flags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "situation", "questions", "competencies", "strong_response", "red_flags"],
        "additionalProperties": False,
    }}},
    "required": ["scenarios"],
    "additionalProperties": False,
}


def ensure_scenarios(db: Session, t: models.Training, role_title: str) -> list[models.Scenario]:
    """Catalog trainings don't come with scenarios; write a bank the first time one is needed."""
    existing = list(db.scalars(select(models.Scenario).where(models.Scenario.training_id == t.id)))
    if len(existing) >= 3:
        return existing
    prompt = (
        f"Write 6 realistic workplace scenarios for an interview-style assessment (like CASPer or an MMI) for the LANL training "
        f"below, for someone working as {role_title}. Each needs a specific situation with real tension (time pressure, "
        "a coworker, a safety or ethics call), 2-3 open questions, the competencies it tests, what a strong response considers, "
        f"and red flags.\n\n<training>\n{training_source(t)}\n</training>"
    )
    data = ai._call_json(prompt, SCENARIOS_SCHEMA, max_tokens=10000)
    items = data["scenarios"] if data else _offline_scenarios(t, role_title)
    for sc in items:
        db.add(models.Scenario(training_id=t.id, title=sc["title"][:300], situation=sc["situation"], questions=sc["questions"][:3],
                               competencies=sc["competencies"], strong_response=sc["strong_response"], red_flags=sc["red_flags"]))
    db.flush()
    return list(db.scalars(select(models.Scenario).where(models.Scenario.training_id == t.id)))


def _offline_scenarios(t: models.Training, role: str) -> list[dict]:
    topics = [l.strip() for l in (t.outline or "").splitlines() if l.strip()] or [t.title]
    situations = [
        ("A coworker cuts a corner", "You notice an experienced coworker skipping part of {topic} because \"it's always fine.\" "
         "They've been here 15 years and you're new to the team."),
        ("Deadline versus doing it right", "Your lead asks you to finish work involving {topic} by end of day. Doing it correctly "
         "will take until tomorrow, and the customer is waiting."),
        ("Something doesn't match", "Halfway through a task involving {topic}, conditions don't match the plan you were briefed on. "
         "Nobody else is around and stopping will delay the next shift."),
        ("You made the mistake", "You realize that yesterday you got part of {topic} wrong. Nobody has noticed, and fixing it means "
         "redoing a coworker's work too."),
    ]
    out = []
    for i, (title, text) in enumerate(situations):
        topic = topics[i % len(topics)].lower()
        out.append({
            "title": title, "situation": f"You're working as {role}. " + text.format(topic=topic),
            "questions": ["What do you do, and why?", "How do you handle the people involved?", "What would you do to prevent this next time?"],
            "competencies": ["judgment", "communication", "integrity"],
            "strong_response": ["puts safety and the requirement ahead of schedule", "stops or pauses work when conditions change",
                                "talks to the person directly and respectfully", "involves the supervisor or the right contact",
                                "is honest about mistakes", "follows up on the root cause"],
            "red_flags": ["ignores the problem", "hides a mistake", "confronts aggressively or publicly", "keeps working outside the plan"],
        })
    return out


def pick_scenarios(db: Session, t: models.Training, emp: models.Employee, role_title: str, n: int = 3) -> list[models.Scenario]:
    bank = ensure_scenarios(db, t, role_title)
    seen = set()
    for s in db.scalars(select(models.InterviewSession).where(models.InterviewSession.employee_id == emp.id)):
        seen.update(s.scenario_ids or [])
    fresh = [s for s in bank if s.id not in seen] or bank
    rng = random.Random(f"{emp.id}-{len(seen)}")
    return rng.sample(fresh, min(n, len(fresh)))


# ---- scoring ------------------------------------------------------------------------

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "responses": {"type": "array", "items": {
            "type": "object",
            "properties": {"response_id": {"type": "integer"}, "score": {"type": "number"}, "feedback": {"type": "string"}},
            "required": ["response_id", "score", "feedback"], "additionalProperties": False}},
        "competencies": {"type": "array", "items": {
            "type": "object", "properties": {"name": {"type": "string"}, "score": {"type": "number"}},
            "required": ["name", "score"], "additionalProperties": False}},
        "overall": {"type": "number"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "improvements": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["responses", "competencies", "overall", "strengths", "improvements"],
    "additionalProperties": False,
}

GOOD_MARKERS = ["safety", "safe", "supervisor", "lead", "escalat", "document", "communicat", "listen", "understand", "why",
                "because", "first", "then", "procedure", "policy", "report", "risk", "team", "stakeholder", "customer",
                "honest", "transparen", "follow up", "root cause", "pause", "stop", "ask", "respect", "privately", "plan"]


def score_interview(db: Session, session: models.InterviewSession, role_title: str) -> dict:
    scen = {s.id: s for s in db.scalars(select(models.Scenario).where(models.Scenario.id.in_(session.scenario_ids)))}
    items = []
    for r in session.responses:
        s = scen[r.scenario_id]
        q = s.questions[r.question_index] if r.question_index < len(s.questions) else ""
        items.append({"response_id": r.id, "scenario": s.title, "situation": s.situation, "question": q,
                      "strong_response_considers": s.strong_response, "red_flags": s.red_flags,
                      "competencies": s.competencies, "answer": r.transcript or "(no answer)", "seconds_used": r.seconds_used})
    prompt = (
        f"Score this situational judgment assessment for someone working as {role_title}, the way trained raters score CASPer "
        "or an MMI: judge the reasoning, priorities and how they treat people, not polish or length. Spoken answers were "
        "transcribed automatically, so ignore filler words and transcription errors.\n"
        "Scale 1-9 per response: 1-3 misses the core issue or shows a red flag; 4-6 reasonable but incomplete; 7-9 addresses "
        "the core issue, weighs the people and the requirements, and gives a concrete plan. Give one or two sentences of "
        "specific feedback per response, addressed to the learner. Then score each competency, an overall score, and 2-3 "
        "strengths and improvements.\n\n" + json.dumps(items, indent=1)
    )
    data = ai._call_json(prompt, SCORE_SCHEMA, max_tokens=8000)
    by_id = {r.id: r for r in session.responses}
    if data:
        for row in data["responses"]:
            r = by_id.get(row["response_id"])
            if r:
                r.score, r.feedback = _clamp(row["score"]), row["feedback"]
        comps = {c["name"].lower(): _clamp(c["score"]) for c in data["competencies"]}
        overall, by = _clamp(data["overall"]), settings.ai_model
        fb = {"strengths": data["strengths"], "improvements": data["improvements"]}
    else:
        comps, by = {}, "offline"
        # Like a human rater, credit what the person covered across all their answers to a scenario.
        combined: dict[int, str] = {}
        for r in session.responses:
            combined[r.scenario_id] = combined.get(r.scenario_id, "") + " " + (r.transcript or "")
        for r, it in zip(session.responses, items):
            r.score, r.feedback = _offline_score(it, combined.get(r.scenario_id, ""))
            for c in it["competencies"]:
                comps.setdefault(c.lower(), []).append(r.score)
        comps = {k: round(sum(v) / len(v), 1) for k, v in comps.items()}
        scores = [r.score for r in session.responses if r.score is not None]
        overall = round(sum(scores) / len(scores), 1) if scores else 1.0
        fb = {"strengths": ["Answered every question"] if all(r.transcript.strip() for r in session.responses) else [],
              "improvements": ["Say what you'd do first and why", "Name who you'd involve (lead, safety contact, customer)",
                               "Close with how you'd prevent it next time"],
              "note": "Offline estimate based on what your answers covered. Your manager can review the recording and adjust."}
    session.overall, session.competency_scores, session.feedback, session.scored_by, session.status = overall, comps, fb, by, "scored"
    return {"overall": overall, "competencies": comps, "feedback": fb, "scored_by": by}


def _clamp(v) -> float:
    return round(max(1.0, min(9.0, float(v))), 1)


def _offline_score(item: dict, scenario_text: str = "") -> tuple[float, str]:
    answer = item["answer"].lower()
    words = len(answer.split())
    if words < 5:
        return 1.0, "No real answer was given."
    whole = (scenario_text or answer).lower()

    def covered(phrase: str, text: str = answer) -> bool:
        keys = [w for w in re.findall(r"[a-z]{5,}", phrase.lower())][:4]
        return any(k[:6] in text for k in keys)
    rubric = item["strong_response_considers"]
    own = sum(covered(p) for p in rubric) / max(1, len(rubric))
    across = sum(covered(p, whole) for p in rubric) / max(1, len(rubric))
    coverage = 0.4 * own + 0.6 * across
    markers = sum(1 for m in GOOD_MARKERS if m in answer)
    flags = sum(1 for f in item["red_flags"] if all(w[:6] in answer for w in re.findall(r"[a-z]{5,}", f.lower())[:2]))
    raw = 0.5 * coverage + 0.3 * min(1, markers / 6) + 0.2 * min(1, words / 110) - 0.15 * flags
    score = _clamp(1 + 8 * max(0, raw))
    missing = [p for p in rubric if not covered(p, whole)][:2]
    fb = "Good coverage of the key issues." if not missing else "Consider: " + "; ".join(missing) + "."
    return score, fb


def interview_to_percent(overall: float) -> float:
    """Map 1-9 onto the 0-100 scale so the pass line (INTERVIEW_PASS) lands on PASS_SCORE.

    Keeps retraining rules (retake under 80, refresher 80-89, full validity 90+) meaningful for interviews.
    """
    p, ps = settings.interview_pass, settings.pass_score
    if overall >= p:
        return round(ps + (overall - p) / (9 - p) * (100 - ps), 1)
    return round(max(0.0, (overall - 1) / (p - 1) * ps), 1)


# ---- quizzes for document-built courses -------------------------------------------------

MUTATIONS = [
    (r"\bmust not\b", "may"), (r"\bshall not\b", "may"), (r"\bmay not\b", "may"),
    (r"\bmust\b", "may, if the schedule allows,"), (r"\bshall\b", "should, when convenient,"),
    (r"\bis required\b", "is optional"), (r"\bare required\b", "are optional"), (r"\brequires\b", "suggests"),
    (r"\bprohibited\b", "allowed with a coworker's OK"), (r"\bnever\b", "sometimes"), (r"\balways\b", "only when asked to"),
    (r"\bbefore\b", "after"), (r"\bwithin\b", "after"), (r"\bimmediately\b", "at the next quarterly review"),
    (r"\bin writing\b", "verbally"), (r"\bthe same day\b", "within a month"), (r"\bevery month\b", "once a year"),
]


def _mutations(statement: str) -> list[str]:
    out = []
    for pat, rep in MUTATIONS:
        if re.search(pat, statement, re.IGNORECASE):
            out.append(re.sub(pat, rep, statement, count=1, flags=re.IGNORECASE))
    nums = re.findall(r"\$?\d[\d,]*(?:\.\d+)?", statement)
    for n in nums[:2]:
        raw = float(n.replace("$", "").replace(",", ""))
        bigger = int(raw * 4) if raw >= 1 else raw + 3
        fmt = f"${bigger:,}" if n.startswith("$") else f"{bigger:,}"
        out.append(statement.replace(n, fmt, 1))
    seen, unique = set(), []
    for o in out:
        if o != statement and o not in seen:
            seen.add(o)
            unique.append(o)
    return unique


def document_quiz(db: Session, emp: models.Employee, t: models.Training, profile: dict, n: int = 8) -> dict:
    """Multiple-choice questions written from the course's actual requirements."""
    mods = list(db.scalars(select(models.CourseModule).where(models.CourseModule.training_id == t.id).order_by(models.CourseModule.position)))
    weakest = sorted(t.skills or [], key=lambda s: profile.get("mastery", {}).get(s, 0))[:3]
    source = "\n\n".join(f"## {m.title} (pages {m.page_start}-{m.page_end})\n" + "\n".join(f"- {k}" for k in m.key_points) for m in mods)
    prompt = (
        f"Write {n} multiple-choice questions (4 options) that check whether someone working as {emp.job_title} knows the "
        f"requirements in this course, built from the LANL document \"{t.title}\". Test the actual rules: who is "
        "responsible, what is required, when, and the thresholds. Prefer short workplace framings over pure recall. "
        "Wrong options must be plausible (a wrong threshold, the wrong order, an optional-sounding version of a requirement). "
        f"Spread questions across modules, with extra weight on: {', '.join(weakest) or 'all skills'}. Set skill to one of: "
        f"{', '.join(t.skills or [t.category])}. Explanations should cite the page range.\n\n<course>\n{source}\n</course>"
    )
    data = ai._call_json(prompt, ai.QUESTIONS_SCHEMA, max_tokens=8000)
    if data and data.get("questions"):
        qs = [q for q in data["questions"] if len(q["options"]) >= 2 and 0 <= q["answer_index"] < len(q["options"])]
        return {"questions": qs[:n], "generated_by": settings.ai_model, "focus_skills": weakest}
    return {"questions": _offline_document_quiz(t, mods, n), "generated_by": "offline", "focus_skills": weakest}


def _offline_document_quiz(t: models.Training, mods: list[models.CourseModule], n: int) -> list[dict]:
    rng = random.Random(f"{t.code}-{n}-{random.random()}")
    pool = [(m, k) for m in mods for k in m.key_points if len(_mutations(k)) >= 1]
    rng.shuffle(pool)
    # one question per module first, so the quiz covers the whole course
    picked, used = [], set()
    for m, k in pool:
        if m.id not in used:
            picked.append((m, k)); used.add(m.id)
        if len(picked) >= n:
            break
    for m, k in pool:
        if len(picked) >= n:
            break
        if (m, k) not in picked:
            picked.append((m, k))
    generic = ["This is a recommendation only and can be skipped when the schedule is tight.",
               "Any team member can decide this informally without telling anyone.",
               "This only applies to projects outside the Laboratory."]
    out = []
    for m, k in picked:
        wrong = _mutations(k)[:3]
        wrong += [g for g in generic if g not in wrong][: 3 - len(wrong)]
        options = [k, *wrong]
        rng.shuffle(options)
        out.append({"question": f"Which statement matches {t.title}, \"{m.title}\"?", "options": options,
                    "answer_index": options.index(k), "skill": (m.skills or t.skills or [t.category])[0],
                    "explanation": f"Pages {m.page_start}-{m.page_end}: {k}"})
    return out



# ---- readiness ----------------------------------------------------------------------------

READINESS_LABEL = {"ready": "Ready", "ready_with_support": "Ready with support", "not_ready": "Not ready yet"}


def score_readiness(db: Session, session: models.InterviewSession) -> dict:
    """How ready is this person to handle the situations this training is about?

    readiness score (0-100) = 55% interview score + 20% weakest competency + 25% mastery of the training's skills
    (when the training also has a quiz: 15% skills + 10% best quiz score).
      Ready               score >= 75, interview at or above the pass mark, no competency below 5 of 9
      Ready with support  score >= 55 and interview >= 4.5: can start, with coaching on the weak areas
      Not ready yet       otherwise: review the recommended modules and redo the interview
    Uses the manager's score when they've reviewed it.
    """
    from datetime import date, timedelta

    from .adaptive import get_mastery

    a = session.assignment
    t = a.training
    emp = db.get(models.Employee, session.employee_id)
    overall = session.manager_overall if session.manager_overall is not None else (session.overall or 1)
    comps = session.competency_scores or {}
    pct = lambda v: max(0.0, min(100.0, (v - 1) / 8 * 100))  # noqa: E731  (1-9 scale -> 0-100)
    weakest_name, weakest = (min(comps.items(), key=lambda kv: kv[1]) if comps else ("overall", overall))
    mastery = get_mastery(db, emp)
    skills = t.skills or []
    skill_pct = 100 * sum(mastery.get(s_, (emp.skills or {}).get(s_, 0)) for s_ in skills) / len(skills) if skills else pct(overall)
    quiz = [x.score for x in a.attempts_log if x.kind == "quiz"] if t.assessment_type == "both" else []
    quiz_pct = max(quiz) if quiz else None
    parts = [(0.55, pct(overall)), (0.20, pct(weakest))]
    parts += [(0.15, skill_pct), (0.10, quiz_pct)] if quiz_pct is not None else [(0.25, skill_pct)]
    score = round(sum(w * v for w, v in parts), 1)

    pass_mark = settings.interview_pass
    if score >= 75 and overall >= pass_mark and weakest >= 5:
        level = "ready"
    elif score >= 55 and overall >= 4.5:
        level = "ready_with_support"
    else:
        level = "not_ready"

    status = lambda v: "strong" if v >= 7 else "solid" if v >= 5 else "develop"  # noqa: E731
    competencies = [{"name": k, "score": v, "status": status(v)} for k, v in sorted(comps.items(), key=lambda kv: kv[1])]
    focus = [c["name"] for c in competencies if c["status"] == "develop"] or [c["name"] for c in competencies[:1] if c["score"] < 7]

    # Which modules to review: the ones behind the lowest-scored scenarios.
    review = []
    scen = {x.id: x for x in db.scalars(select(models.Scenario).where(models.Scenario.id.in_(session.scenario_ids or [0])))}
    low = sorted((r for r in session.responses if r.score is not None), key=lambda r: r.score)[:3]
    mods = list(db.scalars(select(models.CourseModule).where(models.CourseModule.training_id == t.id)))
    for r in low:
        sc = scen.get(r.scenario_id)
        m = re.match(r"(\d+)\s*-\s*(\d+)", (sc.source_pages or "") if sc else "")
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            for mod in mods:
                if mod.page_start <= hi and mod.page_end >= lo and mod.id not in [x["module_id"] for x in review]:
                    review.append({"module_id": mod.id, "title": mod.title, "pages": f"{mod.page_start}-{mod.page_end}",
                                   "because": f"scenario \"{sc.title}\" scored {r.score}/9"})
    role = emp.job_title or "this role"
    retake_date = date.today() + timedelta(days=settings.retake_window_days)
    retake_by = f"{retake_date:%b} {retake_date.day}, {retake_date:%Y}"  # portable (no %-d on Windows)
    summary = {
        "ready": f"Ready to handle these situations on their own as {role}.",
        "ready_with_support": f"Can take this on as {role} with coaching on {', '.join(focus) or 'a few areas'}.",
        "not_ready": f"Not ready to handle these situations alone yet. Review the material and redo the interview by {retake_by}.",
    }[level]
    next_steps = {
        "ready": ["No further action needed for this training", "Next refresher follows the normal retraining cycle"],
        "ready_with_support": [f"Pair with a mentor or lead on {', '.join(focus) or 'the weaker areas'} for the first 30 days",
                               "Manager check-in after 30 days", "Optional: redo the interview to move to Ready"],
        "not_ready": ["Review the recommended modules below", f"Redo the interview by {retake_by}",
                      "Talk it through with your manager or a mentor before the retake"],
    }[level]
    detail = {"label": READINESS_LABEL[level], "summary": summary, "next_steps": next_steps, "competencies": competencies,
              "focus_areas": focus, "review_modules": review[:3],
              "inputs": {"interview": overall, "weakest_competency": {"name": weakest_name, "score": weakest},
                         "skill_mastery_pct": round(skill_pct, 1), "quiz_best": quiz_pct,
                         "scored_by": "manager" if session.manager_overall is not None else session.scored_by}}
    session.readiness, session.readiness_score, session.readiness_detail = level, score, detail
    return {"readiness": level, "readiness_score": score, **detail}
