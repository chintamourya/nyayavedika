// Citizen portal: language picker (en/hi/te string table), the 5-question eligibility check with its explanation,
// the application draft and the Word download. No login: the server treats
// a request without a token as an anonymous citizen (demo mode).
demoBanner();
const LANG_NAMES = { en: "English", hi: "Hindi", te: "Telugu" };
const FOLLOWUP_LIMIT = 5, ATTACHMENT_LIMIT = 2;
const FOLLOWUP_SESSION_KEY = "nyayavedika_legal_aid_followup_session";
const FOLLOWUP_COUNT_KEY = "nyayavedika_legal_aid_followup_count";
let STR = {}, lang = "en";
const t = (k) => STR[lang]?.[k] ?? STR.en?.[k] ?? k;
try { lang = localStorage.getItem("nyayavedika_lang") || "en"; } catch { /* default */ }
function newFollowupSessionId() {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
function sessionValue(key) {
  try { return sessionStorage.getItem(key); } catch { return null; }
}
function saveSessionValue(key, value) {
  try { sessionStorage.setItem(key, value); } catch { /* the current tab still tracks its in-memory state */ }
}
let questionSession = sessionValue(FOLLOWUP_SESSION_KEY) || newFollowupSessionId();
let followupsUsed = Math.min(FOLLOWUP_LIMIT, Math.max(0, Number(sessionValue(FOLLOWUP_COUNT_KEY)) || 0));
saveSessionValue(FOLLOWUP_SESSION_KEY, questionSession);

function applyLang() {
  document.documentElement.lang = lang;
  $$("[data-t]").forEach((el) => { el.textContent = t(el.dataset.t); });
  $$("[data-tp]").forEach((el) => { el.placeholder = t(el.dataset.tp); });
  $$("[data-ta]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.ta)); el.title = t(el.dataset.ta); });
  $$(".langs button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
  renderGuideQuestions();
  renderFollowupStatus();
  if (typeof problemChat !== "undefined" && problemChat.length === 0) renderProblemGreeting();
}
$$(".langs button").forEach((b) => b.addEventListener("click", () => {
  lang = b.dataset.lang; try { localStorage.setItem("nyayavedika_lang", lang); } catch { /* ok */ }
  applyLang();
}));
const guide = $("#guide");
let lastSummarisedDocument = null;   // the file just summarised: NOT sent anywhere until the person chooses to use it
let attachedSummaryDocument = null;  // set only by the "Use this document for a legal-aid question" button

function renderFollowupStatus() {
  $("#followupCount").textContent = t("followup_count").replace("{used}", followupsUsed).replace("{limit}", FOLLOWUP_LIMIT);
  $("#legalQuestion").disabled = followupsUsed >= FOLLOWUP_LIMIT;
  $("#followupRestriction").classList.toggle("hidden", followupsUsed < FOLLOWUP_LIMIT);
  $("#startNewLegalAidSession").classList.toggle("hidden", followupsUsed < FOLLOWUP_LIMIT);
}
function setFollowupsUsed(count) {
  followupsUsed = Math.min(FOLLOWUP_LIMIT, Math.max(0, Number(count) || 0));
  saveSessionValue(FOLLOWUP_COUNT_KEY, String(followupsUsed));
  renderFollowupStatus();
}
function setLegalAidError(message) {
  const box = $("#legalAidError");
  box.textContent = message || "";
  box.classList.toggle("hidden", !message);
}
function setSummaryError(message) {
  const box = $("#citizenSummaryError");
  box.textContent = message || "";
  box.classList.toggle("hidden", !message);
}
function renderAttachedNote() {
  const note = $("#attachedSummaryNote");
  note.textContent = "";
  note.classList.toggle("hidden", !attachedSummaryDocument);
  if (!attachedSummaryDocument) return;
  note.append(t("attached_summary_note").replace("{name}", attachedSummaryDocument.name || attachedSummaryDocument.filename) + " ");
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "btn ghost small";
  remove.textContent = t("remove_attachment");
  remove.addEventListener("click", () => { attachedSummaryDocument = null; updateLegalDocumentCount(); });
  note.append(remove);
}
function updateLegalDocumentCount() {
  const files = [...$("#legalDocuments").files];
  if (attachedSummaryDocument && !files.includes(attachedSummaryDocument)) files.push(attachedSummaryDocument);
  $("#legalDocumentCount").textContent = t("document_count").replace("{count}", files.length).replace("{limit}", ATTACHMENT_LIMIT);
  renderAttachedNote();
  const invalidType = files.some((file) => !/\.(pdf|txt)$/i.test(file.name));
  const empty = files.some((file) => !(file.size ?? file.text?.length));
  if (files.length > ATTACHMENT_LIMIT) setLegalAidError(t("document_limit_reason"));
  else if (invalidType) setLegalAidError(t("bad_document_name"));
  else if (empty) setLegalAidError(t("empty_document"));
  else setLegalAidError("");
}
$("#legalDocuments").addEventListener("change", updateLegalDocumentCount);
$("#legalQuestion").addEventListener("input", () => setLegalAidError(""));
$("#startNewLegalAidSession").addEventListener("click", () => {
  questionSession = newFollowupSessionId();
  saveSessionValue(FOLLOWUP_SESSION_KEY, questionSession);
  saveSessionValue(FOLLOWUP_COUNT_KEY, "0");
  setFollowupsUsed(0);
  $("#legalQuestion").value = "";
  attachedSummaryDocument = null;
  updateLegalDocumentCount();
  setLegalAidError("");
  toast("A new legal-aid question session is ready.");
});

function showCitizenTab(name) {
  $$(".citizen-tabs [data-citizen-tab]").forEach((button) => {
    const active = button.dataset.citizenTab === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  const panelId = { summary: "citizen-summary", problem: "citizen-problem", rights: "citizen-rights" }[name] || "chat";
  $$(".citizen-panel").forEach((panel) => panel.classList.toggle("hidden", panel.id !== panelId));
  if (name === "rights") loadRights();
}

// ---------------------------------------------------------------- Know your rights (legal_info.html entries)
let RIGHTS = null;
function safeLink(href) {
  try { const u = new URL(href); return ["http:", "https:"].includes(u.protocol) ? u.href : ""; } catch { return ""; }
}
function rightsCard(topic, open) {
  const sources = topic.sources.map((s) => {
    const href = safeLink(s.url);
    const host = href ? new URL(href).hostname.replace(/^www\./, "") : "source";
    return `<li>${href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(host)}</a>` : esc(host)}` +
      `${s.note ? ` - ${esc(s.note)}` : ""}${s.checked ? ` <span class="hint">(checked ${esc(s.checked)})</span>` : ""}</li>`;
  }).join("");
  return `<details class="right"${open ? " open" : ""} id="right-${esc(topic.id)}"><summary>${esc(topic.title)}` +
    `${topic.authority === "primary" ? ' <span class="badge ok">official</span>' : ""}</summary>` +
    `<ul>${topic.facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>` +
    `${topic.meta.map((m) => `<p class="hint">${esc(m)}</p>`).join("")}` +
    `<details class="src"><summary>${esc(t("rights_sources"))} (${topic.sources.length})</summary><ul>${sources}</ul></details></details>`;
}
function renderRights() {
  if (!RIGHTS) return;
  const q = ($("#rightsSearch").value || "").trim().toLowerCase();
  const words = q.split(/\s+/).filter(Boolean);
  // short words (FIR, RTI) must match a whole word, so "fir" does not find "first"; longer ones may match a word start
  const norm = (s) => " " + s.replace(/[^a-z0-9ऀ-෿]+/g, " ").trim() + " ";
  const startsWord = (hay, w) => { const k = norm(w).trimEnd(); return norm(hay).includes(k.length <= 4 ? k + " " : k); };
  const hits = RIGHTS.topics.filter((tp) => {
    const hay = [tp.title, ...tp.facts, ...tp.meta].join(" ").toLowerCase();
    return words.every((w) => startsWord(hay, w));
  });
  $("#rightsMeta").textContent = `${hits.length} / ${RIGHTS.count}` + (RIGHTS.checked ? ` · checked ${RIGHTS.checked}` : "") +
    ` · ${t("rights_note")}`;
  $("#rightsList").innerHTML = hits.map((tp) => rightsCard(tp, words.length > 0 && hits.length <= 3)).join("") ||
    `<p class="hint">${esc(t("rights_empty"))}</p>`;
}
async function loadRights() {
  if (RIGHTS) return renderRights();
  $("#rightsMeta").textContent = "Loading...";
  try {
    RIGHTS = await api("/api/legal-aid/topics", { noToken: true });
    renderRights();
  } catch (err) {
    $("#rightsMeta").textContent = `Could not load topics: ${err.message || err}`;
  }
}
$("#rightsSearch")?.addEventListener("input", renderRights);
$$(".citizen-tabs [data-citizen-tab]").forEach((button) => {
  button.addEventListener("click", () => showCitizenTab(button.dataset.citizenTab));
});

const RESEARCH_SECTIONS = [
  ["laws_and_provisions", "problem_laws"],
  ["rights_and_protections", "problem_rights"],
  ["possible_remedies", "problem_remedies"],
  ["authorities", "problem_authorities"],
  ["free_legal_aid", "problem_free_aid"],
  ["next_steps", "problem_next_steps"],
  ["limitations", "problem_limitations"],
  ["conflicts", "problem_conflicts"],
];
function officialResearchUrl(raw) {
  try {
    const url = new URL(raw);
    const host = url.hostname.toLowerCase().replace(/\.$/, "");
    const official = host === "gov.in" || host.endsWith(".gov.in") || host === "nic.in" ||
      host.endsWith(".nic.in") || host.endsWith(".gov") || host.endsWith(".nalsa.gov.in");
    return url.protocol === "https:" && official ? url.href : "";
  } catch { return ""; }
}
function renderResearchPoints(points, heading, prefix = "") {
  if (!points?.length) return "";
  return `<section class="research-section"><h3>${esc(t(heading))}</h3><ul>${points.map((point) =>
    `<li>${point.basis === "inference" ? `<span class="badge">${esc(t("problem_inference"))}</span> ` : ""}` +
    `${esc(point.text)} ${point.source_ids.map((id) =>
      `<a class="source-citation" href="#problem-source-${prefix}${Number(id)}">[${Number(id)}]</a>`).join(" ")}</li>`
  ).join("")}</ul></section>`;
}
function researchHtml(result, prefix = "") {
  if (result.no_reliable_sources) {
    return `<p class="banner-warn">${esc(result.message || t("problem_no_sources"))}</p>`;
  }
  const understanding = result.understanding || {};
  const sections = RESEARCH_SECTIONS.map(([key, label]) => renderResearchPoints(result.answer?.[key], label, prefix)).join("");
  const sources = (result.sources || []).map((source) => {
    const id = Number(source.id);
    const href = officialResearchUrl(source.url);
    if (!Number.isInteger(id) || id < 1 || !href) return "";
    return `<li id="problem-source-${prefix}${id}"><b>[${id}] ${esc(source.title)}</b> ` +
      `<span class="hint">${esc(source.organization)} · ${esc(t("problem_queries_used"))}: ${esc((source.query_ids || []).join(", "))}</span>` +
      `<p>${esc(source.excerpt)}</p><a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(href)}</a></li>`;
  }).join("");
  const listSection = (items, label) => items?.length
    ? `<h3>${esc(t(label))}</h3><ul>${items.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : "";
  return `<p><b>${esc(t("problem_understanding"))}:</b> ${esc(result.answer?.understanding || t("problem_no_summary"))}</p>` +
    `${understanding.legal_question ? `<p><b>${esc(t("problem_legal_question"))}:</b> ${esc(understanding.legal_question)}</p>` : ""}` +
    `<p class="hint">${esc(understanding.category || "")}${understanding.jurisdiction ? ` · ${esc(understanding.jurisdiction)}` : ""}` +
    `${result.retrieved_on ? ` · ${esc(t("problem_retrieved"))}: ${esc(result.retrieved_on)}` : ""}</p>` +
    `${listSection(understanding.facts, "problem_key_facts")}` +
    `${listSection(understanding.parties, "problem_parties")}` +
    `${listSection(understanding.events, "problem_events")}` +
    `${listSection(understanding.dates, "problem_dates")}` +
    `${sections || `<p class="banner-warn">${esc(t("problem_no_grounded_points"))}</p>`}` +
    `<p class="hint">${esc(result.answer?.grounding_note || t("problem_grounding_note"))}</p>` +
    `<section class="research-section"><h3>${esc(t("problem_sources"))}</h3><ol>${sources || `<li>${esc(t("problem_no_sources"))}</li>`}</ol></section>`;
}

// ---------------------------------------------------------------- Describe a legal problem: conversational chat
// The server decides each turn (ask one question / reply / research). Research answers are still built only from
// retrieved official sources. History is kept in memory only; nothing is stored.
let problemChat = [];          // [{role, content, kind}] sent with every turn
let problemAnswerCount = 0;    // gives each answer's source anchors a unique prefix
let problemBusy = false;
const PROBLEM_MAX_TURNS = 5, PROBLEM_MAX_FOLLOWUPS = 2;   // session-only memory: last 5 turns; 2 follow-ups after an answer
function problemFollowupsUsed() {
  const first = problemChat.findIndex((m) => m.kind === "answer");
  return first < 0 ? 0 : problemChat.slice(first + 1).filter((m) => m.role === "user").length;
}
function problemLimitReached() {
  return problemChat.filter((m) => m.role === "user").length >= PROBLEM_MAX_TURNS ||
    problemFollowupsUsed() >= PROBLEM_MAX_FOLLOWUPS;
}
function lockProblemInputIfNeeded() {
  const locked = problemLimitReached();
  $("#problemChatInput").disabled = $("#problemChatSend").disabled = locked;
  if (locked) addProblemBubble("bot", t("problem_chat_limit"), { extra: "limit" });
}
const problemLog = () => $("#problemChatLog");
function scrollProblemLog() { const log = problemLog(); log.scrollTop = log.scrollHeight; }
function addProblemBubble(kind, content, { html = false, extra = "" } = {}) {
  const div = document.createElement("div");
  div.className = `msg ${kind}${extra ? ` ${extra}` : ""}`;
  const sender = document.createElement("span");
  sender.className = "msg-sender";
  sender.textContent = kind === "user" ? t("problem_chat_you") : t("title");
  const body = document.createElement("div");
  body.className = "msg-content";
  if (html) body.innerHTML = content; else body.textContent = content;
  div.append(sender, body);
  problemLog().appendChild(div);
  scrollProblemLog();
  return div;
}
function createProblemProgress(pending) {
  pending.setAttribute("role", "status");
  pending.setAttribute("aria-live", "polite");
  const body = $(".msg-content", pending);
  body.replaceChildren();

  const spinner = document.createElement("span");
  spinner.className = "problem-chat-spinner";
  spinner.setAttribute("aria-hidden", "true");
  const copy = document.createElement("div");
  copy.className = "problem-chat-progress-copy";
  const heading = document.createElement("strong");
  heading.textContent = t("problem_chat_working");
  const detail = document.createElement("p");
  detail.textContent = t("problem_chat_progress");
  const elapsed = document.createElement("small");
  elapsed.className = "problem-chat-elapsed";
  elapsed.setAttribute("aria-hidden", "true");
  copy.append(heading, detail, elapsed);
  body.append(spinner, copy);

  const startedAt = Date.now();
  const updateElapsed = () => {
    const seconds = Math.floor((Date.now() - startedAt) / 1000);
    elapsed.textContent = t("problem_chat_elapsed")
      .replace("{time}", `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`);
  };
  updateElapsed();
  const interval = setInterval(updateElapsed, 1000);
  const delay = setTimeout(() => { detail.textContent = t("problem_chat_still_working"); }, 8000);
  return () => {
    clearInterval(interval);
    clearTimeout(delay);
  };
}
function renderProblemGreeting() {
  problemLog().replaceChildren();
  $("#problemChatChips").replaceChildren();
  addProblemBubble("bot", t("problem_chat_greeting"), { extra: "greeting" });
}
function setProblemChips(suggestions) {
  const box = $("#problemChatChips");
  box.replaceChildren();
  (suggestions || []).forEach((text) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "btn ghost small";
    chip.textContent = text;
    chip.addEventListener("click", () => sendProblemMessage(text));
    box.appendChild(chip);
  });
}
function setProblemError(message) {
  const error = $("#problemResearchError");
  error.textContent = message || "";
  error.classList.toggle("hidden", !message);
}
function historyTextFor(reply) {
  if (reply.type === "answer") {
    const result = reply.result || {};
    return result.answer?.understanding || result.understanding?.legal_question || result.message || "A summary of official sources was shown.";
  }
  return reply.reply || "";
}
async function sendProblemMessage(text) {
  text = (text || "").trim();
  if (!text || problemBusy) return;
  problemBusy = true;
  setProblemError("");
  setProblemChips([]);
  const input = $("#problemChatInput"), send = $("#problemChatSend");
  addProblemBubble("user", text);
  problemChat.push({ role: "user", content: text, kind: "" });
  input.value = "";
  input.disabled = send.disabled = true;
  send.textContent = t("problem_chat_sending");
  const pending = addProblemBubble("bot", "", { extra: "pending" });
  const clearProgress = createProblemProgress(pending);
  try {
    const reply = await api("/api/legal-problem/chat", {
      method: "POST",
      noToken: true,
      json: { messages: problemChat, language: LANG_NAMES[lang] },
    });
    clearProgress();
    pending.remove();
    if (reply.type === "answer") {
      problemAnswerCount += 1;
      let html = researchHtml(reply.result || {}, `${problemAnswerCount}-`);
      if (reply.followups?.length) {
        html += `<p class="hint">${esc(t("problem_chat_followups"))}</p><ul>${reply.followups.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`;
      }
      addProblemBubble("bot", html, { html: true, extra: "answer" });
    } else {
      addProblemBubble("bot", reply.reply || "");
      setProblemChips(reply.suggestions);
    }
    problemChat.push({ role: "assistant", content: historyTextFor(reply), kind: reply.type === "ask" ? "ask" : reply.type === "answer" ? "answer" : "" });
    problemChat = problemChat.slice(-PROBLEM_MAX_TURNS * 2);   // never keep more than the last 5 turns in memory
  } catch (err) {
    clearProgress();
    pending.remove();
    problemLog().lastElementChild?.remove();     // take back the unanswered message so a retry does not duplicate it
    problemChat.pop();
    input.value = text;
    setProblemError(err.message || t("problem_request_failed"));
  } finally {
    problemBusy = false;
    send.textContent = t("problem_chat_send");
    input.disabled = send.disabled = false;
    lockProblemInputIfNeeded();
    if (!input.disabled) input.focus();
  }
}
$("#problemChatForm").addEventListener("submit", (event) => {
  event.preventDefault();
  sendProblemMessage($("#problemChatInput").value);
});
$("#problemChatInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $("#problemChatForm").requestSubmit();
  }
});
$("#problemChatReset").addEventListener("click", () => {
  if (problemBusy) return;
  problemChat = [];
  problemAnswerCount = 0;
  setProblemError("");
  $("#problemChatInput").disabled = $("#problemChatSend").disabled = false;
  renderProblemGreeting();
});

function sourceMarkup(source) {
  const references = source.references || [source.n];
  let link = "";
  if (source.source_url) {
    try {
      const url = new URL(source.source_url);
      if (["http:", "https:"].includes(url.protocol)) link = ` · <a href="${esc(url.href)}" target="_blank" rel="noopener">${esc(url.href)}</a>`;
    } catch { /* show a non-URL source label without making it clickable */ }
  }
  return `<li>[${references.map(esc).join(", ")}] ${esc(source.heading || "Source")} (${esc(source.authority || "source")})${source.last_verified ? ` · checked ${esc(source.last_verified)}` : ""}${link}</li>`;
}

async function downloadDocx(prefill) {
  const name = await downloadFrom("/api/legal-aid/application.docx", { json: prefill, noToken: true }, "legal_aid_application.docx");
  toast(`Downloaded ${name}`);
}

// ---------------------------------------------------------------- 5-question guide
const QS = ["in_custody", "woman", "sc_st", "disability"];
function renderGuideQuestions() {
  $$("#guideForm fieldset.q").slice(0, 4).forEach((fs, i) => {
    const key = QS[i];
    const prev = $(`input[name=${key}]:checked`, fs)?.value || "";
    fs.innerHTML = `<legend>${esc(t(["q_custody", "q_woman", "q_scst", "q_disability"][i]))}</legend>` +
      [["yes", t("yes")], ["no", t("no")], ["", t("unknown")]].map(([v, l]) =>
        `<label><input type="radio" name="${key}" value="${v}" ${prev === v ? "checked" : ""}> ${esc(l)}</label>`).join("");
  });
}
function guideApplicant() {
  const a = {};
  QS.forEach((k) => { const v = $(`input[name=${k}]:checked`)?.value; if (v) a[k] = v === "yes"; });
  const inc = $("#income").value; if (inc !== "") a.annual_income = Number(inc);
  return a;
}
$("#guideForm").addEventListener("submit", (e) => {
  e.preventDefault();
  busy(e.submitter, async () => {
    setLegalAidError("");
    const applicant = guideApplicant(), district = $("#district").value.trim(), state = $("#state").value;
    const prefill = { applicant, district, state, language: LANG_NAMES[lang] };
    const question = $("#legalQuestion").value.trim();
    const selectedFiles = [...$("#legalDocuments").files];
    if (attachedSummaryDocument && !selectedFiles.includes(attachedSummaryDocument)) selectedFiles.push(attachedSummaryDocument);
    if (question && followupsUsed >= FOLLOWUP_LIMIT) {
      const message = t("followup_limit_reason");
      setLegalAidError(message);
      throw new Error(message);
    }
    if (selectedFiles.length > ATTACHMENT_LIMIT) {
      const message = t("document_limit_reason");
      setLegalAidError(message);
      throw new Error(message);
    }
    if (selectedFiles.length && !question) {
      const message = "Add a question to use the attached document(s).";
      setLegalAidError(message);
      throw new Error(message);
    }
    try {
      const documents = await Promise.all(selectedFiles.map(async (file) => {
        if (!(file instanceof File)) return file;
        if (!/\.(pdf|txt)$/i.test(file.name)) throw new Error(`${file.name}: ${t("bad_document_name")}`);
        if (!file.size) throw new Error(`${file.name}: ${t("empty_document")}`);
        return { filename: file.name, content_base64: await fileToBase64(file) };
      }));
      // the explanation does not depend on the eligibility reply, so it starts at the same time (it is the slower,
      // model-written part); it is drawn only after the result card exists
      const explainP = question ? null : api("/api/legal-aid/explain", { json: prefill, noToken: true });
      explainP?.catch(() => {});  // handled below; avoids an unhandled-rejection warning if the main call fails first
      const r = await api("/api/legal-aid", { json: prefill, noToken: true });
      renderResult(r, prefill, Boolean(question));
      if (question) {
        renderQuestionPending();
        $("#followupCount").textContent = `Sending follow-up ${followupsUsed + 1} of ${FOLLOWUP_LIMIT}…`;
        const answer = await api("/api/legal-aid/ask", {
          json: { question, question_session: questionSession, language: prefill.language, documents },
          noToken: true,
        });
        setFollowupsUsed(answer.followups_used ?? followupsUsed + 1);
        renderQuestionAnswer(answer);
      } else {
        explainP
          .then(renderExplanation)
          .catch((error) => { $("#explain").innerHTML = `<p class="error">Could not load explanation: ${esc(error.message)}</p>`; });
      }
    } catch (error) {
      if (error.status === 429) setFollowupsUsed(FOLLOWUP_LIMIT);
      setLegalAidError(`Could not complete the request: ${error.message}`);
      $("#explain").innerHTML = `<p class="error">${esc(error.message)}</p>`;
      throw error;
    }
  });
});
function renderExplanation(x) {
  const used = new Set(x.used || []);
  const srcs = (x.sources || []).filter((s) => used.has(s.n));
  $("#explain").innerHTML = `
    <h3>${esc(t("explain_h"))}</h3>
    <p class="hint"><span class="badge ${x.engine === "llm" ? "src-ai" : "src-rules"}">${esc(t(x.engine === "llm" ? "ai_label" : "rules_label"))}</span></p>
    <p>${esc(x.answer)}</p>
    ${(x.next_steps || []).length ? `<p><b>${esc(t("next"))}:</b></p><ol>${x.next_steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>` : ""}
    ${srcs.length ? `<p><b>${esc(t("sources"))}:</b></p><ul>${srcs.map((s) => `<li>[${s.n}] ${esc(s.heading || "")} -
      <a href="${esc(s.source_url)}" target="_blank" rel="noopener">${esc(s.source_url)}</a> (${esc(s.authority)}, checked ${esc(s.last_verified)})</li>`).join("")}</ul>` : ""}
    ${x.secondary_only_note ? `<p class="hint">${esc(x.secondary_only_note)}</p>` : ""}`;
}
function legalAnswerMarkup(value) {
  const text = String(value || "").replace(/\r\n?/g, "\n").trim().replace(/:\s+([-*])\s+(?=\S)/g, ":\n$1 ");
  const blocks = [];
  let paragraph = [], bullets = [];
  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push(`<p>${paragraph.map((line) => esc(line).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")).join(" ")}</p>`);
    paragraph = [];
  };
  const flushBullets = () => {
    if (!bullets.length) return;
    blocks.push(`<ul>${bullets.map((line) => `<li>${esc(line).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")}</li>`).join("")}</ul>`);
    bullets = [];
  };
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    const bullet = line.match(/^[-*]\s+(.+)/);
    if (!line) {
      flushParagraph();
      flushBullets();
    } else if (bullet) {
      flushParagraph();
      bullets.push(bullet[1]);
    } else {
      flushBullets();
      paragraph.push(line.replace(/^#{1,6}\s+/, ""));
    }
  }
  flushParagraph();
  flushBullets();
  return blocks.join("");
}
function renderQuestionPending() {
  $("#explain").innerHTML = `
    <h3>${esc(t("question_answer"))}</h3>
    <div class="summary-progress is-running" role="status" aria-live="polite">
      <span class="summary-spinner" aria-hidden="true"></span>
      <span>${esc(t("answer_preparing"))}</span>
    </div>`;
}
function groupQuestionSources(sources) {
  const grouped = new Map();
  for (const source of sources) {
    const key = source.source_url || `${source.heading || ""}|${source.authority || ""}`;
    if (!grouped.has(key)) grouped.set(key, { ...source, references: [], headings: [] });
    const group = grouped.get(key);
    if (!group.references.includes(source.n)) group.references.push(source.n);
    if (source.heading && !group.headings.includes(source.heading)) group.headings.push(source.heading);
  }
  return [...grouped.values()].map((source) => ({
    ...source,
    heading: source.headings.join("; ") || source.heading,
  }));
}
function renderQuestionAnswer(x) {
  const ids = new Set(x.used || []);
  const sources = (x.sources || []).filter((source) => ids.has(source.n));
  const shown = groupQuestionSources(sources.length ? sources : (x.sources || []));
  $("#explain").innerHTML = `
    <h3>${esc(t("question_answer"))} <span class="badge ${x.engine === "llm" ? "src-ai" : "src-rules"}">${esc(t(x.engine === "llm" ? "answer_label_ai" : "answer_label_sources"))}</span></h3>
    <div class="legal-answer">${legalAnswerMarkup(x.answer)}</div>
    ${shown.length ? `<p><b>${esc(t("sources"))}:</b></p><ul class="legal-sources">${shown.map(sourceMarkup).join("")}</ul>` : ""}
    ${x.secondary_only_note ? `<p class="hint">${esc(x.secondary_only_note)}</p>` : ""}
    ${x.web_search_used ? '<p class="hint">No matching local guide was found; official web sources were checked.</p>' : ""}
    ${x.web_search_error ? '<p class="hint">No matching local guide was found, and online search is unavailable right now.</p>' : ""}
    <p class="hint">${esc(x.disclaimer || t("disclaimer"))}</p>`;
}
function openDraft(prefill) {
  $("#draftBox").innerHTML = `<label>${esc(t("draft_problem"))}<textarea id="problem" rows="3" maxlength="1200"></textarea></label>
    <div class="actions"><button class="btn big" id="writeDraft">${esc(t("draft_write"))}</button></div><div id="draftOut"></div>`;
  $("#writeDraft").addEventListener("click", (e) => busy(e.target, async () => {
    const problem = $("#problem").value.trim();
    const r = await api("/api/legal-aid", { json: { ...prefill, problem, draft: true }, noToken: true });
    $("#draftOut").innerHTML = `<h3>${esc(t("draft_h"))}</h3>
      <p class="hint"><span class="badge ${r.draft.engine === "template" ? "src-rules" : "src-ai"}">${r.draft.engine === "template" ? "Template" : "AI draft"}</span></p>
      <pre class="draft">${esc(r.draft.application)}</pre>
      <div class="actions"><button class="btn" id="copyDraft">${esc(t("copy"))}</button><button class="btn" id="dlDraft">${esc(t("download"))}</button></div>`;
    $("#copyDraft").addEventListener("click", () => navigator.clipboard?.writeText(r.draft.application).then(() => toast("Copied")));
    $("#dlDraft").addEventListener("click", (ev) => busy(ev.target, () => downloadDocx({ ...prefill, problem })));
  }));
  $("#problem").focus();
}
const VERDICT_ICON = { likely_eligible: "✔", possibly_eligible: "?", not_on_facts_given: "✖" };
function renderResult(r, prefill, questionPending = false) {
  const go = r.where_to_go || {};
  $("#resultCard").innerHTML = `<div class="card" aria-live="polite">
    ${r.urgent ? `<div class="banner-bad"><b>${esc(t("urgent"))}</b><ul>${r.urgent.map((u) => `<li><b>${esc(u.number)}</b> - ${esc(u.for)}</li>`).join("")}</ul></div>` : ""}
    <h3>${esc(t(questionPending ? "eligibility_result" : "result"))}</h3>
    <p class="verdict ${esc(r.outcome)}"><span aria-hidden="true">${VERDICT_ICON[r.outcome]}</span> ${esc(t("v_" + r.outcome))}</p>
    ${r.grounds.length ? `<p><b>${esc(t("why"))}:</b> ${r.grounds.map((g) => `Sec. ${esc(g.clause)} - ${esc(g.ground)}`).join("; ")}</p>` : ""}
    ${r.missing_facts.length ? `<p><b>${esc(t("missing"))}:</b> ${r.missing_facts.map(pretty).join(", ")}</p>` : ""}
    <p><b>${esc(t("where"))}:</b> ${esc(go.office)} - ${esc(go.address || "")}<br>${esc(t("phone"))}: <b>${esc(go.phone)}</b> <span class="hint">(${esc(go.label || "")})</span></p>
    <p><b>${esc(t("carry"))}:</b></p><ul>${r.documents_needed.map((d) => `<li>${esc(d)}</li>`).join("")}</ul>
    <p class="hint">${esc(r.income_limit_note)} · Sec. 12, Legal Services Authorities Act, 1987</p>
    <div id="explain" aria-live="polite"><p class="hint">${esc(t(questionPending ? "answer_preparing" : "explaining"))}</p></div>
    <div class="actions">${r.outcome !== "not_on_facts_given" ? `<button class="btn big" id="draftBtn">${esc(t("draft_btn"))}</button>` : ""}</div>
    <div id="draftBox"></div>
    <p class="helpline">${esc(t("helpline"))}</p><p class="hint">${esc(r.what_happens_next || "")} ${esc(t("disclaimer"))}</p></div>`;
  $("#draftBtn")?.addEventListener("click", () => openDraft(prefill));
  $("#resultCard").scrollIntoView({ behavior: "smooth" });
}

$("#citizenSummaryForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const submitter = e.submitter;
  const originalLabel = submitter?.textContent;
  if (submitter) submitter.textContent = t("summarize_working");
  busy(submitter, async () => {
    const progressBox = $("#citizenSummaryStatus");
    const errorBox = $("#citizenSummaryError");
    setSummaryError("");
    progressBox.classList.add("hidden");
    let progress;
    try {
      const file = $("#citizenSummaryFile").files[0];
      const text = $("#citizenSummaryText").value.trim();
      if (Boolean(file) === Boolean(text)) throw new Error("Choose one PDF/TXT file or paste document text.");
      if (file && !/\.(pdf|txt)$/i.test(file.name)) throw new Error(t("bad_document_name"));
      if (file && !file.size) throw new Error(t("empty_document"));
      progress = createSummaryProgress("citizenSummaryStatus", {
        cancel: t("summarize_cancel"),
        canceling: t("summarize_canceling"),
        canceled: t("summarize_canceled"),
        timeout: t("summarize_timeout"),
        elapsed: t("summarize_elapsed"),
        preparing: t("summarize_preparing"),
        sending: t("summarize_sending"),
        waiting: t("summarize_server_work"),
      });
      $("#citizenSummaryOut").innerHTML = "";
      const body = file
        ? { filename: file.name, content_base64: await fileToBase64(file, {
          signal: progress.signal,
          onProgress: (loaded, total) => progress.set(
            t("summarize_preparing").replace("{percent}", Math.floor(loaded / total * 100))),
        }), language: LANG_NAMES[lang] }
        : { filename: "document.txt", text, language: LANG_NAMES[lang] };
      progress.set(t("summarize_sending"));
      const request = api("/api/documents/summarize", { json: body, noToken: true, signal: progress.signal });
      progress.set(t("summarize_server_work"));
      const result = await request;
      progress.complete(t(result.mode === "llm" ? "summarize_done_ai" : "summarize_done_rules"));
      lastSummarisedDocument = file || { filename: "document.txt", text };
      attachedSummaryDocument = null;  // a new summary never rides along with the next legal-aid question
      updateLegalDocumentCount();
      const analysis = result.analysis || {};
      const verification = result.verification || {};
      $("#citizenSummaryOut").innerHTML = `<div class="card">
        <h3>${esc(result.filename)} · ${esc(result.pages)} page(s) <span class="badge ${result.mode === "llm" ? "src-ai" : "src-rules"}">${esc(result.label || result.mode)}</span></h3>
        <section class="summary-view-lead">
          <h4>${esc(t("summarize_result_heading"))}</h4>
          <p>${esc(result.plain || analysis.plain_language_summary || "No plain-language summary was produced.")}</p>
        </section>
        ${renderDocumentSummaryDetails(result, t)}
        <p class="hint">${esc(t("summarize_reader_note"))}</p>
        <p class="hint">Document type: ${esc(result.doc_type || "unknown")} · ${(verification.grounded ?? verification.overall_grounded)
          ? "Every date and section shown was found in the document text" : "Some details need checking against the original"}</p>
        ${verification.unverified?.length ? `<p class="banner-warn">Left out because they do not appear in the document: ${verification.unverified.map(esc).join("; ")}</p>` : ""}
        ${result.low_confidence_pages?.length ? `<p class="banner-warn">Low OCR confidence on page(s): ${esc(result.low_confidence_pages.join(", "))}</p>` : ""}
        <button class="btn" id="useSummaryForAid" type="button">${esc(t("summary_use_legal_aid"))}</button>
      </div>`;
      $("#useSummaryForAid").addEventListener("click", () => {
        attachedSummaryDocument = lastSummarisedDocument;  // the only place a summarised file is attached
        updateLegalDocumentCount();
        showCitizenTab("legal");
        $("#legalQuestion").focus();
        toast("Document ready. Add a question and submit the eligibility form to use it.");
      });
    } catch (error) {
      if (progress?.signal.aborted) {
        if (progress.timedOut()) {
          progress.fail(t("summarize_timeout"));
          setSummaryError(t("summarize_timeout"));
        } else {
          progress.cancelled(t("summarize_canceled"));
        }
      } else {
        const detail = error.message || "An unexpected error occurred.";
        progress?.fail(t("summarize_failure").replace("{error}", detail));
        setSummaryError(t("summarize_failure").replace("{error}", detail));
      }
    } finally {
      progress?.dispose();
      if (submitter) submitter.textContent = originalLabel;
    }
  });
});

// ---------------------------------------------------------------- start
// the health check runs alongside the string table instead of after it; its note is shown once strings are ready
const healthP = api("/api/health", { noToken: true }).catch(() => null);
fetch("/static/i18n.json?v=2", { cache: "no-cache" }).then((r) => {
  if (!r.ok) throw new Error(`Translation request failed (${r.status})`);
  return r.json();
}).then((s) => { STR = s; }).catch((error) => {
  console.error("Could not load citizen translations.", error);
}).finally(() => {
  applyLang();
  healthP.then((h) => { if (h && !h.llm_enabled) $("#offlineNote").textContent = t("offline_note"); });
});
