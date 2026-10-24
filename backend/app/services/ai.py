"""AI content generation.

Uses Claude when ANTHROPIC_API_KEY is set. Without a key (or if a call fails)
every function falls back to content built from the training's own outline, so
the platform still works offline and in demos. Responses say which one ran in
the `generated_by` field.

Refusal handling: requests opt into server-side fallbacks ("default"), and any
remaining refusal drops to the offline generator.
"""
from __future__ import annotations

import json
import logging
import random
import re
from typing import Any

from ..config import settings
from .. import models
from ..safeguards import ai_guard

log = logging.getLogger(__name__)

SYSTEM = (
    "You are the instructional designer inside Los Alamos National Laboratory's adaptive training platform. "
    "You write training material for LANL employees that is accurate, practical and specific to their job role, "
    "procedures, equipment and facilities. Follow LANL's safety-first culture: when a topic involves hazards, "
    "say plainly what to do and who to contact, and point back to the official procedure or the source training "
    "for anything authoritative. Never invent specific LANL document numbers, phone numbers or limits; say "
    "'see the official procedure' instead. Match the requested difficulty, pacing and delivery method exactly."
)

_client = None


def ai_enabled() -> bool:
    return bool(settings.anthropic_api_key)


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120, max_retries=2)
    return _client


def _call_json(prompt: str, schema: dict, max_tokens: int = 8000) -> dict | None:
    """One Claude call that returns JSON matching `schema`, or None to signal fallback."""
    if not ai_enabled() or not ai_guard.acquire():
        return None
    ok = False
    try:
        result = _call_json_inner(prompt, schema, max_tokens)
        ok = result is not None
        return result
    finally:
        ai_guard.release(ok)


