"""Free legal aid access: eligibility under Sec. 12 of the Legal Services Authorities Act, 1987,
guidance on where to apply, and a draft application.

Code decides (this module, deterministic), the knowledge index explains (legal_aid_kb), the internet confirms
facts that change (get_state_fact: table first, trusted web search when missing or older than
WEB_FACT_TTL_DAYS, written back with source and date), and the LLM only talks and drafts.
Outcomes: likely_eligible | possibly_eligible (with missing_facts) | not_on_facts_given.

Drafting style follows the formatting contract in Case-Draft-Backend/source/prompts.py
(numbered paragraphs, formal language, no markdown).
"""
import logging
import re
import threading
import time
from collections import OrderedDict
from datetime import date, datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel

from . import config, llm

logger = logging.getLogger(__name__)

HELPLINE = config.LEGAL_AID_HELPLINE
MAX_FOLLOWUPS = config.LEGAL_AID_MAX_FOLLOWUPS
MAX_QUESTION_DOCUMENTS = config.LEGAL_AID_MAX_QUESTION_DOCUMENTS
_FOLLOWUP_SESSION_TTL = config.LEGAL_AID_FOLLOWUP_SESSION_TTL_SECONDS
_MAX_TRACKED_FOLLOWUP_SESSIONS = config.LEGAL_AID_MAX_TRACKED_SESSIONS
_followup_sessions = OrderedDict()
_followup_lock = threading.Lock()
DISCLAIMER = f"Legal information, not legal advice. Please have it checked by a legal-aid lawyer. Helpline {HELPLINE}."
OUTCOME_LABELS = {"likely_eligible": "Likely eligible", "possibly_eligible": "Possibly eligible - a few facts needed",
                  "not_on_facts_given": "Not eligible on the facts given"}
STATUS_FLOW = ["checked", "drafted", "applied", "lawyer_assigned", "closed"]
WHAT_NEXT = {
    "checked": "Next: draft the application here, or go to the legal services office with the documents listed.",
    "drafted": "Next: sign the application and submit it to the DLSA (in person, by post, or on the NALSA portal).",
    "applied": "Next: the DLSA usually decides within a few days and informs you; keep the acknowledgement number.",
    "lawyer_assigned": "Next: meet your panel lawyer with all case papers; you pay nothing for the lawyer or court fees.",
    "closed": "The request is closed. If the problem returns, you can apply again or call 15100.",
}

# Sec. 12 LSA Act categories. Field name -> (clause, description)
CATEGORIES = {
    "sc_st": ("12(a)", "Member of a Scheduled Caste or Scheduled Tribe"),
    "trafficking_victim": ("12(b)", "Victim of trafficking in human beings or begar"),
    "woman": ("12(c)", "Woman"),
    "child": ("12(c)", "Child"),
    "disability": ("12(d)", "Person with disability"),
    "disaster_victim": ("12(e)", "Victim of mass disaster, ethnic violence, caste atrocity, flood, drought, earthquake or industrial disaster"),
    "industrial_workman": ("12(f)", "Industrial workman"),
    "in_custody": ("12(g)", "In custody (including protective home, juvenile justice home, psychiatric hospital or nursing home)"),
}

DOCUMENTS = {
    "common": ["Any identity proof", "Copies of case papers / FIR / notice / summons you have received",
               "Short written note of your problem (the authority can help you write it)"],
    "income": ["Income certificate or self-declaration affidavit of annual income"],
    "sc_st": ["Caste certificate"],
    "disability": ["Disability certificate"],
    "in_custody": ["Jail/custody details (the jail visiting lawyer or paralegal volunteer can apply on your behalf)"],
}

FORUMS = {
    "supreme_court": "Supreme Court Legal Services Committee, New Delhi",
    "high_court": "High Court Legal Services Committee of the State",
    "district": "District Legal Services Authority (DLSA) at the District Court complex",
    "taluk": "Taluk / Mandal Legal Services Committee at the Taluk court",
}


CORE_FACTS = ("woman", "child", "sc_st", "disability", "in_custody")  # asked first when no ground is found yet


def inr(n) -> str:
    """Indian digit grouping: 300000 -> 3,00,000."""
    s = str(int(round(float(n))))
    head, tail = s[:-3], s[-3:]
    while len(head) > 2:
        tail, head = head[-2:] + "," + tail, head[:-2]
    return f"{head},{tail}" if head else tail


