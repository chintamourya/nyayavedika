"""Demo access control: three roles from static bearer tokens (no real login).

The role is resolved server-side from `Authorization: Bearer <token>` against DEMO_TOKEN_STAFF /
DEMO_TOKEN_LAWYER / DEMO_TOKEN_CITIZEN. Anything the client sends as "mode" or "agent" is ignored.
POLICY is the one role matrix; server.py attaches `guard("<METHOD> <path>")` to every /api route.
"""
import hmac
from dataclasses import dataclass
from typing import Optional, Tuple

from . import config

STAFF, LAWYER, CITIZEN = "staff", "lawyer", "citizen"
ALL_ROLES = (STAFF, LAWYER, CITIZEN)
COURT = (STAFF, LAWYER)

# "METHOD /path" -> roles allowed. /api/health, / and /static stay public (no case data).
POLICY = {
    # staff: docket, cases, triage, schedule, cause lists, insights
    "GET /api/cases": (STAFF,),
    "POST /api/cases": (STAFF,),
    "POST /api/triage": (STAFF,),
    "POST /api/schedule": (STAFF,),
    "POST /api/registry/run": (STAFF,),
    "POST /api/registry/decide": (STAFF,),
    "GET /api/impact": (STAFF,),
    "GET /api/impact/export.csv": (STAFF,),
    "GET /api/intake/limits": (STAFF,),
    "POST /api/intake/batches": (STAFF,),
    "GET /api/intake/batches/{batch_id}": (STAFF,),
    "POST /api/intake/batches/{batch_id}/jobs/{job_id}/retry": (STAFF,),
    "POST /api/intake/rows": (STAFF,),
    "PATCH /api/cases/{case_id:path}": (STAFF,),
    "POST /api/cause-lists/draft": (STAFF,),
    "GET /api/cause-lists/{cause_list_id}": (STAFF,),
    "POST /api/cause-lists/{cause_list_id}/publish": (STAFF,),
    "POST /api/cause-lists/{cause_list_id}/reject": (STAFF,),
    "POST /api/cases/{case_id:path}/accept-slot": (STAFF,),
    "POST /api/hearings/{hearing_id}/outcome": (STAFF,),
    "GET /api/today": COURT,
    "GET /api/rules": COURT,
    "GET /api/docket": (STAFF,),
    "GET /api/cases/{case_id:path}/detail": (STAFF,),
    "GET /api/insights/weekly": (STAFF,),
    "GET /api/documents/{doc_id}/pages/{page}": COURT,
    "GET /api/whoami": ALL_ROLES,
    "POST /api/jobs/{name}/run": (STAFF,),
    # court users: case files, drafting, undertrial alerts (lawyer decides; staff may read)
    "POST /api/documents/analyze": COURT,
    "POST /api/documents/summarize": ALL_ROLES,
    "GET /api/sample-judgment": COURT,
    "POST /api/summarize/offline": COURT,
    "POST /api/draft": COURT,
    "GET /api/drafting/sections": COURT,
    "POST /api/undertrial/scan": COURT,
    "GET /api/alerts": COURT,
    "POST /api/alerts/decide": (LAWYER,),
    "POST /api/alerts/{alert_id}/state": COURT,   # lawyer decides; staff may record filed / heard / outcome
    "GET /api/alerts/data-needed": COURT,
    "POST /api/legal-aid/{request_id}/outcome": COURT,
    # everyone: legal-aid check, assistant (agent chosen by role), feedback
    "POST /api/legal-aid": ALL_ROLES,
    "POST /api/legal-aid/application.docx": ALL_ROLES,
    "POST /api/legal-aid/explain": ALL_ROLES,
    "POST /api/legal-aid/ask": ALL_ROLES,
    "GET /api/legal-aid/kb": ALL_ROLES,
    "GET /api/legal-aid/topics": ALL_ROLES,
    "GET /api/legal-aid/state-fact": ALL_ROLES,
    "GET /api/alerts/{alert_id}/release.docx": COURT,
    "POST /api/agent/chat": ALL_ROLES,
    "POST /api/agent/chat/files": ALL_ROLES,
    "POST /api/agent/resume": ALL_ROLES,
    "POST /api/feedback": ALL_ROLES,
    # landing-page field feedback: anyone may read the wall and submit; only staff can hide an entry
    "GET /api/field-feedback": ALL_ROLES,
    "GET /api/field-feedback/all": ALL_ROLES,
    "POST /api/field-feedback": ALL_ROLES,
    "POST /api/field-feedback/{feedback_id}/hide": (STAFF,),
}
PUBLIC = {"GET /api/health"}


