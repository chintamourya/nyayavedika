// Staff app: Today, Intake, Docket (+ case drawer), Cause list, Undertrial.
// The server decides the role from the token and checks every call; tabs are only hidden for convenience.
demoBanner();
const ADVOCATE_DOOR = location.pathname === "/advocate";
let ROLE = null, LIMITS = { max_files: 5, max_files_per_folder: 2, max_pages_per_file: 50, max_file_mb: 25, allowed_types: ["pdf", "txt"] };
let limitsReady = false, limitsError = "";

if (ADVOCATE_DOOR) {
  document.title = "NyayaVedika - Advocate";
  $("#portalKind").textContent = "Advocate";
  $("#portalSubtitle").textContent = "Lawyer access to the shared justice-support platform";
  $("#tokenLabel").textContent = "Lawyer access token";
  $("#demoToken").placeholder = "Enter your lawyer token";
  $("#tokenHint").textContent = "Use the lawyer token configured by your administrator.";
  $("#signedInTokenHint").classList.add("hidden");
  $("#portalTabs").setAttribute("aria-label", "Advocate screens");
}

// Where a row came from (see the legend at the top of the page).
const SRC = { synthetic: ["src-synth", "Synthetic", "Generated demo data"], upload: ["src-upload", "Uploaded", "From documents sent through Intake"],
  csv: ["src-upload", "Imported", "From an imported CSV / JSON file"], citizen: ["src-upload", "Citizen request", "Asked for by a citizen"] };
function srcBadge(s) {
  const [cls, label, why] = SRC[s] || SRC.synthetic;
  return `<span class="badge ${cls}" title="${esc(why)}">${label}</span>`;
}
function engineBadge(label) {  // a summary / draft written by the model, or by the rules and templates
  const ai = /\bAI\b|llm|grok/i.test(label || "");
  return `<span class="badge ${ai ? "src-ai" : "src-rules"}" title="${esc(label || "")}">${ai ? "AI" : "Rules"}</span>`;
}
function mixLine(m) {
  if (!m) return "";
  const real = (m.upload || 0) + (m.csv || 0);
  return `Pending cases: ${srcBadge("synthetic")} ${m.synthetic || 0} &nbsp; ${srcBadge("upload")} ${real}` +
    (m.synthetic ? ` <span class="hint">- counts below include the synthetic demo cases.</span>` : "");
}

// Flags in plain words (the code stays in the tooltip and in the filters' values).
const FLAG_LABEL = { UNDERTRIAL_RELEASE_ELIGIBLE: "Past Sec. 479 limit", UNDERTRIAL_NEARING_THRESHOLD: "Near Sec. 479 limit",
  CUSTODY_DATE_MISSING: "Custody date missing", CUSTODY_UNKNOWN: "Custody unknown", TIME_BOUND_LAW: "Time-bound law",
  DECADE_OLD: "10+ years old", NEEDS_REVIEW: "Needs review", CHRONIC_ADJOURNMENT: "Often adjourned", DORMANT: "Not heard recently" };
const flagLabel = (f) => esc(FLAG_LABEL[f] || String(f ?? "").replace(/_/g, " ").toLowerCase());

// ---------------------------------------------------------------- shell
function showTab(name) {
  const switching = !$(`#tab-${name}`)?.classList.contains("active");
  $$(".tabs .tab[data-tab]").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$("main .panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + name));
  if (switching && window.scrollY > 0) window.scrollTo({ top: 0 });  // a new screen starts at its top, not mid-page
  ({ today: loadToday, docket: loadDocket, undertrial: loadAlerts }[name] || (() => {}))();
}
$$(".tabs .tab[data-tab]").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));

const ROLE_NAME = { staff: "Court staff", lawyer: "Lawyer", citizen: "Citizen" };
function signedIn(on) {  // signed in: show who you are + "Switch user"; signed out: the token field and Sign in
  $("#signinForm").classList.toggle("hidden", on);
  $("#signedIn").classList.toggle("hidden", !on);
}
async function whoami() {
  try {
    const me = await api("/api/whoami");
    ROLE = me.role;
    $("#who").textContent = `Signed in · ${ROLE_NAME[me.role] || me.role} (${me.actor})`;
    const roleAllowed = ADVOCATE_DOOR ? ROLE === "lawyer" : ["staff", "lawyer"].includes(ROLE);
    signedIn(roleAllowed);
    if (!roleAllowed) {
      $("#portalAccessMessage").textContent = ADVOCATE_DOOR
        ? "This is the Advocate portal. Enter a lawyer access token to continue; the current token does not have the lawyer role."
        : "This portal requires a Court Staff or lawyer access token. Enter one, or use the Citizen portal for citizen services.";
      $("#portalAccessMessage").classList.remove("hidden");
      $("#portalTabs").classList.add("hidden");
      $$("main .panel").forEach((panel) => panel.classList.remove("active"));
      return;
    }
    $$("[data-staff]").forEach((el) => el.classList.toggle("hidden", ROLE !== "staff"));
    $$("[data-court]").forEach((el) => el.classList.toggle("hidden", !["staff", "lawyer"].includes(ROLE)));
    if (ROLE === "citizen") toast("This token is a citizen token - use the citizen portal.", "error");
    $("#portalAccessMessage").classList.add("hidden");
    $("#portalTabs").classList.remove("hidden");
    if (ROLE !== "citizen") fillHow();
    if (ROLE === "staff") api("/api/intake/limits").then((l) => {
      LIMITS = l; limitsReady = true; limitsError = "";
      picked.forEach((p) => { p.reason = checkFile(p.file); });
      renderFiles();
    }).catch((e) => { limitsError = e.message; renderFiles(); });
    // show a screen again: a signed-out first load hides every panel, and signing in used to leave the page blank
    const active = $(".tabs .tab.active[data-tab]");
    showTab(active && !active.classList.contains("hidden") ? active.dataset.tab : "today");
  } catch (e) {
    signedIn(false);
    $("#who").textContent = "not signed in";
    $("#portalAccessMessage").textContent = ADVOCATE_DOOR
      ? "Enter a lawyer access token to use the Advocate portal."
      : "Enter a staff or lawyer access token to use this portal.";
    $("#portalAccessMessage").classList.remove("hidden");
    $("#portalTabs").classList.add("hidden");
    $$("main .panel").forEach((panel) => panel.classList.remove("active"));
  }
}
const tokenInput = $("#demoToken");
tokenBox(tokenInput, whoami);
if (!ADVOCATE_DOOR) {
  tokenInput.type = "text";
  tokenInput.value = "mourya";
  setToken("mourya");
}
$("#signinForm").addEventListener("submit", (e) => {  // Enter or the Sign in button
  e.preventDefault();
  setToken($("#demoToken").value);
  whoami();
});
$("#tokenChange").addEventListener("click", () => { signedIn(false); $("#demoToken").select(); $("#demoToken").focus(); });
whoami();

