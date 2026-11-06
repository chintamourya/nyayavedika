"""Turn a real pilot log into the numbers judges ask for (criterion 4, proven impact). Pure functions, no database.

One CSV row per case a paralegal or lawyer screened with the tool (see pilot/pilot_log_template.csv):
  case_ref          anonymised reference (never a name)
  tool_status       eligible | likely_eligible | needs_review | not_eligible   (what the tool said)
  lawyer_verdict    eligible | not_eligible                                    (what the lawyer decided after checking)
  manual_minutes    minutes this kind of screening took before, by hand (baseline, measured on the same cases)
  tool_minutes      minutes it took with the tool, including the lawyer's check
  days_over_limit   days in custody beyond the Sec. 479 limit when flagged (0 if none)
  application_filed yes | no
  outcome           released | denied | pending | none
"""
import csv
import statistics
from typing import Dict, Iterable, List, Optional

FLAGGED = ("eligible", "likely_eligible", "needs_review")


def _num(value) -> Optional[float]:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _ratio(n: float, d: float) -> Optional[float]:
    return round(n / d, 3) if d else None


def summarise(rows: Iterable[Dict]) -> Dict:
    rows = list(rows)
    flagged = [r for r in rows if (r.get("tool_status") or "").strip() in FLAGGED]
    judged = [r for r in rows if (r.get("lawyer_verdict") or "").strip() in ("eligible", "not_eligible")]
    tp = sum(1 for r in judged if r["tool_status"].strip() in FLAGGED and r["lawyer_verdict"].strip() == "eligible")
    fp = sum(1 for r in judged if r["tool_status"].strip() in FLAGGED and r["lawyer_verdict"].strip() == "not_eligible")
    fn = sum(1 for r in judged if r["tool_status"].strip() not in FLAGGED and r["lawyer_verdict"].strip() == "eligible")
    both = [(m, t) for m, t in ((_num(r.get("manual_minutes")), _num(r.get("tool_minutes"))) for r in rows)
            if m is not None and t is not None]
    over = [d for d in (_num(r.get("days_over_limit")) for r in flagged) if d is not None and d > 0]
    filed = [r for r in rows if (r.get("application_filed") or "").strip().lower() in ("yes", "y", "true")]
    outcomes = [(r.get("outcome") or "").strip().lower() for r in filed]
    return {
        "cases_screened": len(rows),
        "flagged_for_release": len(flagged),
        "lawyer_checked": len(judged),
        "precision": _ratio(tp, tp + fp),      # of cases the tool flagged, how many the lawyer confirmed
        "recall": _ratio(tp, tp + fn),         # of cases the lawyer says qualify, how many the tool flagged
        "median_manual_minutes": statistics.median(m for m, _ in both) if both else None,
        "median_tool_minutes": statistics.median(t for _, t in both) if both else None,
        "cases_with_timing": len(both),
        "days_over_limit_total": int(sum(over)),
        "people_held_past_limit": len(over),
        "applications_filed": len(filed),
        "released": outcomes.count("released"),
        "denied": outcomes.count("denied"),
        "pending": outcomes.count("pending"),
    }


def read_csv(path) -> List[Dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def to_markdown(m: Dict, source: str = "pilot log") -> str:
    def f(v, unit=""):
        return "n/a" if v is None else f"{v}{unit}"
    manual, tool = m["median_manual_minutes"], m["median_tool_minutes"]
    saved = f"{round(100 * (manual - tool) / manual)}%" if manual and tool is not None else "n/a"
    return "\n".join([
        f"# Pilot results (from {source})", "",
        "These are field numbers from real screened cases, not synthetic data. Report them exactly as measured.", "",
        "| Measure | Result |", "|---|---|",
        f"| Cases screened | {m['cases_screened']} |",
        f"| Flagged for release review | {m['flagged_for_release']} |",
        f"| Checked by a lawyer | {m['lawyer_checked']} |",
        f"| Precision (flagged cases the lawyer confirmed) | {f(m['precision'])} |",
        f"| Recall (qualifying cases the tool flagged) | {f(m['recall'])} |",
        f"| Median minutes per case, by hand (baseline) | {f(manual)} |",
        f"| Median minutes per case, with the tool | {f(tool)} |",
        f"| Time saved per case | {saved} (on {m['cases_with_timing']} timed cases) |",
        f"| People found held past the Sec. 479 limit | {m['people_held_past_limit']} |",
        f"| Total days past the limit across them | {m['days_over_limit_total']} |",
        f"| Release applications filed | {m['applications_filed']} |",
        f"| Released / denied / pending | {m['released']} / {m['denied']} / {m['pending']} |", ""])
