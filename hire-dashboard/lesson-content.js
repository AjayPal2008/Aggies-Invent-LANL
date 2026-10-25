import { esc, $, $$ } from "/shared/api.js?v=20261025a";
import { speak, stopSpeaking, canSpeak } from "/shared/a11y.js?v=20261025a";
import { videoPlayer } from "./learning.js";

export const DELIVERY_MODES = [
  { id: "text", title: "Text lesson", icon: "Aa", description: "Read clear sections, source explanations, key takeaways, and short checks as you go." },
  { id: "visual", title: "Visual study", icon: "◇", description: "Explore concept cards and supporting evidence, then open each card for the full explanation." },
  { id: "video", title: "Video walkthrough", icon: "▶", description: "Watch narrated, animated slides with captions, speed controls, transcripts, and section quizzes." },
  { id: "mindmap", title: "Mind map", icon: "⑂", description: "Explore the complete topic map with supporting details. Expand it fullscreen and adjust the zoom." },
  { id: "audio", title: "Audio lesson", icon: "♪", description: "Listen section by section with browser narration, follow the transcript, and pause for quick checks." },
];

export function getLessonSections(course) {
  if (course.learning_sections?.length) return course.learning_sections;
  return course.key_points.map(p => ({ id: p.id || p.point, concept_id: p.id || p.point, title: p.point,
    explanation: p.explanation, paragraphs: [p.explanation], takeaways: [p.explanation], page: p.page, kind: "Core concept" }));
}

function bodyHtml(section) {
  return (section.paragraphs?.length ? section.paragraphs : [section.explanation]).map(p => `<p>${esc(p)}</p>`).join("");
}

function checkpointHtml(sections, group, makeQuestion, getCheckpoint) {
  const source = sections.slice(-2);
  const questions = [0, 1].map((variant) => {
    const section = source[variant % source.length];
    const q = makeQuestion({ point: section.title, explanation: section.explanation }, variant);
    return { ...q, section, key: `${section.id}:check-${variant}`, variant };
  });
  const finished = questions.every(q => getCheckpoint(q.key)?.correct);
  return { questions, html: `<section class="studio-checkpoint" aria-labelledby="checkpoint-heading-${group}"><div class="card-head"><h3 id="checkpoint-heading-${group}">Pause &amp; check ${group + 1}</h3><span class="badge plain">2 questions</span></div><p class="muted small">Check what you just learned before moving to the next section.</p><form data-checkpoint="${group}">${questions.map((q, i) => {
    const result = getCheckpoint(q.key);
    return `<fieldset><legend>${i + 1}. ${esc(q.prompt)}</legend><p>${esc(q.statement)}</p>${q.options.map((option, n) => `<label class="item"><input type="radio" required name="answer-${i}" value="${n}" ${result?.choice === n ? "checked" : ""} ${result?.correct ? "disabled" : ""}> ${esc(option)}</label>`).join("")}${result?.correct ? '<p class="small studio-correct">Correct — recorded in your concept progress.</p>' : ""}</fieldset>`;
  }).join("")}<button class="btn" ${finished ? "disabled" : ""}>${finished ? "Checkpoint completed" : "Check these answers"}</button><div class="studio-check-feedback" role="status"></div></form></section>` };
}

