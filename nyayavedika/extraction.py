"""Uploaded document -> canonical case fields.

    classify doc type -> extract CaseDraft (LLM, else rules) -> normalise (ISO dates, enums, statute_ref)
    -> validate (missing / low confidence -> needs_review, value NOT used) -> case row + provenance
    -> provisional score (unknown custody on a criminal matter = possible custody, never scored low)

Code decides, LLM talks: the LLM only proposes field values with a confidence; every LLM date and
section must literally occur in the source or it is dropped. Without an LLM key the regex rules run
and the output is labelled engine="rules".
"""
import logging
import re
from datetime import date
from typing import Dict, List, Optional, Tuple, Union

from pydantic import BaseModel

from . import config, llm, store, triage

logger = logging.getLogger(__name__)

CRIMINAL = ("criminal_trial", "criminal_appeal", "bail", "habeas_corpus")
DOC_TYPES = ("fir", "order", "petition", "bail_custody", "other")
DATE = r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})"
SECTION = r"(\d+[A-Z]?(?:\([0-9a-zA-Z]+\))*)"


class DraftField(BaseModel):
    value: Optional[Union[bool, float, str]] = None
    confidence: float = 0.0
    page: Optional[int] = None
    evidence: str = ""


class CaseDraft(BaseModel):
    """One entry per cases column the document can tell us about, each with a confidence 0-1."""
    case_number: DraftField = DraftField()
    case_type: DraftField = DraftField()
    stage: DraftField = DraftField()
    filing_date: DraftField = DraftField()
    accused_in_custody: DraftField = DraftField()
    custody_since: DraftField = DraftField()
    first_time_offender: DraftField = DraftField()
    act: DraftField = DraftField()
    section: DraftField = DraftField()
    senior_citizen: DraftField = DraftField()
    woman_or_child: DraftField = DraftField()
    disability: DraftField = DraftField()
    next_hearing_date: DraftField = DraftField()
    status: DraftField = DraftField()   # "disposed" when the document itself decides the matter; else left empty (pending)


FIELDS = list(CaseDraft.model_fields)
DATE_FIELDS = ("filing_date", "custody_since", "next_hearing_date")


# ----------------------------------------------------------------------------- helpers
def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text or "")


def _iso(d: str, m: str, y: str) -> Optional[str]:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def _search(pages: List[Dict], pattern: str, flags=re.I) -> Tuple[Optional[re.Match], Optional[int]]:
    for p in pages:
        m = re.search(pattern, _collapse(p["text"]), flags)
        if m:
            return m, p["page"]
    return None, None


def _field(value, confidence: float, page: Optional[int], match: Optional[re.Match]) -> DraftField:
    return DraftField(value=value, confidence=confidence, page=page, evidence=(match.group(0)[:160] if match else ""))


ACT_NAMES = {
    "bns": "BNS", "bharatiya nyaya sanhita": "BNS", "bnss": "BNSS", "bharatiya nagarik suraksha sanhita": "BNSS",
    "ipc": "IPC", "indian penal code": "IPC", "crpc": "CrPC", "code of criminal procedure": "CrPC",
    "ndps act": "NDPS Act", "narcotic drugs and psychotropic substances act": "NDPS Act",
    "ni act": "NI Act", "negotiable instruments act": "NI Act", "arms act": "Arms Act",
    "pocso act": "POCSO Act", "protection of children from sexual offences act": "POCSO Act",
}
# Procedure, not the offence: FIR heading, bail and release provisions.
PROCEDURAL = {("BNSS", "173"), ("BNSS", "479"), ("BNSS", "480"), ("BNSS", "482"), ("BNSS", "483"), ("CrPC", "154"),
              ("CrPC", "436A"), ("CrPC", "437"), ("CrPC", "438"), ("CrPC", "439")}


def canonical_act(name: str) -> str:
    key = re.sub(r"\s+", " ", re.sub(r"(?i)^the\s+|,?\s*\d{4}$", "", (name or "").strip())).lower().strip(" .,")
    return ACT_NAMES.get(key, (name or "").strip())


