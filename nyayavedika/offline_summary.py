"""Extractive (offline) case-document summariser - the fallback path of the Document Analyst agent.

The LLM path lives in nyayavedika/agents/document_analyst.py (map -> synthesize -> verify loop).
Output keys mirror schemas.CaseAnalysis so the UI renders either engine identically.
"""
import re
from typing import Dict, List

from .documents import is_legal_document, split_paragraphs


def summarize(text: str, language: str = "English") -> Dict:
    """Heuristic summary of a case document (no network)."""
    text = text.strip()
    if not text:
        raise ValueError("Document is empty")
    result = heuristic_summary(text)
    result.update(engine="heuristic", characters=len(text), is_legal_document=is_legal_document(text))
    return result


# ---------------------------------------------------------------------------
# Heuristic (offline) extractive summariser
# ---------------------------------------------------------------------------

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_RE = re.compile(
    rf"\b(\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{2,4}}|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTHS}),?\s+\d{{4}}|(?:{MONTHS})\s+\d{{1,2}},\s+\d{{4}})\b",
    re.I)
STATUTE_RE = re.compile(
    r"\b(?:Section|Sec\.|S\.|Article|Order|Rule)\s*\d+[A-Z]?(?:\(\w+\))*(?:\s*(?:and|,|/)\s*\d+[A-Z]?(?:\(\w+\))*)*"
    r"(?:\s+of\s+(?:the\s+)?[A-Z][A-Za-z.,()\s]*?(?:Act|Code|Sanhita|Adhiniyam|Constitution)(?:,?\s*\d{4})?)?")
