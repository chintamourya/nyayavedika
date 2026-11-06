"""Measure the four things the brief asks for and write docs/EVAL.md. All data is SYNTHETIC; no keys needed.

    python scripts/eval_demo.py [--write docs/EVAL.md] [--skip-upload]

  1. Case triage           - Critical cases reach the Critical band; every score carries reasons
  2. Document summarisation - extraction accuracy vs ground truth; unverified dates/sections
  3. Legal aid access       - the 40 rule-engine scenarios; one citizen check
  4. Court scheduling       - 1-week plan (invariants) and the 8-week simulation, aging on vs off
  +  End to end             - 5 files uploaded -> scored -> proposed hearing, in seconds

Misses are reported, not hidden: each failing line says what failed.
"""
import argparse
import json
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import _testenv  # noqa: E402,F401  (offline: no API keys, throw-away DB; everything else still from .env)

from nyayavedika import config, legal_aid, sample_data, scheduler, triage  # noqa: E402

START = date(2026, 10, 26)
SAMPLES = ["fir_01_theft.txt", "fir_02_cheating.pdf", "bail_01_application.pdf", "order_01_bail_granted.pdf",
           "custody_01_jail_certificate.txt"]


def pct(n, d):
    return f"{100 * n / d:.0f}%" if d else "n/a"


def triage_metrics():
    cases = sample_data.generate(600)
    results = triage.triage_all(cases)
    critical = [r for r in results if r["band"] == "Critical"]
    with_reasons = sum(1 for r in results if r["reasons"])
    return {"cases": len(results), "critical": len(critical), "with_reasons": with_reasons,
            "bands": {b: sum(1 for r in results if r["band"] == b) for b in ("Critical", "High", "Medium", "Routine")}}


def summarisation_metrics():
    import eval_samples
    return eval_samples.evaluate(ROOT / "sample_docs")


def legal_aid_metrics():
    cases = json.loads((ROOT / "tests" / "legal_aid_cases.json").read_text(encoding="utf-8"))
    fails = []
    for c in cases:
        r = legal_aid.check_eligibility(c["applicant"])
        ok = r["outcome"] == c["outcome"] and r["eligible"] == (c["outcome"] == "likely_eligible")
        if "clauses" in c:
            ok = ok and sorted(g["clause"] for g in r["grounds"]) == sorted(c["clauses"])
        if not ok:
            fails.append(c["name"])
    return {"total": len(cases), "matched": len(cases) - len(fails), "failures": fails}


def scheduling_metrics():
    triaged = triage.triage_all(sample_data.generate(600))
    plan = scheduler.plan_week(triaged, START, 5, rules_version=triage.RULES_VERSION)   # the planner the app uses
    violations = scheduler.check_plan(plan, {r["case_id"] for r in triaged})
    week = {"violations": violations, "listed": plan["metrics"]["cases_listed"], "critical_total": plan["metrics"]["critical_total"],
            "critical_listed": plan["metrics"]["critical_listed"],
            "advocate_conflicts": plan["metrics"]["advocate_conflicts"],
            "utilisation": plan["metrics"]["avg_bench_utilisation_percent"],
            "fifo_conflicts": plan["metrics"]["baseline_fifo"]["advocate_conflicts"],
            "fifo_listed": plan["metrics"]["baseline_fifo"]["cases_listed"]}
    import simulate_8_weeks as sim
    return {"week": week, "aging_on": sim.run(1500, 700, 8, 42, True, START),
            "aging_off": sim.run(1500, 700, 8, 42, False, START)}


def end_to_end_metrics():
    """Upload five files through the real API (in-process worker) and time upload -> scored -> proposed hearing."""
    from fastapi.testclient import TestClient
    from nyayavedika import db
    tmp = tempfile.mkdtemp()
    config.DEMO_TOKEN_STAFF = "eval"
    config.STORAGE_DIR = f"{tmp}/storage"
    db.reset_engine_for_tests(f"sqlite:///{tmp}/eval.db")
    import server
    head = {"Authorization": "Bearer eval"}
    with TestClient(server.app) as c:
        files = [("files", (n, (ROOT / "sample_docs" / n).read_bytes())) for n in SAMPLES]
        t0 = time.time()
        batch_id = c.post("/api/intake/batches", files=files, data={"mode": "separate"}, headers=head).json()["batch_id"]
        while time.time() - t0 < 300:
            b = c.get(f"/api/intake/batches/{batch_id}", headers=head).json()
            if b["status"] != "running":
                break
            time.sleep(0.5)
        upload_s = time.time() - t0
        d = c.post("/api/cause-lists/draft", json={"days": 5}, headers=head).json()
        total_s = time.time() - t0
    ids = {f["result"]["case_id"] for f in b["files"] if f["result"]}
    listed = {x["case_id"] for day in d["calendar"] for bench in day["benches"] for x in bench["cases"]}
    return {"status": b["status"], "files": len(b["files"]), "scored": len(ids), "upload_to_scored_s": round(upload_s, 1),
            "upload_to_proposed_hearing_s": round(total_s, 1), "uploaded_cases_in_draft": len(ids & listed),
            "violations": d["violations"]}


