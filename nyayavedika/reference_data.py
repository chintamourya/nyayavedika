"""Seed values for the reference tables: case_type_ref, stage_ref, statute_ref.

case_type_ref / stage_ref carry triage.py's built-in constants unchanged, so scores do not move when
code starts reading the tables. statute_ref is DEMO data: verify every row against the bare Act
(indiacode.nic.in) before a pilot. Seeding inserts missing rows only - edits made in the tables survive.
"""
from typing import Dict

from . import triage

STATUTE_NOTE = "demo, verify before pilot"

# Typical days to the next hearing by stage. Not in triage.py today (nothing reads it yet); demo estimate.
TYPICAL_GAP_DAYS = {
    "admission": 14, "notice": 30, "pleadings": 45, "framing_of_issues": 30, "charge": 30, "evidence": 45,
    "arguments": 30, "judgment_reserved": 30, "pronouncement": 14, "execution": 45,
}

# (act, section, offence, max_sentence_years, life_or_death, bailable, compoundable)
# max_sentence_years is the highest term in the section; None when life / death is the maximum. Where sub-sections
# differ a lot (e.g. BNS 316) rows are keyed by sub-section, so a bare base section does not match (never guessed).
STATUTES = [
    ("BNS", "103", "Murder", None, True, False, False),
    ("BNS", "105", "Culpable homicide not amounting to murder", None, True, False, False),
    ("BNS", "106", "Causing death by negligence (hit-and-run up to 10 years)", 10, False, False, False),
    ("BNS", "109", "Attempt to murder", None, True, False, False),
    ("BNS", "115", "Voluntarily causing hurt", 1, False, True, True),
    ("BNS", "117(2)", "Voluntarily causing grievous hurt", 7, False, True, True),
    ("BNS", "127(2)", "Wrongful confinement", 1, False, True, True),
    ("BNS", "131", "Assault or criminal force", 0.25, False, True, True),
    ("BNS", "137", "Kidnapping", 7, False, False, False),
    ("BNS", "140", "Kidnapping or abduction for ransom", None, True, False, False),
    ("BNS", "64", "Rape", None, True, False, False),
    ("BNS", "74", "Assault or criminal force to woman with intent to outrage her modesty", 5, False, False, False),
    ("BNS", "75", "Sexual harassment", 3, False, True, False),
    ("BNS", "78", "Stalking (repeat conviction up to 5 years)", 5, False, False, False),
    ("BNS", "80", "Dowry death", None, True, False, False),
    ("BNS", "85", "Cruelty by husband or relative of husband", 3, False, False, False),
    ("BNS", "303", "Theft (first conviction; repeat conviction 1 to 5 years)", 3, False, False, True),
    ("BNS", "304", "Snatching", 3, False, False, False),
    ("BNS", "305", "Theft in a dwelling house, means of transport or place of worship", 7, False, False, False),
    ("BNS", "308", "Extortion", 10, False, False, False),
    ("BNS", "309", "Robbery", 14, False, False, False),
    ("BNS", "310", "Dacoity", None, True, False, False),
    ("BNS", "316(2)", "Criminal breach of trust", 5, False, False, True),
    ("BNS", "316(5)", "Criminal breach of trust by public servant, banker or agent", None, True, False, False),
    ("BNS", "318", "Cheating", 7, False, False, False),
    ("BNS", "351", "Criminal intimidation", 7, False, True, True),
    ("BNS", "356", "Defamation", 2, False, True, True),
    ("IPC", "302", "Murder", None, True, False, False),
    ("IPC", "304", "Culpable homicide not amounting to murder", None, True, False, False),
    ("IPC", "307", "Attempt to murder", None, True, False, False),
    ("IPC", "323", "Voluntarily causing hurt", 1, False, True, True),
    ("IPC", "325", "Voluntarily causing grievous hurt", 7, False, True, True),
    ("IPC", "354", "Assault or criminal force to woman with intent to outrage her modesty", 5, False, False, False),
    ("IPC", "376", "Rape", None, True, False, False),
    ("IPC", "379", "Theft", 3, False, False, True),
    ("IPC", "380", "Theft in dwelling house", 7, False, False, False),
    ("IPC", "392", "Robbery", 14, False, False, False),
    ("IPC", "406", "Criminal breach of trust", 3, False, False, True),
    ("IPC", "420", "Cheating and dishonestly inducing delivery of property", 7, False, False, True),
    ("IPC", "498A", "Cruelty by husband or relative of husband", 3, False, False, False),
    ("NI Act", "138", "Dishonour of cheque for insufficiency of funds", 2, False, True, True),
    ("NDPS Act", "20", "Cannabis offences (term depends on quantity)", 20, False, False, False),
    ("NDPS Act", "21", "Manufactured drugs offences (term depends on quantity)", 20, False, False, False),
    ("NDPS Act", "27", "Consumption of narcotic drug or psychotropic substance", 1, False, True, False),
    ("Arms Act", "25(1)", "Possession of arms in contravention of the Act", 7, False, False, False),
    ("POCSO Act", "4", "Penetrative sexual assault", None, True, False, False),
]