export function renderLessonContent(container, course, options) {
  const { mode, mindMap, makeQuestion, onCheckpoint, getCheckpoint } = options;
  const sections = getLessonSections(course);
  const checkpoints = [];
  const videos = [];
  let dialog = null;
  let priorFocus = null;
  const sectionIntro = `<section class="studio-intro"><span class="studio-eyebrow">Learning objective</span><h3>${esc(course.title)}</h3><p>${esc(course.objective)}</p><p class="small muted">${sections.length} sections &middot; ${Math.max(1, Math.ceil(sections.length / 2))} short checkpoints &middot; a final topic quiz</p></section>`;
  const contents = `<nav class="studio-contents" aria-label="Lesson sections"><strong>In this lesson</strong><div>${sections.map((s, i) => `<button type="button" class="btn ghost small" data-jump="${i}">${String(i + 1).padStart(2, "0")} ${esc(s.title)}</button>`).join("")}</div></nav>`;
  const mapCourse = { ...course, key_points: sections.map(s => ({ point: s.title, explanation: s.explanation })) };
  const mapHeader = mode === "mindmap" ? `<section class="studio-map-panel"><div class="card-head"><h3>Complete topic map</h3><button class="btn secondary" id="map-fullscreen">Expand fullscreen</button></div><p class="small muted">All lesson concepts, source details, review branches, and key terms. Use the section lessons below to check your understanding.</p><div id="inline-topic-map">${mindMap(mapCourse)}</div></section>` : "";
  const lessons = sections.map((s, index) => {
    let media;
    if (mode === "visual") {
      media = `<div class="studio-visual-grid">${(s.takeaways?.length ? s.takeaways : [s.explanation]).map((point, n) => `<article class="studio-evidence-card"><span class="studio-evidence-number">${n + 1}</span><h4>Key idea ${n + 1}</h4><p>${esc(point)}</p></article>`).join("")}</div><details class="studio-more"><summary>Read the full explanation and context</summary>${bodyHtml(s)}</details>`;
    } else if (mode === "video") {
      const id = `section-video-${index}`;
      videos.push({ id, section: s });
      media = `<p class="small muted">Narrated slides built from the course material. Captions and a complete transcript are available in the player.</p><div id="${id}"></div><p class="small muted" id="${id}-status" role="status"></p>`;
    } else if (mode === "audio") {
      media = `<div class="toolbar"><button class="btn secondary" data-listen="${index}" ${canSpeak() ? "" : "disabled"}>Listen to section ${index + 1}</button><button class="btn ghost" data-stop-audio>Stop audio</button></div>${!canSpeak() ? '<p class="small muted">Your browser does not support narration. The full transcript is below.</p>' : ""}<details class="studio-more" open><summary>Section transcript</summary>${bodyHtml(s)}</details>`;
    } else {
      media = `${bodyHtml(s)}<aside class="studio-takeaways"><h4>Key takeaways</h4><ul>${(s.takeaways || []).map(t => `<li>${esc(t)}</li>`).join("")}</ul></aside>`;
    }
    let check = "";
    if ((index + 1) % 2 === 0 || index === sections.length - 1) {
      const group = checkpoints.length;
      const checkpoint = checkpointHtml(sections.slice(Math.max(0, index - 1), index + 1), group, makeQuestion, getCheckpoint);
      checkpoints.push(checkpoint);
      check = checkpoint.html;
    }
    return `<section class="studio-lesson-section" id="lesson-part-${index}" tabindex="-1"><div class="studio-section-heading"><span class="studio-section-number">${String(index + 1).padStart(2, "0")}</span><div><span class="studio-eyebrow">${esc(s.kind || "Lesson section")}${s.page ? ` &middot; source page ${s.page}` : ""}</span><h3>${esc(s.title)}</h3></div></div><div class="studio-section-body">${media}</div></section>${check}`;
  }).join("");
  container.innerHTML = `${sectionIntro}${contents}${mapHeader}<div class="studio-sections">${lessons}</div><section class="studio-summary"><h3>Bring it together</h3><p>${esc(course.recommended_review)}</p><p>Use the concept practice below for extra reinforcement, then take the final topic quiz when you are ready.</p><details><summary>Original source excerpt</summary><blockquote>${esc(course.source_excerpt)}</blockquote></details></section>`;
  const url = /^https:\/\//i.test(course.attribution.url || "") ? course.attribution.url : null;
  container.insertAdjacentHTML("beforeend", `<p class="small muted studio-attribution">${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(course.attribution.name)}</a>` : esc(course.attribution.name)} &middot; ${esc(course.attribution.license)}</p>`);

  $$("[data-jump]", container).forEach(button => button.onclick = () => {
    const target = $(`#lesson-part-${button.dataset.jump}`, container);
    target.scrollIntoView({ behavior: "smooth", block: "start" }); target.focus({ preventScroll: true });
  });
  $$("[data-listen]", container).forEach(button => button.onclick = () => {
    const section = sections[Number(button.dataset.listen)];
    speak(`${section.title}. ${section.explanation}`, button);
  });
  $$("[data-stop-audio]", container).forEach(button => button.onclick = stopSpeaking);
  videos.forEach(({ id, section }) => {
    const parts = section.paragraphs?.length ? section.paragraphs : [section.explanation];
    videoPlayer($(`#${id}`, container), { scenes: parts.map((paragraph, i) => ({ heading: `${section.title}${parts.length > 1 ? ` (${i + 1}/${parts.length})` : ""}`,
      visual: i === 0 ? "bullets" : "quote", narration: paragraph,
      on_screen: i === 0 ? (section.takeaways || [paragraph]).slice(0, 3) : [paragraph] })), takeaways: section.takeaways || [] }, {
      onDone: () => { $(`#${id}-status`, container).textContent = "Section viewed. Complete the checkpoint below to record your understanding."; },
    });
  });
  $$("[data-checkpoint]", container).forEach(form => {
    const check = checkpoints[Number(form.dataset.checkpoint)];
    form.onsubmit = event => {
      event.preventDefault();
      const button = $("button", form);
      if (button.disabled) return;
      const answers = new FormData(form);
      const feedback = [];
      try {
        check.questions.forEach((q, i) => {
          if (getCheckpoint(q.key)?.correct) { feedback.push("Already completed correctly."); return; }
          const choice = Number(answers.get(`answer-${i}`));
          const correct = q.options[choice] === q.answer;
          onCheckpoint(q.section.concept_id, q.key, correct, choice);
          feedback.push(`${correct ? "Correct." : "Not quite."} ${q.section.explanation}`);
          if (correct) $$(`input[name="answer-${i}"]`, form).forEach(input => { input.disabled = true; });
        });
        $(".studio-check-feedback", form).innerHTML = feedback.map((text, i) => `<p><strong>Question ${i + 1}</strong> ${esc(text)}</p>`).join("");
        const complete = check.questions.every(q => getCheckpoint(q.key)?.correct);
        button.disabled = complete; button.textContent = complete ? "Checkpoint completed" : "Try missed answers again";
      } catch (error) { $(".studio-check-feedback", form).textContent = `Could not save checkpoint: ${error.message}`; }
    };
  });

  const closeMap = () => {
    if (!dialog) return;
    if (document.fullscreenElement === dialog) document.exitFullscreen?.().catch(() => {});
    dialog.close(); dialog.remove(); dialog = null; priorFocus?.focus();
  };
  $("#map-fullscreen", container)?.addEventListener("click", () => {
    priorFocus = document.activeElement;
    dialog = document.createElement("dialog"); dialog.className = "studio-fullscreen-map";
    dialog.setAttribute("aria-label", `${course.title} fullscreen mind map`);
    dialog.innerHTML = `<header><div><span class="studio-eyebrow">Full topic map</span><h2>${esc(course.title)}</h2></div><label>Zoom <input id="map-zoom" type="range" min="60" max="180" value="100"><output id="map-zoom-value">100%</output></label><button class="btn secondary" id="map-close">Close fullscreen</button></header><div class="studio-fullscreen-map-body"><div id="fullscreen-map-content">${mindMap(mapCourse)}</div></div>`;
    document.body.append(dialog); dialog.showModal();
    dialog.requestFullscreen?.().catch(() => {});
    $("#map-close", dialog).onclick = closeMap;
    dialog.addEventListener("cancel", event => { event.preventDefault(); closeMap(); });
    $("#map-zoom", dialog).oninput = event => {
      $("#fullscreen-map-content", dialog).style.width = `${event.target.value}%`;
      $("#map-zoom-value", dialog).textContent = `${event.target.value}%`;
    };
  });
  return () => { stopSpeaking(); closeMap(); container.innerHTML = ""; };
}
