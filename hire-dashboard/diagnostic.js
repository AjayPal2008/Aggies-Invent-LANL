// Learner UI only. Keys, approval records and grading stay in the Python API.
import { api, esc, $, loading } from "/shared/api.js?v=20261024e";

const key = (user) => `lanl_diagnostic_${user.id}`;
const saved = (user) => localStorage.getItem(key(user));
const remember = (user, id) => localStorage.setItem(key(user), id);
const endpoint = (id, suffix) => `/api/diagnostic/sessions/${encodeURIComponent(id)}/${suffix}`;
const link = (url) => /^https:\/\//i.test(url || "") ? esc(url) : "#";

function message(root, text, retry) {
  root.innerHTML = `<section class="card"><h2>Diagnostic assessment</h2><p role="alert">${esc(text)}</p>
    <p class="muted small">Only manually approved, source-grounded questions are used. This diagnostic does not complete required training.</p>
    <button class="btn" id="diagnostic-retry">Try again</button></section>`;
  $("#diagnostic-retry", root).onclick = retry;
}

function choices(options, name) {
  return options.map((o) => `<label class="item" style="cursor:pointer"><input type="radio" name="${name}" value="${esc(o.id)}" required> <span>${esc(o.text)}</span></label>`).join("");
}

function showQuestion(root, envelope, user, go, notice = "") {
  if (envelope.complete) { go("diagnostic-results"); return; }
  const q = envelope.question;
  root.innerHTML = `<div class="card-head"><h1>Diagnostic assessment</h1><span class="badge">${envelope.answered} / ${envelope.budget} answered</span></div>
    <p class="muted small">${esc(q.article_id.replaceAll("-", " "))} · ${esc(q.level)} · fictional scenario</p>
    ${notice ? `<p class="badge warn" role="status">${esc(notice)}</p>` : ""}
    <form id="diagnostic-form" class="list">
      <section class="card"><p>${esc(q.scenario)}</p><h2>${esc(q.question)}</h2>${choices(q.options, "answer")}</section>
      <section class="card"><h3>${esc(q.why.question)}</h3>${choices(q.why.options, "reason")}</section>
      <section class="card"><label class="field">How confident are you?
        <select name="confidence" required><option value="">Choose confidence</option>
        ${q.confidence_choices.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("")}</select></label>
        <p class="small muted">Confidence adds no points. Answer and reasoning are graded separately.</p></section>
      <p id="diagnostic-error" role="alert"></p><div class="toolbar"><button class="btn" type="submit">Submit response</button>
      <button class="btn secondary" type="button" id="diagnostic-refresh">Refresh current question</button></div>
    </form><p class="muted small">Adapted from ${esc(q.attribution.name)} · ${esc(q.attribution.license)} ·
    <a href="${link(q.attribution.url)}" target="_blank" rel="noopener">Source article</a>. No training-completion credit.</p>`;
  $("#diagnostic-refresh", root).onclick = () => diagnosticView(root, user, go);
  let pending = null;
  $("#diagnostic-form", root).onsubmit = async (event) => {
    event.preventDefault();
    const button = event.target.querySelector('button[type="submit"]');
    if (button.disabled) return;
    button.disabled = true;
    $("#diagnostic-error", root).textContent = "";
    const form = new FormData(event.target);
    // Retrying a network-interrupted POST reuses the identical payload. The API
    // also serializes and deduplicates by session + question ID.
    pending ||= { question_id: q.id, answer_id: form.get("answer"), reason_id: form.get("reason"), confidence: form.get("confidence") };
    try {
      const next = await api.post(endpoint(envelope.session_id, "answers"), pending, { retry: false });
      if (!root.isConnected || !$("#diagnostic-form", root)) return;
      if (!next.branch_complete) {
        showQuestion(root, next, user, go, "Continue with the foundational principle. Explanations are held until this branch finishes.");
      } else {
        showFeedback(root, next, user, go);
      }
    } catch (error) {
      const target = $("#diagnostic-error", root);
      if (target) target.textContent = `${error.message} Retry the same response, or refresh the current question.`;
    } finally { button.disabled = false; }
  };
}

function showFeedback(root, envelope, user, go) {
  root.innerHTML = `<h1>Diagnostic branch finished</h1><p class="muted">Feedback is now available for the completed branch.</p>
    <div class="list">${envelope.feedback.map((f) => `<section class="card">
      <h3>Answer: ${f.answer_correct ? "correct" : "needs review"} · Reasoning: ${f.reason_correct ? "correct" : "needs review"}</h3>
      ${[["Answer choices", f.answers], ["Reasoning choices", f.reasons]].map(([title, options]) => `<details><summary>${title}</summary>
        ${options.map((o) => `<p><strong>${esc(o.text)}</strong><br>${esc(o.explanation)}</p>`).join("")}</details>`).join("")}</section>`).join("")}</div>
    <button class="btn" id="diagnostic-continue" style="margin-top:16px">${envelope.complete ? "View concept-level results" : "Continue diagnostic"}</button>`;
  $("#diagnostic-continue", root).onclick = () => envelope.complete ? go("diagnostic-results") : diagnosticView(root, user, go);
}

