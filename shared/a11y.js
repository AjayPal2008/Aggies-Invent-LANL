// Accessibility settings, panel, read-aloud and page-level keyboard/screen reader support.
//
// Settings are saved in the browser right away and, once signed in, to the person's account
// (/api/me/accessibility) so they follow them to any device. Managers never see them.
import { api, esc, session, toast } from "/shared/api.js?v=20261025a";

export const DEFAULTS = {
  textScale: 1, contrast: "standard", colorVision: "standard", font: "standard",
  spacing: false, underline: false, targets: false, reduceMotion: undefined,
  readAloud: true, speechRate: 1,
  captions: "on", captionSize: 1, captionStyle: "standard", showTranscript: false,
  extraTime: 1,
};
const KEY = "lanl_a11y";
const FONT_URL = "https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400&display=swap";
let state = { ...DEFAULTS, ...load() };
let saveTimer = null;
const listeners = new Set();

function load() { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; } }

export function settings() { return { ...state }; }
export function onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }

export function update(patch, { remote = true } = {}) {
  state = { ...state, ...patch };
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* private mode */ }
  apply();
  listeners.forEach((fn) => fn(state));
  if (remote && session.token) {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => api.put("/api/me/accessibility", state).catch(() => {}), 500);
  }
}

export function apply() {
  const root = document.documentElement;
  const scale = Number(state.textScale) || 1;
  root.style.setProperty("--text-scale", scale);
  root.style.setProperty("--cap-scale", Number(state.captionSize) || 1);
  const reduce = state.reduceMotion === undefined ? matchMedia("(prefers-reduced-motion: reduce)").matches : state.reduceMotion;
  const classes = {
    "a11y-contrast-light": state.contrast === "high-light",
    "a11y-contrast-dark": state.contrast === "high-dark",
    "a11y-cvd": state.colorVision === "cvd",
    "a11y-font-readable": state.font === "readable",
    "a11y-spacing": !!state.spacing,
    "a11y-underline": !!state.underline,
    "a11y-targets": !!state.targets,
    "a11y-large-text": scale >= 1.5,
    "a11y-reduce-motion": !!reduce,
    "a11y-cap-contrast": state.captionStyle === "high-contrast",
    "a11y-cap-off": state.captions === "off",
  };
  Object.entries(classes).forEach(([c, on]) => root.classList.toggle(c, on));
  if (state.font === "readable" && !document.querySelector(`link[href="${FONT_URL}"]`)) {
    document.head.append(Object.assign(document.createElement("link"), { rel: "stylesheet", href: FONT_URL }));
  }
}

/** Pull the account's settings after sign-in; push local ones up if the account has none yet. */
export async function syncWithAccount() {
  if (!session.token) return;
  try {
    const remote = await api.get("/api/me/accessibility");
    if (remote && Object.keys(remote).length) update(remote, { remote: false });
    else if (JSON.stringify(load()) !== "{}") await api.put("/api/me/accessibility", state);
  } catch { /* offline or signed out: keep local settings */ }
}

// ---- read aloud ------------------------------------------------------------------------

const synth = window.speechSynthesis;
let speakingBtn = null;

export function canSpeak() { return !!synth; }

export function speak(text, btn = null) {
  if (!synth) { toast("Read aloud isn't available in this browser", true); return; }
  const same = speakingBtn && speakingBtn === btn;
  stopSpeaking();
  if (same) return; // second press stops
  const u = new SpeechSynthesisUtterance(text);
  u.rate = Number(state.speechRate) || 1;
  if (btn) { speakingBtn = btn; btn.setAttribute("aria-pressed", "true"); btn.dataset.label ||= btn.textContent; btn.textContent = "■ Stop"; }
  u.onend = u.onerror = () => stopSpeaking();
  synth.speak(u);
}

export function stopSpeaking() {
  synth?.cancel();
  if (speakingBtn) {
    speakingBtn.setAttribute("aria-pressed", "false");
    speakingBtn.textContent = speakingBtn.dataset.label || "🔊 Read aloud";
    speakingBtn = null;
  }
}

/** A read-aloud button for the nearest [data-speak-scope] (or a selector). Hidden when the setting is off. */
export function speakButton(label = "Read aloud") {
  if (!state.readAloud || !synth) return "";
  return `<button type="button" class="btn ghost small speak" data-speak aria-pressed="false" aria-label="${esc(label)}">🔊 ${esc(label)}</button>`;
}