def _base(section: str) -> str:
    return re.split(r"\(", section, maxsplit=1)[0]


# ----------------------------------------------------------------------------- doc type
def classify_doc_type(first_page: str) -> str:
    t = _collapse(first_page).lower()
    if "first information report" in t or re.search(r"\bfir no\b", t):
        return "fir"
    if re.search(r"custody certificate|application for (?:regular |anticipatory )?bail|bail application", t):
        return "bail_custody"
    if re.search(r"\border sheet\b|\border \(pronounced|\bjudg(?:e)?ments?\b|this court made the following|\bproceedings dated\b|case record|^order\b", t):
        return "order"
    if re.search(r"\bpetition\b|\bcomplaint under\b|\bprayer\b", t):
        return "petition"
    return "other"


# ----------------------------------------------------------------------------- rules (offline) extractor
STAGE_WORDS = {"prosecution evidence": "evidence", "defence evidence": "evidence", "evidence": "evidence",
               "arguments": "arguments", "charge": "charge", "framing of issues": "framing_of_issues",
               "judgment reserved": "judgment_reserved", "pronouncement": "pronouncement", "admission": "admission",
               "notice": "notice", "pleadings": "pleadings", "execution": "execution"}


def _offences(pages: List[Dict]) -> List[Tuple[str, str, int, re.Match]]:
    """(act, section, page, match) candidates in document order, procedural sections removed."""
    acts = r"BNSS|BNS|IPC|CrPC|NDPS Act|NI Act|Arms Act|POCSO Act"
    patterns = [rf"\b({acts})\s+(?:Section|Sec\.?|S\.)\s*{SECTION}",
                rf"\b(?:Section|Sec\.?)\s*{SECTION}\s+of\s+the\s+([A-Z][A-Za-z ]+?(?:Act|Sanhita|Code))",
                rf"\b(?:Section|Sec\.?)\s*{SECTION}\s+({acts})\b"]
    found = []
    for p in pages:
        text = _collapse(p["text"])
        for i, pat in enumerate(patterns):
            for m in re.finditer(pat, text, re.I):
                act, sec = (m.group(1), m.group(2)) if i == 0 else (m.group(2), m.group(1))
                act = canonical_act(act)
                if (act, _base(sec)) not in PROCEDURAL:
                    found.append((p["page"], m.start(), act, sec, m))
    found.sort(key=lambda f: (f[0], f[1]))
    return [(act, sec, page, m) for page, _, act, sec, m in found]


def _case_type(text: str, doc_type: str) -> Tuple[Optional[str], float]:
    t = text.lower()
    rules = [("habeas_corpus", r"habeas corpus|preventive detention|order of detention|detention order|"
                               r"boot-?leggers.{0,120}\bact\b|cofeposa|national security act"),
             ("cheque_bounce", r"negotiable instruments act|section 138 ni act|ni act section 138"),
             ("maintenance", r"maintenance.{0,200}(?:section 144|nagarik suraksha|section 125)|(?:section 144|section 125).{0,200}maintenance"),
             ("bail", r"\(bail\)|application for (?:regular |anticipatory )?bail|bail petition"),
             ("criminal_appeal", r"criminal appeal|appeal against (?:conviction|acquittal)"),
             ("criminal_trial", r"sessions case|charge ?sheet|first information report|undertrial|\b(?:bns|ipc|ndps)\b")]
    for ctype, pat in rules:
        if re.search(pat, t):
            return ctype, 0.85
    guess = triage.classify_free_text(text[:3000])["case_type"]
    return (guess, 0.5) if guess != "other" else (None, 0.0)


