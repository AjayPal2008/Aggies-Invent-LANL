import {
  api, requireRole, topbar, router, esc, $, $$, fmtDate, dueText, statusBadge, bar, toast, modal, loading,
  CATEGORY_LABEL, DELIVERY_LABEL,
} from "/shared/api.js?v=20261024e";
import { rolesView, interviewsView } from "./roles.js";

// Hires are sent back to /hire/ here, and the API refuses them too.
const me = await requireRole(["manager", "admin"]);
topbar(me, "Manager Dashboard");
if (me.role === "admin") $$(".admin-only").forEach((el) => el.classList.remove("hidden"));
const view = $("#view");
const pct = (v) => (v == null ? "—" : `${Math.round(v)}%`);

// ---- Overview ---------------------------------------------------------------

async function overview() {
  loading(view);
  const [o, retrain, team] = await Promise.all([
    api.get("/api/manager/overview"), api.get("/api/manager/retraining?days=60"), api.get("/api/manager/team?new_hires_only=true&sort=overdue"),
  ]);
  const st = o.status, total = (st.not_started || 0) + (st.in_progress || 0) + (st.completed || 0) || 1;
  const fy = Object.entries(o.headcount_by_fiscal_year);
  const fyMax = Math.max(1, ...fy.map(([, n]) => n));
  view.innerHTML = `
    <div class="hero"><h1>${esc(me.name.split(" ")[0])}'s team</h1>
      <p>${o.team_size} people · ${o.new_hires} new hires this year · FY${o.current_fiscal_year}</p></div>
    <div class="grid cols-4" style="margin-bottom:16px">
      ${stat("Team size", o.team_size, "", "team")}
      ${stat("New hires", o.new_hires, "", "team")}
      ${stat("Overdue trainings", o.flags.overdue || 0, "bad", "retraining")}
      ${stat("Needs retake / expiring", `${o.flags.needs_retake || 0} / ${o.flags.expiring || 0}`, "warn", "retraining")}
    </div>
    <div class="grid cols-2" style="margin-bottom:16px">
      <section class="card">
        <div class="card-head"><h3>Assigned training progress</h3><span class="muted small">avg completion ${pct(o.avg_completion)}</span></div>
        <div class="stack">
          <span style="width:${(st.completed || 0) / total * 100}%;background:var(--navy)"></span>
          <span style="width:${(st.in_progress || 0) / total * 100}%;background:var(--navy-light);opacity:.6"></span>
        </div>
        <div class="chips" style="margin-top:8px">
          <span class="badge">Completed ${st.completed || 0}</span><span class="badge plain">In progress ${st.in_progress || 0}</span>
          <span class="badge plain">Not started ${st.not_started || 0}</span><span class="badge warn">Due in 14 days ${o.flags.upcoming || 0}</span>
        </div>
      </section>
      <section class="card">
        <div class="card-head"><h3>Headcount by fiscal year hired</h3><span class="muted small">${o.open_positions} open roles</span></div>
        <div style="display:flex;align-items:flex-end;gap:10px;height:120px">
          ${fy.map(([y, n]) => `<div style="flex:1;text-align:center"><div class="small num">${n}</div>
            <div style="height:${(n / fyMax) * 90}px;background:var(--navy);border-radius:4px 4px 0 0"></div><div class="small muted">FY${String(y).slice(2)}</div></div>`).join("")}
        </div>
      </section>
    </div>
    <div class="grid cols-2">
      <section class="card">
        <div class="card-head"><h3>New hires</h3><button class="btn ghost small" data-goto="team">See all</button></div>
        <div class="list">${team.slice(0, 6).map((p) => `
          <div class="item clickable" data-person="${p.id}" style="cursor:pointer"><div class="grow"><div class="title">${esc(p.name)}</div>
            <div class="small muted">${esc(p.job_title)} · hired ${fmtDate(p.hire_date)}</div>${bar(p.summary.completion_rate)}</div>
            <div class="small" style="text-align:right">${p.summary.overdue ? `<span class="badge bad">${p.summary.overdue} overdue</span><br>` : ""}${p.summary.completed}/${p.summary.total} done</div></div>`).join("") || `<p class="muted">No new hires.</p>`}</div>
      </section>
      <section class="card">
        <div class="card-head"><h3>Retraining coming up</h3><button class="btn ghost small" data-goto="retraining">See all</button></div>
        ${retrainTable(retrain.slice(0, 8))}
      </section>
    </div>`;
  $$("[data-goto]").forEach((b) => b.addEventListener("click", () => go(b.dataset.goto)));
  $$("[data-person]").forEach((b) => b.addEventListener("click", () => hireView(Number(b.dataset.person))));
}

function stat(label, value, cls, target) {
  return `<div class="stat ${cls} clickable" data-goto="${target}"><div class="label">${label}</div><div class="value num">${value}</div></div>`;
}

// ---- Team -------------------------------------------------------------------
// Built for large groups: sub-team cards, search, paging, and bulk actions on any selection.

const teamFilter = { q: "", under: "", direct_only: "", new_hires_only: "", min_level: "", max_level: "", fiscal_year_hired: "", sort: "performance" };
const selected = new Set();
const PAGE = 50;
let teamRows = [], teamIds = [], teamPage = 0;