// ---------------------------------------------------------------- TODAY
async function loadToday() {
  const box = $("#todayKpis");
  try {
    const t = await api("/api/today");
    $("#todayMix").innerHTML = mixLine(t.data_mix);
    $("#pipeline").innerHTML = pipelineStrip(t.pipeline);
    $$("#pipeline [data-pipe]").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.pipe === "docket") setDocketFilters({});
      showTab(b.dataset.pipe);
    }));
    const k = (key, value, label, why, filter) =>
      `<button class="kpi click" data-filter='${esc(JSON.stringify(filter || {}))}' data-key="${key}"><b>${esc(value)}</b><span>${esc(label)}</span><small class="why">${esc(why)}</small></button>`;
    box.innerHTML = [
      k("crit", t.critical_waiting, "Critical waiting", "Critical band, not yet on an upcoming list", { band: "Critical", not_listed: true }),
      k("rel", t.release_eligible, "Release-eligible", "Past the Sec. 479 BNSS limit", { flag: "UNDERTRIAL_RELEASE_ELIGIBLE" }),
      k("past", t.past_deadline, "Past deadline", "Not listed by their band's deadline", { past_deadline: true }),
      k("rev", t.needs_review, "Needs review", "A field is missing or unsure", { needs_review: true }),
      k("up", t.uploaded_today, "Uploaded today", "Files received through Intake", null),
      k("def", t.deferred_3_plus, "Deferred 3+ times", "Left out of 3 published lists in a row - must-list next", { deferred3: true }),
    ].join("");
    $$("#todayKpis .kpi").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.key === "up") return showTab("intake");
      if (b.dataset.key === "rel" && ROLE === "lawyer") return showTab("undertrial");
      setDocketFilters(JSON.parse(b.dataset.filter)); showTab("docket");
    }));
    const todo = [];
    const proposals = capSyntheticExamples(t.fast_lane_proposals);
    proposals.rows.forEach((p) => todo.push(`<li>${band(p.band)} <b>${esc(p.case_id)}</b> ${p.source === "synthetic" ? srcBadge(p.source) : ""} proposed for ${esc(p.day)} ${esc(p.slot)} on ${esc(p.bench_id)} -
      <button class="btn small" data-accept="${esc(p.case_id)}" data-cl="${esc(p.cause_list_id ?? "")}">Accept slot</button> <button class="btn ghost small" data-open="${esc(p.case_id)}">Open case</button>
      <br><span class="hint">Why: ${esc(p.band)} cases are offered the first free slot at once (fast lane) instead of waiting for the weekly list.</span></li>`));
    if (proposals.omitted) todo.push(`<li>${syntheticLimitNote(proposals.omitted)}</li>`);
    if (t.needs_review) todo.push(`<li>${t.needs_review} case(s) need one field fixed - <button class="btn ghost small" data-goto="review">Show them</button></li>`);
    if (t.release_eligible) todo.push(`<li>${t.release_eligible} person(s) appear past the Sec. 479 limit - <button class="btn ghost small" data-goto="ut">Open Undertrial</button></li>`);
    if (t.past_deadline) todo.push(`<li>${t.past_deadline} case(s) are past their listing deadline - they will be must-list in the next draft. <button class="btn ghost small" data-goto="past">Show them</button></li>`);
    if (t.pipeline && !t.pipeline.latest_cause_list) todo.push(`<li>No cause list yet - <button class="btn ghost small" data-goto="cause">Prepare next week's draft</button></li>`);
    else if (t.pipeline?.latest_cause_list?.status === "draft") todo.push(`<li>Draft cause list #${esc(t.pipeline.latest_cause_list.id)} (week of ${esc(t.pipeline.latest_cause_list.start_date)}) is waiting for approval - <button class="btn ghost small" data-goto="cause">Review it</button></li>`);
    $("#todoList").innerHTML = todo.join("") || "<li>Nothing urgent right now.</li>";
    wireCaseButtons($("#todoList"));
    $$("[data-goto]", $("#todoList")).forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.goto === "ut") return showTab("undertrial");
      if (b.dataset.goto === "cause") return showTab("cause");
      setDocketFilters(b.dataset.goto === "past" ? { past_deadline: true } : { needs_review: true }); showTab("docket");
    }));
  } catch (e) { box.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}

function wireCaseButtons(root) {
  $$("[data-open]", root).forEach((b) => b.addEventListener("click", () => openDrawer(b.dataset.open)));
  $$("[data-accept]", root).forEach((b) => b.addEventListener("click", () => busy(b, async () => {
    const clId = b.dataset.cl || (cl && cl.status === "draft" ? cl.id : "");
    await api(`/api/cases/${b.dataset.accept}/accept-slot`, { json: { action: "accept", cause_list_id: clId ? Number(clId) : null } });
    toast("Slot accepted - it stays in the draft list until the Registrar publishes."); b.closest("li, .result")?.classList.add("hint");
  })));
  $$("[data-fix]", root).forEach((b) => b.addEventListener("click", () => correctDialog(b.dataset.fix, b.dataset.field)));
}

