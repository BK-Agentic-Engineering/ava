#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LLAMA_DIR="${LLAMA_CPP_DIR:-$HOME/.cache/llama.cpp}"
MODEL="${MODEL_DIR:-$HOME/.cache/lfm3/models}/LFM3-1.7B-bf16.gguf"
RUN_DIR="${SERVER_RUN_DIR:-$ROOT/harness/runs/server-$(date -u +%Y%m%dT%H%M%S.%NZ)}"
CUDA_LIB="$HOME/.cache/lfm3/cuda-lib"
if command -v nvcc >/dev/null; then
  NVCC="$(command -v nvcc)"
else
  NVCC="$(python3 -c 'import glob, site; print(next(iter(glob.glob(site.getusersitepackages() + "/nvidia/cu*/bin/nvcc")), ""))')"
fi
[[ -n "$NVCC" ]] || { echo "CUDA Toolkit nvcc is required for its runtime library path." >&2; exit 1; }
CUDA_HOME="$(dirname "$(dirname "$NVCC")")"
export LD_LIBRARY_PATH="$CUDA_LIB:$CUDA_HOME/lib:/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
mkdir "$RUN_DIR"
CMD=("$LLAMA_DIR/build/bin/llama-server"
  --model "$MODEL" --host 127.0.0.1 --port 8080
  --n-gpu-layers 99 --ctx-size 262144 --parallel 16 --kv-unified-per-slot 16384
  --n-predict -1 --reasoning-budget -1 --no-context-shift
  --batch-size 2048 --ubatch-size 512 --cont-batching --flash-attn on
  --jinja --cache-type-k f16 --cache-type-v f16 --cache-prompt --metrics)
python3 - "$LLAMA_DIR" "$MODEL" "$RUN_DIR/manifest.json" "${CMD[@]}" <<'PY'
import hashlib, json, pathlib, subprocess, sys
source, model, target, *command = sys.argv[1:]
def digest(path):
    with open(path, 'rb') as stream:
        h = hashlib.sha256()
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
        return h.hexdigest()
revision = subprocess.run(['git', '-C', source, 'rev-parse', 'HEAD'], capture_output=True, text=True)
template = pathlib.Path(source) / 'models/templates/LFM3.jinja'
manifest = {'command': command, 'source_revision': revision.stdout.strip() if revision.returncode == 0 else None,
            'binary_sha256': digest(command[0]), 'model_sha256': digest(model),
            'reference_template_sha256': digest(template),
            'template_source': 'GGUF embedded template; actual server template captured in benchmark run.json /props',
            'precision': {'weights': 'BF16', 'key_cache': 'FP16', 'value_cache': 'FP16'}}
pathlib.Path(target).write_text(json.dumps(manifest, indent=2) + '\n')
PY
GPU_PID=""
SERVER_PID=""
cleanup() {
  [[ -z "$SERVER_PID" ]] || kill "$SERVER_PID" 2>/dev/null || true
  [[ -z "$GPU_PID" ]] || kill "$GPU_PID" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if command -v nvidia-smi >/dev/null; then
  nvidia-smi --query-gpu=timestamp,index,utilization.gpu,utilization.memory,memory.used,power.draw,clocks.sm,temperature.gpu \
    --format=csv -l 1 > "$RUN_DIR/gpu.csv" 2> "$RUN_DIR/gpu.err" &
  GPU_PID=$!
fi
printf 'Manifest: %s/manifest.json\nServer log: %s/server.log\n' "$RUN_DIR" "$RUN_DIR"
"${CMD[@]}" > "$RUN_DIR/server.log" 2>&1 &
SERVER_PID=$!
wait "$SERVER_PID"