function textOf(el) {
  const clone = el.cloneNode(true);
  clone.querySelectorAll("button.speak, [data-speak-skip], script, style").forEach((n) => n.remove());
  clone.querySelectorAll("button.choice").forEach((b, i) => b.prepend(`Option ${i + 1}: `));
  return clone.innerText.replace(/\s+\n/g, "\n").trim();
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-speak]");
  if (!btn) return;
  e.preventDefault();
  e.stopPropagation();
  const target = btn.dataset.speakTarget ? document.querySelector(btn.dataset.speakTarget) : btn.closest("[data-speak-scope]");
  if (target) speak(textOf(target), btn);
});

// ---- panel ------------------------------------------------------------------------------

function radio(name, value, label, current) {
  return `<label><input type="radio" name="${name}" value="${value}" ${String(current) === String(value) ? "checked" : ""}><span>${label}</span></label>`;
}
function check(name, label, help, on) {
  return `<label><input type="checkbox" name="${name}" ${on ? "checked" : ""}><span><strong>${label}</strong><br><span class="small muted">${help}</span></span></label>`;
}

export async function openPanel() {
  const { modal } = await import("/shared/api.js?v=20261025a");
  const s = state;
  const reduce = s.reduceMotion === undefined ? matchMedia("(prefers-reduced-motion: reduce)").matches : s.reduceMotion;
  const m = modal(`
    <div class="modal-head"><h2 id="a11y-title">Accessibility</h2><button class="btn ghost" data-close>Done</button></div>
    <p class="small muted">Changes apply right away and are saved to your account. Shortcut: Alt + A.</p>
    <form class="a11y-panel" id="a11y-form">
      <fieldset><legend>Text size</legend><div class="opts">
        ${[[1, "100%"], [1.25, "125%"], [1.5, "150%"], [1.75, "175%"], [2, "200%"]].map(([v, l]) => radio("textScale", v, l, s.textScale)).join("")}</div></fieldset>
      <fieldset><legend>Contrast</legend><div class="opts">
        ${radio("contrast", "standard", "Standard", s.contrast)}${radio("contrast", "high-light", "High contrast (light)", s.contrast)}${radio("contrast", "high-dark", "High contrast (dark)", s.contrast)}</div></fieldset>
      <fieldset><legend>Color vision</legend><div class="opts">
        ${radio("colorVision", "standard", "Standard colors", s.colorVision)}${radio("colorVision", "cvd", "Color-blind safe (blue / orange, with symbols)", s.colorVision)}</div></fieldset>
      <fieldset><legend>Reading</legend><div class="opts">
        ${radio("font", "standard", "Standard font", s.font)}${radio("font", "readable", "Low-vision font (Atkinson Hyperlegible)", s.font)}</div>
        <div class="toggles">
          ${check("spacing", "Extra line and letter spacing", "Easier to track lines of text.", s.spacing)}
          ${check("underline", "Underline links", "Links don't rely on color.", s.underline)}
          ${check("targets", "Bigger buttons and checkboxes", "Larger click and tap targets.", s.targets)}
          ${check("reduceMotion", "Reduce motion", "Turns off animations and transitions.", reduce)}
        </div></fieldset>
      <fieldset><legend>Read aloud</legend>
        <div class="toggles">${check("readAloud", "Show Read aloud buttons", "On lessons, quiz and interview questions, and tutor replies.", s.readAloud)}</div>
        <div class="opts">${[[0.75, "Slower"], [1, "Normal"], [1.25, "Faster"], [1.5, "Fastest"]].map(([v, l]) => radio("speechRate", v, l, s.speechRate)).join("")}</div>
        <button type="button" class="btn secondary small" id="a11y-test-voice" style="margin-top:8px">Test the voice</button></fieldset>
      <fieldset><legend>Video captions</legend><div class="opts">
        ${radio("captions", "on", "Captions on", s.captions)}${radio("captions", "off", "Captions off", s.captions)}</div>
        <div class="opts" style="margin-top:6px">${[[1, "Normal size"], [1.5, "Large"], [2, "Extra large"]].map(([v, l]) => radio("captionSize", v, l, s.captionSize)).join("")}</div>
        <div class="opts" style="margin-top:6px">${radio("captionStyle", "standard", "Standard style", s.captionStyle)}${radio("captionStyle", "high-contrast", "Yellow on black", s.captionStyle)}</div>
        <div class="toggles">${check("showTranscript", "Always show the full transcript under videos", "Every word of narration, for reading or screen readers.", s.showTranscript)}</div></fieldset>
      <fieldset><legend>Timed assessments</legend>
        <p class="small muted" style="margin:0 0 6px">For approved testing accommodations. Applies to interview reading and answer timers.</p>
        <div class="opts">${[[1, "Standard time"], [1.5, "1.5× time"], [2, "2× time"], [0, "No time limit"]].map(([v, l]) => radio("extraTime", v, l, s.extraTime)).join("")}</div></fieldset>
      <button type="button" class="btn ghost small" id="a11y-reset">Reset to defaults</button>
    </form>`, { wide: true, label: "a11y-title" });
  const form = m.root.querySelector("#a11y-form");
  form.addEventListener("change", (e) => {
    const t = e.target;
    const v = t.type === "checkbox" ? t.checked : (isNaN(Number(t.value)) ? t.value : Number(t.value));
    update({ [t.name]: v });
    toast("Saved");
  });
  m.root.querySelector("#a11y-test-voice").onclick = (e) => speak("This is how lessons and questions will be read to you.", e.target);
  m.root.querySelector("#a11y-reset").onclick = () => { update({ ...DEFAULTS }); m.close(); openPanel(); };
}

