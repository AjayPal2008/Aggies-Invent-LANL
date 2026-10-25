// Video lessons, interview-style assessments and the role plan card for the hire dashboard.
import { api, esc, $, $$, fmtDate, toast, modal, bar } from "/shared/api.js?v=20261025a";
import { settings, speakButton, speak } from "/shared/a11y.js?v=20261025a";

// ---- video player -------------------------------------------------------------------
// Plays AI-written scenes as a narrated video: the browser's speech engine reads the narration,
// on-screen items animate in step with it, captions show the current sentence, and a full
// transcript is always available (for deaf and hard-of-hearing learners and screen readers).

const synth = typeof window !== "undefined" ? window.speechSynthesis : null;

const sentencesOf = (text) => (text.match(/[^.!?]+[.!?]+["”’)]*|[^.!?]+$/g) || [text]).map((x) => x.trim()).filter(Boolean);
let videoInstance = 0;

export function videoPlayer(container, video, { onAnswer, onDone } = {}) {
  const prefs = settings();
  const transcriptId = `vp-tx-${++videoInstance}`;
  let i = 0, playing = false, speed = 1, voiceOn = !!synth, captions = prefs.captions !== "off", timer = null, revealTimers = [], capTimers = [];
  container.innerHTML = `
    <div class="vp" tabindex="0" aria-label="Video lesson. Space to play or pause, arrow keys to change scene.">
      <div class="vp-stage"><div class="vp-scene" aria-live="polite"></div><div class="vp-cap" aria-hidden="true"></div></div>
      <div class="vp-progress">${video.scenes.map((sc, k) => `<button class="vp-seg" data-seg="${k}" aria-label="Scene ${k + 1}: ${esc(sc.heading)}"><span></span></button>`).join("")}</div>
      <div class="vp-controls">
        <button class="btn small" data-act="play">▶ Play</button>
        <button class="btn ghost small" data-act="prev" aria-label="Previous scene">⏮</button>
        <button class="btn ghost small" data-act="next" aria-label="Next scene">⏭</button>
        <span class="small muted vp-count" aria-live="polite"></span><span style="flex:1"></span>
        <label class="small">Speed <select data-act="speed">${[0.75, 1, 1.25, 1.5].map((x) => `<option value="${x}" ${x === 1 ? "selected" : ""}>${x}×</option>`).join("")}</select></label>
        <label class="small"><input type="checkbox" data-act="voice" ${voiceOn ? "checked" : ""} ${synth ? "" : "disabled"}> Narration</label>
        <label class="small"><input type="checkbox" data-act="cc" ${captions ? "checked" : ""}> Captions (CC)</label>
        <button class="btn ghost small" data-act="transcript" aria-expanded="${prefs.showTranscript ? "true" : "false"}" aria-controls="${transcriptId}">Transcript</button>
      </div>
      <section id="${transcriptId}" class="card flat vp-transcript ${prefs.showTranscript ? "" : "hidden"}" aria-label="Transcript">
        <h4>Transcript</h4>
        ${video.scenes.map((sc, k) => `<p data-tx="${k}"><a href="#" data-seg="${k}"><strong>${k + 1}. ${esc(sc.heading)}</strong></a><br>${esc(sc.narration)}</p>`).join("")}
      </section>
      <div class="vp-after hidden"></div>
    </div>`;
  const root = $(".vp", container), stage = $(".vp-scene", container), cap = $(".vp-cap", container);

  const clear = () => {
    clearTimeout(timer); revealTimers.forEach(clearTimeout); capTimers.forEach(clearTimeout);
    revealTimers = []; capTimers = []; synth?.cancel();
  };
  const rate = () => speed * (Number(settings().speechRate) || 1);
  const seconds = (text) => Math.max(4, text.split(/\s+/).length / 2.6) / rate();
  const showCaption = (text) => { cap.textContent = captions ? text : ""; cap.classList.toggle("hidden", !captions || !text); };

  function render(k) {
    const sc = video.scenes[k];
    const items = sc.on_screen || [];
    let body;
    if (sc.visual === "title") body = `<div class="vp-title">${esc(items[0] || sc.heading)}</div>${items[1] ? `<div class="vp-sub">${esc(items[1])}</div>` : ""}`;
    else if (sc.visual === "diagram") body = `<ol class="vp-flow" style="list-style:none;padding:0;margin:4% 0 0">${items.map((x, n) => `${n ? `<li class="vp-arrow vp-item" aria-hidden="true">→</li>` : ""}<li class="vp-step vp-item"><span class="sr-only">Step ${n + 1}: </span>${esc(x)}</li>`).join("")}</ol>`;
    else if (sc.visual === "checklist") body = `<ul class="vp-check">${items.map((x) => `<li class="vp-item"><span aria-hidden="true">✔ </span>${esc(x)}</li>`).join("")}</ul>`;
    else if (sc.visual === "quote") body = `<blockquote class="vp-quote vp-item">“${esc(items[0] || "")}”</blockquote>`;
    else if (sc.visual === "scenario") body = `<div class="vp-scen"><div class="vp-item"><div class="vp-label">Situation</div>${esc(items[0] || "")}</div>
      <div class="vp-item"><div class="vp-label">Right move</div>${esc(items.slice(1).join(" ") || "")}</div></div>`;
    else body = `<ul class="vp-bullets">${items.map((x) => `<li class="vp-item">${esc(x)}</li>`).join("")}</ul>`;
    stage.innerHTML = `<div class="vp-heading">${esc(sc.heading)}</div>${body}`;
    showCaption(sentencesOf(sc.narration)[0]);
    $$(".vp-seg", container).forEach((seg, n) => { seg.firstElementChild.style.width = n < k ? "100%" : "0%"; seg.toggleAttribute("aria-current", n === k); });
    $(".vp-count", container).textContent = `Scene ${k + 1} of ${video.scenes.length}`;
    $$("[data-tx]", container).forEach((p) => p.classList.toggle("current", Number(p.dataset.tx) === k));
    const els = $$(".vp-item", stage);
    els.forEach((e) => e.classList.add("vp-hidden"));
    return els;
  }

  function play(k) {
    clear();
    i = k;
    const sc = video.scenes[k];
    const els = render(k);
    if (!playing) { els.forEach((e) => e.classList.remove("vp-hidden")); return; }
    const dur = seconds(sc.narration) * 1000;
    els.forEach((e, n) => revealTimers.push(setTimeout(() => e.classList.remove("vp-hidden"), (dur * n) / (els.length + 0.5))));
    const seg = $$(".vp-seg", container)[k].firstElementChild;
    seg.style.transition = "none"; seg.style.width = "0%";
    requestAnimationFrame(() => { seg.style.transition = `width ${dur}ms linear`; seg.style.width = "100%"; });
    // Captions: one sentence at a time. Timed by length, re-synced to the voice when the browser reports word boundaries.
    const sents = sentencesOf(sc.narration);
    const words = sents.map((x) => x.split(/\s+/).length);
    const total = words.reduce((a, b) => a + b, 0);
    let at = 0;
    sents.forEach((x, n) => { capTimers.push(setTimeout(() => showCaption(x), (dur * at) / total)); at += words[n]; });
    const next = () => (k + 1 < video.scenes.length ? play(k + 1) : finish());
    if (voiceOn && synth) {
      const u = new SpeechSynthesisUtterance(sc.narration);
      u.rate = rate();
      const starts = [];
      let pos = 0;
      sents.forEach((x) => { const idx = sc.narration.indexOf(x, pos); starts.push(idx < 0 ? pos : idx); pos = (idx < 0 ? pos : idx) + x.length; });
      u.onboundary = (ev) => {
        capTimers.forEach(clearTimeout); capTimers = [];
        let n = 0;
        while (n + 1 < starts.length && ev.charIndex >= starts[n + 1]) n++;
        showCaption(sents[n]);
      };
      u.onend = () => { if (playing && i === k) timer = setTimeout(next, 400); };
      synth.speak(u);
      timer = setTimeout(() => { if (playing && i === k && !synth.speaking) next(); }, dur + 4000); // fallback if speech never starts
    } else {
      timer = setTimeout(next, dur + 300);
    }
  }

  function setPlaying(v) {
    playing = v;
    const b = $('[data-act="play"]', container);
    b.textContent = v ? "❚❚ Pause" : "▶ Play";
    b.setAttribute("aria-label", v ? "Pause video" : "Play video");
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
      ${q ? `<div data-speak-scope><h4>Quick check ${speakButton("Read question")}</h4><p><strong>${esc(q.question)}</strong></p>
        <div>${q.options.map((o, n) => `<button class="choice" data-o="${n}">${esc(o)}</button>`).join("")}</div></div><div class="feedback" role="status"></div>` : ""}
      <div style="margin-top:8px;display:flex;gap:8px"><button class="btn secondary small" data-act="replay">Watch again</button>
        <button class="btn small" data-act="done">Mark this lesson done</button></div></div>`;
    $$("[data-o]", after).forEach((b) => b.addEventListener("click", () => {
      const ok = Number(b.dataset.o) === q.answer_index;
      $$("[data-o]", after).forEach((x, n) => { x.disabled = true; if (n === q.answer_index) x.classList.add("right"); });
      if (!ok) b.classList.add("wrong");
      $(".feedback", after).textContent = `${ok ? "Correct." : "Not quite."} ${q.explanation}`;
      onAnswer?.(ok, q.question);
    }));
    $('[data-act="replay"]', after).onclick = () => { after.classList.add("hidden"); i = 0; setPlaying(true); };
    $('[data-act="done"]', after).onclick = () => onDone?.();
    after.querySelector("h3").setAttribute("tabindex", "-1");
    after.querySelector("h3").focus();
  }

  container.addEventListener("click", (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "play") setPlaying(!playing);
    if (act === "prev") play(Math.max(0, i - 1));
    if (act === "next") (i + 1 < video.scenes.length ? play(i + 1) : finish());
    if (act === "transcript") {
      const tx = $(`#${transcriptId}`, container);
      tx.classList.toggle("hidden");
      e.target.setAttribute("aria-expanded", String(!tx.classList.contains("hidden")));
    }
    const seg = e.target.closest("[data-seg]");
    if (seg) { e.preventDefault(); play(Number(seg.dataset.seg)); }
  });
  container.addEventListener("change", (e) => {
    const act = e.target.dataset.act;
    if (act === "speed") { speed = Number(e.target.value); if (playing) play(i); }
    if (act === "voice") { voiceOn = e.target.checked; if (playing) play(i); }
    if (act === "cc") { captions = e.target.checked; showCaption(captions ? sentencesOf(video.scenes[i].narration)[0] : ""); }
  });
  root.addEventListener("keydown", (e) => {
    if (e.target !== root) return;
    if (e.key === " " || e.key === "k") { e.preventDefault(); setPlaying(!playing); }
    if (e.key === "ArrowRight") { e.preventDefault(); i + 1 < video.scenes.length ? play(i + 1) : finish(); }
    if (e.key === "ArrowLeft") { e.preventDefault(); play(Math.max(0, i - 1)); }
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
  // Testing accommodation from accessibility settings: 1.5x, 2x or no time limit (0).
  const extra = Number(settings().extraTime ?? 1);
  const scaleTime = (sec) => (extra === 0 ? null : Math.round(sec * (extra || 1)));
  data.read_seconds = scaleTime(data.read_seconds);
  data.answer_seconds = { text: scaleTime(data.answer_seconds.text), audio: scaleTime(data.answer_seconds.audio) };
  const timeNote = extra === 0 ? `<p class="badge ok">Accommodation on: no time limit</p>` : extra > 1 ? `<p class="badge ok">Accommodation on: ${extra}× time</p>` : "";
  const mins = (sec) => (sec == null ? "no time limit" : `${Math.round((sec / 60) * 10) / 10} minutes per question`);
  m.root.innerHTML = `
    <div class="modal-head"><h2>Situational assessment: ${esc(data.training.title)}</h2><button class="btn ghost" data-close>Exit</button></div>
    ${timeNote}
    <p>You'll get <strong>${data.scenarios.length} workplace scenarios</strong>. For each one you have ${data.read_seconds == null ? "as long as you need" : `about ${data.read_seconds} seconds`} to read it,
      then ${data.answer_seconds.text == null ? "an untimed" : "a timed"} answer for each question, like CASPer or a multiple mini interview. There are no trick questions: explain what you'd do and why,
      who you'd involve, and how you'd treat the people involved.</p>
    <div class="card flat" style="background:var(--navy-tint)">
      <h4>How do you want to answer?</h4>
      <label class="item small"><input type="radio" name="mode" value="text" checked> <div><strong>Type</strong> · ${mins(data.answer_seconds.text)}</div></label>
      <label class="item small" style="margin-top:6px"><input type="radio" name="mode" value="audio" ${canRecord ? "" : "disabled"}> <div><strong>Speak</strong> · ${data.answer_seconds.audio == null ? "no time limit" : `${data.answer_seconds.audio} seconds per question`}.
        Your answer is recorded ${Recognition ? "and transcribed as you talk" : "(your browser can't transcribe, so you'll type a short summary too)"}. ${canRecord ? "" : "Not available in this browser."}</div></label>
    </div>
    <p class="small muted">Need more time or prefer to have things read aloud? Open <strong>Accessibility</strong> (Alt + A) before you begin.</p>
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
      <div class="card flat" id="situation" style="background:var(--navy-tint);font-size:1rem;line-height:1.6">${esc(sc.situation)}</div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap">
        <button class="btn" id="go">I'm ready</button>
        ${synth ? `<button class="btn secondary speak" data-speak data-speak-target="#situation" aria-pressed="false">🔊 Read it to me</button>` : ""}
        <span class="small muted" role="timer">${seconds == null ? "No time limit" : `Questions start in <strong id="t">${seconds}</strong>s`}</span></div>`;
    let left = seconds;
    const tick = seconds == null ? null : setInterval(() => { left--; const t = $("#t", m.root); if (t) t.textContent = left; if (left <= 0) end(); }, 1000);
    const end = () => { clearInterval(tick); synth?.cancel(); resolve(); };
    $("#go", m.root).onclick = end;
    if (settings().readAloud && settings().autoRead) speak(sc.situation);
  });
}

function answerStep(m, sc, qi, mode, stream, seconds, done, total) {
  return new Promise((resolve) => {
    m.root.innerHTML = `${header(sc, done, total)}
      <details class="small" style="margin-bottom:8px"><summary>Scenario</summary><p>${esc(sc.situation)}</p></details>
      <h3 id="q-text">${esc(sc.questions[qi])} ${synth ? `<button type="button" class="btn ghost small speak" data-speak data-speak-target="#q-text" aria-pressed="false">🔊 Read question</button>` : ""}</h3>
      ${mode === "audio" ? `<div class="card flat"><div style="display:flex;align-items:center;gap:8px"><span class="rec-dot"></span><strong>Recording</strong>
          <span class="small muted">Speak your answer. ${Recognition ? "The transcript appears below; fix anything it misheard." : "Type a short summary below."}</span></div>
          <label for="ans" class="sr-only">Your answer</label>
          <textarea id="ans" rows="6" style="width:100%;margin-top:8px" placeholder="${Recognition ? "Transcribing…" : "Summary of what you said"}"></textarea></div>`
        : `<label for="ans" class="sr-only">Your answer</label><textarea id="ans" rows="9" style="width:100%" placeholder="What would you do, and why?"></textarea>`}
      <div style="display:flex;gap:8px;align-items:center;margin-top:10px">
        <button class="btn" id="next">${done + 1 === total ? "Finish" : "Next question"}</button>
        <span class="small muted" role="timer">${seconds == null ? "No time limit" : `Time left <strong id="t">${fmtClock(seconds)}</strong>`}</span>
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
    const tick = seconds == null ? null : setInterval(() => {
      left--;
      const t = $("#t", m.root);
      if (t) t.textContent = fmtClock(left);
      if (left === 30) import("/shared/a11y.js?v=20261025a").then((a) => a.announce("30 seconds left"));
      if (left <= 0) end();
    }, 1000);
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
      <div style="text-align:right"><div class="num" style="font-family:Poppins,sans-serif;font-size:1.75rem;font-weight:700;color:var(--navy-dark)">${Math.round(score)}</div>
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