async function team() {
  const f = teamFilter;
  view.innerHTML = `
    <div class="card-head"><h1>Team &amp; new hires</h1>
      <div style="display:flex;gap:8px"><button class="btn secondary small" id="export">Export CSV</button></div></div>
    <div id="org" class="grid cols-4" style="margin-bottom:12px"></div>
    <div class="toolbar">
      <label class="field" style="flex:1;min-width:200px">Search<input id="t-q" value="${esc(f.q)}" placeholder="Name, email, title or Z number"></label>
      <label class="field">Sub-team<select id="t-under"><option value="">Whole org</option></select></label>
      <label class="field">Reports<select id="t-direct"><option value="">Direct and indirect</option><option value="true">Direct reports only</option></select></label>
      <label class="field">Who<select id="t-new"><option value="">Everyone</option><option value="true">New hires only</option></select></label>
      <label class="field">Min level<select id="t-min"><option value="">Any</option>${[1, 2, 3, 4, 5].map((l) => `<option>${l}</option>`).join("")}</select></label>
      <label class="field">Max level<select id="t-max"><option value="">Any</option>${[1, 2, 3, 4, 5].map((l) => `<option>${l}</option>`).join("")}</select></label>
      <label class="field">Hired in<select id="t-fy"><option value="">Any fiscal year</option>${[0, 1, 2, 3, 4, 5].map((k) => { const y = new Date().getFullYear() + 1 - k; return `<option value="${y}">FY${y}</option>`; }).join("")}</select></label>
      <label class="field">Rank by<select id="t-sort"><option value="performance">Performance</option><option value="completion">Training completion</option><option value="overdue">Most overdue</option><option value="level">Level</option><option value="hire_date">Hire date</option><option value="name">Name</option></select></label>
    </div>
    <div id="bulk" class="card hidden" style="position:sticky;top:64px;z-index:10;margin-bottom:12px;background:var(--navy);color:#fff;display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:10px 14px">
      <strong id="bulk-count"></strong><span class="spacer" style="flex:1"></span>
      <button class="btn secondary small" data-bulk="assign">Assign training</button>
      <button class="btn secondary small" data-bulk="role">Assign role requirements</button>
      <button class="btn secondary small" data-bulk="due">Change due dates</button>
      <button class="btn secondary small" data-bulk="remove">Remove training</button>
      <button class="btn secondary small" data-bulk="remind">Email reminders</button>
      <button class="btn ghost small" style="color:#fff" data-bulk="clear">Clear</button>
    </div>
    <div id="t-table"></div>`;
  loadOrg();
  const bind = [["#t-under", "under"], ["#t-direct", "direct_only"], ["#t-new", "new_hires_only"], ["#t-min", "min_level"], ["#t-max", "max_level"], ["#t-fy", "fiscal_year_hired"], ["#t-sort", "sort"]];
  bind.forEach(([sel, k]) => { $(sel).value = f[k]; $(sel).addEventListener("change", (e) => { f[k] = e.target.value; teamPage = 0; loadTeam(); }); });
  let timer;
  $("#t-q").addEventListener("input", (e) => { f.q = e.target.value; clearTimeout(timer); timer = setTimeout(() => { teamPage = 0; loadTeam(); }, 250); });
  $("#export").onclick = () => api.download("/api/manager/team.csv", `team-${new Date().toISOString().slice(0, 10)}.csv`);
  $$("[data-bulk]").forEach((b) => b.addEventListener("click", () => bulkAction(b.dataset.bulk)));
  loadTeam();
}

async function loadOrg() {
  const o = await api.get("/api/manager/org");
  const box = $("#org");
  if (!box) return;
  const sel = $("#t-under");
  o.groups.forEach((g) => sel.insertAdjacentHTML("beforeend", `<option value="${g.lead.id}">${esc(g.lead.name)}'s team (${g.size})</option>`));
  sel.value = teamFilter.under;
  box.innerHTML = `
    <div class="stat clickable" data-under=""><div class="label">Whole org</div><div class="value num">${o.team_size}</div>
      <div class="small muted">${o.direct_reports} direct reports${o.groups.length ? ` · ${o.groups.length} sub-teams` : ""}</div></div>
    ${o.groups.map((g) => `<div class="stat clickable ${g.overdue ? "warn" : ""}" data-under="${g.lead.id}">
      <div class="label">${esc(g.lead.name)}'s team</div><div class="value num">${g.size}</div>
      <div class="small muted">${pct(g.avg_completion)} complete · ${g.overdue} overdue · ${g.new_hires} new</div></div>`).join("")}`;
  $$("[data-under]", box).forEach((c) => c.addEventListener("click", () => {
    teamFilter.under = c.dataset.under; $("#t-under").value = c.dataset.under; teamPage = 0; loadTeam();
  }));
}

async function loadTeam() {
  const box = $("#t-table");
  loading(box);
  const q = new URLSearchParams(Object.entries(teamFilter).filter(([, v]) => v !== ""));
  // The server pages and ranks; only 50 rows come down at a time, so orgs of thousands stay fast.
  const [rows, ids] = await Promise.all([api.get(`/api/manager/team?${q}&page=${teamPage}&page_size=${PAGE}`),
    api.get(`/api/manager/team?${q}&ids_only=true`)]);
  teamRows = rows;
  teamIds = ids.ids;
  renderTeam();
}