// ---- page-level setup -------------------------------------------------------------------

export function setupPage() {
  apply();
  const main = document.querySelector("main") || document.querySelector(".login-form");
  if (main && !main.id) main.id = "main";
  if (main) main.setAttribute("tabindex", "-1");
  if (!document.querySelector(".skip-link") && main) {
    const a = Object.assign(document.createElement("a"), { className: "skip-link", href: `#${main.id}`, textContent: "Skip to main content" });
    a.addEventListener("click", (e) => { e.preventDefault(); main.focus(); });
    document.body.prepend(a);
  }
  if (!document.querySelector(".a11y-fab")) {
    const b = Object.assign(document.createElement("button"), { className: "btn a11y-fab", type: "button", innerHTML: "♿ Accessibility" });
    b.setAttribute("aria-label", "Accessibility settings (Alt + A)");
    b.onclick = openPanel;
    document.body.append(b);
  }
  if (!document.getElementById("a11y-live")) {
    const live = Object.assign(document.createElement("div"), { id: "a11y-live", className: "sr-only" });
    live.setAttribute("aria-live", "polite");
    document.body.append(live);
  }
  document.addEventListener("keydown", (e) => {
    if (e.altKey && (e.key === "a" || e.key === "A" || e.code === "KeyA")) { e.preventDefault(); openPanel(); }
  });
  window.addEventListener("beforeunload", stopSpeaking);
}

/** Tell screen readers about a change that isn't a focus move (e.g. a new page view). */
export function announce(text) {
  const live = document.getElementById("a11y-live");
  if (live) { live.textContent = ""; setTimeout(() => (live.textContent = text), 50); }
}

/** Small A− / A+ text size control for the top bar. */
export function textSizeControls() {
  const steps = [1, 1.25, 1.5, 1.75, 2];
  const wrap = document.createElement("div");
  wrap.setAttribute("role", "group");
  wrap.setAttribute("aria-label", "Text size");
  wrap.style.cssText = "display:flex;gap:4px;align-items:center";
  const render = () => {
    const i = steps.indexOf(Number(state.textScale));
    wrap.innerHTML = `<button class="btn ghost small" data-ts="-1" aria-label="Smaller text" ${i <= 0 ? "disabled" : ""}>A−</button>
      <span class="small muted" aria-live="polite">${Math.round(state.textScale * 100)}%</span>
      <button class="btn ghost small" data-ts="1" aria-label="Larger text" ${i >= steps.length - 1 ? "disabled" : ""}>A+</button>`;
  };
  wrap.addEventListener("click", (e) => {
    const d = Number(e.target.closest("[data-ts]")?.dataset.ts);
    if (!d) return;
    const i = Math.max(0, steps.indexOf(Number(state.textScale)));
    update({ textScale: steps[Math.min(steps.length - 1, Math.max(0, i + d))] });
  });
  onChange(render);
  render();
  return wrap;
}
