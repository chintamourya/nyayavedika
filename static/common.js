// Shared helpers for the staff app and the citizen portal (vanilla JS, no build step).
// All server text is escaped before it is inserted into the page.
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pretty = (s) => esc(String(s ?? "").replace(/_/g, " "));
const SYNTHETIC_EXAMPLE_LIMIT = 10;
function capSyntheticExamples(rows, limit = SYNTHETIC_EXAMPLE_LIMIT) {
  let shown = 0, omitted = 0;
  const visible = rows.filter((row) => {
    if (row?.source !== "synthetic") return true;
    if (shown < limit) { shown++; return true; }
    omitted++;
    return false;
  });
  return { rows: visible, omitted };
}
function syntheticLimitNote(omitted) {
  return omitted
    ? `<span class="hint">Showing at most ${SYNTHETIC_EXAMPLE_LIMIT} synthetic examples in this list. Full records, totals, and actions are unchanged.</span>`
    : "";
}

function renderDocumentSummaryDetails(result, translate) {
  const analysis = result.analysis || {};
  const details = analysis.case_details || {};
  const structured = result.structured || {};
  const parties = [...(details.petitioners || []), ...(details.respondents || [])].filter(Boolean);
  const outcome = analysis.outcome && analysis.outcome !== "outcome not found"
    ? analysis.outcome
    : translate("summary_not_found");
  const facts = [
    details.case_number && `<div><dt>${esc(translate("summary_case_number"))}</dt><dd>${esc(details.case_number)}</dd></div>`,
    details.court_name && `<div><dt>${esc(translate("summary_court"))}</dt><dd>${esc(details.court_name)}</dd></div>`,
    parties.length && `<div><dt>${esc(translate("summary_parties"))}</dt><dd>${parties.map(esc).join(" · ")}</dd></div>`,
    structured.custody_since && `<div><dt>${esc(translate("summary_custody_since"))}</dt><dd>${esc(structured.custody_since)}</dd></div>`,
  ].filter(Boolean);
  const timeline = (analysis.timeline || []).map((item) => `<li class="summary-view-event">
    <time>${esc(item.date || "")}</time><div>${esc(item.event || "")}
      ${item.page ? `<span class="summary-view-page">${esc(translate("summary_page").replace("{page}", item.page))}</span>` : ""}
    </div></li>`).join("");
  const issues = (analysis.issues || []).map((item) => `<li>
    ${esc(item.issue || "")}${item.decision ? `<p class="hint">${esc(item.decision)}</p>` : ""}
  </li>`).join("");
  const statutes = (analysis.statutes_cited || []).map((item) => `<span class="summary-view-tag">${esc(item)}</span>`).join("");
  const directions = (analysis.directions_and_deadlines || []).map((item) => `<li>${esc(item)}</li>`).join("");
  const nextDate = structured.next_hearing_date;
  const hasDetails = facts.length || timeline || issues || statutes || directions || nextDate
    || (analysis.outcome && analysis.outcome !== "outcome not found");

  return `${hasDetails ? `<section class="summary-view-details" aria-label="${esc(translate("summary_case_details"))}">
    ${facts.length ? `<div class="summary-view-facts"><h4>${esc(translate("summary_case_details"))}</h4><dl>${facts.join("")}</dl></div>` : ""}
    <div class="summary-view-status"><b>${esc(translate("summary_outcome"))}</b><span>${esc(outcome)}</span>
      ${nextDate ? `<span class="summary-view-next">${esc(translate("summary_next_hearing"))}: ${esc(nextDate)}</span>` : ""}
    </div>
    ${timeline ? `<section class="summary-view-section"><h4>${esc(translate("summary_timeline"))}</h4><ol class="summary-view-timeline">${timeline}</ol></section>` : ""}
    ${issues ? `<section class="summary-view-section"><h4>${esc(translate("summary_issues"))}</h4><ul>${issues}</ul></section>` : ""}
    ${statutes ? `<section class="summary-view-section"><h4>${esc(translate("summary_statutes"))}</h4><div class="summary-view-tags">${statutes}</div></section>` : ""}
    ${directions ? `<section class="summary-view-section"><h4>${esc(translate("summary_directions"))}</h4><ul>${directions}</ul></section>` : ""}
  </section>` : ""}
  ${result.brief ? `<details class="summary-view-raw"><summary>${esc(translate("summary_show_brief"))}</summary><pre class="doc">${esc(result.brief)}</pre></details>` : ""}`;
}

const TOKEN_KEY = "nyayavedika_demo_token";
const getToken = () => { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; } };
const setToken = (t) => { try { localStorage.setItem(TOKEN_KEY, t.trim()); } catch { /* private window: this page only */ } };

