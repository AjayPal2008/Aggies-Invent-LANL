import {
  api, requireRole, topbar, router, esc, $, $$, fmtDate, fmtTime, dueText, statusBadge, bar, toast, modal, loading,
  CATEGORY_LABEL, DELIVERY_LABEL,
} from "/shared/api.js?v=20261025a";
import { videoPlayer, interviewFlow, rolePlanCard, showResult } from "./learning.js";
import { speak, stopSpeaking, speakButton } from "/shared/a11y.js?v=20261025a";
import { diagnosticView, diagnosticResults } from "./diagnostic.js";
import { reviewStudio, mindMap, readProgress, progressPanel, inProgressPanel } from "./review-studio.js?v=20261025g";

const me = await requireRole(["hire", "manager", "admin"]);
topbar(me, "My Training");
if (isNewEmployee()) $(".who").innerHTML = "<strong>Demo new Hire</strong>";
const view = $("#view");
let dash = null; // cached /api/me/dashboard
const studio = { code: null, lesson: null, chat: [], module: null };

async function refresh() { dash = await api.get("/api/me/dashboard"); return dash; }

const MODALITY_LABEL = { video: "Video", text: "Reading", visual: "Visual demonstration", simulation: "Simulation", quiz: "Quiz practice", exercise: "Guided exercise" };
const LEVEL_LABEL = { intro: "Introductory", intermediate: "Intermediate", advanced: "Advanced" };

// ---- Overview ---------------------------------------------------------------

