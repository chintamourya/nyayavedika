"""Phase 5: triage tweaks, queue memory, memory-aware planner + invariants, publishing, fast lane,
outcomes / learned adjournment, jobs, Undertrial Watch fixes, 8-week simulation. stdlib sqlite3, no keys.
"""
import copy
import importlib.util
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import cause_list, config, demo_seed, intake, jobs, sample_data, scheduler, store, triage, worker  # noqa: E402
from nyayavedika.agents import undertrial_watch as uw  # noqa: E402

TODAY = date(2026, 10, 26)  # a Monday


def docket(n=600, seed=42):
    return triage.triage_all(sample_data.generate(n, seed=seed, today=TODAY), TODAY)


class TriageTweakTests(unittest.TestCase):
    def test_custody_without_date_is_flagged_and_kept_as_custody(self):
        r = triage.score_case({"case_id": "C1", "case_type": "criminal_trial", "filing_date": "2025-01-01",
                               "accused_in_custody": True, "max_sentence_years": 7}, TODAY)
        self.assertIn("CUSTODY_DATE_MISSING", r["flags"])
        self.assertTrue(r["needs_review"])
        self.assertIn("Accused in custody +15", r["reasons"])

    def test_age_counts_from_first_eligible_on(self):
        base = {"case_id": "A", "case_type": "civil_suit", "filing_date": "2016-01-01", "stage": "evidence"}
        old = triage.score_case(base, TODAY)["score"]
        recent = triage.score_case({**base, "first_eligible_on": "2026-09-01"}, TODAY)["score"]
        self.assertLess(recent, old)

    def test_time_bound_law_flag_and_points(self):
        cheque = triage.score_case({"case_id": "N", "case_type": "cheque_bounce", "filing_date": "2026-10-01"}, TODAY)
        self.assertIn("TIME_BOUND_LAW", cheque["flags"])
        self.assertTrue(any("143(3) NI Act" in x for x in cheque["reasons"]))
        self.assertEqual(cheque["rules_version"], "rules-v2")


class PlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = docket()
        cls.plan = scheduler.plan_week(cls.results, TODAY, 5, rules_version=triage.RULES_VERSION)

    def test_invariants_hold_and_nothing_is_lost(self):
        self.assertEqual(self.plan["violations"], [])
        self.assertEqual(scheduler.check_plan(self.plan, {r["case_id"] for r in self.results}), [])

    def test_utilisation_beats_the_old_planner(self):
        old = scheduler.build_cause_list(self.results, TODAY, 5)["metrics"]
        new = self.plan["metrics"]
        self.assertGreater(new["avg_bench_utilisation_percent"], old["avg_bench_utilisation_percent"])
        self.assertLess(new["cases_carried_over"], old["cases_carried_over"])
        self.assertEqual(new["advocate_conflicts"], 0)

    def test_same_input_same_plan(self):
        again = scheduler.plan_week(copy.deepcopy(self.results), TODAY, 5, rules_version=triage.RULES_VERSION)
        self.assertEqual(again, self.plan)

    def test_check_plan_catches_violations(self):
        bad = copy.deepcopy(self.plan)
        day = bad["calendar"][0]
        a, b = day["benches"][0]["cases"][0], day["benches"][1]["cases"][0]
        b.update(start_min=a["start_min"], end_min=a["end_min"], advocates=a["advocates"])
        day["benches"][2]["cases"][0]["expected_minutes"] = 10_000
        bad["unscheduled"].append({"case_id": a["case_id"]})
        bad["deadline_watch"].append({"case_id": "LATE/1", "sla_due_on": "2026-10-27", "listed_on": None})
        bad["custody_checks"].append({"case_id": "CU/1", "custody_since": None, "flags": [], "needs_review": False})
        text = " | ".join(scheduler.check_plan(bad, {"NOT/IN/PLAN"}))
        for expected in ("double-booked", "available", "appears twice", "nothing lost", "LATE/1", "CU/1"):
            self.assertIn(expected, text)

    def test_queue_memory_formula(self):
        st = {"consecutive_deferrals": 2, "sla_due_on": (TODAY - timedelta(days=21)).isoformat()}
        p = scheduler.effective_priority(40, "Routine", st, TODAY)
        self.assertEqual((p["aging_boost"], p["score_eff"], p["must_list"]), (12, 52, True))  # 3*2 + 2*3 weeks
        self.assertTrue(scheduler.effective_priority(40, "Routine", {"consecutive_deferrals": 3}, TODAY)["must_list"])
        self.assertFalse(scheduler.effective_priority(40, "Routine", {"consecutive_deferrals": 2}, TODAY)["must_list"])
        self.assertEqual(scheduler.effective_priority(90, "High", {"consecutive_deferrals": 20}, TODAY)["score_eff"], 100)

    def test_must_list_shortfall_is_reported_not_dropped(self):
        state = {r["case_id"]: {"consecutive_deferrals": 3} for r in self.results}
        plan = scheduler.plan_week(self.results, TODAY, 2, state=state)
        self.assertIsNotNone(plan["capacity_shortfall"])
        self.assertIn("exceeds the reserve", plan["capacity_shortfall"]["message"])
        self.assertEqual(plan["violations"], [])

    def test_calendar_and_hold_are_respected(self):
        cal = [{"day": "2026-10-27", "kind": "holiday", "bench_id": None},
               {"day": "2026-10-26", "kind": "judge_leave", "bench_id": "CR-2"}]
        held = self.results[0]["case_id"]
        plan = scheduler.plan_week(self.results, TODAY, 5, calendar=cal, state={held: {"hold_until": "2026-12-01"}})
        self.assertNotIn("2026-10-27", [d["date"] for d in plan["calendar"]])
        cr2 = next(b for b in plan["calendar"][0]["benches"] if b["bench_id"] == "CR-2")
        self.assertEqual((cr2["open"], cr2["cases"]), (False, []))
        self.assertEqual([h["case_id"] for h in plan["on_hold"]], [held])
        self.assertEqual(scheduler.check_plan(plan, {r["case_id"] for r in self.results}), [])

    def test_unlisted_cases_carry_a_reason(self):
        tiny = [{**b, "minutes_per_day": 30} for b in scheduler.DEFAULT_BENCHES]
        plan = scheduler.plan_week(self.results, TODAY, 1, benches=tiny)
        self.assertTrue(plan["unscheduled"])
        self.assertTrue({u["reason"] for u in plan["unscheduled"]} <= {"capacity", "advocate_conflict", "no_bench"})
        self.assertEqual(plan["violations"], [])  # critical cases not listed in time raise deadline alerts


class DbTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.old = (config.DATABASE_URL, config.STORAGE_DIR)
        config.DATABASE_URL, config.STORAGE_DIR = f"sqlite:///{tmp}/t.db", f"{tmp}/storage"
        self.db = store.connect()
        store.prepare_database(self.db)

    def tearDown(self):
        self.db.close()
        config.DATABASE_URL, config.STORAGE_DIR = self.old
        triage.load_adjournment_rates({})

    def seed(self, n=200):
        demo_seed.write(self.db, demo_seed.build(n, 42, TODAY))


