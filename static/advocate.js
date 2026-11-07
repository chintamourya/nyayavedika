// Advocate Door. The backend verifies the lawyer role and each document's private workspace capability;
// nothing here is a security boundary. All server text is escaped with esc() before it reaches innerHTML.
const WORKSPACE_KEY = "nyayavedika_advocate_workspace";
const DOCUMENT_KEY = "nyayavedika_advocate_document";
const THEME_KEY = "nyayavedika_advocate_theme";
const INSIGHT_LABELS = { issues: "Issues", facts: "Facts", background: "Case Background", summary: "Summarization" };
let workspaceToken = "";
let activeDocument = null;

// ---------------------------------------------------------------- small helpers
function sessionGet(key) { try { return sessionStorage.getItem(key) || ""; } catch { return ""; } }
function sessionSet(key, value) { try { sessionStorage.setItem(key, value); } catch { /* in-memory state is kept */ } }
function showStatus(message, bad = false) {
  const box = $("#advocateStatus");
  box.textContent = message || "";
  box.classList.toggle("hidden", !message);
  box.classList.toggle("banner-bad", bad);
  box.classList.toggle("banner-warn", !bad);
}
function setError(selector, message) {
  const box = $(selector);
  box.textContent = message || "";
  box.classList.toggle("hidden", !message);
}
function toast(message) {
  const el = Object.assign(document.createElement("div"), { className: "toast", textContent: message });
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 3200);
}
function isPdf(file) { return file && (file.type === "application/pdf" || /\.pdf$/i.test(file.name)); }
function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  return bytes < 1048576 ? `${(bytes / 1024).toFixed(0)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
}
function b64ToFile(name, mime, content) {
  const binary = atob(content);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new File([bytes], name, { type: mime });
}
function downloadFile(file) {
  const url = URL.createObjectURL(file);
  const link = Object.assign(document.createElement("a"), { href: url, download: file.name });
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}
function safeDownload(name, mime, content) { downloadFile(b64ToFile(name, mime, content)); }
function downloadText(name, text) { downloadFile(new File([text], name, { type: "text/plain;charset=utf-8" })); }
function icon(name) { return `<svg class="ic"><use href="#i-${name}"/></svg>`; }
// "1,3-5" -> [1,3,4,5]; throws a readable Error on bad input.
function parsePages(text, max) {
  const out = [];
  for (const part of String(text || "").split(/[\s,;]+/).filter(Boolean)) {
    const m = part.match(/^(\d+)(?:-(\d+))?$/);
    if (!m) throw new Error(`"${part}" is not a page number or range.`);
    const a = Number(m[1]), b = Number(m[2] || m[1]);
    if (a < 1 || b < a || (max && b > max)) throw new Error(`Page ${part} is outside this document${max ? ` (1-${max})` : ""}.`);
    for (let n = a; n <= b; n++) if (!out.includes(n)) out.push(n);
  }
  return out;
}
function compressPages(nums) {
  const sorted = [...nums].sort((a, b) => a - b), parts = [];
  for (let i = 0; i < sorted.length; i++) {
    let j = i;
    while (sorted[j + 1] === sorted[j] + 1) j++;
    parts.push(j > i ? `${sorted[i]}-${sorted[j]}` : String(sorted[i]));
    i = j;
  }
  return parts.join(",");
}

// ---------------------------------------------------------------- session impact metrics (real counts only)
const METRICS_KEY = "nyayavedika_advocate_metrics";
const metrics = { ops: 0, pages: 0, docs: 0, insights: 0, reused: 0, lastMs: 0 };
try { Object.assign(metrics, JSON.parse(sessionGet(METRICS_KEY) || "{}")); } catch { /* start from zero */ }
function bump(field, amount = 1) {
  metrics[field] = (field === "lastMs" ? amount : (Number(metrics[field]) || 0) + amount);
  sessionSet(METRICS_KEY, JSON.stringify(metrics));
  renderMetrics();
}
function renderMetrics() {
  const set = (id, value) => { const el = $(id); if (el) el.textContent = value; };
  ["#mOps", "#mOps2"].forEach((id) => set(id, metrics.ops));
  ["#mDocs", "#mDocs2"].forEach((id) => set(id, metrics.docs));
  ["#mInsights", "#mInsights2"].forEach((id) => set(id, metrics.insights));
  set("#mPages", metrics.pages);
  set("#mReused", metrics.reused);
  set("#mLast", metrics.lastMs ? `${(metrics.lastMs / 1000).toFixed(1)} s` : "–");
}

// ---------------------------------------------------------------- theme, auth, tabs
function applyTheme(theme) {
  if (theme) document.documentElement.setAttribute("data-theme", theme);
  else document.documentElement.removeAttribute("data-theme");
}
try { applyTheme(localStorage.getItem(THEME_KEY) || ""); } catch { /* follow the system theme */ }
$("#themeToggle").addEventListener("click", () => {
  const dark = document.documentElement.getAttribute("data-theme") === "dark"
    || (!document.documentElement.getAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
  const next = dark ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem(THEME_KEY, next); } catch { /* not persisted */ }
});

async function initialize() {
  showStatus("");
  try {
    const user = await api("/api/whoami");
    $("#who").textContent = user.role;
    $("#who").classList.toggle("ok", user.role === "lawyer");
    if (user.role !== "lawyer") {
      showStatus("The Advocate Door requires a lawyer access token. Court Staff and Citizen tokens cannot use it.", true);
      $$(".advocate-panel, .advocate-tabs").forEach((el) => el.classList.add("hidden"));
      return;
    }
    $$(".advocate-tabs").forEach((el) => el.classList.remove("hidden"));
    showTab(currentTab);
    workspaceToken = sessionGet(WORKSPACE_KEY);
    if (!workspaceToken) {
      const workspace = await api("/api/advocate/workspaces", { method: "POST", json: {} });
      workspaceToken = workspace.workspace_token;
      sessionSet(WORKSPACE_KEY, workspaceToken);
    }
    try { activeDocument = JSON.parse(sessionGet(DOCUMENT_KEY) || "null"); } catch { activeDocument = null; }
    if (activeDocument?.doc_id) renderActiveDocument(activeDocument);
  } catch (error) {
    $("#who").textContent = "not signed in";
    $("#who").classList.remove("ok");
    showStatus(error.message || "Enter a lawyer access token to use the Advocate Door.", true);
    $$(".advocate-panel, .advocate-tabs").forEach((el) => el.classList.add("hidden"));
  }
}

let currentTab = "studio";
function showTab(name) {
  currentTab = name;
  $$("[data-advocate-tab]").forEach((tab) => {
    const active = tab.dataset.advocateTab === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  $$(".advocate-panel").forEach((panel) => panel.classList.toggle("hidden", panel.id !== `advocate-${name}`));
}
$$("[data-advocate-tab]").forEach((button) => button.addEventListener("click", () => showTab(button.dataset.advocateTab)));
document.addEventListener("keydown", (event) => {
  if (event.altKey && event.key === "1") { event.preventDefault(); showTab("studio"); }
  if (event.altKey && event.key === "2") { event.preventDefault(); showTab("insights"); }
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && currentTab === "studio") {
    event.preventDefault();
    $("#studioForm").requestSubmit();
  }
});
// Dropping a PDF anywhere on the page goes to the active tab; the drop zones handle their own events.
function wireDrop(zone, onFiles) {
  ["dragenter", "dragover"].forEach((name) => zone.addEventListener(name, (event) => {
    event.preventDefault(); zone.classList.add("over");
  }));
  ["dragleave", "drop"].forEach((name) => zone.addEventListener(name, (event) => {
    event.preventDefault(); zone.classList.remove("over");
  }));
  zone.addEventListener("drop", (event) => { event.stopPropagation(); onFiles([...event.dataTransfer.files]); });
}

// ================================================================ DOCUMENT STUDIO
const studio = { files: [], pages: [], order: [], selected: new Set(), anchor: null, rotated: new Map(), previewUrl: "", op: "merge" };
const needsSelection = { rotate: "rotate", remove: "remove" };

function updateStudioOperation() {
  const operation = $("#studioOperation").value;
  studio.op = operation;
  $$("#opCards .op").forEach((card) => card.setAttribute("aria-checked", String(card.dataset.op === operation)));
  $$("#studioOptions [data-operations]").forEach((el) =>
    el.classList.toggle("hidden", !el.dataset.operations.split(" ").includes(operation)));
  const merge = operation === "merge";
  $("#studioFiles").multiple = merge;
  $("#studioDropSub").textContent = merge ? "Two or more PDFs, merged in the order you set" : "One PDF at a time";
  $("#mergeList").classList.toggle("hidden", !(merge && studio.files.length));
  $("#studioSubmitLabel").textContent = { merge: "Merge PDFs", split: "Split PDF", reorder: "Apply new order", rotate: "Rotate selected pages",
    remove: "Remove selected pages", ocr: "Extract text (OCR)", bookmarks: "Add bookmarks", index: "Create clickable index",
    page_numbers: "Add page numbers" }[operation];
  const pageParent = $("#pageTools").parentElement;
  [pageParent, $("#pageGridHint"), $("#studioPageList")].forEach((el) => el.classList.toggle("hidden", merge));
  $("#pageGridHint").textContent = operation === "reorder"
    ? "Drag pages to reorder them. The order on the left updates as you drop."
    : "Click to select · Shift-click for a range · use the eye to jump the preview to that page.";
  renderPages();
  renderMergeList();
  updateHints();
}
$("#opCards").addEventListener("click", (event) => {
  const card = event.target.closest(".op");
  if (!card) return;
  $("#studioOperation").value = card.dataset.op;
  updateStudioOperation();
  setError("#studioError", "");
});
$("#opCards").addEventListener("keydown", (event) => {
  if (!["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(event.key)) return;
  const cards = $$("#opCards .op");
  const index = cards.indexOf(event.target.closest(".op"));
  if (index < 0) return;
  event.preventDefault();
  const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : -1;
  const next = cards[(index + step + cards.length) % cards.length];
  next.focus(); next.click();
});

function gridOrder() { return studio.op === "reorder" ? studio.order : studio.pages; }
function syncFromSelection() {
  const selected = [...studio.selected];
  if (studio.op === "remove") $("#removePages").value = compressPages(selected);
  $("#rotateHint").textContent = selected.length
    ? `${selected.length} page${selected.length === 1 ? "" : "s"} selected: ${compressPages(selected)}`
    : "Select pages in the page grid.";
}
function syncOrderInput() { $("#pageOrder").value = studio.order.join(","); }

function renderPages() {
  const grid = $("#studioPageList");
  const reorder = studio.op === "reorder";
  grid.innerHTML = gridOrder().map((page) => {
    const rot = studio.rotated.get(page);
    return `<div class="pg${studio.selected.has(page) ? " sel" : ""}${rot ? " rotated" : ""}" data-page="${Number(page)}" ` +
      `role="checkbox" aria-checked="${studio.selected.has(page)}" tabindex="0" draggable="${reorder}">` +
      `<span class="lbl" ${rot ? `data-rot="↻${rot}°"` : ""}>${Number(page)}</span>` +
      `<button type="button" class="view" data-view="${Number(page)}" aria-label="Show page ${Number(page)} in preview">${icon("eye")}</button></div>`;
  }).join("");
  $("#studioPageCount").textContent = studio.pages.length
    ? `${studio.pages.length} page${studio.pages.length === 1 ? "" : "s"}${studio.selected.size ? ` · ${studio.selected.size} selected` : ""}` : "";
}
function togglePage(page, shift) {
  const order = gridOrder();
  if (shift && studio.anchor != null) {
    const a = order.indexOf(studio.anchor), b = order.indexOf(page);
    order.slice(Math.min(a, b), Math.max(a, b) + 1).forEach((p) => studio.selected.add(p));
  } else {
    if (studio.selected.has(page)) studio.selected.delete(page); else studio.selected.add(page);
    studio.anchor = page;
  }
  syncFromSelection();
  renderPages();
}
function showPage(page) {
  if (studio.previewUrl) $("#studioPreview").src = `${studio.previewUrl}#page=${Number(page)}`;
}
$("#studioPageList").addEventListener("click", (event) => {
  const view = event.target.closest("[data-view]");
  if (view) return showPage(Number(view.dataset.view));
  const tile = event.target.closest(".pg");
  if (tile) togglePage(Number(tile.dataset.page), event.shiftKey);
});
$("#studioPageList").addEventListener("keydown", (event) => {
  const tile = event.target.closest(".pg");
  if (tile && (event.key === " " || event.key === "Enter")) { event.preventDefault(); togglePage(Number(tile.dataset.page), event.shiftKey); }
});
// drag to reorder (reorder operation only)
let dragPage = null;
$("#studioPageList").addEventListener("dragstart", (event) => {
  const tile = event.target.closest(".pg");
  if (!tile || studio.op !== "reorder") return;
  dragPage = Number(tile.dataset.page);
  tile.classList.add("dragging");
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", String(dragPage));
});
$("#studioPageList").addEventListener("dragover", (event) => {
  if (dragPage == null) return;
  event.preventDefault();
  $$(".pg.dropbefore", $("#studioPageList")).forEach((el) => el.classList.remove("dropbefore"));
  event.target.closest(".pg")?.classList.add("dropbefore");
});
$("#studioPageList").addEventListener("drop", (event) => {
  if (dragPage == null) return;
  event.preventDefault();
  const target = event.target.closest(".pg");
  const from = studio.order.indexOf(dragPage);
  const targetAt = target ? studio.order.indexOf(Number(target.dataset.page)) : studio.order.length;
  studio.order.splice(from, 1);
  // dragging forward lands after the target, dragging backward lands before it
  const to = target ? studio.order.indexOf(Number(target.dataset.page)) + (from < targetAt ? 1 : 0) : studio.order.length;
  studio.order.splice(to, 0, dragPage);
  dragPage = null;
  syncOrderInput();
  renderPages();
});
$("#studioPageList").addEventListener("dragend", () => { dragPage = null; renderPages(); });