def _db_rows(table: str, where: Dict, db=None) -> List[Dict]:
    """Table lookups never break the rule engine: no database -> empty (and the labelled fallback is used)."""
    try:
        from . import store
        with store._session(db) as s:
            return s.select(table, where) if table in s.tables() else []
    except Exception as exc:
        logger.info("legal-aid lookup %s skipped: %s", table, exc)
        return []


# ----------------------------------------------------------------------------- facts that change (internet with memory)
_AMOUNT = re.compile(r"(?:rs\.?|₹|inr)\s*([\d,]+(?:\.\d+)?)\s*(lakhs?)?|(\d+(?:\.\d+)?)\s*(lakhs?)", re.I)


def _parse_income_limit(text: str) -> Optional[int]:
    for m in _AMOUNT.finditer(text or ""):
        window = text[max(0, m.start() - 150): m.end() + 150].lower()
        if "income" not in window:
            continue
        num, lakh = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        value = float(num.replace(",", "")) * (100000 if lakh else 1)
        if 10000 <= value <= 10_000_000:
            return int(value)
    return None


def _fact_display(state: str, key: str, value, source_url: Optional[str], verified_at: Optional[str], synthetic: bool) -> str:
    label = {"income_limit": "Income limit", "helpline": "Legal-aid helpline"}.get(key, key)
    shown = f"Rs. {inr(value)}" if key == "income_limit" and value is not None else value
    if value is None:
        return f"{label} in {state}: not on file - confirm with the State Legal Services Authority"
    if synthetic or not verified_at:
        return f"{label} in {state}: {shown} (demo value, not verified - confirm with the DLSA)"
    domain = urlparse(source_url or "").netloc or source_url
    return f"{label} in {state}: {shown}, checked on {datetime.fromisoformat(verified_at).strftime('%d %b %Y')} at {domain}"


def get_state_fact(state: str, key: str = "income_limit", db=None, today: Optional[date] = None, search=None) -> Dict:
    """Table first; if missing or older than WEB_FACT_TTL_DAYS, search the trusted domains, save, and return with its date."""
    today = today or date.today()
    rows = _db_rows("state_legal_aid_params", {"state": state}, db)
    row = rows[0] if rows else {}
    value, verified, synthetic = row.get(key), row.get("verified_at"), bool(row.get("synthetic"))
    fresh = bool(verified and not synthetic and (today - datetime.fromisoformat(verified).date()).days <= config.WEB_FACT_TTL_DAYS)
    source = "table"
    if value is None or not fresh:
        if search is None:
            from . import websearch
            search = websearch.search if websearch.available() else None
        found = None
        if search and key == "income_limit":
            res = search(f"{state} State Legal Services Authority free legal aid annual income limit")
            for item in [{"content": res.get("answer") or "", "url": (res.get("results") or [{}])[0].get("url")}] + (res.get("results") or []):
                amount = _parse_income_limit(item.get("content") or "")
                if amount and item.get("url"):
                    found = (amount, item["url"])
                    break
        if found:
            value, url = found
            verified, synthetic, source = datetime.now(timezone.utc).isoformat(), False, "web"
            try:
                from . import store
                with store._session(db) as s:
                    s.upsert("state_legal_aid_params", [{"state": state, "income_limit": value, "source_url": url,
                                                         "verified_at": verified, "synthetic": False}], ["state"])
                    s.commit()
            except Exception as exc:
                logger.warning("could not save %s for %s: %s", key, state, exc)
            row = {**row, "source_url": url}
    return {"state": state, "key": key, "value": value, "source": source if value is not None else "none",
            "source_url": row.get("source_url"), "verified_at": verified, "synthetic": synthetic,
            "fresh": source == "web" or fresh,
            "display": _fact_display(state, key, value, row.get("source_url"), verified, synthetic)}


