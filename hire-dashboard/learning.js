// Video lessons, interview-style assessments and the role plan card for the hire dashboard.
import { api, esc, $, $$, fmtDate, toast, modal, bar } from "/shared/api.js?v=20261024e";

// ---- video player -------------------------------------------------------------------
// Plays AI-written scenes as a narrated video: the browser's speech engine reads the narration,
// on-screen items animate in step with it, and captions follow along.

const synth = typeof window !== "undefined" ? window.speechSynthesis : null;

export function videoPlayer(container, video, { onAnswer, onDone } = {}) {
  let i = 0, playing = false, speed = 1, voiceOn = !!synth, captions = true, timer = null, revealTimers = [];
  container.innerHTML = `
    <div class="vp">
      <div class="vp-stage" aria-live="polite"><div class="vp-scene"></div><div class="vp-cap"></div></div>
      <div class="vp-progress">${video.scenes.map((_, k) => `<button class="vp-seg" data-seg="${k}" aria-label="Scene ${k + 1}"><span></span></button>`).join("")}</div>
      <div class="vp-controls">
        <button class="btn small" data-act="play">▶ Play</button>
        <button class="btn ghost small" data-act="prev" aria-label="Previous scene">⏮</button>
        <button class="btn ghost small" data-act="next" aria-label="Next scene">⏭</button>
        <span class="small muted vp-count"></span><span style="flex:1"></span>
        <label class="small">Speed <select data-act="speed">${[0.75, 1, 1.25, 1.5].map((s) => `<option value="${s}" ${s === 1 ? "selected" : ""}>${s}×</option>`).join("")}</select></label>
        <label class="small"><input type="checkbox" data-act="voice" ${voiceOn ? "checked" : ""} ${synth ? "" : "disabled"}> Narration</label>
        <label class="small"><input type="checkbox" data-act="cc" checked> Captions</label>
      </div>
      <div class="vp-after hidden"></div>
    </div>`;
  const stage = $(".vp-scene", container), cap = $(".vp-cap", container);

  const clear = () => { clearTimeout(timer); revealTimers.forEach(clearTimeout); revealTimers = []; synth?.cancel(); };
  const seconds = (text) => Math.max(4, text.split(/\s+/).length / 2.6) / speed;

  function render(k) {
    const s = video.scenes[k];
    const items = s.on_screen || [];
    let body;
    if (s.visual === "title") body = `<div class="vp-title">${esc(items[0] || s.heading)}</div>${items[1] ? `<div class="vp-sub">${esc(items[1])}</div>` : ""}`;
    else if (s.visual === "diagram") body = `<div class="vp-flow">${items.map((x, n) => `${n ? `<span class="vp-arrow vp-item">→</span>` : ""}<span class="vp-step vp-item">${esc(x)}</span>`).join("")}</div>`;
    else if (s.visual === "checklist") body = `<ul class="vp-check">${items.map((x) => `<li class="vp-item">✔ ${esc(x)}</li>`).join("")}</ul>`;
    else if (s.visual === "quote") body = `<blockquote class="vp-quote vp-item">“${esc(items[0] || "")}”</blockquote>`;
    else if (s.visual === "scenario") body = `<div class="vp-scen"><div class="vp-item"><div class="vp-label">Situation</div>${esc(items[0] || "")}</div>
      <div class="vp-item"><div class="vp-label">Right move</div>${esc(items.slice(1).join(" ") || "")}</div></div>`;
    else body = `<ul class="vp-bullets">${items.map((x) => `<li class="vp-item">${esc(x)}</li>`).join("")}</ul>`;
    stage.innerHTML = `<div class="vp-heading">${esc(s.heading)}</div>${body}`;
    cap.textContent = captions ? s.narration : "";
    cap.classList.toggle("hidden", !captions);
    $$(".vp-seg", container).forEach((seg, n) => seg.firstElementChild.style.width = n < k ? "100%" : "0%");
    $(".vp-count", container).textContent = `Scene ${k + 1} of ${video.scenes.length}`;
    const els = $$(".vp-item", stage);
    els.forEach((e) => e.classList.add("vp-hidden"));
    return els;
  }

  function play(k) {
    clear();
    i = k;
    const s = video.scenes[k];
    const els = render(k);
    if (!playing) { els.forEach((e) => e.classList.remove("vp-hidden")); return; }
    const dur = seconds(s.narration) * 1000;
    els.forEach((e, n) => revealTimers.push(setTimeout(() => e.classList.remove("vp-hidden"), (dur * n) / (els.length + 0.5))));
    const seg = $$(".vp-seg", container)[k].firstElementChild;
    seg.style.transition = "none"; seg.style.width = "0%";
    requestAnimationFrame(() => { seg.style.transition = `width ${dur}ms linear`; seg.style.width = "100%"; });
    const next = () => (k + 1 < video.scenes.length ? play(k + 1) : finish());
    if (voiceOn && synth) {
      const u = new SpeechSynthesisUtterance(s.narration);
      u.rate = speed;
      u.onend = () => { if (playing && i === k) timer = setTimeout(next, 400); };
      synth.speak(u);
      timer = setTimeout(() => { if (playing && i === k && !synth.speaking) next(); }, dur + 4000); // fallback if speech never starts
    } else {
      timer = setTimeout(next, dur + 300);
    }
  }

  function setPlaying(v) {
    playing = v;
    $('[data-act="play"]', container).textContent = v ? "❚❚ Pause" : "▶ Play";
    if (v) play(i); else clear();
  }

  function finish() {
    setPlaying(false);
    $$(".vp-seg", container).forEach((seg) => (seg.firstElementChild.style.width = "100%"));
    const after = $(".vp-after", container);
    const q = video.check_question;
    after.classList.remove("hidden");
    after.innerHTML = `<div class="card flat" style="margin-top:10px;background:var(--navy-tint)">
      <h3>Takeaways</h3><ul>${(video.takeaways || []).map((t) => `<li>${esc(t)}</li>`).join("")}</ul>
      ${q ? `<h4>Quick check</h4><p><strong>${esc(q.question)}</strong></p><div>${q.options.map((o, n) => `<button class="choice" data-o="${n}">${esc(o)}</button>`).join("")}</div><div class="feedback"></div>` : ""}
      <div style="margin-top:8px;display:flex;gap:8px"><button class="btn secondary small" data-act="replay">Watch again</button>
        <button class="btn small" data-act="done">Mark this lesson done</button></div></div>`;
    $$("[data-o]", after).forEach((b) => b.addEventListener("click", () => {
      const ok = Number(b.dataset.o) === q.answer_index;
      $$("[data-o]", after).forEach((x, n) => { x.disabled = true; if (n === q.answer_index) x.classList.add("right"); });
      if (!ok) b.classList.add("wrong");
      $(".feedback", after).textContent = q.explanation;
      onAnswer?.(ok, q.question);
    }));
    $('[data-act="replay"]', after).onclick = () => { after.classList.add("hidden"); i = 0; setPlaying(true); };
    $('[data-act="done"]', after).onclick = () => onDone?.();
  }

  container.addEventListener("click", (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "play") setPlaying(!playing);
    if (act === "prev") play(Math.max(0, i - 1));
    if (act === "next") (i + 1 < video.scenes.length ? play(i + 1) : finish());
    const seg = e.target.closest("[data-seg]");
    if (seg) play(Number(seg.dataset.seg));
  });
  container.addEventListener("change", (e) => {
    const act = e.target.dataset.act;
    if (act === "speed") { speed = Number(e.target.value); if (playing) play(i); }
    if (act === "voice") { voiceOn = e.target.checked; if (playing) play(i); }
    if (act === "cc") { captions = e.target.checked; cap.textContent = captions ? video.scenes[i].narration : ""; cap.classList.toggle("hidden", !captions); }
  });
  render(0).forEach((e) => e.classList.remove("vp-hidden"));
  // Stop talking if the learner navigates away.
  const obs = new MutationObserver(() => { if (!document.body.contains(container) || !container.querySelector(".vp")) { clear(); obs.disconnect(); } });
  obs.observe(document.body, { childList: true, subtree: true });
}