// ---------------------------------------------------------------- INTAKE
let picked = []; // {file, rel, reason}
function checkFile(f) {
  const ext = (f.name.split(".").pop() || "").toLowerCase();
  if (!LIMITS.allowed_types.includes(ext)) return `File type .${ext} is not accepted`;
  if (f.size === 0) return "The file is empty";
  if (f.size > LIMITS.max_file_mb * 1048576) return `${(f.size / 1048576).toFixed(1)} MB - limit is ${LIMITS.max_file_mb} MB`;
  return "";
}
function addFiles(list, fromFolder) {
  // list: File objects, or {file, rel} from a dropped folder. Junk (.DS_Store, Thumbs.db, ~$ temp files) is dropped silently.
  for (const it of list) {
    const f = it.file || it, rel = it.file ? it.rel : (fromFolder ? f.webkitRelativePath : "");
    if (isJunkFile(f.name, rel)) continue;
    picked.push({ file: f, rel, reason: checkFile(f) });
  }
  renderFiles();
}
function renderFiles() {
  const ok = picked.filter((p) => !p.reason);
  const total = ok.length + ($("#pasteText").value.trim() ? 1 : 0);
  $("#limitLine").textContent = limitsError
    ? `Could not load upload limits: ${limitsError}. Reload the page before submitting.`
    : limitsReady
      ? `Demo mode: up to ${LIMITS.max_files} files at a time, ${LIMITS.max_files_per_folder} files per folder, ${LIMITS.max_pages_per_file} pages and ${LIMITS.max_file_mb} MB per file. Types: ${LIMITS.allowed_types.join(", ")}.`
      : "Loading upload limits from the server…";
  const lots = Math.ceil(total / LIMITS.max_files);
  $("#fileCount").textContent = `${total} file(s)` + (lots > 1 ? ` - will be sent in ${lots} batches of up to ${LIMITS.max_files}` : "");
  $("#fileList").innerHTML = picked.map((p, i) => `<li><span>${esc(p.rel || p.file.name)} <span class="hint">${(p.file.size / 1024).toFixed(0)} KB</span>
    ${p.reason ? `<span class="why">✖ ${esc(p.reason)}</span>` : ""}</span><button class="btn ghost small" data-rm="${i}" aria-label="Remove ${esc(p.file.name)}">Remove</button></li>`).join("");
  $$("[data-rm]").forEach((b) => b.addEventListener("click", () => { picked.splice(+b.dataset.rm, 1); renderFiles(); }));
  $("#submitIntake").disabled = total === 0 || !limitsReady;
}
const dz = $("#dropzone");
["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
dz.addEventListener("drop", async (e) => addFiles(await filesFromDrop(e.dataTransfer), false));
$("#filePick").addEventListener("change", (e) => { addFiles(e.target.files, false); e.target.value = ""; });
$("#folderPick").addEventListener("change", (e) => { addFiles(e.target.files, true); e.target.value = ""; });
$("#pasteText").addEventListener("input", renderFiles);
$$("input[name=mode]").forEach((r) => r.addEventListener("change", () =>
  $("#caseNumber").classList.toggle("hidden", !["one_case", "existing_case"].includes($("input[name=mode]:checked").value))));

$("#submitIntake").addEventListener("click", (e) => busy(e.target, async () => {
  const errorBox = $("#intakeError");
  errorBox.textContent = "";
  errorBox.classList.add("hidden");
  const mode = $("input[name=mode]:checked").value;
  let files = picked.filter((p) => !p.reason);
  if (mode === "by_folder") files.sort((x, y) => (x.rel || "").localeCompare(y.rel || ""));  // keep a folder's files together
  if (mode === "by_folder" || files.some((p) => (p.rel || "").replace(/\\/g, "/").includes("/"))) {
    const folders = new Map();
    files.forEach((p) => {
      const path = (p.rel || p.file.name).replace(/\\/g, "/");
      const folder = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
      folders.set(folder, (folders.get(folder) || 0) + 1);
    });
    if ([...folders.values()].some((count) => count > LIMITS.max_files_per_folder)) {
      errorBox.textContent = `Each folder may contain up to ${LIMITS.max_files_per_folder} files. Move extra files to another folder or remove them.`;
      errorBox.classList.remove("hidden");
      return;
    }
  }
  const text = $("#pasteText").value.trim();
  let caseNo = $("#caseNumber").value.trim();
  const per = LIMITS.max_files, lots = [];
  if (text && files.length >= per) { lots.push({ chunk: files.slice(0, per - 1), text }); files = files.slice(per - 1); } else if (text) { lots.push({ chunk: files, text }); files = []; }
  for (let i = 0; i < files.length; i += per) lots.push({ chunk: files.slice(i, i + per), text: "" });
  // One case spread over several batches needs one shared case number, so the batches land on the same case.
  if (mode === "one_case" && lots.length > 1 && !caseNo) caseNo = `UPL/${new Date().getFullYear()}/${Math.random().toString(36).slice(2, 8).toUpperCase()}`;
  if (mode === "existing_case" && !caseNo) throw new Error("Enter the case number to attach these files to.");
  const batches = [];
  for (const [n, lot] of lots.entries()) {
    const fd = new FormData();
    lot.chunk.forEach((p) => { fd.append("files", p.file); fd.append("relative_paths", p.rel || p.file.name); });
    fd.append("mode", mode);
    if (caseNo && ["one_case", "existing_case"].includes(mode)) fd.append("case_number", caseNo);
    if (lot.text) fd.append("text", lot.text);
    $("#fileCount").textContent = `Sending batch ${n + 1} of ${lots.length}…`;
    try {
      batches.push(await api("/api/intake/batches", { form: fd }));
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove("hidden");
      if (batches.length) pollBatches(batches.map((batch) => batch.batch_id));
      return;
    }
  }
  picked = []; $("#pasteText").value = ""; renderFiles();
  pollBatches(batches.map((o) => o.batch_id));
}));

const STEPS = ["Uploaded", "Reading", "Summarising", "Prioritising", "Proposed hearing"];
const STAGE_AT = { queued: 0, reading: 1, summarising: 2, extracting: 3, scored: 3, needs_review: 3, proposed: 4, summarised: 3, failed: 0 };
const STEP_TIP = ["Saved; waiting for the reader", "Text taken from the PDF / text file, page by page",
  "One model call reads the file (or the rules if the model is unavailable)", "Facts extracted with page references, then the priority score",
  "Critical cases are offered the first free hearing slot at once"];
let pollTimer = null;
function pollBatch(id, first) {
  clearTimeout(pollTimer);
  const started = Date.now();
  const tick = async () => {
    try {
      const b = await api(`/api/intake/batches/${id}`);
      renderBatch(b, first);
      if (b.status === "running" && Date.now() - started > 45000 && b.files.every((f) => f.status === "queued")) {
        $("#batchView").insertAdjacentHTML("afterbegin",
          `<p class="banner-warn">⚠ Nothing has picked this up after 45 s. The intake worker may not be running: restart the server, or run <code>python -m nyayavedika.worker</code> in a second terminal.</p>`);
      }
      if (b.status === "running") pollTimer = setTimeout(tick, (b.poll_seconds || 2) * 1000);
    } catch (e) { $("#batchView").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  };
  tick();
}
function pollBatches(ids) {
  if (ids.length === 1) return pollBatch(ids[0]);
  clearTimeout(pollTimer);
  $("#batchView").innerHTML = ids.map((id) => `<div id="bv-${esc(id)}"></div>`).join("");
  const tick = async () => {
    let running = false;
    for (const id of ids) {
      try {
        const b = await api(`/api/intake/batches/${id}`);
        $(`#bv-${id}`).innerHTML = batchHtml(b); wireBatch($(`#bv-${id}`), b);
        running = running || b.status === "running";
      } catch (e) { $(`#bv-${id}`).innerHTML = `<p class="error">${esc(e.message)}</p>`; }
    }
    if (running) pollTimer = setTimeout(tick, 2000);
  };
  tick();
}
function steps(stage, status, f = {}) {
  const slot = !!(f.result && f.result.proposed_slot);
  // a failed job keeps the last stage it reached; a needs-review case can still have a fast-lane slot
  const at = slot ? 4 : STAGE_AT[stage === "failed" ? (f.last_stage || "queued") : stage] ?? 0;
  return `<div class="steps" aria-label="progress">${STEPS.map((s, i) => {
    let cls = i < at || (i === at && status === "done") ? "done" : i === at ? "now" : "";
    if (status === "failed" && i === at) cls = "bad";
    if (i === 4 && !slot && status === "done") return `<span class="step" title="Only Critical cases get a slot at once; the rest wait for the weekly cause list">${s}: not needed</span>`;
    return `<span class="step ${cls}" title="${esc(STEP_TIP[i])}">${cls === "done" ? "✓ " : cls === "bad" ? "✖ " : ""}${s}</span>`;
  }).join("")}</div>`;
}
function resultCard(f) {
  const r = f.result || {};
  if (f.status === "failed") return `<p class="error">✖ ${esc(f.error)}</p><button class="btn ghost small" data-retry="${esc(f.job_id)}">Retry</button>`;
  if (f.status !== "done") return `<p class="hint">${esc(f.error || "Working…")}</p>`;
  const slot = r.proposed_slot ? `<p>📅 Proposed hearing: <b>${esc(r.proposed_slot.day)} ${esc(r.proposed_slot.slot_start)}-${esc(r.proposed_slot.slot_end)}</b> on ${esc(r.proposed_slot.bench_id)}</p>` : "";
  const review = (r.review_fields || []).map((fld) => `<button class="btn small" data-fix="${esc(r.case_id)}" data-field="${esc(fld)}">Fill in ${pretty(fld)}</button>`).join(" ");
  return `<div class="result ${r.data_quality === "needs_review" ? "needs" : ""}">
    <div class="row gap wrap">${band(r.band)} <b>${esc(r.score)}</b> <span class="hint">score</span>${scoreBar(r.score, r.band)} <b>${esc(r.case_id)}</b> ${srcBadge("upload")} ${engineBadge(r.label)} <span class="hint">${esc(r.label || "")}</span></div>
    ${r.data_quality === "needs_review" ? `<p class="banner-warn">⚠ Needs review: ${review}</p>` : ""}
    <ul class="reasons">${(r.brief || []).map((l) => `<li>${esc(l)}</li>`).join("")}</ul>
    <div class="chips">${(r.reasons || []).slice(0, 5).map((x) => `<span class="chip">${esc(x)}</span>`).join("")}</div>
    ${(r.conflicts || []).length ? `<p class="banner-bad">Documents disagree on ${(r.conflicts || []).map((c) => pretty(c.field)).join(", ")} - fill it in after checking.</p>` : ""}
    ${slot}
    <div class="actions"><button class="btn small" data-open="${esc(r.case_id)}">Open case</button>
      <button class="btn ghost small" data-fix="${esc(r.case_id)}">Correct field</button>
      ${r.proposed_slot ? `<button class="btn ghost small" data-accept="${esc(r.case_id)}">Accept slot</button>` : ""}</div></div>`;
}
function batchHtml(b) {
  const skipped = (b.not_queued || []).map((f) => `<li>${esc(f.filename)} - <span class="why">${esc(f.reason)}</span></li>`).join("");
  return `<div class="card"><h3>Batch ${esc(b.batch_id)} · ${pretty(b.mode)} · ${esc(b.status)}${b.case_number ? ` · ${esc(b.case_number)}` : ""}</h3>
    ${skipped ? `<p class="hint">Not processed:</p><ul class="filelist">${skipped}</ul>` : ""}
    ${b.files.map((f) => `<div class="card"><b>${esc(f.filename)}</b>${steps(f.stage, f.status, f)}${resultCard(f)}</div>`).join("")}
    ${b.status !== "running" && b.files.some((f) => f.status === "done") ? `<p class="hint">Next: the cases are on the <a href="#" data-gotab="docket">Docket</a>; they join the next weekly <a href="#" data-gotab="cause">Cause list</a>.</p>` : ""}</div>`;
}
function wireBatch(root, b) {
  wireCaseButtons(root);
  $$("[data-gotab]", root).forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); if (a.dataset.gotab === "docket") setDocketFilters({}); showTab(a.dataset.gotab); }));
  $$("[data-retry]", root).forEach((btn) => btn.addEventListener("click", () => busy(btn, async () => {
    await api(`/api/intake/batches/${b.batch_id}/jobs/${btn.dataset.retry}/retry`, { method: "POST" }); pollBatch(b.batch_id);
  })));
}
function renderBatch(b) { $("#batchView").innerHTML = batchHtml(b); wireBatch($("#batchView"), b); }

const EDITABLE = ["filing_date", "stage", "case_type", "accused_in_custody", "custody_since", "max_sentence_years", "first_time_offender",
  "act", "section", "next_hearing_date", "status"];
