// Training library: institutional (everyone), division (Weapons, STE, Operations) and role trainings,
// with the PDFs and slide decks the AI builds lessons from. Managers browse; admins edit.
import { api, esc, $, $$, fmtDate, toast, modal, loading, CATEGORY_LABEL } from "/shared/api.js?v=20261025a";

const LAYER = { institutional: "Institutional", division: "Division", role: "Role", unassigned: "Unassigned" };
const PHASES = { 1: "First 2 weeks", 2: "First 30 days", 3: "First 90 days" };
const ENTRY = { new_hire: "New hire (new to LANL)", promotion: "Internal promotion", transfer: "Internal transfer" };
let data = null;
let tab = "institutional";
let selectedRole = null;

export async function libraryView(view) {
  loading(view, "Loading the training library…");
  data = await api.get("/api/library");
  const c = data.counts;
  const programTabs = data.programs.map((p) => [p.key, p.name]);
  view.innerHTML = `
    <div class="card-head"><h1>Training library</h1>
      ${data.can_edit ? `<div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn secondary small" id="lib-new">New training</button>
        <button class="btn secondary small" id="lib-annual">Run annual cycle</button>
        <button class="btn small" id="lib-import">Import all materials</button></div>` : ""}</div>
    <p class="muted">Every training LANL requires, organized the way UTrain assigns it: <strong>institutional</strong> (everyone),
      <strong>division</strong> (Weapons, Science, Technology &amp; Engineering, Operations) and <strong>role</strong> (technical and soft skills).
      The PDFs and slide decks attached here are what the AI uses to build personalized lessons.</p>
    <div class="grid cols-4" style="margin-bottom:12px">
      <div class="stat"><div class="label">Trainings</div><div class="value num">${c.trainings}</div></div>
      <div class="stat"><div class="label">Institutional</div><div class="value num">${c.by_layer.institutional || 0}</div></div>
      <div class="stat"><div class="label">Division + role</div><div class="value num">${(c.by_layer.division || 0) + (c.by_layer.role || 0)}</div></div>
      <div class="stat ${c.materials_ready < c.materials ? "warn" : "ok"}"><div class="label">Materials in library</div>
        <div class="value num">${c.materials_ready}<span class="small muted"> / ${c.materials}</span></div></div>
    </div>
    <details class="small muted" style="margin-bottom:12px"><summary>About this data</summary><p>${esc(data.about)}</p>
      <p>Sources: ${data.sources.map((s) => `<a href="${esc(s)}" target="_blank" rel="noopener">${esc(s)}</a>`).join(" · ")}</p></details>
    <div class="chips" role="tablist" style="margin-bottom:12px">
      ${[["institutional", "Institutional"], ...programTabs, ["roles", "Roles"], ["catalog", "Course catalog"], ["path", "Plan preview"]]
        .map(([k, v]) => `<button class="chip ${tab === k ? "active" : ""}" role="tab" aria-selected="${tab === k}" data-tab="${k}">${esc(v)}</button>`).join("")}
    </div>
    <div id="lib-body"></div>`;
  $$("[data-tab]").forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; libraryView(view); }));
  $("#lib-import")?.addEventListener("click", async () => {
    const r = await api.post("/api/library/materials/import", {});
    toast(r.queued ? `Importing ${r.queued} materials in the background…` : "Every linked material is already in the library");
    if (r.queued) setTimeout(() => libraryView(view), 6000);
  });
  $("#lib-annual")?.addEventListener("click", () => annualCycle(view));
  $("#lib-new")?.addEventListener("click", () => newTraining(view));
  const body = $("#lib-body");
  if (tab === "institutional") institutional(view, body);
  else if (tab === "roles") rolesTab(view, body);
  else if (tab === "catalog") catalog(view, body);
  else if (tab === "path") pathPreview(body);
  else division(view, body, data.programs.find((p) => p.key === tab));
}

const byCode = () => Object.fromEntries(data.trainings.map((t) => [t.code, t]));

function materialsCell(t) {
  if (!t.materials_total) return `<span class="small muted">none</span>`;
  const cls = t.materials_ready === t.materials_total ? "ok" : t.materials.some((m) => m.status === "failed") ? "bad" : "warn";
  return `<span class="badge ${cls}">${t.materials_ready}/${t.materials_total} in library</span>`;
}