ACT_RE = re.compile(r"\b(?:the\s+)?([A-Z][A-Za-z.()\s]{2,60}?(?:Act|Code|Sanhita|Adhiniyam)(?:,\s*\d{4})?)")
PRECEDENT_RE = re.compile(r"\b[A-Z][\w.&\s]{2,60}?\s+v(?:s)?\.?\s+[A-Z][\w.&\s]{2,60}?[,(]\s*(?:\(?\d{4}\)?\s*)?\d*\s*(?:SCC|AIR|SCR|INSC|CriLJ)[^.;]{0,30}")
OUTCOME_WORDS = {  # checked in order - more specific phrases first
    "partly allowed": "Partly allowed", "partially allowed": "Partly allowed", "allowed": "Allowed", "dismissed": "Dismissed", "disposed of": "Disposed of", "acquitted": "Acquitted",
    "convicted": "Convicted", "set aside": "Set aside", "remanded": "Remanded", "bail is granted": "Bail granted",
    "granted bail": "Bail granted", "bail is rejected": "Bail rejected", "quashed": "Quashed",
}
SIGNAL_WORDS = ["held", "therefore", "accordingly", "we find", "it is clear", "consider", "whether",
                "directed", "submitted", "contended", "observed", "conclude", "issue", "question"]


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+(?=[A-Z(\"'])", text) if s.strip()]


def _date_key(raw: str):
    """Sortable (y, m, d) for the date formats DATE_RE matches; unknowns sort last."""
    nums = re.findall(r"\d+", raw)
    month_names = MONTHS.lower().split("|")
    named = next((i + 1 for i, mname in enumerate(month_names) if mname in raw.lower()), None)
    try:
        if named:
            return (int(nums[-1]), named, int(nums[0]))
        d, mth, y = (int(n) for n in nums[:3])
        return (y + 2000 if y < 100 else y, mth, d)
    except (ValueError, IndexError):
        return (9999, 0, 0)


def _para_ref(paragraph: str, index: int) -> str:
    m = re.match(r"\s*(\d{1,3})\.\s", paragraph)
    return f"Para {m.group(1)}" if m else f"Para {index + 1}"


def heuristic_summary(text: str) -> Dict:
    paragraphs = split_paragraphs(text)
    lower = text.lower()

    timeline = []
    for i, para in enumerate(paragraphs):
        for sent in _sentences(para):
            m = DATE_RE.search(sent)
            if m and len(timeline) < 25:
                timeline.append({"date": m.group(1), "event": sent[:260], "para_reference": _para_ref(para, i)})
                break
    timeline.sort(key=lambda t: _date_key(t["date"]))

    issues = []
    for i, para in enumerate(paragraphs):
        # Framed points for determination: "Whether ...?" clauses, even when enumerated inline as (i), (ii)
        for m in re.finditer(r"\bWhether\b[^?]{10,400}\?", para):
            issues.append({"issue": m.group(0).strip(), "key_points": [], "decision": None, "para_reference": _para_ref(para, i)})
    if not issues:
        for i, para in enumerate(paragraphs):
            for sent in _sentences(para):
                if re.search(r"\b(?:question|issue)s?\s+(?:that\s+)?(?:arises?|for (?:our )?consideration)", sent, re.I):
                    issues.append({"issue": sent[:300], "key_points": [], "decision": None, "para_reference": _para_ref(para, i)})
    issues = issues[:8]

    statutes = sorted({re.sub(r"\s+", " ", m.group(0)).strip(" ,.") for m in STATUTE_RE.finditer(text)})[:25]
    acts = sorted({re.sub(r"\s+", " ", m.group(1)).strip() for m in ACT_RE.finditer(text)})[:15]
    precedents = sorted({re.sub(r"\s+", " ", m.group(0)).strip(" ,.") for m in PRECEDENT_RE.finditer(text)})[:15]

    tail = lower[-max(1500, len(lower) // 5):]
    outcome = next((label for word, label in OUTCOME_WORDS.items() if word in tail), None)

    directions = []
    for sent in _sentences(" ".join(paragraphs[-6:])):
        if re.search(r"\b(directed|shall|within\s+\w+\s+(?:days|weeks|months)|list(?:ed)? (?:on|after))\b", sent, re.I):
            directions.append(re.sub(r"\s+\d{1,3}\.$", "", sent)[:260])

    # Extractive key points: highest-signal paragraphs, in document order
    scored = []
    for i, para in enumerate(paragraphs):
        if len(para) < 60 or (issues and "whether" in para.lower()):  # issue paragraphs are already shown
            continue
        score = sum(para.lower().count(w) for w in SIGNAL_WORDS) + (2 if i >= len(paragraphs) * 0.7 else 0)
        scored.append((score, i, para))
    top = sorted(sorted(scored, reverse=True)[:5], key=lambda x: x[1])
    key_points = [p[:400] + ("..." if len(p) > 400 else "") for _, _, p in top]

    if issues and outcome:
        for issue in issues:
            issue["decision"] = outcome
    if issues:
        issues[0]["key_points"] = key_points[:3]

    case_details = _heuristic_case_details(text)
    plain = _plain_summary(case_details, outcome, timeline, issues, directions)

    return {
        "case_details": case_details,
        "document_type": "judgment" if re.search(r"\bjudg(e)?ment\b", lower) else "other",
        "timeline": timeline,
        "issues": issues,
        "key_points": key_points,
        "statutes_cited": statutes or acts,
        "acts_referenced": acts,
        "precedents_cited": precedents,
        "outcome": outcome,
        "directions_and_deadlines": directions[:6],
        "plain_language_summary": plain,
        "triage_signals": {
            "custody": bool(re.search(r"\b(in (?:judicial )?custody|undertrial|in jail since)\b", lower)),
            "bail_matter": "bail" in lower,
            "senior_citizen_party": bool(re.search(r"senior citizen|aged (?:about )?(?:[6-9]\d) years", lower)),
            "woman_or_child_party": bool(re.search(r"\b(minor|child|widow|wife|woman|girl)\b", lower)),
            "compoundable_or_settleable": bool(re.search(r"138 of the negotiable|compromise|settlement|mediation|lok adalat|compoundable", lower)),
            "urgency_reason": None,
        },
    }


def _heuristic_case_details(text: str) -> Dict:
    head = text[:4000]
    case_no = re.search(r"\b((?:W\.P\.|Writ Petition|Crl\.?\s?A\.|Criminal Appeal|Civil Appeal|C\.A\.|O\.S\.|Bail Appl(?:ication)?\.?|CRL\.M\.C\.|S\.A\.|M\.A\.C\.T\.|C\.C\.)\s*(?:\(\w+\)\s*)?(?:No\.?\s*)?\d+\s*(?:/|of)\s*\d{4})", head, re.I)
    court = re.search(r"\b(?:IN THE\s+)?((?:SUPREME COURT OF INDIA|HIGH COURT OF [A-Z ]+|HIGH COURT AT [A-Z ]+|COURT OF THE [A-Z ,]+|[A-Z ]*(?:DISTRICT|SESSIONS|FAMILY) COURT[A-Z ,]*))", head, re.I)
    pet = re.findall(r"^\s*(.{3,80}?)\s*\.{2,}\s*(?:Petitioner|Appellant|Applicant|Complainant)s?\b", head, re.M | re.I)
    res = re.findall(r"^\s*(.{3,80}?)\s*\.{2,}\s*(?:Respondent|Accused|Opposite Part(?:y|ies))s?\b", head, re.M | re.I)
    if not pet:
        vs = re.search(r"([A-Z][\w.& ]{2,60}?)\s+(?:vs?\.?|versus)\s+([A-Z][\w.& ]{2,60})", head)
        if vs:
            pet, res = [vs.group(1).strip()], [vs.group(2).strip()]
    judges = re.findall(r"(?:HON'?BLE|CORAM:?)\s*(?:MR\.|MS\.|MRS\.)?\s*(?:JUSTICE\s+)?([A-Z][A-Z. ]{3,40})", head)
    date = re.search(r"(?:Date of (?:Judgment|Order|Decision)|Dated|Pronounced on)\s*[:\-]?\s*" + DATE_RE.pattern, head, re.I)
    return {
        "case_number": case_no.group(1).strip() if case_no else None,
        "court_name": court.group(1).strip().title() if court else None,
        "petitioners": [p.strip(" .,") for p in pet][:5],
        "respondents": [r.strip(" .,") for r in res][:5],
        "judges": [j.strip().title() for j in judges][:3],
        "date_of_order": date.group(1) if date else None,
    }


def _plain_summary(details, outcome, timeline, issues, directions) -> str:
    parts = []
    pet = ", ".join(details.get("petitioners") or []) or "the petitioner"
    res = ", ".join(details.get("respondents") or []) or "the respondent"
    court = details.get("court_name") or "the court"
    parts.append(f"This is a case between {pet} and {res} before {court}.")
    if timeline:
        parts.append(f"The dispute goes back to {timeline[0]['date']}.")
    if issues:
        parts.append(f"The court had to decide {len(issues)} main question(s), starting with: "
                     f"{issues[0]['issue'][:180].rstrip('.')}.")
    parts.append(f"Result: {outcome}." if outcome else "The final outcome could not be identified automatically - read the last paragraphs.")
    if directions:
        parts.append(f"Next steps ordered by the court: {directions[0][:200]}")
    parts.append("(Auto-generated extractive summary - configure a language model for a fuller plain-language explanation.)")
    return " ".join(parts)
