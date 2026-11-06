"""Single-T4 smoke execution and its stdlib-only isolated-environment launcher.

Importing this module does not import Torch, k2, kaldifeat or audio packages.
The notebook bundles this exact file; edit this file and regenerate the bundle.
"""
import argparse
from contextlib import contextmanager
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import traceback
import urllib.request


UV_VERSION = '0.9.5'
PYTHON_VERSION = '3.12.12'


def child_environment():
    env = os.environ.copy()
    for name in ['PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'CONDA_PREFIX']:
        env.pop(name, None)
    env.update(CUDA_VISIBLE_DEVICES='0', CUBLAS_WORKSPACE_CONFIG=':4096:8',
               GIT_PYTHON_REFRESH='quiet', HF_HUB_DISABLE_XET='1', PYTHONNOUSERSITE='1')
    return env


def run_logged(command, log_path, env):
    """Stream both output channels, retain the command/log, and propagate failures."""
    command = [str(part) for part in command]
    output = []
    with Path(log_path).open('x', encoding='utf-8') as log:
        log.write('COMMAND ' + json.dumps(command) + '\n')
        log.flush()
        with subprocess.Popen(command, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                              errors='replace', bufsize=1) as process:
            try:
                for line in process.stdout:
                    print(line, end='', flush=True)
                    log.write(line)
                    log.flush()
                    output.append(line)
                returncode = process.wait()
            except BaseException:
                # An interrupted launcher must not leave an unobserved writer
                # running while the operator resumes the same output files.
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                raise
        if returncode:
            raise subprocess.CalledProcessError(returncode, command)
    return ''.join(output)


def dependency_command(uv, python):
    packages = [f'{name}=={version}' for name, version in EXPECTED.items() if name not in WHEELS]
    packages += [f'{name} @ {url}' for name, url in WHEELS.items()]
    # Match the previous pip resolver's best-match behavior across these two official indexes.
    return [str(uv), 'pip', 'install', '--python', str(python), '--no-config',
            '--index-url', 'https://pypi.org/simple',
            '--extra-index-url', 'https://download.pytorch.org/whl/cu128',
            '--index-strategy', 'unsafe-best-match', *packages]


def launch_child(python, script, run_id, precision, output_root, log_path):
    python = Path(python)
    if not python.is_absolute():
        raise ValueError('The isolated Python executable must be an absolute path.')
    return run_logged([python, '-I', '-u', script, '--run-id', run_id, '--precision', precision,
                       '--output-root', str(output_root)], log_path, child_environment())


def provision_environment(runtime, env, step, record, save, log_directory):
    uv = runtime / 'uv'
    url = f'https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz'
    record.update(stage='download_uv', command=['GET', url])
    save()
    archive = runtime / 'uv.tar.gz'
    urllib.request.urlretrieve(url, archive)
    with tarfile.open(archive, 'r:gz') as bundle:
        uv.write_bytes(bundle.extractfile('uv-x86_64-unknown-linux-gnu/uv').read())
    uv.chmod(0o755)
    actual_uv = step('uv_version', [uv, '--version']).strip()
    assert actual_uv.split()[1] == UV_VERSION, actual_uv
    record['uv_version_observed'] = actual_uv
    step('python_install', [uv, 'python', 'install', PYTHON_VERSION, '--no-bin', '--no-config'])
    venv = runtime / 'venv'
    if not (venv / 'bin/python').exists():
        step('create_venv', [uv, 'venv', '--python', PYTHON_VERSION, '--managed-python',
                             '--no-project', '--no-config', str(venv)])
    python = (venv / 'bin/python').absolute()  # Do not resolve the venv symlink to its base interpreter.
    probe = ('import sys,json,site; '
             f'assert sys.version_info[:3] == {tuple(map(int, PYTHON_VERSION.split(".")))}; '
             'assert sys.prefix != sys.base_prefix; assert not site.ENABLE_USER_SITE; '
             'print(json.dumps({"version":sys.version,"executable":sys.executable,"prefix":sys.prefix}))')
    record['child_interpreter'] = json.loads(step('child_interpreter', [python, '-I', '-c', probe]))
    assert 'include-system-site-packages = false' in (venv / 'pyvenv.cfg').read_text().lower()
    step('install', dependency_command(uv, python))
    frozen = step('freeze', [uv, 'pip', 'freeze', '--python', python, '--no-config'])
    (Path(log_directory) / 'pip_freeze.txt').write_text(frozen, encoding='utf-8')
    return python


def launch_smoke(run_id, precision, output_root=Path('/kaggle/working/gipformer15_smoke')):
    """Provision before a fresh child starts; never mutate the host Python environment."""
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise ValueError('RUN_ID must use letters, digits, underscores or hyphens.')
    if precision not in {'fp16', 'fp32_diagnostic'}:
        raise ValueError('Select fp16 or explicit fp32_diagnostic.')
    out = Path(output_root).resolve() / run_id
    try:
        out.mkdir(parents=True)
    except FileExistsError:
        raise FileExistsError(f'Attempt already exists: {out}. Choose a new RUN_ID; preserve it.') from None
    runtime = out.parent.parent / 'gipformer15_runtime' / run_id
    record = {'run_id': run_id, 'precision_requested': precision,
              'host_python': sys.version, 'host_executable': sys.executable,
              'host_platform': platform.platform(), 'uv_version': UV_VERSION,
              'child_python_requested': PYTHON_VERSION, 'output_directory': str(out),
              'runtime_directory': str(runtime), 'review_status': 'pending_human_review'}

    def save():
        (out / 'launcher_metadata.json').write_text(json.dumps(record, indent=2), encoding='utf-8')

    def step(name, command):
        record.update(stage=name, command=[str(x) for x in command])
        save()
        return run_logged(command, out / (name + '.log'), env)

    env = child_environment()
    env.update(UV_PYTHON_INSTALL_DIR=str(runtime / 'python'),
               UV_PYTHON_BIN_DIR=str(runtime / 'bin'), UV_CACHE_DIR=str(runtime / 'cache'))
    print('RUN_ID:', run_id, 'Return artifact directory:', out, flush=True)
    save()
    try:
        record['stage'] = 'host_inspection'
        save()
        assert platform.system() == 'Linux' and platform.machine() == 'x86_64'
        record['host_nvidia_smi'] = step('host_hardware', ['nvidia-smi'])
        script = out / 'gipformer15_smoke.py'
        shutil.copyfile(Path(__file__).resolve(), script)
        runtime.mkdir(parents=True)
        python = provision_environment(runtime, env, step, record, save, out)
        record.update(stage='child_execution', command=[str(python), '-I', '-u', str(script),
                      '--run-id', run_id, '--precision', precision, '--output-root', str(out.parent)])
        save()
        launch_child(python, script, run_id, precision, out.parent, out / 'child.log')
        record.update(stage='child_completed', child_exit_code=0)
    except Exception as error:
        record.update(error=traceback.format_exc())
        if isinstance(error, subprocess.CalledProcessError):
            record['exit_code'] = error.returncode
        save()
        raise
    save()
    return out


PINS = {
    'gipformer': '0cac5b183d2e1a9e3429ff69080e09cc62ebdf9b',
    'icefall': '9c966762e058bd7ba79d9da71e42fc06b64b703e',
    'model': 'dd9227dcd8705c13f33bdbe59728d546ab94480f',
    'dataset': '3a5b30157034e7eadd5c75fae1a820c6f9383398',
}

EXPECTED = {
    'torch': '2.8.0+cu128', 'torchaudio': '2.8.0+cu128',
    'k2': '1.24.4.dev20250807+cuda12.8.torch2.8.0',
    'kaldifeat': '1.25.5.dev20250807+cuda12.8.torch2.8.0',
    'sentencepiece': '0.2.1', 'kaldialign': '0.9.2', 'pypinyin': '0.50.0',
    'tensorboard': '2.20.0', 'huggingface-hub': '0.34.4', 'numpy': '2.2.6',
    'soundfile': '0.13.1', 'scipy': '1.15.3', 'pyarrow': '23.0.1',
    'fsspec': '2026.2.0', 'aiohttp': '3.13.3', 'graphviz': '0.21',
}

tag = 'cp312'
suffix = f'{tag}-{tag}-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl'
WHEELS = {
    'k2': 'https://huggingface.co/csukuangfj/k2/resolve/f9222235425ce5eee567edda570c0abac4607ff0/ubuntu-cuda/'
          + f'k2-{EXPECTED["k2"]}-{suffix}',
    'kaldifeat': 'https://huggingface.co/csukuangfj/kaldifeat/resolve/35208a9fa3513e4a59cccec114dfbb7afcf688d5/cuda/1.25.5.dev20241029/linux/'
          + f'kaldifeat-{EXPECTED["kaldifeat"]}-{suffix}',
}

SMOKE = [{'region': 'North',
  'province_code': 22,
  'province_name': 'TuyenQuang',
  'filename': '22_0238.wav',
  'text': 'Tuyên truyền đến các bác là bây giờ là có thể theo nhiều hình thức. Các bác có thể lấy '
          'lương hưu ở điểm chi trả và cũng có thể là chuyển tiền qua ngân hàng. Tôi cũng tuyên '
          'truyền đến các bác, các bác cũng rất là đồng tình.',
  'speakerID': 'spk_22_0167',
  'gender': 0,
  'shard': 'data/valid-00001-of-00013.parquet',
  'row_group': 1,
  'row_in_group': 46,
  'source_duration': 12.521496598639455,
  'source_sample_rate': 44100,
  'source_channels': 2},
 {'region': 'North',
  'province_code': 11,
  'province_name': 'CaoBang',
  'filename': '11_0277.wav',
  'text': 'Trong những năm qua và những năm tới đây thì Bộ đội Biên Phòng cũng rất là nhiều công '
          'việc ngoài công việc bảo vệ an ninh chính trị, trật tự an toàn xã hội cũng như công tác '
          'tuần tra bảo vệ biên giới thì đội Biên Phòng còn có nhiệm vụ cũng quan trọng nữa đó là '
          'đồng hành cùng với chính quyền địa phương và bà con nhân dân để phát triển kinh tế nhất '
          'là trong dịch Covid những năm qua',
  'speakerID': 'spk_11_0130',
  'gender': 1,
  'shard': 'data/valid-00000-of-00013.parquet',
  'row_group': 0,
  'row_in_group': 3,
  'source_duration': 26.548004535147392,
  'source_sample_rate': 44100,
  'source_channels': 2},
 {'region': 'Central',
  'province_code': 37,
  'province_name': 'NgheAn',
  'filename': '37_0304.wav',
  'text': 'Trường lớp thì thực ra bây giờ ta có cái nghị quyết mười chín của ban chấp hành trung '
          'ương Cho nên đang còn tinh giảm biên chế này, tái cấu trúc này, tinh gọn bộ máy này '
          'Nhưng bây giờ mở cái trường mới rất là khó.',
  'speakerID': 'spk_37_0226',
  'gender': 1,
  'shard': 'data/valid-00004-of-00013.parquet',
  'row_group': 0,
  'row_in_group': 59,
  'source_duration': 12.106,
  'source_sample_rate': 48000,
  'source_channels': 2},
 {'region': 'Central',
  'province_code': 38,
  'province_name': 'HaTinh',
  'filename': '38_0266.wav',
  'text': 'Thì sau khi về trụ sở mới thì lực lượng công an xã cảm thấy là có một cái động lực, rồi '
          'là có cái tinh thần làm việc trong cái quá trình giao dịch là dân rất thuần lời cho quá '
          'trình đến giao dịch này. Rồi đó đấy cũng là một động lực để cho anh em yên tâm công '
          'tác. Và quá trình làm việc là phần đấu phát huy được cái năng lực sở trường của bản '
          'thân.',
  'speakerID': 'spk_38_0195',
  'gender': 1,
  'shard': 'data/valid-00004-of-00013.parquet',
  'row_group': 1,
  'row_in_group': 6,
  'source_duration': 21.010458333333332,
  'source_sample_rate': 48000,
  'source_channels': 1},
 {'region': 'South',
  'province_code': 68,
  'province_name': 'KienGiang',
  'filename': '68_0228.wav',
  'text': 'Rồi là những cái mùa học các em đầu năm học cũng là vận động tập vở, sách xe đạp cho '
          'các em mà hộ gia đình khó khăn để cho các em đến trường cho nó được bằng bạn bạn bè với '
          'trên địa bàn xã.',
  'speakerID': 'spk_68_0097',
  'gender': 1,
  'shard': 'data/valid-00007-of-00013.parquet',
  'row_group': 0,
  'row_in_group': 70,
  'source_duration': 16.191995464852607,
  'source_sample_rate': 44100,
  'source_channels': 2},
 {'region': 'South',
  'province_code': 84,
  'province_name': 'TraVinh',
  'filename': '84_0246.wav',
  'text': 'Do đó thì Trung ương cả năm hai ngàn hai hai và hai ngàn hai ba tập trung cho mình '
          'nguồn vốn và vốn của địa phương, cộng chung hai cái nguồn lực này trên năm trăm bảy '
          'mươi tỷ đồng. Mình giải quyết trong đó mười dự án lớn. Và địa phương tập trung thực '
          'hiện một số dự án mang tính bức thiết hiện nay, gồm có là đất ở, nhà ở, chuyển đổi '
          'nghề, nước sinh hoạt cho đồng bào.',
  'speakerID': 'spk_84_0119',
  'gender': 1,
  'shard': 'data/valid-00010-of-00013.parquet',
  'row_group': 0,
  'row_in_group': 90,
  'source_duration': 30.68199546485261,
  'source_sample_rate': 44100,
  'source_channels': 2}]


def prepare_attempt(root, run_id):
    from pathlib import Path
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise ValueError('RUN_ID must use letters, digits, underscores or hyphens.')
    output = Path(root) / run_id
    if (output / 'inference').exists():
        raise FileExistsError(f'Attempt already started: {output}. Choose a new RUN_ID; preserve this directory.')
    output.mkdir(parents=True, exist_ok=True)
    return output

def begin_inference(output):
    inference = output / 'inference'
    try:
        inference.mkdir()  # Exclusive reservation, including attempts that fail before predictions.
    except FileExistsError:
        raise FileExistsError(f'Attempt already started: {output}. Choose a new RUN_ID; preserve this directory.') from None
    return inference

# CPU helpers: also exercised directly by local tests, without loading a model.
def prepare_audio(audio_bytes):
    import io
    import math
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    wave, sample_rate = sf.read(io.BytesIO(audio_bytes), dtype='float32', always_2d=True)
    if not len(wave) or not np.isfinite(wave).all():
        raise ValueError('Empty/nonfinite source audio')
    mono = wave.mean(axis=1, dtype=np.float32)
    if sample_rate != 16000:
        divisor = math.gcd(sample_rate, 16000)
        mono = resample_poly(mono, 16000 // divisor, sample_rate // divisor)
    mono = np.ascontiguousarray(mono, dtype=np.float32)
    return mono, {'source_sample_rate': sample_rate, 'source_channels': wave.shape[1],
                  'source_duration': len(wave) / sample_rate, 'duration': len(mono) / 16000}

def compare_passes(records):
    first = {r['sample_id']: r for r in records if r['pass'] == 1}
    second = {r['sample_id']: r for r in records if r['pass'] == 2}
    if not first or first.keys() != second.keys() or len(records) != len(first) + len(second):
        raise ValueError('Repeat passes need the same unique sample IDs')
    comparisons = []
    for sample_id, a in first.items():
        b = second[sample_id]
        ok = a['status'] == b['status'] == 'ok'
        comparisons.append({'sample_id': sample_id, 'both_ok': ok,
                            'stable': ok and a['text'] == b['text'] and a['tokens'] == b['tokens'],
                            'pass1_text': a['text'], 'pass2_text': b['text'],
                            'pass1_tokens': a['tokens'], 'pass2_tokens': b['tokens']})
    return comparisons


def summarize_execution(records, expected_ids, fp16_path_loaded):
    comparisons = compare_passes(records)
    expected = set(expected_ids)
    complete = (len(records) == 2 * len(expected)
                and {r['sample_id'] for r in records} == expected)
    successful = sum(r['status'] == 'ok' for r in records)
    stable = complete and all(r['stable'] for r in comparisons)
    return {'execution_passed': bool(fp16_path_loaded and complete
                                    and successful == len(records) and stable),
            'successful_calls': successful, 'stable_all_samples': stable,
            'empty_successful_transcripts': list(dict.fromkeys(
                r['sample_id'] for r in records if r['status'] == 'ok' and not r['text'])),
            'review_status': 'pending_human_review', 'recognition_quality': 'not_assessed'}


def check_encoder_output(encoded, expected_dtype, diagnostics):
    """Preserve upstream FP32 activations in the FP16 mixed-computation path."""
    import torch
    # Pinned Zipformer BiasNorm and SimpleDownsample use pow/softmax under
    # autocast, which may produce FP32. Greedy search projects this unchanged
    # tensor through joiner.encoder_proj inside the same autocast region.
    allowed = (torch.float16, torch.float32) if expected_dtype == torch.float16 else (expected_dtype,)
    diagnostics.update(expected_dtype=str(expected_dtype), actual_dtype=str(encoded.dtype),
                       dtype_matches=encoded.dtype == expected_dtype,
                       allowed_dtypes=[str(value) for value in allowed],
                       dtype_allowed=encoded.dtype in allowed,
                       all_finite=bool(torch.isfinite(encoded).all().item()))
    if not diagnostics['dtype_allowed'] or not diagnostics['all_finite']:
        raise AssertionError('Encoder output validation failed: ' + json.dumps(diagnostics))


def check_neural_output(name, inputs, output, expected_dtype, observed):
    """Check every warmup invocation, retaining diagnostics even on failure."""
    import torch
    observed[name] = {'input': str(inputs[0].dtype), 'output': str(output.dtype),
                      'all_finite': bool(torch.isfinite(output).all().item())}
    if output.dtype != expected_dtype or not observed[name]['all_finite']:
        raise AssertionError(f'Neural output validation failed: {name}: ' + json.dumps(observed[name]))


def initialize_inference(run, precision, stage, save_run):
    """Validated single-T4 setup; return audio-only transcription and warmup closures."""
    PRECISION = precision
    with stage('runtime_inspection'):
        smi = subprocess.run(['nvidia-smi'], text=True, capture_output=True, check=True).stdout
        run['nvidia_smi_before'] = smi
        print(sys.version, platform.platform(), smi, sep='\n')
        assert platform.system() == 'Linux' and platform.machine() == 'x86_64'
        assert platform.python_version() == PYTHON_VERSION, 'Child requires exact Python ' + PYTHON_VERSION
        assert sys.prefix != sys.base_prefix, 'Child must run inside its isolated virtual environment.'

    with stage('installed_dependencies'):
        run['expected_packages'] = EXPECTED
        run['native_wheels'] = WHEELS
        run['packages'] = {name: metadata.version(name) for name in EXPECTED}
        assert run['packages'] == EXPECTED, run['packages']

    with stage('cuda_and_native_imports'):
        import torch
        import torchaudio
        import k2
        import kaldifeat
        assert torch.__version__ == EXPECTED['torch'] and torch.version.cuda == '12.8'
        assert torch.cuda.is_available() and torch.cuda.device_count() == 1
        DEVICE = torch.device('cuda:0')
        torch.cuda.set_device(DEVICE)
        assert 'T4' in torch.cuda.get_device_name(DEVICE), 'This smoke is specified for one T4.'
        torch.manual_seed(20261031)
        torch.cuda.manual_seed(20261031)
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.use_deterministic_algorithms(True)
        probe = torch.ones((8, 8), dtype=torch.float16, device=DEVICE)
        _ = probe @ probe
        torch.cuda.synchronize(DEVICE)
        del probe, _
        run.update(torch=torch.__version__, cuda_runtime=torch.version.cuda,
                   gpu=torch.cuda.get_device_name(DEVICE), visible_gpu_count=torch.cuda.device_count(),
                   device=str(DEVICE), deterministic_algorithms=True, seed=20261031)
        print({k: run[k] for k in ['torch', 'cuda_runtime', 'gpu', 'device', 'visible_gpu_count']})

    def checkout(url, revision, directory, sparse_paths):
        if not directory.exists():
            directory.mkdir(parents=True)
            for args in [['init'], ['remote', 'add', 'origin', url],
                         ['fetch', '--depth', '1', '--filter=blob:none', 'origin', revision],
                         ['sparse-checkout', 'init', '--cone'],
                         ['sparse-checkout', 'set', *sparse_paths], ['checkout', '--detach', 'FETCH_HEAD']]:
                subprocess.run(['git', '-C', str(directory), *args], check=True)
        actual = subprocess.check_output(['git', '-C', str(directory), 'rev-parse', 'HEAD'], text=True).strip()
        assert actual == revision, (directory, actual)

    with stage('pinned_sources_and_weights'):
        from huggingface_hub import hf_hub_download
        sources = Path('/kaggle/working/gipformer15_sources')
        upstream = sources / 'gipformer'
        icefall = sources / 'icefall'
        checkout('https://github.com/ggroup-ai-lab/gipformer.git', PINS['gipformer'], upstream, [])
        checkout('https://github.com/k2-fsa/icefall.git', PINS['icefall'], icefall,
                 ['icefall', 'egs/librispeech/ASR'])
        model_files = {name: hf_hub_download('g-group-ai-lab/gipformer1.5-68M-rnnt',
                                           filename=name, revision=PINS['model'])
                       for name in ['model.pt', 'bpe.model', 'tokens.txt', 'config.json']}

    with stage('model_load_and_precision_conversion'):
        import argparse
        import importlib.util
        import sentencepiece as spm
        from collections import Counter
        spec = importlib.util.spec_from_file_location('gipformer_official', upstream / 'infer_pytorch.py')
        official = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(official)
        official.setup_icefall(icefall)
        from train import add_model_arguments, get_model, get_params
        from beam_search import greedy_search_batch
        parser = argparse.ArgumentParser()
        add_model_arguments(parser)
        params = get_params()
        params.update(vars(parser.parse_args([])))
        table = k2.SymbolTable.from_file(model_files['tokens.txt'])
        params.blank_id = table['<blk>']
        params.unk_id = table['<unk>']
        params.vocab_size = len([s for s in table.symbols if not s.startswith('#')])
        params.context_size = 2
        run['decoder'] = {'method': 'greedy_search_batch', 'max_sym_per_frame': 1,
                          'blank_penalty': 0, 'return_timestamps': False, 'context_size': 2,
                          'batch_size': 1, 'vocab_size': params.vocab_size}
        run['model_arguments'] = vars(parser.parse_args([]))
        torch.cuda.synchronize(DEVICE)
        start = time.perf_counter()
        model = get_model(params)
        checkpoint = torch.load(model_files['model.pt'], map_location='cpu', weights_only=True)
        state = checkpoint['model'] if 'model' in checkpoint else checkpoint
        run['checkpoint_tensor_dtypes'] = dict(Counter(str(v.dtype) for v in state.values()))
        incompatible = model.load_state_dict(state, strict=False)
        run['checkpoint_keys'] = {'missing': list(incompatible.missing_keys),
                                  'unexpected': list(incompatible.unexpected_keys)}
        print('Checkpoint keys:', run['checkpoint_keys'])
        save_run()
        assert not incompatible.missing_keys, run['checkpoint_keys']
        assert set(incompatible.unexpected_keys) == {'ctc_output.1.weight', 'ctc_output.1.bias'}, run['checkpoint_keys']
        dtype = torch.float16 if PRECISION == 'fp16' else torch.float32
        model = model.to(device=DEVICE, dtype=dtype).eval()
        model.requires_grad_(False)
        assert all(p.device == DEVICE and p.dtype == dtype for p in model.parameters())
        torch.cuda.synchronize(DEVICE)
        run['model_load_seconds'] = time.perf_counter() - start
        run['parameter_count'] = sum(p.numel() for p in model.parameters())
        run['parameter_dtypes'] = dict(Counter(str(p.dtype) for p in model.parameters()))
        run['floating_buffer_dtypes'] = dict(Counter(str(b.dtype) for b in model.buffers() if b.is_floating_point()))
        del checkpoint, state
        tokenizer = spm.SentencePieceProcessor(model_file=model_files['bpe.model'])
        opts = kaldifeat.FbankOptions()
        opts.device = torch.device('cpu')
        opts.frame_opts.samp_freq = 16000
        opts.frame_opts.dither = 0
        opts.frame_opts.snip_edges = False
        opts.mel_opts.num_bins = 80
        opts.mel_opts.high_freq = -400
        fbank = kaldifeat.Fbank(opts)
        run['fbank'] = {'device': 'cpu', 'dtype': 'float32', 'dither': 0,
                        'snip_edges': False, 'num_bins': 80, 'high_freq': -400}
        run['precision'] = {'weights': str(dtype), 'model_input': str(dtype),
                            'cuda_autocast': PRECISION == 'fp16', 'autocast_dtype': 'float16',
                            'internal_fp32_ops': 'allowed by upstream activation/normalization implementation',
                            'encoder_output_policy': ('finite FP16 or FP32 under FP16 autocast; preserved without casting'
                                                      if PRECISION == 'fp16' else 'finite FP32 diagnostic'),
                            'audio_and_fbank': 'float32 CPU', 'quantization': None}
        print('Load seconds:', run['model_load_seconds'], 'Precision:', run['precision'])

    def transcribe(wave):
        # Only audio enters this function; no reference, region or speaker information.
        with torch.inference_mode():
            features = fbank([torch.from_numpy(wave)])[0]
            assert features.dtype == torch.float32 and torch.isfinite(features).all()
            lengths = torch.tensor([features.size(0)], device=DEVICE, dtype=torch.int64)
            features = features.unsqueeze(0).to(device=DEVICE, dtype=dtype)
            with torch.autocast('cuda', dtype=torch.float16, enabled=PRECISION == 'fp16'):
                encoded, encoded_lengths = model.forward_encoder(features, lengths)
                check_encoder_output(encoded, dtype, run.setdefault('encoder_output', {}))
                tokens = greedy_search_batch(model=model, encoder_out=encoded,
                    encoder_out_lens=encoded_lengths, blank_penalty=0, return_timestamps=False)[0]
            return tokenizer.decode(tokens), tokens

    def warmup(prepared):
        with stage('precision_probe_and_warmup'):
            # Warm all six input shapes; observe real neural outputs without replacing model operations.
            observed = {}
            handles = []
            def capture(name):
                def hook(module, args, output):
                    check_neural_output(name, args, output, dtype, observed)
                return hook
            for name, module in [('encoder_conv', model.encoder_embed.conv[0]),
                                 ('decoder_embedding', model.decoder.embedding),
                                 ('joiner_encoder_proj', model.joiner.encoder_proj),
                                 ('joiner_decoder_proj', model.joiner.decoder_proj),
                                 ('joiner_logits', model.joiner.output_linear)]:
                handles.append(module.register_forward_hook(capture(name)))
            torch.cuda.synchronize(DEVICE)
            start = time.perf_counter()
            try:
                for item, wave in prepared:
                    run['warmup_sample_id'] = item['sample_id']
                    warmup_text, _ = transcribe(wave)
                torch.cuda.synchronize(DEVICE)
            finally:
                for handle in handles:
                    handle.remove()
                run['observed_neural_dtypes'] = observed
            run['warmup_seconds'] = time.perf_counter() - start
            run['warmup_samples'] = len(prepared)
            assert len(observed) == 5 and all(x['output'] == str(dtype) for x in observed.values()), observed
            run['fp16_path_loaded'] = PRECISION == 'fp16'
            run['fp16_execution'] = 'warmup_completed' if PRECISION == 'fp16' else 'not_tested_fp32_diagnostic'
            print('Warmup (not a measured sample):', run['warmup_seconds'], observed)

    return transcribe, warmup, lambda: torch.cuda.synchronize(DEVICE)


def run_smoke(run_id, precision, output_root):
    RUN_ID = run_id
    PRECISION = precision
    OUT = prepare_attempt(output_root, run_id)
    os.environ.update({k: child_environment()[k] for k in ['CUDA_VISIBLE_DEVICES',
        'CUBLAS_WORKSPACE_CONFIG', 'GIT_PYTHON_REFRESH', 'HF_HUB_DISABLE_XET']})
    run = {'run_id': RUN_ID, 'precision_requested': PRECISION, 'revisions': PINS,
           'scope': 'six-sample valid engineering smoke; not a benchmark',
           'gpu_inference': 'not_run', 'fp16_execution': 'unverified',
           'fp16_path_loaded': False, 'execution_passed': False,
           'empty_successful_transcripts': [], 'review_status': 'pending_human_review',
           'recognition_quality': 'not_assessed',
           'python': sys.version, 'python_executable': sys.executable, 'uv_version': UV_VERSION, 'platform': platform.platform(), 'libc': platform.libc_ver(),
           'cuda_visible_devices': os.environ['CUDA_VISIBLE_DEVICES'],
           'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}

    def save_run():
        (OUT / 'run_metadata.json').write_text(
            json.dumps(run, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

    @contextmanager
    def stage(name):
        try:
            yield
        except Exception:
            run['failure_stage'] = name
            run['error'] = traceback.format_exc()
            save_run()
            raise
        else:
            save_run()

    INFERENCE = begin_inference(OUT)
    transcribe, warmup, _ = initialize_inference(run, PRECISION, stage, save_run)
    import torch
    DEVICE = torch.device('cuda:0')

    with stage('validation_audio'):
        import fsspec
        import pyarrow.parquet as pq
        prepared = []
        manifest = []
        for expected in SMOKE:
            assert expected['shard'].startswith('data/valid-')
            url = ('https://huggingface.co/datasets/nguyendv02/ViMD_Dataset/resolve/'
                   + PINS['dataset'] + '/' + expected['shard'])
            start = time.perf_counter()
            with fsspec.open(url, 'rb', block_size=65536, cache_type='none') as handle:
                parquet = pq.ParquetFile(handle, pre_buffer=False)
                source = parquet.read_row_group(expected['row_group'], columns=[
                    'audio', 'filename', 'region', 'speakerID', 'text']).slice(
                    expected['row_in_group'], 1).to_pylist()[0]
            for key in ['filename', 'region', 'speakerID', 'text']:
                assert source[key] == expected[key], (key, expected['filename'])
            wave, audio_info = prepare_audio(source['audio']['bytes'])
            sample_id = 'ViMD_Dataset/valid/' + expected['filename']
            item = {**expected, **audio_info, 'sample_id': sample_id,
                    'source': 'nguyendv02/ViMD_Dataset', 'dataset_revision': PINS['dataset'],
                    'split': 'valid', 'speaker_id': expected['speakerID'], 'reference': source['text'],
                    'preparation_seconds': time.perf_counter() - start}
            manifest.append(item)
            prepared.append((item, wave))
            print(sample_id, item['region'], item['speaker_id'], round(item['duration'], 3))
        (INFERENCE / 'smoke_manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        run['audio'] = {'sample_rate': 16000, 'channels': 1, 'dtype': 'float32',
                        'resampler': 'scipy.signal.resample_poly', 'denoise_vad_trimming': False}

    warmup(prepared)

    # Exclusive creation also protects against rerunning just this cell in the same kernel.
    if (INFERENCE / 'predictions.jsonl').exists():
        raise FileExistsError(f'Predictions already exist in {OUT}. Choose a new RUN_ID and launch again from the top.')
    prediction_stream = (INFERENCE / 'predictions.jsonl').open('x', encoding='utf-8')
    records = []
    with stage('two_measured_passes'):
        with prediction_stream as stream:
            for pass_number in (1, 2):
                for item, wave in prepared:
                    record = {**item, 'pass': pass_number, 'precision': PRECISION,
                              'status': 'error', 'text': None, 'tokens': None, 'error': None}
                    start = None
                    try:
                        torch.cuda.synchronize(DEVICE)
                        start = time.perf_counter()
                        text, tokens = transcribe(wave)
                        torch.cuda.synchronize(DEVICE)
                        record.update(status='ok', text=text, tokens=tokens)
                    except Exception:
                        record['error'] = traceback.format_exc()
                    record['warm_inference_seconds'] = None if start is None else time.perf_counter() - start
                    record['latency_scope'] = 'fbank+transfer+encoder+greedy; excludes audio preparation'
                    records.append(record)
                    stream.write(json.dumps(record, ensure_ascii=False) + '\n')
                    stream.flush()
                    print(pass_number, item['sample_id'], item['region'], item['speaker_id'], item['duration'])
                    print('REF:', item['reference'])
                    print('HYP:', record['text'], 'STATUS:', record['status'],
                          'SECONDS:', record['warm_inference_seconds'], 'ERROR:', record['error'])
        comparison = compare_passes(records)
        (INFERENCE / 'stability.json').write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding='utf-8')
        run['gpu_inference'] = 'completed_with_errors' if any(r['status'] != 'ok' for r in records) else 'completed'
        summary = summarize_execution(records, [item['sample_id'] for item, _ in prepared],
                                      fp16_path_loaded=run['fp16_path_loaded'])
        run.update(summary)
        run['fp16_execution'] = ('execution_check_passed' if run['execution_passed']
                                 else 'failed_or_unstable' if PRECISION == 'fp16' else 'not_tested_fp32_diagnostic')
        run['gpu0_peak_allocated_bytes'] = torch.cuda.max_memory_allocated(DEVICE)
        run['nvidia_smi_after'] = subprocess.check_output(['nvidia-smi'], text=True)
        print(json.dumps(comparison, ensure_ascii=False, indent=2))
        print('Execution summary (not recognition-quality acceptance):')
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print('Artifacts:', OUT, sorted(p.name for p in OUT.iterdir()))
        save_run()
        assert run['successful_calls'] == 12, 'Inference errors saved; return diagnostics for review.'
        assert run['stable_all_samples'], 'Output differences saved; do not select one pass.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--precision', choices=['fp16', 'fp32_diagnostic'], required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    run_smoke(args.run_id, args.precision, args.output_root)


if __name__ == '__main__':
    main()
