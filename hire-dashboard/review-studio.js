import { api, esc, $, $$, loading } from "/shared/api.js?v=20261025a";
import { speak, stopSpeaking, canSpeak } from "/shared/a11y.js?v=20261025a";

let selected = null;
let format = "text";

const progressKey = user => `lanl_studio_progress_v1_${user.id}`;
export function readProgress(user) {
  try {
    const data = JSON.parse(localStorage.getItem(progressKey(user)) || "null");
    if (data?.version === 1 && data.courses && Array.isArray(data.days)) return data;
  } catch { /* Start with an empty profile when storage is unavailable. */ }
  return { version: 1, courses: {}, days: [], points: 0, rewards: [] };
}
function saveProgress(user, state) {
  // Surface storage failure instead of claiming progress was saved.
  localStorage.setItem(progressKey(user), JSON.stringify(state));
}
function localDay(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
export function streakDays(state, today = new Date()) {
  const dates = new Set(state.days);
  const date = new Date(today.getFullYear(), today.getMonth(), today.getDate(), 12);
  if (!dates.has(localDay(date))) date.setDate(date.getDate() - 1);
  let count = 0;
  while (dates.has(localDay(date))) { count++; date.setDate(date.getDate() - 1); }
  return count;
}
function reward(state, id, points) {
  if (!state.rewards.includes(id)) { state.rewards.push(id); state.points += points; }
  const day = localDay();
  if (!state.days.includes(day)) state.days.push(day);
}
function trackCourse(state, course, session) {
  const id = `${session}:${course.id}`;
  state.courses[id] ||= { id: course.id, session, title: course.title, enrolled: false, reviewed: false, passed: false, concepts: {}, added: Date.now() };
  const item = state.courses[id];
  (course.key_points || []).forEach(p => { item.concepts[p.id || p.point] ||= { title: p.point, streak: 0, momentum: false, correct: [], attempts: 0 }; });
  return item;
}
export function subjectProgress(course) {
  if (course.passed) return 100;
  const concepts = Object.values(course.concepts);
  const practice = concepts.length ? concepts.reduce((sum, c) => sum + Math.min(3, c.correct.length) / 3, 0) / concepts.length : 0;
  const momentum = concepts.length ? concepts.filter(c => c.momentum).length / concepts.length : 0;
  return Math.min(85, Math.round((course.reviewed ? 20 : 0) + practice * 45 + momentum * 20));
}
export function recordPractice(state, item, conceptId, variant, correct) {
  const concept = item.concepts[conceptId];
  concept.attempts++;
  concept.streak = correct ? Math.min(3, concept.streak + 1) : 0;
  if (correct && !concept.correct.includes(variant)) concept.correct.push(variant);
  if (concept.streak >= 3) concept.momentum = true;
  if (correct) reward(state, `${item.session}:${item.id}:${conceptId}:${variant}`, 10);
}
export function progressPanel(state) {
  const courses = Object.values(state.courses).filter(c => c.enrolled).sort((a,b) => a.added - b.added);
  const fill = courses.length === 1 && courses[0].passed ? 100 : 0;
  const segments = courses.slice(1).map((c,i)=>`<span style="position:absolute;left:${i/(courses.length-1)*100}%;width:${100/(courses.length-1)}%;height:100%;background:${c.passed ? "#2458bf" : "#d9dde5"};transition:background .4s"></span>`).join("");
  return `<h3>Learning progress</h3><p class="small muted">${courses.filter(c => c.passed).length} of ${courses.length} courses completed</p>
    <div style="overflow-x:auto;padding:20px 4px 8px"><div style="position:relative;min-width:${Math.max(240, courses.length * 90)}px">
      <div role="progressbar" aria-label="Courses completed" aria-valuemin="0" aria-valuemax="${Math.max(1,courses.length)}" aria-valuenow="${courses.filter(c=>c.passed).length}" style="position:absolute;top:9px;left:${courses.length ? 50/courses.length : 0}%;right:${courses.length ? 50/courses.length : 0}%;height:5px;background:#d9dde5;border-radius:10px"><div style="height:100%;width:${fill}%;background:#2458bf;border-radius:10px;transition:width .4s"></div>${segments}</div>
      <div style="position:relative;display:flex;justify-content:space-between;gap:12px">${courses.map((c,i) => `<div style="flex:1;min-width:0;text-align:center"><span aria-label="${esc(c.title)}: ${c.passed ? "completed" : "in progress"}" style="display:inline-grid;place-items:center;width:24px;height:24px;border-radius:50%;background:${c.passed ? "#2458bf" : "#e0e3e9"};color:${c.passed ? "white" : "#657085"};border:3px solid white;box-sizing:border-box;font-size:11px;font-weight:700">${c.passed ? "?" : i+1}</span><div class="small muted" style="margin-top:8px;overflow-wrap:anywhere">${esc(c.title)}</div></div>`).join("") || `<p class="small muted">Add a course in Learning Studio to start your path.</p>`}</div></div></div>
    <div style="display:flex;gap:24px;border-top:1px solid #e4e8ef;margin-top:16px;padding-top:18px"><div><span aria-hidden="true" style="color:#bd6726;font-size:24px">??</span> <strong>${streakDays(state)} day streak</strong><p class="small muted">Learn each day to keep your streak.</p></div><div><strong style="color:#173f8c;font-size:23px">+${state.points}</strong><p class="small muted">Learning points</p></div></div>
    <p class="small muted">Progress saved in this browser.</p>`;
}
export function inProgressPanel(state) {
  const courses = Object.values(state.courses).filter(c => c.enrolled);
  return `<h3>Courses in progress</h3><div class="list">${courses.map(c => `<div><div style="display:flex;justify-content:space-between;gap:12px"><strong>${esc(c.title)}</strong><span class="small muted">${c.passed ? "Quiz passed" : `${subjectProgress(c)}%`}</span></div>${greenBar(subjectProgress(c), c.title)}<p class="small muted">${c.passed ? "Course completed" : "Pass the topic quiz to finish."}</p><details><summary class="small">Concept momentum</summary>${Object.values(c.concepts).map(concept=>`<p class="small">${esc(concept.title)} ? ${concept.momentum?"Momentum unlocked":`${concept.streak} / 3 correct in a row`}</p>${greenBar(concept.momentum?100:concept.streak/3*100,concept.title+" momentum")}`).join("")}</details></div>`).join("") || '<p class="muted">Select a course in Learning Studio and check ?Add to courses in progress?.</p>'}</div>`;
}
function greenBar(value, title) {
  return `<div role="progressbar" aria-label="${esc(title)} progress" aria-valuenow="${value}" aria-valuemin="0" aria-valuemax="100" style="height:7px;background:#e1e5e6;border-radius:20px;margin-top:10px;overflow:hidden"><div style="height:100%;width:${value}%;background:#248558;border-radius:20px;transition:width .4s"></div></div>`;
}
export function conceptQuestion(point, variant = 0) {
  const text = point.explanation || point.point;
  const terms = [...new Set(text.match(/[A-Za-z][A-Za-z-]{4,}/g) || [])].filter(w => !/^(their|there|these|those|which|should|would|could|about|other)$/i.test(w));
  const answer = terms[variant % Math.max(1,terms.length)] || text;
  const other = [...new Set([...terms.filter(t=>t.toLowerCase()!==answer.toLowerCase()), "unrelated", "optional", "automatic"])].slice(0,3);
  const options = [answer, ...other].sort((a,b) => {
    const score = x => [...x].reduce((sum,c) => sum + c.charCodeAt(0),variant * 17) % 101;
    return score(a) - score(b) || a.localeCompare(b);
  });
  return { prompt: `Complete this statement about ${point.point}:`, statement: text.replace(answer, "________"), answer, options };
}

export function mindMap(course) {
  const palette = [
    { ink: "#3156ba", light: "#eef3ff", edge: "#a9bdef" },
    { ink: "#14776c", light: "#ecfaf5", edge: "#91d4c4" },
    { ink: "#8652b6", light: "#f7efff", edge: "#d0b0ea" },
    { ink: "#a46316", light: "#fff8e9", edge: "#eac887" },
  ];
  const groups = (course.key_points || []).map((p, i) => ({
    title: p.point, label: `CONCEPT ${String(i + 1).padStart(2, "0")}`,
    leaves: (p.explanation || "").match(/[^.!?]+[.!?]+(?:\s|$)|[^.!?]+$/g)?.map(t => t.trim()).filter(Boolean) || [],
  }));
  if (course.recommended_review) groups.push({ title: "Put it into practice", label: "REVIEW", leaves: [course.recommended_review] });
  if (course.source_excerpt) groups.push({ title: "Connect to the source", label: "SOURCE", leaves: [course.source_excerpt] });
  if (!groups.length) groups.push({ title: "Learning objective", label: "START HERE", leaves: [course.objective || course.title] });
  // Estimate wrapped lines generously so longer course requirements stay inside their cards.
  const cardHeight = (text, chars, base) => base + Math.ceil(String(text || "").length / chars) * 23;
  let cursor = 70;
  const layout = groups.map((g, i) => {
    const leafHeights = g.leaves.map(t => Math.max(94, cardHeight(t, 46, 40)));
    const branchHeight = Math.max(cardHeight(g.title, 29, 65), leafHeights.reduce((a, h) => a + h, 0) + Math.max(0, leafHeights.length - 1) * 18);
    const result = { ...g, color: palette[i % palette.length], top: cursor, height: branchHeight, leafHeights };
    cursor += branchHeight + 42;
    return result;
  });
  const height = Math.max(440, cursor + 25);
  const centerY = height / 2;
  const objectiveHeight = Math.max(190, cardHeight(course.title, 22, 60) + cardHeight(course.objective, 28, 30));
  const node = (x, y, w, h, label, title, color, root = false) => `<foreignObject x="${x}" y="${y}" width="${w}" height="${h}"><div xmlns="http://www.w3.org/1999/xhtml" style="box-sizing:border-box;height:100%;padding:20px;border-radius:18px;border:1px solid ${root ? "#253b86" : color.edge};background:${root ? "#142663" : color.light};color:${root ? "white" : "#182747"};font:15px/1.5 system-ui,sans-serif;overflow:auto"><div style="font-size:10px;font-weight:800;letter-spacing:1.8px;color:${root ? "#b8cbff" : color.ink};margin-bottom:10px">${esc(label)}</div><div style="font-size:${root ? 20 : 16}px;font-weight:${root ? 700 : 600};overflow-wrap:anywhere">${esc(title)}</div></div></foreignObject>`;
  const curve = (x1, y1, x2, y2, color) => `<path d="M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}" fill="none" stroke="${color}" stroke-width="2.5"/><circle cx="${x2}" cy="${y2}" r="4" fill="${color}"/>`;
  return `<div style="border:1px solid #e1e7f2;border-radius:22px;background:linear-gradient(135deg,#f8faff,#f1f5fb);padding:18px">
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:10px"><strong style="color:#182b62">Your concept map</strong><span class="small muted">Course ? concepts ? details</span></div>
    <p class="small muted">Follow each colored branch. Scroll across to explore the details.</p>
    <div tabindex="0" role="region" aria-label="Scrollable course mind map" style="overflow:auto;border-radius:14px;background:radial-gradient(#dce3f0 1px,transparent 1px);background-size:18px 18px">
    <svg viewBox="0 0 1260 ${height}" style="display:block;width:100%;min-width:1080px" role="img" aria-label="Branched mind map of ${esc(course.title)}">
    <title>${esc(course.title)}</title><desc>Course objective branches into ${layout.length} topics, each connected to supporting details from the course material.</desc>
    ${layout.map(g => {
      const y = g.top + g.height / 2;
      const h = Math.max(115, cardHeight(g.title, 29, 65));
      let leafY = g.top;
      return curve(295, centerY, 405, y, g.color.edge) + node(405, y - h / 2, 320, h, g.label, g.title, g.color) + g.leaves.map((text, i) => {
        const lh = g.leafHeights[i];
        const html = curve(725, y, 820, leafY + lh / 2, g.color.edge) + node(820, leafY, 420, lh, g.label === "SOURCE" ? "SOURCE EXCERPT" : g.label === "REVIEW" ? "SUGGESTED REVIEW" : `DETAIL ${i + 1}`, text, g.color);
        leafY += lh + 18;
        return html;
      }).join("");
    }).join("")}
    ${node(15, centerY - objectiveHeight / 2, 280, objectiveHeight, "LEARNING OBJECTIVE", course.title + (course.objective ? " ? " + course.objective : ""), palette[0], true)}
    </svg></div></div>`;
}

export async function reviewStudio(view, go, assignedCourses, user) {
  stopSpeaking();
  loading(view);
  try {
    const data = await api.get("/api/diagnostic/review-courses");
    if (!view.isConnected) return;
    const state = readProgress(user);
    data.courses.forEach(c => trackCourse(state, c, data.session_id));
    if (!data.courses.some(c => c.id === selected)) selected = data.courses[0]?.id || null;
    const course = data.courses.find(c => c.id === selected);
    const item = course ? trackCourse(state, course, data.session_id) : null;
    const redraw = () => reviewStudio(view, go, assignedCourses, user);
    view.innerHTML = `<div class="card-head"><h1>Learning studio</h1></div>
      <p class="muted">Choose a course and a format. Build momentum with practice, then pass the topic quiz to finish.</p>
      <section class="card" id="studio-progress" style="margin-bottom:18px">${progressPanel(state)}</section>
      <div class="grid side"><section class="card"><h2>Your review courses</h2>
      <div class="list">${data.courses.map(c => {
        const saved = trackCourse(state,c,data.session_id);
        return `<button class="item ${c.id === selected ? "active" : ""}" style="text-align:left;font:inherit;cursor:pointer;display:block" data-course="${esc(c.id)}" aria-pressed="${c.id === selected}"><strong>${esc(c.title)}</strong><p class="small muted">Priority ${esc(c.importance)} ? ${saved.passed ? "Quiz passed" : saved.enrolled ? "In progress" : "Ready to start"}</p><div data-course-progress="${esc(c.id)}">${saved.enrolled ? greenBar(subjectProgress(saved),c.title) : ""}</div></button>`;
      }).join("") || `<p>${data.session_id ? "No review courses indicated by your latest diagnostic." : "Complete a diagnostic to build your review courses."}</p><button class="btn" id="studio-diagnostic">Take diagnostic</button>`}</div>
      <button class="btn secondary" id="assigned-courses" style="margin-top:16px">Browse assigned courses</button></section>
      <section id="review-workspace" class="card">${course ? `<h2>${esc(course.title)}</h2>
        <label style="display:flex;gap:8px;align-items:center;color:#7a8391;font-size:13px;font-weight:300;margin:4px 0 18px"><span>[</span><input id="course-enroll" type="checkbox" ${item.enrolled ? "checked" : ""} style="accent-color:#248558;width:18px;height:18px"><span>${item.enrolled ? '<span style="color:#248558">? Added to courses in progress</span>' : "Select if you want to add to courses in progress"}</span><span>]</span></label>
        <div id="subject-progress">${greenBar(subjectProgress(item),course.title)}<p class="small muted">${subjectProgress(item)}% ? ${item.passed ? "Topic quiz passed" : "A topic quiz is required for completion"}</p></div>
        <div class="toolbar"><label class="field">Delivery<select id="review-format"><option value="text">Text</option><option value="mindmap">Mind map</option><option value="audio">Audio</option></select></label><button class="btn secondary" id="start-topic-quiz">${item.passed ? "Retake topic quiz" : "Start topic quiz"}</button></div>
        <section id="concept-practice" style="margin:20px 0"></section>
        <div id="topic-quiz"></div><div id="review-content" style="margin-top:20px"></div>
        <p class="small muted">Momentum lets you skip the remaining review and go straight to the quiz. Required training obligations remain separately tracked.</p>
        <button class="btn secondary" id="review-complete">${item.reviewed ? "Material reviewed" : "Mark material reviewed"}</button><p id="review-status" role="status"></p>` : '<h2>Learn your way</h2><p>Select a course to get started.</p>'}</section></div>`;
    $("#studio-diagnostic",view)?.addEventListener("click",()=>go("diagnostic"));
    $("#assigned-courses",view)?.addEventListener("click",assignedCourses);
    $$("[data-course]",view).forEach(b=>b.onclick=()=>{selected=b.dataset.course;redraw();});
    if (!course) return;
    const persist = () => { saveProgress(user,state); };
    const refreshProgress = () => {
      $("#studio-progress",view).innerHTML=progressPanel(state);
      $$("[data-course-progress]",view).filter(node=>node.dataset.courseProgress===course.id).forEach(node=>{node.innerHTML=item.enrolled?greenBar(subjectProgress(item),course.title):"";});
      $("#subject-progress",view).innerHTML = `${greenBar(subjectProgress(item),course.title)}<p class="small muted">${subjectProgress(item)}% ? ${item.passed ? "Topic quiz passed" : "A topic quiz is required for completion"}</p>`;
    };
    $("#course-enroll",view).onchange = event => {
      item.enrolled = event.target.checked;
      try { persist(); redraw(); } catch(error) { event.target.checked=!item.enrolled; $("#review-status",view).textContent="Unable to save progress in this browser. " + error.message; }
    };
    const render = () => {
      stopSpeaking();
      const text = `<h3>Learning objective</h3><p>${esc(course.objective)}</p>${course.key_points.map(p=>`<h3>${esc(p.point)}</h3><p>${esc(p.explanation)}</p>`).join("")}<h3>Source material</h3><blockquote>${esc(course.source_excerpt)}</blockquote><p>${esc(course.recommended_review)}</p>`;
      const content = $("#review-content",view);
      content.innerHTML = format === "mindmap" ? mindMap(course) : format === "audio" ? `<h3>Listen to this course</h3><div class="toolbar"><button class="btn" id="review-play" ${canSpeak()?"":"disabled"}>Play audio</button><button class="btn secondary" id="review-stop">Stop audio</button></div>${!canSpeak()?'<p>Audio is unavailable in this browser. Read the transcript below.</p>':""}<details><summary>Audio transcript</summary>${text}</details>` : text;
      const url = /^https:\/\//i.test(course.attribution.url || "") ? course.attribution.url : null;
      content.innerHTML += `<p class="small muted">${url?`<a href="${esc(url)}" target="_blank" rel="noopener">${esc(course.attribution.name)}</a>`:esc(course.attribution.name)} ? ${esc(course.attribution.license)}</p>`;
      $("#review-play",view)?.addEventListener("click",e=>speak([course.title,course.objective,...course.key_points.map(p=>`${p.point}. ${p.explanation}`),course.source_excerpt,course.recommended_review].join("\n\n"),e.currentTarget));
      $("#review-stop",view)?.addEventListener("click",stopSpeaking);
    };
    $("#review-format",view).value=format;
    $("#review-format",view).onchange=e=>{format=e.target.value;render();};
    render();
    function renderConcepts() {
      $("#concept-practice",view).innerHTML=`<h3>Concept momentum</h3><p class="small muted">Three correct answers in a row unlock momentum for that concept.</p><div class="list">${course.key_points.map((p,i)=>{
        const c=item.concepts[p.id||p.point];
        return `<section style="border:1px solid #e0e7e4;border-radius:12px;padding:14px"><strong>${esc(p.point)}</strong>${greenBar(c.momentum?100:c.streak/3*100,p.point+" momentum")}<p class="small muted">${c.momentum?"Momentum unlocked ? review shortcut earned":`${c.streak} / 3 consecutive correct`}</p><button class="btn secondary small" data-practice="${i}">Practice concept</button>${c.momentum?'<button class="btn small" data-skip-review style="margin-left:8px">Skip review ? topic quiz</button>':""}<div data-practice-question="${i}"></div></section>`;
      }).join("")}</div>`;
      $$("[data-practice]",view).forEach(b=>b.onclick=()=>practiceConcept(Number(b.dataset.practice)));
      $$("[data-skip-review]",view).forEach(b=>b.onclick=startQuiz);
    }
    function practiceConcept(index) {
      stopSpeaking();
      const p=course.key_points[index], c=item.concepts[p.id||p.point], variant=c.attempts%3;
      const question=conceptQuestion(p,variant);
      const box=$(`[data-practice-question="${index}"]`,view);
      box.innerHTML=`<form style="margin-top:14px"><p><strong>${esc(question.prompt)}</strong></p><p>${esc(question.statement)}</p>${question.options.map((o,i)=>`<label class="item"><input required type="radio" name="concept-answer" value="${i}"> ${esc(o)}</label>`).join("")}<button class="btn small" style="margin-top:10px">Check answer</button><p role="status"></p></form>`;
      $("form",box).onsubmit=event=>{
        event.preventDefault();
        const button=$('button',box);if(button.disabled)return;button.disabled=true;
        const answer=question.options[Number(new FormData(event.target).get("concept-answer"))];
        const correct=answer===question.answer;
        recordPractice(state,item,p.id||p.point,variant,correct);
        try {persist();refreshProgress();renderConcepts();const feedback=$(`[data-practice-question="${index}"]`,view);feedback.innerHTML=`<p role="status">${correct?"Correct. ":"Not quite. "}${esc(p.explanation)}${item.concepts[p.id||p.point].momentum?" Momentum unlocked ? you can go straight to the quiz.":""}</p>`;} catch(error){$("p[role=status]",box).textContent="Could not save: "+error.message;}
      };
    }
    function startQuiz() {
      stopSpeaking();
      const questions=course.key_points.map((p,i)=>conceptQuestion(p,(i+1)%3));
      const box=$("#topic-quiz",view);
      if (!questions.length) {box.innerHTML='<p role="alert">This course has no quiz material available yet.</p>';return;}
      box.innerHTML=`<section style="background:#f5f8fe;border:1px solid #cfdbef;border-radius:14px;padding:18px"><h3>Topic quiz</h3><p>Answer every question. Score at least 80% to complete this course.</p><form id="topic-quiz-form">${questions.map((q,i)=>`<fieldset style="border:0;padding:10px 0"><legend>${i+1}. ${esc(q.prompt)}</legend><p>${esc(q.statement)}</p>${q.options.map((o,j)=>`<label class="item"><input type="radio" required name="quiz-${i}" value="${j}"> ${esc(o)}</label>`).join("")}</fieldset>`).join("")}<button class="btn">Submit topic quiz</button><p id="quiz-result" role="status"></p></form></section>`;
      box.scrollIntoView({behavior:"smooth",block:"start"});
      $("#topic-quiz-form",view).onsubmit=async event=>{
        event.preventDefault();const button=$('button',event.target);if(button.disabled)return;button.disabled=true;
        const answers=new FormData(event.target);
        const score=questions.filter((q,i)=>q.options[Number(answers.get(`quiz-${i}`))]===q.answer).length;
        const passed=score/questions.length>=.8;
        if(passed){
          item.passed=true;
          reward(state,`${item.session}:${item.id}:quiz`,50);
        }
        try {
          persist();
          if(passed){
            await api.post(`/api/diagnostic/sessions/${encodeURIComponent(data.session_id)}/review-courses/${encodeURIComponent(course.id)}/complete`,{}, {retry:false});
            item.reviewed=true;persist();await redraw();$("#review-status",view).textContent=`Quiz passed: ${score} / ${questions.length}. Course complete!`;
          } else {$("#quiz-result",view).innerHTML=`${score} / ${questions.length} correct. Review the concepts and try again. ${questions.map((q,i)=>`<p>${i+1}. ${esc(course.key_points[i].explanation)}</p>`).join("")}`;button.disabled=false;}
        } catch(error){$("#quiz-result",view).textContent="Your browser progress was saved if storage is available, but syncing the review failed. "+error.message;button.disabled=false;}
      };
    }
    renderConcepts();
    $("#start-topic-quiz",view).onclick=startQuiz;
    const button=$("#review-complete",view);button.disabled=item.reviewed;
    button.onclick=async()=>{
      button.disabled=true;
      try {await api.post(`/api/diagnostic/sessions/${encodeURIComponent(data.session_id)}/review-courses/${encodeURIComponent(course.id)}/complete`,{},{retry:false});item.reviewed=true;reward(state,`${item.session}:${item.id}:review`,5);persist();await redraw();}
      catch(error){$("#review-status",view).textContent=error.message;button.disabled=false;}
    };
    const observer=new MutationObserver(()=>{if(!view.contains(button)){stopSpeaking();observer.disconnect();}});
    observer.observe(view,{childList:true,subtree:true});
  } catch(error) {
    view.innerHTML=`<section class="card"><h1>Learning studio</h1><p role="alert">${esc(error.message)}</p><button class="btn" id="studio-retry">Try again</button></section>`;
    $("#studio-retry",view).onclick=()=>reviewStudio(view,go,assignedCourses,user);
  }
}
