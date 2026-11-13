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
// Uploaded and imported records always come before synthetic demo examples; the order inside each group is kept
// (priority, time slot, days over the mark ...), so a real case is never buried under generated ones.
const isSynthetic = (row) => (row?.source || "synthetic") === "synthetic";
function realFirst(rows) {
  return [...(rows || [])].map((row, i) => [row, i])
    .sort(([a, i], [b, j]) => (isSynthetic(a) - isSynthetic(b)) || (i - j)).map(([row]) => row);
}
function capRealFirst(rows, limit) { return capSyntheticExamples(realFirst(rows), limit); }
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
  ({ today: loadToday, docket: loadDocket, undertrial: loadAlerts, cause: () => { loadSavedLists(); loadClPreview(); } }[name] || (() => {}))();
}
$$(".tabs .tab[data-tab]").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
$$("[data-workflow-tab]").forEach((button) => button.addEventListener("click", () => {
  const tab = button.dataset.workflowTab;
  if (tab === "diary") {   // the Court diary lives on Today
    showTab("today");
    $("#diaryCard").scrollIntoView({ behavior: "smooth" });
    return;
  }
  if (tab === "docket") setDocketFilters({});
  showTab(tab);
}));

// ---------------------------------------------------------------- first-visit guide
const GUIDE_KEY = "nyayavedika_staff_guide_seen";
function guideSeen() { try { return localStorage.getItem(GUIDE_KEY) === "1"; } catch { return false; } }
function markGuideSeen() { try { localStorage.setItem(GUIDE_KEY, "1"); } catch { /* shown again next visit */ } }
$("#guideDone").addEventListener("click", () => { markGuideSeen(); $("#staffGuide").open = false; });
$("#guideStart").addEventListener("click", () => { markGuideSeen(); $("#staffGuide").open = false; setDocketFilters({}); showTab("docket"); });
$("#guideOpen").addEventListener("click", () => { showTab("today"); $("#staffGuide").open = true; $("#staffGuide").scrollIntoView({ behavior: "smooth" }); });

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
    if (ROLE === "staff" && !guideSeen()) $("#staffGuide").open = true;   // first visit: the whole flow, up front
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
    const proposals = capRealFirst(t.fast_lane_proposals);
    proposals.rows.forEach((p) => todo.push(`<li>${band(p.band)} <b>${esc(p.case_id)}</b> ${p.source === "synthetic" ? srcBadge(p.source) : ""} proposed for ${esc(p.day)} ${esc(p.slot)} on ${esc(p.bench_id)} -
      <button class="btn small" data-accept="${esc(p.case_id)}" data-cl="${esc(p.cause_list_id ?? "")}">Accept slot</button> <button class="btn ghost small" data-open="${esc(p.case_id)}">Open case</button>
      <br><span class="hint">Why: ${esc(p.band)} cases are offered the first free slot at once (fast lane) instead of waiting for the weekly list.</span></li>`));
    if (proposals.omitted) todo.push(`<li>${syntheticLimitNote(proposals.omitted)}</li>`);
    if (t.needs_review) todo.push(`<li>${t.needs_review} case(s) need one field fixed - <button class="btn ghost small" data-goto="review">Show them</button></li>`);
    if (t.release_eligible) todo.push(`<li>${t.release_eligible} person(s) appear past the Sec. 479 limit - <button class="btn ghost small" data-goto="ut">Open Undertrial</button></li>`);
    if (t.past_deadline) todo.push(`<li>${t.past_deadline} case(s) are past their listing deadline - they will be must-list in the next draft. <button class="btn ghost small" data-goto="past">Show them</button></li>`);
    if (t.pipeline && !t.pipeline.latest_cause_list) todo.push(`<li>No cause list yet - <button class="btn ghost small" data-goto="cause">Prepare next week's draft</button></li>`);
    else if (t.pipeline?.latest_cause_list?.status === "draft") todo.push(`<li>Draft cause list #${esc(t.pipeline.latest_cause_list.id)} (week of ${esc(t.pipeline.latest_cause_list.start_date)}) is waiting for approval - <button class="btn ghost small" data-goto="cause" data-cl="${esc(t.pipeline.latest_cause_list.id)}">Review it</button></li>`);
    $("#todoList").innerHTML = todo.join("") || "<li>Nothing urgent right now.</li>";
    wireCaseButtons($("#todoList"));
    $$("[data-goto]", $("#todoList")).forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.goto === "ut") return showTab("undertrial");
      if (b.dataset.goto === "cause") {
        showTab("cause");
        // "Review it" used to land on an empty screen: the draft lived only in the page that prepared it
        if (b.dataset.cl) openCauseList(Number(b.dataset.cl));
        return;
      }
      setDocketFilters(b.dataset.goto === "past" ? { past_deadline: true } : { needs_review: true }); showTab("docket");
    }));
    if (ROLE === "staff") renderTriageFocus(t);
  } catch (e) { box.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  if (ROLE === "staff") { loadDiary(); loadSchedFocus(); }
}