$("#pageTools").addEventListener("click", (event) => {
  const mode = event.target.closest("[data-select]")?.dataset.select;
  if (!mode) return;
  const all = studio.pages;
  if (mode === "all") studio.selected = new Set(all);
  if (mode === "none") studio.selected = new Set();
  if (mode === "odd") studio.selected = new Set(all.filter((p) => p % 2 === 1));
  if (mode === "even") studio.selected = new Set(all.filter((p) => p % 2 === 0));
  if (mode === "invert") studio.selected = new Set(all.filter((p) => !studio.selected.has(p)));
  syncFromSelection();
  renderPages();
});
$("#removePages").addEventListener("input", () => {
  try { studio.selected = new Set(parsePages($("#removePages").value, studio.pages.length)); renderPages(); } catch { /* validated on submit */ }
});
$("#pageOrder").addEventListener("input", () => {
  try {
    const order = parsePages($("#pageOrder").value, studio.pages.length);
    if (order.length === studio.pages.length) { studio.order = order; renderPages(); }
  } catch { /* validated on submit */ }
});
$("#orderReverse").addEventListener("click", () => { studio.order.reverse(); syncOrderInput(); renderPages(); });
$("#orderReset").addEventListener("click", () => { studio.order = [...studio.pages]; syncOrderInput(); renderPages(); });
$("#rotateDegrees").addEventListener("change", updateHints);

