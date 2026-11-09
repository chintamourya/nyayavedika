"""Staff triage / scheduling efficiency and request latency: no duplicate scheduling across lists, batched DB access,
docket band counts, parallel searches and early understanding in the citizen research chat, parallel advocate parts,
compressed and cacheable static assets. stdlib sqlite3, no keys, no network."""
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401
import importlib.util
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import cause_list, config, demo_seed, legal_problem, sample_data, scheduler, staff_api, store, triage  # noqa: E402

TODAY = date(2026, 10, 26)  # a Monday


class PlannerAlreadyListedTests(unittest.TestCase):
    def test_case_with_a_firm_slot_elsewhere_is_not_listed_again_and_nothing_is_lost(self):
        results = triage.triage_all(sample_data.generate(120, seed=7, today=TODAY), TODAY)
        target = results[0]["case_id"]   # the highest-priority case: it would certainly be listed otherwise
        held = {target: {"day": "2026-10-27", "bench_id": "CR-1", "slot": "10:30-10:40", "listing_status": "accepted",
                         "cause_list_id": 9}}
        plan = scheduler.plan_week(results, TODAY, 5, already_listed=held)
        listed = {c["case_id"] for d in plan["calendar"] for b in d["benches"] for c in b["cases"]}
        self.assertNotIn(target, listed)
        self.assertNotIn(target, {u["case_id"] for u in plan["unscheduled"]})
        self.assertEqual([a["case_id"] for a in plan["already_listed"]], [target])
        self.assertEqual(plan["already_listed"][0]["listing_status"], "accepted")
        self.assertEqual(plan["metrics"]["already_listed"], 1)
        self.assertEqual(plan["violations"], [])
        self.assertEqual(scheduler.check_plan(plan, {r["case_id"] for r in results}), [])   # accounted for, not lost

    def test_check_plan_still_catches_a_case_both_listed_and_elsewhere(self):
        results = triage.triage_all(sample_data.generate(60, seed=3, today=TODAY), TODAY)
        plan = scheduler.plan_week(results, TODAY, 5)
        some = next(c for d in plan["calendar"] for b in d["benches"] for c in b["cases"])
        plan["already_listed"] = [{"case_id": some["case_id"]}]
        self.assertTrue(any("appears twice" in v for v in scheduler.check_plan(plan)))


class WeekBalanceTests(unittest.TestCase):
    """A week with spare bench time is spread across the days; a full week is packed; urgent cases never move."""

    @staticmethod
    def _days(plan, bands):
        return [i for i, d in enumerate(plan["calendar"]) for b in d["benches"] for c in b["cases"] if c["band"] in bands]

    def test_a_light_week_is_spread_and_lists_the_same_cases(self):
        results = triage.triage_all(sample_data.generate(120, seed=42, today=TODAY), TODAY)
        packed = scheduler.plan_week(results, TODAY, 5, balance=False)
        level = scheduler.plan_week(results, TODAY, 5)
        self.assertTrue(level["metrics"]["balanced"])
        daily = level["metrics"]["daily_utilisation_percent"]
        self.assertLess(max(daily) - min(daily), max(packed["metrics"]["daily_utilisation_percent"]) - min(packed["metrics"]["daily_utilisation_percent"]))
        self.assertTrue(all(u > 0 for u in daily))                       # no idle day left while Monday is crowded
        self.assertEqual(level["metrics"]["cases_listed"], packed["metrics"]["cases_listed"])
        self.assertEqual(self._days(level, {"Critical"}), self._days(packed, {"Critical"}))   # urgent cases keep day 1
        self.assertEqual(level["violations"], [])
        self.assertEqual(scheduler.check_plan(level, {r["case_id"] for r in results}), [])

    def test_balanced_cases_stay_within_their_listing_deadline(self):
        results = triage.triage_all(sample_data.generate(120, seed=42, today=TODAY), TODAY)
        plan = scheduler.plan_week(results, TODAY, 5)
        for band in scheduler.BALANCE_BANDS:
            self.assertTrue(all(i < config.SLA_DAYS[band] for i in self._days(plan, {band})), band)

    def test_a_full_week_is_packed_when_spreading_would_list_fewer_cases(self):
        results = triage.triage_all(sample_data.generate(900, seed=42, today=TODAY), TODAY)
        packed = scheduler.plan_week(results, TODAY, 5, balance=False)
        chosen = scheduler.plan_week(results, TODAY, 5)
        self.assertGreaterEqual(chosen["metrics"]["cases_listed"], packed["metrics"]["cases_listed"])
        if not chosen["metrics"]["balanced"]:
            self.assertIn("fewer cases listed", chosen["metrics"]["balance_note"])

    def test_same_input_same_balanced_plan(self):
        results = triage.triage_all(sample_data.generate(150, seed=9, today=TODAY), TODAY)
        self.assertEqual(scheduler.plan_week(results, TODAY, 5), scheduler.plan_week(results, TODAY, 5))


