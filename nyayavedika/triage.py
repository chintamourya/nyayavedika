"""Case triage: priority scoring, red-flag detection and disposal-route recommendation.

The weights are transparent and editable (RULES below) so a registry can audit every score.
Free-text classification follows the court-classifier pattern in
backend-case-search-prod/workflow_agents/court_classifer.py (LLM -> strict JSON -> fallback).
"""
import logging
import math
import re
from datetime import date, datetime
from typing import Dict, List, Optional

from . import config, llm
from .models import IntakeClassification

logger = logging.getLogger(__name__)

CASE_TYPES = [
    "habeas_corpus", "bail", "criminal_trial", "criminal_appeal", "cheque_bounce", "motor_accident",
    "maintenance", "domestic_violence", "matrimonial", "child_custody", "civil_suit", "rent_eviction",
    "land_revenue", "commercial", "consumer", "labour", "service", "writ", "execution", "other",
]

# Base urgency by case type (0-30). Liberty and subsistence matters first.
TYPE_URGENCY = {
    "habeas_corpus": 30, "bail": 24, "child_custody": 18, "maintenance": 18, "domestic_violence": 18,
    "criminal_appeal": 12, "criminal_trial": 12, "motor_accident": 10, "labour": 10, "execution": 8,
    "rent_eviction": 6, "service": 6, "matrimonial": 8, "writ": 8, "consumer": 6, "cheque_bounce": 5,
    "commercial": 6, "civil_suit": 5, "land_revenue": 5, "other": 4,
}

# Matters that are typically settleable outside a full trial.
ADR_ROUTES = {
    "cheque_bounce": "Lok Adalat / compounding under Sec. 147 NI Act",
    "motor_accident": "Lok Adalat (MACT settlement)",
    "matrimonial": "Mediation centre (Sec. 89 CPC / family court counselling)",
    "maintenance": "Mediation centre / Lok Adalat",
    "rent_eviction": "Mediation centre (Sec. 89 CPC)",
    "consumer": "Consumer mediation cell",
    "commercial": "Pre-institution mediation (Sec. 12A Commercial Courts Act)",
    "civil_suit": "Mediation / Lok Adalat (Sec. 89 CPC)",
    "labour": "Conciliation / Lok Adalat",
    "land_revenue": "Lok Adalat",
}

# Typical hearing time (minutes) by stage, used by the scheduler.
STAGE_MINUTES = {
    "admission": 5, "notice": 5, "pleadings": 5, "framing_of_issues": 10, "charge": 10,
    "evidence": 30, "arguments": 40, "judgment_reserved": 5, "pronouncement": 5, "execution": 10,
}
TYPE_MINUTES = {"bail": 10, "habeas_corpus": 20}

STAGE_ADJ_RISK = {
    "admission": 0.25, "notice": 0.45, "pleadings": 0.55, "framing_of_issues": 0.35, "charge": 0.4,
    "evidence": 0.5, "arguments": 0.35, "judgment_reserved": 0.1, "pronouncement": 0.1, "execution": 0.45,
}

# Statutory timelines: small boost + flag (case_type_ref.time_bound_points / time_bound_law).
TIME_BOUND = {
    "cheque_bounce": (3, "Sec. 143(3) NI Act: trial to be concluded within 6 months"),
    "maintenance": (3, "Sec. 144 BNSS: interim maintenance to be decided within 60 days"),
    "domestic_violence": (3, "Sec. 12(5) PWDV Act: to be disposed of within 60 days"),
}

RULES_VERSION = "rules-v2"  # written to triage_scores; bump when weights change (v2: time-bound law, custody date flag)

# The constants above are the fallback. case_type_ref / stage_ref (seeded with these exact values) replace
# them via load_reference() when those tables have rows; the dicts are updated in place so importers see it.
_DEFAULTS = {name: dict(d) for name, d in (("TYPE_URGENCY", TYPE_URGENCY), ("ADR_ROUTES", ADR_ROUTES),
                                          ("TYPE_MINUTES", TYPE_MINUTES), ("STAGE_MINUTES", STAGE_MINUTES),
                                          ("STAGE_ADJ_RISK", STAGE_ADJ_RISK), ("TIME_BOUND", TIME_BOUND))}