def _call_json_inner(prompt: str, schema: dict, max_tokens: int) -> dict | None:
    import anthropic

    try:
        resp = _get_client().beta.messages.create(
            model=settings.ai_model,
            max_tokens=max_tokens,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM,
            output_config={"effort": settings.ai_effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.RateLimitError:
        log.warning("Claude rate limited; using offline content")
        return None
    except anthropic.APIStatusError as exc:
        log.warning("Claude API error %s: %s", exc.status_code, exc.message)
        return None
    except anthropic.APIConnectionError:
        log.warning("Claude unreachable; using offline content")
        return None
    if resp.stop_reason in ("refusal", "max_tokens"):
        log.warning("Claude stop_reason=%s; using offline content", resp.stop_reason)
        return None
    text = "".join(b.text for b in resp.content if b.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("Claude returned invalid JSON; using offline content")
        return None


def call_json_long(prompt: str, schema: dict, max_tokens: int = 32000, system_extra: str = "") -> dict | None:
    """Like _call_json but streams, for long documents and long outputs (avoids HTTP timeouts)."""
    if not ai_enabled() or not ai_guard.acquire():
        return None
    ok = False
    try:
        result = _call_json_long_inner(prompt, schema, max_tokens, system_extra)
        ok = result is not None
        return result
    finally:
        ai_guard.release(ok)


def _call_json_long_inner(prompt: str, schema: dict, max_tokens: int, system_extra: str) -> dict | None:
    import anthropic

    try:
        with _get_client().beta.messages.stream(
            model=settings.ai_model,
            max_tokens=max_tokens,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM + ("\n\n" + system_extra if system_extra else ""),
            output_config={"effort": settings.ai_effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            resp = stream.get_final_message()
    except anthropic.RateLimitError:
        log.warning("Claude rate limited; using offline content")
        return None
    except anthropic.APIStatusError as exc:
        log.warning("Claude API error %s: %s", exc.status_code, exc.message)
        return None
    except anthropic.APIConnectionError:
        log.warning("Claude unreachable; using offline content")
        return None
    if resp.stop_reason in ("refusal", "max_tokens"):
        log.warning("Claude stop_reason=%s; using offline content", resp.stop_reason)
        return None
    text = "".join(b.text for b in resp.content if b.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("Claude returned invalid JSON; using offline content")
        return None


def _call_text(system_extra: str, messages: list[dict], max_tokens: int = 4000) -> str | None:
    if not ai_enabled() or not ai_guard.acquire():
        return None
    ok = False
    try:
        result = _call_text_inner(system_extra, messages, max_tokens)
        ok = result is not None
        return result
    finally:
        ai_guard.release(ok)


def _call_text_inner(system_extra: str, messages: list[dict], max_tokens: int) -> str | None:
    import anthropic

    try:
        resp = _get_client().beta.messages.create(
            model=settings.ai_model,
            max_tokens=max_tokens,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM + "\n\n" + system_extra,
            output_config={"effort": "low"},
            messages=messages,
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        log.warning("Claude chat failed: %s", exc)
        return None
    if resp.stop_reason == "refusal":
        return None
    return "".join(b.text for b in resp.content if b.type == "text") or None


# ---- shared context -----------------------------------------------------------

def _learner_block(emp: models.Employee, profile: dict) -> str:
    pacing = profile.get("pacing", {})
    return (
        f"Learner: {emp.job_title or 'employee'} (level {emp.level}) in division {emp.division_code}, "
        f"{emp.years_experience:g} years relevant experience.\n"
        f"Stated learning style: {emp.learning_style}. Best-performing delivery method so far: {profile.get('modality')}.\n"
        f"Difficulty: {profile.get('difficulty')}. Pacing: {pacing.get('pace')} "
        f"(about {pacing.get('chunk_minutes')} minute chunks, {pacing.get('examples_per_concept')} examples per concept).\n"
        f"Current mastery by skill (0-1): {json.dumps(profile.get('mastery', {}))}\n"
        f"Background: {emp.background or 'not provided'}"
    )


def _training_block(t: models.Training) -> str:
    from .library import excerpt_for

    source = excerpt_for(t.code)  # the admin library's material for this training, when it has one
    return (
        f"Training {t.code}: {t.title}\nCategory: {t.category}. Delivery: {t.delivery}. Source: {t.source_system} {t.source_url}\n"
        f"Description: {t.description}\nSkills: {', '.join(t.skills or [])}\n"
        f"Equipment: {', '.join(t.equipment or []) or 'none'}. Facilities: {', '.join(t.facilities or []) or 'none'}\n"
        f"Outline:\n{t.outline}"
        + (f"\n\nSource material from the training library (teach from this; don't invent requirements it doesn't state):\n"
           f"<source>\n{source}\n</source>" if source else "")
    )


def _topics(t: models.Training) -> list[str]:
    lines = [l.strip(" -•\t") for l in (t.outline or "").splitlines() if l.strip(" -•\t")]
    return lines or [t.title]


# ---- lessons ------------------------------------------------------------------

LESSON_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "overview": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "kind": {"type": "string", "enum": ["text", "visual", "simulation", "exercise", "check"]},
                    "body": {"type": "string"},
                    "diagram_steps": {"type": "array", "items": {"type": "string"}},
                    "scenario": {"type": "string"},
                    "choices": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}, "correct": {"type": "boolean"}, "feedback": {"type": "string"}},
                            "required": ["text", "correct", "feedback"],
                            "additionalProperties": False,
                        },
                    },
                    "exercise_steps": {"type": "array", "items": {"type": "string"}},
                    "skill": {"type": "string"},
                },
                "required": ["heading", "kind", "body", "diagram_steps", "scenario", "choices", "exercise_steps", "skill"],
                "additionalProperties": False,
            },
        },
        "key_points": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "overview", "sections", "key_points"],
    "additionalProperties": False,
}


