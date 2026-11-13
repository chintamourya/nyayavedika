"""Court Staff daily desk: reopening a saved cause list, readiness notes, the hearing board and outcome recording,
and the docket's plain-words "why this needs attention". stdlib sqlite3, no keys, no network."""
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import auth, cause_list, config, demo_seed, staff_api, store, triage  # noqa: E402

TODAY = date(2026, 10, 26)  # a Monday


class DeskDb(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.old = (config.DATABASE_URL, config.STORAGE_DIR)
        config.DATABASE_URL, config.STORAGE_DIR = f"sqlite:///{tmp}/t.db", f"{tmp}/storage"
        self.db = store.connect()
        store.prepare_database(self.db)
        demo_seed.write(self.db, demo_seed.build(120, 42, TODAY))

    def tearDown(self):
        self.db.close()
        config.DATABASE_URL, config.STORAGE_DIR = self.old
        triage.load_adjournment_rates({})

    def _listed(self, payload):
        return sorted(c["case_id"] for d in payload["calendar"] for b in d["benches"] for c in b["cases"])


class CauseListReopenTests(DeskDb):
    def test_saved_draft_reopens_with_the_same_cases_and_reflects_moves_and_holds(self):
        plan = cause_list.prepare(self.db, TODAY, 5)
        cid = cause_list.save_draft(self.db, plan)
        view = cause_list.view(self.db, cid)
        self.assertEqual(view["status"], "draft")
        self.assertEqual(self._listed(view), self._listed(plan))
        self.assertEqual(view["metrics"]["cases_listed"], len(self._listed(plan)))
        self.assertTrue(set(view["readiness"]) <= set(self._listed(plan)))

        held = self._listed(plan)[0]
        cause_list.accept_slot(self.db, held, "hold", "demo-staff", "staff", cause_list_id=cid)
        after = cause_list.view(self.db, cid)
        self.assertNotIn(held, self._listed(after))
        self.assertEqual(len(self._listed(after)), len(self._listed(plan)) - 1)

    def test_recent_lists_name_the_draft_and_its_case_count(self):
        plan = cause_list.prepare(self.db, TODAY, 5)
        cid = cause_list.save_draft(self.db, plan)
        lists = cause_list.recent(self.db)["lists"]
        self.assertEqual(lists[0]["id"], cid)
        self.assertEqual(lists[0]["status"], "draft")
        self.assertEqual(lists[0]["cases"], len(self._listed(plan)))
        self.assertNotIn("plan", lists[0])

    def test_unknown_list_is_a_lookup_error(self):
        with self.assertRaises(LookupError):
            cause_list.view(self.db, 99999)

    def test_published_list_reopens_read_only_with_published_slots(self):
        plan = cause_list.prepare(self.db, TODAY, 5)
        cid = cause_list.save_draft(self.db, plan)
        cause_list.publish(self.db, cid, "demo-staff", "staff")
        view = cause_list.view(self.db, cid)
        self.assertEqual(view["status"], "published")
        self.assertEqual(self._listed(view), self._listed(plan))
        self.assertTrue(all(c["listing_status"] == "published"
                            for d in view["calendar"] for b in d["benches"] for c in b["cases"]))


class HearingBoardTests(DeskDb):
    def _publish(self):
        plan = cause_list.prepare(self.db, TODAY, 5)
        cid = cause_list.save_draft(self.db, plan)
        cause_list.publish(self.db, cid, "demo-staff", "staff")
        return plan

    def test_board_lists_the_day_with_slots_and_records_outcomes(self):
        plan = self._publish()
        first_day = date.fromisoformat(plan["calendar"][0]["date"])
        board = staff_api.hearing_board(self.db, first_day, 1, today=first_day)
        expected = sum(len(b["cases"]) for b in plan["calendar"][0]["benches"])
        self.assertEqual(board["counts"]["listed"], expected)
        self.assertEqual(board["counts"]["to_record"], expected)
        h = board["hearings"][0]
        self.assertTrue(h["slot_start"])
        self.assertIsInstance(h["readiness"], list)

        before = int(store.get_case(h["case_id"], db=self.db).get("adjournments") or 0)
        nxt = (first_day + timedelta(days=21)).isoformat()
        out = cause_list.record_outcome(self.db, h["hearing_id"], "adjourned", "demo-staff", "staff",
                                        reason="Witness absent", next_date=nxt)
        self.assertEqual((out["next_date"], out["corrected"]), (nxt, False))
        case = store.get_case(h["case_id"], db=self.db)
        self.assertEqual((case["next_hearing_date"], int(case["adjournments"])), (nxt, before + 1))
        # correcting the same hearing must not count a second adjournment
        cause_list.record_outcome(self.db, h["hearing_id"], "adjourned", "demo-staff", "staff",
                                  reason="Advocate sought time", next_date=nxt)
        self.assertEqual(int(store.get_case(h["case_id"], db=self.db)["adjournments"]), before + 1)
        board = staff_api.hearing_board(self.db, first_day, 1, today=first_day)
        self.assertEqual(board["counts"]["recorded"], 1)
        self.assertEqual(self.db.select("audit_log", {"action": "hearing_outcome"}, order="id DESC")[0]["actor"], "demo-staff")

    def test_next_date_is_validated(self):
        plan = self._publish()
        first_day = date.fromisoformat(plan["calendar"][0]["date"])
        h = staff_api.hearing_board(self.db, first_day, 1, today=first_day)["hearings"][0]
        with self.assertRaises(ValueError):
            cause_list.record_outcome(self.db, h["hearing_id"], "adjourned", "demo-staff", "staff",
                                      next_date=first_day.isoformat())
        with self.assertRaises(ValueError):
            cause_list.record_outcome(self.db, h["hearing_id"], "adjourned", "demo-staff", "staff", next_date="31/12/2026")
        out = cause_list.record_outcome(self.db, h["hearing_id"], "disposed", "demo-staff", "staff",
                                        next_date=(first_day + timedelta(days=5)).isoformat())
        self.assertIsNone(out["next_date"])   # a disposed matter keeps no next date

    def test_earlier_hearings_without_an_outcome_are_listed_to_record(self):
        plan = self._publish()
        first_day = date.fromisoformat(plan["calendar"][0]["date"])
        later = first_day + timedelta(days=10)
        board = staff_api.hearing_board(self.db, later, 1, today=later)
        self.assertEqual(board["counts"]["listed"], 0)
        self.assertTrue(board["unrecorded_earlier"])
        self.assertTrue(all(not x["outcome"] for x in board["unrecorded_earlier"]))


class DocketAttentionTests(unittest.TestCase):
    def test_reasons_come_only_from_stored_facts(self):
        today = "2026-10-26"
        row = {"flags": ["UNDERTRIAL_RELEASE_ELIGIBLE", "CUSTODY_DATE_MISSING"], "sla_due_on": "2026-10-01",
               "listed_on": None, "must_list": True, "deferred": 3, "next_hearing_date": "2026-10-20",
               "data_quality": "needs_review", "band": "Critical"}
        texts = " | ".join(a["text"] for a in staff_api.attention_reasons(row, today))
        for expected in ("Sec. 479", "Custody details missing", "deadline 2026-10-01", "left out of 3",
                         "2026-10-20 has passed", "missing or uncertain", "Critical band"):
            self.assertIn(expected, texts)
        self.assertEqual(staff_api.attention_reasons({"flags": [], "band": "Routine"}, today), [])
        listed = {**row, "listed_on": "2026-10-28"}
        self.assertNotIn("has passed and no hearing slot", " ".join(a["text"] for a in staff_api.attention_reasons(listed, today)))

    def test_readiness_notes(self):
        notes = staff_api.readiness_notes({"accused_in_custody": True, "data_quality": "needs_review",
                                           "review_fields": ["custody_since"], "stage": None, "adjournments": 12})
        text = " | ".join(notes)
        for expected in ("custody since", "production", "Stage not recorded"):
            self.assertIn(expected, text)
        self.assertNotIn("adjourned", text)   # context for the docket, not a readiness task
        self.assertEqual(staff_api.readiness_notes({"stage": "evidence", "adjournments": 30}), [])


class TriageAndSchedulingSummaryTests(DeskDb):
    def test_preview_matches_what_the_planner_then_does(self):
        before = self.db.count("triage_scores")
        pv = cause_list.preview(self.db, TODAY, 5)
        self.assertEqual(self.db.count("triage_scores"), before)   # read-only
        self.assertEqual(pv["sittings"], 5 * pv["benches"])
        self.assertGreater(pv["capacity_minutes"], 0)
        self.assertEqual(sum(pv["by_band"].values()), pv["waiting"])
        self.assertLessEqual(pv["must_list"], pv["waiting"])
        plan = cause_list.prepare(self.db, TODAY, 5)
        listed = len(self._listed(plan))
        self.assertEqual(listed + len(plan["unscheduled"]), pv["waiting"])   # same population as the planner
        self.assertEqual(plan["metrics"]["must_list_total"], pv["must_list"])  # same must-list rule and fresh scores
        if pv["fits"]:
            self.assertEqual(plan["unscheduled"], [])
        # a court holiday removes that day's bench time
        self.db.insert("court_calendar", [{"day": TODAY.isoformat(), "kind": "holiday"}])
        self.assertEqual(cause_list.preview(self.db, TODAY, 5)["closed_days"], [TODAY.isoformat()])

    def test_today_names_the_top_unlisted_cases_with_reasons(self):
        t = cause_list.today_counters(self.db, TODAY)
        self.assertEqual(sum(t["by_band"].values()), t["pipeline"]["docket_pending"])
        top = t["top_unlisted"]
        self.assertTrue(top)
        self.assertEqual([r["score"] for r in top], sorted((r["score"] for r in top), reverse=True))
        self.assertTrue(all("attention" in r for r in top))

    def test_docket_rows_carry_their_score_drivers(self):
        cause_list.score_changed(self.db, TODAY)
        rows = staff_api.docket(self.db, limit=20)["rows"]
        with_drivers = [r for r in rows if r["drivers"]]
        self.assertTrue(with_drivers)
        pts = [float(d["points"]) for d in with_drivers[0]["drivers"]]
        self.assertEqual(pts, sorted(pts, reverse=True))
        self.assertTrue(all(p > 0 for p in pts))


class RealCasesFirstTests(DeskDb):
    """A low-priority uploaded / imported case must still be listed above high-priority synthetic examples."""
    def setUp(self):
        super().setUp()
        case = {"case_id": "UPL/2026/LOW", "case_type": "civil_suit", "stage": "evidence", "filing_date": "2026-09-01"}
        store.upsert_case(case, triage.score_case(case, TODAY), source="upload", db=self.db)
        self.db.commit()

    def test_today_docket_and_diary_put_uploads_on_top(self):
        top = cause_list.today_counters(self.db, TODAY)["top_unlisted"]
        self.assertEqual(top[0]["case_id"], "UPL/2026/LOW")
        self.assertTrue(all(r["source"] == "synthetic" for r in top[1:]))
        self.assertEqual(staff_api.docket(self.db)["rows"][0]["case_id"], "UPL/2026/LOW")
        plan = cause_list.prepare(self.db, TODAY, 5)
        cid = cause_list.save_draft(self.db, plan)
        cause_list.publish(self.db, cid, "demo-staff", "staff")
        day = next(d["date"] for d in plan["calendar"] for b in d["benches"] for c in b["cases"] if c["case_id"] == "UPL/2026/LOW")
        board = staff_api.hearing_board(self.db, date.fromisoformat(day), 1, today=date.fromisoformat(day))
        self.assertEqual(board["hearings"][0]["case_id"], "UPL/2026/LOW")
        sources = [h["source"] == "synthetic" for h in board["hearings"]]
        self.assertEqual(sources, sorted(sources))   # no upload after a synthetic row

    def test_frontend_orders_every_staff_list_real_first(self):
        script = (ROOT / "static" / "staff.js").read_text(encoding="utf-8")
        self.assertNotIn("capSyntheticExamples(", script.replace("return capSyntheticExamples(realFirst(rows), limit)", ""))
        self.assertIn("realFirst(x.cases)", script)
        self.assertIn("realFirst(p.unscheduled)", script)


class UndertrialRolesTests(DeskDb):
    """A lawyer approves or dismisses; court staff then record filing, hearing and the court's decision."""
    def test_staff_records_court_steps_but_cannot_decide(self):
        from nyayavedika.agents import undertrial_watch as uw
        uw.run_scan(today=TODAY)
        alerts = self.db.select("alerts", {"status": "pending"}, order="id")
        self.assertTrue(alerts)
        first = alerts[0]["id"]
        for decision in ("approved", "dismissed"):
            with self.assertRaises(PermissionError):
                uw.advance_alert(first, decision, "demo-staff", "staff", reason="not mine to decide")
        uw.assign_counsel(first, "Advocate Example", "dlsa_assignment", actor="demo-staff", role="staff")
        uw.advance_alert(first, "approved", "demo-lawyer", "lawyer")
        for step, note in (("filed", None), ("heard", None), ("release_ordered", "On bail, 2026-10-30"), ("released", None)):
            self.assertEqual(uw.advance_alert(first, step, "demo-staff", "staff", note=note)["status"], step)
        with self.assertRaises(ValueError):          # an impossible step is refused, not a crash
            uw.advance_alert(first, "filed", "demo-staff", "staff")
        actions = [a["action"] for a in self.db.select("audit_log", order="id") if a["entity"] == f"alert:{first}"]
        self.assertEqual(actions, ["alert_counsel_recorded", "alert_approved", "alert_filed", "alert_heard",
                                   "alert_release_ordered", "alert_released"])


class Section479AuthorityTests(DeskDb):
    """Counsel decides whether to file; only the court orders release; the registry records court events."""
    def _alert(self):
        from nyayavedika.agents import undertrial_watch as uw
        uw.run_scan(today=TODAY)
        return uw, self.db.select("alerts", {"status": "pending"}, order="id")[0]["id"]

    def test_lawyer_cannot_record_court_events(self):
        uw, aid = self._alert()
        uw.assign_counsel(aid, "Advocate Example", "dlsa_assignment", actor="demo-staff", role="staff")
        uw.advance_alert(aid, "approved", "demo-lawyer", "lawyer")
        for step in ("filed", "heard", "release_ordered", "denied", "released"):
            with self.assertRaises(PermissionError):
                uw.advance_alert(aid, step, "demo-lawyer", "lawyer", note="x")

    def test_lawyer_cannot_decide_before_registry_assigns_counsel(self):
        uw, aid = self._alert()
        with self.assertRaises(PermissionError):
            uw.advance_alert(aid, "approved", "demo-lawyer", "lawyer")
        self.assertEqual(self.db.select("alerts", {"id": aid})[0]["status"], "pending")

    def test_release_needs_a_court_order_and_the_order_needs_its_details(self):
        uw, aid = self._alert()
        uw.assign_counsel(aid, "Advocate Example", "dlsa_assignment", actor="demo-staff", role="staff")
        uw.advance_alert(aid, "approved", "demo-lawyer", "lawyer")
        uw.advance_alert(aid, "filed", "demo-staff", "staff", note="Crl.M.P. 41/2026")
        with self.assertRaises(ValueError):
            uw.advance_alert(aid, "released", "demo-staff", "staff")             # no release without an order
        with self.assertRaises(ValueError):
            uw.advance_alert(aid, "release_ordered", "demo-staff", "staff")      # the order's details are required
        with self.assertRaises(ValueError):
            uw.advance_alert(aid, "denied", "demo-staff", "staff")
        uw.advance_alert(aid, "release_ordered", "demo-staff", "staff", note="On bond (first-time offender), 2026-10-30")
        alert = self.db.select("alerts", {"id": aid})[0]
        self.assertEqual([s["status"] for s in alert["details"]["steps"]], ["approved", "filed", "release_ordered"])
        self.assertEqual(alert["details"]["steps"][1]["note"], "Crl.M.P. 41/2026")
        # still in custody until actually released: no second alert, and the live count keeps it open
        self.assertEqual(uw.run_scan(today=TODAY)["new_release_alerts"], 0)
        self.assertIn(aid, [a["id"] for a in staff_api.alerts(self.db, "all")["alerts"] if a["custody_days"] is not None])

    def test_registry_records_counsel_on_record(self):
        uw, aid = self._alert()
        with self.assertRaises(ValueError):
            uw.assign_counsel(aid, "", "dlsa_assignment", actor="demo-staff", role="staff")
        with self.assertRaises(ValueError):
            uw.assign_counsel(aid, "Adv. R. Lakshmi", "self_appointed", actor="demo-staff", role="staff")
        out = uw.assign_counsel(aid, "Adv. R. Lakshmi", "dlsa_assignment", "DLSA/HYD/LA/412/2026", "demo-staff", "staff")
        self.assertEqual(out["counsel"]["basis_label"], "DLSA assignment letter (legal aid)")
        uw.assign_counsel(aid, "Adv. K. Rao", "vakalatnama", actor="demo-staff", role="staff")   # counsel can change
        alert = self.db.select("alerts", {"id": aid})[0]
        self.assertEqual((alert["details"]["counsel"]["name"], alert["status"]), ("Adv. K. Rao", "pending"))
        self.assertEqual(len([a for a in self.db.select("audit_log") if a["action"] == "alert_counsel_recorded"]), 2)
        self.assertEqual(auth.POLICY["POST /api/alerts/{alert_id}/counsel"], (auth.STAFF,))   # nobody self-assigns

    def test_draft_asks_for_bail_or_bond_as_the_law_says(self):
        from nyayavedika.agents import undertrial_watch as uw
        rc = {"custody_days": 400, "threshold_days": 365, "basis": "one-third (first-time offender)", "needs_review": []}
        base = {"case_id": "X/1", "custody_since": "2025-01-01", "max_sentence_years": 3, "release_check": rc}
        self.assertIn("RELEASE ON BOND", uw._template({**base, "first_time_offender": True}))
        self.assertIn("RELEASE ON BAIL", uw._template({**base, "first_time_offender": False}))
        self.assertNotIn("entitled to release", uw._template({**base, "first_time_offender": True}))


class PolicyTests(unittest.TestCase):
    def test_new_court_routes_are_staff_only(self):
        for key in ("GET /api/cause-lists", "GET /api/cause-lists/{cause_list_id}/view", "GET /api/hearings",
                    "GET /api/scheduling/preview",
                    "POST /api/hearings/{hearing_id}/outcome"):
            self.assertEqual(auth.POLICY[key], (auth.STAFF,), key)


if __name__ == "__main__":
    unittest.main()
