import json
import time
import unittest
import unicodedata
from pathlib import Path
from tempfile import TemporaryDirectory

from lifemate.agent import LocalBackend, ToolProtocol, ToolRuntime, JazTrace
from lifemate.evaluate import score_calls, token_f1, maximum_matches, match_value, evaluate_run
import jaz


TOOLS = {"calendar.list_events": {"parameters": {"type": "object", "properties": {}}}}
CALL = {"name": "calendar.list_events", "arguments": {}}


class ScoringTests(unittest.TestCase):
    def test_hash_gate(self):
        self.assertEqual(score_calls([CALL], [CALL], False, TOOLS)["score"], 0)

    def test_duplicate_calls(self):
        result = score_calls([CALL, CALL], [CALL], True, TOOLS)
        self.assertEqual((result["matched"], result["unmatched"]), (1, 1))
        self.assertAlmostEqual(result["score"], 2 / 3)

    def test_rejected_call_is_unmatched(self):
        self.assertEqual(score_calls([CALL], [CALL], True, TOOLS, [False])["score"], 0)

    def test_empty_gold_special_case(self):
        self.assertEqual(score_calls([], [], False, TOOLS)["score"], 1)
        self.assertEqual(score_calls([CALL], [], True, TOOLS)["score"], 0)

    def test_maximum_matching_not_greedy(self):
        self.assertEqual(maximum_matches([[0, 1], [0]], 2), 2)

    def test_fuzzy_strict_threshold(self):
        self.assertEqual(token_f1("a b c d", "a b c x y z"), 0.6)
        self.assertFalse(match_value("a b c d", "a b c x y z", {"x-match": "fuzzy"}))
        self.assertTrue(match_value("a b c d", "a b c x", {"x-match": "fuzzy"}))

    def test_unicode_nfc_and_lowercase(self):
        self.assertEqual(token_f1("CÀ PHÊ", unicodedata.normalize("NFD", "cà phê")), 1)

    def test_argument_exactness(self):
        self.assertFalse(match_value(True, 1, {}))
        self.assertFalse(match_value(["a", "b"], ["b", "a"], {"type": "array"}))
        self.assertFalse(match_value({"x": 1, "extra": 2}, {"x": 1}, {}))

    def test_incomplete_run_cannot_shrink_scoring_denominator(self):
        with TemporaryDirectory() as folder:
            run = Path(folder)
            (run / "metadata.json").write_text(json.dumps({"sample_ids": ["a", "b"]}))
            (run / "submission.jsonl").write_text(json.dumps({"id": "a"}) + "\n")
            with self.assertRaisesRegex(ValueError, "không thu nhỏ N"):
                evaluate_run(Path("."), "train", run)


class MemoryTrace:
    def __init__(self):
        self.events = []
    def write(self, event, **payload):
        self.events.append({"event": event, **payload})


class FakeEnv:
    def __init__(self):
        self.calls = []
    def call(self, name, arguments):
        self.calls.append({"name": name, "arguments": arguments})
        if name == "sys.ask_missing_info":
            return {"ok": True, "waiting_for_user": True}
        return {"ok": False, "error": "Test SDK error"}


class ScriptedModel:
    def __init__(self):
        self.messages = []
    def generate(self, messages, tools, **kwargs):
        self.messages.append(messages)
        if len(self.messages) == 1:
            calls = [CALL]
        else:
            assert any(m["role"] == "tool" and "Test SDK error" in m["content"] for m in messages)
            calls = [{"name": "sys.ask_missing_info", "arguments": {
                "tool_name": "reminders.create", "params": ["time"]}}]
        return {"raw_text": "scripted unit-test response", "assistant_text": "scripted",
                "tool_calls": calls, "content": "", "parse_error": None}


class JazIntegrationTests(unittest.TestCase):
    def test_jaz_loop_returns_error_to_model_and_stops_on_wait(self):
        env, trace, model = FakeEnv(), MemoryTrace(), ScriptedModel()
        deadline = time.monotonic() + 30
        backend = LocalBackend(model, [], deadline, trace)
        runtime = ToolRuntime(env, deadline, trace)
        messages = [{"role": "user", "content": "unit test"}]
        with JazTrace(trace), jaz.ConfigOverride(
            llm=backend, repl=runtime, protocol=ToolProtocol(messages)
        ):
            result = jaz.invoke(request="unit test")
        self.assertEqual(result["status"], "waiting_for_user")
        self.assertEqual(len(env.calls), 2)
        self.assertEqual(backend.calls, 2)
        self.assertTrue(any(e.get("name") == "LLMQueryEnter" for e in trace.events))

    def test_runtime_does_not_execute_python(self):
        runtime = ToolRuntime(FakeEnv(), time.monotonic() + 30, MemoryTrace())
        with self.assertRaises(json.JSONDecodeError):
            runtime.exec({}, "raise RuntimeError('python code')", "0")


if __name__ == "__main__":
    unittest.main()
