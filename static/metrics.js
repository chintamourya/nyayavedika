(() => {
  const number = (value) => Number(value || 0).toLocaleString();
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const card = (value, label, note = "") => `<article class="metric-card"><b>${esc(value)}</b><span>${esc(label)}</span>${note ? `<small>${esc(note)}</small>` : ""}</article>`;

  function showCards(root, rows) {
    root.innerHTML = rows.join("");
  }

  async function loadMetrics() {
    const status = $("#metricsStatus");
    const content = $("#metricsContent");
    status.textContent = "Loading live metrics…";
    try {
      const m = await api("/api/demo/metrics", { noToken: true });
      const reachByDoor = m.reach.by_door || {};
      const visits = m.door_visits.by_door || {};
      const usage = m.api_usage;
      const features = Object.entries(usage.by_feature || {});
      const doors = ["citizen", "advocate", "staff"];
      const products = [
        ["citizen_sessions", "Citizen sessions"],
        ["legal_aid_checks", "Legal-aid checks"],
        ["legal_aid_applications_drafted", "Applications drafted"],
        ["documents_analyzed", "Documents analyzed"],
        ["undertrials_flagged", "Undertrials flagged"],
        ["release_applications_approved", "Release applications approved"],
        ["cases_triaged", "Cases triaged"],
        ["cause_lists_published", "Cause lists published"],
        ["cases_listed", "Cases listed"],
      ];
      const feedback = m.feedback;
      showCards($("#reachCards"), [
        card(number(m.reach.unique_browsers), "Distinct browsers"),
        card(number(m.reach.public_browsers), "Public-site browsers"),
        ...["citizen", "advocate", "staff"].map((door) =>
          card(number(reachByDoor[door]), `${door[0].toUpperCase()}${door.slice(1)} distinct browsers`)),
        card(number(m.door_visits.total), "Total portal visits", "Repeat visits count again"),
        ...["citizen", "advocate", "staff"].map((door) =>
          card(number(visits[door]), `${door[0].toUpperCase()}${door.slice(1)} door visits`, `${number(reachByDoor[door])} distinct browsers`)),
      ]);
      showCards($("#featureCards"), [
        card(number(usage.total.requests), "API requests", `${number(usage.total.unique_browsers)} distinct browsers · ${number(usage.total.successful)} successful · ${number(usage.total.failed)} failed`),
        card(usage.total.avg_server_ms == null ? "—" : `${number(usage.total.avg_server_ms)} ms`, "Average server response"),
        ...features.map(([name, row]) => card(number(row.requests), name.replace(/_/g, " "), `${number(row.unique_browsers)} distinct browsers · ${number(row.successful)} successful · ${number(row.failed)} failed · ${row.avg_server_ms ?? "—"} ms avg`)),
      ]);
      $("#doorTools").innerHTML = doors.map((door) => {
        const stats = usage.by_door?.[door] || { requests: 0, successful: 0, failed: 0, unique_browsers: 0, avg_server_ms: null, features: {} };
        const tools = Object.entries(stats.features || {});
        const title = `${door[0].toUpperCase()}${door.slice(1)} door`;
        const toolCards = tools.length
          ? tools.map(([name, row]) => card(number(row.requests), name.replace(/_/g, " "),
            `${number(row.unique_browsers)} distinct browsers · ${number(row.successful)} successful · ${number(row.failed)} failed · ${row.avg_server_ms ?? "—"} ms avg`)).join("")
          : `<p class="hint">No recorded API tool usage for this door yet.</p>`;
        return `<section class="metrics-door" aria-label="${esc(title)}">
          <h3>${esc(title)} · ${number(visits[door])} visits</h3>
          <div class="metrics-grid">
            ${card(number(stats.requests), "All tool requests in this door", `${number(stats.unique_browsers)} distinct browsers · ${number(stats.successful)} successful · ${number(stats.failed)} failed`)}
            ${card(stats.avg_server_ms == null ? "—" : `${number(stats.avg_server_ms)} ms`, "Average server response")}
          </div>
          <div class="metrics-grid">${toolCards}</div>
        </section>`;
      }).join("");
      showCards($("#productCards"), products.map(([key, label]) => card(number(m.product[key]), label)));
      showCards($("#feedbackCards"), [
        card(number(feedback.responses), "Feedback responses", "Voluntary responses"),
        card(feedback.avg_rating == null ? "—" : `${feedback.avg_rating}/5`, "Average rating"),
        card(feedback.outcome_changed_pct == null ? "—" : `${feedback.outcome_changed_pct}%`, "Report a change", "Self-reported"),
        card(feedback.would_recommend_pct == null ? "—" : `${feedback.would_recommend_pct}%`, "Would recommend", "Self-reported"),
      ]);
      $("#metricsDisclaimer").textContent =
        "Aggregated activity. Distinct-browser counts use a random persistent browser identifier. Activity records do not include names, contact details, IP addresses, request text, or uploaded-document contents. Feedback outcomes are voluntary self-reports.";
      content.hidden = false;
      status.textContent = "";
      $("#metricsUpdated").textContent = `Last updated ${new Date().toLocaleString()}`;
    } catch (error) {
      content.hidden = true;
      status.textContent = `Metrics could not be loaded: ${error.message}`;
    }
  }

  $("#metricsRefresh").addEventListener("click", loadMetrics);
  loadMetrics();
})();