def render(m):
    t, s, la, sc, e2e = m["triage"], m["summ"], m["legal"], m["sched"], m.get("e2e")
    w, on, off = sc["week"], sc["aging_on"], sc["aging_off"]
    L = ["# Evaluation (SYNTHETIC data - not court results)", "",
         f"Generated by `python scripts/eval_demo.py` on {date.today().isoformat()} (offline: rules + extractive, no LLM). "
         "Numbers describe invented cases and invented courts; they show the system behaves as designed, not how a real court performs.", "",
         "## 1. Case triage", "",
         f"- {t['cases']} synthetic cases scored; every case carries reasons: {t['with_reasons']}/{t['cases']} ({pct(t['with_reasons'], t['cases'])})",
         f"- Bands: " + ", ".join(f"{k} {v}" for k, v in t["bands"].items()), "",
         "## 2. Document summarisation and extraction", "",
         f"- {s['line']}"]
    L += [f"- Skipped: {x}" for x in s["skipped"]] + [f"- Unverified: {x}" for x in s["unverified"]]
    L += ["", "## 3. Legal aid access", "",
          f"- Rule-engine scenarios matching expected outcome: {la['matched']}/{la['total']} ({pct(la['matched'], la['total'])})"]
    L += [f"- MISS: {x}" for x in la["failures"]]
    L += ["", "## 4. Court scheduling", "",
          f"- One week, 600 pending cases: {w['listed']} listed (first-come-first-served would list {w['fifo_listed']}); "
          f"Critical listed {w['critical_listed']}/{w['critical_total']}; advocate conflicts {w['advocate_conflicts']} "
          f"(first-come-first-served: {w['fifo_conflicts']}); bench utilisation {w['utilisation']}%; "
          f"invariant violations: {len(w['violations'])}",
          *[f"- VIOLATION: {v}" for v in w["violations"]],
          "", "8-week simulation, 1,500 initial + 700 new filings a week:", "",
          "| | aging + must-list | plain priority |", "|---|---|---|",
          f"| Longest wait, Critical (days) | {on['longest_wait_days']['Critical']} | {off['longest_wait_days']['Critical']} |",
          f"| Longest wait, High | {on['longest_wait_days']['High']} | {off['longest_wait_days']['High']} |",
          f"| Longest wait, Medium | {on['longest_wait_days']['Medium']} | {off['longest_wait_days']['Medium']} |",
          f"| Longest wait, Routine | {on['longest_wait_days']['Routine']} | {off['longest_wait_days']['Routine']} |",
          f"| Deferred 3+ times | {on['deferred_3_plus_percent']}% | {off['deferred_3_plus_percent']}% |",
          f"| Past deadline | {on['past_deadline']} | {off['past_deadline']} |",
          f"| Bench utilisation | {on['avg_utilisation_percent']}% | {off['avg_utilisation_percent']}% |"]
    if e2e:
        L += ["", "## 5. End to end", "",
              f"- {e2e['files']} files uploaded: batch {e2e['status']}, {e2e['scored']} cases scored in {e2e['upload_to_scored_s']} s; "
              f"draft cause list ready {e2e['upload_to_proposed_hearing_s']} s after upload (target: under 180 s); "
              f"{e2e['uploaded_cases_in_draft']}/{e2e['scored']} uploaded cases in the draft; invariant violations: {len(e2e['violations'])}",
              "- Timing is with no LLM and a local database. With a remote database and an LLM it is slower: measure again there."]
    L += ["", "## Known limits", "",
          "- Rules (urgency points, bands, Sec. 12 clauses, State income limits) need review by a lawyer before any real use.",
          "- One synthetic court; DLSA and State values are placeholders unless marked verified.",
          "- Offline extraction is rule-based and tuned to the sample document layouts; real judgments differ "
          "(see tests/test_real_judgments.py). The LLM path is not covered by these numbers.",
          "- Demo tokens are not real authentication."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", default=str(ROOT / "docs" / "EVAL.md"))
    ap.add_argument("--skip-upload", action="store_true", help="skip the end-to-end upload timing (needs fastapi etc.)")
    a = ap.parse_args()
    m = {"triage": triage_metrics(), "summ": summarisation_metrics(), "legal": legal_aid_metrics(), "sched": scheduling_metrics()}
    if not a.skip_upload:
        try:
            m["e2e"] = end_to_end_metrics()
        except ImportError as exc:
            print(f"end-to-end timing skipped: {exc}")
    text = render(m)
    Path(a.write).write_text(text, encoding="utf-8")
    print(text)
