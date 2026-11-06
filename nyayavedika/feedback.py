"""Field feedback from real users (advocates, lawyers, court staff, citizens) - the evidence behind "Proven impact".

One short form on the landing page (about 3 minutes, never more than 5). The questions follow the four judging
criteria, so every answer maps to a number a reviewer can check:

  Size of the problem      problem_frequency, people_affected
  Severity of the problem  cost_types, days_lost, rupees_lost
  Quality of the solution  rating, ease, accuracy, would_recommend
  Proven impact            outcomes, time_saved

Only the role and the star rating are required. New submissions are published by default. Free text is run through
documents.redact_pii, and names are cut to a first name. Staff can hide an entry through the staff-only API.
Used by both server.py and scripts/dev_api.py so the two servers behave the same.
"""
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import documents

ROLES = ("advocate", "lawyer", "court_staff", "citizen", "other")
FEATURES = ("legal_aid", "rights_guide", "document_summary", "triage", "cause_list", "undertrial_alerts")
FREQUENCY = ("rarely", "sometimes", "often", "weekly")
COSTS = ("missed_hearing", "lost_wages", "travel", "long_custody", "fees", "no_lawyer", "stress")
ACCURACY = ("correct", "mostly", "wrong", "unsure")
OUTCOMES = ("understood_rights", "got_legal_aid", "saved_time", "case_moved", "nothing_yet")
TIME_SAVED = ("none", "under_1h", "1_to_3h", "half_day", "day_plus")
RECOMMEND = ("yes", "maybe", "no")
LANGUAGES = ("en", "hi", "te", "other")

SHORT_CHARS = 140
WALL_LIMIT = 60


class FeedbackError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _choice(value: Any, allowed, field: str, required: bool = False) -> Optional[str]:
    if value in (None, ""):
        if required:
            raise FeedbackError(400, f"{field} is required")
        return None
    if value not in allowed:
        raise FeedbackError(400, f"{field} must be one of: {', '.join(allowed)}")
    return value


def _choices(values: Any, allowed, field: str) -> List[str]:
    if values in (None, ""):
        return []
    if not isinstance(values, list):
        raise FeedbackError(400, f"{field} must be a list")
    bad = [v for v in values if v not in allowed]
    if bad:
        raise FeedbackError(400, f"{field}: unknown value {bad[0]!r}")
    return [v for v in allowed if v in values]          # de-duplicated, stable order


def _stars(value: Any, field: str, required: bool = False) -> Optional[int]:
    if value in (None, ""):
        if required:
            raise FeedbackError(400, f"{field} is required (1-5)")
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise FeedbackError(400, f"{field} must be 1-5")
    if not 1 <= n <= 5:
        raise FeedbackError(400, f"{field} must be 1-5")
    return n


def _count(value: Any, field: str, cap: int) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise FeedbackError(400, f"{field} must be a whole number")
    if n < 0:
        raise FeedbackError(400, f"{field} cannot be negative")
    return min(n, cap)


def _text(value: Any, limit: int) -> str:
    return documents.redact_pii(re.sub(r"\s+", " ", str(value or "")).strip())[:limit]


def first_name(value: Any) -> str:
    """Public wall shows a first name only."""
    parts = _text(value, 60).split(" ")
    return parts[0][:24] if parts and parts[0] else ""


def short_text(headline: str, comment: str) -> str:
    """The one-liner on a card: the person's own headline, else the first sentence of the comment, trimmed."""
    if headline:
        return headline
    text = (comment or "").strip()
    if not text:
        return ""
    first = re.split(r"(?<=[.!?।])\s", text, maxsplit=1)[0]
    cut = first if len(first) <= SHORT_CHARS else first[:SHORT_CHARS].rsplit(" ", 1)[0] + "…"
    return cut


def clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalise a submission. Raises FeedbackError(400) with a message the form can show."""
    p = payload or {}
    role = _choice(p.get("role"), ROLES, "role", required=True)
    rating = _stars(p.get("rating"), "rating", required=True)
    comment = _text(p.get("comment"), 1000)
    headline = _text(p.get("headline"), 120)
    answers = {
        "problem_frequency": _choice(p.get("problem_frequency"), FREQUENCY, "problem_frequency"),
        "people_affected": _count(p.get("people_affected"), "people_affected", 10_000_000),
        "cost_types": _choices(p.get("cost_types"), COSTS, "cost_types"),
        "days_lost": _count(p.get("days_lost"), "days_lost", 3650),
        "rupees_lost": _count(p.get("rupees_lost"), "rupees_lost", 100_000_000),
        "ease": _stars(p.get("ease"), "ease"),
        "accuracy": _choice(p.get("accuracy"), ACCURACY, "accuracy"),
        "outcomes": _choices(p.get("outcomes"), OUTCOMES, "outcomes"),
        "time_saved": _choice(p.get("time_saved"), TIME_SAVED, "time_saved"),
        "language": _choice(p.get("language"), LANGUAGES, "language"),
    }
    return {
        "role": role, "rating": rating,
        "name": first_name(p.get("name")), "place": _text(p.get("place"), 60),
        "features": _choices(p.get("features"), FEATURES, "features"),
        "would_recommend": _choice(p.get("would_recommend"), RECOMMEND, "would_recommend"),
        "headline": headline, "comment": comment,
        "answers": {k: v for k, v in answers.items() if v not in (None, [], "")},
        "published": True,
    }


def ensure_table(db) -> None:
    """Create the table on first use, so a server started before scripts/migrate_demo.py was run still works."""
    if "field_feedback" not in db.tables():
        from .db_schema import migrate
        migrate(db)
        db.commit()


def submit(db, payload: Dict[str, Any], auth_role: str = "citizen") -> Dict[str, Any]:
    row = clean(payload)
    ensure_table(db)
    new_id = db.insert("field_feedback", [{**row, "auth_role": auth_role, "created_at": _now()}], returning="id")
    return {"ok": True, "id": new_id, "published": row["published"]}


def hide(db, feedback_id: int) -> Dict[str, Any]:
    ensure_table(db)
    if not db.select("field_feedback", {"id": feedback_id}):
        raise FeedbackError(404, f"No feedback {feedback_id}")
    db.update("field_feedback", {"id": feedback_id}, {"published": False})
    return {"ok": True, "id": feedback_id, "published": False}


def _pct(part: int, whole: int) -> Optional[int]:
    return round(100 * part / whole) if whole else None


def summarise(rows: List[Dict]) -> Dict[str, Any]:
    """Numbers over ALL responses (hidden ones included): the figures a reviewer can quote."""
    n = len(rows)
    ratings = [r["rating"] for r in rows if r.get("rating")]
    eases = [(r.get("answers") or {}).get("ease") for r in rows]
    eases = [e for e in eases if e]
    recommend = [r["would_recommend"] for r in rows if r.get("would_recommend")]
    outcomes = [(r.get("answers") or {}).get("outcomes") or [] for r in rows]
    answered_outcome = [o for o in outcomes if o]
    changed = [o for o in answered_outcome if any(x != "nothing_yet" for x in o)]
    freq = [(r.get("answers") or {}).get("problem_frequency") for r in rows]
    faced_often = [f for f in freq if f in ("often", "weekly")]
    by_role: Dict[str, int] = {}
    for r in rows:
        by_role[r["role"]] = by_role.get(r["role"], 0) + 1
    return {
        "responses": n,
        "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "avg_ease": round(sum(eases) / len(eases), 1) if eases else None,
        "would_recommend_pct": _pct(sum(1 for v in recommend if v == "yes"), len(recommend)),
        "outcome_changed_pct": _pct(len(changed), len(answered_outcome)),
        "face_problem_often_pct": _pct(len(faced_often), len([f for f in freq if f])),
        "by_role": by_role,
    }


def public(db, limit: Optional[int] = WALL_LIMIT) -> Dict[str, Any]:
    ensure_table(db)
    rows = db.select("field_feedback", order="id DESC")
    wall = [r for r in rows if r.get("published")]
    if limit is not None:
        wall = wall[:limit]
    items = [{
        "id": r["id"], "created_at": str(r.get("created_at") or "")[:10],
        "role": r["role"], "name": r.get("name") or "", "place": r.get("place") or "",
        "rating": r["rating"], "short": short_text(r.get("headline") or "", r.get("comment") or ""),
        "headline": r.get("headline") or "", "comment": r.get("comment") or "",
        "features": r.get("features") or [], "would_recommend": r.get("would_recommend"),
        "answers": r.get("answers") or {},
    } for r in wall]
    return {"summary": summarise(rows), "items": items}