function renderTeam() {
  const box = $("#t-table");
  const rows = teamRows;
  const total = teamIds.length;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const shown = rows;
  const allSelected = total && teamIds.every((id) => selected.has(id));
  box.innerHTML = total ? `
    <div class="toolbar" style="justify-content:space-between;align-items:center">
      <span class="small muted">${total} ${total === 1 ? "person" : "people"} · showing ${teamPage * PAGE + 1}–${teamPage * PAGE + shown.length}</span>
      <div style="display:flex;gap:6px;align-items:center">
        <button class="btn ghost small" id="sel-all">${allSelected ? "Unselect" : "Select"} all ${total}</button>
        ${pages > 1 ? `<button class="btn secondary small" id="prev" ${teamPage === 0 ? "disabled" : ""}>‹</button>
          <span class="small">Page ${teamPage + 1} of ${pages}</span>
          <button class="btn secondary small" id="next" ${teamPage >= pages - 1 ? "disabled" : ""}>›</button>` : ""}
      </div></div>
    <div class="card table-wrap" style="padding:0;max-height:70vh;overflow-y:auto"><table>
    <thead style="position:sticky;top:0;background:#fff;z-index:1"><tr><th><input type="checkbox" id="all" aria-label="Select this page"></th><th>#</th><th>Name</th><th>Sub-team</th><th>Level</th><th>Hired</th><th>Trainings</th>
      <th>Completion</th><th>Avg score</th><th>HR rating</th><th>Perf. index</th><th>Gaps</th></tr></thead>
    <tbody>${shown.map((r) => `<tr class="clickable" data-id="${r.id}">
      <td><input type="checkbox" data-sel="${r.id}" ${selected.has(r.id) ? "checked" : ""} aria-label="Select ${esc(r.name)}"></td>
      <td class="num">${r.rank}</td>
      <td><strong>${esc(r.name)}</strong> ${r.is_new_hire ? `<span class="badge">New</span>` : ""} ${r.role === "manager" ? `<span class="badge plain">Lead</span>` : ""}<div class="small muted">${esc(r.job_title)} · ${esc(r.division_code)}</div></td>
      <td class="small">${r.sub_team ? esc(r.sub_team.name) : `<span class="muted">Direct</span>`}</td>
      <td class="num">${r.level}</td><td class="small">${fmtDate(r.hire_date)}</td>
      <td class="small">${r.summary.completed}/${r.summary.total} done${r.summary.in_progress ? ` · ${r.summary.in_progress} active` : ""}
        ${r.summary.overdue ? `<br><span class="badge bad">${r.summary.overdue} overdue</span>` : ""}${r.summary.needs_retake ? ` <span class="badge warn">${r.summary.needs_retake} retake</span>` : ""}</td>
      <td style="min-width:110px">${bar(r.summary.completion_rate)}<span class="small num">${pct(r.summary.completion_rate)}</span></td>
      <td class="num">${r.avg_score ?? "—"}</td><td class="num">${r.performance_rating ?? "—"}</td>
      <td class="num"><strong>${r.performance_index}</strong></td><td class="num">${r.gap_count}</td></tr>`).join("")}</tbody></table></div>`
    : `<div class="card empty">Nobody matches these filters.</div>`;
  $$("[data-sel]", box).forEach((c) => {
    c.addEventListener("click", (e) => e.stopPropagation());
    c.addEventListener("change", () => { c.checked ? selected.add(Number(c.dataset.sel)) : selected.delete(Number(c.dataset.sel)); syncBulk(); });
  });
  $("#all", box)?.addEventListener("change", (e) => { shown.forEach((r) => (e.target.checked ? selected.add(r.id) : selected.delete(r.id))); renderTeam(); });
  $("#sel-all", box)?.addEventListener("click", () => { teamIds.forEach((id) => (allSelected ? selected.delete(id) : selected.add(id))); renderTeam(); });
  $("#prev", box)?.addEventListener("click", () => { teamPage--; loadTeam(); });
  $("#next", box)?.addEventListener("click", () => { teamPage++; loadTeam(); });
  $$("tr[data-id]", box).forEach((tr) => tr.addEventListener("click", () => hireView(Number(tr.dataset.id))));
  syncBulk();
}

function syncBulk() {
  const bar_ = $("#bulk");
  if (!bar_) return;
  bar_.classList.toggle("hidden", !selected.size);
  bar_.style.display = selected.size ? "flex" : "none";
  const inView = new Set(teamIds);
  const hidden = [...selected].filter((id) => !inView.has(id)).length;
  $("#bulk-count").textContent = `${selected.size} selected${hidden ? ` (${hidden} not in this view)` : ""}`;
}

async function bulkAction(kind) {
  const ids = [...selected];
  const done = (msg) => { toast(msg); selected.clear(); loadTeam(); };
  try {
    if (kind === "clear") { selected.clear(); renderTeam(); return; }
    if (kind === "assign") return assignModal(ids);
    if (kind === "remind") return reminders(ids);
    if (kind === "role") {
      if (!confirm(`Assign every missing role requirement to ${ids.length} people?`)) return;
      const r = await api.post("/api/manager/assignments/role-requirements", { employee_ids: ids });
      return done(`Assigned ${r.created.length} missing requirement${r.created.length === 1 ? "" : "s"}`);
    }
    if (kind === "due") {
      const pick = await trainingPicker({ title: `Change due dates for ${ids.length} people`, action: "Change due dates", due: "required",
        hint: "Leave all trainings unchecked to move every unfinished assignment." });
      if (!pick) return;
      const r = await api.post("/api/manager/assignments/bulk-due-date", { employee_ids: ids, training_codes: pick.codes, due_date: pick.due,
        stagger_weeks: pick.stagger });
      return done(`Updated ${r.changed} due date${r.changed === 1 ? "" : "s"}`);
    }
    if (kind === "remove") {
      const pick = await trainingPicker({ title: `Remove trainings from ${ids.length} people`, action: "Remove", hint: "Completed records are kept." });
      if (!pick || !pick.codes.length) return;
      const r = await api.post("/api/manager/assignments/bulk-remove", { employee_ids: ids, training_codes: pick.codes });
      return done(`Removed ${r.removed} assignment${r.removed === 1 ? "" : "s"}`);
    }
  } catch (e) { toast(e.message, true); }
}