function trainingRow(t, extra = "") {
  return `<tr class="clickable" data-code="${esc(t.code)}">
    <td class="num small">${esc(t.course_number || t.code)}</td>
    <td><strong>${esc(t.title)}</strong><div class="small muted">${esc(CATEGORY_LABEL[t.category] || t.category)} · ${esc(t.source_system)}</div></td>
    <td class="small">${t.audience === "new_hire" ? "New hires" : "Everyone"}</td>
    <td class="small">${t.frequency === "annual" ? `<span class="badge">Annual</span>` : "Once"}${t.refresher_of ? `<div class="muted">refresher of ${esc(t.refresher_of)}</div>` : ""}</td>
    <td>${materialsCell(t)}</td>
    <td class="small">${t.modules ? (t.lessons_status === "draft" ? `<span class="badge warn">${t.modules} modules · draft</span>`
      : `<span class="badge ok">${t.modules} modules</span>`) : `<span class="muted">not built</span>`}</td>${extra}</tr>`;
}

function wireRows(view, root) {
  $$("tr[data-code]", root).forEach((tr) => tr.addEventListener("click", (e) => {
    if (e.target.closest("button, select, input, a")) return;
    trainingDetail(view, tr.dataset.code);
  }));
}

function institutional(view, body) {
  const rows = data.trainings.filter((t) => t.layer === "institutional");
  body.innerHTML = `<section class="card">
    <div class="card-head"><h2>Institutional training</h2><span class="small muted">Required for everyone at LANL, regardless of role or experience</span></div>
    <p class="small muted">New hires take the courses marked “New hires” once during onboarding. “Annual” courses come round every year for everyone;
      people moving to a new role internally don't redo institutional training, it simply continues on their annual cycle.</p>
    <div class="table-wrap"><table><thead><tr><th>Course #</th><th>Training</th><th>Who</th><th>How often</th><th>Materials</th><th>Lessons</th></tr></thead>
    <tbody>${rows.map((t) => trainingRow(t)).join("")}</tbody></table></div></section>`;
  wireRows(view, body);
}

function division(view, body, p) {
  const tr = byCode();
  body.innerHTML = `<section class="card" style="margin-bottom:16px">
      <div class="card-head"><div><h2>${esc(p.name)}</h2><p class="small muted" style="margin:0">${esc(p.description)}</p></div></div>
      <h3>Required for everyone in ${esc(p.name)}</h3>
      <p class="small muted">Assigned to new hires and to people moving in from another division. Draft defaults: confirm with the division's training coordinator.</p>
      ${p.requirements.length ? `<div class="table-wrap"><table><thead><tr><th>When</th><th>Training</th><th>Why</th><th>Materials</th>${data.can_edit ? "<th></th>" : ""}</tr></thead>
      <tbody>${p.requirements.map((r) => { const t = tr[r.training_code] || { title: r.training_code, materials: [] }; return `<tr class="clickable" data-code="${esc(r.training_code)}">
        <td class="small">${PHASES[r.phase] || ""}</td><td><strong>${esc(t.title)}</strong><div class="small muted">${esc(r.training_code)}</div></td>
        <td class="small">${esc(r.reason)}</td><td>${t.materials_total != null ? materialsCell(t) : ""}</td>
        ${data.can_edit ? `<td><button class="btn ghost small" data-del-div="${r.id}">Remove</button></td>` : ""}</tr>`; }).join("")}</tbody></table></div>`
        : `<p class="muted">No division-wide requirements yet.</p>`}
      ${data.can_edit ? addForm("div-add", false) : ""}
    </section>
    <section class="card"><h3>Divisions in ${esc(p.name)}</h3>
      ${p.divisions.length ? `<div class="chips">${p.divisions.map((d) => `<span class="badge plain">${esc(d.code)} · ${esc(d.name)}</span>`).join("")}</div>`
        : `<p class="muted small">No divisions from the directory are mapped here yet.</p>`}
      <h3 style="margin-top:12px">Roles in ${esc(p.name)}</h3>
      <div class="chips">${data.roles.filter((r) => r.programs.includes(p.key)).map((r) => `<button class="chip" data-role-go="${esc(r.key)}">${esc(r.title)}</button>`).join("")}</div>
    </section>`;
  wireRows(view, body);
  $$("[data-del-div]", body).forEach((b) => b.addEventListener("click", async () => {
    await api.del(`/api/library/divisions/requirements/${b.dataset.delDiv}`); toast("Removed"); libraryView(view);
  }));
  $$("[data-role-go]", body).forEach((b) => b.addEventListener("click", () => { selectedRole = b.dataset.roleGo; tab = "roles"; libraryView(view); }));
  $("#div-add", body)?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await api.post(`/api/library/divisions/${p.key}/requirements`, { training_code: f.get("code"), phase: Number(f.get("phase")), reason: f.get("reason") });
      toast("Added"); libraryView(view);
    } catch (err) { toast(err.message, true); }
  });
}

