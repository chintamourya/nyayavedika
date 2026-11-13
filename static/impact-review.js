// Impact evidence review desk (staff token). Lists reports with identity details, lets a staff user mark each one
// verified / rejected with a note, shows the verified-only summary and exports CSV.
const LINK_ROLES = [["advocate", "Advocates"], ["legal_aid_lawyer", "Legal-aid lawyers"], ["court_staff", "Court staff"],
  ["paralegal", "Para-legal volunteers"], ["law_student", "Law students"], ["citizen", "Citizens"]];
let OPTS = null;
const label = (list, v) => (OPTS?.[list] || []).find((o) => o.value === v)?.label || String(v ?? "").replace(/_/g, " ");

$("#shareLinks").innerHTML = LINK_ROLES.map(([r, l]) => {
  const url = `${location.origin}/impact-report?role=${r}`;
  return `<div><b>${esc(l)}</b><input readonly value="${esc(url)}" aria-label="Link for ${esc(l)}"><button class="btn ghost small" type="button" data-copy="${esc(url)}">Copy</button></div>`;
}).join("");
$$("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(b.dataset.copy); toast("Link copied."); } catch { toast("Copy is blocked; select the link and copy it.", "error"); }
}));

$("#revToken").value = getToken();
$("#revSignin").addEventListener("submit", (e) => { e.preventDefault(); setToken($("#revToken").value); load(); });
$("#revStatus").addEventListener("change", loadList);
$("#revExport").addEventListener("click", (e) => busy(e.target, async () => {
  toast(`Downloaded ${await downloadFrom("/api/impact-reports/export.csv", {}, "impact_reports.csv")} - keep it private.`);
}));