// ---------------------------------------------------------------- Today: triage and scheduling at a glance
const BAND_ORDER = ["Critical", "High", "Medium", "Routine"];
function bandBar(byBand, attr = "data-focus-band") {
  const total = BAND_ORDER.reduce((s, b) => s + (byBand?.[b] || 0), 0) || 1;
  return `<div class="band-bar" role="group" aria-label="Pending cases by band">${BAND_ORDER.map((b) => {
    const n = byBand?.[b] || 0;
    return n ? `<button type="button" class="band-seg ${b.toLowerCase()}" ${attr}="${b}" style="flex-grow:${n / total}"
      title="${esc(n)} ${esc(b)} case(s) - open them">${esc(n)}</button>` : "";
  }).join("")}</div>
  <div class="band-key">${BAND_ORDER.map((b) => `<span>${band(b)} ${esc(byBand?.[b] || 0)}</span>`).join("")}</div>`;
}
function renderTriageFocus(t) {
  const top = t.top_unlisted || [];
  const synth = top.filter((r) => r.source === "synthetic").length;
  $("#triageFocusBody").innerHTML = `
    <p class="focus-lead"><b>${esc(t.pipeline?.docket_pending ?? 0)}</b> pending matter(s) ranked by fixed rules.
      <b>${esc(t.critical_waiting)}</b> Critical not yet on a list${t.release_eligible ? ` · <b>${esc(t.release_eligible)}</b> past the Sec. 479 mark` : ""}${t.needs_review ? ` · <b>${esc(t.needs_review)}</b> with a detail to verify` : ""}.</p>
    ${bandBar(t.by_band)}
    <h4>Top of the queue - no hearing slot yet</h4>
    ${top.length ? `<ol class="queue-top">${top.map((r) => `<li><button class="linkish" data-open="${esc(r.case_id)}">${esc(r.case_id)}</button>
        ${r.source === "synthetic" ? srcBadge("synthetic") : srcBadge(r.source)} ${band(r.band)} <b>${esc(r.score)}</b>
        <span class="hint">${pretty(r.case_type || "")}${r.stage ? ` · ${pretty(r.stage)}` : ""}</span>
        ${r.attention?.length ? `<br><span class="hint">${esc(r.attention[0].text)}</span>` : ""}</li>`).join("")}</ol>
        ${synth ? `<p class="hint">Uploaded and imported cases are shown first; synthetic examples fill the rest.</p>` : ""}`
      : `<p class="empty-state">Every pending matter already holds a hearing slot.</p>`}
    <div class="row gap wrap"><button class="btn" type="button" data-focus-go="triage">Open the triage queue →</button>
      ${t.needs_review ? `<button class="btn ghost" type="button" data-focus-go="review">Verify ${esc(t.needs_review)} detail(s)</button>` : ""}</div>`;
  const root = $("#triageFocus");
  wireCaseButtons(root);
  $$("[data-focus-band]", root).forEach((b) => b.addEventListener("click", () => { setDocketFilters({ band: b.dataset.focusBand }); showTab("docket"); }));
  $$("[data-focus-go]", root).forEach((b) => b.addEventListener("click", () => {
    setDocketFilters(b.dataset.focusGo === "review" ? { needs_review: true } : { not_listed: true }); showTab("docket");
  }));
}
function hours(min) { return `${(Number(min || 0) / 60).toFixed(min >= 600 ? 0 : 1)} h`; }
function capacityMeter(pv) {
  const cap = pv.capacity_minutes || 0, need = pv.waiting_minutes || 0;
  const max = Math.max(cap, need, 1);
  return `<div class="cap-meter" role="img" aria-label="Bench time ${hours(cap)}, waiting work ${hours(need)}">
      <div class="cap-row"><span>Bench time</span><div class="cap-track"><i class="cap" style="width:${(100 * cap / max).toFixed(1)}%"></i></div><b>${hours(cap)}</b></div>
      <div class="cap-row"><span>Waiting work</span><div class="cap-track"><i class="need ${need > cap ? "over" : ""}" style="width:${(100 * need / max).toFixed(1)}%"></i>
        <i class="must" style="width:${(100 * (pv.must_list_minutes || 0) / max).toFixed(1)}%" title="Must-list share"></i></div><b>${hours(need)}</b></div>
    </div>`;
}
function previewHtml(pv, compact) {
  return `<p class="focus-lead ${pv.fits ? "ok" : "warn"}">${pv.fits ? "✓" : "⚠"} ${esc(pv.verdict)}</p>
    ${capacityMeter(pv)}
    <ul class="sched-facts">
      <li><b>${esc(pv.sittings)}</b> bench sittings on ${esc(pv.days.length)} working day(s)${pv.closed_days.length ? ` <span class="hint">(court closed ${esc(pv.closed_days.join(", "))})</span>` : ""}${pv.benches_on_leave ? ` <span class="hint">· ${esc(pv.benches_on_leave)} bench-day(s) on leave</span>` : ""}</li>
      <li><b>${esc(pv.waiting)}</b> matter(s) waiting to be listed, of which <b>${esc(pv.must_list)}</b> must-list
        (Critical, custody past the mark, deadline missed or left out 3 times)${pv.must_list_over_reserve ? ` - <span class="why">more than the time kept aside for them</span>` : ""}</li>
      ${!compact ? `<li>${esc(pv.past_deadline)} past their listing deadline · ${esc(pv.in_custody)} in custody · ${esc(pv.on_hold)} on hold · ${esc(pv.already_listed)} already hold a slot that week</li>` : ""}
    </ul>
    <p class="hint">${esc(pv.note)} An estimate before drafting; the draft is the real check.</p>`;
}
async function loadSchedFocus() {
  const start = nextMonday();
  try {
    const [pv, lists] = await Promise.all([api(`/api/scheduling/preview?start=${start}`), api("/api/cause-lists?limit=12")]);
    const open = lists.lists.find((l) => l.status === "draft" && !l.fast_lane && l.start_date === start);
    $("#schedFocusH").textContent = `Scheduling - week of ${start}`;
    $("#schedFocusBody").innerHTML = `${previewHtml(pv, true)}
      <div class="row gap wrap">${open
        ? `<button class="btn" type="button" data-sched-open="${esc(open.id)}">Review draft #${esc(open.id)} →</button>`
        : `<button class="btn" type="button" data-sched-go>Prepare this week's draft →</button>`}</div>`;
    $("[data-sched-open]", $("#schedFocus"))?.addEventListener("click", (e) => { showTab("cause"); openCauseList(Number(e.target.dataset.schedOpen)); });
    $("[data-sched-go]", $("#schedFocus"))?.addEventListener("click", () => { $("#clStart").value = start; showTab("cause"); });
  } catch (e) { $("#schedFocusBody").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}

// ---------------------------------------------------------------- COURT DIARY (published hearings + outcomes)
const OUTCOME_LABEL = { heard: "Heard", adjourned: "Adjourned", disposed: "Disposed", not_reached: "Not reached" };
const ADJ_REASONS = ["Advocate sought time", "Witness not present", "Accused not produced", "Summons / notice not served",
  "Records or report awaited", "Presiding Officer on leave", "Part-heard, to continue"];
function isoAdd(iso, days) {
  const d = new Date(iso + "T00:00:00"); d.setDate(d.getDate() + days);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
let diarySeq = 0;
function diaryRow(h, showDate) {
  const done = !!h.outcome;
  const outcome = done
    ? `<span class="outcome-tag ${esc(h.outcome)}">${esc(OUTCOME_LABEL[h.outcome] || h.outcome)}</span>${h.next_date ? ` <span class="hint">next ${esc(h.next_date)}</span>` : ""}${h.reason ? `<br><span class="hint">${esc(h.reason)}</span>` : ""}`
    : `<span class="outcome-tag pending">To record</span>`;
  const ready = (h.readiness || []).map((n) => `<li>${esc(n)}</li>`).join("");
  return `<tr class="${done ? "recorded" : ""}">
    <td class="num">${showDate ? `${esc(h.hearing_date)}<br>` : ""}${esc(h.slot_start || "-")}</td>
    <td><b>${esc(h.case_id)}</b> ${h.source === "synthetic" ? srcBadge("synthetic") : ""}<br><span class="hint">${pretty(h.case_type || "")}${h.stage ? ` · ${pretty(h.stage)}` : ""}</span></td>
    <td>${band(h.band)}${h.accused_in_custody ? ' <span class="flag" title="Accused in custody">custody</span>' : ""}</td>
    <td>${ready ? `<ul class="ready-notes">${ready}</ul>` : '<span class="hint">Nothing to check</span>'}</td>
    <td>${outcome}</td>
    <td class="diary-actions"><button class="btn ${done ? "ghost " : ""}small" data-outcome="${esc(h.hearing_id)}" data-case="${esc(h.case_id)}" data-date="${esc(h.hearing_date)}">${done ? "Correct" : "Record"}</button>
      <button class="btn ghost small" data-open="${esc(h.case_id)}">Open</button></td></tr>`;
}
function diaryTable(rows, showDate) {
  return `<div class="table-wrap"><table class="diary-table"><thead><tr><th>${showDate ? "Date / time" : "Time"}</th><th>Case</th><th>Band</th>
    <th>Check before the call</th><th>Proceedings</th><th></th></tr></thead><tbody>${rows.map((h) => diaryRow(h, showDate)).join("")}</tbody></table></div>`;
}
async function loadDiary(day) {
  if (ROLE !== "staff") return;
  const input = $("#diaryDay");
  if (day) input.value = day;
  if (!input.value) input.value = todayIso();
  const seq = ++diarySeq;
  $("#diaryBody").setAttribute("aria-busy", "true");
  try {
    const d = await api(`/api/hearings?start=${encodeURIComponent(input.value)}&days=1`);
    if (seq !== diarySeq) return;
    const c = d.counts;
    const label = input.value === todayIso() ? "Today" : new Date(input.value + "T00:00:00").toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
    $("#diaryCounts").innerHTML = c.listed
      ? `<b>${esc(label)}:</b> ${esc(c.listed)} matter(s) listed · <span class="ok">${esc(c.recorded)} recorded</span> · <b>${esc(c.to_record)}</b> to record${c.in_custody ? ` · ${esc(c.in_custody)} in custody (production needed)` : ""}`
      : `<b>${esc(label)}:</b> no matters on a published cause list.`;
    const shown = capRealFirst(d.hearings);
    const benches = [...new Set(shown.rows.map((h) => h.bench_id))];
    $("#diaryBody").innerHTML = shown.rows.length
      ? benches.map((b) => `<div class="diary-bench"><h4>${esc(b)} <span class="hint">· ${shown.rows.filter((h) => h.bench_id === b).length} matter(s)</span></h4>
          ${diaryTable(shown.rows.filter((h) => h.bench_id === b), false)}</div>`).join("") + syntheticLimitNote(shown.omitted)
      : `<p class="empty-state">No hearings on a published list for this day. Lists become hearings only when the Registrar publishes them on the <a href="#" data-gotab="cause">Cause list</a> screen.</p>`;
    const back = capRealFirst(d.unrecorded_earlier || []);
    $("#diaryBacklogH").textContent = `Earlier hearings with no outcome recorded (${(d.unrecorded_earlier || []).length})`;
    $("#diaryBacklogBox").classList.toggle("hidden", !(d.unrecorded_earlier || []).length);
    $("#diaryBacklog").innerHTML = back.rows.length
      ? `<p class="hint">From the last 30 days. Until an outcome is recorded the case keeps a past next date, and the adjournment history used for planning stays incomplete.</p>${diaryTable(back.rows, true)}${syntheticLimitNote(back.omitted)}`
      : "";
    const root = $("#diaryCard");
    wireCaseButtons(root);
    $$("[data-gotab]", root).forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); showTab(a.dataset.gotab); }));
    $$("[data-outcome]", root).forEach((b) => b.addEventListener("click", () => outcomeDialog(b.dataset.outcome, b.dataset.case, b.dataset.date)));
  } catch (e) {
    if (seq === diarySeq) $("#diaryBody").innerHTML = `<p class="error">Could not load the diary: ${esc(e.message)}</p>`;
  } finally {
    if (seq === diarySeq) $("#diaryBody").removeAttribute("aria-busy");
  }
}
$("#diaryDay").addEventListener("change", () => loadDiary());
$("#diaryPrev").addEventListener("click", () => loadDiary(isoAdd($("#diaryDay").value || todayIso(), -1)));
$("#diaryNext").addEventListener("click", () => loadDiary(isoAdd($("#diaryDay").value || todayIso(), 1)));
$("#diaryToday").addEventListener("click", () => loadDiary(todayIso()));

function outcomeDialog(hearingId, caseId, hearingDate) {
  $("#dialogBody").innerHTML = `<h3>Record proceedings · ${esc(caseId)}</h3>
    <p class="hint">Hearing of ${esc(hearingDate)}. Record what the court did; this does not change any order. It is written to the audit log and can be corrected.</p>
    <fieldset class="q outcome-pick"><legend>What happened?</legend>
      ${Object.entries(OUTCOME_LABEL).map(([v, l], i) => `<label><input type="radio" name="ocOutcome" value="${v}" ${i === 1 ? "checked" : ""}> ${esc(l)}</label>`).join("")}
    </fieldset>
    <div id="ocAdj"><label for="ocReasonPick">Reason for adjournment</label>
      <select id="ocReasonPick">${ADJ_REASONS.map((r) => `<option>${esc(r)}</option>`).join("")}<option value="">Other (type below)</option></select></div>
    <label for="ocReason">Note <span class="hint">(optional, up to 300 characters)</span></label>
    <input id="ocReason" maxlength="300" placeholder="e.g. Counsel for the accused sought time to file reply">
    <div id="ocNextWrap"><label for="ocNext">Next date fixed by the court</label>
      <input id="ocNext" type="date" min="${esc(isoAdd(hearingDate, 1))}"></div>
    <p id="ocErr" class="banner-bad hidden" role="alert"></p>
    <div class="row gap"><button class="btn" id="ocSave">Save</button></div>`;
  $("#dialog").showModal();
  const sync = () => {
    const o = $("input[name=ocOutcome]:checked").value;
    $("#ocAdj").classList.toggle("hidden", o !== "adjourned");
    $("#ocNextWrap").classList.toggle("hidden", o === "disposed");
    $("label[for=ocNext]").textContent = o === "heard" ? "Next date (if the matter continues)" : "Next date fixed by the court";
  };
  $$("input[name=ocOutcome]").forEach((r) => r.addEventListener("change", sync));
  sync();
  $("#ocSave").addEventListener("click", (e) => busy(e.target, async () => {
    const outcome = $("input[name=ocOutcome]:checked").value;
    const next = $("#ocNext").value;
    const note = $("#ocReason").value.trim();
    const reason = outcome === "adjourned" ? [$("#ocReasonPick").value, note].filter(Boolean).join(" - ") : note;
    const err = $("#ocErr");
    const fail = (m) => { err.textContent = m; err.classList.remove("hidden"); };
    err.classList.add("hidden");
    if (["adjourned", "not_reached"].includes(outcome) && !next) return fail("Enter the next date the court fixed.");
    if (next && next <= hearingDate) return fail("The next date must be after the hearing date.");
    if (outcome === "adjourned" && !reason) return fail("Choose or type the reason for the adjournment.");
    await api(`/api/hearings/${hearingId}/outcome`, { json: { outcome, reason: reason || null, next_date: outcome === "disposed" ? null : (next || null) } });
    $("#dialog").close();
    toast(`${caseId}: ${OUTCOME_LABEL[outcome]} recorded${next && outcome !== "disposed" ? `, next date ${next}` : ""}.`);
    loadDiary();
  }));
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
  const mode = $("input[name=mode]:checked")?.value;
  const needsNumber = mode === "existing_case" && !$("#caseNumber").value.trim();
  const rejected = picked.length - ok.length;
  $("#intakeCheck").innerHTML = [
    rejected ? `<span class="why">✖ ${rejected} file(s) will be skipped - see the reasons above.</span>` : "",
    needsNumber ? `<span class="why">Enter the case number to attach these files to.</span>` : "",
  ].filter(Boolean).join(" ");
  $("#submitIntake").disabled = total === 0 || !limitsReady || needsNumber;
}
const dz = $("#dropzone");
["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
dz.addEventListener("drop", async (e) => addFiles(await filesFromDrop(e.dataTransfer), false));
$("#filePick").addEventListener("change", (e) => { addFiles(e.target.files, false); e.target.value = ""; });
$("#folderPick").addEventListener("change", (e) => { addFiles(e.target.files, true); e.target.value = ""; });
$("#pasteText").addEventListener("input", renderFiles);
$$("input[name=mode]").forEach((r) => r.addEventListener("change", () => {
  const mode = $("input[name=mode]:checked").value;
  $("#caseNumber").classList.toggle("hidden", !["one_case", "existing_case"].includes(mode));
  $("#caseNumber").placeholder = mode === "existing_case" ? "case number on the Docket (required), e.g. SC/2024/9"
    : "case number if known (optional), e.g. SC/2024/9";
  renderFiles();
}));
$("#caseNumber").addEventListener("input", renderFiles);

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
let pollTimer = null, pollRun = 0, pollIds = [];
const POLL_MAX_MISSES = 5;   // a brief network or server hiccup must not stop the progress view for good
// a retry inside a multi-batch view keeps every batch of that submission on screen
function pollBatch(id) { pollBatches(pollIds.includes(id) ? pollIds : [id]); }
function pollBatches(ids) {
  clearTimeout(pollTimer);
  pollIds = [...ids];
  const run = ++pollRun, started = Date.now();
  let misses = 0;
  $("#batchView").innerHTML = ids.map((id) => `<div data-batch-view="${esc(id)}"></div>`).join("");
  const box = (id) => $(`[data-batch-view="${CSS.escape(id)}"]`);
  const tick = async () => {
    let running = false, failedNow = false, stalled = false;
    for (const id of ids) {
      try {
        const b = await api(`/api/intake/batches/${encodeURIComponent(id)}`);
        if (run !== pollRun) return;   // a newer submission took over the view
        box(id).innerHTML = batchHtml(b); wireBatch(box(id), b);
        running = running || b.status === "running";
        stalled = stalled || (b.status === "running" && b.files.length > 0 && b.files.every((f) => f.status === "queued"));
      } catch (e) {
        if (run !== pollRun) return;
        failedNow = true;
        if (e.status && e.status < 500 && e.status !== 429) { box(id).innerHTML = `<p class="error">${esc(e.message)}</p>`; continue; }
        running = true;   // transient: keep the last view and try again
        box(id).querySelector(".poll-warn")?.remove();
        box(id).insertAdjacentHTML("afterbegin", `<p class="banner-warn poll-warn">Lost contact with the server (${esc(e.message)}). Retrying…</p>`);
      }
    }
    misses = failedNow ? misses + 1 : 0;
    if (stalled && Date.now() - started > 45000 && !$("#batchView .stall-warn")) {
      $("#batchView").insertAdjacentHTML("afterbegin",
        `<p class="banner-warn stall-warn">⚠ Nothing has picked this up after 45 s. The intake worker may not be running: restart the server, or run <code>python -m nyayavedika.worker</code> in a second terminal.</p>`);
    }
    if (misses >= POLL_MAX_MISSES) {
      $("#batchView").insertAdjacentHTML("afterbegin", `<p class="banner-bad">Stopped checking after ${POLL_MAX_MISSES} failed attempts. The files are still queued on the server.
        <button class="btn ghost small" type="button" id="pollResume">Check again</button></p>`);
      $("#pollResume")?.addEventListener("click", () => pollBatches(ids));
      return;
    }
    if (running) pollTimer = setTimeout(tick, Math.min(15000, 2000 * 2 ** misses));
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
function batchSummary(b) {
  const n = b.files.length, done = b.files.filter((f) => f.status === "done").length;
  const failed = b.files.filter((f) => f.status === "failed").length;
  const review = b.files.filter((f) => f.status === "done" && f.result?.data_quality === "needs_review").length;
  const working = n - done - failed;
  const pct = n ? Math.round((100 * (done + failed)) / n) : 100;
  return `<div class="batch-summary" role="status" aria-live="polite">
    <div class="batch-bar" aria-hidden="true"><i style="width:${pct}%"></i></div>
    <span><b>${esc(done)}</b> of ${esc(n)} done</span>${working ? ` · <span>${esc(working)} working</span>` : ""}
    ${failed ? ` · <span class="error">${esc(failed)} failed</span>` : ""}${review ? ` · <span class="why">${esc(review)} need a detail checked</span>` : ""}
    ${failed > 1 ? ` <button class="btn ghost small" data-retry-all>Retry all failed</button>` : ""}</div>`;
}
function batchHtml(b) {
  const skipped = (b.not_queued || []).map((f) => `<li>${esc(f.filename)} - <span class="why">${esc(f.reason)}</span></li>`).join("");
  return `<div class="card"><h3>Batch ${esc(b.batch_id)} · ${pretty(b.mode)} · ${esc(b.status)}${b.case_number ? ` · ${esc(b.case_number)}` : ""}</h3>
    ${batchSummary(b)}
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
  $$("[data-retry-all]", root).forEach((btn) => btn.addEventListener("click", () => busy(btn, async () => {
    const failed = b.files.filter((f) => f.status === "failed");
    const out = await Promise.allSettled(failed.map((f) =>
      api(`/api/intake/batches/${b.batch_id}/jobs/${f.job_id}/retry`, { method: "POST" })));
    const bad = out.filter((o) => o.status === "rejected").length;
    toast(bad ? `${failed.length - bad} retried; ${bad} could not be retried.` : `${failed.length} file(s) sent back to the queue.`, bad ? "error" : "info");
    pollBatch(b.batch_id);
  })));
}

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
  // a queue stays highlighted only while its exact filters are on
  const q = QUEUES.find((x) => JSON.stringify(x[3]) === JSON.stringify(f || {}));
  activeQueue = q ? q[0] : "";
  renderQueues();
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
    lastDocket = d;
    if ($("#fType").options.length <= 1) $("#fType").innerHTML += d.types.map((t) => `<option value="${esc(t)}">${pretty(t)}</option>`).join("");
    // band counts ignore the band filter itself (server side), so the other bands stay visible as one-click switches
    $("#docketBands").innerHTML = docketBands(d.by_band, $("#fBand").value);
    $$("#docketBands [data-band]").forEach((c) => c.addEventListener("click", () => {
      $("#fBand").value = $("#fBand").value === c.dataset.band ? "" : c.dataset.band; loadDocket();
    }));
    const display = capRealFirst(d.rows);
    const synth = display.rows.filter((r) => r.source === "synthetic").length;
    $("#docketCount").innerHTML = `${d.total} pending case(s) match${d.total > display.rows.length ? `; showing ${display.rows.length} example(s)` : ""}.`
      + ` Of those shown: ${synth} synthetic, ${display.rows.length - synth} from uploads or imports.`
      + " " + syntheticLimitNote(display.omitted);
    $("#docketTable tbody").innerHTML = display.rows.map((r) => `<tr class="clickable" tabindex="0" data-case="${esc(r.case_id)}">
      <td><b>${esc(r.case_id)}</b> ${srcBadge(r.source)}${r.data_quality === "needs_review" ? ' <span class="flag">⚠ needs review</span>' : ""}</td>
      <td>${band(r.band)}</td><td class="num">${esc(r.score)}${scoreBar(r.score, r.band)}${driverList(r.drivers)}</td><td>${pretty(r.case_type)}<br><span class="hint">${pretty(r.stage || "stage missing")}</span></td>
      <td>${(r.flags || []).map((f) => `<span class="flag" title="${esc(f)}">${flagLabel(f)}</span>`).join("")}${attentionList(r.attention)}</td>
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
// The biggest point contributions behind a score (same reasons as the drawer's Priority tab).
function driverList(drivers) {
  if (!drivers || !drivers.length) return "";
  return `<ul class="drivers">${drivers.map((d) => `<li><b>+${esc(Math.round(Number(d.points)))}</b> ${esc(d.text)}</li>`).join("")}</ul>`;
}
// Triage queues: the usual first questions of a registry, one click each. Each one is a combination of docket filters.
const QUEUES = [
  ["custody", "Custody and bail first", "Accused in custody: production, bail and Sec. 479 checks", { custody: true }],
  ["s479", "Past the Sec. 479 mark", "Custody appears to have crossed one-third / one-half of the maximum sentence", { flag: "UNDERTRIAL_RELEASE_ELIGIBLE" }],
  ["critical", "Critical, not yet listed", "Must be listed within a day; no upcoming slot", { band: "Critical", not_listed: true }],
  ["late", "Listing deadline missed", "Not listed within the band's deadline", { past_deadline: true }],
  ["must", "Left out 3+ times", "Deferred from three published lists in a row - must-list next", { deferred3: true }],
  ["timebound", "Time-bound by statute", "e.g. Sec. 143 NI Act cheque cases, DV Act, maintenance", { flag: "TIME_BOUND_LAW" }],
  ["old", "Pending 10+ years", "Old cases flagged for priority disposal", { flag: "DECADE_OLD" }],
  ["review", "Details to verify", "A fact read from the papers is missing or uncertain", { needs_review: true }],
];
let activeQueue = "";
function renderQueues() {
  $("#triageQueues").innerHTML = `<span class="hint">Triage queues:</span> ${QUEUES.map(([key, label, why]) =>
    `<button type="button" class="queue-chip ${activeQueue === key ? "on" : ""}" data-queue="${key}" aria-pressed="${activeQueue === key}" title="${esc(why)}">${esc(label)}</button>`).join("")}
    ${activeQueue ? `<button type="button" class="btn ghost small" data-queue="">Show the whole docket</button>` : ""}`;
  $$("[data-queue]", $("#triageQueues")).forEach((b) => b.addEventListener("click", () => {
    activeQueue = activeQueue === b.dataset.queue ? "" : b.dataset.queue;
    const q = QUEUES.find((x) => x[0] === activeQueue);
    setDocketFilters(q ? q[3] : {});
    loadDocket();
  }));
}
renderQueues();

// Why a row needs a person: built server-side from stored facts only (flags, queue, dates, data quality).
function attentionList(items, max = 2) {
  if (!items || !items.length) return "";
  const shown = items.slice(0, max), more = items.length - shown.length;
  return `<ul class="attention">${shown.map((a) => `<li class="${esc(a.level)}">${esc(a.text)}</li>`).join("")}
    ${more ? `<li class="more" title="${esc(items.slice(max).map((a) => a.text).join("\n"))}">+${more} more</li>` : ""}</ul>`;
}
let lastDocket = null;
function csvCell(v) {
  const s = Array.isArray(v) ? v.join("; ") : String(v ?? "");
  return /[",\n;]/.test(s) || /^[=+\-@]/.test(s) ? `"${(/^[=+\-@]/.test(s) ? "'" : "") + s.replace(/"/g, '""')}"` : s;
}
$("#fExport").addEventListener("click", () => {
  if (!lastDocket || !lastDocket.rows.length) return toast("Nothing to export: load the docket first.", "error");
  const cols = [["case_id", "Case"], ["source", "Source"], ["band", "Band"], ["score", "Score"], ["case_type", "Type"], ["stage", "Stage"],
    ["flags", "Flags"], ["deferred", "Deferred in a row"], ["sla_due_on", "List by"], ["next_hearing_date", "Next hearing"],
    ["listed_on", "On upcoming list"], ["data_quality", "Data quality"]];
  const lines = [cols.map(([, h]) => h).concat("Why it needs attention").join(",")]
    .concat(lastDocket.rows.map((r) => cols.map(([k]) => csvCell(r[k])).concat(csvCell((r.attention || []).map((a) => a.text))).join(",")));
  const url = URL.createObjectURL(new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: `docket_${todayIso()}.csv` });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
  toast(`Exported ${lastDocket.rows.length} row(s)${lastDocket.total > lastDocket.rows.length ? ` of ${lastDocket.total}` : ""}.`);
});
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
function checkWeekStart() {
  const v = $("#clStart").value, warn = $("#clStartWarn");
  const msg = !v ? "Choose the Monday the week starts on."
    : new Date(v + "T00:00:00").getDay() !== 1 ? "This date is not a Monday. The draft will start on this day and run for five working days."
      : v < todayIso() ? "This week has already started or passed. Hearings cannot be planned on past days." : "";
  warn.textContent = msg; warn.classList.toggle("hidden", !msg);
  $("#clDraft").disabled = !v;
  const open = (savedLists || []).find((l) => l.status === "draft" && !l.fast_lane && l.start_date === v);
  if (open) {
    warn.innerHTML = `${esc(msg)} ${msg ? "<br>" : ""}Draft #${esc(open.id)} for this week is already open.
      <button class="btn ghost small" type="button" data-open-cl="${esc(open.id)}">Open it</button> - preparing again replaces it.`;
    warn.classList.remove("hidden");
    $("[data-open-cl]", warn).addEventListener("click", () => openCauseList(open.id));
  }
}
$("#clStart").addEventListener("change", () => { checkWeekStart(); loadClPreview(); });
let previewSeq = 0;
async function loadClPreview() {
  const v = $("#clStart").value, box = $("#clPreview");
  if (!v) { box.innerHTML = ""; return; }
  const seq = ++previewSeq;
  box.innerHTML = `<p class="hint" role="status">Checking bench time for the week of ${esc(v)}…</p>`;
  try {
    const pv = await api(`/api/scheduling/preview?start=${encodeURIComponent(v)}`);
    if (seq !== previewSeq) return;
    box.innerHTML = `<h4>Before you draft: will the week fit?</h4>${previewHtml(pv, false)}`;
  } catch (e) { if (seq === previewSeq) box.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}
let savedLists = null;
const CL_STATUS = { draft: "Draft - awaiting approval", published: "Published", rejected: "Rejected", superseded: "Replaced by a newer draft" };
async function loadSavedLists() {
  try {
    const { lists } = await api("/api/cause-lists?limit=12");
    savedLists = lists;
    const open = lists.filter((l) => l.status === "draft");
    $("#clOpenDrafts").textContent = `${open.length} open draft${open.length === 1 ? "" : "s"}`;
    $("#clOpenDrafts").classList.toggle("hidden", !open.length);
    if (open.length) $("#clSavedBox").open = true;
    $("#clSaved").innerHTML = lists.length ? `<div class="table-wrap"><table><thead><tr><th>#</th><th>Week of</th><th>Kind</th><th>Status</th><th class="num">Matters</th><th></th></tr></thead><tbody>
      ${lists.map((l) => `<tr${cl && cl.id === l.id ? ' class="current"' : ""}><td>${esc(l.id)}</td><td>${esc(l.start_date)}</td><td>${l.fast_lane ? "Fast-lane slots" : "Weekly list"}</td>
        <td>${esc(CL_STATUS[l.status] || l.status)}${l.approved_by ? ` <span class="hint">by ${esc(l.approved_by)}</span>` : ""}</td><td class="num">${esc(l.cases)}</td>
        <td>${["draft", "published"].includes(l.status) ? `<button class="btn ghost small" data-open-cl="${esc(l.id)}">Open</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`
      : `<p class="hint">No lists yet. Prepare the first draft above.</p>`;
    $$("[data-open-cl]", $("#clSaved")).forEach((b) => b.addEventListener("click", () => openCauseList(Number(b.dataset.openCl))));
    checkWeekStart();
  } catch (e) { $("#clSaved").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}
async function openCauseList(id) {
  try {
    $("#clView").innerHTML = `<p class="hint" role="status">Opening list #${esc(id)}…</p>`;
    await loadRules();
    const v = await api(`/api/cause-lists/${encodeURIComponent(id)}/view`);
    cl = { id: v.cause_list_id, plan: v, status: v.status };
    if (v.start_date) $("#clStart").value = v.start_date;
    renderCauseList();
    $("#clView").scrollIntoView({ behavior: "smooth" });
  } catch (e) { $("#clView").innerHTML = `<p class="error">Could not open list #${esc(id)}: ${esc(e.message)}</p>`; }
}
$("#clDraft").addEventListener("click", (e) => busy(e.target, async () => {
  await loadRules();
  const out = await api("/api/cause-lists/draft", { json: { start_date: $("#clStart").value, days: 5 } });
  cl = { id: out.cause_list_id, plan: out, status: "draft" };
  renderCauseList();
  loadSavedLists();
  $("#clView").scrollIntoView({ behavior: "smooth" });
}));

// Listing heads, in the order a daily cause list is usually read out: pronouncements first, then custody and bail,
// fresh matters, and the trial stages. The head comes from the case type and its recorded stage (purpose of listing).
const LIST_HEADS = [
  ["orders", "For judgment / orders", (c) => ["judgment_reserved", "pronouncement"].includes(c.stage)],
  ["custody", "Bail and custody matters", (c, custody) => ["bail", "habeas_corpus"].includes(c.case_type) || custody],
  ["fresh", "Fresh matters - admission and notice", (c) => ["admission", "notice"].includes(c.stage)],
  ["charge", "For charge / framing of issues", (c) => ["charge", "framing_of_issues"].includes(c.stage)],
  ["evidence", "For evidence", (c) => c.stage === "evidence"],
  ["arguments", "For arguments", (c) => c.stage === "arguments"],
  ["pleadings", "Pleadings and written statements", (c) => c.stage === "pleadings"],
  ["execution", "Execution", (c) => c.stage === "execution" || c.case_type === "execution"],
  ["other", "Other matters", () => true],
];
function listHead(c, readiness) {
  const custody = (readiness?.[c.case_id] || []).some((n) => /in custody/i.test(n));
  return LIST_HEADS.find(([, , test]) => test(c, custody));
}
// A court-style printable list: per day and bench, matters under their listing heads with running item numbers.
function printCauseList() {
  if (!cl) return;
  const p = cl.plan, draft = cl.status !== "published";
  const days = p.calendar.map((d) => {
    const benches = d.benches.filter((b) => b.open !== false && b.cases.length).map((b) => {
      let item = 0;
      const groups = LIST_HEADS.map(([key, title]) => [title, b.cases.filter((c) => listHead(c, p.readiness)[0] === key)])
        .filter(([, cs]) => cs.length);
      return `
      <h3>${esc(b.bench_id)}${b.name && b.name !== b.bench_id ? ` - ${esc(b.name)}` : ""}</h3>
      <table><thead><tr><th>Item</th><th>Time</th><th>Case number</th><th>Nature / purpose of listing</th><th>Remarks</th></tr></thead><tbody>
      ${groups.map(([title, cs]) => `<tr class="head"><td colspan="5">${esc(title)}</td></tr>` + cs.map((c) => `<tr><td>${++item}</td><td>${esc((c.slot || "").split("-")[0])}</td><td>${esc(c.case_id)}</td>
        <td>${esc(String(c.case_type || "").replace(/_/g, " "))}${c.stage ? ` / ${esc(String(c.stage).replace(/_/g, " "))}` : ""}</td>
        <td>${c.must_list ? "Must-list" : ""}${(p.readiness || {})[c.case_id]?.some((n) => /in custody/i.test(n)) ? `${c.must_list ? "; " : ""}Accused in custody - production` : ""}</td></tr>`).join("")).join("")}
      </tbody></table>`;
    }).join("");
    return benches ? `<section><h2>${esc(weekday(d.date))}, ${esc(d.date)}</h2>${benches}</section>` : "";
  }).join("");
  const w = window.open("", "_blank");
  if (!w) return toast("The browser blocked the print window. Allow pop-ups for this site and try again.", "error");
  w.document.write(`<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Cause list #${esc(cl.id)}</title>
    <style>body{font:13px/1.45 Georgia,"Times New Roman",serif;color:#111;margin:24px}h1{font-size:18px;margin:0}h2{font-size:15px;margin:22px 0 6px;border-bottom:1px solid #444}
    h3{font-size:13px;margin:12px 0 4px}table{width:100%;border-collapse:collapse;margin-bottom:8px}th,td{border:1px solid #999;padding:4px 6px;text-align:left;vertical-align:top}
    th{background:#eee}tr.head td{background:#f6f6f6;font-weight:bold;font-style:italic}.mark{border:2px solid #a00;color:#a00;padding:4px 8px;display:inline-block;margin:8px 0;font-weight:bold}.foot{margin-top:24px;font-size:11px;color:#555}
    @media print{.noprint{display:none}}</style></head><body>
    <h1>Cause list for the week of ${esc(p.start_date || p.calendar[0]?.date || "")}</h1>
    <p>List #${esc(cl.id)} · ${draft ? "" : `published${p.approved_by ? ` · approved by ${esc(p.approved_by)}` : ""}`}</p>
    ${draft ? `<p class="mark">DRAFT - not approved, not for circulation</p>` : ""}
    ${days || "<p>No matters listed.</p>"}
    <p class="foot">Prepared with NyayaVedika from the court's own records. Timings are planning estimates; the order of calling is at the discretion of the Presiding Officer.</p>
    <p class="noprint"><button onclick="window.print()">Print</button></p></body></html>`);
  w.document.close();
}

// What the scheduler did, in one paragraph a Registrar can read before approving.
function inShort(p, m) {
  const reasons = {};
  (p.unscheduled || []).forEach((u) => { reasons[u.reason] = (reasons[u.reason] || 0) + 1; });
  const why = { capacity: "no bench time left", advocate_conflict: "advocate busy in another court", no_bench: "no bench takes the case type" };
  const carried = Object.entries(reasons).map(([k, n]) => `${n} - ${why[k] || k}`).join("; ");
  const b = m.baseline_fifo || {};
  const parts = [`<b>${esc(m.cases_listed ?? 0)}</b> matter(s) listed`];
  if (m.must_list_total != null) parts.push(`<b>${esc(m.must_list_listed ?? 0)} of ${esc(m.must_list_total)}</b> must-list matters placed first in the reserved time`);
  if (m.avg_bench_utilisation_percent != null) parts.push(`about <b>${esc(m.avg_bench_utilisation_percent)}%</b> of bench time planned`);
  if (m.advocate_conflicts != null) parts.push(`${m.advocate_conflicts ? `<b>${esc(m.advocate_conflicts)}</b> advocate clash(es)` : "no advocate clashes"}`);
  const vs = b.critical_avg_wait_days != null && m.critical_avg_wait_days != null && m.critical_avg_wait_days !== b.critical_avg_wait_days
    ? ` Compared with listing oldest-first, Critical matters wait <b>${esc(m.critical_avg_wait_days)}</b> day(s) on average instead of ${esc(b.critical_avg_wait_days)}.` : "";
  return `<p class="in-short"><b>In short:</b> ${parts.join(" · ")}.
    ${(p.unscheduled || []).length ? `${esc(p.unscheduled.length)} carried to a later week (${esc(carried)}); each climbs next time.` : "Nothing is carried over."}${vs}</p>`;
}

function rejectDialog() {
  $("#dialogBody").innerHTML = `<h3>Reject draft #${esc(cl.id)}</h3>
    <p class="hint">Rejecting drops this draft's slots. No hearing is created and no case is marked deferred. You can prepare a new draft afterwards.</p>
    <label for="rjNote">Reason (recorded in the audit log)</label><input id="rjNote" maxlength="300" placeholder="e.g. Bench CR-2 on leave on Wednesday">
    <p id="rjErr" class="banner-bad hidden" role="alert"></p>
    <div class="row gap"><button class="btn" id="rjGo">Reject draft</button></div>`;
  $("#dialog").showModal();
  $("#rjGo").addEventListener("click", (e) => busy(e.target, async () => {
    const note = $("#rjNote").value.trim();
    if (!note) { $("#rjErr").textContent = "Give a short reason."; $("#rjErr").classList.remove("hidden"); return; }
    await api(`/api/cause-lists/${cl.id}/reject`, { json: { note } });
    $("#dialog").close();
    cl.status = "rejected"; renderCauseList(); loadSavedLists();
    toast(`Draft #${cl.id} rejected.`);
  }));
}

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
      // `grounded` is what the server's verify() returns; the old check read a key that never existed
      const grounded = verification.grounded ?? verification.overall_grounded;
      const ai = result.mode === "llm";
      $("#staffSummaryOut").innerHTML = `<div class="card">
        <h3>${esc(result.filename)} · ${esc(result.pages)} page(s) <span class="badge ${ai ? "src-ai" : "src-rules"}">${esc(result.label || result.mode)}</span></h3>
        <div class="evidence-key" aria-label="How to read this summary">
          <span><i class="key-dot written"></i><b>Written summary</b> - ${ai ? "composed by the language model" : "composed from the document's own sentences by rules"}; an aid to reading, not a record.</span>
          <span><i class="key-dot extracted"></i><b>From the document</b> - dates, sections and details found in the text, with page numbers where known.</span>
        </div>
        <section class="summary-view-lead summary-written">
          <h4>What this paper says <span class="hint">· written summary</span></h4>
          <p>${esc(result.plain || analysis.plain_language_summary || "No plain-language summary was produced.")}</p>
        </section>
        <div class="summary-extracted">${renderDocumentSummaryDetails(result, (key) => summaryLabels[key] || key)}</div>
        <p class="hint">Document type: ${esc(result.doc_type || "unknown")} · ${grounded
          ? `✓ Every date and section shown (${esc(verification.checked ?? 0)} checked) was found in the document text`
          : "Some details could not be matched to the text - check them against the original"}</p>
        ${verification.unverified?.length ? `<p class="banner-warn">Removed because they do not appear in the document: ${verification.unverified.map(esc).join("; ")}</p>` : ""}
        ${result.low_confidence_pages?.length ? `<p class="banner-warn">Low OCR confidence on page(s): ${esc(result.low_confidence_pages.join(", "))} - read those pages in the original.</p>` : ""}
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
  clStep(cl.status === "draft" ? 2 : cl.status === "published" ? 4 : 1);
  const conflictIds = new Set((p.violations || []).flatMap((v) => (v.match(/\(([^ ]+) on/g) || []).map((x) => x.slice(1, -3))));
  const listed = p.calendar.flatMap((d) => d.benches.flatMap((x) => x.cases));
  const allCaseExamples = capRealFirst([...listed, ...p.unscheduled]);
  const visibleCaseIds = new Set(allCaseExamples.rows.map((c) => c.case_id));
  const uploaded = listed.filter((c) => c.source && c.source !== "synthetic").length;
  const unscheduledDisplay = realFirst(p.unscheduled).filter((c) => c.source !== "synthetic" || visibleCaseIds.has(c.case_id));
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
  const ready = Object.entries(p.readiness || {});
  const readyShown = capRealFirst(ready.map(([id, notes]) => ({ case_id: id, notes, source: (listed.find((c) => c.case_id === id) || {}).source })));
  const readinessBox = ready.length ? `<details class="compare-box readiness"><summary>Readiness - ${esc(ready.length)} listed matter(s) need something arranged or checked</summary>
      <p class="hint">From the case records only. Fix details on the case (Open → Correct field) before the list is published, or arrange production for custody matters.</p>
      <ul>${readyShown.rows.map((r) => `<li><button class="linkish" data-open="${esc(r.case_id)}">${esc(r.case_id)}</button> ${r.source && r.source !== "synthetic" ? srcBadge(r.source) : ""} - ${r.notes.map(esc).join("; ")}</li>`).join("")}</ul>
      ${syntheticLimitNote(readyShown.omitted)}</details>` : "";
  const kind = cl.status === "draft" ? "draft" : cl.status === "published" ? "published list" : `${cl.status} draft`;
  $("#clView").innerHTML = `<div class="card">
    <div class="row between wrap"><h3>2. Check the ${cl.status === "draft" ? "draft" : "list"} <span class="hint">· ${esc(kind)} #${esc(cl.id)}${p.start_date ? ` · week of ${esc(p.start_date)}` : ""}</span></h3>
      <button class="btn ghost small" type="button" id="clPrint">Print view</button></div>
    ${cl.status === "rejected" ? `<p class="banner-warn">This draft was rejected. Its slots were dropped; prepare a new draft for the week.</p>` : ""}
    ${inShort(p, m)}
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
    ${readinessBox}
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
              <ul class="slots">${realFirst(x.cases).filter((c) => c.source !== "synthetic" || visibleCaseIds.has(c.case_id)).slice(0, 60).map((c) => clCase(c, conflictIds)).join("") || "<li class='hint'>No displayed examples</li>"}</ul>
              ${x.cases.filter((c) => c.source !== "synthetic" || visibleCaseIds.has(c.case_id)).length > 60 ? `<span class="hint">More cases are included in the draft.</span>` : ""}</div>`).join("")}</div></details>`;
    }).join("")}
    ${p.unscheduled.length ? `<details class="day"><summary><b>Carried to a later week</b> · ${p.unscheduled.length} case(s)</summary>
        <p class="hint">Each of these is deferred +1 when the list is published, so it climbs in next week's draft.</p>
      <ul>${unscheduledDisplay.map((u) => `<li>${band(u.band)} ${esc(u.case_id)} ${u.source && u.source !== "synthetic" ? srcBadge(u.source) : ""} - ${esc(REASON[u.reason] || u.reason)}${u.must_list ? ' <span class="must">must-list</span>' : ""}</li>`).join("")}</ul></details>` : ""}
    ${elsewhere.length ? `<details class="day"><summary><b>Already listed elsewhere this week</b> · ${elsewhere.length} case(s)</summary>
        <p class="hint">These cases already hold a slot on another list for these dates (an accepted fast-lane slot, a published list or another draft), so this draft does not list them again.</p>
      <ul>${capRealFirst(elsewhere).rows.map((u) => `<li>${band(u.band)} ${esc(u.case_id)} ${u.source && u.source !== "synthetic" ? srcBadge(u.source) : ""} - ${esc(u.day)} ${esc((u.slot || "").split("-")[0])} on ${esc(u.bench_id)} <span class="hint">(${esc(u.listing_status)}, list #${esc(u.cause_list_id)})</span></li>`).join("")}</ul></details>` : ""}
  </div>
  <div class="card">
    <h3>3. Approve and publish</h3>
    ${cl.status === "draft"
      ? `<p>Publishing will: create ${esc(m.cases_listed)} hearing(s) · set each listed case's next date · reset their deferral count ·
           defer the ${esc(p.unscheduled.length)} carried-over case(s) by one. Until then this is only a draft.</p>
         ${problems.length ? `<p class="banner-warn">There are ${problems.length} problem(s) above - publish only if you accept them.</p>` : ""}
         ${ready.length ? `<p class="hint">${esc(ready.length)} listed matter(s) have readiness notes above. They do not block publishing.</p>` : ""}
         <label class="confirm-line"><input type="checkbox" id="clConfirm"> I have checked this draft and am authorised to publish it.</label>
         <div class="row gap wrap"><button class="btn" id="clPublish" disabled>Approve and publish</button>
           <button class="btn ghost" id="clReject">Reject draft…</button></div>`
      : cl.status === "published"
        ? `<div class="banner-ok">✓ Published. Hearings are created; next dates are set; carried-over cases were deferred +1. They appear on the <a href="#" id="clToDocket">Docket</a>
            and in the <a href="#" id="clToDiary">Court diary</a> on the day.</div>`
        : `<p class="hint">Nothing to approve: this draft is ${esc(cl.status)}.</p>`}
  </div>`;
  $("#clConfirm")?.addEventListener("change", (e) => { $("#clPublish").disabled = !e.target.checked; });
  $("#clPublish")?.addEventListener("click", (e) => busy(e.target, async () => {
    const out = await api(`/api/cause-lists/${cl.id}/publish`, { method: "POST" });
    cl.status = "published"; renderCauseList(); loadSavedLists(); toast(`Published: ${out.hearings_created} hearing(s) created.`);
  }));
  $("#clReject")?.addEventListener("click", rejectDialog);
  $("#clPrint")?.addEventListener("click", printCauseList);
  wireCaseButtons($(".readiness", $("#clView")) || document.createElement("div"));
  $("#clToDocket")?.addEventListener("click", (e) => { e.preventDefault(); setDocketFilters({}); showTab("docket"); });
  $("#clToDiary")?.addEventListener("click", (e) => {
    e.preventDefault(); showTab("today");
    const first = p.calendar[0]?.date;
    if (first) loadDiary(first);
    $("#diaryCard").scrollIntoView({ behavior: "smooth" });
  });
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

// ---------------------------------------------------------------- UNDERTRIAL (Sec. 479 BNSS, as it runs in court)
// found -> COUNSEL decides to file -> REGISTRY records filing -> hearing -> the COURT's order -> release from custody.
// Counsel's decision is taken in the Advocate portal; court staff record what the court did. The server enforces this.
const UT_NEXT = {   // the registry's next entries, by current status
  approved: [["filed", "Record: application filed / registered"]],
  filed: [["heard", "Record: heard"], ["release_ordered", "Record court order: release"], ["denied", "Record court order: continued detention"]],
  heard: [["release_ordered", "Record court order: release"], ["denied", "Record court order: continued detention"]],
  release_ordered: [["released", "Record: released from custody"]],
};
const UT_TRACK = ["Found", "Counsel decides", "Filed", "Heard", "Court's order", "Released"];
const UT_STEP = { pending: 1, approved: 2, filed: 3, heard: 4, release_ordered: 5, denied: 5, released: 6, dismissed: 2 };
const UT_STATUS = { pending: "awaiting counsel's decision", approved: "counsel will file", filed: "application filed",
  heard: "heard by the court", release_ordered: "court ordered release", denied: "court ordered continued detention",
  released: "released from custody", dismissed: "counsel decided not to file" };
function utHistory(a) {
  const steps = (a.details || {}).steps || [];
  return steps.length ? `<details class="ut-history"><summary>Record of steps (${steps.length})</summary><ol>${steps.map((s) =>
    `<li><b>${esc(UT_STATUS[s.status] || s.status)}</b> <span class="hint">${esc(String(s.at || "").slice(0, 10))} · ${esc(s.role === "lawyer" ? "counsel" : s.role === "staff" ? "court staff" : s.role)}</span>${s.note ? ` - ${esc(s.note)}` : ""}</li>`).join("")}</ol></details>` : "";
}
// Counsel on record: entered by the registry from the DLSA assignment letter or a vakalatnama.
function utCounsel(a, lawyer) {
  const c = (a.details || {}).counsel;
  const line = c ? `<p class="ut-counsel"><b>Counsel on record:</b> ${esc(c.name)} <span class="hint">· ${esc(c.basis_label)}${c.reference ? `, ref. ${esc(c.reference)}` : ""}</span></p>`
    : `<p class="ut-counsel none"><b>No counsel on record yet.</b> <span class="hint">Record the panel lawyer from the DLSA assignment letter, or the advocate from the vakalatnama.</span></p>`;
  if (lawyer || ["released", "denied", "dismissed"].includes(a.status)) return line;
  return `${line}<details class="ut-assign"><summary>${c ? "Change counsel on record" : "Record counsel on record"}</summary>
    <div class="row gap wrap">
      <label>Counsel's name <input data-cn-name="${a.id}" maxlength="120" value="${esc(c?.name || "")}"></label>
      <label>From <select data-cn-basis="${a.id}"><option value="dlsa_assignment" ${c?.basis !== "vakalatnama" ? "selected" : ""}>DLSA assignment letter (legal aid)</option>
        <option value="vakalatnama" ${c?.basis === "vakalatnama" ? "selected" : ""}>Vakalatnama filed</option></select></label>
      <label>Reference no. <span class="hint">(optional)</span> <input data-cn-ref="${a.id}" maxlength="120" value="${esc(c?.reference || "")}" placeholder="e.g. DLSA/HYD/LA/412/2026"></label>
      <button class="btn small" data-cn-save="${a.id}">Save</button></div></details>`;
}
// Each registry entry asks for what a court record would carry.
function utStepDialog(id, caseId, to) {
  const today = todayIso();
  const body = {
    filed: `<label for="usNote">Petition / registration number <span class="hint">(optional)</span></label><input id="usNote" maxlength="120" placeholder="e.g. Crl.M.P. 412/2026">`,
    heard: `<label for="usNote">Note <span class="hint">(optional)</span></label><input id="usNote" maxlength="200" placeholder="e.g. PP heard; order reserved">`,
    release_ordered: `<fieldset class="q"><legend>The court ordered release</legend>
        <label><input type="radio" name="usKind" value="On bail (one-half of the maximum undergone)" checked> On bail - one-half undergone</label>
        <label><input type="radio" name="usKind" value="On bond as a first-time offender (one-third undergone)"> On bond - first-time offender, one-third undergone</label></fieldset>
      <label for="usDate">Date of the order</label><input id="usDate" type="date" max="${today}" value="${today}">
      <label for="usNote">Conditions or bond amount <span class="hint">(optional)</span></label><input id="usNote" maxlength="200">`,
    denied: `<p class="hint">Under Sec. 479(1) the court may order continued detention after hearing the Public Prosecutor, for reasons recorded in writing.</p>
      <label for="usDate">Date of the order</label><input id="usDate" type="date" max="${today}" value="${today}">
      <label for="usNote">Reasons as recorded <span class="hint">(short)</span></label><input id="usNote" maxlength="200">`,
    released: `<label for="usDate">Date released from custody</label><input id="usDate" type="date" max="${today}" value="${today}">
      <label for="usNote">Note <span class="hint">(optional)</span></label><input id="usNote" maxlength="200" placeholder="e.g. personal bond accepted; release order sent to jail">`,
  }[to];
  $("#dialogBody").innerHTML = `<h3>${esc(caseId)} · ${esc(UT_STATUS[to])}</h3>
    <p class="hint">You are recording what the court did; this does not decide anything. It is written to the audit log.</p>
    ${body}<p id="usErr" class="banner-bad hidden" role="alert"></p><div class="row gap"><button class="btn" id="usSave">Save</button></div>`;
  $("#dialog").showModal();
  $("#usSave").addEventListener("click", (e) => busy(e.target, async () => {
    const kind = $("input[name=usKind]:checked")?.value, date = $("#usDate")?.value, extra = $("#usNote")?.value.trim();
    if (["release_ordered", "denied", "released"].includes(to) && !date) {
      $("#usErr").textContent = "Enter the date."; $("#usErr").classList.remove("hidden"); return;
    }
    const note = [kind, date && `${to === "released" ? "released on" : "order dated"} ${date}`, extra].filter(Boolean).join("; ");
    await api(`/api/alerts/${id}/state`, { json: { status: to, note } });
    $("#dialog").close(); toast(`${caseId}: ${UT_STATUS[to]} recorded.`); loadAlerts();
  }));
}
// What the deterministic check found, in words a reviewer can act on (triage.undertrial_release_check statuses).
const UT_FINDING = {
  eligible: "Custody has crossed the mark on the recorded facts - verify dates and exclusions before filing",
  likely_eligible: "One-third mark crossed; applies only if this is a first offence - confirm there is no earlier conviction",
  needs_review: "Mark crossed, but a bar may apply (more than one offence or case pending, Sec. 479(2)) - lawyer to examine",
  not_eligible: "Mark not yet crossed",
};
function alertCard(a) {
  const over = a.days_over_limit > 0;
  const lawyer = ROLE === "lawyer";
  const releaseReview = ["undertrial_release", "release_review_request"].includes(a.kind);
  const next = UT_NEXT[a.status];
  const primary = a.status === "pending"
    ? (lawyer ? `<button class="btn" data-approve="${a.id}">Decide to file the application</button>`
              : `<span class="hint">Waiting for counsel (the legal-aid lawyer) to decide whether to file - done in the Advocate portal.</span>`)
    : next && !lawyer ? next.map(([to, label], i) => `<button class="btn ${i ? "ghost" : ""}" data-advance="${a.id}" data-to="${to}" data-case="${esc(a.case_id)}">${label}</button>`).join(" ")
      : next ? `<span class="hint">The court registry records the next step.</span>` : "";
  const step = UT_STEP[a.status] || 1;
  const track = UT_TRACK.map((s, i) => i === 4 && a.status === "denied" ? "Detention continued" : s)
    .map((s, i) => `<li class="${i + 1 < step ? "done" : i + 1 === step ? "now" : ""}">${s}</li>`).join("");
  return `<div class="card ut">
    <div class="row between wrap">
      <div><b>${esc(a.case_id)}</b> ${srcBadge(a.source)}
        <span class="badge ${a.days_over_limit >= 0 ? "band-critical" : "band-high"}">${over ? "‼ " + esc(a.days_over_limit) + " days past the mark" : a.days_over_limit === 0 ? "‼ reaches the mark today" : "▲ near the mark"}</span>
        ${a.status !== "pending" ? `<span class="pill">now: ${esc(UT_STATUS[a.status] || a.status)}</span>` : ""}</div>
      <span class="hint">${esc(a.custody_days ?? "?")} days in custody · Sec. 479 mark ${esc(a.threshold_days ?? "?")} days${a.basis ? ` (${esc(a.basis)})` : ""}</span></div>
    <ol class="flow small">${track}</ol>
    ${a.release_status && UT_FINDING[a.release_status] ? `<p class="ut-finding ${esc(a.release_status)}"><b>Finding:</b> ${esc(UT_FINDING[a.release_status])}</p>` : ""}
    ${custodyMath(a)}
    ${(a.release_notes || []).length ? `<p class="banner-warn">${a.release_notes.map(esc).join("<br>")}</p>` : ""}
    <div class="actions">${primary}
      <button class="btn ghost" data-docx="${a.id}">Download application (Word)</button>
      ${releaseReview && ROLE === "staff" ? `<button class="btn ghost" data-superintendent="${a.id}" data-language="en">Custody-record review request (English)</button>
      <button class="btn ghost" data-superintendent="${a.id}" data-language="hi">निरुद्धि-अवधि जाँच निवेदन (हिन्दी)</button>
      <button class="btn ghost" data-superintendent="${a.id}" data-language="te">నిర్బంధ కాల వివరాల పరిశీలన వినతి (తెలుగు)</button>` : ""}</div>
    <details><summary>Read the draft application ${engineBadge(a.draft_engine === "ai" ? "AI" : "rules")} and the checklist</summary>
      <div class="alertcard"><pre class="doc">${esc(a.draft || "")}</pre>
        <div><h3>Counsel verifies before filing</h3><div class="checklist">${((a.details || {}).checklist || []).map((c) => `<label><input type="checkbox"> ${esc(c)}</label>`).join("")}</div></div></div></details>
    ${utCounsel(a, lawyer)}
    ${utHistory(a)}
    ${lawyer && ["pending", "approved"].includes(a.status) ? `<details><summary>Not filing? Record the reason</summary>
      <label>Reason (required) <input data-reason="${a.id}"></label>
      <label>Check again after <input type="date" data-snooze="${a.id}"></label>
      <button class="btn ghost small" data-dismiss="${a.id}">Not filing</button></details>` : ""}
  </div>`;
}
async function loadAlerts() {
  loadRules();
  $("#utRole").textContent = ROLE === "lawyer"
    ? "You are signed in as counsel: you decide whether to file. The court decides release; the registry records it."
    : "As court staff you run the check, send the custody-record review request, fill in missing custody details, and record "
      + "what happens in court: filing, hearing, the court's order and release. Counsel decides whether to file; only the court orders release.";
  try {
    // both lists load at once; a failure of the missing-information list does not hide the alerts
    const needP = api("/api/alerts/data-needed").catch((e) => ({ error: e.message, data_needed: [] }));
    const { alerts } = await api("/api/alerts?status=all");
    const decide = alerts.filter((a) => a.status === "pending");
    const progress = alerts.filter((a) => UT_NEXT[a.status]);
    $("#utNeedH").textContent = `Awaiting counsel's decision (${decide.length})`;
    $("#utProgH").textContent = `In progress (${progress.length})`;
    const closed = alerts.filter((a) => ["released", "denied", "dismissed"].includes(a.status));   // release_ordered stays open: still in custody
    $("#utFlow").innerHTML = [["Found", "pending"], ["Counsel will file", "approved"], ["Filed in court", "filed"], ["Heard", "heard"],
      ["Release ordered", "release_ordered"]]
      .map(([l, s]) => `<li title="${alerts.filter((a) => a.status === s).length} alert(s) at this step">${l} <b>${alerts.filter((a) => a.status === s).length}</b></li>`).join("")
      + `<li title="released, denied or dismissed">Closed <b>${closed.length}</b></li>`;
    const alertDisplay = capRealFirst(alerts);
    const visibleDecide = alertDisplay.rows.filter((a) => a.status === "pending");
    const visibleProgress = alertDisplay.rows.filter((a) => UT_NEXT[a.status]);
    $("#utDecide").innerHTML = visibleDecide.map(alertCard).join("") + syntheticLimitNote(alertDisplay.omitted)
      || "<p class='hint'>Nothing is waiting for a decision. ✓</p>";
    $("#utProgress").innerHTML = visibleProgress.map(alertCard).join("")
      || "<p class='hint'>Nothing in progress.</p>";
    const root = $("#tab-undertrial");
    $$("[data-approve]", root).forEach((b) => b.addEventListener("click", () => busy(b, async () => {
      await api("/api/alerts/decide", { json: { decisions: { [b.dataset.approve]: { approve: true } } } }); toast("Recorded: counsel will file the application."); loadAlerts();
    })));
    $$("[data-dismiss]", root).forEach((b) => b.addEventListener("click", () => busy(b, async () => {
      const id = b.dataset.dismiss, reason = $(`[data-reason="${id}"]`).value.trim(), snooze = $(`[data-snooze="${id}"]`).value;
      if (!reason) throw new Error("A dismissal needs a reason.");
      await api("/api/alerts/decide", { json: { decisions: { [id]: { approve: false, reason, snooze_until: snooze || null } } } });
      toast("Recorded: not filing. It returns only after the check-again date or if the custody facts change."); loadAlerts();
    })));
    $$("[data-advance]", root).forEach((b) => b.addEventListener("click", () => utStepDialog(b.dataset.advance, b.dataset.case, b.dataset.to)));
    $$("[data-cn-save]", root).forEach((b) => b.addEventListener("click", () => busy(b, async () => {
      const id = b.dataset.cnSave;
      await api(`/api/alerts/${id}/counsel`, { json: { name: $(`[data-cn-name="${id}"]`).value.trim(),
        basis: $(`[data-cn-basis="${id}"]`).value, reference: $(`[data-cn-ref="${id}"]`).value.trim() } });
      toast("Counsel on record saved."); loadAlerts();
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
    const neededDisplay = capRealFirst(need.data_needed);
    $("#utNeeded").innerHTML = neededDisplay.rows.map((d) => `<li><b>${esc(d.case_id)}</b> ${d.source === "synthetic" ? srcBadge(d.source) : ""}: missing ${d.missing.map(pretty).join(", ")} - ask ${esc(d.who_can_supply.join("; "))}
      ${ROLE === "staff" ? d.missing.map((f) => `<button class="btn ghost small" data-fix="${esc(d.case_id)}" data-field="${esc(f)}">Fill in ${pretty(f)}</button>`).join(" ") : ""}</li>`).join("") || "<li>None.</li>";
    wireCaseButtons($("#utNeeded"));
    if (neededDisplay.omitted) $("#utNeeded").insertAdjacentHTML("beforeend", `<li>${syntheticLimitNote(neededDisplay.omitted)}</li>`);
  } catch (e) { $("#utDecide").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}
$("#utScan").addEventListener("click", (e) => busy(e.target, async () => {
  const out = await api("/api/jobs/undertrial_scan/run", { method: "POST" });
  toast(`Checked: ${out.new_release_alerts} new, ${out.data_needed} need information.`); loadAlerts();
}));

renderFiles();
