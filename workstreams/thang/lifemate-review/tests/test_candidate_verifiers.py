"""Portable regressions; invented probes are not recorded model failures."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'dataset_v1_candidate'


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


grounding = load('trace_grounding')
answers = load('grade_final_wave_answers')


class CandidateVerifierTests(unittest.TestCase):
    def test_complete_identifiers_and_chronology(self):
        call = {'name': 'package_tracking.track', 'arguments': {'tracking_id': ' gom 908 '},
                'result': {'ok': True, 'tracking_id': 'GOM908'}}
        visible = {'allowed_tools': [call['name']]}
        for request, supported in [('GOM908', True), ('gom 908', True),
                                   ('GOM9080', False), ('XGOM908', False), ('GOM908-X', False)]:
            self.assertEqual(not grounding.unsupported_identifiers(
                {**visible, 'request': request}, [call]), supported)
        read = {**call, 'arguments': {}}
        self.assertFalse(grounding.unsupported_identifiers(visible, [read, call]))
        self.assertTrue(grounding.unsupported_identifiers(visible, [call, read]))

    def test_channels_do_not_inherit_tracking_normalization(self):
        call = {'name': 'tv.tune', 'arguments': {'channel': 'ABC12'}, 'result': {'ok': True}}
        for request in ['ABC123', 'ABC 12', 'XABC12']:
            self.assertTrue(grounding.unsupported_identifiers(
                {'allowed_tools': ['tv.tune'], 'request': request}, [call]))

    def test_percent_and_units(self):
        cases = [
            ('TR9_WEATHER_LOOKNEXT', {'forecast': [{'location': 'Huế', 'date': '2027-03-12', 'rain_pct': 50}]},
             {'50%': 'pass', '0.050%': 'fail', '0,050%': 'fail', '50,0%': 'pass'}),
            ('TR9_WALLET_LOOK', {'balance': 150000},
             {'150.000 đồng': 'pass', '150 000 đồng': 'pass', '150,000 đồng': 'unresolved', '149.000 đồng': 'fail'}),
            ('TR12_LEARN_LOOK', {'courses': [{'name': 'Gấp Nếp', 'provider': 'Nhà Cói', 'progress_minutes': 30}]},
             {'30 phút': 'pass', '30,0 phút': 'pass', '0.030 phút': 'unresolved', '30,5 phút': 'fail'})]
        for sid, result, examples in cases:
            tool = answers.RULES[sid][0]
            visible = {'allowed_tools': [tool]}
            calls = [{'name': tool, 'result': {'ok': True, **result}}]
            for text, expected in examples.items():
                self.assertEqual(answers.grade(sid, visible, calls, text)['verdict'], expected)
            text = next(iter(examples))
            self.assertEqual(answers.grade(sid, visible, [], text)['verdict'], 'fail')
            self.assertEqual(answers.grade(sid, visible, calls, None)['verdict'], 'fail')
            self.assertNotEqual(answers.grade(sid, visible, calls, text + ' Tôi đã chuyển tiền.')['verdict'], 'pass')


if __name__ == '__main__':
    unittest.main()