const THEME_KEY = "nyayavedika_theme";
function applyTheme(theme) {
  const selected = theme === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", selected);
  const dark = selected === "dark";
  document.querySelectorAll(".theme-toggle").forEach((button) => {
    button.textContent = dark ? "Light mode" : "Dark mode";
    button.setAttribute("aria-label", `Switch to ${dark ? "light" : "dark"} mode`);
    button.setAttribute("aria-pressed", String(dark));
    button.title = `Switch to ${dark ? "light" : "dark"} mode`;
  });
  const themeColor = document.querySelector('meta[name="theme-color"]');
  if (themeColor) themeColor.content = dark ? "#0c1422" : "#0866ff";
}
function initializeTheme() {
  let saved = "";
  try {
    saved = localStorage.getItem(THEME_KEY) || localStorage.getItem("nyayavedika_advocate_theme") || "";
  } catch { /* defaults to light when browser storage is unavailable */ }
  applyTheme(saved);
  document.querySelectorAll(".theme-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      applyTheme(next);
      try { localStorage.setItem(THEME_KEY, next); } catch { /* theme stays active for this page */ }
    });
  });
}
initializeTheme();

const REACH_BROWSER_KEY = "nyayavedika_reach_browser";
let sessionBrowserId = "";

function currentReachDoor() {
  const path = window.location.pathname.replace(/\/+$/, "");
  return { "/citizen": "citizen", "/advocate": "advocate", "/staff": "staff" }[path] || "public";
}

function browserActivityId() {
  const valid = (value) => value && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
  try {
    const saved = localStorage.getItem(REACH_BROWSER_KEY);
    if (valid(saved)) return saved;
  } catch { /* use a session-only identifier when browser storage is unavailable */ }
  try {
    const saved = sessionStorage.getItem(REACH_BROWSER_KEY);
    if (valid(saved)) return saved;
  } catch { /* use an in-memory identifier when browser storage is unavailable */ }
  if (sessionBrowserId) return sessionBrowserId;
  if (!globalThis.crypto?.getRandomValues) return "";
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  sessionBrowserId = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  try {
    localStorage.setItem(REACH_BROWSER_KEY, sessionBrowserId);
  } catch {
    try { sessionStorage.setItem(REACH_BROWSER_KEY, sessionBrowserId); } catch { /* in-memory for this page only */ }
  }
  return sessionBrowserId;
}

function addUsageNotice() {
  const target = document.querySelector("main, .landing");
  if (!target || document.querySelector(".usage-notice")) return;
  const notice = document.createElement("section");
  notice.className = "card usage-notice";
  notice.setAttribute("aria-label", "Activity measurement");
  notice.innerHTML = `<b>Activity measurement</b>
    <p class="hint">We measure page visits and feature use to understand activity. A random browser ID is used to count distinct browsers across portals; the server stores only its hash. Activity records do not include names, contact details, IP addresses, request text, or uploaded-document contents.</p>`;
  target.prepend(notice);
  const door = currentReachDoor();
  const browserId = browserActivityId();
  if (door && browserId) {
    api(`/api/reach/${door}`, { method: "POST", json: { browser_id: browserId }, noToken: true })
      .catch((error) => console.warn(`Browser reach could not be recorded: ${error.message}`));
  }
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", addUsageNotice, { once: true });
else addUsageNotice();

class ApiError extends Error {
  constructor(status, detail) {
    const msg = typeof detail === "string" ? detail
      : Array.isArray(detail)
        ? detail.map((issue) => {
          const field = Array.isArray(issue.loc) ? issue.loc.slice(-1)[0] : "request";
          return `${field}: ${issue.msg || "invalid value"}`;
        }).join("; ")
        : detail?.message || "Request failed";
    const fileErrors = Array.isArray(detail?.files)
      ? detail.files.filter((file) => file.status === "rejected")
        .map((file) => `${file.filename}: ${file.reason}`)
      : [];
    super(fileErrors.length ? `${msg} — ${fileErrors.join("; ")}` : msg);
    this.status = status; this.detail = detail;
  }
}

// api(path) GET; api(path, {method, json, form, raw}) - raw returns the Response (for file downloads)
async function api(path, opts = {}) {
  const headers = {};
  const browserId = path.startsWith("/api/") ? browserActivityId() : "";
  if (browserId) headers["X-Anonymous-Browser-ID"] = browserId;
  const token = opts.noToken ? "" : getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
    const path = window.location.pathname.replace(/\/+$/, "");
    const portalRole = { "/advocate": "lawyer", "/staff": "staff", "/citizen": "citizen" }[path];
    if (portalRole) headers["X-Demo-Role"] = portalRole;
  }
  let body;
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.json); }
  if (opts.form) body = opts.form;
  const res = await fetch(path, { method: opts.method || (body ? "POST" : "GET"), headers, body, signal: opts.signal });
  if (opts.raw && res.ok) return res;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401) throw new ApiError(401, "Enter your demo access token (top right).");
    throw new ApiError(res.status, data.detail ?? data.error ?? res.statusText);
  }
  return data;
}

