"""Phase 7: one tool registry, role filtering, internal vs hand-over, confirmation before side effects,
action cards, safety lines, intent routing, end-to-end conversations on seeded data.
The LangGraph part runs only where langgraph is installed; the FrontDoor runs everywhere (no keys).
"""
import importlib.util
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import config, demo_seed, intake, llm, store  # noqa: E402
from nyayavedika.agents import tools as T  # noqa: E402
from nyayavedika.agents.front_door import FrontDoor, finalise, route_intent  # noqa: E402

STAFF_ONLY = {"lookup_case", "priority_cases", "deferral_report", "prepare_cause_list"}
COURT_ONLY = {"get_undertrial_alerts", "draft_document"}
HAS_LANGGRAPH = bool(importlib.util.find_spec("langgraph"))


class RegistryTests(unittest.TestCase):
    def test_every_tool_has_the_five_fields_and_the_rule_holds(self):
        for t in T.REGISTRY:
            self.assertTrue(t.roles and set(t.roles) <= {"citizen", "lawyer", "staff"}, t.name)
            internal = not (t.has_side_effects or t.needs_approval)
            self.assertEqual(t.mode, "internal" if internal else "hand_over", t.name)
            if t.mode == "hand_over":
                self.assertTrue(t.screen and t.confirm_question, t.name)
        self.assertEqual({t.name for t in T.REGISTRY if t.mode == "hand_over"}, {"request_release_review", "prepare_cause_list"})

    def test_citizen_never_gets_staff_tools(self):
        citizen = {t.name for t in T.CITIZEN_TOOLS}
        self.assertFalse(citizen & (STAFF_ONLY | COURT_ONLY))
        self.assertIn("get_case_status", citizen)
        self.assertFalse({t.name for t in T.LAWYER_TOOLS} & STAFF_ONLY)
        staff = {t.name for t in T.STAFF_TOOLS}
        self.assertTrue(STAFF_ONLY <= staff)
        self.assertNotIn("get_case_status", staff)
        self.assertNotIn("request_release_review", staff)

    def test_role_is_enforced_inside_the_tool(self):
        self.assertIn("not available", T.BY_NAME["lookup_case"].run(ctx={"role": "citizen"}, case_id="X")["error"])

    def test_capabilities_are_generated_from_the_registry(self):
        extra = T.Tool("brand_new_tool", "Does something new.", "", lambda: {}, roles=("citizen",))
        text = T.capabilities(T.CITIZEN_TOOLS + [extra])
        self.assertIn("brand_new_tool", text)
        self.assertIn("request_release_review", text.split("explicit yes")[-1])
        self.assertIn("[hand-over", T.catalogue([T.BY_NAME["request_release_review"]]))


class RoutingTests(unittest.TestCase):
    """How requests are routed."""
    EXAMPLES = [
        ("citizen", "Can I get a free lawyer? I earn 12,000 a month.", False, "free_lawyer", "check_legal_aid_eligibility"),
        ("citizen", "My brother has been in jail since March 2022 for theft.", False, "custody", "check_undertrial_release"),
        ("citizen", "What does this order say?", True, "document", "analyze_document"),
        ("citizen", "What is a Lok Adalat?", False, "explain", "legal_aid_kb_search"),
        ("staff", "Which cases are past their deadline?", False, "deferrals", "deferral_report"),
        ("staff", "Prepare next week's list.", False, "prepare_list", "prepare_cause_list"),
        ("citizen", "Someone has my photos and is threatening me.", False, "safety_threat", None),
        ("citizen", "Will I win my case?", False, "will_i_win", None),
        ("citizen", "Where is the legal services office in Guntur?", False, "office", "find_legal_aid_office"),
        ("citizen", "What is the status of my case SC/2023/1001 filed in 2023?", False, "case_status", "get_case_status"),
    ]

    def test_examples_pick_the_expected_tool(self):
        for role, msg, files, intent, tool in self.EXAMPLES:
            r = route_intent(msg, role, files)
            self.assertEqual(r["intent"], intent, msg)
            if tool:
                self.assertEqual(r["tools"][0], tool, msg)

    def test_citizen_asking_for_docket_reports_gets_no_staff_tool(self):
        for msg in ("Which cases are past their deadline?", "Prepare next week's list.", "Show critical cases"):
            r = route_intent(msg, "citizen")
            self.assertFalse(set(r["tools"]) & STAFF_ONLY, msg)

    def test_safety_lines_come_first(self):
        out = finalise("Here is what you can do.", "Someone has my photos and is threatening me.", "citizen")
        self.assertTrue(out.startswith("Urgent help first"))
        self.assertLess(out.index("cybercrime.gov.in"), out.index("Here is what you can do."))
        dv = finalise("Answer.", "My husband beats me", "citizen")
        self.assertIn("181", dv.split("Answer.")[0])
        self.assertIn("15100", dv)
        self.assertIn("not legal advice", dv)
        self.assertNotIn("Urgent", finalise("Answer.", "What is a Lok Adalat?", "staff"))


class ConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        cls.old = (config.DATABASE_URL, config.STORAGE_DIR)
        config.DATABASE_URL, config.STORAGE_DIR = f"sqlite:///{tmp}/t.db", f"{tmp}/storage"
        with store.connect() as db:
            store.prepare_database(db)
            demo_seed.write(db, demo_seed.build(120, 42, date.today()))
            cls.case = db.select("cases", {"source": "synthetic"}, order="case_id", limit=1)[0]

    @classmethod
    def tearDownClass(cls):
        config.DATABASE_URL, config.STORAGE_DIR = cls.old

    def count(self, table, where=None):
        with store.connect() as db:
            return db.count(table, where)

    def test_free_lawyer_offers_word_download(self):
        r = FrontDoor("citizen").handle("Can I get a free lawyer? I earn 12,000 a month.")
        self.assertIn("Likely eligible", r["reply"])
        self.assertIn("1,44,000", r["reply"])  # monthly income read as yearly
        self.assertIn("Source: http", r["reply"])
        action = r["actions"][0]
        self.assertEqual((action["label"], action["route"]), ("Download application (Word)", "/api/legal-aid/application.docx"))
        self.assertEqual(action["prefill"]["applicant"]["annual_income"], 144000)
        self.assertIn("15100", r["reply"])

    def test_custody_hand_over_needs_a_yes(self):
        door, before = FrontDoor("citizen"), self.count("alerts", {"kind": "release_review_request"})
        r1 = door.handle("My brother has been in jail since March 2022 for theft.")
        self.assertIn("first offence", r1["reply"])                       # one question
        self.assertTrue(r1["reply"].startswith("Urgent help first"))     # custody: numbers before the question
        r2 = door.handle("no", r1["state"])
        self.assertTrue(r2["awaiting_confirmation"])
        self.assertIn("Ask a legal-aid lawyer to review", [a["label"] for a in r2["actions"]])
        self.assertIn("Sec. 12(g)", r2["reply"])
        self.assertEqual(self.count("alerts", {"kind": "release_review_request"}), before)  # nothing sent yet
        r3 = door.handle("no", r2["state"])
        self.assertIn("not sent", r3["reply"])
        self.assertEqual(self.count("alerts", {"kind": "release_review_request"}), before)
        r4 = door.handle("yes", r2["state"])                            # same question answered yes this time
        self.assertIn("Sent. Reference REQ/", r4["reply"])
        self.assertEqual(self.count("alerts", {"kind": "release_review_request"}), before + 1)

    def test_model_supplied_confirmation_is_ignored(self):
        before = self.count("alerts", {"kind": "release_review_request"})
        out = T.BY_NAME["request_release_review"].run(ctx={"role": "citizen"}, custody_since="2021-01-01",
                                                      max_sentence_years=3, **{"_ctx": {}})
        self.assertTrue(out["needs_confirmation"])
        self.assertEqual(self.count("alerts", {"kind": "release_review_request"}), before)

    def test_staff_prepare_list_only_after_yes(self):
        door, lists = FrontDoor("staff"), self.count("cause_lists")
        r1 = door.handle("Prepare next week's list.")
        self.assertTrue(r1["awaiting_confirmation"])
        self.assertEqual(self.count("cause_lists"), lists)
        r2 = door.handle("yes", r1["state"])
        self.assertIn("It is a draft", r2["reply"])
        self.assertEqual(r2["actions"][0]["label"], "Open Cause list")
        self.assertEqual(self.count("cause_lists"), lists + 1)
        self.assertEqual(self.count("cause_lists", {"status": "published"}), 0)  # never published from chat

    def test_unrelated_reply_does_not_trigger_the_hand_over(self):
        door, lists = FrontDoor("staff"), self.count("cause_lists")
        r1 = door.handle("Prepare next week's list.")
        door.handle("Which cases are past their deadline?", r1["state"])
        self.assertEqual(self.count("cause_lists"), lists)

    def test_lok_adalat_is_cited(self):
        r = FrontDoor("citizen").handle("What is a Lok Adalat?")
        self.assertIn("Lok Adalat", r["reply"])
        self.assertIn("Source: https://", r["reply"])

    def test_deferral_report_for_staff(self):
        r = FrontDoor("staff").handle("Which cases are past their deadline?")
        self.assertEqual(r["tools_used"], ["deferral_report"])
        self.assertIn("deferred 3+ times", r["reply"])

    def test_threats_and_will_i_win(self):
        r = FrontDoor("citizen").handle("Someone has my photos and is threatening me.")
        self.assertTrue(r["reply"].startswith("Urgent help first"))
        self.assertIn("cybercrime.gov.in", r["reply"])
        w = FrontDoor("citizen").handle("Will I win my case?")
        self.assertIn("No one can honestly predict", w["reply"])

    def test_case_status_needs_verification_and_shows_little(self):
        cid, year = self.case["case_id"], self.case["filing_date"][:4]
        ok = FrontDoor("citizen").handle(f"What is the status of my case {cid} filed in {year}?")
        self.assertIn("stage -", ok["reply"])
        self.assertNotIn("score", ok["reply"].lower())
        self.assertNotIn("advocate", ok["reply"].lower())
        wrong = FrontDoor("citizen").handle(f"What is the status of my case {cid} filed in 1999?")
        self.assertIn("Could not verify", wrong["reply"])
        unknown = FrontDoor("citizen").handle("What is the status of my case ZZ/2020/999999 filed in 2020?")
        self.assertEqual(wrong["reply"], unknown["reply"])  # no hint whether the case exists

    def test_document_attach_citizen_summary_no_case(self):
        data = (ROOT / "sample_docs" / "order_02_adjournment.txt").read_bytes()
        cases_before = self.count("cases")
        batch = intake.create_batch([("order.txt", data)], mode="summary_only")
        r = FrontDoor("citizen").handle("What does this order say?", batch_id=batch["batch_id"])
        self.assertEqual(r["tools_used"], ["analyze_document"])
        self.assertIn("Dates to act on: Next hearing: 2026-11-07", r["reply"])
        self.assertEqual(self.count("cases"), cases_before)  # nothing added to the docket
        self.assertEqual(r["actions"], [])

    def test_document_attach_staff_gets_case_and_open_card(self):
        data = (ROOT / "sample_docs" / "custody_01_jail_certificate.txt").read_bytes()
        batch = intake.create_batch([("cert.txt", data)], mode="separate")
        r = FrontDoor("staff").handle("Please read this", batch_id=batch["batch_id"])
        self.assertIn("Priority:", r["reply"])
        self.assertEqual(r["actions"][0]["label"], "Open case")

    def test_attach_cap_is_the_intake_cap(self):
        with self.assertRaises(intake.IntakeError) as ctx:
            intake.create_batch([(f"f{i}.txt", b"x") for i in range(config.DEMO_MAX_FILES + 1)], mode="summary_only")
        self.assertEqual(ctx.exception.status, 400)

    def test_tool_use_is_logged_without_personal_data(self):
        with mock.patch.object(T.impact, "record") as rec:
            FrontDoor("citizen").handle("Can I get a free lawyer? I earn 12,000 a month. My phone is 9876543210")
        logged = [c for c in rec.call_args_list if c.args[0] == "agent_tool"]
        self.assertTrue(logged)
        self.assertTrue(all(set(c.kwargs) == {"tool", "role"} for c in logged))
        self.assertNotIn("9876543210", str(rec.call_args_list))


