#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_DIR="${MODEL_DIR:-$HOME/.cache/lfm3/models}"
LLAMA_DIR="${LLAMA_CPP_DIR:-$HOME/.cache/llama.cpp}"
LLAMA_REV="3ba1ce0e28d991800e1585b7d3533f77213939d6"
MODEL_FILE="LFM3-1.7B-bf16.gguf"
CUDA_LIB="$HOME/.cache/lfm3/cuda-lib"
if command -v nvcc >/dev/null; then
  NVCC_CANDIDATE="$(command -v nvcc)"
else
  NVCC_CANDIDATE="$(python3 -c 'import glob, site; print(next(iter(glob.glob(site.getusersitepackages() + "/nvidia/cu*/bin/nvcc")), ""))')"
  [[ -n "$NVCC_CANDIDATE" ]] || { echo "CUDA Toolkit nvcc is required." >&2; exit 1; }
fi
CUDA_HOME="$(dirname "$(dirname "$NVCC_CANDIDATE")")"
export CUDA_HOME PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib:/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
mkdir -p "$CUDA_LIB" "$MODEL_DIR"
for lib in cudart cublas cublasLt; do
  so="$(find "$CUDA_HOME/lib" -maxdepth 1 -name "lib${lib}.so.*" -print -quit)"
  [[ -z "$so" ]] || ln -sf "$so" "$CUDA_LIB/lib${lib}.so"
done
command -v cmake >/dev/null
command -v git >/dev/null
command -v hf >/dev/null || { echo "Install huggingface_hub: python3 -m pip install -U huggingface_hub" >&2; exit 1; }
if [[ ! -s "$MODEL_DIR/$MODEL_FILE" || "$(stat -c%s "$MODEL_DIR/$MODEL_FILE")" != 3466626336 ]]; then
  hf download bartowski/LFM3-1.7B-GGUF --include "$MODEL_FILE" --local-dir "$MODEL_DIR"
fi
echo "1201c4fb4b49002d29989ff2791e65e64dd8778a9c0f198e82ba7345a3d2ef96  $MODEL_DIR/$MODEL_FILE" | sha256sum --check
if [[ ! -d "$LLAMA_DIR/.git" ]]; then
  if [[ -d "$LLAMA_DIR" ]]; then
    echo "Existing sources have no Git provenance: $LLAMA_DIR. Set LLAMA_CPP_DIR to a new directory." >&2
    exit 1
  fi
  mkdir -p "$(dirname "$LLAMA_DIR")"
  git init "$LLAMA_DIR"
  git -C "$LLAMA_DIR" remote add origin https://github.com/ggml-org/llama.cpp.git
fi
if [[ -n "$(git -C "$LLAMA_DIR" status --porcelain)" ]]; then
  echo "Refusing to replace modified llama.cpp sources." >&2
  exit 1
fi
git -C "$LLAMA_DIR" fetch --depth 1 origin "$LLAMA_REV"
git -C "$LLAMA_DIR" checkout --detach "$LLAMA_REV"
cmake -S "$LLAMA_DIR" -B "$LLAMA_DIR/build" \
  -DGGML_CUDA=ON -DCMAKE_CUDA_COMPILER="$NVCC_CANDIDATE" -DCUDAToolkit_ROOT="$CUDA_HOME" \
  -DCMAKE_LIBRARY_PATH="$CUDA_LIB" -DCMAKE_CUDA_ARCHITECTURES=89 -DCMAKE_BUILD_TYPE=Release \
  -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_UI=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_TESTS=OFF
cmake --build "$LLAMA_DIR/build" --config Release --parallel "${BUILD_JOBS:-$(nproc)}" --target llama-server
printf 'Setup complete. Start serving with:\n  MODEL_DIR="%s" LLAMA_CPP_DIR="%s" %s/harness/serve.sh\n' "$MODEL_DIR" "$LLAMA_DIR" "$ROOT"
