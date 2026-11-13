// "How this works" for the staff screens. Every number shown here comes from GET /api/rules, which reads the
// same constants the scoring, scheduling and Sec. 479 code runs on - so the explanation cannot drift from the logic.
let RULES = null;
async function loadRules() {
  if (RULES) return RULES;
  try { RULES = await api("/api/rules"); } catch { RULES = null; }
  return RULES;
}
const BAND_COLOR = { Critical: "var(--critical)", High: "var(--high)", Medium: "var(--medium)", Routine: "var(--routine)" };

// A 0-100 scale with the band cut-offs and a marker for this score.
function bandScale(score, rules = RULES) {
  if (!rules) return "";
  const cuts = [...rules.bands].sort((a, b) => a.min_score - b.min_score);
  const segs = cuts.map((b, i) => {
    const end = i + 1 < cuts.length ? cuts[i + 1].min_score : 100;
    return `<i class="seg" style="left:${b.min_score}%;width:${end - b.min_score}%;background:${BAND_COLOR[b.band]}" title="${esc(b.band)}: ${b.min_score}-${end}"></i>`;
  }).join("");
  const s = Math.max(0, Math.min(100, Number(score) || 0));
  return `<div class="scale" role="img" aria-label="score ${esc(s)} of 100">${segs}${score == null ? "" : `<b class="mark" style="left:${s}%"></b>`}</div>
    <div class="scale-labels">${cuts.map((b) => `<span style="left:${b.min_score}%">${esc(b.band)} ≥${b.min_score}</span>`).join("")}</div>`;
}
// Small inline bar for tables.
function scoreBar(score, bandName) {
  const s = Math.max(0, Math.min(100, Number(score) || 0));
  return `<span class="mini" title="Score ${esc(score)} of 100 - see 'How the score works'"><i style="width:${s}%;background:${BAND_COLOR[bandName] || "#888"}"></i></span>`;
}

// The drawer's Priority tab: each reason with its points, adding up to the score.
function scoreBreakdown(priority, rules = RULES) {
  const chips = priority.chips || [];
  const rows = chips.map((c) => {
    const pts = c.points != null ? Number(c.points) : null;
    const w = pts ? Math.min(100, Math.abs(pts) * 2.5) : 0;
    const sign = pts != null && pts > 0 ? "+" : "";
    return `<tr><td>${esc(c.text)}</td><td class="num">${pts != null ? `${sign}${esc(pts)}` : "-"}</td>
      <td><span class="mini wide"><i style="width:${w}%"></i></span></td></tr>`;
  }).join("");
  const sum = chips.reduce((s, c) => s + (Number(c.points) || 0), 0);
  const capped = sum > 100 ? ` (capped at ${rules?.score_cap || 100})` : "";
  const forced = (priority.flags || []).includes("UNDERTRIAL_RELEASE_ELIGIBLE")
    ? `<p class="hint">Band forced to <b>Critical</b>: the person is past the Sec. 479 limit and must not wait behind other matters.</p>` : "";
  const band = rules?.bands.find((b) => b.band === priority.band);
  return `${bandScale(priority.score, rules)}
    <table class="rules"><tr><th>Why</th><th class="num">Points</th><th></th></tr>${rows}
      <tr class="total"><td>Total${capped}</td><td class="num"><b>${esc(priority.score)}</b></td><td>${band ? `→ ${esc(band.band)}` : ""}</td></tr></table>
    ${forced}
    ${band ? `<p class="hint">${esc(band.band)} cases should be listed within <b>${esc(band.sla_days)} day(s)</b> of becoming ready - after that they become must-list.</p>` : ""}`;
}

// Undertrial card: custody days against the one-third / one-half marks.
function custodyMath(a) {
  if (a.custody_days == null || !a.threshold_days) return "";
  const limit = Number(a.threshold_days), days = Number(a.custody_days);
  const max = Math.max(limit * 1.25, days * 1.05);
  const pct = (v) => `${Math.min(100, (100 * v) / max).toFixed(1)}%`;
  const over = days - limit;
  return `<div class="custody" title="${esc(days)} days in custody; Sec. 479 mark ${esc(limit)} days">
      <div class="track"><i class="fill ${over >= 0 ? "over" : ""}" style="width:${pct(days)}"></i><b class="limit" style="left:${pct(limit)}"></b></div>
      <p class="hint">${esc(days)} days in custody ÷ mark ${esc(limit)} days (${esc(a.basis || "Sec. 479 BNSS")}) =
        <b>${Math.round((100 * days) / limit)}%</b> ${over >= 0 ? `- <b>${esc(over)} days past</b>` : `- ${esc(-over)} days to go`}
        <br>Custody counted from the recorded date to today; any period of delay caused by the accused is not deducted here.</p></div>`;
}

