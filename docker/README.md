# LifeMate — smolagents + llama.cpp Docker

The image uses the existing smolagents ToolCallingAgent and structured llama.cpp API with LFM3-1.7B F16 GGUF and live Gipformer ONNX FP16 ASR. It contains no JAZ, Transformers, PyTorch, BTC dataset, gold labels or historical run artifacts. The notebook and script share `load_models` and `run_split` from `lifemate.deploy`.

The team confirmed that the organizers ran and scored Docker v3. The later `lifemate-smolagents:handoff-local` image passed the local build and a real-audio GPU smoke test with SDK replay. Organizer verification for that image is pending.

Defaults: `/data/private_test`, full split, `/result/submission.jsonl`, 30 seconds/sample including SDK setup and current/history ASR, 16,384 context tokens, 2,048 output tokens/turn, eight steps, fixed seed 0 and greedy decoding. Deadlines are checked around native work; native CUDA calls cannot be forcibly cancelled by Python. An overrun is reported, not presented as a timing pass. Failed samples retain only calls/state actually executed. No scoring or replay runs during inference.

The image stores its source, scripts and notebook in the `/code` directory. `/code/predict.sh` is an executable file and the default image command. The organizer can also launch it with `/bin/bash /code/predict.sh`. Model assets are bundled in `/app/models`. The script prints model load and per-sample times to stdout. Each submission row has `id`, `tool_calls`, `state_hash`, `time` (integer milliseconds). Traces, results and llama-server logs remain under the mounted `/result`. Reusing an existing output file fails instead of replacing evidence.

The final output line reports the number of samples, rows written, step-limit stops and execution errors. A step-limit stop keeps its actual SDK calls and state hash. When all rows are written and there are no execution errors, the script exits with code 0. A missing row, timeout, token-limit stop or protocol error still results in a nonzero exit code.

ASR model loading includes a synthetic zero-feature encoder/decoder/joiner warmup, without reading any dataset audio. This initializes cold CUDA kernels before sample timing. Its cost is printed in ASR load time; actual current/history audio decoding remains inside each sample's 30-second budget. On the local RTX 5070 Laptop the diagnostic cold warmup took 74.6 seconds, followed by 0.10–0.25 seconds per tested audio file. This is not an organizer timing certification.

## Build after source changes (PowerShell)

From the ava repository:

```powershell
$Assets = (Resolve-Path -LiteralPath (Read-Host 'Model assets directory')).Path
$Image = 'lifemate-smolagents:handoff-local'
.\docker\build.ps1 -Image $Image -Assets $Assets
```

The build copies the current Python modules and reads the supplied model assets through a BuildKit context. See the repository's top-level README for the asset layout. The helper downloads and verifies the pinned official Linux llama.cpp release when the cache is empty. The built image runs with bundled dependencies and model assets.

The image installs CUDA 12.8/cuDNN 9 runtime libraries on pinned Python 3.12.12 on Debian Trixie (glibc 2.41), using the CUDA 12.8 ONNX Runtime 1.26.0 wheel. `docker/requirements.txt` and `docker/cuda-requirements.txt` pin the Python and native runtime packages. `/app/installed-requirements.txt` records the full installed set. Use the organizer's LifeMate portal and Docker Guide for submission requirements.

## Offline GPU smoke test — one real audio sample

Use a new output directory; a smoke output is not a full submission.

```powershell
$Data = (Resolve-Path -LiteralPath (Read-Host 'Devkit root containing the splits')).Path
$Result = Join-Path $PWD 'runs\smoke-new'
New-Item -ItemType Directory -Path $Result -ErrorAction Stop
docker run --rm --gpus 'device=0' --network none --mount "type=bind,source=$Data,target=/data,readonly" --mount "type=bind,source=$Result,target=/result" $Image /code/predict.sh --split public_test --smoke-test
```

For the organizer's private split, mount its parent as `/data`, use a fresh `/result` and omit all arguments. This processes every row. Do not run a full dataset during development without approval.

To inspect one particular real sample (including its history audio), add `--sample-id public_0006` after `--smoke-test`. Selecting an ID without smoke mode is rejected.

## Notebook timing interface

```powershell
docker run --rm --gpus 'device=0' -p 127.0.0.1:9777:9777 --mount 'type=bind,source=PATH_TO_DATA_ROOT,target=/data,readonly' --mount 'type=bind,source=PATH_TO_FRESH_RESULT,target=/result' --entrypoint /code/start_jupyter.sh $Image
```

Open localhost:9777 with token `zac2026`, open `/code/predict_notebook.ipynb`, and run all cells. It writes `/result/jupyter_submission.jsonl` for the full private split by default. For an offline headless run, use `--network none` and `--entrypoint jupyter` with `nbconvert --to notebook --execute /code/predict_notebook.ipynb --output executed.ipynb --output-dir /result`. The organizer controls network isolation when using their notebook UI.

## Export and prepare manual submission

```powershell
$Archive = Join-Path $PWD 'outputs\zac2026_TeamName.tar.gz'
python docker/export_image.py $Image $Archive
docker load -i $Archive
```

The export command runs Docker save, gzip and MD5 without a PowerShell binary pipeline. The `.tar.gz.md5` companion contains the checksum of the compressed archive. Verify load and inference on another machine, then manually upload the archive to Google Drive with Anyone-with-link access and enter its link/MD5 in Solution Submission. No helper uploads, commits or pushes anything.

Primary contract: https://challenge.zalo.ai/portal/lifemate and its linked Docker Guide. Native runtime compatibility: https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html. Pinned server: https://github.com/ggml-org/llama.cpp/releases/tag/b12110.