def rules_draft(pages: List[Dict], doc_type: str) -> CaseDraft:
    text = _collapse("\n".join(p["text"] for p in pages))
    d = CaseDraft()
    ctype, conf = _case_type(text, doc_type)
    if ctype:
        d.case_type = DraftField(value=ctype, confidence=conf, page=1, evidence=f"document wording ({doc_type})")

    m, pg = _search(pages, r"\bstage(?: of)?\s*[:\-]?\s*(prosecution evidence|defence evidence|evidence|arguments|charge|"
                           r"framing of issues|judgment reserved|pronouncement|admission|notice|pleadings|execution)\b")
    if m:
        d.stage = _field(STAGE_WORDS[m.group(1).lower()], 0.9, pg, m)
    elif doc_type == "order":
        m, pg = _search(pages, r"order \(pronounced|petition is allowed|bail is granted|is dismissed|is rejected")
        if m:
            d.stage = _field("pronouncement", 0.7, pg, m)
    elif doc_type in ("fir", "petition", "bail_custody"):
        d.stage = DraftField(value="admission", confidence=0.6, page=1, evidence=f"new {doc_type}: first listing")

    m, pg = _search(pages, rf"(?:date of fir|filed on|date of filing|instituted on|date of institution)\s*[:\-]?\s*{DATE}")
    if m:
        d.filing_date = _field(_iso(*m.groups()[-3:]), 0.9, pg, m)

    # A decided matter (writ / appeal / revision allowed, dismissed or disposed of) is no longer a pending hearing.
    disposed, dpg = _search(pages, r"\b(?:writ petition|writ appeal|criminal appeal|criminal revision|revision|appeal|petition)\s+"
                                   r"(?:is|stands)\s+(?:hereby\s+)?(?:allowed|dismissed|disposed of)\b")
    liberty, lpg = _search(pages, r"\bset (?:at liberty|free)\b|\breleased forthwith\b|\bshall be released\b")
    if disposed and doc_type == "order":
        d.status = _field("disposed", 0.85, dpg, disposed)
    m, pg = _search(pages, r"(?:in|to) judicial custody|undertrial prisoner|in jail since|lodged in")
    if disposed and liberty and doc_type == "order":
        d.accused_in_custody = _field(False, 0.8, lpg, liberty)   # the order itself ends the custody
    elif m:
        d.accused_in_custody = _field(True, 0.85, pg, m)
    else:
        m, pg = _search(pages, r"not (?:been )?arrested|not in custody|anticipatory bail")
        if m:
            d.accused_in_custody = _field(False, 0.8, pg, m)
    m, pg = _search(pages, rf"custody[^.]{{0,80}}?(?:since|from)\s+{DATE}|remanded to judicial custody on\s+{DATE}")
    if m:
        g = [x for x in m.groups() if x]
        d.custody_since = _field(_iso(*g[-3:]), 0.85, pg, m)
    m, pg = _search(pages, r"first[- ]time (?:accused|offender)")
    if m:
        d.first_time_offender = _field(True, 0.8, pg, m)

    offences = _offences(pages)
    if offences:
        act, sec, pg, m = offences[0]
        d.act = _field(act, 0.85, pg, m)
        d.section = _field(sec, 0.85, pg, m)

    m, pg = _search(pages, r"(FIR No\.?:?\s*[\w/]+|(?:Sessions Case|S\.C\.|M\.C\.|Crl\.\s*M\.P\.|Criminal Miscellaneous "
                           r"Petition|C\.C\.|O\.S\.)\s*No\.?\s*\d+\s*(?:of|/)\s*\d{4})")
    if m:
        d.case_number = _field(m.group(1), 0.8, pg, m)
    m, pg = _search(pages, rf"(?:adjourned to|call on|next date\s*[:\-]?|listed on)\s*{DATE}")
    if m:
        d.next_hearing_date = _field(_iso(*m.groups()[-3:]), 0.8, pg, m)
    m, pg = _search(pages, r"aged (?:about )?[6-9]\d\b|senior citizen")
    if m:
        d.senior_citizen = _field(True, 0.6, pg, m)
    # In a detention writ the wife / mother is the petitioner, not the person in custody: no vulnerable-party flag.
    relative_words = "smt\\.|minor|child|widow|woman|girl" if ctype == "habeas_corpus" else "smt\\.|minor|child|widow|wife|woman|girl|daughter"
    m, pg = _search(pages, rf"\b(?:{relative_words})\b")
    if m:
        d.woman_or_child = _field(True, 0.6, pg, m)
    m, pg = _search(pages, r"\b(?:disabled|disability|blind|deaf)\b")
    if m:
        d.disability = _field(True, 0.6, pg, m)
    return d