function addForm(id, withKind, programs = null) {
  return `<form id="${id}" class="toolbar" style="margin-top:10px">
    <label class="field" style="flex:2;min-width:220px">Add a training<select name="code" required><option value="">Choose…</option>
      ${data.trainings.map((t) => `<option value="${esc(t.code)}">${esc(t.course_number || t.code)} · ${esc(t.title)}</option>`).join("")}</select></label>
    ${withKind ? `<label class="field">Type<select name="kind"><option value="technical">Technical</option><option value="soft">Soft skill</option></select></label>` : ""}
    ${programs ? `<label class="field">Applies in<select name="program"><option value="">Every division</option>${programs.map(([k, v]) => `<option value="${k}">${esc(v)} only</option>`).join("")}</select></label>` : ""}
    <label class="field">When<select name="phase">${Object.entries(PHASES).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
    <label class="field" style="flex:2;min-width:160px">Why<input name="reason" placeholder="Optional reason"></label>
    <button class="btn">Add</button></form>`;
}

function rolesTab(view, body) {
  const names = Object.fromEntries(data.programs.map((p) => [p.key, p.name]));
  selectedRole ||= data.roles[0]?.key;
  const role = data.roles.find((r) => r.key === selectedRole);
  const tr = byCode();
  const families = [...new Set(data.roles.map((r) => r.family))];
  const reqRow = (r) => { const t = tr[r.training_code] || { title: r.training_code }; return `<tr class="clickable" data-code="${esc(r.training_code)}">
    <td class="small">${PHASES[r.phase] || ""}</td><td><strong>${esc(t.title)}</strong><div class="small muted">${esc(r.training_code)}${r.reason ? ` · ${esc(r.reason)}` : ""}</div></td>
    <td>${t.materials_total != null ? materialsCell(t) : ""}</td>${data.can_edit ? `<td><button class="btn ghost small" data-del-role="${r.id}">Remove</button></td>` : ""}</tr>`; };
  const section = (title, rows) => `<h4 style="margin-top:12px">${title}</h4>${rows.length ? `<div class="table-wrap"><table><tbody>${rows.map(reqRow).join("")}</tbody></table></div>`
    : `<p class="small muted">None.</p>`}`;
  body.innerHTML = `<div class="grid" style="grid-template-columns:minmax(220px,280px) minmax(0,1fr)">
    <section class="card" style="align-self:start">
      ${families.map((f) => `<h4>${esc(f)}</h4><div class="list" style="margin-bottom:8px">${data.roles.filter((r) => r.family === f).map((r) => `
        <button class="item small" data-role="${esc(r.key)}" style="text-align:left;cursor:pointer;font:inherit;${r.key === selectedRole ? "border-color:var(--navy);background:var(--navy-tint)" : ""}">
          <div class="grow"><strong>${esc(r.title)}</strong><div class="muted">${r.programs.map((p) => esc(names[p] || p)).join(", ")}</div></div></button>`).join("")}</div>`).join("")}
      ${data.can_edit ? `<button class="btn secondary small" id="role-new">New role</button>` : ""}
    </section>
    <section class="card">${role ? `
      <h2>${esc(role.title)}</h2><p class="small muted">${esc(role.description)}</p>
      <p class="small"><strong>In:</strong> ${role.programs.map((p) => `<span class="badge plain">${esc(names[p] || p)}</span>`).join(" ")}
        ${role.positions.length ? `· <strong>Positions using it:</strong> ${role.positions.map((p) => `<span class="badge">${esc(p.title)} (${esc(p.code)})</span>`).join(" ")}` : ""}</p>
      <p class="small muted">Role trainings go to everyone entering the role, including internal promotions and transfers. The role is defined once and shared;
        division-specific additions apply only in that division.</p>
      ${section("Technical (every division)", role.requirements.filter((r) => !r.program && r.kind === "technical"))}
      ${section("Soft skills (every division)", role.requirements.filter((r) => !r.program && r.kind === "soft"))}
      ${role.programs.map((p) => { const rows = role.requirements.filter((r) => r.program === p); return rows.length ? section(`Only in ${esc(names[p] || p)}`, rows) : ""; }).join("")}
      ${data.can_edit ? addForm("role-add", true, role.programs.map((p) => [p, names[p] || p])) : ""}` : `<p class="muted">No roles yet.</p>`}
    </section></div>`;
  $$("[data-role]", body).forEach((b) => b.addEventListener("click", () => { selectedRole = b.dataset.role; rolesTab(view, body); }));
  wireRows(view, body);
  $$("[data-del-role]", body).forEach((b) => b.addEventListener("click", async () => {
    await api.del(`/api/library/roles/requirements/${b.dataset.delRole}`); toast("Removed"); libraryView(view);
  }));
  $("#role-add", body)?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await api.post(`/api/library/roles/${role.key}/requirements`, { training_code: f.get("code"), kind: f.get("kind"), phase: Number(f.get("phase")),
        reason: f.get("reason"), program: f.get("program") || null });
      toast("Added"); libraryView(view);
    } catch (err) { toast(err.message, true); }
  });
  $("#role-new", body)?.addEventListener("click", () => newRole(view));
}

