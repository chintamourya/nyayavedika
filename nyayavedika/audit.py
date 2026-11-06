"""Who decided what. Every human decision (approve, dismiss, publish, outcome, edit) goes through record().

Writes an audit_log row (Phase 2 table) plus an impact event "decision" for the counts. Details must not
contain personal data - ids, statuses and counts only. An audit failure is logged, never raised.
"""
import logging
from typing import Any

from . import impact

logger = logging.getLogger(__name__)


def record(principal, action: str, entity: str, **detail: Any) -> None:
    logger.info("decision actor=%s role=%s action=%s entity=%s", principal.actor, principal.role, action, entity)
    try:
        from . import store
        store.audit(principal.actor, principal.role, action, entity, detail)
    except Exception as exc:  # e.g. migration not run yet
        logger.warning("audit_log write failed (%s); run scripts/migrate_demo.py", exc)
    impact.record("decision", actor=principal.actor, role=principal.role, action=action, entity=entity, **detail)