# ----------------------------------------------------------------------------- LLM extractor + grounding
EXTRACT_SYSTEM = f"""You extract case facts from an Indian court document for the registry.
Fill each field with: value, confidence (0-1), page (1-based) and a short verbatim evidence quote.
Use ONLY the document. If a fact is not stated, leave value null and confidence 0. Never infer a date.
case_type: one of {triage.CASE_TYPES}. stage: one of {list(triage.STAGE_MINUTES)}.
Dates as YYYY-MM-DD. act: short name (BNS, BNSS, IPC, NDPS Act, NI Act ...); section: as written, e.g. 303(2).
filing_date = date of FIR / filing / institution. custody_since = date judicial custody began."""


def _date_grounded(iso_value: str, text: str) -> bool:
    try:
        y, m, d = (int(x) for x in str(iso_value).split("-"))
    except ValueError:
        return False
    return bool(re.search(rf"\b0?{d}[./-]0?{m}[./-]{y}\b", text) or str(iso_value) in text)


def ground(draft: CaseDraft, text: str) -> CaseDraft:
    """Drop LLM values that do not literally occur in the source (dates, section numbers, acts)."""
    flat = _collapse(text)
    for name in FIELDS:
        f = getattr(draft, name)
        if f.value in (None, ""):
            continue
        ok = True
        if name in DATE_FIELDS:
            f.value = store._iso_date(f.value)
            ok = bool(f.value) and _date_grounded(f.value, flat)
        elif name == "section":
            ok = bool(re.search(rf"\b{re.escape(_base(str(f.value)))}\b", flat))
        elif name == "act":
            f.value = canonical_act(str(f.value))
        if not ok:
            setattr(draft, name, DraftField(evidence=f"dropped: '{f.value}' not found in source"))
    return draft


def llm_draft(text: str, doc_type: str) -> Optional[CaseDraft]:
    if not llm.available():
        return None
    try:
        out = llm.structured(EXTRACT_SYSTEM, f"<document type='{doc_type}'>\n{text[:config.SINGLE_PASS_TOKENS * 4]}\n</document>",
                             CaseDraft, fast=True)
        return ground(out, text)
    except Exception as exc:
        logger.warning("LLM extraction failed, using rules: %s", exc)
        return None


def extract(pages: List[Dict], doc_type: Optional[str] = None, ai_draft: Union[CaseDraft, Dict, None] = None,
            use_llm: bool = True) -> Tuple[CaseDraft, str]:
    """Rules always run; a grounded LLM value replaces a rules value only when at least as confident.
    The worker passes the fields from its one document call as `ai_draft` (already grounded) with use_llm=False,
    so extraction makes no second model call."""
    doc_type = doc_type or classify_doc_type(pages[0]["text"] if pages else "")
    draft = rules_draft(pages, doc_type)
    if isinstance(ai_draft, dict):
        ai_draft = CaseDraft.model_validate(ai_draft)
    ai = ai_draft if ai_draft is not None else (llm_draft("\n\n".join(p["text"] for p in pages), doc_type) if use_llm else None)
    if ai is None:
        return draft, "rules"
    for name in FIELDS:
        a, r = getattr(ai, name), getattr(draft, name)
        if a.value not in (None, "") and a.confidence >= r.confidence:
            setattr(draft, name, a)
    return draft, "llm+rules"


# ----------------------------------------------------------------------------- normalise + validate
def required_fields(case: Dict) -> List[str]:
    if case.get("status") == "disposed":  # decided: nothing left to schedule, so no review chase
        return ["case_type"]
    req = ["case_type", "stage", "filing_date"]
    if case.get("case_type") in CRIMINAL:
        req += ["accused_in_custody", "act", "section"]
        if case.get("accused_in_custody"):
            req.append("custody_since")
    return req


