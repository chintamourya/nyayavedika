// NyayaVedika dashboard - vanilla JS. All server text is escaped before insertion.
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pretty = (s) => esc(String(s ?? "").replace(/_/g, " "));

// Demo access token: the server decides the role (staff / lawyer / citizen) from it.
const tokenKey = "nyayavedika_demo_token";
const getToken = () => { try { return localStorage.getItem(tokenKey) || ""; } catch { return ""; } };
$("#demoToken").value = getToken();
$("#demoToken").addEventListener("change", (e) => {
  try { localStorage.setItem(tokenKey, e.target.value.trim()); } catch { /* private window: token lasts this page only */ }
  thread = null; awaitingAnswer = false;
});

async function api(path, body) {
  const token = $("#demoToken").value.trim() || getToken();
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const res = await fetch(path, body === undefined ? { headers }
    : { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) throw new Error("Enter your demo access token at the top of the page.");
  if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
  return data;
}
async function busy(btn, fn) {
  btn.disabled = true;
  try { await fn(); } catch (e) { alert(e.message); } finally { btn.disabled = false; }
}
const kpi = (value, label, note) => `<div class="kpi"><b>${esc(value)}</b><span>${esc(label)}</span>${note ? `<small>${esc(note)}</small>` : ""}</div>`;

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + t.dataset.tab));
  if (t.dataset.tab === "watch") loadAlerts();
  if (t.dataset.tab === "impact") loadImpact();
}));

// ---------- health ----------
api("/api/health").then((h) => {
  const parts = [h.llm_enabled ? `Azure OpenAI ${h.model}` : "LLM offline", h.vector.vector_db ? "Pinecone" : "no vector DB",
    h.web_search ? "Tavily" : "no web search", h.ocr.pytesseract ? "Tesseract OCR" : "no OCR"];
  $("#engine").textContent = parts.join(" · ");
}).catch(() => ($("#engine").textContent = "server unreachable"));

// ---------- feedback ----------
document.querySelectorAll("[data-rate]").forEach((b) => b.addEventListener("click", async () => {
  await api("/api/feedback", { feature: b.dataset.feature, rating: +b.dataset.rate });
  b.parentElement.innerHTML = "<span class='hint'>Thank you for the feedback.</span>";
}));

// ---------- Nyaya Mitra chat ----------
let thread = null, awaitingAnswer = false;
function addMsg(cls, html) {
  $("#chatLog").insertAdjacentHTML("beforeend", `<div class="msg ${cls}">${html}</div>`);
  $("#chatLog").scrollTop = $("#chatLog").scrollHeight;
}
function renderSteps(steps) {
  const visible = (steps || []).filter((s) => s.action && s.action !== "ask_user" && s.observation);
  if (!visible.length) return "";
  return `<details class="trace"><summary>Tools used: ${visible.length}</summary><ol>${visible.map((s) =>
    `<li><b>${pretty(s.action)}</b> <code>${esc(JSON.stringify(s.input ?? {}))}</code><div class="obs">${esc(String(s.observation).slice(0, 600))}</div></li>`).join("")}</ol></details>`;
}
$("#newChat").addEventListener("click", () => {
  thread = null; awaitingAnswer = false;
  $("#chatLog").innerHTML = '<div class="msg bot">New conversation started. How can I help?</div>';
});
$("#chatForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("#chatInput").value.trim();
  if (!text) return;
  $("#chatInput").value = "";
  addMsg("user", esc(text));
  addMsg("bot pending", "Thinking…");
  try {
    const r = awaitingAnswer
      ? await api("/api/agent/resume", { thread_id: thread, answer: text, language: $("#chatLang").value })
      : await api("/api/agent/chat", { message: text, thread_id: thread, language: $("#chatLang").value });
    thread = r.thread_id;
    document.querySelector(".msg.pending")?.remove();
    awaitingAnswer = !!r.question;
    addMsg("bot", esc(r.question || r.reply || "(no reply)").replace(/\n/g, "<br>") + renderSteps(r.steps));
  } catch (err) {
    document.querySelector(".msg.pending")?.remove();
    addMsg("bot error", esc(err.message));
  }
});