# Learned adjournment rates per (case_type, stage) from recorded hearings (load_adjournment_rates); empty -> stage prior.
ADJ_RATES: Dict = {}


def load_adjournment_rates(rates: Dict) -> None:
    ADJ_RATES.clear()
    ADJ_RATES.update(rates)


def _replace(target: Dict, values: Dict) -> None:
    target.clear()
    target.update(values)


def reset_reference() -> None:
    for name, values in _DEFAULTS.items():
        _replace(globals()[name], values)


def load_reference(case_type_rows: List[Dict], stage_rows: List[Dict]) -> bool:
    """Use reference-table rows; an empty table keeps the built-in constants. Returns True if anything loaded."""
    if case_type_rows:
        _replace(TYPE_URGENCY, {r["case_type"]: r["base_urgency"] for r in case_type_rows if r.get("base_urgency") is not None})
        _replace(ADR_ROUTES, {r["case_type"]: r["adr_route"] for r in case_type_rows if r.get("adr_route")})
        _replace(TYPE_MINUTES, {r["case_type"]: r["default_minutes"] for r in case_type_rows if r.get("default_minutes")})
        _replace(TIME_BOUND, {r["case_type"]: (r["time_bound_points"], r.get("time_bound_law") or "")
                              for r in case_type_rows if r.get("time_bound_points")})
    if stage_rows:
        _replace(STAGE_MINUTES, {r["stage"]: r["default_minutes"] for r in stage_rows if r.get("default_minutes") is not None})
        _replace(STAGE_ADJ_RISK, {r["stage"]: r["adjournment_prior"] for r in stage_rows if r.get("adjournment_prior") is not None})
    return bool(case_type_rows or stage_rows)


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None


def adjournment_risk(case: Dict) -> float:
    """Rough probability the next listing is adjourned (used to size cause lists realistically)."""
    learned = ADJ_RATES.get((case.get("case_type"), case.get("stage")))
    risk = learned if learned is not None else STAGE_ADJ_RISK.get(case.get("stage", ""), 0.4)
    risk += min(case.get("adjournments", 0), 20) * 0.015
    risk += 0.05 if len(case.get("advocate_ids", [])) > 3 else 0
    risk -= 0.1 if case.get("accused_in_custody") else 0
    return round(min(max(risk, 0.05), 0.9), 2)


def estimated_minutes(case: Dict) -> int:
    return TYPE_MINUTES.get(case.get("case_type"), STAGE_MINUTES.get(case.get("stage", ""), 10))


# Sec. 479 BNSS parts that are NOT arithmetic. Anything here makes the case "needs_review" for a lawyer.
IGNORED_SECTION_TOKENS = {"34", "149", "3(5)"}   # common intention / unlawful assembly: not a separate offence


def is_life_or_death(max_sentence) -> bool:
    """True when the maximum punishment includes life imprisonment or death (Sec. 479 does not apply)."""
    text = str(max_sentence or "").lower()
    return "life" in text or "death" in text


_LIFE_OR_DEATH_WORDS = re.compile(
    r"\b(murder|culpable homicide amounting to murder|rape|gang[- ]?rape|dacoity|acid attack|terror\w*|uapa)\b", re.I)


def charge_is_life_or_death(text: str = "", act: str = "", section: str = "") -> bool:
    """True when the charge described is normally punishable with death or life imprisonment (Sec. 479 BNSS does not
    apply). Looks at words (murder, rape, dacoity ...) and at IPC 302 / BNS 103. Deliberately conservative: a person
    must never be told they are eligible on a number they gave ('7 years') when the charge itself is murder.
    The lawyer still confirms the exact section."""
    if _LIFE_OR_DEATH_WORDS.search(str(text or "")):
        return True
    where = f"{act} {text}".lower()
    sec = str(section or "")
    if re.search(r"\b302\b", sec) and re.search(r"\bipc\b|penal code", where):
        return True
    if re.search(r"\b103\b", sec) and re.search(r"\bbns\b|nyaya sanhita", where):
        return True
    return False