async function overview() {
  loading(view);
  if (isNewEmployee()) {
    await diagnosticOverview();
    return;
  }
  const [d, plan] = await Promise.all([refresh(), api.get("/api/me/role-plan").catch(() => null)]);
  const s = d.summary;
  const b = d.buckets;
  const first = me.name.split(" ")[0];
  view.innerHTML = `
    <div class="hero">
      <h1>Welcome back, ${esc(first)}</h1>
      <p>${d.employee.is_new_hire ? "You're in your first year. Your plan starts broad and gets more specific as you go." : "Here's what needs your attention."}
         ${b.overdue.length ? `<strong>${b.overdue.length} overdue.</strong>` : ""}</p>
    </div>
    ${rolePlanCard(plan)}
    <div class="grid cols-4" style="margin-bottom:16px">
      ${stat("Overdue", b.overdue.length, "bad", "overdue")}
      ${stat("Due in 14 days", b.upcoming.length, "warn", "upcoming")}
      ${stat("In progress", s.in_progress, "", "in_progress")}
      ${stat("Completed", `${s.completed}<span class="muted small"> / ${s.total}</span>`, "ok", "completed")}
    </div>
    <div class="grid side">
      <section class="card">
        <div class="card-head"><h2>Your learning path</h2><span class="muted small">Ordered by urgency, gaps and prerequisites</span></div>
        <div class="list">${d.path.map(pathItem).join("") || `<div class="empty">You're all caught up.</div>`}</div>
      </section>
      <div class="grid" style="align-content:start">
        <section class="card">
          <div class="card-head"><h3>Knowledge gaps</h3><span class="badge">${d.gaps.length}</span></div>
          ${gapsHtml(d.gaps.slice(0, 8))}
        </section>
        <section class="card">
          <h3>How you're learning</h3>
          ${profileSummary(d.profile)}
        </section>
      </div>
    </div>`;
  $$(".stat[data-flag]").forEach((el) => el.addEventListener("click", () => { trainingsFilter.flag = el.dataset.flag; go("studio"); }));
  wirePathButtons();
}

function isNewEmployee() {
  let selected = new URLSearchParams(location.search).get("new_employee") === "1";
  try { selected ||= sessionStorage.getItem("lanl_employee_path") === "new"; } catch { /* optional storage */ }
  return selected && me.email?.toLowerCase() === "hire@lanl.gov";
}

async function diagnosticOverview() {
  try {
    const latest = await api.get("/api/diagnostic/latest-completed");
    if (!latest.available) {
      view.innerHTML = `<section class="hero"><h1>Welcome, ${esc(me.name.split(" ")[0])}</h1><p>Complete your diagnostic to build your learning path.</p></section>
        <section class="card"><h2>Your learning path</h2><p>No diagnostic completed yet. Knowledge gaps and progress have not been assessed.</p>
        <button class="btn" id="overview-start">Take diagnostic</button></section>`;
      $("#overview-start").onclick = () => go("diagnostic");
      return;
    }
    const r = latest.report;
    const objectives = new Map(r.objectives.map(o => [o.objective_id, o]));
    const review = r.review_priority.map(id => objectives.get(id)).filter(Boolean);
    const uncertain = r.objectives.filter(o => o.status === "not assessed");
    const positive = r.objectives.filter(o => o.status === "evidence of understanding");
    const metric = (label, value) => `<div class="stat"><div class="label">${label}</div><div class="value">${value}</div></div>`;
    view.innerHTML = `<section class="hero"><h1>Your diagnostic progress</h1><p>Based on your latest completed diagnostic. Required training completion is tracked separately.</p></section>
      <div class="grid cols-4" style="margin-bottom:16px">${metric("Questions answered", r.questions_answered)}${metric("Answers correct", r.answers_correct)}${metric("Answers incorrect", r.questions_answered - r.answers_correct)}${metric("Reasons correct", r.reasons_correct)}</div>
      <div class="grid side"><section class="card"><div class="card-head"><h2>Your learning path</h2><span class="muted small">Important concepts needing review first</span></div>
      <div class="list">${review.map((o, i) => `<div class="item"><span class="badge">${i + 1}</span><div class="grow"><div class="title">${esc(o.name)}</div><p class="small muted">${esc(o.article_id.replaceAll("-", " "))} ? Priority ${o.importance}</p>
      <details><summary>Review source material</summary><blockquote>${esc(o.review_resources.excerpt)}</blockquote><p class="small">Resource points: ${o.review_resources.resource_point_ids.map(esc).join(", ")}</p></details></div></div>`).join("") || '<p>No review gap was observed in tested concepts.</p>'}</div></section>
      <div class="grid" style="align-content:start"><section class="card"><div class="card-head"><h3>Knowledge gaps</h3><span class="badge">${review.length}</span></div>
      <div class="list">${review.map(o => `<div><strong>${esc(o.name)}</strong><p class="small">${esc(o.observed_gap)}</p><span class="badge warn">${esc(o.status)}</span></div>`).join("") || '<p>No observed gaps. Untested concepts remain uncertain.</p>'}</div></section>
      <section class="card"><h3>Assessment coverage</h3><p>${positive.length} concepts with evidence of understanding.</p><p>${uncertain.length} concepts not assessed.</p><p>Reasoning incorrect: ${r.questions_answered - r.reasons_correct}.</p></section></div></div>
      <button class="btn" id="overview-trainings" style="margin-top:16px">Open my review courses</button>
      <button class="btn secondary" id="overview-results" style="margin-top:16px">View diagnostic responses and results</button>`;
    $("#overview-trainings").onclick = () => go("studio");
    $("#overview-results").onclick = () => {
      localStorage.setItem(`lanl_diagnostic_${me.id}_new_employee`, r.session_id);
      localStorage.setItem(`lanl_diagnostic_${me.id}`, r.session_id);
      go("diagnostic-results");
    };
  } catch (error) {
    view.innerHTML = `<section class="card"><h2>Diagnostic progress unavailable</h2><p role="alert">${esc(error.message)}</p><button class="btn" id="overview-retry">Try again</button></section>`;
    $("#overview-retry").onclick = diagnosticOverview;
  }
}

function stat(label, value, cls, flag) {
  return `<div class="stat ${cls} clickable" data-flag="${flag}"><div class="label">${label}</div><div class="value num">${value}</div></div>`;
}

function pathItem(p, i) {
  const urgent = p.reasons.some((r) => r === "overdue" || r === "retake needed");
  return `<div class="item">
    <div class="badge ${urgent ? "bad" : ""}" style="min-width:28px;text-align:center">${i + 1}</div>
    <div class="grow">
      <div class="title">${esc(p.title)} <span class="muted small">${esc(p.training_code)}</span></div>
      <div class="small muted">${p.reasons.map(esc).join(" · ")}</div>
      <div class="chips" style="margin-top:4px">
        <span class="badge plain">${CATEGORY_LABEL[p.category] || p.category}</span>
        <span class="badge plain">${DELIVERY_LABEL[p.delivery]}</span>
        <span class="badge">${LEVEL_LABEL[p.difficulty]}</span>
        <span class="badge">Best for you: ${MODALITY_LABEL[p.suggested_modality]}</span>
      </div>
    </div>
    <button class="btn small" data-learn="${esc(p.training_code)}">Learn</button>
  </div>`;
}

function wirePathButtons(root = view) {
  $$("[data-learn]", root).forEach((b) => b.addEventListener("click", () => { studio.code = b.dataset.learn; studio.lesson = null; studio.chat = []; go("assigned-studio"); }));
}

function gapsHtml(gaps) {
  if (!gaps.length) return `<p class="muted">No gaps found for your role and assignments.</p>`;
  return `<div class="list">${gaps.map((g) => `
    <div>
      <div style="display:flex;justify-content:space-between" class="small"><strong>${esc(g.skill)}</strong>
        <span class="muted num">${Math.round(g.mastery * 100)}%</span></div>
      ${bar(g.mastery * 100, g.severity === "high" ? "bad" : "warn")}
      <div class="small muted">${g.why.slice(0, 2).map(esc).join(", ")}</div>
    </div>`).join("")}</div>`;
}

function profileSummary(p) {
  const top = Object.entries(p.modality_scores).sort((a, b) => b[1] - a[1]);
  const max = top[0][1];
  return `
    <p class="small"><strong>Pace:</strong> ${esc(p.pacing.pace)} · ${esc(p.pacing.reason)}</p>
    <p class="small"><strong>Stated style:</strong> ${esc(p.learning_style)} · <strong>Works best:</strong> ${MODALITY_LABEL[p.modality]}</p>
    <div class="list">${top.map(([m, v]) => `<div class="small">${MODALITY_LABEL[m]} ${bar((v / max) * 100)}</div>`).join("")}</div>`;
}

// ---- My trainings -----------------------------------------------------------

const trainingsFilter = { category: "", required: "", status: "", flag: "", sort: "due_date" };

async function trainings() { return studioView(); }

async function assignedTrainings() {

  const f = trainingsFilter;
  view.innerHTML = `
    <div class="card-head"><h1>Learning studio</h1></div>
    <div class="toolbar">
      <div class="chips" id="cat-chips">
        ${["", "safety", "technical", "culture", "compliance"].map((c) => `<button class="chip ${f.category === c ? "active" : ""}" data-cat="${c}">${c ? CATEGORY_LABEL[c] : "All categories"}</button>`).join("")}
      </div>
    </div>
    <div class="toolbar">
      <label class="field">Required
        <select id="f-req"><option value="">Required and optional</option><option value="true">Required</option><option value="false">Optional</option></select></label>
      <label class="field">Status
        <select id="f-status"><option value="">Any status</option><option value="not_started">Not started</option><option value="in_progress">In progress</option><option value="completed">Completed</option></select></label>
      <label class="field">Show
        <select id="f-flag"><option value="">Everything</option><option value="overdue">Overdue</option><option value="upcoming">Due in 14 days</option><option value="needs_retake">Retake needed</option><option value="expiring">Expiring soon</option></select></label>
      <label class="field">Sort by
        <select id="f-sort"><option value="due_date">Due date</option><option value="title">Title</option><option value="status">Status</option><option value="category">Category</option></select></label>
    </div>
    <div id="list"></div>`;
  $("#f-req").value = f.required; $("#f-status").value = f.status; $("#f-flag").value = f.flag; $("#f-sort").value = f.sort;
  $$("#cat-chips .chip").forEach((c) => c.addEventListener("click", () => { f.category = c.dataset.cat; trainings(); }));
  [["#f-req", "required"], ["#f-status", "status"], ["#f-flag", "flag"], ["#f-sort", "sort"]].forEach(([sel, key]) =>
    $(sel).addEventListener("change", (e) => { f[key] = e.target.value; loadList(); }));
  loadList();
}

async function loadList() {
  const f = trainingsFilter;
  const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v !== ""));
  const list = $("#list");
  loading(list);
  const items = await api.get(`/api/me/assignments?${q}`);
  list.innerHTML = items.length ? `<div class="list">${items.map(assignmentItem).join("")}</div>` : `<div class="empty card">Nothing matches these filters.</div>`;
  wireAssignmentButtons(list);
}

function assignmentItem(a) {
  const t = a.training;
  const done = a.status === "completed";
  return `<div class="item">
    <div class="grow">
      <div class="title">${esc(t.title)} <span class="muted small">${esc(t.code)}</span> ${statusBadge(a)} ${readinessBadge(a)}</div>
      <div class="small muted">
        ${CATEGORY_LABEL[t.category] || t.category} · ${t.required ? "Required" : "Optional"} · ${DELIVERY_LABEL[t.delivery]} · ${t.duration_minutes} min ·
        from <a href="${esc(t.source_url)}" target="_blank" rel="noopener">${esc(t.source_system)}</a>
      </div>
      <div class="small" style="margin-top:4px">
        ${done ? `Completed ${fmtDate(a.completed_at)}${a.best_score != null ? ` · score ${a.best_score}` : ""}${a.expires_at ? ` · expires ${fmtDate(a.expires_at)}` : ""}${a.next_retraining ? ` · next retraining ${fmtDate(a.next_retraining)}` : ""}`
               : `${dueText(a.due_date)}${a.due_date ? ` (${fmtDate(a.due_date)})` : ""}${a.best_score != null ? ` · best score ${a.best_score}` : ""}`}
        ${a.session ? ` · Registered: ${fmtDate(a.session.starts_at)} ${fmtTime(a.session.starts_at)}, ${esc(a.session.location)}` : ""}
      </div>
      ${done ? "" : `<div style="max-width:320px;margin-top:6px">${bar(a.progress)}</div>`}
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">
      <button class="btn small" data-learn="${esc(t.code)}">${done ? "Review" : "Learn"}</button>
      ${t.delivery !== "online" && !done ? `<button class="btn secondary small" data-sessions="${a.id}" data-code="${esc(t.code)}">${a.session ? "Change class" : "Pick a class"}</button>` : ""}
      ${assessButtons(a, done)}
    </div>
  </div>`;
}

/** Jump to one module of a course in the learning studio (used by "Review these modules"). */
function openModule(code, moduleId) {
  studio.code = code; studio.module = moduleId; studio.lesson = null; studio.chat = [];
  go("assigned-studio");
}

function readinessBadge(a) {
  if (!a.readiness) return "";
  const cls = { ready: "ok", ready_with_support: "warn", not_ready: "bad" }[a.readiness.readiness] || "";
  return `<button class="badge ${cls}" data-result="${a.readiness.session_id}" style="border:0;cursor:pointer" title="See the full result">Readiness: ${esc(a.readiness.label)}</button>`;
}

function assessButtons(a, done) {
  const type = a.training.assessment_type || "quiz";
  const quiz = `<button class="btn secondary small" data-assess="${a.id}">${done ? "Retake quiz" : "Take quiz"}</button>`;
  const iv = `<button class="btn secondary small" data-interview="${a.id}" title="Scenario-based, like CASPer">${done ? "Redo interview" : "Start interview"}</button>`;
  return type === "situational" ? iv : type === "both" ? quiz + iv : quiz;
}

function wireAssignmentButtons(root) {
  $$("[data-interview]", root).forEach((b) => b.addEventListener("click", () => interviewFlow(Number(b.dataset.interview), () => { dash = null; }, openModule)));
  $$("[data-result]", root).forEach((b) => b.addEventListener("click", async () => {
    const m = modal(`<div class="empty"><span class="spinner"></span></div>`, { wide: true });
    showResult(m, await api.get(`/api/me/interviews/${b.dataset.result}`), openModule);
  }));
  wirePathButtons(root);
  $$("[data-assess]", root).forEach((b) => b.addEventListener("click", () => assessment(Number(b.dataset.assess))));
  $$("[data-sessions]", root).forEach((b) => b.addEventListener("click", () => pickSession(Number(b.dataset.sessions), b.dataset.code)));
}

async function pickSession(assignmentId, code) {
  const t = await api.get(`/api/trainings/${encodeURIComponent(code)}`);
  const upcoming = t.sessions.filter((s) => new Date(s.starts_at) > new Date());
  const m = modal(`
    <div class="modal-head"><h2>Classes for ${esc(t.title)}</h2><button class="btn ghost" data-close>Close</button></div>
    ${upcoming.length ? `<div class="list">${upcoming.map((s) => `
      <div class="item"><div class="grow"><div class="title">${fmtDate(s.starts_at, { weekday: "long", month: "short", day: "numeric" })}, ${fmtTime(s.starts_at)}–${fmtTime(s.ends_at)}</div>
      <div class="small muted">${esc(s.location)} · Instructor ${esc(s.instructor)} · ${s.capacity} seats</div></div>
      <button class="btn small" data-session="${s.id}">Register</button></div>`).join("")}</div>`
      : `<p class="muted">No upcoming classes are scheduled. Check <a href="${esc(t.source_url)}" target="_blank">${esc(t.source_system)}</a>.</p>`}`);
  $$("[data-session]", m.root).forEach((b) => b.addEventListener("click", async () => {
    try {
      await api.post(`/api/me/assignments/${assignmentId}/register`, { session_id: Number(b.dataset.session) });
      toast("Registered. It's on your calendar.");
      m.close();
      go(location.hash.slice(1));
    } catch (e) { toast(e.message, true); }
  }));
}

// ---- Assessment -------------------------------------------------------------

async function assessment(assignmentId) {
  const m = modal(`<div class="empty"><span class="spinner"></span> Building your assessment…</div>`, { wide: true });
  try {
    const a = await api.post(`/api/me/assignments/${assignmentId}/assessment`);
    m.root.innerHTML = `
      <div class="modal-head"><h2>Assessment</h2><button class="btn ghost" data-close>Close</button></div>
      <p class="muted small">${a.questions.length} questions. You need 80% to pass. ${a.generated_by === "offline" ? "(Offline question bank)" : ""}</p>
      <form id="assess-form" class="list">
        ${a.questions.map((q, i) => `
          <fieldset class="card flat" data-speak-scope><legend><strong>${i + 1}. ${esc(q.question)}</strong> ${speakButton("Read question")}</legend>
            ${q.options.map((o, j) => `<label class="small" style="display:block;padding:4px 0"><input type="radio" name="q${i}" value="${j}" required> ${esc(o)}</label>`).join("")}
          </fieldset>`).join("")}
        <button class="btn" type="submit">Submit answers</button>
      </form>`;
    $("#assess-form", m.root).addEventListener("submit", async (e) => {
      e.preventDefault();
      const answers = a.questions.map((_, i) => Number(new FormData(e.target).get(`q${i}`)));
      const r = await api.post(`/api/me/assessments/${a.assessment_id}/submit`, { answers });
      m.root.innerHTML = `
        <div class="modal-head"><h2>${r.passed ? "Passed" : "Not passed yet"}: ${r.score}%</h2><button class="btn ghost" data-close>Close</button></div>
        <p>${r.passed ? `Nice work. ${r.assignment.next_retraining ? `Your next refresher is ${fmtDate(r.assignment.next_retraining)}.` : ""}`
                      : `You can retake it once you've reviewed the material. We've scheduled a retake by ${fmtDate(r.assignment.next_retraining)} and adjusted your lessons toward the topics you missed.`}</p>
        <div class="list">${r.review.map((x, i) => `
          <div class="card flat"><div class="small"><span class="badge ${x.correct ? "ok" : "bad"}">${x.correct ? "Correct" : "Missed"}</span> <strong>${i + 1}. ${esc(x.question)}</strong></div>
          <div class="small muted" style="margin-top:4px">${esc(x.explanation)}</div></div>`).join("")}</div>`;
      dash = null;
    });
  } catch (e) { m.root.innerHTML = `<p>${esc(e.message)}</p><button class="btn" data-close>Close</button>`; }
}

// ---- Calendar ---------------------------------------------------------------

let calMonth = new Date(); calMonth.setDate(1);

async function calendar() {
  const start = new Date(calMonth); start.setDate(1 - start.getDay());
  const end = new Date(start); end.setDate(start.getDate() + 41);
  const iso = (d) => d.toISOString().slice(0, 10);
  loading(view);
  const events = await api.get(`/api/me/calendar?start=${iso(start)}&end=${iso(end)}`);
  const byDay = {};
  events.forEach((e) => (byDay[e.date] ||= []).push(e));
  const todayIso = iso(new Date());
  let cells = "";
  for (let i = 0; i < 42; i++) {
    const d = new Date(start); d.setDate(start.getDate() + i);
    const key = iso(d);
    cells += `<div class="day ${d.getMonth() !== calMonth.getMonth() ? "other" : ""} ${key === todayIso ? "today" : ""}">
      <div class="d">${d.getDate()}</div>
      ${(byDay[key] || []).map((e) => `<button class="ev ${e.type} ${e.overdue ? "overdue" : ""}" data-ev='${esc(JSON.stringify(e))}' title="${esc(e.title)}"
        aria-label="${esc(`${{ due: e.overdue ? "Overdue" : "Due", registered: "Registered class", available: "Open class" }[e.type]}: ${e.title}, ${fmtDate(e.date)}${e.starts_at ? " at " + fmtTime(e.starts_at) : ""}`)}">
        ${e.starts_at ? fmtTime(e.starts_at) + " " : ""}${esc(e.type === "due" ? e.title : e.title)}</button>`).join("")}
    </div>`;
  }
  const upcoming = events.filter((e) => e.type === "registered" && e.date >= todayIso);
  view.innerHTML = `
    <div class="card-head"><h1>Calendar</h1>
      <div style="display:flex;gap:6px;align-items:center">
        <button class="btn secondary small" id="prev" aria-label="Previous month">‹</button>
        <strong style="min-width:140px;text-align:center">${calMonth.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</strong>
        <button class="btn secondary small" id="next" aria-label="Next month">›</button>
        <button class="btn ghost small" id="today">Today</button>
      </div></div>
    <div class="chips" style="margin-bottom:10px">
      <span class="badge">■ Registered class</span><span class="badge plain">■ Open class you can join</span>
      <span class="badge warn">■ Due date</span><span class="badge bad">■ Overdue</span>
    </div>
    <div class="grid side">
      <div class="card" style="padding:0;overflow:hidden"><div class="cal">${"Sun Mon Tue Wed Thu Fri Sat".split(" ").map((x) => `<div class="dow">${x}</div>`).join("")}${cells}</div></div>
      <section class="card"><h3>Your upcoming in-person classes</h3>
        ${upcoming.length ? `<div class="list">${upcoming.map((e) => `<div class="small"><strong>${esc(e.title)}</strong><br>
          ${fmtDate(e.starts_at, { weekday: "short", month: "short", day: "numeric" })}, ${fmtTime(e.starts_at)}–${fmtTime(e.ends_at)}<br>
          <span class="muted">${esc(e.location)} · ${esc(e.instructor)}</span></div>`).join("")}</div>`
          : `<p class="muted small">None yet. Click a light blue class on the calendar to register.</p>`}
      </section>
    </div>`;
  $("#prev").onclick = () => { calMonth.setMonth(calMonth.getMonth() - 1); calendar(); };
  $("#next").onclick = () => { calMonth.setMonth(calMonth.getMonth() + 1); calendar(); };
  $("#today").onclick = () => { calMonth = new Date(); calMonth.setDate(1); calendar(); };
  $$(".ev").forEach((b) => b.addEventListener("click", () => eventDetail(JSON.parse(b.dataset.ev))));
}

function eventDetail(e) {
  const m = modal(`
    <div class="modal-head"><h2>${esc(e.title)}</h2><button class="btn ghost" data-close>Close</button></div>
    ${e.starts_at ? `<p><strong>${fmtDate(e.starts_at, { weekday: "long", month: "long", day: "numeric" })}</strong>, ${fmtTime(e.starts_at)}–${fmtTime(e.ends_at)}</p>
      <p>${esc(e.location)} · Instructor ${esc(e.instructor)}</p>` : `<p>${esc(dueText(e.date))}</p>`}
    <div style="display:flex;gap:8px">
      ${e.type === "available" ? `<button class="btn" id="reg">Register for this class</button>` : ""}
      <button class="btn secondary" data-learn="${esc(e.training_code)}">Prepare in learning studio</button>
    </div>`);
  wirePathButtons(m.root);
  $$("[data-learn]", m.root).forEach((b) => b.addEventListener("click", m.close));
  $("#reg", m.root)?.addEventListener("click", async () => {
    try { await api.post(`/api/me/assignments/${e.assignment_id}/register`, { session_id: e.id }); toast("Registered"); m.close(); calendar(); }
    catch (err) { toast(err.message, true); }
  });
}

// ---- Learning studio --------------------------------------------------------

async function studioView() {
  return reviewStudio(view, go, assignedStudioView, me);
}

async function assignedStudioView() {
  if (!dash) await refresh();
  const assigned = dash.assignments.map((a) => a.training);
  if (!studio.code) studio.code = dash.path[0]?.training_code || assigned[0]?.code;
  if (!studio.code) { view.innerHTML = `<div class="empty card">No trainings assigned yet. Browse <a href="#catalog">all trainings</a>.</div>`; return; }
  const t = await api.get(`/api/trainings/${encodeURIComponent(studio.code)}`);
  const options = [...new Map([...assigned, t].map((x) => [x.code, x])).values()];
  const course = t.from_document ? await api.get(`/api/me/trainings/${encodeURIComponent(t.code)}/modules`) : null;
  if (course && !course.modules.some((m) => m.id === studio.module)) studio.module = (course.modules.find((m) => !m.done) || course.modules[0])?.id ?? null;
  if (!course) studio.module = null;
  const myAssignment = dash.assignments.find((a) => a.training.code === t.code);
  view.innerHTML = `
    <div class="card-head"><h1>Learning studio</h1></div>
    <div class="grid side">
      <div class="grid" style="align-content:start">
        <section class="card">
          <div class="toolbar">
            <label class="field" style="flex:1">Training
              <select id="s-training">${options.map((o) => `<option value="${esc(o.code)}" ${o.code === t.code ? "selected" : ""}>${esc(o.code)} · ${esc(o.title)}</option>`).join("")}</select></label>
            <label class="field">Delivery
              <select id="s-modality"><option value="text">Text</option><option value="mindmap">Mind map</option><option value="audio">Audio</option></select></label>
            <label class="field">Level
              <select id="s-level"><option value="">Adapt to me</option>${Object.entries(LEVEL_LABEL).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
          </div>
          <div class="toolbar">
            <label class="field" style="flex:1">Customize this lesson (optional)
              <input id="s-request" placeholder="e.g. use an analogy, focus on the glovebox part, keep it to 5 minutes"></label>
            <button class="btn" id="s-gen">Generate lesson</button>
            <button class="btn secondary" id="s-practice">Practice questions</button>
          </div>
          <p class="small muted">${esc(t.description)} ${t.from_document ? `<a href="#" id="s-src">Open the original document</a>`
            : `<a href="${esc(t.source_url)}" target="_blank" rel="noopener">Open in ${esc(t.source_system)}</a>`}</p>
          ${myAssignment ? `<div style="display:flex;gap:6px;align-items:center"><span class="small muted">When you're ready:</span>${assessButtons(myAssignment, myAssignment.status === "completed")}</div>` : ""}
        </section>
        ${course ? `<section class="card"><div class="card-head"><h3>Course modules</h3><span class="small muted">${course.modules.filter((m) => m.done).length} of ${course.modules.length} done ·
          built from ${esc(t.title)} so you don't have to read all of it</span></div>
          <div class="list module-list" style="max-height:260px;overflow-y:auto">${course.modules.map((m, n) => `
            <button class="item small ${m.id === studio.module ? "active" : ""}" data-module="${m.id}" style="text-align:left;cursor:pointer;font:inherit">
              <span class="badge ${m.done ? "ok" : "plain"}">${m.done ? "✔" : n + 1}</span>
              <div class="grow"><strong>${esc(m.title)}</strong><div class="muted">pages ${esc(m.pages)}${m.summary ? ` · ${esc(m.summary.slice(0, 110))}` : ""}</div></div></button>`).join("")}</div></section>` : ""}
        <section id="lesson"></section>
      </div>
      <section class="card chat">
        <h3>Ask the tutor</h3>
        <p class="small muted">Questions about ${esc(t.title)}, or ask it to explain something a different way.</p>
        <div class="msgs" id="msgs"></div>
        <form id="chat-form"><input id="chat-input" placeholder="Ask a question…" autocomplete="off"><button class="btn">Send</button></form>
      </section>
    </div>`;
  $("#s-training").onchange = (e) => { studio.code = e.target.value; studio.lesson = null; studio.chat = []; assignedStudioView(); };
  $("#s-gen").onclick = () => genLesson(t);
  $$("[data-module]").forEach((b) => b.addEventListener("click", () => { studio.module = Number(b.dataset.module); studio.lesson = null; assignedStudioView(); }));
  wireAssignmentButtons(view);
  $("#s-src")?.addEventListener("click", async (e) => { e.preventDefault(); try { window.open(await api.blobUrl(t.source_url), "_blank"); } catch (err) { toast(err.message, true); } });
  if (course && !studio.lesson) $("#s-gen").textContent = "Start this module";
  $("#s-practice").onclick = () => practice(t);
  $("#chat-form").onsubmit = (e) => { e.preventDefault(); sendChat(t); };
  renderChat();
  if (studio.lesson && studio.lesson.training_code === t.code) renderLesson(t, studio.lesson);
  else $("#lesson").innerHTML = `<div class="card empty">Generate a lesson to start. It begins at your level and adapts as you answer.</div>`;
}

async function genLesson(t) {
  const box = $("#lesson");
  loading(box, "Writing a lesson for you…");
  $("#s-gen").disabled = true;
  try {
    const delivery = $("#s-modality").value;
    const body = { request: $("#s-request").value, modality: "text", difficulty: $("#s-level").value || null };
    if (studio.module) studio.lesson = await api.post(`/api/me/modules/${studio.module}/lesson`, body);
    else if (body.modality === "video") studio.lesson = await api.post(`/api/me/trainings/${encodeURIComponent(t.code)}/video`, body);
    else studio.lesson = await api.post(`/api/me/trainings/${encodeURIComponent(t.code)}/lesson`, body);
    studio.lesson.training_code = t.code;
    studio.lesson.delivery = delivery;
    renderLesson(t, studio.lesson);
    dash = null;
  } catch (e) { box.innerHTML = `<div class="card">${esc(e.message)}</div>`; }
  finally { $("#s-gen").disabled = false; }
}

async function finishLesson(t, l) {
  if (l.module_id) {
    const r = await api.post(`/api/me/modules/${l.module_id}/complete`);
    toast(`Module done · ${r.done} of ${r.total} · course ${r.progress ?? 0}% complete`);
    dash = null; studio.lesson = null; studio.module = null; assignedStudioView();
    return;
  }
  const a = (dash || (await refresh())).assignments.find((x) => x.training.code === t.code);
  if (a) { await api.post(`/api/me/assignments/${a.id}/progress`, { progress: Math.min(90, a.progress + 30) }); toast("Progress saved"); dash = null; }
  else toast("Lesson complete");
}

function renderLesson(t, l) {
  const box = $("#lesson");
  if (l.kind === "video") {
    box.innerHTML = `<div class="card"><div class="card-head"><h2>${esc(l.module_title || l.title)}</h2>
      <div class="chips"><span class="badge">Video</span><span class="badge">${LEVEL_LABEL[l.difficulty] || l.difficulty}</span>
      ${l.pages ? `<span class="badge plain">pages ${esc(l.pages)}</span>` : ""}<span class="badge plain">${l.generated_by === "offline" ? "Offline content" : "AI generated"}</span></div></div>
      <div id="vp"></div></div>`;
    videoPlayer($("#vp", box), l, {
      onAnswer: (ok, q) => recordAnswer(t, l.skill || t.skills?.[0] || t.category, ok, "video", q),
      onDone: () => finishLesson(t, l),
    });
    return;
  }
  if (["mindmap", "audio"].includes(l.delivery)) {
    const points = l.sections.map(s => ({ point: s.heading || s.kind || "Key concept", explanation: [s.body, s.text, s.content, s.scenario, s.explanation].filter(v => typeof v === "string").join(" ") }));
    const transcript = [l.title, l.overview, ...points.map(p => `${p.point}. ${p.explanation}`), ...l.key_points].join("\n\n");
    box.innerHTML = `<div class="card"><h2>${esc(l.title)}</h2>${l.delivery === "mindmap" ? mindMap({ title: l.title, objective: l.overview, key_points: points }) : `<button class="btn" id="lesson-audio">Play audio</button> <button class="btn secondary" id="lesson-stop">Stop audio</button><details><summary>Audio transcript</summary><p style="white-space:pre-line">${esc(transcript)}</p></details>`}<button class="btn" id="finish">I finished this lesson</button></div>`;
    $("#lesson-audio", box)?.addEventListener("click", event => speak(transcript, event.currentTarget));
    $("#lesson-stop", box)?.addEventListener("click", stopSpeaking);
    $("#finish", box).onclick = () => { stopSpeaking(); finishLesson(t, l); };
    const observer = new MutationObserver(() => { if (!box.isConnected || !$("#finish", box)) { stopSpeaking(); observer.disconnect(); } });
    observer.observe(view, { childList: true, subtree: true });
    return;
  }
  box.innerHTML = `
    <div class="card">
      <div class="card-head"><h2>${esc(l.title)}</h2>
        <div class="chips"><span class="badge">${LEVEL_LABEL[l.difficulty] || l.difficulty}</span><span class="badge">${MODALITY_LABEL[l.modality]}</span>
        <span class="badge plain">${l.generated_by === "offline" ? "Offline content" : "AI generated"}</span></div></div>
      <p class="muted">${esc(l.overview)}</p>
      <p class="small muted">${esc(l.pacing?.reason || "")}</p>
      <div class="list" id="sections">${l.sections.map((s, i) => sectionHtml(s, i)).join("")}</div>
      <div class="card flat" style="margin-top:12px;background:var(--navy-tint)"><h3>Key points</h3><ul>${l.key_points.map((k) => `<li>${esc(k)}</li>`).join("")}</ul>
        <button class="btn small" id="finish">I finished this lesson</button></div>
    </div>`;
  $$("[data-choice]", box).forEach((btn) => btn.addEventListener("click", async () => {
    const s = l.sections[Number(btn.dataset.sec)];
    const c = s.choices[Number(btn.dataset.choice)];
    const wrap = btn.parentElement;
    $$(".choice", wrap).forEach((x) => (x.disabled = true));
    btn.classList.add(c.correct ? "right" : "wrong");
    $(".feedback", wrap).innerHTML = `${c.correct ? "✔" : "✘"} ${esc(c.feedback)}`;
    await recordAnswer(t, s.skill, c.correct, "simulation", s.scenario);
  }));
  $$("[data-exercise]", box).forEach((btn) => btn.addEventListener("click", async () => {
    const s = l.sections[Number(btn.dataset.exercise)];
    const boxes = $$(`input[data-ex="${btn.dataset.exercise}"]`, box);
    const done = boxes.filter((b) => b.checked).length;
    await recordAnswer(t, s.skill, done === boxes.length, "exercise", s.heading);
    btn.textContent = done === boxes.length ? "Done ✔" : `Saved (${done}/${boxes.length})`;
  }));
  $$("[data-understood]", box).forEach((btn) => btn.addEventListener("click", async () => {
    const s = l.sections[Number(btn.dataset.understood)];
    const ok = btn.dataset.val === "1";
    await recordAnswer(t, s.skill, ok, s.kind === "visual" ? "visual" : "text", s.heading);
    btn.parentElement.innerHTML = `<span class="small muted">${ok ? "Great, noted." : "Got it. Next lessons will slow down here."}</span>`;
  }));
  $("#finish").onclick = () => finishLesson(t, l);
}

function sectionHtml(s, i) {
  const understood = `<div style="margin-top:8px" class="small">Did this make sense?
    <button class="btn ghost small" data-understood="${i}" data-val="1">Yes</button>
    <button class="btn ghost small" data-understood="${i}" data-val="0">Not really</button></div>`;
  let inner = `<p>${esc(s.body)}</p>`;
  if (s.kind === "visual" && s.diagram_steps.length) {
    inner += `<div class="flow">${s.diagram_steps.map((x, k) => `${k ? `<span class="arrow">→</span>` : ""}<span class="step">${esc(x)}</span>`).join("")}</div>${understood}`;
  } else if (s.kind === "simulation") {
    inner += `<div class="card flat" style="background:var(--navy-tint)"><strong>Scenario:</strong> ${esc(s.scenario)}</div>
      <div>${s.choices.map((c, k) => `<button class="choice" data-sec="${i}" data-choice="${k}">${esc(c.text)}</button>`).join("")}<div class="feedback"></div></div>`;
  } else if (s.kind === "exercise") {
    inner += `<div class="checklist">${s.exercise_steps.map((x) => `<label><input type="checkbox" data-ex="${i}"> ${esc(x)}</label>`).join("")}</div>
      <button class="btn secondary small" data-exercise="${i}">Mark exercise done</button>`;
  } else {
    inner += understood;
  }
  return `<div class="lesson-section" data-speak-scope><div class="kind">${esc(MODALITY_LABEL[s.kind] || s.kind)} · ${esc(s.skill)}</div>
    <h3>${esc(s.heading)} ${speakButton("Read this section")}</h3>${inner}</div>`;
}

async function recordAnswer(t, skill, correct, modality, question = "") {
  try {
    const r = await api.post("/api/me/answer", { training_code: t.code, skill: skill || t.skills[0] || t.category, correct, modality, question });
    toast(`${r.skill}: mastery ${Math.round(r.mastery * 100)}% · now ${LEVEL_LABEL[r.difficulty]} · ${r.pacing.pace} pace`);
    dash = null;
    return r;
  } catch (e) { toast(e.message, true); }
}

async function practice(t) {
  const box = $("#lesson");
  loading(box, "Writing practice questions…");
  const r = await api.post(`/api/me/trainings/${encodeURIComponent(t.code)}/practice`, { count: 5 });
  box.innerHTML = `<div class="card">
    <div class="card-head"><h2>Practice: ${esc(t.title)}</h2><span class="badge plain">Focus: ${r.focus_skills.map(esc).join(", ") || "all"}</span></div>
    <div class="list">${r.questions.map((q, i) => `
      <div class="lesson-section" data-q="${i}" data-speak-scope role="group" aria-label="Question ${i + 1}"><div class="kind">Question ${i + 1} · ${esc(q.skill)}</div>
        <strong>${esc(q.question)}</strong> ${speakButton("Read question")}
        <div>${q.options.map((o, k) => `<button class="choice" data-opt="${k}">${esc(o)}</button>`).join("")}</div><div class="feedback"></div></div>`).join("")}
    </div>
    <div style="margin-top:12px;display:flex;gap:8px"><button class="btn secondary" id="more">More questions</button><span id="tally" class="muted small"></span></div></div>`;
  let right = 0, answered = 0;
  $$("[data-q]", box).forEach((qel) => {
    const q = r.questions[Number(qel.dataset.q)];
    $$(".choice", qel).forEach((btn) => btn.addEventListener("click", async () => {
      const k = Number(btn.dataset.opt);
      const ok = k === q.answer_index;
      $$(".choice", qel).forEach((x, j) => { x.disabled = true; if (j === q.answer_index) x.classList.add("right"); });
      if (!ok) btn.classList.add("wrong");
      $(".feedback", qel).textContent = q.explanation;
      answered++; if (ok) right++;
      $("#tally").textContent = `${right}/${answered} correct`;
      await recordAnswer(t, q.skill, ok, "quiz", q.question);
    }));
  });
  $("#more").onclick = () => practice(t);
}

function renderChat() {
  const box = $("#msgs");
  if (!box) return;
  box.innerHTML = studio.chat.length ? studio.chat.map((m) => `<div class="msg ${m.role}" ${m.role === "assistant" ? "data-speak-scope" : ""}>${esc(m.content)}${m.role === "assistant" ? `<div>${speakButton("Read reply")}</div>` : ""}</div>`).join("")
    : `<p class="muted small">Try: "Explain this like I'm new to the lab" or "Give me a real example from a facility."</p>`;
  box.scrollTop = box.scrollHeight;
}

async function sendChat(t) {
  const input = $("#chat-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  const history = studio.chat.slice();
  studio.chat.push({ role: "user", content: text });
  renderChat();
  $("#msgs").insertAdjacentHTML("beforeend", `<div class="msg assistant" id="typing"><span class="spinner"></span></div>`);
  try {
    const r = await api.post("/api/me/tutor", { message: text, training_code: t.code, history });
    studio.chat.push({ role: "assistant", content: r.reply });
  } catch (e) { studio.chat.push({ role: "assistant", content: `Sorry, that failed: ${e.message}` }); }
  renderChat();
}

// ---- Catalog ----------------------------------------------------------------

const catFilter = { q: "", category: "", delivery: "", source: "", required: "" };

async function catalog() {
  const sources = await api.get("/api/trainings/sources");
  view.innerHTML = `
    <div class="card-head"><h1>All trainings</h1><span class="muted small">One catalog for every LANL training site</span></div>
    <div class="chips" style="margin-bottom:12px">
      <button class="chip ${catFilter.source === "" ? "active" : ""}" data-src="">All sites</button>
      ${sources.map((s) => `<button class="chip ${catFilter.source === s.source_system ? "active" : ""}" data-src="${esc(s.source_system)}">${esc(s.source_system)} (${s.count})</button>`).join("")}
    </div>
    <div class="toolbar">
      <label class="field" style="flex:1">Search<input id="c-q" value="${esc(catFilter.q)}" placeholder="Title, code or description"></label>
      <label class="field">Category<select id="c-cat"><option value="">Any</option>${Object.entries(CATEGORY_LABEL).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
      <label class="field">Delivery<select id="c-del"><option value="">Any</option>${Object.entries(DELIVERY_LABEL).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
      <label class="field">Required<select id="c-req"><option value="">Any</option><option value="true">Required</option><option value="false">Optional</option></select></label>
    </div>
    <div id="c-list"></div>`;
  $("#c-cat").value = catFilter.category; $("#c-del").value = catFilter.delivery; $("#c-req").value = catFilter.required;
  $$("[data-src]").forEach((c) => c.addEventListener("click", () => { catFilter.source = c.dataset.src; catalog(); }));
  let timer;
  $("#c-q").addEventListener("input", (e) => { catFilter.q = e.target.value; clearTimeout(timer); timer = setTimeout(loadCatalog, 250); });
  [["#c-cat", "category"], ["#c-del", "delivery"], ["#c-req", "required"]].forEach(([s, k]) => $(s).addEventListener("change", (e) => { catFilter[k] = e.target.value; loadCatalog(); }));
  loadCatalog();
}

async function loadCatalog() {
  const q = new URLSearchParams(Object.entries(catFilter).filter(([, v]) => v !== ""));
  const items = await api.get(`/api/trainings?${q}`);
  const mine = new Set((dash || (await refresh())).assignments.map((a) => a.training.code));
  $("#c-list").innerHTML = `<div class="table-wrap card" style="padding:0"><table>
    <thead><tr><th>Code</th><th>Title</th><th>Category</th><th>Delivery</th><th>Site</th><th>Length</th><th></th></tr></thead>
    <tbody>${items.map((t) => `<tr>
      <td class="num">${esc(t.code)}</td>
      <td><strong>${esc(t.title)}</strong> ${t.required ? `<span class="badge">Required</span>` : ""} ${mine.has(t.code) ? `<span class="badge ok">Assigned</span>` : ""}</td>
      <td>${CATEGORY_LABEL[t.category] || t.category}</td><td>${DELIVERY_LABEL[t.delivery]}</td>
      <td><a href="${esc(t.source_url)}" target="_blank" rel="noopener">${esc(t.source_system)}</a></td>
      <td class="num">${t.duration_minutes} min</td>
      <td><button class="btn small secondary" data-learn="${esc(t.code)}">Preview</button></td></tr>`).join("")}</tbody></table></div>
    ${items.length ? "" : `<div class="empty">No trainings match.</div>`}`;
  wirePathButtons($("#c-list"));
}

// ---- Profile ----------------------------------------------------------------

const demoProfiles = new Map();
function demoLearningProfile(user) {
  const storageKey = `lanl_profile_demo_${user.id}`;
  if (demoProfiles.has(user.id)) return demoProfiles.get(user.id);
  try {
    const stored = JSON.parse(sessionStorage.getItem(storageKey) || "null");
    if (stored?.skills?.length && stored.skills.every(skill=>Number.isFinite(skill.score)&&Number.isFinite(skill.completed))) {
      demoProfiles.set(user.id,stored);return stored;
    }
  } catch { /* The preview also works without browser storage. */ }
  const roster = [
    ["Cybersecurity", "Technical"], ["Data analysis", "Technical"], ["Python programming", "Technical"],
    ["Radiation awareness", "Safety"], ["Chemical safety", "Safety"], ["Laboratory practices", "Safety"],
    ["Project planning", "Professional"], ["Communication", "Professional"], ["Problem solving", "Professional"], ["Risk assessment", "Safety"],
  ];
  const sample = { skills: roster.map(([name,category])=>({name,category,score:45+Math.floor(Math.random()*50),completed:1+Math.floor(Math.random()*6)})), streak:3+Math.floor(Math.random()*12) };
  sample.completed=sample.skills.reduce((sum,skill)=>sum+skill.completed,0);
  sample.points=sample.completed*50+sample.streak*10;
  demoProfiles.set(user.id,sample);
  try { sessionStorage.setItem(storageKey,JSON.stringify(sample)); } catch { /* In-memory preview remains available. */ }
  return sample;
}

async function profile() {
  loading(view);
  await refresh();
  const state=readProgress(me),sample=demoLearningProfile(me);
  const colors=["#153c87","#2874ae","#329c99","#75af96","#94a7c9","#6e659c","#b0bccc","#357f86","#9b7ba7","#5e7c58"];
  const total=sample.skills.reduce((sum,skill)=>sum+skill.score,0);
  let angle=0;
  const slices=sample.skills.map((skill,i)=>{const start=angle;angle+=skill.score/total*360;return `${colors[i%colors.length]} ${start}deg ${angle}deg`;});
  view.innerHTML=`<div class="card-head"><h1>My learning profile</h1><span class="badge plain">Demo profile</span></div>
    <p class="muted">Explore your skills and learning achievements. The skills preview uses sample data; your recorded course activity is in its own tab.</p>
    <div role="tablist" aria-label="Learning profile" class="toolbar" style="margin:20px 0"><button class="btn" role="tab" id="profile-skills-tab" aria-selected="true" aria-controls="profile-skills" data-profile-tab="skills">Skills &amp; achievements</button><button class="btn secondary" role="tab" id="profile-activity-tab" aria-selected="false" tabindex="-1" aria-controls="profile-activity" data-profile-tab="activity">My course activity</button></div>
    <section role="tabpanel" id="profile-skills" aria-labelledby="profile-skills-tab">
      <p class="small muted">Randomized demo values, kept consistent during this browser session.</p>
      <div class="grid cols-4" style="margin:16px 0 24px"><div class="stat"><div class="label">Courses completed</div><div class="value">${sample.completed}</div><p class="small muted">Across ${sample.skills.length} skill areas</p></div><div class="stat"><div class="label">Daily streak</div><div class="value"><span aria-hidden="true">&#128293;</span> ${sample.streak}</div><p class="small muted">Consecutive learning days</p></div><div class="stat"><div class="label">Learning points</div><div class="value">${sample.points}</div><p class="small muted">Demo achievement points</p></div><div class="stat"><div class="label">Skills explored</div><div class="value">${sample.skills.length}</div><p class="small muted">Technical, safety and professional</p></div></div>
      <div class="grid cols-2"><section class="card"><h2>My skills</h2><p class="small muted">Slice sizes show the relative share of the sample skill scores.</p><div role="img" aria-label="Demo skill distribution: ${esc(sample.skills.map(skill=>`${skill.name}: ${skill.score} percent skill score`).join(', '))}" style="width:min(250px,100%);aspect-ratio:1;margin:24px auto;border-radius:50%;background:conic-gradient(${slices.join(',')});border:7px solid #f2f5fa;box-shadow:0 6px 24px #112b6210"></div><div class="list">${sample.skills.map((skill,i)=>`<div class="small" style="display:flex;align-items:center;gap:10px"><span aria-hidden="true" style="width:11px;height:11px;border-radius:3px;background:${colors[i]}"></span><span style="flex:1">${esc(skill.name)}</span><strong>${skill.score}%</strong></div>`).join('')}</div></section>
      <section class="card"><h2>Skills breakdown</h2><p class="small muted">Sample proficiency and completed courses for each skill.</p><div class="chips" style="margin:16px 0" aria-label="Filter skills">${["All","Technical","Safety","Professional"].map(category=>`<button class="chip ${category==="All"?"active":""}" data-skill-category="${category}" aria-pressed="${category==="All"}">${category}</button>`).join('')}</div><div id="profile-skill-list" class="list"></div></section></div>
    </section>
    <section role="tabpanel" id="profile-activity" aria-labelledby="profile-activity-tab" hidden><div class="grid cols-2"><section class="card">${progressPanel(state)}</section><section class="card">${inProgressPanel(state)}</section></div><a class="btn secondary" href="#studio" style="margin-top:16px">Continue in Learning Studio</a></section>`;
  function renderSkills(category="All") {
    $("#profile-skill-list",view).innerHTML=sample.skills.filter(skill=>category==="All"||skill.category===category).map(skill=>`<article style="padding:14px 0;border-bottom:1px solid var(--border)"><div class="card-head"><strong>${esc(skill.name)}</strong><span class="badge plain">${skill.category}</span></div>${bar(skill.score,skill.score>=75?"ok":"")}<div class="small muted" style="display:flex;justify-content:space-between;margin-top:8px"><span>${skill.score}% proficiency</span><strong>${skill.completed} course${skill.completed===1?"":"s"} completed</strong></div></article>`).join('');
    $$("[data-skill-category]",view).forEach(button=>{button.classList.toggle("active",button.dataset.skillCategory===category);button.setAttribute("aria-pressed",String(button.dataset.skillCategory===category));});
  }
  renderSkills();
  $$("[data-skill-category]",view).forEach(button=>button.onclick=()=>renderSkills(button.dataset.skillCategory));
  const tabs=$$("[data-profile-tab]",view);
  function activateTab(tab){tabs.forEach(button=>{const active=button===tab;button.setAttribute("aria-selected",String(active));button.tabIndex=active?0:-1;button.classList.toggle("secondary",!active);$("#profile-"+button.dataset.profileTab,view).hidden=!active;});}
  tabs.forEach((tab,index)=>{
    tab.onclick=()=>activateTab(tab);
    tab.onkeydown=event=>{
      let next;if(event.key==="ArrowRight")next=(index+1)%tabs.length;else if(event.key==="ArrowLeft")next=(index+tabs.length-1)%tabs.length;else if(event.key==="Home")next=0;else if(event.key==="End")next=tabs.length-1;else return;
      event.preventDefault();activateTab(tabs[next]);tabs[next].focus();
    };
  });
}

const go = router({ overview, trainings, calendar, studio: studioView, "assigned-studio": assignedStudioView, catalog, profile,
  // AJ's source-grounded diagnostic: reviewed questions from the Resource_File documents.
  // queueMicrotask: these need `go`, which isn't assigned yet if the page opens directly on #diagnostic.
  diagnostic: () => queueMicrotask(() => diagnosticView(view, me, go)),
  "diagnostic-results": () => queueMicrotask(() => diagnosticResults(view, me, go)),
}, "overview");