# ----------------------------------------------------------------------------- where to go, urgent help
def where_to_go(state: Optional[str], district: Optional[str], court_level: str = "district", db=None) -> Dict:
    if court_level in ("high_court", "supreme_court"):
        return {"office": FORUMS[court_level], "address": None, "phone": HELPLINE, "label": "Apply to the committee of that court."}
    rows = _db_rows("dlsa_directory", {"state": state}, db) if state else []
    match = next((r for r in rows if district and (r["district"] or "").lower() == district.lower()), None)
    if match:
        return {"office": match["office"], "address": match["address"], "phone": match["phone"] or f"{HELPLINE} (national helpline)",
                "district": match["district"], "state": match["state"], "source_url": match["source_url"],
                "label": "Demo directory entry - verify before visiting" if match.get("synthetic") or not match.get("verified_at")
                else f"Checked on {str(match['verified_at'])[:10]}"}
    return {"office": f"District Legal Services Authority{', ' + district if district else ''}",
            "address": "District Court complex" + (f", {district}" if district else ""), "phone": f"{HELPLINE} (national helpline)",
            "label": "Office address not on file - call 15100 to confirm"}


def urgent_help(applicant: Dict) -> Optional[List[Dict]]:
    """Emergency numbers come before any question when someone is in custody, facing domestic violence, or a child is at risk."""
    numbers = []
    if applicant.get("in_custody") or applicant.get("domestic_violence") or applicant.get("child_at_risk"):
        numbers.append({"number": "112", "for": "Police / emergency - immediate danger"})
    if applicant.get("domestic_violence"):
        numbers.append({"number": "181", "for": "Women's helpline (domestic violence, shelter, counselling)"})
    if applicant.get("child_at_risk"):
        numbers.append({"number": "1098", "for": "Childline - child in danger or needing care"})
    if numbers:
        numbers.append({"number": HELPLINE, "for": "NALSA legal aid helpline - free lawyer, including for a person in custody"})
    return numbers or None


# ----------------------------------------------------------------------------- the rule engine
def check_eligibility(applicant: Dict, db=None) -> Dict:
    """Deterministic Sec. 12 check -> likely_eligible | possibly_eligible | not_on_facts_given, with reasons."""
    grounds: List[Dict] = []
    for key, (clause, desc) in CATEGORIES.items():
        if applicant.get(key):
            grounds.append({"clause": clause, "ground": desc})

    state = applicant.get("state") or config.DEMO_STATE
    if applicant.get("income_limit"):
        limit_info = {"value": float(applicant["income_limit"]), "display": f"Income limit given: Rs. {inr(applicant['income_limit'])}",
                      "fallback": False}
    else:
        fact = get_state_fact(state, "income_limit", db=db, search=False)  # the rule engine never waits on the web
        if fact["value"] is not None:
            limit_info = {"value": float(fact["value"]), "display": fact["display"], "fallback": False,
                          "source_url": fact["source_url"], "verified_at": fact["verified_at"]}
        else:
            limit_info = {"value": float(config.LEGAL_AID_INCOME_LIMIT), "fallback": True,
                          "display": f"Rs. {inr(config.LEGAL_AID_INCOME_LIMIT)} (default, State limit not on file)"}
    limit = limit_info["value"]

    income = applicant.get("annual_income")
    income_known = income not in (None, "")
    over_limit = False
    if income_known:
        try:
            if float(income) <= limit:
                grounds.append({"clause": "12(h)", "ground": f"Annual income Rs. {inr(income)} is within the limit of Rs. {inr(limit)}"})
            else:
                over_limit = True
        except (TypeError, ValueError):
            income_known = False

    if grounds:
        outcome, missing = "likely_eligible", []
    elif income_known and over_limit:
        outcome, missing = "not_on_facts_given", []
    else:
        outcome = "possibly_eligible"
        missing = ["annual_income"] + [k for k in CORE_FACTS if applicant.get(k) is None]
    eligible = outcome == "likely_eligible"

    docs = list(DOCUMENTS["common"])
    if any(g["clause"] == "12(h)" for g in grounds) or outcome == "possibly_eligible":
        docs += DOCUMENTS["income"]
    for k in ("sc_st", "disability", "in_custody"):
        if applicant.get(k):
            docs += DOCUMENTS[k]

    court_level = applicant.get("court_level", "district")
    forum = FORUMS.get(court_level, FORUMS["district"])
    go = where_to_go(state, applicant.get("district"), court_level, db=db)
    steps = [
        f"Apply to the {forum}. Applications can be made in person, by post, or online on the NALSA Legal Services portal.",
        "Call the national legal aid helpline 15100 (toll-free) for guidance in your language.",
        "If you are in custody, ask the jail authorities or the visiting legal-aid lawyer - you do not need to pay anything.",
        "Once approved, a panel lawyer is assigned to you free of cost, including court fees and process charges.",
    ]
    if applicant.get("dispute_settleable"):
        steps.append("Your dispute may be settled faster through a Lok Adalat - ask the authority to refer it; there is no court fee and the award is final.")
    if outcome == "possibly_eligible":
        steps = [f"Tell us your annual family income: the limit used is {limit_info['display']}."] + \
                ([f"Also say if any of these apply: {', '.join(k.replace('_', ' ') for k in missing[1:])}."] if missing[1:] else []) + steps
    elif outcome == "not_on_facts_given":
        steps = [
            "You do not appear to fall in a Sec. 12 category on the details given. The income limit differs by State - confirm with your DLSA.",
            "Women, children, SC/ST members, persons with disability and persons in custody qualify whatever their income - tell us if one applies.",
            "You can still seek free advice at a legal aid clinic or the helpline 15100, and approach a Lok Adalat for settleable disputes.",
        ]

    return {
        "outcome": outcome,
        "outcome_label": OUTCOME_LABELS[outcome],
        "eligible": eligible,
        "grounds": grounds,
        "missing_facts": missing,
        "urgent": urgent_help(applicant),
        "income_limit_used": limit,
        "income_limit_note": limit_info["display"],
        "income_limit_fallback": limit_info["fallback"],
        "state": state,
        "where_to_apply": forum,
        "where_to_go": go,
        "documents_needed": docs,
        "next_steps": steps,
        "what_happens_next": WHAT_NEXT["checked"],
        "disclaimer": DISCLAIMER,
    }