def multiple_offences(case: Dict) -> bool:
    """Sec. 479(2): no release under this section when more than one offence / case is pending against the person.
    True when the case says so (`other_pending_cases`) or several sections are charged. A heuristic: a false
    positive only sends the case to a lawyer, a false negative would hide a blocker, so we lean to True."""
    other = case.get("other_pending_cases")
    if other and other not in ("0", "no", "false", "False"):
        return True
    section = case.get("section")
    sections = section if isinstance(section, (list, tuple)) else re.split(r"[,;/&]|\band\b|\br/w\b", str(section or ""), flags=re.I)
    parts = [str(x).strip().lower() for x in sections if str(x).strip()]
    return len([x for x in parts if x not in IGNORED_SECTION_TOKENS]) > 1


def undertrial_release_check(case: Dict, today: date) -> Optional[Dict]:
    """Sec. 479 BNSS (earlier Sec. 436A CrPC): an undertrial detained for one-half of the maximum sentence
    (one-third for a first-time offender, i.e. never convicted) is entitled to release on bond. Not for offences
    punishable with death or life, and not when several offences / cases are pending (Sec. 479(2)).

    Returns None when the check cannot run (not in custody, date or sentence missing, life / death offence).
    Otherwise a dict. `eligible` stays the plain arithmetic ("custody has crossed the threshold") so every older
    caller keeps working; `status` is the triage answer a human should read:

        eligible         crossed the threshold, first-offender status known, no blockers
        likely_eligible  crossed the one-third mark, but first-offender status is unknown (one-half not yet crossed)
        needs_review     crossed the threshold, but a blocker needs a lawyer (e.g. several offences or cases)
        not_eligible     threshold not crossed yet (see percent_of_threshold)

    Whatever the status, a lawyer decides: delay caused by the accused is excluded from the period and the
    custody dates must be verified (see undertrial_watch.CHECKLIST).
    """
    if not case.get("accused_in_custody"):
        return None
    if charge_is_life_or_death(" ".join(str(case.get(k) or "") for k in ("offence", "charge")),
                               str(case.get("act") or ""), str(case.get("section") or "")):
        return None   # murder / rape / dacoity ...: punishable with death or life, Sec. 479 does not apply
    since = _parse_date(case.get("custody_since"))
    max_years = case.get("max_sentence_years")
    if not since or not max_years or case.get("life_or_death") or is_life_or_death(max_years):
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(max_years))   # "7", 7.0 or "7 years"
    if not m or float(m.group(0)) <= 0:
        return None
    days = (today - since).days
    max_days = float(m.group(0)) * 365
    one_third, one_half = max_days / 3, max_days / 2
    first_time = case.get("first_time_offender")          # True / False / None (unknown)
    known = first_time is not None
    if known:
        threshold = one_third if first_time else one_half
        basis = "one-third (first-time offender)" if first_time else "one-half"
    else:
        threshold = one_third                               # lowest possible limit, so nobody is missed
        basis = "one-third if a first-time offender, otherwise one-half (not yet confirmed)"
    crossed = days >= threshold
    needs_review = []
    if multiple_offences(case):
        needs_review.append("More than one offence or case may be pending - Sec. 479(2) bars release; lawyer to verify")
    if not crossed:
        status = "not_eligible"
    elif needs_review:
        status = "needs_review"
    elif not known and days < one_half:
        status = "likely_eligible"
        needs_review.append("Eligible only if this is a first offence (no earlier conviction); confirm with the family or records")
    else:
        status = "eligible"
    return {
        "custody_days": days,
        "threshold_days": int(threshold),
        "threshold_one_third_days": int(one_third),
        "threshold_one_half_days": int(one_half),
        "basis": basis,
        "eligible": crossed,
        "status": status,
        "needs_review": needs_review,
        "percent_of_threshold": round(100 * days / threshold, 1) if threshold else None,
    }


# Judgement weights for the custody part of the score (not from any statute; tune with registry feedback).
CUSTODY_POINTS = config.CUSTODY_POINTS
RELEASE_ELIGIBLE_POINTS = config.RELEASE_ELIGIBLE_POINTS
NEARING_THRESHOLD_POINTS = config.NEARING_THRESHOLD_POINTS
NEAR_THRESHOLD_PERCENT = config.NEAR_THRESHOLD_PERCENT
# The other weights in score_case, named so the staff screens can show the same numbers (GET /api/rules).
POINTS = config.TRIAGE_POINTS
NEAR_DISPOSAL_STAGES = ("arguments", "judgment_reserved", "pronouncement")
BAND_CUTS = [(name, cut) for name, cut in config.BAND_CUTS]   # score >= cut