$("#splitMode").addEventListener("change", () => $("#splitRangeBox").classList.toggle("hidden", $("#splitMode").value === "pages"));
function fillSplitRanges(size) {
  const total = studio.pages.length;
  if (!total) return toast("Add a PDF first.");
  const parts = [];
  for (let start = 1; start <= total; start += size) parts.push(start === Math.min(start + size - 1, total) ? `${start}` : `${start}-${Math.min(start + size - 1, total)}`);
  $("#splitRanges").value = parts.join(";");
}
$("#splitEveryBtn").addEventListener("click", () => fillSplitRanges(Math.max(1, Number($("#splitEvery").value) || 1)));
$("#splitHalfBtn").addEventListener("click", () => fillSplitRanges(Math.ceil(studio.pages.length / 2)));

$$("[data-fill]").forEach((button) => button.addEventListener("click", () => {
  const target = $(`#${button.dataset.fill}`);
  const isIndex = button.dataset.fill === "indexItems";
  const pages = studio.selected.size ? [...studio.selected].sort((a, b) => a - b) : studio.pages;
  if (!pages.length) return toast("Add a PDF first.");
  target.value = pages.slice(0, isIndex ? 40 : 200).map((p) => (isIndex ? `${p}: Page ${p}` : `${p} Page ${p}`)).join("\n");
  updateHints();
  toast("Placeholders added. Replace each 'Page N' with a real title.");
}));
function countLines(selector) { return $(selector).value.split(/\n/).filter((line) => line.trim()).length; }
function updateHints() {
  $("#bookmarkCount").textContent = `${countLines("#bookmarkItems")} bookmark(s)`;
  $("#indexCount").textContent = `${countLines("#indexItems")} / 40 entries`;
  const total = studio.pages.length, start = Number($("#startNumber").value) || 1;
  $("#numberHint").textContent = total ? `Pages will read ${start} to ${start + total - 1}.` : "Add a PDF to see the numbering range.";
}
["#bookmarkItems", "#indexItems", "#startNumber"].forEach((sel) => $(sel).addEventListener("input", updateHints));