APPLICATION_SYSTEM = """You draft applications for free legal aid under Section 12 and 13 of the Legal Services
Authorities Act, 1987, addressed to the Member Secretary / Secretary of the relevant Legal Services Authority.

CRITICAL FORMATTING REQUIREMENTS:
- Formal, simple language a legal-aid clerk will accept; no markdown (no **, *, ---)
- Start with the addressee block, subject line, then numbered paragraphs (1., 2., 3.)
- State the applicant's eligibility ground(s) with the clause of Section 12
- Summarise the legal problem factually from the facts given; never invent facts
- Leave [placeholders] for anything not provided (name, address, case number, date)
- End with a prayer for assignment of a panel lawyer and a verification/signature block
Write the entire application exclusively in the selected language {language}, regardless of the applicant's
input language. Do not include an English translation or mix languages. Preserve case numbers, statutory citations,
official names, and placeholders."""


def draft_application(applicant: Dict, eligibility: Dict, problem: str, language: str = "English") -> Dict:
    if llm.available():
        try:
            facts = (f"Eligibility grounds: {eligibility['grounds']}\nForum: {eligibility['where_to_apply']}\n"
                     f"Court case number (if any): {applicant.get('case_number') or '[not provided]'}\n"
                     f"Problem described by applicant:\n{problem}")
            text = llm.text(APPLICATION_SYSTEM.replace("{language}", language), facts)
            text = llm.enforce_language([text], language)[0]
            return {"engine": "llm", "application": text}
        except Exception as exc:
            logger.warning("LLM drafting failed: %s", exc)
    grounds = "; ".join(f"Section {g['clause']} - {g['ground']}" for g in eligibility["grounds"]) or "[ground of eligibility]"
    text = f"""To,
The Member Secretary / Secretary,
{eligibility['where_to_apply']}

Subject: Application for free legal services under Sections 12 and 13 of the Legal Services Authorities Act, 1987

Respected Sir/Madam,

1. That I, [Name of applicant], residing at [address], am entitled to free legal services under {grounds}.

2. That the brief facts of my legal problem are as follows: {problem.strip() or '[describe the problem]'}

3. That the matter is {('pending as ' + applicant['case_number']) if applicant.get('case_number') else '[pending before / to be filed in]'} [name of court].

4. That I am unable to engage a lawyer on my own and require legal assistance to protect my rights.

PRAYER
It is therefore respectfully prayed that a panel lawyer may kindly be assigned to me free of cost, and that such other legal services as are necessary may be provided.

VERIFICATION
I, [Name of applicant], do hereby verify that the contents of this application are true to my knowledge and belief.

Place: [place]
Date: [date]                                                    Signature / Thumb impression of applicant
"""
    text = llm.enforce_language([text], language)[0]
    return {"engine": "template", "application": text}