class CauseListDbTests(DbTestCase):
    def test_draft_publish_flow(self):
        self.seed()
        self.db.execute("UPDATE benches SET minutes_per_day = 60")  # force some deferrals
        plan = cause_list.prepare(self.db, TODAY, 5)
        self.assertEqual(plan["violations"], [])
        cid = cause_list.save_draft(self.db, plan)
        listed = sum(len(b["cases"]) for d in plan["calendar"] for b in d["benches"])
        self.assertEqual(self.db.count("listings", {"cause_list_id": cid}), listed)
        self.assertEqual(self.db.count("deferrals", {"cause_list_id": cid}), 0)   # recorded on publish
        some_deferred = plan["unscheduled"][0]["case_id"]
        some_listed = plan["calendar"][0]["benches"][0]["cases"][0]["case_id"]
        before = (store.queue_state(some_deferred, db=self.db) or {}).get("consecutive_deferrals") or 0
        self.assertEqual(self.db.count("hearings", {"outcome": None}), 0)
        # a second draft of the same week supersedes the first; neither touches the queue counters
        cid2 = cause_list.save_draft(self.db, plan)
        self.assertEqual(self.db.select("cause_lists", {"id": cid})[0]["status"], "superseded")
        self.assertEqual((store.queue_state(some_deferred, db=self.db) or {}).get("consecutive_deferrals") or 0, before)
        self.assertEqual(self.db.count("deferrals", {"cause_list_id": cid2}), 0)
        cid = cid2
        out = cause_list.publish(self.db, cid, "demo-staff", "staff")
        self.assertEqual(self.db.count("deferrals", {"cause_list_id": cid}), len(plan["unscheduled"]))
        self.assertEqual(store.queue_state(some_deferred, db=self.db)["consecutive_deferrals"], before + 1)
        self.assertEqual(store.queue_state(some_listed, db=self.db)["consecutive_deferrals"], 0)
        self.assertEqual(out["hearings_created"], listed)
        self.assertEqual(self.db.count("listings", {"cause_list_id": cid, "status": "published"}), listed)
        self.assertEqual(store.get_case(some_listed, db=self.db)["next_hearing_date"], plan["calendar"][0]["date"])
        self.assertEqual(self.db.select("audit_log", {"action": "cause_list_published"})[0]["actor"], "demo-staff")
        with self.assertRaises(ValueError):
            cause_list.publish(self.db, cid, "demo-staff", "staff")

    def test_only_changed_cases_are_rescored(self):
        self.seed(50)
        self.assertEqual(cause_list.score_changed(self.db, TODAY), 0)
        case_id = self.db.select("cases", order="case_id", limit=1)[0]["case_id"]
        intake.patch_case(case_id, {"stage": "arguments"}, "demo-staff", "staff", db=self.db)
        self.db.execute("UPDATE cases SET updated_at = '2999-01-01' WHERE case_id = :c", {"c": case_id})
        self.assertEqual(cause_list.score_changed(self.db, TODAY), 1)

    def test_outcomes_and_learned_adjournment_rate(self):
        store.upsert_case({"case_id": "L/1", "case_type": "civil_suit", "stage": "evidence", "filing_date": "2024-01-01"},
                          triage.score_case({"case_id": "L/1", "case_type": "civil_suit"}, TODAY), source="csv", db=self.db)
        ids = [self.db.insert("hearings", [{"case_id": "L/1", "hearing_date": f"2026-0{m}-10", "bench_id": "CR-3"}], returning="hearing_id")
               for m in range(1, 9)]
        for h in ids[:7]:
            cause_list.record_outcome(self.db, h, "heard", "demo-staff", "staff")
        cause_list.record_outcome(self.db, ids[7], "adjourned", "demo-staff", "staff", reason="witness absent")
        prior = triage.STAGE_ADJ_RISK["evidence"]
        self.assertAlmostEqual(cause_list.learned_rates(self.db)[("civil_suit", "evidence")],
                               round((1 + 10 * prior) / (8 + 10), 3))
        self.assertEqual(store.get_case("L/1", db=self.db)["adjournments"], 1)
        h = self.db.insert("hearings", [{"case_id": "L/1", "hearing_date": "2026-10-20", "bench_id": "CR-3"}], returning="hearing_id")
        cause_list.record_outcome(self.db, h, "disposed", "demo-staff", "staff")
        self.assertEqual(self.db.select("cases", {"case_id": "L/1"})[0]["status"], "disposed")
        with self.assertRaises(ValueError):
            cause_list.record_outcome(self.db, h, "vanished", "demo-staff", "staff")


