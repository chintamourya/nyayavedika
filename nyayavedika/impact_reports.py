"""Impact evidence reports: what happened when a real person used NyayaVedika on real work.

The public field-feedback wall (feedback.py) is anonymous and short. This is the longer, verifiable record behind
"Proven impact": who reported (checkable for professionals), what they used it for, how long the task took without and
with NyayaVedika, whether the output matched the source, and the concrete outcome.

Privacy rules, enforced here and not only in the form:
  * Identity details (name, email, Bar Council enrolment, law school ...) are stored only to let the NyayaVedika team
    confirm the person is real. They are never returned by a public endpoint, never shown on any public page, and
    never sent to a language model.
  * Free text (outcome, testimonial) is run through documents.redact_pii, so phone numbers, emails, Aadhaar and PAN
    typed into it are masked. The form asks people not to name clients or parties.
  * Storing a report needs explicit consent; quoting it needs a separate choice (not at all / anonymously /
    with name and role), and only verified reports are ever offered as quotable.
  * Verification is a human act by a staff user (verify()), written to the audit log by the caller.
Used by server.py and scripts/dev_api.py so both servers behave the same.
"""
import csv
import io
import re
import statistics
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from . import documents

ROLES = {
    "advocate": "Advocate (enrolled with a State Bar Council)",
    "legal_aid_lawyer": "Legal-aid / panel lawyer (DLSA, TLSC, SLSA)",
    "court_staff": "Court staff (registry, bench clerk, records)",
    "paralegal": "Para-legal volunteer",
    "law_student": "Law student / intern",
    "citizen": "Citizen or family member",
    "other": "Other",
}
PROFESSIONAL = ("advocate", "legal_aid_lawyer", "court_staff", "paralegal", "law_student")
FEATURES = {
    "advocate_summary": "Advocate: document summary, facts, issues, background",
    "advocate_chat": "Advocate: questions on a document",
    "document_studio": "Advocate: Document Studio (merge, split, index, page numbers, OCR)",
    "staff_intake": "Court staff: intake of case papers",
    "staff_triage": "Court staff: case triage (Docket)",
    "staff_cause_list": "Court staff: cause list scheduling",
    "staff_diary": "Court staff: court diary (recording proceedings)",
    "undertrial_watch": "Undertrial watch (Sec. 479 BNSS)",
    "document_summary": "Document summary",
    "legal_aid_check": "Citizen: free legal aid eligibility and application",
    "legal_problem": "Citizen: describe a legal problem",
    "rights_guide": "Citizen: know your rights",
}
USED_ON = {"real_matter": "A real matter I was working on", "sample": "A sample or old closed file",
           "trial": "Only trying it out"}
TASKS = {
    "read_case_file": "Reading and understanding a case file / judgment",
    "prepare_brief": "Preparing a brief, list of dates or synopsis",
    "draft_application": "Drafting an application (bail, Sec. 479, legal aid)",
    "triage_docket": "Deciding which pending cases need attention first",
    "prepare_cause_list": "Preparing a cause list",
    "record_proceedings": "Recording hearing outcomes / next dates",
    "check_custody": "Checking custody period against Sec. 479 BNSS",
    "find_legal_aid": "Finding out about free legal aid",
    "understand_rights": "Understanding my rights or my case",
    "other": "Something else",
}
OUTCOMES = {
    "saved_time": "The task took less time",
    "found_missing_fact": "Found a fact, date or issue I would have missed",
    "application_filed": "An application was filed in court",
    "release_application": "A release / bail application under Sec. 479 BNSS was prepared",
    "legal_aid_applied": "Applied for free legal aid",
    "legal_aid_obtained": "Got a legal-aid lawyer",
    "hearing_listed": "A matter was listed for hearing sooner",
    "list_prepared_faster": "The cause list was ready faster",
    "understood_case": "I (or my client) understood the case better",
    "nothing_yet": "No outcome yet",
}
ACCURACY = {"matched": "Matched the original", "minor_errors": "Minor errors I corrected",
            "major_errors": "Major errors", "not_checked": "I did not check"}
CONTINUE = ("yes", "maybe", "no")
QUOTE = {"no": "Do not quote me", "anonymous": "Quote me without my name",
         "named": "Quote me with my name and role"}
STATUS = ("pending", "verified", "rejected")

EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
ENROLMENT = re.compile(r"^[A-Za-z0-9/.\- ]{3,40}$")
MAX_TEXT = 1200


_RECENT: Dict[str, List[float]] = {}   # client key -> submit times, in memory only (never stored)


