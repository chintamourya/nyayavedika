// Impact report: the shareable evidence form. Choices come from GET /api/impact-reports/options so the form and the
// server-side checks (nyayavedika/impact_reports.py) never drift. ?role=advocate (etc.) preselects the role.
const form = $("#reportForm");
let OPT = null;

function choiceList(container, name, items, type) {
  container.insertAdjacentHTML("beforeend", items.map((o) =>
    `<label class="choice"><input type="${type}" name="${esc(name)}" value="${esc(o.value)}"> <span>${esc(o.label)}</span></label>`).join(""));
}
function scale(container) {
  const name = container.dataset.scale;
  const words = ["", "Not at all", "A little", "Somewhat", "Very", "Extremely"];
  container.insertAdjacentHTML("beforeend", `<div class="scale-row">${[1, 2, 3, 4, 5].map((n) =>
    `<label title="${words[n]}"><input type="radio" name="${name}" value="${n}"><span>${n}</span></label>`).join("")}</div>
    <div class="scale-ends"><span>${words[1]}</span><span>${words[5]}</span></div>`);
}
function role() { return $("input[name=role]:checked", form)?.value || ""; }
function showRoleFields() {
  const r = role(), pro = OPT?.professional_roles.includes(r);
  $$("#identityFields [data-for]").forEach((el) => {
    const who = el.dataset.for.split(" ");
    el.classList.toggle("hidden", !r || !(who.includes("all") || who.includes(r)));
  });
  $$(".pro-only").forEach((el) => el.classList.toggle("hidden", !pro));
  $("#identityFields").classList.toggle("hidden", !r);
}
function savedLine() {
  const a = Number(form.minutes_without.value), b = Number(form.minutes_with.value), out = $("#savedLine");
  if (a > 0 && b > 0) {
    const d = a - b;
    out.textContent = d > 0 ? `That is ${d} minute(s) saved on this task (${Math.round((100 * d) / a)}% less time).`
      : d < 0 ? "It took longer with NyayaVedika - please say so; that is useful evidence too." : "About the same time.";
    out.classList.remove("hidden");
  } else out.classList.add("hidden");
}

async function init() {
  try {
    OPT = await api("/api/impact-reports/options", { noToken: true });
  } catch (e) {
    $("#formError").textContent = `The form could not load: ${e.message}. Please reload the page.`;
    $("#formError").classList.remove("hidden");
    return;
  }
  choiceList($("#roleChoices"), "role", OPT.roles, "radio");
  choiceList($("#featureChoices"), "features", OPT.features, "checkbox");
  choiceList($("#usedOnChoices"), "used_on", OPT.used_on, "radio");
  choiceList($("#outcomeChoices"), "outcomes", OPT.outcomes, "checkbox");
  choiceList($("#accuracyChoices"), "accuracy", OPT.accuracy, "radio");
  choiceList($("#quoteChoices"), "quote_permission", OPT.quote, "radio");
  $("#taskSelect").insertAdjacentHTML("beforeend", OPT.tasks.map((t) => `<option value="${esc(t.value)}">${esc(t.label)}</option>`).join(""));
  $$(".rating").forEach(scale);
  form.enrolment_year.max = OPT.this_year;
  form.used_from.max = new Date().toISOString().slice(0, 10);
  const wanted = new URLSearchParams(location.search).get("role");
  const pre = wanted && $(`input[name=role][value="${CSS.escape(wanted)}"]`, form);
  if (pre) pre.checked = true;
  $$("input[name=role]", form).forEach((r) => r.addEventListener("change", showRoleFields));
  $$("input[name=accuracy]", form).forEach((r) => r.addEventListener("change", () =>
    $("#errorsWrap").classList.toggle("hidden", !["minor_errors", "major_errors"].includes(r.value) || !r.checked)));
  form.minutes_without.addEventListener("input", savedLine);
  form.minutes_with.addEventListener("input", savedLine);
  showRoleFields();
}

function payload() {
  const f = form, val = (n) => (f[n]?.value || "").trim();
  const checked = (n) => $$(`input[name=${n}]:checked`, f).map((x) => x.value);
  const one = (n) => checked(n)[0] || "";
  const out = { role: role(), features: checked("features"), outcomes: checked("outcomes"), used_on: one("used_on"),
    timing_basis: one("timing_basis"), accuracy: one("accuracy"), would_continue: one("would_continue"),
    quote_permission: one("quote_permission") || "no", usefulness: one("usefulness"), ease: one("ease"), trust: one("trust"),
    consent_store: f.consent_store.checked, consent_contact: f.consent_contact.checked };
  ["full_name", "email", "enrolment_number", "enrolment_year", "law_school", "practice_court",
    "legal_services_authority", "designation", "work_experience", "district", "state", "profile_url", "times_used", "used_from",
    "task", "minutes_without", "minutes_with", "documents_handled", "pages_handled", "cases_handled", "errors_found",
    "outcome_detail", "testimonial", "website"].forEach((n) => {
    const field = f[n], wrap = field?.closest("[data-for]");
    if (field && !(wrap && wrap.classList.contains("hidden"))) out[n] = val(n);   // hidden role fields are not sent
  });
  return out;
}
function quickCheck(p) {   // the server checks everything again; this only catches the common gaps early
  if (!p.role) return "Please choose your role.";
  if (OPT.professional_roles.includes(p.role) && (!p.full_name || !p.email)) return "Please give your full name and email.";
  if (!p.features.length) return "Please choose at least one part of NyayaVedika you used.";
  if (!p.used_on) return "Please say what you used it on.";
  if (!p.outcomes.length) return "Please choose at least one outcome (or 'No outcome yet').";
  if (!p.usefulness) return "Please rate how useful it was.";
  if (!p.consent_store) return "Please agree to the storage of this report.";
  return "";
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const btn = $("#submitReport"), err = $("#formError");
  const p = payload(), problem = quickCheck(p);
  err.classList.add("hidden");
  if (problem) { err.textContent = problem; err.classList.remove("hidden"); err.scrollIntoView({ behavior: "smooth", block: "center" }); return; }
  btn.disabled = true; btn.textContent = "Sending…";
  api("/api/impact-reports", { json: p, noToken: true }).then((out) => {
    form.classList.add("hidden");
    $("#thanksText").textContent = out.message;
    $("#thanksRef").textContent = `IR-${out.id}`;
    $("#thanks").classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }).catch((x) => {
    err.textContent = x.message; err.classList.remove("hidden");
    err.scrollIntoView({ behavior: "smooth", block: "center" });
  }).finally(() => { btn.disabled = false; btn.textContent = "Submit report"; });
});
$("#another").addEventListener("click", () => {
  form.reset(); showRoleFields(); savedLine();
  $("#thanks").classList.add("hidden"); form.classList.remove("hidden"); window.scrollTo({ top: 0 });
});
init();