function kpi(v, l) { return `<div><b>${esc(v ?? "-")}</b><span>${esc(l)}</span></div>`; }
async function loadSummary() {
  const s = await api("/api/impact-reports/summary");
  const t = s.time, o = s.outcomes;
  const topOutcomes = Object.entries(o).filter(([k, n]) => n && k !== "nothing_yet").sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `<li>${esc(label("outcomes", k))}: <b>${esc(n)}</b></li>`).join("");
  $("#revSummary").innerHTML = `<h2>Evidence so far</h2>
    <p class="hint">${esc(s.note)}</p>
    <div class="ev-kpis">${kpi(s.verified, "verified reports")}${kpi(s.pending, "waiting for verification")}
      ${kpi(s.verified_professionals, "verified professionals")}${kpi(s.verified_on_real_matters, "used on real matters")}
      ${kpi(t.median_minutes_saved != null ? `${t.median_minutes_saved} min` : null, `median time saved per task (${t.paired_reports} paired, ${t.timed} timed)`)}
      ${kpi(t.median_percent_saved != null ? `${t.median_percent_saved}%` : null, "median share of time saved")}
      ${kpi(t.total_hours_saved, "hours saved in total")}
      ${kpi(s.volume.documents, "documents handled")}${kpi(s.volume.cases_or_people, "cases or people helped")}
      ${kpi(s.accuracy.checked ? `${s.accuracy.matched}/${s.accuracy.checked}` : null, "outputs checked that matched the source")}
      ${kpi(s.avg_usefulness, "average usefulness (1-5)")}${kpi(s.would_continue_pct != null ? `${s.would_continue_pct}%` : null, "will keep using it")}</div>
    ${topOutcomes ? `<h3>Outcomes in verified reports</h3><ul>${topOutcomes}</ul>` : ""}
    ${s.quotes.length ? `<h3>Quotable (verified, with permission)</h3><ul>${s.quotes.map((q) => `<li>"${esc(q.text)}" - ${esc(q.by)}</li>`).join("")}</ul>` : ""}`;
}
function row(k, v) { return v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length) ? "" : `<dt>${esc(k)}</dt><dd>${v}</dd>`; }
function card(r) {
  const id = r.identity || {}, u = r.usage || {}, m = r.measures || {}, g = r.ratings || {};
  const list = (key, vals) => (vals || []).map((v) => esc(label(key, v))).join("; ");
  return `<article class="card report-card ${esc(r.status)}">
    <div class="row between wrap"><b>IR-${esc(r.id)} · ${esc(label("roles", r.role))}</b>
      <span class="pill">${esc(r.status)}${r.verified_by ? ` by ${esc(r.verified_by)}` : ""}</span></div>
    <dl>
      ${row("Submitted", esc(String(r.created_at || "").slice(0, 16).replace("T", " ")))}
      ${row("Name", esc(id.full_name))}${row("Email", id.email ? `<a href="mailto:${esc(id.email)}">${esc(id.email)}</a>` : "")}
      ${row("Enrolment number", id.enrolment_number ? `<b>${esc(id.enrolment_number)}</b>${id.enrolment_year ? ` (${esc(id.enrolment_year)})` : ""}` : "")}
      ${row("Law school", esc(id.law_school))}
      ${row("Courts practised in", esc(id.practice_court))}${row("Designation", esc(id.designation))}
      ${row("Legal services authority", esc(id.legal_services_authority))}${row("Work experience", esc(id.work_experience))}
      ${row("Place", esc([id.district, id.state].filter(Boolean).join(", ")))}
      ${row("Profile", id.profile_url ? `<a href="${esc(id.profile_url)}" target="_blank" rel="noopener noreferrer">${esc(id.profile_url)}</a>` : "")}
      ${row("Used", `${list("features", u.features)}${u.used_on ? ` - <i>${esc(label("used_on", u.used_on))}</i>` : ""}${u.times_used ? ` · ${esc(u.times_used)} time(s)` : ""}`)}
      ${row("Task", esc(label("tasks", u.task)))}
      ${row("Time", m.minutes_without ? `${esc(m.minutes_without)} min without → ${esc(m.minutes_with)} min with (${esc(m.timing_basis)})` : "")}
      ${row("Volume", [m.documents_handled != null ? `${m.documents_handled} documents` : "", m.pages_handled != null ? `${m.pages_handled} pages` : "", m.cases_handled != null ? `${m.cases_handled} cases/people` : ""].filter(Boolean).map(esc).join(" · "))}
      ${row("Accuracy", m.accuracy ? `${esc(label("accuracy", m.accuracy))}${m.errors_found != null ? ` · ${esc(m.errors_found)} error(s)` : ""}` : "")}
      ${row("Outcomes", list("outcomes", r.outcomes))}${row("What happened", esc(r.outcome_detail))}
      ${row("Ratings", [g.usefulness && `useful ${g.usefulness}/5`, g.ease && `easy ${g.ease}/5`, g.trust && `trust ${g.trust}/5`].filter(Boolean).map(esc).join(" · "))}
      ${row("Keep using", esc(r.would_continue))}${row("Quote", r.testimonial ? `"${esc(r.testimonial)}" <span class="hint">(${esc(label("quote", r.quote_permission))})</span>` : "")}
      ${row("May contact", r.consent_contact ? "yes" : "no")}${row("Check note", esc(r.verification_note))}
    </dl>
    <div class="row gap wrap"><input data-note="${esc(r.id)}" placeholder="What you checked (e.g. found on BCT roll)" maxlength="300" style="flex:1;min-width:220px">
      <button class="btn small" data-verify="${esc(r.id)}" data-to="verified">Mark verified</button>
      <button class="btn ghost small" data-verify="${esc(r.id)}" data-to="rejected">Reject</button>
      ${r.status !== "pending" ? `<button class="btn ghost small" data-verify="${esc(r.id)}" data-to="pending">Back to pending</button>` : ""}</div>
  </article>`;
}
async function loadList() {
  try {
    const { reports } = await api(`/api/impact-reports?status=${encodeURIComponent($("#revStatus").value)}`);
    $("#revList").innerHTML = reports.map(card).join("") || `<p class="empty-state">No reports here yet. Share a link above.</p>`;
    $$("[data-verify]").forEach((b) => b.addEventListener("click", () => busy(b, async () => {
      const id = b.dataset.verify, note = $(`[data-note="${id}"]`).value.trim();
      if (b.dataset.to === "verified" && !note) throw new Error("Write what you checked before marking it verified.");
      await api(`/api/impact-reports/${id}/verify`, { json: { status: b.dataset.to, note } });
      toast(`IR-${id} marked ${b.dataset.to}.`); load();
    })));
  } catch (e) { $("#revList").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}
async function load() {
  $("#revMsg").classList.add("hidden");
  try {
    OPTS = OPTS || await api("/api/impact-reports/options", { noToken: true });
    await loadSummary();
    await loadList();
  } catch (e) {
    $("#revMsg").textContent = e.status === 403 ? "This page needs a staff token." : e.message;
    $("#revMsg").classList.remove("hidden");
  }
}
if (getToken()) load();
