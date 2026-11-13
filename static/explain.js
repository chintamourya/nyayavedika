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
  return `<div class="custody" title="${esc(days)} days in custody; limit ${esc(limit)} days">
      <div class="track"><i class="fill ${over >= 0 ? "over" : ""}" style="width:${pct(days)}"></i><b class="limit" style="left:${pct(limit)}"></b></div>
      <p class="hint">${esc(days)} days in custody ÷ limit ${esc(limit)} days (${esc(a.basis || "Sec. 479 BNSS")}) =
        <b>${Math.round((100 * days) / limit)}%</b> ${over >= 0 ? `- <b>${esc(over)} days over</b>` : `- ${esc(-over)} days to go`}</p></div>`;
}

// Today: how a record moves through the screens, with live counts.
function pipelineStrip(p, role) {
  if (!p) return "";
  const cl = p.latest_cause_list;
  const step = (tab, n, label, sub, tip, staffOnly = false) => {
    const body = `<b>${esc(n)}</b><span>${esc(label)}</span><small>${esc(sub)}</small>`;
    return staffOnly && role !== "staff"
      ? `<span class="pipe end" aria-disabled="true" title="${esc(tip)} Staff-only screen">${body}</span>`
      : `<button class="pipe" data-pipe="${tab}" title="${esc(tip)}">${body}</button>`;
  };
  return `<div class="pipeline" aria-label="How cases move">
    ${step("intake", p.intake_in_progress, "Intake", "files being read", "Uploaded files are read, summarised, scored and turned into cases", true)}
    <span class="arrow" aria-hidden="true">→</span>
    ${step("docket", p.docket_pending, "Docket", `${p.docket_needs_review} need a fix`, "Every pending case with its priority score and band", true)}
    <span class="arrow" aria-hidden="true">→</span>
    ${step("cause", p.listed_upcoming, "Cause list", cl ? `latest #${cl.id} ${cl.status}` : "no list yet", "The weekly list: urgent and long-waiting cases first, within bench time", true)}
    <span class="arrow" aria-hidden="true">→</span>
    <span class="pipe end"><b>⚖</b><span>Hearing</span><small>outcome recorded</small></span>
    <span class="branch" aria-hidden="true">↳</span>
    ${step("undertrial", p.alerts_open, "Undertrial", `${p.in_custody} in custody · ${p.alerts_waiting_decision} to decide`, "Custody cases are checked daily against Sec. 479 BNSS")}
  </div>`;
}

const HOW = {
  today: (r) => `<p>Today gathers what needs a person now. Each tile is a filter: click it to see the cases behind the number.</p>
    <ul><li><b>Critical waiting</b>: score ≥ ${r.bands[0].min_score} (or past the Sec. 479 limit) and not yet on an upcoming list.</li>
    <li><b>Past deadline</b>: not listed within the band's deadline (${r.bands.map((b) => `${b.band} ${b.sla_days}d`).join(", ")}).</li>
    <li><b>Deferred ${r.schedule.must_list_after_deferrals}+ times</b>: left out of ${r.schedule.must_list_after_deferrals} lists in a row - the next draft must list them.</li>
    <li><b>Proposed slots</b>: a new urgent upload gets a suggested hearing at once; accepting keeps it in the draft until the list is published.</li></ul>`,
  intake: (r) => `<p>Each file goes through: <b>queued → reading → summarising → extracting facts → scored → hearing proposed</b>.</p>
    <ul><li>Accepted: ${r.intake.allowed_types.join(", ")} · up to ${r.intake.max_files} files per batch, ${r.intake.max_pages} pages per file.</li>
    <li>The same file sent twice is recognised by its content and not processed again.</li>
    <li>A fact the reader is unsure of is marked <b>needs review</b> with a button to fill it in; the case is re-scored when you save.</li>
    <li>Urgent cases (Critical) get a proposed hearing slot straight away; others wait for the weekly cause list.</li></ul>`,
  docket: (r) => `<p><b>Use this screen:</b> filter the queue, then open a case to check its facts and cited sources. The score and band help order work; they are not a legal decision or hearing-readiness result.</p>
    <p>The score (0-${r.score_cap}) adds up these points; the band follows from the score.</p>
    <table class="rules"><tr><th>Factor</th><th>Points</th><th>Rule</th></tr>${r.factors.map((f) =>
      `<tr><td>${esc(f.factor)}</td><td>${esc(f.points)}</td><td>${esc(f.rule)}</td></tr>`).join("")}</table>
    ${bandScale(null, r)}
    <p class="hint">Bands and listing deadlines: ${r.bands.map((b) => `${b.band} ≥${b.min_score} → list within ${b.sla_days} day(s)`).join(" · ")}.</p>
    <details><summary>Base points by case type</summary><p class="hint">${Object.entries(r.base_by_type).map(([k, v]) => `${esc(k.replace(/_/g, " "))} ${v}`).join(" · ")}</p></details>`,
  cause: (r) => `<p>The draft is built in this order:</p><ol>${r.schedule.order.map((o) => `<li>${esc(o)}</li>`).join("")}</ol>
    <ul><li><b>Effective score</b> = ${esc(r.schedule.effective_score)} - so a case that keeps being left out climbs.</li>
    <li>${r.schedule.must_list_reserve_percent}% of every bench's day is kept for must-list cases.</li>
    <li>No advocate is booked in two courts within ${r.schedule.advocate_buffer_minutes} minutes; lunch ${esc(r.schedule.lunch)}.</li>
    <li>Cases that do not fit are <b>carried over</b> with the reason (capacity, advocate clash, no suitable bench) and are deferred +1.</li>
    <li>Publishing creates the hearings and sets each case's next date; a case left out again is deferred once more.</li></ul>`,
  undertrial: (r) => `<p>${esc(r.undertrial.law)}: an undertrial must be released on bond after custody of
    <b>${esc(r.undertrial.first_offender)}</b> (first offence) or <b>${esc(r.undertrial.others)}</b> (otherwise).</p>
    <ul><li>Unknown first-offence status: ${esc(r.undertrial.unknown_offender)}.</li>
    <li>Not applied to: ${esc(r.undertrial.excluded)}.</li>
    <li>"Near the limit" = ${r.undertrial.near_percent}% or more of the limit.</li>
    <li>Each alert moves: found (pending) → approved by a legal-aid lawyer → filed → heard → released or denied. A dismissal needs a reason.</li>
    <li>Staff can open the case, track custody-record follow-up and flag lawyer review. These are internal notes, not messages or legal approvals.</li></ul>
    <p class="hint">Example: maximum sentence 7 years = 2,555 days. First offence: limit 852 days; otherwise 1,277 days.</p>`,
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
    el.innerHTML = `<details class="how"${open ? " open" : ""}><summary>ⓘ Why and how to use this screen</summary><div>${fn(r)}</div></details>`;
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