// ---- files
function renderMergeList() {
  const list = $("#mergeList");
  const merge = studio.op === "merge";
  list.classList.toggle("hidden", !(merge && studio.files.length));
  list.innerHTML = studio.files.map((file, i) =>
    `<li data-i="${i}">${icon("file")}<span class="name">${esc(file.name)}</span><span class="muted">${esc(formatSize(file.size))}</span>` +
    `<button type="button" class="mini" data-move="-1" aria-label="Move up"${i === 0 ? " disabled" : ""}>↑</button>` +
    `<button type="button" class="mini" data-move="1" aria-label="Move down"${i === studio.files.length - 1 ? " disabled" : ""}>↓</button>` +
    `<button type="button" class="mini" data-remove aria-label="Remove ${esc(file.name)}">${icon("x")}</button></li>`).join("");
  $("#studioFilesHint").textContent = merge && studio.files.length ? `${studio.files.length} file(s)` : "";
}
$("#mergeList").addEventListener("click", (event) => {
  const item = event.target.closest("li");
  if (!item) return;
  const i = Number(item.dataset.i);
  const move = event.target.closest("[data-move]");
  if (move) {
    const j = i + Number(move.dataset.move);
    if (j >= 0 && j < studio.files.length) [studio.files[i], studio.files[j]] = [studio.files[j], studio.files[i]];
  } else if (event.target.closest("[data-remove]")) {
    studio.files.splice(i, 1);
  } else return;
  loadPreview();
  renderMergeList();
});

