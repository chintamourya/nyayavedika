"""Repository layer for the demo data model (nyayavedika/db_schema.py). New code reads and writes through here.

One small adapter, two backends:
    sqlite:///...      -> Python's built-in sqlite3 (no extra dependency; tests run on it)
    postgresql+pg8000  -> a SQLAlchemy connection from db.engine()
SQL uses :named parameters; JSON / date / timestamp values are cast per dialect from the column type
in SCHEMA, and rows come back normalised (JSON parsed, dates as ISO strings, booleans as bool).
The older helpers in db.py keep working; they are not rewritten.
"""
import json
import logging
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from . import config
from .db_schema import SCHEMA, column_types

logger = logging.getLogger(__name__)

_PG_CASTS = {"json": "JSONB", "date": "DATE", "ts": "TIMESTAMPTZ"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_date(value) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(value)[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _prep(typ: Optional[str], value: Any) -> Any:
    if value is None:
        return None
    if typ == "json":
        return json.dumps(value, default=str, ensure_ascii=False)
    if typ == "date":
        return _iso_date(value)
    if typ == "ts":
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    if typ == "bool":
        return bool(value)
    return value


def _norm(types: Dict[str, str], row: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in row.items():
        typ = types.get(k)
        if v is not None:
            if typ == "json" and isinstance(v, str):
                v = json.loads(v)
            elif typ == "date":
                v = _iso_date(v)
            elif typ == "ts" and isinstance(v, (date, datetime)):
                v = v.isoformat()
            elif typ == "bool":
                v = bool(v)
        out[k] = v
    return out


class Database:
    """Thin DB-API style wrapper. Use as a context manager: commits on success, rolls back on error."""

    def __init__(self, url: Optional[str] = None):
        url = url or config.DATABASE_URL
        self.url = url
        if url.startswith("sqlite"):
            self.dialect = "sqlite"
            path = url.split(":///", 1)[1] if ":///" in url else ":memory:"
            self._conn = sqlite3.connect(path or ":memory:", timeout=config.SQLITE_TIMEOUT_SECONDS)  # worker threads wait for the write lock
            self._conn.row_factory = sqlite3.Row
        elif url.startswith("postgresql"):
            self.dialect = "postgresql"
            from sqlalchemy import text
            from . import db as sa_db
            self._text = text
            self._conn = sa_db.engine().connect()
        else:
            raise ValueError(f"unsupported DATABASE_URL scheme: {url.split(':', 1)[0]}")
        self._col_cache: Optional[Dict[str, Dict[str, str]]] = None

    # ---------------------------------------------------------------- raw
    def execute(self, sql: str, params: Optional[Dict] = None) -> List[Dict]:
        if self.dialect == "postgresql" and sql.lstrip()[:6].upper() in ("CREATE", "ALTER ", "DROP T"):
            self._col_cache = None  # DDL changed the schema: reload on next columns()
        if self.dialect == "sqlite":
            cur = self._conn.execute(sql, params or {})
            return [dict(r) for r in cur.fetchall()] if cur.description else []
        res = self._conn.execute(self._text(sql), params or {})
        return [dict(m) for m in res.mappings()] if res.returns_rows else []

    def executemany(self, sql: str, rows: List[Dict]) -> None:
        if not rows:
            return
        if self.dialect == "sqlite":
            self._conn.executemany(sql, rows)
        else:
            self._conn.execute(self._text(sql), rows)

    def query(self, sql: str, params: Optional[Dict] = None, table: Optional[str] = None) -> List[Dict]:
        rows = self.execute(sql, params)
        return [_norm(column_types(table), r) for r in rows] if table else rows

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.rollback() if exc_type else self.commit()
        finally:
            self.close()

    # ---------------------------------------------------------------- introspection
    def tables(self) -> set:
        if self.dialect == "sqlite":
            return {r["name"] for r in self.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return {r["table_name"] for r in self.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")}

    def columns(self, table: str) -> Dict[str, str]:
        if self.dialect == "sqlite":
            return {r["name"]: (r["type"] or "").lower() for r in self.execute(f"PRAGMA table_info({table})")}
        if self._col_cache is None:  # one round trip for every table instead of one per table
            self._col_cache = {}
            for r in self.execute("SELECT table_name, column_name, data_type FROM information_schema.columns "
                                  "WHERE table_schema = current_schema()"):
                self._col_cache.setdefault(r["table_name"], {})[r["column_name"]] = r["data_type"].lower()
        return dict(self._col_cache.get(table, {}))

    def index_names(self) -> set:
        """Existing index names (PostgreSQL), so migrate can skip CREATE INDEX IF NOT EXISTS round trips."""
        if self.dialect != "postgresql":
            return set()
        return {r["indexname"] for r in self.execute("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")}

    # ---------------------------------------------------------------- builders
    def _ph(self, typ: Optional[str], name: str) -> str:
        if self.dialect == "postgresql" and typ in _PG_CASTS:
            return f"CAST(:{name} AS {_PG_CASTS[typ]})"
        return f":{name}"

    def _where(self, table: str, where: Optional[Dict]) -> (str, Dict):
        if not where:
            return "", {}
        types, parts, params = column_types(table), [], {}
        for i, (col, val) in enumerate(where.items()):
            if val is None:
                parts.append(f"{col} IS NULL")
            elif isinstance(val, (list, tuple, set)):
                names = [f"w{i}_{j}" for j in range(len(val))]
                parts.append(f"{col} IN ({', '.join(self._ph(types.get(col), n) for n in names)})" if names else "1 = 0")
                params.update({n: _prep(types.get(col), v) for n, v in zip(names, val)})
            else:
                parts.append(f"{col} = {self._ph(types.get(col), f'w{i}')}")
                params[f"w{i}"] = _prep(types.get(col), val)
        return " WHERE " + " AND ".join(parts), params

    def _rows(self, table: str, rows: Iterable[Dict]) -> (List[str], List[Dict]):
        types = column_types(table)
        rows = list(rows)
        cols = [c for c in types if any(c in r for r in rows)]
        return cols, [{c: _prep(types[c], r.get(c)) for c in cols} for r in rows]

    def _insert_many(self, table: str, cols: List[str], types: Dict[str, str], prepared: List[Dict], suffix: str = "") -> None:
        """One multi-row INSERT per chunk on PostgreSQL (executemany over pg8000 is one round trip per row,
        which is minutes on a remote database). SQLite keeps executemany."""
        if self.dialect == "sqlite" or len(prepared) == 1:
            self.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES "
                             f"({', '.join(self._ph(types[c], c) for c in cols)}){suffix}", prepared)
            return
        step = max(1, min(200, 30000 // max(1, len(cols))))
        for i in range(0, len(prepared), step):
            chunk, params, values = prepared[i:i + step], {}, []
            for n, row in enumerate(chunk):
                values.append("(" + ", ".join(self._ph(types[c], f"{c}_{n}") for c in cols) + ")")
                params.update({f"{c}_{n}": row[c] for c in cols})
            self.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES {', '.join(values)}{suffix}", params)

    def insert(self, table: str, rows: Iterable[Dict], returning: Optional[str] = None) -> Optional[Any]:
        """Insert rows. With `returning` (single row), return that column of the new row (e.g. its id)."""
        cols, prepared = self._rows(table, rows)
        if not prepared:
            return None
        types = column_types(table)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(self._ph(types[c], c) for c in cols)})"
        if returning and len(prepared) == 1:
            return self.execute(f"{sql} RETURNING {returning}", prepared[0])[0][returning]
        self._insert_many(table, cols, types, prepared)
        return None

    def upsert(self, table: str, rows: Iterable[Dict], keys: Iterable[str], update: bool = True) -> int:
        """INSERT ... ON CONFLICT (keys) DO UPDATE (or DO NOTHING when update=False, keeping existing rows)."""
        cols, prepared = self._rows(table, rows)
        if not prepared:
            return 0
        keys, types = list(keys), column_types(table)
        if self.dialect == "postgresql":  # one multi-row statement cannot touch the same key twice
            prepared = list({tuple(r.get(k) for k in keys): r for r in prepared}.values())
        rest = [c for c in cols if c not in keys]
        action = ("DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in rest)) if update and rest else "DO NOTHING"
        self._insert_many(table, cols, types, prepared, f" ON CONFLICT ({', '.join(keys)}) {action}")
        return len(prepared)

    def update(self, table: str, where: Dict, values: Dict) -> None:
        types = column_types(table)
        sets = ", ".join(f"{c} = {self._ph(types.get(c), f'v_{c}')}" for c in values)
        clause, params = self._where(table, where)
        params.update({f"v_{c}": _prep(types.get(c), v) for c, v in values.items()})
        self.execute(f"UPDATE {table} SET {sets}{clause}", params)

    def select(self, table: str, where: Optional[Dict] = None, order: Optional[str] = None,
               limit: Optional[int] = None) -> List[Dict]:
        clause, params = self._where(table, where)
        sql = f"SELECT * FROM {table}{clause}" + (f" ORDER BY {order}" if order else "") + \
              (f" LIMIT {int(limit)}" if limit else "")
        return self.query(sql, params, table)

    def delete(self, table: str, where: Optional[Dict] = None) -> None:
        clause, params = self._where(table, where)
        self.execute(f"DELETE FROM {table}{clause}", params)

    def count(self, table: str, where: Optional[Dict] = None) -> int:
        clause, params = self._where(table, where)
        return int(self.execute(f"SELECT COUNT(*) AS n FROM {table}{clause}", params)[0]["n"])


def connect(url: Optional[str] = None, migrate: bool = True) -> Database:
    """Open a connection. The first time this process opens a given database it is migrated (idempotent), so no
    request path depends on start-up having run first: an app served without its lifespan (a test client, a worker
    started on its own, a script) used to see the old narrow `cases` table that db.engine()'s create_all() makes,
    and failed with "no such column: source". After the first open this costs nothing.
    migrate=False opens the database exactly as it is (for inspecting or testing the migration itself)."""
    db = Database(url)
    if migrate and db.url not in _prepared:
        try:
            with _migrate_lock:
                if db.url not in _prepared:
                    prepare_database(db)
        except Exception:
            db.close()
            raise
    return db


@contextmanager
def _session(db: Optional[Database]):
    if db is not None:
        yield db
    else:
        with connect() as own:
            yield own


# ============================================================================ cases
PROMOTED_BOOLS = ("accused_in_custody", "first_time_offender", "senior_citizen", "woman_or_child", "disability", "legal_aid")
PROMOTED_DATES = ("filing_date", "custody_since", "last_hearing_date", "next_hearing_date")


def _number(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def case_row(case: Dict, scored: Optional[Dict] = None, source: Optional[str] = None,
             data_quality: Optional[str] = None, field_provenance: Optional[Dict] = None) -> Dict:
    """Canonical cases row from a case dict. A missing boolean stays NULL ("unknown"), never False."""
    ms = case.get("max_sentence_years")
    life = str(ms).strip().lower() in ("life", "death") if ms not in (None, "") else None
    row = {
        "case_id": case["case_id"], "court_id": case.get("court_id") or "DEMO-DC",
        "case_type": case.get("case_type"), "stage": case.get("stage") or None,
        "status": case.get("status") or "pending",
        "max_sentence_years": None if life else _number(ms), "life_or_death": life,
        "act": case.get("act"), "section": None if case.get("section") is None else str(case.get("section")),
        "adjournments": case.get("adjournments"),
        "source": source or case.get("source") or "synthetic",
        "data_quality": data_quality or case.get("data_quality") or "complete",
        "field_provenance": field_provenance if field_provenance is not None else case.get("field_provenance"),
        "data": case, "updated_at": _now_iso(),
    }
    row.update({k: (None if case.get(k) is None else bool(case[k])) for k in PROMOTED_BOOLS})
    row.update({k: _iso_date(case.get(k)) for k in PROMOTED_DATES})
    if scored:
        row.update(score=scored.get("score"), band=scored.get("band"), flags=scored.get("flags"),
                   route=scored.get("recommended_route"))
    return row


def upsert_cases(cases: Iterable[Dict], scores: Optional[Dict[str, Dict]] = None, source: Optional[str] = None,
                 db: Optional[Database] = None) -> int:
    scores = scores or {}
    rows = [case_row(c, scores.get(c["case_id"]), source) for c in cases]
    with _session(db) as s:
        return s.upsert("cases", rows, ["case_id"])


def upsert_case(case: Dict, scored: Optional[Dict] = None, source: Optional[str] = None,
                data_quality: Optional[str] = None, field_provenance: Optional[Dict] = None,
                db: Optional[Database] = None) -> None:
    with _session(db) as s:
        s.upsert("cases", [case_row(case, scored, source, data_quality, field_provenance)], ["case_id"])


def _case_out(row: Dict) -> Dict:
    return {**(row.get("data") or {}), "source": row.get("source"), "data_quality": row.get("data_quality"),
            "field_provenance": row.get("field_provenance"), "_score": row.get("score"), "_band": row.get("band"),
            "_flags": row.get("flags"), "_route": row.get("route")}


def get_case(case_id: str, db: Optional[Database] = None) -> Optional[Dict]:
    with _session(db) as s:
        rows = s.select("cases", {"case_id": case_id})
    return _case_out(rows[0]) if rows else None


def get_cases(case_ids: Iterable[str], db: Optional[Database] = None) -> Dict[str, Dict]:
    """Many cases in one query (case_id -> case), so loops over listings / alerts do not issue one SELECT per row.
    Chunked so the IN list stays well under driver parameter limits."""
    ids = sorted({c for c in case_ids if c})
    out: Dict[str, Dict] = {}
    if not ids:
        return out
    with _session(db) as s:
        for i in range(0, len(ids), 500):
            for r in s.select("cases", {"case_id": ids[i:i + 500]}):
                out[r["case_id"]] = _case_out(r)
    return out


def pending_cases(court_id: Optional[str] = None, limit: Optional[int] = None, db: Optional[Database] = None) -> List[Dict]:
    where = {"status": "pending", **({"court_id": court_id} if court_id else {})}
    with _session(db) as s:
        return [_case_out(r) for r in s.select("cases", where, order="score DESC", limit=limit)]


def backfill_case_columns(db: Database) -> int:
    """Fill promoted columns for rows written by the older db.upsert_cases (only JSON data set)."""
    rows = db.query("SELECT case_id, data, score, band, flags, route FROM cases WHERE case_type IS NULL", table="cases")
    out = []
    for r in rows:
        if not r.get("data"):
            continue
        scored = {"score": r["score"], "band": r["band"], "flags": r["flags"], "recommended_route": r["route"]}
        out.append(case_row({**r["data"], "case_id": r["case_id"]}, scored))
    db.upsert("cases", out, ["case_id"])
    return len(out)


# ============================================================================ triage history and queue state
def insert_triage_scores(results: Iterable[Dict], rules_version: str, db: Optional[Database] = None) -> int:
    rows = [{"case_id": r["case_id"], "scored_at": _now_iso(), "score": r["score"], "band": r["band"],
             "flags": r["flags"], "reasons": r["reasons"], "rules_version": rules_version} for r in results]
    with _session(db) as s:
        s.insert("triage_scores", rows)
    return len(rows)


def queue_state(case_id: str, db: Optional[Database] = None) -> Optional[Dict]:
    with _session(db) as s:
        rows = s.select("case_queue_state", {"case_id": case_id})
    return rows[0] if rows else None


def upsert_queue_state(rows: Iterable[Dict], db: Optional[Database] = None) -> int:
    rows = [{**r, "updated_at": _now_iso()} for r in rows]
    with _session(db) as s:
        return s.upsert("case_queue_state", rows, ["case_id"])


def insert_listing(db: Optional[Database] = None, **row) -> int:
    with _session(db) as s:
        return s.insert("listings", [row], returning="id")


def insert_deferral(db: Optional[Database] = None, **row) -> int:
    with _session(db) as s:
        return s.insert("deferrals", [row], returning="id")


# ============================================================================ reference data
def _act_key(act: str) -> str:
    key = re.sub(r"[^a-z0-9]", "", (act or "").lower())
    return key[:-3] if key.endswith("act") and len(key) > 3 else key


def statute(act: str, section: str, db: Optional[Database] = None) -> Optional[Dict]:
    """Look up Act + section (e.g. 'BNS', '303(2)'). Falls back to the base section number."""
    sec = re.sub(r"(?i)^(sec(tion)?\.?|s\.)\s*", "", str(section or "")).strip().replace(" ", "")
    if not act or not sec:
        return None
    with _session(db) as s:
        rows = s.select("statute_ref")
    by_key = {(_act_key(r["act"]), r["section"].lower()): r for r in rows}
    return by_key.get((_act_key(act), sec.lower())) or by_key.get((_act_key(act), sec.split("(")[0].lower()))


def load_reference_into_triage(db: Optional[Database] = None) -> bool:
    """Point triage at case_type_ref / stage_ref. Empty tables -> triage keeps its built-in constants."""
    from . import triage
    with _session(db) as s:
        if not {"case_type_ref", "stage_ref"} <= s.tables():
            return False
        return triage.load_reference(s.select("case_type_ref"), s.select("stage_ref"))


def prepare_database(db: Optional[Database] = None) -> Dict:
    """Migrate (idempotent), insert missing reference rows, backfill promoted case columns."""
    from . import reference_data
    from .db_schema import migrate
    # Database() directly (not connect()) so connect()'s first-open migration does not run the same work twice
    with (_session(db) if db is not None else Database()) as s:
        report = migrate(s)
        report["reference_rows_added"] = reference_data.seed_reference(s)
        report["cases_backfilled"] = backfill_case_columns(s)
        s.commit()
    if not _in_memory(s.url):   # every new in-memory connection is a fresh, empty database: never mark it done
        _prepared.add(s.url)
    return report


_prepared: set = set()
_migrate_lock = threading.RLock()


def _in_memory(url: Optional[str]) -> bool:
    return not url or url in ("sqlite://", "sqlite:///", "sqlite:///:memory:") or url.endswith(":memory:")


def ensure_database(db: Optional[Database] = None) -> None:
    """prepare_database() once per process and database, for request paths (GET alerts / data-needed, registry run):
    the full migration is ~15 round trips, and start-up already ran it. A schema that has since disappeared (a test
    or dev reset of the file) is detected with one cheap query and migrated again."""
    with _session(db) as s:
        if getattr(s, "url", None) in _prepared and {"cases", "alerts", "case_queue_state"} <= s.tables():
            return
        prepare_database(s)


# ============================================================================ audit
def audit(actor: str, role: str, action: str, entity: str, detail: Optional[Dict] = None,
          db: Optional[Database] = None) -> None:
    with _session(db) as s:
        s.insert("audit_log", [{"actor": actor, "role": role, "action": action, "entity": entity,
                                "detail": detail or {}, "ts": _now_iso()}])