// ---- interview-style assessment ---------------------------------------------------------

const Recognition = typeof window !== "undefined" ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null;

export async function interviewFlow(assignmentId, onFinished, onReview) {
  const m = modal(`<div class="empty"><span class="spinner"></span> Preparing your scenarios…</div>`, { wide: true });
  let data;
  try { data = await api.post(`/api/me/assignments/${assignmentId}/interview`); }
  catch (e) { m.root.innerHTML = `<p>${esc(e.message)}</p><button class="btn" data-close>Close</button>`; return; }
  const canRecord = !!(navigator.mediaDevices && window.MediaRecorder);
  m.root.innerHTML = `
    <div class="modal-head"><h2>Situational assessment: ${esc(data.training.title)}</h2><button class="btn ghost" data-close>Exit</button></div>
    <p>You'll get <strong>${data.scenarios.length} workplace scenarios</strong>. For each one you have about ${data.read_seconds} seconds to read it,
      then a timed answer for each question, like CASPer or a multiple mini interview. There are no trick questions: explain what you'd do and why,
      who you'd involve, and how you'd treat the people involved.</p>
    <div class="card flat" style="background:var(--navy-tint)">
      <h4>How do you want to answer?</h4>
      <label class="item small"><input type="radio" name="mode" value="text" checked> <div><strong>Type</strong> · ${Math.round(data.answer_seconds.text / 60 * 10) / 10} minutes per question</div></label>
      <label class="item small" style="margin-top:6px"><input type="radio" name="mode" value="audio" ${canRecord ? "" : "disabled"}> <div><strong>Speak</strong> · ${data.answer_seconds.audio} seconds per question.
        Your answer is recorded ${Recognition ? "and transcribed as you talk" : "(your browser can't transcribe, so you'll type a short summary too)"}. ${canRecord ? "" : "Not available in this browser."}</div></label>
    </div>
    <div style="margin-top:12px"><button class="btn" id="iv-begin">Begin</button></div>`;
  $("#iv-begin", m.root).onclick = async () => {
    const mode = $("input[name=mode]:checked", m.root).value;
    let stream = null;
    if (mode === "audio") {
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
      catch { toast("Microphone permission was denied, switching to typed answers", true); }
    }
    runScenarios(m, data, stream ? "audio" : "text", stream, onFinished, onReview);
  };
}