RELEASE_FIR = (b"FIRST INFORMATION REPORT (Under Section 173 BNSS)\nFIR No.: 0099/2023    Date of FIR: 10.01.2023\n"
               b"Act and Section: BNS Section 303(2) (Theft)\nThe accused was remanded to judicial custody on 12.01.2023.\n"
               b"Status: Accused in judicial custody since 12.01.2023.\n")


class FastLaneTests(DbTestCase):
    def test_release_eligible_upload_gets_a_proposed_slot(self):
        out = intake.create_batch([("fir_old.txt", RELEASE_FIR)], db=self.db)
        worker.run(once=True, concurrency=1)
        job = intake.batch_status(out["batch_id"], db=self.db)["files"][0]
        self.assertEqual(job["stage"], "proposed")
        slot = job["result"]["proposed_slot"]
        self.assertTrue(slot["day"] > TODAY.isoformat() or slot["day"] >= date.today().isoformat())
        self.assertIn("UNDERTRIAL_RELEASE_ELIGIBLE", job["result"]["flags"])
        today = cause_list.today_counters(self.db)
        self.assertEqual([p["case_id"] for p in today["fast_lane_proposals"]], [job["case_id"]])
        self.assertEqual(self.db.count("alerts", {"case_id": job["case_id"], "status": "pending"}), 1)  # hand-off
        # Registrar decisions
        moved = cause_list.accept_slot(self.db, job["case_id"], "move", "demo-staff", "staff", bench_id="CR-5")
        self.assertEqual(moved["slot"]["bench_id"], "CR-5")
        held = cause_list.accept_slot(self.db, job["case_id"], "hold", "demo-staff", "staff", hold_until="2027-01-01")
        self.assertEqual(store.queue_state(job["case_id"], db=self.db)["hold_until"], "2027-01-01")
        self.assertEqual(held["hold_until"], "2027-01-01")
        with self.assertRaises(LookupError):
            cause_list.accept_slot(self.db, job["case_id"], "accept", "demo-staff", "staff")


class UndertrialTests(DbTestCase):
    def setUp(self):
        super().setUp()
        case = {"case_id": "UT/1", "case_type": "criminal_trial", "filing_date": "2023-01-10", "stage": "evidence",
                "accused_in_custody": True, "custody_since": "2023-01-12", "max_sentence_years": 3, "act": "BNS", "section": "303"}
        store.upsert_case(case, triage.score_case(case, TODAY), source="csv", db=self.db)
        gap = {"case_id": "UT/2", "case_type": "criminal_trial", "filing_date": "2025-01-10", "accused_in_custody": True}
        store.upsert_case(gap, triage.score_case(gap, TODAY), source="csv", db=self.db)
        self.db.commit()

    def alerts(self):
        return self.db.select("alerts", {"case_id": "UT/1"}, order="id")

    def test_dismissed_today_does_not_return_tomorrow(self):
        first = uw.run_scan(today=TODAY)
        self.assertEqual(first["new_release_alerts"], 1)
        self.assertEqual(first["data_needed"][0]["case_id"], "UT/2")
        self.assertIn("custody certificate", first["data_needed"][0]["who_can_supply"][0])
        alert = self.alerts()[0]
        self.assertTrue(any("not attributable to the accused" in c for c in alert["details"]["checklist"]))
        uw.assign_counsel(alert["id"], "Advocate Example", "dlsa_assignment", actor="demo-staff", role="staff")
        with self.assertRaises(ValueError):
            uw.advance_alert(alert["id"], "dismissed", "demo-lawyer", "lawyer")  # a reason is required
        uw.advance_alert(alert["id"], "dismissed", "demo-lawyer", "lawyer", reason="released in another case")
        self.assertEqual(uw.run_scan(today=TODAY + timedelta(days=1))["new_release_alerts"], 0)
        self.assertEqual(len(self.alerts()), 1)

    def test_snooze_expiry_and_custody_change_bring_it_back(self):
        uw.run_scan(today=TODAY)
        uw.assign_counsel(self.alerts()[0]["id"], "Advocate Example", "dlsa_assignment", actor="demo-staff", role="staff")
        uw.advance_alert(self.alerts()[0]["id"], "dismissed", "demo-lawyer", "lawyer", reason="check later",
                         snooze_until="2000-01-01T00:00:00+00:00")
        self.assertEqual(uw.run_scan(today=TODAY)["new_release_alerts"], 1)  # snooze is over
        uw.assign_counsel(self.alerts()[-1]["id"], "Advocate Example", "dlsa_assignment", actor="demo-staff", role="staff")
        uw.advance_alert(self.alerts()[-1]["id"], "dismissed", "demo-lawyer", "lawyer", reason="wrong custody date")
        out = intake.patch_case("UT/1", {"custody_since": "2023-02-01"}, "demo-staff", "staff")
        self.assertEqual(out["undertrial_rescan"]["new_release_alerts"], 1)  # facts changed -> rescanned

    def test_lifecycle(self):
        uw.run_scan(today=TODAY)
        aid = self.alerts()[0]["id"]
        uw.assign_counsel(aid, "Advocate Example", "dlsa_assignment", actor="demo-staff", role="staff")
        uw.advance_alert(aid, "approved", "demo-lawyer", "lawyer")          # counsel decides to file
        for status, note in (("filed", "Crl.M.P. 12/2026"), ("heard", None),
                             ("release_ordered", "On bond, order dated 2026-10-30"), ("released", None)):
            uw.advance_alert(aid, status, "demo-staff", "staff", note=note)   # the registry records the court's steps
        self.assertEqual(self.alerts()[0]["status"], "released")
        with self.assertRaises(ValueError):
            uw.advance_alert(aid, "pending", "demo-lawyer", "lawyer")
        self.assertEqual(uw.run_scan(today=TODAY)["new_release_alerts"], 0)