EXPLAIN_SYSTEM = """You explain a free-legal-aid eligibility result to an ordinary person exclusively in the selected
language {language}, regardless of the language in which the user wrote. Do not code-switch or include an English translation.
The DECISION below was made by the rules of Section 12, Legal Services Authorities Act, 1987: never change it,
never promise a lawyer, never predict a case. Use ONLY the decision facts and the numbered PASSAGES; cite passages
you used as [1], [2]. Plain words, short sentences, no markdown headings.
Return: answer (4-7 sentences: what the result means for this person and why), next_steps (3-5 short concrete
steps), used (the passage numbers you relied on)."""


class Explanation(BaseModel):
    answer: str = ""
    next_steps: List[str] = []
    used: List[int] = []


QUESTION_SYSTEM = """Answer an Indian legal-information question exclusively in the selected language {language},
regardless of the language in which the user wrote, using ONLY the numbered sources. Do not code-switch or include an English translation.
Do not invent laws, citations, dates or procedures. Do not promise outcomes or give personalized legal advice.
Say clearly when sources do not answer the question; advise contacting the DLSA or helpline 15100 when needed.
If an uploaded document is included, distinguish what it says from general legal information.
Use short, plain sentences and cite every factual claim with [n].
Return answer (concise, useful response) and used (the numbered sources you relied on)."""


class QuestionAnswer(BaseModel):
    answer: str = ""
    used: List[int] = []


class FollowupLimitReached(ValueError):
    pass


def _prune_followup_sessions(now: float) -> None:
    while _followup_sessions:
        _, (_, last_seen) = next(iter(_followup_sessions.items()))
        if now - last_seen <= _FOLLOWUP_SESSION_TTL:
            break
        _followup_sessions.popitem(last=False)


def followups_used(session_id: str) -> int:
    now = time.monotonic()
    with _followup_lock:
        _prune_followup_sessions(now)
        entry = _followup_sessions.get(session_id)
        if entry is None:
            return 0
        _followup_sessions.move_to_end(session_id)
        return entry[0]


def record_followup(session_id: str) -> int:
    """Count a successfully answered question without retaining its text or documents."""
    now = time.monotonic()
    with _followup_lock:
        _prune_followup_sessions(now)
        count = _followup_sessions.get(session_id, (0, now))[0]
        if count >= MAX_FOLLOWUPS:
            raise FollowupLimitReached(f"This session has reached its {MAX_FOLLOWUPS}-question follow-up limit.")
        _followup_sessions[session_id] = (count + 1, now)
        _followup_sessions.move_to_end(session_id)
        while len(_followup_sessions) > _MAX_TRACKED_FOLLOWUP_SESSIONS:
            _followup_sessions.popitem(last=False)
        return count + 1


def _document_excerpt(question: str, document_text: str) -> str:
    stop = {"what", "does", "this", "that", "about", "tell", "show", "say", "says", "mean", "please", "explain",
            "document", "order", "from", "with", "your"}
    terms = {word for word in re.findall(r"[a-z0-9]{3,}", question.lower()) if word not in stop}
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|\n", document_text)
                  if part.strip() and not part.strip().startswith("[")]
    if not paragraphs:
        return ""
    ranked = sorted(paragraphs, key=lambda part: len(terms & set(re.findall(r"[a-z0-9]{3,}", part.lower()))),
                    reverse=True)
    return ranked[0][:600]


