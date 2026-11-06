"""Nyaya Mitra front door: intent -> small tool set -> use it yourself, or hand over.

    route_intent(message, role, has_files)  deterministic intent rules (offline, and fallback for the model's intent step)
    pick_tools(message, role, has_files)    rules pick a small tool set (no model call)
    FrontDoor.handle(...)                   the offline conversation: runs internal tools, asks ONE missing fact,
                                            asks for a clear "yes" before any hand-over, returns reply + action cards
    finalise(reply, message, role)          safety lines first (112 / 181 / 1098 / cybercrime portal / 15100) and the
                                            closing next step + helpline + "information, not advice" for citizens

Everything legal in a reply comes from a tool result or a cited passage; web facts carry their date.
"""
import re
from typing import Dict, List, Optional

from .. import legal_aid, triage
from .context import facts_from_context
from .tools import BY_NAME, CITIZEN, tools_for

YES = re.compile(r"^\s*(yes|y|haan|ha|ok|okay|sure|please do|go ahead|send it|confirm|avunu|హా|అవును|हाँ|हां|जी हाँ)(\b|\s|$)", re.I)
NO = re.compile(r"^\s*(no|n|nahi|nahin|don'?t|do not|stop|cancel|not now|kaadu|వద్దు|కాదు|नहीं|ना)(\b|\s|$)", re.I)
CASE_NO = re.compile(r"\b([A-Z][A-Z.()]{0,9}/\d{4}/\d{1,6}|[A-Z]{1,6}/\d{1,6}/\d{4})\b")

# Follow-ups about what the 5-question guide just showed. Only used when the guide's result came with the message.
FOLLOW_UP = re.compile(r"other (sections?|laws?|provisions?|rights?|grounds?)|any (other|more) (sections?|laws?|rights?|help)|"
                       r"in my fa(vou?r)|work(s)? (for|in) (me|my)|help(s)? me|what else|anything else|my options|"
                       r"what (should|can|do) i do|next steps?|what now|what happens (now|next)|\bmy rights\b", re.I)

INTENT_RULES = [  # (intent, pattern, tools) - first match wins
    ("safety_threat", r"(photo|image|picture|video|morph).{0,80}(threat|blackmail|leak|share|post|viral)|"
                      r"(threat|blackmail).{0,80}(photo|image|picture|video)|harass|stalk|morphed", []),
    ("will_i_win", r"will i win|chances? of (winning|success)|will (the|my) case (succeed|win)|can i win", []),
    ("prepare_list", r"(prepare|draft|make|build|create).{0,40}(cause list|next week'?s list|weekly list|list for next week)", ["prepare_cause_list"]),
    ("deferrals", r"past (their |its |the )?deadline|overdue|deferred|carried over|starv", ["deferral_report"]),
    ("alerts", r"\balerts?\b|undertrial watch|release applications?", ["get_undertrial_alerts"]),
    ("priority", r"(critical|urgent|priority|top|highest).{0,20}cases|which cases", ["priority_cases"]),
    ("case_status", r"(status|next hearing|next date|stage).{0,60}case|case.{0,60}(status|next hearing|next date)", ["get_case_status", "lookup_case"]),
    ("custody", r"\b(jail(ed|ing)?|custody|arrest(ed)?|detain(ed)?|imprisoned|prison|undertrial|lock-?up|remand(ed)?)\b",
     ["check_undertrial_release", "check_legal_aid_eligibility", "request_release_review"]),
    ("office", r"(where|address|office|phone|contact|nearest).{0,50}(legal services|legal aid|dlsa)|"
               r"(legal services|dlsa).{0,40}(office|address|phone)", ["find_legal_aid_office"]),
    ("free_lawyer", r"free lawyer|legal aid|can'?t afford|cannot afford|\bearn\b|income|salary|free legal",
     ["check_legal_aid_eligibility", "legal_aid_kb_search", "draft_legal_aid_application"]),
    ("explain", r"^(what|how|who|when|why|is|are|does|do|explain)\b|meaning of", ["legal_aid_kb_search"]),
]