class JobTests(DbTestCase):
    def test_jobs_write_agent_runs(self):
        self.seed(120)
        self.db.commit()
        for name in ("aging_update", "undertrial_scan", "weekly_cause_list", "daily_topup"):
            out = jobs.run(name, TODAY)
            self.assertEqual(out["job"], name)
        self.assertEqual(jobs.run("weekly_cause_list", TODAY)["violations"], 0)
        runs = self.db.select("agent_runs", order="id")
        self.assertTrue(all(r["ended"] and r["counts"] is not None for r in runs if r["job"] != "ingest_worker"))
        with self.assertRaises(KeyError):
            jobs.run("make_coffee", TODAY)


class SimulationTests(unittest.TestCase):
    def test_aging_removes_past_deadline_cases(self):
        spec = importlib.util.spec_from_file_location("sim", ROOT / "scripts" / "simulate_8_weeks.py")
        sim = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sim)
        start, old = date(2026, 11, 2), config.SLA_DAYS
        config.SLA_DAYS = {"Critical": 1, "High": 3, "Medium": 5, "Routine": 10}  # shorter clocks: starvation shows in 4 weeks
        try:
            with_aging = sim.run(1200, 650, 4, 42, True, start)
            without = sim.run(1200, 650, 4, 42, False, start)
        finally:
            config.SLA_DAYS = old
        # overloaded beyond the (shortened) deadlines nobody can be on time; aging still caps the worst wait
        self.assertLess(with_aging["longest_wait_days"]["Routine"], without["longest_wait_days"]["Routine"])
        # the full default run (8 weeks, real SLA days) is recorded in docs/SIMULATION.md
        report = (ROOT / "docs" / "SIMULATION.md").read_text(encoding="utf-8")
        self.assertIn("SYNTHETIC", report)
        row = next(line for line in report.splitlines() if line.startswith("| Cases past deadline"))
        self.assertEqual(row.split("|")[2].strip(), "1")
        self.assertNotEqual(row.split("|")[3].strip(), "0")


if __name__ == "__main__":
    unittest.main()