def answer_question(question: str, language: str = "English", document_text: str = "",
                    document_name: str = "Uploaded document", search=None, web_search=None) -> Dict:
    """Answer from the local legal-aid index first; consult trusted official web sources only when it has no hit."""
    question = (question or "").strip()[:1500]
    if not question:
        raise ValueError("Enter a legal-aid question.")

    from . import legal_aid_kb, websearch
    kb = (search or legal_aid_kb.search)(question, 4)
    passages = kb.get("passages") or []
    web = None
    if not passages:
        web = (web_search or websearch.search)(question, max_results=4, trusted_only=True)

    sources = []
    if document_text.strip():
        sources.append({"n": 1, "heading": document_name, "source_url": None, "authority": "uploaded document",
                        "last_verified": None, "text": document_text.strip()[:12000]})
    for passage in passages:
        sources.append({"n": len(sources) + 1, "heading": passage.get("heading") or "Legal-aid guide",
                        "source_url": passage.get("source_url"), "authority": passage.get("authority") or "unknown",
                        "last_verified": passage.get("last_verified"), "text": passage.get("text", "")[:1200]})
    web_source_start = len(sources) + 1
    if web:
        for result in web.get("results") or []:
            sources.append({"n": len(sources) + 1, "heading": result.get("title") or "Official web result",
                            "source_url": result.get("url"), "authority": "official web search",
                            "last_verified": None, "text": result.get("content", "")[:1200]})

    out = {"answer": "", "engine": "rules", "used": [], "sources": sources,
           "knowledge_engine": kb.get("engine"), "web_search_used": web is not None,
           "web_search_error": web.get("error") if web else None,
           "secondary_only_note": kb.get("secondary_only_note"),
           "disclaimer": DISCLAIMER}
    if llm.available() and sources:
        numbered = "\n\n".join(f"[{s['n']}] {s['heading']} ({s['authority']}; {s.get('source_url') or 'user-provided'})\n"
                               f"{s['text']}" for s in sources)
        try:
            answer = llm.structured(
                QUESTION_SYSTEM.replace("{language}", language or "English"),
                f"<question>{question}</question>\n<sources>\n{numbered}\n</sources>",
                QuestionAnswer, fast=True, max_tokens=900)
            used = [n for n in answer.used if 1 <= n <= len(sources)]
            if answer.answer.strip():
                localized = llm.enforce_language([answer.answer.strip()], language)[0]
                return {**out, "answer": localized, "engine": "llm", "used": used}
        except Exception as exc:
            logger.warning("legal-aid question answer by LLM failed (%s); using retrieved sources", type(exc).__name__)

    excerpt = _document_excerpt(question, document_text) if document_text.strip() else ""
    if excerpt:
        out["answer"] = f"The uploaded document says: {excerpt} [1]. Check the original document before acting."
        out["used"] = [1]
    elif web and web.get("answer"):
        web_numbers = list(range(web_source_start, len(sources) + 1))
        citations = " ".join(f"[{number}]" for number in web_numbers)
        out["answer"] = (f"{web['answer']} {citations}" if citations
                         else f"{web['answer']} (Online results returned no source links.)")
        out["used"] = web_numbers
    elif passages:
        source_number = 1 + bool(document_text.strip())
        out["answer"] = (f"Relevant information from the local legal-aid guide: "
                         f"{passages[0].get('text', '')[:700]} [See source {source_number} below.]")
        out["used"] = [source_number]
    elif document_text.strip():
        out["answer"] = ("I could not find a matching legal-aid guide or official web source. "
                         "The uploaded document is available for review; contact the DLSA or call 15100 for guidance.")
        out["used"] = [1]
    else:
        out["answer"] = ("I could not find a matching legal-aid guide or official web source for this question. "
                         "Please contact your District Legal Services Authority or call 15100.")
    out["answer"] = llm.enforce_language([out["answer"]], language)[0]
    return out


KB_WORDS = [  # eligibility ground -> the words the legal-aid guides use for it (helps the offline keyword search)
    ("woman", "woman women child entitled section 12"), ("child", "woman child entitled age apply"),
    ("scheduled", "member scheduled caste scheduled tribe entitled"), ("disab", "disabled disability entitled"),
    ("custody", "custody protective home entitled criminal matters"), ("trafficking", "victim trafficking begar"),
    ("disaster", "victim mass disaster ethnic violence caste atrocity flood drought earthquake"),
    ("industrial", "industrial workman"), ("income", "income ceiling limit eligibility criteria"),
]


def kb_query(eligibility: Dict, problem: str = "") -> str:
    """Search words for the knowledge index from the decision (grounds, missing facts) and the person's words."""
    words = []
    for g in eligibility.get("grounds") or []:
        ground = g["ground"].lower()
        words += [w for key, w in KB_WORDS if key in ground] or [g["ground"]]
    words += [m.replace("_", " ") for m in eligibility.get("missing_facts") or []]
    if eligibility.get("outcome") == "not_on_facts_given":
        words.append("income ceiling limit eligibility criteria")
    if not eligibility.get("grounds"):
        words.append("who are entitled to free legal services")
    return " ".join(w for w in words + [problem[:300]] if w)