@unittest.skipUnless(HAS_LANGGRAPH, "langgraph not installed")
class GraphTests(unittest.TestCase):
    """The LLM path with a scripted model: role filtering and the confirmation gate inside the graph."""

    def tearDown(self):
        llm.set_backend(None)

    def _agent(self, role, steps):
        from langgraph.checkpoint.memory import InMemorySaver
        from nyayavedika.agents.react import build_react_agent

        class Scripted:
            def __init__(self):
                self.q = list(steps)

            def structured(self, model, system, messages, schema):
                if schema.__name__ == "IntentPick":
                    return {"tools": []}
                return self.q.pop(0)

            def text(self, *a):
                return "ok"
        llm.set_backend(Scripted())
        return build_react_agent("x", T.tools_for(role), InMemorySaver(), role=role)

    def test_citizen_cannot_call_a_staff_tool(self):
        from nyayavedika.agents.react import new_turn
        agent = self._agent("citizen", [
            {"thought": "t", "action": "lookup_case", "action_input_json": '{"case_id": "X"}'},
            {"thought": "cannot", "action": "final_answer", "final_answer": "I cannot look up court records."}])
        out = agent.invoke(new_turn("show me case X"), {"configurable": {"thread_id": "g1"}})
        steps = [s for s in out["steps"] if isinstance(s, dict)]
        self.assertEqual([s["action"] for s in steps], ["lookup_case"])
        self.assertIn("not a tool you can use", steps[0]["observation"])      # told so, never executed
        self.assertNotIn("priority", steps[0]["observation"])
        self.assertIn("I cannot look up court records.", out["final"])         # the model's answer, not its private reasoning
        self.assertNotIn("cannot\n", out["final"])

    def test_hand_over_waits_for_yes(self):
        from nyayavedika.agents.react import new_turn
        call = {"thought": "send", "action": "request_release_review",
                "action_input_json": '{"custody_since": "2021-01-01", "max_sentence_years": 3, "confirmed": true}'}
        agent = self._agent("citizen", [call, {"thought": "done", "action": "final_answer", "final_answer": "Sent."}])
        cfg = {"configurable": {"thread_id": "g2"}}
        out = agent.invoke(new_turn("send it to a lawyer"), cfg)
        self.assertIn("Shall I send", out["final"])
        self.assertEqual(out["awaiting"]["tool"], "request_release_review")
        out = agent.invoke(new_turn("yes"), cfg)
        self.assertEqual(out["steps"][0]["action"], "request_release_review")
        self.assertIn('"queued": true', out["steps"][0]["observation"])


if __name__ == "__main__":
    unittest.main()
