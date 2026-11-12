"""Selected runtime boundaries, with the real SDK and scripted model/ASR responses."""

import copy
import io
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock, patch

from lifemate import deploy
from lifemate.data import samples
from lifemate.llamacpp_client import LlamaCpp, ResponseFormatError
from lifemate.trace import Trace


DATA = Path(os.environ["LIFEMATE_TEST_DATA"]) if "LIFEMATE_TEST_DATA" in os.environ else Path(__file__).resolve().parents[2] / "train+public_test/train+public_test"


class ASR:
    def __init__(self):
        self.paths = []

    def transcribe(self, path, *, deadline):
        self.paths.append(path)
        assert time.monotonic() < deadline
        return "Kiểm tra số dư ví của tôi."


def backend(replies):
    client = LlamaCpp.__new__(LlamaCpp)
    client.identity = {"kind": "scripted_api", "context_tokens": 16384}
    client.seed = 0
    client.requests = []
    iterator = iter(replies)

    def request(path, body=None, timeout=30):
        client.requests.append(copy.deepcopy(body))
        calls, finish = next(iterator)
        return {"choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": "",
            "tool_calls": [{"id": f"call_{len(client.requests)}_{i}", "type": "function",
                "function": {"name": name, "arguments": arguments if isinstance(arguments, str)
                             else json.dumps(arguments)}} for i, (name, arguments) in enumerate(calls)]}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20}}

    client.request = request
    return client


FINAL = ([("final_answer", {"answer": "Đã xong."})], "tool_calls")


class DeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        source = DATA / "public_test"
        target = cls.root / "public_test"
        target.mkdir()
        shutil.copytree(source / "zaic_tools", target / "zaic_tools", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(source / "public_test_tools_catalog.json", target)
        cls.items = list(samples(DATA, "public_test", limit=2))
        cls.items[0]["history"] = [{"role": "user", "audio": "history.wav"},
            {"role": "assistant", "text": "Đã thực hiện.",
             "tool_calls": [{"name": "ewallet.get_balance", "arguments": {}}],
             "tool_results": [{"ok": True, "balance": 1}]}]
        (target / "public_test.jsonl").write_text("".join(json.dumps(x) + "\n" for x in cls.items), encoding="utf-8")
        for item in cls.items:
            folder = target / "public_test_environment" / item["id"]
            folder.parent.mkdir(exist_ok=True)
            shutil.copytree(source / "public_test_environment" / item["id"], folder)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def infer(self, client, *, budget=deploy.BUDGET):
        asr = ASR()
        with TemporaryDirectory() as folder:
            trace = Trace(Path(folder) / "trace.jsonl", self.items[0]["id"])
            try:
                result = deploy.infer_sample(self.items[0], self.root, "public_test", asr, client, trace, budget=budget)
            finally:
                trace.close()
            events = [json.loads(x) for x in (Path(folder) / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
        return result, asr, events

    def test_sdk_calls_rejections_noops_and_history_feedback(self):
        client = backend([([("ewallet.get_balance", {})], "tool_calls"),
            ([("ewallet.transfer", {"amount": 999999999999, "phone": "0900000000"})], "tool_calls"),
            ([("ewallet.transfer", {})], "tool_calls"), FINAL])
        record, asr, _ = self.infer(client)
        self.assertEqual(record["status"], "completed", record)
        self.assertEqual(len(record["calls"]), 3)
        self.assertTrue(record["calls"][1]["result"]["ok"])
        self.assertFalse(record["calls"][1]["result"]["done"])
        self.assertFalse(record["calls"][2]["result"]["ok"])
        self.assertEqual(record["submission"]["tool_calls"], [p["call"] for p in record["calls"]])
        self.assertEqual(record["submission"]["state_hash"], record["calls"][-1]["state_hash"])
        self.assertEqual(len(asr.paths), 2)
        wire = client.requests[-1]["messages"]
        feedback = [json.loads(x["content"]) for x in wire if x["role"] == "tool"]
        self.assertIn(record["calls"][1]["result"], feedback)
        self.assertIn(record["calls"][2]["result"], feedback)
        self.assertEqual(client.requests[0]["seed"], 0)
        self.assertEqual(client.requests[0]["max_tokens"], 2048)
        self.assertEqual(client.requests[0]["temperature"], 0)
        self.assertEqual(len(wire[-1]["content"]), len("<tool_call>\n"))

    def test_missing_information_stops_later_calls(self):
        client = backend([([("sys.ask_missing_info", {"tool_name": "ewallet.transfer", "params": ["amount"]}),
                            ("ewallet.get_balance", {})], "tool_calls")])
        result, _, _ = self.infer(client)
        self.assertEqual(result["status"], "waiting_for_user")
        self.assertEqual(len(result["calls"]), 1)

    def test_multiple_sdk_calls_keep_order_and_feedback_ids(self):
        calls = [("ewallet.get_balance", {}), ("ewallet.transfer", {})]
        client = backend([(calls, "tool_calls"), FINAL])
        result, _, _ = self.infer(client)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual([p["call"]["name"] for p in result["calls"]], [name for name, _ in calls])
        feedback = client.requests[-1]["messages"][-3:-1]
        self.assertEqual([m["tool_call_id"] for m in feedback], ["call_1_0", "call_1_1"])
        self.assertEqual([json.loads(m["content"]) for m in feedback],
                         [p["result"] for p in result["calls"]])

    def test_mixed_final_answer_is_rejected_before_sdk_dispatch(self):
        mixed = [("ewallet.get_balance", {}), *FINAL[0]]
        result, _, events = self.infer(backend([(mixed, "tool_calls"), FINAL]))
        self.assertEqual((result["status"], result["reason"]), ("protocol_error", "tool_calls"))
        self.assertEqual(result["submission"]["tool_calls"], [])
        self.assertEqual(result["metrics"]["model_calls"], 1)
        self.assertIsNotNone(next(e for e in events if e["event"] == "model_error")["raw_response"])

    def test_duplicate_tool_ids_are_rejected_before_sdk_dispatch(self):
        client = backend([([("ewallet.get_balance", {}), ("ewallet.transfer", {})], "tool_calls"), FINAL])
        request = client.request

        def duplicate_ids(*args, **kwargs):
            response = request(*args, **kwargs)
            calls = response["choices"][0]["message"]["tool_calls"]
            if len(calls) > 1:
                calls[1]["id"] = calls[0]["id"]
            return response

        client.request = duplicate_ids
        result, _, _ = self.infer(client)
        self.assertEqual((result["status"], result["reason"]), ("protocol_error", "tool_calls"))
        self.assertEqual(result["submission"]["tool_calls"], [])

    def test_step_limit_preserves_executed_calls_and_returns_success_for_written_output(self):
        client = backend([([("ewallet.get_balance", {})], "tool_calls")] * deploy.MAX_STEPS)
        with TemporaryDirectory() as folder:
            output = Path(folder)
            errors = deploy.run_split(self.root, "public_test", output, ASR(), client, smoke_test=True)
            result = json.loads((output / "submission/results.jsonl").read_text(encoding="utf-8"))
            row = json.loads((output / "submission.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(errors, 0)
        self.assertEqual((result["status"], result["reason"]), ("budget_exhausted", "step_limit"))
        self.assertEqual(client.calls, deploy.MAX_STEPS)
        self.assertEqual(row["tool_calls"], [pair["call"] for pair in result["calls"]])
        self.assertEqual(len(row["tool_calls"]), deploy.MAX_STEPS)
        self.assertEqual(row["state_hash"], result["calls"][-1]["state_hash"])

    def test_sdk_setup_error_leaves_no_row_and_returns_failure(self):
        with TemporaryDirectory() as folder, patch.object(deploy, "create_env", side_effect=RuntimeError("missing environment")):
            output = Path(folder)
            errors = deploy.run_split(self.root, "public_test", output, ASR(), backend([]), smoke_test=True)
            result = json.loads((output / "submission/results.jsonl").read_text(encoding="utf-8"))
            self.assertEqual((output / "submission.jsonl").read_text(encoding="utf-8"), "")
        self.assertEqual(errors, 1)
        self.assertEqual(result["status"], "runner_error")

    def test_truncated_arguments_stop_before_json_decode_or_sdk_execution(self):
        client = backend([([("ewallet.transfer", '{"amount": "unterminated')], "length")])
        result, _, events = self.infer(client)
        self.assertEqual((result["status"], result["reason"]), ("budget_exhausted", "token_limit"))
        self.assertEqual(result["calls"], [])
        self.assertTrue(next(e for e in events if e["event"] == "model")["hit_token_limit"])

    def test_truncated_xml_is_a_token_limit(self):
        client = backend([])
        client.request = Mock(return_value={"choices": [{"finish_reason": "length",
            "message": {"role": "assistant", "content": "<tool_call>\n<function=ewallet.transfer"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 2048}})
        result, _, events = self.infer(client)
        self.assertEqual((result["status"], result["reason"]), ("budget_exhausted", "token_limit"))
        self.assertEqual(result["submission"]["tool_calls"], [])
        self.assertIn("<tool_call>", next(e for e in events if e["event"] == "model")["raw_text"])

    def test_unparsed_xml_is_a_protocol_error_with_raw_evidence(self):
        client = backend([])
        client.request = Mock(return_value={"choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": "<tool_call>\n<function=ewallet.transfer"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30}})
        result, _, events = self.infer(client)
        self.assertEqual((result["status"], result["reason"]), ("protocol_error", "tool_calls"))
        self.assertEqual(result["submission"]["tool_calls"], [])
        self.assertIsNotNone(next(e for e in events if e["event"] == "model_error")["raw_response"])

    def test_untruncated_invalid_arguments_keep_raw_evidence(self):
        client = backend([([("ewallet.transfer", '{"amount": "unterminated')], "tool_calls")])
        result, _, events = self.infer(client)
        self.assertEqual((result["status"], result["reason"]), ("protocol_error", "tool_arguments"))
        self.assertEqual(result["calls"], [])
        self.assertIsNotNone(next(e for e in events if e["event"] == "model_error")["raw_response"])

    def test_invalid_http_json_is_distinct_from_tool_arguments(self):
        client = LlamaCpp.__new__(LlamaCpp)
        client.url = "http://127.0.0.1:8087"
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"choices": "broken')):
            with self.assertRaises(ResponseFormatError) as caught:
                client.request("/v1/chat/completions")
        self.assertEqual(caught.exception.stage, "http_json")
        self.assertEqual(caught.exception.raw_response, '{"choices": "broken')

    def test_expired_budget_keeps_real_sdk_hash_without_model_calls(self):
        from lifemate.config import Budget
        result, _, _ = self.infer(backend([]), budget=Budget(seconds=0))
        self.assertEqual(result["reason"], "time_limit")
        self.assertEqual(result["metrics"]["model_calls"], 0)
        self.assertEqual(len(result["submission"]["state_hash"]), 64)

    def test_default_selection_covers_whole_split_and_outputs_docker_fields(self):
        original = Path.read_bytes

        def read_bytes(path):
            if path.name == "state.json":
                raise AssertionError("Participant code must not fingerprint environment files")
            return original(path)

        with TemporaryDirectory() as folder, patch.object(Path, "read_bytes", read_bytes), \
                patch.object(deploy, "create_env", wraps=deploy.create_env) as factory:
            failed = deploy.run_split(self.root, "public_test", Path(folder), ASR(), backend([FINAL, FINAL]))
            rows = [json.loads(x) for x in (Path(folder) / "submission.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(failed, 0)
        self.assertEqual(factory.call_count, 2)
        self.assertEqual([r["id"] for r in rows], [r["id"] for r in self.items])
        self.assertTrue(all(set(r) == {"id", "tool_calls", "state_hash", "time"} for r in rows))
        self.assertTrue(all(isinstance(r["time"], int) and r["time"] >= 0 for r in rows))

    def test_single_sample_selection_requires_smoke_mode(self):
        with TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                deploy.run_split(self.root, "public_test", Path(folder), ASR(), backend([]),
                                 sample_id=self.items[1]["id"])
            deploy.run_split(self.root, "public_test", Path(folder), ASR(), backend([FINAL]),
                             smoke_test=True, sample_id=self.items[1]["id"])
            rows = [json.loads(x) for x in (Path(folder) / "submission.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["id"] for r in rows], [self.items[1]["id"]])

    def test_selected_imports_do_not_load_historical_backends(self):
        self.assertFalse(any(x == "jaz" or x.startswith("jaz.") or x == "transformers"
                             or x.startswith("transformers.") for x in sys.modules))

    def test_unready_server_times_out_and_is_terminated(self):
        server = Mock()
        server.poll.return_value = None
        with TemporaryDirectory() as folder, patch("lifemate.asr.GipformerASR"), \
                patch.object(deploy.subprocess, "Popen", return_value=server), \
                patch.object(deploy, "SERVER_STARTUP_TIMEOUT", 0, create=True), \
                patch.object(deploy.urllib.request, "urlopen", side_effect=AssertionError("deadline exceeded")):
            with self.assertRaisesRegex(TimeoutError, "llama-server.*llama-server.log"):
                with deploy.load_models(folder, folder):
                    self.fail("Unready server was accepted")
        server.terminate.assert_called_once()
        server.wait.assert_called_once_with(timeout=10)


if __name__ == "__main__":
    unittest.main()