async function runScenarios(m, data, mode, stream, onFinished, onReview) {
  const total = data.scenarios.reduce((n, s) => n + s.questions.length, 0);
  let done = 0;
  for (const sc of data.scenarios) {
    await readStep(m, sc, data.read_seconds, done, total);
    for (let qi = 0; qi < sc.questions.length; qi++) {
      const ans = await answerStep(m, sc, qi, mode, stream, data.answer_seconds[mode], done, total);
      done++;
      const f = new FormData();
      f.append("scenario_id", sc.id); f.append("question_index", qi); f.append("mode", ans.audio ? "audio" : "text");
      f.append("transcript", ans.text); f.append("seconds_used", ans.seconds);
      if (ans.audio) f.append("audio", ans.audio, `answer-${sc.id}-${qi}.webm`);
      try { await api.upload(`/api/me/interviews/${data.session_id}/responses`, f); }
      catch (e) { toast(`Couldn't save that answer: ${e.message}`, true); }
    }
  }
  stream?.getTracks().forEach((t) => t.stop());
  m.root.innerHTML = `<div class="empty"><span class="spinner"></span> Scoring your answers…</div>`;
  try {
    const r = await api.post(`/api/me/interviews/${data.session_id}/submit`);
    showResult(m, r, onReview);
    onFinished?.(r);
  } catch (e) { m.root.innerHTML = `<p>${esc(e.message)}</p><button class="btn" data-close>Close</button>`; }
}

function header(sc, done, total) {
  return `<div class="card-head"><h2>${esc(sc.title)}</h2><span class="small muted">Question ${Math.min(done + 1, total)} of ${total}</span></div>
    <div style="margin-bottom:10px">${bar((done / total) * 100)}</div>`;
}

function readStep(m, sc, seconds, done, total) {
  return new Promise((resolve) => {
    m.root.innerHTML = `${header(sc, done, total)}
      <div class="card flat" style="background:var(--navy-tint);font-size:16px;line-height:1.6">${esc(sc.situation)}</div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:12px">
        <button class="btn" id="go">I'm ready</button>
        ${synth ? `<button class="btn secondary" id="listen">🔊 Read it to me</button>` : ""}
        <span class="small muted">Questions start in <strong id="t">${seconds}</strong>s</span></div>`;
    let left = seconds;
    const tick = setInterval(() => { left--; const t = $("#t", m.root); if (t) t.textContent = left; if (left <= 0) end(); }, 1000);
    const end = () => { clearInterval(tick); synth?.cancel(); resolve(); };
    $("#go", m.root).onclick = end;
    $("#listen", m.root)?.addEventListener("click", () => { synth.cancel(); synth.speak(new SpeechSynthesisUtterance(sc.situation)); });
  });
}