def rate_ok(key: str, limit: int = 10, window_seconds: int = 3600) -> bool:
    """The public form is open; at most `limit` reports per client per hour stops a script from flooding it."""
    import time
    now = time.time()
    hits = [t for t in _RECENT.get(key or "-", []) if now - t < window_seconds]
    if len(hits) >= limit:
        _RECENT[key or "-"] = hits
        return False
    _RECENT[key or "-"] = hits + [now]
    if len(_RECENT) > 5000:   # bound the memory
        _RECENT.clear()
    return True


class ReportError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def options() -> Dict[str, Any]:
    """Everything the public form needs to draw itself (labels live here, so the form and the checks never drift)."""
    as_list = lambda d: [{"value": k, "label": v} for k, v in d.items()]  # noqa: E731
    return {"roles": as_list(ROLES), "professional_roles": list(PROFESSIONAL), "features": as_list(FEATURES),
            "used_on": as_list(USED_ON), "tasks": as_list(TASKS), "outcomes": as_list(OUTCOMES),
            "accuracy": as_list(ACCURACY), "quote": as_list(QUOTE), "continue": list(CONTINUE),
            "this_year": date.today().year}


# ----------------------------------------------------------------------------- validation
def _plain(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _free(value: Any, limit: int = MAX_TEXT) -> str:
    return documents.redact_pii(_plain(value, limit))


def _pick(value: Any, allowed, field: str, required: bool = False) -> Optional[str]:
    if value in (None, ""):
        if required:
            raise ReportError(400, f"Please choose {field}.")
        return None
    if value not in allowed:
        raise ReportError(400, f"{field}: {value!r} is not one of the options")
    return value


def _many(values: Any, allowed, field: str, required: bool = False) -> List[str]:
    if values in (None, "", []):
        if required:
            raise ReportError(400, f"Please choose at least one {field}.")
        return []
    if not isinstance(values, list):
        raise ReportError(400, f"{field} must be a list")
    bad = [v for v in values if v not in allowed]
    if bad:
        raise ReportError(400, f"{field}: unknown option {bad[0]!r}")
    return [v for v in allowed if v in values]


def _int(value: Any, field: str, low: int, high: int) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        raise ReportError(400, f"{field} must be a number")
    if not low <= n <= high:
        raise ReportError(400, f"{field} must be between {low} and {high}")
    return n


def _year(value: Any, field: str) -> Optional[int]:
    return _int(value, field, 1950, date.today().year + 6)   # law students give an expected year


def clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalise one report. Raises ReportError(400) with a sentence the form can show as is."""
    p = payload or {}
    if _plain(p.get("website"), 200):          # honeypot: hidden from people, filled by bots
        raise ReportError(400, "This form could not be accepted.")
    if p.get("consent_store") is not True:
        raise ReportError(400, "Please agree to the storage of this report so it can be used as evidence.")
    role = _pick(p.get("role"), ROLES, "your role", required=True)
    pro = role in PROFESSIONAL

    name = _plain(p.get("full_name"), 120)
    email = _plain(p.get("email"), 160).lower()
    if pro and len(name) < 3:
        raise ReportError(400, "Please give your full name; professional reports are verified before they are counted.")
    if (pro or email) and not EMAIL.match(email):
        raise ReportError(400, "Please give a valid email address so the team can confirm the report.")
    identity = {"full_name": name, "email": email,
                "district": _plain(p.get("district"), 80), "state": _plain(p.get("state"), 60)}
    if role in ("advocate", "legal_aid_lawyer"):
        enrol = _plain(p.get("enrolment_number"), 40)                                    # optional
        if enrol and not ENROLMENT.match(enrol):
            raise ReportError(400, "The enrolment number may contain only letters, digits and / - . characters.")
        identity.update(enrolment_number=enrol.upper(),
                        enrolment_year=_year(p.get("enrolment_year"), "Year of enrolment"),
                        practice_court=_plain(p.get("practice_court"), 120))          # optional
    if role in ("advocate", "legal_aid_lawyer", "law_student"):
        school = _plain(p.get("law_school"), 160)
        if len(school) < 3:
            raise ReportError(400, "Please name the college or university of your law degree.")
        identity["law_school"] = school
    if role == "legal_aid_lawyer":
        identity["legal_services_authority"] = _plain(p.get("legal_services_authority"), 120)   # optional
    if role in ("court_staff", "paralegal"):
        identity["designation"] = _plain(p.get("designation"), 80)                            # optional
    if role in PROFESSIONAL:
        identity["work_experience"] = _plain(p.get("work_experience"), 300)                   # optional
    identity["profile_url"] = _plain(p.get("profile_url"), 200) if str(p.get("profile_url") or "").startswith("https://") else ""

    before = _int(p.get("minutes_without"), "Time without NyayaVedika", 1, 6000)
    with_tool = _int(p.get("minutes_with"), "Time with NyayaVedika", 1, 6000)
    if (before is None) != (with_tool is None):
        raise ReportError(400, "Give both times (without and with NyayaVedika), or leave both blank.")
    usage = {
        "features": _many(p.get("features"), FEATURES, "feature used", required=True),
        "used_on": _pick(p.get("used_on"), USED_ON, "what you used it on", required=True),
        "times_used": _int(p.get("times_used"), "Times used", 1, 10000),
        "used_from": _plain(p.get("used_from"), 10) or None,
        "task": _pick(p.get("task"), TASKS, "the task"),
    }
    if usage["used_from"]:
        try:
            date.fromisoformat(usage["used_from"])
        except ValueError:
            raise ReportError(400, "First used on must be a date.")
    measures = {
        "minutes_without": before, "minutes_with": with_tool,
        "timing_basis": _pick(p.get("timing_basis"), ("estimated", "timed"), "how the time was measured")
        if before is not None else None,
        "documents_handled": _int(p.get("documents_handled"), "Documents handled", 0, 100000),
        "pages_handled": _int(p.get("pages_handled"), "Pages handled", 0, 1000000),
        "cases_handled": _int(p.get("cases_handled"), "Cases or people helped", 0, 100000),
        "accuracy": _pick(p.get("accuracy"), ACCURACY, "accuracy"),
        "errors_found": _int(p.get("errors_found"), "Errors found", 0, 1000),
    }
    if before is not None and not measures["timing_basis"]:
        raise ReportError(400, "Say whether the times were estimated or timed.")
    ratings = {k: _int(p.get(k), k.replace("_", " ").capitalize(), 1, 5) for k in ("usefulness", "ease", "trust")}
    if not ratings["usefulness"]:
        raise ReportError(400, "Please rate how useful it was (1-5).")
    outcomes = _many(p.get("outcomes"), OUTCOMES, "outcome", required=True)
    if "nothing_yet" in outcomes and len(outcomes) > 1:
        outcomes.remove("nothing_yet")
    return {
        "role": role, "identity": identity, "usage": usage, "measures": measures, "ratings": ratings,
        "outcomes": outcomes, "outcome_detail": _free(p.get("outcome_detail")),
        "would_continue": _pick(p.get("would_continue"), CONTINUE, "whether you would keep using it"),
        "testimonial": _free(p.get("testimonial"), 600),
        "quote_permission": _pick(p.get("quote_permission"), QUOTE, "quote permission") or "no",
        "consent_contact": p.get("consent_contact") is True,
    }


# ----------------------------------------------------------------------------- storage
def ensure_table(db) -> None:
    if "impact_reports" not in db.tables():
        from .db_schema import migrate
        migrate(db)
        db.commit()


def submit(db, payload: Dict[str, Any], source: str = "form") -> Dict[str, Any]:
    row = clean(payload)
    ensure_table(db)
    new_id = db.insert("impact_reports", [{**row, "source": source, "status": "pending", "created_at": _now()}],
                       returning="id")
    db.commit()
    return {"ok": True, "id": new_id, "status": "pending",
            "message": "Thank you. Your report is saved. Professional reports are counted once the team has confirmed "
                       "them; we may write to you at the email you gave."}


def verify(db, report_id: int, status: str, actor: str, note: str = "") -> Dict[str, Any]:
    if status not in STATUS:
        raise ReportError(400, f"status must be one of {', '.join(STATUS)}")
    ensure_table(db)
    if not db.select("impact_reports", {"id": report_id}):
        raise ReportError(404, f"No impact report {report_id}")
    db.update("impact_reports", {"id": report_id},
              {"status": status, "verified_by": actor, "verified_at": _now(), "verification_note": _plain(note, 300)})
    db.commit()
    return {"ok": True, "id": report_id, "status": status}


def rows(db) -> List[Dict]:
    ensure_table(db)
    return db.select("impact_reports", order="id DESC")


def listing(db, status: str = "") -> Dict[str, Any]:
    """Staff only: every report including identity, for the verification desk."""
    out = rows(db)
    if status:
        out = [r for r in out if r["status"] == status]
    return {"reports": out}


# ----------------------------------------------------------------------------- the numbers a README can quote
def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def summary(db) -> Dict[str, Any]:
    """Aggregates for the evidence write-up. Headline figures use VERIFIED reports only; totals show what is pending."""
    allr = rows(db)
    ver = [r for r in allr if r["status"] == "verified"]
    paired = [r for r in ver if (r.get("measures") or {}).get("minutes_without") and (r.get("measures") or {}).get("minutes_with")]
    saved = [r["measures"]["minutes_without"] - r["measures"]["minutes_with"] for r in paired]
    pct = [100 * (r["measures"]["minutes_without"] - r["measures"]["minutes_with"]) / r["measures"]["minutes_without"] for r in paired]
    real = [r for r in ver if (r.get("usage") or {}).get("used_on") == "real_matter"]
    count = lambda items, key: {k: sum(1 for r in items if k in (r.get(key) or [])) for k in OUTCOMES}  # noqa: E731
    by_role: Dict[str, Dict[str, int]] = {}
    for r in allr:
        by_role.setdefault(r["role"], {"pending": 0, "verified": 0, "rejected": 0})[r["status"]] += 1
    acc = [(r.get("measures") or {}).get("accuracy") for r in ver]
    checked = [a for a in acc if a and a != "not_checked"]
    use = [(r.get("ratings") or {}).get("usefulness") for r in ver]
    totals = lambda key: sum((r.get("measures") or {}).get(key) or 0 for r in ver)  # noqa: E731
    return {
        "reports": len(allr), "verified": len(ver), "pending": sum(1 for r in allr if r["status"] == "pending"),
        "by_role": by_role,
        "verified_professionals": sum(1 for r in ver if r["role"] in PROFESSIONAL),
        "verified_on_real_matters": len(real),
        "time": {"paired_reports": len(paired), "timed": sum(1 for r in paired if r["measures"].get("timing_basis") == "timed"),
                 "median_minutes_without": _median(r["measures"]["minutes_without"] for r in paired),
                 "median_minutes_with": _median(r["measures"]["minutes_with"] for r in paired),
                 "median_minutes_saved": _median(saved),
                 "median_percent_saved": round(_median(pct)) if pct else None,
                 "total_hours_saved": round(sum(saved) / 60, 1) if saved else 0},
        "volume": {"documents": totals("documents_handled"), "pages": totals("pages_handled"),
                   "cases_or_people": totals("cases_handled")},
        "outcomes": count(ver, "outcomes"),
        "accuracy": {"checked": len(checked), "matched": sum(1 for a in checked if a == "matched"),
                     "minor_errors": sum(1 for a in checked if a == "minor_errors"),
                     "major_errors": sum(1 for a in checked if a == "major_errors")},
        "avg_usefulness": round(sum(use) / len([u for u in use if u]), 1) if any(use) else None,
        "would_continue_pct": round(100 * sum(1 for r in ver if r.get("would_continue") == "yes")
                                    / len([r for r in ver if r.get("would_continue")])) if any(r.get("would_continue") for r in ver) else None,
        "quotes": [{"id": r["id"], "text": r["testimonial"],
                    "by": (f"{r['identity'].get('full_name')}, {ROLES[r['role']]}" if r["quote_permission"] == "named"
                           else ROLES[r["role"]]) + (f", {r['identity'].get('district')}" if r["identity"].get("district") else "")}
                   for r in ver if r.get("testimonial") and r.get("quote_permission") in ("anonymous", "named")],
        "note": "Headline figures count verified reports only. Times are as reported; 'timed' marks reports where the "
                "person measured both runs.",
    }


EXPORT_COLUMNS = ("id", "created_at", "status", "verified_by", "verified_at", "role", "full_name", "email", "district",
                  "state", "enrolment_number", "enrolment_year", "law_school", "practice_court",
                  "legal_services_authority", "designation", "work_experience", "profile_url", "features",
                  "used_on", "times_used", "used_from", "task", "minutes_without", "minutes_with", "timing_basis",
                  "documents_handled", "pages_handled", "cases_handled", "accuracy", "errors_found", "usefulness",
                  "ease", "trust", "outcomes", "outcome_detail", "would_continue", "testimonial", "quote_permission",
                  "consent_contact")


def _cell(v: Any) -> str:
    s = "; ".join(map(str, v)) if isinstance(v, list) else ("" if v is None else str(v))
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s   # a spreadsheet must not run a cell as a formula


def export_csv(db) -> str:
    """Staff only. Contains identity details: keep the file private."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EXPORT_COLUMNS)
    for r in rows(db):
        flat = {**r, **(r.get("identity") or {}), **(r.get("usage") or {}), **(r.get("measures") or {}),
                **(r.get("ratings") or {})}
        w.writerow([_cell(flat.get(c)) for c in EXPORT_COLUMNS])
    return buf.getvalue()