function fileToBase64(file, { signal, onProgress } = {}) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    const cleanup = () => signal?.removeEventListener("abort", abort);
    const abort = () => reader.abort();
    if (signal?.aborted) {
      reject(new DOMException("File reading was canceled.", "AbortError"));
      return;
    }
    signal?.addEventListener("abort", abort, { once: true });
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(reader.error || new Error("Could not read the file"));
    reader.onabort = () => reject(new DOMException("File reading was canceled.", "AbortError"));
    reader.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded, event.total);
    };
    reader.onloadend = cleanup;
    reader.readAsDataURL(file);
  });
}

function createSummaryProgress(statusId, labels) {
  const box = $(`#${statusId}`);
  const message = $("[data-summary-message]", box);
  const cancel = $("[data-summary-cancel]", box);
  const controller = new AbortController();
  const startedAt = Date.now();
  let currentMessage = "";
  let timedOut = false;
  let finished = false;

  const render = () => {
    const seconds = Math.floor((Date.now() - startedAt) / 1000);
    const elapsed = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
    message.textContent = `${currentMessage} · ${labels.elapsed.replace("{time}", elapsed)}`;
  };
  const set = (nextMessage) => {
    currentMessage = nextMessage;
    render();
  };
  const finish = (state, finalMessage) => {
    if (finished) return;
    finished = true;
    clearInterval(interval);
    clearTimeout(timeout);
    box.classList.remove("is-running");
    box.classList.add(state);
    cancel.hidden = true;
    cancel.disabled = false;
    message.textContent = finalMessage;
  };
  const cancelRequest = () => {
    if (finished || controller.signal.aborted) return;
    cancel.disabled = true;
    set(labels.canceling);
    controller.abort();
  };

  box.classList.remove("hidden", "is-complete", "is-failed", "is-cancelled");
  box.classList.add("is-running");
  cancel.textContent = labels.cancel;
  cancel.hidden = false;
  cancel.disabled = false;
  cancel.addEventListener("click", cancelRequest);
  const interval = setInterval(render, 1000);
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, 5 * 60 * 1000);

  return {
    signal: controller.signal,
    set,
    complete: (text) => finish("is-complete", text),
    fail: (text) => finish("is-failed", text),
    cancelled: (text) => finish("is-cancelled", text),
    timedOut: () => timedOut,
    dispose: () => {
      clearInterval(interval);
      clearTimeout(timeout);
      cancel.removeEventListener("click", cancelRequest);
    },
  };
}

async function downloadFrom(path, opts, fallbackName) {
  const res = await api(path, { ...opts, raw: true });
  const cd = res.headers.get("Content-Disposition") || "";
  const name = (cd.match(/filename="([^"]+)"/) || [])[1] || fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
  return name;
}

function toast(msg, kind = "info") {
  const t = Object.assign(document.createElement("div"), { className: `toast ${kind}`, role: "status" });
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 4500);
}

async function busy(btn, fn) {
  if (btn) btn.disabled = true;
  try { return await fn(); } catch (e) { toast(e.message, "error"); } finally { if (btn) btn.disabled = false; }
}

// Band badge: icon + text + colour (never colour alone)
const BAND_ICON = { Critical: "‼", High: "▲", Medium: "■", Routine: "○" };
const band = (b) => b ? `<span class="badge band-${esc(b).toLowerCase()}"><span aria-hidden="true">${BAND_ICON[b] || "•"}</span> ${esc(b)}</span>` : "";

function demoBanner() { /* banner removed; kept as a no-op so existing callers still work */ }

function tokenBox(input, onChange) {
  input.value = getToken();
  input.addEventListener("change", () => { setToken(input.value); onChange && onChange(); });
}

function nextMonday(from = new Date()) {
  const d = new Date(from); const add = (8 - d.getDay()) % 7 || 7; d.setDate(d.getDate() + add);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;   // local date, not UTC
}

// ---- files and folders (shared by the staff Intake, the staff assistant and the citizen chat)
const JUNK = /^(\.ds_store|thumbs\.db|desktop\.ini|\.gitkeep|\.localized)$/i;
const isJunkFile = (name, rel) => JUNK.test(name) || /^(~\$|\._)/.test(name) || /(^|\/)__MACOSX(\/|$)/.test(rel || "");

// Every file under a dropped item, folders included (dataTransfer.files lists a folder as one empty entry).
async function filesFromDrop(dt) {
  const out = [];
  const walk = async (entry, path) => {
    if (entry.isFile) {
      const file = await new Promise((res, rej) => entry.file(res, rej));
      out.push({ file, rel: path ? `${path}/${entry.name}` : "" });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      for (;;) {   // readEntries returns at most ~100 entries per call
        const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
        if (!batch.length) break;
        for (const child of batch) await walk(child, path ? `${path}/${entry.name}` : entry.name);
      }
    }
  };
  const items = [...(dt.items || [])].map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null));
  if (items.length && items.every(Boolean)) { for (const e of items) await walk(e, ""); return out; }
  return [...dt.files].map((file) => ({ file, rel: "" }));
}