function answerStep(m, sc, qi, mode, stream, seconds, done, total) {
  return new Promise((resolve) => {
    m.root.innerHTML = `${header(sc, done, total)}
      <details class="small" style="margin-bottom:8px"><summary>Scenario</summary><p>${esc(sc.situation)}</p></details>
      <h3>${esc(sc.questions[qi])}</h3>
      ${mode === "audio" ? `<div class="card flat"><div style="display:flex;align-items:center;gap:8px"><span class="rec-dot"></span><strong>Recording</strong>
          <span class="small muted">Speak your answer. ${Recognition ? "The transcript appears below; fix anything it misheard." : "Type a short summary below."}</span></div>
          <textarea id="ans" rows="6" style="width:100%;margin-top:8px" placeholder="${Recognition ? "Transcribing…" : "Summary of what you said"}"></textarea></div>`
        : `<textarea id="ans" rows="9" style="width:100%" placeholder="What would you do, and why?"></textarea>`}
      <div style="display:flex;gap:8px;align-items:center;margin-top:10px">
        <button class="btn" id="next">${done + 1 === total ? "Finish" : "Next question"}</button>
        <span class="small muted">Time left <strong id="t">${fmtClock(seconds)}</strong></span>
        <span class="small muted" id="wc"></span></div>`;
    const ta = $("#ans", m.root);
    ta.focus();
    ta.addEventListener("input", () => ($("#wc", m.root).textContent = `${ta.value.trim().split(/\s+/).filter(Boolean).length} words`));
    let recorder = null, chunks = [], rec = null, finalText = "";
    if (mode === "audio" && stream) {
      recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      recorder.start();
      if (Recognition) {
        rec = new Recognition();
        rec.continuous = true; rec.interimResults = true; rec.lang = "en-US";
        rec.onresult = (e) => {
          let interim = "";
          for (let k = e.resultIndex; k < e.results.length; k++) {
            if (e.results[k].isFinal) finalText += e.results[k][0].transcript + " ";
            else interim += e.results[k][0].transcript;
          }
          ta.value = (finalText + interim).trim();
        };
        rec.onerror = () => {};
        try { rec.start(); } catch { /* already started */ }
      }
    }
    const started = Date.now();
    let left = seconds;
    const tick = setInterval(() => { left--; const t = $("#t", m.root); if (t) t.textContent = fmtClock(left); if (left <= 0) end(); }, 1000);
    let ended = false;
    const end = () => {
      if (ended) return;
      ended = true;
      clearInterval(tick);
      rec?.stop();
      const used = Math.round((Date.now() - started) / 1000);
      if (recorder && recorder.state !== "inactive") {
        recorder.onstop = () => setTimeout(() => resolve({ text: ta.value, seconds: used, audio: new Blob(chunks, { type: recorder.mimeType || "audio/webm" }) }), 300);
        recorder.stop();
      } else {
        resolve({ text: ta.value, seconds: used, audio: null });
      }
    };
    $("#next", m.root).onclick = end;
  });
}

function fmtClock(s) { s = Math.max(0, s); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }

const READY_CLASS = { ready: "ok", ready_with_support: "warn", not_ready: "bad" };