function loadPreview() {
  if (studio.previewUrl) URL.revokeObjectURL(studio.previewUrl);
  studio.previewUrl = "";
  const first = studio.files[0];
  $("#studioPreviewWrap").classList.toggle("hidden", !first);
  $("#studioEmpty").classList.toggle("hidden", Boolean(first));
  $("#studioDrop").classList.toggle("has-file", Boolean(first));
  if (!first) { studio.pages = []; studio.order = []; studio.selected = new Set(); renderPages(); return; }
  studio.previewUrl = URL.createObjectURL(first);
  $("#studioPreview").src = studio.previewUrl;
}
async function inspectFirst() {
  const file = studio.files[0];
  studio.pages = []; studio.order = []; studio.selected = new Set(); studio.rotated = new Map(); studio.anchor = null;
  renderPages();
  if (!file) return;
  $("#studioPageCount").textContent = "Checking PDF pages…";
  try {
    const result = await api("/api/advocate/studio", {
      method: "POST",
      json: { operation: "inspect", files: [{ filename: file.name, content_base64: await fileToBase64(file) }] },
    });
    if (studio.files[0] !== file) return;   // a newer file replaced it while this was running
    studio.pages = result.pages.map(Number);
    studio.order = [...studio.pages];
    syncOrderInput();
    renderPages();
    updateHints();
  } catch (error) {
    $("#studioPageCount").textContent = "";
    setError("#studioError", error.message || "The PDF preview could not be inspected.");
  }
}
async function addStudioFiles(picked) {
  setError("#studioError", "");
  const pdfs = picked.filter(isPdf);
  if (picked.length && !pdfs.length) return setError("#studioError", "Only PDF files can be used here.");
  if (pdfs.length < picked.length) toast("Skipped files that are not PDFs.");
  if (!pdfs.length) return;
  $("#studioOutput").replaceChildren();
  $("#studioChain").classList.add("hidden");
  const merge = studio.op === "merge";
  studio.files = merge ? [...studio.files, ...pdfs] : [pdfs[0]];
  loadPreview();
  renderMergeList();
  await inspectFirst();
}
$("#studioFiles").addEventListener("change", async () => {
  const picked = [...$("#studioFiles").files];
  $("#studioFiles").value = "";
  await addStudioFiles(picked);
});
wireDrop($("#studioDrop"), addStudioFiles);

function studioOptions(operation) {
  const total = studio.pages.length;
  if (operation === "split") return { split_mode: $("#splitMode").value, ranges: $("#splitRanges").value };
  if (operation === "reorder") return { page_order: parsePages($("#pageOrder").value, total) };
  if (operation === "rotate") return { pages: [...studio.selected].sort((a, b) => a - b), degrees: Number($("#rotateDegrees").value) };
  if (operation === "remove") return { pages: parsePages($("#removePages").value, total) };
  if (operation === "bookmarks") return { items: $("#bookmarkItems").value };
  if (operation === "index") return { items: $("#indexItems").value };
  if (operation === "page_numbers") return { start_number: Number($("#startNumber").value) };
  return {};
}
// Friendly checks before a round trip; the server validates everything again.
function validateStudio(operation) {
  const total = studio.pages.length;
  if (!studio.files.length) return "Add a PDF first.";
  if (operation === "merge" && studio.files.length < 2) return "Add at least two PDFs to merge.";
  if (operation === "split" && $("#splitMode").value === "ranges" && !$("#splitRanges").value.trim()) return "Enter page ranges such as 1-3;4-6, or use the quick-fill buttons.";
  if (operation === "reorder") {
    const order = parsePages($("#pageOrder").value, total);
    if (order.length !== total) return `List all ${total} pages exactly once (you have ${order.length}).`;
  }
  if (operation === "rotate" && !studio.selected.size) return "Select the pages to rotate in the page grid.";
  if (operation === "remove") {
    const remove = parsePages($("#removePages").value, total);
    if (!remove.length) return "Select the pages to remove.";
    if (remove.length >= total) return "At least one page must remain.";
  }
  if (operation === "bookmarks" && !$("#bookmarkItems").value.trim()) return "Add at least one bookmark.";
  if (operation === "index" && !$("#indexItems").value.trim()) return "Add at least one index entry.";
  if (operation === "index" && countLines("#indexItems") > 40) return "An index can contain at most 40 entries.";
  return "";
}