def generate_lesson(emp: models.Employee, t: models.Training, profile: dict, request: str = "", source: str = "") -> dict:
    prompt = (
        f"{_training_block(t)}\n\n{_learner_block(emp, profile)}\n\n"
        "Write one lesson for this learner. Lead with the delivery method that works best for them "
        f"({profile.get('modality')}) but mix in at least one other kind. Use these section kinds:\n"
        "- text: explanation in `body`.\n- visual: a visual demonstration; put the ordered steps of the diagram in `diagram_steps`.\n"
        "- simulation: a realistic workplace scenario at LANL in `scenario`, with 3-4 `choices` (one correct) and feedback for each.\n"
        "- exercise: a guided exercise with `exercise_steps`.\n- check: a quick knowledge check in `body`.\n"
        "Leave fields that don't apply to a section as empty strings or empty arrays. Set `skill` to the skill each section builds.\n"
        "At intro difficulty, start broad and define terms. At advanced difficulty, focus on edge cases and judgment calls.\n"
        + (f"\nThe learner asked: {request}\n" if request else "")
        + (f"\nTeach from this source material (cite it, don't invent beyond it):\n<source>\n{source}\n</source>\n" if source else "")
    )
    data = _call_json(prompt, LESSON_SCHEMA, max_tokens=12000)
    if data:
        data["generated_by"] = settings.ai_model
    else:
        data = _offline_lesson(emp, t, profile, request)
    data.update({"training_code": t.code, "difficulty": profile.get("difficulty"), "modality": profile.get("modality"),
                 "pacing": profile.get("pacing")})
    return data


def _offline_lesson(emp: models.Employee, t: models.Training, profile: dict, request: str) -> dict:
    topics = _topics(t)
    diff = profile.get("difficulty") or "intro"
    modality = profile.get("modality") or "text"
    skills = t.skills or [t.category]
    per_chunk = {"slow": 2, "steady": 3, "fast": 5}.get(profile.get("pacing", {}).get("pace", "steady"), 3)
    chunk = topics[:per_chunk] if diff == "intro" else topics
    sections = []
    intro_line = {
        "intro": "This lesson starts with the big picture and the vocabulary you'll hear on the job.",
        "intermediate": "You already know the basics, so this lesson connects them to day-to-day procedures.",
        "advanced": "This lesson focuses on edge cases and judgment calls.",
    }[diff]
    sections.append(_section("Why this matters", "text",
                             f"{t.description or t.title} {intro_line} As a {emp.job_title or 'LANL employee'}, "
                             f"you'll use this whenever you work with {', '.join(t.equipment or t.facilities or ['these processes'])}.",
                             skill=skills[0]))
    order = [modality] + [m for m in ("visual", "simulation", "exercise", "text") if m != modality]
    for i, topic in enumerate(chunk):
        kind = order[i % len(order)] if modality != "quiz" else order[(i + 1) % len(order)]
        skill = skills[i % len(skills)]
        if kind == "visual":
            sections.append(_section(topic, "visual", f"Follow the flow for: {topic}.",
                                     diagram_steps=["Identify the task and hazards", f"Apply: {topic}", "Verify controls are in place",
                                                    "Proceed, or stop and ask", "Document and report"], skill=skill))
        elif kind == "simulation":
            sections.append(_section(topic, "simulation", "Pick what you would do.",
                                     scenario=f"You're about to start work involving {topic.lower()} and notice something doesn't match the procedure.",
                                     choices=[
                                         {"text": "Pause the work, report it to your supervisor, and check the procedure", "correct": True,
                                          "feedback": "Right. Stopping and asking is always acceptable at LANL."},
                                         {"text": "Continue carefully since you're nearly done", "correct": False,
                                          "feedback": "Finishing quickly doesn't make an unexpected condition safe."},
                                         {"text": "Fix it yourself without telling anyone", "correct": False,
                                          "feedback": "Unreported changes bypass the controls that keep others safe."},
                                     ], skill=skill))
        elif kind == "exercise":
            sections.append(_section(topic, "exercise", f"Work through {topic.lower()} step by step.",
                                     exercise_steps=[f"Find the section of the official procedure covering {topic.lower()}",
                                                     "Write down the hazards or failure points", "List the controls or checks that address each one",
                                                     "Explain it to a coworker or your mentor in two sentences"], skill=skill))
        else:
            depth = {"intro": "Start with what it is and why it exists.", "intermediate": "Focus on how it's applied in your work.",
                     "advanced": "Consider what goes wrong and how you'd catch it early."}[diff]
            sections.append(_section(topic, "text", f"{topic}. {depth} See {t.source_system} course {t.code} for the authoritative version.", skill=skill))
    sections.append(_section("Quick check", "check", f"In one sentence, explain how {topics[0].lower()} applies to your job.", skill=skills[0]))
    return {
        "title": f"{t.title}{': ' + request if request else ''}",
        "overview": f"A {diff} lesson tuned for a {profile.get('pacing', {}).get('pace', 'steady')} pace, led by {modality} content.",
        "sections": sections,
        "key_points": [f"{tp}" for tp in topics[:4]] + ["When in doubt, stop and ask."],
        "generated_by": "offline",
    }


