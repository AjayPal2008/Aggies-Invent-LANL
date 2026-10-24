// Role setup and interview review pages for the manager dashboard.
//   Role plans: upload a role's job description, requirements and internal documents, let the AI build
//   courses from them, curate the role's training plan, and start people in the role.
//   Interview reviews: read or listen to interview-style assessment answers and confirm or override the AI score.
import { api, esc, $, $$, fmtDate, toast, modal, loading, CATEGORY_LABEL } from "/shared/api.js?v=20261024e";
import { readinessCard } from "/hire/learning.js";

const PHASES = { 1: "First 2 weeks", 2: "First 30 days", 3: "First 90 days" };
const AUDIENCE = { all: "Everyone", new_hire: "New to LANL only", internal: "Internal moves", promotion: "Promotions only", transfer: "Transfers only" };
const ENTRY = { new_hire: "New hire", promotion: "Promotion", transfer: "Transfer" };
const KINDS = { job_description: "Job description", requirements: "Role requirements", handbook: "Handbook", manual: "Manual",
  policy: "Policy", procedure: "Procedure" };
const ASSESS = { quiz: "Quiz", situational: "Interview", both: "Quiz + interview" };
const ASSESS_HELP = "Quiz: policies, rules, procedures, technical facts. Interview: leading people and judgment calls. Both: needs the rules and the judgment.";

let current = null; // selected role code
let plan = []; // editable plan items

export async function rolesView(view) {
  loading(view);
  const list = await api.get("/api/manager/roles");
  current ||= (list.find((r) => r.documents) || list.find((r) => r.is_open) || list[0])?.code;
  view.innerHTML = `
    <div class="card-head"><h1>Role plans</h1><button class="btn" id="new-role">New role</button></div>
    <p class="muted">Upload a role's job description, requirements and internal documents. The AI turns long documents into
      courses, suggests a training plan, and tailors it to each person depending on whether they're new to LANL, promoted or transferring.</p>
    <div class="grid" style="grid-template-columns:minmax(220px,280px) minmax(0,1fr)">
      <section class="card" style="align-self:start;max-height:80vh;overflow-y:auto">
        <input id="r-q" placeholder="Find a role" style="width:100%;margin-bottom:8px">
        <div class="list" id="r-list">${list.map((r) => `
          <button class="item" data-role="${esc(r.code)}" data-text="${esc((r.title + " " + r.code + " " + r.division_code).toLowerCase())}"
            style="text-align:left;cursor:pointer;font:inherit;${r.code === current ? "border-color:var(--navy);background:var(--navy-tint)" : ""}">
            <div class="grow"><div class="title">${esc(r.title)}</div>
              <div class="small muted">${esc(r.code)} · L${r.level}</div>
              <div class="chips" style="margin-top:3px">${r.is_open ? `<span class="badge">Open</span>` : ""}${r.has_plan ? `<span class="badge ok">Plan</span>` : ""}
                ${r.documents ? `<span class="badge plain">${r.documents} doc${r.documents === 1 ? "" : "s"}</span>` : ""}</div></div></button>`).join("")}</div>
      </section>
      <section id="role-detail"></section>
    </div>`;
  $("#r-q").addEventListener("input", (e) => $$("[data-text]").forEach((b) => b.classList.toggle("hidden", !b.dataset.text.includes(e.target.value.toLowerCase()))));
  $$("[data-role]").forEach((b) => b.addEventListener("click", () => { current = b.dataset.role; rolesView(view); }));
  $("#new-role").onclick = () => roleForm(view, null);
  if (current) roleDetail(view, list.find((r) => r.code === current));
}