def case_type_rows():
    d = triage._DEFAULTS
    return [{"case_type": t, "base_urgency": d["TYPE_URGENCY"][t], "default_minutes": d["TYPE_MINUTES"].get(t),
             "adr_route": d["ADR_ROUTES"].get(t), "sla_days": None,
             "time_bound_points": d["TIME_BOUND"].get(t, (None, None))[0],
             "time_bound_law": d["TIME_BOUND"].get(t, (None, None))[1]} for t in triage.CASE_TYPES]


def stage_rows():
    d = triage._DEFAULTS
    return [{"stage": s, "default_minutes": d["STAGE_MINUTES"][s], "adjournment_prior": d["STAGE_ADJ_RISK"][s],
             "typical_gap_days": TYPICAL_GAP_DAYS[s]} for s in d["STAGE_MINUTES"]]


def statute_rows():
    return [{"act": a, "section": s, "offence": o, "max_sentence_years": y, "life_or_death": ld, "bailable": b,
             "compoundable": c, "note": STATUTE_NOTE} for a, s, o, y, ld, b, c in STATUTES]


DEMO_STATES = ["Telangana", "Andhra Pradesh", "Karnataka", "Maharashtra", "Tamil Nadu"]


def state_param_rows():
    """Synthetic placeholders (verify against each State's notification before showing as fact)."""
    from . import config
    return [{"state": s, "income_limit": config.LEGAL_AID_INCOME_LIMIT, "helpline": "15100", "source_url": None,
             "verified_at": None, "synthetic": True} for s in DEMO_STATES]


def seed_reference(db) -> Dict[str, int]:
    """Insert missing reference rows (existing rows, including local edits, are kept). Returns rows added."""
    added = {}
    for table, rows, keys in (("case_type_ref", case_type_rows(), ["case_type"]), ("stage_ref", stage_rows(), ["stage"]),
                              ("statute_ref", statute_rows(), ["act", "section"]),
                              ("state_legal_aid_params", state_param_rows(), ["state"])):
        before = db.count(table)
        db.upsert(table, rows, keys, update=False)
        added[table] = db.count(table) - before
    if not db.execute("SELECT 1 AS n FROM case_type_ref WHERE time_bound_points IS NULL LIMIT 1"):
        return added
    for r in case_type_rows():  # columns added later (rules-v2) start empty on older databases: fill them once
        if r["time_bound_points"]:
            db.execute("UPDATE case_type_ref SET time_bound_points = :p, time_bound_law = :l "
                       "WHERE case_type = :t AND time_bound_points IS NULL",
                       {"p": r["time_bound_points"], "l": r["time_bound_law"], "t": r["case_type"]})
    return added