def _section(heading, kind, body, diagram_steps=None, scenario="", choices=None, exercise_steps=None, skill=""):
    return {"heading": heading, "kind": kind, "body": body, "diagram_steps": diagram_steps or [], "scenario": scenario,
            "choices": choices or [], "exercise_steps": exercise_steps or [], "skill": skill}


# ---- questions ----------------------------------------------------------------

QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "answer_index": {"type": "integer"},
                    "explanation": {"type": "string"},
                    "skill": {"type": "string"},
                },
                "required": ["question", "options", "answer_index", "explanation", "skill"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}


def practice_questions(emp: models.Employee, t: models.Training, profile: dict, n: int = 5, focus_skills: list[str] | None = None) -> dict:
    focus = focus_skills or sorted(t.skills or [], key=lambda s: profile.get("mastery", {}).get(s, 0))[:3]
    prompt = (
        f"{_training_block(t)}\n\n{_learner_block(emp, profile)}\n\n"
        f"Write {n} multiple-choice practice questions with 4 options each. Weight them toward the weakest skills: "
        f"{', '.join(focus) or 'all skills'}. Set `skill` to one of: {', '.join(t.skills or [t.category])}. "
        "Prefer realistic job scenarios over recall. `answer_index` is 0-based. Explanations should teach, not just restate."
    )
    data = _call_json(prompt, QUESTIONS_SCHEMA, max_tokens=8000)
    if data and data.get("questions"):
        qs = [q for q in data["questions"] if len(q["options"]) >= 2 and 0 <= q["answer_index"] < len(q["options"])]
        return {"questions": qs[:n], "generated_by": settings.ai_model, "focus_skills": focus}
    return {"questions": _offline_questions(t, n, focus), "generated_by": "offline", "focus_skills": focus}


def _offline_questions(t: models.Training, n: int, focus: list[str]) -> list[dict]:
    topics = _topics(t)
    skills = focus or t.skills or [t.category]
    rng = random.Random(f"{t.code}-{n}-{len(topics)}")
    templates = [
        ("You're unsure whether a step in {topic} applies to today's task. What should you do first?",
         ["Stop and check the procedure or ask your supervisor", "Skip the step to save time", "Ask a coworker to do it for you",
          "Do it the way you did last time"], "Stopping to verify is always the expected action."),
        ("Which best describes the purpose of {topic}?",
         ["Reducing risk to people, the mission and the facility", "Meeting a paperwork deadline only",
          "It is optional when work is urgent", "It only applies to supervisors"], "Controls exist to protect people and work, not just for compliance."),
        ("During work involving {topic}, conditions change from what was planned. What is the right response?",
         ["Pause, reassess, and get the plan updated before continuing", "Continue since the plan was already approved",
          "Finish quickly before anyone notices", "Leave the area without telling anyone"], "A changed condition means the original plan may no longer be valid."),
        ("Where is the authoritative source for {topic}?",
         [f"The official procedure and {t.source_system} course {t.code}", "A coworker's notes", "An internet search", "Memory from a past job"],
         "Always work from the current official procedure."),
    ]
    out = []
    for i in range(n):
        topic = topics[i % len(topics)].lower()
        q, opts, why = templates[i % len(templates)]
        correct = opts[0]
        shuffled = opts[:]
        rng.shuffle(shuffled)
        out.append({"question": q.format(topic=topic), "options": shuffled, "answer_index": shuffled.index(correct),
                    "explanation": why, "skill": skills[i % len(skills)]})
    return out