/** Pick trainings (and optionally a due date). Resolves {codes, due} or null if cancelled. */
async function trainingPicker({ title, action, due = "", hint = "" }) {
  const trainings = await api.get("/api/trainings");
  return new Promise((resolve) => {
    const m = modal(`
      <div class="modal-head"><h2>${esc(title)}</h2><button class="btn ghost" data-close>Cancel</button></div>
      <div class="toolbar"><label class="field" style="flex:1">Filter<input id="p-q" placeholder="Search trainings"></label>
        ${due ? `<label class="field">Due date<input type="date" id="p-due" ${due === "required" ? "required" : ""}></label>
          <label class="field">Spread due dates<select id="p-stagger"><option value="0">Same day for everyone</option><option value="1">Over 1 week</option><option value="2">Over 2 weeks</option><option value="4">Over 4 weeks</option></select></label>` : ""}</div>
      <div style="max-height:380px;overflow-y:auto" class="list" id="p-list">${trainings.map((t) => `
        <label class="item small" data-text="${esc((t.code + " " + t.title + " " + t.category).toLowerCase())}"><input type="checkbox" value="${esc(t.code)}">
          <div class="grow"><strong>${esc(t.title)}</strong> <span class="muted">${esc(t.code)}</span><div class="muted">${CATEGORY_LABEL[t.category] || ""} · ${DELIVERY_LABEL[t.delivery]}</div></div></label>`).join("")}</div>
      ${hint ? `<p class="small muted">${esc(hint)}</p>` : ""}
      <button class="btn" id="p-go">${esc(action)}</button>`);
    let result = null;
    const obs = new MutationObserver(() => { if (!document.body.contains(m.root)) { obs.disconnect(); resolve(result); } });
    obs.observe(document.body, { childList: true });
    $("#p-q", m.root).addEventListener("input", (e) => $$("[data-text]", m.root).forEach((el) => el.classList.toggle("hidden", !el.dataset.text.includes(e.target.value.toLowerCase()))));
    $("#p-go", m.root).onclick = () => {
      const dueVal = $("#p-due", m.root)?.value || null;
      if (due === "required" && !dueVal) return toast("Pick a due date", true);
      result = { codes: $$("#p-list input:checked", m.root).map((c) => c.value), due: dueVal, stagger: Number($("#p-stagger", m.root)?.value || 0) };
      m.close();
    };
  });
}

// ---- Hire view (read-only) --------------------------------------------------

async function hireView(id) {
  const m = modal(`<div class="empty"><span class="spinner"></span> Loading…</div>`, { wide: true });
  const d = await api.get(`/api/manager/team/${id}`);
  const e = d.employee, s = d.summary, p = d.promotion;
  const skills = Object.entries(e.skills).sort((a, b) => b[1] - a[1]).slice(0, 14);
  m.root.innerHTML = `
    <div class="modal-head"><div><h2>${esc(e.name)} <span class="badge plain">Hire view · read only</span></h2>
      <div class="muted small">${esc(e.job_title)} · Level ${e.level} · ${esc(e.division_code)} · ${esc(e.email)}</div></div>
      <button class="btn ghost" data-close>Close</button></div>
    <div class="grid cols-4" style="margin-bottom:12px">
      <div class="stat"><div class="label">Hired</div><div class="value" style="font-size:16px">${fmtDate(e.hire_date)}</div></div>
      <div class="stat"><div class="label">Experience</div><div class="value">${e.years_experience}<span class="small muted"> yrs</span></div></div>
      <div class="stat"><div class="label">HR rating / salary</div><div class="value" style="font-size:16px">${e.performance_rating ?? "—"} · ${e.salary ? "$" + Math.round(e.salary).toLocaleString() : "—"}</div></div>
      <div class="stat ${s.overdue ? "bad" : "ok"}"><div class="label">Completed</div><div class="value">${s.completed}/${s.total}</div></div>
    </div>
    <div class="grid side">
      <div>
        <div class="card-head"><h3>Trainings</h3><button class="btn small" id="hv-assign">Assign training</button></div>
        <div class="table-wrap"><table><thead><tr><th>Training</th><th>Status</th><th>Due / done</th><th>Score</th><th>Tries</th><th>Next retraining</th><th></th></tr></thead>
        <tbody>${d.assignments.map((a) => `<tr>
          <td><strong>${esc(a.training.title)}</strong><div class="small muted">${esc(a.training.code)} · ${CATEGORY_LABEL[a.training.category] || ""} · ${a.training.required ? "Required" : "Optional"}</div></td>
          <td>${statusBadge(a)}${a.readiness ? ` <span class="badge ${{ ready: "ok", ready_with_support: "warn", not_ready: "bad" }[a.readiness.readiness]}">${esc(a.readiness.label)}</span>` : ""}
            ${a.status === "in_progress" ? `<div style="width:80px">${bar(a.progress)}</div>` : ""}</td>
          <td class="small">${a.status === "completed" ? fmtDate(a.completed_at)
            : `<input type="date" value="${a.due_date || ""}" data-due="${a.id}" aria-label="Due date" style="padding:3px 6px"><div class="muted">${dueText(a.due_date)}</div>`}</td>
          <td class="num">${a.best_score ?? "—"}</td><td class="num">${a.attempts}</td>
          <td class="small">${fmtDate(a.next_retraining)}</td>
          <td>${a.status !== "completed" ? `<button class="btn ghost small" data-unassign="${a.id}">Remove</button>` : ""}</td></tr>`).join("")}</tbody></table></div>
        <h3 style="margin-top:16px">Recommended path</h3>
        <ol class="small">${d.path.slice(0, 6).map((x) => `<li><strong>${esc(x.title)}</strong> <span class="muted">${x.reasons.map(esc).join(" · ")}</span></li>`).join("")}</ol>
      </div>
      <div class="grid" style="align-content:start">
        <section class="card flat"><h3>Promotion readiness ${p.ready ? `<span class="badge ok">Ready</span>` : `<span class="badge plain">Not yet</span>`}</h3>
          ${p.next_position ? `<p class="small muted">Next step: ${esc(p.next_position.title)} (level ${p.next_position.level})</p>` : `<p class="small muted">No next-level role defined in this division.</p>`}
          ${Object.entries(p.checks).map(([k, v]) => `<div class="small">${v ? "✔" : "✘"} ${esc(k)}</div>`).join("")}</section>
        <section class="card flat"><div class="card-head"><h3>Skills</h3><button class="btn secondary small" id="hv-infer">Re-estimate with AI</button></div>
          <div id="hv-skills" class="list">${skills.map(([k, v]) => `<div class="small">${esc(k)} <span class="muted num">${Math.round(v * 100)}%</span>${bar(v * 100, v >= 0.7 ? "ok" : "")}</div>`).join("")}</div></section>
        <section class="card flat"><h3>Knowledge gaps</h3>${d.gaps.slice(0, 6).map((g) => `<div class="small">${esc(g.skill)} ${bar(g.mastery * 100, "warn")}</div>`).join("") || `<p class="small muted">None</p>`}</section>
        <section class="card flat"><h3>Learning profile</h3><p class="small">Style: ${esc(d.profile.learning_style)} · works best with ${esc(d.profile.modality)} · ${esc(d.profile.pacing.pace)} pace</p></section>
      </div>
    </div>`;
  $("#hv-assign", m.root).onclick = () => { m.close(); assignModal([id]); };
  $$("[data-due]", m.root).forEach((inp) => inp.addEventListener("change", async () => {
    if (!inp.value) return;
    try { await api.patch(`/api/manager/assignments/${inp.dataset.due}`, { due_date: inp.value }); toast("Due date updated"); inp.nextElementSibling.textContent = dueText(inp.value); }
    catch (e) { toast(e.message, true); }
  }));
  $$("[data-unassign]", m.root).forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Remove this assignment?")) return;
    await api.del(`/api/manager/assignments/${b.dataset.unassign}`); toast("Removed"); m.close(); hireView(id);
  }));
  $("#hv-infer", m.root).onclick = async (ev) => {
    ev.target.disabled = true; ev.target.textContent = "Estimating…";
    const r = await api.post(`/api/manager/team/${id}/infer-skills`);
    const top = Object.entries(r.saved_skills).sort((a, b) => b[1] - a[1]).slice(0, 14);
    $("#hv-skills", m.root).innerHTML = top.map(([k, v]) => `<div class="small">${esc(k)} <span class="muted num">${Math.round(v * 100)}%</span>${bar(v * 100, v >= 0.7 ? "ok" : "")}</div>`).join("");
    ev.target.textContent = r.generated_by === "offline" ? "Updated (offline)" : "Updated";
  };
}

