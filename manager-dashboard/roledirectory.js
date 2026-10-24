// Role directory: one page per role with its job description, skills and the exact trainings to assign.
// A manager opens the role they hired someone into (or are promoting someone to) and gets a clean list.
import { api, esc, $, $$, toast, modal, loading, CATEGORY_LABEL } from "/shared/api.js?v=20261025a";

const LAYER = { institutional: "Institutional", division: "Division", role: "Role" };
const LAYER_HINT = {
  institutional: "Everyone at LANL completes these.",
  division: "Required by the division.",
  role: "Technical and soft skills for this role.",
};
const ASSESS = { quiz: "Quiz", situational: "Interview", both: "Quiz + interview" };
const PATHS = { new_hire: "New hire", promotion: "Promotion within the division", transfer: "Moving from another division" };

const state = { roles: null, programs: null, q: "", program: "", key: null, detailProgram: null, entry: "new_hire", fromProgram: null };

export async function roleDirectoryView(view) {
  if (state.key) return roleDetail(view);
  loading(view, "Loading roles…");
  if (!state.roles) {
    const [roles, lib] = await Promise.all([api.get("/api/library/roles"), api.get("/api/library")]);
    state.roles = roles;
    state.programs = Object.fromEntries(lib.programs.map((p) => [p.key, p.name]));
  }
  const q = state.q.toLowerCase();
  const shown = state.roles.filter((r) => (!state.program || r.programs.includes(state.program))
    && (!q || [r.title, r.family, r.description, ...(r.skills || [])].join(" ").toLowerCase().includes(q)));
  const families = [...new Set(shown.map((r) => r.family || "Other"))];
  view.innerHTML = `
    <div class="page-head"><div><h1>Role directory</h1>
      <p class="muted">Open the role someone was hired into or promoted to. You get its job description, the skills it needs and a clean list of every training to assign.</p></div></div>
    <div class="toolbar">
      <label class="field grow">Search roles or skills<input id="rd-q" value="${esc(state.q)}" placeholder="e.g. engineer, lockout/tagout"></label>
      <div class="chips" role="tablist" aria-label="Division">
        ${[["", "All divisions"], ...Object.entries(state.programs)].map(([k, v]) => `<button class="chip ${state.program === k ? "active" : ""}" role="tab"
          aria-selected="${state.program === k}" data-prog="${k}">${esc(v)}</button>`).join("")}
      </div>
    </div>
    ${families.map((f) => `<h2 class="small muted" style="margin:18px 0 8px;text-transform:uppercase;letter-spacing:.04em">${esc(f)}</h2>
      <div class="grid cols-3">${shown.filter((r) => (r.family || "Other") === f).map((r) => `
        <button class="card clickable" data-role="${esc(r.key)}" style="text-align:left;font:inherit;cursor:pointer">
          <h3 style="margin:0 0 4px">${esc(r.title)}</h3>
          <p class="small muted" style="margin:0 0 8px">${esc(r.description)}</p>
          <div class="chips">${r.programs.map((p) => `<span class="badge plain">${esc(state.programs[p] || p)}</span>`).join("")}</div>
          <p class="small" style="margin:8px 0 0">${r.requirements.length} role trainings · ${(r.skills || []).length} skills</p>
        </button>`).join("")}</div>`).join("") || `<p class="muted">No roles match.</p>`}`;
  const input = $("#rd-q", view);
  input.addEventListener("input", () => {
    clearTimeout(input._t);
    input._t = setTimeout(() => { state.q = input.value; roleDirectoryView(view).then(() => { const i = $("#rd-q", view); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 200);
  });
  $$("[data-prog]", view).forEach((b) => b.addEventListener("click", () => { state.program = b.dataset.prog; roleDirectoryView(view); }));
  $$("[data-role]", view).forEach((b) => b.addEventListener("click", () => {
    state.key = b.dataset.role;
    state.detailProgram = state.program || null;
    state.entry = "new_hire";
    state.fromProgram = null;
    roleDirectoryView(view);
    window.scrollTo(0, 0);
  }));
}

async function roleDetail(view) {
  loading(view, "Loading role…");
  const qs = state.detailProgram ? `?program=${state.detailProgram}` : "";
  const r = await api.get(`/api/library/roles/${encodeURIComponent(state.key)}/detail${qs}`);
  state.detailProgram = r.program;
  const names = r.program_names;
  const others = r.programs.length > 1 ? r.programs.filter((p) => p !== r.program) : Object.keys(names).filter((p) => p !== r.program);
  if (!state.fromProgram || state.fromProgram === r.program) state.fromProgram = others[0] || null;
  let path = r.paths[state.entry];
  if (state.entry === "transfer" && state.fromProgram) {
    path = await api.post("/api/library/path", { program: r.program, role_key: r.key, entry_path: "transfer", from_program: state.fromProgram });
  }
  const included = path.items.filter((i) => i.include);
  const skipped = path.items.filter((i) => !i.include);
  const minutes = included.reduce((s, i) => s + (i.duration_minutes || 0), 0);

  view.innerHTML = `
    <p><button class="btn ghost small" id="rd-back">← All roles</button></p>
    <div class="page-head"><div><div class="small muted">${esc(r.family)}</div><h1>${esc(r.title)}</h1>
      <p class="muted">${esc(r.description)}</p></div>
      ${r.can_edit ? `<button class="btn secondary" id="rd-edit">Edit job description &amp; skills</button>` : ""}</div>
    <div class="chips" role="tablist" aria-label="Division" style="margin-bottom:14px">
      ${r.programs.map((p) => `<button class="chip ${p === r.program ? "active" : ""}" role="tab" aria-selected="${p === r.program}" data-dprog="${p}">${esc(names[p] || p)}</button>`).join("")}
    </div>

    <div class="grid cols-2">
      <section class="card">
        <h2>Job description</h2>
        ${r.job_description ? `<div class="small" style="white-space:pre-wrap">${esc(r.job_description)}</div>`
          : `<p class="small muted">No full job description yet.${r.can_edit ? " Use “Edit job description & skills” to add one." : " An admin can add one."}</p>`}
        ${r.job_descriptions.length ? `<h3 class="small" style="margin-top:12px">Job description files</h3><div class="list">${r.job_descriptions.map((d) => `
          <div class="item small"><div class="grow"><strong>${esc(d.title)}</strong><div class="muted">${esc(d.position_code)} · ${d.pages} pages</div></div>
            <button class="btn ghost small" data-open-doc="${d.id}">Open</button></div>`).join("")}</div>` : ""}
        ${r.positions.length ? `<h3 class="small" style="margin-top:12px">Positions using this role in ${esc(names[r.program] || "")}</h3>
          <div class="list">${r.positions.map((p) => `<div class="item small"><div class="grow"><strong>${esc(p.title)}</strong>
            <div class="muted">${esc(p.code)} · ${esc(p.division_code)} · Level ${p.level}${p.min_years ? ` · ${p.min_years}+ years` : ""}${p.is_open ? " · open" : ""}</div>
            ${p.prerequisites?.length ? `<div class="muted">Needs: ${p.prerequisites.map(esc).join("; ")}</div>` : ""}</div></div>`).join("")}</div>` : ""}
      </section>
      <section class="card">
        <h2>Skills needed</h2>
        ${r.skills.length ? `<div class="chips">${r.skills.map((s) => `<span class="badge plain" title="From: ${esc(s.from.join(", "))}">${esc(s.skill)}</span>`).join("")}</div>`
          : `<p class="small muted">No skills listed yet.</p>`}
        <p class="small muted" style="margin-top:10px">Skills come from the role, its positions and its trainings. Hover a skill to see where it comes from.</p>
      </section>
    </div>

    <section class="card" style="margin-top:16px" id="rd-list">
      <div class="card-head" style="flex-wrap:wrap;gap:10px">
        <div><h2 style="margin:0">Trainings to assign</h2>
          <div class="small muted">${included.length} trainings${minutes ? ` · about ${Math.round(minutes / 60)} hours` : ""} ·
            ${["institutional", "division", "role"].map((k) => `${path.by_layer[k]} ${LAYER[k].toLowerCase()}`).join(", ")}</div></div>
        <div class="toolbar" style="margin:0">
          <label class="field">Who are you assigning?<select id="rd-entry">${Object.entries(PATHS).map(([k, v]) => `<option value="${k}" ${state.entry === k ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
          ${state.entry === "transfer" ? `<label class="field">Coming from<select id="rd-from">${others.map((p) => `<option value="${p}" ${state.fromProgram === p ? "selected" : ""}>${esc(names[p] || p)}</option>`).join("")}</select></label>` : ""}
        </div>
      </div>
      <p class="small">${state.entry === "new_hire" ? "New to LANL: institutional onboarding, the division's trainings and the role's trainings."
        : state.entry === "promotion" ? `Already in ${esc(names[r.program] || "the division")}: only the new role's trainings. Institutional and division trainings are already done and renew on their own cycle.`
        : `Moving in from ${esc(names[state.fromProgram] || "another division")}: ${esc(names[r.program] || "this division")}'s trainings plus the role's trainings.`}</p>
      ${["institutional", "division", "role"].map((layer) => {
        const rows = included.filter((i) => i.layer === layer);
        if (!rows.length) return "";
        return `<h3 style="margin:16px 0 4px">${LAYER[layer]} <span class="small muted">· ${LAYER_HINT[layer]}</span></h3>
          <div class="table-wrap"><table><thead><tr><th class="no-print"><span class="sr-only">Include</span></th><th>When</th><th>Training</th><th>Type</th><th>Assessed by</th><th>Length</th></tr></thead>
          <tbody>${rows.map((i) => `<tr>
            <td class="no-print"><input type="checkbox" data-inc="${esc(i.training_code)}" checked aria-label="Include ${esc(i.title)}"></td>
            <td class="small">${esc(i.phase_label)}</td>
            <td><strong>${esc(i.title)}</strong><div class="small muted">${esc(i.course_number ? "Course " + i.course_number : i.training_code)}${i.reason ? ` · ${esc(i.reason)}` : ""}</div></td>
            <td class="small">${i.kind === "soft" ? "Soft skill" : i.kind === "technical" ? "Technical" : esc(CATEGORY_LABEL[i.category] || (i.category ? i.category[0].toUpperCase() + i.category.slice(1) : ""))}</td>
            <td class="small">${esc(ASSESS[i.assessment_type] || "")}</td>
            <td class="small">${i.duration_minutes ? `${i.duration_minutes} min` : ""}</td></tr>`).join("")}</tbody></table></div>`;
      }).join("")}
      ${skipped.length ? `<details style="margin-top:12px"><summary class="small">Not needed for this path (${skipped.length})</summary>
        <ul class="small">${skipped.map((i) => `<li>${esc(i.title)} <span class="muted">· ${esc(i.why)}</span></li>`).join("")}</ul></details>` : ""}
      <div class="toolbar no-print" style="margin-top:14px">
        <button class="btn" id="rd-assign">Assign to people…</button>
        <button class="btn secondary" id="rd-copy">Copy list</button>
        <button class="btn ghost" id="rd-print">Print</button>
      </div>
    </section>`;

  const chosen = () => included.filter((i) => $(`[data-inc="${CSS.escape(i.training_code)}"]`, view)?.checked);
  $("#rd-back", view).onclick = () => { state.key = null; roleDirectoryView(view); };
  $$("[data-dprog]", view).forEach((b) => b.addEventListener("click", () => { state.detailProgram = b.dataset.dprog; state.fromProgram = null; roleDetail(view); }));
  $("#rd-entry", view).onchange = (e) => { state.entry = e.target.value; roleDetail(view); };
  $("#rd-from", view)?.addEventListener("change", (e) => { state.fromProgram = e.target.value; roleDetail(view); });
  $$("[data-open-doc]", view).forEach((b) => b.addEventListener("click", async () => {
    try { window.open(await api.blobUrl(`/api/documents/${b.dataset.openDoc}/file`), "_blank"); } catch (err) { toast(err.message, true); }
  }));
  $("#rd-print", view).onclick = () => window.print();
  $("#rd-copy", view).onclick = async () => {
    const lines = [`${r.title} · ${names[r.program] || ""} · ${PATHS[state.entry]}`, ""];
    for (const layer of ["institutional", "division", "role"]) {
      const rows = chosen().filter((i) => i.layer === layer);
      if (!rows.length) continue;
      lines.push(`${LAYER[layer]}:`, ...rows.map((i) => `- ${i.title} (${i.course_number ? "Course " + i.course_number : i.training_code}) · ${i.phase_label}`), "");
    }
    try { await navigator.clipboard.writeText(lines.join("\n")); toast("Copied the training list"); } catch { toast("Couldn't copy. Use Print instead.", true); }
  };
  $("#rd-assign", view).onclick = () => assignModal(view, r, chosen(), included);
  $("#rd-edit", view)?.addEventListener("click", () => editRole(view, r));
}

async function assignModal(view, r, chosen, included) {
  if (!chosen.length) return toast("Tick at least one training", true);
  const exclude = included.filter((i) => !chosen.includes(i)).map((i) => i.training_code);
  const team = await api.get("/api/manager/team?lite=true&page_size=40").catch(() => []);
  const picked = new Map();
  const person = (p) => `<button class="item small" data-pick="${esc(JSON.stringify({ id: p.id, name: p.name, job_title: p.job_title }))}" style="text-align:left;cursor:pointer;font:inherit">
    <div class="grow"><strong>${esc(p.name)}</strong><div class="muted">${esc(p.job_title || "")} · ${esc(p.division_code || "")}${p.on_team === false ? " · other team" : ""}</div></div><span class="badge">Add</span></button>`;
  const m = modal(`
    <div class="modal-head"><h2>Assign ${chosen.length} trainings</h2><button class="btn ghost" data-close>Cancel</button></div>
    <p class="small muted">${esc(r.title)} · ${esc(r.program_names[r.program] || "")} · ${esc(PATHS[state.entry])}. Anything they already have open is left as it is.</p>
    <div class="grid cols-2">
      <div><label class="field">Find anyone at LANL<input id="as-q" placeholder="Name, email or Z number"></label>
        <div class="list" id="as-results" style="max-height:280px;overflow-y:auto;margin-top:6px">${(Array.isArray(team) ? team : team.items || []).map(person).join("")}</div></div>
      <div><h3 class="small">Selected</h3><div class="list" id="as-picked"><p class="muted small">Nobody yet.</p></div>
        <label class="field" style="margin-top:8px">Start date<input type="date" id="as-date" value="${new Date().toISOString().slice(0, 10)}"></label>
        ${r.positions.length ? `<label class="field">Also move them into position<select id="as-pos"><option value="">Don't change their position</option>
          ${r.positions.map((p) => `<option value="${esc(p.code)}">${esc(p.title)} (${esc(p.code)})</option>`).join("")}</select></label>` : ""}
        <button class="btn" id="as-go" style="margin-top:10px">Assign</button></div>
    </div><div id="as-out" style="margin-top:10px"></div>`, { wide: true });
  const renderPicked = () => {
    $("#as-picked", m.root).innerHTML = [...picked.values()].map((p) => `<div class="item small"><div class="grow"><strong>${esc(p.name)}</strong>
      <div class="muted">${esc(p.job_title || "")}</div></div><button class="btn ghost small" data-unpick="${p.id}">Remove</button></div>`).join("") || `<p class="muted small">Nobody yet.</p>`;
    $$("[data-unpick]", m.root).forEach((b) => (b.onclick = () => { picked.delete(Number(b.dataset.unpick)); renderPicked(); }));
  };
  const wire = () => $$("[data-pick]", m.root).forEach((b) => (b.onclick = () => { const p = JSON.parse(b.dataset.pick); picked.set(p.id, p); renderPicked(); }));
  wire();
  let timer;
  $("#as-q", m.root).addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = e.target.value.trim();
      if (q.length < 2) return;
      const rows = await api.get(`/api/manager/people/search?q=${encodeURIComponent(q)}`);
      $("#as-results", m.root).innerHTML = rows.map(person).join("") || `<p class="muted small">No matches.</p>`;
      wire();
    }, 250);
  });
  $("#as-go", m.root).onclick = async () => {
    if (!picked.size) return toast("Pick at least one person", true);
    try {
      const out = await api.post(`/api/library/roles/${encodeURIComponent(r.key)}/assign`, {
        program: r.program, entry_path: state.entry, from_program: state.entry === "transfer" ? state.fromProgram : null,
        employee_ids: [...picked.keys()], start_date: $("#as-date", m.root).value || null, exclude,
        position_code: $("#as-pos", m.root)?.value || null,
      });
      $("#as-out", m.root).innerHTML = `<div class="list">${out.people.map((p) => `<div class="item small"><div class="grow"><strong>${esc(p.name)}</strong>
        <div class="muted">${p.assigned.length} assigned${p.already_assigned.length ? ` · ${p.already_assigned.length} already open` : ""}</div></div><span class="badge ok">Done</span></div>`).join("")}</div>`;
      toast("Trainings assigned");
    } catch (err) { toast(err.message, true); }
  };
}

function editRole(view, r) {
  const m = modal(`
    <div class="modal-head"><h2>Edit ${esc(r.title)}</h2><button class="btn ghost" data-close>Cancel</button></div>
    <form id="er">
      <label class="field">Summary<input name="description" value="${esc(r.description)}"></label>
      <label class="field">Full job description<textarea name="job_description" rows="10" placeholder="Paste the posted job description">${esc(r.job_description)}</textarea></label>
      <label class="field">Skills (comma separated)<input name="skills" value="${esc(r.skills.filter((s) => s.from.includes("Role")).map((s) => s.skill).join(", "))}"></label>
      <button class="btn" style="margin-top:8px">Save</button>
    </form>`, { wide: true });
  $("#er", m.root).onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    try {
      await api.patch(`/api/library/roles/${encodeURIComponent(r.key)}`, {
        title: r.title, family: r.family, programs: r.programs, description: f.description,
        job_description: f.job_description, skills: f.skills.split(",").map((s) => s.trim()).filter(Boolean),
      });
      state.roles = null;
      toast("Saved"); m.close(); roleDetail(view);
    } catch (err) { toast(err.message, true); }
  };
}