function catalog(view, body) {
  body.innerHTML = `<section class="card">
    <div class="toolbar"><label class="field" style="flex:1">Search<input id="cat-q" placeholder="Title, course number or category"></label>
      <label class="field">Layer<select id="cat-layer"><option value="">All</option>${Object.entries(LAYER).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label></div>
    <div class="table-wrap"><table><thead><tr><th>Course #</th><th>Training</th><th>Who</th><th>How often</th><th>Materials</th><th>Lessons</th><th>Layer</th></tr></thead>
    <tbody id="cat-rows"></tbody></table></div></section>`;
  const render = () => {
    const q = $("#cat-q").value.toLowerCase(), layer = $("#cat-layer").value;
    const rows = data.trainings.filter((t) => (!layer || t.layer === layer) && `${t.title} ${t.code} ${t.course_number} ${t.category}`.toLowerCase().includes(q));
    $("#cat-rows").innerHTML = rows.map((t) => trainingRow(t, `<td><span class="badge plain">${LAYER[t.layer] || t.layer}</span></td>`)).join("");
    wireRows(view, body);
  };
  $("#cat-q").addEventListener("input", render);
  $("#cat-layer").addEventListener("change", render);
  render();
}

function pathPreview(body) {
  body.innerHTML = `<section class="card">
    <h2>What would someone get?</h2>
    <p class="small muted">Pick a division, a role and how the person is entering it. New hires get all three layers; internal moves skip institutional
      onboarding, and skip division training too when they stay in the same division.</p>
    <form id="pp" class="toolbar">
      <label class="field">Division<select name="program">${data.programs.map((p) => `<option value="${p.key}">${esc(p.name)}</option>`).join("")}</select></label>
      <label class="field">Role<select name="role"><option value="">(division only)</option>${data.roles.map((r) => `<option value="${esc(r.key)}">${esc(r.title)}</option>`).join("")}</select></label>
      <label class="field">Entering as<select name="entry">${Object.entries(ENTRY).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
      <label class="field">Coming from<select name="from"><option value="">Same division</option>${data.programs.map((p) => `<option value="${p.key}">${esc(p.name)}</option>`).join("")}</select></label>
      <button class="btn">Show plan</button></form>
    <div id="pp-out"></div></section>`;
  $("#pp").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const program = f.get("program"), entry = f.get("entry");
    const r = await api.post("/api/library/path", { program, role_key: f.get("role") || null, entry_path: entry,
      from_program: entry === "new_hire" ? null : (f.get("from") || program) });
    $("#pp-out").innerHTML = `<p><strong>${r.included} trainings</strong>: ${r.by_layer.institutional} institutional, ${r.by_layer.division} division, ${r.by_layer.role} role.</p>
      ${["institutional", "division", "role"].map((layer) => { const rows = r.items.filter((i) => i.layer === layer); return rows.length ? `
        <h3>${LAYER[layer]}</h3><table><tbody>${rows.map((i) => `<tr style="${i.include ? "" : "opacity:.6"}"><td>${i.include ? "✓" : "–"}</td>
          <td><strong>${esc(i.title)}</strong> <span class="small muted">${esc(i.course_number || i.training_code)}</span>${i.kind ? ` <span class="badge plain">${i.kind === "soft" ? "soft skill" : "technical"}</span>` : ""}</td>
          <td class="small">${i.include ? esc(i.phase_label) : ""}</td><td class="small">${i.include ? esc(i.reason) : "Skipped: " + esc(i.why)}</td></tr>`).join("")}</tbody></table>` : ""; }).join("")}`;
  });
  $("#pp").requestSubmit();
}

