"""Collection integrity versus batch-local development restrictions; no runtime needed."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from replay_expansion_batch_04 import ROOT, StrictLoader, validate_design


class SplitValidationTests(unittest.TestCase):
    def setUp(self):
        paths = sorted((ROOT / 'data/synthetic/design').glob('*.yaml'))
        self.docs = [yaml.load(p.read_text(encoding='utf-8'), Loader=StrictLoader) for p in paths]
        self.design = next(d for d in self.docs if d['version'] == 'expansion_batch_04')
        # Independently authored, in-memory only; no ancestry from the dev fixture.
        self.train = {
            'worlds': [{'world_id': 'TEST_ONLY_TRAIN_WORLD', 'lineage_id': 'TEST_ONLY_TRAIN_LINEAGE',
                        'split': 'train', 'variants': {}}],
            'scenarios': [{'scenario_id': 'TEST_ONLY_TRAIN_SCENARIO', 'world_id': 'TEST_ONLY_TRAIN_WORLD',
                           'lineage_id': 'TEST_ONLY_TRAIN_LINEAGE', 'fixture_variant': 'base',
                           'status': 'authored', 'exportable': True,
                           'contrast': {'with': 'TEST_ONLY_TRAIN_SCENARIO'}}],
        }
        self.docs.append(self.train)

    def test_unrelated_train_design_allowed(self):
        result = validate_design(self.design, self.docs)
        self.assertEqual(result['global_scenarios'], sum(len(d['scenarios']) for d in self.docs))
        self.assertEqual(result['global_world_instances'], sum(len(d['worlds']) for d in self.docs))
        self.assertEqual(result['named_lineage_ids'], len({w['lineage_id'] for d in self.docs for w in d['worlds']}))

    def test_batch_and_its_world_must_stay_dev(self):
        for location in ['design', 'world']:
            with self.subTest(location=location):
                design = deepcopy(self.design)
                (design if location == 'design' else design['worlds'][0])['split'] = 'train'
                docs = [design if d is self.design else d for d in self.docs]
                with self.assertRaisesRegex(AssertionError, 'Batch 04.*dev'):
                    validate_design(design, docs)

    def test_batch_scenario_must_stay_non_exportable(self):
        self.design['scenarios'][0]['exportable'] = True
        with self.assertRaisesRegex(AssertionError, 'Batch 04 scenarios must remain non-exportable'):
            validate_design(self.design, self.docs)

    def test_batch_scenario_must_stay_spec_only(self):
        self.design['scenarios'][0]['status'] = 'authored'
        with self.assertRaisesRegex(AssertionError, 'Batch 04 scenarios must remain spec_only'):
            validate_design(self.design, self.docs)

    def test_unrelated_duplicate_ids_rejected(self):
        for collection in ['worlds', 'scenarios']:
            with self.subTest(collection=collection):
                docs = deepcopy(self.docs)
                docs[-1][collection].append(deepcopy(docs[-1][collection][0]))
                with self.assertRaisesRegex(AssertionError, 'Duplicate WORLD/scenario ID'):
                    validate_design(self.design, docs)

    def test_unrelated_broken_reference_rejected(self):
        self.train['scenarios'][0]['contrast']['with'] = 'NO_SUCH_SCENARIO'
        with self.assertRaisesRegex(AssertionError, 'Unknown contrast reference'):
            validate_design(self.design, self.docs)

    def test_development_parent_requirement_retained(self):
        parent = next(w for d in self.docs for w in d['worlds'] if w['world_id'] == 'W_B03_HISTORY_EVENT')
        parent['split'] = 'train'
        with self.assertRaises(AssertionError):
            validate_design(self.design, self.docs)


if __name__ == '__main__':
    unittest.main()