async function roleDetail(view, role) {
  const box = $("#role-detail");
  loading(box);
  const [docs, p] = await Promise.all([api.get(`/api/manager/documents?position_code=${encodeURIComponent(role.code)}`),
    api.get(`/api/manager/roles/${encodeURIComponent(role.code)}/plan`)]);
  plan = p.items.map((i) => ({ ...i }));
  box.innerHTML = `
    <section class="card" style="margin-bottom:16px">
      <div class="card-head"><div><h2>${esc(role.title)}</h2>
        <div class="small muted">${esc(role.code)} · ${esc(role.division_code)} · Level ${role.level} · ${role.min_years}+ years${role.leadership ? " · Leadership role" : ""}${role.is_open ? ` · ${role.headcount} open` : ""}</div></div>
        <div style="display:flex;gap:6px"><button class="btn secondary small" id="edit-role">Edit</button><button class="btn small" id="start">Start people in this role</button></div></div>
      <div class="small"><strong>Skills:</strong> ${(role.required_skills || []).map((s) => `<span class="badge plain">${esc(s)}</span>`).join(" ") || "<span class='muted'>none yet</span>"}</div>
      ${role.prerequisites?.length ? `<div class="small" style="margin-top:4px"><strong>Prerequisites:</strong> ${role.prerequisites.map(esc).join("; ")}</div>` : ""}
    </section>

    <section class="card" style="margin-bottom:16px">
      <div class="card-head"><h3>Documents</h3><span class="small muted">PDF, Word or text · long manuals are fine</span></div>
      <form id="up" class="toolbar">
        <label class="field">Type<select name="kind">${Object.entries(KINDS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
        <label class="field" style="flex:1">Title<input name="title" placeholder="Defaults to the file name"></label>
        <label class="field">File<input type="file" name="file" accept=".pdf,.docx,.txt,.md" required></label>
        <button class="btn">Upload</button>
      </form>
      <p class="small muted">Handbooks, manuals, policies and procedures become courses with modules, video lessons and interview scenarios.
        Job descriptions and requirements are used to build the plan.</p>
      <div class="list" id="docs">${docs.map(docCard).join("") || `<p class="muted small">No documents yet.</p>`}</div>
      <div style="margin-top:10px;display:flex;gap:8px;align-items:center">
        <button class="btn secondary" id="analyze">Analyze job description &amp; suggest plan</button><span class="small muted" id="an-status"></span></div>
      <div id="analysis"></div>
    </section>

    <section class="card">
      <div class="card-head"><h3>Training plan</h3>
        <span class="small muted">${p.saved ? "Saved plan" : "Suggested plan (not saved yet)"}</span></div>
      <p class="small muted">${esc(ASSESS_HELP)}</p>
      <p class="small muted">Who gets what is decided per person: "New to LANL only" items (culture, how the Lab works) are skipped for internal
        promotions and transfers, anything already completed and current is skipped, and experienced people can skip items with a years threshold.</p>
      <div id="plan"></div>
      <div class="toolbar" style="margin-top:10px">
        <label class="field" style="flex:1">Add a training<select id="add-t"><option value="">Choose…</option></select></label>
        <button class="btn secondary" id="add">Add</button><span style="flex:1"></span>
        <button class="btn" id="save">Save plan</button></div>
    </section>`;
  renderPlan();
  const trainings = await api.get("/api/trainings");
  $("#add-t").innerHTML += trainings.map((t) => `<option value="${esc(t.code)}">${esc(t.code)} · ${esc(t.title)}</option>`).join("");
  $("#add").onclick = () => {
    const t = trainings.find((x) => x.code === $("#add-t").value);
    if (!t || plan.some((i) => i.training_code === t.code)) return;
    plan.push({ training_code: t.code, title: t.title, category: t.category, assessment_type: t.assessment_type, phase: 2, audience: "all",
      required: true, skip_if_years_at_least: null, reason: "Added by manager" });
    renderPlan();
  };
  $("#save").onclick = async () => {
    try { await api.put(`/api/manager/roles/${encodeURIComponent(role.code)}/plan`, { items: plan }); toast("Plan saved"); rolesView(view); }
    catch (e) { toast(e.message, true); }
  };
  $("#edit-role").onclick = () => roleForm(view, role);
  $("#start").onclick = () => startModal(view, role);
  $("#up").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    f.append("position_code", role.code);
    const btn = e.target.querySelector("button");
    btn.disabled = true; btn.textContent = "Uploading…";
    try {
      const d = await api.upload("/api/manager/documents", f);
      toast(d.status === "generating" ? `Read ${d.pages} pages. Building the course in the background…` : `Uploaded ${d.pages} page${d.pages === 1 ? "" : "s"}`);
      roleDetail(view, role);
    } catch (err) { toast(err.message, true); btn.disabled = false; btn.textContent = "Upload"; }
  };
  wireDocs(view, role);
  $("#analyze").onclick = async () => {
    $("#an-status").innerHTML = `<span class="spinner"></span> Reading the job description…`;
    try {
      const a = await api.post(`/api/manager/roles/${encodeURIComponent(role.code)}/analyze`, { apply_skills: true });
      $("#an-status").textContent = a.generated_by === "offline" ? "Offline analysis (add an API key for a deeper read)" : "";
      if (a.error) { $("#analysis").innerHTML = `<p class="small" style="color:var(--bad)">${esc(a.error)}</p>`; return; }
      $("#analysis").innerHTML = `<div class="card flat" style="margin-top:10px;background:var(--navy-tint)">
        <p>${esc(a.summary)}</p>
        <div class="grid cols-2">
          <div><h4>Responsibilities</h4><ul class="small">${a.responsibilities.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
          <div><h4>Skills (saved to the role)</h4><div class="chips">${a.required_skills.map((s) => `<span class="badge">${esc(s)}</span>`).join("")}</div>
            <h4 style="margin-top:8px">Minimum experience</h4><p class="small">${a.min_years} years</p>
            ${a.uncovered_topics?.length ? `<h4>Not covered by any training yet</h4><ul class="small">${a.uncovered_topics.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>
        </div>
        <button class="btn small" id="use-plan">Use the suggested plan (${a.plan.length} trainings)</button></div>`;
      $("#use-plan").onclick = () => {
        const titles = Object.fromEntries(trainings.map((t) => [t.code, t]));
        plan = a.plan.map((i) => ({ ...i, title: titles[i.training_code]?.title || i.training_code, category: titles[i.training_code]?.category,
          assessment_type: titles[i.training_code]?.assessment_type }));
        renderPlan(); toast("Suggested plan loaded. Review it, then Save plan.");
      };
    } catch (e) { $("#an-status").textContent = e.message; }
  };
}

function docCard(d) {
  const st = { generating: `<span class="badge warn"><span class="spinner" style="width:10px;height:10px;border-width:2px"></span> Building course</span>`,
    ready: `<span class="badge ok">Course ready</span>`, failed: `<span class="badge bad">Failed</span>`, extracted: `<span class="badge plain">Read</span>` }[d.status] || "";
  const c = d.course;
  return `<div class="card flat" data-doc="${d.id}" data-status="${d.status}">
    <div class="card-head" style="margin-bottom:4px"><div><strong>${esc(d.title)}</strong> <span class="badge plain">${esc(KINDS[d.kind] || d.kind)}</span> ${st}
      <div class="small muted">${d.pages} pages · ${d.words.toLocaleString()} words · about ${d.reading_minutes} min to read · uploaded ${fmtDate(d.uploaded_at)}</div></div>
      <div style="display:flex;gap:6px">${["handbook", "manual", "policy", "procedure"].includes(d.kind) ? `<button class="btn ghost small" data-rebuild="${d.id}">Rebuild course</button>` : ""}
        <button class="btn ghost small" data-del="${d.id}">Delete</button></div></div>
    ${d.error ? `<p class="small" style="color:var(--bad)">${esc(d.error)}</p>` : ""}
    ${c ? `<details><summary class="small"><strong>${esc(c.code)}: ${c.modules.length} modules</strong>, ${c.scenarios} interview scenarios, ${ASSESS[c.assessment_type]} assessment,
        about ${c.duration_minutes} min instead of ${d.reading_minutes} min of reading ${d.generated_by === "offline" ? "· offline build" : ""}</summary>
      <ol class="small">${c.modules.map((m) => `<li><strong>${esc(m.title)}</strong> <span class="muted">pages ${m.pages}</span>
        ${m.key_points?.length ? `<div class="muted">${esc(m.key_points[0])}</div>` : ""}</li>`).join("")}</ol></details>` : ""}
  </div>`;
}

function wireDocs(view, role) {
  $$("[data-rebuild]").forEach((b) => b.addEventListener("click", async () => { await api.post(`/api/manager/documents/${b.dataset.rebuild}/build`); toast("Rebuilding…"); roleDetail(view, role); }));
  $$("[data-del]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Delete this document and the course built from it?")) return;
    try { await api.del(`/api/manager/documents/${b.dataset.del}`); toast("Deleted"); roleDetail(view, role); } catch (e) { toast(e.message, true); }
  }));
  // Poll while a course is being built.
  if ($$('[data-status="generating"]').length) {
    setTimeout(async () => {
      if (!document.body.contains($("#docs"))) return;
      const docs = await api.get(`/api/manager/documents?position_code=${encodeURIComponent(role.code)}`);
      const wasGenerating = $$('[data-status="generating"]').length;
      $("#docs").innerHTML = docs.map(docCard).join("");
      wireDocs(view, role);
      if (wasGenerating && !docs.some((d) => d.status === "generating")) { toast("Course ready"); roleDetail(view, role); }
    }, 3000);
  }
}

function renderPlan() {
  const box = $("#plan");
  const sorted = [...plan].sort((a, b) => a.phase - b.phase);
  box.innerHTML = plan.length ? `<div class="table-wrap"><table><thead><tr><th>When</th><th>Training</th><th title="${ASSESS_HELP}">Assessed by</th><th>For</th><th>Required</th><th>Skip if years ≥</th><th>Why</th><th></th></tr></thead>
    <tbody>${sorted.map((i) => `<tr data-code="${esc(i.training_code)}">
      <td><select data-f="phase">${Object.entries(PHASES).map(([k, v]) => `<option value="${k}" ${+k === +i.phase ? "selected" : ""}>${v}</option>`).join("")}</select></td>
      <td style="min-width:240px"><strong>${esc(i.title)}</strong><div class="small muted">${esc(i.training_code)} · ${CATEGORY_LABEL[i.category] || i.category || ""}${i.from_document ? " · from documents" : ""}</div></td>
      <td><select data-assess title="${ASSESS_HELP}">${Object.entries(ASSESS).map(([k, v]) => `<option value="${k}" ${k === (i.assessment_type || "quiz") ? "selected" : ""}>${v}</option>`).join("")}</select></td>
      <td><select data-f="audience">${Object.entries(AUDIENCE).map(([k, v]) => `<option value="${k}" ${k === i.audience ? "selected" : ""}>${v}</option>`).join("")}</select></td>
      <td><input type="checkbox" data-f="required" ${i.required ? "checked" : ""}></td>
      <td><input type="number" min="0" step="1" style="width:70px" data-f="skip_if_years_at_least" value="${i.skip_if_years_at_least ?? ""}"></td>
      <td class="small"><input data-f="reason" value="${esc(i.reason || "")}" style="width:100%;min-width:160px"></td>
      <td><button class="btn ghost small" data-remove>Remove</button></td></tr>`).join("")}</tbody></table></div>`
    : `<p class="muted">No trainings in the plan yet.</p>`;
  $$("tr[data-code]", box).forEach((tr) => {
    const item = plan.find((i) => i.training_code === tr.dataset.code);
    $$("[data-f]", tr).forEach((el) => el.addEventListener("change", () => {
      const f = el.dataset.f;
      item[f] = f === "required" ? el.checked : f === "phase" ? Number(el.value) : f === "skip_if_years_at_least" ? (el.value === "" ? null : Number(el.value)) : el.value;
      if (f === "phase") renderPlan();
    }));
    $("[data-remove]", tr).onclick = () => { plan = plan.filter((i) => i !== item); renderPlan(); };
    $("[data-assess]", tr).addEventListener("change", async (e) => {
      // Applies to the training everywhere, right away (not only when the plan is saved).
      try {
        await api.patch(`/api/manager/trainings/${encodeURIComponent(item.training_code)}/assessment`, { assessment_type: e.target.value });
        item.assessment_type = e.target.value;
        toast(`${item.title} is now assessed by ${ASSESS[e.target.value].toLowerCase()}`);
      } catch (err) { toast(err.message, true); e.target.value = item.assessment_type; }
    });
  });
}

function roleForm(view, role) {
  const r = role || { title: "", division_code: "", level: 1, min_years: 0, required_skills: [], prerequisites: [], is_open: true, headcount: 1 };
  const m = modal(`
    <div class="modal-head"><h2>${role ? "Edit role" : "New role"}</h2><button class="btn ghost" data-close>Cancel</button></div>
    <form id="rf" class="grid cols-2">
      <label class="field">Title<input name="title" required value="${esc(r.title)}"></label>
      <label class="field">Division code<input name="division_code" required value="${esc(r.division_code)}" placeholder="e.g. CCS"></label>
      <label class="field">Level<input name="level" type="number" min="1" max="6" value="${r.level}"></label>
      <label class="field">Minimum years<input name="min_years" type="number" min="0" step="0.5" value="${r.min_years}"></label>
      <label class="field" style="grid-column:1/-1">Required skills (comma separated)<input name="required_skills" value="${esc((r.required_skills || []).join(", "))}"></label>
      <label class="field" style="grid-column:1/-1">Prerequisites (semicolon separated)<input name="prerequisites" value="${esc((r.prerequisites || []).join("; "))}"></label>
      <label class="field">Open positions<input name="headcount" type="number" min="0" value="${r.headcount}"></label>
      <label class="field">Hiring now<select name="is_open"><option value="true" ${r.is_open ? "selected" : ""}>Yes</option><option value="false" ${!r.is_open ? "selected" : ""}>No</option></select></label>
      <div><button class="btn">${role ? "Save" : "Create role"}</button></div>
    </form>`);
  $("#rf", m.root).onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = { title: f.get("title"), division_code: f.get("division_code"), level: Number(f.get("level")), min_years: Number(f.get("min_years")),
      required_skills: String(f.get("required_skills")).split(",").map((s) => s.trim()).filter(Boolean),
      prerequisites: String(f.get("prerequisites")).split(";").map((s) => s.trim()).filter(Boolean),
      headcount: Number(f.get("headcount")), is_open: f.get("is_open") === "true" };
    try {
      const saved = role ? await api.patch(`/api/manager/roles/${encodeURIComponent(role.code)}`, body) : await api.post("/api/manager/roles", body);
      current = saved.code; m.close(); toast(role ? "Saved" : "Role created. Upload its job description next."); rolesView(view);
    } catch (err) { toast(err.message, true); }
  };
}

// ---- start people in a role ------------------------------------------------------

async function startModal(view, role) {
  const team = await api.get("/api/manager/team?lite=true&page_size=40");
  const picked = new Map(); // id -> {name, title}
  const m = modal(`
    <div class="modal-head"><h2>Start people in ${esc(role.title)}</h2><button class="btn ghost" data-close>Cancel</button></div>
    <p class="small muted">Pick a new hire, someone being promoted, or someone transferring. Their plan is tailored automatically; you can adjust it before confirming.</p>
    <div class="grid cols-2">
      <div>
        <label class="field">Find anyone at LANL<input id="s-q" placeholder="Name, email or Z number"></label>
        <div class="list" id="s-results" style="max-height:300px;overflow-y:auto;margin-top:6px">${team.slice(0, 40).map((p) => personRow(p)).join("")}</div>
      </div>
      <div>
        <h4>Selected</h4><div class="list" id="s-picked"><p class="muted small">Nobody yet.</p></div>
        <label class="field" style="margin-top:8px">Start date<input type="date" id="s-date" value="${new Date().toISOString().slice(0, 10)}"></label>
        <button class="btn" id="s-preview" style="margin-top:8px">Preview their plans</button>
      </div>
    </div>
    <div id="s-out" style="margin-top:12px"></div>`, { wide: true });
  const renderPicked = () => {
    $("#s-picked", m.root).innerHTML = [...picked.entries()].map(([id, p]) => `<div class="item small"><div class="grow"><strong>${esc(p.name)}</strong><div class="muted">${esc(p.job_title)} · L${p.level}</div></div>
      <button class="btn ghost small" data-unpick="${id}">Remove</button></div>`).join("") || `<p class="muted small">Nobody yet.</p>`;
    $$("[data-unpick]", m.root).forEach((b) => (b.onclick = () => { picked.delete(Number(b.dataset.unpick)); renderPicked(); }));
  };
  const wirePick = () => $$("[data-pick]", m.root).forEach((b) => (b.onclick = () => { const p = JSON.parse(b.dataset.person); picked.set(p.id, p); renderPicked(); }));
  wirePick();
  let timer;
  $("#s-q", m.root).addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = e.target.value.trim();
      const rows = q.length < 2 ? team.slice(0, 40) : await api.get(`/api/manager/people/search?q=${encodeURIComponent(q)}`);
      $("#s-results", m.root).innerHTML = rows.map(personRow).join("") || `<p class="muted small">No matches.</p>`;
      wirePick();
    }, 250);
  });
  $("#s-preview", m.root).onclick = () => previewPlans(m, view, role, picked);
}

function personRow(p) {
  const data = esc(JSON.stringify({ id: p.id, name: p.name, job_title: p.job_title, level: p.level }));
  return `<button class="item small" data-pick data-person="${data}" style="text-align:left;cursor:pointer;font:inherit"><div class="grow"><strong>${esc(p.name)}</strong>
    <div class="muted">${esc(p.job_title)} · L${p.level} · ${esc(p.division_code)}${p.is_new_hire ? " · new hire" : ""}${p.on_team === false ? " · other team" : ""}</div></div><span class="badge">Add</span></button>`;
}

async function previewPlans(m, view, role, picked, entryPaths = {}) {
  if (!picked.size) return toast("Pick at least one person", true);
  const out = $("#s-out", m.root);
  loading(out, "Tailoring plans…");
  const body = { employee_ids: [...picked.keys()], entry_paths: entryPaths, start_date: $("#s-date", m.root).value || null };
  const previews = await api.post(`/api/manager/roles/${encodeURIComponent(role.code)}/preview`, body);
  out.innerHTML = previews.map((p) => `
    <section class="card flat" style="margin-bottom:10px" data-emp="${p.employee_id}">
      <div class="card-head"><div><h3>${esc(p.name)}</h3><div class="small muted">Now: ${esc(p.current_title)} · L${p.current_level} · ${p.years_experience} years</div></div>
        <label class="field">Entering as<select data-entry>${Object.entries(ENTRY).map(([k, v]) => `<option value="${k}" ${k === p.entry_path ? "selected" : ""}>${v}${k === p.detected_entry_path ? " (detected)" : ""}</option>`).join("")}</select></label></div>
      ${p.warnings.length ? `<div class="chips" style="margin-bottom:6px">${p.warnings.map((w) => `<span class="badge warn">${esc(w)}</span>`).join("")}</div>` : ""}
      <table><thead><tr><th></th><th>When</th><th>Training</th><th>Why</th><th>Due</th></tr></thead><tbody>
      ${p.items.map((i) => `<tr style="${i.include ? "" : "opacity:.6"}"><td><input type="checkbox" data-code="${esc(i.training_code)}" data-default="${i.include}" ${i.include ? "checked" : ""}></td>
        <td class="small">${esc(i.phase_label)}</td><td><strong>${esc(i.title)}</strong> <span class="badge plain">${ASSESS[i.assessment_type] || "Quiz"}</span></td>
        <td class="small">${i.include ? "" : "Skipped: "}${esc(i.why)}</td><td class="small">${i.include ? fmtDate(i.due_date) : ""}</td></tr>`).join("")}
      </tbody></table>
      <div class="small muted">${p.items.filter((i) => i.include).length} assigned, ${p.items.filter((i) => !i.include).length} skipped</div>
    </section>`).join("") + `<button class="btn" id="s-go">Confirm and assign</button>`;
  $$("[data-entry]", out).forEach((sel) => sel.addEventListener("change", () => {
    const paths = Object.fromEntries($$("[data-emp]", out).map((c) => [c.dataset.emp, $("[data-entry]", c).value]));
    previewPlans(m, view, role, picked, paths);
  }));
  $("#s-go", out).onclick = async () => {
    const payload = { ...body, entry_paths: {}, exclude: {}, include: {} };
    $$("[data-emp]", out).forEach((c) => {
      const id = c.dataset.emp;
      payload.entry_paths[id] = $("[data-entry]", c).value;
      payload.exclude[id] = $$("[data-code]", c).filter((x) => x.dataset.default === "true" && !x.checked).map((x) => x.dataset.code);
      payload.include[id] = $$("[data-code]", c).filter((x) => x.dataset.default === "false" && x.checked).map((x) => x.dataset.code);
    });
    try {
      const r = await api.post(`/api/manager/roles/${encodeURIComponent(role.code)}/start`, payload);
      toast(r.map((x) => `${x.name}: ${x.assigned.length} assigned`).join(" · "));
      m.close();
    } catch (e) { toast(e.message, true); }
  };
}

// ---- interview review -------------------------------------------------------------

export async function interviewsView(view, openPerson) {
  loading(view);
  const rows = await api.get("/api/manager/interviews");
  const pass = 5.5;
  view.innerHTML = `
    <div class="card-head"><h1>Interview reviews</h1><span class="muted small">Scenario-based assessments, scored 1–9 like CASPer. Pass mark ${pass}.</span></div>
    <p class="muted">The AI scores each answer against a rubric. Listen to or read the answers, then confirm or change the score; your score is the one that counts.</p>
    ${rows.length ? `<section class="card table-wrap" style="padding:0"><table><thead><tr><th>Person</th><th>Training</th><th>Submitted</th><th>AI score</th><th>Your score</th><th>Readiness</th><th>Status</th></tr></thead>
      <tbody>${rows.map((r) => `<tr class="clickable" data-s="${r.id}"><td><strong>${esc(r.name)}</strong><div class="small muted">${esc(r.job_title)}</div></td>
        <td>${esc(r.training_title)}</td><td class="small">${fmtDate(r.submitted_at)}</td>
        <td class="num">${r.overall ?? "—"}${r.scored_by === "offline" ? ` <span class="badge plain">offline</span>` : ""}</td>
        <td class="num">${r.manager_overall ?? "—"}</td>
        <td>${r.readiness ? `<span class="badge ${{ ready: "ok", ready_with_support: "warn", not_ready: "bad" }[r.readiness]}">${esc(r.readiness_detail?.label || r.readiness)}</span>
          <span class="small muted num">${Math.round(r.readiness_score)}</span>` : "—"}</td>
        <td>${r.status === "reviewed" ? `<span class="badge ok">Reviewed</span>` : `<span class="badge warn">Needs review</span>`}
          ${r.final != null ? (r.final >= pass ? `<span class="badge ok">Pass</span>` : `<span class="badge bad">Below pass</span>`) : ""}</td></tr>`).join("")}</tbody></table></section>`
      : `<div class="card empty">No interview assessments submitted yet.</div>`}`;
  $$("[data-s]").forEach((tr) => tr.addEventListener("click", () => reviewModal(view, Number(tr.dataset.s))));
}

async function reviewModal(view, id) {
  const m = modal(`<div class="empty"><span class="spinner"></span> Loading…</div>`, { wide: true });
  const s = await api.get(`/api/manager/interviews/${id}`);
  m.root.innerHTML = `
    <div class="modal-head"><div><h2>${esc(s.name)} · ${esc(s.training_title)}</h2>
      <div class="small muted">Submitted ${fmtDate(s.submitted_at)} · AI score ${s.overall ?? "—"} / 9 (${esc(s.scored_by)})</div></div><button class="btn ghost" data-close>Close</button></div>
    ${readinessCard(s.readiness_detail, s.readiness, s.readiness_score)}
    ${s.scenarios.map((sc) => `
      <section class="card flat" style="margin-bottom:10px">
        <h3>${esc(sc.title)}</h3><p class="small">${esc(sc.situation)}</p>
        ${sc.questions.map((q, qi) => { const r = sc.responses.find((x) => x.question_index === qi); return `
          <div style="border-top:1px solid var(--border);padding-top:8px;margin-top:8px">
            <div class="small"><strong>Q${qi + 1}. ${esc(q)}</strong></div>
            ${r ? `<div class="small muted">${r.mode === "audio" ? "Spoken" : "Typed"} · ${r.seconds_used}s · AI score <strong>${r.score ?? "—"}</strong></div>
              ${r.has_audio ? `<audio controls data-audio="${r.id}" style="width:100%;margin:4px 0"></audio>` : ""}
              <blockquote class="small" style="margin:4px 0;padding:6px 10px;background:var(--navy-tint);border-radius:6px;white-space:pre-wrap">${esc(r.transcript || "(no transcript)")}</blockquote>
              <div class="small"><em>${esc(r.feedback || "")}</em></div>` : `<div class="small muted">Not answered</div>`}
          </div>`; }).join("")}
        <details style="margin-top:8px"><summary class="small">Rubric</summary>
          <div class="grid cols-2 small"><div><strong>A strong answer considers</strong><ul>${sc.strong_response.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
          <div><strong>Red flags</strong><ul>${sc.red_flags.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div></div></details>
      </section>`).join("")}
    <form id="rv" class="card flat" style="background:var(--navy-tint)">
      <h3>Your review</h3>
      <div class="toolbar"><label class="field">Overall score (1–9)<input name="overall" type="number" min="1" max="9" step="0.5" value="${s.manager_overall ?? s.overall ?? ""}"></label>
        <label class="field" style="flex:1">Notes for ${esc(s.name.split(" ")[0])}<input name="notes" value="${esc(s.manager_notes || "")}"></label>
        <button class="btn">Save review</button></div>
      <p class="small muted">Readiness is recalculated from your score when you save.</p>
    </form>`;
  $$("[data-audio]", m.root).forEach(async (el) => { try { el.src = await api.blobUrl(`/api/manager/interviews/responses/${el.dataset.audio}/audio`); } catch { el.replaceWith("Recording unavailable"); } });
  $("#rv", m.root).onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await api.post(`/api/manager/interviews/${id}/review`, { overall: f.get("overall") ? Number(f.get("overall")) : null, notes: f.get("notes") });
      toast("Review saved"); m.close(); interviewsView(view);
    } catch (err) { toast(err.message, true); }
  };
}