// ---- Assign -----------------------------------------------------------------

async function assignModal(employeeIds) {
  const trainings = await api.get("/api/trainings");
  const m = modal(`
    <div class="modal-head"><h2>Assign training to ${employeeIds.length} ${employeeIds.length === 1 ? "person" : "people"}</h2><button class="btn ghost" data-close>Cancel</button></div>
    <div class="toolbar"><label class="field" style="flex:1">Filter<input id="a-q" placeholder="Search trainings"></label>
      <label class="field">Due date<input type="date" id="a-due"></label>
      <label class="field">Spread due dates<select id="a-stagger"><option value="0">Same day for everyone</option><option value="1">Over 1 week</option><option value="2">Over 2 weeks</option><option value="4">Over 4 weeks</option></select></label></div>
    <div style="max-height:380px;overflow-y:auto" class="list" id="a-list">${trainings.map((t) => `
      <label class="item small" data-text="${esc((t.code + " " + t.title + " " + t.category).toLowerCase())}"><input type="checkbox" value="${esc(t.code)}">
        <div class="grow"><strong>${esc(t.title)}</strong> <span class="muted">${esc(t.code)}</span><div class="muted">${CATEGORY_LABEL[t.category] || ""} · ${DELIVERY_LABEL[t.delivery]} · ${esc(t.source_system)}${t.required ? " · Required" : ""}</div></div></label>`).join("")}</div>
    <p class="small muted">Leave the due date empty to use the default (30 days for required, 60 for optional; new hires get at least 30 days from their start).
      For big groups, spreading due dates keeps everyone from logging in the night before.</p>
    <button class="btn" id="a-go">Assign</button>`);
  $("#a-q", m.root).addEventListener("input", (e) => $$("[data-text]", m.root).forEach((el) => el.classList.toggle("hidden", !el.dataset.text.includes(e.target.value.toLowerCase()))));
  $("#a-go", m.root).onclick = async () => {
    const codes = $$("#a-list input:checked", m.root).map((c) => c.value);
    if (!codes.length) return toast("Pick at least one training", true);
    try {
      const r = await api.post("/api/manager/assignments", { employee_ids: employeeIds, training_codes: codes, due_date: $("#a-due", m.root).value || null,
        stagger_weeks: Number($("#a-stagger", m.root).value) });
      toast(`Assigned ${r.created.length}${r.skipped.length ? `, skipped ${r.skipped.length} already assigned` : ""}`);
      m.close();
      selected.clear();
      if (location.hash === "#team") loadTeam();
      else if (location.hash === "#assign") assign();
    } catch (e) { toast(e.message, true); }
  };
}