class DbTestCase(unittest.TestCase):
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

    def _fast_lane_list(self, case_id: str, status: str, day: str = "2026-10-28") -> int:
        cid = self.db.insert("cause_lists", [{"court_id": "DEMO-DC", "start_date": "2026-10-27", "status": "draft",
                                              "plan": {"fast_lane": True, "days": 5}, "metrics": {}, "created_at": "x"}],
                             returning="id")
        self.db.insert("listings", [{"cause_list_id": cid, "case_id": case_id, "day": day, "bench_id": "CR-5",
                                     "slot_start": "10:30", "slot_end": "10:40", "expected_minutes": 10, "band": "Critical",
                                     "score": 90, "status": status}])
        self.db.commit()
        return cid


class NoDuplicateSchedulingTests(DbTestCase):
    def _pending_id(self):
        return self.db.select("cases", {"status": "pending"}, order="score DESC", limit=1)[0]["case_id"]

    def test_accepted_fast_lane_slot_keeps_the_case_off_the_weekly_draft(self):
        case_id = self._pending_id()
        self._fast_lane_list(case_id, "accepted")
        plan = cause_list.prepare(self.db, TODAY, 5)
        listed = {c["case_id"] for d in plan["calendar"] for b in d["benches"] for c in b["cases"]}
        self.assertNotIn(case_id, listed)
        self.assertIn(case_id, {a["case_id"] for a in plan["already_listed"]})
        self.assertEqual(plan["violations"], [])

    def test_published_list_outside_the_week_does_not_block(self):
        case_id = self._pending_id()
        self._fast_lane_list(case_id, "accepted", day="2026-12-01")   # a later week
        plan = cause_list.prepare(self.db, TODAY, 5)
        self.assertNotIn(case_id, {a["case_id"] for a in plan["already_listed"]})

    def test_redrafting_the_same_week_is_not_blocked_by_the_draft_it_replaces(self):
        first = cause_list.prepare(self.db, TODAY, 5)
        cause_list.save_draft(self.db, first)
        again = cause_list.prepare(self.db, TODAY, 5)
        self.assertEqual(again["already_listed"], [])
        self.assertEqual(again["metrics"]["cases_listed"], first["metrics"]["cases_listed"])

    def test_weekly_draft_withdraws_an_unaccepted_fast_lane_proposal_in_the_same_week(self):
        case_id = self._pending_id()
        fl = self._fast_lane_list(case_id, "proposed")
        plan = cause_list.prepare(self.db, TODAY, 5)
        listed = {c["case_id"] for d in plan["calendar"] for b in d["benches"] for c in b["cases"]}
        self.assertIn(case_id, listed)                       # a proposal is not a firm slot
        cause_list.save_draft(self.db, plan)
        self.assertEqual(self.db.select("listings", {"cause_list_id": fl})[0]["status"], "dropped")

    def test_publish_still_creates_one_hearing_per_listing(self):
        plan = cause_list.prepare(self.db, TODAY, 5)
        cid = cause_list.save_draft(self.db, plan)
        listed = sum(len(b["cases"]) for d in plan["calendar"] for b in d["benches"])
        before = self.db.count("hearings")   # the seeded history already has hearings
        out = cause_list.publish(self.db, cid, "demo-staff", "staff")
        self.assertEqual(out["hearings_created"], listed)
        self.assertEqual(self.db.count("hearings") - before, listed)
        some = plan["calendar"][0]["benches"][0]["cases"][0]["case_id"]
        self.assertEqual(store.queue_state(some, db=self.db)["last_listed_on"], plan["calendar"][0]["date"])
        # a fresh draft of the published week lists nobody twice
        again = cause_list.prepare(self.db, TODAY, 5)
        relisted = {c["case_id"] for d in again["calendar"] for b in d["benches"] for c in b["cases"]}
        published = {r["case_id"] for r in self.db.select("listings", {"cause_list_id": cid})}
        self.assertFalse(relisted & published)


