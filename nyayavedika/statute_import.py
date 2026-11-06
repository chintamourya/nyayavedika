"""Load a verified Act / section / maximum-sentence table from CSV (pure functions, no database needed).

CSV columns: act, section, offence, max_sentence_years, life_or_death, bailable, compoundable, verified_by, source
- max_sentence_years: the HIGHEST term in the section, in years (0.25 = 3 months). Leave empty when life_or_death is yes.
- life_or_death: yes when death or imprisonment for life is a possible punishment (Sec. 479 then does not apply).
- verified_by + source: who checked the row against the bare Act, and where (e.g. indiacode.nic.in link). Rows without
  verified_by are still loaded but marked "UNVERIFIED" in the note, so a pilot can see what is not yet signed off.
"""
import csv
from datetime import date
from typing import Dict, Iterable, List, Tuple

COLUMNS = ["act", "section", "offence", "max_sentence_years", "life_or_death", "bailable", "compoundable",
           "verified_by", "source"]
_YES = {"1", "true", "yes", "y"}
_NO = {"0", "false", "no", "n", ""}


def _flag(value, name: str, errors: List[str]) -> bool:
    text = str(value or "").strip().lower()
    if text in _YES:
        return True
    if text in _NO:
        return False
    errors.append(f"{name} must be yes or no, got {value!r}")
    return False


def parse_rows(rows: Iterable[Dict], today: date = None) -> Tuple[List[Dict], List[str]]:
    """Return (valid statute_ref rows, problems). A bad row is reported and skipped, never guessed."""
    today = today or date.today()
    out, problems, seen = [], [], set()
    for n, raw in enumerate(rows, start=2):  # row 1 is the header
        errors: List[str] = []
        act = str(raw.get("act") or "").strip()
        section = str(raw.get("section") or "").strip().replace(" ", "")
        if not act or not section:
            problems.append(f"row {n}: act and section are required")
            continue
        life = _flag(raw.get("life_or_death"), "life_or_death", errors)
        years_text = str(raw.get("max_sentence_years") or "").strip()
        years = None
        if years_text:
            try:
                years = float(years_text)
                if years <= 0:
                    errors.append("max_sentence_years must be above 0")
            except ValueError:
                errors.append(f"max_sentence_years is not a number: {years_text!r}")
        elif not life:
            errors.append("max_sentence_years is empty and life_or_death is not yes")
        if life and years is not None:
            errors.append("life_or_death is yes, so leave max_sentence_years empty")
        bailable = _flag(raw.get("bailable"), "bailable", errors)
        compoundable = _flag(raw.get("compoundable"), "compoundable", errors)
        key = (act.lower(), section.lower())
        if key in seen:
            errors.append("duplicate act + section in this file")
        seen.add(key)
        if errors:
            problems.append(f"row {n} ({act} {section}): " + "; ".join(errors))
            continue
        who, source = str(raw.get("verified_by") or "").strip(), str(raw.get("source") or "").strip()
        note = (f"verified by {who} on {today.isoformat()}" + (f"; {source}" if source else "")) if who else "UNVERIFIED"
        out.append({"act": act, "section": section, "offence": str(raw.get("offence") or "").strip(),
                    "max_sentence_years": None if life else years, "life_or_death": life,
                    "bailable": bailable, "compoundable": compoundable, "note": note})
    return out, problems


def read_csv(path) -> Tuple[List[Dict], List[str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in COLUMNS[:7] if c not in (reader.fieldnames or [])]
        if missing:
            return [], [f"missing columns: {', '.join(missing)}"]
        return parse_rows(reader)