// Today: how a record moves through the screens, with live counts.
function pipelineStrip(p) {
  if (!p) return "";
  const cl = p.latest_cause_list;
  const step = (tab, n, label, sub, tip) => `<button class="pipe" data-pipe="${tab}" title="${esc(tip)}"><b>${esc(n)}</b><span>${esc(label)}</span><small>${esc(sub)}</small></button>`;
  return `<div class="pipeline" aria-label="How cases move">
    ${step("intake", p.intake_in_progress, "Intake", "files being read", "Uploaded files are read, summarised, scored and turned into cases")}
    <span class="arrow" aria-hidden="true">→</span>
    ${step("docket", p.docket_pending, "Triage", `${p.docket_needs_review} need a fix`, "Every pending case with its priority score and band")}
    <span class="arrow" aria-hidden="true">→</span>
    ${step("cause", p.listed_upcoming, "Scheduling", cl ? `latest #${cl.id} ${cl.status}` : "no list yet", "The weekly cause list: urgent and long-waiting cases first, within bench time")}
    <span class="arrow" aria-hidden="true">→</span>
    <span class="pipe end"><b>⚖</b><span>Hearing</span><small>outcome recorded</small></span>
    <span class="branch" aria-hidden="true">↳</span>
    ${step("undertrial", p.alerts_open, "Undertrial", `${p.in_custody} in custody · ${p.alerts_waiting_decision} to decide`, "Custody cases are checked daily against Sec. 479 BNSS")}
  </div>`;
}

const HOW = {
  today: (r) => `<p>Today is the daily desk: start here. The order on the page follows the work.</p>
    <ul><li><b>Needs attention now</b>: proposed fast-lane slots to accept, cases with a detail to verify, people past the Sec. 479 mark, missed listing deadlines, and a draft list waiting for approval.</li>
    <li><b>Case triage panel</b>: pending matters by band (click a band to open it) and the highest-priority cases that hold no hearing slot yet, each with its main reason.</li>
    <li><b>Scheduling panel</b>: next week's bench time against the expected time of the waiting cases, and how many are must-list. One click prepares or reopens the draft.</li>
    <li><b>Court diary</b>: matters on published lists for any day. After the sitting, record heard / adjourned (reason and next date) / disposed / not reached. The next date must be after the hearing date; corrections never count an adjournment twice; earlier hearings with nothing recorded are listed below it.</li>
    <li><b>Other counts</b>: each tile is a filter - Critical waiting (score ≥ ${r.bands[0].min_score} or past the Sec. 479 mark, not yet listed), past deadline (${r.bands.map((b) => `${b.band} ${b.sla_days}d`).join(", ")}), deferred ${r.schedule.must_list_after_deferrals}+ times in a row, needs review.</li>
    <li>Uploaded and imported cases are always listed above synthetic demo cases.</li></ul>`,
  intake: (r) => `<p>Step 1. Each file goes through: <b>queued → reading → summarising → extracting facts → scored → hearing proposed</b>.</p>
    <ul><li>Accepted: ${r.intake.allowed_types.join(", ")} · up to ${r.intake.max_files} files per batch, ${r.intake.max_pages} pages per file. Single files, several files, a folder, or pasted text.</li>
    <li>Say how the files belong together: each a separate case, one case per sub-folder, all one case, or attach to an existing case number (required for that choice).</li>
    <li>The batch shows a progress bar and counts; a failed file can be retried alone, or all failed files at once. Brief network drops are retried automatically.</li>
    <li>The same file sent twice is recognised by its content and not processed again.</li>
    <li>A fact the reader is unsure of is marked <b>needs review</b> with a button to fill it in; the case is re-scored when you save.</li>
    <li>Critical cases get a proposed hearing slot straight away; others wait for the weekly cause list.</li></ul>`,
  docket: (r) => `<p>Step 2, case triage. The score (0-${r.score_cap}) adds up these fixed points - never an AI opinion - and the band follows from the score.</p>
    <table class="rules"><tr><th>Factor</th><th>Points</th><th>Rule</th></tr>${r.factors.map((f) =>
      `<tr><td>${esc(f.factor)}</td><td>${esc(f.points)}</td><td>${esc(f.rule)}</td></tr>`).join("")}</table>
    ${bandScale(null, r)}
    <p class="hint">Bands and listing deadlines: ${r.bands.map((b) => `${b.band} ≥${b.min_score} → list within ${b.sla_days} day(s)`).join(" · ")}.</p>
    <ul><li><b>Triage queues</b> above the table: custody and bail, past the Sec. 479 mark, Critical not yet listed, listing deadline missed, left out 3+ times, time-bound by statute, pending 10+ years, details to verify.</li>
    <li>Under each score: its biggest point contributions. In the flags column: why the case needs a person, in plain words, from stored facts only.</li>
    <li>Click a row for the full breakdown, facts with source pages, timeline and history. Correct a wrong fact there; the case is re-scored and the change is audited.</li>
    <li>Uploaded and imported cases come first, then synthetic examples. "Export view (CSV)" downloads the rows on screen.</li></ul>
    <details><summary>Base points by case type</summary><p class="hint">${Object.entries(r.base_by_type).map(([k, v]) => `${esc(k.replace(/_/g, " "))} ${v}`).join(" · ")}</p></details>`,
  cause: (r) => `<p>Step 3, efficient scheduling. Before drafting, the <b>bench-time check</b> compares the week's sitting time (holidays and judges on leave removed) with the expected time of the waiting cases. The draft is then built in this order:</p><ol>${r.schedule.order.map((o) => `<li>${esc(o)}</li>`).join("")}</ol>
    <ul><li><b>Effective score</b> = ${esc(r.schedule.effective_score)} - so a case that keeps being left out climbs.</li>
    <li>${r.schedule.must_list_reserve_percent}% of every bench's day is kept for must-list cases.</li>
    <li>No advocate is booked in two courts within ${r.schedule.advocate_buffer_minutes} minutes; lunch ${esc(r.schedule.lunch)}.</li>
    <li>Cases that do not fit are <b>carried over</b> with the reason (capacity, advocate clash, no suitable bench) and are deferred +1 when the list is published.</li>
    <li>Check the draft: the <b>In short</b> paragraph, problems, <b>readiness</b> notes (custody production, details to verify), and move or hold a matter if needed.</li>
    <li>Approval needs the confirmation tick; publishing creates the hearings and sets each case's next date. A draft can be rejected with a reason. Saved drafts and published lists can be reopened.</li>
    <li><b>Print view</b> groups each bench's matters under the usual listing heads with item numbers; timings are estimates and the Presiding Officer decides the order of calling.</li></ul>`,
  undertrial: (r) => `<p>${esc(r.undertrial.law)}: an undertrial who has been detained for <b>${esc(r.undertrial.others)}</b>
    is to be released by the court on bail; a first-time offender, after <b>${esc(r.undertrial.first_offender)}</b>, on bond.
    The court may, after hearing the Public Prosecutor and for reasons in writing, order continued detention, and the
    period of delay caused by the accused is not counted. The jail superintendent is to apply to the court when the mark is reached (Sec. 479(3)).</p>
    <ul><li>Unknown first-offence status: ${esc(r.undertrial.unknown_offender)}.</li>
    <li>Not applied to: ${esc(r.undertrial.excluded)}.</li>
    <li>"Near the mark" = ${r.undertrial.near_percent}% or more of it.</li>
    <li><b>Who does what.</b> Court staff record <b>counsel on record</b> from the DLSA assignment letter or a vakalatnama.
      Counsel (usually a DLSA legal-aid lawyer) decides in the Advocate portal whether to file, or records why not.
      Court staff then record the filing (petition number), the hearing, <b>the court's order</b> (release on bail or bond, or continued detention, with the order date) and release from custody once the bond is accepted.
      <b>Only the court</b> decides release; the system refuses any step from the wrong role.</li>
    <li>Staff can also run the check again, fill in a missing custody date or sentence, and download the draft application and the custody-record review request (English, Hindi, Telugu).</li>
    <li>NyayaVedika only does the arithmetic on recorded dates and flags blockers; it never decides eligibility.</li></ul>
    <p class="hint">Example: maximum sentence 7 years = 2,555 days. First offence: mark at 851 days (one-third); otherwise 1,277 days (one-half).</p>`,
  insights: () => `<p>Weekly health of the docket and the evidence of impact.</p>
    <ul><li><b>Longest wait</b> per band counts from the day a case became ready to list.</li>
    <li><b>Before / after</b> compares the latest draft with listing oldest-first on the same cases and benches.</li>
    <li><b>Impact</b> counts real events logged by the app (checks run, documents read, alerts approved, lists published) - export them as CSV for evidence.</li></ul>`,
};
async function fillHow() {
  const r = await loadRules();
  $$("[data-how]").forEach((el) => {
    const fn = HOW[el.dataset.how];
    if (!fn || !r) { el.innerHTML = ""; return; }
    const open = el.querySelector("details.how")?.open;
    el.innerHTML = `<details class="how"${open ? " open" : ""}><summary>ⓘ How this works</summary><div>${fn(r)}</div></details>`;
  });
}

// Cause list: why a case is in this place on the draft.
function whyListed(c, rules = RULES) {
  const lines = [];
  const phase = { must: "Must-list (placed first, in the reserved time)", regular: "Regular order (band, then effective score)", backfill: "Backfill (a short matter fitted into a gap)" }[c.phase];
  if (phase) lines.push(phase);
  if (c.must_list) lines.push(c.deferred >= (rules?.schedule.must_list_after_deferrals || 3) ? `Deferred ${c.deferred}× in a row` : "Critical, release-eligible or past its deadline");
  if (c.score_eff != null && c.score != null && c.score_eff !== c.score) lines.push(`Score ${c.score} + aging ${(c.score_eff - c.score).toFixed(1)} = ${c.score_eff}`);
  else if (c.score != null) lines.push(`Score ${c.score} (${c.band})`);
  if (c.expected_minutes) lines.push(`About ${Math.round(c.expected_minutes)} min expected (stage ${String(c.stage || "-").replace(/_/g, " ")})`);
  if (c.route) lines.push(`Route: ${c.route}`);
  return `<ul class="why-box">${lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>`;
}
