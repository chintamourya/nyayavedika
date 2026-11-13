"""Demo data model: one table spec, an idempotent migration for SQLite and PostgreSQL.

    python scripts/migrate_demo.py          (safe to run any number of times)

Column types are portable tokens; DDL maps them per dialect (JSONB on Postgres, TEXT on SQLite).
Existing tables (cases, documents, alerts, cause_lists, legal_aid_requests) are extended with
ADD COLUMN; on Postgres their generic json columns are converted to JSONB.
"""
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

# token -> (postgres, sqlite)
DDL_TYPES = {
    "id": ("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT"),
    "text": ("TEXT", "TEXT"),
    "int": ("INTEGER", "INTEGER"),
    "real": ("DOUBLE PRECISION", "REAL"),
    "bool": ("BOOLEAN", "INTEGER"),
    "date": ("DATE", "TEXT"),
    "ts": ("TIMESTAMPTZ", "TEXT"),
    "json": ("JSONB", "TEXT"),
}
NOW = "DEFAULT CURRENT_TIMESTAMP"

# table -> {"columns": [(name, type, extra)], "pk": (cols) | None, "indexes": [(name, sql_cols, where, unique, pg_only)]}
SCHEMA: Dict[str, Dict] = {
    "courts": {
        "columns": [("court_id", "text", ""), ("name", "text", ""), ("state", "text", ""), ("district", "text", ""),
                    ("level", "text", "")],
        "pk": ("court_id",), "indexes": []},
    "benches": {
        "columns": [("bench_id", "text", ""), ("court_id", "text", ""), ("name", "text", ""), ("case_types", "json", ""),
                    ("minutes_per_day", "int", ""), ("active", "bool", "DEFAULT TRUE")],
        "pk": ("bench_id",), "indexes": [("ix_benches_court_active", "court_id, active", None, False, False)]},
    "court_calendar": {
        "columns": [("id", "id", ""), ("court_id", "text", ""), ("day", "date", ""), ("kind", "text", ""),
                    ("bench_id", "text", ""), ("note", "text", "")],
        "pk": None, "indexes": [("ix_calendar_court_day", "court_id, day", None, False, False)]},
    "case_type_ref": {
        "columns": [("case_type", "text", ""), ("base_urgency", "int", ""), ("default_minutes", "int", ""),
                    ("adr_route", "text", ""), ("sla_days", "int", ""), ("time_bound_points", "int", ""),
                    ("time_bound_law", "text", ""), ("updated_at", "ts", NOW)],
        "pk": ("case_type",), "indexes": []},
    "stage_ref": {
        "columns": [("stage", "text", ""), ("default_minutes", "int", ""), ("adjournment_prior", "real", ""),
                    ("typical_gap_days", "int", ""), ("updated_at", "ts", NOW)],
        "pk": ("stage",), "indexes": []},
    "statute_ref": {
        "columns": [("act", "text", ""), ("section", "text", ""), ("offence", "text", ""),
                    ("max_sentence_years", "real", ""), ("life_or_death", "bool", ""), ("bailable", "bool", ""),
                    ("compoundable", "bool", ""), ("note", "text", "")],
        "pk": ("act", "section"), "indexes": []},
    "cases": {
        "columns": [("case_id", "text", ""), ("court_id", "text", ""), ("case_type", "text", ""), ("stage", "text", ""),
                    ("filing_date", "date", ""), ("status", "text", "DEFAULT 'pending'"),
                    ("accused_in_custody", "bool", ""), ("custody_since", "date", ""),
                    ("max_sentence_years", "real", ""), ("life_or_death", "bool", ""),
                    ("first_time_offender", "bool", ""), ("act", "text", ""), ("section", "text", ""),
                    ("senior_citizen", "bool", ""), ("woman_or_child", "bool", ""), ("disability", "bool", ""),
                    ("legal_aid", "bool", ""), ("adjournments", "int", ""), ("last_hearing_date", "date", ""),
                    ("next_hearing_date", "date", ""), ("source", "text", ""),
                    ("data_quality", "text", "DEFAULT 'complete'"), ("field_provenance", "json", ""),
                    ("score", "real", ""), ("band", "text", ""), ("flags", "json", ""), ("route", "text", ""),
                    ("data", "json", ""), ("updated_at", "ts", NOW)],
        "pk": ("case_id",),
        "indexes": [("ix_cases_pending", "court_id, status, band, score DESC", "status = 'pending'", False, False),
                    ("ix_cases_next_hearing", "next_hearing_date", None, False, False),
                    ("ix_cases_type_stage", "case_type, stage", None, False, False),
                    ("ix_cases_custody", "accused_in_custody", "accused_in_custody", False, False),
                    ("ix_cases_flags_gin", "USING GIN (flags)", None, False, True)]},
    "advocates": {
        "columns": [("advocate_id", "text", ""), ("name", "text", ""), ("source", "text", "")],
        "pk": ("advocate_id",), "indexes": []},
    "case_advocates": {
        "columns": [("case_id", "text", ""), ("advocate_id", "text", ""), ("role", "text", "")],
        "pk": ("case_id", "advocate_id"), "indexes": [("ix_case_advocates_adv", "advocate_id", None, False, False)]},
    "hearings": {
        "columns": [("hearing_id", "id", ""), ("case_id", "text", ""), ("hearing_date", "date", ""),
                    ("bench_id", "text", ""), ("outcome", "text", ""), ("reason", "text", ""), ("next_date", "date", "")],
        "pk": None, "indexes": [("ix_hearings_case_date", "case_id, hearing_date DESC", None, False, False),
                                ("ix_hearings_date_bench", "hearing_date, bench_id", None, False, False)]},
    "documents": {
        "columns": [("doc_id", "text", ""), ("case_id", "text", ""), ("batch_id", "text", ""), ("filename", "text", ""),
                    ("storage_uri", "text", ""), ("doc_type", "text", ""), ("language", "text", ""),
                    ("pages", "int", ""), ("ocr_pages", "int", ""), ("status", "text", ""), ("analysis", "json", ""),
                    ("verified", "bool", ""), ("created_at", "ts", NOW)],
        "pk": ("doc_id",), "indexes": [("ix_documents_case", "case_id", None, False, False)]},
    "document_analyses": {
        "columns": [("id", "id", ""), ("doc_id", "text", ""), ("version", "int", ""), ("engine", "text", ""),
                    ("model", "text", ""), ("analysis", "json", ""), ("verified", "bool", ""), ("created_at", "ts", NOW)],
        "pk": None, "indexes": [("ux_document_analyses_version", "doc_id, version DESC", None, True, False)]},
    "ingest_batches": {
        "columns": [("batch_id", "text", ""), ("mode", "text", ""), ("file_count", "int", ""),
                    ("status", "text", "DEFAULT 'queued'"), ("case_number", "text", ""), ("created_by", "text", ""),
                    ("files_rejected", "json", ""), ("created_at", "ts", NOW), ("updated_at", "ts", NOW)],
        "pk": ("batch_id",), "indexes": []},
    "ingest_jobs": {  # doubles as the work queue (Phase 3 claims rows by status, created_at)
        "columns": [("job_id", "text", ""), ("batch_id", "text", ""), ("doc_id", "text", ""), ("case_id", "text", ""),
                    ("filename", "text", ""), ("relative_path", "text", ""), ("stage", "text", "DEFAULT 'queued'"),
                    ("status", "text", "DEFAULT 'queued'"), ("attempts", "int", "DEFAULT 0"), ("error", "text", ""),
                    ("result", "json", ""), ("heartbeat_at", "ts", ""), ("available_at", "ts", ""),
                    ("created_at", "ts", NOW), ("updated_at", "ts", NOW)],
        "pk": ("job_id",), "indexes": [("ix_ingest_jobs_claim", "status, created_at", None, False, False),
                                       ("ix_ingest_jobs_batch", "batch_id", None, False, False)]},
    "triage_scores": {
        "columns": [("id", "id", ""), ("case_id", "text", ""), ("scored_at", "ts", NOW), ("score", "real", ""),
                    ("band", "text", ""), ("flags", "json", ""), ("reasons", "json", ""), ("rules_version", "text", ""),
                    ("ai_adjustment", "real", ""), ("ai_reason", "text", "")],
        "pk": None, "indexes": [("ix_triage_scores_case", "case_id, scored_at DESC", None, False, False)]},
    "case_queue_state": {
        "columns": [("case_id", "text", ""), ("first_eligible_on", "date", ""), ("times_considered", "int", "DEFAULT 0"),
                    ("times_deferred", "int", "DEFAULT 0"), ("consecutive_deferrals", "int", "DEFAULT 0"),
                    ("last_deferral_reason", "text", ""), ("last_listed_on", "date", ""), ("sla_due_on", "date", ""),
                    ("aging_boost", "real", "DEFAULT 0"), ("must_list", "bool", "DEFAULT FALSE"),
                    ("hold_until", "date", ""), ("needs_review", "bool", "DEFAULT FALSE"), ("updated_at", "ts", NOW)],
        "pk": ("case_id",), "indexes": [("ix_queue_must_list", "must_list", "must_list", False, False),
                                        ("ix_queue_sla_due", "sla_due_on", None, False, False)]},
    "cause_lists": {
        "columns": [("id", "id", ""), ("created_at", "ts", NOW), ("court_id", "text", ""), ("start_date", "text", ""),
                    ("plan", "json", ""), ("metrics", "json", ""), ("explanation", "text", ""),
                    ("status", "text", "DEFAULT 'draft'"), ("approved_by", "text", ""), ("decided_at", "ts", "")],
        "pk": None, "indexes": []},
    "listings": {
        "columns": [("id", "id", ""), ("cause_list_id", "int", ""), ("case_id", "text", ""), ("day", "date", ""),
                    ("bench_id", "text", ""), ("slot_start", "text", ""), ("slot_end", "text", ""),
                    ("expected_minutes", "int", ""), ("band", "text", ""), ("score", "real", ""),
                    ("status", "text", "DEFAULT 'planned'")],
        "pk": None, "indexes": [("ix_listings_slot", "cause_list_id, day, bench_id, slot_start", None, False, False),
                                ("ix_listings_case_day", "case_id, day", None, False, False)]},
    "deferrals": {  # append-only
        "columns": [("id", "id", ""), ("case_id", "text", ""), ("cause_list_id", "int", ""), ("run_at", "ts", NOW),
                    ("reason", "text", ""), ("score", "real", ""), ("band", "text", "")],
        "pk": None, "indexes": [("ix_deferrals_case_run", "case_id, run_at DESC", None, False, False)]},
    "alerts": {  # lifecycle: pending, approved, filed, heard, released, denied, dismissed
        "columns": [("id", "id", ""), ("created_at", "ts", NOW), ("case_id", "text", ""), ("kind", "text", ""),
                    ("details", "json", ""), ("draft", "text", ""), ("status", "text", "DEFAULT 'pending'"),
                    ("decided_at", "ts", ""), ("decision_note", "text", ""), ("snooze_until", "ts", ""),
                    ("dismiss_reason", "text", ""), ("assigned_to", "text", "")],
        "pk": None, "indexes": [("ux_alerts_open_case_kind", "case_id, kind",
                                 "status IN ('pending', 'approved', 'filed')", True, False)]},
    "legal_aid_requests": {
        "columns": [("id", "id", ""), ("created_at", "ts", NOW), ("channel", "text", ""), ("district", "text", ""),
                    ("language", "text", ""), ("eligible", "bool", ""), ("grounds", "json", ""),
                    ("status", "text", "DEFAULT 'checked'"), ("state", "text", ""), ("source", "text", ""),
                    ("applied_on", "date", ""), ("lawyer_assigned_on", "date", ""), ("resolved_on", "date", "")],
        "pk": None, "indexes": [("ix_legal_aid_district_created", "district, created_at", None, False, False)]},
    "field_feedback": {  # landing-page feedback from advocates, lawyers, court staff, citizens (see nyayavedika/feedback.py)
        "columns": [("id", "id", ""), ("created_at", "ts", NOW), ("role", "text", ""), ("auth_role", "text", ""),
                    ("name", "text", ""), ("place", "text", ""), ("features", "json", ""), ("rating", "int", ""),
                    ("would_recommend", "text", ""), ("headline", "text", ""), ("comment", "text", ""),
                    ("answers", "json", ""), ("consent_public", "bool", "DEFAULT FALSE"),
                    ("published", "bool", "DEFAULT FALSE")],
        "pk": None, "indexes": [("ix_field_feedback_pub", "published, created_at", None, False, False)]},
    "impact_reports": {  # verifiable field evidence (see nyayavedika/impact_reports.py); identity is staff-only
        "columns": [("id", "id", ""), ("created_at", "ts", NOW), ("source", "text", ""), ("role", "text", ""),
                    ("identity", "json", ""), ("usage", "json", ""), ("measures", "json", ""), ("ratings", "json", ""),
                    ("outcomes", "json", ""), ("outcome_detail", "text", ""), ("would_continue", "text", ""),
                    ("testimonial", "text", ""), ("quote_permission", "text", "DEFAULT 'no'"),
                    ("consent_contact", "bool", "DEFAULT FALSE"), ("status", "text", "DEFAULT 'pending'"),
                    ("verified_by", "text", ""), ("verified_at", "ts", ""), ("verification_note", "text", "")],
        "pk": None, "indexes": [("ix_impact_reports_status", "status, created_at", None, False, False)]},
    "reach_visitors": {
        "columns": [("visitor_hash", "text", ""), ("door", "text", ""), ("first_seen", "ts", NOW)],
        "pk": ("visitor_hash", "door"), "indexes": []},
    "browser_feature_activity": {
        "columns": [("visitor_hash", "text", ""), ("door", "text", ""), ("feature", "text", ""),
                    ("first_seen", "ts", NOW)],
        "pk": ("visitor_hash", "door", "feature"), "indexes": []},
    "dlsa_directory": {
        "columns": [("id", "id", ""), ("state", "text", ""), ("district", "text", ""), ("office", "text", ""),
                    ("address", "text", ""), ("phone", "text", ""), ("email", "text", ""), ("source_url", "text", ""),
                    ("verified_at", "ts", ""), ("synthetic", "bool", "DEFAULT FALSE")],
        "pk": None, "indexes": [("ix_dlsa_state_district", "state, district", None, False, False)]},
    "state_legal_aid_params": {
        "columns": [("state", "text", ""), ("income_limit", "int", ""), ("helpline", "text", ""),
                    ("source_url", "text", ""), ("verified_at", "ts", ""), ("synthetic", "bool", "DEFAULT FALSE")],
        "pk": ("state",), "indexes": []},
    "audit_log": {
        "columns": [("id", "id", ""), ("actor", "text", ""), ("role", "text", ""), ("action", "text", ""),
                    ("entity", "text", ""), ("detail", "json", ""), ("ts", "ts", NOW)],
        "pk": None, "indexes": [("ix_audit_entity_ts", "entity, ts", None, False, False)]},
    "agent_runs": {
        "columns": [("id", "id", ""), ("job", "text", ""), ("started", "ts", NOW), ("ended", "ts", ""),
                    ("counts", "json", ""), ("error", "text", "")],
        "pk": None, "indexes": []},
}