// ---- training detail: materials, uploads, AI lessons ----------------------------------------

async function trainingDetail(view, code) {
  const t = byCode()[code];
  if (!t) return;
  const m = modal(`
    <div class="modal-head"><div><h2>${esc(t.title)}</h2><div class="small muted">${esc(t.course_number ? "Course " + t.course_number : t.code)} ·
      ${esc(LAYER[t.layer] || t.layer)} · ${esc(t.source_system)}</div></div><button class="btn ghost" data-close>Close</button></div>
    <p>${esc(t.description || "")}</p>
    ${t.source_url ? `<p class="small">Source: <a href="${esc(t.source_url)}" target="_blank" rel="noopener">${esc(t.source_url)}</a></p>` : ""}
    ${data.can_edit ? `<form id="td-edit" class="toolbar">
      <label class="field">Layer<select name="layer">${["institutional", "division", "role"].map((k) => `<option value="${k}" ${t.layer === k ? "selected" : ""}>${LAYER[k]}</option>`).join("")}</select></label>
      <label class="field">Who<select name="audience"><option value="all" ${t.audience === "all" ? "selected" : ""}>Everyone</option><option value="new_hire" ${t.audience === "new_hire" ? "selected" : ""}>New hires only</option></select></label>
      <label class="field">How often<select name="frequency"><option value="once" ${t.frequency === "once" ? "selected" : ""}>Once</option><option value="annual" ${t.frequency === "annual" ? "selected" : ""}>Every year</option></select></label>
      <label class="field">Assessed by<select name="assessment_type">${[["quiz", "Quiz"], ["situational", "Interview"], ["both", "Quiz + interview"]].map(([k, v]) => `<option value="${k}" ${t.assessment_type === k ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <button class="btn secondary">Save</button></form>` : ""}
    <h3>Materials</h3>
    <p class="small muted">The AI builds this training's lessons, videos, quizzes and scenarios from the richest material below.</p>
    ${t.materials.length ? `<div class="list">${t.materials.map((x) => `<div class="item small"><div class="grow"><strong>${esc(x.title)}</strong>
        <span class="badge ${x.status === "failed" ? "bad" : x.document_id ? "ok" : "plain"}">${x.status === "linked" ? "not imported yet" : esc(x.status)}</span>
        <div class="muted">${esc(x.kind.toUpperCase())}${x.bytes ? ` · ${(x.bytes / 1e6).toFixed(1)} MB` : ""}${x.retrieved_at ? ` · retrieved ${fmtDate(x.retrieved_at)}` : ""}
          ${x.url ? ` · <a href="${esc(x.url)}" target="_blank" rel="noopener">original</a>` : ""}</div>${x.error ? `<div style="color:var(--bad)">${esc(x.error)}</div>` : ""}</div>
        <div class="mat-actions">
          ${x.document_id ? `<button class="btn ghost small" data-open-doc="${x.document_id}" aria-label="Open ${esc(x.title)}">Open</button>` : ""}
          ${data.can_edit ? `<button class="btn ghost small" data-rename-mat="${x.id}" data-title="${esc(x.title)}" aria-label="Rename ${esc(x.title)}">Rename</button>
            <label class="btn ghost small" aria-label="Replace the file for ${esc(x.title)}">Replace file
              <input type="file" data-replace-mat="${x.id}" accept=".pdf,.pptx,.docx,.txt,.md" hidden></label>
            ${x.url ? `<button class="btn ghost small" data-refresh-mat="${x.id}" aria-label="Download ${esc(x.title)} again from LANL">${x.document_id ? "Re-download" : "Download"}</button>` : ""}
            <button class="btn ghost small danger" data-del-mat="${x.id}" data-title="${esc(x.title)}" aria-label="Delete ${esc(x.title)}">Delete</button>` : ""}
        </div></div>`).join("")}</div>`
      : `<p class="muted small">No materials yet.</p>`}
    ${data.can_edit ? `<div class="toolbar" style="margin-top:10px">
      ${t.materials.some((x) => !x.document_id && x.kind === "pdf") ? `<button class="btn secondary small" id="td-import">Import linked PDFs</button>` : ""}
      <form id="td-up" class="toolbar" style="margin:0"><label class="field">Add a PDF, slide deck or document<input type="file" name="file" accept=".pdf,.pptx,.docx,.txt,.md" required></label>
        <button class="btn secondary small">Upload</button></form>
      <span style="flex:1"></span>
      <button class="btn small" id="td-build" ${t.materials_ready ? "" : "disabled"}>${t.modules ? "Rebuild lessons" : "Build lessons from materials"}</button></div>
      <p class="small">${!t.modules ? `<span class="muted">Lessons aren't built yet.</span>`
        : t.lessons_status === "draft" ? `<span class="badge warn">Draft</span> ${t.modules} modules built. Learners can't see them until you review and publish.
            <button class="btn small" id="td-review" style="margin-left:6px">Review &amp; publish</button>`
        : `<span class="badge ok">Published</span> ${t.modules} modules. Learners see them in the learning studio.
            <button class="btn ghost small" id="td-review">Review again</button>`}</p>` : ""}`, { wide: true });
  const refresh = async () => { m.close(); await libraryView(view); trainingDetail(view, code); };
  $("#td-edit", m.root)?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    try { await api.patch(`/api/library/trainings/${encodeURIComponent(code)}`, f); toast("Saved"); refresh(); } catch (err) { toast(err.message, true); }
  });
  $("#td-import", m.root)?.addEventListener("click", async () => {
    await api.post("/api/library/materials/import", { training_code: code }); toast("Importing…"); setTimeout(refresh, 3000);
  });
  $("#td-up", m.root)?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api.upload(`/api/library/trainings/${encodeURIComponent(code)}/materials`, new FormData(e.target)); toast("Uploaded"); refresh(); }
    catch (err) { toast(err.message, true); }
  });
  $("#td-build", m.root)?.addEventListener("click", async (e) => {
    e.target.disabled = true; e.target.textContent = "Building…";
    try { const r = await api.post(`/api/library/trainings/${encodeURIComponent(code)}/build`); toast(`Building lessons from ${r.pages} pages…`); setTimeout(refresh, 4000); }
    catch (err) { toast(err.message, true); e.target.disabled = false; }
  });
  $("#td-review", m.root)?.addEventListener("click", () => { m.close(); reviewLessons(view, code); });
  $$("[data-open-doc]", m.root).forEach((b) => b.addEventListener("click", async () => {
    try { window.open(await api.blobUrl(`/api/documents/${b.dataset.openDoc}/file`), "_blank"); } catch (err) { toast(err.message, true); }
  }));
  $$("[data-del-mat]", m.root).forEach((b) => b.addEventListener("click", async () => {
    if (!confirm(`Delete "${b.dataset.title}" from this training? Lessons already built from it stay until you rebuild.`)) return;
    try { await api.del(`/api/library/materials/${b.dataset.delMat}`); toast("Deleted"); refresh(); } catch (err) { toast(err.message, true); }
  }));
  $$("[data-rename-mat]", m.root).forEach((b) => b.addEventListener("click", async () => {
    const title = prompt("Material title", b.dataset.title);
    if (!title || title === b.dataset.title) return;
    try { await api.patch(`/api/library/materials/${b.dataset.renameMat}`, { title }); toast("Renamed"); refresh(); } catch (err) { toast(err.message, true); }
  }));
  $$("[data-replace-mat]", m.root).forEach((inp) => inp.addEventListener("change", async () => {
    if (!inp.files.length) return;
    const f = new FormData(); f.append("file", inp.files[0]);
    try { await api.upload(`/api/library/materials/${inp.dataset.replaceMat}/file`, f); toast("File replaced. Rebuild lessons to use it."); refresh(); }
    catch (err) { toast(err.message, true); }
  }));
  $$("[data-refresh-mat]", m.root).forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true; b.textContent = "Downloading…";
    try { await api.post(`/api/library/materials/${b.dataset.refreshMat}/refresh`); toast("Downloading the latest copy…"); setTimeout(refresh, 3000); }
    catch (err) { toast(err.message, true); b.disabled = false; }
  }));
}