function renderStudioResult(result, operation) {
  const output = $("#studioOutput");
  if (result.ocr_pages) {
    const pages = result.ocr_pages.map((page) =>
      `<details class="ocr-page"><summary>Page ${Number(page.page)} · ${esc(page.source)}${page.confidence == null ? "" : ` · ${esc(page.confidence)}%`}</summary>` +
      `<pre>${esc(page.text || "No text recognized on this page.")}</pre></details>`).join("");
    const download = result.download;
    output.innerHTML = `<div class="result">${icon("ocr")}<b>${esc(result.recognized_pages)} of ${esc(result.extracted_pages)} pages contain recognized text.</b>` +
      (download ? `<button class="btn sm" type="button" id="downloadOcrText">${icon("download")} Download OCR text</button>` : "") + `</div>` +
      (pages || `<p class="hint">No text was recognized. Check that the OCR engine and required language packs are installed.</p>`);
    if (download) $("#downloadOcrText").addEventListener("click", () =>
      safeDownload(download.filename, download.mime_type, download.content_base64));
    return;
  }
  const files = result.files || [];
  output.innerHTML = files.map((file, i) =>
    `<div class="result" data-i="${i}">${icon("file")}<b>${esc(file.filename)}</b>` +
    `<button class="btn sm" type="button" data-download>${icon("download")} Download</button>` +
    `<button class="btn sm" type="button" data-chain title="Use this result as the input for another operation">${icon("chain")} Keep editing</button>` +
    `</div>`).join("");
  $$(".result", output).forEach((row) => {
    const file = files[Number(row.dataset.i)];
    row.querySelector("[data-download]").addEventListener("click", () => safeDownload(file.filename, file.mime_type, file.content_base64));
    row.querySelector("[data-chain]").addEventListener("click", async () => {
      const next = b64ToFile(file.filename, file.mime_type, file.content_base64);
      studio.files = [next];
      $("#studioOperation").value = studio.op === "merge" ? "reorder" : studio.op;
      updateStudioOperation();
      loadPreview();
      renderMergeList();
      await inspectFirst();
      $("#studioChain").innerHTML = `${icon("chain")} Working on <b>${esc(next.name)}</b> (result of the last step)`;
      $("#studioChain").classList.remove("hidden");
      output.replaceChildren();
      toast("Result loaded. Choose the next operation.");
    });
  });
  if (files.length) toast(files.length === 1 ? "Your PDF is ready." : `${files.length} PDFs are ready.`);
}

$("#studioForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const operation = $("#studioOperation").value;
  setError("#studioError", "");
  $("#studioOutput").replaceChildren();
  let options, problem;
  try { problem = validateStudio(operation); options = problem ? null : studioOptions(operation); } catch (error) { problem = error.message; }
  if (problem) return setError("#studioError", problem);
  $("#studioLoading").classList.remove("hidden");
  $("#studioSubmit").disabled = true;
  try {
    const sources = operation === "merge" ? studio.files : [studio.files[0]];
    const encoded = await Promise.all(sources.map(async (file) =>
      ({ filename: file.name, content_base64: await fileToBase64(file) })));
    const result = await api("/api/advocate/studio", { method: "POST", json: { operation, files: encoded, options } });
    renderStudioResult(result, operation);
    bump("ops");
    if (operation !== "merge") bump("pages", studio.pages.length);
  } catch (error) {
    setError("#studioError", error.message || "The PDF operation could not be completed.");
  } finally {
    $("#studioLoading").classList.add("hidden");
    $("#studioSubmit").disabled = false;
  }
});

// ================================================================ AI DOCUMENT INSIGHTS
const insights = { uploadedAt: 0, file: null, url: "", cache: new Map(), current: "", filter: "", evidence: true };

