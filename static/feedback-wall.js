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
  const itemsRoot = $("#wallCards");
  const status = $("#wallStatus");
  let items = [];
  let summary = {};

  const label = (map, key) => map[key] || String(key || "").replace(/_/g, " ");
  const stars = (rating) => {
    const n = Math.max(0, Math.min(5, Number(rating) || 0));
    return `<span class="wall-stars" aria-label="${n} out of 5 stars">${"★".repeat(n)}<span class="wall-star-off">${"★".repeat(5 - n)}</span><b>${n}<span>/5</span></b></span>`;
  };
  const chips = (values, map) => values?.length
    ? `<div class="wall-chips">${values.map((v) => `<span>${esc(label(map, v))}</span>`).join("")}</div>` : "";
  const fact = (title, value) => value !== null && value !== undefined && value !== ""
    ? `<div class="wall-fact"><dt>${esc(title)}</dt><dd>${value}</dd></div>` : "";
  const dateText = (value) => {
    if (!value) return "";
    const date = new Date(`${value}T00:00:00`);
    return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
  };

  function renderStats() {
    const entries = [
      [summary.responses ?? 0, "Responses", "💬"],
      [summary.avg_rating == null ? "—" : `${summary.avg_rating}/5`, "Average rating", "★"],
      [summary.outcome_changed_pct == null ? "—" : `${summary.outcome_changed_pct}%`, "Report a positive change", "↗"],
      [summary.would_recommend_pct == null ? "—" : `${summary.would_recommend_pct}%`, "Would recommend", "♥"],
    ];
    $("#wallStats").innerHTML = entries.map(([value, name, icon]) =>
      `<div class="wall-stat"><span class="wall-stat-icon">${icon}</span><div><b>${esc(value)}</b><span>${esc(name)}</span></div></div>`).join("");
    const timing = summary.task_timing || {};
    const timingNote = $("#wallTiming");
    if (timingNote) {
      timingNote.textContent = timing.paired_responses >= 5 && timing.median_before_minutes != null
        ? `Comparable task-time reports: median ${timing.median_before_minutes} min before and ${timing.median_with_tool_minutes} min with NyayaVedika across ${timing.paired_responses} responses (${timing.self_reported} estimated, ${timing.observed} timed/observed). Voluntary reports; not independently verified.`
        : timing.paired_responses
          ? `There are ${timing.paired_responses} comparable task-time reports. Aggregate times appear once at least 5 responses are available.`
          : "No comparable before-and-with-tool task-time reports yet.";
    }
  }

  function renderRoles() {
    const select = $("#wallRole");
    const current = select.value;
    const counts = {};
    for (const item of items) counts[item.role] = (counts[item.role] || 0) + 1;
    select.innerHTML = `<option value="all">All roles (${items.length})</option>` +
      Object.keys(counts).sort().map((role) => `<option value="${esc(role)}">${esc(label(LABELS.role, role))} (${counts[role]})</option>`).join("");
    if ([...select.options].some((option) => option.value === current)) select.value = current;
  }

  function card(item) {
    const answers = item.answers || {};
    const name = [item.name, item.place].filter(Boolean).map(esc).join(" · ") || "Community member";
    const title = item.headline ? `<h3>${esc(item.headline)}</h3>` : "";
    const comment = item.comment ? `<blockquote>${esc(item.comment)}</blockquote>` :
      `<p class="wall-rating-only">Shared a rating and experience with NyayaVedika.</p>`;
    const features = chips(item.features, LABELS.features);
    const problem = [
      fact("Frequency of the problem", answers.problem_frequency ? esc(label(LABELS.frequency, answers.problem_frequency)) : ""),
      fact("People or cases per month", esc(answers.people_affected)),
      fact("What it costs", chips(answers.cost_types, LABELS.costs)),
      fact("Days lost", esc(answers.days_lost)),
      fact("Money lost", answers.rupees_lost == null ? "" : `₹${esc(Number(answers.rupees_lost).toLocaleString("en-IN"))}`),
    ].join("");
    const experience = [
      fact("Ease of use", answers.ease ? stars(answers.ease) : ""),
      fact("Answer quality", answers.accuracy ? esc(label(LABELS.accuracy, answers.accuracy)) : ""),
      fact("What changed", chips(answers.outcomes, LABELS.outcomes)),
      fact("Time saved", answers.time_saved ? esc(label(LABELS.timeSaved, answers.time_saved)) : ""),
      fact("Would recommend", item.would_recommend ? esc(label(LABELS.recommend, item.would_recommend)) : ""),
    ].join("");
    const detail = [
      features ? `<div class="wall-detail-group"><h4>What they used</h4>${features}</div>` : "",
      problem ? `<div class="wall-detail-group"><h4>The problem</h4><dl>${problem}</dl></div>` : "",
      experience ? `<div class="wall-detail-group"><h4>The experience</h4><dl>${experience}</dl></div>` : "",
    ].join("");
    const role = label(LABELS.role, item.role);
    const searchable = [role, item.name, item.place, item.headline, item.comment, ...(item.features || [])].join(" ").toLowerCase();
    return `<article class="wall-card" data-role="${esc(item.role)}" data-rating="${Number(item.rating) || 0}" data-search="${esc(searchable)}">
      <div class="wall-card-top"><span class="wall-role">${esc(role)}</span>${stars(item.rating)}</div>
      ${title}${comment}
      <div class="wall-card-bottom"><span class="wall-byline"><b>${name}</b>${item.created_at ? `<time datetime="${esc(item.created_at)}">${esc(dateText(item.created_at))}</time>` : ""}</span></div>
      ${detail ? `<details class="wall-details"><summary>More about their experience <span aria-hidden="true">＋</span></summary>${detail}</details>` : ""}
    </article>`;
  }

  function renderCards() {
    const term = $("#wallSearch").value.trim().toLowerCase();
    const role = $("#wallRole").value;
    const sort = $("#wallSort").value;
    const visible = items.filter((item) => {
      const text = [label(LABELS.role, item.role), item.name, item.place, item.headline, item.comment,
        ...(item.features || []), ...Object.values(item.answers || {})].flat().join(" ").toLowerCase();
      return (role === "all" || item.role === role) && (!term || text.includes(term));
    });
    if (sort === "rating") visible.sort((a, b) => Number(b.rating) - Number(a.rating));
    $("#wallCount").textContent = `Showing ${visible.length} of ${items.length} ${items.length === 1 ? "response" : "responses"}`;
    if (!items.length) {
      itemsRoot.innerHTML = "";
      status.className = "wall-status wall-empty";
      status.innerHTML = "<b>No feedback published yet.</b><span>New community responses will appear here.</span>";
      status.hidden = false;
      return;
    }
    if (!visible.length) {
      itemsRoot.innerHTML = "";
      status.className = "wall-status wall-empty";
      status.innerHTML = "<b>No matching feedback</b><span>Try another search or role filter.</span>";
      status.hidden = false;
      return;
    }
    status.hidden = true;
    itemsRoot.innerHTML = visible.map(card).join("");
  }

  async function load() {
    const refresh = $("#wallRefresh");
    refresh.disabled = true;
    refresh.textContent = "Loading…";
    status.className = "wall-status";
    status.textContent = "Loading the latest community feedback…";
    status.hidden = false;
    try {
      const data = await api("/api/field-feedback/all", { noToken: true });
      items = Array.isArray(data.items) ? data.items : [];
      summary = data.summary || {};
      renderStats();
      renderRoles();
      renderCards();
    } catch (error) {
      status.className = "wall-status wall-error";
      status.innerHTML = `<b>We couldn’t load the feedback just now.</b><span>${esc(error.message || "Please try again.")}</span>`;
      status.hidden = false;
    } finally {
      refresh.disabled = false;
      refresh.textContent = "↻ Refresh";
    }
  }

  $("#wallSearch").addEventListener("input", renderCards);
  $("#wallRole").addEventListener("change", renderCards);
  $("#wallSort").addEventListener("change", renderCards);
  $("#wallRefresh").addEventListener("click", load);
  document.addEventListener("feedbackSubmitted", load);
  load();
})();