function newTraining(view) {
  const m = modal(`<div class="modal-head"><h2>New training</h2><button class="btn ghost" data-close>Cancel</button></div>
    <form id="nt" class="grid cols-2">
      <label class="field">Code<input name="code" required placeholder="e.g. UT-12345 or WPN-201"></label>
      <label class="field">UTrain course number<input name="course_number"></label>
      <label class="field" style="grid-column:1/-1">Title<input name="title" required></label>
      <label class="field">Layer<select name="layer"><option value="institutional">Institutional (everyone)</option><option value="division">Division</option><option value="role" selected>Role</option></select></label>
      <label class="field">Category<select name="category">${["safety", "security", "ethics", "policy", "compliance", "culture", "environment", "export", "technical"].map((c) => `<option>${c}</option>`).join("")}</select></label>
      <label class="field">Who<select name="audience"><option value="all">Everyone</option><option value="new_hire">New hires only</option></select></label>
      <label class="field">How often<select name="frequency"><option value="once">Once</option><option value="annual">Every year</option></select></label>
      <label class="field" style="grid-column:1/-1">Description<input name="description"></label>
      <div><button class="btn">Create</button></div></form>`);
  $("#nt", m.root).onsubmit = async (e) => {
    e.preventDefault();
    try { const t = await api.post("/api/library/trainings", Object.fromEntries(new FormData(e.target))); m.close(); await libraryView(view); trainingDetail(view, t.code); }
    catch (err) { toast(err.message, true); }
  };
}