function renderActiveDocument(documentInfo) {
  const scanned = Number(documentInfo.ocr_pages) || 0;
  $("#insightDocument").innerHTML = `${icon("file")}<span class="name">${esc(documentInfo.filename)}</span>` +
    `<div class="stats"><span class="stat">${Number(documentInfo.pages)} pages</span>` +
    `<span class="stat${scanned ? " warn" : ""}">${scanned} scanned page${scanned === 1 ? "" : "s"} read by OCR</span>` +
    `<span class="stat">Text cached for reuse</span></div>`;
  $("#insightDocument").classList.remove("hidden");
  $("#insightActions").classList.remove("locked");
  $("#insightEmpty").querySelector("b").textContent = "Pick an insight to begin";
  $$(".insight-choice").forEach((button) =>
    button.classList.toggle("cached", insights.cache.has(`${documentInfo.doc_id}:${button.dataset.insight}`)));
  $("#insightPreviewBox").classList.toggle("hidden", !insights.url);
}
async function uploadInsightFile(file) {
  if (!file) return;
  if (!isPdf(file)) return setError("#insightError", "Only PDF files can be analysed.");
  setError("#insightError", "");
  $("#insightOutput").replaceChildren();
  $("#insightEmpty").classList.remove("hidden");
  $("#insightUploadLoading").classList.remove("hidden");
  $("#insightUploadButton").disabled = true;
  try {
    const documentInfo = await api("/api/advocate/documents", {
      method: "POST",
      json: { workspace_token: workspaceToken, filename: file.name, content_base64: await fileToBase64(file) },
    });
    activeDocument = documentInfo;
    bump("docs");
    insights.uploadedAt = performance.now();
    insights.cache.clear();
    insights.current = "";
    insights.file = file;
    if (insights.url) URL.revokeObjectURL(insights.url);
    insights.url = URL.createObjectURL(file);
    $("#insightPreview").src = insights.url;
    sessionSet(DOCUMENT_KEY, JSON.stringify(documentInfo));
    renderActiveDocument(documentInfo);
    $$(".insight-choice").forEach((b) => b.classList.remove("active"));
    toast("Document ready. Choose an insight.");
  } catch (error) {
    setError("#insightError", error.message || "The document could not be extracted.");
  } finally {
    $("#insightUploadLoading").classList.add("hidden");
    $("#insightUploadButton").disabled = false;
  }
}
$("#insightFile").addEventListener("change", () => {
  const file = $("#insightFile").files[0];
  $("#insightFileName").textContent = file ? `${file.name} · ${formatSize(file.size)}` : "Scanned pages are recognised automatically";
  $("#insightDrop").classList.toggle("has-file", Boolean(file));
});
wireDrop($("#insightDrop"), (files) => {
  const file = files[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  $("#insightFile").files = transfer.files;
  $("#insightFile").dispatchEvent(new Event("change"));
  if (isPdf(file)) uploadInsightFile(file);
});
$("#insightUploadForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const file = $("#insightFile").files[0];
  if (!file) return setError("#insightError", "Choose a PDF first.");
  uploadInsightFile(file);
});

function markText(html) {
  const q = insights.filter.trim();
  if (!q) return html;
  const safe = esc(q).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return html.replace(new RegExp(`(${safe})`, "gi"), "<mark>$1</mark>");
}
function pointMatches(point) {
  const q = insights.filter.trim().toLowerCase();
  return !q || `${point.text} ${point.evidence}`.toLowerCase().includes(q);
}
function insightPlainText(result, label) {
  const lines = [`${label} - ${result.filename}`, `${result.pages} pages, ${result.ocr_pages} OCR page(s)`, ""];
  (result.sections || []).forEach((section) => {
    lines.push(section.title.toUpperCase());
    section.points.forEach((point, i) => {
      lines.push(`${i + 1}. ${point.basis === "inference" ? "[Inference] " : ""}${point.text} (p. ${point.page_refs.join(", ")})`);
      if (point.evidence) lines.push(`   Source: "${point.evidence}"`);
    });
    lines.push("");
  });
  lines.push("AI-generated from the uploaded document. Verify against the original before relying on it.");
  return lines.join("\n");
}
function renderInsight(result, type) {
  const label = INSIGHT_LABELS[type] || result.insight_type;
  const output = $("#insightOutput");
  $("#insightEmpty").classList.add("hidden");
  const sections = (result.sections || []).map((section, s) => {
    const visible = section.points.filter(pointMatches);
    if (!visible.length) return "";
    const items = visible.map((point) => {
      const evidence = esc(point.evidence);
      const refs = point.page_refs.map(Number).map((n) =>
        `<button type="button" class="pref" data-goto="${n}"${insights.url ? "" : " disabled"} title="${insights.url ? "Show this page in the preview" : "Preview unavailable after a reload"}">p. ${n}</button>`).join("");
      return `<li class="pt"><span class="txt">${point.basis === "inference" ? '<span class="badge">Inference</span> ' : ""}${markText(esc(point.text))}</span>` +
        `<div class="meta">${refs}</div><blockquote>${markText(evidence)}</blockquote></li>`;
    }).join("");
    return `<details class="sec" open data-s="${s}"><summary>${esc(section.title)}<span class="count">${visible.length} point${visible.length === 1 ? "" : "s"}</span></summary><ol class="pts">${items}</ol></details>`;
  }).join("");
  const empty = (result.sections || []).length
    ? `<p class="banner banner-warn">No points match "${esc(insights.filter)}".</p>`
    : `<p class="banner banner-warn">${esc(result.message || "No source-grounded insight was returned.")}</p>`;
  output.className = insights.evidence ? "" : "hide-evidence";
  output.innerHTML =
    `<div class="out-head"><h3><span class="tag ${esc(type)}">${esc(label)}</span> ${esc(result.filename)}</h3>` +
    `<span class="muted">${esc(result.pages)} pages · ${esc(result.ocr_pages)} OCR page(s)</span></div>` +
    `<div class="toolbar"><input type="search" id="insightSearch" placeholder="Filter points and source text…" value="${esc(insights.filter)}" aria-label="Filter insight points">` +
    `<label><input type="checkbox" id="evidenceToggle"${insights.evidence ? " checked" : ""}> Show source text</label>` +
    `<button class="btn sm" type="button" id="expandAll">Expand all</button><button class="btn sm" type="button" id="collapseAll">Collapse all</button>` +
    `<button class="btn sm" type="button" id="copyInsight">${icon("copy")} Copy</button>` +
    `<button class="btn sm" type="button" id="saveInsight">${icon("download")} Save .txt</button>` +
    `<button class="btn sm" type="button" id="printInsight">${icon("print")} Print</button>` +
    `<button class="btn sm" type="button" id="regenInsight">Regenerate</button></div>` +
    `${sections || empty}`;
  const text = insightPlainText(result, label);
  $("#insightSearch").addEventListener("input", (event) => {
    insights.filter = event.target.value;
    const caret = event.target.selectionStart;
    renderInsight(result, type);
    const box = $("#insightSearch"); box.focus(); box.setSelectionRange(caret, caret);
  });
  $("#evidenceToggle").addEventListener("change", (event) => {
    insights.evidence = event.target.checked;
    output.classList.toggle("hide-evidence", !insights.evidence);
  });
  $("#expandAll").addEventListener("click", () => $$(".sec", output).forEach((d) => { d.open = true; }));
  $("#collapseAll").addEventListener("click", () => $$(".sec", output).forEach((d) => { d.open = false; }));
  $("#copyInsight").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(text); toast("Copied to clipboard."); } catch { toast("Copy is blocked by the browser."); }
  });
  $("#saveInsight").addEventListener("click", () =>
    downloadText(`${(result.filename || "document").replace(/\.pdf$/i, "")}_${type}.txt`, text));
  $("#printInsight").addEventListener("click", () => window.print());
  $("#regenInsight").addEventListener("click", () => runInsight(type, true));
  $$("[data-goto]", output).forEach((chip) => chip.addEventListener("click", () => {
    if (!insights.url) return;
    $("#insightPreviewBox").open = true;
    $("#insightPreview").src = `${insights.url}#page=${Number(chip.dataset.goto)}`;
    $("#insightPreviewBox").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }));
}

