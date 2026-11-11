"""PostgreSQL persistence (SQLAlchemy Core, MIT + pg8000 driver, BSD-3).

DATABASE_URL examples:
    postgresql+pg8000://nyayavedika:password@localhost:5432/nyayavedika     (production / pilot)
    sqlite:///nyayavedika_dev.db                                        (local dev fallback)

Privacy by design: legal-aid and assistant tables store categories, district and outcomes only -
never names, phone numbers or ID numbers.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import (JSON, Boolean, Column, Date, DateTime, Float, Integer, MetaData, String, Table, Text,
                        create_engine, func, select)
from sqlalchemy.engine import Engine

from . import config

logger = logging.getLogger(__name__)
metadata = MetaData()


def _now():
    return datetime.now(timezone.utc)


cases = Table(
    "cases", metadata,
    Column("case_id", String(64), primary_key=True),
    Column("court_id", String(64), index=True, default="DEMO-DC"),
    Column("data", JSON, nullable=False),               # full case record (CIS/NJDG export fields)
    Column("score", Float), Column("band", String(16), index=True),
    Column("flags", JSON), Column("route", Text),
    Column("updated_at", DateTime(timezone=True), default=_now, onupdate=_now),
)

documents = Table(
    "documents", metadata,
    Column("doc_id", String(64), primary_key=True),     # content hash
    Column("case_id", String(64), index=True),
    Column("filename", String(255)), Column("pages", Integer), Column("ocr_pages", Integer),
    Column("analysis", JSON), Column("verified", Boolean, default=False),
    Column("created_at", DateTime(timezone=True), default=_now),
)

advocate_workspaces = Table(
    "advocate_workspaces", metadata,
    Column("workspace_hash", String(64), primary_key=True),
    Column("created_at", DateTime(timezone=True), default=_now),
)

advocate_documents = Table(
    "advocate_documents", metadata,
    Column("doc_id", String(64), primary_key=True),
    Column("workspace_hash", String(64), nullable=False, index=True),
    Column("storage_key", String(64), nullable=False),
    Column("filename", String(255), nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("pages", Integer, nullable=False),
    Column("ocr_pages", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), default=_now),
)

legal_aid_requests = Table(
    "legal_aid_requests", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", DateTime(timezone=True), default=_now),
    Column("channel", String(32)),                       # web / helpdesk / paralegal / jail
    Column("district", String(64)), Column("language", String(32)),
    Column("eligible", Boolean), Column("grounds", JSON),
    Column("status", String(32), default="checked"),     # checked -> drafted -> applied -> lawyer_assigned
    # kept in step with nyayavedika/db_schema.py so a fresh create_all() already has them (the migration only adds missing ones)
    Column("state", String(64)), Column("source", String(32)),
    Column("applied_on", Date), Column("lawyer_assigned_on", Date), Column("resolved_on", Date),
)

alerts = Table(
    "alerts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", DateTime(timezone=True), default=_now),
    Column("case_id", String(64), index=True), Column("kind", String(48)),
    Column("details", JSON), Column("draft", Text),
    Column("status", String(16), default="pending"),     # pending -> approved / dismissed
    Column("decided_at", DateTime(timezone=True)), Column("decision_note", Text),
)

cause_lists = Table(
    "cause_lists", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", DateTime(timezone=True), default=_now),
    Column("court_id", String(64)), Column("start_date", String(10)),
    Column("plan", JSON), Column("metrics", JSON), Column("explanation", Text),
    Column("status", String(16), default="draft"),       # draft -> published / rejected
)

impact_events = Table(
    "impact_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), default=_now, index=True),
    Column("event", String(64), index=True), Column("value", Float, default=1.0),
    Column("meta", JSON),
)

reach_visitors = Table(
    "reach_visitors", metadata,
    Column("visitor_hash", String(64), primary_key=True),
    Column("door", String(16), primary_key=True),
    Column("first_seen", DateTime(timezone=True), default=_now),
)

browser_feature_activity = Table(
    "browser_feature_activity", metadata,
    Column("visitor_hash", String(64), primary_key=True),
    Column("door", String(16), primary_key=True),
    Column("feature", String(64), primary_key=True),
    Column("first_seen", DateTime(timezone=True), default=_now),
)

feedback = Table(
    "feedback", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), default=_now),
    Column("feature", String(48)), Column("role", String(32)),
    Column("rating", Integer), Column("comment", Text),
)

_engine: Optional[Engine] = None


def _connect_args(url: str) -> Dict[str, Any]:
    """Hosted Postgres (Supabase etc.) requires TLS; pg8000 needs an explicit SSL context."""
    if not url.startswith("postgresql"):
        return {}
    host = url.split("@")[-1].split("/")[0].split(":")[0]
    if host in config.DATABASE_LOCAL_HOSTS:
        return {}
    import ssl
    ca = config.DATABASE_SSL_CA          # optional: path to Supabase's CA .crt for full verification
    if ca:
        return {"ssl_context": ssl.create_default_context(cafile=ca)}
    # Same as libpq sslmode=require: encrypted, but the chain is not verified (Supabase's pooler cert is signed
    # by a private CA that is not in the OS trust store, so strict verification fails with
    # "self-signed certificate in certificate chain").
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return {"ssl_context": ctx}


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, future=True,
                                connect_args=_connect_args(config.DATABASE_URL))
        metadata.create_all(_engine)
        logger.info("Database ready (%s)", config.DATABASE_URL.split("@")[-1])
    return _engine


def reset_engine_for_tests(url: str) -> None:
    global _engine
    config.DATABASE_URL = url
    _engine = None


# ---------------------------------------------------------------- cases
def upsert_cases(records: Iterable[Dict[str, Any]], scores: Optional[Dict[str, Dict]] = None) -> int:
    """Batched upsert: one SELECT for existing ids, then multi-row INSERT / executemany UPDATE
    (per-row round trips were minutes-slow against a remote database such as Supabase)."""
    from sqlalchemy import bindparam
    scores = scores or {}
    rows: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        s = scores.get(rec["case_id"], {})
        rows[rec["case_id"]] = {"case_id": rec["case_id"], "court_id": rec.get("court_id", "DEMO-DC"), "data": rec,
                                "score": s.get("score"), "band": s.get("band"), "flags": s.get("flags"),
                                "route": s.get("recommended_route"), "updated_at": _now()}
    if not rows:
        return 0
    ids = list(rows)
    with engine().begin() as conn:
        existing = set()
        for i in range(0, len(ids), 500):
            existing.update(r[0] for r in conn.execute(select(cases.c.case_id).where(cases.c.case_id.in_(ids[i:i + 500]))))
        new_rows = [r for k, r in rows.items() if k not in existing]
        upd_rows = [{**r, "b_id": r["case_id"]} for k, r in rows.items() if k in existing]
        for i in range(0, len(new_rows), 200):
            conn.execute(cases.insert(), new_rows[i:i + 200])
        if upd_rows:
            cols = ("court_id", "data", "score", "band", "flags", "route", "updated_at")
            conn.execute(cases.update().where(cases.c.case_id == bindparam("b_id"))
                         .values({c: bindparam(c) for c in cols}), upd_rows)
    return len(rows)


def list_cases(court_id: Optional[str] = None, custody_only: bool = False) -> List[Dict]:
    q = select(cases.c.data)
    if court_id:
        q = q.where(cases.c.court_id == court_id)
    with engine().connect() as conn:
        rows = [r.data for r in conn.execute(q)]
    return [r for r in rows if r.get("accused_in_custody")] if custody_only else rows


def get_case(case_id: str) -> Optional[Dict]:
    with engine().connect() as conn:
        row = conn.execute(select(cases).where(cases.c.case_id == case_id)).first()
    if not row:
        return None
    return {**row.data, "_score": row.score, "_band": row.band, "_flags": row.flags, "_route": row.route}


def merge_case_signals(case_id: str, signals: Dict[str, Any]) -> None:
    """Fold facts extracted from documents back into the case record (only fills gaps)."""
    with engine().begin() as conn:
        row = conn.execute(select(cases.c.data).where(cases.c.case_id == case_id)).first()
        if not row:
            return
        data = dict(row.data)
        for k, v in signals.items():
            if v not in (None, "", []) and not data.get(k):
                data[k] = v
        conn.execute(cases.update().where(cases.c.case_id == case_id).values(data=data, updated_at=_now()))


# ---------------------------------------------------------------- generic helpers
def insert(table: Table, **values) -> int:
    with engine().begin() as conn:
        res = conn.execute(table.insert().values(**values))
        return res.inserted_primary_key[0] if res.inserted_primary_key else 0


def update(table: Table, key_col: str, key, **values) -> None:
    with engine().begin() as conn:
        conn.execute(table.update().where(table.c[key_col] == key).values(**values))


def fetch(table: Table, where=None, limit: int = 200, order=None) -> List[Dict]:
    q = select(table)
    if where is not None:
        q = q.where(where)
    if order is not None:
        q = q.order_by(order)
    with engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(q.limit(limit))]


def save_document(doc_id: str, **values) -> None:
    with engine().begin() as conn:
        if conn.execute(select(documents.c.doc_id).where(documents.c.doc_id == doc_id)).first():
            conn.execute(documents.update().where(documents.c.doc_id == doc_id).values(**values))
        else:
            conn.execute(documents.insert().values(doc_id=doc_id, **values))


def create_advocate_workspace(workspace_hash: str) -> None:
    with engine().begin() as conn:
        conn.execute(advocate_workspaces.insert().values(workspace_hash=workspace_hash))


def has_advocate_workspace(workspace_hash: str) -> bool:
    with engine().connect() as conn:
        return conn.execute(
            select(advocate_workspaces.c.workspace_hash)
            .where(advocate_workspaces.c.workspace_hash == workspace_hash)
        ).first() is not None


def register_advocate_document(workspace_hash: str, doc_id: str, storage_key: str, filename: str,
                               size_bytes: int, pages: int, ocr_pages: int) -> None:
    with engine().begin() as conn:
        conn.execute(advocate_documents.insert().values(
            workspace_hash=workspace_hash, doc_id=doc_id, storage_key=storage_key, filename=filename,
            size_bytes=size_bytes, pages=pages, ocr_pages=ocr_pages, created_at=_now(),
        ))


def get_advocate_document(workspace_hash: str, doc_id: str) -> Optional[Dict[str, Any]]:
    with engine().connect() as conn:
        row = conn.execute(select(advocate_documents).where(
            advocate_documents.c.workspace_hash == workspace_hash,
            advocate_documents.c.doc_id == doc_id,
        )).first()
    return dict(row._mapping) if row else None


def advocate_documents_by_size(workspace_hash: str, size_bytes: int) -> List[Dict[str, Any]]:
    with engine().connect() as conn:
        rows = conn.execute(select(advocate_documents).where(
            advocate_documents.c.workspace_hash == workspace_hash,
            advocate_documents.c.size_bytes == size_bytes,
        ).order_by(advocate_documents.c.created_at)).all()
    return [dict(row._mapping) for row in rows]


def is_advocate_document(doc_id: str) -> bool:
    with engine().connect() as conn:
        return conn.execute(
            select(advocate_documents.c.doc_id).where(advocate_documents.c.doc_id == doc_id)
        ).first() is not None


def event_totals() -> Dict[str, Dict[str, float]]:
    q = select(impact_events.c.event, func.count(), func.sum(impact_events.c.value)).group_by(impact_events.c.event)
    with engine().connect() as conn:
        return {e: {"count": c, "total": float(t or 0)} for e, c, t in conn.execute(q)}


def register_reach(visitor_hash: str, door: str) -> bool:
    """Count a pseudonymous browser once per site or portal; duplicate visits are harmless."""
    from sqlalchemy.exc import IntegrityError
    try:
        with engine().begin() as conn:
            conn.execute(reach_visitors.insert().values(visitor_hash=visitor_hash, door=door))
        return True
    except IntegrityError:
        return False


def delete_reach(visitor_hash: str) -> None:
    with engine().begin() as conn:
        conn.execute(reach_visitors.delete().where(reach_visitors.c.visitor_hash == visitor_hash))
        conn.execute(browser_feature_activity.delete().where(browser_feature_activity.c.visitor_hash == visitor_hash))


def reach_totals() -> Dict[str, Any]:
    with engine().connect() as conn:
        rows = conn.execute(select(reach_visitors.c.visitor_hash, reach_visitors.c.door)).all()
    all_browsers = {row.visitor_hash for row in rows}
    by_door = {door: sum(1 for row in rows if row.door == door) for door in ("citizen", "advocate", "staff")}
    public_browsers = len({row.visitor_hash for row in rows if row.door == "public"})
    return {"unique_browsers": len(all_browsers), "public_browsers": public_browsers, "by_door": by_door}


def register_browser_feature(visitor_hash: str, door: str, feature: str) -> bool:
    """Count a browser once per portal feature without retaining its raw browser ID."""
    from sqlalchemy.exc import IntegrityError
    try:
        with engine().begin() as conn:
            conn.execute(browser_feature_activity.insert().values(
                visitor_hash=visitor_hash, door=door, feature=feature,
            ))
        return True
    except IntegrityError:
        return False


def browser_feature_totals() -> Dict[str, Any]:
    with engine().connect() as conn:
        rows = conn.execute(select(
            browser_feature_activity.c.visitor_hash,
            browser_feature_activity.c.door,
            browser_feature_activity.c.feature,
        )).all()
    all_browsers = {row.visitor_hash for row in rows}
    by_door: Dict[str, set] = {}
    by_feature: Dict[str, set] = {}
    by_door_feature: Dict[str, Dict[str, set]] = {}
    for row in rows:
        by_door.setdefault(row.door, set()).add(row.visitor_hash)
        by_feature.setdefault(row.feature, set()).add(row.visitor_hash)
        by_door_feature.setdefault(row.door, {}).setdefault(row.feature, set()).add(row.visitor_hash)
    return {
        "unique_browsers": len(all_browsers),
        "by_door": {door: len(visitors) for door, visitors in by_door.items()},
        "by_feature": {feature: len(visitors) for feature, visitors in by_feature.items()},
        "by_door_feature": {
            door: {feature: len(visitors) for feature, visitors in features.items()}
            for door, features in by_door_feature.items()
        },
    }