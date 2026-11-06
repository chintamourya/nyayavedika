"""Agent & infrastructure tests with a scripted LLM backend (no network, no API keys).

LangGraph / SQLAlchemy tests are skipped when those packages are not installed.
"""
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import llm, ocr  # noqa: E402
from nyayavedika.models import AgentStep, CaseAnalysis  # noqa: E402

try:
    import langgraph  # noqa: F401
    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False
try:
    import sqlalchemy  # noqa: F401
    HAS_SQLA = True
except ImportError:
    HAS_SQLA = False


class ScriptedBackend:
    """Returns queued structured outputs in order; records prompts for assertions."""

    def __init__(self, structured=None, texts=None):
        self.structured_q = list(structured or [])
        self.text_q = list(texts or [])
        self.seen = []

    def structured(self, model, system_prompt, messages, schema):
        self.seen.append(messages[-1]["content"])
        return self.structured_q.pop(0)

    def text(self, model, system_prompt, messages):
        self.seen.append(messages[-1]["content"])
        return self.text_q.pop(0) if self.text_q else "ok"


class LLMLayerTests(unittest.TestCase):
    def tearDown(self):
        llm.set_backend(None)

    def test_offline_status(self):
        llm.set_backend(None)
        self.assertFalse(llm.available())

    def test_structured_validates_and_redacts(self):
        backend = ScriptedBackend(structured=[{"thought": "t", "action": "final_answer", "final_answer": "hi"}])
        llm.set_backend(backend)
        step = llm.structured("sys", "my number is 9876543210", AgentStep)
        self.assertIsInstance(step, AgentStep)
        self.assertIn("[PHONE]", backend.seen[0])
        self.assertNotIn("9876543210", backend.seen[0])

    def test_extract_json(self):
        self.assertEqual(llm.extract_and_parse_json('```json\n{"a": 1}\n```'), {"a": 1})


class CheckpointConfigTests(unittest.TestCase):
    def test_dsn_derived_from_database_url(self):
        from nyayavedika import config
        from nyayavedika.agents.checkpoint import checkpoint_dsn
        old = (config.DATABASE_URL, config.CHECKPOINT_DB_URI)
        try:
            config.CHECKPOINT_DB_URI = ""
            config.DATABASE_URL = "postgresql+pg8000://u:p@db:5432/nyayavedika"
            self.assertEqual(checkpoint_dsn(), "postgresql://u:p@db:5432/nyayavedika")
            config.DATABASE_URL = "sqlite:///x.db"
            self.assertEqual(checkpoint_dsn(), "")
            config.CHECKPOINT_DB_URI = "postgresql://other/db"
            self.assertEqual(checkpoint_dsn(), "postgresql://other/db")
        finally:
            config.DATABASE_URL, config.CHECKPOINT_DB_URI = old


class OCRHeuristicTests(unittest.TestCase):
    def test_sparse_page_needs_ocr(self):
        self.assertTrue(ocr.page_needs_ocr("12", 595, 842))
        self.assertFalse(ocr.page_needs_ocr("This is a dense native text page. " * 60, 595, 842))

    def test_text_file_passthrough(self):
        pages = ocr.extract("hello court".encode(), "a.txt")
        self.assertEqual(pages[0]["source"], "text")


