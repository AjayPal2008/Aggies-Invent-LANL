import { api, esc, $, $$, loading } from "/shared/api.js?v=20261025a";
import { stopSpeaking } from "/shared/a11y.js?v=20261025a";
import { DELIVERY_MODES, getLessonSections, renderLessonContent } from "./lesson-content.js?v=20261025a";

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

function courseFamily(course) {
  const title = course.title.toLowerCase();
  const families = [
    ["transport", /hmpt|transportation|movement by highway|preparing shipments/],
    ["confined", /confined space/], ["forklift", /forklift/], ["pressure", /pressure safety|compression fittings|gas cylinder/],
    ["crane", /crane|materials handling/], ["fall", /fall protection|ladder/],
    ["waste", /hazwoper|hazardous waste|rcra|waste generation/], ["chemical", /chemical|asbestos|beryllium|lead safety/],
    ["radiation", /radiation|nuclear|radioactive/], ["electrical", /electrical/], ["laser", /laser/],
  ];
  return families.find(([,pattern])=>pattern.test(title))?.[0] || null;
}
function foundationLevel(course) {
  const title=course.title.toLowerCase();
  if(/introduction|fundamentals|awareness|orientation/.test(title))return 0;
  if(/advanced|supervisor|qualified|instructor|competent person|rescue/.test(title))return 2;
  return 1;
}

export function generateLearningPaths(courses, state, session) {
  const saved = c => trackCourse(state,c,c.progress_session || session);
  const targets = courses.filter(c=>saved(c).enrolled&&!saved(c).passed);
  if(!targets.length)return [];
  const byId=new Map(courses.map(c=>[c.id,c]));
  const targetIds=new Set(targets.map(c=>c.id));
  const rank=(a,b)=>foundationLevel(a)-foundationLevel(b) || (b.importance||0)-(a.importance||0) || a.title.localeCompare(b.title);
  const routes=targets.sort(rank).map(target=>{
    const entries=new Map(),visiting=new Set();
    function add(course,reason) {
      if(visiting.has(course.id)||entries.has(course.id)||saved(course).passed)return;
      visiting.add(course.id);
      (course.prerequisites||[]).forEach(id=>{if(byId.has(id))add(byId.get(id),"Prerequisite for "+course.title);});
      visiting.delete(course.id);entries.set(course.id,{course,reason});
    }
    // These title-based preparation suggestions are recommendations, not official prerequisites.
    const family=courseFamily(target);
    const related=courses.filter(c=>c.id!==target.id && family && courseFamily(c)===family && !saved(c).passed).sort(rank);
    const foundations=related.filter(c=>foundationLevel(c)===0);
    const candidates=[...foundations,...related.filter(c=>!foundations.includes(c))];
    const needed=Math.max(0,Math.min(4,4-(target.prerequisites||[]).length));
    candidates.slice(0,needed).forEach(c=>add(c,(foundationLevel(c)>foundationLevel(target)?"Suggested next course: ":"Suggested preparation: ")+family+" concepts"));
    add(target,"Your selected course");
    return {targets:[target.id],entries};
  });
  // Connected routes become one path, including transitive overlaps (A/B and B/C).
  for(let i=0;i<routes.length;i++)for(let j=i+1;j<routes.length;){
    if([...routes[j].entries.keys()].some(id=>routes[i].entries.has(id))){
      routes[j].entries.forEach((entry,id)=>{if(!routes[i].entries.has(id))routes[i].entries.set(id,entry);});
      routes[i].targets.push(...routes[j].targets);routes.splice(j,1);j=i+1;
    }else j++;
  }
  return routes.map((route,index)=>{
    const ordered=[],visited=new Set(),visiting=new Set();
    const entries=[...route.entries.values()].sort((a,b)=>rank(a.course,b.course));
    function visit(entry){
      const c=entry.course;if(visited.has(c.id)||visiting.has(c.id))return;
      visiting.add(c.id);
      (c.prerequisites||[]).forEach(id=>{if(route.entries.has(id))visit(route.entries.get(id));});
      visiting.delete(c.id);visited.add(c.id);ordered.push(entry);
    }
    entries.forEach(visit);
    return {id:`path-${index+1}`,targets:[...new Set(route.targets)],title:route.targets.map(id=>byId.get(id).title).join(" + "),courses:ordered.map(({course:c,reason})=>{
      const item=saved(c),concepts=Object.values(item.concepts),momentum=concepts.length>0&&concepts.every(p=>p.momentum);
      return {id:c.id,title:c.title,selected:targetIds.has(c.id),reason:targetIds.has(c.id)?"Your selected course":reason,next:momentum?"quiz":item.reviewed?"practice":"review",steps:momentum?["Momentum earned","Pass topic quiz"]:["Review","Practice concepts","Pass topic quiz"]};
    })};
  });
}