async function runInsight(type, force = false) {
  if (!activeDocument?.doc_id) return setError("#insightError", "Upload a PDF before selecting an insight.");
  setError("#insightError", "");
  insights.current = type;
  $$(".insight-choice").forEach((b) => b.classList.toggle("active", b.dataset.insight === type));
  const key = `${activeDocument.doc_id}:${type}`;
  if (!force && insights.cache.has(key)) {
    renderInsight(insights.cache.get(key), type);
    bump("reused");
    return toast(`${INSIGHT_LABELS[type]} reused. No new analysis needed.`);
  }
  $("#insightOutput").replaceChildren();
  $("#insightEmpty").classList.add("hidden");
  $("#insightLoadingText").textContent = `Generating ${INSIGHT_LABELS[type]} from the cached document text…`;
  $("#insightLoading").classList.remove("hidden");
  $("#insightSkeleton").classList.remove("hidden");
  $$(".insight-choice").forEach((choice) => { choice.disabled = true; });
  const started = performance.now();
  try {
    const result = await api(`/api/advocate/documents/${encodeURIComponent(activeDocument.doc_id)}/insights`, {
      method: "POST",
      json: { workspace_token: workspaceToken, insight_type: type },
    });
    if ((result.sections || []).length) {
      insights.cache.set(key, result);
      bump("insights");
      bump("lastMs", Math.round(performance.now() - started));
      $(`.insight-choice[data-insight="${type}"]`).classList.add("cached");
    }
    renderInsight(result, type);
  } catch (error) {
    $("#insightEmpty").classList.remove("hidden");
    setError("#insightError", error.message || "The selected insight could not be generated.");
  } finally {
    $("#insightLoading").classList.add("hidden");
    $("#insightSkeleton").classList.add("hidden");
    $$(".insight-choice").forEach((choice) => { choice.disabled = false; });
  }
}
$$(".insight-choice").forEach((button) => button.addEventListener("click", () => runInsight(button.dataset.insight)));

// ---------------------------------------------------------------- start
tokenBox($("#demoToken"), initialize);
renderMetrics();
updateStudioOperation();
$("#studioOperation").value = "merge";
updateStudioOperation();
initialize();