// ---------- Document Analyst ----------
let upload = null;
$("#loadSample").addEventListener("click", async () => {
  upload = null;
  $("#docText").value = (await api("/api/sample-judgment")).text;
  $("#docInfo").textContent = "Fictional sample judgment loaded.";
});
$("#docFile").addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    upload = { filename: file.name, content_base64: reader.result.split(",")[1] };
    $("#docInfo").textContent = `Ready: ${file.name} (${Math.round(file.size / 1024)} KB)`;
    $("#docText").value = "";
  };
  reader.readAsDataURL(file);
});
$("#runDoc").addEventListener("click", (e) => busy(e.target, async () => {
  const body = upload ? { ...upload } : { text: $("#docText").value, filename: "pasted.txt" };
  body.language = $("#docLang").value;
  body.case_id = $("#docCase").value || null;
  $("#docOut").innerHTML = "<p class='hint'>Agent working: OCR, indexing, reading, verifying…</p>";
  const r = await api("/api/documents/analyze", body);
  const s = r.analysis, d = s.case_details || {}, v = s.verification || {};
  const list = (arr) => (arr && arr.length ? `<ul>${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "<p class='hint'>None found</p>");
  $("#docOut").innerHTML = `
    <div class="card"><b>Agent trace</b> <span class="pill">${esc(s.engine)}</span> <span class="pill ${v.overall_grounded ? "okpill" : "warnpill"}">${v.overall_grounded ? "✔ verified against source" : "⚠ partially verified"}</span>
      <ol class="reasons">${r.trace.map((t) => `<li>${esc(t)}</li>`).join("")}</ol>
      <span class="hint">${r.pages} page(s), ${r.ocr_pages} OCR'd</span></div>
    ${s.case_priority ? `<div class="card"><b>Case re-prioritised:</b> <span class="band ${esc(s.case_priority.band)}">${esc(s.case_priority.band)} (${esc(s.case_priority.score)})</span> · ${esc(s.case_priority.recommended_route)}</div>` : ""}
    <div class="card"><h3>Plain-language summary</h3><p>${esc(s.plain_language_summary)}</p></div>
    <div class="grid2">
      <div class="card"><h3>Case details</h3><table>
        <tr><th>Case no.</th><td>${esc(d.case_number || "-")}</td></tr><tr><th>Court</th><td>${esc(d.court_name || "-")}</td></tr>
        <tr><th>Petitioner(s)</th><td>${esc((d.petitioners || []).join(", ") || "-")}</td></tr><tr><th>Respondent(s)</th><td>${esc((d.respondents || []).join(", ") || "-")}</td></tr>
        <tr><th>Date of order</th><td>${esc(d.date_of_order || "-")}</td></tr><tr><th>Outcome</th><td><b>${esc(s.outcome || "-")}</b></td></tr></table></div>
      <div class="card"><h3>Directions & deadlines</h3>${list(s.directions_and_deadlines)}</div>
    </div>
    <div class="card"><h3>Issues</h3>${(s.issues || []).map((i) => `<p><b>${esc(i.issue)}</b> <span class="hint">${esc(i.para_reference || "")}</span><br>${i.decision ? `Decision: ${esc(i.decision)}` : ""}</p>${(i.key_points || []).length ? list(i.key_points) : ""}`).join("") || "<p class='hint'>None found</p>"}</div>
    <div class="card"><h3>Timeline</h3><table><tr><th>Date</th><th>Event</th><th>Ref</th></tr>${(s.timeline || []).map((t) => `<tr><td>${esc(t.date)}</td><td>${esc(t.event)}</td><td>${esc(t.para_reference)}</td></tr>`).join("")}</table></div>
    <div class="grid2"><div class="card"><h3>Statutes cited</h3>${list(s.statutes_cited)}</div><div class="card"><h3>Precedents cited</h3>${list(s.precedents_cited)}</div></div>
    ${(v.corrections || []).length ? `<div class="card"><h3>Verifier findings</h3>${list(v.corrections)}</div>` : ""}`;
}));

// ---------- Undertrial Watch ----------
async function loadAlerts() {
  const { alerts } = await api("/api/alerts?status=pending");
  $("#alerts").innerHTML = alerts.length ? alerts.map((a) => {
    const rc = (a.details || {}).release_check || {};
    return `<div class="card alert" data-id="${a.id}">
      <div class="row between wrap"><b>${esc(a.case_id)}</b><span class="band Critical">${esc(rc.custody_days)} days in custody · threshold ${esc(rc.threshold_days)} days (${esc(rc.percent_of_threshold)}%)</span></div>
      <details><summary>Draft release application</summary><pre class="doc">${esc(a.draft)}</pre></details>
      <div class="row gap"><input class="note" placeholder="Note (optional)"><button class="btn" data-approve="1">Approve &amp; send to legal-aid lawyer</button><button class="btn ghost" data-approve="0">Dismiss</button></div>
    </div>`;
  }).join("") : "<p class='hint'>No pending release alerts. Run a scan.</p>";
}
$("#alerts").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-approve]");
  if (!b) return;
  const card = b.closest(".alert");
  await api("/api/alerts/decide", { decisions: { [card.dataset.id]: { approve: b.dataset.approve === "1", note: card.querySelector(".note").value } } });
  card.remove();
});
$("#runWatch").addEventListener("click", (e) => busy(e.target, async () => {
  const r = await api("/api/undertrial/scan", {});
  const s = r.summary || {};
  $("#watchKpis").innerHTML = [kpi(s.new_release_alerts ?? 0, "new people entitled to release", "Sec. 479 BNSS"),
    kpi(s.approaching_threshold ?? 0, "approaching the threshold (≥75%)")].join("");
  await loadAlerts();
}));

// ---------- Registry Agent ----------
$("#regStart").valueAsDate = new Date();
let regThread = null;
$("#runRegistry").addEventListener("click", (e) => busy(e.target, async () => {
  $("#regNote").innerHTML = "<p class='hint'>Agent working: triage, review, scheduling…</p>";
  const r = await api("/api/registry/run", { start_date: $("#regStart").value, days: +$("#regDays").value });
  regThread = r.thread_id;
  const m = r.plan.metrics, b = m.baseline_fifo;
  $("#regKpis").innerHTML = [
    kpi(`${m.critical_listed}/${m.critical_total}`, "critical cases listed", `oldest-first: ${b.critical_listed}`),
    kpi(m.critical_avg_wait_days ?? "-", "avg. wait for critical (days)", `oldest-first: ${b.critical_avg_wait_days ?? "-"}`),
    kpi(m.expected_effective_hearings, "expected effective hearings", `oldest-first: ${b.expected_effective_hearings}`),
    kpi(m.advocate_conflicts, "advocate double-bookings", `oldest-first: ${b.advocate_conflicts}`),
    kpi(m.cases_carried_over, "carried over"),
  ].join("");
  const adj = (r.review.adjustments || []);
  $("#regNote").innerHTML = `<div class="card"><h3>Registrar's note <span class="pill">${esc(r.review.engine)} review · ${adj.length} adjustment(s)</span></h3><p>${esc(r.explanation)}</p>
    ${adj.length ? `<ul class="reasons">${adj.map((a) => `<li>${esc(a.case_id)} ${a.adjustment > 0 ? "+" : ""}${esc(a.adjustment)}: ${esc(a.reason)}</li>`).join("")}</ul>` : ""}
    ${(r.review.data_quality_notes || []).length ? `<b>Data to collect</b><ul class="reasons">${r.review.data_quality_notes.slice(0, 10).map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
    ${r.awaiting_approval ? `<div class="row gap"><button class="btn" id="approveList">Approve &amp; publish</button><button class="btn ghost" id="rejectList">Reject</button></div>` : ""}</div>`;
  $("#regTable").innerHTML = `<div class="card table-wrap"><h3>Top priorities</h3><table><tr><th>Case</th><th>Type</th><th>Stage</th><th>Pending</th><th>Score</th><th>Band</th><th>Flags</th><th>Route</th></tr>
    ${r.top_cases.slice(0, 40).map((c) => `<tr title="${esc(c.reasons.join(" · "))}"><td>${esc(c.case_id)}</td><td>${pretty(c.case_type)}</td><td>${pretty(c.stage)}</td><td>${esc(c.years_pending)} y</td><td><b>${esc(c.score)}</b></td><td class="band ${esc(c.band)}">${esc(c.band)}</td><td>${c.flags.map((f) => `<span class="flag">${pretty(f)}</span>`).join("")}</td><td>${esc(c.recommended_route)}</td></tr>`).join("")}</table></div>`;
  $("#calendar").innerHTML = r.plan.calendar.map((d) => `
    <div class="day"><h3>${esc(new Date(d.date).toDateString())}</h3><div class="benches">
    ${d.benches.map((bn) => `<div class="card bench"><b>${esc(bn.name)}</b>
      <div class="util">${bn.cases.length} cases · expected ${esc(bn.expected_minutes)} min · ${esc(bn.utilisation_percent)}% utilised</div>
      <ul>${bn.cases.map((c) => `<li><span class="slot">${esc(c.slot)}</span><span class="band ${esc(c.band)}">●</span> ${esc(c.case_id)} · ${pretty(c.stage)}${c.batch ? ` <span class="batch">[${esc(c.batch)}]</span>` : ""}</li>`).join("")}</ul>
    </div>`).join("")}</div></div>`).join("");
}));
$("#regNote").addEventListener("click", async (e) => {
  if (!["approveList", "rejectList"].includes(e.target.id)) return;
  const r = await api("/api/registry/decide", { thread_id: regThread, approve: e.target.id === "approveList" });
  e.target.parentElement.innerHTML = `<b>Cause list ${esc(r.status)}.</b>`;
});

// ---------- Legal aid form ----------
$("#aidForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const applicant = {};
  e.target.querySelectorAll("input[type=checkbox]").forEach((c) => (applicant[c.name] = c.checked));
  applicant.annual_income = fd.get("annual_income");
  applicant.court_level = fd.get("court_level");
  busy(e.target.querySelector("button[type=submit]"), async () => {
    const r = await api("/api/legal-aid", { applicant, draft: applicant.draft, problem: fd.get("problem"), language: fd.get("language"), district: fd.get("district") });
    $("#aidOut").innerHTML = `
      <div class="card"><h3 class="${r.eligible ? "ok" : "no"}">${r.eligible ? "✔ You are likely eligible for FREE legal aid" : "✖ Not eligible on the details given"}</h3>
        ${r.grounds.length ? `<ul>${r.grounds.map((g) => `<li>Section ${esc(g.clause)}: ${esc(g.ground)}</li>`).join("")}</ul>` : ""}
        <p><b>Where to apply:</b> ${esc(r.where_to_apply)}</p>
        <b>Next steps</b><ol>${r.next_steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>
        <b>Documents to carry</b><ul>${r.documents_needed.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
        <p class="hint">${esc(r.income_limit_note)}</p></div>
      ${r.draft ? `<div class="card"><h3>Draft application <span class="pill">${esc(r.draft.engine)}</span></h3><pre class="doc">${esc(r.draft.application)}</pre></div>` : ""}`;
  });
});

// ---------- Impact ----------
async function loadImpact() {
  const i = await api("/api/impact");
  $("#impactKpis").innerHTML = [
    kpi(i.people_reached, "people reached"),
    kpi(i.legal_aid.found_eligible, "found eligible for free legal aid", `${i.legal_aid.eligibility_checks} checks`),
    kpi(i.legal_aid.applications_drafted, "legal-aid applications drafted"),
    kpi(i.legal_aid.lawyers_assigned_reported, "lawyers assigned (partner-reported)"),
    kpi(i.undertrials.flagged, "undertrials flagged for release"),
    kpi(i.undertrials.release_applications_approved, "release applications approved"),
    kpi(i.documents.pages, "case-file pages analysed", `${i.documents.analyzed} documents`),
    kpi(i.documents.reading_hours_saved_est, "reading hours saved (est.)", `${i.assumptions.minutes_per_page_read} min/page`),
    kpi(i.registry.cases_triaged, "case triage runs (cases)"),
    kpi(i.registry.cause_lists_published, "cause lists published", `${i.registry.cases_listed} listings`),
    kpi(i.feedback.avg_rating ?? "-", "avg. user rating (1-5)", `${i.feedback.responses} responses`),
  ].join("");
}
$("#refreshImpact").addEventListener("click", loadImpact);