def band_for(score: float) -> str:
    return next(name for name, cut in BAND_CUTS if score >= cut)


def score_case(case: Dict, today: Optional[date] = None) -> Dict:
    """Return a 0-100 priority score with human-readable reasons and recommended route."""
    today = today or date.today()
    reasons: List[str] = []
    flags: List[str] = []
    score = 0.0

    ctype = case.get("case_type", "other")
    base = TYPE_URGENCY.get(ctype, 4)
    score += base
    reasons.append(f"Case type '{ctype.replace('_', ' ')}' base urgency +{base}")

    # Waiting counts from the day the case became ready to list (queue state), else from filing.
    eligible = _parse_date(case.get("first_eligible_on"))
    filed = eligible or _parse_date(case.get("filing_date"))
    years = (today - filed).days / 365.25 if filed else 0
    age_pts = min(years * POINTS["age_per_year"], POINTS["age_cap"])
    if age_pts:
        score += age_pts
        reasons.append(f"{'Waiting since eligible' if eligible else 'Pending'} {years:.1f} years +{age_pts:.0f}")
    if years >= POINTS["decade_years"]:
        flags.append("DECADE_OLD")

    if ctype in TIME_BOUND:
        pts, law = TIME_BOUND[ctype]
        score += pts
        flags.append("TIME_BOUND_LAW")
        reasons.append(f"Statutory timeline ({law}) +{pts}")

    needs_review = False
    if case.get("accused_in_custody"):
        score += CUSTODY_POINTS
        reasons.append(f"Accused in custody +{CUSTODY_POINTS}")
        if not _parse_date(case.get("custody_since")):
            flags.append("CUSTODY_DATE_MISSING")
            needs_review = True
            reasons.append("Custody date missing - Sec. 479 check not possible; needs review (kept as custody)")
        ut = undertrial_release_check(case, today)
        if ut and ut["eligible"]:
            score += RELEASE_ELIGIBLE_POINTS
            flags.append("UNDERTRIAL_RELEASE_ELIGIBLE")
            reasons.append(f"Custody {ut['custody_days']}d exceeds Sec. 479 BNSS threshold ({ut['threshold_days']}d, "
                           f"{ut['basis']}) +{RELEASE_ELIGIBLE_POINTS}")
            if ut["status"] in ("needs_review", "likely_eligible"):
                needs_review = True
                reasons.append("; ".join(ut["needs_review"]))
        elif ut and ut["percent_of_threshold"] and ut["percent_of_threshold"] >= NEAR_THRESHOLD_PERCENT:
            score += NEARING_THRESHOLD_POINTS
            flags.append("UNDERTRIAL_NEARING_THRESHOLD")
            reasons.append(f"Custody at {ut['percent_of_threshold']}% of Sec. 479 BNSS threshold +{NEARING_THRESHOLD_POINTS}")

    vulnerable = [k for k in ("senior_citizen", "woman_or_child", "disability") if case.get(k)]
    if vulnerable:
        pts = POINTS["vulnerable_each"] * len(vulnerable)
        score += pts
        reasons.append(f"Vulnerable party ({', '.join(v.replace('_', ' ') for v in vulnerable)}) +{pts}")

    adj = case.get("adjournments", 0)
    if adj >= POINTS["chronic_adjournment_at"]:
        score += POINTS["chronic_adjournment"]
        flags.append("CHRONIC_ADJOURNMENT")
        reasons.append(f"{adj} adjournments - needs firm listing +{POINTS['chronic_adjournment']}")

    stage = case.get("stage", "")
    if stage in NEAR_DISPOSAL_STAGES:
        score += POINTS["near_disposal"]
        reasons.append(f"Near disposal (stage: {stage.replace('_', ' ')}) +{POINTS['near_disposal']}")

    last = _parse_date(case.get("last_hearing_date"))
    if last and (today - last).days > POINTS["dormant_after_days"]:
        score += POINTS["dormant"]
        flags.append("DORMANT")
        reasons.append(f"Not heard for {(today - last).days} days +{POINTS['dormant']}")

    if case.get("legal_aid"):
        score += POINTS["legal_aid"]
        reasons.append(f"Legally-aided party +{POINTS['legal_aid']}")

    score = round(min(score, 100), 1)
    band = band_for(score)
    if "UNDERTRIAL_RELEASE_ELIGIBLE" in flags:
        band = "Critical"  # entitled to release yet still detained - never wait behind other matters
    route = recommend_route(case, flags)

    return {
        "case_id": case.get("case_id"),
        "score": score,
        "band": band,
        "flags": flags,
        "reasons": reasons,
        "recommended_route": route,
        "estimated_minutes": estimated_minutes(case),
        "adjournment_risk": adjournment_risk(case),
        "years_pending": round(years, 1),
        "needs_review": needs_review or case.get("data_quality") == "needs_review",
        "rules_version": RULES_VERSION,
    }


