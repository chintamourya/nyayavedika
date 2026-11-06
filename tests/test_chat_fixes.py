"""Regression tests for the Nyaya Mitra chat failures seen on 5 Nov 2026 (schema echo, raw JSON, repeated questions,
murder treated as a 7-year offence) and for the lighter cause-list publish."""
import json
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nyayavedika import config, llm, store, triage  # noqa: E402
from nyayavedika.agents import front_door  # noqa: E402
from nyayavedika.agents import tools as T  # noqa: E402
from nyayavedika.models import AgentStep  # noqa: E402
import test_agent_resilience as R  # noqa: E402


class SchemaTests(unittest.TestCase):
    def test_agent_step_schema_has_nothing_a_small_model_can_echo(self):
        schema = AgentStep.model_json_schema()
        self.assertNotIn("description", schema)
        self.assertTrue(all("description" not in p for p in schema["properties"].values()))
        self.assertEqual(schema["required"], ["action"])

    def test_react_rules_show_a_real_example(self):
        from nyayavedika.agents.react import REACT_RULES
        text = REACT_RULES.format(tools="T", max_steps=8)
        self.assertIn('"action": "ask_user"', text)


class MurderTests(unittest.TestCase):
    def test_charge_words_and_sections(self):
        self.assertTrue(triage.charge_is_life_or_death("jailed for false case of murder"))
        self.assertTrue(triage.charge_is_life_or_death("", "IPC", "302"))
        self.assertTrue(triage.charge_is_life_or_death("", "BNS", "103"))
        self.assertFalse(triage.charge_is_life_or_death("theft"))
        self.assertFalse(triage.charge_is_life_or_death("", "NI Act", "138"))

    def test_user_given_seven_years_does_not_override_a_murder_charge(self):
        out = T._check_undertrial_release("2026-11-04", 7, True, offence="false case of murder")
        self.assertFalse(out["applicable"])
        self.assertIn("life imprisonment", out["reason"])

    def test_case_with_murder_section_is_not_release_checked(self):
        case = {"accused_in_custody": True, "custody_since": "2020-01-01", "max_sentence_years": 7,
                "act": "BNS", "section": "103", "first_time_offender": True}
        self.assertIsNone(triage.undertrial_release_check(case, date(2026, 11, 5)))

    def test_theft_still_checked(self):
        out = T._check_undertrial_release("2023-01-01", 3, True, offence="theft")
        self.assertTrue(out["applicable"])
        self.assertTrue(out["eligible"])


class FrontDoorTests(unittest.TestCase):
    def test_murder_flow_asks_nothing_more_and_is_plain_text(self):
        r = front_door.FrontDoor("citizen").handle("I was jailed for a false case of murder")
        self.assertIn("does not apply", r["reply"])
        self.assertFalse(r["state"].get("awaiting"))
        self.assertNotIn("{", r["reply"])

    def test_typo_first_offence(self):
        self.assertTrue(front_door.extract_facts("firt offence")["first_time_offender"])


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.old_db = config.DATABASE_URL
        config.DATABASE_URL = f"sqlite:///{tempfile.mkdtemp()}/t.db"
        store.prepare_database()
        llm.set_backend(R.Failing())
        with mock.patch.dict(sys.modules, R._stub_langgraph()):
            from nyayavedika.agents.assistants import offline_turn
            from nyayavedika.agents.react import build_react_agent
            self.graph = build_react_agent("x", T.tools_for("citizen"), None, offline_turn("citizen"), role="citizen",
                                           intent_fn=lambda m, f: front_door.pick_tools(m, "citizen", f))

    def tearDown(self):
        llm.set_backend(None)
        config.DATABASE_URL = self.old_db

    def test_json_tool_result_is_never_shown_to_a_citizen(self):
        steps = [{"thought": "t", "action": "check_undertrial_release", "input": {},
                  "observation": json.dumps({"applicable": True, "custody_days": 1, "threshold_days": 851})}]
        out = self.graph.nodes["agent"]({"messages": [{"role": "user", "content": "my brother is in jail since March 2022 for theft"}],
                                         "steps": steps, "allowed": ["check_undertrial_release"]})
        self.assertNotIn('"applicable"', out["final"])
        self.assertNotIn("threshold_days", out["final"])

    def test_guide_reads_earlier_answers_instead_of_asking_again(self):
        msgs = [{"role": "user", "content": "my brother has been in jail since March 2022 for theft"},
                {"role": "assistant", "content": "Which state and district are you in?"},
                {"role": "user", "content": "telangana, warangal. it is his first offence"}]
        out = self.graph.nodes["agent"]({"messages": msgs, "steps": [], "allowed": None})
        self.assertNotIn("first offence?", out["final"].lower())
        self.assertNotIn("since when", out["final"].lower())
        self.assertIn("Sec. 479", out["final"])


if __name__ == "__main__":
    unittest.main()