async function assign() {
  loading(view);
  const people = await api.get("/api/manager/team?lite=true");
  const subs = [...new Map(people.filter((p) => p.sub_team).map((p) => [p.sub_team.id, p.sub_team])).values()];
  view.innerHTML = `
    <div class="card-head"><h1>Assign trainings</h1></div>
    <section class="card">
      <p class="muted">Choose people, then pick trainings from every LANL training site.</p>
      <div class="toolbar">
        <label class="field" style="flex:1;min-width:200px">Find people<input id="pick-q" placeholder="Name, title or Z number"></label>
        <button class="btn secondary small" id="pick-new">Select new hires</button>
        ${subs.map((t) => `<button class="btn secondary small" data-pick-sub="${t.id}">${esc(t.name)}'s team</button>`).join("")}
        <button class="btn secondary small" id="pick-all">Select everyone shown</button><button class="btn ghost small" id="pick-none">Clear</button>
        <span class="small muted" id="pick-count">0 selected</span></div>
      <div class="grid cols-3" style="max-height:60vh;overflow-y:auto">${people.map((p) => `<label class="item small" data-text="${esc((p.name + " " + p.job_title + " " + p.employee_number).toLowerCase())}">
        <input type="checkbox" data-p="${p.id}" data-new="${p.is_new_hire}" data-sub="${p.sub_team?.id ?? ""}" data-self="${p.id}">
        <div class="grow"><strong>${esc(p.name)}</strong><div class="muted">${esc(p.job_title)} · L${p.level}${p.sub_team ? ` · ${esc(p.sub_team.name)}'s team` : ""}</div></div></label>`).join("")}</div>
      <div style="margin-top:12px;display:flex;gap:8px"><button class="btn" id="next">Choose trainings</button>
        <button class="btn secondary" id="next-role">Assign missing role requirements</button></div>
    </section>`;
  const boxes = $$("[data-p]");
  const visible = () => boxes.filter((b) => !b.closest("label").classList.contains("hidden"));
  const count = () => ($("#pick-count").textContent = `${boxes.filter((b) => b.checked).length} selected`);
  boxes.forEach((b) => b.addEventListener("change", count));
  $("#pick-q").addEventListener("input", (e) => $$("[data-text]").forEach((el) => el.classList.toggle("hidden", !el.dataset.text.includes(e.target.value.toLowerCase()))));
  $("#pick-new").onclick = () => { boxes.forEach((b) => (b.checked = b.dataset.new === "true")); count(); };
  $$("[data-pick-sub]").forEach((btn) => (btn.onclick = () => {
    boxes.forEach((b) => (b.checked = b.dataset.sub === btn.dataset.pickSub || b.dataset.self === btn.dataset.pickSub)); count();
  }));
  $("#pick-all").onclick = () => { visible().forEach((b) => (b.checked = true)); count(); };
  $("#pick-none").onclick = () => { boxes.forEach((b) => (b.checked = false)); count(); };
  const chosen = () => boxes.filter((b) => b.checked).map((b) => Number(b.dataset.p));
  $("#next").onclick = () => { const ids = chosen(); if (!ids.length) return toast("Pick at least one person", true); assignModal(ids); };
  $("#next-role").onclick = async () => {
    const ids = chosen(); if (!ids.length) return toast("Pick at least one person", true);
    const r = await api.post("/api/manager/assignments/role-requirements", { employee_ids: ids });
    toast(`Assigned ${r.created.length} missing requirement${r.created.length === 1 ? "" : "s"}`);
  };
}

// ---- Retraining -------------------------------------------------------------

function retrainTable(rows) {
  if (!rows.length) return `<p class="muted small">Nothing coming up.</p>`;
  const cls = { "failed assessment": "bad", expired: "bad", expiring: "warn", "scheduled refresher": "" };
  return `<div class="table-wrap"><table><thead><tr><th>Person</th><th>Training</th><th>Why</th><th>Score</th><th>Expires</th><th>Retrain by</th></tr></thead>
    <tbody>${rows.map((r) => `<tr><td>${esc(r.name)}</td><td><strong>${esc(r.title)}</strong><div class="small muted">${esc(r.training_code)}</div></td>
      <td><span class="badge ${cls[r.reason] ?? ""}">${esc(r.reason)}</span></td><td class="num">${r.best_score ?? "—"}</td>
      <td class="small">${fmtDate(r.expires_at)}</td><td class="small">${fmtDate(r.next_retraining)}</td></tr>`).join("")}</tbody></table></div>`;
}

async function retraining() {
  loading(view);
  const rows = await api.get("/api/manager/retraining?days=120");
  view.innerHTML = `
    <div class="card-head"><h1>Expiring trainings &amp; retakes</h1></div>
    <p class="muted">Retraining cycles come from assessment scores: under 80 means a retake within 14 days, 80–89 means a refresher at 75% of the certification period, 90+ follows the normal expiry.</p>
    <div class="toolbar"><button class="btn" id="remind">Email reminders to my team</button></div>
    <section class="card">${retrainTable(rows)}</section>`;
  $("#remind").onclick = () => reminders([]);
}

async function reminders(ids = []) {
  const preview = await api.post("/api/manager/reminders", { employee_ids: ids, send: false });
  const m = modal(`
    <div class="modal-head"><h2>Reminder emails (${preview.messages.length})</h2><button class="btn ghost" data-close>Cancel</button></div>
    <p class="small muted">Each person gets one email listing what's overdue, needs a retake, is expiring, or is due soon. Nothing is sent until you click Send.</p>
    <div class="list" style="max-height:420px;overflow-y:auto">${preview.messages.map((x) => `
      <div class="card flat"><div class="small"><strong>To:</strong> ${esc(x.to)}<br><strong>Subject:</strong> ${esc(x.subject)}</div>
      <pre class="small" style="white-space:pre-wrap;margin:6px 0 0;font-family:inherit">${esc(x.body)}</pre></div>`).join("") || `<p class="muted">Nobody has anything due.</p>`}</div>
    <div style="margin-top:12px"><button class="btn" id="send" ${preview.messages.length ? "" : "disabled"}>Send ${preview.messages.length} emails</button></div>`, { wide: true });
  $("#send", m.root).onclick = async (e) => {
    e.target.disabled = true;
    try {
      const r = await api.post("/api/manager/reminders", { employee_ids: ids, send: true });
      toast(r.mode === "preview" ? "Email is in preview mode on the server (set EMAIL_MODE to send). Nothing was sent." : `Sent ${r.sent} emails`);
      m.close();
    } catch (err) { toast(err.message, true); e.target.disabled = false; }
  };
}

// ---- Compliance & knowledge gaps --------------------------------------------

let heatGroup = "position";

async function insightsView() {
  loading(view);
  const [heat, comp] = await Promise.all([api.get(`/api/manager/insights/heatmap?group_by=${heatGroup}`), api.get("/api/manager/insights/compliance")]);
  const color = (v) => {
    if (v == null) return "background:#f4f5f9;color:#b0b5c8";
    // white -> navy as mastery rises; red tint under 40%
    if (v < 0.4) return `background:rgba(179,38,30,${0.18 + (0.4 - v)});color:${v < 0.2 ? "#fff" : "var(--bad)"}`;
    return `background:rgba(11,30,132,${0.12 + v * 0.8});color:${v > 0.55 ? "#fff" : "var(--navy-dark)"}`;
  };
  view.innerHTML = `
    <div class="card-head"><h1>Compliance &amp; knowledge gaps</h1></div>
    <section class="card" style="margin-bottom:16px">
      <div class="card-head"><h3>Required training compliance by division</h3><span class="muted small">Complete and current, out of required assignments</span></div>
      <div class="table-wrap"><table><thead><tr><th>Division</th><th>People</th><th>Compliance</th><th>Safety compliance</th><th>Overdue</th><th>Expired</th></tr></thead>
      <tbody>${comp.map((c) => `<tr><td><strong>${esc(c.division_code)}</strong> <span class="muted small">${esc(c.division_name)}</span></td><td class="num">${c.people}</td>
        <td style="min-width:140px">${bar(c.compliance_rate, c.compliance_rate < 70 ? "bad" : c.compliance_rate < 90 ? "warn" : "ok")}<span class="small num">${pct(c.compliance_rate)}</span></td>
        <td style="min-width:140px">${bar(c.safety_compliance_rate, c.safety_compliance_rate < 70 ? "bad" : c.safety_compliance_rate < 90 ? "warn" : "ok")}<span class="small num">${pct(c.safety_compliance_rate)}</span></td>
        <td class="num">${c.overdue}</td><td class="num">${c.expired}</td></tr>`).join("")}</tbody></table></div>
    </section>
    <section class="card">
      <div class="card-head"><h3>Knowledge-gap heatmap</h3>
        <div class="chips"><button class="chip ${heatGroup === "position" ? "active" : ""}" data-g="position">By role</button>
        <button class="chip ${heatGroup === "equipment" ? "active" : ""}" data-g="equipment">By equipment</button></div></div>
      <p class="small muted">Average estimated mastery of each skill. Darker blue is stronger; red is where people are weakest and training should focus.</p>
      ${heat.rows.length ? `<div class="table-wrap"><table style="font-size:12px"><thead><tr><th>${heatGroup === "position" ? "Role" : "Equipment"}</th><th>People</th>
        ${heat.skills.map((s) => `<th style="writing-mode:vertical-rl;transform:rotate(180deg);height:160px;vertical-align:bottom;white-space:nowrap">${esc(s)}</th>`).join("")}</tr></thead>
        <tbody>${heat.rows.map((r) => `<tr><td><strong>${esc(r.group)}</strong></td><td class="num">${r.people}</td>
          ${heat.skills.map((s) => { const v = r.cells[s]; return `<td class="num" style="text-align:center;${color(v)}" title="${esc(s)}">${v == null ? "" : Math.round(v * 100)}</td>`; }).join("")}</tr>`).join("")}</tbody></table></div>`
        : `<div class="empty">Not enough data yet.</div>`}
    </section>`;
  $$("[data-g]").forEach((b) => b.addEventListener("click", () => { heatGroup = b.dataset.g; insightsView(); }));
}

// ---- Open roles -------------------------------------------------------------

const roleFilter = { qualified_only: "", min_level: "", max_level: "", new_hires_only: "", scope: "lab" };

async function roles() {
  loading(view);
  const positions = await api.get("/api/manager/positions");
  view.innerHTML = `
    <div class="card-head"><h1>Open roles</h1><span class="muted small">Candidates ranked by AI-estimated skills, completed trainings, experience and performance</span></div>
    <div class="grid side">
      <section class="card" style="align-self:start"><div class="list">${positions.map((p) => `
        <button class="item" style="text-align:left;cursor:pointer;font:inherit" data-pos="${esc(p.code)}"><div class="grow"><div class="title">${esc(p.title)}</div>
          <div class="small muted">${esc(p.code)} · ${esc(p.division_code)} · Level ${p.level} · ${p.min_years}+ yrs${p.fiscal_year ? ` · FY${p.fiscal_year}` : ""} · ${p.headcount} opening${p.headcount === 1 ? "" : "s"}</div></div></button>`).join("") || `<p class="muted">No open roles.</p>`}</div></section>
      <section id="cands" class="card"><div class="empty">Pick a role to see who fits.</div></section>
    </div>`;
  $$("[data-pos]").forEach((b) => b.addEventListener("click", () => { $$("[data-pos]").forEach((x) => (x.style.borderColor = "")); b.style.borderColor = "var(--navy)"; candidates(b.dataset.pos); }));
  if (positions[0]) $$("[data-pos]")[0].click();
}

async function candidates(code) {
  const box = $("#cands");
  loading(box);
  const q = new URLSearchParams(Object.entries(roleFilter).filter(([, v]) => v !== ""));
  const r = await api.get(`/api/manager/positions/${encodeURIComponent(code)}/candidates?${q}`);
  const p = r.position;
  box.innerHTML = `
    <div class="card-head"><h2>${esc(p.title)}</h2></div>
    <p class="small"><strong>Skills:</strong> ${p.required_skills.map((s) => `<span class="badge plain">${esc(s)}</span>`).join(" ")}</p>
    <p class="small"><strong>Trainings:</strong> ${p.required_trainings.map((s) => `<span class="badge plain">${esc(s)}</span>`).join(" ")} · <strong>Years:</strong> ${p.min_years}+ · <strong>Level:</strong> ${p.level}</p>
    ${p.prerequisites.length ? `<p class="small"><strong>Prerequisites:</strong> ${p.prerequisites.map(esc).join("; ")}</p>` : ""}
    <div class="toolbar">
      <label class="field">Search<select id="r-scope"><option value="lab">Whole lab</option><option value="team">My team</option></select></label>
      <label class="field">Show<select id="r-q"><option value="">Everyone ranked</option><option value="true">Meets all requirements</option></select></label>
      <label class="field">Who<select id="r-new"><option value="">Anyone</option><option value="true">New hires only</option></select></label>
      <label class="field">Min level<select id="r-min"><option value="">Any</option>${[1, 2, 3, 4].map((l) => `<option>${l}</option>`).join("")}</select></label>
      <label class="field">Max level<select id="r-max"><option value="">Any</option>${[1, 2, 3, 4].map((l) => `<option>${l}</option>`).join("")}</select></label>
    </div>
    ${r.candidates.length ? `<div class="table-wrap"><table><thead><tr><th>#</th><th>Candidate</th><th>Fit</th><th>Skills</th><th>Trainings</th><th>Years</th><th>Missing</th></tr></thead>
      <tbody>${r.candidates.slice(0, 25).map((c, i) => `<tr>
        <td class="num">${i + 1}</td>
        <td><strong>${esc(c.name)}</strong> ${c.meets_requirements ? `<span class="badge ok">Qualified</span>` : ""}<div class="small muted">${esc(c.job_title)} · L${c.level}</div></td>
        <td style="min-width:90px"><strong class="num">${c.fit_score}</strong>${bar(c.fit_score, c.fit_score >= 75 ? "ok" : "")}</td>
        <td class="num">${pct(c.skill_coverage)}</td><td class="num">${pct(c.training_coverage)}</td>
        <td class="num">${c.years_experience} ${c.meets_years ? "✔" : "✘"}</td>
        <td class="small">${[...c.missing_skills, ...c.missing_trainings].slice(0, 4).map((x) => `<span class="badge warn">${esc(x)}</span>`).join(" ") || "—"}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty">No candidates match these filters.</div>`}`;
  [["#r-scope", "scope"], ["#r-q", "qualified_only"], ["#r-new", "new_hires_only"], ["#r-min", "min_level"], ["#r-max", "max_level"]].forEach(([s, k]) => {
    $(s, box).value = roleFilter[k];
    $(s, box).addEventListener("change", (e) => { roleFilter[k] = e.target.value; candidates(code); });
  });
}

// ---- Promotions -------------------------------------------------------------

async function promotions() {
  loading(view);
  const rows = await api.get("/api/manager/promotions");
  view.innerHTML = `
    <div class="card-head"><h1>Promotion readiness</h1><span class="muted small">${rows.filter((r) => r.ready).length} of ${rows.length} ready</span></div>
    <div class="grid cols-2">${rows.map((r) => `
      <section class="card"><div class="card-head"><h3>${esc(r.name)}</h3>${r.ready ? `<span class="badge ok">Ready</span>` : `<span class="badge plain">Not yet</span>`}</div>
        <p class="small muted">${esc(r.job_title)} · Level ${r.current_level}${r.next_position ? ` → ${esc(r.next_position.title)}` : ""} · performance index ${r.performance_index}</p>
        ${Object.entries(r.checks).map(([k, v]) => `<div class="small">${v ? "✔" : "✘"} ${esc(k)}</div>`).join("")}
        <button class="btn ghost small" data-person="${r.employee_id}" style="margin-top:6px">Open hire view</button></section>`).join("")}</div>`;
  $$("[data-person]").forEach((b) => b.addEventListener("click", () => hireView(Number(b.dataset.person))));
}

// ---- Data sources (admin) ---------------------------------------------------

async function data() {
  loading(view);
  const [c, runs] = await Promise.all([api.get("/api/admin/connectors"), api.get("/api/admin/sync-runs")]);
  const label = { directory: "LANL directory (divisions, positions)", utrain: "UTrain + other training sites", oracle_hr: "Oracle HR (employees, history)" };
  view.innerHTML = `
    <div class="card-head"><h1>Data sources</h1><button class="btn" id="sync">Sync everything now</button></div>
    <div class="grid cols-3" style="margin-bottom:16px">${c.health.map((h) => `
      <section class="card"><h3>${esc(label[h.source] || h.source)}</h3>
        <p class="small">Mode: <span class="badge">${esc(c.modes[h.source])}</span> ${h.ok ? `<span class="badge ok">Connected</span>` : `<span class="badge bad">Error</span>`}</p>
        <p class="small muted">${h.ok ? Object.entries(h.counts).map(([k, v]) => `${v} ${k}`).join(" · ") : esc(h.error)}</p></section>`).join("")}</div>
    <section class="card" style="margin-bottom:16px"><h3>Upload an export</h3>
      <p class="small muted">CSV or JSON. Column names are matched automatically; add a mapping.json for unusual headers. Files go to <code>${esc(c.data_dir)}</code>.</p>
      <form id="up" class="toolbar"><label class="field">Data type<select name="entity">
        ${["employees", "training_history", "trainings", "training_sessions", "divisions", "positions", "mapping"].map((e) => `<option>${e}</option>`).join("")}
        <option value="__site">trainings from another site…</option></select></label>
        <label class="field" id="site-field" style="display:none">Site name<input name="site" placeholder="e.g. nucleus"></label>
        <label class="field">File<input type="file" name="file" accept=".csv,.json" required></label><button class="btn">Upload &amp; sync</button></form></section>
    <section class="card"><h3>Recent syncs</h3><div class="table-wrap"><table><thead><tr><th>When</th><th>Source</th><th>Created</th><th>Updated</th><th>Warnings</th></tr></thead>
      <tbody>${runs.map((r) => `<tr><td class="small">${new Date(r.started_at + "Z").toLocaleString()}</td><td>${esc(r.source)}</td><td class="num">${r.created}</td><td class="num">${r.updated}</td>
        <td class="small">${r.errors.length ? r.errors.slice(0, 3).map(esc).join("<br>") : "—"}</td></tr>`).join("")}</tbody></table></div></section>`;
  $("#sync").onclick = async (e) => {
    e.target.disabled = true;
    try { const r = await api.post("/api/admin/sync"); toast(`Synced. ${r.auto_assigned} required trainings auto-assigned.`); data(); }
    catch (err) { toast(err.message, true); e.target.disabled = false; }
  };
  $("#up [name=entity]").onchange = (e) => ($("#site-field").style.display = e.target.value === "__site" ? "" : "none");
  $("#up").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    let entity = f.get("entity");
    if (entity === "__site") entity = "trainings_" + String(f.get("site") || "other").toLowerCase().replace(/[^a-z0-9]+/g, "_");
    const body = new FormData(); body.append("file", f.get("file"));
    try { await api.upload(`/api/admin/upload/${entity}`, body); await api.post("/api/admin/sync"); toast("Uploaded and synced"); data(); }
    catch (err) { toast(err.message, true); }
  };
}

const go = router({ overview, team, assign, retraining, insights: insightsView, roleplans: () => rolesView(view),
  interviews: () => interviewsView(view), roles, promotions, data }, "overview");