export function learningPathsHtml(paths) {
  if(!paths?.length)return '<p class="small muted">Select at least one unfinished course, then generate your recommendations.</p>';
  return paths.map((path,index)=>`<details style="border:1px solid #dce4ee;border-radius:14px;padding:16px;margin-top:12px;background:#fafbfd"><summary style="cursor:pointer;color:#153c87;font-weight:700">Path ${String(index+1).padStart(2,"0")} <span style="font-weight:400;color:#6a7585;font-size:13px"> ? ${path.courses.length} courses ? ${path.targets.length} selected</span></summary><p class="small muted" style="margin-top:14px">${esc(path.title)}</p><ol style="padding-left:22px">${path.courses.map(t=>`<li style="margin:12px 0;padding:14px;border-radius:12px;border:1px solid ${t.selected?"#96c9ac":"#e0e5ec"};background:${t.selected?"#ecf8f0":"white"}"><strong style="color:${t.selected?"#1d7247":"#182747"}">${esc(t.title)}</strong>${t.selected?'<span class="badge ok" style="margin-left:8px">Selected</span>':""}<p class="small muted">${esc(t.reason)}</p><p class="small muted">${t.steps.map(esc).join(" &rarr; ")}</p><button class="btn secondary small" data-path-course="${esc(t.id)}" data-path-action="${esc(t.next)}">Open course</button></li>`).join("")}</ol></details>`).join("");
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
    const [data, materials] = await Promise.all([api.get("/api/diagnostic/review-courses"),api.get("/api/diagnostic/material-courses")]);
    data.courses = [...data.courses, ...materials.courses];
    if (!view.isConnected) return;
    const state = readProgress(user);
    data.courses.forEach(c => trackCourse(state, c, c.progress_session || data.session_id));
    if (!data.courses.some(c => c.id === selected)) selected = data.courses[0]?.id || null;
    const selectedCourses=data.courses.filter(c=>trackCourse(state,c,c.progress_session||data.session_id).enrolled);
    const canGenerate=selectedCourses.some(c=>!trackCourse(state,c,c.progress_session||data.session_id).passed);
    if(state.pathGroups?.length)state.pathGroups=generateLearningPaths(data.courses,state,data.session_id);
    const course = data.courses.find(c => c.id === selected);
    const item = course ? trackCourse(state, course, course.progress_session || data.session_id) : null;
    const redraw = () => reviewStudio(view, go, assignedCourses, user);
    view.innerHTML = `<link rel="stylesheet" href="/hire/studio.css?v=20261025a"><div class="card-head"><h1>Learning studio</h1></div>
      <p class="muted">Choose a course and a format. Build momentum with practice, then pass the topic quiz to finish.</p>
      <section class="card" style="margin-bottom:18px"><div class="card-head"><h2>Your learning paths</h2><button class="btn" id="generate-path" ${canGenerate?"":"disabled"}>Generate paths</button></div><p class="small muted">Check the courses you want to take. Recommendations usually contain 3&ndash;5 related courses, with foundations first. Paths sharing courses are merged; selected courses appear in green. Preparation suggestions are not official training prerequisites.</p><p class="small muted">${selectedCourses.length} course${selectedCourses.length===1?"":"s"} selected${canGenerate?"":" ? Select an unfinished course to enable generation"}.</p><div id="generated-path">${learningPathsHtml(state.pathGroups)}</div></section>
      <section class="card" id="studio-progress" style="margin-bottom:18px">${progressPanel(state)}</section>
      <div class="studio-layout"><section class="card studio-selection"><h2>1. Select your courses</h2><p class="small muted">Diagnostic reviews and Survey &amp; Materials PDF topics</p>
      <div class="studio-course-grid">${data.courses.map(c => {
        const saved = trackCourse(state,c,c.progress_session || data.session_id);
        return `<button class="item ${c.id === selected ? "active" : ""}" style="text-align:left;font:inherit;cursor:pointer;display:block;${saved.enrolled?"background:#ecf8f0;border:1px solid #96c9ac;box-shadow:inset 4px 0 #248558;":""}" data-course="${esc(c.id)}" aria-pressed="${c.id === selected}"><strong style="${saved.enrolled?"color:#1d7247":""}">${esc(c.title)}</strong>${saved.enrolled?'<span class="badge ok" style="margin-left:8px">Selected</span>':""}<p class="small muted">Priority ${esc(c.importance)} ? ${c.origin === "survey-materials" ? "PDF topic ? " : "Diagnostic review ? "}${saved.passed ? "Quiz passed" : saved.enrolled ? "In progress" : "Ready to start"}</p><div data-course-progress="${esc(c.id)}">${saved.enrolled ? greenBar(subjectProgress(saved),c.title) : ""}</div></button>`;
      }).join("") || `<p>${data.session_id ? "No review courses indicated by your latest diagnostic." : "Complete a diagnostic to build your review courses."}</p><button class="btn" id="studio-diagnostic">Take diagnostic</button>`}</div>
      <button class="btn secondary" id="assigned-courses" style="margin-top:16px">Browse assigned courses</button></section>
      <section id="review-workspace" class="card studio-lesson">${course ? `<h2 style="${item.enrolled?"color:#1d7247":""}">${esc(course.title)}</h2>
        <label style="display:flex;gap:8px;align-items:center;color:#7a8391;font-size:13px;font-weight:300;margin:4px 0 18px"><span>[</span><input id="course-enroll" type="checkbox" ${item.enrolled ? "checked" : ""} style="accent-color:#248558;width:18px;height:18px"><span>${item.enrolled ? '<span style="color:#248558">&#10003; Added to courses in progress</span>' : "Select if you want to add to courses in progress"}</span><span>]</span></label>
        <div id="subject-progress">${greenBar(subjectProgress(item),course.title)}<p class="small muted">${subjectProgress(item)}% ? ${item.passed ? "Topic quiz passed" : "A topic quiz is required for completion"}</p></div>
        <section class="studio-delivery" aria-labelledby="delivery-heading"><span class="studio-eyebrow">2. Choose how to learn</span><h3 id="delivery-heading">Your lesson, in your preferred format</h3><p class="muted">Each format covers the same expanded material. Short checkpoints are woven through the lesson, and the final quiz completes the topic.</p><label class="sr-only">Delivery<select id="review-format">${DELIVERY_MODES.map(m=>`<option value="${m.id}">${esc(m.title)}</option>`).join("")}</select></label><div class="studio-media-options">${DELIVERY_MODES.map(m=>`<button type="button" class="studio-media-option" data-media-mode="${m.id}" aria-pressed="${m.id===format}"><span class="studio-mode-icon" aria-hidden="true">${m.icon}</span><strong>${esc(m.title)}</strong><span class="small muted">${esc(m.description)}</span></button>`).join("")}</div><div class="toolbar"><p class="small muted" style="flex:1">Your checkpoint answers contribute to concept momentum. Switching format keeps your progress.</p><button class="btn secondary" id="start-topic-quiz">${item.passed ? "Retake final topic quiz" : "Start final topic quiz"}</button></div></section>
        <div id="review-content"></div><section id="concept-practice" style="margin:24px 0"></section><div id="topic-quiz"></div>
        <p class="small muted">Momentum lets you skip the remaining review and go straight to the quiz. Required training obligations remain separately tracked.</p>
        <button class="btn secondary" id="review-complete">${item.reviewed ? "Material reviewed" : "Mark material reviewed"}</button><p id="review-status" role="status"></p>` : '<h2>Learn your way</h2><p>Select a course to get started.</p>'}</section></div>`;
    $("#studio-diagnostic",view)?.addEventListener("click",()=>go("diagnostic"));
    $("#assigned-courses",view)?.addEventListener("click",assignedCourses);
    $$("[data-course]",view).forEach(b=>b.onclick=async()=>{selected=b.dataset.course;await redraw();$("#review-workspace",view)?.scrollIntoView({behavior:"smooth",block:"start"});});
    $("#generate-path",view).onclick=()=>{
      try {
        if(!canGenerate)return;
        state.pathGroups=generateLearningPaths(data.courses,state,data.session_id);
        delete state.path;
        saveProgress(user,state);redraw();
      } catch(error){$("#generated-path",view).textContent="Could not save path: "+error.message;}
    };
    $$("[data-path-course]",view).forEach(b=>b.onclick=async()=>{
      selected=b.dataset.pathCourse;await redraw();
      if(b.dataset.pathAction==="quiz")$("#start-topic-quiz",view)?.click();
    });
    if (!course) return;
    const completionUrl=course.origin==="survey-materials"?`/api/diagnostic/materials/${encodeURIComponent(course.id)}/complete`:`/api/diagnostic/sessions/${encodeURIComponent(data.session_id)}/review-courses/${encodeURIComponent(course.id)}/complete`;
    const persist = () => { saveProgress(user,state); };
    const refreshProgress = () => {
      $("#studio-progress",view).innerHTML=progressPanel(state);
      $$("[data-course-progress]",view).filter(node=>node.dataset.courseProgress===course.id).forEach(node=>{node.innerHTML=item.enrolled?greenBar(subjectProgress(item),course.title):"";});
      $("#subject-progress",view).innerHTML = `${greenBar(subjectProgress(item),course.title)}<p class="small muted">${subjectProgress(item)}% ? ${item.passed ? "Topic quiz passed" : "A topic quiz is required for completion"}</p>`;
    };
    $("#course-enroll",view).onchange = event => {
      item.enrolled = event.target.checked;
      delete state.pathGroups;
      delete state.path;
      try { persist(); redraw(); } catch(error) { event.target.checked=!item.enrolled; $("#review-status",view).textContent="Unable to save progress in this browser. " + error.message; }
    };
    let disposeLesson=()=>{};
    const render = () => {
      disposeLesson();
      item.checkpoints ||= {};
      $$("[data-media-mode]",view).forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.mediaMode===format)));
      disposeLesson=renderLessonContent($("#review-content",view),course,{
        mode:format,mindMap,makeQuestion:conceptQuestion,
        getCheckpoint:key=>item.checkpoints[key],
        onCheckpoint:(conceptId,key,correct,choice)=>{
          if(item.checkpoints[key]?.correct)return;
          const id=item.concepts[conceptId]?conceptId:Object.keys(item.concepts)[0];
          if(id)recordPractice(state,item,id,"lesson:"+key,correct);
          item.checkpoints[key]={correct,choice};persist();refreshProgress();renderConcepts();
        },
      });
    };
    $("#review-format",view).value=format;
    $("#review-format",view).onchange=event=>{format=event.target.value;render();};
    $$("[data-media-mode]",view).forEach(button=>button.onclick=()=>{format=button.dataset.mediaMode;$("#review-format",view).value=format;render();});
    render();
    function renderConcepts() {
      $("#concept-practice",view).innerHTML=`<details class="studio-more"><summary>Concept momentum and extra practice</summary><p class="small muted">Three correct answers in a row unlock momentum for that concept. Lesson checkpoints also count.</p><div class="list">${course.key_points.map((p,i)=>{
        const c=item.concepts[p.id||p.point];
        return `<section style="border:1px solid #e0e7e4;border-radius:12px;padding:14px"><strong>${esc(p.point)}</strong>${greenBar(c.momentum?100:c.streak/3*100,p.point+" momentum")}<p class="small muted">${c.momentum?"Momentum unlocked ? review shortcut earned":`${c.streak} / 3 consecutive correct`}</p><button class="btn secondary small" data-practice="${i}">Practice concept</button>${c.momentum?'<button class="btn small" data-skip-review style="margin-left:8px">Skip review ? topic quiz</button>':""}<div data-practice-question="${i}"></div></section>`;
      }).join("")}</div></details>`;
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
      const quizSections=getLessonSections(course);
      const questions=quizSections.map((section,i)=>conceptQuestion({point:section.title,explanation:section.explanation},(i+1)%3));
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
            await api.post(completionUrl,{}, {retry:false});
            item.reviewed=true;persist();await redraw();$("#review-status",view).textContent=`Quiz passed: ${score} / ${questions.length}. Course complete!`;
          } else {$("#quiz-result",view).innerHTML=`${score} / ${questions.length} correct. Review the concepts and try again. ${questions.map((q,i)=>`<p>${i+1}. ${esc(quizSections[i].explanation)}</p>`).join("")}`;button.disabled=false;}
        } catch(error){$("#quiz-result",view).textContent="Your browser progress was saved if storage is available, but syncing the review failed. "+error.message;button.disabled=false;}
      };
    }
    renderConcepts();
    $("#start-topic-quiz",view).onclick=startQuiz;
    const button=$("#review-complete",view);button.disabled=item.reviewed;
    button.onclick=async()=>{
      button.disabled=true;
      try {await api.post(completionUrl,{},{retry:false});item.reviewed=true;reward(state,`${item.session}:${item.id}:review`,5);persist();await redraw();}
      catch(error){$("#review-status",view).textContent=error.message;button.disabled=false;}
    };
    const observer=new MutationObserver(()=>{if(!view.contains(button)){disposeLesson();observer.disconnect();}});
    observer.observe(view,{childList:true,subtree:true});
  } catch(error) {
    view.innerHTML=`<section class="card"><h1>Learning studio</h1><p role="alert">${esc(error.message)}</p><button class="btn" id="studio-retry">Try again</button></section>`;
    $("#studio-retry",view).onclick=()=>reviewStudio(view,go,assignedCourses,user);
  }
}