# ---- tutor chat ---------------------------------------------------------------

def tutor_reply(emp: models.Employee, t: models.Training | None, profile: dict, history: list[dict], message: str) -> dict:
    context = _training_block(t) if t else "No specific training selected."
    system_extra = (
        f"You are now a one-on-one tutor in a chat.\n{context}\n\n{_learner_block(emp, profile)}\n\n"
        "Keep replies short and conversational (under 200 words). Adjust to the learner's difficulty and pacing. "
        "End with one short question that checks understanding. If asked to customize the lesson, explain what you'd change."
    )
    msgs = [{"role": m["role"], "content": m["content"]} for m in history[-10:] if m.get("role") in ("user", "assistant") and m.get("content")]
    msgs.append({"role": "user", "content": message})
    text = _call_text(system_extra, msgs)
    if text:
        return {"reply": text, "generated_by": settings.ai_model}
    topic = _topics(t)[0] if t else "your training"
    return {
        "reply": (f"(Offline tutor) Good question. For {t.title if t else 'this topic'}, start with {topic.lower()}: "
                  f"what it is, why it exists, and when it applies to your work as a {emp.job_title or 'LANL employee'}. "
                  f"Check the official {t.source_system + ' ' if t else ''}material for exact requirements. "
                  "Can you describe a situation in your job where this would come up?"),
        "generated_by": "offline",
    }


# ---- skill inference ----------------------------------------------------------

SKILLS_SCHEMA = {
    "type": "object",
    "properties": {
        "skills": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"skill": {"type": "string"}, "confidence": {"type": "number"}, "evidence": {"type": "string"}},
                "required": ["skill", "confidence", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["skills"],
    "additionalProperties": False,
}


def infer_skills(emp: models.Employee, vocabulary: list[str], completed: list[dict]) -> dict:
    """Estimate skills from background text and training history. Returns {skill: {confidence, evidence}}."""
    prompt = (
        f"Employee: {emp.job_title}, level {emp.level}, {emp.years_experience:g} years experience, division {emp.division_code}.\n"
        f"Background: {emp.background or 'not provided'}\n"
        f"Completed trainings with scores: {json.dumps(completed)}\n\n"
        f"From this vocabulary only: {', '.join(vocabulary)}\n"
        "List the skills this person likely has, with confidence 0-1 and one short line of evidence. Be conservative: "
        "a completed training with a low score is weak evidence, and job title alone is moderate evidence."
    )
    data = _call_json(prompt, SKILLS_SCHEMA, max_tokens=4000)
    if data:
        vocab = set(vocabulary)
        return {"generated_by": settings.ai_model,
                "skills": {s["skill"].lower(): {"confidence": max(0, min(1, s["confidence"])), "evidence": s["evidence"]}
                           for s in data["skills"] if s["skill"].lower() in vocab}}
    # Offline: keyword match against background and title.
    text = f"{emp.background} {emp.job_title}".lower()
    found = {}
    for skill in vocabulary:
        words = [w for w in re.split(r"[\s_\-/]+", skill) if len(w) > 2]
        if skill in text or (words and all(w in text for w in words)):
            found[skill] = {"confidence": 0.55, "evidence": "mentioned in background or job title"}
    for c in completed:
        for s in c.get("skills", []):
            conf = 0.5 if c.get("score") is None else min(1.0, c["score"] / 100) * 0.9
            if conf > found.get(s, {}).get("confidence", 0):
                found[s] = {"confidence": round(conf, 2), "evidence": f"completed {c['code']}"}
    return {"generated_by": "offline", "skills": found}