class BatchedReadTests(DbTestCase):
    def test_get_cases_returns_every_requested_case_in_one_call(self):
        ids = [r["case_id"] for r in self.db.select("cases", limit=30)]
        with mock.patch.object(self.db, "select", wraps=self.db.select) as sel:
            got = store.get_cases(ids + ["missing/1", None], db=self.db)
        self.assertEqual(set(got), set(ids))
        self.assertEqual(sel.call_count, 1)
        self.assertEqual(got[ids[0]], store.get_case(ids[0], db=self.db))

    def test_rescore_custody_matches_the_rules(self):
        self.db.execute("UPDATE cases SET band = 'Routine', flags = '[]' WHERE accused_in_custody = 1")
        self.db.commit()
        changed = cause_list.rescore_custody(self.db, TODAY)
        self.assertGreater(changed, 0)
        self.assertEqual(cause_list.rescore_custody(self.db, TODAY), 0)   # idempotent: nothing stale is left

    def test_ensure_database_skips_the_migration_once_prepared(self):
        with mock.patch("nyayavedika.db_schema.migrate", side_effect=AssertionError("migrated again")):
            store.ensure_database(self.db)   # prepared in setUp: no second migration

    def test_today_counters_shape(self):
        t = cause_list.today_counters(self.db, TODAY)
        for key in ("critical_waiting", "release_eligible", "past_deadline", "needs_review", "uploaded_today",
                    "deferred_3_plus", "pipeline", "data_mix"):
            self.assertIn(key, t)
        self.assertEqual(t["pipeline"]["docket_pending"], self.db.count("cases", {"status": "pending"}))


class DocketBandTests(DbTestCase):
    def test_band_counts_ignore_the_band_filter_and_match_the_rows(self):
        everything = staff_api.docket(self.db, limit=10000)
        self.assertEqual(sum(everything["by_band"].values()), everything["total"])
        critical = staff_api.docket(self.db, band="Critical", limit=10000)
        self.assertEqual(critical["by_band"], everything["by_band"])
        self.assertEqual(critical["total"], everything["by_band"]["Critical"])
        self.assertTrue(all(r["band"] == "Critical" for r in critical["rows"]))


class CitizenResearchLatencyTests(unittest.TestCase):
    UNDERSTANDING = {"category": "Property and land disputes", "facts": ["A neighbour blocked a shared path."],
                     "parties": [], "dates": [], "jurisdiction": "Warangal, Telangana", "missing_info": [],
                     "legal_question": "What process addresses a blocked path?"}
    FORMULATIONS = {"first": "India Code Telangana easement access path", "second": "Telangana authority blocked pathway complaint"}
    ANSWER = {"understanding": "x", "laws_and_provisions": [], "rights_and_protections": [], "possible_remedies": [],
              "authorities": [], "free_legal_aid": [], "next_steps": [], "limitations": [], "conflicts": []}

    def _structured(self, calls):
        def structured(_system, _prompt, schema, **kwargs):
            calls.append((schema.__name__, kwargs.get("fast", False)))
            payload = {legal_problem.ProblemUnderstanding: self.UNDERSTANDING,
                       legal_problem.SearchFormulations: self.FORMULATIONS,
                       legal_problem.ResearchAnswer: self.ANSWER}[schema]
            return schema.model_validate(payload)
        return structured

    def test_the_two_searches_run_at_the_same_time_and_formulations_use_the_fast_model(self):
        calls, barrier = [], threading.Barrier(2, timeout=5)

        def search(query, **_kwargs):
            barrier.wait()   # raises BrokenBarrierError if the second search does not start while the first runs
            return {"results": [{"title": "Law", "url": "https://indiacode.nic.in/handle/1",
                                 "content": "Section 12 easement", "score": 0.9}]}

        with mock.patch.object(legal_problem.llm, "available", return_value=True), \
                mock.patch.object(legal_problem.llm, "structured", side_effect=self._structured(calls)):
            out = legal_problem.research("A neighbour blocked our shared path.", search_fn=search)
        self.assertFalse(out["no_reliable_sources"])
        self.assertIn(("SearchFormulations", True), calls)

    def test_a_failed_search_still_fails_the_whole_answer(self):
        def search(query, **_kwargs):
            return {"results": [], "error": "boom"} if "authority" in query else {"results": []}

        with mock.patch.object(legal_problem.llm, "available", return_value=True), \
                mock.patch.object(legal_problem.llm, "structured", side_effect=self._structured([])):
            with self.assertRaises(legal_problem.ResearchUnavailable):
                legal_problem.research("A neighbour blocked our shared path.", search_fn=search)

    def test_chat_starts_understanding_alongside_the_turn_decision_and_uses_it_once(self):
        calls, started = [], threading.Event()
        structured = self._structured(calls)

        def understanding_first(system, prompt, schema, **kw):
            if schema is legal_problem.ProblemUnderstanding:
                started.set()
            return structured(system, prompt, schema, **kw)

        def decision(_system, _messages, schema, **_kw):
            self.assertTrue(started.wait(5), "understanding did not start before the turn decision returned")
            return schema.model_validate({"action": "research"})

        def search(_q, **_k):
            return {"results": [{"title": "Law", "url": "https://indiacode.nic.in/handle/1", "content": "Section 12 easement",
                                 "score": 0.9}]}

        history = [{"role": "user", "content": "My neighbour has built a wall across the shared path to my house in Warangal."}]
        with mock.patch.object(legal_problem.llm, "available", return_value=True), \
                mock.patch.object(legal_problem.llm, "structured", side_effect=understanding_first), \
                mock.patch.object(legal_problem.llm, "structured_chat", side_effect=decision):
            out = legal_problem.chat_turn(history, search_fn=search)
        self.assertEqual(out["type"], "answer")
        self.assertEqual([c for c, _ in calls].count("ProblemUnderstanding"), 1)

    def test_greetings_do_not_spend_an_early_understanding_call(self):
        self.assertFalse(legal_problem._likely_research([{"role": "user", "content": "hi", "kind": ""}], True))
        self.assertTrue(legal_problem._likely_research(
            [{"role": "user", "content": "landlord", "kind": ""}, {"role": "assistant", "content": "What happened?", "kind": "ask"},
             {"role": "user", "content": "he wants me out", "kind": ""}], True))


