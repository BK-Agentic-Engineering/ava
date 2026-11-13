"""Resume binds checkpoint bytes and effective generation policy, not a claimed revision."""
import os
import unittest
from unittest.mock import MagicMock, patch

from harness_support import workspace, NativeScript, PACKAGE
from lifemate.agent import run_session
from lifemate.batch import session_trace
from lifemate.llm import LocalLLM, inference_identity, generation_policy
from lifemate.sdk import create_env
from lifemate.store import SessionStore, RecoveryRequired
from lifemate.synthetic import prepare_case


class BackendIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.runtime, cls.tokenizer, cls.cases = workspace()

    def setup_session(self, tag):
        folder = self.root / tag
        folder.mkdir()
        checkpoint = folder / 'checkpoint_fixture'
        checkpoint.mkdir()
        files = {
            'model.safetensors': b'weights0', 'config.json': b'{"version":0}',
            'tokenizer.json': b'{"vocab":0}', 'tokenizer_config.json': b'{"tokenizer":0}',
            'chat_template.jinja': b'template0', 'modeling_lfm3.py': b'VALUE=0\n',
            'configuration_lfm3.py': b'CONFIG=0\n', 'lfm3_conv.py': b'CONV=0\n',
            'generation_config.json': b'{"generation":0}',
            'checkpoint.json': b'{"revision":"unchanged"}',
        }
        for name, content in files.items():
            (checkpoint / name).write_bytes(content)
        case = self.cases['TR16_APP_KEEP']
        prepared = prepare_case(case, PACKAGE, self.runtime, f'{folder.name}/{case["sample_id"]}')
        prepared['run_id'] = f'{folder.name}/{case["sample_id"]}'
        store = SessionStore(folder / 'sessions' / prepared['id'])
        return folder, checkpoint, prepared, store

    def execute(self, folder, prepared, store, identity, actions, resume=False):
        backend = NativeScript(self.tokenizer, actions, folder / ('resume_backend' if resume else 'backend'))
        trace = session_trace(folder, prepared['id'])
        def factory():
            if resume:
                raise AssertionError('Committed or mismatched identity must not create SDK')
            return create_env(self.runtime, 'train', prepared['id'])
        try:
            record = run_session(prepared, backend, factory, trace, store=store,
                backend_identity={'kind': 'scripted_identity_test', **identity}, resume=resume)
        finally:
            trace.close()
        return record, backend

    def test_changed_artifact_bytes_reject_resume_even_with_same_revision_size_and_mtime(self):
        folder, checkpoint, prepared, store = self.setup_session('identity_artifacts')
        original_identity = inference_identity(checkpoint, generation_policy())
        committed, _ = self.execute(folder, prepared, store, original_identity, ['Finished'])
        unchanged = inference_identity(checkpoint, generation_policy())
        self.assertEqual(unchanged, original_identity)
        record, backend = self.execute(folder, prepared, store, unchanged, [], resume=True)
        self.assertEqual(record, committed)
        self.assertEqual(backend.inputs, [])
        for name in original_identity['artifacts']:
            if name == 'checkpoint.json':
                continue
            with self.subTest(artifact=name):
                path = checkpoint / name
                previous = path.read_bytes()
                stat = path.stat()
                try:
                    path.write_bytes(previous.replace(b'0', b'1'))
                    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                    changed = inference_identity(checkpoint, generation_policy())
                    self.assertNotEqual(changed['artifacts'][name], original_identity['artifacts'][name])
                    self.assertEqual((checkpoint / 'checkpoint.json').read_bytes(), b'{"revision":"unchanged"}')
                    with self.assertRaisesRegex(RecoveryRequired, 'different'):
                        self.execute(folder, prepared, store, changed, [], resume=True)
                finally:
                    path.write_bytes(previous)
                    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(inference_identity(checkpoint, generation_policy()), original_identity)

    def test_generation_precision_and_backend_versions_are_part_of_resume_identity(self):
        folder, checkpoint, prepared, store = self.setup_session('identity_generation')
        original = inference_identity(checkpoint, generation_policy())
        self.execute(folder, prepared, store, original, ['Finished'])
        policy = generation_policy()
        policy.repetition_penalty = 1.05  # Temporary identity fixture, never used for real inference.
        changed_generation = inference_identity(checkpoint, policy)
        changed_precision = inference_identity(checkpoint, generation_policy(), precision='float16')
        changed_version = {**original, 'versions': {**original['versions'], 'torch': 'changed-fixture'}}
        for tag, identity in [('generation', changed_generation), ('precision', changed_precision), ('version', changed_version)]:
            with self.subTest(kind=tag), self.assertRaisesRegex(RecoveryRequired, 'different'):
                self.execute(folder, prepared, store, identity, [], resume=True)

    def test_precision_is_explicit_for_kaggle_and_default_stays_bfloat16(self):
        import torch
        _, checkpoint, _, _ = self.setup_session('precision_constructor')
        for precision, kwargs in [('bfloat16', {}), ('float16', {'precision': 'float16'})]:
            with self.subTest(precision=precision):
                model = MagicMock()
                model.eval.return_value = model
                with patch('lifemate.llm.AutoTokenizer.from_pretrained'), \
                     patch('lifemate.llm.AutoModelForCausalLM.from_pretrained', return_value=model) as load:
                    backend = LocalLLM(checkpoint, **kwargs)
                self.assertEqual(load.call_args.kwargs['dtype'], getattr(torch, precision))
                self.assertEqual(backend.identity['precision'], precision)


if __name__ == '__main__':
    unittest.main()