@unittest.skipUnless(HAS_LANGGRAPH, "langgraph not installed")
class ReactAgentTests(unittest.TestCase):
    def tearDown(self):
        llm.set_backend(None)

    def test_tool_then_clarify_then_answer(self):
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.types import Command
        from nyayavedika.agents.react import build_react_agent, new_turn
        from nyayavedika.agents.tools import CITIZEN_TOOLS

        llm.set_backend(ScriptedBackend(structured=[
            {"thought": "need release calc", "action": "check_undertrial_release",
             "action_input_json": '{"custody_since": "2022-01-01", "max_sentence_years": 3}'},
            {"thought": "need income", "action": "ask_user", "question_for_user": "What is your family income?"},
            {"thought": "done", "action": "final_answer", "final_answer": "Eligible for release; apply via DLSA."},
        ]))
        agent = build_react_agent("You help.", CITIZEN_TOOLS, InMemorySaver())
        cfg = {"configurable": {"thread_id": "t1"}}
        out = agent.invoke(new_turn("brother in jail since 2022 for theft"), cfg)
        self.assertIn("__interrupt__", out)
        self.assertEqual(out["steps"][0]["action"], "check_undertrial_release")
        self.assertIn('"eligible": true', out["steps"][0]["observation"])
        out = agent.invoke(Command(resume="about 80,000 a year"), cfg)
        self.assertEqual(out["final"], "Eligible for release; apply via DLSA.")
        self.assertEqual([s["action"] for s in out["steps"]], ["check_undertrial_release", "ask_user"])

    def test_offline_fallback(self):
        from langgraph.checkpoint.memory import InMemorySaver
        from nyayavedika.agents.assistants import _citizen_offline
        from nyayavedika.agents.react import build_react_agent, new_turn
        from nyayavedika.agents.tools import CITIZEN_TOOLS
        llm.set_backend(None)
        agent = build_react_agent("x", CITIZEN_TOOLS, InMemorySaver(), _citizen_offline)
        out = agent.invoke(new_turn("My 67 year old father is in judicial custody since March 2022 in a theft case"),
                           {"configurable": {"thread_id": "t2"}})
        self.assertIn("Sec. 479 BNSS", out["final"])

    def test_offline_cyber_harassment_gives_immediate_steps(self):
        from langgraph.checkpoint.memory import InMemorySaver
        from nyayavedika.agents.assistants import _citizen_offline
        from nyayavedika.agents.react import build_react_agent, new_turn
        from nyayavedika.agents.tools import CITIZEN_TOOLS
        llm.set_backend(None)
        agent = build_react_agent("x", CITIZEN_TOOLS, InMemorySaver(), _citizen_offline)
        out = agent.invoke(new_turn("Someone on Instagram is harassing me and morphed my photos"),
                           {"configurable": {"thread_id": "t-cyber"}})
        self.assertIn("cybercrime.gov.in", out["final"])
        self.assertIn("screenshots", out["final"])
        self.assertIn("112", out["final"])
        self.assertNotIn("tell me more", out["final"].lower())


@unittest.skipUnless(HAS_LANGGRAPH and HAS_SQLA, "langgraph / sqlalchemy not installed")
class WorkflowGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from nyayavedika import db, sample_data, triage
        cls.tmp = tempfile.mkdtemp()
        db.reset_engine_for_tests(f"sqlite:///{cls.tmp}/t.db")
        cases = sample_data.generate(200)
        db.upsert_cases(cases, {r["case_id"]: r for r in triage.triage_all(cases)})

    def tearDown(self):
        llm.set_backend(None)

    def test_document_analyst_verify_loop(self):
        from nyayavedika.agents import document_analyst
        text = (ROOT / "data" / "sample_judgment.txt").read_text(encoding="utf-8")
        bad = CaseAnalysis(timeline=[{"date": "01.01.1999", "event": "invented"}], outcome="Partly allowed").model_dump()
        good = CaseAnalysis(timeline=[{"date": "05.06.2016", "event": "quarrel"}], outcome="Partly allowed").model_dump()
        ok_report = {"checks": [], "overall_grounded": True, "corrections": []}
        llm.set_backend(ScriptedBackend(structured=[bad, ok_report, good, ok_report]))
        r = document_analyst.analyze("doc-test", "j.txt", text=text)
        self.assertEqual(r["analysis"]["timeline"][0]["date"], "05.06.2016")
        self.assertTrue(any("2 " in t or "attempt 2" in t for t in r["trace"]))

    def test_undertrial_watch_requires_approval(self):
        from langgraph.types import Command
        from nyayavedika import db
        from nyayavedika.agents import undertrial_watch
        cfg = {"configurable": {"thread_id": "w1"}}
        out = undertrial_watch.graph().invoke({"drafts": []}, cfg)
        self.assertIn("__interrupt__", out)
        pending = db.fetch(db.alerts, where=db.alerts.c.status == "pending")
        self.assertTrue(pending)
        decisions = {str(pending[0]["id"]): {"approve": True}}
        undertrial_watch.graph().invoke(Command(resume=decisions), cfg)
        self.assertEqual(db.fetch(db.alerts, where=db.alerts.c.id == pending[0]["id"])[0]["status"], "approved")

    def test_registry_pipeline(self):
        from langgraph.types import Command
        from nyayavedika.agents import registry
        cfg = {"configurable": {"thread_id": "r1"}}
        out = registry.graph().invoke({"start_date": "2026-10-26", "days": 3}, cfg)
        self.assertIn("__interrupt__", out)
        self.assertEqual(out["plan"]["metrics"]["advocate_conflicts"], 0)
        registry.graph().invoke(Command(resume={"approve": True}), cfg)


if __name__ == "__main__":
    unittest.main()
