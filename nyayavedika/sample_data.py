"""Deterministic synthetic case docket for demos. Contains no real parties or personal data.

Replace with an export from your CIS / NJDG / e-Courts system (same field names) for real use.
"""
import random
from datetime import date, timedelta
from typing import Dict, List

PREFIX = {
    "habeas_corpus": "HCP", "bail": "BA", "criminal_trial": "SC", "criminal_appeal": "CRL.A",
    "cheque_bounce": "CC", "motor_accident": "MACT", "maintenance": "MC", "domestic_violence": "DVC",
    "matrimonial": "HMOP", "child_custody": "GWOP", "civil_suit": "OS", "rent_eviction": "RCC",
    "land_revenue": "LAOP", "commercial": "COS", "consumer": "CC(CF)", "labour": "ID",
    "service": "WP(S)", "writ": "WP", "execution": "EP",
}
MIX = [("cheque_bounce", 14), ("civil_suit", 12), ("criminal_trial", 12), ("bail", 6), ("motor_accident", 8),
       ("maintenance", 6), ("matrimonial", 6), ("domestic_violence", 4), ("rent_eviction", 5), ("land_revenue", 4),
       ("commercial", 3), ("consumer", 3), ("labour", 3), ("service", 3), ("writ", 3), ("execution", 4),
       ("criminal_appeal", 3), ("habeas_corpus", 1), ("child_custody", 2)]
STAGES_CIVIL = ["admission", "notice", "pleadings", "framing_of_issues", "evidence", "arguments", "judgment_reserved"]
STAGES_CRIM = ["charge", "evidence", "evidence", "arguments", "judgment_reserved"]
ACT = {"cheque_bounce": ("NI Act", "138"), "motor_accident": ("MV Act", "166"), "maintenance": ("BNSS", "144"),
       "domestic_violence": ("PWDV Act", "12"), "matrimonial": ("HM Act", "13"), "rent_eviction": ("Rent Control Act", "10"),
       "consumer": ("CP Act", "35"), "labour": ("ID Act", "2A"), "commercial": ("CC Act", "12A")}


def generate(n: int = 100, seed: int = 42, today: date = None) -> List[Dict]:
    rng = random.Random(seed)
    today = today or date.today()
    pool = [t for t, w in MIX for _ in range(w)]
    advocates = [f"ADV-{i:02d}" for i in range(1, 26)]
    cases = []
    for i in range(n):
        ctype = rng.choice(pool)
        age_days = int(rng.triangular(30, 15 * 365, 3 * 365))
        if ctype in ("bail", "habeas_corpus"):
            age_days = rng.randint(3, 90)
        filed = today - timedelta(days=age_days)
        criminal = ctype in ("criminal_trial", "criminal_appeal", "bail", "habeas_corpus")
        stage = rng.choice(STAGES_CRIM if criminal else STAGES_CIVIL)
        if ctype in ("bail", "habeas_corpus"):
            stage = "admission"
        case = {
            "case_id": f"{PREFIX[ctype]}/{filed.year}/{1000 + i:04d}",
            "case_type": ctype,
            "filing_date": filed.isoformat(),
            "stage": stage,
            "adjournments": min(int(age_days / 365 * rng.uniform(1, 5)), 40),
            "last_hearing_date": (today - timedelta(days=rng.choice([7, 21, 45, 90, 200, 400]))).isoformat(),
            "advocate_ids": rng.sample(advocates, rng.choice([1, 2, 2, 3])),
            "senior_citizen": rng.random() < 0.12,
            "woman_or_child": ctype in ("maintenance", "domestic_violence", "child_custody") or rng.random() < 0.15,
            "disability": rng.random() < 0.03,
            "legal_aid": rng.random() < 0.15,
        }
        if ctype in ACT:
            case["act"], case["section"] = ACT[ctype]
        if ctype in ("criminal_trial", "bail", "habeas_corpus") and rng.random() < 0.6:
            case["accused_in_custody"] = True
            case["custody_since"] = (today - timedelta(days=rng.randint(20, min(age_days + 60, 6 * 365)))).isoformat()
            case["max_sentence_years"] = rng.choice([3, 5, 7, 7, 10, "life"])
            case["first_time_offender"] = rng.random() < 0.5
            case["act"], case["section"] = rng.choice([("BNS", "303"), ("BNS", "318"), ("NDPS Act", "20"), ("BNS", "115")])
        cases.append(case)
    return cases
