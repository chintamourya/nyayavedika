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

const TOKEN_KEY = "nyayavedika_demo_token";
const getToken = () => { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; } };
const setToken = (t) => { try { localStorage.setItem(TOKEN_KEY, t.trim()); } catch { /* private window: this page only */ } };

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
  const token = opts.noToken ? "" : getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
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