function newRole(view) {
  const m = modal(`<div class="modal-head"><h2>New role</h2><button class="btn ghost" data-close>Cancel</button></div>
    <form id="nr" class="grid cols-2">
      <label class="field" style="grid-column:1/-1">Title<input name="title" required placeholder="e.g. Radiological Control Technician"></label>
      <label class="field">Family<input name="family" placeholder="Leadership, Engineering, Science, Technician…"></label>
      <label class="field" style="grid-column:1/-1">Description<input name="description"></label>
      <fieldset style="grid-column:1/-1"><legend>Divisions that have this role</legend>${data.programs.map((p) => `<label><input type="checkbox" name="programs" value="${p.key}"> ${esc(p.name)}</label> `).join("")}</fieldset>
      <div><button class="btn">Create</button></div></form>`);
  $("#nr", m.root).onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const r = await api.post("/api/library/roles", { title: f.get("title"), family: f.get("family"), description: f.get("description"), programs: f.getAll("programs") });
      m.close(); selectedRole = r.key; tab = "roles"; libraryView(view);
    } catch (err) { toast(err.message, true); }
  };
}

async function annualCycle(view) {
  const due = new Date(); due.setDate(due.getDate() + 60);
  const annual = data.trainings.filter((t) => t.layer === "institutional" && t.frequency === "annual");
  const m = modal(`<div class="modal-head"><h2>Annual institutional training</h2><button class="btn ghost" data-close>Cancel</button></div>
    <p class="small muted">Assigns this year's annual courses to everyone who isn't current. Spreading due dates keeps 20,000 people from logging in on the same night.</p>
    <form id="ac" class="grid cols-2">
      <label class="field">Deadline<input type="date" name="due" value="${due.toISOString().slice(0, 10)}" required></label>
      <label class="field">Spread over<select name="weeks"><option value="0">Same day</option><option value="2">2 weeks</option><option value="4" selected>4 weeks</option><option value="8">8 weeks</option></select></label>
      <fieldset style="grid-column:1/-1"><legend>Courses</legend>${annual.map((t) => `<label style="display:block"><input type="checkbox" name="codes" value="${esc(t.code)}" checked> ${esc(t.course_number)} · ${esc(t.title)}</label>`).join("")}</fieldset>
      <div><button class="btn">Assign</button></div></form>`);
  $("#ac", m.root).onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const r = await api.post("/api/library/annual-cycle", { due_date: f.get("due"), stagger_weeks: Number(f.get("weeks")), codes: f.getAll("codes") });
    toast(`${r.assigned} assigned, ${r.reopened} reopened, ${r.already_current} already current across ${r.people} people`);
    m.close();
  };
}


