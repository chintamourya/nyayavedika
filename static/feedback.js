// Landing-page feedback: a wall of short cards (click for the full feedback) and a short form
// (about 3 minutes, never more than 5). Vanilla JS; needs common.js (esc, api, getToken, toast).
// The four question groups follow the judging criteria: size of the problem, severity, quality of the solution, proven impact.
(() => {
  const LABELS = {
    role: { advocate: "Advocate", lawyer: "Lawyer", court_staff: "Court staff", citizen: "Citizen", other: "Other" },
    features: { legal_aid: "Free legal aid check", rights_guide: "Rights guide / chat", document_summary: "Document summary",
      triage: "Case triage", cause_list: "Cause list", undertrial_alerts: "Undertrial alerts" },
    frequency: { rarely: "Rarely", sometimes: "Sometimes", often: "Often", weekly: "Every week" },
    costs: { missed_hearing: "Missed or adjourned hearings", lost_wages: "Lost wages", travel: "Extra travel days",
      long_custody: "Time in custody", fees: "Fees paid", no_lawyer: "No lawyer available", stress: "Stress on the family" },
    accuracy: { correct: "Correct and clear", mostly: "Mostly correct", wrong: "Something was wrong", unsure: "Not sure" },
    outcomes: { understood_rights: "Understood my rights", got_legal_aid: "Reached legal aid or a lawyer",
      saved_time: "Saved time", case_moved: "A case moved faster", nothing_yet: "Nothing yet" },
    timeSaved: { none: "None", under_1h: "Under 1 hour", "1_to_3h": "1–3 hours", half_day: "Half a day", day_plus: "A day or more" },
    recommend: { yes: "Yes", maybe: "Maybe", no: "No" },
  };
  const STEPS = 4, MINUTES_LEFT = [3, 2, 2, 1];
  const RATING_WORD = ["", "Poor", "Fair", "Good", "Very good", "Excellent"];

  const stars = (n) => `<span class="fb-stars" role="img" aria-label="${n} out of 5">${"★".repeat(n)}<span class="off">${"★".repeat(5 - n)}</span></span>`;
  const who = (i) => [i.name, i.place].filter(Boolean).map(esc).join(" · ");
  const wall = $("#fbCards");
  let data = { summary: {}, items: [] };
  let filter = "all";

  // ------------------------------------------------------------------ wall
  const pctText = (v) => (v == null ? "–" : `${v}%`);
  function renderStats() {
    if (!$("#fbStats")) return;
    const s = data.summary || {};
    const responses = s.responses ?? 0;
    const rows = [
      [responses, responses === 1 ? "response" : "responses", ""],
      [s.avg_rating ?? "–", "average rating (out of 5)", ""],
      [pctText(s.outcome_changed_pct), "say it changed something for them", ""],
      [pctText(s.would_recommend_pct), "would recommend it", ""],
    ];
    $("#fbStats").innerHTML = rows.map(([v, l]) => `<div class="kpi"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("");
  }

  function renderFilters() {
    if (!$("#fbFilters")) return;
    const counts = {};
    data.items.forEach((i) => { counts[i.role] = (counts[i.role] || 0) + 1; });
    const roles = Object.keys(LABELS.role).filter((r) => counts[r]);
    const box = $("#fbFilters");
    if (roles.length < 2) { box.innerHTML = ""; return; }
    const btn = (key, text, n) => `<button type="button" class="fb-filter" aria-pressed="${filter === key}" data-role="${key}">${esc(text)} <span>${n}</span></button>`;
    box.innerHTML = btn("all", "All", data.items.length) + roles.map((r) => btn(r, LABELS.role[r], counts[r])).join("");
  }

  function renderCards() {
    const list = $("#fbCards");
    if (!list) return;
    const items = data.items.filter((i) => filter === "all" || i.role === filter);
    if (!data.items.length) {
      list.innerHTML = `<div class="fb-empty"><b>No feedback published yet.</b>
        <p>The numbers above include every response, including older private or hidden ones. New submissions appear here automatically. We do not add placeholder reviews.
        Used NyayaVedika? Share your feedback in under 5 minutes.</p></div>`;
      return;
    }
    list.innerHTML = items.map((i) => `
      <button type="button" class="fb-card" data-id="${i.id}" aria-haspopup="dialog">
        <span class="fb-card-top"><span class="badge fb-role-${esc(i.role)}">${esc(LABELS.role[i.role] || i.role)}</span>${stars(i.rating)}</span>
        <span class="fb-short">${esc(i.short || "(rating only)")}</span>
        <span class="fb-card-foot"><span>${who(i) || "Anonymous"}</span><span class="fb-more">Read full feedback →</span></span>
      </button>`).join("");
  }

  async function loadWall() {
    if (!wall) return;
    try {
      data = await api("/api/field-feedback", { noToken: true });
    } catch (e) {
      $("#fbCards").innerHTML = `<p class="hint">Feedback could not be loaded right now. ${esc(e.message)}</p>`;
      return;
    }
    renderStats(); renderFilters(); renderCards();
  }

  // ------------------------------------------------------------------ full feedback
  const fact = (label, value) => (value ? `<div><dt>${esc(label)}</dt><dd>${value}</dd></div>` : "");
  const chips = (keys, map) => (keys && keys.length ? `<span class="chips">${keys.map((k) => `<span class="chip">${esc(map[k] || k)}</span>`).join("")}</span>` : "");
  const section = (title, body) => (body ? `<section class="fb-sec"><h4>${esc(title)}</h4><dl>${body}</dl></section>` : "");

  function openDetail(id) {
    const i = data.items.find((x) => x.id === +id);
    if (!i) return;
    const a = i.answers || {};
    const problem = fact("How often delays or no access to legal help come up", esc(LABELS.frequency[a.problem_frequency] || ""))
      + fact("People or cases seen per month", a.people_affected != null ? esc(a.people_affected) : "");
    const cost = fact("What it has cost", chips(a.cost_types, LABELS.costs))
      + fact("Days lost", a.days_lost != null ? esc(a.days_lost) : "")
      + fact("Money lost", a.rupees_lost != null ? `₹${esc(Number(a.rupees_lost).toLocaleString("en-IN"))}` : "");
    const quality = fact("Features used", chips(i.features, LABELS.features))
      + fact("Ease of use", a.ease ? stars(a.ease) : "")
      + fact("Was the answer right?", esc(LABELS.accuracy[a.accuracy] || ""))
      + fact("Would recommend", esc(LABELS.recommend[i.would_recommend] || ""));
    const impact = fact("What changed", chips(a.outcomes, LABELS.outcomes))
      + fact("Time saved", esc(LABELS.timeSaved[a.time_saved] || ""));
    $("#fbDetailBody").innerHTML = `
      <div class="row between wrap gap">
        <span class="badge fb-role-${esc(i.role)}">${esc(LABELS.role[i.role] || i.role)}</span>${stars(i.rating)}
      </div>
      <p class="hint">${who(i) || "Anonymous"}${i.created_at ? ` · ${esc(i.created_at)}` : ""}</p>
      ${i.headline ? `<h3 id="fbDetailTitle" tabindex="-1">${esc(i.headline)}</h3>` : `<h3 id="fbDetailTitle" tabindex="-1">Feedback from ${esc(LABELS.role[i.role] || "a user").toLowerCase()}</h3>`}
      ${i.comment ? `<p class="fb-full">${esc(i.comment)}</p>` : ""}
      ${section("The problem", problem)}${section("What it cost", cost)}${section("How well it worked", quality)}${section("What changed", impact)}
      <div class="row between gap fb-actions"><button type="button" class="btn" data-close>Close</button></div>`;
    const d = $("#fbDetail");
    d.showModal();
    d.scrollTop = 0;
    $("#fbDetailTitle").focus({ preventScroll: true });
  }

  // ------------------------------------------------------------------ form
  const radios = (name, map, { required = false } = {}) => `<div class="fb-opts" role="radiogroup">${Object.entries(map).map(([v, t]) =>
    `<label class="fb-opt"><input type="radio" name="${name}" value="${v}"${required ? " required" : ""}><span>${esc(t)}</span></label>`).join("")}</div>`;
  const checks = (name, map) => `<div class="fb-opts">${Object.entries(map).map(([v, t]) =>
    `<label class="fb-opt"><input type="checkbox" name="${name}" value="${v}"><span>${esc(t)}</span></label>`).join("")}</div>`;
  const starInput = (name) => `<div class="fb-starin" data-stars="${name}" role="radiogroup">${[1, 2, 3, 4, 5].map((n) =>
    `<label title="${RATING_WORD[n]}"><input type="radio" name="${name}" value="${n}"><span aria-hidden="true">★</span><span class="sr-only">${n} star${n > 1 ? "s" : ""}, ${RATING_WORD[n]}</span></label>`).join("")}<output class="hint" data-for="${name}"></output></div>`;
  const q = (label, body, hint = "") => `<fieldset class="fb-q"><legend>${label}</legend>${hint ? `<p class="hint">${hint}</p>` : ""}${body}</fieldset>`;
  const num = (name, label, ph, max = null) => `<label class="fb-num">${esc(label)}<input type="number" name="${name}" min="0"${max ? ` max="${max}"` : ""} inputmode="numeric" placeholder="${esc(ph)}"></label>`;

  function formHtml() {
    return `
    <div class="fb-time" role="note"><span aria-hidden="true">⏱</span>
      <div><b>Takes under 5 minutes</b> (most people finish in about 3). Only your role and a star rating are required.
      Skip anything you like. You can write in English, हिन्दी or తెలుగు.</div></div>
    <div class="fb-progress" aria-live="polite"><div class="fb-bar"><i id="fbBar"></i></div><span id="fbStepText"></span></div>
    <form id="fbForm" novalidate>
      <div class="fb-step" data-step="1">
        <h3>About you</h3>
        ${q("I am a… <span class=\"req\">(required)</span>", radios("role", LABELS.role, { required: true }))}
        <div class="grid2">
          <label>First name <span class="hint">(optional)</span><input name="name" maxlength="60" autocomplete="given-name"></label>
          <label>Court, district or town <span class="hint">(optional)</span><input name="place" maxlength="60"></label>
        </div>
        ${q("What did you try?", checks("features", LABELS.features), "Tick all that apply.")}
      </div>
      <div class="fb-step" data-step="2" hidden>
        <h3>The problem you face</h3>
        ${q("How often do you, or the people you help, face court delays or no access to legal help?", radios("problem_frequency", LABELS.frequency))}
        ${num("people_affected", "About how many people or cases like this do you see in a month?", "e.g. 20")}
        ${q("What has that cost?", checks("cost_types", LABELS.costs), "Tick all that apply.")}
        <div class="grid2">${num("days_lost", "Days lost (typical case)", "e.g. 12")}${num("rupees_lost", "Money lost in ₹ (typical case)", "e.g. 5000")}</div>
      </div>
      <div class="fb-step" data-step="3" hidden>
        <h3>How well did it work?</h3>
        ${q("Overall rating <span class=\"req\">(required)</span>", starInput("rating"))}
        ${q("How easy was it to use?", starInput("ease"))}
        ${q("Was what it told you correct and clear?", radios("accuracy", LABELS.accuracy))}
        ${q("What changed for you?", checks("outcomes", LABELS.outcomes), "Tick all that apply. “Nothing yet” is a useful answer too.")}
        ${q("Roughly how much time did it save you?", radios("time_saved", LABELS.timeSaved))}
        <fieldset class="fb-fieldset"><legend>Optional: compare the same task before and with NyayaVedika</legend>
          <p class="hint">Enter minutes only if you can make a reasonable comparison. These times are used in aggregate and are not shown on your public feedback card.</p>
          <div class="grid2">${num("task_minutes_before", "Minutes before using NyayaVedika", "e.g. 45", 600)}
            ${num("task_minutes_with_tool", "Minutes with NyayaVedika", "e.g. 20", 600)}</div>
          ${q("How were these times obtained?", radios("timing_basis", { self_reported: "My estimate", observed: "Timed / observed" }))}
        </fieldset>
        ${q("Would you recommend it to a colleague or neighbour?", radios("would_recommend", LABELS.recommend))}
      </div>
      <div class="fb-step" data-step="4" hidden>
        <h3>In your own words</h3>
        <p class="hint">Submitting publishes your feedback on this page. Your role, rating, answers, optional first name and place, and any headline or comment you provide may be shown. Comparable task times are used only in aggregate and are not shown on your card. We mask obvious phone numbers, email addresses, Aadhaar numbers and case numbers.</p>
        <label>One line that sums it up <span class="hint">(optional, shown on the card)</span>
          <input name="headline" maxlength="120"></label>
        <label>What worked, what did not, what should we fix? <span class="hint">(optional)</span>
          <textarea name="comment" rows="5" maxlength="1000"></textarea></label>
        <p class="hint"><span id="fbCount">0</span>/1000. Please do not write phone numbers, Aadhaar or case numbers. We mask the obvious ones.</p>
      </div>
      <p class="error" id="fbError" role="alert" hidden></p>
      <div class="row between gap fb-nav">
        <button type="button" class="btn ghost" id="fbBack">Back</button>
        <span class="row gap"><button type="button" class="btn ghost" data-close>Cancel</button>
        <button type="button" class="btn" id="fbNext">Next</button></span>
      </div>
    </form>
    <div id="fbThanks" hidden></div>`;
  }

  let step = 1;
  const form = () => $("#fbForm");
  function showStep(n) {
    step = n;
    $$(".fb-step", form()).forEach((s) => { s.hidden = +s.dataset.step !== n; });
    $("#fbBack").style.visibility = n === 1 ? "hidden" : "visible";
    $("#fbNext").textContent = n === STEPS ? "Send feedback" : "Next";
    $("#fbBar").style.width = `${(n / STEPS) * 100}%`;
    $("#fbStepText").textContent = `Step ${n} of ${STEPS} · about ${MINUTES_LEFT[n - 1]} min left`;
    $("#fbError").hidden = true;
    $("#fbFormDialog").scrollTop = 0;
    const first = $(".fb-step:not([hidden]) input, .fb-step:not([hidden]) textarea", form());
    if (first && n > 1) first.focus({ preventScroll: true });
  }
  const val = (name) => (form().elements[name] || {}).value || "";
  const many = (name) => $$(`input[name="${name}"]:checked`, form()).map((e) => e.value);
  const fail = (msg) => { const e = $("#fbError"); e.textContent = msg; e.hidden = false; };

  function validate(n) {
    if (n === 1 && !val("role")) { fail("Please pick who you are, so we can show the right voice."); return false; }
    if (n === 3 && !val("rating")) { fail("Please give an overall star rating."); return false; }
    if (n === 3) {
      const before = val("task_minutes_before"), withTool = val("task_minutes_with_tool");
      if (!!before !== !!withTool) { fail("For a useful comparison, enter both task times or leave both blank."); return false; }
      if (before && !val("timing_basis")) { fail("Please say whether the task times were estimated or observed."); return false; }
    }
    return true;
  }

  function payload() {
    const f = form();
    const n = (k) => (f.elements[k].value === "" ? null : Number(f.elements[k].value));
    return {
      role: val("role"), name: val("name"), place: val("place"), features: many("features"),
      problem_frequency: val("problem_frequency") || null, people_affected: n("people_affected"),
      cost_types: many("cost_types"), days_lost: n("days_lost"), rupees_lost: n("rupees_lost"),
      rating: val("rating"), ease: val("ease") || null, accuracy: val("accuracy") || null,
      outcomes: many("outcomes"), time_saved: val("time_saved") || null, would_recommend: val("would_recommend") || null,
      task_minutes_before: n("task_minutes_before"), task_minutes_with_tool: n("task_minutes_with_tool"),
      timing_basis: val("timing_basis") || null,
      headline: val("headline"), comment: val("comment"),
    };
  }

  async function submit() {
    const btn = $("#fbNext");
    btn.disabled = true; btn.textContent = "Sending…";
    try {
      const res = await api("/api/field-feedback", { json: payload(), noToken: true });
      $("#fbForm").hidden = true; $(".fb-progress").hidden = true; $(".fb-time").hidden = true;
      const t = $("#fbThanks");
      t.hidden = false;
      t.innerHTML = `<h3>Thank you.</h3>
        <p>Your feedback is now on this page.</p>
        <p class="hint">It helps us show what is working and fix what is not.</p>
        <button type="button" class="btn" data-close>Done</button>`;
      document.dispatchEvent(new CustomEvent("feedbackSubmitted"));
      loadWall();
    } catch (e) {
      fail(e.message || "Could not send. Please try again.");
      btn.textContent = "Send feedback";
    } finally {
      btn.disabled = false;
    }
  }

  function openForm() {
    const d = $("#fbFormDialog");
    const thanks = $("#fbThanks");
    if (!form() || (thanks && !thanks.hidden)) { d.innerHTML = `<div class="fb-dialog-body" id="fbFormBody"></div>`; $("#fbFormBody").innerHTML = `<h2 id="fbFormTitle">Share your feedback</h2>` + formHtml(); wireForm(); showStep(1); }
    d.showModal();
  }

  function wireForm() {
    const f = form();
    $("#fbNext").addEventListener("click", () => {
      if (!validate(step)) return;
      step === STEPS ? submit() : showStep(step + 1);
    });
    $("#fbBack").addEventListener("click", () => showStep(step - 1));
    f.addEventListener("submit", (e) => e.preventDefault());
    f.elements.comment.addEventListener("input", () => { $("#fbCount").textContent = f.elements.comment.value.length; });
    // Enter inside a text input should go to the next step, not submit early
    f.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT" && e.target.type !== "checkbox" && e.target.type !== "radio") { e.preventDefault(); $("#fbNext").click(); } });
    f.addEventListener("change", (e) => {
      $("#fbError").hidden = true;
      const g = e.target.closest(".fb-starin");
      if (!g) return;
      const v = +e.target.value;
      $$("label", g).forEach((l, idx) => l.classList.toggle("on", idx < v));
      $(`output[data-for="${g.dataset.stars}"]`, g).textContent = RATING_WORD[v];
    });
  }

  // ------------------------------------------------------------------ events
  $("#fbFilters")?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-role]");
    if (!b) return;
    filter = b.dataset.role; renderFilters(); renderCards();
  });
  wall?.addEventListener("click", (e) => { const c = e.target.closest(".fb-card"); if (c) openDetail(c.dataset.id); });
  $$("[data-open-feedback]").forEach((b) => b.addEventListener("click", openForm));
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) e.target.closest("dialog")?.close();
    else if (e.target.tagName === "DIALOG") e.target.close();          // click on the backdrop
  });
  if (wall) loadWall();
})();