def column_types(table: str) -> Dict[str, str]:
    return {name: typ for name, typ, _ in SCHEMA[table]["columns"]}


def _col_ddl(dialect: str, name: str, typ: str, extra: str) -> str:
    sql_type = DDL_TYPES[typ][0 if dialect == "postgresql" else 1]
    if dialect == "sqlite" and extra in ("DEFAULT TRUE", "DEFAULT FALSE"):
        extra = "DEFAULT 1" if extra == "DEFAULT TRUE" else "DEFAULT 0"
    return f"{name} {sql_type} {extra}".strip()


def create_table_sql(dialect: str, table: str) -> str:
    spec = SCHEMA[table]
    cols = [_col_ddl(dialect, n, t, e) for n, t, e in spec["columns"]]
    if spec["pk"]:
        cols.append(f"PRIMARY KEY ({', '.join(spec['pk'])})")
    return f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(cols)})"


def index_sql(dialect: str, table: str, index) -> str:
    name, cols, where, unique, pg_only = index
    if pg_only and dialect != "postgresql":
        return ""
    target = cols if cols.startswith("USING") else f"({cols})"
    sql = f"CREATE {'UNIQUE ' if unique else ''}INDEX IF NOT EXISTS {name} ON {table} {target}"
    return sql + (f" WHERE {where}" if where else "")


