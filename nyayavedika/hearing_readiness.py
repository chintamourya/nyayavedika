"""Staff-managed hearing preparation checks, kept separate from legal decisions."""
from datetime import datetime, timezone
import uuid
from typing import Dict, List

from . import documents, impact, store

STATUSES = ("open", "ready", "not_applicable")
MAX_ITEMS = 30
MAX_LABEL_LENGTH = 180


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def items(case: Dict) -> List[Dict]:
    value = case.get("hearing_readiness") or []
    if not isinstance(value, list):
        raise ValueError("Stored hearing-readiness checklist is invalid")
    return value


def system_signals(review_fields: List[str], conflicts: List[Dict], documents_list: List[Dict]) -> List[Dict]:
    """Return observable follow-ups; absence is never treated as proof a document is required."""
    signals = []
    if not documents_list:
        signals.append({
            "key": "no_documents",
            "title": "No case documents attached",
            "detail": "Confirm whether documents are needed for the upcoming hearing.",
        })
    for field in review_fields:
        signals.append({
            "key": f"field:{field}",
            "title": "Extracted case field needs review",
            "detail": field.replace("_", " "),
            "field": field,
        })
    for conflict in conflicts:
        field = conflict.get("field")
        if field:
            signals.append({
                "key": f"conflict:{field}",
                "title": "Documents disagree on a case field",
                "detail": field.replace("_", " "),
            })
    for document in documents_list:
        pages = document.get("low_confidence_pages") or []
        if pages:
            signals.append({
                "key": f"ocr:{document['doc_id']}",
                "title": "Low OCR confidence",
                "detail": f"{document['filename']}: page(s) {', '.join(str(page) for page in pages)}",
            })
    return signals


def update(db, case_id: str, body: Dict, actor: str, role: str) -> Dict:
    action = body.get("action")
    if action not in ("add", "status", "remove"):
        raise ValueError("action must be add, status, or remove")

    action_event = None
    with store._session(db) as session:
        rows = session.select("cases", {"case_id": case_id})
        if not rows:
            raise LookupError(f"No case {case_id}")
        case_row = rows[0]
        data = case_row.get("data") or {}
        if not isinstance(data, dict):
            raise ValueError("Stored case data is invalid")
        checklist = data.get("hearing_readiness") or []
        if not isinstance(checklist, list):
            raise ValueError("Stored hearing-readiness checklist is invalid")
        checklist = list(checklist)
        details = {}

        if action == "add":
            label = body.get("label")
            if not isinstance(label, str) or not label.strip() or len(label) > 500:
                raise ValueError("Give a checklist item of up to 500 characters")
            label = documents.redact_pii(label).strip()
            if not label or len(label) > MAX_LABEL_LENGTH:
                raise ValueError(f"Checklist items must be at most {MAX_LABEL_LENGTH} characters after redaction")
            if len(checklist) >= MAX_ITEMS:
                raise ValueError(f"A case can have at most {MAX_ITEMS} checklist items")
            item_id = uuid.uuid4().hex
            now = _now()
            checklist.append({"id": item_id, "label": label, "status": "open", "created_at": now, "updated_at": now})
            action_event = "hearing_readiness_item_added"
            details = {"item_id": item_id, "status": "open"}
        else:
            item_id = body.get("item_id")
            if not isinstance(item_id, str) or not item_id or len(item_id) > 64:
                raise ValueError("Give a valid checklist item id")
            item_index = next((i for i, item in enumerate(checklist) if item.get("id") == item_id), None)
            if item_index is None:
                raise LookupError(f"No checklist item {item_id}")
            item = dict(checklist[item_index])
            previous = item.get("status", "open")
            if action == "remove":
                checklist.pop(item_index)
                action_event = "hearing_readiness_item_removed"
                details = {"item_id": item_id, "status": previous}
            else:
                status = body.get("status")
                if status not in STATUSES:
                    raise ValueError(f"status must be one of {', '.join(STATUSES)}")
                if status == previous:
                    return {"items": checklist}
                item.update(status=status, updated_at=_now())
                checklist[item_index] = item
                action_event = {
                    "ready": "hearing_readiness_item_marked_ready",
                    "not_applicable": "hearing_readiness_item_marked_not_applicable",
                    "open": "hearing_readiness_item_reopened",
                }[status]
                details = {"item_id": item_id, "from": previous, "to": status}

        data["hearing_readiness"] = checklist
        session.update("cases", {"case_id": case_id}, {"data": data})
        store.audit(actor, role, f"hearing_readiness_{action}", f"case:{case_id}", details, db=session)
        session.commit()
        source = case_row.get("source") or "synthetic"

    impact.record(action_event, source=source)
    return {"items": checklist}