/** Readiness card: the overall call, why, what to do next, and which modules to review. */
export function readinessCard(rd, level, score, { compact = false } = {}) {
  if (!level || !rd) return "";
  const cls = READY_CLASS[level] || "";
  return `<section class="card flat readiness ${cls}" style="border-left:6px solid var(--${cls === "ok" ? "ok" : cls === "warn" ? "warn" : "bad"});margin-bottom:12px">
    <div class="card-head" style="margin-bottom:6px"><div><div class="small muted" style="text-transform:uppercase;letter-spacing:.06em;font-weight:700">Readiness</div>
      <h2 style="margin:0">${esc(rd.label)}</h2></div>
      <div style="text-align:right"><div class="num" style="font-family:Poppins,sans-serif;font-size:28px;font-weight:700;color:var(--navy-dark)">${Math.round(score)}</div>
      <div class="small muted">out of 100</div></div></div>
    <p style="margin-bottom:8px">${esc(rd.summary)}</p>
    ${compact ? "" : `
    <div class="grid cols-2" style="gap:12px">
      <div><h4>Next steps</h4><ul class="small">${(rd.next_steps || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        ${rd.review_modules?.length ? `<h4>Review these modules</h4><div class="list">${rd.review_modules.map((mo) => `
          <button class="item small" data-review="${mo.module_id}" style="text-align:left;cursor:pointer;font:inherit"><div class="grow"><strong>${esc(mo.title)}</strong>
          <div class="muted">pages ${esc(mo.pages)} · ${esc(mo.because)}</div></div><span class="badge">Open</span></button>`).join("")}</div>` : ""}</div>
      <div><h4>By competency</h4>${(rd.competencies || []).map((c) => `<div class="small">${esc(c.name)}
          <span class="badge ${c.status === "strong" ? "ok" : c.status === "solid" ? "" : "warn"}">${c.status === "develop" ? "to develop" : c.status}</span>
          <span class="muted num">${c.score}/9</span>${bar(((c.score - 1) / 8) * 100, c.status === "develop" ? "warn" : c.status === "strong" ? "ok" : "")}</div>`).join("")}
        <p class="small muted" style="margin-top:6px">Based on the interview (${rd.inputs?.interview}/9${rd.inputs?.scored_by === "manager" ? ", set by your manager" : ""}),
          the weakest competency, ${rd.inputs?.skill_mastery_pct}% mastery of this training's skills${rd.inputs?.quiz_best != null ? ` and a quiz score of ${rd.inputs.quiz_best}` : ""}.</p></div>
    </div>`}
  </section>`;
}

export function showResult(m, r, onReview) {
  const final = r.final;
  m.root.innerHTML = `
    <div class="modal-head"><h2>Interview result · ${final ?? "—"} / 9 ${r.passed ? `<span class="badge ok">Passed</span>` : `<span class="badge warn">Under the ${r.pass_mark} pass mark</span>`}</h2>
      <button class="btn ghost" data-close>Close</button></div>
    ${readinessCard(r.readiness_detail, r.readiness, r.readiness_score)}
    <p class="muted small">Pass mark ${r.pass_mark}. ${r.scored_by === "offline" ? "This is an offline estimate; your manager will review your answers and can adjust the score."
      : "Scored by AI against a rubric. Your manager can review your answers and adjust the score."}
      ${r.manager_overall != null ? `Your manager set the score to ${r.manager_overall}.` : ""}</p>
    ${r.manager_notes ? `<div class="card flat"><strong>From your manager:</strong> ${esc(r.manager_notes)}</div>` : ""}
    <div class="grid cols-2" style="margin-bottom:10px">
      <div class="card flat"><h4>Strengths</h4><ul class="small">${(r.feedback?.strengths || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ul></div>
      <div class="card flat"><h4>To work on</h4><ul class="small">${(r.feedback?.improvements || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ul></div>
    </div>
    ${r.scenarios.map((sc) => `<section class="card flat" style="margin-bottom:8px"><h3>${esc(sc.title)}</h3>
      ${sc.responses.map((x) => `<div class="small" style="margin-top:6px"><strong>${esc(x.question)}</strong> <span class="badge ${x.score >= r.pass_mark ? "ok" : "warn"}">${x.score ?? "—"}/9</span>
        <div class="muted" style="white-space:pre-wrap">${esc(x.transcript || "(no answer)")}</div><div><em>${esc(x.feedback || "")}</em></div></div>`).join("")}
      ${sc.strong_response?.length ? `<details class="small" style="margin-top:6px"><summary>What a strong answer considers</summary><ul>${sc.strong_response.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></details>` : ""}
    </section>`).join("")}`;
  $$("[data-review]", m.root).forEach((b) => b.addEventListener("click", () => { m.close(); onReview?.(r.assignment.training.code, Number(b.dataset.review)); }));
}

// ---- role plan card ---------------------------------------------------------------

const ENTRY = { new_hire: "New to LANL", promotion: "Promoted into this role", transfer: "Transferred into this role" };

export function rolePlanCard(p) {
  if (!p || !p.phases.length) return "";
  return `<section class="card" style="margin-bottom:16px">
    <div class="card-head"><div><h2>Your plan for ${esc(p.position.title)}</h2>
      <div class="small muted">${ENTRY[p.entry_path] || ""} · started ${fmtDate(p.role_start_date)} · tailored to your experience, so things you've already done are left out</div></div></div>
    <div class="grid cols-3">${p.phases.map((ph) => `<div class="card flat">
      <div class="card-head" style="margin-bottom:6px"><h3>${esc(ph.label)}</h3><span class="small muted">by ${fmtDate(ph.ends)}</span></div>
      ${bar((ph.done / ph.items.length) * 100, ph.done === ph.items.length ? "ok" : "")}
      <div class="small muted" style="margin:4px 0">${ph.done} of ${ph.items.length} done</div>
      <div class="list">${ph.items.map((it) => `<div class="small">${it.status === "completed" ? "✔" : "○"} <a href="#studio" data-learn="${esc(it.training_code)}">${esc(it.title)}</a>
        ${it.assessment_type === "situational" ? `<span class="badge plain">interview</span>` : it.assessment_type === "both" ? `<span class="badge plain">quiz + interview</span>` : ""}</div>`).join("")}</div></div>`).join("")}</div>
  </section>`;
}
