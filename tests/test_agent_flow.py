"""Agent flow over HTTP with a scripted model (no keys, no network):
attached files are always read, a question the agent asked is answered by the next message, an unknown tool
never leaks the model's reasoning, Yes/No is offered only for confirmations, sessions are counted once.
    python -m unittest tests.test_agent_flow
"""
import importlib.util
import json
import os
import re
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import config, llm  # noqa: E402

_OLD_INLINE = config.INLINE_WORKER


def setUpModule():       # scoped to this module: a global setting at import would leak into the other test files
    config.INLINE_WORKER = False


def tearDownModule():
    config.INLINE_WORKER = _OLD_INLINE


HAS_DEPS = all(importlib.util.find_spec(m) for m in ("fastapi", "httpx", "sqlalchemy", "langgraph", "multipart"))
TOK = {"staff": "af-staff", "lawyer": "af-lawyer", "citizen": "af-citizen"}


class Scripted:
    """AgentStep answers come from a queue; every other schema gets an empty (valid) object."""

    def __init__(self, steps=()):
        self.q, self.prompts = list(steps), []

    def structured(self, model, system, messages, schema):
        if schema.__name__ == "AgentStep":
            self.prompts.append(messages[-1]["content"])
            return self.q.pop(0)
        if schema.__name__ == "LanguageRewrite":
            sources = json.loads(messages[-1]["content"])
            return {"translations": ["हिंदी में उत्तर। " + " ".join(re.findall(r"\d+(?:[./-]\d+)*", source))
                                    for source in sources]}
        if schema.__name__ == "DocTypeGuess":
            return {"doc_type": "fir"}
        return {} if schema.__name__ != "IntentPick" else {"tools": []}

    def text(self, model, system, messages):
        self.prompts.append(messages[-1]["content"])
        return "Fallback answer written from the tool results."