def normalise(draft: CaseDraft, doc_id: str, db=None) -> Tuple[Dict, Dict, List[str]]:
    """-> (fields, provenance, review). Values below EXTRACT_MIN_CONFIDENCE are NOT used (listed for review)."""
    fields, prov, review = {}, {}, []
    for name in FIELDS:
        f = getattr(draft, name)
        value = f.value
        if name in DATE_FIELDS:
            value = store._iso_date(value)
        elif name == "case_type" and value not in triage.CASE_TYPES:
            value = None
        elif name == "stage" and value not in triage.STAGE_MINUTES:
            value = None
        elif name == "status" and value != "disposed":
            value = None
        if value in (None, ""):
            continue
        entry = {"doc_id": doc_id, "page": f.page, "confidence": round(f.confidence, 2), "evidence": f.evidence}
        if f.confidence < config.EXTRACT_MIN_CONFIDENCE:
            prov[name] = {**entry, "status": "low_confidence", "candidate": value}
            review.append(name)
            continue
        fields[name] = value
        prov[name] = entry
    if fields.get("act") and fields.get("section"):
        ref = store.statute(fields["act"], fields["section"], db=db)
        if ref:
            fields["act"], fields["section"] = ref["act"], ref["section"]
            fields["max_sentence_years"] = "life" if ref["life_or_death"] else ref["max_sentence_years"]
            fields["bailable"] = ref["bailable"]
            prov["max_sentence_years"] = {"source": "statute_ref", "act": ref["act"], "section": ref["section"],
                                          "note": ref["note"]}
        else:
            fields["section"] = _base(str(fields["section"]))
    return fields, prov, review


def missing_fields(case: Dict) -> List[str]:
    missing = [f for f in required_fields(case) if case.get(f) in (None, "")]
    if case.get("case_type") in CRIMINAL and case.get("act") and case.get("max_sentence_years") is None:
        missing.append("max_sentence_years")  # Act + section not in statute_ref: staff must confirm
    return missing


def provisional_score(case: Dict, today: Optional[date] = None) -> Dict:
    """Rules score; an unknown custody status on a criminal matter is scored as custody (Hard rule 3)."""
    probe = dict(case)
    unknown_custody = case.get("case_type") in CRIMINAL and case.get("accused_in_custody") is None
    if unknown_custody:
        probe["accused_in_custody"] = True
    r = triage.score_case(probe, today)
    if unknown_custody:
        r["flags"].append("CUSTODY_UNKNOWN")
        r["reasons"].append("Custody status not found in the papers - scored as possible custody until staff confirm")
    if case.get("data_quality") == "needs_review":
        r["flags"].append("NEEDS_REVIEW")
        r["reasons"].append("Needs review: " + ", ".join(case.get("review_fields") or []))
    return r


def brief(case: Dict, doc_type: str, today: Optional[date] = None) -> List[str]:
    """Three grounded lines built from the extracted fields (Phase 4 adds the AI brief)."""
    today = today or date.today()
    label = {"fir": "FIR", "order": "Order", "petition": "Petition", "bail_custody": "Bail / custody paper"}.get(doc_type, "Document")
    lines = [f"{label}: {(case.get('case_type') or 'type unknown').replace('_', ' ')}"
             + (f", {case['case_number']}" if case.get("case_number") else "")]
    if case.get("act") and case.get("section"):
        ms = case.get("max_sentence_years")
        if isinstance(ms, float) and ms.is_integer():
            ms = int(ms)
        lines.append(f"Offence: {case['act']} {case['section']}" + (f", maximum {ms}" + (" years" if ms != "life" else "")
                                                                       if ms is not None else ""))
    else:
        lines.append("Offence / provision: not identified")
    if case.get("accused_in_custody") and case.get("custody_since"):
        days = (today - date.fromisoformat(case["custody_since"])).days
        lines.append(f"Accused in custody since {case['custody_since']} ({days} days)")
    elif case.get("accused_in_custody") is None and case.get("case_type") in CRIMINAL:
        lines.append("Custody status unknown - treated as possible custody")
    else:
        lines.append(f"Stage: {(case.get('stage') or 'unknown').replace('_', ' ')}; filed {case.get('filing_date') or 'date unknown'}")
    return lines
