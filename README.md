# AVA harness

A local, text-only tool-use harness for evaluating LFM3 against the ZAC 2026 LifeMate task format. It sends each task to a local llama.cpp server, executes tool calls in the supplied task environment, and records traces and evaluation results. It is not the official scorer.

## Requirements

- Linux with an NVIDIA GPU and CUDA toolkit (`nvcc`)
- Python 3.10+
- CMake, Git, and the `huggingface_hub` CLI (`python3 -m pip install -U huggingface_hub`)
- Authorized access to the ZAC 2026 LifeMate data bundle; this repository does not include it

Extract the data bundle under `data/`, with `train/` and `public_test/` directories. The scripts use its task catalogs, environments, and `zaic_tools` runtime. Do not publish or redistribute that bundle.

## Run

Build the pinned CUDA llama.cpp server and download the BF16 model:

```bash
./harness/setup.sh
./harness/serve.sh
```

In another terminal, run the local evaluation (use the server manifest path printed by `serve.sh`):

```bash
python3 harness/benchmark.py --limit 100 --workers 8 \
  --server-manifest harness/runs/server-<timestamp>/manifest.json
```

Runs write traces, results, a submission file, and a report under `harness/runs/`. See `python3 harness/benchmark.py --help` for options.

Inspect a run with `python3 harness/analyze.py harness/runs/<run-directory>`. The offline contract check is `python3 harness/check.py`; it also requires the data bundle.

## Files

- `agent.py`: prompt, tool schemas, and model/tool execution loop
- `benchmark.py`: task runner and local metrics
- `diagnostics.py`: trace and evaluation helpers
- `analyze.py`: run analysis
- `setup.sh`, `serve.sh`: model-server setup and launch
- `check.py`: offline contract check
