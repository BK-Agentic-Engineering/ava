# CUDA 12.8 runtime is installed explicitly; no PyTorch/Transformers/JAZ base layer.
FROM python:3.12.12-slim-trixie@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c AS llama
COPY --from=llama_release /llama-b12110-bin-ubuntu-cuda-12.8-x64.tar.gz /tmp/llama.tar.gz
RUN python -c "import hashlib; p='/tmp/llama.tar.gz'; assert hashlib.file_digest(open(p,'rb'),'sha256').hexdigest() == '4af1e1da23661db4a5b84b29aae16ebc053df689c5b8b1427c4670f2c6406d8c'" \
    && mkdir -p /opt/llamacpp \
    && tar -xzf /tmp/llama.tar.gz -C /opt/llamacpp --strip-components=1 \
    && find /opt/llamacpp -maxdepth 1 -type f ! -name 'llama-server' ! -name '*.so*' ! -name 'LICENSE' -delete

FROM python:3.12.12-slim-trixie@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c
WORKDIR /app
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
    NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    LD_LIBRARY_PATH=/opt/llamacpp:/usr/local/lib/python3.12/site-packages/nvidia/cuda_runtime/lib:/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libsndfile1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY docker/requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt \
    && python -m pip freeze > /app/installed-requirements.txt
COPY --from=llama /opt/llamacpp/ /opt/llamacpp/
COPY --from=model_assets /asr/fp16/ /app/models/asr/fp16/
COPY --from=model_assets /asr/tokens.txt /asr/checkpoint.json /app/models/asr/
COPY --from=model_assets /llm/lfm3-1.7b-gguf/LFM3-1.7B-F16.gguf /app/models/llm/lfm3-1.7b-gguf/
COPY --from=model_assets /llm/lfm3-1.7b/LICENSE /app/licenses/LFM3-LICENSE
COPY docker/cuda-requirements.txt /app/cuda-requirements.txt
RUN python -m pip install --no-cache-dir -r /app/cuda-requirements.txt \
    && python -m pip freeze > /app/installed-requirements.txt
WORKDIR /code
ENV PYTHONPATH=/code/src \
    LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/lib/python3.12/site-packages/nvidia/cuda_nvrtc/lib:/usr/local/lib/python3.12/site-packages/nvidia/cufft/lib:/usr/local/lib/python3.12/site-packages/nvidia/curand/lib:/usr/local/lib/python3.12/site-packages/nvidia/nvjitlink/lib
COPY src/lifemate/__init__.py src/lifemate/deploy.py src/lifemate/llamacpp_client.py \
     src/lifemate/smolagents_harness.py src/lifemate/execution.py src/lifemate/asr.py \
     src/lifemate/config.py src/lifemate/data.py src/lifemate/tools.py src/lifemate/sdk.py \
     src/lifemate/store.py src/lifemate/submission.py src/lifemate/trace.py /code/src/lifemate/
COPY --chmod=0755 docker/predict.sh docker/start_jupyter.sh /code/
COPY docker/predict_notebook.ipynb docker/requirements.txt docker/cuda-requirements.txt /code/
COPY docker/README.md /code/README.md
COPY docker/training_code/ /code/training_code/
RUN test ! -L /code && test ! -L /code/predict.sh && test -f /code/predict.sh && test -x /code/predict.sh \
    && python -c "import importlib.util; assert all(importlib.util.find_spec(m) is None for m in ('jaz','transformers','torch')); import lifemate.deploy" \
    && /opt/llamacpp/llama-server --version
CMD ["/code/predict.sh"]