def explain(eligibility: Dict, problem: str = "", language: str = "English", search=None) -> Dict:
    """The rules' decision explained with indexed passages and current relevant legal_info.html entries.
    One fast model call; a template answer from the same decision when no model is available or it fails."""
    from . import legal_aid_kb
    query = kb_query(eligibility, problem)
    kb = (search or legal_aid_kb.search)(query, 4)
    passages = list(kb.get("passages") or [])
    legal_info_query = f"free legal aid eligibility Section 12 {query}"
    for passage in legal_aid_kb.search_legal_info(legal_info_query, 3):
        if not any(existing.get("heading") == passage.get("heading")
                   and existing.get("source_url") == passage.get("source_url") for existing in passages):
            passages.append(passage)
    sources = [{"n": i + 1, "heading": p.get("heading"), "source_url": p.get("source_url"), "authority": p.get("authority"),
                "last_verified": p.get("last_verified")} for i, p in enumerate(passages)]
    out = {"engine": "template", "sources": sources, "kb_engine": kb.get("engine"),
           "secondary_only_note": kb.get("secondary_only_note"), "disclaimer": DISCLAIMER}
    if llm.available():
        decision = {k: eligibility.get(k) for k in ("outcome_label", "grounds", "missing_facts", "income_limit_note",
                                                    "where_to_apply", "documents_needed", "state")}
        numbered = "\n\n".join(f"[{s['n']}] {p.get('heading') or ''}\n{p['text'][:900]}" for s, p in zip(sources, passages))
        try:
            e = llm.structured(EXPLAIN_SYSTEM.replace("{language}", language or "English"),
                               f"<decision>\n{decision}\n</decision>\n<problem>{problem[:600]}</problem>\n"
                               f"<passages>\n{numbered or '(none found)'}\n</passages>", Explanation, fast=True, max_tokens=900)
            if e.answer.strip():
                used = [n for n in e.used if 1 <= n <= len(sources)]
                localized = llm.enforce_language([e.answer.strip(), *(e.next_steps[:5] or eligibility["next_steps"])],
                                                 language)
                return {**out, "engine": "llm", "answer": localized[0], "next_steps": localized[1:], "used": used}
        except Exception as exc:
            logger.warning("legal-aid explanation by LLM failed (%s); using the template", type(exc).__name__)
    lead = {"likely_eligible": "On what you told us, you are likely entitled to a free lawyer",
            "possibly_eligible": "You may be entitled to a free lawyer; a few facts are still needed",
            "not_on_facts_given": "On what you told us, you do not fall in a free-legal-aid category"}[eligibility["outcome"]]
    why = "; ".join(f"Section {g['clause']} - {g['ground']}" for g in eligibility.get("grounds") or [])
    answer = f"{lead}{(' (' + why + ')') if why else ''}. {eligibility.get('income_limit_note') or ''}".strip()
    if passages:
        answer += f" More: {passages[0].get('heading') or 'see source'} [1]."
    next_steps = eligibility.get("next_steps") or []
    localized = llm.enforce_language([answer, *next_steps], language)
    return {**out, "answer": localized[0], "next_steps": localized[1:], "used": [1] if passages else []}


FACTS_SYSTEM = """Write ONE short paragraph (3-5 sentences, first person, formal and simple English) stating the
applicant's legal problem for a free legal aid application. Use ONLY the facts given; do not add names, dates,
places, sections or events that are not in them. Write [to be filled] for anything needed but not given. No markdown."""


def facts_paragraph(problem: str) -> Dict:
    """Short facts paragraph for the application: LLM from the stated facts only, else a template sentence."""
    problem = (problem or "").strip()
    if problem and llm.available():
        try:
            return {"engine": "llm", "text": llm.text(FACTS_SYSTEM, problem, fast=True).strip()}
        except Exception as exc:
            logger.warning("facts paragraph by LLM failed: %s", exc)
    text = (f"The brief facts of my legal problem are as follows: {problem}" if problem
            else "The brief facts of my legal problem are: [to be filled].")
    return {"engine": "template", "text": text}
