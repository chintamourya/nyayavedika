"""Agent flow over HTTP with a scripted model (no keys, no network):
attached files are always read, a question the agent asked is answered by the next message, an unknown tool
never leaks the model's reasoning, Yes/No is offered only for confirmations, sessions are counted once.
    python -m unittest tests.test_agent_flow
"""
import importlib.util
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import tempfile
import unittest
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

    def chat(self, message, thread=None, role="citizen"):
        return self.c.post("/api/agent/chat", json={"message": message, "thread_id": thread},
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


if __name__ == "__main__":
    unittest.main()
