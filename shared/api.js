// Shared API client and small UI helpers for both dashboards (no build step needed).

const TOKEN_KEY = "lanl_token";
const USER_KEY = "lanl_user";

export const session = {
  get token() { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  get user() { try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); } catch { return null; } },
  save(token, user) { localStorage.setItem(TOKEN_KEY, token); localStorage.setItem(USER_KEY, JSON.stringify(user)); },
  clear() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); },
};

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

const RETRYABLE = new Set([429, 502, 503, 504]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Small banner while the client waits out a busy server. */
function busyBanner(show) {
  let el = document.getElementById("busy-banner");
  if (!show) { el?.remove(); return; }
  if (!el) {
    el = document.createElement("div");
    el.id = "busy-banner";
    el.setAttribute("role", "status");
    el.style.cssText = "position:fixed;top:0;left:50%;transform:translateX(-50%);z-index:70;background:#a35a00;color:#fff;padding:6px 14px;border-radius:0 0 8px 8px;font-size:0.8125rem";
    el.textContent = "Lots of people are online right now. Retrying…";
    document.body.append(el);
  }
}

async function request(method, path, body, isForm = false, { retry = true } = {}) {
  const headers = {};
  if (session.token) headers.Authorization = `Bearer ${session.token}`;
  if (body && !isForm) headers["Content-Type"] = "application/json";
  // Peak-time safety: retry when the server says it's busy (429/503) or a replica restarts (502/504),
  // with exponential backoff and jitter so thousands of browsers don't retry in lockstep.
  // Writes are only retried on 429/503, which the server sends before doing any work.
  const maxTries = retry ? 4 : 1;
  for (let attempt = 1; ; attempt++) {
    let res;
    try {
      res = await fetch(path, { method, headers, body: body ? (isForm ? body : JSON.stringify(body)) : undefined });
    } catch (networkError) {
      if (method === "GET" && attempt < maxTries) { busyBanner(true); await sleep(backoff(attempt)); continue; }
      busyBanner(false);
      throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
    }
    const safeToRetry = method === "GET" || res.status === 429 || res.status === 503;
    if (RETRYABLE.has(res.status) && safeToRetry && attempt < maxTries) {
      busyBanner(true);
      const after = Number(res.headers.get("retry-after"));
      await sleep(after ? Math.min(after * 1000, 15000) + Math.random() * 500 : backoff(attempt));
      continue;
    }
    busyBanner(false);
    if (res.status === 401) {
      session.clear();
      location.href = "/login/?expired=1";
      throw new ApiError(401, "Signed out");
    }
    const data = res.headers.get("content-type")?.includes("json") ? await res.json() : await res.text();
    if (!res.ok) throw new ApiError(res.status, (data && data.detail) || res.statusText);
    return data;
  }
}

function backoff(attempt) {
  return Math.min(8000, 500 * 2 ** (attempt - 1)) * (0.5 + Math.random());
}

/** Download a protected file (e.g. the team CSV) with the user's token. */
async function download(path, filename) {
  const res = await fetch(path, { headers: session.token ? { Authorization: `Bearer ${session.token}` } : {} });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Fetch a protected file (e.g. an interview recording) and return a temporary object URL. */
async function blobUrl(path) {
  const res = await fetch(path, { headers: session.token ? { Authorization: `Bearer ${session.token}` } : {} });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return URL.createObjectURL(await res.blob());
}

export const api = {
  download,
  blobUrl,
  get: (p) => request("GET", p),
  post: (p, b, opts) => request("POST", p, b || {}, false, opts),
  patch: (p, b) => request("PATCH", p, b),
  put: (p, b) => request("PUT", p, b),
  del: (p) => request("DELETE", p),
  upload: (p, form) => request("POST", p, form, true),
};

/** Redirect to login if signed out; to the right dashboard if the role isn't allowed. */
export async function requireRole(roles) {
  if (!session.token) { location.href = "/login/"; return null; }
  const me = await api.get("/api/auth/me");
  if (!roles.includes(me.role)) { location.href = "/hire/"; return null; }
  return me;
}

export function logout() { session.clear(); location.href = "/login/"; }

// ---- DOM helpers ----------------------------------------------------------

export function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function fmtDate(iso, opts = { month: "short", day: "numeric", year: "numeric" }) {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? iso + "T00:00:00" : iso);
  return d.toLocaleDateString(undefined, opts);
}
export function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
export function daysFromNow(iso) {
  if (!iso) return null;
  const d = new Date(iso + "T00:00:00"), t = new Date(); t.setHours(0, 0, 0, 0);
  return Math.round((d - t) / 86400000);
}
export function dueText(iso) {
  const n = daysFromNow(iso);
  if (n === null) return "No due date";
  if (n < 0) return `${-n} day${n === -1 ? "" : "s"} overdue`;
  if (n === 0) return "Due today";
  return `Due in ${n} day${n === 1 ? "" : "s"}`;
}

const STATUS = { not_started: ["Not started", "plain"], in_progress: ["In progress", ""], completed: ["Completed", "ok"] };
export function statusBadge(a) {
  if (a.flags?.overdue) return `<span class="badge bad">Overdue</span>`;
  if (a.flags?.needs_retake) return `<span class="badge bad">Retake needed</span>`;
  if (a.flags?.expiring) return `<span class="badge warn">Expiring</span>`;
  const [label, cls] = STATUS[a.status] || [a.status, ""];
  return `<span class="badge ${cls}">${label}</span>`;
}
export const CATEGORY_LABEL = { safety: "Safety", technical: "Technical", culture: "Company culture", compliance: "Compliance" };
export const DELIVERY_LABEL = { online: "Online", in_person: "In person", hybrid: "Hybrid" };

export function bar(pct, cls = "", label = "") {
  const v = Math.max(0, Math.min(100, Number(pct) || 0));
  return `<div class="bar ${cls}" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(v)}"
    ${label ? `aria-label="${esc(label)}"` : ""}><span style="width:${v}%"></span></div>`;
}

export function toast(msg, isError = false) {
  let box = document.getElementById("toast");
  if (!box) { box = document.createElement("div"); box.id = "toast"; document.body.append(box); }
  box.setAttribute("aria-live", "polite");
  const el = document.createElement("div");
  if (isError) { el.className = "error"; el.setAttribute("role", "alert"); } else el.setAttribute("role", "status");
  el.textContent = msg;
  box.append(el);
  setTimeout(() => el.remove(), 4000);
}

/** Accessible dialog: labelled, focus moves in and is trapped while open, Escape closes, focus returns after. */
export function modal(html, { wide = false, label = "" } = {}) {
  const opener = document.activeElement;
  const overlay = document.createElement("div");
  overlay.className = "overlay";
  overlay.innerHTML = `<div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true" tabindex="-1">${html}</div>`;
  const dialog = overlay.firstElementChild;
  const focusables = () => [...dialog.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select, textarea, audio, [tabindex]:not([tabindex="-1"])')]
    .filter((el) => el.offsetParent !== null);
  const setLabel = () => {
    const h = label ? dialog.querySelector(`#${label}`) : dialog.querySelector("h2, h3");
    if (h) { h.id ||= `dlg-${Math.random().toString(36).slice(2, 8)}`; dialog.setAttribute("aria-labelledby", h.id); }
  };
  const onKey = (e) => {
    if (!document.body.contains(overlay)) return document.removeEventListener("keydown", onKey, true);
    if (e.key === "Escape") { e.preventDefault(); close(); }
    if (e.key === "Tab") {
      const f = focusables();
      if (!f.length) { e.preventDefault(); dialog.focus(); return; }
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  };
  const close = () => {
    overlay.remove();
    document.removeEventListener("keydown", onKey, true);
    window.speechSynthesis?.cancel();
    if (opener && document.body.contains(opener)) opener.focus();
  };
  overlay.addEventListener("click", (e) => { if (e.target === overlay || e.target.closest("[data-close]")) close(); });
  document.addEventListener("keydown", onKey, true);
  document.body.append(overlay);
  setLabel();
  // Content is often swapped in later (loading -> result): relabel when it changes.
  new MutationObserver(setLabel).observe(dialog, { childList: true });
  (focusables().find((el) => !el.matches("[data-close]")) || dialog).focus();
  return { root: dialog, close };
}

export function loading(el, text = "Loading…") { el.innerHTML = `<div class="empty"><span class="spinner"></span> ${esc(text)}</div>`; }

/** Wire up a set of sidebar buttons [data-view] to render functions. Remembers the view in the URL hash. */
export function router(views, fallback) {
  const base = document.title.split(" · ").pop();
  let first = true;
  const go = async (name) => {
    if (!views[name]) name = fallback;
    let label = name;
    $$(".sidenav button[data-view]").forEach((b) => {
      const on = b.dataset.view === name;
      b.classList.toggle("active", on);
      on ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current");
      if (on) label = b.textContent.trim();
    });
    history.replaceState(null, "", `#${name}`);
    document.title = `${label} · ${base}`;
    await views[name]();
    if (!first) {
      // Move keyboard and screen reader focus to the new page's heading.
      const h = document.querySelector("#view h1, #view h2");
      if (h) { h.setAttribute("tabindex", "-1"); h.focus({ preventScroll: false }); }
      import("/shared/a11y.js?v=20261024f").then((m) => m.announce(`${label} page`));
    }
    first = false;
  };
  $$(".sidenav button[data-view]").forEach((b) => b.addEventListener("click", () => go(b.dataset.view)));
  go(location.hash.slice(1) || fallback);
  return go;
}

export function topbar(me, appName) {
  $("#topbar").innerHTML = `
    <img class="logo" src="/shared/assets/lanl-logo.svg" alt="Los Alamos National Laboratory">
    <span class="app-name">${esc(appName)}</span>
    <span class="spacer"></span>
    <div class="who"><strong>${esc(me.name)}</strong>${esc(me.job_title)} · ${esc(me.division_code)}</div>
    ${me.role !== "hire" && appName.includes("My") ? `<a class="btn secondary small" href="/manager/">Manager dashboard</a>` : ""}
    ${me.role !== "hire" && !appName.includes("My") ? `<a class="btn secondary small" href="/hire/">My trainings</a>` : ""}
    <span id="ts-controls"></span>
    <button class="btn ghost small" id="a11y-open" aria-label="Accessibility settings (Alt + A)">♿ Accessibility</button>
    <button class="btn ghost small" id="logout">Sign out</button>`;
  $("#logout").onclick = logout;
  import("/shared/a11y.js?v=20261024f").then((a) => {
    a.setupPage();
    a.syncWithAccount();
    $("#ts-controls").replaceWith(a.textSizeControls());
    $("#a11y-open").onclick = a.openPanel;
    document.querySelector(".a11y-fab")?.remove(); // the top bar has the button on signed-in pages
  });
}