def recommend_route(case: Dict, flags: List[str]) -> str:
    ctype = case.get("case_type", "other")
    if "UNDERTRIAL_RELEASE_ELIGIBLE" in flags:
        return "Refer to Undertrial Review Committee / list for release under Sec. 479 BNSS"
    if ctype in ("habeas_corpus", "bail"):
        return "List immediately (liberty matter)"
    if ctype in ADR_ROUTES and case.get("stage") not in ("arguments", "judgment_reserved"):
        return ADR_ROUTES[ctype]
    if ctype == "criminal_trial" and case.get("max_sentence_years") and str(case["max_sentence_years"]).replace(".", "").isdigit() \
            and float(case["max_sentence_years"]) < 7 and not case.get("offence_against_woman_or_child"):
        return "Explore plea bargaining (Chapter XXIII BNSS) / summary trial"
    if "DECADE_OLD" in flags:
        return "Fast-track list (10+ year old case)"
    return "Regular list"


def triage_all(cases: List[Dict], today: Optional[date] = None) -> List[Dict]:
    results = []
    for case in cases:
        r = score_case(case, today)
        r["case"] = case
        results.append(r)
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def backlog_stats(results: List[Dict]) -> Dict:
    n = len(results) or 1
    by_band, by_route, by_type = {}, {}, {}
    for r in results:
        by_band[r["band"]] = by_band.get(r["band"], 0) + 1
        route = r["recommended_route"].split(" (")[0].split(" /")[0]
        by_route[route] = by_route.get(route, 0) + 1
        t = r["case"].get("case_type", "other")
        by_type[t] = by_type.get(t, 0) + 1
    adr = sum(1 for r in results if any(k in r["recommended_route"] for k in ("Lok Adalat", "Mediation", "mediation", "Conciliation", "compounding")))
    return {
        "total_cases": len(results),
        "by_band": by_band,
        "by_route": by_route,
        "by_type": by_type,
        "avg_years_pending": round(sum(r["years_pending"] for r in results) / n, 1),
        "decade_old": sum(1 for r in results if "DECADE_OLD" in r["flags"]),
        "undertrial_release_eligible": sum(1 for r in results if "UNDERTRIAL_RELEASE_ELIGIBLE" in r["flags"]),
        "adr_diversion_candidates": adr,
        "adr_diversion_percent": round(100 * adr / n, 1),
    }


# ---------------------------------------------------------------------------
# Free-text intake classification (e-filing / legal-aid intake desk)
# ---------------------------------------------------------------------------

CLASSIFY_SYSTEM = f"""You classify Indian court case intake descriptions for registry triage.
case_type must be one of {CASE_TYPES}; stage one of {list(STAGE_MINUTES)}.
Use only what the description states; default booleans to false and stage to "admission".
custody_since: YYYY-MM-DD; for a partial date (month/year only) use the first day of that month.
max_sentence_years: the statutory maximum for the offence named (BNS / IPC) as a number, or "life"/"death"; null if unclear.
summary: one neutral sentence, no personal identifiers."""