export async function diagnosticView(root, user, go) {
  loading(root);
  try {
    const status = await api.get("/api/diagnostic/status");
    if (!status.available) { message(root, status.message, () => diagnosticView(root, user, go)); return; }
    const id = saved(user);
    if (id) {
      try { showQuestion(root, await api.get(endpoint(id, "current")), user, go); return; }
      catch (error) {
        if (![404, 409].includes(error.status)) throw error;
        localStorage.removeItem(key(user));
      }
    }
    root.innerHTML = `<section class="hero"><h1>Find your next learning step</h1><p>Apply important concepts, explain your reasoning, and identify targeted review.</p></section>
      <section class="card"><h2>A short diagnostic across four topics</h2><p>Up to eight initial scenarios, within a total budget of 12 including foundation and prerequisite probes.</p>
      <p>Untested concepts remain not assessed. Correct responses provide evidence of understanding, not certified mastery. Required training is separate.</p>
      <button class="btn" id="diagnostic-start">Start diagnostic</button><p id="diagnostic-error" role="alert"></p></section>`;
    $("#diagnostic-start", root).onclick = async (event) => {
      event.target.disabled = true;
      try {
        const envelope = await api.post("/api/diagnostic/sessions", { initial_limit: 8, budget: 12 }, { retry: false });
        remember(user, envelope.session_id);
        showQuestion(root, envelope, user, go);
      } catch (error) {
        const target = $("#diagnostic-error", root);
        if (target) target.textContent = error.message;
        event.target.disabled = false;
      }
    };
  } catch (error) { message(root, error.message, () => diagnosticView(root, user, go)); }
}

export async function diagnosticResults(root, user, go) {
  const id = saved(user);
  if (!id) { go("diagnostic"); return; }
  loading(root);
  try {
    const report = await api.get(endpoint(id, "results"));
    const priority = report.review_priority.map((cid) => report.objectives.find((c) => c.objective_id === cid));
    const articles = Object.keys(report.article_coverage);
    root.innerHTML = `<div class="hero"><h1>Your diagnostic evidence</h1><p>${esc(report.interpretation)}</p></div>
      <div class="grid cols-4"><div class="stat"><div class="label">Scenarios answered</div><div class="value">${report.questions_answered}</div></div>
      <div class="stat"><div class="label">Answers correct</div><div class="value">${report.answers_correct}</div></div>
      <div class="stat"><div class="label">Reasons correct</div><div class="value">${report.reasons_correct}</div></div>
      <div class="stat"><div class="label">Confidence points</div><div class="value">0</div></div></div>
      <section class="card" style="margin-top:16px"><h2>Targeted review</h2><p>Importance 3 is highest priority.</p>
      ${priority.length ? `<ol>${priority.map((o) => `<li><strong>${esc(o.name)}</strong> · priority ${o.importance}<br>${esc(o.recommended_review)}</li>`).join("")}</ol>` : "<p>No review gap was observed among tested concepts. Untested concepts remain uncertain.</p>"}</section>
      ${articles.map((article) => `<section class="card" style="margin-top:16px"><h2>${esc(article.replaceAll("-", " "))}</h2>
        <p class="muted">${report.article_coverage[article].tested} / ${report.article_coverage[article].mapped} mapped concepts tested${report.article_coverage[article].mapped ? "" : "; not assessed — this topic has no mapped questions in the current bank"}</p>
        <div class="list">${report.objectives.filter((o) => o.article_id === article).map((o) => `<details class="card flat"><summary><strong>${esc(o.name)}</strong> · ${esc(o.status)}</summary>
          <p>${esc(o.objective)}</p><p>Foundation: ${esc(o.evidence.foundation)} · Application: ${esc(o.evidence.application)} · Reasoning: ${esc(o.evidence.reasoning)}</p>
          <p>Foundation reasoning: ${esc(o.evidence.foundation_reasoning)}</p><p><strong>Observed gap:</strong> ${esc(o.observed_gap)}</p>
          <p><strong>Recommended review:</strong> ${esc(o.recommended_review)}</p><p><strong>Untested:</strong> ${esc(o.untested.join(", ") || "none of these diagnostic components")}; post-training transfer remains untested.</p>
          ${o.followup_unavailable ? `<p>${esc(o.followup_unavailable)}</p>` : ""}
          <blockquote>${esc(o.review_resources.excerpt)}</blockquote><p class="small">Resource points: ${o.review_resources.resource_point_ids.map(esc).join(", ")} ·
          <a href="${link(o.review_resources.source.url)}" target="_blank" rel="noopener">${esc(o.review_resources.source.name)}</a> · ${esc(o.review_resources.source.license)}</p>
        </details>`).join("")}</div></section>`).join("")}
      <section class="card" style="margin-top:16px"><h2>Required training — separate obligations</h2>${report.required_training.map((o) => `<p>${esc(o.article_id)}: ${o.required ? "required" : "optional"} · ${esc(o.completion)}</p>`).join("")}</section>
      <button class="btn secondary" id="diagnostic-new" style="margin-top:16px">Start a new diagnostic</button>`;
    $("#diagnostic-new", root).onclick = () => { localStorage.removeItem(key(user)); go("diagnostic"); };
  } catch (error) {
    message(root, `${error.message} You may need to finish or restart the diagnostic.`, () => go("diagnostic"));
  }
}
