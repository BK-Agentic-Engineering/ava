"""CPU-only: scripted native output -> tokenizer/parser -> Jaz -> organizer SDK.

Artifacts are explicitly scripted runs, never model-quality measurements.
"""

import copy
import json
import time
import unittest
from unittest.mock import patch

from lifemate.data import read_jsonl
from lifemate.llm import LocalLLM
from lifemate.sdk import create_env
from lifemate.synthetic import execute_case, read, save


from harness_support import PACKAGE, NativeScript, AgentEnv, native_call, observations, workspace


class NativeHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder, cls.runtime, cls.tokenizer, cls.cases = workspace()
        cls.reference_bytes = {p: p.read_bytes() for p in PACKAGE.glob("*.output.json")}
        cls.executions = []

    @classmethod
    def tearDownClass(cls):
        unchanged = all(p.read_bytes() == data for p, data in cls.reference_bytes.items())
        save(cls.folder / "audit_runs.json", {"backend": "scripted_native", "llm_weights_loaded": False,
             "reference_outputs_unchanged": unchanged, "executions": cls.executions})
        print("\nNATIVE AUDIT ARTIFACTS:", cls.folder)
        if not unchanged:
            raise AssertionError("Reference output was modified")

    def flow(self, sid, tag, actions, *, seconds=30, change=None):
        case = copy.deepcopy(self.cases[sid])
        if change:
            change(case)
        folder = self.folder / tag
        folder.mkdir()
        model = NativeScript(self.tokenizer, actions, folder)
        sessions = []

        def factory(*args):
            env = create_env(*args)
            sessions.append(env)
            return AgentEnv(env)

        with patch("lifemate.synthetic.create_env", side_effect=factory):
            prediction, summary = execute_case(case, PACKAGE, self.runtime, folder, model,
                backend_kind="scripted_native", seconds=seconds)
        self.assertEqual(len(sessions), 1)
        sdk = sessions[0]
        self.assertEqual(set(prediction), {"id", "tool_calls", "state_hash"})
        self.assertEqual(prediction["tool_calls"], sdk.get_tool_calls())
        self.assertEqual(prediction["state_hash"], sdk.get_state_hash())
        # This is the caller's normal persistence step, without loading a model.
        (folder / "submission.jsonl").write_text(json.dumps(prediction, ensure_ascii=False) + "\n", encoding="utf-8")
        (folder / "samples.jsonl").write_text(json.dumps(summary, ensure_ascii=False) + "\n", encoding="utf-8")
        events = list(read_jsonl(folder / "traces" / f"{sid}.jsonl"))
        executed = [e for e in events if e["event"] == "tool"]
        self.assertEqual([e["call"] for e in executed], prediction["tool_calls"])
        self.assertEqual([entry["result"] for entry in sdk.log], [e["result"] for e in executed])
        known_ids = {e["call_id"] for e in executed}
        seen = []
        for event in events:
            if event["event"] == "tool":
                seen.append(event)
            elif event["event"] == "model_input":
                returned = [m for m in event["messages"] if m["role"] == "tool"
                            and m.get("tool_call_id") in known_ids]
                self.assertEqual([m["tool_call_id"] for m in returned], [e["call_id"] for e in seen])
                self.assertEqual([json.loads(m["content"]) for m in returned], [e["result"] for e in seen])
        output = read(folder / "model_outputs" / f"{sid}.output.json")
        calls, results = output["execution"]["tool_calls"], output["execution"]["tool_results"]
        self.assertEqual([r["payload"] for r in results], [e["result"] for e in executed])
        self.assertEqual([r["call_id"] for r in results], [c["call_id"] for c in calls])
        self.assertEqual(len(set(c["call_id"] for c in calls)), len(calls))
        self.assertEqual(output["provenance"]["trace_call_id_map"],
                         {e["call_id"]: c["call_id"] for e, c in zip(executed, calls)})
        self.assertEqual(output["availability"]["model_run"], "not_performed")
        if model.inputs:
            self.assertTrue(any(e.get("name") == "LLMQueryEnter" for e in events))
        else:
            self.assertEqual(summary["reason"], "time_limit")
        self.executions.append({"flow": tag, "status": summary["status"],
                                "sdk_calls": len(executed), "queries": len(model.inputs)})
        return prediction, summary, output, model, sdk, events

    def test_sdk_error_repair_ordered_batch_and_noop(self):
        chosen = {}

        def batch(messages, prompt):
            row = observations(messages)[-1]["appliances"][0]
            chosen.update(id=row["id"], cycle=row["cycles"][-1])
            self.assertIn("<tool_response>", prompt)
            self.assertIn(row["id"], prompt)
            return (native_call("appliances.stop")
                    + native_call("appliances.stop", appliance_id=chosen["id"])
                    + native_call("appliances.start_cycle", appliance_id=chosen["id"],
                                  cycle=chosen["cycle"], delay_minutes="hai"))

        def repair(messages, prompt):
            results = observations(messages)[-3:]
            self.assertEqual([r["ok"] for r in results], [False, True, False])
            self.assertEqual(results[1]["item"]["state"]["status"], "idle")
            self.assertIn("delay_minutes", results[2]["error"])
            self.assertEqual(prompt.count("<tool_response>"), 4)
            # A native integer must reach SDK as integer; the second start becomes a real no-op.
            return 2 * native_call("appliances.start_cycle", appliance_id=chosen["id"],
                                   cycle=chosen["cycle"], delay_minutes=2)

        def finish(messages, prompt):
            results = observations(messages)
            self.assertEqual(results[-2]["item"]["state"]["status"], "scheduled")
            self.assertTrue(results[-1]["ok"])
            self.assertIs(results[-1]["done"], False)
            self.assertIn(results[-1]["message"], prompt)
            self.assertEqual(results[2]["item"]["state"]["status"], "idle")
            return ""

        pred, summary, out, model, sdk, _ = self.flow("TR16_APP_KEEP", "repair_batch_noop", [
            native_call("appliances.list", type="washer"), batch, repair, finish])
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(out["final_text"], "")
        self.assertEqual(len(pred["tool_calls"]), 6)
        self.assertEqual([c["name"] for c in pred["tool_calls"]][1:3], ["appliances.stop"] * 2)
        self.assertIsInstance(pred["tool_calls"][-1]["arguments"]["delay_minutes"], int)

    def test_lookup_then_ask_stops_before_later_call(self):
        def ask(messages, prompt):
            self.assertTrue(observations(messages)[-1]["ok"])
            return (native_call("sys.ask_missing_info", tool_name="reminders.create", params=["time"])
                    + native_call("reminders.create", content="must not execute", time="2027-01-01T08:00:00+07:00"))
        pred, summary, out, _, _, events = self.flow("B02_N_C", "lookup_ask", [
            native_call("calendar.list_events"), ask])
        self.assertEqual(summary["status"], "waiting_for_user")
        self.assertIsNone(out["final_text"])
        self.assertEqual([c["name"] for c in pred["tool_calls"]],
                         ["calendar.list_events", "sys.ask_missing_info"])
        self.assertEqual(pred["tool_calls"][-1]["arguments"]["params"], ["time"])
        self.assertEqual(len([e for e in events if e["event"] == "model"][-1]["tool_calls"]), 2)

    def test_observe_then_no_write(self):
        def finish(messages, prompt):
            row = observations(messages)[-1]["appliances"][0]
            self.assertEqual(row["state"]["status"], "running")
            return "Máy đang chạy, giữ nguyên."
        pred, _, out, _, sdk, _ = self.flow("TR16_APP_KEEP", "observe_only", [
            native_call("appliances.list", type="washer"), finish])
        self.assertEqual(len(pred["tool_calls"]), 1)
        # Private snapshot is inspected only by this verifier/test after agent execution.
        initial = read(PACKAGE / "private/TR16_APP_KEEP.json")["initial_state"]
        self.assertEqual(sdk.get_state(), initial)
        self.assertEqual(out["final_text"], "Máy đang chạy, giữ nguyên.")

    def test_history_is_evidence_and_private_data_is_not_rendered(self):
        def create(messages, prompt):
            self.assertNotIn("PRIVATE_SENTINEL_403", prompt)
            item = observations(messages)[0]["item"]
            self.assertNotIn("payload", observations(messages)[0])
            self.assertIn(item["time"], prompt)
            self.assertEqual(prompt.count("<function=reminders.create>"), 1)
            return native_call("calendar.create_event", title=item["content"], start=item["time"])
        pred, _, out, model, sdk, _ = self.flow("TR15_PLANNING_TOMORROW", "history", [create, "Đã thêm lịch."],
            change=lambda c: c.update(private_test_data="PRIVATE_SENTINEL_403"))
        self.assertEqual([c["name"] for c in pred["tool_calls"]], ["calendar.create_event"])
        before = read(PACKAGE / "private/TR15_PLANNING_TOMORROW.json")["initial_state"]
        self.assertEqual(sdk.get_state()["reminders"], before["reminders"])
        self.assertNotIn("PRIVATE_SENTINEL_403", json.dumps(model.inputs))

    def test_native_unknown_argument_is_not_silently_lost(self):
        raw = "<tool_call><function=appliances.list><parameter=bad-key>001</parameter></function></tool_call>"
        pred, summary, _, _, _, _ = self.flow("TR16_APP_KEEP", "argument_preservation", [raw, "Đã đọc."])
        self.assertEqual(pred["tool_calls"][0]["arguments"], {"bad-key": "001"})
        self.assertEqual(summary["status"], "completed")

    def test_unknown_tool_rejection_and_parser_error_are_distinct(self):
        malformed = "<tool_call><function=appliances.list><parameter=type>washer</parameter><parameter=type>dryer</parameter></function></tool_call>"
        def after_parse_error(messages, prompt):
            self.assertEqual(observations(messages), [])
            self.assertIn("Lỗi parse tool call", messages[-1]["content"])
            return native_call("unknown-tool.read", **{"odd-key": "001"})
        def after_sdk_error(messages, prompt):
            self.assertFalse(observations(messages)[-1]["ok"])
            return native_call("appliances.list", type="washer")
        pred, _, _, _, _, events = self.flow("TR16_APP_KEEP", "parse_vs_sdk_error", [
            malformed, after_parse_error, after_sdk_error, "Xong"])
        self.assertEqual([c["name"] for c in pred["tool_calls"]], ["unknown-tool.read", "appliances.list"])
        self.assertEqual(pred["tool_calls"][0]["arguments"], {"odd-key": "001"})
        self.assertTrue([e for e in events if e["event"] == "model"][0]["parse_error"])

    def test_plain_text_is_not_converted_into_a_call(self):
        text = "Tôi có thể gọi appliances.list nếu bạn muốn."
        pred, _, out, _, _, _ = self.flow("TR16_APP_KEEP", "plain_text", [text])
        self.assertEqual(pred["tool_calls"], [])
        self.assertEqual(out["final_text"], text)
        record = read(self.folder / "plain_text/sessions/TR16_APP_KEEP/result.json")
        self.assertEqual(record["backend"]["name"], "native-harness-tests")
        self.assertGreaterEqual(record["metrics"]["preparation_seconds"], 0)

    def test_budget_timeout_interruption_and_runner_error_preserve_evidence(self):
        def interrupt(messages, prompt):
            raise KeyboardInterrupt()
        def fail(messages, prompt):
            raise RuntimeError("injected backend failure")
        read_call = native_call("appliances.list", type="washer")
        for name, actions, seconds, status, count in [
            ("token_limit", [(read_call, {"hit_token_limit": True})], 30, "budget_exhausted", 0),
            ("deadline", [read_call], 0, "budget_exhausted", 0),
            ("partial_timeout", [read_call, (read_call, {"timed_out": True})], 30, "budget_exhausted", 1),
            ("interrupt", [read_call, interrupt], 30, "externally_interrupted", 1),
            ("backend_error", [read_call, fail], 30, "runner_error", 1),
        ]:
            with self.subTest(name=name):
                pred, summary, out, _, _, _ = self.flow("TR16_APP_KEEP", name, actions, seconds=seconds)
                self.assertEqual(summary["status"], status)
                self.assertEqual(len(pred["tool_calls"]), count)
                self.assertIsNone(out["final_text"])
                self.assertEqual(out["termination"]["status"], "budget_exhausted" if status == "timeout" else status)

    def test_permission_drift_is_rejected_before_backend_runs(self):
        case = copy.deepcopy(self.cases["TR16_APP_KEEP"])
        case["private_execution"]["tools"].remove("appliances.list")
        folder = self.folder / "permission_drift"
        folder.mkdir()
        model = NativeScript(self.tokenizer, [], folder)
        with self.assertRaisesRegex(ValueError, "quyền runtime"):
            execute_case(case, PACKAGE, self.runtime, folder, model, backend_kind="scripted_native")
        self.assertEqual(model.inputs, [])

    def test_production_generation_wrapper_without_loading_weights(self):
        import torch
        from types import SimpleNamespace
        raw = native_call("appliances.list", type="washer") + "<|im_end|>"

        def produce_tokens(**kwargs):
            suffix = torch.tensor([self.tokenizer.encode(raw, add_special_tokens=False)])
            return torch.cat((kwargs["input_ids"], suffix), dim=1)

        llm = LocalLLM.__new__(LocalLLM)  # Bypass weight loading, replace only token generation.
        llm.tokenizer = self.tokenizer
        llm.model = SimpleNamespace(device=torch.device("cpu"), generate=produce_tokens,
            generation_config=SimpleNamespace(eos_token_id=self.tokenizer.convert_tokens_to_ids("<|im_end|>")))
        from lifemate.synthetic import case_tools, render_visible
        case = self.cases["TR16_APP_KEEP"]
        messages, _ = render_visible(case["agent_visible"], "wrapper-test")
        response = llm.generate(messages, case_tools(case, PACKAGE), deadline=time.monotonic() + 30)
        self.assertEqual(response["raw_text"], raw)
        self.assertEqual(response["tool_calls"], [{"name": "appliances.list", "arguments": {"type": "washer"}}])
        self.assertIsNone(response["parse_error"])
        self.assertFalse(response["hit_token_limit"])

    def test_cli_stops_after_interruption_and_keeps_partial_submission(self):
        import sys
        from types import SimpleNamespace
        from lifemate.cli import main
        rows = []
        for sid in ("TR16_APP_KEEP", "B02_N_C"):
            case = self.cases[sid]
            context = copy.deepcopy(case["agent_visible"]["context"])
            context["installed_apps"] = {}
            for name in case["private_execution"]["tools"]:
                context["installed_apps"].setdefault(name.split(".")[0], {"tools": []})["tools"].append(name)
            rows.append({"id": sid, "audio": "", "audio_text": case["agent_visible"]["request"],
                         "context": context, "history": []})
        (self.runtime / "train/train.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        (self.runtime / "VERSION").write_text("scripted harness audit", encoding="utf-8")
        folder = self.folder / "cli_interrupt"
        def interrupt(messages, prompt):
            raise KeyboardInterrupt()
        model = NativeScript(self.tokenizer, [native_call("appliances.list"), interrupt], folder)
        model.model = SimpleNamespace(parameters=lambda: [])
        argv = ["run.py", "--data-root", str(self.runtime), "--text", "--limit", "2", "--output", str(folder)]
        with patch.object(sys, "argv", argv), \
             patch("lifemate.llm.LocalLLM", return_value=model), \
             patch("torch.cuda.get_device_name", return_value="scripted CPU test"), \
             patch("lifemate.evaluate.evaluate_run", side_effect=AssertionError("Must not score an interrupted batch")):
            main()
        predictions = list(read_jsonl(folder / "submission.jsonl"))
        summaries = list(read_jsonl(folder / "samples.jsonl"))
        self.assertEqual(len(predictions), 1)
        self.assertEqual(len(predictions[0]["tool_calls"]), 1)
        self.assertEqual(summaries[0]["status"], "externally_interrupted")
        metadata = read(folder / "metadata.json")
        self.assertEqual(metadata["completed_samples"], 0)  # Paused is not committed/completed.
        self.assertFalse(metadata["is_complete_split"])
        metadata.update(backend_kind="scripted_native", models={"llm": "SCRIPTED_NATIVE_NO_WEIGHTS", "asr": "not_used"})
        save(folder / "metadata.json", metadata)


if __name__ == "__main__":
    unittest.main()