def _dedupe_open_alerts(db) -> int:
    """The unique open-alert index fails on old duplicates; dismiss all but the newest of each."""
    rows = db.query("SELECT id, case_id, kind FROM alerts WHERE status IN ('pending', 'approved', 'filed') "
                    "ORDER BY id DESC")
    seen, dupes = set(), []
    for r in rows:
        key = (r["case_id"], r["kind"])
        if key in seen:
            dupes.append(r["id"])
        seen.add(key)
    for alert_id in dupes:
        db.update("alerts", {"id": alert_id}, {"status": "dismissed", "dismiss_reason": "duplicate (migration)"})
    return len(dupes)


def migrate(db) -> Dict[str, List[str]]:
    """Create / extend every table and index. Idempotent. Returns what changed."""
    report = {"created": [], "columns_added": [], "converted_to_jsonb": [], "indexes_ensured": [], "alerts_deduped": 0}
    existing = db.tables()
    for table, spec in SCHEMA.items():
        if table not in existing:
            db.execute(create_table_sql(db.dialect, table))
            report["created"].append(table)
            continue
        have = db.columns(table)
        for name, typ, extra in spec["columns"]:
            if name not in have:
                if typ == "id":  # cannot add a primary key to an existing table; tables that have one keep theirs
                    continue
                db.execute(f"ALTER TABLE {table} ADD COLUMN {_col_ddl(db.dialect, name, typ, extra)}")
                report["columns_added"].append(f"{table}.{name}")
            elif db.dialect == "postgresql" and typ == "json" and have[name] == "json":
                db.execute(f"ALTER TABLE {table} ALTER COLUMN {name} TYPE JSONB USING {name}::jsonb")
                report["converted_to_jsonb"].append(f"{table}.{name}")
    report["alerts_deduped"] = _dedupe_open_alerts(db)
    have_indexes = db.index_names()  # one query; CREATE INDEX IF NOT EXISTS per index was a round trip each
    for table, spec in SCHEMA.items():
        for index in spec["indexes"]:
            if index[0] in have_indexes:
                report["indexes_ensured"].append(index[0])
                continue
            sql = index_sql(db.dialect, table, index)
            if sql:
                db.execute(sql)
                report["indexes_ensured"].append(index[0])
    db.commit()
    logger.info("migration done: %d tables created, %d columns added", len(report["created"]), len(report["columns_added"]))
    return report