function correctDialog(caseId, field) {
  $("#dialogBody").innerHTML = `<h3>Correct a field · ${esc(caseId)}</h3>
    <label>Field <select id="cfField">${EDITABLE.map((f) => `<option ${f === field ? "selected" : ""}>${f}</option>`).join("")}</select></label>
    <label>Value <input id="cfValue" placeholder="YYYY-MM-DD for dates, true/false for yes/no"></label>
    <p class="hint">The case is re-scored and the change is written to the audit log.</p>
    <button class="btn" id="cfSave">Save</button> <span id="cfOut"></span>`;
  $("#dialog").showModal();
  $("#cfSave").addEventListener("click", (e) => busy(e.target, async () => {
    const out = await api(`/api/cases/${caseId}`, { method: "PATCH", json: { [$("#cfField").value]: $("#cfValue").value } });
    $("#cfOut").innerHTML = `${band(out.priority.band)} ${esc(out.priority.score)} · ${out.data_quality === "complete" ? "✓ complete" : "still needs: " + esc(out.review_fields.join(", "))}`;
    toast("Saved and re-scored.");
  }));
}
$("#dialogClose").addEventListener("click", () => $("#dialog").close());

// ---------------------------------------------------------------- DOCKET + drawer
function setDocketFilters(f) {
  $("#fBand").value = f.band || ""; $("#fFlag").value = f.flag || ""; $("#fDef").checked = !!f.deferred3;
  $("#fReview").checked = !!f.needs_review; $("#fCustody").checked = !!f.custody; $("#fPast").checked = !!f.past_deadline;
  $("#fNotListed").checked = !!f.not_listed; $("#fType").value = f.case_type || ""; $("#fQ").value = f.q || "";
}
let docketSeq = 0;
function docketBands(byBand, active) {  // one chip per band with its count; click to filter, click again to clear
  if (!byBand) return "";
  return `<span class="hint">Triage bands:</span> ${Object.entries(byBand).map(([b, n]) =>
    `<button type="button" class="band-chip ${active === b ? "on" : ""}" data-band="${esc(b)}" aria-pressed="${active === b}">${band(b)} <b>${esc(n)}</b></button>`).join("")}
    ${active ? `<button type="button" class="btn ghost small" data-band="">Show all bands</button>` : ""}`;
}
async function loadDocket() {
  const p = new URLSearchParams({ band: $("#fBand").value, case_type: $("#fType").value, flag: $("#fFlag").value, q: $("#fQ").value });
  [["deferred3", "#fDef"], ["needs_review", "#fReview"], ["custody", "#fCustody"], ["past_deadline", "#fPast"], ["not_listed", "#fNotListed"]]
    .forEach(([k, s]) => { if ($(s).checked) p.set(k, "true"); });
  // the less-used filters live under "More filters": count the ones switched on, and open the panel when a Today
  // number turned one on, so it is clear why the list is shorter
  const hiddenOn = ["#fDef", "#fReview", "#fCustody", "#fPast", "#fNotListed"].filter((s) => $(s).checked).length + ($("#fFlag").value ? 1 : 0);
  $("#filterCount").textContent = `${hiddenOn} on`;
  $("#filterCount").classList.toggle("hidden", !hiddenOn);
  if (hiddenOn) $("#moreFilters").open = true;
  const seq = ++docketSeq;  // rapid filter changes: only the newest answer is drawn
  $("#docketTable").setAttribute("aria-busy", "true");
  $("#docketCount").textContent = "Loading the docket…";
  try {
    const d = await api(`/api/docket?${p}`);
    if (seq !== docketSeq) return;
    if ($("#fType").options.length <= 1) $("#fType").innerHTML += d.types.map((t) => `<option value="${esc(t)}">${pretty(t)}</option>`).join("");
    // band counts ignore the band filter itself (server side), so the other bands stay visible as one-click switches
    $("#docketBands").innerHTML = docketBands(d.by_band, $("#fBand").value);
    $$("#docketBands [data-band]").forEach((c) => c.addEventListener("click", () => {
      $("#fBand").value = $("#fBand").value === c.dataset.band ? "" : c.dataset.band; loadDocket();
    }));
    const display = capSyntheticExamples(d.rows);
    const synth = display.rows.filter((r) => r.source === "synthetic").length;
    $("#docketCount").innerHTML = `${d.total} pending case(s) match${d.total > display.rows.length ? `; showing ${display.rows.length} example(s)` : ""}.`
      + ` Of those shown: ${synth} synthetic, ${display.rows.length - synth} from uploads or imports.`
      + " " + syntheticLimitNote(display.omitted);
    $("#docketTable tbody").innerHTML = display.rows.map((r) => `<tr class="clickable" tabindex="0" data-case="${esc(r.case_id)}">
      <td><b>${esc(r.case_id)}</b> ${srcBadge(r.source)}${r.data_quality === "needs_review" ? ' <span class="flag">⚠ needs review</span>' : ""}</td>
      <td>${band(r.band)}</td><td class="num">${esc(r.score)}${scoreBar(r.score, r.band)}</td><td>${pretty(r.case_type)}<br><span class="hint">${pretty(r.stage || "stage missing")}</span></td>
      <td>${(r.flags || []).map((f) => `<span class="flag" title="${esc(f)}">${flagLabel(f)}</span>`).join("")}</td>
      <td>${r.deferred ? `${esc(r.deferred)}×${r.must_list ? ' <span class="must">must-list</span>' : ""}` : "-"}</td>
      <td>${esc(r.sla_due_on || "-")}${r.sla_due_on && r.sla_due_on < todayIso() ? ' <span class="flag">late</span>' : ""}</td>
      <td>${esc(r.next_hearing_date || "-")}${r.listed_on ? `<br><span class="hint">on ${esc(r.listing_status)} list ${esc(r.listed_on)}</span>` : ""}</td></tr>`).join("")
      || `<tr><td colspan="8" class="empty-row">No pending case matches these filters. <button type="button" class="btn ghost small" id="docketClear">Clear filters</button></td></tr>`;
    $("#docketClear")?.addEventListener("click", () => { setDocketFilters({}); loadDocket(); });
    $$("#docketTable tr[data-case]").forEach((tr) => {
      tr.addEventListener("click", () => openDrawer(tr.dataset.case));
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") openDrawer(tr.dataset.case); });
    });
  } catch (e) {
    if (seq === docketSeq) $("#docketCount").innerHTML = `<span class="error">${esc(e.message)}</span>`;
  } finally {
    if (seq === docketSeq) $("#docketTable").removeAttribute("aria-busy");
  }
}
$("#fApply").addEventListener("click", loadDocket);
$$("#docketFilters select, #docketFilters input[type=checkbox]").forEach((el) => el.addEventListener("change", loadDocket));
let docketTyping = null;  // search as you type (short pause), Enter searches at once
$("#fQ").addEventListener("input", () => { clearTimeout(docketTyping); docketTyping = setTimeout(loadDocket, 350); });
$("#fQ").addEventListener("keydown", (e) => { if (e.key === "Enter") { clearTimeout(docketTyping); loadDocket(); } });
function todayIso() { const d = new Date(), p = (n) => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; }