@unittest.skipUnless(HAS_DEPS, "needs fastapi, httpx, sqlalchemy, langgraph, python-multipart")
class AgentFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from nyayavedika import db
        cls.old = (config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER, config.DEMO_TOKEN_CITIZEN, config.STORAGE_DIR)
        tmp = tempfile.mkdtemp()
        config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER, config.DEMO_TOKEN_CITIZEN = TOK.values()
        config.STORAGE_DIR = f"{tmp}/storage"
        db.reset_engine_for_tests(f"sqlite:///{tmp}/af.db")
        import server
        cls.ctx = TestClient(server.app)
        cls.c = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)
        config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER, config.DEMO_TOKEN_CITIZEN, config.STORAGE_DIR = cls.old

    def tearDown(self):
        llm.set_backend(None)

    def chat(self, message, thread=None, role="citizen", language=""):
        return self.c.post("/api/agent/chat", json={"message": message, "thread_id": thread, "language": language},
                           headers={"Authorization": f"Bearer {TOK[role]}"}).json()

    def attach(self, names, message="what does this say?", thread=None, role="citizen"):
        files = [("files", (n, (ROOT / "sample_docs" / n).read_bytes())) for n in names]
        return self.c.post("/api/agent/chat/files", files=files, data={"message": message, "thread_id": thread or ""},
                           headers={"Authorization": f"Bearer {TOK[role]}"})

    # ------------------------------------------------------------------ files
    def test_attached_file_is_read_even_if_the_model_never_asks_for_it(self):
        backend = Scripted([{"thought": "t", "action": "final_answer", "final_answer": "It is an FIR about a theft."}])
        llm.set_backend(backend)
        r = self.attach(["fir_01_theft.txt"]).json()
        self.assertEqual(r["reply"].split("\n")[0], "It is an FIR about a theft.")
        self.assertEqual(r["steps"][0]["action"], "analyze_document")
        self.assertIn("fir_01_theft.txt", r["steps"][0]["observation"])
        self.assertIn("analyze_document", backend.prompts[0])                  # the model saw what was read

    def test_wrong_batch_id_from_the_model_is_replaced(self):
        llm.set_backend(Scripted([
            {"thought": "t", "action": "analyze_document", "action_input_json": '{"batch_id": "made-up"}'},
            {"thought": "d", "action": "final_answer", "final_answer": "ok"}]))
        r = self.attach(["fir_01_theft.txt"]).json()
        self.assertTrue(all("No batch" not in s["observation"] for s in r["steps"]))

    def test_same_file_twice_gets_a_summary_both_times(self):
        for _ in range(2):
            r = self.attach(["fir_01_theft.txt"]).json()
            self.assertIn("First Information Report", r["reply"])
            self.assertNotIn("could not be read", r["reply"])

    def test_junk_next_to_a_real_file_is_fine(self):
        files = [("files", ("fir_01_theft.txt", (ROOT / "sample_docs" / "fir_01_theft.txt").read_bytes())),
                 ("files", (".DS_Store", b"\0"))]
        r = self.c.post("/api/agent/chat/files", files=files, data={"message": "read"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("First Information Report", r.json()["reply"])

    def test_too_many_files_is_a_clear_400(self):
        r = self.attach(["fir_01_theft.txt"] * (config.DEMO_MAX_FILES + 1))
        self.assertEqual(r.status_code, 400)
        self.assertIn("files at a time", r.json()["detail"])

    # ------------------------------------------------------------------ questions and answers
    def test_answer_to_a_question_resumes_the_thread(self):
        backend = Scripted([
            {"thought": "need income", "action": "ask_user", "question_for_user": "What is your family income per year?"},
            {"thought": "done", "action": "final_answer", "final_answer": "With that income you are likely eligible."}])
        llm.set_backend(backend)
        first = self.chat("can I get a free lawyer?")
        self.assertEqual(first["question"], "What is your family income per year?")
        self.assertEqual((first["answer_kind"], first["awaiting_confirmation"]), ("text", False))
        second = self.chat("about 80000 a year", first["thread_id"])        # plain /chat, not /resume
        self.assertIn("likely eligible", second["reply"])
        self.assertIn("user answered: about 80000 a year", backend.prompts[1])  # the question was not lost

    def test_selected_language_change_applies_when_resuming_a_question(self):
        backend = Scripted([
            {"thought": "need income", "action": "ask_user", "question_for_user": "What is your family income per year?"},
            {"thought": "done", "action": "final_answer", "final_answer": "Here is your answer."},
        ])
        llm.set_backend(backend)
        first = self.chat("can I get a free lawyer?", language="English")

        second = self.chat("about 80000 a year", first["thread_id"], language="Hindi")

        self.assertEqual(second["reply"], "हिंदी में उत्तर। 15100")
        self.assertIn("Final answers must be in Hindi.", backend.prompts[1])

    def test_selected_hindi_is_used_when_citizen_writes_in_english(self):
        backend = Scripted([{"thought": "done", "action": "final_answer", "final_answer": "Here is your answer."}])
        llm.set_backend(backend)

        response = self.chat("I need help.", language="Hindi")

        self.assertEqual(response["reply"], "हिंदी में उत्तर। 15100")
        self.assertIn("Final answers must be in Hindi.", backend.prompts[0])

    def test_resume_endpoint_without_a_question_acts_as_a_message(self):
        llm.set_backend(Scripted([{"thought": "d", "action": "final_answer", "final_answer": "Hello."}]))
        r = self.c.post("/api/agent/resume", json={"thread_id": "citizen-nothing0000", "answer": "hi"},
                        headers={"Authorization": f"Bearer {TOK['citizen']}"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("Hello.", r.json()["reply"])

    # ------------------------------------------------------------------ model mistakes
    def test_unknown_tool_is_corrected_not_shown(self):
        backend = Scripted([
            {"thought": "SECRET REASONING", "action": "do_magic", "action_input_json": "{}"},
            {"thought": "ok", "action": "final_answer", "final_answer": "Call 15100."}])
        llm.set_backend(backend)
        r = self.chat("help")
        self.assertIn("Call 15100.", r["reply"])
        self.assertNotIn("SECRET REASONING", r["reply"])
        self.assertIn("not a tool you can use", backend.prompts[1])

    def test_empty_final_answer_never_shows_the_reasoning(self):
        llm.set_backend(Scripted([{"thought": "PRIVATE THOUGHT", "action": "final_answer", "final_answer": ""}]))
        r = self.chat("help")
        self.assertNotIn("PRIVATE THOUGHT", r["reply"])
        self.assertIn("Fallback answer", r["reply"])

    def test_answer_under_an_odd_action_name_is_used(self):
        llm.set_backend(Scripted([{"thought": "t", "action": "respond", "final_answer": "Here is the answer."}]))
        self.assertIn("Here is the answer.", self.chat("help")["reply"])

    # ------------------------------------------------------------------ confirmations
    def test_yes_no_only_for_confirmations(self):
        call = {"thought": "send", "action": "request_release_review",
                "action_input_json": '{"custody_since": "2021-01-01", "max_sentence_years": 3}'}
        llm.set_backend(Scripted([call]))
        r = self.chat("my brother is in jail, send it to a lawyer")
        self.assertEqual((r["answer_kind"], r["awaiting_confirmation"]), ("confirm", True))

    def test_offline_custody_question_is_a_text_answer(self):
        r = self.chat("My brother has been in jail for theft.")
        self.assertEqual(r["answer_kind"], "text")                          # "since when?" is typed, not Yes / No
        self.assertFalse(r["awaiting_confirmation"])
        r2 = self.chat("since March 2022", r["thread_id"])
        self.assertEqual(r2["answer_kind"], "yes_no")                       # "first offence? yes / no / not sure"

    # ------------------------------------------------------------------ metrics
    def test_a_session_is_counted_once_not_per_message(self):
        from nyayavedika import db
        before = db.event_totals().get("citizen_session", {}).get("count", 0)
        t = self.chat("What is a Lok Adalat?")["thread_id"]
        for _ in range(3):
            self.chat("and what else?", t)
        after = db.event_totals().get("citizen_session", {}).get("count", 0)
        self.assertEqual(after - before, 1)

    def test_people_reached_is_sessions_only(self):
        from nyayavedika import db, impact
        self.chat("Can I get a free lawyer? I earn 12,000 a month.")
        t = db.event_totals()
        s = impact.summary()
        self.assertEqual(s["people_reached"], t["citizen_session"]["count"])   # checks inside a chat are not added again
        self.assertGreaterEqual(s["legal_aid"]["eligibility_checks"], 1)
        self.assertIn("not unique", s["note"])

    def test_api_feature_usage_records_counts_and_server_time(self):
        from nyayavedika import db, impact
        before = db.event_totals().get("api_usage_citizen_legal_aid_success", {}).get("count", 0)
        response = self.c.get("/api/legal-aid/topics", headers={"Authorization": f"Bearer {TOK['citizen']}"})
        self.assertEqual(response.status_code, 200)
        summary = impact.summary()
        self.assertEqual(summary["api_usage"]["by_door"]["citizen"]["features"]["legal_aid_check"]["successful"], before + 1)
        self.assertGreaterEqual(summary["api_usage"]["total"]["avg_server_ms"], 0)
        self.assertIsNone(impact.api_feature("/api/impact/export.csv"))
        self.assertEqual(impact.api_feature("/api/legal-aid/{request_id}/outcome"), "legal_aid_check")
        self.assertEqual(impact.api_feature("/api/agent/chat", door="citizen"), "citizen_assistant")
        self.assertEqual(impact.api_feature("/api/agent/chat", door="advocate"), "advocate_assistant")
        self.assertEqual(impact.api_feature("/api/agent/chat", door="staff"), "staff_assistant")
        self.assertEqual(impact.api_door("/api/legal-aid/topics", "GET", f"Bearer {TOK['citizen']}", None), "citizen")
        self.assertEqual(impact.api_door("/api/advocate/documents", "POST", f"Bearer {TOK['lawyer']}", None), "advocate")
        self.assertEqual(impact.api_door("/api/cases", "GET", f"Bearer {TOK['staff']}", None), "staff")
        staff_summary = self.c.get("/api/impact", headers={"Authorization": f"Bearer {TOK['staff']}"})
        self.assertEqual(staff_summary.status_code, 200)
        self.assertIn("field_feedback", staff_summary.json())

    def test_api_metrics_count_distinct_browsers_per_door_and_feature(self):
        from nyayavedika import db, impact
        before = db.browser_feature_totals()["by_door_feature"].get("citizen", {}).get("legal_aid_check", 0)
        first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
        headers = {"Authorization": f"Bearer {TOK['citizen']}"}
        for browser_id in (first_id, first_id, second_id):
            response = self.c.get(
                "/api/legal-aid/topics",
                headers={**headers, "X-Anonymous-Browser-ID": browser_id},
            )
            self.assertEqual(response.status_code, 200)
        metrics = impact.demo_summary()["api_usage"]
        row = metrics["by_door"]["citizen"]["features"]["legal_aid_check"]
        self.assertEqual(row["unique_browsers"], before + 2)
        self.assertGreaterEqual(metrics["total"]["unique_browsers"], before + 2)
        self.assertNotIn(first_id, str(metrics))
        self.assertNotIn(second_id, str(metrics))

    def test_public_demo_metrics_endpoint_returns_aggregates_without_auth(self):
        response = self.c.get("/api/demo/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        payload = response.json()
        self.assertIn("reach", payload)
        self.assertIn("door_visits", payload)
        self.assertIn("by_door", payload["api_usage"])
        self.assertIn("by_feature", payload["api_usage"])
        self.assertIn("product", payload)
        self.assertIn("feedback", payload)
        self.assertIn("pilot_comparison", payload)
        self.assertFalse(payload["pilot_comparison"]["available"])
        self.assertIn("unique_browsers", payload["api_usage"]["total"])
        self.assertIn("unique_browsers", payload["api_usage"]["by_door"]["citizen"])
        self.assertIn("random persistent browser identifier", payload["disclaimer"])
        self.assertNotIn("not verified", payload["disclaimer"].lower())
        self.assertNotIn("visitor_hash", str(payload))
        self.assertNotIn("comment", payload["feedback"])
        self.assertNotIn("items", payload)
        self.assertEqual(self.c.get("/api/impact").status_code, 401)
        from scripts import dev_api
        route = next(route for route in dev_api.ROUTES if route[1].match("/api/demo/metrics"))
        self.assertIsNone(route[2])
        self.assertEqual(dev_api.PAGES["/metrics"], "metrics.html")
        page = self.c.get("/metrics")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="metricsContent"', page.text)
        self.assertNotIn("Before / after pilot comparison", page.text)
        self.assertNotIn('id="pilotCards"', page.text)
        self.assertIn("/api/demo/metrics", (ROOT / "static" / "metrics.js").read_text(encoding="utf-8"))
        template = self.c.get("/pilot/template.csv")
        self.assertEqual(template.status_code, 200)
        self.assertIn("text/csv", template.headers["content-type"])
        self.assertIn("manual_status", template.text)

    def test_demo_metrics_includes_anonymized_pilot_comparison_aggregates(self):
        from unittest.mock import patch
        from nyayavedika import impact
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pilot_log.csv"
            path.write_text(
                "case_ref,manual_status,tool_status,lawyer_verdict,manual_minutes,tool_minutes,days_over_limit,application_filed,outcome\n"
                "anon-1,eligible,eligible,eligible,40,20,0,no,none\n"
                "anon-2,not_eligible,needs_review,not_eligible,30,20,0,no,none\n",
                encoding="utf-8",
            )
            with patch.object(impact, "PILOT_LOG_PATH", path):
                response = self.c.get("/api/demo/metrics")
        pilot = response.json()["pilot_comparison"]
        self.assertTrue(pilot["available"])
        self.assertEqual(pilot["cases_screened"], 2)
        self.assertEqual(pilot["precision"], 0.5)
        self.assertEqual(pilot["manual_accuracy"], 1.0)
        self.assertEqual(pilot["accuracy"], 0.5)
        self.assertEqual(pilot["accuracy_comparison_cases"], 2)
        self.assertEqual(pilot["median_minutes_saved"], 15.0)
        self.assertNotIn("anon-1", str(response.json()))

    def test_portal_page_visit_is_counted_without_visitor_identity(self):
        from nyayavedika import db, impact
        before = db.event_totals().get("door_visit_advocate", {}).get("count", 0)
        response = self.c.get("/advocate")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.event_totals()["door_visit_advocate"]["count"], before + 1)
        self.assertEqual(impact.summary()["door_visits"]["by_door"]["advocate"], before + 1)

    def test_automatic_reach_counts_distinct_browsers_across_pages_and_portals(self):
        from nyayavedika import db, impact
        browser_id = str(uuid.uuid4())
        payload = {"browser_id": browser_id}
        self.assertEqual(self.c.post("/api/reach/public", json=payload).status_code, 200)
        self.assertEqual(self.c.post("/api/reach/citizen", json=payload).status_code, 200)
        self.assertEqual(self.c.post("/api/reach/citizen", json=payload).status_code, 200)
        self.assertEqual(self.c.post("/api/reach/advocate", json=payload).status_code, 200)
        reach = impact.summary()["reach"]
        self.assertEqual(reach["unique_browsers"], 1)
        self.assertEqual(reach["public_browsers"], 1)
        self.assertEqual(reach["by_door"], {"citizen": 1, "advocate": 1, "staff": 0})
        self.assertNotEqual(impact.reach_hash(browser_id), browser_id)
        before_feature_visitors = db.browser_feature_totals()["by_door_feature"].get("citizen", {}).get("legal_aid_check", 0)
        db.register_browser_feature(impact.reach_hash(browser_id), "citizen", "legal_aid_check")
        self.assertEqual(self.c.request("DELETE", "/api/reach", json=payload).status_code, 200)
        self.assertEqual(db.reach_totals(), {
            "unique_browsers": 0, "public_browsers": 0, "by_door": {"citizen": 0, "advocate": 0, "staff": 0}
        })
        self.assertEqual(
            db.browser_feature_totals()["by_door_feature"].get("citizen", {}).get("legal_aid_check", 0),
            before_feature_visitors,
        )

    def test_reach_endpoint_rejects_non_uuid(self):
        response = self.c.post("/api/reach/citizen", json={"browser_id": "not-an-id"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