@dataclass(frozen=True)
class Principal:
    role: str
    actor: str      # who to record on decisions; demo tokens are per role, so "demo-<role>"


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _tokens() -> Tuple[Tuple[str, str], ...]:
    # Read at call time so tests (and a restarted demo) can change config.
    return ((STAFF, config.DEMO_TOKEN_STAFF), (LAWYER, config.DEMO_TOKEN_LAWYER), (CITIZEN, config.DEMO_TOKEN_CITIZEN))


def configured_roles() -> Tuple[str, ...]:
    return tuple(role for role, tok in _tokens() if tok)


def token_problems() -> list:
    """Configuration mistakes that break role separation. Shown as warnings at start-up.
    Two roles sharing one token would both resolve to the first role (staff), so the lawyer-only
    approval endpoint could never be used; short or placeholder tokens are guessable."""
    problems, seen = [], {}
    for role, tok in _tokens():
        if not tok:
            continue
        if tok in seen:
            problems.append(f"DEMO_TOKEN_{role.upper()} equals DEMO_TOKEN_{seen[tok].upper()}: both would act as '{seen[tok]}'")
        seen.setdefault(tok, role)
        if len(tok) < 12 or tok.lower().startswith("change-me"):
            problems.append(f"DEMO_TOKEN_{role.upper()} is short or a placeholder: use a long random string")
    return problems


def resolve(authorization: Optional[str]) -> Principal:
    """Bearer token -> Principal, or AuthError(401)."""
    scheme, _, token = (authorization or "").strip().partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise AuthError(401, "Sign in required: send 'Authorization: Bearer <demo token>'")
    for role, expected in _tokens():
        if expected and hmac.compare_digest(token.encode(), expected.encode()):
            return Principal(role=role, actor=f"demo-{role}")
    raise AuthError(401, "Unknown or expired token")


def check(authorization: Optional[str], *roles: str) -> Principal:
    """Resolve the caller and enforce the role list: 401 unknown caller, 403 wrong role.
    No token at all on a citizen endpoint = anonymous citizen (the portal needs no login) when ANONYMOUS_CITIZEN is on;
    a wrong token is still 401, and staff / lawyer endpoints always need a token."""
    if not (authorization or "").strip() and CITIZEN in roles and config.ANONYMOUS_CITIZEN:
        return Principal(role=CITIZEN, actor="anonymous-citizen")
    principal = resolve(authorization)
    if principal.role not in roles:
        raise AuthError(403, f"The '{principal.role}' role cannot use this endpoint")
    return principal


def require_role(*roles: str):
    """FastAPI dependency returning the Principal; raises HTTP 401/403."""
    from fastapi import Header, HTTPException

    def dependency(authorization: Optional[str] = Header(default=None)) -> Principal:
        try:
            return check(authorization, *roles)
        except AuthError as exc:
            raise HTTPException(exc.status, exc.message,
                                headers={"WWW-Authenticate": "Bearer"} if exc.status == 401 else None)

    dependency.roles = roles
    return dependency


def guard(key: str):
    """`Depends(...)` for the POLICY entry `key` ("METHOD /path"). KeyError if the route has no policy."""
    from fastapi import Depends
    return Depends(require_role(*POLICY[key]))