# Statutory maximum sentence (years) for common offences under the BNS, used when intake text names one.
OFFENCE_MAX_YEARS = [
    (r"murder", "life"), (r"robbery", 10), (r"dacoity", "life"), (r"rape", "life"),
    (r"cheating", 7), (r"theft", 3), (r"criminal breach of trust", 5), (r"grievous hurt", 7),
]
_MONTH_NUM = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}


def _custody_since(text: str) -> Optional[str]:
    m = re.search(r"(?:custody|jail|arrested|detained)[^.]{0,40}?since\s+(?:(\w+)\s+)?(\d{4})", text)
    if not m:
        return None
    month = _MONTH_NUM.get((m.group(1) or "").lower(), 1)
    return date(int(m.group(2)), month, 1).isoformat()

KEYWORDS = [
    ("habeas_corpus", r"habeas|illegal(ly)? detain|missing (son|daughter|person)"),
    ("bail", r"\bbail\b"),
    ("cheque_bounce", r"cheque|138 (of the )?n\.?i\.?|negotiable instrument"),
    ("motor_accident", r"motor accident|mact|road accident|vehicle accident"),
    ("domestic_violence", r"domestic violence|dv act|protection of women"),
    ("maintenance", r"maintenance|section 125|sec\.? 144 bnss"),
    ("child_custody", r"custody of (the )?(child|minor)|guardian"),
    ("matrimonial", r"divorce|marriage|restitution of conjugal"),
    ("rent_eviction", r"evict|tenant|landlord|rent"),
    ("labour", r"workman|wages|industrial dispute|gratuity|termination of service"),
    ("consumer", r"consumer|deficiency in service|defective product"),
    ("land_revenue", r"land|mutation|revenue|patta|survey no"),
    ("service", r"promotion|pension|transfer order|seniority"),
    ("commercial", r"commercial|invoice|supply agreement|arbitration"),
    ("criminal_appeal", r"appeal against (conviction|acquittal)"),
    ("criminal_trial", r"\bfir\b|charge ?sheet|accused|offence|\bipc\b|\bbns\b|theft|murder|assault|robbery|cheating|judicial custody"),
    ("writ", r"writ|article 226|article 32"),
    ("civil_suit", r"suit|injunction|declaration|partition|specific performance"),
]


def classify_free_text(description: str) -> Dict:
    if llm.available():
        try:
            out = llm.structured(CLASSIFY_SYSTEM, f"<description>\n{description}\n</description>",
                                 IntakeClassification, fast=True).model_dump()
            if out.get("case_type") in CASE_TYPES:
                ms = out.get("max_sentence_years")
                if ms and str(ms).replace(".", "").isdigit():
                    out["max_sentence_years"] = float(ms)
                out["engine"] = "llm"
                return out
        except Exception as exc:
            logger.warning("LLM classification failed: %s", exc)
    text = description.lower()
    ctype = next((t for t, pat in KEYWORDS if re.search(pat, text)), "other")
    age = re.search(r"\b(?:aged?|age)\s*(?:about\s*)?(\d{2})\b|\b(\d{2})[- ]year[- ]old\b", text)
    age_val = int(next(g for g in age.groups() if g)) if age else None
    in_custody = bool(re.search(r"in (judicial )?custody|in jail|arrested|lodged in", text))
    max_years = next((y for pat, y in OFFENCE_MAX_YEARS if re.search(pat, text)), None)
    return {
        "case_type": ctype,
        "stage": "admission",
        "accused_in_custody": in_custody,
        "custody_since": _custody_since(text) if in_custody else None,
        "max_sentence_years": max_years,
        "senior_citizen": bool((age_val and age_val >= 60) or "senior citizen" in text),
        "woman_or_child": bool(re.search(r"\b(woman|women|wife|widow|girl|minor|child|daughter|mother)\b", text)),
        "disability": bool(re.search(r"disab|blind|deaf|handicap", text)),
        "act": None,
        "section": None,
        "summary": description[:200],
        "engine": "heuristic",
    }


def eta_years_to_clear(pending: int, monthly_institution: float, monthly_disposal: float) -> Optional[float]:
    """Simple backlog clearance estimate; None if the backlog is growing."""
    net = monthly_disposal - monthly_institution
    if net <= 0:
        return None
    return round(math.ceil(pending / net) / 12, 1)
