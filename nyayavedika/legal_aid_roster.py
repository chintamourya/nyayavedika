"""Staff-managed legal-aid lawyer roster and Undertrial alert assignment."""
from datetime import datetime, timezone
import uuid
from typing import Dict, List

from . import impact, store

MAX_NAME = 120
MAX_DISTRICT = 80
MAX_REFERENCE = 240


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_lawyers(db, actor_role: str) -> Dict[str, List[Dict]]:
    if actor_role not in ("staff", "lawyer"):
        raise PermissionError("Only court staff and lawyers can view the legal-aid roster")
    with store._session(db) as session:
        rows = session.select("legal_aid_roster", {"active": True}, order="district, name")
    return {"lawyers": rows}


def add_lawyer(db, body: Dict, actor: str, role: str) -> Dict:
    if role != "staff":
        raise PermissionError("Only court staff can manage the legal-aid roster")
    name = body.get("name")
    district = body.get("district")
    reference = body.get("verification_reference")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_NAME:
        raise ValueError(f"Give a lawyer name of up to {MAX_NAME} characters")
    if not isinstance(district, str) or not district.strip() or len(district.strip()) > MAX_DISTRICT:
        raise ValueError(f"Give a district of up to {MAX_DISTRICT} characters")
    if not isinstance(reference, str) or not reference.strip() or len(reference.strip()) > MAX_REFERENCE:
        raise ValueError(f"Give an official roster/source reference of up to {MAX_REFERENCE} characters")
    if body.get("verified") is not True:
        raise ValueError("Confirm that you checked this lawyer against the official legal-aid roster")

    name, district, reference = name.strip(), district.strip(), reference.strip()
    lawyer_id = uuid.uuid4().hex
    verified_at = _now()
    with store._session(db) as session:
        rows = session.select("legal_aid_roster", {"active": True})
        if any(row["name"].casefold() == name.casefold()
               and row["district"].casefold() == district.casefold() for row in rows):
            raise ValueError("This lawyer is already on the active roster for that district")
        session.insert("legal_aid_roster", [{
            "lawyer_id": lawyer_id, "name": name, "district": district,
            "verification_reference": reference, "verified_by": actor, "verified_at": verified_at,
            "active": True, "created_at": verified_at,
        }])
        store.audit(actor, role, "legal_aid_roster_lawyer_added", f"legal_aid_lawyer:{lawyer_id}",
                    {"lawyer_id": lawyer_id, "district": district}, db=session)
        session.commit()
        lawyer = session.select("legal_aid_roster", {"lawyer_id": lawyer_id})[0]
    return lawyer


def deactivate_lawyer(db, lawyer_id: str, actor: str, role: str) -> Dict:
    if role != "staff":
        raise PermissionError("Only court staff can manage the legal-aid roster")
    with store._session(db) as session:
        rows = session.select("legal_aid_roster", {"lawyer_id": lawyer_id})
        if not rows:
            raise LookupError(f"No legal-aid lawyer {lawyer_id}")
        lawyer = rows[0]
        if not lawyer["active"]:
            return lawyer
        active_alerts = session.select("alerts", {"status": ["pending", "approved", "filed", "heard"]})
        for alert in active_alerts:
            details = alert.get("details") or {}
            if not isinstance(details, dict):
                raise ValueError("Stored alert details are invalid")
            if details.get("legal_aid_lawyer_id") == lawyer_id:
                raise ValueError("Reassign this lawyer's active alerts before deactivating the roster entry")
        session.update("legal_aid_roster", {"lawyer_id": lawyer_id}, {"active": False})
        store.audit(actor, role, "legal_aid_roster_lawyer_deactivated", f"legal_aid_lawyer:{lawyer_id}",
                    {"lawyer_id": lawyer_id}, db=session)
        session.commit()
        lawyer["active"] = False
    return lawyer


def assign_alert(db, alert_id: int, lawyer_id: str, actor: str, role: str) -> Dict:
    if role != "staff":
        raise PermissionError("Only court staff can assign a legal-aid lawyer")
    if not isinstance(lawyer_id, str) or not lawyer_id or len(lawyer_id) > 64:
        raise ValueError("Choose a valid legal-aid lawyer")

    with store._session(db) as session:
        alerts = session.select("alerts", {"id": int(alert_id)})
        if not alerts:
            raise LookupError(f"No alert {alert_id}")
        alert = alerts[0]
        if alert["kind"] != "undertrial_release":
            raise ValueError("Lawyer assignment is available only for Undertrial Watch alerts")
        if alert["status"] != "pending":
            raise ValueError("Only a pending Undertrial alert can be assigned for review")
        lawyers = session.select("legal_aid_roster", {"lawyer_id": lawyer_id, "active": True})
        if not lawyers:
            raise LookupError("That lawyer is not on the active verified roster")

        stored_details = alert.get("details") or {}
        if not isinstance(stored_details, dict):
            raise ValueError("Stored alert details are invalid")
        details = dict(stored_details)
        if details.get("legal_aid_lawyer_id") == lawyer_id and details.get("lawyer_review_requested_at"):
            return {"alert_id": int(alert_id), "case_id": alert["case_id"], "details": details}

        lawyer = lawyers[0]
        now = _now()
        details.update({
            "legal_aid_lawyer_id": lawyer_id,
            "legal_aid_lawyer_name": lawyer["name"],
            "legal_aid_lawyer_district": lawyer["district"],
            "legal_aid_lawyer_assigned_at": now,
            "legal_aid_lawyer_assigned_by": actor,
            "lawyer_review_requested_at": now,
            "lawyer_review_requested_by": actor,
        })
        session.update("alerts", {"id": int(alert_id)}, {"details": details})
        store.audit(actor, role, "undertrial_lawyer_assigned", f"alert:{alert_id}",
                    {"lawyer_id": lawyer_id, "lawyer_review_requested": True}, db=session)
        session.commit()
        case = store.get_case(alert["case_id"], db=session)
        source = (case or {}).get("source") or "unknown"

    impact.record("undertrial_lawyer_assigned", source=source)
    return {"alert_id": int(alert_id), "case_id": alert["case_id"], "details": details}