def route_intent(message: str, role: str, has_files: bool = False) -> Dict:
    allowed = {t.name for t in tools_for(role)}
    if has_files:
        return {"intent": "document", "tools": ["analyze_document"]}
    text = (message or "").lower()
    for intent, pattern, tools in INTENT_RULES:
        if re.search(pattern, text):
            picked = [t for t in tools if t in allowed]
            if tools and not picked:
                continue  # e.g. a citizen asking for docket reports: not their tool, keep looking
            return {"intent": intent, "tools": picked}
    return {"intent": "explain", "tools": ["legal_aid_kb_search"]}


CORE_TOOLS = ("legal_aid_kb_search", "check_legal_aid_eligibility", "find_legal_aid_office", "lookup_case")


def pick_tools(message: str, role: str, has_files: bool = False) -> List[str]:
    """The tools offered to the model this turn: the rules' pick plus a few core tools. No model call - a separate
    intent call per message doubled the requests and ran into the provider's rate limit. A small list also keeps
    the prompt short."""
    allowed = [t.name for t in tools_for(role)]
    rules = route_intent(message, role, has_files)["tools"]
    if has_files:
        return rules
    return list(dict.fromkeys(rules + [t for t in CORE_TOOLS if t in allowed]))


# ----------------------------------------------------------------------------- safety and closing lines
CYBER = ["Save screenshots or screen recordings of the messages, the account and the dates; keep the links. Do not delete them.",
         "Report it at cybercrime.gov.in or call 1930 (cyber crime helpline), and report the account to the platform.",
         "If you are in immediate danger, call 112."]


def safety_lines(message: str, facts: Optional[Dict] = None) -> List[str]:
    text, facts = (message or "").lower(), facts or {}
    urgent = legal_aid.urgent_help({
        "in_custody": facts.get("in_custody") or bool(re.search(r"\b(jail|custody|arrested|detained|lock-?up)\b", text)),
        "domestic_violence": bool(re.search(r"beat|beats|hit me|hits me|domestic violence|abus|husband.{0,20}(hurt|threat)", text)),
        "child_at_risk": bool(re.search(r"child.{0,40}(danger|abus|beaten|missing|trafficked|at risk)", text))})
    lines = [f"{u['number']}: {u['for']}" for u in urgent or []]
    if re.search(INTENT_RULES[0][1], text):
        lines = CYBER + [f"{legal_aid.HELPLINE}: free legal aid helpline"] + [l for l in lines if not l.startswith(("112", "15100"))]
    return lines


def finalise(reply: str, message: str, role: str, facts: Optional[Dict] = None) -> str:
    """Safety first, then the answer; citizens always get a next step, the helpline and the disclaimer."""
    lines = safety_lines(message, facts)
    out = reply.strip()
    if lines and not any(l.split(":")[0] in out[:400] for l in lines[:1]):
        out = "Urgent help first:\n- " + "\n- ".join(lines) + "\n\n" + out
    if role == CITIZEN and legal_aid.HELPLINE not in out:
        out += f"\n\nNext step: call the free legal aid helpline {legal_aid.HELPLINE} for help in your language."
    if role == CITIZEN and "not legal advice" not in out:
        out += "\n(Legal information, not legal advice.)"
    return out


# ----------------------------------------------------------------------------- facts from a message (offline)
MONTHLY = re.compile(r"(?:earn|income|salary|get|make)\D{0,15}?(?:rs\.?|₹|inr)?\s*([\d,]{3,})\s*(?:rupees|rs)?\s*"
                     r"(a|per|every|/)?\s*(month|year|annum|yr|mo)?", re.I)


def extract_facts(message: str) -> Dict:
    c = triage.classify_free_text(message)  # heuristic offline; the LLM path reads facts itself
    text = message.lower()
    facts = {"case_type": c["case_type"], "in_custody": bool(c.get("accused_in_custody")),
             "custody_since": c.get("custody_since"), "max_sentence_years": c.get("max_sentence_years")}
    if re.search(r"\b(i am|i'm) (a )?(woman|girl|wife|widow|mother)\b|\bmy husband\b", text):
        facts["woman"] = True
    m = MONTHLY.search(message)
    if m:
        amount = int(m.group(1).replace(",", ""))
        facts["annual_income"] = amount * 12 if (m.group(3) or "").lower() in ("month", "mo") else amount
    for state in ("Telangana", "Andhra Pradesh", "Karnataka", "Maharashtra", "Tamil Nadu"):
        if state.lower() in text:
            facts["state"] = state
    m = re.search(r"\bin ([A-Z][a-zA-Z-]+)(?:\?|\.|,|$| district)", message)
    if m and m.group(1).lower() not in ("jail", "custody", "the", "a", "my", "india"):
        facts["district"] = m.group(1)
    if re.search(r"\bf[ie]rs?t (time|offen)", text):
        facts["first_time_offender"] = not re.search(r"not (his|her|the|a) first|not first", text)
    return facts