class FriendlyUiMarkupTests(unittest.TestCase):
    """Guards for the usability fixes found in the browser preview (static checks, no server)."""
    STATIC = ROOT / "static"

    def test_signing_in_shows_a_screen_and_has_a_button(self):
        html = (self.STATIC / "staff.html").read_text(encoding="utf-8")
        js = (self.STATIC / "staff.js").read_text(encoding="utf-8")
        self.assertIn('id="signinForm"', html)
        self.assertIn('id="tokenGo"', html)
        self.assertIn('$("#signinForm").addEventListener("submit"', js)
        self.assertIn('tokenInput.value = "mourya";', js)
        self.assertIn('setToken("mourya");', js)
        self.assertIn('$("#signedInTokenHint").classList.add("hidden");', js)
        self.assertIn('id="signedInTokenHint">Demo staff token: mourya', html)
        # the old success path only loaded Today's data and left every panel hidden after a signed-out first load
        self.assertIn('showTab(active && !active.classList.contains("hidden") ? active.dataset.tab : "today")', js)

    def test_do_next_comes_before_the_numbers_and_flow(self):
        html = (self.STATIC / "staff.html").read_text(encoding="utf-8")
        self.assertLess(html.index('id="todoList"'), html.index('id="todayKpis"'))
        self.assertLess(html.index('id="todayKpis"'), html.index('id="pipeline"'))

    def test_staff_tab_bar_styles_target_the_real_nav(self):
        css = (self.STATIC / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="portalTabs"', (self.STATIC / "staff.html").read_text(encoding="utf-8"))
        self.assertIn("nav#portalTabs", css)
        self.assertNotIn('nav[aria-label="Staff screens"]', css)

    def test_every_landing_door_has_a_visible_button(self):
        html = (self.STATIC / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('class="door-go"'), 3)
        self.assertEqual(html.count('class="door-who"'), 3)


@unittest.skipUnless(importlib.util.find_spec("sqlalchemy"), "sqlalchemy not installed")
class SchemaOnFirstOpenTests(unittest.TestCase):
    def test_a_database_made_only_by_create_all_is_migrated_on_first_connect(self):
        from nyayavedika import db as sa_db
        old = config.DATABASE_URL
        try:
            sa_db.reset_engine_for_tests(f"sqlite:///{tempfile.mkdtemp()}/narrow.db")
            sa_db.engine()   # the app's create_all(): the old narrow `cases` table, no `source` column
            with store.connect() as s:
                self.assertIn("source", s.columns("cases"))
                self.assertEqual(staff_api.case_sources(s), {})       # the query behind GET /api/alerts
                self.assertEqual(staff_api.alerts(s, "all"), {"alerts": []})
        finally:
            sa_db.reset_engine_for_tests(old)


HAS_SERVER_DEPS = all(importlib.util.find_spec(m) for m in ("fastapi", "httpx", "sqlalchemy", "langgraph"))


@unittest.skipUnless(HAS_SERVER_DEPS, "fastapi / httpx / sqlalchemy / langgraph not installed")
class StaticDeliveryTests(unittest.TestCase):
    def test_versioned_assets_are_cacheable_and_responses_are_compressed(self):
        from fastapi.testclient import TestClient
        import server
        client = TestClient(server.app)
        r = client.get("/static/styles.css?v=9", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("max-age", r.headers["cache-control"])
        self.assertEqual(r.headers.get("content-encoding"), "gzip")
        self.assertEqual(client.get("/static/styles.css").headers["cache-control"], "no-cache")


if __name__ == "__main__":
    unittest.main()
