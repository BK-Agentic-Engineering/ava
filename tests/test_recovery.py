import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from harness_support import workspace, NativeScript, native_call, ROOT, PACKAGE, observations
from lifemate.agent import run_session
from lifemate.batch import run_batch, export_results, session_trace
from lifemate.config import Budget
from lifemate.data import read_jsonl
from lifemate.sdk import create_env, load_sdk
from lifemate.store import SessionStore, RecoveryRequired
from lifemate.synthetic import prepare_case, read, save, export_case, evaluate_cases, DEFAULT_VERIFIERS


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.runtime, cls.tokenizer, cls.cases = workspace()
        cls.identity = {"kind": "scripted_native", "name": "recovery-tests"}

    def setup_session(self, name, sid="TR16_APP_KEEP"):
        folder = self.root / name
        folder.mkdir()
        prepared = prepare_case(self.cases[sid], PACKAGE, self.runtime, f"{folder.name}/{sid}")
        prepared["run_id"] = f"{folder.name}/{sid}"
        return folder, prepared

    def execute(self, folder, prepared, actions, resume=False, budget=None, env_factory=None):
        backend = NativeScript(self.tokenizer, actions, folder / ("resume_backend" if resume else "backend"))
        env = prepared["environment"]
        trace = session_trace(folder, prepared["id"])
        try:
            result = run_session(prepared, backend, env_factory or (
                lambda: create_env(Path(env["root"]), env["split"], env["sample_id"])), trace,
                store=SessionStore(folder / "sessions" / prepared["id"]),
                backend_identity=self.identity, budget=budget, resume=resume)
        finally:
            trace.close()
        return result, backend

    def crash(self, name, phase, raw):
        folder, prepared = self.setup_session(name)
        payload = {"folder": str(folder), "prepared": prepared, "identity": self.identity,
                   "phase": phase, "raw": raw}
        save(folder / "worker_input.json", payload)
        child = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tests/crash_worker.py"),
            str(folder / "worker_input.json")], capture_output=True, text=True, encoding="utf-8", timeout=60)
        save(folder / "child_exit.json", {"returncode": child.returncode, "stdout": child.stdout, "stderr": child.stderr})
        self.assertIn(child.returncode, {77, 78, 79, 80, 81}, child.stderr)
        return folder, prepared

    def test_hard_crash_after_write_result_restores_pending_batch_without_duplicate_write(self):
        raw = native_call("reminders.create", content="persisted once", time="2027-10-05T08:00:00+07:00") + native_call("appliances.list")
        folder, prepared = self.crash("crash_after_result", "after_result", raw)
        self.assertFalse((folder / "sessions/TR16_APP_KEEP/result.json").exists())
        sessions = []
        def factory():
            env = create_env(self.runtime, "train", "TR16_APP_KEEP")
            sessions.append(env)
            return env
        def finish(messages, prompt):
            result = observations(messages)
            self.assertTrue(result[-2]["ok"])
            self.assertIn("appliances", result[-1])
            return "Restored."
        record, backend = self.execute(folder, prepared, [finish], resume=True, env_factory=factory)
        self.assertEqual(record["status"], "completed")
        self.assertEqual([p["call"]["name"] for p in record["calls"]], ["reminders.create", "appliances.list"])
        self.assertEqual(len(record["submission"]["tool_calls"]), 2)
        state = sessions[0].get_state()
        self.assertEqual(sum(x.get("content") == "persisted once" for x in state["reminders"]["reminders"]), 1)
        self.assertEqual(len(backend.inputs), 1)

    def test_hard_crash_after_sdk_before_result_is_not_guessed(self):
        folder, prepared = self.crash("ambiguous_call", "after_sdk_before_result",
            native_call("reminders.create", content="ambiguous", time="2027-10-05T08:00:00+07:00"))
        original = (folder / "sessions/TR16_APP_KEEP/journal.jsonl").read_bytes()
        record, backend = self.execute(folder, prepared, [], resume=True)
        self.assertEqual(record["status"], "recovery_required")
        self.assertIsNone(record["submission"])
        self.assertEqual(backend.inputs, [])
        self.assertEqual((folder / "sessions/TR16_APP_KEEP/journal.jsonl").read_bytes(), original)

    def test_torn_journal_and_corrupt_result_are_retained(self):
        folder, prepared = self.crash("torn_journal", "torn_result", native_call("appliances.list"))
        journal = folder / "sessions/TR16_APP_KEEP/journal.jsonl"
        original = journal.read_bytes()
        with self.assertRaisesRegex(RecoveryRequired, "incomplete"):
            self.execute(folder, prepared, [], resume=True)
        self.assertEqual(journal.read_bytes(), original)
        corrupt = SessionStore(self.root / "corrupt_committed")
        (corrupt.folder / "result.json").write_text('{"id":', encoding="utf-8")
        with self.assertRaisesRegex(RecoveryRequired, "corrupt"):
            corrupt.result()

    def test_inflight_model_crash_reports_unaccounted_time(self):
        folder, prepared = self.crash("inflight_model", "inflight_model", "unused")
        record, backend = self.execute(folder, prepared, [], resume=True)
        self.assertEqual(record["status"], "recovery_required")
        self.assertIn("unaccounted", record["reason"])
        self.assertEqual(backend.inputs, [])

    def test_committed_result_survives_missing_or_torn_exports_and_skips_backend(self):
        folder, prepared = self.crash("committed_before_export", "after_commit", "Finished")
        committed = (folder / "sessions/TR16_APP_KEEP/result.json").read_bytes()
        def forbidden():
            raise AssertionError("Committed session must not create environment")
        record, backend = self.execute(folder, prepared, [], resume=True, env_factory=forbidden)
        self.assertEqual(record["status"], "completed")
        self.assertEqual(backend.inputs, [])
        (folder / "submission.jsonl").write_text('{"broken":', encoding="utf-8")
        export_results(folder, [prepared["id"]])
        self.assertEqual(list(read_jsonl(folder / "submission.jsonl")), [record["submission"]])
        self.assertEqual(list(read_jsonl(folder / "samples.jsonl"))[0]["status"], "completed")
        self.assertEqual((folder / "sessions/TR16_APP_KEEP/result.json").read_bytes(), committed)

    def test_keyboard_interrupt_resumes_messages_and_committed_calls(self):
        folder, prepared = self.setup_session("resume_keyboard")
        def interrupt(messages, prompt):
            raise KeyboardInterrupt()
        paused, _ = self.execute(folder, prepared, [native_call("appliances.list"), interrupt])
        self.assertFalse(paused["terminal"])
        self.assertFalse((folder / "sessions/TR16_APP_KEEP/result.json").exists())
        def finish(messages, prompt):
            self.assertIn("appliances", observations(messages)[-1])
            return "Continued"
        record, _ = self.execute(folder, prepared, [finish], resume=True)
        self.assertEqual(record["status"], "completed")
        self.assertEqual(len(record["calls"]), 1)
        self.assertEqual(record["metrics"]["model_calls"], 3)

    def test_resume_refuses_changed_budget_backend_or_input(self):
        folder, prepared = self.setup_session("configuration_binding")
        self.execute(folder, prepared, ["Done"])
        with self.assertRaisesRegex(RecoveryRequired, "different"):
            self.execute(folder, prepared, [], resume=True, budget=Budget(seconds=31))
        changed = copy.deepcopy(prepared)
        changed["messages"][-1]["content"] += " changed"
        with self.assertRaisesRegex(RecoveryRequired, "different"):
            self.execute(folder, changed, [], resume=True)

    def test_batch_preparation_error_preserves_other_results_and_resume_skips_them(self):
        folder = self.root / "batch_prepare_failure"
        items = [self.cases[s] for s in ("TR16_APP_KEEP", "B02_N_C", "TR15_PLANNING_TOMORROW")]
        def prepare(item):
            if item["sample_id"] == "B02_N_C":
                raise ValueError("injected missing fixture")
            return prepare_case(item, PACKAGE, self.runtime, f"{folder.name}/{item['sample_id']}")
        backend = NativeScript(self.tokenizer, ["First", "Third"], self.root / "batch_backend")
        records = run_batch(items, prepare, backend, folder, backend_identity=self.identity)
        self.assertEqual([r["status"] for r in records], ["completed", "preparation_error", "completed"])
        self.assertEqual(len(list(read_jsonl(folder / "submission.jsonl"))), 2)
        never = NativeScript(self.tokenizer, [], self.root / "batch_resumed_backend")
        resumed = run_batch(items, prepare, never, folder, backend_identity=self.identity, resume=True)
        self.assertEqual([r["status"] for r in resumed], ["completed", "preparation_error", "completed"])
        self.assertEqual(never.inputs, [])

    def test_context_and_zero_output_budget_stop_before_token_producer(self):
        for tag, budget, reason in [("context_limit", Budget(context_tokens=1), "context_limit"),
                                    ("zero_output", Budget(output_tokens=0), "token_limit")]:
            folder, prepared = self.setup_session(tag)
            record, _ = self.execute(folder, prepared, [], budget=budget)
            self.assertEqual(record["status"], "budget_exhausted")
            self.assertEqual(record["reason"], reason)
            self.assertEqual(record["submission"]["tool_calls"], [])

    def test_preparation_is_charged_to_baseline_budget_and_not_charged_again_on_resume(self):
        folder, prepared = self.setup_session("preparation_budget")
        prepared["timings"] = {"preparation_seconds": 2}
        record, backend = self.execute(folder, prepared, [], budget=Budget(seconds=1))
        self.assertEqual(record["status"], "budget_exhausted")
        self.assertEqual(record["reason"], "time_limit")
        self.assertEqual(backend.inputs, [])
        self.assertGreaterEqual(record["metrics"]["elapsed_seconds"], 2)
        folder, prepared = self.setup_session("preparation_resume")
        prepared["timings"] = {"preparation_seconds": 0.2}
        def interrupt(messages, prompt):
            raise KeyboardInterrupt()
        paused, _ = self.execute(folder, prepared, [native_call("appliances.list"), interrupt])
        prepared["timings"] = {"preparation_seconds": 20}
        resumed, _ = self.execute(folder, prepared, ["Finished"], resume=True)
        self.assertEqual(resumed["metrics"]["charged_preparation_seconds"], 0.2)
        self.assertGreaterEqual(resumed["metrics"]["elapsed_seconds"], paused["metrics"]["elapsed_seconds"])
        self.assertLess(resumed["metrics"]["elapsed_seconds"], 20)

    def test_replay_mismatch_is_not_silently_accepted(self):
        folder, prepared = self.setup_session("replay_mismatch")
        def interrupt(messages, prompt):
            raise KeyboardInterrupt()
        self.execute(folder, prepared, [native_call("appliances.list"), interrupt])
        env = create_env(self.runtime, "train", prepared["id"])
        original = env.call
        def mismatching(name, args):
            return {**original(name, args), "injected_change": True}
        env.call = mismatching
        record, backend = self.execute(folder, prepared, [], resume=True, env_factory=lambda: env)
        self.assertEqual(record["status"], "recovery_required")
        self.assertIsNone(record["submission"])
        self.assertEqual(backend.inputs, [])

    def test_phase_measurements_and_state_do_not_leak_between_samples(self):
        folder = self.root / "sample_isolation"
        items = [self.cases[s] for s in ("TR16_APP_KEEP", "B02_N_C")]
        backend = NativeScript(self.tokenizer, [native_call("reminders.create", content="only-first",
            time="2027-10-05T08:00:00+07:00"), "First finished", "Second finished"], self.root / "isolation_backend")
        sessions = []
        def factory(root, split, sid):
            env = create_env(root, split, sid)
            sessions.append(env)
            return env
        with patch("lifemate.batch.create_env", side_effect=factory):
            records = run_batch(items, lambda c: prepare_case(c, PACKAGE, self.runtime,
                f"{folder.name}/{c['sample_id']}"), backend, folder, backend_identity=self.identity)
        self.assertEqual(len(sessions), 2)
        self.assertFalse(any(r.get("content") == "only-first" for r in sessions[1].get_state()["reminders"]["reminders"]))
        metrics = records[0]["metrics"]
        for key in ("render_tokenize_seconds", "inference_seconds", "parse_seconds", "tool_seconds"):
            self.assertGreaterEqual(metrics[key], 0)
        self.assertLessEqual(sum(metrics[k] for k in ("render_tokenize_seconds", "inference_seconds", "parse_seconds")), metrics["backend_wall_seconds"])

    def test_new_case_declares_verifier_without_runner_id_branch(self):
        from lifemate.synthetic import resolve
        case = copy.deepcopy(self.cases["TR16_APP_KEEP"])
        case.update(sample_id="NEW_DECLARED_CASE", source_metadata={"split": "dev", "status": "spec_only", "exportable": False},
            verification=read(DEFAULT_VERIFIERS)["cases"]["TR16_APP_KEEP"],
            reference_output_ref={"path": "TR16_APP_KEEP.output.json", "selector": ""})
        initial = resolve(PACKAGE, case["private_execution"]["initial_state_ref"])
        save(self.runtime / "train/train_environment/NEW_DECLARED_CASE/state.json", {
            **initial, "_meta": {"tools": case["private_execution"]["tools"], "current_time": case["private_execution"]["current_time"]}})
        folder = self.root / "new_case"
        backend = NativeScript(self.tokenizer, [native_call("appliances.list", type="washer"), "Running"], self.root / "new_case_backend")
        records = run_batch([case], lambda c: prepare_case(c, PACKAGE, self.runtime,
            f"{folder.name}/{c['sample_id']}"), backend, folder, backend_identity=self.identity)
        self.assertEqual(records[0]["source"]["metadata"], case["source_metadata"])
        export_case(records[0], folder)
        reports = evaluate_cases(PACKAGE, self.runtime, folder, [case], overlay=None)
        self.assertEqual(reports[0]["oracle"]["verdict"], "pass")
        self.assertTrue(reports[0]["hash_reproduced"])
        self.assertEqual(reports[0]["local_btc_metric"]["score"], 1)

    def test_sdk_import_origin_is_bound_and_fresh_processes_are_isolated(self):
        other = self.root / "other_source"
        from lifemate.synthetic import prepare_runtime
        root2 = prepare_runtime(PACKAGE, other, list(self.cases.values()))
        code = """from pathlib import Path
import sys
from lifemate.sdk import create_env
a=Path(sys.argv[1]); b=Path(sys.argv[2])
x=create_env(a,'train','TR16_APP_KEEP')
print(x.get_state_hash())
try: create_env(b,'train','TR16_APP_KEEP')
except RuntimeError: print('ORIGIN_BLOCKED')
else: raise AssertionError('SDK source mixed')
"""
        child = subprocess.run([sys.executable, "-X", "utf8", "-c", code, str(self.runtime), str(root2)],
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertIn("ORIGIN_BLOCKED", child.stdout)
        second = subprocess.run([sys.executable, "-X", "utf8", "-c",
            "from pathlib import Path;import sys;from lifemate.sdk import create_env; print(create_env(Path(sys.argv[1]),'train','TR16_APP_KEEP').get_state_hash())", str(root2)],
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(child.stdout.splitlines()[0], second.stdout.strip())
        save(self.root / "sdk_isolation.json", {"same_process": child.stdout, "fresh_process": second.stdout})

    def test_optional_defaults_oracle_and_strict_matcher_are_separate(self):
        folder = self.root / "optional_defaults"
        case = self.cases["TR15_PLANNING_TOMORROW"]
        backend = NativeScript(self.tokenizer, [native_call("calendar.create_event", title="Rà dây neo",
            start="2027-09-18T08:20:00+07:00", end="2027-09-18T09:20:00+07:00"), "Done"],
            self.root / "optional_default_backend")
        run_batch([case], lambda c: prepare_case(c, PACKAGE, self.runtime,
            f"{folder.name}/{c['sample_id']}"), backend, folder, backend_identity=self.identity)
        report = evaluate_cases(PACKAGE, self.runtime, folder, [case])[0]
        self.assertEqual(report["oracle"]["verdict"], "pass")
        self.assertEqual(report["local_btc_metric"]["score"], 0)
        self.assertTrue(report["hash_reproduced"])

    def test_submitted_hash_integrity_and_replay_metric_are_separate(self):
        folder = self.root / "hash_integrity"
        case = self.cases["TR16_APP_KEEP"]
        backend = NativeScript(self.tokenizer, [native_call("appliances.list", type="washer"), "Done"],
            self.root / "hash_integrity_backend")
        run_batch([case], lambda c: prepare_case(c, PACKAGE, self.runtime,
            f"{folder.name}/{c['sample_id']}"), backend, folder, backend_identity=self.identity)
        predictions = list(read_jsonl(folder / "submission.jsonl"))
        # Deliberately corrupt a derived test export; the canonical record remains intact.
        predictions[0]["state_hash"] = "0" * 64
        (folder / "submission.jsonl").write_text(json.dumps(predictions[0]) + "\n", encoding="utf-8")
        report = evaluate_cases(PACKAGE, self.runtime, folder, [case])[0]
        self.assertFalse(report["hash_reproduced"])
        self.assertEqual(report["local_btc_metric"]["score"], 0)
        self.assertEqual(report["replay_metric"]["score"], 1)
        self.assertEqual(report["oracle"]["verdict"], "pass")

    def test_recap_consumes_canonical_records_and_handles_preparation_failure(self):
        from lifemate.recap import render_recap
        folder = self.root / "recap_source"
        items = [self.cases["TR16_APP_KEEP"], self.cases["B02_N_C"]]
        def prepare(item):
            if item["sample_id"] == "B02_N_C":
                raise ValueError("fixture unavailable")
            return prepare_case(item, PACKAGE, self.runtime, f"{folder.name}/{item['sample_id']}")
        run_batch(items, prepare, NativeScript(self.tokenizer, ["Done"], self.root / "recap_backend"),
            folder, backend_identity=self.identity, source={"split": "test", "mode": "scripted_native", "split_samples": 2})
        html = render_recap(folder).read_text(encoding="utf-8")
        self.assertIn("preparation_error", html)
        self.assertIn("Chưa có điểm đầy đủ", html)
        self.assertIn("Done", html)

    def test_sdk_bytes_changed_at_same_origin_require_fresh_process(self):
        load_sdk(self.runtime, "train")
        path = self.runtime / "train/zaic_tools/utils.py"
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"\n# controlled test mutation\n")
            with self.assertRaisesRegex(RuntimeError, "changed after import"):
                load_sdk(self.runtime, "train")
        finally:
            path.write_bytes(original)
        self.assertIsNotNone(load_sdk(self.runtime, "train"))


if __name__ == "__main__":
    unittest.main()