_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]


def month_year(text: str) -> Optional[str]:
    """'March 2022' / 'since 2021' / '03/2022' -> first day of that month (the conservative reading)."""
    t = (text or "").lower()
    m = re.search(r"\b(" + "|".join(_MONTHS) + r"|" + "|".join(x[:3] for x in _MONTHS) + r")[a-z]*\.?\s+(\d{4})\b", t)
    if m:
        return f"{m.group(2)}-{[x[:3] for x in _MONTHS].index(m.group(1)[:3]) + 1:02d}-01"
    m = re.search(r"\b(\d{1,2})[/-](\d{4})\b", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{m.group(2)}-{int(m.group(1)):02d}-01"
    m = re.search(r"\b(19|20)\d{2}\b", t)
    return f"{m.group(0)}-01-01" if m else None


def _yes_no(text: str) -> Optional[bool]:
    return True if YES.search(text or "") else False if NO.search(text or "") else None


def answer_kind(awaiting: Optional[Dict], interrupted: bool = False) -> Optional[str]:
    """What the chat screen should offer next: 'confirm' (Yes / No for a hand-over), 'yes_no' (a yes / no fact),
    'text' (an open question: the person just types) or None."""
    if interrupted:
        return "text"
    if not awaiting:
        return None
    if awaiting.get("kind") == "confirm" or "tool" in awaiting and "kind" not in awaiting:
        return "confirm"
    return "yes_no" if awaiting.get("fact") == "first_time_offender" else "text"


# ----------------------------------------------------------------------------- the offline conversation
class FrontDoor:
    """Deterministic conversation used when no LLM is configured (and for tests). State is a plain dict kept by the caller."""

    def __init__(self, role: str, actor: str = ""):
        self.role, self.ctx = role, {"role": role, "actor": actor or f"demo-{role}"}

    def _run(self, name: str, confirmed: bool = False, **args):
        return BY_NAME[name].run(ctx=self.ctx, confirmed=confirmed, **args)

    def handle(self, message: str, state: Optional[Dict] = None, batch_id: Optional[str] = None,
               context: Optional[Dict] = None) -> Dict:
        state = dict(state or {})
        awaiting = state.pop("awaiting", None)
        used: List[str] = []
        if awaiting and awaiting["kind"] == "confirm":
            answer = _yes_no(message)
            if answer is True:
                out = self._run(awaiting["tool"], confirmed=True, **awaiting["args"])
                used.append(awaiting["tool"])
                return self._done(self._after_handover(awaiting["tool"], out), message, used, state, out.get("actions", []))
            if answer is False:
                return self._done("Okay - I have not sent or changed anything.", message, used, state)
            # anything else: treat as a new message (the hand-over did not run)
        if awaiting and awaiting["kind"] == "fact":
            new = {k: v for k, v in extract_facts(message).items() if v not in (None, False, "")}
            facts = {**awaiting["facts"], **new}
            answered = False
            if awaiting["fact"] == "first_time_offender":
                yn = _yes_no(message)
                if facts.get("first_time_offender") is None and (yn is not None or re.search(r"not sure|don'?t know", message, re.I)):
                    facts["first_time_offender"] = bool(yn)  # "not sure": the stricter one-half rule
                answered = facts.get("first_time_offender") is not None
            elif awaiting["fact"] == "custody_since":
                facts["custody_since"] = facts.get("custody_since") or month_year(message)
                answered = bool(facts["custody_since"])
            if answered:
                return self._custody(awaiting.get("message", message), facts, state, used)
            # not an answer to the question: handle it as a new message

        route = route_intent(message, self.role, bool(batch_id))
        intent = route["intent"]
        # What the person already told the 5-question guide counts as said; what they type now overrides it.
        facts = {**facts_from_context(context), **{k: v for k, v in extract_facts(message).items() if v not in (None, False, "")}}
        if context and not batch_id and intent not in ("safety_threat", "will_i_win") and FOLLOW_UP.search(message or ""):
            return self._from_context(message, context, facts, state, used)
        if intent == "document":
            return self._document(message, batch_id, state)
        if intent == "safety_threat":
            return self._done("I'm sorry this is happening. You can stop it, and you do not have to share the photos here. "
                              "Are they threatening to share intimate images, or asking for money?", message, used, state)
        if intent == "will_i_win":
            return self._done("No one can honestly predict the result of a case, and I can't either. What I can do: explain "
                              "your options (a lawyer's opinion, settlement or Lok Adalat where allowed, appeal routes), and check "
                              "whether you can get a free lawyer from the Legal Services Authority.", message, used, state)
        if intent == "custody" and "check_undertrial_release" in route["tools"]:
            return self._custody(message, facts, state, used)
        if intent == "free_lawyer":
            return self._legal_aid(message, facts, state, used)
        if intent == "office":
            out = self._run("find_legal_aid_office", district=facts.get("district", ""), state=facts.get("state", ""))
            used.append("find_legal_aid_office")
            o = out["office"]
            text = f"{o['office']}\nAddress: {o.get('address') or 'not on file'}\nPhone: {o['phone']}\n({o['label']})"
            return self._done(text, message, used, state)
        if intent == "case_status":
            return self._case_status(message, state, used)
        if intent in ("deferrals", "alerts", "priority"):
            name = route["tools"][0]
            out = self._run(name)
            used.append(name)
            return self._done(self._report(name, out), message, used, state)
        if intent == "prepare_list":
            tool = BY_NAME["prepare_cause_list"]
            state["awaiting"] = {"kind": "confirm", "tool": tool.name, "args": {}}
            return self._done(tool.confirm_question, message, used, state,
                              [{"label": "Yes, prepare the draft", "route": "chat:confirm", "prefill": {"tool": tool.name}}],
                              awaiting=True)
        return self._explain(message, state, used)

    # --------------------------------------------------------------- flows
    def _from_context(self, message, ctx, facts, state, used):
        """A follow-up to the 5-question guide: start from the grounds it found, then say what else may help and what
        is still needed. Code and cited passages only - no section is named that a tool did not return."""
        lines = []
        grounds = ctx.get("grounds") or []
        if grounds:
            lines.append("From the check you just did, free legal aid applies to you under: " +
                         "; ".join(f"Sec. {g['clause']} - {g['ground']}" for g in grounds) + ". "
                         "Any one ground is enough; they do not need to be combined.")
        else:
            lines.append(f"From the check you just did: {ctx.get('outcome') and legal_aid.OUTCOME_LABELS.get(ctx['outcome']) or 'no ground found yet'}.")
        # Other Sec. 12 categories the person marked 'not sure' (a 'no' is respected, not asked again)
        app = ctx.get("applicant") or {}
        unsure = [(k, legal_aid.CATEGORIES[k]) for k in ("woman", "sc_st", "disability") if k not in app]
        if unsure:
            lines.append("Other grounds to check, if true for the person: " +
                         "; ".join(f"Sec. {c} - {d}" for _, (c, d) in unsure) + ". Tell me if any applies.")
        if facts.get("in_custody"):
            lines.append("Because the person is in custody, a second route also exists: Sec. 479 BNSS can allow release on "
                         "bond after the person has spent a set part of the maximum sentence in custody (one-third for a first "
                         "offence, one-half otherwise). It does not apply to offences punishable with death or life "
                         "imprisonment. A legal-aid lawyer can also apply for regular bail.")
            if not facts.get("custody_since"):
                state["awaiting"] = {"kind": "fact", "fact": "custody_since", "facts": facts, "message": message}
                lines.append("To check Sec. 479 BNSS for you I need two things: since when is the person in custody "
                             "(month and year), and what is the charge (for example theft or cheating)?")
        kb = self._run("legal_aid_kb_search", query="rights of a person in custody free legal aid lawyer " + (message or ""), top_k=1)
        used.append("legal_aid_kb_search")
        if kb.get("passages"):
            lines.append(f"Legal-aid guide source: {kb['passages'][0]['citation']}")
        if ctx.get("office") or ctx.get("phone"):
            lines.append(f"Where to go: {ctx.get('office') or 'District Legal Services Authority'}; phone {ctx.get('phone') or legal_aid.HELPLINE}.")
        return self._done("\n".join(lines), message, used, state, awaiting="awaiting" in state, facts=facts)

    def _custody(self, message, facts, state, used):
        if triage.charge_is_life_or_death(message):
            # murder etc.: Sec. 479 BNSS does not apply, so do not ask for dates or a first-offence answer that cannot matter
            lines = ["Sec. 479 BNSS (release after part of the sentence) does not apply to offences punishable with death or "
                     "life imprisonment, such as murder. That does not close the door: a lawyer can still apply for regular "
                     "bail and challenge the evidence. Please do not give up on the case."]
            used.append("check_undertrial_release")
            elig = self._run("check_legal_aid_eligibility", in_custody=True, district=facts.get("district", ""))
            used.append("check_legal_aid_eligibility")
            lines.append(f"Free legal aid: {elig['outcome_label']} - a person in custody qualifies under Sec. 12(g). "
                         f"Apply at the {elig['where_to_apply']}, or ask the jail's legal-aid lawyer. Helpline 15100.")
            return self._done("\n".join(lines), message, used, state, facts=facts)
        if not facts.get("custody_since"):
            state["awaiting"] = {"kind": "fact", "fact": "custody_since", "facts": facts, "message": message}
            return self._done("To check release under Sec. 479 BNSS I need one fact: since when has the person been in "
                              "custody (month and year)?", message, used, state, awaiting=True)
        if facts.get("first_time_offender") is None:
            state["awaiting"] = {"kind": "fact", "fact": "first_time_offender", "facts": facts, "message": message}
            return self._done("To check release under Sec. 479 BNSS I need one fact: is this the person's first offence? "
                              "(yes / no / not sure)", message, used, state, awaiting=True)
        lines, actions = [], []
        if facts.get("max_sentence_years"):
            rel = self._run("check_undertrial_release", custody_since=facts["custody_since"],
                            max_sentence_years=facts["max_sentence_years"], first_time_offender=facts["first_time_offender"],
                            offence=message)
            used.append("check_undertrial_release")
            if rel.get("applicable"):
                lines.append(f"Custody since {facts['custody_since']}: {rel['custody_days']} days. The Sec. 479 BNSS limit for "
                             f"this offence is {rel['threshold_days']} days, {rel['basis']} ({rel['percent_of_threshold']}%).")
                if rel["eligible"]:
                    lines.append("The person appears to have crossed the limit and may be entitled to release on bond. "
                                 "A lawyer must check the conditions (other pending cases, delay caused by the accused).")
                    tool = BY_NAME["request_release_review"]
                    args = {"custody_since": facts["custody_since"], "max_sentence_years": facts["max_sentence_years"],
                            "first_time_offender": facts["first_time_offender"], "description": message[:200]}
                    state["awaiting"] = {"kind": "confirm", "tool": tool.name, "args": args}
                    actions.append({"label": "Ask a legal-aid lawyer to review", "route": "chat:confirm",
                                    "prefill": {"tool": tool.name, "args": args}})
                    if rel.get("needs_review"):
                        lines.append("A lawyer must check: " + "; ".join(rel["needs_review"]) + ".")
                    lines.append(tool.confirm_question)
            else:
                lines.append(f"Sec. 479 BNSS: {rel['reason']}.")
        else:
            lines.append("I could not tell the offence, so I cannot compute the Sec. 479 BNSS limit yet; a legal-aid lawyer can.")
        elig = self._run("check_legal_aid_eligibility", in_custody=True, district=facts.get("district", ""))
        used.append("check_legal_aid_eligibility")
        lines.append(f"Free legal aid: {elig['outcome_label']} - a person in custody qualifies under Sec. 12(g). "
                     f"Apply at the {elig['where_to_apply']}, or ask the jail's legal-aid lawyer.")
        return self._done("\n".join(lines), message, used, state, actions, awaiting="awaiting" in state, facts=facts)

    def _legal_aid(self, message, facts, state, used):
        applicant = {k: facts[k] for k in ("annual_income", "woman", "in_custody", "district", "state") if facts.get(k)}
        elig = self._run("check_legal_aid_eligibility", **applicant)
        used.append("check_legal_aid_eligibility")
        lines = [f"{elig['outcome_label']}."]
        if elig["grounds"]:
            lines.append("Why: " + "; ".join(f"Sec. {g['clause']} - {g['ground']}" for g in elig["grounds"]) + ".")
        lines.append(f"Income limit used: {elig['income_limit_note']}.")
        go = elig["where_to_go"]
        lines.append(f"Where to go: {go['office']} ({go.get('address') or 'District Court complex'}), phone {go['phone']}.")
        kb = self._run("legal_aid_kb_search", query="who is eligible for free legal aid and how to apply", top_k=1)
        used.append("legal_aid_kb_search")
        if kb.get("passages"):
            p = kb["passages"][0]
            lines.append(f"Source: {p['citation']}")
        actions = []
        if elig["outcome"] == "possibly_eligible":
            lines.append("One question: what is your family's total income per year (or per month)?")
        else:
            draft = self._run("draft_legal_aid_application", problem=message, **applicant)
            used.append("draft_legal_aid_application")
            actions = draft.get("actions", [])
            lines.append("I can prepare your application: use 'Download application (Word)', fill the blanks, sign and submit it.")
        return self._done("\n".join(lines), message, used, state, actions, facts=facts)

    def _case_status(self, message, state, used):
        if self.role != CITIZEN:
            m = CASE_NO.search(message)
            if not m:
                return self._done("Which case number?", message, used, state)
            out = self._run("lookup_case", case_id=m.group(1))
            used.append("lookup_case")
            if out.get("error"):
                return self._done(out["error"], message, used, state)
            c, p = out["case"], out["priority"]
            return self._done(f"{m.group(1)}: {c.get('case_type')}, stage {c.get('stage')}, next hearing "
                              f"{c.get('next_hearing_date') or 'not fixed'}; priority {p['band']} ({p['score']}).",
                              message, used, state, [{"label": "Open case", "route": f"/staff/cases/{m.group(1)}",
                                                      "prefill": {"case_id": m.group(1)}}])
        m, year = CASE_NO.search(message), re.search(r"\b(19|20)\d{2}\b(?![/\d])", message)
        if not m or not year:
            return self._done("Please give the case number exactly as on your papers and the year it was filed, so I can verify it.",
                              message, used, state)
        out = self._run("get_case_status", case_number=m.group(1), filing_year=year.group(0))
        used.append("get_case_status")
        text = (f"Case {m.group(1)}: stage - {out['stage']}; next hearing - {out['next_hearing_date']}."
                if out["verified"] else out["message"])
        return self._done(text, message, used, state)

    def _document(self, message, batch_id, state):
        out = self._run("analyze_document", batch_id=batch_id)
        if out.get("error"):
            return self._done(out["error"], message, ["analyze_document"], state)
        blocks = []
        for f in out.get("files", []):
            head = f"{f['file']} ({f['label']}):" if f.get("label") else f"{f['file']}:"
            lines = []
            if f.get("duplicate_of"):
                lines.append(f"Already in the docket as case {f['duplicate_of']} - not read again.")
            if f.get("summary"):
                lines.append(f["summary"])
                if f.get("deadlines"):
                    lines.append("Dates to act on: " + "; ".join(f["deadlines"]))
            if f.get("brief"):
                lines += list(f["brief"])
                if f.get("band"):
                    lines.append(f"Priority: {f['band']} ({f.get('score')})")
                if f.get("review_fields"):
                    lines.append("Needs review: " + ", ".join(f["review_fields"]))
            if lines:
                blocks.append("\n".join([head] + lines))
            elif f.get("status") in ("rejected", "duplicate"):
                blocks.append(f"{f['file']}: not read - {f.get('error')}")
            else:
                blocks.append(f"{f['file']}: could not be read - {f.get('error') or 'unknown problem'}")
        if len(blocks) > 1:
            blocks.insert(0, f"I read {sum(1 for f in out['files'] if f.get('summary') or f.get('brief'))} of {len(blocks)} files.")
        return self._done("\n\n".join(blocks) or "No readable file was attached.", message, ["analyze_document"], state,
                          out.get("actions", []))

    def _explain(self, message, state, used):
        kb = self._run("legal_aid_kb_search", query=message, top_k=2)
        used.append("legal_aid_kb_search")
        if not kb.get("passages"):
            return self._done("I could not find this in the legal-aid knowledge base. A legal-aid lawyer can explain it.",
                              message, used, state)
        p = kb["passages"][0]
        terms = [w for w in re.findall(r"[a-z]{4,}", message.lower()) if w not in ("what", "does", "mean", "when", "explain")]
        if p.get("collection") == "legal_info.html":
            # a curated entry: bullet facts, each already one point with its section of law - quote the best three
            facts = [l[2:].strip() for l in p["text"].splitlines() if l.startswith("- ")]
            ranked = sorted(range(len(facts)), key=lambda i: (-sum(t in facts[i].lower() for t in terms), i))[:3]
            law = next((l for l in p["text"].splitlines() if l.startswith(("Law:", "Helplines:"))), "")
            text = f"{p['heading']}:\n" + "\n".join("- " + facts[i] for i in sorted(ranked)) + (f"\n{law}" if law else "")
            text += "\nSource: " + p["citation"]
            if kb.get("secondary_only_note"):
                text += f"\nNote: {kb['secondary_only_note']}"
            return self._done(text, message, used, state)
        sentences = re.split(r"(?<=[.?!])\s+", p["text"].split("\n", 1)[-1])
        best = max(range(len(sentences)), key=lambda i: (sum(t in sentences[i].lower() for t in terms), -i)) if sentences else 0
        quote = [s for s in sentences[best:best + 2] if not s.rstrip().endswith("?")] or sentences[best:best + 1]
        body = " ".join(quote)  # quote the part of the passage that answers the question (not the next FAQ heading)
        text = f"From the legal-aid knowledge base: \"{body}\"\nSource: {p['citation']}"
        if kb.get("secondary_only_note"):
            text += f"\nNote: {kb['secondary_only_note']}"
        return self._done(text, message, used, state)

    def _report(self, name, out) -> str:
        if name == "deferral_report":
            lines = [f"{out['past_deadline']} case(s) are past their listing deadline; {out['deferred_3_plus']} were deferred 3+ times in a row."]
            lines += [f"- {c['case_id']} ({c['band']}): due {c['sla_due_on']}, deferred {c['consecutive_deferrals']}x, "
                      f"last reason {c['last_reason'] or '-'}" for c in out["past_deadline_cases"][:8]]
            return "\n".join(lines)
        if name == "get_undertrial_alerts":
            return f"{out['count']} alert(s): " + "; ".join(f"#{a['id']} {a['case_id']} ({a['custody_days']}/{a['threshold_days']} days)"
                                                            for a in out["alerts"][:8])
        return f"{out['count']} case(s): " + "; ".join(f"{c['case_id']} {c['band']} {c['score']}" for c in out["cases"][:10])

    def _after_handover(self, name, out) -> str:
        if out.get("error") or out.get("needs_confirmation"):
            return out.get("error") or "That needs a clear yes first."
        if name == "request_release_review":
            return (f"Sent. Reference {out['reference']}. {out['next']}" if out.get("queued") else
                    f"Not sent: {out.get('reason')}.")
        if name == "prepare_cause_list":
            return (f"Draft cause list #{out['cause_list_id']} from {out['start_date']}: {out['listed']} listed, "
                    f"{out['carried_over']} carried over, utilisation {out['utilisation_percent']}%, must-list {out['must_list']}, "
                    f"deadline alerts {out['deadline_alerts']}, capacity shortfall {'yes' if out['capacity_shortfall'] else 'no'}. "
                    "It is a draft - the Registrar approves it on the Cause list screen.")
        return "Done."

    def _done(self, text, message, used, state, actions=None, awaiting=False, facts=None) -> Dict:
        return {"reply": finalise(text, message, self.role, facts), "actions": actions or [], "tools_used": used,
                "awaiting_confirmation": bool(state.get("awaiting") and state["awaiting"]["kind"] == "confirm"),
                "awaiting": bool(awaiting) or bool(state.get("awaiting")), "state": state}