let current = null;
async function openDrawer(caseId) {
  try {
    [current] = await Promise.all([api(`/api/cases/${caseId}/detail`), loadRules()]);
    $("#dTitle").textContent = caseId; $("#dBand").innerHTML = band(current.priority.band);
    $("#drawer").classList.add("open"); $("#drawer").setAttribute("aria-hidden", "false");
    drawerTab("brief"); $("#dClose").focus();
  } catch (e) { toast(e.message, "error"); }
}
$("#dClose").addEventListener("click", () => { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#dClose").click(); });
$$("#drawer [data-dtab]").forEach((t) => t.addEventListener("click", () => drawerTab(t.dataset.dtab)));

function srcLink(prov) {
  if (!prov) return "";
  if (prov.source === "statute_ref") return `<span class="src">from statute table (${esc(prov.act)} ${esc(prov.section)})</span>`;
  if (prov.source === "staff") return `<span class="src">set by ${esc(prov.actor)}</span>`;
  if (prov.status === "conflict") return `<span class="src no">documents disagree: ${(prov.values || []).map((v) => esc(v.value)).join(" vs ")}</span>`;
  if (prov.doc_id) return `<span class="src">p. ${esc(prov.page)} · confidence ${esc(prov.confidence)} <button class="btn ghost small" data-page="${esc(prov.doc_id)}|${esc(prov.page)}">source page</button></span>`;
  return `<span class="src">${esc(prov.source || "")}</span>`;
}
function drawerTab(tab) {
  $$("#drawer [data-dtab]").forEach((t) => t.classList.toggle("active", t.dataset.dtab === tab));
  const c = current, body = $("#dBody");
  if (tab === "brief") {
    body.innerHTML = `${c.glance ? `<ul class="reasons">${c.glance.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : ""}
      ${c.review_fields.length ? `<p class="banner-warn">⚠ Needs review: ${c.review_fields.map((f) => `<button class="btn small" data-fix="${esc(c.case_id)}" data-field="${esc(f)}">Fill in ${pretty(f)}</button>`).join(" ")}</p>` : ""}
      ${Object.entries(c.facts).map(([k, v]) => `<div class="fact"><span class="hint">${pretty(k)}</span><span>${esc(v ?? "-")} ${srcLink(c.provenance[k])}</span></div>`).join("")}
      <p class="hint">Source: ${srcBadge(c.source)} · queue: deferred ${esc(c.queue.consecutive_deferrals || 0)}× · due by ${esc(c.queue.sla_due_on || "-")}</p>
      ${c.listings.length ? `<p>Listing: ${c.listings.map((l) => `${esc(l.day)} ${esc(l.slot_start)} ${esc(l.bench_id)} (${esc(l.status)})`).join("; ")}
        <button class="btn ghost small" data-accept="${esc(c.case_id)}">Accept slot</button></p>` : ""}
      <button class="btn ghost small" data-fix="${esc(c.case_id)}">Correct field</button>`;
  } else if (tab === "priority") {
    const p = c.priority, q = c.queue || {};
    body.innerHTML = `<p>${band(p.band)} <b>${esc(p.score)}</b> · ${esc(p.route || "")} <span class="hint">(${esc(p.rules_version || "")})</span></p>
      ${scoreBreakdown(p)}
      <p>${p.flags.map((f) => `<span class="flag" title="${esc(f)}">${flagLabel(f)}</span>`).join("")}</p>
      <h3>In the scheduling queue</h3>
      <p class="hint">Deferred ${esc(q.consecutive_deferrals || 0)}× in a row · aging boost +${esc(q.aging_boost || 0)} · due by ${esc(q.sla_due_on || "-")}
        ${q.must_list ? " · <b>must-list</b> in the next draft" : ""}. ${RULES ? `Effective score = ${esc(RULES.schedule.effective_score)}.` : ""}</p>
      ${p.ai_adjustment ? `<p>AI review ${esc(p.ai_adjustment)}: ${esc(p.ai_reason)}</p>` : ""}`;
  } else if (tab === "timeline") {
    body.innerHTML = c.timeline.length ? `<table><tr><th>Date</th><th>Event</th><th>Source</th></tr>${c.timeline.map((t) => `<tr><td>${esc(t.date)}</td><td>${esc(t.event)}</td>
      <td>${t.doc_id && t.page ? `<button class="btn ghost small" data-page="${esc(t.doc_id)}|${esc(t.page)}">${esc(t.filename || "doc")} p. ${esc(t.page)}</button>` : "-"}</td></tr>`).join("")}</table>`
      : "<p class='hint'>No dated events from documents yet.</p>";
  } else if (tab === "documents") {
    body.innerHTML = c.documents.map((d) => `<div class="card"><b>${esc(d.filename)}</b> · ${pretty(d.doc_type)} · ${esc(d.pages)} page(s) ${engineBadge(d.label)} <span class="hint">${esc(d.label || "")}</span>
      ${(d.glance || []).length ? `<ul class="reasons">${d.glance.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : ""}
      ${d.low_confidence_pages.length ? `<p class="banner-warn">Check pages ${esc(d.low_confidence_pages.join(", "))}: low OCR confidence</p>` : ""}
      <details><summary>One-page brief</summary><pre class="doc">${esc(d.brief || "")}</pre></details></div>`).join("") || "<p class='hint'>No documents.</p>";
  } else {
    const h = c.history;
    const hearings = c.source === "synthetic" ? h.hearings.slice(0, SYNTHETIC_EXAMPLE_LIMIT) : h.hearings;
    const deferrals = c.source === "synthetic" ? h.deferrals.slice(0, SYNTHETIC_EXAMPLE_LIMIT) : h.deferrals;
    const historyNote = c.source === "synthetic"
      ? syntheticLimitNote(Math.max(0, h.hearings.length - hearings.length) + Math.max(0, h.deferrals.length - deferrals.length))
      : "";
    body.innerHTML = `${historyNote}<h3>Hearings (adjourned in court)</h3><table><tr><th>Date</th><th>Bench</th><th>Outcome</th></tr>${hearings.map((x) => `<tr><td>${esc(x.hearing_date)}</td><td>${esc(x.bench_id)}</td><td>${pretty(x.outcome || "to be recorded")} ${esc(x.reason || "")}</td></tr>`).join("")}</table>
      <h3>Deferred by the scheduler</h3><table><tr><th>Run</th><th>Reason</th><th>Band</th></tr>${deferrals.map((x) => `<tr><td>${esc((x.run_at || "").slice(0, 10))}</td><td>${pretty(x.reason)}</td><td>${band(x.band)}</td></tr>`).join("") || "<tr><td colspan=3>None</td></tr>"}</table>`;
  }
  wireCaseButtons(body);
  $$("[data-page]", body).forEach((b) => b.addEventListener("click", async () => {
    const [doc, page] = b.dataset.page.split("|");
    try {
      const p = await api(`/api/documents/${doc}/pages/${page}`);
      $("#dialogBody").innerHTML = `<h3>${esc(p.filename)} · page ${esc(p.page)} of ${esc(p.pages)}</h3><pre class="doc">${esc(p.text || "(text not available)")}</pre>`;
      $("#dialog").showModal();
    } catch (e) { toast(e.message, "error"); }
  }));
}

// ---------------------------------------------------------------- CAUSE LIST (1 pick the week -> 2 check the draft -> 3 approve)
let cl = null;
$("#clStart").value = nextMonday();
function clStep(n) {
  $$("#clFlow li").forEach((li) => { const s = +li.dataset.step; li.className = s < n ? "done" : s === n ? "now" : ""; });
}
$("#clDraft").addEventListener("click", (e) => busy(e.target, async () => {
  await loadRules();
  const out = await api("/api/cause-lists/draft", { json: { start_date: $("#clStart").value, days: 5 } });
  cl = { id: out.cause_list_id, plan: out, status: "draft" };
  renderCauseList();
  $("#clView").scrollIntoView({ behavior: "smooth" });
}));

$("#staffSummaryForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const submitter = e.submitter;
  const originalLabel = submitter?.textContent;
  if (submitter) submitter.textContent = "Summarizing...";
  busy(submitter, async () => {
    const errorBox = $("#staffSummaryError");
    const progressBox = $("#staffSummaryStatus");
    errorBox.textContent = "";
    errorBox.classList.add("hidden");
    progressBox.classList.add("hidden");
    let progress;
    try {
      const file = $("#staffSummaryFile").files[0];
      const text = $("#staffSummaryText").value.trim();
      if (Boolean(file) === Boolean(text)) throw new Error("Choose one PDF/TXT file or paste document text.");
      if (file && !/\.(pdf|txt)$/i.test(file.name)) throw new Error("Choose a PDF or TXT file.");
      if (file && !file.size) throw new Error("The selected file is empty.");
      progress = createSummaryProgress("staffSummaryStatus", {
        cancel: "Cancel",
        canceling: "Canceling...",
        canceled: "Canceled. No summary was returned. The server may continue processing.",
        timeout: "Stopped waiting after 5 minutes. No result was received; the server may still be processing.",
        elapsed: "{time} elapsed",
        preparing: "Preparing the document: {percent}%",
        sending: "Sending the document to the server...",
        waiting: "Request sent. The server is reading the document and preparing the summary. Keep this page open.",
      });
      $("#staffSummaryOut").innerHTML = "";
      const body = file
        ? { filename: file.name, content_base64: await fileToBase64(file, {
          signal: progress.signal,
          onProgress: (loaded, total) => progress.set(`Preparing the document: ${Math.floor(loaded / total * 100)}%`),
        }) }
        : { filename: "document.txt", text };
      progress.set("Sending the document to the server...");
      const request = api("/api/documents/summarize", { json: body, signal: progress.signal });
      progress.set("Request sent. The server is reading the document and preparing the summary. Keep this page open.");
      const result = await request;
      progress.complete(result.mode === "llm"
        ? "AI summary ready."
        : "Rules-based summary ready. AI was unavailable; see the note in the result.");
      const analysis = result.analysis || {};
      const verification = result.verification || {};
      const summaryLabels = {
        summary_case_details: "Case details",
        summary_case_number: "Case number",
        summary_court: "Court",
        summary_parties: "People involved",
        summary_custody_since: "In custody since",
        summary_outcome: "Outcome in this paper",
        summary_next_hearing: "Next hearing",
        summary_timeline: "What happened",
        summary_issues: "Issues discussed",
        summary_statutes: "Laws mentioned",
        summary_directions: "What the court says to do",
        summary_not_found: "Not stated in the pages read",
        summary_page: "Page {page}",
        summary_show_brief: "Show the full text view",
      };
      $("#staffSummaryOut").innerHTML = `<div class="card">
        <h3>${esc(result.filename)} · ${esc(result.pages)} page(s) <span class="badge ${result.mode === "llm" ? "src-ai" : "src-rules"}">${esc(result.label || result.mode)}</span></h3>
        <section class="summary-view-lead">
          <h4>What this paper says</h4>
          <p>${esc(result.plain || analysis.plain_language_summary || "No plain-language summary was produced.")}</p>
        </section>
        ${renderDocumentSummaryDetails(result, (key) => summaryLabels[key] || key)}
        <p class="hint">Document type: ${esc(result.doc_type || "unknown")} · ${verification.overall_grounded ? "Grounding checks passed" : "Check details against the original"}</p>
        ${verification.unverified?.length ? `<p class="banner-warn">Check: ${verification.unverified.map(esc).join("; ")}</p>` : ""}
        ${result.low_confidence_pages?.length ? `<p class="banner-warn">Low OCR confidence on page(s): ${esc(result.low_confidence_pages.join(", "))}</p>` : ""}
      </div>`;
    } catch (error) {
      if (progress?.signal.aborted) {
        if (progress.timedOut()) {
          progress.fail("Stopped waiting after 5 minutes. No result was received; the server may still be processing.");
          errorBox.textContent = "The request timed out. The server may still be processing; no summary was returned.";
          errorBox.classList.remove("hidden");
        } else {
          progress.cancelled("Canceled. No summary was returned. The server may continue processing.");
        }
      } else {
        const detail = error.message || "An unexpected error occurred.";
        progress?.fail(`Summary failed: ${detail}`);
        errorBox.textContent = `Could not summarize the document: ${detail}`;
        errorBox.classList.remove("hidden");
      }
    } finally {
      progress?.dispose();
      if (submitter) submitter.textContent = originalLabel;
    }
  });
});

const weekday = (d) => new Date(d + "T00:00:00").toLocaleDateString(undefined, { weekday: "long" });
function clCase(c, conflictIds) {
  const real = c.source && c.source !== "synthetic";
  return `<li class="lc ${conflictIds.has(c.case_id) ? "conflict" : ""}" tabindex="0" data-move="${esc(c.case_id)}" title="${esc(c.route || "")} - click to move or hold">
    <span class="slot">${esc(c.slot.split("-")[0])}</span>${band(c.band)} <b>${esc(c.case_id)}</b> ${real ? srcBadge(c.source) : ""}
    ${c.must_list ? `<span class="must">must-list${c.deferred ? ` · deferred ${esc(c.deferred)}×` : ""}</span>` : ""}</li>`;
}
function renderCauseList() {
  if (!cl) return;
  const p = cl.plan, m = p.metrics, b = m.baseline_fifo || {};
  const REASON = { capacity: "no bench time left that week", advocate_conflict: "the advocate is in another court then", no_bench: "no bench takes this case type" };
  clStep(cl.status === "draft" ? 2 : 4);
  const conflictIds = new Set((p.violations || []).flatMap((v) => (v.match(/\(([^ ]+) on/g) || []).map((x) => x.slice(1, -3))));
  const listed = p.calendar.flatMap((d) => d.benches.flatMap((x) => x.cases));
  const allCaseExamples = capSyntheticExamples([...listed, ...p.unscheduled]);
  const visibleCaseIds = new Set(allCaseExamples.rows.map((c) => c.case_id));
  const uploaded = listed.filter((c) => c.source && c.source !== "synthetic").length;
  const unscheduledDisplay = p.unscheduled.filter((c) => c.source !== "synthetic" || visibleCaseIds.has(c.case_id));
  const problems = [
    ...(p.capacity_shortfall ? [`Not enough bench time: ${p.capacity_shortfall.message}`] : []),
    ...(p.violations || []),
    ...((p.deadline_alerts || []).length ? [`${p.deadline_alerts.length} critical case(s) cannot be listed by their deadline.`] : []),
  ];
  const k = (v, l, why) => `<div class="kpi"><b>${esc(v)}</b><span>${esc(l)}</span><small class="why">${esc(why)}</small></div>`;
  const row = (label, a, z, better) => `<tr><td>${esc(label)}</td><td><b>${esc(a)}</b></td><td>${esc(z)}</td><td>${better ? "✓ better" : ""}</td></tr>`;
  const elsewhere = p.already_listed || [];
  // the whole week on one screen: bench x day, share of the sitting time planned, and how many matters
  const benchIds = (p.calendar[0]?.benches || []).map((x) => x.bench_id);
  const loadLevel = (u) => (u > 95 ? "full" : u > 75 ? "high" : u > 40 ? "mid" : u > 0 ? "low" : "none");
  const loadGrid = `<div class="table-wrap"><table class="load-grid" aria-label="Bench time planned per day">
    <thead><tr><th scope="col">Bench</th>${p.calendar.map((d) => `<th scope="col">${esc(weekday(d.date).slice(0, 3))} <span class="hint">${esc(d.date.slice(5))}</span></th>`).join("")}</tr></thead>
    <tbody>${benchIds.map((id) => `<tr><th scope="row">${esc(id)}</th>${p.calendar.map((d) => {
      const x = d.benches.find((y) => y.bench_id === id) || {};
      if (x.open === false) return `<td class="load closed" title="Closed (judge on leave)">closed</td>`;
      const u = x.utilisation_percent || 0;
      return `<td class="load ${loadLevel(u)}" title="${esc(x.cases?.length || 0)} matter(s), ${esc(x.expected_minutes || 0)} of ${esc(x.minutes_per_day || 0)} min">${esc(Math.round(u))}%<small>${esc(x.cases?.length || 0)} case${(x.cases?.length || 0) === 1 ? "" : "s"}</small></td>`;
    }).join("")}</tr>`).join("")}</tbody></table></div>
    <p class="hint">Each cell: share of the bench's sitting time planned (expected minutes, allowing for likely adjournments) and the number of matters.</p>`;
  $("#clView").innerHTML = `<div class="card">
    <h3>2. Check the draft <span class="hint">· draft #${esc(cl.id)} · ${esc(cl.status)}</span></h3>
    <div class="kpis">
      ${k(m.cases_listed, "cases listed", `${uploaded} uploaded · ${m.cases_listed - uploaded} synthetic`)}
      ${k(`${m.must_list_listed}/${m.must_list_total}`, "must-list cases fitted", "urgent, or deferred 3+ times")}
      ${k(m.cases_carried_over, "carried to a later week", "reasons at the bottom")}
      ${k(`${m.avg_bench_utilisation_percent}%`, "bench time used", "average over the week")}
      ${elsewhere.length ? k(elsewhere.length, "already listed elsewhere", "kept on their existing slot - not listed twice") : ""}
    </div>
    <details class="compare-box" open><summary>Week at a glance - bench load</summary>
      ${m.balance_note ? `<p class="hint"><b>${m.balanced ? "⚖ Balanced week." : "▤ Packed week."}</b> ${esc(m.balance_note)}</p>` : ""}${loadGrid}</details>
    ${problems.length ? `<div class="banner-bad"><b>Check before approving:</b><br>${problems.map(esc).join("<br>")}</div>`
      : `<div class="banner-ok">✓ All checks pass: every must-list case fits, no advocate is in two courts at once, no bench runs over time.</div>`}
    ${syntheticLimitNote(allCaseExamples.omitted)}
    <details class="compare-box"><summary>Why this order? Compare with listing oldest-first</summary>
      <table><tr><th></th><th>This draft</th><th>Oldest-first</th><th></th></tr>
        ${row("Average wait of critical cases (days)", m.critical_avg_wait_days, b.critical_avg_wait_days, m.critical_avg_wait_days < b.critical_avg_wait_days)}
        ${row("Advocate double-bookings", m.advocate_conflicts, b.advocate_conflicts, m.advocate_conflicts < b.advocate_conflicts)}
        ${row("Hearings expected to go ahead", m.expected_effective_hearings, b.expected_effective_hearings, m.expected_effective_hearings > b.expected_effective_hearings)}
        ${row("Cases listed", m.cases_listed, b.cases_listed, m.cases_listed > b.cases_listed)}</table></details>
    <p class="hint">Open a day to see its list. ${cl.status === "draft" ? "Click a case to see why it is there, or to move or hold it." : "Click a case to open it."}
      Cases without a badge are synthetic demo cases. <span class="must">must-list</span> = placed first in the reserved time.</p>
    ${p.calendar.map((d, i) => {
      const n = d.benches.reduce((s, x) => s + x.cases.length, 0);
      return `<details class="day" ${i === 0 ? "open" : ""}><summary><b>${esc(weekday(d.date))} ${esc(d.date)}</b> · ${n} case(s)
          ${d.benches.some((x) => x.open === false) ? '<span class="hint">· a bench is closed</span>' : ""}</summary>
        <div class="benches">${d.benches.map((x) => x.open === false
          ? `<div class="bench closed"><b>${esc(x.bench_id)}</b> <span class="hint">closed (judge on leave)</span></div>`
          : `<div class="bench"><div class="row between"><span><b>${esc(x.bench_id)}</b> <span class="hint">${esc(x.name)}</span></span>
              <span class="hint">${esc(x.utilisation_percent)}% of the day</span></div>
              <div class="util"><i class="${x.utilisation_percent > 90 ? "hi" : ""}" style="width:${Math.min(100, x.utilisation_percent)}%"></i></div>
              <ul class="slots">${x.cases.filter((c) => c.source !== "synthetic" || visibleCaseIds.has(c.case_id)).slice(0, 60).map((c) => clCase(c, conflictIds)).join("") || "<li class='hint'>No displayed examples</li>"}</ul>
              ${x.cases.filter((c) => c.source !== "synthetic" || visibleCaseIds.has(c.case_id)).length > 60 ? `<span class="hint">More cases are included in the draft.</span>` : ""}</div>`).join("")}</div></details>`;
    }).join("")}
    ${p.unscheduled.length ? `<details class="day"><summary><b>Carried to a later week</b> · ${p.unscheduled.length} case(s)</summary>
        <p class="hint">Each of these is deferred +1 when the list is published, so it climbs in next week's draft.</p>
      <ul>${unscheduledDisplay.map((u) => `<li>${band(u.band)} ${esc(u.case_id)} ${u.source && u.source !== "synthetic" ? srcBadge(u.source) : ""} - ${esc(REASON[u.reason] || u.reason)}${u.must_list ? ' <span class="must">must-list</span>' : ""}</li>`).join("")}</ul></details>` : ""}
    ${elsewhere.length ? `<details class="day"><summary><b>Already listed elsewhere this week</b> · ${elsewhere.length} case(s)</summary>
        <p class="hint">These cases already hold a slot on another list for these dates (an accepted fast-lane slot, a published list or another draft), so this draft does not list them again.</p>
      <ul>${capSyntheticExamples(elsewhere).rows.map((u) => `<li>${band(u.band)} ${esc(u.case_id)} ${u.source && u.source !== "synthetic" ? srcBadge(u.source) : ""} - ${esc(u.day)} ${esc((u.slot || "").split("-")[0])} on ${esc(u.bench_id)} <span class="hint">(${esc(u.listing_status)}, list #${esc(u.cause_list_id)})</span></li>`).join("")}</ul></details>` : ""}
  </div>
  <div class="card">
    <h3>3. Approve and publish</h3>
    ${cl.status === "draft"
      ? `<p>Publishing will: create ${esc(m.cases_listed)} hearing(s) · set each listed case's next date · reset their deferral count ·
           defer the ${esc(p.unscheduled.length)} carried-over case(s) by one. Until then this is only a draft.</p>
         ${problems.length ? `<p class="banner-warn">There are ${problems.length} problem(s) above - publish only if you accept them.</p>` : ""}
         <button class="btn" id="clPublish">Approve and publish</button>`
      : `<div class="banner-ok">✓ Published. Hearings are created; next dates are set; carried-over cases were deferred +1. They appear on the <a href="#" id="clToDocket">Docket</a>.</div>`}
  </div>`;
  $("#clPublish")?.addEventListener("click", (e) => busy(e.target, async () => {
    const out = await api(`/api/cause-lists/${cl.id}/publish`, { method: "POST" });
    cl.status = "published"; renderCauseList(); toast(`Published: ${out.hearings_created} hearing(s) created.`);
  }));
  $("#clToDocket")?.addEventListener("click", (e) => { e.preventDefault(); setDocketFilters({}); showTab("docket"); });
  $$("[data-move]").forEach((el) => {
    const go = () => moveDialog(el.dataset.move);
    el.addEventListener("click", go); el.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  });
}
function moveDialog(caseId) {
  if (cl.status !== "draft") return openDrawer(caseId);
  const days = cl.plan.calendar.map((d) => d.date), benches = cl.plan.calendar[0].benches.map((b) => b.bench_id);
  const currentDay = cl.plan.calendar.find((d) => d.benches.some((b) => b.cases.some((c) => c.case_id === caseId)))?.date;
  const item = cl.plan.calendar.flatMap((d) => d.benches.flatMap((b) => b.cases)).find((c) => c.case_id === caseId);
  $("#dialogBody").innerHTML = `<h3>${esc(caseId)} ${item ? band(item.band) : ""}</h3>
    ${item ? `<p class="hint">Why it is here:</p>${whyListed(item)}` : ""}
    <p><button class="btn ghost small" data-open="${esc(caseId)}">Open case</button></p>
    <h3>Move to…</h3><label>Day <select id="mvDay"><option value="${esc(currentDay || "")}">${currentDay ? `Keep current day (${esc(currentDay)})` : "Any day"}</option>${days.filter((d) => d !== currentDay).map((d) => `<option>${esc(d)}</option>`).join("")}</select></label>
    <label>Bench <select id="mvBench"><option value="">any bench</option>${benches.map((b) => `<option>${esc(b)}</option>`).join("")}</select></label>
    <p class="hint">Choose a day or bench. The move is checked for capacity and advocate clashes.
      Holding takes the case off this list for 7 days (not counted as a deferral).</p>
    <button class="btn" id="mvGo">Move</button> <button class="btn ghost" id="mvHold">Hold this case</button>`;
  $("#dialog").showModal();
  wireCaseButtons($("#dialogBody"));
  const updateMoveAvailability = () => {
    $("#mvGo").disabled = !$("#mvDay").value && !$("#mvBench").value;
  };
  $("#mvDay").addEventListener("change", updateMoveAvailability);
  $("#mvBench").addEventListener("change", updateMoveAvailability);
  updateMoveAvailability();
  $("#mvGo").addEventListener("click", (e) => busy(e.target, async () => {
    const out = await api(`/api/cases/${caseId}/accept-slot`, { json: { action: "move", day: $("#mvDay").value || null, bench_id: $("#mvBench").value || null, cause_list_id: cl.id } });
    toast(`Moved to ${out.slot.day} ${out.slot.slot_start} on ${out.slot.bench_id}.`); $("#dialog").close();
    relocate(caseId, out.slot);
  }));
  $("#mvHold").addEventListener("click", (e) => busy(e.target, async () => {
    await api(`/api/cases/${caseId}/accept-slot`, { json: { action: "hold", cause_list_id: cl.id } });
    toast("On hold for 7 days."); $("#dialog").close(); relocate(caseId, null);
  }));
}
function relocate(caseId, slot) { // reflect a move / hold in the draft view
  let item = null;
  cl.plan.calendar.forEach((d) => d.benches.forEach((b) => {
    const i = b.cases.findIndex((c) => c.case_id === caseId);
    if (i >= 0) { item = b.cases[i]; b.cases.splice(i, 1); }
  }));
  if (slot && item) {
    const bench = cl.plan.calendar.find((d) => d.date === slot.day)?.benches.find((b) => b.bench_id === slot.bench_id);
    bench && bench.cases.push({ ...item, slot: `${slot.slot_start}-${slot.slot_end}` });
    bench && bench.cases.sort((x, y) => x.slot.localeCompare(y.slot));
  }
  renderCauseList();
}

// ---------------------------------------------------------------- UNDERTRIAL (found -> lawyer approves -> filed -> heard -> released)
const UT_NEXT = { approved: [["filed", "Mark as filed in court"]], filed: [["heard", "Mark as heard"]],
  heard: [["released", "Released on bond"], ["denied", "Release denied"]] };
const UT_STEP = { pending: 1, approved: 2, filed: 3, heard: 4, released: 5, denied: 5, dismissed: 1 };
function alertCard(a) {
  const over = a.days_over_limit > 0;
  const lawyer = ROLE === "lawyer";
  const releaseReview = ["undertrial_release", "release_review_request"].includes(a.kind);
  const next = UT_NEXT[a.status];
  const primary = a.status === "pending"
    ? (lawyer ? `<button class="btn" data-approve="${a.id}">Approve - file a release application</button>`
              : `<span class="hint">Waiting for a legal-aid lawyer to approve.</span>`)
    : next ? next.map(([to, label], i) => `<button class="btn ${i ? "ghost" : ""}" data-advance="${a.id}" data-to="${to}">${label}</button>`).join(" ") : "";
  const step = UT_STEP[a.status] || 1;
  const track = ["Found", "Approved", "Filed", "Heard", a.status === "denied" ? "Denied" : "Released"]
    .map((s, i) => `<li class="${i + 1 < step ? "done" : i + 1 === step ? "now" : ""}">${s}</li>`).join("");
  return `<div class="card ut">
    <div class="row between wrap">
      <div><b>${esc(a.case_id)}</b> ${srcBadge(a.source)}
        <span class="badge ${a.days_over_limit >= 0 ? "band-critical" : "band-high"}">${over ? "‼ " + esc(a.days_over_limit) + " days over the limit" : a.days_over_limit === 0 ? "‼ at the limit today" : "▲ near the limit"}</span>
        ${a.status !== "pending" ? `<span class="pill">now: ${pretty(a.status)}</span>` : ""}</div>
      <span class="hint">${esc(a.custody_days ?? "?")} days in custody · legal limit ${esc(a.threshold_days ?? "?")} days${a.basis ? ` (${esc(a.basis)})` : ""}${a.release_status && a.release_status !== "eligible" ? ` · ${esc(a.release_status.replace("_", " "))}` : ""}</span></div>
    <ol class="flow small">${track}</ol>
    ${custodyMath(a)}
    ${(a.release_notes || []).length ? `<p class="banner-warn">${a.release_notes.map(esc).join("<br>")}</p>` : ""}
    <div class="actions">${primary}
      <button class="btn ghost" data-docx="${a.id}">Download application (Word)</button>
      ${releaseReview ? `<button class="btn ghost" data-superintendent="${a.id}" data-language="en">Custody-record review request (English)</button>
      <button class="btn ghost" data-superintendent="${a.id}" data-language="hi">निरुद्धि-अवधि जाँच निवेदन (हिन्दी)</button>
      <button class="btn ghost" data-superintendent="${a.id}" data-language="te">నిర్బంధ కాల వివరాల పరిశీలన వినతి (తెలుగు)</button>` : ""}</div>
    <details><summary>Read the draft application ${engineBadge(a.draft_engine === "ai" ? "AI" : "rules")} and the checklist</summary>
      <div class="alertcard"><pre class="doc">${esc(a.draft || "")}</pre>
        <div><h3>Verify before filing</h3><div class="checklist">${((a.details || {}).checklist || []).map((c) => `<label><input type="checkbox"> ${esc(c)}</label>`).join("")}</div></div></div></details>
    ${lawyer && ["pending", "approved"].includes(a.status) ? `<details><summary>Not needed? Dismiss</summary>
      <label>Reason (required) <input data-reason="${a.id}"></label>
      <label>Check again after <input type="date" data-snooze="${a.id}"></label>
      <button class="btn ghost small" data-dismiss="${a.id}">Dismiss</button></details>` : ""}
  </div>`;
}
async function loadAlerts() {
  loadRules();
  $("#utRole").textContent = ROLE === "lawyer" ? "You are signed in as a legal-aid lawyer: you approve or dismiss."
    : "You can read these; a legal-aid lawyer approves or dismisses.";
  try {
    // both lists load at once; a failure of the missing-information list does not hide the alerts
    const needP = api("/api/alerts/data-needed").catch((e) => ({ error: e.message, data_needed: [] }));
    const { alerts } = await api("/api/alerts?status=all");
    const decide = alerts.filter((a) => a.status === "pending");
    const progress = alerts.filter((a) => UT_NEXT[a.status]);
    $("#utNeedH").textContent = `Needs a decision (${decide.length})`;
    $("#utProgH").textContent = `In progress (${progress.length})`;
    const closed = alerts.filter((a) => ["released", "denied", "dismissed"].includes(a.status));
    $("#utFlow").innerHTML = [["Found", "pending"], ["Lawyer approves", "approved"], ["Filed in court", "filed"], ["Heard", "heard"]]
      .map(([l, s]) => `<li title="${alerts.filter((a) => a.status === s).length} alert(s) at this step">${l} <b>${alerts.filter((a) => a.status === s).length}</b></li>`).join("")
      + `<li title="released, denied or dismissed">Closed <b>${closed.length}</b></li>`;
    const alertDisplay = capSyntheticExamples(alerts);
    const visibleDecide = alertDisplay.rows.filter((a) => a.status === "pending");
    const visibleProgress = alertDisplay.rows.filter((a) => UT_NEXT[a.status]);
    $("#utDecide").innerHTML = visibleDecide.map(alertCard).join("") + syntheticLimitNote(alertDisplay.omitted)
      || "<p class='hint'>Nothing is waiting for a decision. ✓</p>";
    $("#utProgress").innerHTML = visibleProgress.map(alertCard).join("")
      || "<p class='hint'>Nothing in progress.</p>";
    const root = $("#tab-undertrial");
    $$("[data-approve]", root).forEach((b) => b.addEventListener("click", () => busy(b, async () => {
      await api("/api/alerts/decide", { json: { decisions: { [b.dataset.approve]: { approve: true } } } }); toast("Approved - now file it in court."); loadAlerts();
    })));
    $$("[data-dismiss]", root).forEach((b) => b.addEventListener("click", () => busy(b, async () => {
      const id = b.dataset.dismiss, reason = $(`[data-reason="${id}"]`).value.trim(), snooze = $(`[data-snooze="${id}"]`).value;
      if (!reason) throw new Error("A dismissal needs a reason.");
      await api("/api/alerts/decide", { json: { decisions: { [id]: { approve: false, reason, snooze_until: snooze || null } } } });
      toast("Dismissed - it will not come back unless the facts change."); loadAlerts();
    })));
    $$("[data-advance]", root).forEach((b) => b.addEventListener("click", () => busy(b, async () => {
      await api(`/api/alerts/${b.dataset.advance}/state`, { json: { status: b.dataset.to } }); toast(`Marked ${b.dataset.to}.`); loadAlerts();
    })));
    $$("[data-docx]", root).forEach((b) => b.addEventListener("click", () => busy(b, async () => {
      toast(`Downloaded ${await downloadFrom(`/api/alerts/${b.dataset.docx}/release.docx`, {}, "release_application.docx")}`);
    })));
    $$("[data-superintendent]", root).forEach((b) => b.addEventListener("click", () => busy(b, async () => {
      const language = b.dataset.language;
      const filename = `custody_record_review_request_${language}.docx`;
      toast(`Downloaded ${await downloadFrom(
        `/api/alerts/${b.dataset.superintendent}/superintendent.docx?language=${language}`, {}, filename)}`);
    })));
    const need = await needP;
    if (need.error) { $("#utNeeded").innerHTML = `<li class="error">${esc(need.error)}</li>`; return; }
    $("#utNeededH").textContent = `Missing information (${need.data_needed.length} case(s))`;
    const neededDisplay = capSyntheticExamples(need.data_needed);
    $("#utNeeded").innerHTML = neededDisplay.rows.map((d) => `<li><b>${esc(d.case_id)}</b> ${d.source === "synthetic" ? srcBadge(d.source) : ""}: missing ${d.missing.map(pretty).join(", ")} - ask ${esc(d.who_can_supply.join("; "))}</li>`).join("") || "<li>None.</li>";
    if (neededDisplay.omitted) $("#utNeeded").insertAdjacentHTML("beforeend", `<li>${syntheticLimitNote(neededDisplay.omitted)}</li>`);
  } catch (e) { $("#utDecide").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}
$("#utScan").addEventListener("click", (e) => busy(e.target, async () => {
  const out = await api("/api/jobs/undertrial_scan/run", { method: "POST" });
  toast(`Checked: ${out.new_release_alerts} new, ${out.data_needed} need information.`); loadAlerts();
}));

renderFiles();