/** Review built modules against their source pages, then publish them to learners (adapted from AJ's review step). */
async function reviewLessons(view, code) {
  const r = await api.get(`/api/library/trainings/${encodeURIComponent(code)}/modules`);
  const t = byCode()[code];
  const m = modal(`
    <div class="modal-head"><div><h2>Review lessons: ${esc(t.title)}</h2>
      <div class="small muted">${r.modules.length} modules · ${r.lessons_status === "draft" ? "draft, not visible to learners" : "published"}</div></div>
      <button class="btn ghost" data-close>Close</button></div>
    <p class="small muted">Check each module's key points against the source pages. Generated content can be wrong; publishing makes it visible to learners.
      ${r.document_id ? `<button class="btn ghost small" id="rv-src">Open the source document</button>` : ""}</p>
    <div class="list" style="max-height:55vh;overflow-y:auto">${r.modules.map((mo, i) => `
      <section class="card flat"><h3>${i + 1}. ${esc(mo.title)} <span class="badge plain">pages ${esc(mo.pages)}</span></h3>
        <p class="small">${esc(mo.summary)}</p>
        ${mo.key_points.length ? `<ul class="small">${mo.key_points.map((k) => `<li>${esc(k)}</li>`).join("")}</ul>` : `<p class="small muted">No key points.</p>`}
      </section>`).join("")}</div>
    <form id="rv" style="margin-top:12px">
      <label class="small" style="display:flex;gap:8px;align-items:flex-start"><input type="checkbox" name="reviewed" required>
        <span>I've checked these modules against the source pages and they're accurate enough to publish.</span></label>
      <div style="display:flex;gap:8px;margin-top:8px"><button class="btn">${r.lessons_status === "draft" ? "Publish to learners" : "Keep published"}</button>
        ${r.lessons_status === "published" ? `<button type="button" class="btn secondary" id="rv-unpublish">Take back to draft</button>` : ""}</div>
    </form>`, { wide: true });
  $("#rv-src", m.root)?.addEventListener("click", async () => {
    try { window.open(await api.blobUrl(`/api/documents/${r.document_id}/file`), "_blank"); } catch (err) { toast(err.message, true); }
  });
  $("#rv", m.root).onsubmit = async (e) => {
    e.preventDefault();
    try { await api.post(`/api/library/trainings/${encodeURIComponent(code)}/publish`, { reviewed: true, publish: true }); toast("Published to learners"); m.close(); libraryView(view); }
    catch (err) { toast(err.message, true); }
  };
  $("#rv-unpublish", m.root)?.addEventListener("click", async () => {
    await api.post(`/api/library/trainings/${encodeURIComponent(code)}/publish`, { publish: false }); toast("Back to draft"); m.close(); libraryView(view);
  });
}
