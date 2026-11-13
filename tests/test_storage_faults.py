"""I/O faults with native token output, real Jaz, tokenizer/parser and SDK."""
from pathlib import Path
import unittest
from unittest.mock import patch

from harness_support import workspace, NativeScript, native_call, PACKAGE
from lifemate.agent import run_session
from lifemate.batch import run_batch, export_results, session_trace
from lifemate.data import read_jsonl
from lifemate.sdk import create_env
from lifemate.store import SessionStore
from lifemate.synthetic import prepare_case
from lifemate.trace import Trace


class StorageFaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.runtime, cls.tokenizer, cls.cases = workspace()
        cls.identity = {'kind': 'scripted_native', 'name': 'storage-faults'}

    def setup_session(self, name):
        folder = self.root / name
        folder.mkdir()
        case = self.cases['TR16_APP_KEEP']
        prepared = prepare_case(case, PACKAGE, self.runtime, f'{folder.name}/{case["sample_id"]}')
        prepared['run_id'] = f'{folder.name}/{case["sample_id"]}'
        store = SessionStore(folder / 'sessions' / prepared['id'])
        env = create_env(self.runtime, 'train', prepared['id'])
        return folder, prepared, store, env

    def execute(self, folder, prepared, store, env, actions, *, resume=False):
        backend = NativeScript(self.tokenizer, actions, folder / ('resumed_backend' if resume else 'backend'))
        trace = session_trace(folder, prepared['id'])
        try:
            record = run_session(prepared, backend, lambda: env, trace, store=store,
                backend_identity=self.identity, resume=resume)
        finally:
            trace.close()
        return record, backend

    def write_call(self):
        return native_call('reminders.create', content='I/O evidence', time='2027-10-05T08:00:00+07:00')

    def assert_consistent(self, record, store, env):
        pairs = [e for e in store.events() if e['event'] == 'tool']
        expected = env.get_tool_calls()
        self.assertEqual([p['call'] for p in record['calls']], expected)
        self.assertEqual([p['call'] for p in pairs], expected)
        self.assertEqual([p['result'] for p in record['calls']], [p['result'] for p in pairs])
        self.assertEqual(record['submission']['tool_calls'], expected)
        self.assertEqual(record['submission']['state_hash'], env.get_state_hash())
        self.assertEqual(store.result(), record)

    def test_trace_failure_after_durable_result_keeps_canonical_pair(self):
        folder, prepared, store, env = self.setup_session('io_trace_result')
        original = Trace.write
        def fail(stream, event, **data):
            if event == 'tool':
                raise OSError('injected trace write failure')
            return original(stream, event, **data)
        with patch.object(Trace, 'write', fail):
            record, backend = self.execute(folder, prepared, store, env, [self.write_call()])
        self.assert_consistent(record, store, env)
        self.assertEqual(record['status'], 'runner_error')
        self.assertEqual(record['reason'], 'trace_io')
        self.assertIn('trace write failure', record['error'])
        self.assertEqual(len(backend.inputs), 1)
        export_results(folder, [prepared['id']])
        self.assertEqual(list(read_jsonl(folder / 'submission.jsonl')), [record['submission']])

    def test_trace_error_after_deadline_keeps_error_cause_and_sdk_evidence(self):
        folder, prepared, store, env = self.setup_session('trace_error_after_deadline')
        original = Trace.write
        clock = [0.0]
        def fail(stream, event, **data):
            if event == 'tool':
                clock[0] = 31.0  # Trace fails after the 30-second deadline.
                raise OSError('trace failed after deadline')
            return original(stream, event, **data)
        with patch('lifemate.agent.time.monotonic', side_effect=lambda: clock[0]), \
             patch.object(Trace, 'write', fail):
            record, backend = self.execute(folder, prepared, store, env, [self.write_call()])
        self.assertEqual(record['status'], 'runner_error')
        self.assertEqual(record['reason'], 'trace_io')
        self.assertTrue(record['metrics']['deadline_exceeded'])
        self.assertIn('trace failed after deadline', record['error'])
        self.assert_consistent(record, store, env)
        self.assertEqual(len(backend.inputs), 1)

    def test_journal_result_write_failure_never_seals_full_result(self):
        original = SessionStore.append
        for after in (False, True):
            with self.subTest(after_durable_append=after):
                folder, prepared, store, env = self.setup_session(f'io_journal_{after}')
                def fail(target, event, **data):
                    if event == 'tool':
                        if after:
                            original(target, event, **data)
                        raise OSError('injected journal result failure')
                    return original(target, event, **data)
                with patch.object(SessionStore, 'append', fail):
                    record, _ = self.execute(folder, prepared, store, env, [self.write_call()])
                self.assertEqual(record['status'], 'recovery_required')
                self.assertFalse(record['terminal'])
                self.assertIsNone(store.result())
                self.assertIsNone(record['submission'])
                self.assertEqual([p['call'] for p in record['calls']], env.get_tool_calls())
                fresh = create_env(self.runtime, 'train', prepared['id'])
                resumed, backend = self.execute(folder, prepared, store, fresh,
                    ['Finished'] if after else [], resume=True)
                if after:
                    self.assert_consistent(resumed, store, fresh)
                    self.assertEqual(len(fresh.get_tool_calls()), 1)
                else:
                    self.assertEqual(resumed['status'], 'recovery_required')
                    self.assertEqual(backend.inputs, [])
                    self.assertEqual(fresh.get_tool_calls(), [])

    def test_exception_after_sdk_execution_before_result_stays_ambiguous(self):
        folder, prepared, store, env = self.setup_session('io_after_sdk')
        call = env.call
        def fail(name, arguments):
            call(name, arguments)
            raise OSError('injected failure after SDK execution')
        env.call = fail
        record, _ = self.execute(folder, prepared, store, env, [self.write_call()])
        self.assertEqual(len(env.get_tool_calls()), 1)
        self.assertEqual(record['status'], 'recovery_required')
        self.assertIsNone(store.result())
        self.assertIsNone(record['submission'])
        self.assertEqual([e['event'] for e in store.events()].count('tool'), 0)

    def test_commit_failure_before_or_after_replace_can_recover_without_model(self):
        original = SessionStore.commit
        for after in (False, True):
            with self.subTest(after_replace=after):
                folder, prepared, store, env = self.setup_session(f'io_commit_{after}')
                def fail(target, record):
                    if after:
                        original(target, record)
                    raise OSError('injected commit boundary')
                with patch.object(SessionStore, 'commit', fail), self.assertRaisesRegex(OSError, 'commit boundary'):
                    self.execute(folder, prepared, store, env, [self.write_call(), 'Finished'])
                self.assertEqual(store.result() is not None, after)
                fresh = create_env(self.runtime, 'train', prepared['id'])
                record, backend = self.execute(folder, prepared, store, fresh, [], resume=True)
                self.assertEqual(backend.inputs, [])
                self.assertEqual(len(record['calls']), 1)
                self.assertEqual(len(record['submission']['tool_calls']), 1)
                self.assertEqual(len(fresh.get_tool_calls()), 0 if after else 1)
                export_results(folder, [prepared['id']])
                self.assertEqual(list(read_jsonl(folder / 'submission.jsonl')), [record['submission']])

    def test_trace_footer_failure_after_commit_keeps_result_and_resume_skips_sdk(self):
        folder, prepared, store, env = self.setup_session('io_trace_footer')
        original = Trace.write
        def fail(stream, event, **data):
            if event == 'end':
                raise OSError('injected footer failure')
            return original(stream, event, **data)
        with patch.object(Trace, 'write', fail), self.assertRaisesRegex(OSError, 'footer failure'):
            self.execute(folder, prepared, store, env, [self.write_call(), 'Finished'])
        committed = store.result()
        self.assert_consistent(committed, store, env)
        fresh = create_env(self.runtime, 'train', prepared['id'])
        record, backend = self.execute(folder, prepared, store, fresh, [], resume=True)
        self.assertEqual(record, committed)
        self.assertEqual(fresh.get_tool_calls(), [])
        self.assertEqual(backend.inputs, [])

    def test_export_failure_keeps_commit_and_resume_rebuilds_without_execution(self):
        import os
        folder = self.root / 'io_export'
        case = self.cases['TR16_APP_KEEP']
        prepare = lambda item: prepare_case(item, PACKAGE, self.runtime, f'{folder.name}/{item["sample_id"]}')
        backend = NativeScript(self.tokenizer, [self.write_call(), 'Finished'], folder / 'backend')
        replace = os.replace
        def fail(src, dst):
            if Path(dst).name == 'submission.jsonl':
                raise OSError('injected export failure')
            return replace(src, dst)
        with patch('lifemate.batch.os.replace', side_effect=fail), self.assertRaisesRegex(OSError, 'export failure'):
            run_batch([case], prepare, backend, folder, backend_identity=self.identity)
        store = SessionStore(folder / 'sessions' / case['sample_id'])
        before = (store.folder / 'result.json').read_bytes()
        never = NativeScript(self.tokenizer, [], folder / 'never_backend')
        with patch('lifemate.batch.create_env', side_effect=AssertionError('Must skip SDK')):
            records = run_batch([case], prepare, never, folder, backend_identity=self.identity, resume=True)
        self.assertEqual(never.inputs, [])
        self.assertEqual(list(read_jsonl(folder / 'submission.jsonl')), [records[0]['submission']])
        self.assertEqual((store.folder / 'result.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
